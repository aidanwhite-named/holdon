"""코치 파사드: PlayerView 하나로 도우미 카드 4종을 만든다."""

from __future__ import annotations

import random
from dataclasses import dataclass

from ..equity import EquityResult, OutsReport, ThreatReport, analyze_threats, find_outs, monte_carlo_equity
from ..evaluator import evaluate
from ..models import PlayerView
from .action_advisor import AdvisorInput, Recommendation, recommend
from .board import BoardTexture, analyze_board, draw_type
from .hand_reader import OpponentRead, read_opponents
from .position_advisor import PositionCard, position_card


@dataclass
class CoachReport:
    position: PositionCard
    equity: EquityResult          # 추정 레인지 대비
    equity_random: EquityResult   # 랜덤 핸드 대비
    recommendation: Recommendation
    reads: list[OpponentRead]
    view: PlayerView
    outs: OutsReport | None = None
    threats: ThreatReport | None = None
    texture: BoardTexture | None = None

    def cards(self) -> dict[str, list[str]]:
        """UI 용: 카드 제목 → 본문 줄."""
        v = self.view
        equity_lines = []
        if v.board:
            rank = evaluate(v.hole, v.board)
            draw = draw_type(v.hole, v.board)
            equity_lines.append(f"현재 족보: {rank}" + (f" + {draw}" if draw else ""))
        equity_lines.append(f"랜덤 상대: {self.equity_random.summary()}")
        if any(r.range is not None for r in self.reads):
            equity_lines.append(f"추정 레인지 상대: {self.equity.summary()}")
        if self.outs:
            equity_lines.append(self.outs.summary())
        if self.threats:
            equity_lines += self.threats.summary().splitlines()
        reads = [line for r in self.reads for line in r.lines()] or ["남은 상대 없음"]
        return {
            "① 포지션": self.position.lines(),
            "② 에쿼티 · 승률": equity_lines,
            "③ 팟 오즈 · 추천 액션": self.recommendation.lines(),
            "④ 핸드 리딩 (상대 레인지 추론)": reads,
        }

    def render(self) -> str:
        out = []
        for title, lines in self.cards().items():
            out.append(f"┌ {title}")
            out += [f"│ {line}" for line in lines]
        return "\n".join(out)


class Coach:
    """실시간 코칭 엔진.

    iterations: 몬테카를로 횟수 (추정 레인지 / 랜덤 상대 각각)
    with_threats: 위협 분석(전수 조사)은 사람용 화면에만 필요 — 봇은 끈다
    """

    def __init__(self, iterations: int = 1500, rng: random.Random | None = None, with_threats: bool = True) -> None:
        self.iterations = iterations
        self.rng = rng or random.Random()
        self.with_threats = with_threats

    def analyze(self, view: PlayerView) -> CoachReport:
        reads = read_opponents(view)
        n_opp = max(1, len(reads))
        eq_random = monte_carlo_equity(view.hole, view.board, n_opp, self.iterations, self.rng)
        ranges = [r.range for r in reads]
        if reads and any(r is not None for r in ranges):
            eq_range = monte_carlo_equity(view.hole, view.board, n_opp, self.iterations, self.rng, opponent_ranges=ranges)
        else:
            eq_range = eq_random

        outs = find_outs(view.hole, view.board) if len(view.board) in (3, 4) else None
        threats = analyze_threats(view.hole, view.board) if self.with_threats and len(view.board) >= 3 else None
        texture = analyze_board(view.board) if len(view.board) >= 3 else None
        position = position_card(view)

        rec = recommend(AdvisorInput(view, eq_range, eq_random, position, reads, outs, texture))
        return CoachReport(position, eq_range, eq_random, rec, reads, view, outs, threats, texture)

    def recommend(self, view: PlayerView) -> Recommendation:
        return self.analyze(view).recommendation
