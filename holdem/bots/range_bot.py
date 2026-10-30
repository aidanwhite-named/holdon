"""2단계 봇: 코칭 엔진의 추천(차트 + 레인지 리딩 + 에쿼티)을 따르되 스타일·실력만큼 벗어난다.

- skill 이 높을수록 추천을 정확히 따른다 (낮으면 무작위 실수)
- tightness 가 낮으면 폴드 대신 콜을 자주 한다 (루즈)
- aggression 이 높으면 콜 대신 레이즈, 낮으면 레이즈 대신 콜 (패시브)
- bluff_freq 만큼 체크 대신 블러프 벳
"""

from __future__ import annotations

import random

from ..coach import Coach
from ..config import BotProfile
from ..models import Action, ActionType, PlayerView


class RangeBot:
    def __init__(self, profile: BotProfile, rng: random.Random | None = None) -> None:
        self.profile = profile
        self.rng = rng or random.Random()
        self.coach = Coach(iterations=int(150 + 450 * profile.skill), rng=self.rng, with_threats=False)

    def decide(self, view: PlayerView) -> Action:
        p, rng, legal = self.profile, self.rng, view.legal
        rec = self.coach.recommend(view)
        pot_bet = view.current_bet + 0.6 * (view.pot + view.to_call)

        if rng.random() < 0.25 * (1.0 - p.skill):  # 실력 부족으로 인한 실수
            return rng.choice(
                [Action.call(), Action.fold() if not legal.can_check else Action.check()]
                + ([Action.raise_to(legal.min_raise_to)] if legal.can_raise else [])
            )

        if rec.action == ActionType.FOLD:
            if legal.can_raise and rng.random() < 0.5 * p.bluff_freq * p.aggression:
                return self._raise(view, view.current_bet * 3)
            if view.pot_odds < 0.4 and rng.random() < 0.4 * (1.0 - p.tightness):
                return Action.call()
            return Action.fold()

        if rec.action == ActionType.CHECK:
            if legal.can_raise and rng.random() < p.bluff_freq * (0.5 + p.aggression):
                return self._raise(view, 0.5 * view.pot)
            return Action.check()

        if rec.action == ActionType.CALL:
            if legal.can_raise and rng.random() < 0.25 * p.aggression:
                return self._raise(view, pot_bet)
            return Action.call()

        # BET / RAISE / ALL_IN
        if rng.random() < 0.35 * (1.0 - p.aggression):
            return Action.call() if not legal.can_check else Action.check()
        return rec.to_action()

    @staticmethod
    def _raise(view: PlayerView, target: float) -> Action:
        legal = view.legal
        return Action.raise_to(int(max(legal.min_raise_to, min(target, legal.max_raise_to))))
