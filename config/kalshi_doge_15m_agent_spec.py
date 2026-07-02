"""
DOGE 15m Agent Specification for MERID KalshiGrid

Regime-aware DOGE up/down trades on Kalshi 15m contracts.
Cloned from BTC 15m pattern with DOGE-specific parameters.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List


@dataclass
class Doge15mAgentSpec:
    agent_id: str = "doge_15m_regime"
    name: str = "DOGE 15m Regime Trader"
    description: str = "Regime-aware DOGE up/down trades on Kalshi 15m contracts"

    # Market scope
    target_markets: List[str] = field(default_factory=lambda: ["KXDOGEUPDOWN-15M"])
    max_concurrent_positions: int = 1
    max_daily_trades: int = 20

    # Risk parameters
    max_position_size_pct: float = 0.0025
    max_crypto_exposure_pct: float = 0.05
    stop_loss_pct: float = -0.005
    take_profit_pct: float = 0.01
    daily_dd_limit_pct: float = -0.02

    # Entry filters
    min_edge_threshold: float = 0.012
    max_vol_ratio: float = 2.0
    min_time_to_expiry: int = 120
    max_time_to_expiry: int = 900
    min_regime_confidence: float = 0.5
    regime_window_minutes: int = 15


@dataclass
class Doge15mInputs:
    rti_current: float
    rti_60s_sma: float

    vol_1m_realized: float
    vol_5m_realized: float
    vol_15m_realized: float
    vol_baseline_median: float

    market_id: str
    strike_price: float
    time_to_expiry: int
    orderbook_bid: float
    orderbook_ask: float

    doge_15m_regime_signal: Dict[str, Any]

    crypto_vol_alert_active: bool
    current_position_size: float
    daily_pnl: float


class Doge15mSignalGenerator:
    def __init__(self, spec: Doge15mAgentSpec):
        self.spec = spec

    def generate_signal(self, inputs: Doge15mInputs) -> Optional[Dict[str, Any]]:
        if inputs.crypto_vol_alert_active:
            return None

        if inputs.current_position_size >= self.spec.max_crypto_exposure_pct:
            return None

        if inputs.vol_5m_realized > self.spec.max_vol_ratio * inputs.vol_baseline_median:
            return None

        if inputs.time_to_expiry < self.spec.min_time_to_expiry:
            return None

        if inputs.time_to_expiry > self.spec.max_time_to_expiry:
            return None

        regime = inputs.doge_15m_regime_signal
        if regime.get("confidence", 0) < self.spec.min_regime_confidence:
            return None
        if regime.get("regime") == "chop":
            return None

        edge = regime.get("edge_estimate", 0.0)
        if edge < self.spec.min_edge_threshold:
            return None

        direction = regime.get("direction")
        if not direction:
            return None

        kelly_fraction = min(1.0, edge / 0.1)
        position_size = kelly_fraction * self.spec.max_position_size_pct

        return {
            "action": "buy" if direction == "up" else "sell",
            "market_id": inputs.market_id,
            "size_pct": position_size,
            "reason": f"Regime: {regime['regime']}, Edge: {edge:.3f}",
            "stop_loss_pct": self.spec.stop_loss_pct,
            "take_profit_pct": self.spec.take_profit_pct,
            "edge_estimate": edge,
            "regime_confidence": regime.get("confidence", 0.0),
        }


class Doge15mRiskRules:
    def __init__(self, spec: Doge15mAgentSpec):
        self.spec = spec

    def pre_trade_check(self, signal: Dict[str, Any], inputs: Doge15mInputs) -> Dict[str, Any]:
        allowed, reason = True, ""

        if inputs.current_position_size + signal["size_pct"] > self.spec.max_crypto_exposure_pct:
            allowed, reason = False, "Would exceed crypto exposure limit"

        if getattr(inputs, "daily_trade_count", 0) >= self.spec.max_daily_trades:
            allowed, reason = False, "Daily trade limit reached"

        if inputs.daily_pnl < self.spec.daily_dd_limit_pct:
            allowed, reason = False, "Daily drawdown limit reached"

        return {
            "allowed": allowed,
            "reason": reason,
            "adjusted_size_pct": signal["size_pct"] if allowed else 0.0,
        }


# Integration points
DOGE_15M_AGENT_SPEC = Doge15mAgentSpec()
DOGE_15M_SIGNAL_GENERATOR = Doge15mSignalGenerator(DOGE_15M_AGENT_SPEC)
DOGE_15M_RISK_RULES = Doge15mRiskRules(DOGE_15M_AGENT_SPEC)
