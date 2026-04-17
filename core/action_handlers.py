"""
Default action handlers registered with the FunctionRouter.
"""
from __future__ import annotations

from typing import Any, Dict

from core.execution_guard import ActionType
from core.function_router import FunctionSignature, get_function_router
from core.tools.run_swarm_tests import run_swarm_tests
from utils.logger import get_logger

logger = get_logger("core.action_handlers")


def _handle_propose_order(payload: Dict[str, Any]) -> Dict[str, Any]:
    # Placeholder for order proposal integration.
    logger.info("Routing order proposal: %s", payload)
    return {"accepted": True, "details": payload}


def _handle_explain_decision(payload: Dict[str, Any]) -> Dict[str, Any]:
    # Could invoke explainability service for ad-hoc descriptions.
    logger.info("Explain decision payload: %s", payload)
    return {"explanation": "Explanation requested", "payload": payload}


def _handle_request_sim(payload: Dict[str, Any]) -> Dict[str, Any]:
    logger.info("Sim run requested: %s", payload)
    return {"scheduled": True, "job_id": f"sim_{payload.get('scenario', 'default')}"}


def register_default_actions() -> None:
    router = get_function_router()
    router.register(
        "propose_order",
        FunctionSignature(
            action_type=ActionType.PROPOSE_ORDER,
            func=_handle_propose_order,
            required_permissions={ActionType.PROPOSE_ORDER.value: True},
        ),
    )
    router.register(
        "explain_decision",
        FunctionSignature(
            action_type=ActionType.EXPLAIN_DECISION,
            func=_handle_explain_decision,
            required_permissions={ActionType.EXPLAIN_DECISION.value: True},
        ),
    )
    router.register(
        "request_sim_run",
        FunctionSignature(
            action_type=ActionType.REQUEST_SIM_RUN,
            func=_handle_request_sim,
            required_permissions={ActionType.REQUEST_SIM_RUN.value: True},
        ),
    )
    router.register(
        "run_swarm_tests",
        FunctionSignature(
            action_type=ActionType.EXPLAIN_DECISION,
            func=lambda payload: run_swarm_tests(),
            required_permissions={ActionType.EXPLAIN_DECISION.value: True},
        ),
    )
