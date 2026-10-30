from __future__ import annotations

from typing import Protocol

from ..models import Action, PlayerView


class Bot(Protocol):
    """봇 인터페이스: 볼 수 있는 정보(PlayerView)만으로 액션을 결정한다."""

    def decide(self, view: PlayerView) -> Action: ...
