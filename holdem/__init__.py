"""텍사스 홀덤 학습용 시뮬레이터 코어 패키지.

UI와 무관한 순수 로직만 담는다. CLI / Streamlit 등 어떤 프런트엔드든
`GameEngine`을 한 액션씩 구동(step-driven)하는 방식으로 붙일 수 있다.
"""

from .blinds import BlindClock, BlindLevel, DEFAULT_SCHEDULE, generate_schedule
from .cards import Deck, parse_cards, pretty
from .config import BotProfile, GameSettings
from .engine import GameEngine, IllegalActionError
from .equity import analyze_threats, find_outs, monte_carlo_equity, pot_odds
from .evaluator import HandRank, evaluate
from .models import Action, ActionType, LegalActions, PlayerView, Street

__all__ = [
    "Action",
    "ActionType",
    "BlindClock",
    "BlindLevel",
    "BotProfile",
    "DEFAULT_SCHEDULE",
    "Deck",
    "GameEngine",
    "GameSettings",
    "HandRank",
    "IllegalActionError",
    "LegalActions",
    "PlayerView",
    "Street",
    "analyze_threats",
    "evaluate",
    "find_outs",
    "generate_schedule",
    "monte_carlo_equity",
    "parse_cards",
    "pot_odds",
    "pretty",
]
