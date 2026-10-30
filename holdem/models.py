"""엔진이 주고받는 데이터 모델."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum

from .config import BotProfile
from .evaluator import HandRank


class Street(IntEnum):
    PREFLOP = 0
    FLOP = 1
    TURN = 2
    RIVER = 3

    @property
    def label(self) -> str:
        return ("프리플랍", "플랍", "턴", "리버")[self]


class ActionType(Enum):
    FOLD = "fold"
    CHECK = "check"
    CALL = "call"
    BET = "bet"
    RAISE = "raise"
    ALL_IN = "all_in"


ACTION_LABEL_KO = {
    ActionType.FOLD: "폴드",
    ActionType.CHECK: "체크",
    ActionType.CALL: "콜",
    ActionType.BET: "벳",
    ActionType.RAISE: "레이즈",
    ActionType.ALL_IN: "올인",
}


@dataclass(frozen=True)
class Action:
    type: ActionType
    amount: int = 0  # BET/RAISE: 이번 스트리트에서 내 총 베팅액 (raise-to)

    @classmethod
    def fold(cls) -> "Action":
        return cls(ActionType.FOLD)

    @classmethod
    def check(cls) -> "Action":
        return cls(ActionType.CHECK)

    @classmethod
    def call(cls) -> "Action":
        return cls(ActionType.CALL)

    @classmethod
    def bet(cls, to: int) -> "Action":
        return cls(ActionType.BET, to)

    @classmethod
    def raise_to(cls, to: int) -> "Action":
        return cls(ActionType.RAISE, to)

    @classmethod
    def all_in(cls) -> "Action":
        return cls(ActionType.ALL_IN)


@dataclass
class Player:
    seat: int
    name: str
    stack: int
    is_human: bool = False
    profile: BotProfile | None = None

    # 핸드 단위 상태
    hole: list[int] = field(default_factory=list)
    position: str = ""
    dealt_in: bool = False
    folded: bool = False
    all_in: bool = False
    street_bet: int = 0   # 이번 스트리트 베팅액
    total_bet: int = 0    # 이번 핸드 총 기여액 (앤티 포함)
    acted: bool = False   # 마지막 베팅/레이즈 이후 행동했는가
    raise_seen: int | None = None  # 마지막 행동 시점의 풀 레이즈 횟수 (재레이즈 권한 판정)

    def reset_for_hand(self, dealt_in: bool) -> None:
        self.hole = []
        self.position = ""
        self.dealt_in = dealt_in
        self.folded = not dealt_in
        self.all_in = False
        self.street_bet = 0
        self.total_bet = 0
        self.acted = False
        self.raise_seen = None

    @property
    def in_hand(self) -> bool:
        return self.dealt_in and not self.folded

    @property
    def can_act(self) -> bool:
        return self.in_hand and not self.all_in


@dataclass(frozen=True)
class LegalActions:
    to_call: int        # 콜에 필요한 금액 (스택 제한 전)
    call_amount: int    # 실제로 낼 콜 금액 (스택 부족 시 올인 콜)
    can_check: bool
    can_raise: bool
    min_raise_to: int   # 최소 레이즈 총액 (스택 부족 시 올인 금액)
    max_raise_to: int   # 최대 = 올인

    def describe(self) -> str:
        parts = ["[f]폴드"]
        parts.append("[k]체크" if self.can_check else f"[c]콜 {self.call_amount:,}")
        if self.can_raise:
            verb = "벳" if self.to_call == 0 else "레이즈"
            parts.append(f"[r 금액]{verb} ({self.min_raise_to:,}~{self.max_raise_to:,}, 예: r 50%)")
        parts.append("[a]올인")
        return "  ".join(parts)


@dataclass(frozen=True)
class ActionRecord:
    street: Street
    seat: int
    name: str
    position: str
    kind: ActionType      # FOLD/CHECK/CALL/BET/RAISE (정규화된 행동)
    added: int            # 이번 행동으로 낸 칩
    street_total: int     # 행동 후 이번 스트리트 총 베팅액
    all_in: bool
    pot_after: int
    facing_bet: int = 0   # 행동 직전 스트리트 최고 베팅액

    @property
    def pot_before(self) -> int:
        return self.pot_after - self.added

    @property
    def size_ratio(self) -> float:
        """벳: 팟 대비 비율 (0.5 = 하프 팟). 레이즈: 직전 벳 대비 배수 (3.0 = 3배)."""
        if self.kind == ActionType.BET:
            return self.added / self.pot_before if self.pot_before else 0.0
        if self.kind == ActionType.RAISE and self.facing_bet:
            return self.street_total / self.facing_bet
        return 0.0

    def __str__(self) -> str:
        who = f"{self.name}({self.position})"
        label = ACTION_LABEL_KO[self.kind]
        if self.kind in (ActionType.BET, ActionType.RAISE):
            text = f"{who} {label} → {self.street_total:,}"
        elif self.kind == ActionType.CALL:
            text = f"{who} {label} {self.added:,}"
        else:
            text = f"{who} {label}"
        return text + (" (올인)" if self.all_in else "")


@dataclass(frozen=True)
class PotAward:
    amount: int
    eligible: list[int]
    winners: list[int]
    hand_name: str | None  # 쇼다운 없이 끝나면 None
    uncalled_return: bool = False  # 쇼다운에서 아무도 콜하지 않은 초과 베팅 반환분


@dataclass(frozen=True)
class HandResult:
    awards: list[PotAward]
    showdown: dict[int, HandRank]  # 쇼다운에 참여한 좌석 → 족보 (없으면 빈 dict)
    net: dict[int, int]            # 좌석 → 이번 핸드 손익
    busted: list[int]              # 이번 핸드로 탈락한 좌석

    @property
    def went_to_showdown(self) -> bool:
        return bool(self.showdown)


@dataclass(frozen=True)
class SeatInfo:
    """다른 플레이어의 공개 정보 (홀카드 제외)."""

    seat: int
    name: str
    position: str
    stack: int
    street_bet: int
    total_bet: int
    in_hand: bool
    all_in: bool


@dataclass(frozen=True)
class PlayerView:
    """한 플레이어가 볼 수 있는 정보만 담은 스냅샷 (봇/코치 입력)."""

    seat: int
    position: str
    hole: tuple[int, ...]
    board: tuple[int, ...]
    street: Street
    pot: int                 # 현재 팟 (모든 베팅 포함, 내 콜 전)
    stack: int
    street_bet: int
    current_bet: int
    legal: LegalActions
    big_blind: int
    num_opponents: int       # 폴드하지 않은 상대 수
    num_dealt: int           # 이번 핸드에 참여한 인원
    history: tuple[ActionRecord, ...]
    opponents: tuple[SeatInfo, ...] = ()  # 이번 핸드에 참여한 다른 플레이어 전원

    @property
    def effective_stack(self) -> int:
        """나와 남은 상대 중 가장 큰 스택 사이의 유효 스택 (이번 스트리트 베팅 포함)."""
        mine = self.stack + self.street_bet
        others = [o.stack + o.street_bet for o in self.opponents if o.in_hand]
        return min(mine, max(others)) if others else mine

    @property
    def to_call(self) -> int:
        return self.legal.call_amount

    @property
    def pot_odds(self) -> float:
        call = self.legal.call_amount
        return call / (self.pot + call) if call else 0.0

    @property
    def spr(self) -> float:
        """스택 대 팟 비율 (Stack-to-Pot Ratio)."""
        return self.stack / self.pot if self.pot else float("inf")
