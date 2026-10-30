"""HTML 컴포넌트: 포커 테이블, 카드, 레인지 그리드, 레인지 구성 막대.

모든 함수는 순수 문자열을 반환한다 (Streamlit 의 st.html 로 렌더링, 테스트 용이).
"""

from __future__ import annotations

import html
import math
from typing import Iterable

from treys import Card

from holdem import GameEngine
from holdem.models import ACTION_LABEL_KO, ActionType
from holdem.ranges import HandRange, grid_code

SUITS = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}

CSS = """
.ho-card{display:inline-flex;flex-direction:column;align-items:center;justify-content:center;
  background:#fdfdfb;color:#1b1b1b;border:1px solid #b9b9b9;border-radius:6px;
  box-shadow:0 1px 3px rgba(0,0,0,.35);margin:0 2px;font-family:Georgia,serif;line-height:1}
.ho-card b{font-weight:700}.ho-card i{font-style:normal}
.ho-card.ho-red{color:#c62828}
.ho-card.ho-back{background:repeating-linear-gradient(45deg,#2a4d8f,#2a4d8f 4px,#3a62ad 4px,#3a62ad 8px);border-color:#1c335f}
.ho-sm{width:30px;height:42px;font-size:14px}.ho-sm i{font-size:15px}
.ho-md{width:44px;height:62px;font-size:20px}.ho-md i{font-size:22px}
.ho-table{position:relative;width:100%;aspect-ratio:16/10;min-height:380px;margin:4px 0 8px}
.ho-felt{position:absolute;left:9%;right:9%;top:13%;bottom:13%;border-radius:50%;
  background:radial-gradient(ellipse at center,#2f7d50 0%,#1f5c3a 70%,#174a2e 100%);
  border:10px solid #5b3a1e;box-shadow:inset 0 0 30px rgba(0,0,0,.45),0 4px 14px rgba(0,0,0,.35)}
.ho-center{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);text-align:center;color:#f4f4f4}
.ho-pot{margin-top:6px;font-size:14px;font-weight:600;background:rgba(0,0,0,.35);border-radius:12px;padding:2px 10px;display:inline-block}
.ho-street{font-size:12px;opacity:.85;margin-bottom:4px}
.ho-seat{position:absolute;transform:translate(-50%,-50%);min-width:108px;max-width:140px;padding:5px 8px;
  border-radius:10px;background:rgba(20,24,28,.88);color:#f1f1f1;border:2px solid #3b4148;
  text-align:center;font-size:12px;line-height:1.3;z-index:2}
.ho-seat .ho-name{font-weight:700;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ho-seat .ho-pos{display:inline-block;background:#e0b04a;color:#2a1d00;border-radius:6px;padding:0 5px;font-size:11px;font-weight:700;margin-left:3px}
.ho-seat .ho-stack{font-variant-numeric:tabular-nums;color:#cfe8d5}
.ho-seat .ho-act{font-size:11px;color:#ffd77a;min-height:14px}
.ho-seat.ho-hero{border-color:#4fc3f7}
.ho-seat.ho-turn{border-color:#ffd54f;box-shadow:0 0 0 3px rgba(255,213,79,.35)}
.ho-seat.ho-folded{opacity:.45}
.ho-seat.ho-out{opacity:.3}
.ho-seat.ho-winner{border-color:#ffb300;box-shadow:0 0 14px rgba(255,179,0,.8)}
.ho-tag{display:inline-block;border-radius:5px;padding:0 5px;font-size:10px;font-weight:700;margin-top:2px}
.ho-tag-allin{background:#d84315;color:#fff}.ho-tag-fold{background:#616161;color:#fff}
.ho-bet{position:absolute;transform:translate(-50%,-50%);background:#fff3c4;color:#4a3500;border:2px dashed #c79a00;
  border-radius:12px;padding:1px 7px;font-size:12px;font-weight:700;z-index:1;white-space:nowrap}
.ho-dealer{position:absolute;transform:translate(-50%,-50%);width:22px;height:22px;border-radius:50%;background:#fff;
  color:#111;font-weight:800;font-size:12px;line-height:22px;text-align:center;border:2px solid #999;z-index:1}
.ho-cards{margin:3px 0;min-height:44px}
@media (max-width:640px){
  .ho-table{min-height:330px;aspect-ratio:4/5}
  .ho-seat{min-width:84px;padding:3px 4px;font-size:11px}
  .ho-sm{width:24px;height:34px;font-size:12px}.ho-sm i{font-size:12px}
  .ho-md{width:34px;height:48px;font-size:16px}
}
.ho-grid{display:grid;grid-template-columns:repeat(13,1fr);gap:2px;font-size:10px;max-width:520px}
.ho-grid div{text-align:center;padding:3px 0;border-radius:3px;background:rgba(128,128,128,.16);font-variant-numeric:tabular-nums}
.ho-grid .ho-in{background:#2e8b57;color:#fff}
.ho-grid .ho-part{background:#9ccfa9;color:#103020}
.ho-grid .ho-me{outline:2px solid #f0b400;outline-offset:-1px;font-weight:800}
.ho-sum{display:grid;grid-template-columns:repeat(3,minmax(0,1fr)) minmax(0,2fr);gap:10px;align-items:end;
  border:1px solid rgba(128,128,128,.35);border-radius:10px;padding:10px 14px;margin-bottom:6px}
.ho-sum small{display:block;opacity:.7;font-size:12px}
.ho-sum b{font-size:20px;white-space:nowrap}
.ho-sum .ho-rec b{font-size:18px;white-space:normal}
.ho-stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}
.ho-stats small{display:block;opacity:.7;font-size:13px}
.ho-stats b{font-size:26px;font-weight:600;white-space:nowrap;font-variant-numeric:tabular-nums}
@media (max-width:640px){.ho-stats{grid-template-columns:repeat(2,minmax(0,1fr))}.ho-stats b{font-size:20px}}
.ho-conf-높음{color:#2e9d4f}.ho-conf-보통{color:#e08a00}.ho-conf-낮음{color:#d64545}
@media (max-width:640px){.ho-sum{grid-template-columns:repeat(3,minmax(0,1fr))}.ho-sum .ho-rec{grid-column:1/-1}}
.ho-bar{display:flex;height:16px;border-radius:5px;overflow:hidden;margin:4px 0}
.ho-legend{font-size:12px;line-height:1.6}
.ho-legend span{display:inline-block;width:10px;height:10px;border-radius:2px;margin:0 4px 0 8px;vertical-align:middle}
"""

