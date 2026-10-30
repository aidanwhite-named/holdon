import random

import pytest

from conftest import RandomLegalBot, make_engine, rig
from holdem import Action, ActionType, parse_cards
from holdem.bots import RangeBot
from holdem.coach import Coach, analyze_board, categorize, draw_type, read_opponents
from holdem.coach.board import AIR, DRAW, MONSTER, TOP_PAIR, WEAK_PAIR
from holdem.config import BotProfile


def P(text):
    return parse_cards(text)


@pytest.fixture
def coach():
    return Coach(iterations=600, rng=random.Random(0), with_threats=False)


def six_max(holes, board="Kh8h2sTc4d"):
    """6인, 버튼 0 → SB 1, BB 2, UTG 3, HJ 4, CO 5."""
    engine = make_engine(6, stacks=[10_000] * 6)
    engine.start_hand()
    rig(engine, holes, board)
    return engine


ALL_HOLES = {0: "AhKd", 1: "7c7d", 2: "QsJs", 3: "AsQh", 4: "Th9h", 5: "2c3d"}


# --------------------------------------------------------------------------- #
# 보드 / 카테고리
# --------------------------------------------------------------------------- #
def test_board_texture():
    assert analyze_board(P("As7d2c")).label == "드라이"
    wet = analyze_board(P("9h8hTc"))
    assert wet.label == "웻" and wet.max_suit == 2 and wet.connected == 3


@pytest.mark.parametrize(
    "hole, board, expected",
    [
        ("AhKh", "2h7h9c", "플러시 드로우"),
        ("8s9d", "6c7hKd", "양방 스트레이트 드로우"),
        ("8h9h", "6h7cKh", "콤보 드로우"),
        ("AsKd", "QcJh2d", "거트샷"),
        ("AsKd", "Ac7h2d", None),
    ],
)
def test_draw_type(hole, board, expected):
    assert draw_type(P(hole), P(board)) == expected


@pytest.mark.parametrize(
    "hole, board, expected",
    [
        ("7c7d", "Kh7h2s", MONSTER),
        ("AsKd", "Kh8h2s", TOP_PAIR),
        ("QsQd", "Jh8h2s", TOP_PAIR),   # 오버페어
        ("9s9d", "Kh8h2s", WEAK_PAIR),
        ("AhQh", "Kh8h2s", DRAW),
        ("AsQd", "Kh8h2c", AIR),
        ("Kd5c", "Kh8h8s", TOP_PAIR),   # 페어 보드 + 내 페어 = 사실상 탑페어
    ],
)
def test_categorize(hole, board, expected):
    assert categorize(P(hole), P(board)) == expected


# --------------------------------------------------------------------------- #
# 핸드 리딩
# --------------------------------------------------------------------------- #
def test_opener_range_tighter_than_limper():
    engine = six_max(ALL_HOLES)
    engine.apply_action(Action.raise_to(250))  # UTG 오픈
    engine.apply_action(Action.call())         # HJ 콜
    reads = {r.position: r for r in read_opponents(engine.view_for(5))}
    assert reads["UTG"].range is not None and reads["HJ"].range is not None
    assert reads["BTN"].range is None           # 아직 액션 없음 → 랜덤
    assert reads["HJ"].combos < reads["UTG"].combos  # 콜드콜 레인지가 더 좁다


def test_three_bet_range_is_much_tighter_than_open():
    engine = six_max(ALL_HOLES)
    engine.apply_action(Action.raise_to(250))  # UTG
    engine.apply_action(Action.fold())         # HJ
    engine.apply_action(Action.raise_to(800))  # CO 3벳
    reads = {r.position: r for r in read_opponents(engine.view_for(0))}
    assert reads["CO"].combos < 60 < reads["UTG"].combos


def test_postflop_bet_shifts_range_toward_value():
    engine = six_max(ALL_HOLES)
    engine.apply_action(Action.raise_to(250))  # UTG
    for _ in range(2):
        engine.apply_action(Action.fold())     # HJ, CO
    engine.apply_action(Action.call())         # BTN
    engine.apply_action(Action.fold())         # SB
    engine.apply_action(Action.fold())         # BB
    before = next(r for r in read_opponents(engine.view_for(3)) if r.position == "BTN")
    engine.apply_action(Action.check())        # UTG 체크
    engine.apply_action(Action.raise_to(500))  # BTN 벳 (팟의 ~90%)
    after = next(r for r in read_opponents(engine.view_for(3)) if r.position == "BTN")
    strong = lambda r: r.composition[MONSTER] + r.composition[TOP_PAIR]  # noqa: E731
    assert after.combos < before.combos
    assert strong(after) > strong(before)


