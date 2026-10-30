"""블라인드 구조와 타이머 기반 레벨업."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Sequence


@dataclass(frozen=True)
class BlindLevel:
    small_blind: int
    big_blind: int
    ante: int = 0

    def __post_init__(self) -> None:
        if not 0 < self.small_blind <= self.big_blind:
            raise ValueError(f"잘못된 블라인드: {self.small_blind}/{self.big_blind}")
        if self.ante < 0:
            raise ValueError("앤티는 0 이상이어야 합니다")

    def __str__(self) -> str:
        text = f"{self.small_blind:,}/{self.big_blind:,}"
        return f"{text} (앤티 {self.ante:,})" if self.ante else text


# 시작 스택 10,000 기준 딥스택(200BB) 토너먼트 구조
DEFAULT_SCHEDULE: tuple[BlindLevel, ...] = (
    BlindLevel(25, 50),
    BlindLevel(50, 100),
    BlindLevel(75, 150),
    BlindLevel(100, 200),
    BlindLevel(150, 300),
    BlindLevel(200, 400, 50),
    BlindLevel(300, 600, 75),
    BlindLevel(400, 800, 100),
    BlindLevel(600, 1200, 200),
    BlindLevel(800, 1600, 200),
    BlindLevel(1000, 2000, 300),
    BlindLevel(1500, 3000, 400),
    BlindLevel(2000, 4000, 500),
)


def _round_nice(x: float) -> int:
    """유효숫자 2자리로 반올림하고 짝수로 맞춘다 (SB = BB/2가 정수가 되도록)."""
    step = 10 ** max(0, len(str(int(x))) - 2)
    value = max(2, int(round(x / step)) * step)
    return value + (value % 2)


def generate_schedule(
    start_big_blind: int = 50,
    levels: int = 15,
    growth: float = 1.4,
    ante_from_level: int | None = 6,
    ante_ratio: float = 0.125,
) -> list[BlindLevel]:
    """증가율(growth)로 블라인드 구조를 자동 생성한다.

    growth 1.25~1.3 = 딥스택, 1.4~1.5 = 레귤러, 2.0 = 터보 정도의 체감.
    """
    schedule: list[BlindLevel] = []
    bb = float(start_big_blind)
    for i in range(levels):
        big = _round_nice(bb)
        if schedule and big <= schedule[-1].big_blind:
            big = schedule[-1].big_blind + 2
        ante = 0
        if ante_from_level is not None and i + 1 >= ante_from_level:
            ante = max(1, int(big * ante_ratio))
        schedule.append(BlindLevel(big // 2, big, ante))
        bb *= growth
    return schedule


class BlindClock:
    """시간(초) 또는 진행된 핸드 수에 따라 블라인드 레벨을 계산한다.

    레벨은 핸드 시작 시점에만 반영된다(진행 중인 핸드의 블라인드는 바뀌지 않음).
    `clock`을 주입할 수 있어 테스트나 일시정지/재개가 쉽다.
    """

    def __init__(
        self,
        schedule: Sequence[BlindLevel],
        level_duration_sec: float | None = 600.0,
        hands_per_level: int | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not schedule:
            raise ValueError("블라인드 스케줄이 비어 있습니다")
        self.schedule = list(schedule)
        self.level_duration_sec = level_duration_sec
        self.hands_per_level = hands_per_level
        self._clock = clock
        self._started_at: float | None = None
        self._paused_at: float | None = None
        self._paused_total = 0.0

    def start(self) -> None:
        if self._started_at is None:
            self._started_at = self._clock()

    def pause(self) -> None:
        if self._started_at is not None and self._paused_at is None:
            self._paused_at = self._clock()

    def resume(self) -> None:
        if self._paused_at is not None:
            self._paused_total += self._clock() - self._paused_at
            self._paused_at = None

    @property
    def paused(self) -> bool:
        return self._paused_at is not None

    def elapsed(self) -> float:
        if self._started_at is None:
            return 0.0
        now = self._paused_at if self._paused_at is not None else self._clock()
        return now - self._started_at - self._paused_total

    def level_index(self, hands_played: int = 0) -> int:
        index = 0
        if self.level_duration_sec:
            index = max(index, int(self.elapsed() // self.level_duration_sec))
        if self.hands_per_level:
            index = max(index, hands_played // self.hands_per_level)
        return min(index, len(self.schedule) - 1)

    def current_level(self, hands_played: int = 0) -> BlindLevel:
        return self.schedule[self.level_index(hands_played)]

    def seconds_to_next_level(self) -> float | None:
        """시간 기반 레벨업이 꺼져 있거나 마지막 레벨이면 None."""
        if not self.level_duration_sec or self.level_index() >= len(self.schedule) - 1:
            return None
        return self.level_duration_sec - (self.elapsed() % self.level_duration_sec)
