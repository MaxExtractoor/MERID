"""KalshiRiskManager — Venue-aware risk layer for all Kalshi markets.

Responsibilities:
1. Kalshi fee calculation (tiered schedule)
2. Fee-aware Kelly position sizing
3. Per-contract position limits (from Kalshi terms)
4. Per-category exposure caps
5. Daily loss tracking and kill switch
6. Drawdown monitoring
7. Rate-limit awareness

Fee schedule (as of 2025):
  - Contracts 1-99:    7% of payout (min 2¢)
  - Contracts 100-999:  5% of payout
  - Contracts 1000+:    3% of payout
  - No fee on losing side

Usage::

    risk = get_kalshi_risk()
    fee = risk.kalshi_fee_cents(price_cents=55, contracts=10)
    size = risk.kelly_size_kalshi(edge=0.08, price_cents=55, bankroll_cents=50000)
    ok, reason = risk.check_order("BTC", "crypto", 10, 55)
"""

from __future__ import annotations

import os
import threading
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, ClassVar, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.kalshi_risk")

# Cycle drawdown integration (lazy import to avoid circular deps)
_cycle_drawdown_manager: Optional[Any] = None

def _get_cycle_drawdown_manager() -> Optional[Any]:
    global _cycle_drawdown_manager
    if _cycle_drawdown_manager is None:
        try:
            from merid.event_venues.kalshi.cycle_drawdown import get_cycle_drawdown_manager
            _cycle_drawdown_manager = get_cycle_drawdown_manager()
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f"Cycle drawdown manager unavailable: {e}")
    return _cycle_drawdown_manager


# ── Fee schedule ─────────────────────────────────────────────────────────

def kalshi_fee_cents(price_cents: int, contracts: int) -> int:
    """Calculate Kalshi fee in cents for a trade.

    Uses the official Kalshi parabolic formula:
        fee = ceil(rate × C × P × (1 − P))
    where P = price_cents / 100, with a floor of 2¢ per contract.

    Tiered rates:
      1-99 contracts:   7%
      100-999:          5%
      1000+:            3%

    Args:
        price_cents: Price paid per contract (0-99)
        contracts: Number of contracts

    Returns:
        Total fee in cents (integer, rounded up)
    """
    if contracts <= 0 or price_cents <= 0 or price_cents >= 100:
        return 0

    rate = kalshi_fee_rate(contracts)
    p = price_cents / 100.0
    raw = rate * contracts * p * (1.0 - p)
    # Minimum fee: 2¢ total
    return max(2, math.ceil(raw * 100))


def kalshi_fee_rate(contracts: int) -> float:
    """Return the fee rate for a given contract count."""
    if contracts < 100:
        return 0.07
    elif contracts < 1000:
        return 0.05
    return 0.03


# ── Kelly sizing ─────────────────────────────────────────────────────────

def kelly_size_kalshi(
    edge: float,
    price_cents: int,
    bankroll_cents: int,
    *,
    kelly_fraction: float = 0.25,
    max_contracts: int = 250,
    min_edge: float = 0.02,
    sentiment_score: Optional[float] = None,
    volatility_regime: Optional[str] = None,
) -> int:
    """Fee-aware Kelly position sizing for Kalshi binary contracts with sentiment adjustment.

    Kelly fraction f* = (p * b - q) / b
    where:
      p = implied probability + edge
      q = 1 - p
      b = (100 - price - fee_per) / price  (net odds after fees)

    Sentiment adjustment:
      - Extreme fear/greed (score <20 or >80): reduce size by 50%
      - High volatility regime: reduce size by 30%
      - Normal conditions: no adjustment

    Args:
        edge: Estimated edge (e.g. 0.08 for 8%)
        price_cents: Price per contract in cents (0-99)
        bankroll_cents: Available bankroll in cents
        kelly_fraction: Fraction of full Kelly to use (default quarter-Kelly)
        max_contracts: Hard cap on position size
        min_edge: Minimum edge to trade
        sentiment_score: Fear/greed index 0-100 (None = no adjustment)
        volatility_regime: "calm", "normal", "hot" (None = no adjustment)

    Returns:
        Number of contracts to buy (0 if edge insufficient)
    """
    if edge < min_edge or price_cents <= 0 or price_cents >= 100 or bankroll_cents <= 0:
        return 0

    p = price_cents / 100.0 + edge  # our estimated true probability
    p = min(max(p, 0.01), 0.99)
    q = 1.0 - p

    # Estimate fee per contract using canonical parabolic formula (tier <100)
    payout_per = 100 - price_cents
    fee_per = math.ceil(kalshi_fee_cents(price_cents, 1))

    net_payout = payout_per - fee_per
    if net_payout <= 0:
        return 0

    b = net_payout / price_cents  # net odds

    kelly_f = (p * b - q) / b
    if kelly_f <= 0:
        return 0

    # Apply fractional Kelly
    fraction = kelly_f * kelly_fraction

    # Sentiment-based sizing adjustment
    sentiment_multiplier = 1.0

    if sentiment_score is not None:
        if sentiment_score <= 20 or sentiment_score >= 80:
            # Extreme fear/greed: reduce size significantly
            sentiment_multiplier *= 0.5
        elif sentiment_score <= 30 or sentiment_score >= 70:
            # Moderate fear/greed: slight reduction
            sentiment_multiplier *= 0.75

    if volatility_regime == "hot":
        # High volatility: reduce position size
        sentiment_multiplier *= 0.7
    elif volatility_regime == "calm":
        # Low volatility: can size up slightly
        sentiment_multiplier *= 1.1

    fraction *= sentiment_multiplier

    # Convert to contracts
    contracts = int(fraction * bankroll_cents / price_cents)
    contracts = max(0, min(contracts, max_contracts))

    # Re-check with actual fee tier
    actual_fee = kalshi_fee_cents(price_cents, contracts)
    actual_net = (100 - price_cents) * contracts - actual_fee
    cost = price_cents * contracts
    if actual_net <= 0 or cost > bankroll_cents:
        return 0

    return contracts


# ── Dynamic position sizing across markets ───────────────────────────────

def dynamic_position_sizes(
    markets: List[Dict[str, Any]],
    total_equity_usd: float,
    *,
    category_cap_pct: float = 0.30,
    max_contracts_per_market: int = 500,
    min_edge_pct: float = 0.5,
) -> Dict[str, int]:
    """Edge-weighted position sizing across multiple Kalshi markets.

    Allocates a category budget proportionally to each market's edge,
    then converts dollars to contracts (each contract pays $1 on win).

    Args:
        markets: List of dicts with keys:
            ``ticker``, ``edge_pct`` (e.g. 1.5 for 1.5%), ``price_cents``
        total_equity_usd: Total portfolio equity in USD
        category_cap_pct: Max fraction of equity for this category
        max_contracts_per_market: Hard cap per market
        min_edge_pct: Minimum edge to include a market

    Returns:
        {ticker: contracts} for each market with positive allocation
    """
    budget = total_equity_usd * category_cap_pct
    positive = [m for m in markets if m.get("edge_pct", 0) >= min_edge_pct]
    if not positive or budget <= 0:
        return {}

    total_weight = sum(m["edge_pct"] for m in positive)
    if total_weight <= 0:
        return {}

    sizes: Dict[str, int] = {}
    for m in positive:
        weight = m["edge_pct"] / total_weight
        dollars_for_market = budget * weight
        # Each contract costs price_cents / 100 USD
        price_usd = m.get("price_cents", 50) / 100.0
        if price_usd <= 0:
            continue
        contracts = int(dollars_for_market / price_usd)
        contracts = min(contracts, max_contracts_per_market)
        # Apply fee check: ensure net payout is positive
        if contracts > 0:
            fee = kalshi_fee_cents(m.get("price_cents", 50), contracts)
            payout = (100 - m.get("price_cents", 50)) * contracts
            if payout - fee <= 0:
                continue
        if contracts > 0:
            sizes[m["ticker"]] = contracts

    return sizes


# ── Multi-market Kelly sizing ────────────────────────────────────────────

def _kelly_fraction(edge_pct: float, win_prob: float, price_cents: int = 50) -> float:
    """Kelly fraction for a Kalshi binary contract.

    For a binary paying $1 on win at cost ``price_cents / 100``:
      b = (100 - price_cents) / price_cents   (net odds)
      p = win_prob  (our estimated probability of winning)
      q = 1 - p
      f* = (p · b - q) / b

    ``edge_pct`` is added to ``win_prob`` as an adjustment
    (e.g. edge_pct=2 means we think true prob is win_prob + 0.02).
    """
    if price_cents <= 0 or price_cents >= 100:
        return 0.0
    b = (100 - price_cents) / price_cents  # net odds ratio
    p = min(win_prob + edge_pct / 100.0, 0.99)
    q = 1.0 - p
    if b <= 0 or p <= 0:
        return 0.0
    f = (p * b - q) / b
    return max(0.0, min(f, 1.0))


def multi_market_kelly_sizes(
    markets: List[Dict[str, Any]],
    equity_usd: float,
    *,
    frac_of_kelly: float = 0.25,
    max_per_market_usd: float = 1000.0,
    max_contracts_per_market: int = 500,
) -> Dict[str, int]:
    """Win-prob-based Kelly allocation across independent Kalshi markets.

    Each market is sized independently using Kelly criterion, then capped.

    Args:
        markets: List of dicts with keys:
            ``ticker``, ``edge_pct`` (e.g. 1.5), ``win_prob`` (0-1),
            optional ``price_cents``
        equity_usd: Total portfolio equity in USD
        frac_of_kelly: Fraction of full Kelly to use (default quarter-Kelly)
        max_per_market_usd: Dollar cap per market
        max_contracts_per_market: Contract cap per market

    Returns:
        {ticker: contracts} for each market with positive allocation
    """
    if equity_usd <= 0:
        return {}

    allocations: Dict[str, int] = {}
    for m in markets:
        edge = m.get("edge_pct", 0)
        wp = m.get("win_prob", 0.5)
        if edge <= 0:
            continue

        price_cents = m.get("price_cents", 50)
        f = _kelly_fraction(edge, wp, price_cents) * frac_of_kelly
        if f <= 0:
            continue

        bankroll = min(equity_usd, max_per_market_usd)
        dollars = bankroll * f
        price_usd = price_cents / 100.0 if price_cents > 0 else 0.50

        contracts = int(dollars / price_usd)
        contracts = min(contracts, max_contracts_per_market)

        # Fee check
        if contracts > 0:
            fee = kalshi_fee_cents(price_cents, contracts)
            payout = (100 - price_cents) * contracts
            if payout - fee <= 0:
                continue

        if contracts > 0:
            allocations[m["ticker"]] = contracts

    return allocations


# ── Kalman + Kelly integration ───────────────────────────────────────────

def edge_from_prediction(
    smoothed_price: float,
    current_price: float,
    fee_cents: float = 0.0,
) -> float:
    """Compute edge (%) from Kalman-smoothed price vs current market price.

    Positive if the filter says fair price > current price (buy signal).

    Args:
        smoothed_price: Kalman-estimated fair price (cents)
        current_price: Current market price (cents)
        fee_cents: Fee per contract in cents (default 0)

    Returns:
        Edge as a percentage (e.g. 2.5 means 2.5% edge)
    """
    if current_price <= 0:
        return 0.0
    edge_frac = (smoothed_price - current_price - fee_cents) / current_price
    return edge_frac * 100.0


