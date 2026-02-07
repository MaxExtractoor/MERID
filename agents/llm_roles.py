"""
LLM Role definitions for MERID.
Llama 3 handles strategy/risk/governance; Gemma 3-1B handles UI/explanations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from core.environment import get_environment_flags
from core.execution_guard import ActionType, ExecutionContext, get_execution_guard
from core.explainability import ExplanationContext, ExplanationType, get_explainability_service
from core.network_client import RoutingProfile, get_network_client
from utils.logger import get_logger

logger = get_logger("agents.llm_roles")


class LLMProvider(str, Enum):
    LLAMA = "llama"
    GEMMA = "gemma"


class LLMRoleType(str, Enum):
    STRATEGY = "strategy"
    RISK = "risk"
    GOVERNANCE = "governance"
    RESEARCH = "research"
    EXPLAINER = "explainer"
    UI = "ui"
    BOT = "bot"


@dataclass
class ToolSchema:
    name: str
    description: str
    action_type: ActionType
    parameters: Dict[str, Any]
    required_permissions: Dict[str, bool]
    allowed_providers: List[LLMProvider]


@dataclass
class LLMRole:
    role_type: LLMRoleType
    provider: LLMProvider
    description: str
    tools: List[ToolSchema] = field(default_factory=list)
    can_propose_orders: bool = False
    can_modify_risk: bool = False
    can_access_network: bool = True


LLAMA_STRATEGY_TOOLS: List[ToolSchema] = [
    ToolSchema(
        name="propose_order",
        description="Propose a new order for execution",
        action_type=ActionType.PROPOSE_ORDER,
        parameters={
            "symbol": "str",
            "side": "str",
            "quantity": "float",
            "order_type": "str",
            "price": "Optional[float]",
            "strategy": "str",
        },
        required_permissions={ActionType.PROPOSE_ORDER.value: True},
        allowed_providers=[LLMProvider.LLAMA],
    ),
    ToolSchema(
        name="adjust_parameter",
        description="Adjust a strategy parameter",
        action_type=ActionType.ADJUST_PARAMETER,
        parameters={
            "strategy": "str",
            "parameter": "str",
            "value": "Any",
        },
        required_permissions={ActionType.ADJUST_PARAMETER.value: True},
        allowed_providers=[LLMProvider.LLAMA],
    ),
    ToolSchema(
        name="request_sim_run",
        description="Request a simulation run for a strategy",
        action_type=ActionType.REQUEST_SIM_RUN,
        parameters={
            "strategy": "str",
            "scenario": "str",
            "duration_days": "int",
        },
        required_permissions={ActionType.REQUEST_SIM_RUN.value: True},
        allowed_providers=[LLMProvider.LLAMA],
    ),
]

LLAMA_RISK_TOOLS: List[ToolSchema] = [
    ToolSchema(
        name="set_risk_limit",
        description="Set a risk limit for a strategy or portfolio",
        action_type=ActionType.ADJUST_PARAMETER,
        parameters={
            "scope": "str",
            "limit_type": "str",
            "value": "float",
        },
        required_permissions={ActionType.ADJUST_PARAMETER.value: True},
        allowed_providers=[LLMProvider.LLAMA],
    ),
    ToolSchema(
        name="trigger_safe_mode",
        description="Trigger safe mode for risk mitigation",
        action_type=ActionType.ADJUST_PARAMETER,
        parameters={
            "reason": "str",
        },
        required_permissions={ActionType.ADJUST_PARAMETER.value: True},
        allowed_providers=[LLMProvider.LLAMA],
    ),
]

LLAMA_GOVERNANCE_TOOLS: List[ToolSchema] = [
    ToolSchema(
        name="promote_strategy",
        description="Promote a strategy to a higher lifecycle stage",
        action_type=ActionType.ADJUST_PARAMETER,
        parameters={
            "strategy": "str",
            "from_stage": "str",
            "to_stage": "str",
        },
        required_permissions={ActionType.ADJUST_PARAMETER.value: True},
        allowed_providers=[LLMProvider.LLAMA],
    ),
    ToolSchema(
        name="demote_strategy",
        description="Demote a strategy to a lower lifecycle stage",
        action_type=ActionType.ADJUST_PARAMETER,
        parameters={
            "strategy": "str",
            "from_stage": "str",
            "to_stage": "str",
            "reason": "str",
        },
        required_permissions={ActionType.ADJUST_PARAMETER.value: True},
        allowed_providers=[LLMProvider.LLAMA],
    ),
]

GEMMA_EXPLAINER_TOOLS: List[ToolSchema] = [
    ToolSchema(
        name="explain_decision",
        description="Generate an explanation for a decision",
        action_type=ActionType.EXPLAIN_DECISION,
        parameters={
            "decision_id": "str",
            "detail_level": "str",
        },
        required_permissions={ActionType.EXPLAIN_DECISION.value: True},
        allowed_providers=[LLMProvider.GEMMA],
    ),
    ToolSchema(
        name="summarize_portfolio",
        description="Summarize portfolio state for UI",
        action_type=ActionType.EXPLAIN_DECISION,
        parameters={
            "scope": "str",
        },
        required_permissions={ActionType.EXPLAIN_DECISION.value: True},
        allowed_providers=[LLMProvider.GEMMA],
    ),
]

GEMMA_BOT_TOOLS: List[ToolSchema] = [
    ToolSchema(
        name="send_alert",
        description="Send an alert message to Telegram or X",
        action_type=ActionType.EXPLAIN_DECISION,
        parameters={
            "channel": "str",
            "message": "str",
            "priority": "str",
        },
        required_permissions={ActionType.EXPLAIN_DECISION.value: True},
        allowed_providers=[LLMProvider.GEMMA],
    ),
]


ROLE_REGISTRY: Dict[LLMRoleType, LLMRole] = {
    LLMRoleType.STRATEGY: LLMRole(
        role_type=LLMRoleType.STRATEGY,
        provider=LLMProvider.LLAMA,
        description="Strategy design, critique, regime detection, parameter search",
        tools=LLAMA_STRATEGY_TOOLS,
        can_propose_orders=True,
        can_modify_risk=False,
        can_access_network=True,
    ),
    LLMRoleType.RISK: LLMRole(
        role_type=LLMRoleType.RISK,
        provider=LLMProvider.LLAMA,
        description="Risk reasoning, limit setting, safe mode triggers",
        tools=LLAMA_RISK_TOOLS,
        can_propose_orders=False,
        can_modify_risk=True,
        can_access_network=True,
    ),
    LLMRoleType.GOVERNANCE: LLMRole(
        role_type=LLMRoleType.GOVERNANCE,
        provider=LLMProvider.LLAMA,
        description="Strategy lifecycle, promotion/demotion, agent oversight",
        tools=LLAMA_GOVERNANCE_TOOLS,
        can_propose_orders=False,
        can_modify_risk=True,
        can_access_network=True,
    ),
    LLMRoleType.RESEARCH: LLMRole(
        role_type=LLMRoleType.RESEARCH,
        provider=LLMProvider.LLAMA,
        description="Experiment design, feature engineering, backtest analysis",
        tools=LLAMA_STRATEGY_TOOLS,
        can_propose_orders=False,
        can_modify_risk=False,
        can_access_network=True,
    ),
    LLMRoleType.EXPLAINER: LLMRole(
        role_type=LLMRoleType.EXPLAINER,
        provider=LLMProvider.GEMMA,
        description="Decision explanations, summaries, help text",
        tools=GEMMA_EXPLAINER_TOOLS,
        can_propose_orders=False,
        can_modify_risk=False,
        can_access_network=False,
    ),
    LLMRoleType.UI: LLMRole(
        role_type=LLMRoleType.UI,
        provider=LLMProvider.GEMMA,
        description="Dashboard text, tooltips, user input parsing",
        tools=GEMMA_EXPLAINER_TOOLS,
        can_propose_orders=False,
        can_modify_risk=False,
        can_access_network=False,
    ),
    LLMRoleType.BOT: LLMRole(
        role_type=LLMRoleType.BOT,
        provider=LLMProvider.GEMMA,
        description="Telegram/X bot messages and alerts",
        tools=GEMMA_BOT_TOOLS,
        can_propose_orders=False,
        can_modify_risk=False,
        can_access_network=True,
    ),
}


class LLMToolRouter:
    """Routes LLM tool calls through Execution Guard with role enforcement."""

    def __init__(self) -> None:
        self._guard = get_execution_guard()
        self._network_client = get_network_client()
        self._explainability = get_explainability_service()
        self._module_name = "agents.llm_roles"
        self._network_client.register_module_profile(self._module_name, RoutingProfile.VPN_A)

    def call_tool(
        self,
        role_type: LLMRoleType,
        tool_name: str,
        payload: Dict[str, Any],
        caller_id: str,
    ) -> Dict[str, Any]:
        role = ROLE_REGISTRY.get(role_type)
        if not role:
            return {"status": "denied", "reason": f"Unknown role {role_type}"}

        tool = next((t for t in role.tools if t.name == tool_name), None)
        if not tool:
            return {"status": "denied", "reason": f"Tool {tool_name} not available for role {role_type.value}"}

        if role.provider not in tool.allowed_providers:
            return {"status": "denied", "reason": f"Provider {role.provider.value} cannot use tool {tool_name}"}

        flags = get_environment_flags()
        if role.can_access_network and not flags.online:
            if tool.action_type in {ActionType.PROPOSE_ORDER, ActionType.INITIATE_PAYMENT}:
                return {"status": "denied", "reason": "Offline mode blocks external actions"}

        context = ExecutionContext(
            caller=caller_id,
            role=role_type.value,
            environment_flags={
                "online": flags.online,
                "routing_profile": flags.enforced_routing_profile.value,
                "vpn_only": flags.vpn_only,
                "privacy_mode": flags.privacy_mode,
            },
            permissions=tool.required_permissions,
        )

        result = self._guard.evaluate(tool.action_type, payload, context)
        self._record_tool_call(role_type, tool_name, payload, result.allowed, result.reason, caller_id)

        if not result.allowed:
            return {"status": "denied", "reason": result.reason}

        return {"status": "ok", "tool": tool_name, "payload": payload}

    def _record_tool_call(
        self,
        role_type: LLMRoleType,
        tool_name: str,
        payload: Dict[str, Any],
        allowed: bool,
        reason: str,
        caller_id: str,
    ) -> None:
        flags = get_environment_flags()
        env_dict = {
            "online": flags.online,
            "routing_profile": flags.enforced_routing_profile.value,
            "vpn_only": flags.vpn_only,
            "privacy_mode": flags.privacy_mode,
        }
        context = ExplanationContext(
            inputs=payload,
            agent_id=caller_id,
            strategy=payload.get("strategy"),
            constraints={"role": role_type.value, "tool": tool_name},
            expected_effect={"allowed": allowed, "reason": reason},
            environment_flags=env_dict,
        )
        self._explainability.record_explanation(
            explanation_type=ExplanationType.PARAM_CHANGE,
            summary=f"LLM tool call {tool_name} by {role_type.value}: {'allowed' if allowed else 'denied'}",
            context=context,
            expert_notes=reason,
        )


_tool_router: Optional[LLMToolRouter] = None


def get_llm_tool_router() -> LLMToolRouter:
    global _tool_router
    if _tool_router is None:
        _tool_router = LLMToolRouter()
    return _tool_router
