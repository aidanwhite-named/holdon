"""핸드 레인지: 표기법('TT+, A2s+, KQo') ↔ 콤보, 가중치 레인지, 13×13 그리드."""

from __future__ import annotations

import random
from bisect import bisect_left
from itertools import accumulate, combinations
from typing import Iterable, Sequence

from treys import Card

RANK_ORDER = "AKQJT98765432"  # 높은 순 (그리드 행/열 순서)
SUITS = "shdc"
TOTAL_COMBOS = 1326
_RANK_VALUE = {r: 14 - i for i, r in enumerate(RANK_ORDER)}  # A=14 … 2=2

Combo = tuple[int, int]


# --------------------------------------------------------------------------- #
# 핸드 코드 (169종)
# --------------------------------------------------------------------------- #
def hand_code(hole: Sequence[int]) -> str:
    """홀카드 2장 → 'AKs' / 'AKo' / 'TT'."""
    a, b = sorted(hole, key=Card.get_rank_int, reverse=True)
    ra, rb = Card.int_to_str(a)[0], Card.int_to_str(b)[0]
    if ra == rb:
        return ra + rb
    return ra + rb + ("s" if Card.get_suit_int(a) == Card.get_suit_int(b) else "o")


def code_combos(code: str) -> list[Combo]:
    r1, r2, kind = code[0], code[1], code[2:]
    if r1 == r2:
        return [(Card.new(r1 + s1), Card.new(r2 + s2)) for s1, s2 in combinations(SUITS, 2)]
    if kind == "s":
        return [(Card.new(r1 + s), Card.new(r2 + s)) for s in SUITS]
    if kind == "o":
        return [(Card.new(r1 + s1), Card.new(r2 + s2)) for s1 in SUITS for s2 in SUITS if s1 != s2]
    raise ValueError(f"잘못된 핸드 코드: {code}")


def combo_count(code: str) -> int:
    return 6 if code[0] == code[1] else 4 if code.endswith("s") else 12


def grid_code(row: int, col: int) -> str:
    """13×13 그리드 좌표 → 코드 (대각선 페어, 위쪽 수딧, 아래쪽 오프수트)."""
    hi, lo = RANK_ORDER[min(row, col)], RANK_ORDER[max(row, col)]
    if row == col:
        return hi + lo
    return hi + lo + ("s" if row < col else "o")


ALL_CODES: tuple[str, ...] = tuple(grid_code(r, c) for r in range(13) for c in range(13))


# --------------------------------------------------------------------------- #
# 표기법 파서
# --------------------------------------------------------------------------- #
def _normalize(token: str) -> str:
    token = token.strip()
    r1, r2, rest = token[0].upper(), token[1].upper(), token[2:].lower()
    if r1 not in _RANK_VALUE or r2 not in _RANK_VALUE or rest not in ("", "s", "o"):
        raise ValueError(f"잘못된 레인지 표기: {token!r}")
    if _RANK_VALUE[r2] > _RANK_VALUE[r1]:
        r1, r2 = r2, r1
    if r1 == r2 and rest:
        raise ValueError(f"페어에는 s/o 를 붙일 수 없습니다: {token!r}")
    return r1 + r2 + rest


def _with_suffix(r1: str, r2: str, suffix: str) -> list[str]:
    if r1 == r2:
        return [r1 + r2]
    return [r1 + r2 + suffix] if suffix else [r1 + r2 + "s", r1 + r2 + "o"]


def _ranks_between(lo: str, hi: str) -> list[str]:
    """lo ~ hi (포함) 사이의 랭크 문자들."""
    return [r for r in RANK_ORDER if _RANK_VALUE[lo] <= _RANK_VALUE[r] <= _RANK_VALUE[hi]]


def _expand(token: str) -> list[str]:
    if "-" in token:
        a, b = (_normalize(t) for t in token.split("-"))
        if a[0] == a[1] and b[0] == b[1]:  # 'TT-77'
            lo, hi = sorted((a[0], b[0]), key=_RANK_VALUE.get)
            return [r + r for r in _ranks_between(lo, hi)]
        if a[0] != b[0] or a[2:] != b[2:]:
            raise ValueError(f"범위 표기는 첫 랭크와 s/o 가 같아야 합니다: {token!r}")
        lo, hi = sorted((a[1], b[1]), key=_RANK_VALUE.get)
        return [c for k in _ranks_between(lo, hi) for c in _with_suffix(a[0], k, a[2:])]
    if token.endswith("+"):
        base = _normalize(token[:-1])
        if base[0] == base[1]:  # '77+'
            return [r + r for r in _ranks_between(base[0], "A")]
        top = RANK_ORDER[RANK_ORDER.index(base[0]) + 1]  # 'A2s+' → A2s … AKs
        return [c for k in _ranks_between(base[1], top) for c in _with_suffix(base[0], k, base[2:])]
    base = _normalize(token)
    return _with_suffix(base[0], base[1], base[2:])


