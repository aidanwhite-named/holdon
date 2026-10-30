"""포지션 안내: 현재 포지션의 특성, 기본 오픈 레인지, 운용 팁."""

from __future__ import annotations

from dataclasses import dataclass

from .. import charts
from ..charts import rfi_range
from ..models import PlayerView
from ..positions import players_behind, postflop_order
from ..ranges import HandRange, hand_code


@dataclass(frozen=True)
class PositionGuide:
    group: str
    summary: str
    tips: tuple[str, ...]


_EARLY = PositionGuide(
    "얼리 포지션",
    "뒤에 행동할 사람이 가장 많아 강한 핸드를 만날 확률이 높고, 포스트플랍 대부분 OOP.",
    (
        "가장 타이트하게: 중간 이상 페어, 강한 브로드웨이, 일부 수딧 에이스만 오픈",
        "오프수트 약한 에이스(A2o~A9o)·약한 킹은 버린다 — 도미네이트 당하기 쉬움",
        "림프 금지: 오픈하면 2.5BB 레이즈, 아니면 폴드",
    ),
)
_MIDDLE = PositionGuide(
    "미들 포지션",
    "얼리보다 뒤에 남은 인원이 적어 레인지를 조금 넓힐 수 있는 자리.",
    (
        "수딧 커넥터·수딧 브로드웨이를 추가하되 오프수트 핸드는 여전히 엄격하게",
        "뒤의 CO·BTN 이 3벳할 수 있다는 점을 고려해 콜하기 애매한 핸드는 오픈하지 않는다",
    ),
)
_GUIDES: dict[str, PositionGuide] = {
    "UTG": _EARLY,
    "UTG+1": _EARLY,
    "UTG+2": _EARLY,
    "MP": _MIDDLE,
    "LJ": _MIDDLE,
    "HJ": PositionGuide(
        "하이잭 (미들-레이트)",
        "블라인드 스틸이 시작되는 자리. 뒤에 CO·BTN 두 명의 레이트 포지션이 남아 있다.",
        (
            "수딧 갭퍼·A9o+ 까지 오픈 가능",
            "CO·BTN 의 3벳에 대비해 4벳/콜/폴드 계획을 미리 세운다",
        ),
    ),
    "CO": PositionGuide(
        "컷오프 (레이트)",
        "버튼 다음으로 좋은 자리. 버튼이 폴드하면 포스트플랍 내내 인 포지션.",
        (
            "블라인드 스틸을 적극적으로: 약 30% 오픈",
            "앞에서 림프가 있으면 강한 핸드로 아이솔레이션 레이즈 (3BB + 림퍼당 1BB)",
            "버튼의 3벳 빈도가 높으면 오픈 레인지 하단을 줄인다",
        ),
    ),
    "BTN": PositionGuide(
        "버튼 (최고의 자리)",
        "포스트플랍에서 항상 마지막에 행동(IP) → 정보 우위로 가장 넓게 플레이.",
        (
            "오픈 레인지 약 45~50%: 대부분의 수딧 핸드와 커넥티드 오프수트",
            "상대가 체크하면 c-bet/스틸, 벳하면 플로팅으로 포지션 활용",
            "앞 사람 오픈에는 콜(인 포지션)과 3벳을 섞는다",
        ),
    ),
    "SB": PositionGuide(
        "스몰 블라인드 (가장 어려운 자리)",
        "0.5BB 를 이미 냈지만 포스트플랍 내내 OOP 이고, 뒤에 BB 가 남아 있다.",
        (
            "콜보다는 3벳 또는 폴드 (OOP 콜은 실현 에쿼티가 낮음)",
            "폴드로 돌아오면 BB 상대로 3BB 오픈 (약 40%)",
            "블라인드를 지키려는 집착은 금물 — 이미 낸 칩은 매몰 비용",
        ),
    ),
    "BB": PositionGuide(
        "빅 블라인드 (디펜스 자리)",
        "이미 1BB 를 내서 콜 가격이 가장 싸다 → 가장 넓게 디펜스하지만 포스트플랍은 대부분 OOP.",
        (
            "팟 오즈 덕분에 레이트 오픈에는 약 45% 이상 디펜스",
            "OOP 라 실현 에쿼티가 낮으므로 오프수트 잡패는 버리고 수딧·커넥티드 위주로",
            "림프 팟에서는 강한 핸드로 레이즈, 나머지는 체크로 무료 플랍",
        ),
    ),
    "BTN/SB": PositionGuide(
        "헤즈업 버튼 (SB)",
        "프리플랍에 먼저 행동하지만 포스트플랍은 항상 IP → 매우 넓게 오픈.",
        (
            "약 70% 이상 오픈 레이즈 (림프보다 레이즈)",
            "상대가 한 명뿐이라 하이카드 가치가 커진다 — K-high, Q-high 도 플레이 가능",
        ),
    ),
}


@dataclass(frozen=True)
class PositionCard:
    position: str
    players_behind: int
    in_position: bool          # 남아 있는 상대 중 포스트플랍 마지막 행동자인가
    guide: PositionGuide
    open_range: HandRange      # 이 자리의 기본 레인지 (오픈 RFI, BB 는 디펜스)
    hand: str                  # 내 핸드 코드 (예: 'AJo')

    @property
    def hand_in_open_range(self) -> bool:
        return self.hand in self.open_range

    def lines(self) -> list[str]:
        ip = "포스트플랍 IP(마지막 행동)" if self.in_position else "포스트플랍 OOP(먼저 행동)"
        inside = "안 ✔" if self.hand_in_open_range else "밖 ✘"
        out = [
            f"{self.position} · {self.guide.group} · 뒤에 {self.players_behind}명 · {ip}",
            f"  {self.guide.summary}",
            f"  기본 레인지: {self.open_range.label} {self.open_range.percent():.1%} → 내 핸드 {self.hand} 는 레인지 {inside}",
        ]
        out += [f"  · {tip}" for tip in self.guide.tips]
        return out


def is_in_position(view: PlayerView) -> bool:
    order = postflop_order(view.num_dealt)
    mine = order.index(view.position)
    return all(order.index(o.position) < mine for o in view.opponents if o.in_hand)


def position_card(view: PlayerView) -> PositionCard:
    behind = players_behind(view.position, view.num_dealt)
    guide = _GUIDES.get(view.position, _MIDDLE)
    # BB 는 오픈할 일이 없으므로 '기본 레인지' 로 디펜스 레인지를 보여준다
    base = charts.BB_DEFEND_VS_LATE if view.position == "BB" else rfi_range(view.position, behind)
    return PositionCard(
        position=view.position,
        players_behind=behind,
        in_position=is_in_position(view),
        guide=guide,
        open_range=base,
        hand=hand_code(view.hole),
    )
