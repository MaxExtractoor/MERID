"""
BTC 15m Sentiment-Aware Risk Dial

Dynamic risk scaling for BTC 15m Kalshi markets based on Fear/Greed + sentiment.
Integrates with SentimentRegimeEngine to provide real-time risk caps.
"""

from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple
from utils.logger import get_logger

import threading

from merid.sentiment.sentiment_regime import (
    SentimentRegimeEngine, 
    get_sentiment_regime_engine,
    SentimentRegime,
)
from merid.sentiment.cfgi_client import quick_fg
from merid.sentiment.sentiment_bundle import combine_sentiment
from merid.risk.promotion_engine import (
    PromotionEngine,
    PerformanceSnapshot,
    PerfState,
    dynamic_size,
    get_promotion_engine,
)

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# FG-based clamps
# ---------------------------------------------------------------------------

@dataclass
class FGState:
    """Inputs for fg_clamps()."""
    value: int          # 0..100 Fear & Greed index
    combined: float     # −1..1 social/news combined sentiment
    confidence: float   # 0..1 signal confidence
    is_synthetic: bool = False  # True when FG came from fallback sin-wave

    def regime(self) -> str:
        """Return the FG regime string matching FearGreedRegime values."""
        if self.value <= 20:
            return "extreme_fear"
        if self.value <= 40:
            return "fear"
        if self.value <= 60:
            return "neutral"
        if self.value <= 80:
            return "greed"
        return "extreme_greed"


def fg_clamps(equity: float, fg: FGState) -> Dict[str, float]:
    """
    Return per-trade and book-level caps based on FG regime.

    Base fractions (2% per-trade, 40% book) are tightened in:
      - Extreme zones (FG ≤ 25 or ≥ 75) with strong social signal → 60%
      - Low confidence → scaled by 0.5 + 0.5 * confidence

    Hard ceiling: 5% equity per trade regardless of inputs.
    """
    base_per_trade_frac = 0.02
    base_max_book_frac  = 0.40

    per_trade = equity * base_per_trade_frac
    max_book  = equity * base_max_book_frac

    # Extreme regime: FG in fear/greed extremes AND strong social signal
    extreme = (fg.value <= 25 or fg.value >= 75) and abs(fg.combined) > 0.2
    if extreme:
        per_trade *= 0.60
        max_book  *= 0.60

    # Confidence scaling: low confidence shrinks book
    conf_mult = 0.5 + 0.5 * max(0.0, min(1.0, fg.confidence))
    per_trade *= conf_mult
    max_book  *= conf_mult

    # Hard 5% cap per trade
    per_trade = min(per_trade, 0.05 * equity)

    return {
        "per_trade_cap": per_trade,
        "max_book_cap": max_book,
        "extreme": extreme,
        "conf_mult": conf_mult,
    }


