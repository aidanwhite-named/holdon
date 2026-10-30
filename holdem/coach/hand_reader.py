"""상대 행동 추론 (Hand Reading Assistant).

1) 프리플랍: 상대의 행동(오픈/림프/콜/3벳/4벳)과 포지션으로 차트 레인지를 고른다.
2) 포스트플랍: 스트리트마다 그 보드에서 콤보의 카테고리(강한 메이드/투페어/탑페어/약한 페어/드로우/에어)로
   가중치를 조정한다.
   - 벳/레이즈: 강한 핸드·드로우 유지, 약한 핸드 감소, 일부 블러프(에어) 유지 (사이즈가 클수록 양극화)
   - 콜: 중간 강도·드로우 유지, 최상위(레이즈했을 핸드)·최하위(폴드했을 핸드) 감소
   - 체크: 최상위 일부(슬로우플레이)만 감소
결과(WeightedRange)는 그대로 몬테카를로 에쿼티의 상대 레인지로 쓰인다.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .. import charts
from ..models import ACTION_LABEL_KO, ActionRecord, ActionType, PlayerView, Street
from ..positions import players_behind
from ..ranges import HandRange, WeightedRange, hand_code
from .board import AIR, CATEGORIES, DRAW, MONSTER, TOP_PAIR, TWO_PAIR_CAT, categorize

AGGRESSIVE = (ActionType.BET, ActionType.RAISE)
_BOARD_LEN = {Street.FLOP: 3, Street.TURN: 4, Street.RIVER: 5}


# --------------------------------------------------------------------------- #
# 프리플랍 레인지
# --------------------------------------------------------------------------- #
def _bb_check_range() -> HandRange:
    """림프 팟에서 BB 체크: 강한 핸드는 보통 레이즈하므로 가중치를 낮춘다."""
    strong = charts.THREEBET_VS_LATE
    any_two = HandRange.any_two()
    return HandRange({c: 0.3 if c in strong else 1.0 for c in any_two.weights}, "BB 체크 (레인지 넓음)")


def _discount(base: HandRange, strong: HandRange, factor: float, label: str) -> HandRange:
    """콜 레인지에서 더 공격적으로 플레이했을 강한 핸드의 비중을 낮춘다."""
    return HandRange({c: w * (factor if c in strong else 1.0) for c, w in base.weights.items()}, label)


def _range_for_action(
    rec: ActionRecord,
    raises_before: int,
    limpers_before: int,
    opener_position: str | None,
    self_raised: bool,
    num_dealt: int,
    big_blind: int,
) -> HandRange | None:
    kind = rec.kind
    behind = players_behind(rec.position, num_dealt)
    opener_early = opener_position is not None and charts.is_early(players_behind(opener_position, num_dealt))

    if kind == ActionType.CHECK:
        return _bb_check_range() if raises_before == 0 else None
    if kind == ActionType.CALL:
        if raises_before == 0:
            return charts.LIMP
        if raises_before == 1:
            if rec.position == "BB":
                base = charts.BB_DEFEND_VS_EARLY if opener_early else charts.BB_DEFEND_VS_LATE
                three_bet = charts.THREEBET_VS_EARLY if opener_early else charts.THREEBET_VS_LATE
                return _discount(base, three_bet, 0.35, base.label)
            if rec.position == "SB":
                return charts.SB_CALL
            return charts.CALL_VS_EARLY if opener_early else charts.CALL_VS_LATE
        if raises_before == 2:
            return charts.CALL_THREEBET if self_raised else charts.COLD_CALL_THREEBET
        return charts.CALL_FOURBET
    if kind in AGGRESSIVE:
        if raises_before == 0:
            if rec.all_in and rec.street_total <= 15 * big_blind:
                return charts.push_range(behind, rec.street_total / big_blind)
            if limpers_before:  # 아이솔레이션 레이즈는 오픈보다 타이트
                return charts.rfi_range(rec.position, min(8, behind + 2))
            return charts.rfi_range(rec.position, behind)
        if raises_before == 1:
            return charts.THREEBET_VS_EARLY if opener_early else charts.THREEBET_VS_LATE
        if raises_before == 2:
            return charts.FOURBET
        return charts.FIVEBET_SHOVE
    return None


def preflop_range(view: PlayerView, seat: int) -> HandRange | None:
    """해당 좌석의 프리플랍 행동으로 추정한 레인지. 아직 자발적 행동이 없으면 None."""
    result: HandRange | None = None
    raises = limpers = 0
    opener: str | None = None
    self_raised = False
    for rec in view.history:
        if rec.street != Street.PREFLOP:
            break
        if rec.seat == seat:
            r = _range_for_action(rec, raises, limpers, opener, self_raised, view.num_dealt, view.big_blind)
            if r is not None:
                # 이전 행동과 모순되지 않는 핸드만 남긴다 (예: 오픈 후 3벳 콜 = 오픈 ∩ 3벳콜)
                result = r if result is None else result.scaled(r, outside=0.05, label=r.label)
            if rec.kind in AGGRESSIVE:
                self_raised = True
        if rec.kind in AGGRESSIVE:
            if raises == 0:
                opener = rec.position
            raises += 1
        elif rec.kind == ActionType.CALL and raises == 0:
            limpers += 1
    return result


# --------------------------------------------------------------------------- #
# 포스트플랍 가중치
# --------------------------------------------------------------------------- #
#                    강한메이드 투페어 탑페어 약한페어 드로우 에어
_WEIGHTS = {
    "raise":      (1.0, 1.0, 0.30, 0.08, 0.50, 0.10),
    "bet_big":    (1.0, 1.0, 0.70, 0.20, 0.70, 0.20),   # 팟의 66% 이상: 양극화
    "bet_medium": (1.0, 1.0, 0.85, 0.35, 0.75, 0.20),
    "bet_small":  (1.0, 1.0, 1.00, 0.60, 0.80, 0.30),   # 팟의 40% 이하: 넓은 레인지
    "call":       (0.40, 0.60, 1.00, 0.80, 1.00, 0.12),  # 최상위는 레이즈했을 것, 에어는 폴드했을 것
    "check":      (0.35, 0.50, 0.70, 1.00, 0.80, 1.00),  # 강한 핸드 일부만 슬로우플레이
}


def _weight_key(rec: ActionRecord) -> str | None:
    if rec.kind == ActionType.RAISE:
        return "raise"
    if rec.kind == ActionType.BET:
        ratio = rec.size_ratio
        return "bet_big" if ratio >= 0.66 else "bet_small" if ratio <= 0.4 else "bet_medium"
    if rec.kind == ActionType.CALL:
        return "call"
    if rec.kind == ActionType.CHECK:
        return "check"
    return None


def _reweight(range_: WeightedRange, rec: ActionRecord, board: list[int]) -> WeightedRange:
    """그 보드에서 각 콤보의 카테고리(메이드 강도/드로우)에 행동별 가중치를 곱한다."""
    key = _weight_key(rec)
    if key is None or not range_.combos:
        return range_
    table = dict(zip(CATEGORIES, _WEIGHTS[key]))
    weights = [w * table[categorize(combo, board)] for combo, w in zip(range_.combos, range_.weights)]
    return WeightedRange(range_.combos, weights, range_.label)


# --------------------------------------------------------------------------- #
# 결과
# --------------------------------------------------------------------------- #
@dataclass
class OpponentRead:
    seat: int
    name: str
    position: str
    line: str                          # 액션 요약
    preflop_label: str
    range: WeightedRange | None        # None = 정보 없음 (랜덤 가정)
    composition: dict[str, float] = field(default_factory=dict)
    guidance: list[str] = field(default_factory=list)

    @property
    def combos(self) -> float:
        return self.range.total_weight if self.range else 1326.0

    def lines(self) -> list[str]:
        head = f"{self.name}({self.position}): {self.line or '아직 자발적 액션 없음'}"
        if self.range is None:
            return [head, "  레인지: 정보 없음 → 랜덤 핸드로 가정"]
        out = [head, f"  추정 레인지: {self.preflop_label} 기반, 약 {self.combos:.0f}콤보 (전체의 {self.combos / 1326:.0%})"]
        if self.composition:
            comp = " / ".join(f"{k} {v:.0%}" for k, v in self.composition.items() if v >= 0.005)
            out.append(f"  구성: {comp}")
        out += [f"  → {g}" for g in self.guidance]
        return out


def _action_line(records: list[ActionRecord], big_blind: int) -> str:
    parts = []
    for rec in records:
        label = ACTION_LABEL_KO[rec.kind]
        if rec.kind == ActionType.BET:
            label += f" {rec.size_ratio:.0%}"
        elif rec.kind == ActionType.RAISE:
            label += f" {rec.street_total / big_blind:.1f}BB" if rec.street == Street.PREFLOP else f" {rec.size_ratio:.1f}배"
        if rec.all_in:
            label += "(올인)"
        parts.append(f"{rec.street.label} {label}")
    return " → ".join(parts)


def _preflop_composition(range_: WeightedRange) -> dict[str, float]:
    buckets: dict[str, float] = defaultdict(float)
    for combo, w in zip(range_.combos, range_.weights):
        code = hand_code(combo)
        hi, lo, suited = code[0], code[1], code.endswith("s")
        broadway = set("AKQJT")
        if code in ("AA", "KK", "QQ", "AKs", "AKo"):
            key = "프리미엄(QQ+, AK)"
        elif hi == lo:
            key = "페어(JJ 이하)"
        elif suited and (hi == "A" or (hi in broadway and lo in broadway)):
            key = "수딧 에이스/브로드웨이"
        elif suited:
            key = "수딧 커넥터·기타 수딧"
        elif hi in broadway and lo in broadway:
            key = "오프수트 브로드웨이"
        else:
            key = "기타 오프수트"
        buckets[key] += w
    total = sum(buckets.values()) or 1.0
    return {k: v / total for k, v in sorted(buckets.items(), key=lambda kv: -kv[1])}


def _postflop_composition(range_: WeightedRange, board: list[int]) -> dict[str, float]:
    buckets = {c: 0.0 for c in CATEGORIES}
    for combo, w in zip(range_.combos, range_.weights):
        buckets[categorize(combo, board)] += w
    total = sum(buckets.values()) or 1.0
    return {k: v / total for k, v in buckets.items()}


def _guidance(read: OpponentRead, records: list[ActionRecord], board: list[int]) -> list[str]:
    tips: list[str] = []
    comp = read.composition
    if board:
        strong = comp.get(MONSTER, 0) + comp.get(TWO_PAIR_CAT, 0)
        value = strong + comp.get(TOP_PAIR, 0)
        if strong >= 0.35:
            tips.append(f"투페어 이상 {strong:.0%}: 원페어로 큰 팟을 만들지 말고 팟 컨트롤·폴드 고려")
        elif value >= 0.55:
            tips.append(f"탑페어 이상 {value:.0%}: 약한 페어로 블러프 캐치하기 어려운 레인지")
        if comp.get(DRAW, 0) >= 0.25:
            tips.append(f"드로우 {comp[DRAW]:.0%}: 밸류 핸드는 크게 벳해 나쁜 가격을 제시, 완성 카드(플러시·스트레이트)에 주의")
        if comp.get(AIR, 0) >= 0.35:
            tips.append(f"에어 {comp[AIR]:.0%}: 블러프 비중 높음 → 쇼다운 밸류 있는 핸드로 콜(블러프 캐치) 가치 상승")
    else:
        pct = read.combos / 1326
        if pct <= 0.12:
            tips.append(f"매우 강한 레인지(상위 {pct:.0%}): 약한 에이스·작은 페어 등 마지널 핸드는 폴드, 계속하면 3벳/4벳으로 양극화")
        elif pct <= 0.3:
            tips.append(f"중간 레인지(상위 {pct:.0%}): 도미네이트 위험(KJ vs KQ 등)에 주의, 포지션이 있으면 콜 가능")
        else:
            tips.append(f"넓은 레인지(상위 {pct:.0%}): 강한 핸드로 적극적으로 밸류, 포스트플랍에서 c-bet 에 자주 폴드할 레인지")

    street_records = [r for r in records if r.street != Street.PREFLOP]
    if street_records:
        last = street_records[-1]
        same_street = [r for r in street_records if r.street == last.street]
        if (
            last.kind == ActionType.RAISE
            and any(r.kind == ActionType.CHECK for r in same_street[:-1])
        ):
            value = comp.get(MONSTER, 0) + comp.get(TWO_PAIR_CAT, 0) + comp.get(TOP_PAIR, 0) + comp.get(DRAW, 0)
            if value >= 0.5:
                tips.append("체크레이즈: 강한 메이드·강한 드로우 위주 — 마지널 핸드는 폴드 쪽")
            else:
                tips.append("체크레이즈지만 프리플랍 레인지에 이 보드의 강한 핸드가 적다 → 블러프 비중이 높게 추정됨")
        elif last.kind == ActionType.BET and last.size_ratio >= 1.0:
            tips.append("오버벳: 넛에 가깝거나 블러프로 양극화된 라인 — 블러프 블로커 여부로 콜 결정")
        elif last.kind == ActionType.BET and last.size_ratio <= 0.35:
            tips.append("작은 벳(1/3 팟 이하): 넓은 레인지로 치는 경우가 많아 레이즈로 반격하기 좋은 사이즈")
    return tips


def read_opponents(view: PlayerView) -> list[OpponentRead]:
    """폴드하지 않은 상대 전원의 레인지를 추정한다 (내 홀카드·보드는 카드 제거에 반영)."""
    dead = set(view.hole) | set(view.board)
    reads: list[OpponentRead] = []
    for opp in view.opponents:
        if not opp.in_hand:
            continue
        records = [r for r in view.history if r.seat == opp.seat]
        pre = preflop_range(view, opp.seat)
        read = OpponentRead(opp.seat, opp.name, opp.position, _action_line(records, view.big_blind), "", None)
        if pre is not None:
            weighted = pre.to_weighted(dead)
            for rec in records:
                if rec.street == Street.PREFLOP:
                    continue
                board = list(view.board[: _BOARD_LEN[rec.street]])
                weighted = _reweight(weighted, rec, board)
            if weighted.total_weight > 0:
                read.range = weighted
                read.preflop_label = pre.label
                read.composition = (
                    _postflop_composition(weighted, list(view.board)) if view.board else _preflop_composition(weighted)
                )
                read.guidance = _guidance(read, records, list(view.board))
        reads.append(read)
    return reads
