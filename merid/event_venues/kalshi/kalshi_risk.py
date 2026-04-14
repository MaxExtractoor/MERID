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

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.kalshi_risk")


# ── Orderbook state classification ──────────────────────────────────────

class OrderbookState(str, Enum):
    """Orderbook data quality classification.

    Used to distinguish missing/stale data from genuine wide spreads.
    """
    MISSING = "missing"      # No bid/ask data available (both None or 0/100 defaults)
    STALE = "stale"          # Data older than threshold
    THIN = "thin"            # Book present but insufficient depth
    NORMAL = "normal"        # Healthy book with reasonable spread and depth


# ── Fee schedule ─────────────────────────────────────────────────────────

def kalshi_fee_cents(price_cents: int, contracts: int) -> int:
    """Calculate Kalshi fee in cents for a trade.

    Fee is charged on the *winning* side only, as a percentage of payout.
    Payout per contract = 100 - price_cents (for YES buyer winning).

    Tiered:
      1-99 contracts:   7% of payout, min 2¢ per contract
      100-999:          5% of payout, min 2¢
      1000+:            3% of payout, min 2¢

    Args:
        price_cents: Price paid per contract (0-99)
        contracts: Number of contracts

    Returns:
        Total fee in cents (integer, rounded up)
    """
    if contracts <= 0 or price_cents <= 0 or price_cents >= 100:
        return 0

    payout_per = 100 - price_cents  # cents won per contract if correct

    if contracts < 100:
        rate = 0.07
    elif contracts < 1000:
        rate = 0.05
    else:
        rate = 0.03

    fee_per = max(2, math.ceil(payout_per * rate))
    return fee_per * contracts


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

    # Estimate fee per contract (use 10-contract tier as default)
    payout_per = 100 - price_cents
    fee_per = max(2, math.ceil(payout_per * 0.07))

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
    max_single_order_contracts: int = 250
    max_single_order_notional_usd: float = 2500.0
    max_position_per_contract: int = 500  # Kalshi typical retail limit

    # Per-category limits
    category_limits: Dict[str, CategoryLimit] = field(default_factory=dict)

    # Drawdown — 4-zone model (green / yellow / orange / red)
    # Green  (0–10%):  full normal sizing
    # Yellow (10–15%): scale sizes by 0.5–0.75
    # Orange (15–20%): aggressively defensive, 0.25–0.33 sizing
    # Red    (>20%):   drawdown_halt_active = True; no new risk-adding orders
    drawdown_yellow_pct: float = 0.10   # Green → Yellow threshold
    drawdown_orange_pct: float = 0.15   # Yellow → Orange threshold (soft limit)
    drawdown_halt_pct: float = 0.20     # Orange → Red / halt threshold (hard limit)
    drawdown_unwind_pct: float = 0.25   # Force unwind at 25% (was 15%)

    # Minimum edge to trade
    min_edge: float = 0.02
    min_post_fee_edge: float = 0.01

    # Live orderbook checks (E1) — applied when caller supplies real params
    max_spread_cents: int = 10        # Reject if bid-ask spread exceeds this
    min_depth_contracts: int = 5      # Reject if available depth below this

    # YES price cap — no YES buy order may exceed this price
    # Default 50¢ (0.50). Set via MERID_MAX_YES_PRICE env var (dollars) or
    # override per-profile by constructing KalshiRiskConfig directly.
    max_yes_price_cents: int = 50

    # Rate limit awareness
    max_orders_per_minute: int = 30
    max_orders_per_hour: int = 300

    def __post_init__(self):
        if not self.category_limits:
            self.category_limits = {
                "crypto": CategoryLimit("crypto", max_notional_usd=5000, max_contracts=500),
                "economics": CategoryLimit("economics", max_notional_usd=3000, max_contracts=300),
                "financials": CategoryLimit("financials", max_notional_usd=3000, max_contracts=300),
                "politics": CategoryLimit("politics", max_notional_usd=2000, max_contracts=200),
                "climate": CategoryLimit("climate", max_notional_usd=1000, max_contracts=100),
                "tech": CategoryLimit("tech", max_notional_usd=2000, max_contracts=200),
                "sports": CategoryLimit("sports", max_notional_usd=2000, max_contracts=200),
                "culture": CategoryLimit("culture", max_notional_usd=1000, max_contracts=100),
                "science": CategoryLimit("science", max_notional_usd=1000, max_contracts=100),
            }