def fg_clamp_breakdown(equity: float, fg: FGState) -> Dict[str, Any]:
    """
    Full audit breakdown of every FG clamp rule that fired.

    Returns the same caps as fg_clamps() plus a human-readable
    ``rules_fired`` list and ``sizing_multiplier`` for UI display.

    Example::
        bd = fg_clamp_breakdown(equity, fg)
        # bd["rules_fired"] = ["extreme_regime_60pct", "low_confidence_0.72x"]
        # bd["sizing_multiplier"] = 0.43
        # bd["fg_regime"] = "extreme_greed"
        # bd["fg_filter_blocked"] = True   ← KalshiFGFilter said no
        # bd["fg_filter_reason"] = "Extreme greed (82) - avoid bullish"
    """
    caps = fg_clamps(equity, fg)
    rules: List[str] = []

    extreme = (fg.value <= 25 or fg.value >= 75) and abs(fg.combined) > 0.2
    if extreme:
        rules.append("extreme_regime_60pct")

    conf_mult = caps["conf_mult"]
    if conf_mult < 0.95:
        rules.append(f"low_confidence_{conf_mult:.2f}x")

    if fg.is_synthetic:
        rules.append("synthetic_fg_data")

    # Sizing multiplier relative to unclamped 2% base
    base_pt = equity * 0.02
    sizing_mult = caps["per_trade_cap"] / base_pt if base_pt > 0 else 1.0

    # KalshiFGFilter directional check (side="yes" as default probe)
    try:
        from merid.sentiment.fg_filter import get_fg_filter
        ff = get_fg_filter()
        ff_result = ff.filter_trade(fg.value, side="yes", strategy_type="directional")
        fg_filter_blocked = not ff_result.allowed
        fg_filter_reason = ff_result.reason
        if fg_filter_blocked:
            rules.append("fg_filter_blocked_yes")
    except Exception as _ffe:
        logger.debug("fg_filter probe skipped: %s", _ffe)
        fg_filter_blocked = False
        fg_filter_reason = "unavailable"

    return {
        **caps,
        "fg_regime": fg.regime(),
        "fg_value": fg.value,
        "combined": fg.combined,
        "confidence": fg.confidence,
        "is_synthetic": fg.is_synthetic,
        "rules_fired": rules,
        "sizing_multiplier": round(sizing_mult, 3),
        "fg_filter_blocked": fg_filter_blocked,
        "fg_filter_reason": fg_filter_reason,
    }


# ---------------------------------------------------------------------------
# Volatility-adjusted sizing
# ---------------------------------------------------------------------------

def atr(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14,
) -> float:
    """
    Average True Range over the last `period` bars.

    Accepts plain Python lists (no pandas dependency at call site).
    Returns 0.0 if insufficient data.
    """
    if len(highs) < 2 or len(lows) < 2 or len(closes) < 2:
        return 0.0

    trs: List[float] = []
    for i in range(1, len(highs)):
        hl   = abs(highs[i]  - lows[i])
        hpc  = abs(highs[i]  - closes[i - 1])
        lpc  = abs(lows[i]   - closes[i - 1])
        trs.append(max(hl, hpc, lpc))

    if not trs:
        return 0.0

    window = trs[-period:]
    return sum(window) / len(window)


def vol_fg_position_size(
    equity: float,
    stop_dollars: float,
    atr_value: float,
    fg: "FGState",
) -> float:
    """
    Dollar risk per trade combining ATR volatility sizing and FG clamps.

    Sizing logic:
      1. Base risk = 1% equity
      2. ATR multiplier: more vol relative to stop → smaller size
      3. Extreme FG (≤25 or ≥75 with |combined| > 0.2) → 60% reduction
      4. Confidence scaling: 0.5 + 0.5 * confidence
      5. Hard 5% cap

    Convert the returned dollar risk to Kalshi contract count in the executor:
        contracts = max(1, int(dollar_risk / price_per_contract))
    """
    base_risk = 0.01 * equity

    # ATR multiplier — more volatility relative to stop → smaller size
    safe_stop = max(stop_dollars, 1e-9)
    atr_mult = max(1.0, atr_value / safe_stop)
    risk = base_risk / atr_mult

    # FG extreme reduction
    extreme = (fg.value <= 25 or fg.value >= 75) and abs(fg.combined) > 0.2
    if extreme:
        risk *= 0.60

    # Confidence scaling
    risk *= (0.5 + 0.5 * max(0.0, min(1.0, fg.confidence)))

    # Hard 5% cap
    risk = min(risk, 0.05 * equity)
    return max(risk, 0.0)


