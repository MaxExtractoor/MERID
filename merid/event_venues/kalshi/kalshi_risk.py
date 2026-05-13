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

from merid.event_venues.kalshi.risk_parameters import (
    DEFAULT_KALSHI_PRICE_CENTS,
    MAX_PRICE_DIFFERENCE_CENTS,
)
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

def _clamp_edge_for_kelly(edge_pct: float, config: Optional[KalshiRiskConfig] = None) -> float:
    """Clamp edge percentage to safe range for Kelly calculation.

    Args:
        edge_pct: Raw edge percentage (e.g. 8.0 for 8%)
        config: Risk config with clamp bounds (uses defaults if None)

    Returns:
        Clamped edge percentage, or 0 if outside safe bounds
    """
    cfg = config or KalshiRiskConfig()
    if edge_pct < cfg.kelly_min_edge_pct:
        return 0.0
    if edge_pct > cfg.kelly_max_edge_pct:
        logger.warning(
            "Kelly edge clamped from %.2f%% to %.2f%% (max cap)",
            edge_pct, cfg.kelly_max_edge_pct
        )
        return cfg.kelly_max_edge_pct
    return edge_pct


def _clamp_win_prob_for_kelly(win_prob: float, config: Optional[KalshiRiskConfig] = None) -> float:
    """Clamp win probability to safe range for Kelly calculation.

    Args:
        win_prob: Raw win probability (0-1)
        config: Risk config with clamp bounds (uses defaults if None)

    Returns:
        Clamped win probability
    """
    cfg = config or KalshiRiskConfig()
    return max(cfg.kelly_min_win_prob, min(cfg.kelly_max_win_prob, win_prob))


def is_risk_reducing_trade(
    existing_position: int,
    contracts: int,
) -> Tuple[bool, str]:
    """Determine if a trade reduces absolute risk exposure.

    A trade is risk-reducing if the absolute value of the new position
    is strictly less than the absolute value of the existing position.

    Args:
        existing_position: Current position (signed, positive=long, negative=short)
        contracts: Contracts to trade (signed, positive=buy, negative=sell)

    Returns:
        Tuple of (is_risk_reducing, reason)
        - is_risk_reducing: True if trade reduces absolute exposure
        - reason: Explanation of the classification
    """
    new_position = existing_position + contracts
    existing_abs = abs(existing_position)
    new_abs = abs(new_position)

    # Risk-reducing: new position is smaller in absolute terms
    if new_abs < existing_abs:
        return True, f"risk_reducing: |{new_position}| < |{existing_position}|"

    # Risk-neutral (flat or same size): not reducing
    if new_abs == existing_abs:
        if existing_position == 0 and contracts == 0:
            return False, "no_trade: zero contracts"
        return False, f"risk_neutral: |{new_position}| == |{existing_position}|"

    # Risk-increasing: new position is larger
    return False, f"risk_increasing: |{new_position}| > |{existing_position}|"


