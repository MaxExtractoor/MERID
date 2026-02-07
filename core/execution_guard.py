"""
Execution Guard for safe function-calling and action validation.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

from utils.logger import get_logger

logger = get_logger("core.execution_guard")


class ActionType(str, Enum):
    """Supported action types."""

    PROPOSE_ORDER = "propose_order"
    ADJUST_PARAMETER = "adjust_parameter"
    REQUEST_SIM_RUN = "request_sim_run"
    INITIATE_PAYMENT = "initiate_payment"
    EXPLAIN_DECISION = "explain_decision"


@dataclass
class ExecutionContext:
    """Context for an action request."""

    caller: str
    role: str
    environment_flags: Dict[str, Any]
    permissions: Dict[str, bool]


@dataclass
class ActionResult:
    """Result of guard evaluation."""

    allowed: bool
    reason: str
    timestamp: float


class ExecutionGuard:
    """Validates function calls against policies and risk limits."""

    def __init__(self) -> None:
        self._policies: Dict[ActionType, Dict[str, Any]] = {}
        self._init_default_policies()

    def set_policy(self, action_type: ActionType, policy: Dict[str, Any]) -> None:
        self._policies[action_type] = policy
        logger.info("Execution policy updated for %s", action_type.value)

    def evaluate(self, action_type: ActionType, payload: Dict[str, Any], context: ExecutionContext) -> ActionResult:
        policy = self._policies.get(action_type)
        if not policy:
            return ActionResult(False, "No policy registered", time.time())

        if context.environment_flags.get("online") is False and action_type in {
            ActionType.PROPOSE_ORDER,
            ActionType.INITIATE_PAYMENT,
        }:
            return self._deny("Offline mode: action denied")

        if context.environment_flags.get("vpn_only") and context.environment_flags.get("routing_profile") not in {"vpn_a", "vpn_b"}:
            return self._deny("VPN-only mode: invalid routing profile")

        if not context.permissions.get(action_type.value, False):
            return self._deny("Caller lacks permission for this action")

        limit = policy.get("risk_limit")
        amount = payload.get("notional", 0)
        if limit is not None and amount > limit:
            return self._deny(f"Amount {amount} exceeds limit {limit}")

        return ActionResult(True, "Approved", time.time())

    def _deny(self, reason: str) -> ActionResult:
        logger.warning("ExecutionGuard deny: %s", reason)
        return ActionResult(False, reason, time.time())

    def _init_default_policies(self) -> None:
        self.set_policy(ActionType.PROPOSE_ORDER, {"risk_limit": 500000.0})
        self.set_policy(ActionType.INITIATE_PAYMENT, {"risk_limit": 250000.0})
        self.set_policy(ActionType.ADJUST_PARAMETER, {"risk_limit": None})
        self.set_policy(ActionType.REQUEST_SIM_RUN, {"risk_limit": None})
        self.set_policy(ActionType.EXPLAIN_DECISION, {"risk_limit": None})


_guard: Optional[ExecutionGuard] = None


def get_execution_guard() -> ExecutionGuard:
    global _guard
    if _guard is None:
        _guard = ExecutionGuard()
    return _guard
