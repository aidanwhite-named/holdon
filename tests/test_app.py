from pathlib import Path

import pytest

from app.components import card_html, composition_html, range_grid_html, table_html
from app.session import GameSession
from holdem import Action, BlindLevel, GameSettings, parse_cards
from holdem import charts

APP = Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py"


def make_session(players=4, seed=11, iterations=200):
    settings = GameSettings(
        num_players=players,
        blind_schedule=[BlindLevel(50, 100)],
        level_duration_sec=None,
        seed=seed,
    )
    return GameSession(settings, coach_iterations=iterations)


# --------------------------------------------------------------------------- #
# 세션 컨트롤러
# --------------------------------------------------------------------------- #
def test_session_stops_on_hero_turn_or_hand_end():
    session = make_session()
    session.start_hand()
    assert session.hero_to_act or not session.engine.hand_in_progress


def test_session_plays_many_hands_and_records_summaries():
    session = make_session(players=6, seed=3)
    total = sum(p.stack for p in session.engine.players)
    for _ in range(15):
        if session.game_over:
            break
        session.start_hand()
        while session.engine.hand_in_progress:
            assert session.hero_to_act
            rec = session.report().recommendation
            assert session.act(rec.to_action()) is None
        assert session.summaries[-1].number == session.hand.number
    assert sum(p.stack for p in session.engine.players) == total
    assert len(session.summaries) == session.engine.hands_played
    assert sum(s.hero_net for s in session.summaries) == session.hero.stack - 10_000


def test_illegal_action_returns_message_and_keeps_turn():
    session = make_session()
    session.start_hand()
    while not session.hero_to_act or session.hero_view().legal.can_check:
        if not session.engine.hand_in_progress:
            session.start_hand()
        elif session.hero_to_act:
            session.act(Action.call())
    error = session.act(Action.check())
    assert error and session.hero_to_act


def test_report_is_cached_per_decision():
    session = make_session()
    session.start_hand()
    while not session.hero_to_act:
        session.start_hand()
    assert session.report() is session.report()


def test_session_requires_human_seat():
    with pytest.raises(ValueError):
        GameSession(GameSettings(num_players=3, human_seat=None))


# --------------------------------------------------------------------------- #
# HTML 컴포넌트
# --------------------------------------------------------------------------- #
def test_card_html_colors_and_back():
    assert "ho-red" in card_html(parse_cards("Ah")[0])
    assert ">10<" in card_html(parse_cards("Ts")[0]) and "ho-red" not in card_html(parse_cards("Ts")[0])
    assert "ho-back" in card_html(None)


def test_table_hides_bot_cards_until_showdown():
    session = make_session()
    session.start_hand()
    markup = table_html(session.engine, session.hero.seat)
    assert markup.count('class="ho-seat') == 4
    assert "ho-back" in markup  # 봇 카드는 뒷면
    hero_cards = "".join(card_html(c, "sm") for c in session.hero.hole)
    assert hero_cards in markup


def test_range_grid_and_composition():
    grid = range_grid_html(charts.THREEBET_VS_EARLY, highlight="AKo")
    assert grid.count("<div") == 1 + 169
    assert "ho-me" in grid and grid.count('class="ho-in') == len(charts.THREEBET_VS_EARLY)
    bar = composition_html({"드로우": 0.6, "에어": 0.4})
    assert "60%" in bar and "40%" in bar


# --------------------------------------------------------------------------- #
# Streamlit 앱 (헤드리스)
# --------------------------------------------------------------------------- #
def test_streamlit_app_full_flow():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not at.exception
    assert "Hold'on" in at.title[0].value

    at.sidebar.slider[0].set_value(3)
    at.sidebar.text_input[0].set_value("7")
    at.sidebar.button[0].click().run()  # 새 게임 시작
    assert not at.exception

    for _ in range(40):  # 추천 따르기 / 다음 핸드 반복
        labels = [b.label for b in at.button]
        if "추천 따르기" in labels:
            next(b for b in at.button if b.label == "추천 따르기").click().run()
        elif "다음 핸드 ▶" in labels:
            next(b for b in at.button if b.label == "다음 핸드 ▶").click().run()
        else:
            break
        assert not at.exception, at.exception
    session = at.session_state["session"]
    assert session.engine.hands_played >= 2
