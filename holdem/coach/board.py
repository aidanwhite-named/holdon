"""보드 텍스처, 메이드 핸드 분류, 드로우 판정 (핸드 리딩·사이징 공용)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Sequence

from treys import Card

from ..cards import pretty, rank_of
from ..evaluator import PAIR, STRAIGHT, THREE_OF_A_KIND, TWO_PAIR, evaluate, rank_count_class

# 핸드 리딩 카테고리 (강한 순)
MONSTER = "강한 메이드(트리플+)"
TWO_PAIR_CAT = "투페어"
TOP_PAIR = "오버페어/탑페어"
WEAK_PAIR = "중간·약한 페어"
DRAW = "드로우"
AIR = "에어"
CATEGORIES = (MONSTER, TWO_PAIR_CAT, TOP_PAIR, WEAK_PAIR, DRAW, AIR)


def _rank_values(cards: Sequence[int]) -> set[int]:
    """2~14 (에이스는 휠용 1 도 포함)."""
    values = {rank_of(c) + 2 for c in cards}
    if 14 in values:
        values.add(1)
    return values


def _board_class(board: Sequence[int]) -> int:
    return evaluate([], board).rank_class if len(board) >= 5 else rank_count_class(board)


# --------------------------------------------------------------------------- #
# 보드 텍스처
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class BoardTexture:
    paired: bool
    max_suit: int          # 같은 무늬 최대 장수
    connected: int         # 5칸 창 안에 들어가는 서로 다른 랭크 최대 개수
    broadways: int         # T 이상 카드 수
    high_rank: int         # 최고 랭크 (2~14)
    wetness: float         # 0(드라이) ~ 1(웻)

    @property
    def label(self) -> str:
        return "드라이" if self.wetness < 0.3 else "보통" if self.wetness < 0.6 else "웻"

    @property
    def suit_label(self) -> str:
        return {1: "레인보우", 2: "투톤", 3: "3장 같은 무늬"}.get(self.max_suit, "4장+ 같은 무늬")

    def describe(self, board: Sequence[int]) -> str:
        bits = [self.suit_label]
        if self.paired:
            bits.append("페어 보드")
        bits.append("커넥티드" if self.connected >= 3 else "세미 커넥티드" if self.connected == 2 else "언커넥티드")
        return f"{pretty(board)} — {'·'.join(bits)} ({self.label})"


def analyze_board(board: Sequence[int]) -> BoardTexture:
    if len(board) < 3:
        raise ValueError("보드 텍스처는 플랍 이후에만 분석합니다")
    suits = Counter(Card.get_suit_int(c) for c in board)
    ranks = Counter(rank_of(c) for c in board)
    values = _rank_values(board)
    connected = max(sum(1 for v in values if low <= v <= low + 4) for low in range(1, 11))
    max_suit = max(suits.values())
    paired = max(ranks.values()) >= 2
    broadways = sum(1 for c in board if rank_of(c) + 2 >= 10)

    wet = 0.0
    if max_suit >= 3:
        wet += 0.45
    elif max_suit == 2 and len(board) < 5:
        wet += 0.25
    wet += 0.4 if connected >= 3 else 0.2 if connected == 2 else 0.0
    wet += 0.1 if broadways >= 2 else 0.0
    wet -= 0.1 if paired else 0.0
    return BoardTexture(paired, max_suit, connected, broadways, max(ranks) + 2, min(1.0, max(0.0, wet)))


# --------------------------------------------------------------------------- #
# 드로우 / 메이드 분류
# --------------------------------------------------------------------------- #
def draw_type(hole: Sequence[int], board: Sequence[int]) -> str | None:
    """'콤보 드로우' / '플러시 드로우' / '양방 스트레이트 드로우' / '거트샷' / None. 플랍·턴 전용."""
    if len(board) not in (3, 4):
        return None
    if evaluate(hole, board).rank_class <= STRAIGHT:
        return None

    cards = [*hole, *board]
    suits = Counter(Card.get_suit_int(c) for c in cards)
    hole_suits = {Card.get_suit_int(c) for c in hole}
    flush_draw = any(n == 4 and s in hole_suits for s, n in suits.items())

    all_values = _rank_values(cards)
    hole_values = _rank_values(hole)
    completing = set()
    for x in range(1, 15):
        if x in all_values:
            continue
        with_x = all_values | {x} | ({1} if x == 14 else set())
        for low in range(1, 11):
            window = set(range(low, low + 5))
            if window <= with_x and window & hole_values:
                completing.add(x if x != 1 else 14)
                break
    straight = "양방 스트레이트 드로우" if len(completing) >= 2 else "거트샷" if completing else None

    if flush_draw and straight:
        return "콤보 드로우"
    if flush_draw:
        return "플러시 드로우"
    return straight


def made_category(hole: Sequence[int], board: Sequence[int]) -> str:
    """보드 대비 내 홀카드가 만든 메이드 핸드 등급 (드로우 제외)."""
    cls = evaluate(hole, board).rank_class
    board_cls = _board_class(board)
    if cls >= board_cls:
        return AIR  # 보드가 플레이 (홀카드 기여 없음)
    if cls <= THREE_OF_A_KIND:
        return MONSTER
    if cls == TWO_PAIR and board_cls != PAIR:
        return TWO_PAIR_CAT

    # 원페어 (또는 페어 보드 + 내 페어 = 사실상 원페어)
    board_ranks = sorted({rank_of(c) for c in board}, reverse=True)
    hole_ranks = [rank_of(c) for c in hole]
    top = board_ranks[0]
    if hole_ranks[0] == hole_ranks[1]:
        return TOP_PAIR if hole_ranks[0] > top else WEAK_PAIR
    paired_with_board = [r for r in hole_ranks if r in board_ranks]
    return TOP_PAIR if paired_with_board and max(paired_with_board) == top else WEAK_PAIR


def categorize(hole: Sequence[int], board: Sequence[int]) -> str:
    """핸드 리딩용 최종 카테고리: 메이드가 약하면 드로우 여부를 우선한다."""
    made = made_category(hole, board)
    if made in (MONSTER, TWO_PAIR_CAT, TOP_PAIR):
        return made
    if draw_type(hole, board):
        return DRAW
    return made
