"""
Function Router that enforces Execution Guard for LLM/tool calls.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict

from core.execution_guard import ActionType, ExecutionContext, get_execution_guard
from core.environment import get_environment_flags
from utils.logger import get_logger

logger = get_logger("core.function_router")


@dataclass
class FunctionSignature:
    """Describes a callable exposed to LLM agents."""

    action_type: ActionType
    func: Callable[..., Any]
    required_permissions: Dict[str, bool]


class FunctionRouter:
    """Routes safe function calls through Execution Guard."""

    def __init__(self) -> None:
        self._signatures: Dict[str, FunctionSignature] = {}
        self._guard = get_execution_guard()

    def register(self, name: str, signature: FunctionSignature) -> None:
        if name in self._signatures:
            logger.warning("Function %s already registered. Overwriting.", name)
        self._signatures[name] = signature
        logger.info("Registered safe function %s", name)

    def call(self, name: str, payload: Dict[str, Any], caller: str, role: str) -> Dict[str, Any]:
        if name not in self._signatures:
            raise ValueError(f"Function '{name}' is not registered")

        signature = self._signatures[name]
        env_flags = get_environment_flags()
        context = ExecutionContext(
            caller=caller,
            role=role,
            environment_flags={
                "online": env_flags.online,
                "routing_profile": env_flags.enforced_routing_profile.value,
                "vpn_only": env_flags.vpn_only,
                "privacy_mode": env_flags.privacy_mode,
            },
            permissions=signature.required_permissions,
        )

        result = self._guard.evaluate(signature.action_type, payload, context)
        if not result.allowed:
            logger.warning("Function %s denied: %s", name, result.reason)
            return {"status": "denied", "reason": result.reason}

        logger.info("Function %s approved for %s", name, caller)
        output = signature.func(payload)
        return {"status": "ok", "output": output}


_router: Optional[FunctionRouter] = None
_router_lock = threading.Lock()


def get_function_router() -> FunctionRouter:
    global _router
    if _router is None:
        with _router_lock:
            if _router is None:
                _router = FunctionRouter()
    return _router
