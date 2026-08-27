"""Fractional-Kelly Position Sizer — Adaptive sizing for Kalshi crypto contracts.

Computes optimal position size for bounded-loss binary contracts using
fractional Kelly criterion, adjusted for:
- Kalshi fee schedule (tiered by contract count)
- Measured profit factor and expectancy from paper sessions
- Per-cell and per-cluster exposure caps
- Sentiment (fear/greed) and volatility regimes (via SentimentVolService)

Design principles from the playbook:
- Start with small fixed fractions (0.25–1%) rather than full Kelly
- Cap total exposure per underlying and per hour
- Only increase size gradually once PF and expectancy are stable
- Strategies with PF closer to 1.0 stay at minimum size
- Extreme fear/greed and high vol regimes reduce size via SizingMultiplier

Usage::

    sizer = PositionSizer()
    size = sizer.compute("BTC_HOURLY", edge_pct=3.0, price_cents=55)
    # Returns contract count (integer)
    
    # With sentiment/vol sizing (new):
    size = sizer.compute("BTC_HOURLY", edge_pct=3.0, price_cents=55,
                         sentiment_vol_asset="BTC")
"""

from __future__ import annotations

import math
import threading
import time as _time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

if TYPE_CHECKING:
    from merid.prediction.unified_edge import EdgeResult

from merid.event_venues.kalshi.fees import calculate_kalshi_fee_per_contract_cents
from merid.event_venues.kalshi.risk_parameters import (
    DEFAULT_KELLY_FRACTION,  # DEPRECATED: Use profile when available
    SIZER_MIN_CONTRACTS,
    SIZER_MAX_CONTRACTS,
    SIZER_MAX_BANKROLL_PCT,
    SIZER_MIN_BANKROLL_PCT,
    SIZER_PF_MIN_FOR_SCALING,
    SIZER_PF_FULL_KELLY_AT,
    SIZER_EXPECTANCY_MIN_CENTS,
    SIZER_MAX_CONTRACTS_PER_UNDERLYING_PER_HOUR,
    SIZER_MIN_TRADES_FOR_SCALING,
    SIZER_DOWNTOWN_CAUTION_THRESHOLD_PCT,
    SIZER_DOWNTOWN_DANGER_THRESHOLD_PCT,
    SIZER_VOL_CAUTION_THRESHOLD_PCT,
    SIZER_VOL_DANGER_THRESHOLD_PCT,
    SIZER_DOWNTOWN_DANGER_REDUCTION,
    SIZER_DOWNTOWN_CAUTION_REDUCTION,
    SIZER_VOL_DANGER_REDUCTION,
    SIZER_VOL_CAUTION_REDUCTION,
    SIZER_TIGHT_REDUCTION,
    SIZER_VOL_HIGH_REDUCTION,
    SIZER_TARGET_VOL,
    SIZER_MIN_SCALE,
    SIZER_MAX_RISK_PCT,
    PROB_MIN_BOUND,
    PROB_MAX_BOUND,
)

# Helper to get Kelly fraction from profile (Task 28: Single source of truth)
def _get_kelly_fraction() -> float:
    """Get Kelly fraction from profile or fallback to deprecated constant."""
    try:
        from merid.risk.profiles.crypto_15m_profile import get_active_profile
        adapter = get_active_profile()
        if adapter is not None and adapter.profile is not None:
            return adapter.profile.kelly_hard_cap
    except Exception:
        pass
    return DEFAULT_KELLY_FRACTION  # Fallback
# REMOVED: get_merid_swarm_confidence_min - sentiment-driven sizing not used in 15m stack
from merid.event_venues.kalshi.fees import (
    calculate_kalshi_fee_cents,
    calculate_kalshi_fee_per_contract_cents,
)

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.position_sizer")


@dataclass
class SizerConfig:
    """Configuration for the position sizer."""

    # Kelly fraction (0.0–1.0). TIGHTENED from 0.25 to 0.15 for small bankroll
    # More conservative sizing to protect capital while building back up
    # Task 28: Single source of truth is profile YAML (kalshi_crypto_15m.yaml)
    kelly_fraction: float = field(default_factory=_get_kelly_fraction)

    # Minimum and maximum contracts per trade
    min_contracts: int = SIZER_MIN_CONTRACTS
    max_contracts: int = SIZER_MAX_CONTRACTS

    # Bankroll fraction caps - 2026-07-08 UPDATE: DISABLED in favor of fixed $1 exposure model
    max_bankroll_pct: float = SIZER_MAX_BANKROLL_PCT  # DISABLED - using fixed $1 exposure cap
    min_bankroll_pct: float = SIZER_MIN_BANKROLL_PCT  # DISABLED - using fixed $1 exposure cap

    # 2026-07-08 UPDATE: Per-trade risk cap DISABLED in favor of fixed $1 exposure model
    per_trade_risk_pct: float = 0.0  # DISABLED - using fixed $1 exposure cap

    # PF/expectancy gates for size scaling
    pf_min_for_scaling: float = SIZER_PF_MIN_FOR_SCALING
    pf_full_kelly_at: float = SIZER_PF_FULL_KELLY_AT
    expectancy_min_cents: float = SIZER_EXPECTANCY_MIN_CENTS

    # Per-underlying hourly exposure cap (contracts)
    max_contracts_per_underlying_per_hour: int = SIZER_MAX_CONTRACTS_PER_UNDERLYING_PER_HOUR

    # Minimum sample size before scaling up from minimum
    min_trades_for_scaling: int = SIZER_MIN_TRADES_FOR_SCALING


DEFAULT_SIZER_CONFIG = SizerConfig()


def kelly_fraction_for_binary(
    win_prob: float,
    win_payout: float,
    loss_amount: float,
) -> float:
    """Compute Kelly fraction for a binary outcome.

    For a binary contract:
    - You pay ``loss_amount`` (your cost) and win ``win_payout`` (100 - cost)
    - Kelly f* = (p * b - q) / b  where b = win_payout / loss_amount

    Args:
        win_prob: Estimated probability of winning (0–1)
        win_payout: Payout on win (e.g. 45 cents if you paid 55)
        loss_amount: Amount lost on loss (e.g. 55 cents, your cost)

    Returns:
        Kelly fraction (can be negative if edge is negative).
    """
    if loss_amount <= 0 or win_payout <= 0:
        return 0.0
    b = win_payout / loss_amount
    q = 1.0 - win_prob
    f = (win_prob * b - q) / b
    return f


# ═══════════════════════════════════════════════════════════════════════════
# Fee calculations — delegated to unified fees module
# ═══════════════════════════════════════════════════════════════════════════
# These functions are now thin wrappers around the unified fees module
# to maintain backward compatibility during migration.

