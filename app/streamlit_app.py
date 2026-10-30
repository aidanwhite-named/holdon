"""Hold'on — 텍사스 홀덤 학습 시뮬레이터 (Streamlit UI).

실행:  streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from app.components import (  # noqa: E402
    CSS,
    composition_html,
    range_grid_html,
    stats_html,
    summary_html,
    table_html,
)
from app.session import GameSession  # noqa: E402
from holdem import Action, BotProfile, GameSettings, evaluate  # noqa: E402
from holdem import charts  # noqa: E402
from holdem.coach import CoachReport, draw_type  # noqa: E402
from holdem.config import BOT_PRESETS, MAX_PLAYERS, MIN_PLAYERS, PRESET_DESCRIPTIONS  # noqa: E402
from holdem.models import ActionType  # noqa: E402

st.set_page_config(page_title="Hold'on 홀덤 트레이너", page_icon="♠", layout="wide")
st.html(f"<style>{CSS}</style>")

PRESET_NAMES = list(BOT_PRESETS)
COACH_TABS = ["① 포지션", "② 에쿼티", "③ 추천 근거", "④ 핸드 리딩"]
CONFIDENCE_COLOR = {"높음": "green", "보통": "orange", "낮음": "red"}


def get_session() -> GameSession | None:
    return st.session_state.get("session")


# --------------------------------------------------------------------------- #
# 콜백
# --------------------------------------------------------------------------- #
def do_action(action: Action) -> None:
    st.session_state.error = get_session().act(action)


def next_hand() -> None:
    session = get_session()
    if not session.engine.hand_in_progress and not session.game_over:
        session.start_hand()
    st.session_state.error = None


def set_amount(key: str, value: int) -> None:
    st.session_state[key] = value


def toggle_clock() -> None:
    clock = get_session().engine.blind_clock
    clock.resume() if clock.paused else clock.pause()


# --------------------------------------------------------------------------- #
# 사이드바: 게임 설정
# --------------------------------------------------------------------------- #
def sidebar() -> None:
    with st.sidebar:
        st.header("♠ 게임 설정")
        with st.form("settings"):
            players = st.slider("인원 (나 포함)", MIN_PLAYERS, MAX_PLAYERS, 6)
            stack = st.number_input("시작 바이인 (칩)", 1_000, 1_000_000, 10_000, step=1_000)
            level_minutes = st.number_input("블라인드 레벨업 주기 (분, 0 = 끔)", 0.0, 120.0, 10.0, step=1.0)
            hands_per_level = st.number_input("N핸드마다 레벨업 (0 = 끔)", 0, 500, 0)
            bot_engine = st.radio(
                "봇 엔진", ["range", "rule"], horizontal=True,
                format_func=lambda v: "코칭 기반 (2단계)" if v == "range" else "에쿼티 기반 (1단계)",
            )
            iterations = st.select_slider("코치 시뮬레이션 횟수", [500, 1000, 1500, 2500, 4000], 1500)
            seed = st.text_input("난수 시드 (비우면 랜덤)", "")
            with st.expander("봇 스타일 (Bot1부터 인원만큼 사용)"):
                styles = [
                    st.selectbox(
                        f"Bot{i + 1}", PRESET_NAMES, index=i % len(PRESET_NAMES), key=f"style_{i}",
                        format_func=lambda s: f"{s} · {PRESET_DESCRIPTIONS[s]}",
                    )
                    for i in range(MAX_PLAYERS - 1)
                ]
            submitted = st.form_submit_button("새 게임 시작", type="primary", width="stretch")

        if submitted:
            try:
                settings = GameSettings(
                    num_players=players,
                    starting_stack=int(stack),
                    level_duration_sec=level_minutes * 60 if level_minutes > 0 else None,
                    hands_per_level=int(hands_per_level) or None,
                    bot_profiles=[BotProfile.preset(s, f"Bot{i + 1}") for i, s in enumerate(styles[: players - 1])],
                    seed=int(seed) if seed.strip() else None,
                )
            except ValueError as e:
                st.error(f"설정 오류: {e}")
            else:
                session = GameSession(settings, bot_engine, iterations)
                session.start_hand()
                st.session_state.session = session
                st.session_state.error = None

        st.divider()
        st.toggle("코칭 카드 표시", value=True, key="show_coach", help="끄면 코칭 없이 실전처럼 연습")
        st.caption("단축키: F 폴드 · K 체크/콜 · B 벳/레이즈 · A 올인 · Y 추천 따르기 · N 다음 핸드")


# --------------------------------------------------------------------------- #
# 상단: 블라인드 타이머 (1초마다 이 영역만 갱신)
# --------------------------------------------------------------------------- #
@st.fragment(run_every=1)
def blind_timer() -> None:
    session = get_session()
    engine, hand = session.engine, session.hand
    clock = engine.blind_clock
    idx = clock.level_index(engine.hands_played)
    remaining = clock.seconds_to_next_level()
    next_level = clock.schedule[idx + 1] if idx + 1 < len(clock.schedule) else None

    timer = "—" if remaining is None else f"{int(remaining // 60):02d}:{int(remaining % 60):02d}"
    left, right = st.columns([6, 1], vertical_alignment="center")
    with left:
        st.html(stats_html([
            ("핸드", f"#{hand.number}"),
            (f"레벨 {hand.level_index + 1} 블라인드", str(hand.level)),
            ("다음 레벨까지", timer + (" ⏸" if clock.paused else "")),
            ("다음 블라인드", str(next_level) if next_level else "마지막 레벨"),
        ]))
    right.button("재개" if clock.paused else "일시정지", on_click=toggle_clock, width="stretch")
    if idx > hand.level_index:
        st.info(f"블라인드가 {clock.schedule[idx]} 로 올라갑니다 — 다음 핸드부터 적용")


# --------------------------------------------------------------------------- #
# 액션 패널
# --------------------------------------------------------------------------- #
def action_panel(session: GameSession, report: CoachReport | None) -> None:
    view = session.hero_view()
    legal = view.legal
    rec = report.recommendation if report else None
    show_coach = st.session_state.get("show_coach", True)

    if rec and show_coach:
        st.markdown(f"**코치 추천:** :{CONFIDENCE_COLOR[rec.confidence]}[{rec.headline}]  ·  신뢰도 {rec.confidence}")

    cols = st.columns(4)
    cols[0].button("폴드", on_click=do_action, args=(Action.fold(),), width="stretch", shortcut="F")
    call_label = "체크" if legal.can_check else f"콜 {legal.call_amount:,}"
    cols[1].button(call_label, on_click=do_action, args=(Action.call(),), width="stretch", shortcut="K")
    cols[2].button(f"올인 {view.stack + view.street_bet:,}", on_click=do_action, args=(Action.all_in(),),
                   width="stretch", shortcut="A")
    cols[3].button("추천 따르기", on_click=do_action, args=(rec.to_action(),) if rec else (Action.check(),),
                   type="primary", disabled=rec is None or not show_coach, width="stretch", shortcut="Y")

    if not legal.can_raise or legal.min_raise_to >= legal.max_raise_to:
        return
    key = f"amount_{session.decision_key()}"
    unit = max(1, view.big_blind // 2)

    def clamp(value: float) -> int:
        value = int(round(value / unit) * unit)
        return max(legal.min_raise_to, min(value, legal.max_raise_to))

    if key not in st.session_state:
        default = rec.raise_to if rec and rec.action in (ActionType.BET, ActionType.RAISE) else legal.min_raise_to
        st.session_state[key] = clamp(default)

    base = view.pot + legal.to_call
    if view.street.name == "PREFLOP":
        fractions = []
        presets = [("최소", legal.min_raise_to), ("2.5BB", clamp(2.5 * view.big_blind)), ("3BB", clamp(3 * view.big_blind))]
    else:
        fractions = [("33%", 0.33), ("50%", 0.5), ("75%", 0.75)]
        presets = [("최소", legal.min_raise_to)]
    presets += [(label, clamp(view.current_bet + frac * base)) for label, frac in fractions + [("팟", 1.0)]]
    preset_cols = st.columns(len(presets))
    for col, (label, value) in zip(preset_cols, presets):
        col.button(label, key=f"{key}_{label}", on_click=set_amount, args=(key, value), width="stretch",
                   help=f"{value:,} 까지")

    verb = "벳" if view.current_bet == 0 else "레이즈"
    amount = st.slider(f"{verb} 금액 (이번 스트리트 총액)", legal.min_raise_to, legal.max_raise_to, key=key, step=unit)
    pot_fraction = (amount - view.current_bet) / base if base else 0
    st.button(f"{verb} → {amount:,}  (팟의 {pot_fraction:.0%})", on_click=do_action, args=(Action.raise_to(amount),),
              width="stretch", shortcut="B")


def hand_over_panel(session: GameSession) -> None:
    summary = session.summaries[-1]
    net = summary.hero_net
    message = f"핸드 #{summary.number} 종료 — 내 손익 {net:+,}"
    (st.success if net > 0 else st.error if net < 0 else st.info)(message)
    for entry in session.hand_log():
        if entry.kind == "result":
            st.markdown(f"- {entry.text}")
    if session.game_over:
        hero = session.hero
        st.warning("게임 종료! " + ("우승했습니다 🎉" if hero.stack > 0 else "칩을 모두 잃었습니다."))
        ranking = sorted(session.engine.players, key=lambda p: -p.stack)
        st.dataframe(
            [{"순위": i + 1, "이름": p.name, "칩": p.stack} for i, p in enumerate(ranking)],
            hide_index=True, width="stretch",
        )
        st.caption("사이드바에서 새 게임을 시작하세요.")
    else:
        st.button("다음 핸드 ▶", on_click=next_hand, type="primary", width="stretch", shortcut="N")


def hand_log(session: GameSession) -> None:
    with st.container(height=230, border=True, autoscroll=True):
        for entry in session.hand_log():
            if entry.kind == "hand":
                st.markdown(f"**{entry.text}**")
            elif entry.kind == "street":
                st.markdown(f"**── {entry.text}**")
            elif entry.kind == "result":
                st.markdown(f":orange[★ {entry.text}]")
            else:
                hero = entry.seat == session.hero.seat
                st.markdown(f":blue[{entry.text}]" if hero else entry.text)


# --------------------------------------------------------------------------- #
# 코칭 카드 4종
# --------------------------------------------------------------------------- #
CHART_OPTIONS = {
    "내 포지션 기본 레인지": None,
    "3벳 (vs 얼리 오픈)": charts.THREEBET_VS_EARLY,
    "3벳 (vs 레이트 오픈)": charts.THREEBET_VS_LATE,
    "콜 (vs 얼리 오픈)": charts.CALL_VS_EARLY,
    "콜 (vs 레이트 오픈)": charts.CALL_VS_LATE,
    "BB 디펜스 (vs 레이트)": charts.BB_DEFEND_VS_LATE,
    "4벳": charts.FOURBET,
}


def coach_summary(report: CoachReport) -> None:
    """항상 보이는 한눈 요약: 포지션 · 에쿼티 · 필요 승률 · 추천."""
    view, rec, card = report.view, report.recommendation, report.position
    st.html(summary_html(
        position=f"{card.position} · {'IP' if card.in_position else 'OOP'}",
        equity=f"{report.equity.equity:.1%}",
        required=f"{view.pot_odds:.1%}" if view.to_call else "—",
        headline=rec.headline,
        confidence=rec.confidence,
    ))


def position_card(report: CoachReport) -> None:
    card = report.position
    with st.container(border=True):
        st.markdown(f"#### ① 포지션 — {card.position}")
        st.markdown(
            f"**{card.guide.group}** · 뒤에 {card.players_behind}명 · "
            + ("포스트플랍 **IP** (마지막 행동)" if card.in_position else "포스트플랍 **OOP** (먼저 행동)")
        )
        st.caption(card.guide.summary)
        for tip in card.guide.tips:
            st.markdown(f"- {tip}")
        choice = st.selectbox("레인지 차트", list(CHART_OPTIONS), key="chart_choice")
        chart = CHART_OPTIONS[choice] or card.open_range
        inside = card.hand in chart
        st.markdown(f"{chart.label} **{chart.percent():.1%}** — 내 핸드 **{card.hand}** {'✅ 포함' if inside else '❌ 제외'}")
        st.html(range_grid_html(chart, highlight=card.hand))
        st.caption("오른쪽 위 = 수딧 · 대각선 = 페어 · 왼쪽 아래 = 오프수트 · 노란 테두리 = 내 핸드")


def equity_card(report: CoachReport) -> None:
    view = report.view
    with st.container(border=True):
        st.markdown("#### ② 에쿼티 · 승률")
        known = any(r.range is not None for r in report.reads)
        cols = st.columns(3)
        cols[0].metric("추정 레인지 대비" if known else "에쿼티", f"{report.equity.equity:.1%}",
                       help="상대 행동으로 추정한 레인지를 상대로 몬테카를로 시뮬레이션")
        cols[1].metric("랜덤 핸드 대비", f"{report.equity_random.equity:.1%}")
        cols[2].metric("필요 승률", f"{view.pot_odds:.1%}" if view.to_call else "—",
                       help="팟 오즈 = 콜 금액 / (팟 + 콜 금액)")
        st.progress(min(1.0, report.equity.equity), text=f"평균 몫 {report.equity.fair_share:.0%} 의 {report.equity.relative_strength:.2f}배")
        if view.board:
            draw = draw_type(view.hole, view.board)
            st.markdown(f"현재 족보: **{evaluate(view.hole, view.board).name_ko}**" + (f" + **{draw}**" if draw else ""))
        if report.outs:
            st.markdown(report.outs.summary())
        if report.threats:
            with st.expander(f"나를 이기는 상대 조합 {report.threats.beat_me:,}개 ({report.threats.beat_ratio:.1%})"):
                st.text(report.threats.summary())


def recommendation_card(report: CoachReport) -> None:
    rec = report.recommendation
    with st.container(border=True):
        st.markdown("#### ③ 팟 오즈 · 추천 액션")
        st.markdown(f"### :{CONFIDENCE_COLOR[rec.confidence]}[{rec.headline}]")
        st.caption(f"신뢰도 {rec.confidence}")
        for reason in rec.reasons:
            st.markdown(f"- {reason}")
        for alt in rec.alternatives:
            st.markdown(f"- *대안:* {alt}")


def reading_card(report: CoachReport) -> None:
    with st.container(border=True):
        st.markdown("#### ④ 핸드 리딩 — 상대 레인지 추론")
        if not report.reads:
            st.caption("남은 상대 없음")
        for read in report.reads:
            title = f"{read.name} ({read.position})"
            if read.range is None:
                st.markdown(f"**{title}** — 아직 자발적 액션 없음 → 랜덤 핸드로 가정")
                continue
            with st.expander(f"{title} · 약 {read.combos:.0f}콤보 ({read.combos / 1326:.0%})", expanded=True):
                st.markdown(f"액션: {read.line}")
                st.caption(f"기준 레인지: {read.preflop_label}")
                if read.composition:
                    st.html(composition_html(read.composition))
                for tip in read.guidance:
                    st.markdown(f"- {tip}")


def history_card(session: GameSession) -> None:
    with st.container(border=True):
        st.markdown("#### 핸드 기록")
        if not session.summaries:
            st.caption("아직 끝난 핸드가 없습니다.")
            return
        cumulative, total = [], 0
        for s in session.summaries:
            total += s.hero_net
            cumulative.append(total)
        if len(cumulative) > 1:
            st.line_chart({"누적 손익": cumulative}, height=160)
        st.dataframe(
            [
                {"#": s.number, "포지션": s.hero_position, "내 핸드": s.hero_hole, "보드": s.board,
                 "손익": s.hero_net, "승자": s.winners}
                for s in reversed(session.summaries)
            ],
            hide_index=True, width="stretch", height=220,
        )
        last = session.summaries[-1]
        if last.showdown:
            st.markdown("**마지막 쇼다운**")
            for name, cards, rank in last.showdown:
                st.markdown(f"- {name}: {cards} — {rank}")


# --------------------------------------------------------------------------- #
# 메인
# --------------------------------------------------------------------------- #
def welcome() -> None:
    st.title("♠ Hold'on — 텍사스 홀덤 트레이너")
    st.markdown(
        "봇과 실제로 플레이하면서 **포지션 · 에쿼티 · 팟 오즈 · 상대 레인지**를 실시간으로 배우는 학습용 시뮬레이터입니다.\n\n"
        "1. 왼쪽 사이드바에서 인원·바이인·블라인드 구조·봇 스타일을 정하고 **새 게임 시작**을 누르세요.\n"
        "2. 내 차례가 되면 오른쪽에 도우미 카드 4종이 나타납니다: ① 포지션 ② 에쿼티 ③ 추천 액션 ④ 핸드 리딩.\n"
        "3. 추천과 다르게 플레이해 보고, 핸드가 끝나면 기록에서 손익을 복기하세요."
    )


def main() -> None:
    sidebar()
    session = get_session()
    if session is None or session.hand is None:
        welcome()
        return

    blind_timer()
    if st.session_state.get("error"):
        st.error(st.session_state.error)

    report = session.report()
    left, right = st.columns([1.15, 1], gap="large")
    with left:
        st.html(table_html(session.engine, session.hero.seat))
        if session.hero_to_act:
            action_panel(session, report)
        elif session.engine.hand_in_progress:
            st.info("내가 올인/폴드한 상태입니다 — 핸드가 자동 진행됩니다.")
        else:
            hand_over_panel(session)
        hand_log(session)

    with right:
        if report and st.session_state.get("show_coach", True):
            coach_summary(report)
            tabs = st.tabs(COACH_TABS, default=COACH_TABS[2])
            for tab, render in zip(tabs, (position_card, equity_card, recommendation_card, reading_card)):
                with tab:
                    render(report)
        else:
            history_card(session)


main()