# --------------------------------------------------------------------------- #
# 추천 액션
# --------------------------------------------------------------------------- #
def test_utg_opens_premium_and_folds_trash(coach):
    engine = six_max({**ALL_HOLES, 3: "AsAd"})
    rec = coach.recommend(engine.view_for(3))
    assert rec.action == ActionType.RAISE and rec.raise_to == 250  # 2.5BB

    engine = six_max({**ALL_HOLES, 3: "7s2d"})
    assert coach.recommend(engine.view_for(3)).action == ActionType.FOLD


def test_three_bet_with_aces_vs_open(coach):
    engine = six_max({**ALL_HOLES, 5: "AhAc", 0: "Kd7c"})
    engine.apply_action(Action.raise_to(250))  # UTG
    engine.apply_action(Action.fold())         # HJ
    rec = coach.recommend(engine.view_for(5))  # CO: IP → 3배
    assert rec.action == ActionType.RAISE and rec.raise_to == 750


def test_short_stack_push_fold(coach):
    engine = make_engine(6, stacks=[10_000, 10_000, 10_000, 500, 10_000, 10_000])
    engine.start_hand()
    rig(engine, {**ALL_HOLES, 3: "9s9d"}, "Kh8h2sTc4d")
    rec = coach.recommend(engine.view_for(3))
    assert rec.action == ActionType.ALL_IN and "푸시" in rec.reasons[0] + rec.size_label


def test_value_bet_and_pot_odds_fold():
    coach = Coach(iterations=800, rng=random.Random(1), with_threats=False)
    # 플랍에서 셋: 밸류 벳
    engine = six_max({**ALL_HOLES, 1: "8c8d"}, board="8h7d2sTc4d")
    engine.apply_action(Action.raise_to(250))   # UTG
    for _ in range(3):
        engine.apply_action(Action.fold())      # HJ, CO, BTN
    engine.apply_action(Action.call())          # SB
    engine.apply_action(Action.fold())          # BB
    rec = coach.recommend(engine.view_for(1))   # SB 선행동
    assert rec.action == ActionType.BET
    assert any("밸류" in r for r in rec.reasons)

    # 에어로 큰 벳을 마주하면 폴드 + 팟 오즈 근거
    engine = six_max({**ALL_HOLES, 1: "5c3d"}, board="AhKd9sTc4d")
    engine.apply_action(Action.raise_to(250))
    for _ in range(3):
        engine.apply_action(Action.fold())
    engine.apply_action(Action.call())          # SB
    engine.apply_action(Action.fold())          # BB
    engine.apply_action(Action.check())         # SB 체크
    engine.apply_action(Action.raise_to(500))   # UTG 벳
    rec = coach.recommend(engine.view_for(1))
    assert rec.action == ActionType.FOLD
    assert any("팟 오즈" in r for r in rec.reasons) and any("MDF" in r for r in rec.reasons)


def test_recommendations_are_always_legal():
    """무작위 상황에서 코치 추천이 항상 엔진의 합법 액션으로 변환된다."""
    rng = random.Random(5)
    coach = Coach(iterations=200, rng=rng, with_threats=False)
    for seed in range(6):
        engine = make_engine(rng.randint(2, 9), seed=seed)
        bot = RandomLegalBot(rng)
        for _ in range(6):
            if engine.is_game_over():
                break
            engine.start_hand()
            while engine.hand_in_progress:
                seat = engine.current_player().seat
                if rng.random() < 0.5:
                    engine.apply_action(coach.recommend(engine.view_for(seat)).to_action())
                else:
                    engine.apply_action(bot.decide(engine.legal_actions()))


def test_coach_report_renders_four_cards():
    coach = Coach(iterations=300, rng=random.Random(0))
    engine = six_max(ALL_HOLES)
    engine.apply_action(Action.raise_to(250))
    report = coach.analyze(engine.view_for(4))
    assert list(report.cards()) == ["① 포지션", "② 에쿼티 · 승률", "③ 팟 오즈 · 추천 액션", "④ 핸드 리딩 (상대 레인지 추론)"]
    assert "추천" in report.render()


def test_range_bot_plays_full_hands():
    engine = make_engine(4, seed=3)
    bots = {p.seat: RangeBot(BotProfile.preset(s), random.Random(p.seat))
            for p, s in zip(engine.players, ("tag", "lag", "station", "maniac"))}
    total = sum(p.stack for p in engine.players)
    for _ in range(8):
        if engine.is_game_over():
            break
        engine.start_hand()
        while engine.hand_in_progress:
            seat = engine.current_player().seat
            engine.apply_action(bots[seat].decide(engine.view_for(seat)))
    assert sum(p.stack for p in engine.players) == total