@dataclass
class RiskState:
    """Mutable runtime risk state."""
    daily_pnl_usd: float = 0.0
    total_notional_usd: float = 0.0
    peak_equity_usd: float = 0.0
    current_equity_usd: float = 0.0
    kill_switch_active: bool = False
    kill_switch_reason: Optional[str] = None
    orders_this_minute: int = 0
    orders_this_hour: int = 0
    last_minute_reset: Optional[datetime] = None
    last_hour_reset: Optional[datetime] = None
    category_notional: Dict[str, float] = field(default_factory=dict)
    category_contracts: Dict[str, int] = field(default_factory=dict)
    breach_log: List[Dict[str, Any]] = field(default_factory=list)
    pnl_history: List[Dict[str, Any]] = field(default_factory=list)


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
        self._state = RiskState()

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
        spread_cents: Optional[int] = None,
        depth_at_price: Optional[int] = None,
        outcome: str = "yes",
    ) -> Tuple[bool, str]:
        """Run all pre-trade risk checks.

        Args:
            ticker: Market ticker
            category: Market category (crypto, economics, etc.)
            contracts: Number of contracts to trade
            price_cents: Price per contract in cents
            edge: Estimated edge
            existing_position: Current position in this contract
            spread_cents: Live bid-ask spread from orderbook snapshot (optional)
            depth_at_price: Available depth at the desired price level (optional)
            outcome: "yes" or "no" — used to enforce max_yes_price_cents cap

        Returns:
            (allowed, reason) — True if order passes all checks
        """
        now = datetime.now(timezone.utc)

        # 0. Phantom kill switch (F2) — block new orders when phantom positions detected.
        # FAIL-CLOSED: any unexpected error during this check is treated as a block signal;
        # only ImportError (optional reconciliation module absent) is allowed to pass through.
        try:
            from merid.reconciliation import is_phantom_kill_switch_active
            if is_phantom_kill_switch_active():
                return False, "phantom_kill_switch:phantom positions detected — orders halted pending reconciliation"
        except ImportError:
            pass  # Reconciliation module is optional; absence is safe
        except Exception as _pks_exc:
            # Fail-closed: unknown error in kill-switch check → block the order
            logger.error(
                "phantom_kill_switch:unavailable — unexpected error, blocking order as fail-safe. "
                "ticker=%s error=%s",
                ticker, _pks_exc,
            )
            return False, "phantom_kill_switch:unavailable"

        # 0b. Bankroll zero guard (E2) — block risk-increasing orders when equity ≤ 0
        if self._state.current_equity_usd <= 0 and self._state.peak_equity_usd > 0:
            return False, f"bankroll_zero:current equity {self._state.current_equity_usd:.2f} is at or below zero"

        # 1. Kill switch
        if self._state.kill_switch_active:
            return False, f"Kill switch active: {self._state.kill_switch_reason}"

        # 1b. YES price cap — hard guard; no YES buy may exceed max_yes_price_cents
        if outcome == "yes" and price_cents > self._config.max_yes_price_cents:
            logger.warning(
                "max_yes_price_cap: ticker=%s price=%d¢ cap=%d¢ contracts=%d category=%s",
                ticker, price_cents, self._config.max_yes_price_cents, contracts, category,
            )
            return False, (
                f"max_yes_price_cap:YES price {price_cents}¢ exceeds cap "
                f"{self._config.max_yes_price_cents}¢ for {ticker}"
            )

        # 2. Single order size
        if contracts > self._config.max_single_order_contracts:
            return False, f"Order size {contracts} exceeds max {self._config.max_single_order_contracts}"

        notional_usd = contracts * price_cents / 100.0
        if notional_usd > self._config.max_single_order_notional_usd:
            return False, f"Order notional ${notional_usd:.2f} exceeds max ${self._config.max_single_order_notional_usd:.2f}"

        # 3. Per-contract position limit
        new_position = existing_position + contracts
        if new_position > self._config.max_position_per_contract:
            return False, f"Position {new_position} would exceed per-contract limit {self._config.max_position_per_contract}"

        # 4. Category exposure
        if category and category in self._config.category_limits:
            cat_limit = self._config.category_limits[category]
            if cat_limit.enabled:
                cat_notional = self._state.category_notional.get(category, 0.0) + notional_usd
                if cat_notional > cat_limit.max_notional_usd:
                    return False, f"Category '{category}' notional ${cat_notional:.2f} exceeds cap ${cat_limit.max_notional_usd:.2f}"

                cat_contracts = self._state.category_contracts.get(category, 0) + contracts
                if cat_contracts > cat_limit.max_contracts:
                    return False, f"Category '{category}' contracts {cat_contracts} exceeds cap {cat_limit.max_contracts}"

        # 5. Total portfolio notional
        total = self._state.total_notional_usd + notional_usd
        if total > self._config.max_total_notional_usd:
            return False, f"Total notional ${total:.2f} exceeds max ${self._config.max_total_notional_usd:.2f}"

        # 6. Daily loss
        if self._state.daily_pnl_usd < -self._config.max_daily_loss_usd:
            self._activate_kill_switch("Daily loss limit breached")
            return False, f"Daily loss ${abs(self._state.daily_pnl_usd):.2f} exceeds max ${self._config.max_daily_loss_usd:.2f}"

        # 7. Drawdown — 4-zone model
        # Red (>halt_pct): engage drawdown_halt_active; reject new risk-adding orders
        #                  but do NOT increment error budget (use drawdown_halt class).
        # Orange / Yellow zones apply size multipliers (enforced at sizing layer).
        if self._state.peak_equity_usd > 0:
            drawdown = (self._state.peak_equity_usd - self._state.current_equity_usd) / self._state.peak_equity_usd
            if drawdown >= self._config.drawdown_unwind_pct:
                self._activate_kill_switch(f"Drawdown {drawdown:.1%} exceeds unwind threshold")
                self._set_drawdown_halt(drawdown)
                return False, f"Drawdown {drawdown:.1%} exceeds unwind threshold {self._config.drawdown_unwind_pct:.1%}"
            if drawdown >= self._config.drawdown_halt_pct:
                self._set_drawdown_halt(drawdown)
                return False, f"Drawdown {drawdown:.1%} exceeds halt threshold {self._config.drawdown_halt_pct:.1%}"

        # 8. Post-fee edge
        if edge > 0:
            fee = kalshi_fee_cents(price_cents, contracts)
            fee_per = fee / max(contracts, 1)
            payout_per = 100 - price_cents
            post_fee_edge = edge - (fee_per / payout_per) if payout_per > 0 else 0
            if post_fee_edge < self._config.min_post_fee_edge:
                return False, f"Post-fee edge {post_fee_edge:.4f} below minimum {self._config.min_post_fee_edge}"

        # 9. Rate limit
        self._reset_rate_counters(now)
        if self._state.orders_this_minute >= self._config.max_orders_per_minute:
            return False, f"Rate limit: {self._state.orders_this_minute} orders this minute"
        if self._state.orders_this_hour >= self._config.max_orders_per_hour:
            return False, f"Rate limit: {self._state.orders_this_hour} orders this hour"

        # 10. Live orderbook checks (E1) — applied only when caller supplies real params
        # Classify orderbook state to distinguish missing data from real wide spreads
        book_state = self._classify_orderbook_state(spread_cents, depth_at_price)

        # Log orderbook classification for MM debugging
        if spread_cents is not None and spread_cents >= 50:
            logger.info(
                "[MM-SPREAD] ticker=%s spread=%d¢ depth=%s book_state=%s",
                ticker, spread_cents, depth_at_price, book_state.value
            )

        # MISSING/STALE: Skip rather than block - data issue, not market condition
        if book_state in (OrderbookState.MISSING, OrderbookState.STALE):
            # Don't enforce spread/depth checks when book is missing/stale
            # This prevents blocking MM on data issues (100¢ spread from 0/100 defaults)
            logger.debug(
                "[MM-SPREAD] Skipping orderbook checks for %s - book_state=%s",
                ticker, book_state.value
            )
        else:
            # THIN/NORMAL: Apply standard risk checks
            if spread_cents is not None and spread_cents > self._config.max_spread_cents:
                return False, (
                    f"Spread {spread_cents}¢ exceeds max {self._config.max_spread_cents}¢ "
                    f"(live orderbook check, book_state={book_state.value})"
                )
            if depth_at_price is not None and depth_at_price < self._config.min_depth_contracts:
                return False, (
                    f"Depth {depth_at_price} contracts below minimum "
                    f"{self._config.min_depth_contracts} (live orderbook check, book_state={book_state.value})"
                )

        return True, "OK"

    def _classify_orderbook_state(
        self,
        spread_cents: Optional[int],
        depth_at_price: Optional[int],
    ) -> OrderbookState:
        """Classify orderbook data quality.

        Returns:
            MISSING if no spread data or spread indicates missing book (>= 80¢)
            THIN if depth is very low (< 3 contracts)
            NORMAL otherwise

        Note: Spread >= 80¢ indicates missing orderbook data (likely 0/100 defaults)
        rather than a genuinely wide market. Real Kalshi crypto spreads rarely exceed 30¢.
        """
        # No spread data provided
        if spread_cents is None:
            return OrderbookState.NORMAL  # Assume normal if not provided

        # Spread >= 80¢ strongly suggests missing/default book data
        # Real spreads on active Kalshi crypto markets are typically 2-20¢
        if spread_cents >= 80:
            return OrderbookState.MISSING

        # Check depth if provided
        if depth_at_price is not None and depth_at_price < 3:
            return OrderbookState.THIN

        return OrderbookState.NORMAL

    # ── State updates ────────────────────────────────────────────────────

    def record_order(self, category: Optional[str], contracts: int, price_cents: int) -> None:
        """Record an order for rate limiting and exposure tracking."""
        now = datetime.now(timezone.utc)
        self._reset_rate_counters(now)
        self._state.orders_this_minute += 1
        self._state.orders_this_hour += 1

        notional = contracts * price_cents / 100.0
        self._state.total_notional_usd += notional

        if category:
            self._state.category_notional[category] = (
                self._state.category_notional.get(category, 0.0) + notional
            )
            self._state.category_contracts[category] = (
                self._state.category_contracts.get(category, 0) + contracts
            )

    def record_pnl(self, pnl_usd: float) -> None:
        """Record realized PnL."""
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

        # Check daily loss
        if self._state.daily_pnl_usd < -self._config.max_daily_loss_usd:
            self._activate_kill_switch("Daily loss limit breached")

        # L8: Trigger DeploymentController auto-rollback on drawdown breach
        if self._state.peak_equity_usd > 0:
            _dd = (self._state.peak_equity_usd - self._state.current_equity_usd) / self._state.peak_equity_usd
            if _dd >= self._config.drawdown_halt_pct:
                self._set_drawdown_halt(_dd)
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

        # Feed realized P&L into the profit-lock engine so Phase-3 protection
        # can track session high-water marks and enforce the give-back limit.
        # Fail-open: if the module is unavailable, sizing proceeds at full size.
        try:
            from merid.risk.profit_lock import get_profit_lock_engine
            get_profit_lock_engine().record_pnl(pnl_usd)
        except Exception:
            pass

        # Auto-clear drawdown kill switch when equity fully recovers
        self._maybe_auto_reset_drawdown_kill_switch()

    def record_equity_snapshot(self, equity_usd: float) -> None:
        """Record an equity snapshot from live balance (called by PortfolioRiskAgent)."""
        self._state.current_equity_usd = equity_usd
        if equity_usd > self._state.peak_equity_usd:
            self._state.peak_equity_usd = equity_usd
        self._state.pnl_history.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "equity": round(equity_usd, 2),
            "daily_pnl": round(self._state.daily_pnl_usd, 2),
        })
        if len(self._state.pnl_history) > 500:
            self._state.pnl_history = self._state.pnl_history[-500:]

        # Auto-clear drawdown kill switch when equity fully recovers
        self._maybe_auto_reset_drawdown_kill_switch()

    def get_pnl_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Return recent PnL history points for the equity curve endpoint."""
        return self._state.pnl_history[-limit:]

    def reset_daily(self) -> None:
        """Reset daily counters (call at start of trading day)."""
        self._state.daily_pnl_usd = 0.0
        self._state.orders_this_minute = 0
        self._state.orders_this_hour = 0
        self._state.category_notional.clear()
        self._state.category_contracts.clear()
        logger.info("KalshiRiskManager daily counters reset")

    # ── Kill switch ──────────────────────────────────────────────────────

    def _set_drawdown_halt(self, drawdown: float) -> None:
        """Engage the dedicated drawdown-halt flag on the global RiskController.

        This is a *policy* gate that is completely separate from the error
        budget.  Calling this never increments the error counter.
        """
        try:
            from merid.risk.kill_switches import risk_controller as _rc
            _rc.set_drawdown_halt(
                True,
                reason=(
                    f"Portfolio drawdown {drawdown:.1%} >= halt threshold "
                    f"{self._config.drawdown_halt_pct:.1%}"
                ),
            )
        except Exception:
            pass  # non-fatal; worst case agents still get the venue-level rejection

    def _maybe_auto_reset_drawdown_kill_switch(self) -> None:
        """Auto-reset kill switch and drawdown_halt flag when drawdown recovers.

        This is the symmetric "clear" path to ``_activate_kill_switch``.
        It runs on every equity update and resets the kill switch when:

          1. kill switch is currently active, AND
          2. the kill switch was triggered by a drawdown event (not daily loss
             or a manual/emergency stop), AND
          3. current drawdown has recovered below the halt threshold.

        Venue status transitions: HALTED → OK (logged at INFO level).
        Daily-loss kills and manual emergency stops are intentionally excluded;
        those require an explicit operator reset.
        """
        if not self._state.kill_switch_active:
            # Even if the venue kill switch is not active we may still need to
            # clear the drawdown_halt flag on recovery.
            pass  # fall through to the drawdown_halt clear logic below

        if self._state.peak_equity_usd <= 0:
            return

        current_dd = (
            (self._state.peak_equity_usd - self._state.current_equity_usd)
            / self._state.peak_equity_usd
        )

        # Clear the global drawdown_halt_active flag when drawdown recovers
        if current_dd < self._config.drawdown_halt_pct:
            try:
                from merid.risk.kill_switches import risk_controller as _rc
                if _rc.is_drawdown_halted():
                    _rc.set_drawdown_halt(False)
            except Exception:
                pass

        if not self._state.kill_switch_active:
            return
        if self._state.kill_switch_reason is None:
            return
        if "drawdown" not in self._state.kill_switch_reason.lower():
            return

        if current_dd < self._config.drawdown_halt_pct:
            logger.info(
                "Drawdown recovered (%.1f%% < halt=%.1f%%) — venue status: ok — auto-resetting kill switch",
                current_dd * 100,
                self._config.drawdown_halt_pct * 100,
            )
            self.reset_kill_switch()

    def _activate_kill_switch(self, reason: str) -> None:
        if not self._state.kill_switch_active:
            self._state.kill_switch_active = True
            self._state.kill_switch_reason = reason
            self._log_breach("kill_switch", reason)
            logger.warning(f"KILL SWITCH ACTIVATED: {reason}")

            # G9: Halt all LIVE/SHADOW agents via DeploymentController
            try:
                from merid.event_venues.kalshi.deployment import get_deployment_controller, AgentMode
                _dc = get_deployment_controller()
                for _aname, _dep in list(_dc._agents.items()):
                    if _dep.mode in (AgentMode.LIVE, AgentMode.SHADOW):
                        _dc.halt(_aname, reason=f"kill_switch: {reason}")
                        logger.warning("[kill-switch] Halted agent %s via DeploymentController", _aname)
            except Exception as _dce:
                logger.debug("kill_switch DeploymentController halt skipped: %s", _dce)

            # Fire Telegram alert (non-blocking, best-effort)
            try:
                import asyncio
                from agents.telegram_agent import get_telegram_agent
                agent = get_telegram_agent()
                if agent.enabled:
                    msg = f"🚨 <b>KALSHI KILL SWITCH ACTIVATED</b>\n\nReason: {reason}\n\n<i>All trading halted. Manual reset required.</i>"
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(agent.send_message(msg, force=True))
                    except RuntimeError:
                        try:
                            asyncio.run(agent.send_message(msg, force=True))
                        except Exception as _tg_exc:
                            logger.debug("kill_switch telegram fallback failed: %s", _tg_exc)
            except Exception as _exc:
                logger.debug(f"Telegram kill-switch alert error (ignored): {_exc}")

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
            logger.debug("kill_switch_reset DeploymentController restore skipped: %s", _dce)

    # ── Rate limit helpers ───────────────────────────────────────────────

    def _reset_rate_counters(self, now: datetime) -> None:
        if self._state.last_minute_reset is None or (now - self._state.last_minute_reset).total_seconds() >= 60:
            self._state.orders_this_minute = 0
            self._state.last_minute_reset = now
        if self._state.last_hour_reset is None or (now - self._state.last_hour_reset).total_seconds() >= 3600:
            self._state.orders_this_hour = 0
            self._state.last_hour_reset = now

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

    # ── Summary ──────────────────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """JSON-serializable risk status."""
        drawdown = 0.0
        if self._state.peak_equity_usd > 0:
            drawdown = (self._state.peak_equity_usd - self._state.current_equity_usd) / self._state.peak_equity_usd

        daily_pnl = round(self._state.daily_pnl_usd, 2)
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
            "daily_trades": self._state.orders_this_hour,
            "daily_fees_usd": 0.0,
            "open_market_count": 0,
            "orders_this_minute": self._state.orders_this_minute,
            "orders_this_hour": self._state.orders_this_hour,
            "category_notional": {k: round(v, 2) for k, v in self._state.category_notional.items()},
            "category_contracts": dict(self._state.category_contracts),
            "breach_count": len(self._state.breach_log),
            "recent_breaches": self._state.breach_log[-5:],
            "limits": {
                "max_total_notional_usd": self._config.max_total_notional_usd,
                "max_daily_loss_usd": self._config.max_daily_loss_usd,
                "max_single_order_contracts": self._config.max_single_order_contracts,
                "max_position_per_contract": self._config.max_position_per_contract,
                "drawdown_halt_pct": self._config.drawdown_halt_pct,
                "drawdown_unwind_pct": self._config.drawdown_unwind_pct,
                "min_edge": self._config.min_edge,
                "min_post_fee_edge": self._config.min_post_fee_edge,
            },
        }


# ── Singleton ────────────────────────────────────────────────────────────

_risk: Optional[KalshiRiskManager] = None


def get_kalshi_risk() -> KalshiRiskManager:
    """Get or create the singleton KalshiRiskManager."""
    global _risk
    if _risk is None:
        _risk = KalshiRiskManager()
    return _risk