class ATRMonitor:
    """
    Tracks a rolling window of ATR values and classifies the current
    volatility regime relative to the recent average.

    Regimes:
      high_vol  — last ATR ≥ high_thresh × window average
      low_vol   — last ATR ≤ low_thresh  × window average
      normal    — everything in between

    Wire alert_needed() into your Telegram/logging layer when regime flips.
    """

    def __init__(
        self,
        window: int = 14,
        high_thresh: float = 2.0,
        low_thresh: float = 0.5,
    ) -> None:
        self.window = window
        self.high_thresh = high_thresh
        self.low_thresh = low_thresh
        self._values: List[float] = []
        self._last_regime: str = "unknown"

    def update(self, atr_value: float) -> None:
        """Append a new ATR reading; trims to window size."""
        self._values.append(atr_value)
        if len(self._values) > self.window:
            self._values.pop(0)

    def regime(self) -> str:
        """Return current volatility regime string."""
        if not self._values:
            return "unknown"
        avg = sum(self._values) / len(self._values)
        last = self._values[-1]
        ratio = last / avg if avg > 0 else 1.0
        if ratio >= self.high_thresh:
            return "high_vol"
        if ratio <= self.low_thresh:
            return "low_vol"
        return "normal"

    def alert_needed(self) -> Optional[str]:
        """
        Return the regime string if it changed from the last call and
        is not 'normal' or 'unknown'.  Returns None otherwise.

        Callers should publish the returned string to Telegram/logs.
        """
        current = self.regime()
        changed = current != self._last_regime
        self._last_regime = current
        if changed and current in ("high_vol", "low_vol"):
            return current
        return None

    def get_status(self) -> Dict[str, object]:
        avg = sum(self._values) / len(self._values) if self._values else 0.0
        return {
            "regime": self.regime(),
            "last_atr": self._values[-1] if self._values else None,
            "window_avg": avg,
            "samples": len(self._values),
        }


def atr_kalshi_position_size(
    equity: float,
    risk_frac: float,
    atr_value: float,
    tick_value: float = 0.01,
) -> float:
    """
    Return contract count using ATR-based position sizing.

    risk_frac:   fraction of equity to risk per trade (e.g. 0.01 = 1%)
    atr_value:   ATR in price units (same as tick_value denominator)
    tick_value:  dollar value of one price unit per contract (e.g. $0.01)

    Formula:
        risk_amount       = equity * risk_frac
        risk_per_contract = atr_value * tick_value
        contracts         = risk_amount / risk_per_contract

    Sanity clamp: contracts ≤ equity / (tick_value * 100)
    """
    risk_amount = equity * max(risk_frac, 0.0)
    risk_per_contract = max(atr_value * tick_value, 1e-6)
    contracts = risk_amount / risk_per_contract
    max_contracts = equity / max(tick_value * 100, 1e-9)
    return max(0.0, min(contracts, max_contracts))


# ---------------------------------------------------------------------------
# Kelly Criterion sizing
# ---------------------------------------------------------------------------

def kelly_fraction(p: float, b: float) -> float:
    """
    Full Kelly fraction for a binary bet.

    Args:
        p: Estimated win probability (0..1).
        b: Net odds — profit per $1 at risk.
           For Kalshi: b = (1 - yes_price) / yes_price
                       where yes_price = yes_price_cents / 100.

    Returns:
        Kelly fraction f* = (b*p - q) / b, floored at 0.
    """
    q = 1.0 - p
    if b <= 0:
        return 0.0
    return max(0.0, (b * p - q) / b)


def kalshi_fractional_kelly_size(
    equity: float,
    yes_price_cents: int,
    est_prob: float,
    frac: float = 0.25,
) -> float:
    """
    Fractional Kelly position size for a Kalshi YES contract.

    Uses 25% Kelly by default (frac=0.25) to reduce variance.
    Hard-capped at 5% equity regardless of Kelly output.

    Combine with ATR / FG / drawdown clamps and take the minimum
    across all methods to avoid overbetting on noisy estimates.

    Args:
        equity:          Current account equity in dollars.
        yes_price_cents: Kalshi yes price in cents (1..99).
        est_prob:        Estimated true win probability (0..1).
        frac:            Kelly fraction to use (default 0.25 = quarter-Kelly).

    Returns:
        Dollar risk per trade.
    """
    x = yes_price_cents / 100.0
    if x <= 0 or x >= 1:
        return 0.0
    b = (1.0 - x) / x
    f_kelly = kelly_fraction(est_prob, b)
    f_use = min(f_kelly * frac, 0.05)
    return equity * f_use


