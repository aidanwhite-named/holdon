"""추천 액션과 베팅 사이즈, 그리고 그 수학적 근거.

프리플랍: 포지션 차트(오픈/3벳/콜/4벳, 숏스택 푸시폴드) 중심.
포스트플랍: 추정 레인지 대비 에쿼티, 팟 오즈, MDF, 보드 텍스처, SPR, 아웃츠/임플라이드 오즈.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import charts
from ..equity import EquityResult, OutsReport
from ..models import Action, ActionRecord, ActionType, PlayerView, Street
from ..positions import players_behind, postflop_order
from ..ranges import HandRange, hand_code
from .board import BoardTexture
from .hand_reader import AGGRESSIVE, OpponentRead
from .position_advisor import PositionCard

_LABEL = {
    ActionType.FOLD: "폴드",
    ActionType.CHECK: "체크",
    ActionType.CALL: "콜",
    ActionType.BET: "벳",
    ActionType.RAISE: "레이즈",
    ActionType.ALL_IN: "올인",
}
RESHOVE_SHORT = HandRange.parse("88+, ATs+, AJo+, KQs", "리쇼브 (≤20BB)")


@dataclass
class Recommendation:
    action: ActionType
    raise_to: int = 0
    size_label: str = ""
    confidence: str = "보통"  # 높음 / 보통 / 낮음
    reasons: list[str] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)

    @property
    def headline(self) -> str:
        text = _LABEL[self.action]
        if self.action in (ActionType.BET, ActionType.RAISE, ActionType.ALL_IN) and self.raise_to:
            text += f" → {self.raise_to:,}"
        if self.size_label:
            text += f" ({self.size_label})"
        return text

    def to_action(self) -> Action:
        if self.action in (ActionType.BET, ActionType.RAISE):
            return Action.raise_to(self.raise_to)
        return Action(self.action)

    def lines(self) -> list[str]:
        out = [f"▶ 추천: {self.headline}   [신뢰도 {self.confidence}]"]
        out += [f"  · {r}" for r in self.reasons]
        out += [f"  ◇ 대안: {a}" for a in self.alternatives]
        return out


@dataclass
class AdvisorInput:
    view: PlayerView
    equity: EquityResult          # 추정 레인지 대비
    equity_random: EquityResult   # 랜덤 핸드 대비
    position: PositionCard
    reads: list[OpponentRead]
    outs: OutsReport | None = None
    texture: BoardTexture | None = None


# --------------------------------------------------------------------------- #
# 공통 헬퍼
# --------------------------------------------------------------------------- #
def _bb(view: PlayerView, amount: float) -> str:
    return f"{amount / view.big_blind:.1f}BB"


def _sized(view: PlayerView, target: float, size_label: str, confidence: str, reasons: list[str],
           alternatives: list[str] | None = None) -> Recommendation:
    """목표 금액을 합법 범위로 맞춘 벳/레이즈 추천 (스택 대부분이면 올인)."""
    legal = view.legal
    alternatives = alternatives or []
    if not legal.can_raise:
        passive = ActionType.CHECK if legal.can_check else ActionType.CALL
        return Recommendation(passive, 0, "", confidence, reasons + ["레이즈 불가 상황(상대 올인 등) → 콜/체크"], alternatives)
    unit = max(1, view.big_blind // 2)
    to = int(round(target / unit) * unit)
    to = max(legal.min_raise_to, min(to, legal.max_raise_to))
    if to >= 0.85 * legal.max_raise_to:
        return Recommendation(
            ActionType.ALL_IN, legal.max_raise_to, "스택 85% 이상 투입 → 올인", confidence, reasons, alternatives
        )
    kind = ActionType.BET if view.current_bet == 0 else ActionType.RAISE
    return Recommendation(kind, to, size_label, confidence, reasons, alternatives)


def _fold_or_check(view: PlayerView, confidence: str, reasons: list[str],
                   alternatives: list[str] | None = None) -> Recommendation:
    kind = ActionType.CHECK if view.legal.can_check else ActionType.FOLD
    return Recommendation(kind, 0, "", confidence, reasons, alternatives or [])


def _equity_line(inp: AdvisorInput) -> str:
    eq, eq_r = inp.equity, inp.equity_random
    known = any(r.range is not None for r in inp.reads)
    if known:
        return (f"추정 레인지 대비 에쿼티 {eq.equity:.1%} (랜덤 상대 가정 {eq_r.equity:.1%}), "
                f"평균 몫 {eq.fair_share:.0%}의 {eq.relative_strength:.2f}배")
    return f"에쿼티 {eq.equity:.1%} (상대 랜덤 가정), 평균 몫 {eq.fair_share:.0%}의 {eq.relative_strength:.2f}배"


def _pot_odds_line(view: PlayerView) -> str:
    call, pot = view.to_call, view.pot
    return f"팟 오즈: 콜 {call:,} / (팟 {pot:,} + 콜 {call:,}) = {view.pot_odds:.1%} → 이 이상 이기면 콜이 이익"


def _is_ip_against(view: PlayerView, other_position: str) -> bool:
    order = postflop_order(view.num_dealt)
    return order.index(view.position) > order.index(other_position)


# --------------------------------------------------------------------------- #
# 프리플랍
# --------------------------------------------------------------------------- #
def _preflop(inp: AdvisorInput) -> Recommendation:
    view = inp.view
    bb = view.big_blind
    code = hand_code(view.hole)
    behind = players_behind(view.position, view.num_dealt)
    eff_bb = view.effective_stack / bb
    pre = [r for r in view.history if r.street == Street.PREFLOP]
    raises = [r for r in pre if r.kind in AGGRESSIVE]
    eq_line = _equity_line(inp)

    if not raises:
        limpers = [r for r in pre if r.kind == ActionType.CALL]
        if eff_bb <= 12:
            push = charts.push_range(behind, eff_bb)
            reasons = [f"유효 스택 {eff_bb:.1f}BB ≤ 12BB → 푸시/폴드 구간 (오픈 후 폴드하면 스택 손실이 큼)",
                       f"{push.label} {push.percent():.0%}: {code} {'포함' if code in push else '제외'}", eq_line]
            if code in push:
                return Recommendation(ActionType.ALL_IN, view.stack + view.street_bet, "푸시", "높음", reasons)
            return _fold_or_check(view, "높음", reasons)

        if not limpers:
            rfi = charts.rfi_range(view.position, behind)
            reasons = [f"{rfi.label} 레인지 {rfi.percent():.1%} (뒤에 {behind}명): {code} {'포함 ✔' if code in rfi else '제외 ✘'}",
                       eq_line]
            if code in rfi:
                size = 3.0 if view.position == "SB" else 2.5
                reasons.append(f"오픈 사이즈 {size}BB: 블라인드에 나쁜 가격을 주면서 폴드 시 손실을 최소화"
                               + (" (SB 는 OOP 라 조금 크게)" if view.position == "SB" else ""))
                return _sized(view, size * bb, f"{size}BB 오픈", "높음", reasons)
            reasons.append("레인지 밖 핸드로 오픈하면 뒤 플레이어의 강한 레인지에 도미네이트/포지션 열세")
            return _fold_or_check(view, "높음", reasons)

        # 림프가 있는 팟
        iso = charts.rfi_range(view.position, min(8, behind + 2))
        oop = view.position in ("SB", "BB")
        reasons = [f"림퍼 {len(limpers)}명 — 림프 레인지는 약하고 넓다 ({charts.LIMP.percent():.0%})", eq_line]
        if code in iso:
            size = 3 + len(limpers) + (1 if oop else 0)
            reasons.append(f"아이솔레이션 레이즈 {size}BB (3BB + 림퍼당 1BB{' + OOP 1BB' if oop else ''}): 헤즈업으로 만들어 이니셔티브 확보")
            return _sized(view, size * bb, f"{size}BB 아이솔레이션", "높음", reasons)
        if view.legal.can_check:
            reasons.append("레이즈할 만큼 강하지 않음 → 무료로 플랍 보기")
            return Recommendation(ActionType.CHECK, reasons=reasons, confidence="높음")
        if code in charts.OVERLIMP and behind <= 3:
            reasons.append("오버림프: 작은 페어·수딧 커넥터는 멀티웨이 저가 팟에서 셋/드로우 임플라이드 오즈가 좋다")
            return Recommendation(ActionType.CALL, reasons=reasons, confidence="낮음",
                                  alternatives=["폴드도 무난 (뒤 블라인드의 스퀴즈 위험)"])
        return _fold_or_check(view, "높음", reasons + ["아이솔레이션 레인지 밖 → 폴드"])

    opener = raises[0]
    opener_behind = players_behind(opener.position, view.num_dealt)
    early = charts.is_early(opener_behind)
    callers = [r for r in pre if r.kind == ActionType.CALL and pre.index(r) > pre.index(opener)]
    ip = _is_ip_against(view, opener.position)
    eq_line = _equity_line(inp)

    if len(raises) == 1:
        three_bet = charts.THREEBET_VS_EARLY if early else charts.THREEBET_VS_LATE
        open_range = charts.rfi_range(opener.position, opener_behind)
        reasons = [f"{opener.position} 오픈 {_bb(view, opener.street_total)} — 예상 레인지 {open_range.label} {open_range.percent():.0%}",
                   eq_line, _pot_odds_line(view)]
        if callers:
            reasons.append(f"콜러 {len(callers)}명 → 스퀴즈 상황: 콜보다 3벳 or 폴드 선호")

        if eff_bb <= 20:
            if code in RESHOVE_SHORT:
                reasons.append(f"유효 스택 {eff_bb:.0f}BB: 3벳 후 폴드할 수 없으므로 리쇼브(올인)로 폴드 에쿼티 극대화")
                return Recommendation(ActionType.ALL_IN, view.stack + view.street_bet, "리쇼브", "높음", reasons)

        if code in three_bet:
            mult = 3 if ip else 4
            target = opener.street_total * (mult + len(callers))
            reasons.append(f"{three_bet.label} {three_bet.percent():.1%}: {code} 포함 — "
                           + ("밸류 3벳" if code in charts.FOURBET or code in ("JJ", "TT", "AQs", "AJs", "KQs", "AQo") else "블러프 3벳 (A 블로커 / 플레이어빌리티)"))
            reasons.append(f"사이즈 {'IP 3배' if ip else 'OOP 4배'}{f' + 콜러당 1배' if callers else ''}: OOP 는 크게 해서 상대의 콜 가격을 높인다")
            return _sized(view, target, f"{mult + len(callers)}배 3벳", "높음", reasons)

        if view.position == "BB":
            defend = charts.BB_DEFEND_VS_EARLY if early else charts.BB_DEFEND_VS_LATE
            reasons.append(f"{defend.label} {defend.percent():.0%}: {code} {'포함' if code in defend else '제외'} — 이미 1BB 를 내 팟 오즈가 가장 좋은 자리")
            if code in defend:
                return Recommendation(ActionType.CALL, reasons=reasons, confidence="보통",
                                      alternatives=["OOP 라 실현 에쿼티가 낮으니 플랍에서 체크-폴드도 자주 나온다는 점을 감안"])
            return _fold_or_check(view, "보통", reasons)

        call_range = charts.SB_CALL if view.position == "SB" else (charts.CALL_VS_EARLY if early else charts.CALL_VS_LATE)
        reasons.append(f"{call_range.label} {call_range.percent():.0%}: {code} {'포함' if code in call_range else '제외'}"
                       + (" — IP 콜은 포지션으로 에쿼티 실현율이 높다" if ip and code in call_range else ""))
        if code in call_range and not (callers and view.position == "SB"):
            return Recommendation(ActionType.CALL, reasons=reasons, confidence="보통")
        return _fold_or_check(view, "높음", reasons + ["콜/3벳 레인지 밖 → 폴드 (도미네이트·포지션 열세)"])

    last = raises[-1]
    hero_opened = opener.seat == view.seat
    reasons = [f"{last.position} 의 {len(raises) + 1}벳 {_bb(view, last.street_total)}", eq_line, _pot_odds_line(view)]
    if len(raises) == 2:
        if code in charts.FOURBET:
            mult = 2.3 if _is_ip_against(view, last.position) else 2.6
            reasons.append(f"{charts.FOURBET.label} 레인지(QQ+, AK, 블러프 A5s): {code} 포함")
            return _sized(view, last.street_total * mult, f"{mult}배 4벳", "높음", reasons)
        call_range = charts.CALL_THREEBET if hero_opened else charts.COLD_CALL_THREEBET
        if code in call_range:
            reasons.append(f"{call_range.label}: {code} 포함 — 셋마이닝·수딧 핸드의 플레이어빌리티")
            return Recommendation(ActionType.CALL, reasons=reasons, confidence="보통")
        return _fold_or_check(view, "높음", reasons + ["3벳 레인지는 강하다 → 레인지 밖 핸드는 폴드"])

    if code in charts.FIVEBET_SHOVE:
        reasons.append("4벳 이상 팟: KK+, AKs 는 올인")
        return Recommendation(ActionType.ALL_IN, view.stack + view.street_bet, "올인", "높음", reasons)
    if code in charts.CALL_FOURBET:
        reasons.append("QQ/AKo 는 4벳 상대로 콜 (상대 레인지 대비 에쿼티 확인)")
        return Recommendation(ActionType.CALL, reasons=reasons, confidence="보통")
    return _fold_or_check(view, "높음", reasons + ["4벳 레인지는 매우 강함(약 2~3%) → 폴드"])


# --------------------------------------------------------------------------- #
# 포스트플랍
# --------------------------------------------------------------------------- #
def _last_aggression(view: PlayerView) -> ActionRecord | None:
    for rec in reversed(view.history):
        if rec.street == view.street and rec.kind in AGGRESSIVE:
            return rec
    return None


def _preflop_raiser(view: PlayerView) -> int | None:
    seat = None
    for rec in view.history:
        if rec.street == Street.PREFLOP and rec.kind in AGGRESSIVE:
            seat = rec.seat
    return seat


_WEAK_OUT_CLASSES = ("원페어", "투페어")


def _strong_outs(outs: OutsReport | None) -> int:
    """트리플 이상을 만드는 아웃츠 (임플라이드 오즈를 기대할 수 있는 '숨은' 강한 핸드)."""
    if not outs:
        return 0
    return sum(len(cards) for name, cards in outs.outs.items() if name not in _WEAK_OUT_CLASSES)


def _discounted_outs(outs: OutsReport | None) -> float:
    """페어 아웃츠는 이겨도 약하고 상대에게도 도움이 될 수 있어 절반만 센다."""
    if not outs:
        return 0.0
    weak = sum(len(cards) for name, cards in outs.outs.items() if name in _WEAK_OUT_CLASSES)
    return _strong_outs(outs) + weak / 2


def _postflop(inp: AdvisorInput) -> Recommendation:
    view, tex, outs = inp.view, inp.texture, inp.outs
    eq = inp.equity.equity
    n = max(1, view.num_opponents)
    rel = inp.equity.relative_strength
    river = view.street == Street.RIVER
    behind_stack = view.effective_stack - view.street_bet
    spr = behind_stack / view.pot if view.pot else 99.0
    out_count = _discounted_outs(outs)
    strong_outs = _strong_outs(outs)

    reasons = [_equity_line(inp)]
    if tex:
        reasons.append(f"보드: {tex.describe(view.board)}")
    if n >= 2:
        reasons.append(f"멀티웨이({n + 1}명): 누군가 강한 핸드를 가졌을 확률↑ → 블러프 줄이고 밸류 기준 상향")

    # ---- 벳이 없는 상황 (체크 가능) ----
    if view.legal.can_check:
        if rel >= 1.25:
            if spr <= 1.5:
                return _sized(view, behind_stack + view.street_bet, "올인", "높음",
                              reasons + [f"SPR {spr:.1f} ≤ 1.5: 스택이 팟 대비 작아 한 번에 올인이 최대 밸류"])
            frac = 0.75 if (tex and tex.wetness >= 0.6) or (river and rel >= 1.6) else 0.5 if (tex and tex.wetness >= 0.3) or river else 0.33
            called_odds = frac / (1 + 2 * frac)
            reasons.append(f"밸류 벳: 평균의 {rel:.2f}배 → 더 약한 핸드에게 콜을 받을 수 있다")
            reasons.append(f"{frac:.0%} 팟 벳이면 상대가 받는 팟 오즈 {called_odds:.0%} → "
                           + ("드로우가 콜하기 불리 (프로텍션)" if frac >= 0.5 else "약한 핸드도 콜하기 쉬운 가격 (드라이 보드 밸류 극대화)"))
            return _sized(view, frac * view.pot, f"팟의 {frac:.0%}", "높음" if rel >= 1.5 else "보통", reasons)

        pfr = _preflop_raiser(view)
        if pfr == view.seat and view.street == Street.FLOP and n == 1 and tex and tex.label == "드라이" and rel >= 0.7:
            reasons.append("프리플랍 레이저 + 드라이 보드: 내 레인지가 강한 핸드(오버페어·탑페어)를 더 많이 가짐 → 레인지 c-bet")
            reasons.append("33% 벳은 상대가 25% 이상만 폴드해도 즉시 이익 (블러프 손익분기 = 벳 / (팟 + 벳))")
            return _sized(view, 0.33 * view.pot, "팟의 33% c-bet", "보통", reasons)

        if not river and out_count >= 8 and n <= 2:
            frac = 0.66 if tex and tex.wetness >= 0.6 else 0.5
            break_even = frac / (1 + frac)
            reasons.append(f"세미블러프: 유효 아웃츠 약 {out_count:.0f}장 (페어 아웃츠는 절반으로 계산) — 콜 받아도 에쿼티 {eq:.0%}")
            reasons.append(f"{frac:.0%} 팟 벳 손익분기 폴드율 {break_even:.0%} — 폴드 에쿼티 + 드로우 에쿼티 두 가지로 이익")
            return _sized(view, frac * view.pot, f"팟의 {frac:.0%} 세미블러프", "보통", reasons,
                          ["체크로 무료 카드 받기 (OOP 이거나 상대가 자주 레이즈하면)"])

        alternatives = []
        if rel >= 0.9:
            reasons.append("쇼다운 밸류가 있지만 벳해서 더 약한 핸드의 콜을 받기 어렵다 → 체크로 팟 컨트롤, 상대 블러프 유도")
        else:
            reasons.append("에쿼티가 평균 이하 → 체크 후 상대 벳에는 팟 오즈로 판단")
            if river and n == 1:
                alternatives.append("블러프 옵션: 75% 벳은 상대가 43% 이상 폴드해야 손익분기 — 상대 레인지에 약한 핸드가 많을 때만")
        return Recommendation(ActionType.CHECK, reasons=reasons, confidence="보통", alternatives=alternatives)

    # ---- 벳을 마주한 상황 ----
    call, pot, po = view.to_call, view.pot, view.pot_odds
    ev_call = eq * (pot + call) - call
    reasons.append(_pot_odds_line(view))
    reasons.append(f"콜 EV ≈ {ev_call:+,.0f} (= 에쿼티 {eq:.2f} × {pot + call:,} − {call:,}, 이후 스트리트 제외)")
    aggr = _last_aggression(view)
    if aggr and aggr.pot_before:
        mdf = aggr.pot_before / (aggr.pot_before + aggr.added)
        reasons.append(f"MDF {mdf:.0%}: 벳 {aggr.added:,} / 팟 {aggr.pot_before:,} — 상대 블러프에 착취당하지 않으려면 레인지의 {mdf:.0%} 이상을 디펜스")

    if rel >= 1.45 and eq >= po + 0.2 and view.legal.can_raise:
        if spr <= 2:
            return _sized(view, behind_stack + view.street_bet, "올인", "높음",
                          reasons + [f"밸류 레이즈 + SPR {spr:.1f}: 올인으로 최대 가치"])
        reasons.append(f"밸류 레이즈: 에쿼티가 필요 승률보다 {eq - po:.0%}p 높고 평균의 {rel:.2f}배 — 상대 벳 레인지 대부분을 이긴다")
        return _sized(view, view.current_bet * 3, "상대 벳의 3배", "높음" if rel >= 1.7 else "보통", reasons,
                      ["콜로 상대의 블러프를 유지 (상대가 매우 공격적이면)"])

    if eq >= po:
        margin = eq - po
        reasons.append(f"에쿼티 {eq:.1%} ≥ 필요 승률 {po:.1%} (+{margin:.1%}p) → 콜이 +EV")
        alternatives = []
        if not river and out_count >= 9 and n == 1 and view.legal.can_raise:
            alternatives.append("세미블러프 레이즈: 강한 드로우는 폴드 에쿼티까지 얻을 수 있다")
        return Recommendation(ActionType.CALL, reasons=reasons, confidence="높음" if margin >= 0.1 else "보통",
                              alternatives=alternatives)

    if not river and outs and strong_outs >= 4:
        hit = strong_outs / outs.unseen
        extra = call / hit - (pot + call)
        remaining = behind_stack - call
        if 0 < extra <= 0.5 * remaining:
            reasons.append(f"직접 팟 오즈는 부족하지만 임플라이드 오즈: 강한 핸드 아웃츠 {strong_outs}장, 다음 카드 적중 {hit:.0%} → "
                           f"맞췄을 때 {extra:,.0f} 이상 더 받아내면 본전 (남은 유효 스택 {remaining:,})")
            return Recommendation(ActionType.CALL, reasons=reasons, confidence="낮음",
                                  alternatives=["상대가 맞은 뒤 잘 안 내주는 타이트한 성향이면 폴드"])

    reasons.append(f"에쿼티 {eq:.1%} < 필요 승률 {po:.1%} → 콜할 때마다 평균 {-ev_call:,.0f} 손실")
    reasons.append("MDF 만큼 디펜스할 핸드는 레인지 상위 몫 — 이 핸드는 하위권이라 폴드 쪽")
    return Recommendation(ActionType.FOLD, reasons=reasons, confidence="높음" if po - eq >= 0.1 else "보통")


def recommend(inp: AdvisorInput) -> Recommendation:
    return _preflop(inp) if inp.view.street == Street.PREFLOP else _postflop(inp)
