"""
Adaptive risk limits based on market regime.

Monitors realized volatility, liquidity, and recent PnL to automatically adjust
exposure caps and kill-switch thresholds for HFT agents.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict


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
        position_cap = max(50_000, 1_000_000 / (1 + regime.volatility))
        drawdown = min(10.0, 5.0 + regime.volatility * 5)
        kill_threshold = 3.0 if regime.pnl_trend < 0 else 5.0
        limits = RiskLimits(
            agent_id=agent_id,
            max_position_usd=position_cap * regime.liquidity_score,
            max_drawdown_pct=drawdown,
            kill_switch_threshold=kill_threshold,
            updated_at=datetime.utcnow(),
        )
        self._limits[agent_id] = limits
        return limits

    def get_limits(self, agent_id: str) -> RiskLimits | None:
        return self._limits.get(agent_id)
