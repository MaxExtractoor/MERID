"""CapitalEngine ΓÇö Exponential money loop for the MERID Γåö Kalshi crypto system.

Manages three distinct capital buckets per the compounding architecture:

1. **Core vault** (protected compounding base)
   Never sized from directly.  Profits are swept here to lock in gains.

2. **Risk capital** (trading stack)
   The only bucket from which position sizes are drawn.
   Grows when profits are harvested, shrinks on losses.

3. **Growth bucket** (house-money)
   A slice of profits earmarked for high-conviction, higher-aggression bets.
   Uses a slightly higher Kelly multiplier but is still bounded.

Profit routing rules (per closed trade):
  - PnL > 0:
      to_core   = pnl * profit_sweep_pct_to_core
      to_growth = pnl * profit_sweep_pct_to_growth
      to_risk   = pnl - to_core - to_growth
  - PnL < 0:
      absorbed by risk capital first, then growth bucket; core is protected.

Drawdown guard:
  - If risk capital drops ΓëÑ drawdown_stepdown_threshold from its peak,
    a global sizing multiplier is reduced until recovery.

Periodic rebalance:
  - If risk capital exceeds a configured multiple of core, the excess is
    swept back into core (locks in gains, keeps risk stack bounded).

Usage::

    engine = CapitalEngine(total_equity=10_000.0)
    risk_cap = engine.get_risk_capital("BTC")
    allocated = engine.allocate_to_trade("BTC", proposed_size=200.0)
    engine.record_trade_result("BTC", realized_pnl=50.0)
    snap = engine.snapshot()
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.risk.capital_engine")


# ΓöÇΓöÇ Per-asset capital configuration ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

@dataclass
class AssetCapitalConfig:
    """Capital-management parameters for a single asset.

    All fractions are expressed relative to the asset's share of risk capital.
    """

    # Fraction of total equity that constitutes the "core vault" target.
    core_capital_target_pct: float = 0.60

    # Fraction of a winning trade's PnL swept into the core vault.
    profit_sweep_pct_to_core: float = 0.50

    # Fraction of a winning trade's PnL added to the growth bucket.
    profit_sweep_pct_to_growth: float = 0.25

    # Maximum fraction of risk capital used from the growth bucket per trade.
    growth_bucket_max_usage_pct: float = 0.10

    # Maximum fraction of risk capital allocated per trade for this asset.
    # CRITICAL: 1% per trade (3% worst case for 3 edges). 2% = 6% total = FORBIDDEN.
    max_risk_pct_per_trade: float = 0.01

    # Maximum fraction of total equity allocated to this asset across all positions.
    asset_max_risk_pct_of_total_equity: float = 0.15

    # Drawdown fraction (of risk-capital peak) that triggers step-down.
    drawdown_stepdown_threshold: float = 0.15

    # Sizing multiplier applied during drawdown (e.g. 0.5 = halve all sizes).
    drawdown_stepdown_multiplier: float = 0.60

    # Risk capital must recover to this fraction of its peak to restore full sizing.
    drawdown_recovery_threshold: float = 0.95

    # If risk capital exceeds this multiple of core, sweep excess back to core.
    risk_to_core_rebalance_multiple: float = 1.00

    def __post_init__(self) -> None:
        sweep_total = self.profit_sweep_pct_to_core + self.profit_sweep_pct_to_growth
        if sweep_total > 1.0:
            raise ValueError(
                f"profit_sweep_pct_to_core ({self.profit_sweep_pct_to_core}) + "
                f"profit_sweep_pct_to_growth ({self.profit_sweep_pct_to_growth}) "
                f"must not exceed 1.0"
            )

    @property
    def profit_recycle_pct_to_risk(self) -> float:
        """Fraction of profits recycled back into the risk stack (auto-compound)."""
        return 1.0 - self.profit_sweep_pct_to_core - self.profit_sweep_pct_to_growth


# ΓöÇΓöÇ Per-asset/timeframe risk budget ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

@dataclass
class RiskBudget:
    """Defines per-trade risk budget for one (asset, timeframe) combination.

    Attributes:
        asset:                       Asset symbol (e.g. "BTC").
        timeframe:                   Kalshi timeframe label (e.g. "intraday").
        max_risk_pct_risk_capital:   Max fraction of risk capital per trade.
        max_concurrent_positions:    Max simultaneously open positions.
    """

    asset: str
    timeframe: str
    max_risk_pct_risk_capital: float
    max_concurrent_positions: int


# ΓöÇΓöÇ Capital snapshot (for telemetry / UI) ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

@dataclass
class CapitalSnapshot:
    """Point-in-time view of all capital buckets and risk parameters.

    Designed to be JSON-serialisable for logging and UI display.
    """

    timestamp: float
    total_equity: float
    core_capital: float
    risk_capital: float
    growth_capital: float
    risk_capital_peak: float
    drawdown_pct: float
    sizing_multiplier: float
    per_asset_risk_capital: Dict[str, float]
    recent_pnl_routing: List[Dict]  # last N routing events for audit

    # Derived helpers ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

    @property
    def in_drawdown(self) -> bool:
        return self.sizing_multiplier < 1.0

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "total_equity": round(self.total_equity, 4),
            "core_capital": round(self.core_capital, 4),
            "risk_capital": round(self.risk_capital, 4),
            "growth_capital": round(self.growth_capital, 4),
            "risk_capital_peak": round(self.risk_capital_peak, 4),
            "drawdown_pct": round(self.drawdown_pct, 4),
            "sizing_multiplier": round(self.sizing_multiplier, 4),
            "in_drawdown": self.in_drawdown,
            "per_asset_risk_capital": {
                k: round(v, 4) for k, v in self.per_asset_risk_capital.items()
            },
        }


# ΓöÇΓöÇ Default per-asset configs ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

def _default_asset_configs() -> Dict[str, AssetCapitalConfig]:
    """Conservative defaults per asset with tighter limits for volatile coins."""
    return {
        "BTC": AssetCapitalConfig(
            core_capital_target_pct=0.60,
            profit_sweep_pct_to_core=0.50,
            profit_sweep_pct_to_growth=0.25,
            growth_bucket_max_usage_pct=0.10,
            max_risk_pct_per_trade=0.020,
            asset_max_risk_pct_of_total_equity=0.30,
            drawdown_stepdown_threshold=0.15,
            drawdown_stepdown_multiplier=0.60,
            drawdown_recovery_threshold=0.95,
            risk_to_core_rebalance_multiple=1.00,
        ),
        "ETH": AssetCapitalConfig(
            core_capital_target_pct=0.60,
            profit_sweep_pct_to_core=0.50,
            profit_sweep_pct_to_growth=0.25,
            growth_bucket_max_usage_pct=0.10,
            max_risk_pct_per_trade=0.020,
            asset_max_risk_pct_of_total_equity=0.25,
            drawdown_stepdown_threshold=0.15,
            drawdown_stepdown_multiplier=0.60,
            drawdown_recovery_threshold=0.95,
            risk_to_core_rebalance_multiple=1.00,
        ),
        "SOL": AssetCapitalConfig(
            core_capital_target_pct=0.65,
            profit_sweep_pct_to_core=0.55,
            profit_sweep_pct_to_growth=0.20,
            growth_bucket_max_usage_pct=0.08,
            max_risk_pct_per_trade=0.015,
            asset_max_risk_pct_of_total_equity=0.15,
            drawdown_stepdown_threshold=0.12,
            drawdown_stepdown_multiplier=0.55,
            drawdown_recovery_threshold=0.95,
            risk_to_core_rebalance_multiple=0.80,
        ),
        "XRP": AssetCapitalConfig(
            core_capital_target_pct=0.65,
            profit_sweep_pct_to_core=0.55,
            profit_sweep_pct_to_growth=0.20,
            growth_bucket_max_usage_pct=0.08,
            max_risk_pct_per_trade=0.015,
            asset_max_risk_pct_of_total_equity=0.15,
            drawdown_stepdown_threshold=0.12,
            drawdown_stepdown_multiplier=0.55,
            drawdown_recovery_threshold=0.95,
            risk_to_core_rebalance_multiple=0.80,
        ),
        "DOGE": AssetCapitalConfig(
            core_capital_target_pct=0.70,
            profit_sweep_pct_to_core=0.60,
            profit_sweep_pct_to_growth=0.15,
            growth_bucket_max_usage_pct=0.06,
            max_risk_pct_per_trade=0.010,
            asset_max_risk_pct_of_total_equity=0.10,
            drawdown_stepdown_threshold=0.10,
            drawdown_stepdown_multiplier=0.50,
            drawdown_recovery_threshold=0.95,
            risk_to_core_rebalance_multiple=0.80,
        ),
    }


def _default_risk_budgets() -> List[RiskBudget]:
    """Default per-(asset, timeframe) risk budgets.

    Intraday BTC/ETH allows up to 2ΓÇô3% of risk capital per trade;
    weekly/monthly up to 5% but fewer concurrent positions.
    Noisier assets (DOGE, XRP) get tighter per-trade caps.
    """
    budgets: List[RiskBudget] = []

    # BTC ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    budgets.extend([
        RiskBudget("BTC", "scalp",    max_risk_pct_risk_capital=0.020, max_concurrent_positions=3),
        RiskBudget("BTC", "intraday", max_risk_pct_risk_capital=0.025, max_concurrent_positions=5),
        RiskBudget("BTC", "swing",    max_risk_pct_risk_capital=0.050, max_concurrent_positions=2),
    ])
    # ETH ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    budgets.extend([
        RiskBudget("ETH", "scalp",    max_risk_pct_risk_capital=0.020, max_concurrent_positions=3),
        RiskBudget("ETH", "intraday", max_risk_pct_risk_capital=0.025, max_concurrent_positions=5),
        RiskBudget("ETH", "swing",    max_risk_pct_risk_capital=0.050, max_concurrent_positions=2),
    ])
    # SOL ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    budgets.extend([
        RiskBudget("SOL", "scalp",    max_risk_pct_risk_capital=0.015, max_concurrent_positions=2),
        RiskBudget("SOL", "intraday", max_risk_pct_risk_capital=0.020, max_concurrent_positions=4),
        RiskBudget("SOL", "swing",    max_risk_pct_risk_capital=0.040, max_concurrent_positions=2),
    ])
    # XRP ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    budgets.extend([
        RiskBudget("XRP", "scalp",    max_risk_pct_risk_capital=0.015, max_concurrent_positions=2),
        RiskBudget("XRP", "intraday", max_risk_pct_risk_capital=0.020, max_concurrent_positions=4),
        RiskBudget("XRP", "swing",    max_risk_pct_risk_capital=0.040, max_concurrent_positions=2),
    ])
    # DOGE ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    budgets.extend([
        RiskBudget("DOGE", "scalp",    max_risk_pct_risk_capital=0.010, max_concurrent_positions=2),
        RiskBudget("DOGE", "intraday", max_risk_pct_risk_capital=0.015, max_concurrent_positions=3),
        RiskBudget("DOGE", "swing",    max_risk_pct_risk_capital=0.030, max_concurrent_positions=2),
    ])
    return budgets


# ΓöÇΓöÇ CapitalEngine ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

class CapitalEngine:
    """Manages the three-bucket capital model and the exponential money loop.

    Args:
        total_equity:          Starting total equity (risk + core + growth).
        asset_configs:         Per-asset capital parameters.  Defaults to
                               conservative values for all five crypto assets.
        risk_budgets:          Per-(asset, timeframe) risk budget table.
        initial_risk_fraction: Fraction of total_equity placed into the risk
                               stack at initialisation (remainder goes to core).
        pnl_routing_log_size:  Number of routing events to keep in memory for
                               audit / snapshot display.
    """

    def __init__(
        self,
        total_equity: float = 10_000.0,
        asset_configs: Optional[Dict[str, AssetCapitalConfig]] = None,
        risk_budgets: Optional[List[RiskBudget]] = None,
        initial_risk_fraction: float = 0.40,
        pnl_routing_log_size: int = 50,
    ) -> None:
        if total_equity <= 0:
            raise ValueError("total_equity must be positive")
        if not (0 < initial_risk_fraction < 1):
            raise ValueError("initial_risk_fraction must be in (0, 1)")

        self._asset_configs: Dict[str, AssetCapitalConfig] = (
            asset_configs or _default_asset_configs()
        )
        # Index risk budgets by (asset, timeframe)
        raw_budgets = risk_budgets or _default_risk_budgets()
        self._risk_budgets: Dict[Tuple[str, str], RiskBudget] = {
            (b.asset, b.timeframe): b for b in raw_budgets
        }

        # ΓöÇΓöÇ Bucket initialisation ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
        self._risk_capital: float = total_equity * initial_risk_fraction
        self._growth_capital: float = 0.0
        self._core_capital: float = total_equity * (1.0 - initial_risk_fraction)

        # ΓöÇΓöÇ Drawdown tracking ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
        self._risk_capital_peak: float = self._risk_capital
        self._sizing_multiplier: float = 1.0  # 1.0 = full; < 1.0 = drawdown step-down

        # ΓöÇΓöÇ Audit log ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
        self._pnl_routing_log: List[Dict] = []
        self._pnl_routing_log_size = pnl_routing_log_size

        logger.info(
            "CapitalEngine initialised: total_equity=%.2f core=%.2f risk=%.2f growth=%.2f",
            total_equity, self._core_capital, self._risk_capital, self._growth_capital,
        )

    # ΓöÇΓöÇ Public read API ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

    @property
    def core_capital(self) -> float:
        """Core vault balance (protected, not used for sizing)."""
        return self._core_capital

    @property
    def risk_capital(self) -> float:
        """Risk stack balance (used for position sizing)."""
        return self._risk_capital

    @property
    def growth_capital(self) -> float:
        """Growth / house-money bucket balance."""
        return self._growth_capital

    @property
    def total_equity(self) -> float:
        """Sum of all three buckets."""
        return self._core_capital + self._risk_capital + self._growth_capital

    @property
    def sizing_multiplier(self) -> float:
        """Current drawdown-based global sizing multiplier (0ΓÇô1)."""
        return self._sizing_multiplier

    # ΓöÇΓöÇ Primary interface ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

    def get_risk_capital(self, asset: str) -> float:
        """Return the effective risk capital available for sizing *asset*.

        Applies asset-level equity cap and the current drawdown multiplier.

        Args:
            asset: Asset symbol (e.g. ``"BTC"``).

        Returns:
            Effective risk capital in the same currency as total_equity.
        """
        cfg = self._asset_configs.get(asset)
        if cfg is None:
            logger.warning("CapitalEngine: unknown asset %r ΓÇö returning zero risk capital", asset)
            return 0.0

        # Hard cap: never let a single asset consume more than its equity limit.
        asset_equity_cap = self.total_equity * cfg.asset_max_risk_pct_of_total_equity
        effective = min(self._risk_capital, asset_equity_cap)

        # Apply global drawdown multiplier.
        return effective * self._sizing_multiplier

    def allocate_to_trade(
        self,
        asset: str,
        suggested_size: float,
        *,
        timeframe: str = "intraday",
        use_growth_bucket: bool = False,
        conviction: float = 0.0,
    ) -> float:
        """Cap *suggested_size* according to per-asset and per-timeframe risk budgets.

        For very high conviction trades (``conviction >= 0.8``) an additional
        fraction from the growth bucket may be added, subject to its own cap.

        Args:
            asset:           Asset symbol.
            suggested_size:  Size proposed by the Kelly/strategy sizing layer.
            timeframe:       Kalshi timeframe label (``"scalp"``, ``"intraday"``,
                             ``"swing"``).
            use_growth_bucket: Allow extra growth-bucket contribution when True
                             AND conviction is high enough.
            conviction:      Structural conviction score (0ΓÇô1).  Values ΓëÑ 0.8
                             unlock growth-bucket extra size.

        Returns:
            Final allocated size (ΓëÑ 0, never exceeds risk budgets).
        """
        cfg = self._asset_configs.get(asset)
        if cfg is None:
            return 0.0

        risk_cap = self.get_risk_capital(asset)

        # Per-trade cap from asset config
        per_trade_cap = risk_cap * cfg.max_risk_pct_per_trade

        # Per-(asset, timeframe) risk budget cap
        budget = self._risk_budgets.get((asset, timeframe))
        if budget is not None:
            budget_cap = risk_cap * budget.max_risk_pct_risk_capital
            per_trade_cap = min(per_trade_cap, budget_cap)

        final_size = min(suggested_size, per_trade_cap)

        # Optional growth-bucket supplement for high-conviction trades
        if use_growth_bucket and conviction >= 0.8 and self._growth_capital > 0:
            extra_cap = self._growth_capital * cfg.growth_bucket_max_usage_pct
            growth_extra = min(suggested_size * 0.15, extra_cap)
            final_size += growth_extra
            logger.debug(
                "CapitalEngine [%s]: growth-bucket extra %.4f (conviction=%.2f)",
                asset, growth_extra, conviction,
            )

        return max(0.0, final_size)

    def record_trade_result(self, asset: str, realized_pnl: float) -> None:
        """Update capital buckets after a trade is closed.

        Positive PnL is routed to core, growth, and risk buckets per config.
        Negative PnL is absorbed by risk capital first, then growth bucket.
        Core capital is **never** reduced by routine losses.

        Args:
            asset:        Asset symbol.
            realized_pnl: Realised profit (positive) or loss (negative).
        """
        cfg = self._asset_configs.get(asset)
        if cfg is None:
            logger.warning("CapitalEngine.record_trade_result: unknown asset %r", asset)
            return

        routing_event: Dict = {
            "ts": time.time(),
            "asset": asset,
            "realized_pnl": realized_pnl,
            "to_core": 0.0,
            "to_growth": 0.0,
            "to_risk": 0.0,
        }

        if realized_pnl > 0:
            to_core = realized_pnl * cfg.profit_sweep_pct_to_core
            to_growth = realized_pnl * cfg.profit_sweep_pct_to_growth
            to_risk = realized_pnl - to_core - to_growth  # auto-compound fraction

            self._core_capital += to_core
            self._growth_capital += to_growth
            self._risk_capital += to_risk

            routing_event.update(to_core=to_core, to_growth=to_growth, to_risk=to_risk)

            logger.debug(
                "CapitalEngine [%s] profit +%.4f ΓåÆ core +%.4f growth +%.4f risk +%.4f",
                asset, realized_pnl, to_core, to_growth, to_risk,
            )

        elif realized_pnl < 0:
            loss = abs(realized_pnl)

            # Absorb from risk capital first
            absorbed_by_risk = min(loss, self._risk_capital)
            self._risk_capital -= absorbed_by_risk
            remaining_loss = loss - absorbed_by_risk

            # Any residual comes from growth bucket
            absorbed_by_growth = min(remaining_loss, self._growth_capital)
            self._growth_capital -= absorbed_by_growth

            routing_event.update(
                to_risk=-absorbed_by_risk,
                to_growth=-absorbed_by_growth,
            )

            logger.debug(
                "CapitalEngine [%s] loss -%.4f ΓåÆ risk -%.4f growth -%.4f",
                asset, loss, absorbed_by_risk, absorbed_by_growth,
            )

        # Clamp to zero (safety guard against floating-point underflow)
        self._risk_capital = max(0.0, self._risk_capital)
        self._growth_capital = max(0.0, self._growth_capital)

        # Append to audit log
        self._pnl_routing_log.append(routing_event)
        if len(self._pnl_routing_log) > self._pnl_routing_log_size:
            self._pnl_routing_log.pop(0)

        # Update drawdown tracking and sizing multiplier
        self._update_drawdown_state(asset)

    def rebalance_core(self, asset_hint: Optional[str] = None) -> float:
        """Periodic rebalance: sweep excess risk capital back into core.

        If ``risk_capital > core_capital * risk_to_core_rebalance_multiple``
        for any configured asset, the excess is moved to core to lock in gains.

        This should be called periodically (e.g. once per day or per heartbeat).

        Args:
            asset_hint: Optional asset for config look-up (uses first registered
                        asset config when None).

        Returns:
            Amount swept to core (0 if no rebalance was needed).
        """
        # Use the most conservative multiple across all asset configs
        min_multiple = min(
            c.risk_to_core_rebalance_multiple for c in self._asset_configs.values()
        )
        threshold = self._core_capital * min_multiple
        swept = 0.0

        if self._risk_capital > threshold:
            excess = self._risk_capital - threshold
            self._risk_capital -= excess
            self._core_capital += excess
            swept = excess
            logger.info(
                "CapitalEngine.rebalance_core: swept %.4f to core (core=%.4f risk=%.4f)",
                swept, self._core_capital, self._risk_capital,
            )

        return swept

    def snapshot(self) -> CapitalSnapshot:
        """Return a point-in-time snapshot of all capital state.

        Suitable for logging, monitoring APIs, and UI display.
        """
        risk_peak = self._risk_capital_peak
        drawdown = 0.0
        if risk_peak > 0:
            drawdown = max(0.0, (risk_peak - self._risk_capital) / risk_peak)

        per_asset: Dict[str, float] = {
            asset: self.get_risk_capital(asset)
            for asset in self._asset_configs
        }

        return CapitalSnapshot(
            timestamp=time.time(),
            total_equity=self.total_equity,
            core_capital=self._core_capital,
            risk_capital=self._risk_capital,
            growth_capital=self._growth_capital,
            risk_capital_peak=risk_peak,
            drawdown_pct=drawdown,
            sizing_multiplier=self._sizing_multiplier,
            per_asset_risk_capital=per_asset,
            recent_pnl_routing=list(self._pnl_routing_log[-10:]),
        )

    def get_risk_budget(self, asset: str, timeframe: str) -> Optional[RiskBudget]:
        """Return the risk budget for *(asset, timeframe)*, or ``None`` if not found."""
        return self._risk_budgets.get((asset, timeframe))

    # ΓöÇΓöÇ Internal helpers ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

    def _update_drawdown_state(self, asset: str) -> None:
        """Update the peak tracker and drawdown-aware sizing multiplier."""
        cfg = self._asset_configs.get(asset)

        # Update peak
        if self._risk_capital > self._risk_capital_peak:
            self._risk_capital_peak = self._risk_capital

        # Compute current drawdown fraction
        if self._risk_capital_peak <= 0:
            return

        drawdown_frac = (self._risk_capital_peak - self._risk_capital) / self._risk_capital_peak

        if cfg is None:
            return

        # Apply or release step-down
        if drawdown_frac >= cfg.drawdown_stepdown_threshold:
            if self._sizing_multiplier == 1.0:
                logger.warning(
                    "CapitalEngine [%s]: drawdown %.1f%% ΓëÑ threshold %.1f%% ΓÇö "
                    "step-down sizing to %.0f%%",
                    asset,
                    drawdown_frac * 100,
                    cfg.drawdown_stepdown_threshold * 100,
                    cfg.drawdown_stepdown_multiplier * 100,
                )
            self._sizing_multiplier = cfg.drawdown_stepdown_multiplier
        else:
            recovery_frac = self._risk_capital / self._risk_capital_peak
            if recovery_frac >= cfg.drawdown_recovery_threshold and self._sizing_multiplier < 1.0:
                self._sizing_multiplier = 1.0
                logger.info(
                    "CapitalEngine [%s]: risk capital recovered to %.1f%% of peak ΓÇö "
                    "restoring full sizing",
                    asset, recovery_frac * 100,
                )

    def check_drawdown_recovery(self, asset: str) -> bool:
        """Force check drawdown recovery regardless of recent trade activity.
        
        P2-5 FIX: This allows drawdown recovery to fire after kill switch reset,
        even if the kill switch was triggered by manual or daily-loss reasons
        rather than drawdown.
        
        Returns:
            True if sizing multiplier was restored to 1.0
        """
        if asset not in self._asset_configs:
            return False
        cfg = self._asset_configs[asset]
        recovery_frac = self._risk_capital / self._risk_capital_peak
        if recovery_frac >= cfg.drawdown_recovery_threshold and self._sizing_multiplier < 1.0:
            self._sizing_multiplier = 1.0
            logger.info(
                "CapitalEngine [%s]: forced recovery check ΓÇö risk capital at %.1f%% of peak, "
                "restoring full sizing",
                asset, recovery_frac * 100,
            )
            return True
        return False
