"""족보 판정: treys Evaluator 래퍼.

treys 점수는 1(로열 플러시) ~ 7462(7-5-4-3-2 하이카드)로, 낮을수록 강하다.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Sequence

from treys import Evaluator

from .cards import rank_of

_EVALUATOR = Evaluator()
WORST_SCORE = 7462

# treys 0.1.8 의 rank class (0 = 로열 플러시 … 9 = 하이카드)
ROYAL_FLUSH, STRAIGHT_FLUSH, FOUR_OF_A_KIND, FULL_HOUSE, FLUSH = 0, 1, 2, 3, 4
STRAIGHT, THREE_OF_A_KIND, TWO_PAIR, PAIR, HIGH_CARD = 5, 6, 7, 8, 9

CLASS_NAME_KO = {
    ROYAL_FLUSH: "로열 플러시",
    STRAIGHT_FLUSH: "스트레이트 플러시",
    FOUR_OF_A_KIND: "포카드",
    FULL_HOUSE: "풀하우스",
    FLUSH: "플러시",
    STRAIGHT: "스트레이트",
    THREE_OF_A_KIND: "트리플",
    TWO_PAIR: "투페어",
    PAIR: "원페어",
    HIGH_CARD: "하이카드",
}


@dataclass(frozen=True, order=True)
class HandRank:
    score: int  # 1(최강) ~ 7462(최약)

    @property
    def rank_class(self) -> int:
        return _EVALUATOR.get_rank_class(self.score)

    @property
    def name_en(self) -> str:
        return _EVALUATOR.class_to_string(self.rank_class)

    @property
    def name_ko(self) -> str:
        return CLASS_NAME_KO[self.rank_class]

    @property
    def strength(self) -> float:
        """족보 전체에서의 절대 강도 (1.0 = 로열 플러시, 0.0 = 최약 하이카드)."""
        return 1.0 - (self.score - 1) / (WORST_SCORE - 1)

    def beats(self, other: "HandRank") -> bool:
        return self.score < other.score

    def __str__(self) -> str:
        return f"{self.name_ko} ({self.name_en})"


# 핫 루프용: list 인자를 그대로 받아 점수 정수만 반환 (총 5~7장)
raw_score = _EVALUATOR.evaluate


def score(hole: Sequence[int], board: Sequence[int]) -> int:
    return raw_score(list(hole), list(board))


def evaluate(hole: Sequence[int], board: Sequence[int]) -> HandRank:
    if len(hole) + len(board) < 5:
        raise ValueError("족보 판정에는 최소 5장(홀카드 + 보드)이 필요합니다")
    return HandRank(score(hole, board))


def rank_count_class(cards: Sequence[int]) -> int:
    """5장 미만에서도 쓸 수 있는 '숫자 조합만' 기준 클래스 (페어/트리플/포카드)."""
    counts = sorted(Counter(rank_of(c) for c in cards).values(), reverse=True)
    if not counts:
        return HIGH_CARD
    if counts[0] >= 4:
        return FOUR_OF_A_KIND
    if counts[0] == 3:
        return FULL_HOUSE if len(counts) > 1 and counts[1] >= 2 else THREE_OF_A_KIND
    if counts[0] == 2:
        return TWO_PAIR if len(counts) > 1 and counts[1] == 2 else PAIR
    return HIGH_CARD
