import random

import pytest

from conftest import RandomLegalBot, make_engine, rig
from holdem import Action, BlindLevel, IllegalActionError, Street


def act(engine, action):
    return engine.apply_action(action)


def test_chip_conservation_fuzz():
    """다양한 인원/스택/앤티로 무작위 액션을 대량 실행해도 칩 총량이 보존된다."""
    for seed in range(40):
        rng = random.Random(seed)
        n = rng.randint(2, 10)
        stacks = [rng.randint(1, 60) * 100 for _ in range(n)]
        schedule = [BlindLevel(50, 100, 0), BlindLevel(100, 200, 25), BlindLevel(200, 400, 50)]
        engine = make_engine(n, stacks=stacks, schedule=schedule, hands_per_level=5, seed=seed)
        bot = RandomLegalBot(rng)
        total = sum(stacks)
        for _ in range(80):
            if engine.is_game_over():
                break
            engine.start_hand()
            steps = 0
            while engine.hand_in_progress:
                act(engine, bot.decide(engine.legal_actions()))
                steps += 1
                assert steps < 500, "베팅 라운드가 끝나지 않음"
            assert sum(p.stack for p in engine.players) == total
            assert all(p.stack >= 0 for p in engine.players)
            assert sum(engine.hand.result.net.values()) == 0
            assert len(engine.hand.board) in (0, 3, 4, 5)


def test_preflop_order_and_blinds_three_handed(engine3):
    hand = engine3.start_hand()
    assert (hand.button, hand.sb_seat, hand.bb_seat) == (0, 1, 2)
    assert [p.position for p in engine3.players] == ["BTN", "SB", "BB"]
    assert engine3.players[1].street_bet == 50 and engine3.players[2].street_bet == 100
    assert engine3.current_player().seat == 0  # BB 다음(=버튼)이 프리플랍 선행동


def test_heads_up_button_posts_small_blind_and_acts_first_preflop():
    engine = make_engine(2)
    hand = engine.start_hand()
    assert hand.sb_seat == hand.button == 0
    assert engine.current_player().seat == 0
    act(engine, Action.call())
    assert engine.current_player().seat == 1  # BB 옵션
    act(engine, Action.check())
    assert hand.street == Street.FLOP
    assert engine.current_player().seat == 1  # 포스트플랍은 BB 선행동


def test_big_blind_gets_option_after_limps(engine3):
    engine3.start_hand()
    act(engine3, Action.call())
    act(engine3, Action.call())
    assert engine3.current_player().seat == 2
    assert engine3.legal_actions().can_check and engine3.legal_actions().can_raise


def test_everyone_folds_to_big_blind(engine3):
    engine3.start_hand()
    act(engine3, Action.fold())
    act(engine3, Action.fold())
    result = engine3.hand.result
    assert result is not None and not result.went_to_showdown
    assert result.net == {0: 0, 1: -50, 2: 50}


def test_min_raise_is_enforced(engine3):
    engine3.start_hand()
    legal = engine3.legal_actions()
    assert legal.min_raise_to == 200
    with pytest.raises(IllegalActionError):
        act(engine3, Action.raise_to(150))
    act(engine3, Action.raise_to(350))  # 레이즈 크기 250
    assert engine3.legal_actions().min_raise_to == 600  # 350 + 250


def test_check_not_allowed_when_facing_bet(engine3):
    engine3.start_hand()
    with pytest.raises(IllegalActionError):
        act(engine3, Action.check())


def test_incomplete_all_in_raise_does_not_reopen_action():
    engine = make_engine(3, stacks=[10_000, 450, 10_000])
    engine.start_hand()
    act(engine, Action.raise_to(300))  # BTN 레이즈 (+200)
    act(engine, Action.all_in())       # SB 450 올인 (+150, 불완전 레이즈)
    bb_legal = engine.legal_actions()
    assert engine.current_player().seat == 2 and bb_legal.can_raise  # BB는 아직 행동 전 → 레이즈 가능
    act(engine, Action.call())
    btn_legal = engine.legal_actions()
    assert engine.current_player().seat == 0
    assert not btn_legal.can_raise and btn_legal.call_amount == 150


