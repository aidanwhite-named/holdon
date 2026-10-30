"""노리밋 텍사스 홀덤 게임 엔진 (UI 독립, 한 액션씩 진행하는 상태 머신).

사용 흐름:
    engine = GameEngine(settings)
    engine.start_hand()
    while engine.hand_in_progress:
        seat = engine.current_player().seat
        action = (사람 입력 또는 bot.decide(engine.view_for(seat)))
        engine.apply_action(action)
    engine.hand.result  # 결과

구현된 규칙: 앤티/블라인드, 헤즈업 버튼=SB, 최소 레이즈(직전 풀 레이즈 크기),
불완전 올인 레이즈는 이미 행동한 플레이어의 재레이즈 권한을 열지 않음,
사이드 팟, 스플릿 팟(홀수 칩은 버튼 왼쪽부터), 올인 시 자동 런아웃.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Callable

from .blinds import BlindClock, BlindLevel
from .cards import Deck
from .config import GameSettings
from .evaluator import HandRank, evaluate
from .models import (
    Action,
    ActionRecord,
    ActionType,
    HandResult,
    LegalActions,
    Player,
    PlayerView,
    PotAward,
    SeatInfo,
    Street,
)
from .positions import assign_positions
from .pots import build_pots


class IllegalActionError(ValueError):
    pass


@dataclass
class HandState:
    number: int
    level: BlindLevel
    level_index: int
    button: int
    sb_seat: int
    bb_seat: int
    deck: Deck
    board: list[int] = field(default_factory=list)
    street: Street = Street.PREFLOP
    current_bet: int = 0        # 이번 스트리트 최고 베팅액
    last_raise_size: int = 0    # 최소 레이즈 증가분
    full_raise_count: int = 0   # 이번 스트리트 풀 레이즈(벳 포함) 횟수
    to_act: int | None = None
    history: list[ActionRecord] = field(default_factory=list)
    start_stacks: dict[int, int] = field(default_factory=dict)
    result: HandResult | None = None


class GameEngine:
    def __init__(self, settings: GameSettings, clock: Callable[[], float] = time.monotonic) -> None:
        self.settings = settings
        self.rng = random.Random(settings.seed)
        self.players: list[Player] = []
        for seat in range(settings.num_players):
            if seat == settings.human_seat:
                self.players.append(Player(seat, settings.human_name, settings.starting_stack, is_human=True))
            else:
                profile = settings.profile_for(seat)
                self.players.append(Player(seat, profile.name, settings.starting_stack, profile=profile))
        self.blind_clock = BlindClock(
            settings.blind_schedule,
            settings.level_duration_sec,
            settings.hands_per_level,
            clock,
        )
        self.button: int | None = None
        self.hands_played = 0
        self.hand: HandState | None = None

    # ------------------------------------------------------------------ #
    # 조회
    # ------------------------------------------------------------------ #
    @property
    def hand_in_progress(self) -> bool:
        return self.hand is not None and self.hand.result is None

    @property
    def pot(self) -> int:
        return sum(p.total_bet for p in self.players)

    @property
    def human(self) -> Player | None:
        return next((p for p in self.players if p.is_human), None)

    def alive_seats(self) -> list[int]:
        return [p.seat for p in self.players if p.stack > 0]

    def is_game_over(self) -> bool:
        if self.hand_in_progress:
            return False
        human = self.human
        return len(self.alive_seats()) < 2 or (human is not None and human.stack == 0)

    def current_player(self) -> Player | None:
        if not self.hand_in_progress or self.hand.to_act is None:
            return None
        return self.players[self.hand.to_act]

    def legal_actions(self) -> LegalActions:
        hand = self._require_hand()
        p = self.current_player()
        if p is None:
            raise RuntimeError("행동할 플레이어가 없습니다")
        to_call = max(0, hand.current_bet - p.street_bet)
        call_amount = min(to_call, p.stack)
        max_to = p.street_bet + p.stack
        others_can_respond = any(o.can_act for o in self.players if o is not p)
        reopened = p.raise_seen is None or hand.full_raise_count > p.raise_seen
        can_raise = max_to > hand.current_bet and others_can_respond and reopened
        return LegalActions(
            to_call=to_call,
            call_amount=call_amount,
            can_check=to_call == 0,
            can_raise=can_raise,
            min_raise_to=min(hand.current_bet + hand.last_raise_size, max_to) if can_raise else 0,
            max_raise_to=max_to if can_raise else 0,
        )

    def view_for(self, seat: int) -> PlayerView:
        """해당 좌석이 지금 행동해야 할 때 볼 수 있는 정보."""
        hand = self._require_hand()
        if hand.to_act != seat:
            raise RuntimeError(f"좌석 {seat} 의 차례가 아닙니다")
        p = self.players[seat]
        return PlayerView(
            seat=seat,
            position=p.position,
            hole=tuple(p.hole),
            board=tuple(hand.board),
            street=hand.street,
            pot=self.pot,
            stack=p.stack,
            street_bet=p.street_bet,
            current_bet=hand.current_bet,
            legal=self.legal_actions(),
            big_blind=hand.level.big_blind,
            num_opponents=sum(1 for o in self.players if o.in_hand and o is not p),
            num_dealt=sum(1 for o in self.players if o.dealt_in),
            history=tuple(hand.history),
            opponents=tuple(
                SeatInfo(o.seat, o.name, o.position, o.stack, o.street_bet, o.total_bet, o.in_hand, o.all_in)
                for o in self.players
                if o.dealt_in and o is not p
            ),
        )

    # ------------------------------------------------------------------ #
    # 핸드 진행
    # ------------------------------------------------------------------ #
    def start_hand(self) -> HandState:
        if self.hand_in_progress:
            raise RuntimeError("이전 핸드가 아직 끝나지 않았습니다")
        if self.is_game_over():
            raise RuntimeError("게임이 종료되었습니다")
        self.blind_clock.start()

        alive = self.alive_seats()
        self.button = self.rng.choice(alive) if self.button is None else self._next_seat(self.button, alive)
        order = self._clockwise(alive, after=self.button)  # 버튼 왼쪽부터 버튼까지
        seats_from_button = [self.button, *order[:-1]]
        positions = assign_positions(seats_from_button)

        level_index = self.blind_clock.level_index(self.hands_played)
        level = self.blind_clock.schedule[level_index]
        if len(alive) == 2:
            sb, bb = self.button, order[0]
        else:
            sb, bb = order[0], order[1]

        hand = HandState(
            number=self.hands_played + 1,
            level=level,
            level_index=level_index,
            button=self.button,
            sb_seat=sb,
            bb_seat=bb,
            deck=Deck(self.rng),
            current_bet=level.big_blind,
            last_raise_size=level.big_blind,
        )
        self.hand = hand
        for p in self.players:
            p.reset_for_hand(dealt_in=p.seat in positions)
            p.position = positions.get(p.seat, "")
            if p.dealt_in:
                hand.start_stacks[p.seat] = p.stack

        if level.ante:
            for seat in alive:
                p = self.players[seat]
                ante = min(level.ante, p.stack)
                p.stack -= ante
                p.total_bet += ante
                p.all_in = p.stack == 0
        self._commit(self.players[sb], level.small_blind)
        self._commit(self.players[bb], level.big_blind)

        for _ in range(2):
            for seat in order:
                self.players[seat].hole.extend(hand.deck.draw(1))

        if self._betting_complete():
            self._end_betting_round()
        else:
            hand.to_act = self._next_needing_action(after=bb)
        return hand

    def apply_action(self, action: Action) -> ActionRecord:
        hand = self._require_hand()
        p = self.current_player()
        if p is None:
            raise RuntimeError("행동할 플레이어가 없습니다")
        legal = self.legal_actions()
        kind, raise_to = self._normalize(action, legal)

        facing_bet = hand.current_bet
        was_unopened = facing_bet == 0
        added = 0
        if kind == ActionType.FOLD:
            p.folded = True
        elif kind == ActionType.CALL:
            added = self._commit(p, legal.call_amount)
        elif kind == ActionType.RAISE:
            raise_size = raise_to - hand.current_bet
            if raise_size >= hand.last_raise_size:  # 풀 레이즈 → 액션 재오픈
                hand.last_raise_size = raise_size
                hand.full_raise_count += 1
            hand.current_bet = raise_to
            added = self._commit(p, raise_to - p.street_bet)
            for other in self.players:
                if other is not p and other.can_act:
                    other.acted = False
            if was_unopened:
                kind = ActionType.BET
        p.acted = True
        p.raise_seen = hand.full_raise_count

        record = ActionRecord(
            street=hand.street,
            seat=p.seat,
            name=p.name,
            position=p.position,
            kind=kind,
            added=added,
            street_total=p.street_bet,
            all_in=p.all_in,
            pot_after=self.pot,
            facing_bet=facing_bet,
        )
        hand.history.append(record)

        if len(self._in_hand()) == 1:
            self._finish_uncontested()
        elif self._betting_complete():
            self._end_betting_round()
        else:
            hand.to_act = self._next_needing_action(after=p.seat)
        return record

    # ------------------------------------------------------------------ #
    # 내부 로직
    # ------------------------------------------------------------------ #
    def _require_hand(self) -> HandState:
        if self.hand is None:
            raise RuntimeError("진행 중인 핸드가 없습니다")
        return self.hand

    def _normalize(self, action: Action, legal: LegalActions) -> tuple[ActionType, int]:
        """입력 액션을 FOLD/CHECK/CALL/RAISE(to) 로 정규화하고 합법성을 검사한다."""
        hand = self._require_hand()
        t = action.type
        if t == ActionType.FOLD:
            return ActionType.FOLD, 0
        if t == ActionType.CHECK:
            if not legal.can_check:
                raise IllegalActionError(f"체크할 수 없습니다 (콜 {legal.call_amount:,} 필요)")
            return ActionType.CHECK, 0
        if t == ActionType.CALL:
            return (ActionType.CHECK, 0) if legal.can_check else (ActionType.CALL, 0)
        if t == ActionType.ALL_IN:
            if legal.can_raise:
                return ActionType.RAISE, legal.max_raise_to
            return (ActionType.CHECK, 0) if legal.can_check else (ActionType.CALL, 0)
        # BET / RAISE
        if not legal.can_raise:
            raise IllegalActionError("지금은 벳/레이즈할 수 없습니다")
        to = action.amount
        if to == legal.max_raise_to and to > hand.current_bet:
            return ActionType.RAISE, to  # 최소 레이즈 미만이어도 올인은 허용
        if not legal.min_raise_to <= to <= legal.max_raise_to:
            raise IllegalActionError(
                f"레이즈 금액은 {legal.min_raise_to:,} ~ {legal.max_raise_to:,} 이어야 합니다 (입력 {to:,})"
            )
        return ActionType.RAISE, to

    def _commit(self, p: Player, amount: int) -> int:
        amount = min(amount, p.stack)
        p.stack -= amount
        p.street_bet += amount
        p.total_bet += amount
        if p.stack == 0:
            p.all_in = True
        return amount

    def _in_hand(self) -> list[Player]:
        return [p for p in self.players if p.in_hand]

    def _betting_complete(self) -> bool:
        hand = self._require_hand()
        in_hand = self._in_hand()
        if len(in_hand) <= 1:
            return True
        actors = [p for p in in_hand if not p.all_in]
        if not actors:
            return True
        if len(actors) == 1 and actors[0].street_bet >= max(p.street_bet for p in in_hand):
            return True  # 나머지 전원 올인이고 남은 1명이 이미 맞춤
        return all(p.acted and p.street_bet == hand.current_bet for p in actors)

    def _needs_action(self, p: Player) -> bool:
        return p.can_act and (not p.acted or p.street_bet < self._require_hand().current_bet)

    def _next_needing_action(self, after: int) -> int | None:
        n = len(self.players)
        for i in range(1, n + 1):
            p = self.players[(after + i) % n]
            if self._needs_action(p):
                return p.seat
        return None

    @staticmethod
    def _next_seat(after: int, candidates: list[int]) -> int:
        later = [s for s in sorted(candidates) if s > after]
        return later[0] if later else min(candidates)

    @staticmethod
    def _clockwise(seats: list[int], after: int) -> list[int]:
        """after 다음 좌석부터 시계 방향으로 정렬 (after 가 포함되면 맨 끝)."""
        ordered = sorted(seats)
        return [s for s in ordered if s > after] + [s for s in ordered if s <= after]

    def _end_betting_round(self) -> None:
        hand = self._require_hand()
        hand.to_act = None
        while True:
            if hand.street == Street.RIVER:
                self._showdown()
                return
            self._deal_next_street()
            if not self._betting_complete():
                hand.to_act = self._next_needing_action(after=hand.button)
                return
            # 액션 가능한 플레이어가 1명 이하 → 남은 보드 자동 런아웃

    def _deal_next_street(self) -> None:
        hand = self._require_hand()
        for p in self.players:
            p.street_bet = 0
            p.acted = False
            p.raise_seen = None
        hand.current_bet = 0
        hand.last_raise_size = hand.level.big_blind
        hand.full_raise_count = 0
        hand.deck.draw(1)  # 번 카드
        hand.board.extend(hand.deck.draw(3 if hand.street == Street.PREFLOP else 1))
        hand.street = Street(hand.street + 1)

    def _finish_uncontested(self) -> None:
        hand = self._require_hand()
        winner = self._in_hand()[0]
        pot = self.pot
        winner.stack += pot
        self._complete([PotAward(pot, [winner.seat], [winner.seat], None)], {})

    def _showdown(self) -> None:
        hand = self._require_hand()
        ranks: dict[int, HandRank] = {p.seat: evaluate(p.hole, hand.board) for p in self._in_hand()}
        pots = build_pots(
            {p.seat: p.total_bet for p in self.players if p.dealt_in},
            folded={p.seat for p in self.players if p.dealt_in and p.folded},
        )
        odd_chip_order = self._clockwise(list(ranks), after=hand.button)
        awards = []
        for pot in pots:
            best = min(ranks[s].score for s in pot.eligible)
            winners = [s for s in odd_chip_order if s in pot.eligible and ranks[s].score == best]
            share, remainder = divmod(pot.amount, len(winners))
            for i, seat in enumerate(winners):
                self.players[seat].stack += share + (1 if i < remainder else 0)
            awards.append(
                PotAward(
                    pot.amount,
                    pot.eligible,
                    winners,
                    ranks[winners[0]].name_ko,
                    uncalled_return=len(pot.eligible) == 1,
                )
            )
        self._complete(awards, ranks)

    def _complete(self, awards: list[PotAward], showdown: dict[int, HandRank]) -> None:
        hand = self._require_hand()
        hand.to_act = None
        net = {seat: self.players[seat].stack - start for seat, start in hand.start_stacks.items()}
        busted = [seat for seat in hand.start_stacks if self.players[seat].stack == 0]
        hand.result = HandResult(awards, showdown, net, busted)
        self.hands_played += 1