CATEGORY_COLORS = {
    "강한 메이드(트리플+)": "#8e44ad",
    "투페어": "#c0392b",
    "오버페어/탑페어": "#e67e22",
    "중간·약한 페어": "#d4ac0d",
    "드로우": "#2e86c1",
    "에어": "#95a5a6",
}
_FALLBACK_COLORS = ("#8e44ad", "#c0392b", "#e67e22", "#d4ac0d", "#2e86c1", "#16a085", "#95a5a6")


# --------------------------------------------------------------------------- #
# 카드
# --------------------------------------------------------------------------- #
def card_html(card: int | None, size: str = "md") -> str:
    """카드 한 장. None 이면 뒷면."""
    if card is None:
        return f'<span class="ho-card ho-back ho-{size}"></span>'
    text = Card.int_to_str(card)
    rank = "10" if text[0] == "T" else text[0]
    red = " ho-red" if text[1] in "hd" else ""
    return f'<span class="ho-card ho-{size}{red}"><b>{rank}</b><i>{SUITS[text[1]]}</i></span>'


def cards_html(cards: Iterable[int | None], size: str = "md") -> str:
    return "".join(card_html(c, size) for c in cards)


# --------------------------------------------------------------------------- #
# 테이블
# --------------------------------------------------------------------------- #
def _seat_xy(offset: int, n: int, scale: float = 1.0) -> tuple[float, float]:
    """내 좌석을 맨 아래(90°)에 두고 시계 방향으로 배치 (화면 좌표, %)."""
    angle = math.radians(90 + offset * 360 / n)
    return 50 + 43 * scale * math.cos(angle), 50 + 41 * scale * math.sin(angle)


def _last_action(engine: GameEngine, seat: int) -> str:
    hand = engine.hand
    for rec in reversed(hand.history):
        if rec.seat == seat and rec.street == hand.street:
            label = ACTION_LABEL_KO[rec.kind]
            if rec.kind in (ActionType.BET, ActionType.RAISE):
                label += f" {rec.street_total:,}"
            elif rec.kind == ActionType.CALL:
                label += f" {rec.added:,}"
            return label
    return ""


