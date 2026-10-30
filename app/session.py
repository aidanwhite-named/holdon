"""UI 독립 게임 세션: 엔진 + 봇 + 코치 + 로그를 묶어 '사람 차례까지 자동 진행'을 담당한다.

Streamlit 은 사용자 입력마다 스크립트를 다시 실행하므로, 이 객체를 session_state 에 보관하고
사람이 행동할 때마다 `act()` → 봇들이 사람 차례(또는 핸드 종료)까지 자동 진행한다.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from holdem import Action, GameEngine, GameSettings, IllegalActionError, PlayerView, pretty
from holdem.bots import RangeBot, RuleBasedBot
from holdem.coach import Coach, CoachReport
from holdem.models import ActionRecord, Street


@dataclass(frozen=True)
class LogEntry:
    hand: int
    kind: str  # "hand" / "street" / "action" / "result"
    text: str
    seat: int | None = None


@dataclass
class HandSummary:
    number: int
    level: str
    hero_hole: str
    hero_position: str
    board: str
    hero_net: int
    winners: str
    showdown: list[tuple[str, str, str]] = field(default_factory=list)  # (이름, 카드, 족보)


class GameSession:
    def __init__(
        self,
        settings: GameSettings,
        bot_engine: str = "range",
        coach_iterations: int = 1500,
    ) -> None:
        if settings.human_seat is None:
            raise ValueError("UI 세션에는 사람 좌석이 필요합니다")
        self.settings = settings
        self.engine = GameEngine(settings)
        seed = settings.seed if settings.seed is not None else random.randrange(1 << 30)
        bot_class = RangeBot if bot_engine == "range" else RuleBasedBot
        self.bots = {
            p.seat: bot_class(p.profile, random.Random(seed + p.seat))
            for p in self.engine.players
            if not p.is_human
        }
        self.coach = Coach(coach_iterations, random.Random(seed - 1))
        self.log: list[LogEntry] = []
        self.summaries: list[HandSummary] = []
        self._shown_board = 0
        self._report_key: tuple[int, int] | None = None
        self._report: CoachReport | None = None

    # ------------------------------------------------------------------ #
    # 조회
    # ------------------------------------------------------------------ #
    @property
    def hero(self):
        return self.engine.human

    @property
    def hand(self):
        return self.engine.hand

    @property
    def hero_to_act(self) -> bool:
        p = self.engine.current_player()
        return p is not None and p.is_human

    @property
    def game_over(self) -> bool:
        return self.engine.is_game_over()

    def hero_view(self) -> PlayerView | None:
        return self.engine.view_for(self.hero.seat) if self.hero_to_act else None

    def decision_key(self) -> tuple[int, int] | None:
        """사람의 의사결정 시점 식별자 (위젯 키·코치 캐시용)."""
        if not self.hero_to_act:
            return None
        return (self.hand.number, len(self.hand.history))

    def report(self) -> CoachReport | None:
        """현재 의사결정 시점의 코칭 리포트 (같은 시점이면 캐시 재사용)."""
        key = self.decision_key()
        if key is None:
            return None
        if key != self._report_key:
            self._report = self.coach.analyze(self.hero_view())
            self._report_key = key
        return self._report

    def hand_log(self, number: int | None = None) -> list[LogEntry]:
        number = number if number is not None else (self.hand.number if self.hand else 0)
        return [e for e in self.log if e.hand == number]

    # ------------------------------------------------------------------ #
    # 진행
    # ------------------------------------------------------------------ #
    def start_hand(self) -> None:
        hand = self.engine.start_hand()
        self._shown_board = 0
        hero = self.hero
        self._log("hand", f"핸드 #{hand.number} · 블라인드 {hand.level} · 내 핸드 {pretty(hero.hole)} ({hero.position})")
        self._after_progress()
        self.run_bots()

    def act(self, action: Action) -> str | None:
        """사람의 액션을 적용한다. 불법 액션이면 에러 메시지를 반환."""
        if not self.hero_to_act:
            return "지금은 내 차례가 아닙니다"
        try:
            record = self.engine.apply_action(action)
        except IllegalActionError as e:
            return str(e)
        self._log_action(record)
        self.run_bots()
        return None

    def run_bots(self, max_steps: int = 500) -> None:
        """사람 차례가 되거나 핸드가 끝날 때까지 봇 액션을 진행한다."""
        for _ in range(max_steps):
            if not self.engine.hand_in_progress or self.hero_to_act:
                return
            p = self.engine.current_player()
            record = self.engine.apply_action(self.bots[p.seat].decide(self.engine.view_for(p.seat)))
            self._log_action(record)
        raise RuntimeError("봇 액션이 끝나지 않습니다")

    # ------------------------------------------------------------------ #
    # 로그
    # ------------------------------------------------------------------ #
    def _log(self, kind: str, text: str, seat: int | None = None) -> None:
        self.log.append(LogEntry(self.hand.number, kind, text, seat))

    def _log_action(self, record: ActionRecord) -> None:
        self._log("action", str(record), record.seat)
        self._after_progress()

    def _after_progress(self) -> None:
        hand = self.hand
        if len(hand.board) > self._shown_board:
            self._shown_board = len(hand.board)
            street = Street(min(len(hand.board) - 2, 3)) if len(hand.board) >= 3 else Street.PREFLOP
            self._log("street", f"{street.label}: {pretty(hand.board)} (팟 {self.engine.pot:,})")
        if hand.result is not None and (not self.summaries or self.summaries[-1].number != hand.number):
            self._finish_hand()

    def _finish_hand(self) -> None:
        hand, result, engine = self.hand, self.hand.result, self.engine
        for award in result.awards:
            names = ", ".join(engine.players[s].name for s in award.winners)
            if award.uncalled_return:
                self._log("result", f"{names}: 콜 되지 않은 {award.amount:,} 반환")
            elif award.hand_name:
                self._log("result", f"{names} 이(가) {award.amount:,} 획득 ({award.hand_name})")
            else:
                self._log("result", f"{names} 이(가) {award.amount:,} 획득 (상대 전원 폴드)")
        for seat in result.busted:
            self._log("result", f"{engine.players[seat].name} 탈락")

        winners = {s for a in result.awards for s in a.winners if not a.uncalled_return}
        hero = self.hero
        self.summaries.append(
            HandSummary(
                number=hand.number,
                level=str(hand.level),
                hero_hole=pretty(hero.hole),
                hero_position=hero.position,
                board=pretty(hand.board) if hand.board else "-",
                hero_net=result.net.get(hero.seat, 0),
                winners=", ".join(engine.players[s].name for s in sorted(winners)),
                showdown=[
                    (engine.players[s].name, pretty(engine.players[s].hole), str(rank))
                    for s, rank in sorted(result.showdown.items(), key=lambda kv: kv[1].score)
                ],
            )
        )
