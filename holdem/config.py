"""게임 설정: 인원, 바이인, 블라인드 구조, 봇 프로필."""

from __future__ import annotations

from dataclasses import dataclass, field, fields

from .blinds import DEFAULT_SCHEDULE, BlindLevel

MIN_PLAYERS = 2
MAX_PLAYERS = 10


@dataclass
class BotProfile:
    """AI 봇의 스타일·실력 파라미터 (모두 0.0 ~ 1.0).

    - tightness : 높을수록 타이트 (참여하는 핸드 범위가 좁음)
    - aggression: 높을수록 어그레시브 (콜보다 벳/레이즈 선호)
    - skill     : 높을수록 에쿼티 추정이 정확 (판단 노이즈 ↓, 시뮬레이션 횟수 ↑)
    - bluff_freq: 약한 핸드로 블러프를 시도하는 기본 빈도
    """

    name: str = "Bot"
    tightness: float = 0.5
    aggression: float = 0.5
    skill: float = 0.7
    bluff_freq: float = 0.08
    style: str = "custom"

    def __post_init__(self) -> None:
        for f in fields(self):
            if f.type == "float":
                value = getattr(self, f.name)
                if not 0.0 <= value <= 1.0:
                    raise ValueError(f"{f.name}={value} 는 0~1 범위여야 합니다")

    @classmethod
    def preset(cls, style: str, name: str | None = None) -> "BotProfile":
        try:
            tightness, aggression, skill, bluff = BOT_PRESETS[style]
        except KeyError:
            raise ValueError(f"알 수 없는 프리셋: {style} (가능: {', '.join(BOT_PRESETS)})") from None
        return cls(name or style.upper(), tightness, aggression, skill, bluff, style)


# style: (tightness, aggression, skill, bluff_freq)
BOT_PRESETS: dict[str, tuple[float, float, float, float]] = {
    "tag": (0.70, 0.75, 0.85, 0.08),      # 타이트-어그레시브: 정석 레귤러
    "lag": (0.35, 0.80, 0.75, 0.15),      # 루즈-어그레시브: 넓게 참여, 압박
    "rock": (0.85, 0.25, 0.60, 0.02),     # 바위: 프리미엄만 플레이
    "station": (0.20, 0.10, 0.30, 0.01),  # 콜링 스테이션: 웬만하면 콜
    "maniac": (0.10, 0.95, 0.30, 0.30),   # 매니악: 무차별 레이즈
    "fish": (0.30, 0.30, 0.15, 0.05),     # 초보: 판단 노이즈 큼
}

PRESET_DESCRIPTIONS: dict[str, str] = {
    "tag": "타이트-어그레시브 (정석형)",
    "lag": "루즈-어그레시브 (공격형)",
    "rock": "락 (초타이트-패시브)",
    "station": "콜링 스테이션 (루즈-패시브)",
    "maniac": "매니악 (초루즈-초공격)",
    "fish": "피시 (초보)",
}

_DEFAULT_ROTATION = ("tag", "lag", "rock", "station", "fish", "maniac")


@dataclass
class GameSettings:
    num_players: int = 6
    starting_stack: int = 10_000
    blind_schedule: list[BlindLevel] = field(default_factory=lambda: list(DEFAULT_SCHEDULE))
    level_duration_sec: float | None = 600.0  # 시간 기반 레벨업 (None = 끔)
    hands_per_level: int | None = None        # 핸드 수 기반 레벨업 (None = 끔)
    human_seat: int | None = 0                # None 이면 봇끼리 자동 대전
    human_name: str = "Hero"
    bot_profiles: list[BotProfile] = field(default_factory=list)  # 봇 좌석 순서대로
    seed: int | None = None

    def __post_init__(self) -> None:
        if not MIN_PLAYERS <= self.num_players <= MAX_PLAYERS:
            raise ValueError(f"플레이어 수는 {MIN_PLAYERS}~{MAX_PLAYERS}명이어야 합니다")
        if self.starting_stack <= 0:
            raise ValueError("시작 스택은 양수여야 합니다")
        if not self.blind_schedule:
            raise ValueError("블라인드 스케줄이 비어 있습니다")
        if self.human_seat is not None and not 0 <= self.human_seat < self.num_players:
            raise ValueError("human_seat 이 좌석 범위를 벗어났습니다")
        bot_count = len(self.bot_seats())
        if len(self.bot_profiles) > bot_count:
            raise ValueError(f"봇 프로필이 봇 좌석 수({bot_count})보다 많습니다")
        for i in range(len(self.bot_profiles), bot_count):
            style = _DEFAULT_ROTATION[i % len(_DEFAULT_ROTATION)]
            self.bot_profiles.append(BotProfile.preset(style, name=f"Bot{i + 1}"))

    def bot_seats(self) -> list[int]:
        return [s for s in range(self.num_players) if s != self.human_seat]

    def profile_for(self, seat: int) -> BotProfile:
        return self.bot_profiles[self.bot_seats().index(seat)]
