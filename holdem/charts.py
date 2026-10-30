"""프리플랍 차트 (100BB 캐시 기준 근사 GTO 레인지, 학습용 단순화 버전).

오픈 레인지는 포지션 '이름'이 아니라 '내 뒤에 남은 인원(players_behind)'으로 고른다.
→ 6-max UTG(뒤에 5명) = 9-max LJ 와 같은 레인지. 인원이 달라도 일관된 기준.
"""

from __future__ import annotations

from .ranges import HandRange

_P = HandRange.parse

# 뒤에 남은 인원 → 레이즈 퍼스트 인(RFI) 오픈 레인지
RFI_BY_BEHIND: dict[int, HandRange] = {
    8: _P("66+, A9s+, A5s, KTs+, QTs+, JTs, T9s, AJo+, KQo", "UTG 오픈"),
    7: _P("55+, A8s+, A5s-A4s, KTs+, QTs+, JTs, T9s, 98s, AJo+, KQo", "UTG+1 오픈"),
    6: _P("44+, A2s+, K9s+, QTs+, JTs, T9s, 98s, 87s, ATo+, KJo+", "MP 오픈"),
    5: _P("22+, A2s+, K9s+, Q9s+, J9s+, T9s, 98s, 87s, 76s, ATo+, KJo+, QJo", "LJ 오픈"),
    4: _P("22+, A2s+, K7s+, Q9s+, J9s+, T8s+, 97s+, 87s, 76s, 65s, A9o+, KTo+, QTo+, JTo", "HJ 오픈"),
    3: _P(
        "22+, A2s+, K5s+, Q8s+, J8s+, T8s+, 97s+, 86s+, 75s+, 65s, 54s, A7o+, A5o, K9o+, Q9o+, J9o+, T9o",
        "CO 오픈",
    ),
    2: _P(
        "22+, A2s+, K2s+, Q4s+, J6s+, T6s+, 96s+, 85s+, 74s+, 64s+, 53s+, 43s, "
        "A2o+, K7o+, Q8o+, J8o+, T8o+, 98o, 87o",
        "BTN 오픈",
    ),
    1: _P(
        "22+, A2s+, K3s+, Q5s+, J7s+, T7s+, 97s+, 86s+, 75s+, 65s, 54s, A4o+, K8o+, Q9o+, J9o+, T9o",
        "SB 오픈",
    ),
}

HEADS_UP_BTN_OPEN = _P(
    "22+, A2s+, A2o+, K2s+, K2o+, Q2s+, Q4o+, J2s+, J6o+, T3s+, T6o+, 95s+, 96o+, 84s+, 86o+, "
    "74s+, 76o, 63s+, 65o, 53s+, 43s",
    "헤즈업 BTN 오픈",
)

# 오프너가 얼리(뒤에 5명 이상)냐 레이트냐로 나눈 대응 레인지
THREEBET_VS_EARLY = _P("QQ+, AKs, AKo, A5s-A4s", "3벳 (vs 얼리 오픈)")
THREEBET_VS_LATE = _P("TT+, AJs+, KQs, AQo+, A5s-A2s, K9s, 76s, 65s", "3벳 (vs 레이트 오픈)")
CALL_VS_EARLY = _P("JJ-22, AQs-ATs, KQs, KJs, QJs, JTs, T9s, 98s, AQo", "콜 (vs 얼리 오픈)")
CALL_VS_LATE = _P("99-22, ATs-A6s, KTs+, QTs+, J9s+, T9s, 98s, 87s, AJo-ATo, KQo", "콜 (vs 레이트 오픈)")
SB_CALL = _P("99-66, AQs-ATs, KQs, KJs, QJs, JTs", "SB 콜")
BB_DEFEND_VS_EARLY = _P(
    "22+, A2s+, K6s+, Q8s+, J8s+, T8s+, 97s+, 86s+, 75s+, 65s, 54s, A9o+, KTo+, QTo+, JTo",
    "BB 디펜스 (vs 얼리 오픈)",
)
BB_DEFEND_VS_LATE = _P(
    "22+, A2s+, K2s+, Q4s+, J6s+, T6s+, 95s+, 85s+, 74s+, 63s+, 53s+, 43s, "
    "A2o+, K8o+, Q9o+, J9o+, T8o+, 98o, 87o, 76o",
    "BB 디펜스 (vs 레이트 오픈)",
)

FOURBET = _P("QQ+, AKs, AKo, A5s", "4벳")
CALL_THREEBET = _P("JJ-88, AQs-ATs, KQs, KJs, QJs, JTs, T9s, AQo", "3벳 콜")
COLD_CALL_THREEBET = _P("QQ-JJ, AKs, AQs", "3벳 콜드콜")
FIVEBET_SHOVE = _P("KK+, AKs", "5벳 올인")
CALL_FOURBET = _P("QQ, AKo", "4벳 콜")

LIMP = _P(
    "22-99, A2s-A9s, K2s-KTs, Q8s-QTs, J8s+, T8s+, 97s+, 86s+, 75s+, 64s+, 54s, "
    "A2o-ATo, K9o-KJo, QTo+, JTo",
    "림프 레인지",
)
OVERLIMP = _P("22-77, A2s-A9s, 54s, 65s, 76s, 87s, 98s, T9s", "오버림프")

# 숏스택 푸시/폴드 (오픈 상황, 유효스택 BB 기준 단순화)
PUSH_LATE_DEEP = _P("22+, A2s+, A7o+, A5o, K9s+, KTo+, QTs+, QJo, JTs", "푸시 (레이트, 9~12BB)")
PUSH_EARLY_DEEP = _P("66+, ATs+, AJo+, KQs", "푸시 (얼리, 9~12BB)")
PUSH_LATE_SHORT = _P(
    "22+, A2s+, A2o+, K5s+, K9o+, Q8s+, QTo+, J8s+, JTo, T8s+, 97s+, 87s, 76s", "푸시 (레이트, ≤8BB)"
)
PUSH_EARLY_SHORT = _P("55+, A8s+, A5s, ATo+, KTs+, KQo", "푸시 (얼리, ≤8BB)")


def rfi_range(position: str, players_behind: int) -> HandRange:
    """오픈 레인지 (라벨은 실제 포지션 이름 — 6-max UTG 는 LJ 차트를 쓰지만 'UTG 오픈'으로 표시)."""
    if position == "BTN/SB":
        return HEADS_UP_BTN_OPEN
    chart = RFI_BY_BEHIND[max(1, min(8, players_behind))]
    return HandRange(chart.weights, f"{position} 오픈")


def push_range(players_behind: int, effective_bb: float) -> HandRange:
    late = players_behind <= 3
    if effective_bb <= 8:
        return PUSH_LATE_SHORT if late else PUSH_EARLY_SHORT
    return PUSH_LATE_DEEP if late else PUSH_EARLY_DEEP


def is_early(players_behind: int) -> bool:
    return players_behind >= 5