# ---------------------------------------------------------------------------
# Volatility tax on Kelly sizing
# ---------------------------------------------------------------------------

def volatility_tax_factor(
    sigma: float,
    sigma_ref: float = 0.02,
    max_penalty: float = 0.50,
) -> float:
    """
    Return a [0, 1] multiplier that reduces Kelly when realised vol is high.

    At or below sigma_ref: no penalty (returns 1.0).
    Above sigma_ref: penalty grows linearly at 0.25 per unit of (sigma/sigma_ref - 1),
    capped at max_penalty.

    Args:
        sigma:       Realised volatility of returns (e.g. std of last N bar returns).
        sigma_ref:   Reference vol; above this, Kelly is reduced.
        max_penalty: Maximum fractional reduction (default 0.50 = halve Kelly at 3× ref vol).

    Returns:
        Multiplier in [1 - max_penalty, 1.0].
    """
    if sigma <= sigma_ref:
        return 1.0
    ratio = sigma / max(sigma_ref, 1e-9)
    penalty = min(max_penalty, (ratio - 1.0) * 0.25)
    return max(0.0, 1.0 - penalty)


def kelly_with_vol_tax(
    equity: float,
    yes_price_cents: int,
    est_prob: float,
    base_frac: float = 0.25,
    sigma: float = 0.0,
    sigma_ref: float = 0.02,
) -> float:
    """
    Fractional Kelly size with a volatility tax applied.

    Combines kelly_fraction() × base_frac × volatility_tax_factor(),
    hard-capped at 5% equity.

    Args:
        equity:          Account equity in dollars.
        yes_price_cents: Kalshi yes price in cents (1..99).
        est_prob:        Estimated true win probability.
        base_frac:       Kelly fraction before vol tax (default 0.25).
        sigma:           Realised return volatility (0 = no tax).
        sigma_ref:       Reference vol for tax calculation.

    Returns:
        Dollar risk per trade.
    """
    x = yes_price_cents / 100.0
    if x <= 0 or x >= 1:
        return 0.0
    b = (1.0 - x) / x
    f_k = kelly_fraction(est_prob, b) * base_frac
    tax = volatility_tax_factor(sigma, sigma_ref=sigma_ref)
    f_adj = min(f_k * tax, 0.05)
    return equity * max(f_adj, 0.0)


# ---------------------------------------------------------------------------
# ATR stop / target levels
# ---------------------------------------------------------------------------

def atr_stop_levels(
    entry_price: float,
    atr_value: float,
    multiplier: float = 2.0,
    side: str = "long",
) -> tuple[float, float]:
    """
    Compute ATR-scaled stop-loss and take-profit levels.

    Works on Kalshi implied probability (0..1) or any normalised price.

    Args:
        entry_price: Entry implied probability or price.
        atr_value:   ATR in the same units as entry_price.
        multiplier:  ATR multiple for stop distance (default 2×).
        side:        "long" (YES) or "short" (NO).

    Returns:
        (stop_level, target_level) both clamped to [0.01, 0.99].

    Usage:
        stop, target = atr_stop_levels(0.55, atr_value=0.04, side="long")
        # → stop ≈ 0.47, target ≈ 0.63
        # Close position if mid-price crosses stop; take profit at target.
    """
    dist = atr_value * multiplier
    if side == "long":
        stop   = max(0.01, entry_price - dist)
        target = min(0.99, entry_price + dist)
    else:
        stop   = min(0.99, entry_price + dist)
        target = max(0.01, entry_price - dist)
    return stop, target