def parse_range(text: str) -> dict[str, float]:
    """'QQ+, AKs, A5s-A2s, KQo:0.5' → {코드: 가중치}. 빈 문자열은 빈 레인지."""
    weights: dict[str, float] = {}
    for raw in text.split(","):
        raw = raw.strip()
        if not raw:
            continue
        weight = 1.0
        if ":" in raw:
            raw, w = raw.split(":")
            weight = float(w)
        for code in _expand(raw):
            weights[code] = max(weights.get(code, 0.0), weight)
    return weights


# --------------------------------------------------------------------------- #
# 레인지 객체
# --------------------------------------------------------------------------- #
class HandRange:
    """169 핸드 코드 단위 레인지 (프리플랍 차트용)."""

    def __init__(self, weights: dict[str, float] | None = None, label: str = "") -> None:
        self.weights = {c: w for c, w in (weights or {}).items() if w > 0}
        self.label = label

    @classmethod
    def parse(cls, text: str, label: str = "") -> "HandRange":
        return cls(parse_range(text), label)

    @classmethod
    def any_two(cls, label: str = "모든 핸드") -> "HandRange":
        return cls({c: 1.0 for c in ALL_CODES}, label)

    def weight(self, code: str) -> float:
        return self.weights.get(code, 0.0)

    def __contains__(self, code: str) -> bool:
        return self.weight(code) > 0

    def __len__(self) -> int:
        return len(self.weights)

    def combo_count(self) -> float:
        return sum(w * combo_count(c) for c, w in self.weights.items())

    def percent(self) -> float:
        """전체 1,326 콤보 중 비율 (가중치 반영)."""
        return self.combo_count() / TOTAL_COMBOS

    def union(self, other: "HandRange", label: str = "") -> "HandRange":
        merged = dict(self.weights)
        for c, w in other.weights.items():
            merged[c] = max(merged.get(c, 0.0), w)
        return HandRange(merged, label or self.label)

    def minus(self, other: "HandRange", label: str = "") -> "HandRange":
        return HandRange({c: w for c, w in self.weights.items() if c not in other}, label or self.label)

    def scaled(self, other: "HandRange", outside: float, label: str = "") -> "HandRange":
        """other 에 속한 핸드는 그대로, 아닌 핸드는 가중치 × outside (부드러운 교집합)."""
        weights = {c: w * (other.weight(c) or outside) for c, w in self.weights.items()}
        return HandRange(weights, label or self.label)

    def combos(self, dead: Iterable[int] = ()) -> list[tuple[Combo, float]]:
        dead_set = set(dead)
        out = []
        for code, w in self.weights.items():
            for a, b in code_combos(code):
                if a not in dead_set and b not in dead_set:
                    out.append(((a, b), w))
        return out

    def to_weighted(self, dead: Iterable[int] = ()) -> "WeightedRange":
        pairs = self.combos(dead)
        return WeightedRange([c for c, _ in pairs], [w for _, w in pairs], self.label)

    def grid(self) -> list[list[tuple[str, float]]]:
        return [[(grid_code(r, c), self.weight(grid_code(r, c))) for c in range(13)] for r in range(13)]

    def render_grid(self, highlight: str | None = None) -> list[str]:
        """터미널용 13×13 차트 (위쪽 수딧 / 대각선 페어 / 아래쪽 오프수트).

        # 포함, + 일부 가중, . 제외, [ ] 내 핸드.
        """
        lines = ["    " + "".join(f" {r} " for r in RANK_ORDER)]
        for r in range(13):
            row = ""
            for c in range(13):
                code = grid_code(r, c)
                w = self.weight(code)
                mark = "#" if w >= 0.99 else "+" if w > 0 else "."
                row += f"[{mark}]" if code == highlight else f" {mark} "
            lines.append(f"  {RANK_ORDER[r]} {row}")
        return lines


class WeightedRange:
    """콤보별 가중치 레인지 (핸드 리딩 결과). monte_carlo_equity 의 opponent_ranges 로 사용."""

    def __init__(self, combos: list[Combo], weights: list[float], label: str = "") -> None:
        keep = [(c, w) for c, w in zip(combos, weights) if w > 0]
        self.combos = [c for c, _ in keep]
        self.weights = [w for _, w in keep]
        self.label = label
        self._cum = list(accumulate(self.weights))

    def __len__(self) -> int:
        return len(self.combos)

    @property
    def total_weight(self) -> float:
        return self._cum[-1] if self._cum else 0.0

    def sample(self, rng: random.Random, used: set[int]) -> list[int] | None:
        """카드 충돌 없이 가중치 비례로 콤보 하나를 뽑는다 (불가능하면 None)."""
        if not self.combos:
            return None
        total = self._cum[-1]
        for _ in range(24):
            a, b = self.combos[bisect_left(self._cum, rng.random() * total)]
            if a not in used and b not in used:
                return [a, b]
        valid = [(c, w) for c, w in zip(self.combos, self.weights) if c[0] not in used and c[1] not in used]
        if not valid:
            return None
        combo = rng.choices([c for c, _ in valid], weights=[w for _, w in valid])[0]
        return list(combo)

    def without(self, dead: Iterable[int]) -> "WeightedRange":
        dead_set = set(dead)
        pairs = [(c, w) for c, w in zip(self.combos, self.weights) if c[0] not in dead_set and c[1] not in dead_set]
        return WeightedRange([c for c, _ in pairs], [w for _, w in pairs], self.label)
