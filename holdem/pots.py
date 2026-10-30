"""메인 팟 / 사이드 팟 계산."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass
class Pot:
    amount: int
    eligible: list[int]  # 이 팟을 가져갈 자격이 있는 좌석 (폴드하지 않은 플레이어)


def build_pots(contributions: Mapping[int, int], folded: set[int]) -> list[Pot]:
    """핸드 전체 기여액(앤티·블라인드 포함)으로 메인/사이드 팟을 나눈다.

    기여액 레벨별로 층을 쌓는 방식: 각 층은 그 레벨 이상을 낸 플레이어들이
    채우고, 그중 폴드하지 않은 플레이어만 가져갈 수 있다.
    맨 위 층에 자격자가 1명뿐이면 그것이 '콜 되지 않은 베팅'(반환분)이다.
    """
    levels = sorted({c for c in contributions.values() if c > 0})
    pots: list[Pot] = []
    carry = 0
    prev = 0
    for level in levels:
        amount = sum(min(c, level) - min(c, prev) for c in contributions.values()) + carry
        eligible = sorted(s for s, c in contributions.items() if c >= level and s not in folded)
        prev = level
        if not eligible:
            # 이 층을 낸 사람이 전부 폴드 → 직전 팟에 합친다 (없으면 다음 층으로 이월)
            if pots:
                pots[-1].amount += amount
                carry = 0
            else:
                carry = amount
            continue
        carry = 0
        if pots and pots[-1].eligible == eligible:
            pots[-1].amount += amount
        else:
            pots.append(Pot(amount, eligible))
    return pots