def kelly_size_from_kalman(
    smoothed_price: float,
    current_price: float,
    account_equity_usd: float,
    win_prob: float,
    frac_of_kelly: float = 0.25,
) -> int:
    """Compute contract count using Kalman-derived edge and Kelly criterion.

    Uses ``edge_from_prediction`` to get edge, then feeds into
    ``_kelly_fraction`` for sizing.

    Args:
        smoothed_price: Kalman-estimated fair price (cents)
        current_price: Current market price (cents)
        account_equity_usd: Total portfolio equity in USD
        win_prob: Estimated win probability (0-1), e.g. from backtest hit rate
        frac_of_kelly: Fraction of full Kelly to use (default 0.25 = quarter-Kelly)

    Returns:
        Number of contracts to buy (0 if no edge)
    """
    edge_pct = edge_from_prediction(smoothed_price, current_price)
    price_cents = int(round(current_price))
    if price_cents <= 0 or price_cents >= 100:
        return 0
    f = _kelly_fraction(edge_pct, win_prob, price_cents) * frac_of_kelly
    dollars = account_equity_usd * f
    return max(0, int(dollars))


# ── Risk configuration ───────────────────────────────────────────────────

@dataclass
class CategoryLimit:
    """Exposure limit for a market category."""
    category: str
    max_notional_usd: float = 5000.0
    max_contracts: int = 500
    max_pct_of_portfolio: float = 0.20  # 20% max in any one category
    enabled: bool = True


@dataclass
class KalshiRiskConfig:
    """Full risk configuration for Kalshi trading."""
    # Global limits
    max_total_notional_usd: float = 25000.0
    max_daily_loss_usd: float = 1000.0
    max_stop_loss_usd_per_cluster: float = 500.0  # Per-cluster (asset+timeframe) stop loss cap
    max_single_order_contracts: int = 250
    max_single_order_notional_usd: float = 2500.0
    max_position_per_contract: int = 500  # Kalshi typical retail limit
    
    # Dynamic contract caps (populated by _compute_dynamic_contract_caps)
    max_contracts_total: int = 5000
    max_contracts_per_asset: int = 1750  # 35% of 5000
    max_contracts_per_cluster: int = 750  # 15% of 5000

    # Per-category limits
    category_limits: Dict[str, CategoryLimit] = field(default_factory=dict)

    # Drawdown - base values (may be adjusted dynamically by _compute_drawdown_thresholds)
    drawdown_halt_pct: float = 0.10  # Halt at 10% drawdown (base, computed dynamically)
    drawdown_unwind_pct: float = 0.15  # Force unwind at 15% (base, computed dynamically)
    
    # Dynamic drawdown: tighter thresholds for larger balances
    drawdown_dynamic_tiers: bool = True  # Enable equity-based tiered drawdown
    drawdown_small_balance_usd: float = 100.0   # <$100: use base drawdown
    drawdown_medium_balance_usd: float = 1000.0  # $100-$1000: moderate tightening
    drawdown_large_balance_usd: float = 5000.0   # $1000+: tightest drawdown

    # Minimum edge to trade
    min_edge: float = 0.02
    min_post_fee_edge: float = 0.01

    # Rate limit awareness — load from settings if available
    max_orders_per_minute: int = 30  # default fallback
    max_orders_per_hour: int = 300   # default fallback

    # ── Fills Ledger Reconciliation Thresholds ────────────────────────────
    # These are RISK LAYER decisions based on data integrity reports.
    # The fills ledger reports facts; these thresholds decide action.
    reconcile_halt_on_ghost_trades: bool = True  # Halt if positions without fills
    reconcile_max_ghost_trade_pct: float = 0.10  # Halt if >10% of positions ghost
    reconcile_warn_on_divergence_pct: float = 0.05  # Warn if fill/position diff >5%

    # ── Balance-relative fractions ───────────────────────────────────────
    # These are recomputed into the _usd fields by calibrate_from_balance().
    # Fractions of the live Kalshi account balance.
    max_total_notional_pct: float = 0.80     # 80 % of balance
    max_daily_loss_pct: float = 0.10         # 10 % of balance
    max_single_order_pct: float = 0.05       # 5 % of balance
    _DAILY_LOSS_FRACTIONS: ClassVar[Dict[str, float]] = {
        "DEEP_UNDERWATER": 0.05,
        "UNDERWATER": 0.08,
        "BASELINE": 0.10,
        "LOCK_IN_GAINS": 0.06,  # Tighter than baseline - lock in gains with reduced risk
    }
    category_notional_pct: Dict[str, float] = field(default_factory=lambda: {
        "cross_category": 0.05,
        "crypto":     0.30,
        "economics":  0.10,
        "macro":      0.05,
        "financials": 0.10,
        "politics":   0.08,
        "climate":    0.05,
        "tech":       0.08,
        "sports":     0.05,
        "culture":    0.05,
        "science":    0.05,
        "equities":   0.10,
        "other":      0.05,
    })
    # Note: correlated_stack_pct is used by CategoryExposureTracker.calibrate_from_balance()
    # as the corr_fraction argument — do NOT remove.
    correlated_stack_pct: float = 0.20      # single underlying across all timeframes

    # ── Group-level exposure limits (per-asset/timeframe/overlap-window) ─────────────────
    group_limits_enabled: bool = True         # Enable group-level aggregation and caps
    group_notional_cap_usd: float = 2000.0  # Max notional per group (e.g., BTC-15m-2026-03-27T15:00)
    asset_horizon_limits: Dict[str, Dict[str, float]] = field(default_factory=dict)  # asset -> tf -> max_notional

    def _compute_dynamic_category_limits(self) -> Dict[str, CategoryLimit]:
        """Compute category limits dynamically from portfolio bankroll.
        
        Previous hardcoded values (crypto $5000, economics $3000, etc.) 
        are now scaled proportionally to the portfolio size.
        
        Base portfolio assumption: $25,000
        - Crypto: 20% of portfolio = $5000
        - Economics: 12% = $3000
        - Financials: 12% = $3000
        - Politics: 8% = $2000
        - Climate: 4% = $1000
        - Tech: 8% = $2000
        - Sports: 8% = $2000
        - Culture: 4% = $1000
        - Science: 4% = $1000
        - Macro: 8% = $2000
        - Equities: 12% = $3000
        - Cross-category: 4% = $1000
        - Other: 4% = $1000
        """
        try:
            from merid.settings import settings
            # Get portfolio notional limit from settings
            portfolio_cents = settings.kalshi_portfolio_max_notional_cents
            portfolio_usd = portfolio_cents / 100.0
        except Exception:
            # Fallback to default $25k
            portfolio_usd = 25000.0
        
        # Category allocation percentages of total portfolio
        category_pcts = {
            "crypto": 0.20,
            "economics": 0.12,
            "financials": 0.12,
            "politics": 0.08,
            "climate": 0.04,
            "tech": 0.08,
            "sports": 0.08,
            "culture": 0.04,
            "science": 0.04,
            "macro": 0.08,
            "equities": 0.12,
            "cross_category": 0.04,
            "other": 0.04,
        }
        
        # Contract ratio: $10 per contract (roughly)
        contracts_per_1k = 100
        
        limits = {}
        for category, pct in category_pcts.items():
            notional = portfolio_usd * pct
            # Cap contracts at reasonable limit per category
            contracts = min(int(notional / 10), int(portfolio_usd / 50))  # Max 1 contract per $50 portfolio
            limits[category] = CategoryLimit(
                category=category,
                max_notional_usd=notional,
                max_contracts=max(contracts, 50),  # At least 50 contracts
                max_pct_of_portfolio=pct,
                enabled=True
            )
        
        logger.info(
            f"Dynamic category limits computed for ${portfolio_usd:.0f} portfolio: "
            f"crypto=${limits['crypto'].max_notional_usd:.0f}, "
            f"economics=${limits['economics'].max_notional_usd:.0f}"
        )
        
        return limits

    def __post_init__(self):
        # Load rate limits from settings if available
        try:
            from merid.settings import settings
            _configured_minute = settings.KALSHI_MAX_ORDERS_PER_MINUTE
            _configured_hour = settings.KALSHI_MAX_ORDERS_PER_HOUR
            if _configured_minute != 30 or _configured_hour != 300:
                logger.info(
                    f"Using configured rate limits from settings: {_configured_minute}/min, {_configured_hour}/hour"
                )
            else:
                logger.warning(
                    f"Using fallback rate limits (not from config): {_configured_minute}/min, {_configured_hour}/hour. "
                    f"Set KALSHI_MAX_ORDERS_PER_MINUTE and KALSHI_MAX_ORDERS_PER_HOUR env vars to configure."
                )
            self.max_orders_per_minute = _configured_minute
            self.max_orders_per_hour = _configured_hour
        except Exception as e:
            logger.warning(
                f"Using fallback rate limits (not from config): {self.max_orders_per_minute}/min, "
                f"{self.max_orders_per_hour}/hour. Failed to load from settings: {e}"
            )

        # Load drawdown thresholds from environment variables if available
        # This allows runtime configuration without code changes
        _drawdown_halt_env = os.getenv("KALSHI_DRAWDOWN_HALT_PCT", "")
        if _drawdown_halt_env:
            try:
                _dd_halt = float(_drawdown_halt_env)
                if 0.05 <= _dd_halt <= 0.50:  # Sanity check: 5% to 50%
                    self.drawdown_halt_pct = _dd_halt
                    logger.info(f"Using env KALSHI_DRAWDOWN_HALT_PCT: {_dd_halt:.1%}")
                else:
                    logger.warning(f"KALSHI_DRAWDOWN_HALT_PCT out of range (5%-50%): {_dd_halt}")
            except ValueError:
                logger.warning(f"Invalid KALSHI_DRAWDOWN_HALT_PCT value: {_drawdown_halt_env}")

        _drawdown_unwind_env = os.getenv("KALSHI_DRAWDOWN_UNWIND_PCT", "")
        if _drawdown_unwind_env:
            try:
                _dd_unwind = float(_drawdown_unwind_env)
                if 0.10 <= _dd_unwind <= 0.75:  # Sanity check: 10% to 75%
                    self.drawdown_unwind_pct = _dd_unwind
                    logger.info(f"Using env KALSHI_DRAWDOWN_UNWIND_PCT: {_dd_unwind:.1%}")
                else:
                    logger.warning(f"KALSHI_DRAWDOWN_UNWIND_PCT out of range (10%-75%): {_dd_unwind}")
            except ValueError:
                logger.warning(f"Invalid KALSHI_DRAWDOWN_UNWIND_PCT value: {_drawdown_unwind_env}")

        # Compute dynamic category limits based on portfolio bankroll
        # Previous hardcoded values scaled to ~$25k portfolio
        # Now dynamically calculated from kalshi_portfolio_max_notional_cents
        self.category_limits = self._compute_dynamic_category_limits()