@dataclass
class BTCRiskDial:
    """Dynamic risk configuration for BTC 15m."""
    # Base config (10.52 starting equity)
    base_per_trade: float = 0.25
    base_max_exposure: float = 0.50
    base_max_positions: int = 2
    
    # Dynamic caps (set by regime engine)
    current_per_trade: float = 0.25
    current_max_exposure: float = 0.50
    current_max_positions: int = 2
    
    # Sentiment inputs
    fg_index: int = 50
    sent_combined: float = 0.0
    volatility: float = 0.2
    
    # Scaling factors
    extreme_scale_down: float = 0.60  # 60% of base in extremes
    contrarian_scale: float = 1.0     # Keep base for contrarian
    
    def get_scale_factor(self) -> float:
        """Get current scaling factor vs base."""
        return self.current_per_trade / self.base_per_trade


def _get_initial_equity() -> float:
    """Resolve starting equity from kalshi_risk state or settings fallback."""
    try:
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
        eq = float(get_kalshi_risk().state.current_equity_usd or 0)
        if eq > 0:
            return eq
    except Exception as _e:
        logger.debug("equity_lookup_kalshi_risk: %s", _e)
    try:
        from merid.settings import settings
        eq = float(getattr(settings, 'PAPER_STARTING_BALANCE', 0) or 0)
        if eq > 0:
            return eq
    except Exception as _e:
        logger.debug("equity_lookup_settings: %s", _e)
    return 0.0


