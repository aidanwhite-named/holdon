"""1단계 기본 봇: 몬테카를로 에쿼티 + 팟 오즈 + 스타일 파라미터.

2단계에서 프리플랍 레인지 차트, 상대 레인지 추정(베팅 패턴 기반) 등으로 확장한다.
"""

from __future__ import annotations

import random

from ..config import BotProfile
from ..equity import monte_carlo_equity
from ..models import Action, PlayerView, Street


class RuleBasedBot:
    def __init__(self, profile: BotProfile, rng: random.Random | None = None) -> None:
        self.profile = profile
        self.rng = rng or random.Random()

    def estimate_equity(self, view: PlayerView) -> float:
        """실력(skill)이 낮을수록 시뮬레이션 횟수가 적고 판단 노이즈가 크다."""
        skill = self.profile.skill
        iterations = int(100 + 500 * skill)
        n_opp = max(1, view.num_opponents)
        equity = monte_carlo_equity(view.hole, view.board, n_opp, iterations, self.rng).equity
        noise = self.rng.gauss(0.0, 0.15 * (1.0 - skill))
        return min(1.0, max(0.0, equity + noise))

    def decide(self, view: PlayerView) -> Action:
        p, legal, rng = self.profile, view.legal, self.rng
        equity = self.estimate_equity(view)
        fair_share = 1.0 / (max(1, view.num_opponents) + 1)
        strength = equity / fair_share  # 1.0 = 평균적인 핸드

        value_threshold = 1.7 - 0.5 * p.aggression
        bluffing = rng.random() < p.bluff_freq * (0.5 + p.aggression)
        wants_raise = legal.can_raise and (strength >= value_threshold or bluffing)

        if legal.can_check:
            if wants_raise and rng.random() < 0.35 + 0.6 * p.aggression:
                return self._sized_raise(view, strength)
            return Action.check()

        required = view.pot_odds * (0.85 + 0.4 * p.tightness)
        if view.street == Street.PREFLOP:
            required = max(required, fair_share * (0.75 + 0.6 * p.tightness))
        if equity < required and not bluffing:
            return Action.fold()
        if wants_raise and rng.random() < 0.25 + 0.6 * p.aggression:
            return self._sized_raise(view, strength)
        return Action.call()

    def _sized_raise(self, view: PlayerView, strength: float) -> Action:
        """팟 대비 비율로 사이징: 강할수록, 공격적일수록 크게."""
        legal = view.legal
        fraction = 0.33 if strength < 1.3 else 0.5 if strength < 1.8 else 0.75
        fraction += 0.25 * self.profile.aggression
        target = view.current_bet + fraction * (view.pot + view.to_call)
        bb = view.big_blind
        target = int(round(target / bb) * bb) if target > 4 * bb else int(target)
        if target >= 0.8 * legal.max_raise_to:  # 스택 대부분이 들어가면 올인
            return Action.all_in()
        return Action.raise_to(max(legal.min_raise_to, min(target, legal.max_raise_to)))
