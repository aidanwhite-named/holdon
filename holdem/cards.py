"""카드 표현: treys 의 정수 카드 인코딩을 그대로 사용한다."""

from __future__ import annotations

import random
from typing import Iterable

from treys import Card

RANKS = "23456789TJQKA"
SUITS = "shdc"
SUIT_SYMBOLS = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}

FULL_DECK: tuple[int, ...] = tuple(Card.new(r + s) for r in RANKS for s in SUITS)


def parse_cards(cards: str | Iterable[str]) -> list[int]:
    """'Ah Kd' / 'AhKd' / ['Ah', 'Kd'] → treys 정수 카드 리스트."""
    if isinstance(cards, str):
        compact = cards.replace(",", " ").replace(" ", "")
        if len(compact) % 2:
            raise ValueError(f"카드 문자열을 해석할 수 없습니다: {cards!r}")
        tokens = [compact[i : i + 2] for i in range(0, len(compact), 2)]
    else:
        tokens = list(cards)
    result = []
    for token in tokens:
        rank, suit = token[0].upper(), token[1].lower()
        if rank not in RANKS or suit not in SUITS:
            raise ValueError(f"잘못된 카드: {token!r}")
        result.append(Card.new(rank + suit))
    if len(set(result)) != len(result):
        raise ValueError(f"중복된 카드가 있습니다: {cards!r}")
    return result


def card_str(card: int) -> str:
    """정수 카드 → 'Ah' 형식."""
    return Card.int_to_str(card)


def pretty(cards: Iterable[int]) -> str:
    """정수 카드들 → 'A♥ K♦' 형식."""
    out = []
    for card in cards:
        text = Card.int_to_str(card)
        out.append(text[0] + SUIT_SYMBOLS[text[1]])
    return " ".join(out)


def rank_of(card: int) -> int:
    """0(2) ~ 12(A)."""
    return Card.get_rank_int(card)


class Deck:
    """시드 가능한 52장 덱 (재현 가능한 학습 시나리오를 위해 rng 주입)."""

    def __init__(self, rng: random.Random | None = None, exclude: Iterable[int] = ()) -> None:
        excluded = set(exclude)
        self.cards = [c for c in FULL_DECK if c not in excluded]
        (rng or random.Random()).shuffle(self.cards)

    def draw(self, n: int = 1) -> list[int]:
        if n < 0 or n > len(self.cards):
            raise ValueError(f"{n}장을 뽑을 수 없습니다 (남은 카드 {len(self.cards)}장)")
        if n == 0:
            return []
        drawn = self.cards[-n:]
        del self.cards[-n:]
        return drawn

    def __len__(self) -> int:
        return len(self.cards)