def _kalshi_fee_rate(contracts: int) -> float:
    """Return the tiered fee rate for a given contract count.
    
    DELEGATED: Uses unified fees module internally.
    """
    from merid.event_venues.kalshi.fees import TIER_RATES, Decimal
    for (low, high), rate in TIER_RATES.items():
        if low <= contracts < high:
            return float(rate)
    return 0.03


def kalshi_fee_cents(price_cents: int, contracts: int) -> int:
    """Compute total Kalshi fee in cents for a trade.
    
    DEPRECATED (2026-07-16): Use calculate_kalshi_fee_cents from fees module directly.
    This function is kept for backwards compatibility only.
    
    DELEGATED to unified fees module: merid.event_venues.kalshi.fees
    Note: Original signature is (price_cents, contracts), unified is (contracts, price_cents)
    """
    import warnings
    warnings.warn(
        "kalshi_fee_cents is deprecated. Use calculate_kalshi_fee_cents from fees module directly.",
        DeprecationWarning,
        stacklevel=2
    )
    return calculate_kalshi_fee_cents(contracts, price_cents)


def kalshi_fee_per_contract_cents(price_cents: int, contracts: int = 1) -> int:
    """Compute per-contract Kalshi fee for a given trade size.
    
    DELEGATED to unified fees module: merid.event_venues.kalshi.fees
    Note: Original signature is (price_cents, contracts), unified is (contracts, price_cents)
    """
    return int(calculate_kalshi_fee_per_contract_cents(contracts, price_cents))


def adaptive_kelly_fraction(
    base_fraction: float,
    profit_factor: float = 0.0,
    max_drawdown_pct: float = 0.0,
    local_vol_pct: float = 0.0,
    *,
    pf_caution_threshold: float = 1.2,
    pf_danger_threshold: float = 1.05,
    dd_caution_threshold: float = SIZER_DOWNTOWN_CAUTION_THRESHOLD_PCT,
    dd_danger_threshold: float = SIZER_DOWNTOWN_DANGER_THRESHOLD_PCT,
    vol_caution_threshold: float = SIZER_VOL_CAUTION_THRESHOLD_PCT,
    vol_danger_threshold: float = SIZER_VOL_DANGER_THRESHOLD_PCT,
) -> float:
    """Compute a vol-aware, drawdown-aware adaptive Kelly fraction.

    Shrinks the base Kelly fraction when conditions deteriorate:

    - **PF < caution** (default 1.2): halve the fraction
    - **PF < danger** (default 1.05): quarter the fraction
    - **Drawdown > caution** (default 15%): halve the fraction
    - **Drawdown > danger** (default 25%): quarter the fraction
    - **Local vol > caution** (default 30%): reduce by 30%
    - **Local vol > danger** (default 50%): halve the fraction

    Multipliers stack multiplicatively so multiple bad signals
    compound into very small fractions.

    Args:
        base_fraction: Starting Kelly fraction (e.g. 0.25).
        profit_factor: Measured PF (0 = unknown, skipped).
        max_drawdown_pct: Current drawdown as percentage (0-100).
        local_vol_pct: Recent PnL volatility as percentage (0-100).
        pf_caution_threshold: PF below which fraction is halved.
        pf_danger_threshold: PF below which fraction is quartered.
        dd_caution_threshold: Drawdown % above which fraction is halved.
        dd_danger_threshold: Drawdown % above which fraction is quartered.
        vol_caution_threshold: Vol % above which fraction is reduced 30%.
        vol_danger_threshold: Vol % above which fraction is halved.

    Returns:
        Adjusted Kelly fraction (>= 0).
    """
    frac = base_fraction

    # PF-based shrinkage (only when PF is known)
    if profit_factor > 0:
        if profit_factor < pf_danger_threshold:
            frac *= SIZER_DOWNTOWN_DANGER_REDUCTION
        elif profit_factor < pf_caution_threshold:
            frac *= SIZER_DOWNTOWN_CAUTION_REDUCTION

    # Drawdown-based shrinkage
    if max_drawdown_pct > dd_danger_threshold:
        frac *= SIZER_DOWNTOWN_DANGER_REDUCTION
    elif max_drawdown_pct > dd_caution_threshold:
        frac *= SIZER_DOWNTOWN_CAUTION_REDUCTION

    # Volatility-based shrinkage
    if local_vol_pct > vol_danger_threshold:
        frac *= SIZER_VOL_DANGER_REDUCTION
    elif local_vol_pct > vol_caution_threshold:
        frac *= SIZER_VOL_HIGH_REDUCTION

    return max(0.0, frac)


def vol_scaled_fraction(
    base_fraction: float,
    realized_vol: float,
    target_vol: float = SIZER_TARGET_VOL,
    min_scale: float = SIZER_MIN_SCALE,
    max_scale: float = 1.0,
) -> float:
    """Volatility-targeted Kelly fraction scaling.

    Continuously modulates the Kelly fraction using the ratio of
    target volatility to realized volatility. Higher realized vol
    results in a smaller effective fraction, keeping strategy-level
    volatility approximately constant.

    This mirrors "volatility-regulated Kelly" — instead of discrete
    threshold-based shrinkage (like adaptive_kelly_fraction), this
    provides smooth, continuous scaling.

    Args:
        base_fraction: Starting Kelly fraction (e.g. 0.25).
        realized_vol: Realized hourly/daily vol of strategy returns
            (e.g. 0.02 for 2%).
        target_vol: Desired volatility level (e.g. 0.02 for 2%).
        min_scale: Floor for the scaling factor (default 0.25).
        max_scale: Ceiling for the scaling factor (default 1.0).

    Returns:
        Scaled Kelly fraction (>= 0).
    """
    if realized_vol <= 0:
        return 0.0
    scale = target_vol / realized_vol
    scale = max(min_scale, min(scale, max_scale))
    return base_fraction * scale


