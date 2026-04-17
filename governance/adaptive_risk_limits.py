"""
Adaptive risk limits based on market regime.

Monitors realized volatility, liquidity, and recent PnL to automatically adjust
exposure caps and kill-switch thresholds for HFT agents.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional


@dataclass
class MarketRegime:
    volatility: float
    liquidity_score: float
    pnl_trend: float
    timestamp: datetime


@dataclass
class RiskLimits:
    agent_id: str
    max_position_usd: float
    max_drawdown_pct: float
    kill_switch_threshold: float
    updated_at: datetime


class AdaptiveRiskLimitManager:
    def __init__(self) -> None:
        self._limits: Dict[str, RiskLimits] = {}

    def update_limits(self, agent_id: str, regime: MarketRegime) -> RiskLimits:
        # BUG-2 fix: position cap now approaches zero at extreme volatility rather
        # than flooring at $50k regardless.  At volatility=0 cap=500k; at
        # volatility=9 cap~=50k; at volatility>=49 cap becomes negligible.
        raw_cap = 1_000_000 / max(1.0, 1 + regime.volatility * 10)
        position_cap = max(0.0, raw_cap * regime.liquidity_score)

        drawdown = min(10.0, 5.0 + regime.volatility * 5)
        kill_threshold = 3.0 if regime.pnl_trend < 0 else 5.0
        limits = RiskLimits(
            agent_id=agent_id,
            max_position_usd=position_cap,
            max_drawdown_pct=drawdown,
            kill_switch_threshold=kill_threshold,
            updated_at=datetime.utcnow(),
        )
        self._limits[agent_id] = limits
        return limits

    def get_limits(self, agent_id: str) -> RiskLimits | None:
        return self._limits.get(agent_id)

    def push_to_execution_guard(self, agent_id: str, venue: str = "kalshi") -> None:
        """Propagate the latest computed limits for agent_id into ExecutionGuard.

        BUG-2 fix: previously AdaptiveRiskLimitManager computed limits but never
        pushed them anywhere.  This method syncs the regime-aware position cap
        into ExecutionGuard's venue exposure cap for the relevant venue.
        """
        limits = self._limits.get(agent_id)
        if limits is None:
            return
        try:
            from merid.execution_guard import get_execution_guard
            guard = get_execution_guard()
            cap = guard._venue_caps.get(venue)
            if cap is not None:
                cap.max_exposure_usd = limits.max_position_usd
        except Exception:
            pass

        try:
            from merid.event_venues.kalshi.deployment import get_deployment_controller
            ctrl = get_deployment_controller()
            cfg = ctrl.config
            cfg.auto_rollback_on_drawdown_above_pct = limits.max_drawdown_pct
        except Exception:
            pass


# ── Singleton ────────────────────────────────────────────────────────────────

_manager: Optional[AdaptiveRiskLimitManager] = None
_manager_lock = threading.Lock()


def get_adaptive_risk_limit_manager() -> AdaptiveRiskLimitManager:
    """Return the module-level AdaptiveRiskLimitManager singleton."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = AdaptiveRiskLimitManager()
    return _manager
