import pytest

from holdem import BlindClock, BlindLevel, BotProfile, GameSettings, evaluate, generate_schedule, parse_cards
from holdem.positions import assign_positions
from holdem.pots import build_pots


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_evaluator_names_and_ordering():
    royal = evaluate(parse_cards("AsKs"), parse_cards("QsJsTs2c3d"))
    pair = evaluate(parse_cards("AsAd"), parse_cards("Kc7h2d"))
    assert royal.name_ko == "로열 플러시" and royal.score == 1
    assert pair.name_ko == "원페어"
    assert royal.beats(pair)


def test_parse_cards_formats_and_errors():
    assert parse_cards("Ah Kd") == parse_cards("AhKd") == parse_cards(["Ah", "Kd"])
    with pytest.raises(ValueError):
        parse_cards("AhAh")
    with pytest.raises(ValueError):
        parse_cards("Zz")


def test_side_pot_layers():
    pots = build_pots({0: 100, 1: 300, 2: 300, 3: 50}, folded={3})
    assert [(p.amount, p.eligible) for p in pots] == [(350, [0, 1, 2]), (400, [1, 2])]


def test_positions_by_table_size():
    assert assign_positions([4, 5, 0, 1, 2, 3]) == {4: "BTN", 5: "SB", 0: "BB", 1: "UTG", 2: "HJ", 3: "CO"}
    assert assign_positions([1, 0]) == {1: "BTN/SB", 0: "BB"}


def test_blind_clock_time_based_levels_and_pause():
    clock = FakeClock()
    schedule = [BlindLevel(25, 50), BlindLevel(50, 100), BlindLevel(100, 200)]
    blinds = BlindClock(schedule, level_duration_sec=60, clock=clock)
    blinds.start()
    clock.now = 59
    assert blinds.current_level().big_blind == 50
    assert blinds.seconds_to_next_level() == pytest.approx(1)
    blinds.pause()
    clock.now = 500
    assert blinds.current_level().big_blind == 50
    blinds.resume()
    clock.now = 502
    assert blinds.current_level().big_blind == 100
    clock.now = 10_000
    assert blinds.current_level().big_blind == 200 and blinds.seconds_to_next_level() is None


def test_generate_schedule_is_strictly_increasing():
    schedule = generate_schedule(start_big_blind=100, levels=20, growth=1.3)
    bbs = [lvl.big_blind for lvl in schedule]
    assert bbs == sorted(set(bbs)) and all(lvl.small_blind * 2 == lvl.big_blind for lvl in schedule)


def test_settings_fill_bot_profiles_and_validate():
    settings = GameSettings(num_players=4, bot_profiles=[BotProfile.preset("rock", "Rocky")])
    assert [p.name for p in settings.bot_profiles] == ["Rocky", "Bot2", "Bot3"]
    assert settings.profile_for(1).style == "rock"
    with pytest.raises(ValueError):
        GameSettings(num_players=11)
    with pytest.raises(ValueError):
        BotProfile(tightness=1.5)