class BTCSentimentRiskDial:
    """
    Dynamic risk dial for BTC 15m Kalshi trading.

    Phase caps (from PromotionEngine) define the ceiling.
    Sentiment/Markov regime can only tighten within those bounds.

    Usage:
        dial = BTCSentimentRiskDial(equity=_get_initial_equity(), promotion_engine=get_promotion_engine())
        caps = dial.update()  # Get current caps

        # In agent:
        if dial.can_trade():
            size = dial.scale_position_size(base_size)
    """

    def __init__(
        self,
        equity: float = 0.0,
        promotion_engine: Optional[PromotionEngine] = None,
    ):
        self.equity = equity if equity > 0 else _get_initial_equity()
        self.promotion_engine: PromotionEngine = promotion_engine or get_promotion_engine()
        self.config = BTCRiskDial()
        self.regime_engine = get_sentiment_regime_engine()
        self._last_update: Optional[Dict[str, Any]] = None
        # Sync base config from current phase immediately
        self._sync_base_from_phase()
    
    # ── Phase sync ────────────────────────────────────────────────────────

    def _sync_base_from_phase(self) -> None:
        """Pull base caps from the current promotion phase."""
        phase_caps = self.promotion_engine.get_caps(self.equity)
        self.config.base_per_trade = phase_caps["per_trade"]
        self.config.base_max_exposure = phase_caps["max_exposure"] / max(self.equity, 0.01)
        self.config.base_max_positions = phase_caps["max_open_trades"]

    def refresh_phase(self, perf: PerformanceSnapshot) -> None:
        """
        Ask the PromotionEngine to re-evaluate the phase ladder and update
        base caps accordingly.  Call this once per day or after each cycle.
        """
        self.promotion_engine.maybe_promote(perf)
        self._sync_base_from_phase()

    def get_caps(self) -> Tuple[float, float, int]:
        """
        Return (per_trade_cap, max_exposure_dollars, max_open_trades) after
        applying the promotion-phase ceiling.  Sentiment dial may have already
        tightened these further via update().
        """
        per_trade = self.config.current_per_trade
        max_exp = self.equity * self.config.current_max_exposure
        max_trades = self.config.current_max_positions
        return per_trade, max_exp, max_trades

    # ── Main update ───────────────────────────────────────────────────────

    def update(self) -> Dict[str, Any]:
        """
        Update risk dial with current market conditions.

        Phase caps are the ceiling; sentiment/Markov regime can only tighten.

        Returns:
            Dict with current risk configuration
        """
        # Re-sync base from phase in case equity changed
        self._sync_base_from_phase()

        # Fetch current sentiment
        try:
            bundle = combine_sentiment("BTC")
            self.config.fg_index = bundle.fg_index
            self.config.sent_combined = bundle.combined
        except Exception as exc:
            logger.warning(f"Failed to fetch sentiment: {exc}")
            # Keep previous values

        # Detect regime
        regime_state = self.regime_engine.detect_regime(
            fg_index=self.config.fg_index,
            sent_combined=self.config.sent_combined,
            volatility=self.config.volatility,
        )

        # Get regime-based caps (expressed as fractions)
        caps = self.regime_engine.get_risk_caps(regime_state.regime)

        # Compound with Markov regime multiplier
        markov_mult = 1.0
        try:
            from merid.sentiment.markov_regime import MarkovSentimentRiskAdapter
            if not hasattr(self, "_markov"):
                self._markov = MarkovSentimentRiskAdapter()
            markov_result = self._markov.update(
                fg_index=self.config.fg_index,
                sentiment=self.config.sent_combined,
                confidence=0.6,
            )
            markov_mult = markov_result.get("total_multiplier", 1.0)
        except Exception as exc:
            logger.debug("Markov regime unavailable: %s", exc)

        # Apply dynamic scaling — clamped to phase ceiling
        phase_caps = self.promotion_engine.get_caps(self.equity)
        self.config.current_per_trade = min(
            caps.max_per_trade * markov_mult,
            phase_caps["per_trade"],
        )
        self.config.current_max_exposure = min(
            caps.max_exposure * markov_mult,
            phase_caps["max_exposure"] / max(self.equity, 0.01),
        )
        self.config.current_max_positions = min(
            caps.max_live_positions,
            phase_caps["max_open_trades"],
        )

        result = {
            "phase": phase_caps["phase"],
            "regime": regime_state.regime.value,
            "fg_index": self.config.fg_index,
            "sent_combined": self.config.sent_combined,
            "scale_factor": self.config.get_scale_factor(),
            "per_trade_cap": self.config.current_per_trade,
            "max_exposure": self.config.current_max_exposure,
            "max_positions": self.config.current_max_positions,
            "phase_per_trade_ceiling": phase_caps["per_trade"],
            "phase_max_exposure_ceiling": phase_caps["max_exposure"],
            "unlocked_timeframes": phase_caps["unlocked_timeframes"],
            "unlocked_assets": phase_caps["unlocked_assets"],
            "allow_live": phase_caps["allow_live"],
            "sentiment_bias_max": caps.sentiment_bias_max,
            "allow_new_entries": caps.allow_new_entries,
            "late_entry_cutoff": caps.late_entry_cutoff,
            "reasoning": regime_state.reasoning,
        }

        self._last_update = result

        logger.info(
            "BTC 15m Risk Dial: phase=%s regime=%s | "
            "FG=%d sent=%+.2f | per_trade=%.3f (ceil=%.3f) | scale=%s",
            phase_caps["phase"],
            regime_state.regime.value,
            self.config.fg_index,
            self.config.sent_combined,
            self.config.current_per_trade,
            phase_caps["per_trade"],
            f"{self.config.get_scale_factor():.0%}",
        )

        return result
    
    def can_trade(self, bar_count: int = 0) -> Tuple[bool, str]:
        """
        Check if trading is allowed.
        
        Args:
            bar_count: Current bar in 15m cycle
        
        Returns:
            (allowed, reason) tuple
        """
        return self.regime_engine.can_enter_position(bar_count)
    
    def scale_position_size(self, base_size: float) -> float:
        """
        Scale position size based on current risk dial.

        Applies phase per-trade ceiling first, then sentiment scale factor.
        Per-trade size is also bounded by per_trade_pct * equity so that
        absolute size compounds with equity without exceeding the phase cap.
        """
        phase_caps = self.promotion_engine.get_caps(self.equity)
        # Hard ceiling: min(phase dollar cap, pct-of-equity cap, sentiment cap)
        pct_cap = self.promotion_engine.current_phase.per_trade_pct * self.equity
        max_size = min(
            phase_caps["per_trade"],
            pct_cap,
            self.equity * self.config.current_per_trade,
        )
        scaled = min(base_size, max_size)

        scale_factor = self.config.get_scale_factor()
        if scale_factor < 1.0:
            scaled = scaled * scale_factor
            logger.debug("Scaled position: %.3f -> %.3f (%s)", base_size, scaled, f"{scale_factor:.0%}")

        return scaled
    
    def get_sentiment_bias_limit(self) -> float:
        """Get max sentiment bias allowed for probability adjustments."""
        caps = self.regime_engine.get_current_caps()
        return caps.sentiment_bias_max
    
    def apply_sentiment_bias(
        self,
        base_prob: float,
        sentiment: float,
    ) -> Tuple[float, str]:
        """
        Apply sentiment bias to base probability.
        
        Args:
            base_prob: Base probability (0-1)
            sentiment: Sentiment score (-1 to 1)
        
        Returns:
            (adjusted_prob, reasoning) tuple
        """
        bias_limit = self.get_sentiment_bias_limit()
        
        if bias_limit == 0:
            return base_prob, "sentiment bias disabled in current regime"
        
        # Scale sentiment to bias limit
        bias = sentiment * bias_limit
        
        # Apply contrarian logic in extremes
        regime = self.regime_engine._current_regime
        if regime and regime.is_extreme():
            # Reduce bias when going with crowd in extremes
            sent_agrees_with_crowd = (regime.fg_index >= 80 and sentiment > 0) or (regime.fg_index <= 20 and sentiment < 0)
            if sent_agrees_with_crowd:
                bias *= 0.5
                logger.debug("Reduced sentiment bias (going with crowd in extreme)")
        
        adjusted = max(0.01, min(0.99, base_prob + bias))
        
        reasoning = f"bias={bias:+.2%} (limit={bias_limit:.2%})"
        return adjusted, reasoning
    
    def check_exposure_limit(
        self,
        current_exposure: float,
        new_trade_size: float,
    ) -> Tuple[bool, float]:
        """
        Check if new trade would exceed exposure limit.
        
        Returns:
            (allowed, max_new_size) tuple
        """
        max_exposure = self.equity * self.config.current_max_exposure
        available = max_exposure - current_exposure
        
        if available <= 0:
            return False, 0.0
        
        allowed_size = min(new_trade_size, available)
        return True, allowed_size
    
    def get_status(self) -> Dict[str, Any]:
        """Get current dial status."""
        if self._last_update is None:
            self.update()

        return {
            "equity": self.equity,
            "phase": self.promotion_engine.current_phase.name,
            "promotion_engine": self.promotion_engine.get_status(),
            "config": {
                "base_per_trade": self.config.base_per_trade,
                "base_max_exposure": self.config.base_max_exposure,
                "current_per_trade": self.config.current_per_trade,
                "current_max_exposure": self.config.current_max_exposure,
                "scale_factor": self.config.get_scale_factor(),
            },
            "last_update": self._last_update,
        }


# Singleton accessor
_dial: Optional[BTCSentimentRiskDial] = None
_dial_lock = threading.Lock()

def get_btc_risk_dial(
    equity: float = 0.0,
    promotion_engine: Optional[PromotionEngine] = None,
) -> BTCSentimentRiskDial:
    """Get the singleton BTCSentimentRiskDial instance."""
    global _dial
    if _dial is None:
        with _dial_lock:
            if _dial is None:
                _dial = BTCSentimentRiskDial(
                equity=equity,
                promotion_engine=promotion_engine or get_promotion_engine(),
            )
    return _dial


# ── Convenience functions ──────────────────────────────────────────

def quick_risk_check(bar_count: int = 0) -> Dict[str, Any]:
    """Quick one-liner to get current risk status."""
    dial = get_btc_risk_dial()
    can_trade, reason = dial.can_trade(bar_count)
    
    return {
        "can_trade": can_trade,
        "reason": reason,
        "caps": dial._last_update if dial._last_update else dial.update(),
    }


def scale_btc_size(base_size: float) -> float:
    """Quick size scaling for BTC 15m."""
    dial = get_btc_risk_dial()
    return dial.scale_position_size(base_size)
