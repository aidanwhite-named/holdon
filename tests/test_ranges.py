import random

import pytest

from holdem import charts, monte_carlo_equity, parse_cards
from holdem.positions import players_behind, postflop_order, preflop_order
from holdem.ranges import ALL_CODES, HandRange, WeightedRange, code_combos, hand_code, parse_range


def test_all_codes_cover_1326_combos():
    assert len(ALL_CODES) == 169
    assert sum(len(code_combos(c)) for c in ALL_CODES) == 1326


@pytest.mark.parametrize(
    "text, expected",
    [
        ("TT+", {"TT", "JJ", "QQ", "KK", "AA"}),
        ("A2s+", {f"A{k}s" for k in "KQJT98765432"}),
        ("KTo+", {"KTo", "KJo", "KQo"}),
        ("A5s-A2s", {"A5s", "A4s", "A3s", "A2s"}),
        ("99-77", {"99", "88", "77"}),
        ("AK", {"AKs", "AKo"}),
        ("ka", {"AKs", "AKo"}),
    ],
)
def test_range_notation(text, expected):
    assert set(parse_range(text)) == expected


def test_range_weights_and_percent():
    r = HandRange.parse("AA, KK:0.5")
    assert r.weight("KK") == 0.5
    assert r.combo_count() == pytest.approx(6 + 3)
    assert HandRange.any_two().percent() == pytest.approx(1.0)


def test_invalid_notation_raises():
    with pytest.raises(ValueError):
        parse_range("AAs")
    with pytest.raises(ValueError):
        parse_range("A5s-K2s")


def test_hand_code():
    assert hand_code(parse_cards("Kd As")) == "AKo"
    assert hand_code(parse_cards("9h Th")) == "T9s"
    assert hand_code(parse_cards("7c 7d")) == "77"


def test_card_removal_in_combos():
    combos = HandRange.parse("AA").combos(dead=parse_cards("As"))
    assert len(combos) == 3


def test_weighted_range_sampling_respects_weights_and_used_cards():
    aa = [tuple(c) for c in (parse_cards("AsAh"), parse_cards("AdAc"))]
    wr = WeightedRange(aa, [9.0, 1.0])
    rng = random.Random(0)
    picks = [tuple(wr.sample(rng, set())) for _ in range(2000)]
    assert 0.85 < picks.count(aa[0]) / len(picks) < 0.95
    assert wr.sample(rng, set(parse_cards("As"))) == list(aa[1])
    assert wr.sample(rng, set(parse_cards("AsAd"))) is None


def test_equity_against_weighted_range():
    kings = HandRange.parse("KK").to_weighted(parse_cards("AhAd"))
    result = monte_carlo_equity(parse_cards("AhAd"), (), 1, 3000, random.Random(0), opponent_ranges=[kings])
    assert result.equity == pytest.approx(0.82, abs=0.03)


def test_open_ranges_widen_as_fewer_players_remain():
    sizes = [charts.RFI_BY_BEHIND[b].percent() for b in range(8, 1, -1)]
    assert sizes == sorted(sizes)
    assert 0.09 < sizes[0] < 0.14 and 0.42 < sizes[-1] < 0.52


def test_rfi_label_uses_real_position():
    assert charts.rfi_range("UTG", 5).label == "UTG 오픈"


def test_position_orders():
    assert preflop_order(6) == ("UTG", "HJ", "CO", "BTN", "SB", "BB")
    assert postflop_order(6) == ("SB", "BB", "UTG", "HJ", "CO", "BTN")
    assert players_behind("UTG", 6) == 5 and players_behind("BTN", 6) == 2
    assert players_behind("BTN/SB", 2) == 1 and players_behind("BB", 2) == 0
