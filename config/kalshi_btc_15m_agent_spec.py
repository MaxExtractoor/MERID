"""
BTC 15m Up/Down Agent Specification for MERID KalshiGrid

Concrete agent spec that slots into existing KalshiGrid and PortfolioRiskAgent.
Focuses on regime-aware direction bets with tight EV and vol-filtered entries.
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

# ── Agent Identity ─────────────────────────────────────────────────────────────

@dataclass
class Btc15mAgentSpec:
    """BTC 15m Kalshi agent configuration."""
    agent_id: str = "btc_15m_regime"
    name: str = "BTC 15m Regime Trader"
    description: str = "Regime-aware BTC up/down trades on Kalshi 15m contracts"

    # Market scope
    target_markets: List[str] = field(default_factory=lambda: ["KXBTUPDOWN-15M"])  # Current 15m BTC up/down contract
    max_concurrent_positions: int = 1  # Only trade one 15m market at a time
    max_daily_trades: int = 20  # Conservative limit

    # Risk parameters
    max_position_size_pct: float = 0.0025  # 0.25% of Kalshi equity per trade
    max_crypto_exposure_pct: float = 0.05  # 5% of Kalshi equity in crypto 15m
    stop_loss_pct: float = -0.005  # -0.5% stop loss (per position)
    take_profit_pct: float = 0.01  # +1% take profit (per position)
    daily_dd_limit_pct: float = -0.02  # -2% daily drawdown limit

    # Entry filters
    min_edge_threshold: float = 0.05  # Only trade if model EV > 5¢ per contract
    max_vol_ratio: float = 2.0  # Skip if 5m realized vol > 2x baseline
    min_time_to_expiry: int = 300  # Don't enter last 5 minutes
    max_time_to_expiry: int = 600  # Only trade first 10 minutes

    # Regime confidence thresholds
    min_regime_confidence: float = 0.7  # Require strong regime signal
    regime_window_minutes: int = 15  # Look at last 15m for regime

# ── Input Feeds ──────────────────────────────────────────────────────────────

@dataclass
class Btc15mInputs:
    """Real-time inputs for BTC 15m agent."""

    # CFB RTI feed (60s settlement basis)
    rti_current: float
    rti_60s_sma: float  # Rolling 60s average for settlement projection

    # Volatility metrics (RTI-based)
    vol_1m_realized: float
    vol_5m_realized: float
    vol_15m_realized: float
    vol_baseline_median: float  # 30-day median for comparison

    # Kalshi market data
    market_id: str
    strike_price: float
    time_to_expiry: int  # seconds
    orderbook_bid: float
    orderbook_ask: float

    # MERID internal signals
    btc_15m_regime_signal: Dict[str, Any]  # From BTC 15m lane
    # {
    #   "regime": "trend_up" | "trend_down" | "chop" | "mean_reversion",
    #   "confidence": 0.8,
    #   "direction": "up" | "down",
    #   "edge_estimate": 0.06  # Expected EV per contract
    # }

    # Risk state
    crypto_vol_alert_active: bool  # From risk stream crypto_vol_spike
    current_position_size: float
    daily_pnl: float

# ── Signal Generation ─────────────────────────────────────────────────────────

class Btc15mSignalGenerator:
    """Generates trading signals for BTC 15m contracts."""

    def __init__(self, spec: Btc15mAgentSpec):
        self.spec = spec

    def generate_signal(self, inputs: Btc15mInputs) -> Optional[Dict[str, Any]]:
        """Generate trading signal based on regime and filters."""

        # 1. Risk filters (fail fast)
        if inputs.crypto_vol_alert_active:
            return None  # Skip during vol spikes

        if inputs.current_position_size >= self.spec.max_crypto_exposure_pct:
            return None  # Respect exposure limits

        if inputs.vol_5m_realized > self.spec.max_vol_ratio * inputs.vol_baseline_median:
            return None  # Too volatile

        if inputs.time_to_expiry < self.spec.min_time_to_expiry:
            return None  # Too close to expiry

        if inputs.time_to_expiry > self.spec.max_time_to_expiry:
            return None  # Too early

        # 2. Regime analysis
        regime = inputs.btc_15m_regime_signal

        if regime.get("confidence", 0) < self.spec.min_regime_confidence:
            return None  # Not confident enough

        if regime.get("regime") == "chop":
            return None  # Skip choppy regimes

        edge = regime.get("edge_estimate", 0)
        if edge < self.spec.min_edge_threshold:
            return None  # EV too low

        # 3. Direction and sizing
        direction = regime.get("direction")
        if not direction:
            return None

        # Calculate position size
        # Kelly fraction scales from 0 to 1.0 of the max_position_size_pct cap
        kelly_fraction = min(1.0, edge / 0.1)  # full cap when edge >= 10¢
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

# ── Risk Rules Integration ───────────────────────────────────────────────────

class Btc15mRiskRules:
    """Risk management rules for BTC 15m trading."""

    def __init__(self, spec: Btc15mAgentSpec):
        self.spec = spec

    def pre_trade_check(self, signal: Dict[str, Any], inputs: Btc15mInputs) -> Dict[str, Any]:
        """Validate signal against risk rules."""

        allowed, reason = True, ""

        # Position limits
        if inputs.current_position_size + signal["size_pct"] > self.spec.max_crypto_exposure_pct:
            allowed = False
            reason = "Would exceed crypto exposure limit"

        # Daily trade limit
        if hasattr(inputs, 'daily_trade_count') and inputs.daily_trade_count >= self.spec.max_daily_trades:
            allowed = False
            reason = "Daily trade limit reached"

        # Daily drawdown check
        if inputs.daily_pnl < self.spec.daily_dd_limit_pct:
            allowed = False
            reason = "Daily drawdown limit reached"

        return {
            "allowed": allowed,
            "reason": reason,
            "adjusted_size_pct": signal["size_pct"] if allowed else 0,
        }

    def post_trade_rules(self, position: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate risk alerts based on position."""

        alerts = []

        # Monitor for quick reversals (15m contracts are fast)
        if position.get("unrealized_pnl", 0) < self.spec.stop_loss_pct:
            alerts.append({
                "type": "position_stop_loss",
                "severity": "warning",
                "message": f"BTC 15m position hit stop loss: {position['unrealized_pnl']:.1%}",
                "action": "close_position"
            })

        return alerts