def edge_to_size_fraction(
    edge_pct: float,
    k1: float = 0.05,  # Edge-to-size multiplier (5% of capital per 1% edge)
    min_fraction: float = 0.005,  # Minimum 0.5% of capital
    max_fraction: float = 0.03,   # Maximum 3% of capital
) -> float:
    """
    Edge-to-size mapping for swing trading position sizing.
    
    Maps edge percentage to capital fraction using linear scaling:
    f_edge = k1 * edge_pct
    
    Clipped to [min_fraction, max_fraction] to prevent extreme sizing.
    
    Args:
        edge_pct: Edge percentage (e.g., 3.0 for 3% edge)
        k1: Edge-to-size multiplier (default 0.05 = 5% capital per 1% edge)
        min_fraction: Minimum capital fraction (default 0.5%)
        max_fraction: Maximum capital fraction (default 3%)
    
    Returns:
        Capital fraction for position sizing (clipped to bounds)
    
    Examples:
        - edge_pct=1.0% → f_edge=0.05 (5% capital)
        - edge_pct=3.0% → f_edge=0.15 (15% capital, clipped to 3%)
        - edge_pct=0.5% → f_edge=0.025 (2.5% capital)
    """
    # Linear mapping: f_edge = k1 * edge_pct
    f_edge = k1 * edge_pct
    
    # Clip to bounds
    f_edge = max(min_fraction, min(f_edge, max_fraction))
    
    return f_edge


def volatility_adjusted_fraction(
    base_fraction: float,
    volatility_regime: str,
    multipliers: Optional[dict] = None,
) -> float:
    """
    Volatility adjustment for position sizing.
    
    Reduces size in high volatility regimes to manage risk.
    
    Args:
        base_fraction: Base capital fraction (e.g., from edge_to_size_fraction)
        volatility_regime: Volatility regime ("LOW", "NORMAL", "HIGH", "EXTREME")
        multipliers: Optional custom multipliers dict
    
    Returns:
        Adjusted capital fraction
    
    Default multipliers:
        - LOW: 1.0 (no reduction)
        - NORMAL: 0.8 (20% reduction)
        - HIGH: 0.5 (50% reduction)
        - EXTREME: 0.25 (75% reduction)
    """
    if multipliers is None:
        multipliers = {
            "LOW": 1.0,
            "NORMAL": 0.8,
            "HIGH": 0.5,
            "EXTREME": 0.25,
        }
    
    multiplier = multipliers.get(volatility_regime, 0.8)  # Default to NORMAL
    return base_fraction * multiplier


def correlation_adjusted_fraction(
    base_fraction: float,
    current_category_allocation_pct: float,
    max_category_allocation_pct: float = 0.30,
) -> float:
    """
    Correlation adjustment for position sizing.
    
    Caps position size based on available category risk to prevent
    over-concentration in correlated assets (e.g., BTC/ETH/SOL).
    
    Args:
        base_fraction: Base capital fraction (e.g., from volatility_adjusted_fraction)
        current_category_allocation_pct: Current allocation to category (0-1)
        max_category_allocation_pct: Maximum allowed category allocation (default 30%)
    
    Returns:
        Adjusted capital fraction (capped to available category risk)
    
    Example:
        - base_fraction=0.03 (3%)
        - current_category_allocation=0.25 (25%)
        - max_category_allocation=0.30 (30%)
        - available_category_risk = 0.30 - 0.25 = 0.05 (5%)
        - Adjusted fraction = min(0.03, 0.05) = 0.03 (3%)
        
        - base_fraction=0.05 (5%)
        - current_category_allocation=0.28 (28%)
        - max_category_allocation=0.30 (30%)
        - available_category_risk = 0.30 - 0.28 = 0.02 (2%)
        - Adjusted fraction = min(0.05, 0.02) = 0.02 (2%)
    """
    available_category_risk = max_category_allocation_pct - current_category_allocation_pct
    
    # Cap to available category risk
    adjusted_fraction = min(base_fraction, available_category_risk)
    
    # Ensure non-negative
    adjusted_fraction = max(0.0, adjusted_fraction)
    
    return adjusted_fraction


def atr_risk_fraction(
    account_risk_pct: float,
    atr: float,
    atr_unit: float,
    max_risk_pct: float = SIZER_MAX_RISK_PCT,
) -> float:
    """ATR-based position sizing for BTC hourly contracts.

    Scales risk inversely proportional to current ATR. When ATR is high
    (volatile market), position size shrinks; when ATR is low, size grows
    up to the account risk cap.

    For Kalshi binaries, `atr_unit` represents the BTC price move that
    historically maps to a large loss on the bracket/hourly contract
    (e.g., if a $500 BTC move ≈ full contract loss, atr_unit = 500).

    This complements `vol_scaled_fraction` (return-based vol) by using
    BTC spot candle data (High/Low/Close) instead of strategy returns.

    Args:
        account_risk_pct: Max fraction of equity to risk per trade
            (e.g. 0.01 for 1%).
        atr: Current ATR value in same units as atr_unit.
        atr_unit: Underlying price move corresponding to full contract
            loss (e.g. 500 for $500 BTC move).
        max_risk_pct: Hard cap on risk fraction (default 2%).

    Returns:
        Risk fraction (0 to max_risk_pct).
    """
    if atr <= 0 or atr_unit <= 0:
        return 0.0
    frac = account_risk_pct * atr_unit / atr
    return min(frac, max_risk_pct)


