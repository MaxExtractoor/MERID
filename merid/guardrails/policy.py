"""
§2 — Policy Engine for High-Risk Tools

Tools like place_order, update_strategy_config, adjust_risk_limits require:
- Hard-coded preconditions (time windows, risk states, scope checks)
- Optionally a second agent's approval or human-in-the-loop for prod
- Structured intent checking before execution

The policy engine sits between the capability check and actual tool execution.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.guardrails.policy")


class PolicyVerdict(str, Enum):
    """Result of a policy check."""
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"
    REQUIRE_CONFIRMATION = "require_confirmation"


@dataclass
class PolicyCheckResult:
    """Detailed result from a policy evaluation."""
    verdict: PolicyVerdict
    reason: str = ""
    required_approvers: List[str] = field(default_factory=list)
    conditions_met: List[str] = field(default_factory=list)
    conditions_failed: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "reason": self.reason,
            "required_approvers": self.required_approvers,
            "conditions_met": self.conditions_met,
            "conditions_failed": self.conditions_failed,
        }


@dataclass
class PolicyRule:
    """One policy rule that gates a tool or set of tools."""
    rule_id: str
    description: str
    # Which tools this rule applies to (empty = all)
    tool_patterns: List[str] = field(default_factory=list)
    # Which scopes this rule applies in
    scopes: List[str] = field(default_factory=lambda: ["live"])
    # The check function: (tool_name, params, context_dict) → PolicyCheckResult
    check_fn: Optional[Callable] = None
    enabled: bool = True


class PolicyEngine:
    """
    Evaluates structured intents against a set of policy rules
    before allowing tool execution.

    Rules are checked in order; first DENY or REQUIRE_APPROVAL wins.
    If all rules pass, the verdict is ALLOW.
    """

    def __init__(self) -> None:
        self._rules: List[PolicyRule] = []
        self._init_default_rules()
        logger.info("PolicyEngine initialized with %d rules", len(self._rules))

    def add_rule(self, rule: PolicyRule) -> None:
        self._rules.append(rule)

    def evaluate(
        self,
        tool_name: str,
        params: Dict[str, Any],
        context: Dict[str, Any],
    ) -> PolicyCheckResult:
        """
        Evaluate all applicable rules for a tool call.

        Args:
            tool_name: Name of the tool being called
            params: Parameters passed to the tool
            context: AgentContext.to_dict() — includes scope, budget, etc.

        Returns:
            PolicyCheckResult with the final verdict
        """
        scope = context.get("scope", "paper")
        conditions_met = []
        conditions_failed = []

        for rule in self._rules:
            if not rule.enabled:
                continue
            # Check if rule applies to this tool
            if rule.tool_patterns and not any(
                p == "*" or p == tool_name or tool_name.startswith(p)
                for p in rule.tool_patterns
            ):
                continue
            # Check if rule applies to this scope
            if rule.scopes and scope not in rule.scopes:
                continue

            if rule.check_fn:
                result = rule.check_fn(tool_name, params, context)
                if result.verdict == PolicyVerdict.DENY:
                    logger.warning(
                        "Policy DENY: rule=%s tool=%s reason=%s",
                        rule.rule_id, tool_name, result.reason,
                    )
                    return result
                if result.verdict == PolicyVerdict.REQUIRE_APPROVAL:
                    logger.info(
                        "Policy REQUIRE_APPROVAL: rule=%s tool=%s",
                        rule.rule_id, tool_name,
                    )
                    return result
                conditions_met.extend(result.conditions_met)
            else:
                conditions_met.append(f"rule:{rule.rule_id}:passed")

        return PolicyCheckResult(
            verdict=PolicyVerdict.ALLOW,
            reason="All policy checks passed",
            conditions_met=conditions_met,
        )

    def get_rules(self) -> List[Dict[str, Any]]:
        return [
            {
                "rule_id": r.rule_id,
                "description": r.description,
                "tool_patterns": r.tool_patterns,
                "scopes": r.scopes,
                "enabled": r.enabled,
            }
            for r in self._rules
        ]

    # ── Default rules ────────────────────────────────────────────────

    def _init_default_rules(self) -> None:
        """Register built-in policy rules for MERID."""

        # Rule 1: No live trading without explicit flag
        self.add_rule(PolicyRule(
            rule_id="no_live_without_flag",
            description="Block live trading unless MERID_ALLOW_LIVE_TRADES is set",
            tool_patterns=["place_order", "cancel_order", "modify_order"],
            scopes=["live"],
            check_fn=self._check_live_trading_flag,
        ))

        # Rule 2: Max notional per order
        self.add_rule(PolicyRule(
            rule_id="max_notional_per_order",
            description="Block orders exceeding agent's max notional",
            tool_patterns=["place_order"],
            scopes=["paper", "live"],
            check_fn=self._check_max_notional,
        ))

        # Rule 3: Kill switch active
        self.add_rule(PolicyRule(
            rule_id="kill_switch",
            description="Block all trading when kill switch is active",
            tool_patterns=["place_order", "cancel_order", "modify_order"],
            scopes=["paper", "live"],
            check_fn=self._check_kill_switch,
        ))

        # Rule 4: Config changes require approval in live
        self.add_rule(PolicyRule(
            rule_id="config_change_approval",
            description="Config changes in live scope require human approval",
            tool_patterns=["update_strategy_config", "adjust_risk_limits", "deploy_model"],
            scopes=["live"],
            check_fn=self._check_config_change_approval,
        ))

        # Rule 5: Rate limit on orders
        self.add_rule(PolicyRule(
            rule_id="order_rate_limit",
            description="Enforce per-agent order rate limits",
            tool_patterns=["place_order"],
            scopes=["paper", "live"],
            check_fn=self._check_order_rate_limit,
        ))

    @staticmethod
    def _check_live_trading_flag(
        tool_name: str, params: Dict[str, Any], context: Dict[str, Any]
    ) -> PolicyCheckResult:
        import os
        allowed = os.getenv("MERID_ALLOW_LIVE_TRADES", "false").lower() in ("true", "1", "yes")
        if not allowed:
            return PolicyCheckResult(
                verdict=PolicyVerdict.DENY,
                reason="MERID_ALLOW_LIVE_TRADES is not set — live trading blocked",
                conditions_failed=["live_trading_flag"],
            )
        return PolicyCheckResult(
            verdict=PolicyVerdict.ALLOW,
            conditions_met=["live_trading_flag"],
        )

    @staticmethod
    def _check_max_notional(
        tool_name: str, params: Dict[str, Any], context: Dict[str, Any]
    ) -> PolicyCheckResult:
        notional = params.get("notional_usd", 0) or params.get("quantity", 0) * params.get("price", 0)
        max_notional = context.get("max_notional_usd", 10_000)
        if notional > max_notional:
            return PolicyCheckResult(
                verdict=PolicyVerdict.DENY,
                reason=f"Order notional ${notional:,.2f} exceeds limit ${max_notional:,.2f}",
                conditions_failed=["max_notional"],
            )
        return PolicyCheckResult(
            verdict=PolicyVerdict.ALLOW,
            conditions_met=["max_notional"],
        )

    @staticmethod
    def _check_kill_switch(
        tool_name: str, params: Dict[str, Any], context: Dict[str, Any]
    ) -> PolicyCheckResult:
        try:
            from trading.config.runtime import get_trading_runtime_config
            cfg = get_trading_runtime_config()
            state = cfg.get_state()
            if state.spectator_mode:
                return PolicyCheckResult(
                    verdict=PolicyVerdict.DENY,
                    reason="Spectator mode is active — trading blocked",
                    conditions_failed=["kill_switch"],
                )
        except Exception as exc:
            logger.debug(f"Kill switch check error (ignored): {exc}")
        return PolicyCheckResult(
            verdict=PolicyVerdict.ALLOW,
            conditions_met=["kill_switch_clear"],
        )

    @staticmethod
    def _check_config_change_approval(
        tool_name: str, params: Dict[str, Any], context: Dict[str, Any]
    ) -> PolicyCheckResult:
        return PolicyCheckResult(
            verdict=PolicyVerdict.REQUIRE_APPROVAL,
            reason=f"Config change via {tool_name} in live scope requires human approval",
            required_approvers=["operator"],
            conditions_failed=["requires_human_approval"],
        )

    @staticmethod
    def _check_order_rate_limit(
        tool_name: str, params: Dict[str, Any], context: Dict[str, Any]
    ) -> PolicyCheckResult:
        # Context carries the agent's order count from the capability store
        max_opm = context.get("max_orders_per_minute", 10)
        current_opm = context.get("orders_this_minute", 0)
        if current_opm >= max_opm:
            return PolicyCheckResult(
                verdict=PolicyVerdict.DENY,
                reason=f"Order rate limit: {current_opm}/{max_opm} orders/min",
                conditions_failed=["order_rate_limit"],
            )
        return PolicyCheckResult(
            verdict=PolicyVerdict.ALLOW,
            conditions_met=["order_rate_limit"],
        )


# ── Singleton ────────────────────────────────────────────────────────

_policy_engine: Optional[PolicyEngine] = None
_policy_engine_lock = threading.Lock()


def get_policy_engine() -> PolicyEngine:
    global _policy_engine
    if _policy_engine is None:
        with _policy_engine_lock:
            if _policy_engine is None:
                _policy_engine = PolicyEngine()
    return _policy_engine