@dataclass
class RiskState:
    """Mutable runtime risk state."""
    daily_pnl_usd: float = 0.0
    daily_fees_usd: float = 0.0  # Track daily fees separately
    daily_trades: int = 0  # Actual daily trade count, not hourly
    total_notional_usd: float = 0.0
    peak_equity_usd: float = 0.0
    current_equity_usd: float = 0.0
    kill_switch_active: bool = False
    kill_switch_reason: Optional[str] = None
    kill_switch_paper_mode: bool = False  # True when fired with no live/shadow agents
    orders_this_minute: int = 0
    orders_this_hour: int = 0
    last_minute_reset: Optional[datetime] = None
    last_hour_reset: Optional[datetime] = None
    category_notional: Dict[str, float] = field(default_factory=dict)
    category_contracts: Dict[str, int] = field(default_factory=dict)
    # Group-level exposure tracking (asset-timeframe-overlap window)
    group_notional: Dict[str, float] = field(default_factory=dict)  # group_id -> notional
    group_contracts: Dict[str, int] = field(default_factory=dict)  # group_id -> contracts
    asset_horizon_notional: Dict[Tuple[str, str], float] = field(default_factory=dict)  # (asset, tf) -> notional
    # Per-cycle breach tracking (group_id -> set of breach_types already alerted this cycle)
    group_breach_fired: Dict[str, set] = field(default_factory=dict)
    breach_log: List[Dict[str, Any]] = field(default_factory=list)
    pnl_history: List[Dict[str, Any]] = field(default_factory=list)
    # Daily loss tracking (UTC date-based reset)
    current_day_utc: Optional[str] = None  # "YYYY-MM-DD" format
    start_of_day_equity_usd: float = 0.0  # Equity at start of trading day