class PositionSizer:
    """Adaptive position sizer for Kalshi binary contracts.

    Combines Kelly criterion with PF/expectancy-based scaling gates
    and exposure caps from the paper session risk framework.
    """

    def __init__(self, config: Optional[SizerConfig] = None) -> None:
        self._config = config or DEFAULT_SIZER_CONFIG
        # Runtime state exposed to the API layer
        self._manual_override_factor: float = 1.0   # operator downsize factor (0-1)
        self._realized_vol: float = SIZER_TARGET_VOL             # rolling realized vol (fraction)
        self._target_vol: float = SIZER_TARGET_VOL               # vol target (fraction)
        self._atr_value: float = 0.0                 # latest ATR reading
        self._atr_fraction: float = 0.0              # ATR-derived risk fraction
        self._kelly_util_pct: float = 0.0            # rolling avg Kelly utilization %

        # Rate/activity tracking for observability
        self._last_positive_edge_time: float = _time.time()
        self._trade_timestamps: deque = deque(maxlen=100)  # Track last 100 trade timestamps
        self._total_sizing_calls: int = 0
        self._positive_edge_count: int = 0

    # ── Runtime properties (read by sizing-metrics API) ──────────────────

    @property
    def kelly_fraction(self) -> float:
        """Base Kelly fraction from config."""
        return self._config.kelly_fraction

    @property
    def effective_fraction(self) -> float:
        """Effective Kelly fraction after manual override."""
        return self._config.kelly_fraction * self._manual_override_factor

    @property
    def vol_scale(self) -> float:
        """Current vol-targeting scale factor (target_vol / realized_vol)."""
        if self._realized_vol <= 0:
            return 1.0
        return min(1.0, max(SIZER_MIN_SCALE, self._target_vol / self._realized_vol))

    @property
    def target_vol(self) -> float:
        return self._target_vol

    @property
    def realized_vol(self) -> float:
        return self._realized_vol

    @property
    def atr_value(self) -> float:
        return self._atr_value

    @property
    def atr_fraction(self) -> float:
        return self._atr_fraction

    @property
    def kelly_utilization_pct(self) -> float:
        return self._kelly_util_pct

    # ── Operator controls ────────────────────────────────────────────────

    def apply_manual_override(
        self,
        factor: float,
        asset: Optional[str] = None,  # noqa: ARG002 — reserved for per-asset overrides
    ) -> None:
        """Reduce effective Kelly fraction by ``factor`` (0.1–1.0).

        Args:
            factor: Multiplicative reduction (e.g. 0.5 = halve sizing).
            asset: Reserved for future per-asset overrides (ignored for now).
        """
        self._manual_override_factor = max(0.0, min(1.0, float(factor)))
        logger.info(f"PositionSizer manual override applied: factor={self._manual_override_factor:.3f}")

    def reset_override(self) -> None:
        """Reset manual override back to full sizing."""
        self._manual_override_factor = 1.0

    def update_vol_state(
        self,
        realized_vol: float,
        atr_value: float = 0.0,
        atr_fraction: float = 0.0,
        kelly_util_pct: float = 0.0,
    ) -> None:
        """Update runtime vol/ATR state (called by portfolio risk agent)."""
        self._realized_vol = max(0.0, realized_vol)
        self._atr_value = max(0.0, atr_value)
        self._atr_fraction = max(0.0, atr_fraction)
        self._kelly_util_pct = max(0.0, kelly_util_pct)

    def compute(
        self,
        agent_name: str,
        edge_pct: float,
        price_cents: int,
        bankroll_cents: int = 500_000,
        *,
        profit_factor: float = 0.0,
        expectancy_cents: float = 0.0,
        total_trades: int = 0,
        current_exposure_contracts: int = 0,
        size_factor: float = 1.0,
        max_drawdown_pct: float = 0.0,
        local_vol_pct: float = 0.0,
        sentiment_vol_asset: Optional[str] = None,
        is_contrarian: bool = False,
        sentiment_timeframe: Optional[str] = None,
        market_ticker: Optional[str] = None,
        swarm_score: Optional[float] = None,
        swarm_confidence: Optional[float] = None,
        decision_trace_id: Optional[str] = None,
    ) -> int:
        """
        Compute position size in contracts.

        DEPRECATED: For Kalshi 15m crypto, use compute_from_edge_result() instead.
        This method will be removed after migration to canonical EdgeResult path.
        Non-Kalshi venues can continue using this method.

        Args:
            agent_name: Cell name (e.g. "BTC_HOURLY") for logging
            edge_pct: Estimated edge as percentage (e.g. 3.0 means 3% edge)
            price_cents: Contract price in cents (1–99)
            bankroll_cents: Total session bankroll in cents
            profit_factor: Measured PF from paper session (0 = unknown)
            expectancy_cents: Measured expectancy per trade in cents
            total_trades: Number of trades in paper session (for sample gate)
            current_exposure_contracts: Current open contracts for this underlying
            size_factor: From paper session risk governance (0.0 if halted, 0.5 if downsized)
            max_drawdown_pct: Current drawdown as percentage (0-100) for adaptive Kelly
            local_vol_pct: Recent PnL volatility as percentage (0-100) for adaptive Kelly
            sentiment_vol_asset: Asset symbol to lookup sentiment/vol sizing (e.g., "BTC")
                If provided, will apply SizingMultiplier from SentimentVolService
            is_contrarian: If True, applies contrarian boost in extreme sentiment regimes

        Returns:
            Integer contract count (0 if trade should be skipped).
        """
        import warnings
        warnings.warn(
            "PositionSizer.compute() is deprecated for Kalshi 15m crypto. "
            "Use compute_from_edge_result() with EdgeResult instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        cfg = self._config

        # Rate/activity tracking: count sizing calls
        self._total_sizing_calls += 1

        # Log input parameters for debugging (WARNING level to ensure visibility)
        logger.warning(
            "[PositionSizer] compute called: agent=%s edge_pct=%.2f price_cents=%d bankroll_cents=%d "
            "size_factor=%.2f profit_factor=%.2f swarm_confidence=%s",
            agent_name, edge_pct, price_cents, bankroll_cents, size_factor, profit_factor,
            f"{swarm_confidence:.3f}" if swarm_confidence is not None else "None"
        )

        # Halted or zero factor → no trade (unless override enabled)
        import os
        if os.getenv("DISABLE_PAPER_SESSION_HALT", "").lower() in ("1", "true", "yes"):
            if size_factor <= 0:
                logger.debug(
                    "[PositionSizer] Paper session halt/downsize disabled via env var for %s - setting size_factor=1.0",
                    agent_name
                )
                size_factor = 1.0
        elif size_factor <= 0:
            logger.warning(
                "[PositionSizer] size_factor=0 for %s (halted/downsized) — returning 0 contracts",
                agent_name
            )
            return 0

        # REMOVED: Swarm conviction floor check - sentiment-driven sizing not used in 15m stack

        # Validate price
        if price_cents <= 0 or price_cents >= 100:
            logger.warning(
                "[PositionSizer] invalid price_cents=%d for %s — returning 0 contracts",
                price_cents, agent_name
            )
            return 0

        # ── Kelly sizing ──────────────────────────────────────────
        win_payout = 100 - price_cents  # cents won on correct prediction
        loss_amount = price_cents       # cents lost on wrong prediction

        # Convert edge to win probability
        # edge_pct is in FRACTION units (0.0-1.0)
        implied_prob = price_cents / 100.0
        est_win_prob = implied_prob + edge_pct  # edge_pct already in FRACTION
        est_win_prob = max(PROB_MIN_BOUND, min(PROB_MAX_BOUND, est_win_prob))

        raw_kelly = kelly_fraction_for_binary(est_win_prob, win_payout, loss_amount)

        # Edge sanity logging: log p_model, p_market, net_edge, Kelly fraction for auditability
        logger.info(
            "[EDGE_SANITY] agent=%s p_model=%.4f p_market=%.4f net_edge=%.4f raw_kelly=%.6f "
            "kelly_fraction_config=%.3f edge_pct=%.6f price_cents=%d",
            agent_name, est_win_prob, implied_prob, edge_pct, raw_kelly,
            cfg.kelly_fraction, edge_pct, price_cents
        )

        # Rate/activity tracking: update last positive edge time
        self._last_positive_edge_time = _time.time()
        self._positive_edge_count += 1

        if raw_kelly <= 0:
            # Negative edge → don't trade
            logger.warning(
                "[PositionSizer] raw_kelly=%.4f <= 0 for %s (edge_pct=%.2f, price_cents=%d) — returning 0 contracts",
                raw_kelly, agent_name, edge_pct, price_cents
            )

            # Rate/activity check: log if no positive edge for > 1 hour
            time_since_last_positive = _time.time() - self._last_positive_edge_time
            if time_since_last_positive > 3600:  # 1 hour
                logger.warning(
                    "[ACTIVITY_CHECK] No positive edge opportunities for %.1f hours (last positive at %s). "
                    "This may indicate modeling reality or market conditions, not a bug.",
                    time_since_last_positive / 3600,
                    _time.strftime("%Y-%m-%d %H:%M:%S", _time.localtime(self._last_positive_edge_time))
                )

            return 0

        # Apply fractional Kelly with adaptive shrinkage
        adapted_fraction = adaptive_kelly_fraction(
            cfg.kelly_fraction,
            profit_factor=profit_factor,
            max_drawdown_pct=max_drawdown_pct,
            local_vol_pct=local_vol_pct,
        )
        f = raw_kelly * adapted_fraction

        # ── Sentiment/Volatility sizing multiplier ───────────────
        sentiment_vol_multiplier = 1.0
        sizing_reasoning = ""
        if sentiment_vol_asset:
            try:
                from merid.prediction.risk.sentiment_vol_service import get_current_sizing_multiplier
                sv_mult = get_current_sizing_multiplier(sentiment_vol_asset, is_contrarian)
                sentiment_vol_multiplier = sv_mult.value
                sizing_reasoning = sv_mult.reasoning
                logger.debug(
                    "PositionSizer: %s sentiment/vol multiplier=%.3f (regime=%s, reason=%s)",
                    sentiment_vol_asset, sentiment_vol_multiplier, sv_mult.get_regime_label(), sizing_reasoning
                )
            except Exception as exc:
                logger.debug("PositionSizer: sentiment/vol lookup failed for %s: %s", sentiment_vol_asset, exc)
                # Continue with multiplier=1.0 (no adjustment)
        
        f *= sentiment_vol_multiplier

        # ── PF/expectancy scaling gate ────────────────────────────
        scale = self._pf_scale(profit_factor, expectancy_cents, total_trades)
        if scale <= 0:
            logger.warning(
                "[PositionSizer] PF scale=%.4f <= 0 for %s (profit_factor=%.2f) — returning 0 contracts",
                scale, agent_name, profit_factor
            )
            return 0
        f *= scale

        # ── Convert fraction to contracts ─────────────────────────
        # f = fraction of bankroll to risk
        # risk per contract = loss_amount cents
        # Include fee estimate (P2-4: use per-contract fee helper)
        # Note: We estimate using tier for <100 contracts initially, then recalculate
        fee_per_contract = kalshi_fee_per_contract_cents(price_cents, 1)
        risk_per_contract = loss_amount + fee_per_contract

        if risk_per_contract <= 0:
            return 0

        bankroll_risk = f * bankroll_cents
        contracts_from_kelly = int(bankroll_risk / risk_per_contract)

        # ── Apply caps ────────────────────────────────────────────
        # Bankroll percentage cap
        max_from_bankroll = int(
            (cfg.max_bankroll_pct / 100.0) * bankroll_cents / risk_per_contract
        )
        contracts = min(contracts_from_kelly, max_from_bankroll)

        # Absolute contract limits — respect Kelly=0 (no edge → no trade)
        if contracts_from_kelly > 0:
            contracts = max(cfg.min_contracts, min(contracts, cfg.max_contracts))
        else:
            contracts = 0

        # Per-underlying hourly exposure cap
        remaining_capacity = max(
            0,
            cfg.max_contracts_per_underlying_per_hour - current_exposure_contracts,
        )
        contracts = min(contracts, remaining_capacity)

        # Capacity exhausted → no trade (must check BEFORE enforcing min-1)
        if contracts <= 0:
            return 0

        # Apply size_factor from risk governance (e.g. 0.5 for downsized)
        contracts = max(1, int(contracts * size_factor))

        # ── Cycle drawdown multiplier ───────────────────────────
        # Apply 15-minute cycle drawdown de-risking
        try:
            from merid.event_venues.kalshi.cycle_drawdown import get_cycle_drawdown_manager
            cdm = get_cycle_drawdown_manager()
            cycle_mult = cdm.get_cycle_risk_multiplier()
            if cycle_mult < 1.0:
                contracts = max(1, int(contracts * cycle_mult))
                logger.debug(
                    "PositionSizer: %s cycle drawdown multiplier=%.3f contracts=%d",
                    agent_name, cycle_mult, contracts
                )
        except Exception as exc:
            logger.debug("PositionSizer: cycle drawdown multiplier failed (fail-open): %s", exc)

        # Final bounds
        contracts = max(0, min(contracts, cfg.max_contracts))

        # P2-4 FIX: Recalculate fee based on actual contract count for tier accuracy
        # If contracts >= 100, the per-contract fee drops from 7% to 5% tier
        actual_fee_per_contract = kalshi_fee_per_contract_cents(price_cents, contracts)

        # Edge sanity logging: log final contract size for auditability
        logger.info(
            "[EDGE_SANITY_FINAL] agent=%s final_contracts=%d adapted_fraction=%.4f "
            "sentiment_vol_multiplier=%.3f pf_scale=%.4f size_factor=%.2f",
            agent_name, contracts, adapted_fraction, sentiment_vol_multiplier, scale, size_factor
        )

        # Rate/activity check: track trade timestamps and detect frequency spikes
        if contracts > 0:
            current_time = _time.time()
            self._trade_timestamps.append(current_time)

            # Detect frequency spike: > 10 sizing computations in 5 minutes
            recent_computations = [t for t in self._trade_timestamps if current_time - t < 300]  # 5 minutes
            if len(recent_computations) > 10:
                logger.warning(
                    "[ACTIVITY_CHECK] Position sizing frequency spike detected: %d sizing computations in last 5 minutes. "
                    "This may indicate unusual market conditions or model behavior. "
                    "NOTE: These are sizing computations, NOT actual trades.",
                    len(recent_computations)
                )

        if sentiment_vol_asset and contracts > 0:
            risk_cents = contracts * (price_cents + actual_fee_per_contract)
            logger.info(
                "[sentiment_sizing] trace=%s asset=%s timeframe=%s ticker=%s "
                "swarm_score=%s swarm_confidence=%s size_contracts=%d risk_cents≈%.0f",
                decision_trace_id or "-",
                sentiment_vol_asset,
                sentiment_timeframe or "-",
                market_ticker or "-",
                f"{swarm_score:.4f}" if swarm_score is not None else "-",
                f"{swarm_confidence:.4f}" if swarm_confidence is not None else "-",
                contracts,
                risk_cents,
            )

        return contracts

    def compute_from_edge_result(
        self,
        agent_name: str,
        edge_result: 'EdgeResult',
        bankroll_cents: int = 500_000,
        *,
        profit_factor: float = 0.0,
        expectancy_cents: float = 0.0,
        total_trades: int = 0,
        current_exposure_contracts: int = 0,
        size_factor: float = 1.0,
        max_drawdown_pct: float = 0.0,
        local_vol_pct: float = 0.0,
        sentiment_vol_asset: Optional[str] = None,
        is_contrarian: bool = False,
        sentiment_timeframe: Optional[str] = None,
        market_ticker: Optional[str] = None,
        swarm_score: Optional[float] = None,
        swarm_confidence: Optional[float] = None,
        decision_trace_id: Optional[str] = None,
    ) -> int:
        """
        Compute position size from canonical EdgeResult.
        
        This is the NEW canonical path - consumes EdgeResult.edge_fee_adjusted
        and EdgeResult.fee_cost_cents directly, avoiding duplicate calculations.
        
        For Kalshi 15m crypto, this is the preferred method. The legacy compute()
        method is deprecated for this use case.
        
        Args:
            agent_name: Cell name (e.g. "BTC_15M") for logging
            edge_result: Canonical EdgeResult from UnifiedEdgeComputer
            bankroll_cents: Total session bankroll in cents
            profit_factor: Measured PF from paper session (0 = unknown)
            expectancy_cents: Measured expectancy per trade in cents
            total_trades: Number of trades in paper session (for sample gate)
            current_exposure_contracts: Current open contracts for this underlying
            size_factor: From paper session risk governance (0.0 if halted, 0.5 if downsized)
            max_drawdown_pct: Current drawdown as percentage (0-100) for adaptive Kelly
            local_vol_pct: Recent PnL volatility as percentage (0-100) for adaptive Kelly
            sentiment_vol_asset: Asset symbol to lookup sentiment/vol sizing (e.g., "BTC")
            is_contrarian: If True, applies contrarian boost in extreme sentiment regimes
            sentiment_timeframe: Timeframe for sentiment lookup
            market_ticker: Market ticker for logging
            swarm_score: Swarm confidence score
            swarm_confidence: Swarm confidence level
            decision_trace_id: Trace ID for logging
        
        Returns:
            Integer contract count (0 if trade should be skipped).
        """
        cfg = self._config
        
        # Extract canonical values from EdgeResult
        fee_aware_edge_prob = edge_result.edge_fee_adjusted  # Already fee-adjusted
        fee_cost_cents = edge_result.fee_cost_cents
        price_cents = edge_result.metadata.get("price_cents", 50)  # From contract
        
        # Validate price
        if price_cents <= 0 or price_cents >= 100:
            logger.warning(
                "[PositionSizer] invalid price_cents=%d from EdgeResult for %s — returning 0 contracts",
                price_cents, agent_name
            )
            return 0
        
        # Recover q from edge_fee_adjusted: q = π + edge_fee_adjusted
        # P1-FIX2: edge_fee_adjusted already accounts for fees, so do not add fee_cost_prob again
        market_implied_prob = edge_result.market_implied_prob
        est_win_prob = market_implied_prob + fee_aware_edge_prob
        est_win_prob = max(PROB_MIN_BOUND, min(PROB_MAX_BOUND, est_win_prob))
        
        # Kelly calculation
        win_payout = 100 - price_cents
        loss_amount = price_cents
        raw_kelly = kelly_fraction_for_binary(est_win_prob, win_payout, loss_amount)
        
        # Edge sanity logging (debug level to avoid spam)
        logger.debug(
            "[EDGE_SANITY-EDGE-RESULT] agent=%s p_model=%.4f p_market=%.4f net_edge=%.4f raw_kelly=%.6f "
            "kelly_fraction_config=%.3f edge_fee_adjusted=%.4f fee_cost_cents=%.2f",
            agent_name, est_win_prob, market_implied_prob, fee_aware_edge_prob, raw_kelly,
            cfg.kelly_fraction, fee_aware_edge_prob, fee_cost_cents
        )
        
        if raw_kelly <= 0:
            logger.warning(
                "[PositionSizer] raw_kelly=%.4f <= 0 for %s (edge_fee_adjusted=%.4f, price_cents=%d) — returning 0 contracts",
                raw_kelly, agent_name, fee_aware_edge_prob, price_cents
            )
            return 0
        
        # Apply fractional Kelly with adaptive shrinkage (reuse existing logic)
        adapted_fraction = adaptive_kelly_fraction(
            cfg.kelly_fraction,
            profit_factor=profit_factor,
            max_drawdown_pct=max_drawdown_pct,
            local_vol_pct=local_vol_pct,
        )
        f = raw_kelly * adapted_fraction

        # ── Sentiment/Volatility sizing multiplier (reuse existing logic) ───────────────
        sentiment_vol_multiplier = 1.0
        sizing_reasoning = ""
        if sentiment_vol_asset:
            try:
                from merid.prediction.risk.sentiment_vol_service import get_current_sizing_multiplier
                sv_mult = get_current_sizing_multiplier(sentiment_vol_asset, is_contrarian)
                sentiment_vol_multiplier = sv_mult.value
                sizing_reasoning = sv_mult.reasoning
                logger.debug(
                    "PositionSizer: %s sentiment/vol multiplier=%.3f (regime=%s, reason=%s)",
                    sentiment_vol_asset, sentiment_vol_multiplier, sv_mult.get_regime_label(), sizing_reasoning
                )
            except Exception as exc:
                logger.debug("PositionSizer: sentiment/vol lookup failed for %s: %s", sentiment_vol_asset, exc)
        
        f *= sentiment_vol_multiplier

        # ── PF/expectancy scaling gate (reuse existing logic) ────────────────────────────
        scale = self._pf_scale(profit_factor, expectancy_cents, total_trades)
        if scale <= 0:
            logger.warning(
                "[PositionSizer] PF scale=%.4f <= 0 for %s (profit_factor=%.2f) — returning 0 contracts",
                scale, agent_name, profit_factor
            )
            return 0
        f *= scale

        # ── Convert fraction to contracts (reuse existing logic) ─────────────────────────
        # Use canonical fee from EdgeResult instead of recalculating
        risk_per_contract = loss_amount + fee_cost_cents

        if risk_per_contract <= 0:
            return 0

        bankroll_risk = f * bankroll_cents
        contracts_from_kelly = int(bankroll_risk / risk_per_contract)

        # ── Apply caps (reuse existing logic) ────────────────────────────────────────────
        # Bankroll percentage cap
        max_from_bankroll = int(
            (cfg.max_bankroll_pct / 100.0) * bankroll_cents / risk_per_contract
        )
        contracts = min(contracts_from_kelly, max_from_bankroll)

        # P2-FIX5: Per-trade risk cap (0.8% of bankroll max per trade)
        max_from_per_trade_risk = int(
            cfg.per_trade_risk_pct * bankroll_cents / risk_per_contract
        )
        contracts = min(contracts, max_from_per_trade_risk)

        # Absolute contract limits — respect Kelly=0 (no edge → no trade)
        if contracts_from_kelly > 0:
            contracts = max(cfg.min_contracts, min(contracts, cfg.max_contracts))
        else:
            contracts = 0

        # Per-underlying hourly exposure cap
        remaining_capacity = max(
            0,
            cfg.max_contracts_per_underlying_per_hour - current_exposure_contracts,
        )
        contracts = min(contracts, remaining_capacity)

        # Capacity exhausted → no trade (must check BEFORE enforcing min-1)
        if contracts <= 0:
            return 0

        # Apply size_factor from risk governance (e.g. 0.5 for downsized)
        contracts = max(1, int(contracts * size_factor))

        # ── Cycle drawdown multiplier (reuse existing logic) ───────────────────────────
        try:
            from merid.event_venues.kalshi.cycle_drawdown import get_cycle_drawdown_manager
            cdm = get_cycle_drawdown_manager()
            cycle_mult = cdm.get_cycle_risk_multiplier()
            if cycle_mult < 1.0:
                contracts = max(1, int(contracts * cycle_mult))
                logger.debug(
                    "PositionSizer: %s cycle drawdown multiplier=%.3f contracts=%d",
                    agent_name, cycle_mult, contracts
                )
        except Exception as exc:
            logger.debug("PositionSizer: cycle drawdown multiplier failed (fail-open): %s", exc)

        # Final bounds
        contracts = max(0, min(contracts, cfg.max_contracts))

        # Final logging (info level for visibility)
        logger.info(
            "[PositionSizer-EDGE-RESULT] agent=%s raw_kelly=%.4f adapted=%.4f kelly_contracts=%d "
            "bankroll_cap=%d final_contracts=%d",
            agent_name, raw_kelly, f, contracts_from_kelly, max_from_bankroll, contracts
        )

        # Rate/activity check (reuse existing logic)
        if contracts > 0:
            current_time = _time.time()
            self._trade_timestamps.append(current_time)

            recent_computations = [t for t in self._trade_timestamps if current_time - t < 300]
            if len(recent_computations) > 10:
                logger.warning(
                    "[ACTIVITY_CHECK] Position sizing frequency spike detected: %d sizing computations in last 5 minutes. "
                    "NOTE: These are sizing computations, NOT actual trades.",
                    len(recent_computations)
                )

        if sentiment_vol_asset and contracts > 0:
            risk_cents = contracts * (price_cents + fee_cost_cents)
            logger.info(
                "[sentiment_sizing-EDGE-RESULT] trace=%s asset=%s timeframe=%s ticker=%s "
                "swarm_score=%s swarm_confidence=%s size_contracts=%d risk_cents≈%.0f",
                decision_trace_id or "-",
                sentiment_vol_asset,
                sentiment_timeframe or "-",
                market_ticker or "-",
                f"{swarm_score:.4f}" if swarm_score is not None else "-",
                f"{swarm_confidence:.4f}" if swarm_confidence is not None else "-",
                contracts,
                risk_cents,
            )

        return contracts

    def _pf_scale(
        self,
        profit_factor: float,
        expectancy_cents: float,
        total_trades: int,
    ) -> float:
        """Compute a 0–1 scaling factor based on measured PF and expectancy.

        - Below min sample size → minimum scale
        - Below PF floor → minimum scale
        - Negative expectancy → 0 (don't trade)
        - Linear ramp from pf_min_for_scaling to pf_full_kelly_at
        """
        cfg = self._config

        # Negative expectancy → don't trade at all
        if expectancy_cents < 0 and total_trades >= cfg.min_trades_for_scaling:
            return 0.0

        # Not enough data → use full scale (1.0) to allow trading
        # BUG-FIX: Previously returned min/max ratio (0.125) which caused 0 contracts
        # when combined with low bankroll. Now uses 1.0 to allow Kelly sizing to work.
        if total_trades < cfg.min_trades_for_scaling:
            return 1.0

        # Below expectancy floor → minimum scale
        if expectancy_cents < cfg.expectancy_min_cents:
            return cfg.min_bankroll_pct / cfg.max_bankroll_pct

        # PF-based linear ramp
        if profit_factor <= 0 or profit_factor < cfg.pf_min_for_scaling:
            return cfg.min_bankroll_pct / cfg.max_bankroll_pct

        if profit_factor >= cfg.pf_full_kelly_at:
            return 1.0

        # Linear interpolation between min and full
        range_pf = cfg.pf_full_kelly_at - cfg.pf_min_for_scaling
        if range_pf <= 0:
            # Degenerate case: pf_min == pf_full, jump directly to full scale
            return 1.0
        progress = (profit_factor - cfg.pf_min_for_scaling) / range_pf
        min_scale = cfg.min_bankroll_pct / cfg.max_bankroll_pct
        return min_scale + progress * (1.0 - min_scale)

    def explain(
        self,
        agent_name: str,
        edge_pct: float,
        price_cents: int,
        bankroll_cents: int = 500_000,
        *,
        profit_factor: float = 0.0,
        expectancy_cents: float = 0.0,
        total_trades: int = 0,
        current_exposure_contracts: int = 0,
        size_factor: float = 1.0,
        max_drawdown_pct: float = 0.0,
        local_vol_pct: float = 0.0,
        sentiment_vol_asset: Optional[str] = None,
        is_contrarian: bool = False,
    ) -> Dict[str, Any]:
        """Compute size and return a detailed explanation dict."""
        cfg = self._config

        implied_prob = price_cents / 100.0
        est_win_prob = max(0.01, min(0.99, implied_prob + edge_pct))  # edge_pct already in FRACTION
        win_payout = 100 - price_cents
        loss_amount = price_cents

        raw_kelly = kelly_fraction_for_binary(est_win_prob, win_payout, loss_amount)
        adapted_fraction = adaptive_kelly_fraction(
            cfg.kelly_fraction,
            profit_factor=profit_factor,
            max_drawdown_pct=max_drawdown_pct,
            local_vol_pct=local_vol_pct,
        )
        fractional_kelly = raw_kelly * adapted_fraction
        pf_scale = self._pf_scale(profit_factor, expectancy_cents, total_trades)

        # Get sentiment/vol multiplier for explanation
        sentiment_vol_mult = 1.0
        sv_regime = None
        sv_reasoning = ""
        if sentiment_vol_asset:
            try:
                from merid.prediction.risk.sentiment_vol_service import get_current_sizing_multiplier
                sv_data = get_current_sizing_multiplier(sentiment_vol_asset, is_contrarian)
                sentiment_vol_mult = sv_data.value
                sv_regime = sv_data.get_regime_label()
                sv_reasoning = sv_data.reasoning
            except Exception as e:
                logger.debug(f"Sentiment-vol sizing unavailable: {e}")

        contracts = self.compute(
            agent_name, edge_pct, price_cents, bankroll_cents,
            profit_factor=profit_factor,
            expectancy_cents=expectancy_cents,
            total_trades=total_trades,
            current_exposure_contracts=current_exposure_contracts,
            size_factor=size_factor,
            max_drawdown_pct=max_drawdown_pct,
            local_vol_pct=local_vol_pct,
            sentiment_vol_asset=sentiment_vol_asset,
            is_contrarian=is_contrarian,
        )

        # P2-4 FIX: Calculate fee based on actual computed contracts for tier accuracy
        fee_per_contract = kalshi_fee_per_contract_cents(price_cents, contracts)
        risk_per_contract = loss_amount + fee_per_contract

        return {
            "agent": agent_name,
            "contracts": contracts,
            "edge_pct": edge_pct,
            "price_cents": price_cents,
            "implied_prob": round(implied_prob, 4),
            "est_win_prob": round(est_win_prob, 4),
            "raw_kelly": round(raw_kelly, 6),
            "fractional_kelly": round(fractional_kelly, 6),
            "kelly_fraction_config": cfg.kelly_fraction,
            "adapted_kelly_fraction": round(adapted_fraction, 6),
            "max_drawdown_pct": max_drawdown_pct,
            "local_vol_pct": local_vol_pct,
            "sentiment_vol_multiplier": round(sentiment_vol_mult, 4),
            "sentiment_vol_regime": sv_regime,
            "sentiment_vol_reasoning": sv_reasoning,
            "pf_scale": round(pf_scale, 4),
            "profit_factor": profit_factor,
            "expectancy_cents": expectancy_cents,
            "total_trades": total_trades,
            "risk_per_contract_cents": risk_per_contract,
            "fee_per_contract_cents": fee_per_contract,
            "bankroll_cents": bankroll_cents,
            "size_factor": size_factor,
            "current_exposure": current_exposure_contracts,
        }


# ── Kelly utilization tracker ────────────────────────────────────────────

class KellyUtilizationTracker:
    """Tracks actual vs theoretical Kelly fraction per trade.

    Records each trade's theoretical full-Kelly fraction, the adapted
    fraction actually used, and the effective bankroll percentage risked.
    Reports rolling utilization metrics for monitoring and promotion gates.

    Usage::

        tracker = KellyUtilizationTracker()
        tracker.record(raw_kelly=0.12, adapted_fraction=0.03,
                       contracts=5, risk_per_contract_cents=57,
                       bankroll_cents=500_000)
        tracker.summary()
    """

    def __init__(self, window_size: int = 200) -> None:
        self._window_size = window_size
        self._records: list[Dict[str, float]] = []

    def record(
        self,
        raw_kelly: float,
        adapted_fraction: float,
        contracts: int,
        risk_per_contract_cents: float,
        bankroll_cents: float,
    ) -> None:
        """Record one trade's Kelly utilization.

        Args:
            raw_kelly: Full Kelly fraction (before fractional/adaptive).
            adapted_fraction: The Kelly fraction actually used (after
                adaptive shrinkage).
            contracts: Contracts actually sized.
            risk_per_contract_cents: Risk per contract including fees.
            bankroll_cents: Total bankroll at time of trade.
        """
        actual_risked_pct = 0.0
        if bankroll_cents > 0:
            actual_risked_pct = (contracts * risk_per_contract_cents) / bankroll_cents * 100

        theoretical_risk_pct = raw_kelly * 100

        utilization = 0.0
        if raw_kelly > 0:
            utilization = (adapted_fraction / raw_kelly) * 100

        self._records.append({
            "raw_kelly": raw_kelly,
            "adapted_fraction": adapted_fraction,
            "actual_risked_pct": actual_risked_pct,
            "theoretical_risk_pct": theoretical_risk_pct,
            "utilization_pct": utilization,
            "contracts": float(contracts),
        })

        if len(self._records) > self._window_size:
            self._records = self._records[-self._window_size:]

    def summary(self) -> Dict[str, Any]:
        """Rolling summary of Kelly utilization metrics."""
        if not self._records:
            return {
                "trade_count": 0,
                "avg_raw_kelly_pct": 0.0,
                "avg_adapted_fraction_pct": 0.0,
                "avg_actual_risked_pct": 0.0,
                "avg_utilization_pct": 0.0,
                "avg_contracts": 0.0,
            }

        n = len(self._records)
        return {
            "trade_count": n,
            "avg_raw_kelly_pct": round(
                sum(r["raw_kelly"] for r in self._records) / n * 100, 4
            ),
            "avg_adapted_fraction_pct": round(
                sum(r["adapted_fraction"] for r in self._records) / n * 100, 4
            ),
            "avg_actual_risked_pct": round(
                sum(r["actual_risked_pct"] for r in self._records) / n, 4
            ),
            "avg_utilization_pct": round(
                sum(r["utilization_pct"] for r in self._records) / n, 2
            ),
            "avg_contracts": round(
                sum(r["contracts"] for r in self._records) / n, 1
            ),
        }

    @property
    def trade_count(self) -> int:
        return len(self._records)

    def reset(self) -> None:
        self._records.clear()


# ── Singleton ────────────────────────────────────────────────────────────

_sizer: Optional[PositionSizer] = None
_sizer_lock = threading.Lock()


def get_position_sizer(config: Optional[SizerConfig] = None) -> PositionSizer:
    """Get or create the singleton PositionSizer."""
    global _sizer
    if _sizer is None:
        with _sizer_lock:
            if _sizer is None:
                _sizer = PositionSizer(config)
    return _sizer