# ── Integration Points ───────────────────────────────────────────────────────

# 1. Add to KalshiGrid agent registry
BTC_15M_AGENT_SPEC = Btc15mAgentSpec()
BTC_15M_SIGNAL_GENERATOR = Btc15mSignalGenerator(BTC_15M_AGENT_SPEC)
BTC_15M_RISK_RULES = Btc15mRiskRules(BTC_15M_AGENT_SPEC)

# 2. Wire into PortfolioRiskAgent
# - Monitor crypto_vol_spike alerts
# - Enforce max_crypto_exposure_pct
# - Track 15m-specific drawdown limits

# 3. Wire into KalshiGrid agent cycle
# - Feed Btc15mInputs to signal generator
# - Apply risk rules pre-trade
# - Submit opinions to consensus with crypto category

# 4. UI Integration
# - Show BTC 15m positions in crypto sub-view
# - Display regime confidence and vol metrics
# - Highlight when vol alerts block trading

# Example usage in agent cycle:
"""
def run_btc_15m_cycle(self, inputs: Btc15mInputs):
    signal = BTC_15M_SIGNAL_GENERATOR.generate_signal(inputs)
    if not signal:
        return None

    risk_check = BTC_15M_RISK_RULES.pre_trade_check(signal, inputs)
    if not risk_check["allowed"]:
        return None

    # Submit to consensus
    opinion = AgentOpinion(
        agent_id=BTC_15M_AGENT_SPEC.agent_id,
        symbol=signal["market_id"],
        venue="kalshi",
        category="crypto",
        # ... rest of opinion
    )
    await consensus.submit_opinion(opinion)
"""
