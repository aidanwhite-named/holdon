import random

import pytest

from holdem import analyze_threats, find_outs, monte_carlo_equity, parse_cards, pot_odds
from holdem.cards import FULL_DECK


def P(text):
    return parse_cards(text)


def test_aces_vs_random_hand_about_85_percent():
    result = monte_carlo_equity(P("AhAd"), (), 1, 6000, random.Random(0))
    assert result.equity == pytest.approx(0.852, abs=0.025)


def test_aces_vs_kings_range_about_82_percent():
    kings = [tuple(P(c)) for c in ("KsKc", "KsKh", "KsKd", "KcKh", "KcKd", "KhKd")]
    result = monte_carlo_equity(P("AhAd"), (), 1, 4000, random.Random(0), opponent_ranges=[kings])
    assert result.equity == pytest.approx(0.82, abs=0.03)


def test_more_opponents_lowers_equity():
    hole = P("AhAd")
    one = monte_carlo_equity(hole, (), 1, 2000, random.Random(1)).equity
    four = monte_carlo_equity(hole, (), 4, 2000, random.Random(1)).equity
    assert four < one - 0.2


def test_river_nuts_always_win():
    result = monte_carlo_equity(P("AsKs"), P("QsJsTs2c3d"), 3, 300, random.Random(0))
    assert result.equity == 1.0 and result.win == 1.0


def test_board_royal_flush_always_ties():
    result = monte_carlo_equity(P("2c3d"), P("AsKsQsJsTs"), 2, 200, random.Random(0))
    assert result.tie == 1.0 and result.equity == pytest.approx(1 / 3)


def test_flush_draw_with_overcards_outs():
    report = find_outs(P("AhKh"), P("2h7h9c"))
    assert len(report.outs["플러시"]) == 9
    assert len(report.outs["원페어"]) == 6
    assert report.count == 15 and report.cards_to_come == 2
    assert report.by_river_prob == pytest.approx(1 - (32 * 31) / (47 * 46))


def test_open_ended_straight_draw_has_8_straight_outs():
    report = find_outs(P("8s9d"), P("6c7hKd"))
    assert len(report.outs["스트레이트"]) == 8


def test_board_pairing_two_pair_is_not_an_out():
    report = find_outs(P("9s9d"), P("Ac7h2d"))  # 7·2 가 보드를 페어로 만들어도 진짜 개선이 아님
    assert "투페어" not in report.outs
    assert len(report.outs["트리플"]) == 2


def test_pair_on_paired_board_is_labelled_one_pair():
    report = find_outs(P("Qh3c"), P("AdAs5d"))
    assert "투페어" not in report.outs
    assert len(report.outs["원페어"]) == 6


def test_threat_analysis_counts_all_combos():
    report = analyze_threats(P("AsKd"), P("Ah7c2d"))
    assert report.total_combos == 1081  # C(47, 2)
    assert report.beat_by_class == {"투페어": 21, "트리플": 7}
    assert report.nut_groups[0].hand_name == "트리플"


def test_nuts_detected():
    report = analyze_threats(P("AsKs"), P("QsJsTs2c3d"))
    assert report.i_have_nuts


def test_pot_odds():
    assert pot_odds(50, 100) == pytest.approx(1 / 3)
    assert pot_odds(0, 100) == 0.0


def test_invalid_inputs_raise():
    with pytest.raises(ValueError):
        monte_carlo_equity(P("AhAh"[:2]) + P("Kd"), P("Kd2c3c"), 1, 10)
    with pytest.raises(ValueError):
        find_outs(P("AhKh"), ())


def test_deck_has_52_unique_cards():
    assert len(set(FULL_DECK)) == 52