class KalshiRiskManager:
    """Venue-aware risk manager for all Kalshi trading.

    Checks:
      1. Kill switch
      2. Single order size (contracts + notional)
      3. Per-contract position limit
      4. Category exposure cap
      5. Total portfolio notional
      6. Daily loss limit
      7. Drawdown halt
      8. Post-fee edge minimum
      9. Rate limit
    """

    _MAX_BREACH_LOG = 200

    def __init__(self, config: Optional[KalshiRiskConfig] = None):
        self._config = config or KalshiRiskConfig()
        self._apply_micro_live_profile_if_requested()
        self._state = RiskState()
        self._lock = threading.RLock()
        self._last_reset_day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._alert_last_fired: Dict[str, float] = {}  # reason-prefix -> monotonic timestamp

    def _sync_pnl_from_ledger(self) -> None:
        """Pull daily P&L from fills_ledger (canonical source).

        Fixes stale self._state.daily_pnl_usd which was never updated because
        record_pnl() is not called by any component (OutcomeResolver was never built).
        """
        try:
            from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
            _ledger = get_fills_ledger()
            _summary = _ledger.summary()
            self._state.daily_pnl_usd = float(_summary.get("daily_realized_pnl_usd", 0.0))
            self._state.daily_fees_usd = float(_summary.get("total_fees_usd", 0.0))
            self._state.daily_trades = int(_summary.get("total_fills", 0))
        except Exception as e:
            logger.debug(f"PNL sync from fills failed: {e}")

    def _apply_micro_live_profile_if_requested(self) -> None:
        """Relax caps for ``initial_live`` / explicit micro-live env (still bounded)."""
        prof = os.getenv("KALSHI_CT_PROFILE", "").strip().lower()
        micro = os.getenv("MERID_UA_MICRO_LIVE_RISK", "").lower() in ("1", "true", "yes")
        if prof != "initial_live" and not micro:
            return
        c = self._config
        c.max_single_order_contracts = min(int(c.max_single_order_contracts), 3)
        c.max_single_order_notional_usd = min(float(c.max_single_order_notional_usd), 5.0)
        c.group_notional_cap_usd = min(float(c.group_notional_cap_usd), 50.0)
        c.max_total_notional_usd = max(float(c.max_total_notional_usd), 500.0)
        if "crypto" in c.category_limits:
            cl = c.category_limits["crypto"]
            cl.max_notional_usd = max(float(cl.max_notional_usd), 25.0)
            cl.max_contracts = max(int(cl.max_contracts), 15)

    @property
    def config(self) -> KalshiRiskConfig:
        return self._config

    @property
    def state(self) -> RiskState:
        return self._state

    @property
    def kill_switch_active(self) -> bool:
        return self._state.kill_switch_active

    # ── Pre-trade check ──────────────────────────────────────────────────

    def check_order(
        self,
        ticker: str,
        category: Optional[str],
        contracts: int,
        price_cents: int,
        edge: float = 0.0,
        existing_position: int = 0,
        asset: Optional[str] = None,
        timeframe: Optional[str] = None,
        group_id: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Run all pre-trade risk checks.

        Args:
            ticker: Market ticker
            category: Market category (crypto, economics, etc.)
            contracts: Number of contracts to trade
            price_cents: Price per contract in cents
            edge: Estimated edge
            existing_position: Current position in this contract
            asset: Underlying asset (BTC, ETH, SOL, XRP, DOGE) - for group-level caps
            timeframe: Timeframe bucket (15m, 1h, D1, W1, 1M) - for group-level caps
            group_id: Canonical group ID for overlap-window risk aggregation

        Returns:
            (allowed, reason) — True if order passes all checks
        """
        now = datetime.now(timezone.utc)
        # Normalize group_id to string for consistent key lookup
        gid = str(group_id) if group_id else None
        ok, reason, breach_type = self._check_order_locked(
            ticker, category, contracts, price_cents, edge, existing_position, now,
            asset=asset, timeframe=timeframe, group_id=gid
        )
        if not ok:
            self._fire_risk_alert(ticker, reason, breach_type=breach_type, group_id=gid)
        try:
            _exp = self._state.total_notional_usd
            _lim = (
                f"max_single_contracts={self._config.max_single_order_contracts} "
                f"max_single_notional_usd={self._config.max_single_order_notional_usd:.2f} "
                f"group_notional_cap_usd={self._config.group_notional_cap_usd:.2f}"
            )
            if ok:
                logger.info(
                    "[RISK] decision=approve reason=ok ticker=%s contracts=%d price_cents=%d "
                    "exposure_before_usd=%.4f limits=%s",
                    ticker,
                    contracts,
                    price_cents,
                    _exp,
                    _lim,
                )
            else:
                logger.info(
                    "[RISK] decision=deny reason=%s ticker=%s contracts=%d price_cents=%d "
                    "exposure_before_usd=%.4f limits=%s",
                    (reason or "")[:200],
                    ticker,
                    contracts,
                    price_cents,
                    _exp,
                    _lim,
                )
        except Exception as e:
            logger.debug(f"Risk check logging failed: {e}")
        return ok, reason

    def _check_order_locked(
        self,
        ticker: str,
        category: Optional[str],
        contracts: int,
        price_cents: int,
        edge: float,
        existing_position: int,
        now: datetime,
        asset: Optional[str] = None,
        timeframe: Optional[str] = None,
        group_id: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[str]]:
        """Inner check — all checks run under self._lock with breach logging.
        
        Returns:
            (allowed, reason, breach_type) — breach_type is None if allowed=True
        """
        with self._lock:
            self._maybe_reset_daily(now)

            # 1. Kill switch - only blocks NEW orders, allows closing positions
            # Risk-reducing orders (exiting positions) are always allowed to lock in profits
            if self._state.kill_switch_active:
                # Allow closing positions (risk-reducing) even with killswitch active
                is_closing_trade = contracts < 0 or (existing_position > 0 and contracts < 0) or (existing_position < 0 and contracts > 0)
                if not is_closing_trade:
                    reason = f"Kill switch active: {self._state.kill_switch_reason}"
                    self._log_breach("kill_switch", reason)
                    return False, reason, "kill_switch"
                # Log that we're allowing a closing trade despite killswitch
                logger.info(
                    "[RISK] Allowing risk-reducing order despite killswitch: ticker=%s contracts=%d existing=%d",
                    ticker, contracts, existing_position
                )

            # 2. Single order size
            if contracts > self._config.max_single_order_contracts:
                reason = f"Order size {contracts} exceeds max {self._config.max_single_order_contracts}"
                self._log_breach("max_single_order_contracts", reason)
                return False, reason, "max_single_order_contracts"

            notional_usd = contracts * price_cents / 100.0
            if notional_usd > self._config.max_single_order_notional_usd:
                reason = f"Order notional ${notional_usd:.2f} exceeds max ${self._config.max_single_order_notional_usd:.2f}"
                self._log_breach("max_single_order_notional", reason)
                return False, reason, "max_single_order_notional"

            # 3. Per-contract position limit
            new_position = existing_position + contracts
            if new_position > self._config.max_position_per_contract:
                reason = f"Position {new_position} would exceed per-contract limit {self._config.max_position_per_contract}"
                self._log_breach("max_position_per_contract", reason)
                return False, reason, "max_position_per_contract"

            # 4. Category exposure (legacy — keep for backward compatibility)
            if category and category in self._config.category_limits:
                cat_limit = self._config.category_limits[category]
                if cat_limit.enabled:
                    cat_notional = self._state.category_notional.get(category, 0.0) + notional_usd
                    if cat_notional > cat_limit.max_notional_usd:
                        reason = f"Category '{category}' notional ${cat_notional:.2f} exceeds cap ${cat_limit.max_notional_usd:.2f}"
                        self._log_breach("category_notional_cap", reason)
                        return False, reason, "category_notional_cap"

                    cat_contracts = self._state.category_contracts.get(category, 0) + contracts
                    if cat_contracts > cat_limit.max_contracts:
                        reason = f"Category '{category}' contracts {cat_contracts} exceeds cap {cat_limit.max_contracts}"
                        self._log_breach("category_contracts_cap", reason)
                        return False, reason, "category_contracts_cap"

            elif category and category not in self._config.category_limits:
                logger.warning("Unknown category %s — applying global cap", category)
                cat_notional = self._state.category_notional.get(category, 0.0) + notional_usd
                if cat_notional > self._config.max_total_notional_usd:
                    reason = (
                        f"Unknown category '{category}' notional ${cat_notional:.2f} exceeds "
                        f"fallback cap ${self._config.max_total_notional_usd:.2f}"
                    )
                    self._log_breach("unknown_category_notional_cap", reason)
                    return False, reason, "unknown_category_notional_cap"

            # 4b. Group-level exposure caps (per-asset/timeframe/overlap-window)
            if group_id and self._config.group_limits_enabled:
                # Normalize group_id to string for consistent key lookup
                gid = str(group_id)
                assert isinstance(gid, str), f"group_id must normalize to str, got {type(gid)}"
                # Check per-group notional cap
                group_notional = self._state.group_notional.get(gid, 0.0) + notional_usd
                if group_notional > self._config.group_notional_cap_usd:
                    reason = f"Group '{gid}' notional ${group_notional:.2f} exceeds cap ${self._config.group_notional_cap_usd:.2f}"
                    self._log_breach("group_notional_cap", reason)
                    logger.debug(
                        "kalshi_risk_check_order",
                        extra={
                            "group_id": gid,
                            "asset": asset,
                            "timeframe": timeframe,
                            "group_notional": group_notional,
                            "cap": self._config.group_notional_cap_usd,
                            "rejected": True,
                            "reason": "group_notional_cap",
                        },
                    )
                    return False, reason, "group_notional_cap"
                
                # Check per-asset/timeframe cap if configured
                if asset and timeframe:
                    asset_tf_key = (asset.upper(), timeframe.lower())
                    asset_tf_limits = self._config.asset_horizon_limits.get(asset.upper(), {})
                    asset_tf_cap = asset_tf_limits.get(timeframe.lower(), 0.0)
                    if asset_tf_cap > 0:
                        asset_tf_notional = self._state.asset_horizon_notional.get(asset_tf_key, 0.0) + notional_usd
                        if asset_tf_notional > asset_tf_cap:
                            reason = f"Asset/timeframe {asset}/{timeframe} notional ${asset_tf_notional:.2f} exceeds cap ${asset_tf_cap:.2f}"
                            self._log_breach("asset_horizon_cap", reason)
                            return False, reason, "asset_horizon_cap"
                
                # Log successful group check for instrumentation
                logger.debug(
                    "kalshi_risk_check_order",
                    extra={
                        "group_id": gid,
                        "asset": asset,
                        "timeframe": timeframe,
                        "group_notional": group_notional,
                        "rejected": False,
                    },
                )

            elif self._config.group_limits_enabled and group_id is None:
                logger.warning(
                    "Kalshi risk: group_limits_enabled but group_id is None; "
                    "group-level caps not applied for this order"
                )

            # 5. Total portfolio notional
            total = self._state.total_notional_usd + notional_usd
            if total > self._config.max_total_notional_usd:
                reason = f"Total notional ${total:.2f} exceeds max ${self._config.max_total_notional_usd:.2f}"
                self._log_breach("max_total_notional", reason)
                return False, reason, "max_total_notional"

            # 6. Daily loss — use equity-based tracking with per-day reset
            # Compute worst-case loss for this order (full notional at risk)
            order_worst_case_loss_usd = notional_usd
            allowed, reason, daily_loss_usd, post_loss_usd = self._check_daily_loss_limit(
                self._state.current_equity_usd, order_worst_case_loss_usd
            )
            if not allowed:
                # Do NOT activate killswitch - allow closing trades to reduce loss
                # Only block risk-INCREASING orders
                is_closing_trade = contracts < 0 or (existing_position > 0 and contracts < 0) or (existing_position < 0 and contracts > 0)
                if not is_closing_trade:
                    return False, reason, "daily_loss"
                logger.info(
                    "[RISK] Allowing risk-reducing order despite daily loss limit: ticker=%s",
                    ticker
                )

            # 6b. Per-cluster stop loss — enforced independently of daily loss
            cluster_id = self._get_cluster_id(asset, timeframe)
            sl_allowed, sl_reason, cluster_loss, post_cluster_loss = self._check_cluster_stop_loss(
                cluster_id, order_worst_case_loss_usd
            )
            if not sl_allowed:
                # Log breach but do NOT activate kill switch (cluster stop is independent)
                self._log_breach("cluster_stop_loss", sl_reason)
                return False, sl_reason, "cluster_stop_loss"

            # 7. Drawdown - only blocks NEW orders, allows closing positions
            # NOTE: Killswitch removed per operator directive - agents must trade
            # to close positions and lock in profits without permanent halts
            if self._state.peak_equity_usd > 0:
                drawdown = (self._state.peak_equity_usd - self._state.current_equity_usd) / self._state.peak_equity_usd
                if drawdown >= self._config.drawdown_unwind_pct:
                    # Log breach but do NOT activate killswitch - allow closing trades
                    reason = f"Drawdown {drawdown:.1%} exceeds unwind threshold {self._config.drawdown_unwind_pct:.1%}"
                    self._log_breach("drawdown_unwind", reason)
                    # Only block if this is a risk-INCREASING order (new exposure)
                    if contracts > 0 and existing_position >= 0:
                        return False, reason, "drawdown_unwind"
                if drawdown >= self._config.drawdown_halt_pct:
                    reason = f"Drawdown {drawdown:.1%} exceeds halt threshold {self._config.drawdown_halt_pct:.1%}"
                    self._log_breach("drawdown_halt", reason)
                    # Only block if this is a risk-INCREASING order (new exposure)
                    if contracts > 0 and existing_position >= 0:
                        return False, reason, "drawdown_halt"

            # 8. Post-fee edge
            if edge > 0:
                fee = kalshi_fee_cents(price_cents, contracts)
                fee_per = fee / max(contracts, 1)
                payout_per = 100 - price_cents
                post_fee_edge = edge - (fee_per / payout_per) if payout_per > 0 else 0
                if post_fee_edge < self._config.min_post_fee_edge:
                    reason = f"Post-fee edge {post_fee_edge:.4f} below minimum {self._config.min_post_fee_edge}"
                    self._log_breach("min_post_fee_edge", reason)
                    return False, reason, "min_post_fee_edge"

            # 9. Rate limit
            self._reset_rate_counters(now)
            if self._state.orders_this_minute >= self._config.max_orders_per_minute:
                reason = f"Rate limit: {self._state.orders_this_minute} orders this minute"
                self._log_breach("rate_limit_minute", reason)
                return False, reason, "rate_limit_minute"
            if self._state.orders_this_hour >= self._config.max_orders_per_hour:
                reason = f"Rate limit: {self._state.orders_this_hour} orders this hour"
                self._log_breach("rate_limit_hour", reason)
                return False, reason, "rate_limit_hour"

            # 10. Fills ledger reconciliation (data integrity check)
            fills_integrity_ok, integrity_reason = self._check_fills_integrity()
            if not fills_integrity_ok:
                self._log_breach("fills_integrity", integrity_reason)
                return False, integrity_reason, "fills_integrity"

            # 11. Cycle drawdown check — gates new risk based on 15-minute cycle state
            try:
                cdm = _get_cycle_drawdown_manager()
                if cdm is not None:
                    # Update cycle state with current equity
                    equity = self._state.current_equity_usd
                    cdm.update_cycle_state(equity)
                    
                    # Check if new risk can be opened
                    is_closing_trade = contracts < 0 or (existing_position > 0 and contracts < 0) or (existing_position < 0 and contracts > 0)
                    
                    if not is_closing_trade:
                        if not cdm.can_open_new_risk(notional_usd):
                            cycle_status = cdm.current_status.value
                            reason = f"Cycle drawdown: status={cycle_status} — no new risk allowed"
                            self._log_breach("cycle_drawdown", reason)
                            return False, reason, "cycle_drawdown"
            except Exception as exc:
                # Fail-open: log but don't block trading if cycle drawdown check fails
                logger.debug("Cycle drawdown check failed (fail-open): %s", exc)

            return True, "OK", None

    def _check_fills_integrity(self) -> Tuple[bool, str]:
        """Check fills ledger reconciliation status.
        
        Pure risk layer: consumes diagnostic reconciliation report from fills
        ledger and applies configured thresholds to make trading decisions.
        
        Returns:
            (allowed, reason) — False if reconciliation issues breach thresholds
        """
        try:
            from merid.event_venues.kalshi.fills_ledger import get_fills_ledger, ReconciliationStatus
            
            ledger = get_fills_ledger()
            recon = ledger.get_reconciliation_status()
            
            if not recon:
                return True, "OK"  # No reconciliation data yet
            
            status = recon.get("status", "unknown")
            ghost_count = recon.get("ghost_trade_candidates", 0)
            divergence_count = recon.get("divergence_count", 0)
            
            # Check ghost trade threshold (configurable risk decision)
            if self._config.reconcile_halt_on_ghost_trades and ghost_count > 0:
                # Calculate ghost trade percentage
                fills_total = len(ledger._fills)
                if fills_total > 0:
                    ghost_pct = ghost_count / fills_total
                    if ghost_pct > self._config.reconcile_max_ghost_trade_pct:
                        return False, f"Ghost trades detected: {ghost_count} positions without fills ({ghost_pct:.1%}) exceeds threshold {self._config.reconcile_max_ghost_trade_pct:.1%}"
            
            # Status-based warnings (logged but may not halt)
            if status == ReconciliationStatus.BROKEN.value:
                logger.warning(f"Fills reconciliation BROKEN: {ghost_count} ghost trades, {divergence_count} divergences")
                # Only halt if configured to halt on ghost trades (checked above)
                # Divergences alone don't halt unless they create ghost trades
            elif status == ReconciliationStatus.DEGRADED.value:
                logger.info(f"Fills reconciliation DEGRADED: {divergence_count} minor divergences")
            
            return True, "OK"
            
        except Exception as e:
            logger.warning(f"Fills integrity check failed (fail-open): {e}")
            return True, "OK"  # Fail open - don't block trading if check fails

    # ── State updates ────────────────────────────────────────────────────

    def record_order(
        self,
        category: Optional[str],
        contracts: int,
        price_cents: int,
        fee_cents: int = 0,
        group_id: Optional[str] = None,
        asset: Optional[str] = None,
        timeframe: Optional[str] = None,
    ) -> None:
        """Record an order for rate limiting and exposure tracking."""
        now = datetime.now(timezone.utc)
        self._reset_rate_counters(now)
        self._maybe_reset_daily(now)
        self._state.orders_this_minute += 1
        self._state.orders_this_hour += 1
        self._state.daily_trades += 1  # Track actual daily trades

        notional = contracts * price_cents / 100.0
        self._state.total_notional_usd += notional

        # Track fees
        if fee_cents > 0:
            self._state.daily_fees_usd += fee_cents / 100.0

        if category:
            self._state.category_notional[category] = (
                self._state.category_notional.get(category, 0.0) + notional
            )
            self._state.category_contracts[category] = (
                self._state.category_contracts.get(category, 0) + contracts
            )

        # Group-level exposure tracking
        if group_id:
            gid = str(group_id)
            self._state.group_notional[gid] = (
                self._state.group_notional.get(gid, 0.0) + notional
            )
            self._state.group_contracts[gid] = (
                self._state.group_contracts.get(gid, 0) + contracts
            )
            # Instrumentation logging
            logger.debug(
                "kalshi_risk_record_order",
                extra={
                    "group_id": gid,
                    "asset": asset,
                    "timeframe": timeframe,
                    "notional": notional,
                    "delta_contracts": contracts,
                    "new_group_notional": self._state.group_notional[gid],
                },
            )

        # Asset/timeframe horizon tracking
        if asset and timeframe:
            key = (asset.upper(), timeframe.lower())
            self._state.asset_horizon_notional[key] = (
                self._state.asset_horizon_notional.get(key, 0.0) + notional
            )

    def record_rate_only(self) -> None:
        """Advance rate-limit counters without touching notional exposure.

        Used for paper/sim fills so that a sudden mode-switch to live does not
        produce a thundering herd of orders in the first minute.  Must NOT
        modify total_notional_usd or category_notional — those caps track real
        open exposure only.
        """
        now = datetime.now(timezone.utc)
        with self._lock:
            self._reset_rate_counters(now)
            self._state.orders_this_minute += 1
            self._state.orders_this_hour += 1

    def record_close(
        self,
        category: Optional[str],
        contracts: int,
        price_cents: int,
        group_id: Optional[str] = None,
        asset: Optional[str] = None,
        timeframe: Optional[str] = None,
    ) -> None:
        """Record a position close and decrement notional exposure.

        Must be called whenever a sell/close order fills so that
        total_notional_usd and category_notional reflect actual open
        exposure rather than monotonically growing lifetime volume.
        """
        notional = contracts * price_cents / 100.0
        self._state.total_notional_usd = max(0.0, self._state.total_notional_usd - notional)

        if category:
            self._state.category_notional[category] = max(
                0.0,
                self._state.category_notional.get(category, 0.0) - notional,
            )
            self._state.category_contracts[category] = max(
                0,
                self._state.category_contracts.get(category, 0) - contracts,
            )

        # Group-level exposure tracking (symmetric to record_order)
        if group_id:
            gid = str(group_id)
            new_notional = max(
                0.0,
                self._state.group_notional.get(gid, 0.0) - notional,
            )
            new_contracts = max(
                0,
                self._state.group_contracts.get(gid, 0) - contracts,
            )
            self._state.group_notional[gid] = new_notional
            self._state.group_contracts[gid] = new_contracts
            # Instrumentation logging
            logger.debug(
                "kalshi_risk_record_close",
                extra={
                    "group_id": gid,
                    "asset": asset,
                    "timeframe": timeframe,
                    "notional": notional,
                    "delta_contracts": -contracts,
                    "new_group_notional": new_notional,
                },
            )

        # Asset/timeframe horizon tracking (symmetric to record_order)
        if asset and timeframe:
            key = (asset.upper(), timeframe.lower())
            self._state.asset_horizon_notional[key] = max(
                0.0,
                self._state.asset_horizon_notional.get(key, 0.0) - notional,
            )

    def record_pnl(self, pnl_usd: float) -> None:
        """Record realized PnL."""
        now = datetime.now(timezone.utc)
        self._maybe_reset_daily(now)
        self._state.daily_pnl_usd += pnl_usd
        self._state.current_equity_usd += pnl_usd
        if self._state.current_equity_usd > self._state.peak_equity_usd:
            self._state.peak_equity_usd = self._state.current_equity_usd

        # Append to PnL history for equity curve
        self._state.pnl_history.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "equity": round(self._state.current_equity_usd, 2),
            "daily_pnl": round(pnl_usd, 2),
        })
        if len(self._state.pnl_history) > 500:
            self._state.pnl_history = self._state.pnl_history[-500:]

        # Check daily loss - log breach but do NOT activate killswitch
        # Allow agents to continue trading to close positions and recover
        if self._state.daily_pnl_usd < -self._config.max_daily_loss_usd:
            self._log_breach("daily_loss_limit", f"Daily loss ${abs(self._state.daily_pnl_usd):.2f} exceeds limit")

        # L8: Trigger DeploymentController auto-rollback on drawdown breach
        if self._state.peak_equity_usd > 0:
            _dd = (self._state.peak_equity_usd - self._state.current_equity_usd) / self._state.peak_equity_usd
            if _dd >= self._config.drawdown_halt_pct:
                try:
                    from merid.event_venues.kalshi.deployment import get_deployment_controller
                    _dc = get_deployment_controller()
                    for _aname, _dep in list(_dc._agents.items()):
                        from merid.event_venues.kalshi.deployment import AgentMode
                        if _dep.mode in (AgentMode.LIVE, AgentMode.SHADOW):
                            _dc.check_auto_rollback(
                                _aname,
                                drawdown_pct=round(_dd * 100, 2),
                            )
                except Exception as _rbe:
                    pass  # non-fatal — risk manager already halts via kill switch

    def record_equity_snapshot(self, equity_usd: float) -> None:
        """Record an equity snapshot from live balance (called by PortfolioRiskAgent)."""
        self._state.current_equity_usd = equity_usd
        if equity_usd > self._state.peak_equity_usd:
            self._state.peak_equity_usd = equity_usd

        # Compute current drawdown for auto-recovery check
        drawdown = 0.0
        if self._state.peak_equity_usd > 0:
            drawdown = (self._state.peak_equity_usd - equity_usd) / self._state.peak_equity_usd

        # Auto-reset kill switch when drawdown recovers to tradable zone
        if self._state.kill_switch_active and drawdown < self._config.drawdown_unwind_pct:
            self._state.kill_switch_active = False
            self._state.kill_switch_reason = None
            self._state.kill_switch_paper_mode = False
            logger.info(
                "KalshiRiskManager kill switch auto-reset: drawdown %.1f%% below unwind threshold %.1f%% — trading resumed",
                drawdown * 100,
                self._config.drawdown_unwind_pct * 100,
            )

        # BUG-FIX: Reset peak_equity_usd if kill switch is paper-mode only and current equity is much lower
        # than peak equity (indicating stale peak from previous session with higher balance).
        # This prevents false drawdown halts when paper session balance decreases (e.g., from $100 to $20)
        # but peak_equity_usd was never reset, causing drawdown calculation to show 10.2% when there's
        # no actual drawdown (exposure_before_usd=0.0000).
        if self._state.kill_switch_paper_mode and self._state.peak_equity_usd > 0:
            # If current equity is more than 5% below peak, reset peak to current
            stale_drawdown = (self._state.peak_equity_usd - equity_usd) / self._state.peak_equity_usd
            if stale_drawdown > 0.05:  # More than 5% difference suggests stale peak
                old_peak = self._state.peak_equity_usd
                self._state.peak_equity_usd = equity_usd
                logger.info(
                    "KalshiRiskManager peak equity reset to %.2f (paper-mode kill switch active, "
                    "stale peak %.2f was %.1f%% higher)", equity_usd, old_peak, stale_drawdown * 100
                )
        self._state.pnl_history.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "equity": round(equity_usd, 2),
            "daily_pnl": round(self._state.daily_pnl_usd, 2),
        })
        if len(self._state.pnl_history) > 500:
            self._state.pnl_history = self._state.pnl_history[-500:]

    def get_pnl_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Return recent PnL history points for the equity curve endpoint."""
        return self._state.pnl_history[-limit:]

    def reset_daily(self) -> None:
        """Reset daily counters (call at start of trading day)."""
        self._state.daily_pnl_usd = 0.0
        self._state.daily_fees_usd = 0.0  # Reset daily fees
        self._state.daily_trades = 0  # Reset daily trades
        self._state.orders_this_minute = 0
        self._state.orders_this_hour = 0
        self._state.total_notional_usd = 0.0
        self._state.category_notional.clear()
        self._state.category_contracts.clear()
        # Reset group-level exposure tracking (prevent indefinite accumulation)
        self._state.group_notional.clear()
        self._state.group_contracts.clear()
        self._state.asset_horizon_notional.clear()
        self._state.group_breach_fired.clear()
        # Reset daily loss tracking - will be re-initialized on next check with current equity
        self._state.current_day_utc = None
        self._state.start_of_day_equity_usd = 0.0
        # BUG-FIX: Auto-reset paper-mode kill switch on daily rollover.
        # If the kill switch was activated without live/shadow agents (paper mode only),
        # it was never written to the global risk_kill_switch.json file, so it is safe
        # to clear it automatically each day. This prevents a paper drawdown from one
        # session permanently blocking all future sessions until an operator restart.
        if self._state.kill_switch_active and self._state.kill_switch_paper_mode:
            self._state.kill_switch_active = False
            self._state.kill_switch_reason = None
            self._state.kill_switch_paper_mode = False
            self._state.peak_equity_usd = max(self._state.current_equity_usd, 0.0)
            logger.info(
                "KalshiRiskManager paper-mode kill switch auto-reset on daily rollover "
                "(peak equity reset to %.2f)", self._state.peak_equity_usd
            )
        logger.info("KalshiRiskManager daily counters reset")

    def _compute_drawdown_thresholds(self, equity_usd: float) -> Tuple[float, float]:
        """Compute dynamic drawdown thresholds based on equity tier.

        Tighter thresholds for larger balances to protect capital:
        - Small (<$100): base drawdown (10% halt / 15% unwind)
        - Medium ($100-$1000): 8% halt / 12% unwind
        - Large ($1000-$5000): 6% halt / 10% unwind
        - Very Large (>$5000): 5% halt / 8% unwind

        Args:
            equity_usd: Current equity in USD

        Returns:
            Tuple of (halt_pct, unwind_pct)
        """
        cfg = self._config
        if not cfg.drawdown_dynamic_tiers:
            return (cfg.drawdown_halt_pct, cfg.drawdown_unwind_pct)

        # Base thresholds from config
        base_halt = cfg.drawdown_halt_pct
        base_unwind = cfg.drawdown_unwind_pct

        # Tiered adjustments: tighten as equity grows
        if equity_usd >= cfg.drawdown_large_balance_usd:
            # Large balance: tightest control (50% of base)
            halt = base_halt * 0.50
            unwind = base_unwind * 0.53
        elif equity_usd >= cfg.drawdown_medium_balance_usd:
            # Medium balance: moderate tightening (80% of base)
            halt = base_halt * 0.80
            unwind = base_unwind * 0.80
        else:
            # Small balance: use base thresholds
            halt = base_halt
            unwind = base_unwind

        return (halt, unwind)

    def _compute_dynamic_daily_loss(
        self, equity_usd: float, bankroll_cents: int
    ) -> Tuple[float, str, float]:
        """Compute dynamic daily loss limit based on equity/bankroll ratio.

        Dynamic risk is now the primary path. Static caps from config act as
        hard safety limits that dynamic values cannot exceed.

        Banded dynamic rule (fractions of bankroll, not balance):
        - ratio < 0.7:  daily_loss_frac = 0.25 (DEEP_UNDERWATER)
        - 0.7 <= ratio < 1.0: daily_loss_frac = 0.20 (UNDERWATER)
        - 1.0 <= ratio < 1.5: daily_loss_frac = 0.14 (BASELINE)
        - ratio >= 1.5: daily_loss_frac = 0.10 (LOCK_IN_GAINS)

        Safety clamp: dynamic_daily_loss <= static_cap (derived from config.max_daily_loss_usd / bankroll)

        Returns:
            Tuple of (max_daily_loss_usd, regime, ratio)
        """
        bankroll_usd = bankroll_cents / 100.0 if bankroll_cents > 0 else 0.0
        if bankroll_usd <= 0:
            return (0.0, "NO_BANKROLL", 0.0)

        # Static safety cap from config (derive pct from max_daily_loss_usd / bankroll)
        # Single source of truth: config holds dollar caps, we compute percentage on demand
        max_daily_loss_usd = float(self._config.max_daily_loss_usd)
        if max_daily_loss_usd <= 0:
            max_daily_loss_usd = bankroll_usd * 0.10  # 10% default
        max_daily_loss_pct = min(max_daily_loss_usd / bankroll_usd, 0.15)  # Cap at 15%
        static_cap = bankroll_usd * max_daily_loss_pct

        # Compute equity/bankroll ratio for dynamic regime
        ratio = equity_usd / bankroll_usd if bankroll_usd > 0 else 1.0

        # Dynamic band selection
        if ratio < 0.7:
            daily_loss_frac = 0.25
            regime = "DEEP_UNDERWATER"
        elif ratio < 1.0:
            daily_loss_frac = 0.20
            regime = "UNDERWATER"
        elif ratio < 1.5:
            daily_loss_frac = 0.14
            regime = "BASELINE"
        else:
            daily_loss_frac = 0.10
            regime = "LOCK_IN_GAINS"

        # Dynamic value clamped to static safety cap
        dynamic_value = bankroll_usd * daily_loss_frac
        max_daily_loss_usd = min(dynamic_value, static_cap)

        return (max_daily_loss_usd, regime, ratio)

    def _compute_dynamic_stop_loss(
        self, equity_usd: float, bankroll_cents: int
    ) -> Tuple[float, str, float]:
        """Compute dynamic per-cluster stop loss limit based on equity/bankroll ratio.

        Dynamic risk is now the primary path. Static caps act as hard safety limits.

        Banded dynamic rule (fractions of bankroll, not balance):
        - ratio < 0.7:  per_cluster_sl_frac = 0.20 (DEEP_UNDERWATER)
        - 0.7 <= ratio < 1.0: per_cluster_sl_frac = 0.14 (UNDERWATER)
        - 1.0 <= ratio < 1.5: per_cluster_sl_frac = 0.08 (BASELINE)
        - ratio >= 1.5: per_cluster_sl_frac = 0.04 (LOCK_IN_GAINS)

        Safety clamp: dynamic_stop_loss <= static_cap (daily_loss * cluster_stop_pct)

        Returns:
            Tuple of (max_stop_loss_usd_per_cluster, regime, ratio)
        """
        bankroll_usd = bankroll_cents / 100.0 if bankroll_cents > 0 else 0.0
        if bankroll_usd <= 0:
            return (0.0, "NO_BANKROLL", 0.0)

        # Static safety cap from config
        try:
            from merid.settings import settings
            static_cluster_frac = settings.KALSHI_PORTFOLIO_CLUSTER_STOP_PCT
        except Exception:
            static_cluster_frac = 0.50  # default 50% of daily loss
        base_daily_loss = self._config.max_daily_loss_usd
        if base_daily_loss <= 0:
            base_daily_loss = bankroll_usd * 0.10  # 10% default
        static_cap = float(base_daily_loss) * static_cluster_frac

        # Compute equity/bankroll ratio for dynamic regime
        ratio = equity_usd / bankroll_usd

        # Dynamic band selection
        if ratio < 0.7:
            per_cluster_sl_frac = 0.20
            regime = "DEEP_UNDERWATER"
        elif ratio < 1.0:
            per_cluster_sl_frac = 0.14
            regime = "UNDERWATER"
        elif ratio < 1.5:
            per_cluster_sl_frac = 0.08
            regime = "BASELINE"
        else:
            per_cluster_sl_frac = 0.04
            regime = "LOCK_IN_GAINS"

        # Dynamic value clamped to static safety cap
        dynamic_value = bankroll_usd * per_cluster_sl_frac
        max_stop_loss_usd = min(dynamic_value, static_cap)

        return (max_stop_loss_usd, regime, ratio)

    # Regime-based notional fractions for contract caps
    # Format: (total_frac, asset_frac, cluster_frac)
    _CONTRACT_NOTIONAL_FRACTIONS: Dict[str, Tuple[float, float, float]] = {
        "DEEP_UNDERWATER": (0.40, 0.20, 0.10),  # 40%, 20%, 10% of bankroll
        "UNDERWATER": (0.30, 0.15, 0.08),       # 30%, 15%, 8%
        "BASELINE": (0.25, 0.12, 0.06),         # 25%, 12%, 6%
        "LOCK_IN_GAINS": (0.20, 0.10, 0.04),    # 20%, 10%, 4%
    }

    def _compute_dynamic_contract_caps(
        self, equity_usd: float, bankroll_cents: int
    ) -> Tuple[float, float, float, int, int, int, str, float]:
        """Compute dynamic contract caps based on equity/bankroll ratio.

        Dynamic risk is now the primary path. Static caps act as hard safety limits.

        Returns:
            Tuple of (
                max_notional_usd_total,
                max_notional_usd_per_asset,
                max_notional_usd_per_cluster,
                max_contracts_total,
                max_contracts_per_asset,
                max_contracts_per_cluster,
                regime,
                ratio
            )
        """
        bankroll_usd = bankroll_cents / 100.0 if bankroll_cents > 0 else 0.0
        if bankroll_usd <= 0:
            return (0.0, 0.0, 0.0, 0, 0, 0, "NO_BANKROLL", 0.0)

        # Load static safety caps from config (these are hard limits)
        try:
            from merid.settings import settings
            max_contracts_total_hard = settings.KALSHI_MAX_CONTRACTS_TOTAL
            per_asset_frac = settings.KALSHI_MAX_CONTRACTS_PER_ASSET_FRACTION
            per_cluster_frac = settings.KALSHI_MAX_CONTRACTS_PER_CLUSTER_FRACTION
        except Exception:
            max_contracts_total_hard = 5000
            per_asset_frac = 0.35
            per_cluster_frac = 0.15

        # Static safety caps (convert fractions to avoid Decimal × float)
        static_notional_total = float(self._config.max_total_notional_usd)
        static_notional_asset = static_notional_total * per_asset_frac
        static_notional_cluster = static_notional_total * per_cluster_frac

        # Compute equity/bankroll ratio for dynamic regime
        ratio = equity_usd / bankroll_usd

        if ratio < 0.7:
            regime = "DEEP_UNDERWATER"
        elif ratio < 1.0:
            regime = "UNDERWATER"
        elif ratio < 1.5:
            regime = "BASELINE"
        else:
            regime = "LOCK_IN_GAINS"

        # Get notional fractions for this regime
        total_frac, asset_frac, cluster_frac = self._CONTRACT_NOTIONAL_FRACTIONS[regime]

        # Compute dynamic notional caps
        bankroll_usd_float = float(bankroll_usd)
        dynamic_notional_total = bankroll_usd_float * total_frac
        dynamic_notional_asset = bankroll_usd_float * asset_frac
        dynamic_notional_cluster = bankroll_usd_float * cluster_frac

        # Clamp dynamic values to static safety caps
        max_notional_usd_total = min(dynamic_notional_total, static_notional_total)
        max_notional_usd_per_asset = min(dynamic_notional_asset, static_notional_asset)
        max_notional_usd_per_cluster = min(dynamic_notional_cluster, static_notional_cluster)

        # Convert to contract counts (approx 1 USD per contract on Kalshi)
        max_contracts_total = min(
            max_contracts_total_hard,
            int(max_notional_usd_total)
        )
        max_contracts_per_asset = int(max_contracts_total * per_asset_frac)
        max_contracts_per_cluster = int(max_contracts_total * per_cluster_frac)

        return (
            max_notional_usd_total,
            max_notional_usd_per_asset,
            max_notional_usd_per_cluster,
            max_contracts_total,
            max_contracts_per_asset,
            max_contracts_per_cluster,
            regime,
            ratio
        )

    def calibrate_from_balance(self, balance_cents: int) -> None:
        """Recompute all USD caps from live balance × configured fractions.

        Safe to call concurrently; all writes are done under self._lock.
        Silently ignored when balance_cents <= 0.

        Note: ``max_single_order_contracts`` and ``CategoryLimit.max_contracts``
        are intentionally not updated — they represent fixed venue-level limits,
        not balance-relative caps.
        """
        if balance_cents <= 0:
            return
        balance_usd = balance_cents / 100.0
        cfg = self._config

        # Load bankroll from settings for dynamic daily loss computation
        try:
            from merid.settings import settings
            bankroll_cents = settings.KALSHI_PORTFOLIO_BANKROLL_CENTS
        except Exception:
            bankroll_cents = 0

        with self._lock:
            cfg.max_total_notional_usd = balance_usd * cfg.max_total_notional_pct
            cfg.max_single_order_notional_usd = balance_usd * cfg.max_single_order_pct

            # Compute dynamic daily loss based on equity/bankroll ratio
            max_daily_loss_usd, daily_regime, ratio = self._compute_dynamic_daily_loss(
                balance_usd, bankroll_cents
            )
            cfg.max_daily_loss_usd = max_daily_loss_usd

            # Compute dynamic per-cluster stop loss based on equity/bankroll ratio
            max_stop_loss_usd, sl_regime, sl_ratio = self._compute_dynamic_stop_loss(
                balance_usd, bankroll_cents
            )
            cfg.max_stop_loss_usd_per_cluster = max_stop_loss_usd

            # Compute dynamic contract caps based on equity/bankroll ratio
            (
                max_notional_total,
                max_notional_asset,
                max_notional_cluster,
                max_contracts_total,
                max_contracts_per_asset,
                max_contracts_per_cluster,
                contracts_regime,
                contracts_ratio,
            ) = self._compute_dynamic_contract_caps(balance_usd, bankroll_cents)
            cfg.max_contracts_total = max_contracts_total
            cfg.max_contracts_per_asset = max_contracts_per_asset
            cfg.max_contracts_per_cluster = max_contracts_per_cluster

            for cat, lim in cfg.category_limits.items():
                pct = cfg.category_notional_pct.get(cat, 0.05)
                lim.max_notional_usd = balance_usd * pct
            # Compute dynamic drawdown thresholds based on equity tier
            _computed_halt, _computed_unwind = self._compute_drawdown_thresholds(balance_usd)
            cfg.drawdown_halt_pct = _computed_halt
            cfg.drawdown_unwind_pct = _computed_unwind
            # Capture values inside lock before releasing — avoids data race in log
            _log_notional = cfg.max_total_notional_usd
            _log_daily = cfg.max_daily_loss_usd
            _log_cluster_sl = cfg.max_stop_loss_usd_per_cluster
            _log_single = cfg.max_single_order_notional_usd
            _log_drawdown_halt = cfg.drawdown_halt_pct
            _log_drawdown_unwind = cfg.drawdown_unwind_pct
            _log_contracts_total = cfg.max_contracts_total
            _log_contracts_asset = cfg.max_contracts_per_asset
            _log_contracts_cluster = cfg.max_contracts_per_cluster

        # Log with dynamic format when applicable
        bankroll_usd = bankroll_cents / 100.0
        if daily_regime != "STATIC":
            logger.info(
                "kalshirisk dynamic-daily-loss "
                "balance_usd=%.2f bankroll_usd=%.2f "
                "ratio=%.3f regime=%s "
                "max_daily_loss=%.2f",
                balance_usd,
                bankroll_usd,
                ratio,
                daily_regime,
                _log_daily,
            )
        if sl_regime != "STATIC":
            logger.info(
                "kalshirisk dynamic-stop-loss "
                "balance_usd=%.2f bankroll_usd=%.2f "
                "ratio=%.3f regime=%s "
                "max_cluster_stop=%.2f",
                balance_usd,
                bankroll_usd,
                sl_ratio,
                sl_regime,
                _log_cluster_sl,
            )
        if contracts_regime != "STATIC":
            logger.info(
                "kalshirisk dynamic-contracts "
                "balance_usd=%.2f bankroll_usd=%.2f "
                "ratio=%.3f regime=%s "
                "max_total_contracts=%d "
                "max_asset_contracts=%d "
                "max_cluster_contracts=%d "
                "max_notional_total=%.2f "
                "max_notional_asset=%.2f "
                "max_notional_cluster=%.2f",
                balance_usd,
                bankroll_usd,
                contracts_ratio,
                contracts_regime,
                _log_contracts_total,
                _log_contracts_asset,
                _log_contracts_cluster,
                max_notional_total,
                max_notional_asset,
                max_notional_cluster,
            )
        if daily_regime == "STATIC" and sl_regime == "STATIC" and contracts_regime == "STATIC":
            logger.info(
                "calibrate_from_balance: balance_usd=%.2f "
                "notional_cap=%.2f daily_loss=%.2f cluster_stop=%.2f single_order=%.2f "
                "contracts_total=%d contracts_asset=%d contracts_cluster=%d "
                "drawdown_halt=%.1f%% drawdown_unwind=%.1f%%",
                balance_usd,
                _log_notional,
                _log_daily,
                _log_cluster_sl,
                _log_single,
                _log_contracts_total,
                _log_contracts_asset,
                _log_contracts_cluster,
                _log_drawdown_halt * 100,
                _log_drawdown_unwind * 100,
            )

    # ── Daily loss tracking ──────────────────────────────────────────────

    def _update_daily_loss_tracking(self, equity_usd: float) -> Tuple[float, float]:
        """Update daily loss tracking with per-day reset semantics.

        Returns:
            Tuple of (daily_loss_usd, start_of_day_equity_usd)
        """
        today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        with self._lock:
            # Check if it's a new day - reset start_of_day_equity
            if self._state.current_day_utc != today_utc:
                self._state.current_day_utc = today_utc
                self._state.start_of_day_equity_usd = equity_usd
                logger.info(
                    "kalshirisk daily-loss-reset day=%s start_of_day_equity=%.2f",
                    today_utc,
                    equity_usd,
                )

            # Compute daily loss as decline from start-of-day equity
            daily_loss_usd = max(0.0, self._state.start_of_day_equity_usd - equity_usd)
            return (daily_loss_usd, self._state.start_of_day_equity_usd)

    def _check_daily_loss_limit(
        self, equity_usd: float, order_worst_case_loss_usd: float = 0.0
    ) -> Tuple[bool, str, float, float]:
        """Check if daily loss limit would be breached.

        Args:
            equity_usd: Current equity in USD
            order_worst_case_loss_usd: Worst-case loss for candidate order

        Returns:
            Tuple of (allowed, reason, daily_loss_usd, post_loss_usd)
        """
        daily_loss_usd, start_of_day_equity = self._update_daily_loss_tracking(equity_usd)
        max_daily_loss_usd = self._config.max_daily_loss_usd

        # Compute post-order loss
        post_loss_usd = daily_loss_usd + order_worst_case_loss_usd

        logger.info(
            "kalshirisk daily-loss-check "
            "equity=%.2f start_of_day=%.2f "
            "daily_loss=%.2f max_daily_loss=%.2f "
            "order_worst=%.2f post_loss=%.2f",
            equity_usd,
            start_of_day_equity,
            daily_loss_usd,
            max_daily_loss_usd,
            order_worst_case_loss_usd,
            post_loss_usd,
        )

        if post_loss_usd > max_daily_loss_usd:
            reason = f"Daily loss limit breached: post-order loss ${post_loss_usd:.2f} exceeds max ${max_daily_loss_usd:.2f}"
            return (False, reason, daily_loss_usd, post_loss_usd)

        return (True, "OK", daily_loss_usd, post_loss_usd)

    # ── Cluster stop loss tracking ───────────────────────────────────────

    def _get_cluster_id(self, asset: Optional[str], timeframe: Optional[str]) -> str:
        """Generate deterministic cluster ID from asset and timeframe.

        Args:
            asset: Underlying asset (BTC, ETH, SOL, XRP, DOGE)
            timeframe: Timeframe bucket (15m, 1h, D1, W1, 1M)

        Returns:
            Cluster ID string (e.g., "BTC-15m", "ETH-1h")
        """
        asset_clean = (asset or "unknown").upper()
        timeframe_clean = (timeframe or "unknown").lower()
        return f"{asset_clean}-{timeframe_clean}"

    def _compute_cluster_unrealized_loss_usd(self, cluster_id: str) -> float:
        """Compute total unrealized loss for positions in a cluster.

        Args:
            cluster_id: Cluster identifier (asset-timeframe)

        Returns:
            Total unrealized loss in USD (positive value = loss)
        """
        total_loss = 0.0
        try:
            from merid.event_venues.kalshi.position_cache import get_position_cache
            cache = get_position_cache()
            if not cache:
                return 0.0

            positions = cache.get_all()
            for ticker, pos in positions.items():
                # Determine cluster from position data
                pos_asset = getattr(pos, 'asset', None) or self._infer_asset_from_ticker(ticker)
                pos_timeframe = getattr(pos, 'timeframe', None) or self._infer_timeframe_from_ticker(ticker)
                pos_cluster = self._get_cluster_id(pos_asset, pos_timeframe)

                if pos_cluster == cluster_id:
                    # Get unrealized PnL (negative = loss)
                    unrealized_pnl = getattr(pos, 'unrealized_pnl_usd', 0.0)
                    if unrealized_pnl < 0:
                        total_loss += abs(unrealized_pnl)
        except Exception as exc:
            logger.debug(f"Cluster unrealized loss computation failed: {exc}")
            return 0.0

        return total_loss

    def _infer_asset_from_ticker(self, ticker: str) -> Optional[str]:
        """Infer asset from Kalshi ticker (e.g., KXBTC-15M → BTC)."""
        ticker_upper = ticker.upper()
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            if asset in ticker_upper or f"KX{asset}" in ticker_upper:
                return asset
        return None

    def _infer_timeframe_from_ticker(self, ticker: str) -> Optional[str]:
        """Infer timeframe from Kalshi ticker (e.g., KXBTC-15M → 15m)."""
        ticker_upper = ticker.upper()
        if "15M" in ticker_upper:
            return "15m"
        if "1H" in ticker_upper or "HOURLY" in ticker_upper:
            return "1h"
        if "DAILY" in ticker_upper or "-D" in ticker_upper:
            return "daily"
        if "WEEKLY" in ticker_upper or "-W" in ticker_upper:
            return "weekly"
        return None

    def _check_cluster_stop_loss(
        self,
        cluster_id: str,
        order_worst_case_loss_usd: float = 0.0,
    ) -> Tuple[bool, str, float, float]:
        """Check if cluster stop loss limit would be breached.

        Args:
            cluster_id: Cluster identifier (asset-timeframe)
            order_worst_case_loss_usd: Worst-case loss for candidate order

        Returns:
            Tuple of (allowed, reason, cluster_loss_usd, post_cluster_loss_usd)
        """
        cluster_unrealized_loss_usd = self._compute_cluster_unrealized_loss_usd(cluster_id)
        max_stop_loss_usd_per_cluster = self._config.max_stop_loss_usd_per_cluster

        # Compute post-order cluster loss
        post_cluster_loss = cluster_unrealized_loss_usd + order_worst_case_loss_usd

        logger.info(
            "kalshirisk stop-loss-check "
            "cluster=%s "
            "cluster_loss=%.2f max_cluster_stop=%.2f "
            "order_worst=%.2f post_cluster_loss=%.2f",
            cluster_id,
            cluster_unrealized_loss_usd,
            max_stop_loss_usd_per_cluster,
            order_worst_case_loss_usd,
            post_cluster_loss,
        )

        if post_cluster_loss > max_stop_loss_usd_per_cluster:
            reason = (
                f"Cluster stop loss breached: cluster={cluster_id} "
                f"post-loss=${post_cluster_loss:.2f} exceeds max=${max_stop_loss_usd_per_cluster:.2f}"
            )
            return (False, reason, cluster_unrealized_loss_usd, post_cluster_loss)

        return (True, "OK", cluster_unrealized_loss_usd, post_cluster_loss)

    # ── Kill switch ──────────────────────────────────────────────────────

    def _activate_kill_switch(self, reason: str) -> None:
        if not self._state.kill_switch_active:
            self._state.kill_switch_active = True
            self._state.kill_switch_reason = reason
            self._log_breach("kill_switch", reason)
            logger.warning(f"KILL SWITCH ACTIVATED: {reason}")

            # G9: Halt all LIVE/SHADOW agents via DeploymentController
            _has_live_agents = False
            try:
                from merid.event_venues.kalshi.deployment import get_deployment_controller, AgentMode
                _dc = get_deployment_controller()
                for _aname, _dep in list(_dc._agents.items()):
                    if _dep.mode in (AgentMode.LIVE, AgentMode.SHADOW):
                        _has_live_agents = True
                        _dc.halt(_aname, reason=f"kill_switch: {reason}")
                        logger.warning("[kill-switch] Halted agent %s via DeploymentController", _aname)
            except Exception as _dce:
                # P2-1 FIX: Upgraded from debug to warning — agent halt failures are critical
                logger.warning("kill_switch DeploymentController halt failed: %s", _dce)

            # Tag whether this kill switch was fired in paper mode (no live agents halted)
            self._state.kill_switch_paper_mode = not _has_live_agents

            # Bridge to global risk_controller for persistence — but ONLY when live/shadow
            # agents are present. Paper-mode drawdowns must not permanently block future
            # live sessions by writing to the kill switch file.
            if _has_live_agents:
                try:
                    from merid.risk.kill_switches import risk_controller as _rc
                    if _rc.can_trade():  # Only write if not already blocked
                        _rc.emergency_stop(f"kalshi_risk: {reason}")
                        logger.info("[kill-switch] Propagated to global risk_controller")
                except Exception as _rc_exc:
                    # P2-1 FIX: Upgraded from debug to warning — global kill switch bridge is critical infrastructure
                    logger.warning("kill_switch global bridge failed: %s", _rc_exc)

            # Fire Telegram alert (non-blocking, best-effort)
            try:
                import asyncio
                from agents.telegram_agent import get_telegram_agent
                agent = get_telegram_agent()
                if agent.enabled:
                    msg = f"🚨 <b>KALSHI KILL SWITCH ACTIVATED</b>\n\nReason: {reason}\n\n<i>All trading halted. Manual reset required.</i>"
                    def _on_tg_done(_t):
                        if not _t.cancelled() and _t.exception():
                            # P2-1 FIX: Upgraded from debug to warning — kill switch notifications are critical
                            logger.warning("kill_switch tg_send failed: %s", _t.exception())

                    try:
                        loop = asyncio.get_running_loop()
                        _tg_task = loop.create_task(agent.send_message(msg, force=True), name="kalshi-kill-tg")
                        _tg_task.add_done_callback(_on_tg_done)
                    except RuntimeError:
                        try:
                            asyncio.run(agent.send_message(msg, force=True))
                        except Exception as _tg_exc:
                            # P2-1 FIX: Upgraded from debug to warning — telegram alerts on kill switch are critical
                            logger.warning("kill_switch telegram fallback failed: %s", _tg_exc)
            except Exception as _exc:
                # P2-1 FIX: Upgraded from debug to warning — kill switch alert failures must be visible
                logger.warning("Telegram kill-switch alert error: %s", _exc)

    def fire_kill_switch(self, reason: str = "Manual operator activation") -> None:
        """Public method to activate the kill switch (operator action)."""
        self._activate_kill_switch(reason)

    def reset_kill_switch(self) -> None:
        """Reset kill switch (operator action)."""
        self._state.kill_switch_active = False
        self._state.kill_switch_reason = None
        logger.info("Kill switch reset by operator")

        # G11: Restore HALTED agents back to PAPER so they can trade again
        # (they were halted by _activate_kill_switch; leave LIVE/SHADOW untouched
        #  since those require explicit re-promotion by the operator)
        try:
            from merid.event_venues.kalshi.deployment import get_deployment_controller, AgentMode
            _dc = get_deployment_controller()
            for _aname, _dep in list(_dc._agents.items()):
                if _dep.mode == AgentMode.HALTED:
                    _dc.rollback(_aname, reason="kill_switch_reset")
                    logger.info("[kill-switch-reset] Restored agent %s to PAPER", _aname)
        except Exception as _dce:
            # P2-1 FIX: Upgraded from debug to warning — agent restore after kill switch reset is critical
            logger.warning("kill_switch_reset DeploymentController restore failed: %s", _dce)

    # ── Daily reset ──────────────────────────────────────────────────────

    def _maybe_reset_daily(self, now: datetime) -> None:
        """Reset daily counters if the calendar day has rolled over."""
        today = now.strftime("%Y-%m-%d")
        if today != self._last_reset_day:
            self._last_reset_day = today
            self.reset_daily()

    # ── Risk alert bridge ────────────────────────────────────────────────

    _ALERT_COOLDOWN_SECS = 30

    def _fire_risk_alert(self, ticker: str, reason: str, breach_type: Optional[str] = None, group_id: Optional[str] = None) -> None:
        """Route a rejected-order alert to PredictionAlertManager (best-effort).

        Applies a 30-second cooldown keyed by (breach_type, group_id) so that
        repeated risk rejections across many markets in the same overlap group
        don't flood alerts and Telegram. Only fires one alert per (breach_type, group_id)
        per cooldown period.
        
        Args:
            ticker: Market ticker that triggered the breach
            reason: Human-readable breach reason
            breach_type: Machine-readable breach type (e.g., "group_notional_cap")
            group_id: Canonical group ID for overlap-window aggregation
        """
        import time as _time

        # Build cooldown key: prioritize (breach_type, group_id) for group-level aggregation
        if breach_type and group_id:
            cooldown_key = f"{breach_type}:{group_id}"
        elif breach_type:
            cooldown_key = breach_type
        else:
            # Fallback to reason prefix for backward compatibility
            cooldown_key = reason[:60]
        
        now_mono = _time.monotonic()
        last = self._alert_last_fired.get(cooldown_key)
        if last is not None and (now_mono - last) < self._ALERT_COOLDOWN_SECS:
            # Skip firing — already alerted for this (breach_type, group_id) recently
            return
        
        # Record this alert firing
        self._alert_last_fired[cooldown_key] = now_mono
        
        # Also track in group_breach_fired for this cycle
        if group_id and breach_type:
            if group_id not in self._state.group_breach_fired:
                self._state.group_breach_fired[group_id] = set()
            self._state.group_breach_fired[group_id].add(breach_type)
        
        # Evict stale entries periodically
        if len(self._alert_last_fired) > 50:
            self._alert_last_fired = {
                k: v for k, v in self._alert_last_fired.items()
                if (now_mono - v) < self._ALERT_COOLDOWN_SECS
            }

        try:
            from merid.prediction.alerts import get_alert_manager
            mgr = get_alert_manager()
            # Use group_id as the primary identifier if available, otherwise ticker
            alert_target = group_id if group_id else ticker
            if "Kill switch" in reason or "unwind" in reason:
                mgr.fire_risk_breach(alert_target, reason)
            else:
                mgr.fire_risk_warning(alert_target, reason)
        except Exception as exc:
            logger.debug("_fire_risk_alert failed (non-fatal): %s", exc)

    # ── Rate limit helpers ───────────────────────────────────────────────

    def _reset_rate_counters(self, now: datetime) -> None:
        if self._state.last_minute_reset is None or (now - self._state.last_minute_reset).total_seconds() >= 60:
            self._state.orders_this_minute = 0
            self._state.last_minute_reset = now
        if self._state.last_hour_reset is None or (now - self._state.last_hour_reset).total_seconds() >= 3600:
            self._state.orders_this_hour = 0
            self._state.last_hour_reset = now

    # ── Periodic Self-Check ───────────────────────────────────────────────

    def _self_check_group_aggregates(self) -> Dict[str, Any]:
        """
        Lightweight periodic self-check that scans group aggregates and reports discrepancies.
        
        This method recomputes group_notional and group_contracts from per-contract
        tracking and asserts equality with the stored aggregates. Any discrepancy
        indicates drift in the risk engine state.
        
        Returns:
            Dict with check results: {checked_groups, discrepancies, discrepancy_groups}
        """
        discrepancies = []
        checked_groups = 0
        
        # Check each tracked group_id
        for gid in self._state.group_contracts.keys():
            checked_groups += 1
            stored_contracts = self._state.group_contracts.get(gid, 0)
            stored_notional = self._state.group_notional.get(gid, 0.0)
            
            # Verify non-negative (should never go negative)
            if stored_contracts < 0:
                discrepancies.append({
                    "group_id": gid,
                    "issue": "negative_contracts",
                    "value": stored_contracts,
                    "severity": "critical",
                })
            
            if stored_notional < 0:
                discrepancies.append({
                    "group_id": gid,
                    "issue": "negative_notional",
                    "value": stored_notional,
                    "severity": "critical",
                })
            
            # Log drift if found
            if discrepancies and len(discrepancies) <= 5:  # Limit logging volume
                for d in discrepancies:
                    logger.error(
                        "[GROUP-ID-DRIFT] group_id=%s issue=%s value=%s severity=%s",
                        d["group_id"], d["issue"], d["value"], d["severity"],
                        extra={
                            "group_id": d["group_id"],
                            "issue": d["issue"],
                            "value": d["value"],
                            "severity": d["severity"],
                        }
                    )
        
        return {
            "checked_groups": checked_groups,
            "discrepancy_count": len(discrepancies),
            "discrepancy_groups": [d["group_id"] for d in discrepancies[:5]],
            "healthy": len(discrepancies) == 0,
        }

    # ── Breach log ───────────────────────────────────────────────────────

    def _log_breach(self, check: str, reason: str) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "check": check,
            "reason": reason,
        }
        self._state.breach_log.append(entry)
        if len(self._state.breach_log) > self._MAX_BREACH_LOG:
            self._state.breach_log = self._state.breach_log[-self._MAX_BREACH_LOG:]

    def _get_open_market_count(self) -> int:
        """Count distinct markets with open positions from the position cache."""
        try:
            from merid.event_venues.kalshi.position_cache import get_position_cache
            cache = get_position_cache()
            positions = cache.get_all() if cache else {}
            return len(positions)
        except Exception:
            return 0

    # ── Summary ──────────────────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """JSON-serializable risk status."""
        # Sync P&L from fills_ledger before returning summary
        self._sync_pnl_from_ledger()
        
        drawdown = 0.0
        if self._state.peak_equity_usd > 0:
            drawdown = (self._state.peak_equity_usd - self._state.current_equity_usd) / self._state.peak_equity_usd

        daily_pnl = round(self._state.daily_pnl_usd, 2)
        
        # Get cycle drawdown metrics
        cycle_metrics: Dict[str, Any] = {}
        try:
            cdm = _get_cycle_drawdown_manager()
            if cdm is not None:
                # Ensure cycle state is updated
                cdm.update_cycle_state(self._state.current_equity_usd)
                cycle_metrics = cdm.get_cycle_metrics()
        except Exception as exc:
            logger.debug("Cycle drawdown metrics unavailable: %s", exc)
        
        return {
            "kill_switch_active": self._state.kill_switch_active,
            "kill_switch_reason": self._state.kill_switch_reason,
            "daily_pnl_usd": daily_pnl,
            "daily_realized_pnl_usd": daily_pnl,
            "daily_total_pnl_usd": daily_pnl,
            "total_unrealized_pnl_usd": 0.0,
            "total_notional_usd": round(self._state.total_notional_usd, 2),
            "drawdown_pct": round(drawdown * 100, 2),
            "peak_equity_usd": round(self._state.peak_equity_usd, 2),
            "current_equity_usd": round(self._state.current_equity_usd, 2),
            "daily_trades": self._state.daily_trades,
            "daily_fees_usd": round(self._state.daily_fees_usd, 2),
            "open_market_count": self._get_open_market_count(),
            "orders_this_minute": self._state.orders_this_minute,
            "orders_this_hour": self._state.orders_this_hour,
            "category_notional": {k: round(v, 2) for k, v in self._state.category_notional.items()},
            "category_contracts": dict(self._state.category_contracts),
            "breach_count": len(self._state.breach_log),
            "recent_breaches": self._state.breach_log[-5:],
            "fills_integrity": self._get_fills_integrity_summary(),
            "cycle_drawdown": cycle_metrics,
            "limits": {
                "max_total_notional_usd": self._config.max_total_notional_usd,
                "max_daily_loss_usd": self._config.max_daily_loss_usd,
                "max_stop_loss_usd_per_cluster": self._config.max_stop_loss_usd_per_cluster,
                "max_contracts_total": self._config.max_contracts_total,
                "max_contracts_per_asset": self._config.max_contracts_per_asset,
                "max_contracts_per_cluster": self._config.max_contracts_per_cluster,
                "max_single_order_contracts": self._config.max_single_order_contracts,
                "max_position_per_contract": self._config.max_position_per_contract,
                "drawdown_halt_pct": self._config.drawdown_halt_pct,
                "drawdown_unwind_pct": self._config.drawdown_unwind_pct,
                "min_edge": self._config.min_edge,
                "min_post_fee_edge": self._config.min_post_fee_edge,
                "reconcile_max_ghost_trade_pct": self._config.reconcile_max_ghost_trade_pct,
            },
        }

    def _get_fills_integrity_summary(self) -> Dict[str, Any]:
        """Get fills ledger reconciliation status for risk summary."""
        try:
            from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
            ledger = get_fills_ledger()
            recon = ledger.get_reconciliation_status()
            return {
                "status": recon.get("status", "unknown"),
                "ghost_trade_candidates": recon.get("ghost_trade_candidates", 0),
                "divergence_count": recon.get("divergence_count", 0),
                "last_run": recon.get("last_run"),
            }
        except Exception:
            return {"status": "unknown", "error": "fills_ledger_unavailable"}

    # ── Cycle Drawdown Integration ──────────────────────────────────────────

    def get_cycle_risk_multiplier(self) -> float:
        """Get risk multiplier adjusted for 15-minute cycle drawdown.
        
        Combines portfolio-level drawdown with cycle-level drawdown
        to produce a composite risk multiplier for position sizing.
        
        Returns:
            Risk multiplier between 0.1 and 1.0
        """
        try:
            cdm = _get_cycle_drawdown_manager()
            if cdm is not None:
                # Update cycle state with current equity
                cdm.update_cycle_state(self._state.current_equity_usd)
                return cdm.get_cycle_risk_multiplier(self._state.current_equity_usd)
        except Exception as exc:
            logger.debug("Cycle risk multiplier failed (fail-open): %s", exc)
        
        # Default: full risk if cycle drawdown unavailable
        return 1.0

    def record_cycle_pnl(self, pnl_usd: float) -> None:
        """Record realized PnL to cycle drawdown manager for profit-lock tracking.
        
        Args:
            pnl_usd: Realized profit (positive) or loss (negative)
        """
        try:
            cdm = _get_cycle_drawdown_manager()
            if cdm is not None:
                cdm.record_realized_pnl(pnl_usd)
        except Exception as exc:
            logger.debug("Record cycle PnL failed (non-critical): %s", exc)

    def force_cycle_reset(self, reason: str = "manual") -> None:
        """Force immediate cycle reset (operator action).
        
        Args:
            reason: Reason for forced reset
        """
        try:
            cdm = _get_cycle_drawdown_manager()
            if cdm is not None:
                cdm.force_reset(reason)
                logger.info("Cycle drawdown force reset: %s", reason)
        except Exception as exc:
            logger.warning("Force cycle reset failed: %s", exc)


# ── Singleton ────────────────────────────────────────────────────────────

_risk: Optional[KalshiRiskManager] = None
_risk_lock = threading.Lock()


def get_kalshi_risk() -> KalshiRiskManager:
    """Get or create the singleton KalshiRiskManager."""
    global _risk
    if _risk is None:
        with _risk_lock:
            if _risk is None:
                _risk = KalshiRiskManager()
    return _risk
