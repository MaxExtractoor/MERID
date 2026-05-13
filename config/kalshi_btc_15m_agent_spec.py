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
    min_edge_threshold: float = 0.012  # 1.2¢ for aggressive micro-scalping (just above 2¢ fee, rely on volume)
    max_vol_ratio: float = 2.0  # Skip if 5m realized vol > 2x baseline
    min_time_to_expiry: int = 120  # Don't enter last 2 minutes (aggressive)
    max_time_to_expiry: int = 900  # Trade first 15 minutes (wider window)

    # Regime confidence thresholds
    min_regime_confidence: float = 0.5  # Lowered for more signals
    regime_window_minutes: int = 15  # Look at last 15m for regime

# ── Input Feeds ──────────────────────────────────────────────────────────────

@dataclass
class Btc15mInputs:
    """Real-time inputs for BTC 15m agent.

    LEAN 15m KALSHI STACK (2026-05-13): Extended with SignalFusion microstructure signals.
    """

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

    # LEAN 15m KALSHI STACK (2026-05-13): SignalFusion microstructure signals
    # orderflow_bias > 0 = net aggressive buying / positive imbalance
    # orderflow_bias < 0 = net selling / negative imbalance
    orderflow_bias: float = 0.0

    # onchain_velocity > 0 = above-baseline on-chain activity (z-scored)
    # onchain_velocity < 0 = muted activity
    onchain_velocity: float = 0.0

# ── Signal Generation ─────────────────────────────────────────────────────────

class Btc15mSignalGenerator:
    """Generates trading signals for BTC 15m contracts.

    LEAN 15m KALSHI STACK (2026-05-13): Probability-space Kelly sizing tied to Kalshi prices.
    """

    def __init__(self, spec: Btc15mAgentSpec):
        self.spec = spec
        # Kelly parameters
        self.kelly_shrink = 0.25  # Fractional Kelly (conservative)
        self.max_kelly_cap = 0.10  # Max position size as fraction of capital

    @staticmethod
    def kelly_fraction(p_model: float, price_cents: float) -> float:
        """Calculate Kelly fraction for a YES bet.

        f* = (p(b+1) - 1) / b, where b = (1-p_market) / p_market
        """
        p_market = price_cents / 100.0
        b = (1 - p_market) / p_market
        numer = p_model * (b + 1) - 1
        if b <= 0 or numer <= 0:
            return 0.0
        f_star = numer / b
        return max(0.0, min(f_star, 1.0))  # Full Kelly upper bound

    @staticmethod
    def cents_to_prob(edge_cents: float) -> float:
        """Convert edge in cents to probability points.

        Around 50c, 1c ≈ 1% probability.
        Can be refined from backtest data.
        """
        return edge_cents / 100.0

    def generate_signal(self, inputs: Btc15mInputs) -> Optional[Dict[str, Any]]:
        """Generate trading signal based on regime, microstructure, and filters.

        LEAN 15m KALSHI STACK (2026-05-13): Incorporates SignalFusion microstructure signals.
        """

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

        # 3. Direction from regime
        direction = regime.get("direction")
        if not direction:
            return None

        # LEAN 15m KALSHI STACK (2026-05-13): Probability-space Kelly sizing
        # Use Kalshi market price to compute implied probability and Kelly fraction
        kalshi_price = (inputs.orderbook_bid + inputs.orderbook_ask) / 2.0  # Mid price

        # Convert base regime edge (in cents) to probability points
        base_edge_est = regime.get("edge_estimate", 0.0)  # in cents
        p_market = kalshi_price / 100.0
        p_model_base = p_market + self.cents_to_prob(base_edge_est)

        # LEAN 15m KALSHI STACK (2026-05-13): Microstructure signal integration
        # orderflow_bias: positive = buying pressure, negative = selling pressure
        # onchain_velocity: positive = elevated on-chain activity, negative = muted
        orderflow_bias = inputs.orderflow_bias
        onchain_velocity = inputs.onchain_velocity

        # Boost p_model when microstructure aligns with regime direction
        # Symmetric, soft thresholds: neutral zone |bias| < 0.1, strong boost |bias| > 0.5
        prob_boost = 0.0
        direction_sign = 1 if direction == "up" else -1
        alignment_score = direction_sign * orderflow_bias

        if alignment_score > 0.5:
            prob_boost = self.cents_to_prob(0.03)  # +3¢ → +0.03 probability for strong alignment
        elif alignment_score > 0.2:
            prob_boost = self.cents_to_prob(0.02)  # +2¢ → +0.02 probability for moderate alignment
        elif alignment_score < -0.1:
            # Neutral/misaligned zone - no boost
            prob_boost = 0.0

        p_model = p_model_base + prob_boost
        p_model = max(0.01, min(0.99, p_model))  # Clamp for safety

        # Gate: require elevated on-chain activity for meaningful moves
        # Only size up when on-chain velocity is above baseline (z-score > 0)
        # AND realized vol is above baseline (avoid deceptive high on-chain / low vol regimes)
        onchain_gate_multiplier = 1.0
        if onchain_velocity < 0:
            # Muted on-chain activity - reduce position size by 50%
            onchain_gate_multiplier = 0.5
        elif onchain_velocity > 1.0 and inputs.vol_15m_realized > inputs.vol_baseline_median:
            # High on-chain activity AND elevated realized vol - can size up 20%
            onchain_gate_multiplier = 1.2

        # Compute Kelly fraction from probability and Kalshi price
        base_kelly = self.kelly_fraction(p_model, kalshi_price)

        # Apply fractional Kelly shrink and cap
        kelly_fraction = min(base_kelly * self.kelly_shrink, self.max_kelly_cap)

        # Apply on-chain gate multiplier
        kelly_fraction *= onchain_gate_multiplier

        # Final position size as percentage of max_position_size_pct
        position_size = kelly_fraction * self.spec.max_position_size_pct

        # Calculate edge per unit stake for logging
        p_mkt = kalshi_price / 100.0
        b = (1 - p_mkt) / p_mkt
        edge_per_stake = p_model * b - (1 - p_model)

        return {
            "action": "buy" if direction == "up" else "sell",
            "market_id": inputs.market_id,
            "size_pct": position_size,
            "reason": (
                f"Regime: {regime['regime']}, p_model: {p_model:.3f} "
                f"(p_mkt: {p_mkt:.3f}, prob_boost: {prob_boost:.3f}), "
                f"Kelly: {kelly_fraction:.3f}, OF: {orderflow_bias:+.2f}, OC: {onchain_velocity:+.2f}"
            ),
            "stop_loss_pct": self.spec.stop_loss_pct,
            "take_profit_pct": self.spec.take_profit_pct,
            "edge_estimate": edge_per_stake,  # EV per unit stake
            "regime_confidence": regime.get("confidence", 0.0),
            # LEAN 15m KALSHI STACK (2026-05-13): Expose probability and Kelly metrics for observability
            "p_market": p_market,
            "p_model": p_model,
            "p_model_base": p_model_base,
            "prob_boost": prob_boost,
            "kelly_fraction": kelly_fraction,
            "orderflow_bias": orderflow_bias,
            "onchain_velocity": onchain_velocity,
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
