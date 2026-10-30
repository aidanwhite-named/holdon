"""테이블 인원에 따른 포지션 이름."""

from __future__ import annotations

from typing import Sequence

# 버튼부터 시계 방향 순서. BB 다음부터 UTG(얼리) → CO(레이트) 순.
POSITION_NAMES: dict[int, tuple[str, ...]] = {
    2: ("BTN/SB", "BB"),  # 헤즈업: 버튼이 SB를 내고 프리플랍 선행동
    3: ("BTN", "SB", "BB"),
    4: ("BTN", "SB", "BB", "UTG"),
    5: ("BTN", "SB", "BB", "UTG", "CO"),
    6: ("BTN", "SB", "BB", "UTG", "HJ", "CO"),
    7: ("BTN", "SB", "BB", "UTG", "MP", "HJ", "CO"),
    8: ("BTN", "SB", "BB", "UTG", "UTG+1", "MP", "HJ", "CO"),
    9: ("BTN", "SB", "BB", "UTG", "UTG+1", "MP", "LJ", "HJ", "CO"),
    10: ("BTN", "SB", "BB", "UTG", "UTG+1", "UTG+2", "MP", "LJ", "HJ", "CO"),
}


def assign_positions(seats_from_button: Sequence[int]) -> dict[int, str]:
    """[버튼 좌석, 그다음 좌석, ...] → {좌석: 포지션 이름}."""
    names = POSITION_NAMES[len(seats_from_button)]
    return dict(zip(seats_from_button, names))


def preflop_order(num_players: int) -> tuple[str, ...]:
    """프리플랍 행동 순서 (UTG … BTN, SB, BB)."""
    names = POSITION_NAMES[num_players]
    return names if num_players == 2 else names[3:] + names[:3]


def postflop_order(num_players: int) -> tuple[str, ...]:
    """포스트플랍 행동 순서 (SB, BB, UTG … BTN). 뒤에 있을수록 인 포지션."""
    names = POSITION_NAMES[num_players]
    return ("BB", "BTN/SB") if num_players == 2 else names[1:] + names[:1]


def players_behind(position: str, num_players: int) -> int:
    """프리플랍에서 내 뒤에 행동할 인원 (블라인드 포함). 오픈 레인지 선택 기준."""
    order = preflop_order(num_players)
    return num_players - 1 - order.index(position)
