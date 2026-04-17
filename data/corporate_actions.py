"""
Automated corporate action handling.

Processes splits/dividends/mergers metadata and emits normalized adjustments
that other modules can apply to positions or price series.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List
from utils.logger import get_logger


logger = get_logger(__name__)


@dataclass
class CorporateAction:
    symbol: str
    action_type: str
    effective_date: datetime
    payload: Dict[str, object]


class CorporateActionEngine:
    def __init__(self) -> None:
        self._actions: List[CorporateAction] = []

    def record_action(self, symbol: str, action_type: str, payload: Dict[str, object]) -> CorporateAction:
        action = CorporateAction(
            symbol=symbol,
            action_type=action_type,
            effective_date=datetime.utcnow(),
            payload=payload,
        )
        self._actions.append(action)
        logger.info("Recorded corporate action %s for %s", action_type, symbol)
        return action

    def get_actions(self, symbol: str) -> List[CorporateAction]:
        return [action for action in self._actions if action.symbol == symbol]