def test_side_pots_awarded_to_correct_winners():
    engine = make_engine(3, stacks=[1_000, 3_000, 5_000])
    engine.start_hand()
    rig(engine, {0: "AsAh", 1: "KsKh", 2: "QsQh"}, "2c7d9hJc3s")
    act(engine, Action.all_in())  # BTN 1,000
    act(engine, Action.all_in())  # SB 3,000
    act(engine, Action.call())    # BB 콜 3,000
    result = engine.hand.result
    assert result.went_to_showdown
    main, side = result.awards
    assert (main.amount, main.winners) == (3_000, [0])
    assert (side.amount, side.winners) == (4_000, [1])
    assert [p.stack for p in engine.players] == [3_000, 4_000, 2_000]


def test_uncalled_bet_is_returned():
    engine = make_engine(3, stacks=[5_000, 500, 5_000])
    engine.start_hand()
    rig(engine, {0: "2c7d", 1: "AsAh", 2: "3c8d"}, "KcQd9h4s3s")
    act(engine, Action.all_in())  # BTN 5,000 올인
    act(engine, Action.all_in())  # SB 500 올인 콜
    act(engine, Action.fold())    # BB 폴드 → BTN 의 초과분 4,500 은 콜 되지 않음
    result = engine.hand.result
    assert result.awards[-1].uncalled_return and result.awards[-1].amount == 4_500
    assert [p.stack for p in engine.players] == [4_500, 1_100, 4_900]


def test_cannot_raise_when_nobody_can_respond():
    engine = make_engine(2, stacks=[500, 5_000])
    engine.start_hand()
    act(engine, Action.all_in())
    legal = engine.legal_actions()
    assert not legal.can_raise and legal.call_amount == 400
    act(engine, Action.all_in())  # 레이즈 불가 → 올인은 콜로 처리
    assert engine.players[1].total_bet == 500


def test_split_pot_with_odd_chip_goes_left_of_button():
    engine = make_engine(3, stacks=[1_000, 1_000, 1_000], blinds=(25, 50, 0))
    engine.start_hand()
    rig(engine, {0: "2c3d", 1: "2d3c", 2: "4h5h"}, "AsKsQsJsTs")
    act(engine, Action.call())  # BTN 50
    act(engine, Action.fold())  # SB 25 폴드
    act(engine, Action.check())  # BB
    while engine.hand_in_progress:
        act(engine, Action.check())
    award = engine.hand.result.awards[0]
    assert award.amount == 125 and award.winners == [2, 0]  # 버튼 왼쪽(BB)부터
    assert engine.players[2].stack == 1_000 + 13 and engine.players[0].stack == 1_000 + 12


def test_all_in_preflop_runs_out_board():
    engine = make_engine(2)
    hand = engine.start_hand()
    act(engine, Action.all_in())
    act(engine, Action.call())
    assert len(hand.board) == 5 and hand.result.went_to_showdown


def test_blind_level_increases_by_hand_count_and_busted_players_are_skipped():
    schedule = [BlindLevel(50, 100), BlindLevel(100, 200)]
    engine = make_engine(3, stacks=[1_000, 0, 1_000], schedule=schedule, hands_per_level=1)
    hand = engine.start_hand()
    assert not engine.players[1].dealt_in and hand.level.big_blind == 100
    act(engine, Action.fold())
    assert engine.start_hand().level.big_blind == 200


def test_view_hides_other_players_and_reports_pot_odds(engine3):
    engine3.start_hand()
    view = engine3.view_for(0)
    assert view.hole == tuple(engine3.players[0].hole)
    assert view.pot == 150 and view.to_call == 100
    assert view.pot_odds == pytest.approx(100 / 250)