def table_html(engine: GameEngine, hero_seat: int, reveal_all: bool = False) -> str:
    hand = engine.hand
    n = len(engine.players)
    result = hand.result if hand else None
    showdown = set(result.showdown) if result else set()
    winners = {s for a in result.awards for s in a.winners if not a.uncalled_return} if result else set()
    to_act = hand.to_act if hand else None

    parts = ['<div class="ho-table"><div class="ho-felt"></div>']

    board = list(hand.board) if hand else []
    board_cards = cards_html(board, "md") if board else '<span style="opacity:.6">보드 대기</span>'
    street = (hand.street.label if result is None else "핸드 종료") if hand else ""
    parts.append(
        f'<div class="ho-center"><div class="ho-street">{street}</div>{board_cards}'
        f'<div><span class="ho-pot">팟 {engine.pot:,}</span></div></div>'
    )

    for p in engine.players:
        offset = (p.seat - hero_seat) % n
        x, y = _seat_xy(offset, n)
        classes = ["ho-seat"]
        if p.is_human:
            classes.append("ho-hero")
        if not p.dealt_in:
            classes.append("ho-out")
        elif p.folded:
            classes.append("ho-folded")
        if p.seat == to_act:
            classes.append("ho-turn")
        if p.seat in winners:
            classes.append("ho-winner")

        if p.dealt_in and p.hole and not p.folded:
            face_up = p.is_human or reveal_all or p.seat in showdown
            hole = cards_html(p.hole if face_up else [None, None], "sm")
        elif p.is_human and p.hole:
            hole = cards_html(p.hole, "sm")
        else:
            hole = ""

        tags = ""
        if not p.dealt_in and p.stack == 0:
            tags = '<span class="ho-tag ho-tag-fold">탈락</span>'
        elif p.folded and p.dealt_in:
            tags = '<span class="ho-tag ho-tag-fold">폴드</span>'
        elif p.all_in:
            tags = '<span class="ho-tag ho-tag-allin">올인</span>'

        position = f'<span class="ho-pos">{html.escape(p.position)}</span>' if p.position else ""
        action = html.escape(_last_action(engine, p.seat)) if hand and p.dealt_in else ""
        parts.append(
            f'<div class="{" ".join(classes)}" style="left:{x:.1f}%;top:{y:.1f}%">'
            f'<div class="ho-name">{html.escape(p.name)}{position}</div>'
            f'<div class="ho-cards">{hole}</div>'
            f'<div class="ho-stack">{p.stack:,}</div>'
            f'<div class="ho-act">{action}</div>{tags}</div>'
        )

        if p.street_bet:
            bx, by = _seat_xy(offset, n, 0.58)
            parts.append(f'<div class="ho-bet" style="left:{bx:.1f}%;top:{by:.1f}%">{p.street_bet:,}</div>')
        if hand and p.seat == hand.button:
            dx, dy = _seat_xy(offset + 0.3, n, 0.6)
            parts.append(f'<div class="ho-dealer" style="left:{dx:.1f}%;top:{dy:.1f}%">D</div>')

    parts.append("</div>")
    return "".join(parts)


# --------------------------------------------------------------------------- #
# 레인지 그리드 / 구성 막대
# --------------------------------------------------------------------------- #
def range_grid_html(range_: HandRange, highlight: str | None = None) -> str:
    """13×13 핸드 차트 (오른쪽 위 수딧, 대각선 페어, 왼쪽 아래 오프수트)."""
    cells = []
    for r in range(13):
        for c in range(13):
            code = grid_code(r, c)
            w = range_.weight(code)
            cls = "ho-in" if w >= 0.99 else "ho-part" if w > 0 else ""
            if code == highlight:
                cls += " ho-me"
            cells.append(f'<div class="{cls.strip()}" title="{code}">{code}</div>')
    return f'<div class="ho-grid">{"".join(cells)}</div>'


def stats_html(cells: list[tuple[str, str]]) -> str:
    """라벨/값 스트립 (블라인드 타이머용). 모바일에서는 2열로 접힌다."""
    body = "".join(f"<div><small>{html.escape(k)}</small><b>{html.escape(v)}</b></div>" for k, v in cells)
    return f'<div class="ho-stats">{body}</div>'


def summary_html(position: str, equity: str, required: str, headline: str, confidence: str) -> str:
    """코칭 한눈 요약 스트립."""
    cells = [("포지션", position), ("에쿼티", equity), ("필요 승률", required)]
    body = "".join(f"<div><small>{label}</small><b>{html.escape(value)}</b></div>" for label, value in cells)
    return (
        f'<div class="ho-sum">{body}<div class="ho-rec"><small>코치 추천 · 신뢰도 {html.escape(confidence)}</small>'
        f'<b class="ho-conf-{html.escape(confidence)}">{html.escape(headline)}</b></div></div>'
    )


def composition_html(composition: dict[str, float]) -> str:
    """레인지 구성 비율 → 누적 막대 + 범례."""
    items = [(k, v) for k, v in composition.items() if v >= 0.005]
    colors = {k: CATEGORY_COLORS.get(k, _FALLBACK_COLORS[i % len(_FALLBACK_COLORS)]) for i, (k, _) in enumerate(items)}
    bar = "".join(
        f'<div style="width:{v * 100:.1f}%;background:{colors[k]}" title="{html.escape(k)} {v:.0%}"></div>' for k, v in items
    )
    legend = "".join(f'<span style="background:{colors[k]}"></span>{html.escape(k)} {v:.0%}' for k, v in items)
    return f'<div class="ho-bar">{bar}</div><div class="ho-legend">{legend}</div>'

