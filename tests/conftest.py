import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from holdem import Action, BlindLevel, GameEngine, GameSettings, parse_cards  # noqa: E402
from holdem.cards import FULL_DECK  # noqa: E402


def make_engine(num_players=3, stacks=None, blinds=(50, 100, 0), button=0, **kwargs) -> GameEngine:
    """버튼 좌석을 고정한 봇 전용 엔진 (첫 핸드의 버튼 = button)."""
    settings = GameSettings(
        num_players=num_players,
        blind_schedule=kwargs.pop("schedule", [BlindLevel(*blinds)]),
        level_duration_sec=None,
        human_seat=None,
        seed=kwargs.pop("seed", 1),
        **kwargs,
    )
    engine = GameEngine(settings)
    if stacks:
        for p, stack in zip(engine.players, stacks):
            p.stack = stack
    engine.button = (button - 1) % num_players
    return engine


def rig(engine: GameEngine, holes: dict[int, str], board: str) -> None:
    """진행 중인 핸드의 홀카드와 이후 보드를 지정한다 (덱은 끝에서부터 뽑힘)."""
    hand = engine.hand
    used = []
    for seat, cards in holes.items():
        engine.players[seat].hole = parse_cards(cards)
        used += engine.players[seat].hole
    flop1, flop2, flop3, turn, river = parse_cards(board)
    used += [flop1, flop2, flop3, turn, river]
    filler = [c for c in FULL_DECK if c not in used]
    burns = [filler.pop() for _ in range(3)]
    hand.deck.cards = filler + [river, burns[2], turn, burns[1], flop1, flop2, flop3, burns[0]]


class RandomLegalBot:
    """합법 액션 중 무작위 선택 (엔진 퍼징용)."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng

    def decide(self, legal) -> Action:
        r = self.rng.random()
        if legal.can_raise and r < 0.25:
            choice = self.rng.random()
            if choice < 0.3:
                return Action.raise_to(legal.min_raise_to)
            if choice < 0.5:
                return Action.all_in()
            return Action.raise_to(self.rng.randint(legal.min_raise_to, legal.max_raise_to))
        if r < 0.4 and not legal.can_check:
            return Action.fold()
        return Action.call()


@pytest.fixture
def engine3():
    return make_engine(3)
