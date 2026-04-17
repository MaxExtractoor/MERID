"""
Social Strategy Router
Bridges strategy metadata, social-aware quant engine, and multi-agent risk controls.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from governance.multi_agent_risk_controls import get_multi_agent_risk_controls
from social.social_aware_quant import get_social_aware_quant_engine
from utils.logger import get_logger
from core.strategy_versioning import StrategyVersion, get_version_registry
from latency_optimizer.orchestrator_hooks import record_social_signal

logger = get_logger("core.social_strategy_router")


def evaluate_social_trade(
    strategy_id: str,
    asset: str,
    portfolio_value: float,
    sentiment_score: float,
    *,
    version: Optional[str] = None,
    agent_id: Optional[str] = None,
    market_metrics: Optional[Dict[str, float]] = None,
    latency_decision_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Evaluate a potential social-driven trade.

    Returns dict with:
        allowed: bool
        reasons: List[str]
        sizing: Dict[str, Any]
        constraints: Dict[str, Any]
    """
    registry = get_version_registry()
    if version:
        strategy = registry.get_version(strategy_id, version)
    else:
        strategy = registry.get_active_version(strategy_id)

    if not strategy:
        return {
            "allowed": False,
            "reasons": [f"Strategy {strategy_id} version not found"],
        }

    if not strategy.is_social_strategy:
        return {
            "allowed": False,
            "reasons": [f"Strategy {strategy_id} is not registered as social-aware"],
        }

    social_engine = get_social_aware_quant_engine()
    market_metrics = market_metrics or {}
    metadata = {
        "strategy_id": strategy_id,
        "asset": asset,
        "version": version or "active",
    }
    with record_social_signal(metadata, decision_key=latency_decision_key):
        sizing = social_engine.evaluate_trade_request(
            asset=asset,
            portfolio_value=portfolio_value,
            sentiment_score=sentiment_score,
            market_metrics=market_metrics,
        )
    sizing["portfolio_value"] = portfolio_value

    risk_controls = get_multi_agent_risk_controls()
    violations: List[str] = []

    if not sizing.get("allowed", True):
        reason = sizing.get("reason")
        if reason:
            violations.append(reason)

    approved, control_violations = risk_controls.validate_social_constraints(
        strategy=strategy,
        sizing_result=sizing,
    )
    violations.extend(control_violations)

    if approved:
        size_usd = sizing.get("size_usd", 0.0)
        if size_usd > 0:
            social_engine.register_position_allocation(asset, size_usd)
            confirmation = sizing.get("confirmation") or {}
            if hasattr(confirmation, "confirmation_score"):
                confirmation_score = confirmation.confirmation_score
            else:
                confirmation_score = confirmation.get("confirmation_score") if isinstance(confirmation, dict) else None
            risk_controls.register_social_trade(
                agent_id=agent_id or strategy_id,
                strategy_id=strategy_id,
                asset=asset,
                size_usd=size_usd,
                metadata={
                    "sentiment_score": sentiment_score,
                    "confirmation_score": confirmation_score,
                },
            )

    return {
        "allowed": approved and not violations,
        "reasons": violations,
        "sizing": sizing,
        "constraints": sizing.get("constraints", {}),
    }


def release_social_position(asset: str, size_usd: float) -> None:
    """Release tracked social exposure when a position is closed."""
    social_engine = get_social_aware_quant_engine()
    social_engine.release_position_allocation(asset, size_usd)