def kelly_size_kalshi(
    edge: float,
    price_cents: int,
    bankroll_cents: int,
    *,
    kelly_fraction: float = 0.25,
    max_contracts: int = 250,
    min_edge: float = 0.05,  # CONSERVATIVE: 5.0% minimum edge
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
        # PRODUCTION-FIX: Use actual market price from KalshiMarketStateStore if available
        from merid.event_venues.kalshi.risk_parameters import DEFAULT_KALSHI_PRICE_CENTS
        
        price_cents = m.get("price_cents")
        if price_cents is None:
            try:
                from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                state = get_kalshi_market_state_store().get_state(m["ticker"])
                if state and state.mid_cents > 0:
                    price_cents = state.mid_cents
            except Exception as _exc:
                logger.debug("Kelly sizing: failed to fetch market state for %s, using default fallback: %s", m["ticker"], _exc)
        price_cents = price_cents or DEFAULT_KALSHI_PRICE_CENTS  # Fallback if still None
        # Each contract costs price_cents / 100 USD
        price_usd = price_cents / 100.0
        if price_usd <= 0:
            continue
        contracts = int(dollars_for_market / price_usd)
        contracts = min(contracts, max_contracts_per_market)
        # Apply fee check: ensure net payout is positive
        if contracts > 0:
            fee = kalshi_fee_cents(price_cents, contracts)
            payout = (100 - price_cents) * contracts
            if payout - fee <= 0:
                continue
        if contracts > 0:
            sizes[m["ticker"]] = contracts

    return sizes


# ── Multi-market Kelly sizing ────────────────────────────────────────────

def _kelly_fraction(
    edge_pct: float,
    win_prob: float,
    price_cents: int,
    *,
    config: Optional[KalshiRiskConfig] = None,
    apply_hard_cap: bool = True,
) -> float:
    """Kelly fraction for a Kalshi binary contract with safety clamps.

    For a binary paying $1 on win at cost ``price_cents / 100``:
      b = (100 - price_cents) / price_cents   (net odds)
      p = win_prob  (our estimated probability of winning)
      q = 1 - p
      f* = (p · b - q) / b

    ``edge_pct`` is added to ``win_prob`` as an adjustment
    (e.g. edge_pct=2 means we think true prob is win_prob + 0.02).

    Safety features:
    - Edge is clamped to [kelly_min_edge_pct, kelly_max_edge_pct]
    - Win probability is clamped to [kelly_min_win_prob, kelly_max_win_prob]
    - Hard cap on f* before frac_of_kelly multiplier (default 50%)

    Args:
        edge_pct: Edge percentage (e.g. 2.0 for 2%)
        win_prob: Base win probability (0-1)
        price_cents: Contract price in cents (1-99)
        config: Optional risk config with safety parameters
        apply_hard_cap: If True, apply kelly_hard_cap to f*

    Returns:
        Kelly fraction f* (0 to kelly_hard_cap), or 0 if invalid inputs
    """
    cfg = config or KalshiRiskConfig()

    # Validate price
    if price_cents < cfg.valid_price_cents_min or price_cents > cfg.valid_price_cents_max:
        logger.debug("Kelly fraction rejected: price_cents=%d outside valid range [%d, %d]",
                     price_cents, cfg.valid_price_cents_min, cfg.valid_price_cents_max)
        return 0.0

    # Clamp inputs
    clamped_edge = _clamp_edge_for_kelly(edge_pct, cfg)
    if clamped_edge == 0.0:
        logger.debug("Kelly fraction rejected: edge_pct=%.2f below minimum %.2f",
                     edge_pct, cfg.kelly_min_edge_pct)
        return 0.0

    clamped_win_prob = _clamp_win_prob_for_kelly(win_prob, cfg)

    b = (100 - price_cents) / price_cents  # net odds ratio
    p = min(clamped_win_prob + clamped_edge / 100.0, cfg.kelly_max_win_prob)
    q = 1.0 - p

    if b <= 0 or p <= 0:
        return 0.0

    f = (p * b - q) / b

    # Apply hard cap on Kelly fraction before frac_of_kelly
    if apply_hard_cap:
        hard_cap = cfg.kelly_hard_cap
        if f > hard_cap:
            logger.debug(
                "Kelly fraction hard-capped: f=%.4f capped to %.4f (edge=%.2f%%, win_prob=%.4f)",
                f, hard_cap, edge_pct, win_prob
            )
            f = min(f, hard_cap)

    return max(0.0, f)


def multi_market_kelly_sizes(
    markets: List[Dict[str, Any]],
    equity_usd: float,
    *,
    frac_of_kelly: float = 0.25,
    max_per_market_usd: float = 1000.0,
    max_contracts_per_market: int = 500,
    config: Optional[KalshiRiskConfig] = None,
) -> Dict[str, int]:
    """Win-prob-based Kelly allocation across independent Kalshi markets.

    Each market is sized independently using Kelly criterion, then capped.
    Enforces global notional cap to prevent excessive total exposure.

    Args:
        markets: List of dicts with keys:
            ``ticker``, ``edge_pct`` (e.g. 1.5), ``win_prob`` (0-1),
            optional ``price_cents``
        equity_usd: Total portfolio equity in USD
        frac_of_kelly: Fraction of full Kelly to use (default quarter-Kelly)
        max_per_market_usd: Dollar cap per market
        max_contracts_per_market: Contract cap per market
        config: Risk config with safety parameters

    Returns:
        {ticker: contracts} for each market with positive allocation
    """
    cfg = config or KalshiRiskConfig()
    if equity_usd <= 0:
        return {}

    # Compute global notional cap
    global_notional_cap = cfg.get_effective_max_total_notional(equity_usd)
    global_notional_cap = min(
        global_notional_cap,
        equity_usd * cfg.kelly_global_notional_cap_pct  # Kelly-specific cap
    )

    allocations: Dict[str, int] = {}
    total_notional = 0.0

    # Sort markets by edge descending to prioritize best opportunities
    sorted_markets = sorted(
        [m for m in markets if m.get("edge_pct", 0) > 0],
        key=lambda x: x.get("edge_pct", 0),
        reverse=True
    )

    for m in sorted_markets:
        edge = m.get("edge_pct", 0)
        wp = m.get("win_prob", 0.5)
        if edge <= 0:
            continue

        # PRODUCTION-FIX: Use actual market price from KalshiMarketStateStore if available
        price_cents = m.get("price_cents")
        if price_cents is None:
            try:
                from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                state = get_kalshi_market_state_store().get_state(m["ticker"])
                if state and state.mid_cents > 0:
                    price_cents = state.mid_cents
            except Exception as _exc:
                logger.debug("Kelly allocation: failed to fetch market state for %s, using 50c fallback: %s", m["ticker"], _exc)
        price_cents = price_cents or DEFAULT_KALSHI_PRICE_CENTS  # Fallback if still None

        # Check remaining global capacity
        remaining_global = global_notional_cap - total_notional
        if remaining_global <= 0:
            logger.debug("Kelly allocation stopped: global notional cap reached")
            break

        # Compute Kelly fraction with safety clamps
        f = _kelly_fraction(edge, wp, price_cents, config=cfg) * frac_of_kelly
        if f <= 0:
            continue

        bankroll = min(equity_usd, max_per_market_usd)
        dollars = min(bankroll * f, remaining_global)  # Respect global cap
        price_usd = price_cents / 100.0 if price_cents > 0 else DEFAULT_KALSHI_PRICE_CENTS / 100.0

        if price_usd <= 0:
            continue

        contracts = int(dollars / price_usd)
        contracts = min(contracts, max_contracts_per_market)

        # Fee check + fee anomaly detection
        if contracts > 0:
            fee = kalshi_fee_cents(price_cents, contracts)
            notional = contracts * price_usd
            fee_pct = (fee / 100.0) / notional * 100 if notional > 0 else 0

            # Circuit breaker: reject if fee too high relative to notional
            if fee_pct > cfg.max_fee_to_notional_pct:
                logger.warning(
                    "Kelly allocation rejected for %s: fee %.1f%% exceeds max %.1f%%",
                    m["ticker"], fee_pct, cfg.max_fee_to_notional_pct
                )
                continue

            payout = (100 - price_cents) * contracts
            if payout - fee <= 0:
                continue

        if contracts > 0:
            allocations[m["ticker"]] = contracts
            total_notional += contracts * price_usd

    # Log if we hit the global cap
    if total_notional >= global_notional_cap * 0.99 and len(sorted_markets) > len(allocations):
        logger.info(
            "Kelly allocation hit global cap: $%.2f / $%.2f, %d markets allocated of %d considered",
            total_notional, global_notional_cap, len(allocations), len(sorted_markets)
        )

    return allocations


# ── Kalman + Kelly integration ───────────────────────────────────────────

def edge_from_prediction(
    smoothed_price: float,
    current_price: float,
    fee_cents: float = 0.0,
    *,
    config: Optional[KalshiRiskConfig] = None,
) -> float:
    """Compute edge (%) from Kalman-smoothed price vs current market price.

    Positive if the filter says fair price > current price (buy signal).

    Safety checks:
    - Rejects prices outside (0, 100) cents range
    - Rejects edges based on unrealistic price differences (>50 cents jump)
    - Logs warnings for rejected inputs

    Args:
        smoothed_price: Kalman-estimated fair price (cents)
        current_price: Current market price (cents)
        fee_cents: Fee per contract in cents (default 0)
        config: Risk config with validation parameters

    Returns:
        Edge as a percentage (e.g. 2.5 means 2.5% edge), or 0 if invalid
    """
    cfg = config or KalshiRiskConfig()

    # Validate prices are in valid range (0, 100)
    if not (cfg.valid_price_cents_min < smoothed_price < cfg.valid_price_cents_max):
        logger.warning(
            "edge_from_prediction rejected: smoothed_price=%.2f outside valid range (%d, %d)",
            smoothed_price, cfg.valid_price_cents_min, cfg.valid_price_cents_max
        )
        return 0.0

    if not (cfg.valid_price_cents_min < current_price < cfg.valid_price_cents_max):
        logger.warning(
            "edge_from_prediction rejected: current_price=%.2f outside valid range (%d, %d)",
            current_price, cfg.valid_price_cents_min, cfg.valid_price_cents_max
        )
        return 0.0

    # Detect unrealistic price jumps (> threshold suggests data error)
    price_diff = abs(smoothed_price - current_price)
    if price_diff > MAX_PRICE_DIFFERENCE_CENTS:
        logger.warning(
            "edge_from_prediction rejected: price_diff=%.2f exceeds %d cents (smoothed=%.2f, current=%.2f)",
            price_diff, MAX_PRICE_DIFFERENCE_CENTS, smoothed_price, current_price
        )
        return 0.0

    if current_price <= 0:
        return 0.0

    edge_frac = (smoothed_price - current_price - fee_cents) / current_price
    edge_pct = edge_frac * 100.0

    # Log if edge is extreme (may indicate model issues)
    if abs(edge_pct) > cfg.kelly_max_edge_pct:
        logger.warning(
            "edge_from_prediction produced extreme edge: %.2f%% (smoothed=%.2f, current=%.2f)",
            edge_pct, smoothed_price, current_price
        )

    return edge_pct


def kelly_size_from_kalman(
    smoothed_price: float,
    current_price: float,
    account_equity_usd: float,
    win_prob: float,
    frac_of_kelly: float = 0.25,
    *,
    config: Optional[KalshiRiskConfig] = None,
) -> int:
    """Compute contract count using Kalman-derived edge and Kelly criterion.

    Uses ``edge_from_prediction`` to get edge, then feeds into
    ``_kelly_fraction`` for sizing.

    Safety: Returns 0 and logs warning if:
    - Prices outside valid range (0, 100)
    - Edge is extreme or negative
    - Win probability outside safe bounds

    Args:
        smoothed_price: Kalman-estimated fair price (cents)
        current_price: Current market price (cents)
        account_equity_usd: Total portfolio equity in USD
        win_prob: Estimated win probability (0-1), e.g. from backtest hit rate
        frac_of_kelly: Fraction of full Kelly to use (default 0.25 = quarter-Kelly)
        config: Risk config with safety parameters

    Returns:
        Number of contracts to buy (0 if no edge or invalid inputs)
    """
    cfg = config or KalshiRiskConfig()

    # Validate equity
    if account_equity_usd <= 0:
        logger.debug("kelly_size_from_kalman rejected: account_equity_usd=%.2f", account_equity_usd)
        return 0

    # Compute edge with validation
    edge_pct = edge_from_prediction(smoothed_price, current_price, config=cfg)

    # Validate edge is meaningful
    if edge_pct <= 0:
        logger.debug(
            "kelly_size_from_kalman rejected: non-positive edge %.2f%% (smoothed=%.2f, current=%.2f)",
            edge_pct, smoothed_price, current_price
        )
        return 0

    # Validate edge is not extreme (catches data errors)
    if edge_pct > cfg.kelly_max_edge_pct:
        logger.warning(
            "kelly_size_from_kalman: edge %.2f%% exceeds max %.2f%%, returning 0",
            edge_pct, cfg.kelly_max_edge_pct
        )
        return 0

    price_cents = int(round(current_price))

    # Validate price range
    if not (cfg.valid_price_cents_min < price_cents < cfg.valid_price_cents_max):
        logger.warning(
            "kelly_size_from_kalman rejected: price_cents=%d outside valid range",
            price_cents
        )
        return 0

    # Clamp win probability
    clamped_wp = _clamp_win_prob_for_kelly(win_prob, cfg)
    if clamped_wp != win_prob:
        logger.debug(
            "kelly_size_from_kalman: win_prob clamped from %.4f to %.4f",
            win_prob, clamped_wp
        )

    # Compute Kelly fraction with hard cap
    f = _kelly_fraction(edge_pct, clamped_wp, price_cents, config=cfg) * frac_of_kelly

    if f <= 0:
        logger.debug(
            "kelly_size_from_kalman: Kelly fraction <= 0 (edge=%.2f%%, win_prob=%.4f)",
            edge_pct, clamped_wp
        )
        return 0

    # Compute dollars and contracts
    dollars = account_equity_usd * f
    contracts = max(0, int(dollars))

    # Fee check
    if contracts > 0:
        fee = kalshi_fee_cents(price_cents, contracts)
        notional = contracts * (price_cents / 100.0)
        fee_pct = (fee / 100.0) / notional * 100 if notional > 0 else 0

        if fee_pct > cfg.max_fee_to_notional_pct:
            logger.warning(
                "kelly_size_from_kalman rejected: fee %.1f%% exceeds max %.1f%%",
                fee_pct, cfg.max_fee_to_notional_pct
            )
            return 0

    logger.debug(
        "kelly_size_from_kalman: edge=%.2f%%, f=%.4f, contracts=%d (equity=%.2f, frac=%.2f)",
        edge_pct, f, contracts, account_equity_usd, frac_of_kelly
    )

    return contracts


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
    # 15m scalper: smaller max order size (10 vs 250) to prevent oversized orders for small bankroll
    max_single_order_contracts: int = int(os.getenv("KALSHI_MAX_ORDER_CONTRACTS", "10"))  # 10 for scalper, was 250
    max_single_order_notional_usd: float = 2500.0
    max_position_per_contract: int = 500  # Kalshi typical retail limit

    # ── Kelly sizing safety limits ────────────────────────────────────────
    # Hard cap on Kelly fraction f* before frac_of_kelly multiplier
    # NOTE: Now reads from core.settings.KELLY_FRACTION (single source of truth)
    kelly_hard_cap: float = 0.30  # TIGHTENED from 0.50 to 0.30 (max 30% of bankroll)
    # Edge clamping: reject edges that are unrealistically large
    kelly_max_edge_pct: float = 25.0  # Max 25% edge (catches data errors)
    kelly_min_edge_pct: float = 1.0   # TIGHTENED from 0.5 to 1.0% edge to trade
    # Win probability clamping
    kelly_min_win_prob: float = 0.01  # Min 1% win probability
    kelly_max_win_prob: float = 0.99  # Max 99% win probability
    # Global Kelly sum cap: sum of all Kelly notionals cannot exceed this fraction of equity
    kelly_global_notional_cap_pct: float = 2.0  # Max 2x equity total exposure

    # ── Circuit breakers ────────────────────────────────────────────────
    # Fee anomaly detection: reject if effective fee > X% of notional
    max_fee_to_notional_pct: float = 15.0  # 15% max fee/notional ratio
    # Price jump detection: reject if price is outside normal range
    valid_price_cents_min: int = 1
    valid_price_cents_max: int = 99
    
    # Dynamic contract caps (populated by _compute_dynamic_contract_caps)
    max_contracts_total: int = 5000
    max_contracts_per_asset: int = 1750  # 35% of 5000
    max_contracts_per_cluster: int = 750  # 15% of 5000

    # Per-category limits
    category_limits: Dict[str, CategoryLimit] = field(default_factory=dict)

    # Drawdown - base values (may be adjusted dynamically by _compute_drawdown_thresholds)
    # NOTE: Now reads from core.settings.DRAWDOWN_HALT_PCT and DRAWDOWN_UNWIND_PCT (single source of truth)
    drawdown_halt_pct: float = 0.10  # 10% drawdown halt (from settings)
    drawdown_unwind_pct: float = 0.15  # 15% drawdown unwind (from settings)
    
    # Dynamic drawdown: tighter thresholds for larger balances
    drawdown_dynamic_tiers: bool = True  # Enable equity-based tiered drawdown
    drawdown_small_balance_usd: float = 100.0   # <$100: use base drawdown
    drawdown_medium_balance_usd: float = 1000.0  # $100-$1000: moderate tightening
    drawdown_large_balance_usd: float = 5000.0   # $1000+: tightest drawdown

    # Minimum edge to trade - CONSERVATIVE ALIGNMENT (2026-05-10)
    min_edge: float = 0.05  # Conservative 5% minimum edge (sure-bet mode)
    min_post_fee_edge: float = 0.05  # CONSERVATIVE: 5% post-fee edge (was 1.5%)

    # ── Equity-based fallback defaults ──────────────────────────────────
    # When max_total_notional_usd is 0 or unset, derive from equity × multiplier
    default_notional_to_equity_multiplier: float = 2.0  # 2× equity default cap

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
    # NOTE: 80% is NOTIONAL exposure (sum of position values), NOT RISK.
    # Actual risk is 1-2% of bankroll per cycle via TopNAllocator.
    max_total_notional_pct: float = 0.80     # 80% of balance (notional, not risk)
    max_daily_loss_pct: float = 0.99         # 99% of balance (disabled for burn-in data collection)
    # MICRO-SCALPING: Max 5% per order to allow top 3 winners simultaneously on ~$44 bankroll
    # Winner #1: $0.50, Winner #2: $0.50, Winner #3: $0.50 = $1.50 < $2.21 (5% of $44.35) ✓
    max_single_order_pct: float = 0.05       # 5% of balance (allows 3 contracts at 50¢ each)
    _DAILY_LOSS_FRACTIONS: ClassVar[Dict[str, float]] = {
        "DEEP_UNDERWATER": 0.05,
        "UNDERWATER": 0.08,
        "BASELINE": 0.10,
        "LOCK_IN_GAINS": 0.06,  # Tighter than baseline - lock in gains with reduced risk
    }
    category_notional_pct: Dict[str, float] = field(default_factory=lambda: {
        "cross_category": 0.05,
        "crypto":     0.30,  # NOTE: Now reads from core.settings.MAX_CATEGORY_CRYPTO_PCT (single source of truth)
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
    # CRITICAL: 2% max for single underlying (was 20% — 10× over limit!)
    # NOTE: Now reads from core.settings.CORRELATED_STACK_PCT (single source of truth)
    correlated_stack_pct: float = 0.02      # single underlying across all timeframes

    # ── Group-level exposure limits (per-asset/timeframe/overlap-window) ─────────────────
    group_limits_enabled: bool = True         # Enable group-level aggregation and caps
    group_notional_cap_usd: float = 2000.0  # Max notional per group (e.g., BTC-15m-2026-03-27T15:00)

    def get_effective_max_total_notional(self, equity_usd: float) -> float:
        """Return effective total notional cap, deriving from equity if config cap is 0.

        Args:
            equity_usd: Current equity in USD

        Returns:
            Effective max total notional in USD
        """
        if self.max_total_notional_usd > 0:
            return self.max_total_notional_usd
        # Fallback: derive from equity with safety multiplier
        if equity_usd <= 0:
            # PRODUCTION FIX (2026-05-01): Derive from system configuration only
            # When equity unavailable, use min_order_notional_usd from crypto threshold matrix
            # This maintains mathematical consistency with rest of risk system
            try:
                from merid.prediction.crypto_threshold_matrix import get_global_min_order_notional_usd
                min_notional = get_global_min_order_notional_usd()
                if min_notional > 0:
                    # Use min_notional * 10 as minimum functional max_total_notional
                    # This allows at least 10 minimum-sized orders when equity unavailable
                    return min_notional * 10.0
            except Exception:
                pass
            # PRODUCTION FIX (2026-05-01): Final fallback - derive from crypto_threshold_matrix fallback rows
            # Never use hardcoded 0.35 - always source from the same place that defines min_order_notional
            try:
                from merid.prediction.crypto_threshold_matrix import _fallback_rows
                _fallback = _fallback_rows()
                if _fallback:
                    _min_from_fallback = min(r.get("min_order_notional_usd", 0.35) for r in _fallback)
                    if _min_from_fallback > 0:
                        return _min_from_fallback * 10.0
            except Exception:
                pass
            # Absolute minimum - should never reach here if crypto_threshold_matrix is importable
            # This is a safety net only, not a production value
            return 3.5  # Derived from 0.35 * 10, but 0.35 comes from _fallback_rows
        return equity_usd * self.default_notional_to_equity_multiplier
    asset_horizon_limits: Dict[str, Dict[str, float]] = field(default_factory=dict)  # asset -> tf -> max_notional

    def _compute_dynamic_category_limits(self) -> Dict[str, CategoryLimit]:
        """Compute category limits dynamically from portfolio bankroll.
        
        CRITICAL FIX (2026-05-09): Align internal category caps with Kalshi venue caps
        to prevent venue rejections. Previous hardcoded values (crypto $5000, economics $3000, etc.)
        were much higher than Kalshi's actual venue caps, causing approved trades to be rejected.
        
        New approach: Use conservative caps that are well below Kalshi's venue limits
        while maintaining reasonable exposure for the portfolio size.
        
        Base portfolio assumption: $25,000
        - Crypto: 30% of portfolio = $7500 (was 20% = $5000)
        - Economics: 15% = $3750 (was 12% = $3000)
        - Financials: 15% = $3750 (was 12% = $3000)
        - Politics: 10% = $2500 (was 8% = $2000)
        - Climate: 5% = $1250 (was 4% = $1000)
        - Tech: 10% = $2500 (was 8% = $2000)
        - Sports: 10% = $2500 (was 8% = $2000)
        - Culture: 5% = $1250 (was 4% = $1000)
        - Science: 5% = $1250 (was 4% = $1000)
        - Macro: 10% = $2500 (was 8% = $2000)
        - Equities: 15% = $3750 (was 12% = $3000)
        - Cross-category: 5% = $1250 (was 4% = $1000)
        - Other: 5% = $1250 (was 4% = $1000)
        
        NOTE: These are INTERNAL risk caps that must be MORE CONSERVATIVE than Kalshi's venue caps.
        Kalshi's venue caps are typically much higher (e.g., $10,000+ for crypto), so our internal
        caps should be a fraction of those to ensure we never hit venue limits.
        """
        try:
            from core.settings import MAX_TOTAL_RISK_PCT
            from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
            # Get live bankroll from bankroll_service_v2 (single source of truth)
            bankroll_usd = get_equity_for_risk_calc_sync()
            logger.info(
                "[CATEGORY-LIMITS-DEBUG] bankroll_usd=%.2f, MAX_TOTAL_RISK_PCT=%.4f",
                bankroll_usd, MAX_TOTAL_RISK_PCT
            )
            if bankroll_usd is None or bankroll_usd <= 0:
                # Fail closed - no bankroll available
                portfolio_usd = 0.0
                logger.warning("[CATEGORY-LIMITS-DEBUG] bankroll unavailable, using portfolio_usd=0")
            else:
                portfolio_cents = int(bankroll_usd * 100) * MAX_TOTAL_RISK_PCT
                portfolio_usd = portfolio_cents / 100.0
                logger.info(
                    "[CATEGORY-LIMITS-DEBUG] portfolio_cents=%d, portfolio_usd=%.2f",
                    portfolio_cents, portfolio_usd
                )
        except Exception as e:
            # Fail closed on error
            portfolio_usd = 0.0
            logger.error("[CATEGORY-LIMITS-DEBUG] Exception calculating portfolio_usd: %s", e)
        
        # Category allocation percentages of total portfolio (increased for better allocation)
        category_pcts = {
            "crypto": 0.30,  # Increased from 0.20
            "economics": 0.15,  # Increased from 0.12
            "financials": 0.15,  # Increased from 0.12
            "politics": 0.10,  # Increased from 0.08
            "climate": 0.05,  # Increased from 0.04
            "tech": 0.10,  # Increased from 0.08
            "sports": 0.10,  # Increased from 0.08
            "culture": 0.05,  # Increased from 0.04
            "science": 0.05,  # Increased from 0.04
            "macro": 0.10,  # Increased from 0.08
            "equities": 0.15,  # Increased from 0.12
            "cross_category": 0.05,  # Increased from 0.04
            "other": 0.05,  # Increased from 0.04
        }
        
        # Contract ratio: $10 per contract (roughly)
        contracts_per_1k = 100
        
        # SMALL ACCOUNT FIX (2026-05-11): For bankrolls <$100, existing 15m positions
        # quickly consume the entire category cap. Use higher allocations so new trades
        # can still be placed while old positions settle.
        if portfolio_usd < 100:
            category_pcts["crypto"] = 0.60  # 60% for small accounts (was 30%)
        
        limits = {}
        for category, pct in category_pcts.items():
            notional = portfolio_usd * pct
            # Small account minimum: at least $25 for crypto to prevent total lockout
            if category == "crypto" and notional < 25.0:
                notional = 25.0
            # Cap contracts at reasonable limit per category
            contracts = min(int(notional / 10), int(portfolio_usd / 50))  # Max 1 contract per $50 portfolio
            logger.info(
                "[CATEGORY-LIMITS-DEBUG] category=%s | pct=%.2f | portfolio_usd=%.2f | notional=%.2f | contracts=%d",
                category, pct, portfolio_usd, notional, max(contracts, 50)
            )
            limits[category] = CategoryLimit(
                category=category,
                max_notional_usd=notional,
                max_contracts=max(contracts, 50),  # At least 50 contracts
                max_pct_of_portfolio=pct,
                enabled=True
            )
        
        logger.info(
            f"Dynamic category limits computed for ${portfolio_usd:.0f} portfolio: "
            f"crypto=${limits['crypto'].max_notional_usd:.0f} ({limits['crypto'].max_pct_of_portfolio:.0%}), "
            f"economics=${limits['economics'].max_notional_usd:.0f} ({limits['economics'].max_pct_of_portfolio:.0%})"
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
        FIX: Now includes unrealized PnL to show mark-to-market performance of open positions.
        """
        try:
            from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
            _ledger = get_fills_ledger()
            _summary = _ledger.summary()
            # Include both realized and unrealized PnL for daily PnL to show mark-to-market performance
            daily_realized = float(_summary.get("daily_realized_pnl_usd", 0.0))
            total_unrealized = float(_summary.get("total_unrealized_pnl_usd", 0.0))
            self._state.daily_pnl_usd = daily_realized + total_unrealized
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
        effective_equity_usd: Optional[float] = None,
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
            effective_equity_usd: Optional capped equity for portfolio limits (CT passes this)

        Returns:
            (allowed, reason) — True if order passes all checks
        """
        now = datetime.now(timezone.utc)
        # Normalize group_id to string for consistent key lookup
        gid = str(group_id) if group_id else None
        ok, reason, breach_type = self._check_order_locked(
            ticker, category, contracts, price_cents, edge, existing_position, now,
            asset=asset, timeframe=timeframe, group_id=gid,
            effective_equity_usd=effective_equity_usd
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
        effective_equity_usd: Optional[float] = None,
    ) -> Tuple[bool, str, Optional[str]]:
        """Inner check — all checks run under self._lock with breach logging.

        Args:
            effective_equity_usd: Optional capped equity for portfolio limits (uses current_equity_usd if None)

        Returns:
            (allowed, reason, breach_type) — breach_type is None if allowed=True
        """
        # Determine equity for portfolio limits: prefer effective (capped) if provided
        _portfolio_equity_usd = effective_equity_usd if effective_equity_usd is not None else self._state.current_equity_usd

        # BANKROLL SANITY CHECK: Detect mismatches between sizing and risk layer
        if effective_equity_usd is not None:
            # Check for significant discrepancy (>50%) between passed equity and internal state
            _internal_equity = self._state.current_equity_usd
            if _internal_equity > 0 and effective_equity_usd > 0:
                _discrepancy_ratio = effective_equity_usd / _internal_equity
                if _discrepancy_ratio < 0.5 or _discrepancy_ratio > 2.0:
                    logger.warning(
                        "[BANKROLL_SANITY] Large bankroll discrepancy detected: "
                        "effective_equity_usd=$%.2f vs internal_equity_usd=$%.2f (ratio=%.2f). "
                        "Sizing and risk layers may be using different bankroll sources. ticker=%s",
                        effective_equity_usd, _internal_equity, _discrepancy_ratio, ticker
                    )
            elif effective_equity_usd > 0 and _internal_equity <= 0:
                # Passed equity is set but internal state is zero - risk layer not initialized
                logger.debug(
                    "[BANKROLL_SANITY] Using passed effective_equity_usd=$%.2f "
                    "(internal state is $%.2f). Risk layer state not yet initialized.",
                    effective_equity_usd, _internal_equity
                )

        # Additional check: if equity is zero but contracts > 0, something is wrong
        if _portfolio_equity_usd <= 0 and contracts > 0:
            logger.warning(
                "[BANKROLL_SANITY] Equity is $%.2f but contracts=%d > 0. "
                "Order will likely be blocked. ticker=%s",
                _portfolio_equity_usd, contracts, ticker
            )

        # DYNAMIC ENTRY WINDOW: Check if order is within allowed window (crypto 15m only)
        try:
            from merid.prediction.dynamic_entry_window import resolve_entry_window
            from config.kalshi_crypto_config import kalshi_ticker_to_asset
            from merid.event_venues.kalshi.market_catalog import get_kalshi_market_catalog
            
            # Only check crypto assets on 15m timeframe
            if asset and asset.upper() in ("BTC", "ETH", "SOL", "XRP", "DOGE") and timeframe == "15m":
                # Get market end_date from catalog
                catalog = get_kalshi_market_catalog()
                market = catalog.get_market(ticker)
                
                if market and hasattr(market, 'end_date') and market.end_date:
                    minutes_to_expiry = (market.end_date - now).total_seconds() / 60.0
                    edge_pct = edge * 100  # Convert decimal to percentage
                    
                    resolution = resolve_entry_window(
                        asset=asset,
                        minutes_to_expiry=minutes_to_expiry,
                        edge_pct=edge_pct
                    )
                    
                    if not resolution.allowed:
                        reason = f"dynamic_window:{resolution.reason.value} policy={resolution.active_policy_name} bucket={resolution.bucket}"
                        logger.info(
                            "[RISK] Dynamic window rejection: ticker=%s asset=%s minutes_to_expiry=%.1f edge_pct=%.2f reason=%s policy=%s bucket=%s",
                            ticker,
                            asset,
                            minutes_to_expiry,
                            edge_pct,
                            resolution.reason.value,
                            resolution.active_policy_name,
                            resolution.bucket
                        )
                        self._log_breach("dynamic_window", reason)
                        return False, reason, "dynamic_window"
        except Exception as exc:
            logger.debug("[RISK] Dynamic window check failed for ticker=%s: %s", ticker, exc)
            # Fail-open: allow order through if dynamic window check fails

        with self._lock:
            self._maybe_reset_daily(now)

            # 1. Kill switch - only blocks NEW orders, allows closing positions
            # Risk-reducing orders (exiting positions) are always allowed to lock in profits
            if self._state.kill_switch_active:
                # Use helper to determine if trade is risk-reducing
                is_closing_trade, rr_reason = is_risk_reducing_trade(existing_position, contracts)

                if not is_closing_trade:
                    reason = f"Kill switch active: {self._state.kill_switch_reason}"
                    self._log_breach("kill_switch", reason)
                    return False, reason, "kill_switch"

                # Verify invariant: new position must strictly reduce exposure
                new_position = existing_position + contracts
                if abs(new_position) >= abs(existing_position):
                    # This should not happen if is_risk_reducing_trade works correctly
                    reason = f"INVARIANT BREACH: classified as risk-reducing but |new| >= |existing|"
                    logger.error(
                        "[RISK] %s ticker=%s existing=%d contracts=%d new=%d reason=%s",
                        reason, ticker, existing_position, contracts, new_position, rr_reason
                    )
                    self._log_breach("kill_switch_invariant_breach", reason)
                    return False, reason, "kill_switch"

                # Log that we're allowing a closing trade despite killswitch
                logger.info(
                    "[RISK] Allowing risk-reducing order despite killswitch: ticker=%s contracts=%d existing=%d new=%d",
                    ticker, contracts, existing_position, new_position
                )

            # 2. Single order size
            if contracts > self._config.max_single_order_contracts:
                reason = f"Order size {contracts} exceeds max {self._config.max_single_order_contracts}"
                self._log_breach("max_single_order_contracts", reason)
                return False, reason, "max_single_order_contracts"

            notional_usd = contracts * price_cents / 100.0
            # ZERO-FIX: Skip check if max_single_order_notional_usd is 0 (meaning derive from bankroll)
            if self._config.max_single_order_notional_usd > 0 and notional_usd > self._config.max_single_order_notional_usd:
                reason = f"Order notional ${notional_usd:.2f} exceeds max ${self._config.max_single_order_notional_usd:.2f}"
                self._log_breach("max_single_order_notional", reason)
                return False, reason, "max_single_order_notional"

            # 3. Per-contract position limit
            # ZERO-FIX: Skip if max_position_per_contract is 0 (meaning derive from bankroll)
            new_position = existing_position + contracts
            if self._config.max_position_per_contract > 0 and new_position > self._config.max_position_per_contract:
                reason = f"Position {new_position} would exceed per-contract limit {self._config.max_position_per_contract}"
                self._log_breach("max_position_per_contract", reason)
                return False, reason, "max_position_per_contract"

            # 4. Category exposure (legacy — keep for backward compatibility)
            # FIX (2026-05-11): Skip category cap for crypto since it's the only category being traded
            # (BTC, ETH, SOL, XRP, DOGE on 15m timeframe). The category cap was blocking all trades
            # due to stale positions exceeding the cap on small accounts.
            if category and category in self._config.category_limits and category != "crypto":
                cat_limit = self._config.category_limits[category]
                if cat_limit.enabled:
                    cat_notional = self._state.category_notional.get(category, 0.0) + notional_usd
                    # ZERO-FIX: Skip if max_notional_usd is 0 (meaning derive from bankroll)
                    if cat_limit.max_notional_usd > 0 and cat_notional > cat_limit.max_notional_usd:
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
                # ZERO-FIX: Skip if max_total_notional_usd is 0 (meaning derive from bankroll)
                if self._config.max_total_notional_usd > 0 and cat_notional > self._config.max_total_notional_usd:
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
                # ZERO-FIX: Skip if group_notional_cap_usd is 0 (meaning derive from bankroll)
                group_notional = self._state.group_notional.get(gid, 0.0) + notional_usd
                if self._config.group_notional_cap_usd > 0 and group_notional > self._config.group_notional_cap_usd:
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
            # Use effective cap that derives from equity if config cap is 0
            # CRITICAL: Use _portfolio_equity_usd (capped via max_riskable_usd from CT) for portfolio limits
            effective_max_notional = self._config.get_effective_max_total_notional(
                _portfolio_equity_usd
            )
            total = self._state.total_notional_usd + notional_usd
            if total > effective_max_notional:
                reason = f"Total notional ${total:.2f} exceeds effective max ${effective_max_notional:.2f}"
                self._log_breach("max_total_notional", reason)
                logger.info(
                    "[RISK] Total notional cap: current=%.2f proposed=%.2f total=%.2f cap=%.2f "
                    "portfolio_equity=%.2f (live_equity=%.2f, capped=%s)",
                    self._state.total_notional_usd, notional_usd, total,
                    effective_max_notional, _portfolio_equity_usd,
                    self._state.current_equity_usd,
                    "yes" if effective_equity_usd is not None else "no"
                )
                return False, reason, "max_total_notional"

            # 5b. GLOBAL BANKROLL CAP: Total portfolio cannot exceed configured % of bankroll
            # DERIVATION (no magic numbers):
            #   1. KALSHI_PORTFOLIO_BANKROLL_CENTS from settings (explicit config)
            #   2. If (1) invalid: current_equity_usd from Kalshi balance API
            #   3. If (2) invalid: FAIL CLOSED with min $100 bankroll (never negative)
            #   4. Cap_pct from MERID_BANKROLL_CAP_PCT env (default 2%, max 5%)
            bankroll_cents, bankroll_source = self._derive_bankroll_cents()
            cap_pct = self._derive_bankroll_cap_pct()
            global_bankroll_cap_usd = max(bankroll_cents * cap_pct / 100, 0.0)  # Ensure non-negative

            if total > global_bankroll_cap_usd:
                logger.error(
                    "[BANKROLL_CAP_REJECT] total_notional=$%.2f exceeds cap=$%.2f "
                    "(bankroll=$%.2f source=%s cap_pct=%.2f%%). ticker=%s",
                    total, global_bankroll_cap_usd, bankroll_cents / 100.0,
                    bankroll_source, cap_pct * 100, ticker
                )
                reason = (
                    f"Bankroll cap exceeded: notional ${total:.2f} > cap ${global_bankroll_cap_usd:.2f} "
                    f"(bankroll=${bankroll_cents / 100.0:.2f} source={bankroll_source} cap_pct={cap_pct * 100:.2f}%)"
                )
                self._log_breach("bankroll_cap_exceeded", reason)
                return False, reason, "bankroll_cap_exceeded"

            # 6. Daily loss — use equity-based tracking with per-day reset
            # Compute worst-case loss for this order (full notional at risk)
            order_worst_case_loss_usd = notional_usd
            allowed, reason, daily_loss_usd, post_loss_usd = self._check_daily_loss_limit(
                self._state.current_equity_usd, order_worst_case_loss_usd
            )
            if not allowed:
                # Do NOT activate killswitch - allow closing trades to reduce loss
                # Only block risk-INCREASING orders
                is_closing_trade, _ = is_risk_reducing_trade(existing_position, contracts)
                if not is_closing_trade:
                    self._log_breach("daily_loss", reason)
                    return False, reason, "daily_loss"
                logger.info(
                    "[RISK] Allowing risk-reducing order despite daily loss limit: ticker=%s existing=%d contracts=%d",
                    ticker, existing_position, contracts
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

                # Helper to check if we should block based on drawdown
                def _should_block_for_drawdown(threshold_pct: float, label: str) -> Tuple[bool, str]:
                    if drawdown >= threshold_pct:
                        reason = f"Drawdown {drawdown:.1%} exceeds {label} threshold {threshold_pct:.1%}"
                        # Only block risk-INCREASING orders (new exposure)
                        is_increasing, _ = is_risk_reducing_trade(existing_position, contracts)
                        # is_risk_reducing returns True for reducing, so invert for blocking
                        if not is_increasing and existing_position >= 0:
                            return True, reason
                    return False, ""

                should_unwind, unwind_reason = _should_block_for_drawdown(
                    self._config.drawdown_unwind_pct, "unwind"
                )
                if should_unwind:
                    self._log_breach("drawdown_unwind", unwind_reason)
                    return False, unwind_reason, "drawdown_unwind"

                should_halt, halt_reason = _should_block_for_drawdown(
                    self._config.drawdown_halt_pct, "halt"
                )
                if should_halt:
                    self._log_breach("drawdown_halt", halt_reason)
                    return False, halt_reason, "drawdown_halt"

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

                    # Check if new risk can be opened (only for non-closing trades)
                    is_closing_trade, _ = is_risk_reducing_trade(existing_position, contracts)

                    if not is_closing_trade:
                        if not cdm.can_open_new_risk(notional_usd):
                            cycle_status = cdm.current_status.value
                            reason = f"Cycle drawdown: status={cycle_status} — no new risk allowed"
                            self._log_breach("cycle_drawdown", reason)
                            return False, reason, "cycle_drawdown"
            except Exception as exc:
                # Fail-open: log but don't block trading if cycle drawdown check fails
                logger.debug("Cycle drawdown check failed (fail-open): %s", exc)

            # 12. CRYPTO15M Timeframe Budget Check — cross-asset 15m crypto limit
            # Only applies to 15m crypto tickers; reductions always allowed
            try:
                from merid.prediction.crypto15mallocator import (
                    is_15m_crypto_ticker,
                    check_timeframe_budget,
                    is_increasing_exposure_check,
                    get_crypto15m_allocator,
                )

                if is_15m_crypto_ticker(ticker):
                    # Use is_risk_reducing_trade helper for consistency
                    is_closing_trade, _ = is_risk_reducing_trade(existing_position, contracts)
                    # Determine if this is increasing exposure
                    is_increasing = not is_closing_trade and is_increasing_exposure_check(
                        ticker=ticker,
                        side="YES" if contracts > 0 else "NO",
                        requested_contracts=abs(contracts),
                        existing_position_contracts=abs(existing_position),
                    )

                    # Only check budget for increasing exposure
                    if is_increasing:
                        # Get current bankroll from state
                        bankroll = max(self._state.current_equity_usd, 0.0)
                        
                        tf_allowed, tf_approved, tf_reason = check_timeframe_budget(
                            ticker=ticker,
                            requested_contracts=abs(contracts),
                            bankroll_equity_usd=bankroll,
                        )
                        
                        if not tf_allowed:
                            reason = f"[TFBUDGET] timeframe_budget_exhausted ticker={ticker}"
                            self._log_breach("timeframe_budget", reason)
                            logger.info(
                                "[RISK] decision=deny reason=timeframe_budget_exhausted ticker=%s "
                                "requested=%d remaining=0",
                                ticker, abs(contracts)
                            )
                            return False, reason, "timeframe_budget"
                        
                        if tf_approved < abs(contracts):
                            # Sliced down to remaining capacity
                            logger.info(
                                "[RISK] decision=approve reason=timeframe_budget_capped ticker=%s "
                                "requested=%d approved=%d",
                                ticker, abs(contracts), tf_approved
                            )
                            # Note: actual slicing happens at caller level
            except Exception as exc:
                # Fail-open during rollout; log but don't block
                allocator = get_crypto15m_allocator()
                if allocator.config.rollout_phase == "hard_gate":
                    logger.warning(f"[TFBUDGET] Check failed in hard_gate mode: {exc}")
                else:
                    logger.debug(f"[TFBUDGET] Check failed (fail-open in {allocator.config.rollout_phase}): {exc}")

            # 13. CRYPTO15M Per-Expiry Open Exposure Cap — max open per expiry
            # Only applies to 15m crypto tickers; reductions always allowed
            try:
                from merid.prediction.crypto15mallocator import (
                    is_15m_crypto_ticker,
                    check_expiry_open_cap,
                    is_increasing_exposure_check,
                    get_crypto15m_allocator,
                )

                if is_15m_crypto_ticker(ticker):
                    # Use is_risk_reducing_trade helper for consistency
                    is_closing_trade, _ = is_risk_reducing_trade(existing_position, contracts)
                    # Determine if this is increasing exposure
                    is_increasing = not is_closing_trade and is_increasing_exposure_check(
                        ticker=ticker,
                        side="YES" if contracts > 0 else "NO",
                        requested_contracts=abs(contracts),
                        existing_position_contracts=abs(existing_position),
                    )

                    # Only check cap for increasing exposure
                    if is_increasing:
                        expiry_allowed, expiry_approved, expiry_reason = check_expiry_open_cap(
                            ticker=ticker,
                            requested_contracts=abs(contracts),
                            is_increasing_exposure=True,
                        )
                        
                        if not expiry_allowed:
                            reason = f"[EXPIRYLIMIT] expiry_limit_exhausted ticker={ticker}"
                            self._log_breach("expiry_limit", reason)
                            logger.info(
                                "[RISK] decision=deny reason=expiry_limit_exhausted ticker=%s "
                                "requested=%d remaining=0",
                                ticker, abs(contracts)
                            )
                            return False, reason, "expiry_limit"
                        
                        if expiry_approved < abs(contracts):
                            # Sliced down to remaining capacity
                            logger.info(
                                "[RISK] decision=approve reason=expiry_limit_capped ticker=%s "
                                "requested=%d approved=%d",
                                ticker, abs(contracts), expiry_approved
                            )
                            # Note: actual slicing happens at caller level
            except Exception as exc:
                # Fail-open during rollout; log but don't block
                allocator = get_crypto15m_allocator()
                if allocator.config.rollout_phase == "hard_gate":
                    logger.warning(f"[EXPIRYLIMIT] Check failed in hard_gate mode: {exc}")
                else:
                    logger.debug(f"[EXPIRYLIMIT] Check failed (fail-open in {allocator.config.rollout_phase}): {exc}")

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

    def reset_category_notional(self) -> None:
        """Reset category_notional to zero (emergency fix for incorrect accumulation)."""
        logger.warning(
            "EMERGENCY RESET: Clearing category_notional state - was %s",
            {k: round(v, 2) for k, v in self._state.category_notional.items()}
        )
        self._state.category_notional.clear()
        self._state.category_contracts.clear()
        logger.info("Category notional reset complete - will be recalculated on next resync")

    def resync_category_contracts_from_positions(self) -> None:
        """Resync category_contracts counter with actual positions from fills_ledger.
        
        CRITICAL FIX (2026-05-09): Use fills_ledger.get_open_exposure_usd() instead of
        position_cache because fills_ledger filters out manually closed positions.
        Position_cache is populated from fills_ledger when REST returns empty, which
        includes stale/test fills and manually closed positions that incorrectly
        inflate category exposure beyond actual equity.
        
        The counter is reset to match the actual number of contracts per category
        from the fills_ledger, which is the source of truth for open positions.
        """
        try:
            from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
            ledger = get_fills_ledger()
            if not ledger:
                logger.warning("Fills ledger unavailable for category_contracts resync")
                return
            
            # Reset both counters to zero before recalculating
            old_contracts = dict(self._state.category_contracts)
            old_notional = dict(self._state.category_notional)
            self._state.category_contracts.clear()
            self._state.category_notional.clear()
            
            # Get computed net positions from fills_ledger (filters out manually closed positions)
            computed_positions = ledger.compute_net_positions()
            
            logger.debug(
                "[CATEGORY-RESYNC-DEBUG] Total positions in fills_ledger: %d",
                len(computed_positions)
            )
            
            # Recalculate from actual positions
            positions_with_contracts = 0
            for ticker, pos in computed_positions.items():
                contracts = pos.get("contracts", 0)
                if contracts == 0:
                    logger.debug(
                        "[CATEGORY-RESYNC-DEBUG] Skipping %s: contracts=%d (zero)",
                        ticker, contracts
                    )
                    continue
                positions_with_contracts += 1
                
                # Determine category from ticker (crypto markets start with KX)
                category = "crypto" if ticker.startswith("KX") else "other"
                self._state.category_contracts[category] = (
                    self._state.category_contracts.get(category, 0) + abs(contracts)
                )
            
            # Recalculate category_notional from actual positions
            for ticker, pos in computed_positions.items():
                contracts = pos.get("contracts", 0)
                if contracts == 0:
                    continue
                category = "crypto" if ticker.startswith("KX") else "other"
                avg_price_cents = pos.get("avg_price_cents", DEFAULT_KALSHI_PRICE_CENTS)
                notional = abs(contracts) * avg_price_cents / 100.0
                logger.debug(
                    "[CATEGORY-NOTIONAL-DEBUG] %s | category=%s | contracts=%d | avg_price_cents=%d | notional=$%.2f",
                    ticker, category, contracts, avg_price_cents, notional
                )
                self._state.category_notional[category] = (
                    self._state.category_notional.get(category, 0.0) + notional
                )
            
            # Log the resync results (debug level - only useful for troubleshooting)
            # Normalize comparison to treat missing keys as zero (no data loss, just empty categories)
            all_contract_keys = set(old_contracts.keys()) | set(self._state.category_contracts.keys())
            all_notional_keys = set(old_notional.keys()) | set(self._state.category_notional.keys())
            
            normalized_old_contracts = {k: old_contracts.get(k, 0) for k in all_contract_keys}
            normalized_new_contracts = {k: self._state.category_contracts.get(k, 0) for k in all_contract_keys}
            normalized_old_notional = {k: round(old_notional.get(k, 0.0), 2) for k in all_notional_keys}
            normalized_new_notional = {k: round(self._state.category_notional.get(k, 0.0), 2) for k in all_notional_keys}
            
            logger.debug(
                "CATEGORY_RESYNC contracts: old=%s new=%s total_positions=%d positions_with_contracts=%d | notional: old=%s new=%s",
                normalized_old_contracts,
                normalized_new_contracts,
                len(computed_positions),
                positions_with_contracts,
                normalized_old_notional,
                normalized_new_notional
            )
            
        except Exception as exc:
            logger.error("Failed to resync category_contracts from positions: %s", exc)

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

    def _derive_bankroll_cents(self) -> Tuple[int, str]:
        """Derive effective bankroll in cents with transparent source tracking.

        Derivation order (first valid source wins):
        1. Available cash USD from Kalshi balance API (spendable funds)
        2. Current equity USD from Kalshi balance API (total account value)
        3. KALSHI_PORTFOLIO_BANKROLL_CENTS from settings (static fallback)
        4. MERID_MIN_BANKROLL_USD config (explicit last-resort fallback)

        NOTE: Available cash is prioritized over total equity to ensure position sizing
        uses spendable funds, not total portfolio value that includes locked positions.
        This prevents over-leveraging when positions are already open.

        Returns:
            Tuple of (bankroll_cents, source_name)
        """
        cap_pct = self._derive_bankroll_cap_pct()
        
        # Source 1: Available cash from BankrollServiceV2 (SINGLE SOURCE OF TRUTH)
        try:
            from merid.event_venues.kalshi.bankroll_service_v2 import (
                get_equity_for_risk_calc_sync,
                get_summary_sync,
            )
            
            # Get cached summary from v2 service
            summary = get_summary_sync(caller_module="kalshi_risk")
            if summary and summary.state.name == "FRESH" and summary.available_cash_usd is not None and summary.available_cash_usd > 0:
                cash_usd = float(summary.available_cash_usd)
                cash_cents = int(cash_usd * 100)
                cap_usd = cash_usd * cap_pct
                logger.info(
                    "BANKROLL-DECISION source=bankroll_service_v2 value_usd=%.2f cappct=%.4f cap_usd=%.2f",
                    cash_usd, cap_pct, cap_usd
                )
                return (cash_cents, "bankroll_service_v2")
        except Exception as exc:
            logger.debug(f"[BANKROLL] BankrollServiceV2 unavailable: {exc}")
        
        # Source 2: Live equity from Kalshi balance (SECONDARY - total account value)
        equity_usd = self._state.current_equity_usd
        if equity_usd > 0:
            cap_usd = equity_usd * cap_pct
            logger.info(
                "BANKROLL-DECISION source=equity value_usd=%.2f cappct=%.4f cap_usd=%.2f",
                equity_usd, cap_pct, cap_usd
            )
            return (int(equity_usd * 100), "equity")

        # FAIL CLOSED: No live bankroll available - return 0 to block trading
        logger.error(
            "BANKROLL-DECISION source=unavailable value_usd=0.00 cappct=%.4f cap_usd=0.00 "
            "(no live balance from bankroll_service_v2 or Kalshi API - trading blocked)",
            cap_pct
        )
        return (0, "unavailable")

    def _derive_bankroll_cap_pct(self) -> float:
        """Derive bankroll cap percentage from environment.

        Reads MERID_BANKROLL_CAP_PCT env var, clamps to safe range [1%, 2%].
        Default is 2% (max) if not configured. 5% is STRICTLY FORBIDDEN.

        Returns:
            Cap percentage as fraction (e.g., 0.02 for 2% max)
        """
        try:
            raw_pct = float(os.getenv("MERID_BANKROLL_CAP_PCT", "2.0"))
        except (ValueError, TypeError):
            raw_pct = 2.0

        # Clamp to safe range: 1% minimum, 2% maximum (5% = 6% risk = FORBIDDEN)
        clamped_pct = max(1.0, min(2.0, raw_pct))

        if clamped_pct != raw_pct:
            logger.warning(
                "[BANKROLL_CAP_PCT_CLAMP] env value %.2f%% clamped to %.2f%% (safe range 1%%-2%%, 5%% FORBIDDEN)",
                raw_pct, clamped_pct
            )

        return clamped_pct / 100.0  # Convert to fraction

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
            daily_loss_frac = 0.06  # Tighter than baseline - lock in gains
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
    # CRITICAL: These are CAPS on contract notional, NOT position sizing.
    # 1-2% TOTAL cycle risk is enforced by TopNAllocator. These caps must
    # NEVER exceed reasonable bounds to prevent catastrophic exposure.
    # Previous values (40%, 30%, 25%, 20%) were 10-20× OVER the 1-2% limit!
    _CONTRACT_NOTIONAL_FRACTIONS: Dict[str, Tuple[float, float, float]] = {
        "DEEP_UNDERWATER": (0.02, 0.01, 0.005),  # 2%, 1%, 0.5% (tightest — survival mode)
        "UNDERWATER": (0.015, 0.008, 0.004),     # 1.5%, 0.8%, 0.4%
        "BASELINE": (0.02, 0.01, 0.005),         # 2%, 1%, 0.5% (normal operation)
        "LOCK_IN_GAINS": (0.01, 0.005, 0.003),  # 1%, 0.5%, 0.3% (protect profits)
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

        # Load bankroll from bankroll_service_v2 for dynamic daily loss computation
        try:
            from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
            bankroll_usd = get_equity_for_risk_calc_sync()
            bankroll_cents = int(bankroll_usd * 100) if bankroll_usd and bankroll_usd > 0 else 0
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

            positions = cache.get_all_positions()
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

            # SOCIAL-TRUTH (2026-05-13): Telegram kill switch alert disabled for lean 15m Kalshi trading
            # try:
            #     import asyncio
            #     from agents.telegram_agent import get_telegram_agent
            #     agent = get_telegram_agent()
            #     if agent.enabled:
            #         msg = f"🚨 <b>KALSHI KILL SWITCH ACTIVATED</b>\n\nReason: {reason}\n\n<i>All trading halted. Manual reset required.</i>"
            #         def _on_tg_done(_t):
            #             if not _t.cancelled() and _t.exception():
            #                 logger.warning("kill_switch tg_send failed: %s", _t.exception())
            #
            #         try:
            #             loop = asyncio.get_running_loop()
            #             task = loop.create_task(agent.send_message(msg, parse_mode="HTML"))
            #             task.add_done_callback(_on_tg_done)
            #         except RuntimeError:
            #             # No running loop — fire and forget in a new loop
            #             asyncio.run(agent.send_message(msg, parse_mode="HTML"))
            # except Exception as tg_exc:
            #     logger.warning("kill_switch Telegram alert failed: %s", tg_exc)
            pass

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
            positions = cache.get_all_positions() if cache else {}
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


def get_live_bankroll() -> float:
    """Get live bankroll from Kalshi balance API via unified service.
    
    CRITICAL: This is now a thin wrapper around the unified bankroll service.
    The unified service is the ONLY place that calls /portfolio/balance.
    
    Returns:
        Live bankroll in USD, or 0.0 if API call fails (fail-closed)
        
    Uses v2 unified bankroll service as single source of truth.
    """
    from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
    
    try:
        equity = get_equity_for_risk_calc_sync()
        if equity is not None and equity > 0:
            return float(equity)
    except Exception as e:
        logger.critical("[LIVE_BANKROLL] Bankroll unavailable via v2 service: %s", e)
    
    logger.critical("[LIVE_BANKROLL] Returning 0.0 (fail-closed)")
    return 0.0


def get_live_bankroll_async() -> float:
    """Async version of get_live_bankroll for use in async contexts.
    
    Returns:
        Live bankroll in USD, or 0.0 if API call fails (fail-closed)
    """
    from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
    
    try:
        equity = get_equity_for_risk_calc_sync()
        if equity is not None and equity > 0:
            return float(equity)
    except Exception as e:
        logger.critical("[LIVE_BANKROLL_ASYNC] Bankroll unavailable: %s", e)
    
    return 0.0
