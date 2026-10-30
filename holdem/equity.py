"""에쿼티(승률) 계산, 아웃츠, '나를 이기는 상대 핸드' 분석.

- monte_carlo_equity : 상대 패를 모를 때(또는 레인지를 가정할 때)의 승률
- find_outs          : 다음 카드로 내 족보가 개선되는 카드 목록과 확률
- analyze_threats    : 현재 보드에서 나를 이기는 상대 홀카드 조합과 넛 핸드
- pot_odds           : 콜에 필요한 최소 승률
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from math import comb
from typing import Any, Sequence

from .cards import FULL_DECK, pretty, rank_of
from .evaluator import (
    CLASS_NAME_KO,
    PAIR,
    TWO_PAIR,
    HandRank,
    evaluate,
    rank_count_class,
    raw_score,
)

Combo = tuple[int, int]


# --------------------------------------------------------------------------- #
# 팟 오즈
# --------------------------------------------------------------------------- #
def pot_odds(to_call: int, pot: int) -> float:
    """콜 금액 / (콜 후 전체 팟). 이 값보다 에쿼티가 높으면 콜이 +EV.

    pot 은 내 콜을 넣기 전 팟(상대 베팅 포함).
    """
    if to_call <= 0:
        return 0.0
    return to_call / (pot + to_call)


# --------------------------------------------------------------------------- #
# 몬테카를로 에쿼티
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class EquityResult:
    win: float
    tie: float
    equity: float  # 승 + 무승부 지분
    iterations: int
    num_opponents: int

    @property
    def lose(self) -> float:
        return max(0.0, 1.0 - self.win - self.tie)

    @property
    def fair_share(self) -> float:
        """상대 수만 고려한 평균 몫. 이보다 높으면 평균 이상의 핸드."""
        return 1.0 / (self.num_opponents + 1)

    @property
    def relative_strength(self) -> float:
        return self.equity / self.fair_share

    def summary(self) -> str:
        return (
            f"에쿼티 {self.equity:.1%} (승 {self.win:.1%} / 무 {self.tie:.1%} / 패 {self.lose:.1%}), "
            f"상대 {self.num_opponents}명 · 시뮬레이션 {self.iterations:,}회. "
            f"평균 몫 {self.fair_share:.1%}의 {self.relative_strength:.2f}배"
        )


def _validate(hole: Sequence[int], board: Sequence[int]) -> None:
    if len(hole) != 2:
        raise ValueError("홀카드는 2장이어야 합니다")
    if len(board) not in (0, 3, 4, 5):
        raise ValueError("보드는 0/3/4/5장이어야 합니다")
    if len(set(hole) | set(board)) != len(hole) + len(board):
        raise ValueError("홀카드와 보드에 중복 카드가 있습니다")


def _sample_from_ranges(
    ranges: Sequence[Any],
    stub: list[int],
    used: set[int],
    rng: random.Random,
) -> list[list[int]]:
    """상대별 레인지에서 카드 충돌 없이 콤보를 하나씩 뽑는다.

    None = 랜덤 2장, `.sample(rng, used)` 를 가진 객체(WeightedRange) = 가중치 샘플링,
    그 외 콤보 시퀀스 = 균등 샘플링.
    """
    hands: list[list[int]] = []
    for combo_range in ranges:
        if combo_range is None:
            free = [c for c in stub if c not in used]
            pick = rng.sample(free, 2)
        elif hasattr(combo_range, "sample"):
            pick = combo_range.sample(rng, used)
            if pick is None:
                raise ValueError("카드 제거 후 레인지에 남은 콤보가 없습니다")
        else:
            pick = None
            for _ in range(24):  # 대부분 몇 번 안에 성공하는 리젝션 샘플링
                a, b = combo_range[rng.randrange(len(combo_range))]
                if a not in used and b not in used:
                    pick = [a, b]
                    break
            if pick is None:
                valid = [c for c in combo_range if c[0] not in used and c[1] not in used]
                if not valid:
                    raise ValueError("카드 제거 후 레인지에 남은 콤보가 없습니다")
                pick = list(rng.choice(valid))
        used.update(pick)
        hands.append(pick)
    return hands


def monte_carlo_equity(
    hole: Sequence[int],
    board: Sequence[int] = (),
    num_opponents: int = 1,
    iterations: int = 2000,
    rng: random.Random | None = None,
    opponent_ranges: Sequence[Any] | None = None,
) -> EquityResult:
    """남은 보드와 상대 홀카드를 무작위로 채워 승률을 추정한다.

    opponent_ranges 를 주면 각 상대의 홀카드를 해당 레인지(콤보 목록 / WeightedRange / None=랜덤)에서 뽑는다.
    표준오차 ≈ sqrt(p(1-p)/N) → 2,000회면 약 ±1.1%p.
    """
    _validate(hole, board)
    if not 1 <= num_opponents <= 9:
        raise ValueError("상대 수는 1~9명이어야 합니다")
    if opponent_ranges is not None and len(opponent_ranges) != num_opponents:
        raise ValueError("opponent_ranges 길이는 상대 수와 같아야 합니다")
    if iterations <= 0:
        raise ValueError("iterations 는 양수여야 합니다")

    rng = rng or random.Random()
    hole_l, board_l = list(hole), list(board)
    known = set(hole_l) | set(board_l)
    stub = [c for c in FULL_DECK if c not in known]
    need = 5 - len(board_l)
    n_opp_cards = 2 * num_opponents

    wins = ties = 0
    equity_sum = 0.0
    for _ in range(iterations):
        if opponent_ranges is None:
            drawn = rng.sample(stub, n_opp_cards + need)
            opp_hands = [drawn[i : i + 2] for i in range(0, n_opp_cards, 2)]
            full_board = board_l + drawn[n_opp_cards:]
        else:
            used = set(known)
            opp_hands = _sample_from_ranges(opponent_ranges, stub, used, rng)
            remaining = [c for c in stub if c not in used]
            full_board = board_l + rng.sample(remaining, need)

        mine = raw_score(hole_l, full_board)
        best, n_best = 7463, 0
        for hand in opp_hands:
            s = raw_score(hand, full_board)
            if s < best:
                best, n_best = s, 1
            elif s == best:
                n_best += 1

        if mine < best:
            wins += 1
            equity_sum += 1.0
        elif mine == best:
            ties += 1
            equity_sum += 1.0 / (n_best + 1)

    return EquityResult(
        win=wins / iterations,
        tie=ties / iterations,
        equity=equity_sum / iterations,
        iterations=iterations,
        num_opponents=num_opponents,
    )


# --------------------------------------------------------------------------- #
# 아웃츠
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class OutsReport:
    current: HandRank
    outs: dict[str, list[int]]  # 개선되는 족보 이름 → 해당 카드들
    unseen: int                 # 내 입장에서 보이지 않는 카드 수
    cards_to_come: int          # 플랍 2장, 턴 1장

    @property
    def count(self) -> int:
        return sum(len(cards) for cards in self.outs.values())

    @property
    def next_card_prob(self) -> float:
        return self.count / self.unseen

    @property
    def by_river_prob(self) -> float:
        if self.cards_to_come == 1:
            return self.next_card_prob
        return 1.0 - comb(self.unseen - self.count, 2) / comb(self.unseen, 2)

    @property
    def rule_of_thumb(self) -> float:
        """2 & 4 법칙: 플랍에서 아웃츠×4%, 턴에서 아웃츠×2%."""
        return self.count * (4 if self.cards_to_come == 2 else 2) / 100

    def summary(self) -> str:
        if not self.count:
            return f"현재 {self.current.name_ko} — 족보를 개선하는 아웃츠가 없습니다."
        parts = ", ".join(f"{name} {len(cards)}장({pretty(cards)})" for name, cards in self.outs.items())
        line = f"아웃츠 {self.count}장: {parts}. 다음 카드 적중 {self.next_card_prob:.1%}"
        if self.cards_to_come == 2:
            line += f", 리버까지 {self.by_river_prob:.1%} (4의 법칙 ≈ {self.rule_of_thumb:.0%})"
        else:
            line += f" (2의 법칙 ≈ {self.rule_of_thumb:.0%})"
        return line


def find_outs(hole: Sequence[int], board: Sequence[int]) -> OutsReport:
    """다음 카드 한 장으로 '내 홀카드 덕분에' 족보 등급이 올라가는 카드를 찾는다.

    휴리스틱 규칙(학습용):
      1) 족보 등급이 현재보다 올라가야 한다.
      2) 보드만으로도 같은 등급이 되는 카드는 제외 (모두가 같이 좋아짐).
      3) 보드를 페어로 만들어 생기는 투페어는 제외 (카운터핏 위험이 큰 '가짜 아웃').
      4) 이미 페어인 보드에서 내 페어가 생기는 '투페어'는 원페어로 분류.
    """
    _validate(hole, board)
    if len(board) not in (3, 4):
        raise ValueError("아웃츠는 플랍/턴에서만 계산합니다")

    current = evaluate(hole, board)
    hole_ranks = {rank_of(c) for c in hole}
    board_ranks = {rank_of(c) for c in board}
    known = set(hole) | set(board)
    unseen = [c for c in FULL_DECK if c not in known]

    outs: dict[str, list[int]] = defaultdict(list)
    for card in unseen:
        board_after = [*board, card]
        new_class = evaluate(hole, board_after).rank_class
        if new_class >= current.rank_class:
            continue
        if len(board_after) >= 5:
            board_class = evaluate([], board_after).rank_class
        else:
            board_class = rank_count_class(board_after)
        if new_class >= board_class:
            continue
        if new_class == TWO_PAIR and rank_of(card) in board_ranks and rank_of(card) not in hole_ranks:
            continue
        if new_class == TWO_PAIR and board_class == PAIR:
            new_class = PAIR  # 페어 보드 + 내 페어 = 사실상 원페어
        outs[CLASS_NAME_KO[new_class]].append(card)

    ordered = dict(sorted(outs.items(), key=lambda kv: -len(kv[1])))
    return OutsReport(current, ordered, len(unseen), 5 - len(board))


# --------------------------------------------------------------------------- #
# 나를 이기는 상대 핸드 (Nut / Threat 분석)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ThreatGroup:
    score: int
    hand_name: str
    combos: tuple[str, ...]  # 대표 콤보 예시
    count: int               # 같은 강도의 전체 콤보 수


@dataclass(frozen=True)
class ThreatReport:
    my_rank: HandRank
    total_combos: int
    beat_me: int
    tie_me: int
    beat_by_class: dict[str, int]
    nut_groups: list[ThreatGroup]  # 현재 보드 기준 가장 강한 상대 핸드들

    @property
    def beat_ratio(self) -> float:
        return self.beat_me / self.total_combos if self.total_combos else 0.0

    @property
    def i_have_nuts(self) -> bool:
        return self.beat_me == 0

    def summary(self) -> str:
        head = (
            f"내 핸드: {self.my_rank.name_ko}. 가능한 상대 콤보 {self.total_combos:,}개 중 "
            f"{self.beat_me:,}개({self.beat_ratio:.1%})가 나를 이기고 {self.tie_me}개는 무승부."
        )
        if self.i_have_nuts:
            return head + " 현재 보드에서 넛(최강 핸드)입니다!"
        classes = ", ".join(f"{name} {n}" for name, n in self.beat_by_class.items())
        nuts = " > ".join(f"{g.hand_name}[{' '.join(g.combos)}]" for g in self.nut_groups[:3])
        return f"{head}\n  나를 이기는 족보: {classes}\n  넛 순서: {nuts}"


def analyze_threats(
    hole: Sequence[int],
    board: Sequence[int],
    top_n: int = 5,
    max_examples: int = 3,
) -> ThreatReport:
    """보이지 않는 카드로 만들 수 있는 모든 상대 홀카드(플랍 기준 1,081개)를 전수 조사한다.

    카드 제거 효과(내 홀카드가 상대 콤보를 막는 것)가 자동 반영된다.
    """
    _validate(hole, board)
    if len(board) < 3:
        raise ValueError("위협 분석은 플랍 이후에만 가능합니다")

    my_rank = evaluate(hole, board)
    board_l = list(board)
    known = set(hole) | set(board)
    unseen = [c for c in FULL_DECK if c not in known]

    by_score: dict[int, list[Combo]] = defaultdict(list)
    for combo in combinations(unseen, 2):
        by_score[raw_score(list(combo), board_l)].append(combo)

    total = sum(len(v) for v in by_score.values())
    beat_by_class: dict[str, int] = defaultdict(int)
    beat = tie = 0
    for s, combos in by_score.items():
        if s < my_rank.score:
            beat += len(combos)
            beat_by_class[HandRank(s).name_ko] += len(combos)
        elif s == my_rank.score:
            tie += len(combos)

    groups = [
        ThreatGroup(
            score=s,
            hand_name=HandRank(s).name_ko,
            combos=tuple(pretty(c).replace(" ", "") for c in by_score[s][:max_examples]),
            count=len(by_score[s]),
        )
        for s in sorted(by_score)[:top_n]
    ]
    ordered_classes = dict(sorted(beat_by_class.items(), key=lambda kv: -kv[1]))
    return ThreatReport(my_rank, total, beat, tie, ordered_classes, groups)
