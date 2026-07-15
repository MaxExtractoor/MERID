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
            logger.debug(f"Cycle drawdown manager unavailable: {e}")
    return _cycle_drawdown_manager


# ── Fee schedule ─────────────────────────────────────────────────────────
# DELEGATED to unified fees module: merid.event_venues.kalshi.fees
# Note: Original signature is (price_cents, contracts), unified is (contracts, price_cents)
from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents

def kalshi_fee_cents(price_cents: int, contracts: int) -> int:
    """Calculate Kalshi fee in cents for a trade.

    DELEGATED to unified fees module: merid.event_venues.kalshi.fees

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
    return calculate_kalshi_fee_cents(contracts, price_cents)


def kalshi_fee_rate(contracts: int) -> float:
    """Return the fee rate for a given contract count.

    DELEGATED to unified fees module: merid.event_venues.kalshi.fees
    """
    from merid.event_venues.kalshi.fees import _get_rate_for_contracts
    return float(_get_rate_for_contracts(contracts))


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
    kelly_fraction: float = 0.02,  # CRITICAL FIX: 2% (aligned with unified risk limit, was 0.05)
    max_contracts: int = 250,
    min_edge: float = 0.02,  # ALIGNED TO 2026 INDUSTRY STANDARD: 2% minimum edge
) -> int:
    """Fee-aware Kelly position sizing for Kalshi binary contracts.

    SENTIMENT ISOLATION (2026-05-15): Removed sentiment_score and volatility_regime parameters.
    For 15m Kalshi crypto profile, sizing is based purely on edge, price, and bankroll.
    No sentiment or regime adjustments applied.

    Kelly fraction f* = (p * b - q) / b
    where:
      p = implied probability + edge
      q = 1 - p
      b = (100 - price - fee_per) / price  (net odds after fees)

    Args:
        edge: Estimated edge (e.g. 0.08 for 8%)
        price_cents: Price per contract in cents (0-99)
        bankroll_cents: Available bankroll in cents
        kelly_fraction: Fraction of full Kelly to use (default quarter-Kelly)
        max_contracts: Hard cap on position size
        min_edge: Minimum edge to trade

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

    # SENTIMENT ISOLATION (2026-05-15): Removed sentiment-based sizing adjustment.
    # For 15m Kalshi crypto profile, sizing is based purely on edge, price, and bankroll.

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
                state = get_kalshi_market_state_store().get_unified(m["ticker"])
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

    For Kalshi 15-minute crypto contracts, prices represent probabilities of YES:
    - Price in cents (0-100) = P(YES) × 100
    - Example: 62 cents = 62% probability of YES
    - Edge = P(YES)_model - P(YES)_market, expressed as percentage

    Positive if the filter says fair price > current price (buy signal).

    Safety checks:
    - Rejects prices outside (0, 100) cents range (probability space)
    - Rejects edges based on unrealistic price differences (>50 cents jump)
    - Logs warnings for rejected inputs
    - PROFILE-GUARD: For kalshi_crypto_15m_v2, validates probability semantics

    Args:
        smoothed_price: Kalman-estimated fair price (cents, must be in 0-100 range representing P(YES))
        current_price: Current market price (cents, must be in 0-100 range representing P(YES))
        fee_cents: Fee per contract in cents (default 0)
        config: Risk config with validation parameters

    Returns:
        Edge as a percentage (e.g. 2.5 means 2.5% edge), or 0 if invalid
    """
    cfg = config or KalshiRiskConfig()

    # PROFILE-GUARD: For kalshi_crypto_15m_v2, enforce probability semantics
    import os
    merid_profile = os.getenv("MERID_PROFILE", "").lower()
    if merid_profile == "kalshi_crypto_15m_v2":
        # Validate that inputs are in probability space (0-100 cents)
        # This prevents accidental use of raw spot prices (e.g., BTC price in USD)
        if not (0 <= smoothed_price <= 100):
            logger.error(
                "[PROFILE-GUARD] edge_from_prediction rejected for kalshi_crypto_15m_v2: "
                "smoothed_price=%.2f is not in probability space (0-100 cents). "
                "This function requires P(YES) in cents, not raw spot prices.",
                smoothed_price
            )
            return 0.0
        if not (0 <= current_price <= 100):
            logger.error(
                "[PROFILE-GUARD] edge_from_prediction rejected for kalshi_crypto_15m_v2: "
                "current_price=%.2f is not in probability space (0-100 cents). "
                "This function requires P(YES) in cents, not raw spot prices.",
                current_price
            )
            return 0.0

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

    # Edge = (P(YES)_model - P(YES)_market - fee) / P(YES)_market
    # This is the correct edge calculation for Kalshi binary contracts
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
    """Exposure limit for a market category.
    
    CRITICAL: max_notional_usd should be derived from live Kalshi balance, not hardcoded.
    Default 0 means "derive from live bankroll" (20% of bankroll per category).
    """
    category: str
    max_notional_usd: float = 0.0  # 0 = derive from live bankroll (was 5000.0 hardcoded)
    max_contracts: int = 500
    max_pct_of_portfolio: float = 0.20  # 20% max in any one category
    enabled: bool = True


@dataclass
class KalshiRiskConfig:
    """Full risk configuration for Kalshi trading.
    
    CRITICAL: max_total_notional_usd should be derived from live Kalshi balance, not hardcoded.
    Default 0 means "derive from live bankroll" (50% of bankroll for total notional).
    
    PROFILE-DRIVEN FIELDS (no defaults - must come from profile):
    - max_fee_to_notional_pct: from risk_policy_max_fee_to_notional_pct
    - min_edge: from strategy_policy_min_edge
    
    NOTE: For profile-driven instantiation, use from_profile() factory method.
    Direct instantiation with defaults is supported for backward compatibility.
    """
    # ── Profile-driven fields (with fallback defaults for compatibility) ─────────
    # Circuit breaker: fee anomaly detection - reject if effective fee > X% of notional
    max_fee_to_notional_pct: float = 15.0  # Default 15% (from profile risk_policy_max_fee_to_notional_pct)
    # Minimum edge to trade - MUST be provided from profile (strategy_policy_min_edge)
    min_edge: float = 0.02  # ALIGNED TO 2026 INDUSTRY STANDARD: 2% (from profile strategy_policy_min_edge)
    # Bankroll cap percentage - from profile venue.bankroll_cap_pct (overrides MERID_BANKROLL_CAP_PCT env)
    # ALIGNED TO 2026 INDUSTRY STANDARD: 1% (from profile venue.bankroll_cap_pct)
    bankroll_cap_pct: float = 0.01  # Default 1% (from profile venue.bankroll_cap_pct)
    
    @classmethod
    def from_profile(cls, profile_data: Dict[str, Any]) -> 'KalshiRiskConfig':
        """
        Factory method to create KalshiRiskConfig from profile data.
        
        This is the recommended way to instantiate KalshiRiskConfig when using
        profile-driven configuration. It ensures profile values are used with
        sensible fallbacks.
        
        Args:
            profile_data: Dictionary containing profile configuration values.
                          Expected keys: risk_policy_max_fee_to_notional_pct,
                                         strategy_policy_min_edge,
                                         venue_bankroll_cap_pct
        
        Returns:
            KalshiRiskConfig instance with profile values applied.
        """
        return cls(
            max_fee_to_notional_pct=profile_data.get('risk_policy_max_fee_to_notional_pct', 15.0),
            min_edge=profile_data.get('strategy_policy_min_edge', 0.05),
            bankroll_cap_pct=profile_data.get('bankroll_cap_pct', 0.02),
        )

    # ── Global limits (with defaults) ────────────────────────────────────────
    min_notional_usd: float = 0.0  # Minimum notional per trade (from profile, 0 = force profile)
    min_contracts: int = 1  # Minimum contracts per trade (venue invariant)
    max_total_notional_usd: float = 0.0  # 0 = derive from live bankroll (was 25000.0 hardcoded)
    max_daily_loss_usd: float = 0.0  # 0 = derive from profile/envelope (was 1000.0 hardcoded)
    max_stop_loss_usd_per_cluster: float = 0.0  # 0 = derive from profile (was 500.0 hardcoded)
    # 2026 STANDARD: Per-asset cluster stop-loss limits
    per_asset_cluster_stop_loss: Dict[str, float] = field(default_factory=dict)
    # CRITICAL FIX (2026-07-07): Increased default from 5 to 10 to allow multi-contract exits
    # Profile config (contract_caps.max_single_order_contracts) takes precedence over this default
    max_single_order_contracts: int = int(os.getenv("KALSHI_MAX_ORDER_CONTRACTS", "10"))  # 10 for production (was 5 - too restrictive for multi-contract exits)
    max_single_order_notional_usd: float = 0.0  # 0 = derive from profile (was 2500.0 hardcoded)
    max_position_per_contract: int = 500  # Kalshi typical retail limit
    # Per-asset max notional caps (from risk envelope with floor applied)
    asset_max_notional_usd: Dict[str, float] = field(default_factory=dict)
    # LEGACY REMOVAL (2026-06-XX): Removed asset_horizon_limits - production stack only trades 15m

    # ── Kelly sizing safety limits ────────────────────────────────────────
    # Hard cap on Kelly fraction f* before frac_of_kelly multiplier
    # NOTE: Now reads from core.settings.KELLY_FRACTION (single source of truth)
    kelly_hard_cap: float = 0.05  # P1-FIX1: TIGHTENED from 0.30 to 0.05 (max 5% of bankroll)
    # Edge clamping: reject edges that are unrealistically large
    kelly_max_edge_pct: float = 25.0  # Max 25% edge (catches data errors)
    kelly_min_edge_pct: float = 1.0   # TIGHTENED from 0.5 to 1.0% edge to trade
    # Win probability clamping
    kelly_min_win_prob: float = 0.01  # Min 1% win probability
    kelly_max_win_prob: float = 0.99  # Max 99% win probability
    # Global Kelly sum cap: sum of all Kelly notionals cannot exceed this fraction of equity
    kelly_global_notional_cap_pct: float = 2.0  # Max 2x equity total exposure

    # ── Circuit breakers ────────────────────────────────────────────────
    # Price jump detection: reject if price is outside normal range
    # Venue invariants - Kalshi binary contract price bounds
    valid_price_cents_min: int = 20  # CRITICAL: Venue invariant (20c min to block deep OTM longshots)
    valid_price_cents_max: int = 99  # Venue invariant (Kalshi max price)
    
    # Dynamic contract caps (populated by _compute_dynamic_contract_caps)
    max_contracts_total: int = 5000
    max_contracts_per_asset: int = 1750  # 35% of 5000 (global fallback)
    max_contracts_per_cluster: int = 750  # 15% of 5000
    
    # Per-asset max contracts from profile (asset-specific overrides)
    # If provided, these override max_contracts_per_asset for specific assets
    per_asset_max_contracts: Dict[str, int] = field(default_factory=dict)

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

    # Post-fee edge (ALIGNED TO 2026 INDUSTRY STANDARD: 2%)
    min_post_fee_edge: float = 0.02  # 2% post-fee edge (industry-aligned)

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
        "crypto": 0.30,  # NOTE: Now reads from core.settings.MAX_CATEGORY_CRYPTO_PCT (single source of truth)
        # LEGACY REMOVAL (2026-06-XX): Removed non-crypto categories (economics, macro, financials, politics, etc.)
        # Production stack only trades 15m crypto markets (BTC, ETH, SOL, XRP, DOGE)
    })
    # Note: correlated_stack_pct is used by CategoryExposureTracker.calibrate_from_balance()
    # as the corr_fraction argument — do NOT remove.
    # CRITICAL: Now reads from core.settings.CORRELATED_STACK_PCT (single source of truth)
    # Increased to 20% to allow trades (was 2% which was too restrictive)
    correlated_stack_pct: float = 0.20      # single underlying across all timeframes

    # ── Group-level exposure limits (per-asset/timeframe/overlap-window) ─────────────────
    group_limits_enabled: bool = True         # Enable group-level aggregation and caps
    group_notional_cap_usd: float = 0.0  # 0 = derive from profile (was 2000.0 hardcoded)

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
                # LEGACY REMOVAL: crypto_threshold_matrix moved to archive/legacy/ during 15m stack cleanup
                # min_notional = get_global_min_order_notional_usd()
                min_notional = None
                if min_notional > 0:
                    # Use min_notional * 10 as minimum functional max_total_notional
                    # This allows at least 10 minimum-sized orders when equity unavailable
                    return min_notional * 10.0
            except Exception:
                pass
            # PRODUCTION FIX (2026-05-01): Final fallback - derive from crypto_threshold_matrix fallback rows
            # Never use hardcoded 0.35 - always source from the same place that defines min_order_notional
            try:
                # LEGACY REMOVAL: crypto_threshold_matrix moved to archive/legacy/ during 15m stack cleanup
                # from merid.prediction.crypto_threshold_matrix import _fallback_rows
                # _fallback = _fallback_rows()
                _fallback = None
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
    # LEGACY REMOVAL (2026-06-XX): Removed asset_horizon_limits field - production stack only trades 15m

    def _compute_dynamic_category_limits(self) -> Dict[str, CategoryLimit]:
        """Compute category limits dynamically from portfolio bankroll.
        
        LEGACY REMOVAL (2026-06-XX): Simplified to only handle crypto category.
        Production stack only trades 15m crypto markets (BTC, ETH, SOL, XRP, DOGE).
        
        PROFILE GATING: If kalshi_crypto_15m_v2 profile is active, use profile-based
        category limits instead of bankroll-derived computation. This ensures balance independence.
        """
        # Check if kalshi_crypto_15m_v2 profile is active
        try:
            from merid.risk.profiles.crypto_15m_profile import is_profile_active, get_active_profile
            if is_profile_active():
                adapter = get_active_profile()
                if adapter is None:
                    raise RuntimeError("MERID_PROFILE=kalshi_crypto_15m_v2 is set but adapter failed to initialize")
                profile_limits = adapter.to_category_limits()
                logger.info(
                    "[CATEGORY-LIMITS-PROFILE] Using profile-based category limits (kalshi_crypto_15m_v2): "
                    f"crypto=${profile_limits['crypto']['max_notional_usd']:.2f}"
                )
                # Log risk config summary
                logger.info(
                    "[RISK-CONFIG] source=kalshi_crypto_15m.yaml global_max_notional=$%.2f category_crypto_max_notional=$%.2f per_asset_enabled=true",
                    profile_limits.get('crypto', {}).get('max_notional_usd', 0),
                    profile_limits.get('crypto', {}).get('max_notional_usd', 0)
                )
                # Convert profile limits to CategoryLimit objects
                limits = {}
                for category, limit_dict in profile_limits.items():
                    # Handle nested dict format for max_contracts
                    max_contracts = limit_dict['max_contracts']
                    if isinstance(max_contracts, dict):
                        max_contracts = max_contracts.get('value', 0)
                    
                    limits[category] = CategoryLimit(
                        category=limit_dict['category'],
                        max_notional_usd=limit_dict['max_notional_usd'],
                        max_contracts=max_contracts,
                        max_pct_of_portfolio=limit_dict['max_pct_of_portfolio'],
                        enabled=limit_dict['enabled']
                    )
                return limits
        except Exception as e:
            raise RuntimeError(
                f"MERID_PROFILE=kalshi_crypto_15m_v2 is active but failed to load profile limits: {e}. "
                "This is a hard error - profile-based risk governance is required when the profile is active."
            )
        
        # LEGACY REMOVAL (2026-06-XX): Removed bankroll-derived computation path
        # Production stack always uses kalshi_crypto_15m_v2 profile
        # If we reach here, it's a configuration error
        raise RuntimeError(
            "kalshi_crypto_15m_v2 profile is not active. "
            "Production stack requires this profile to be active for 15m crypto trading."
        )

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
    asset_contracts: Dict[str, int] = field(default_factory=dict)  # Per-asset contract count
    asset_notional: Dict[str, float] = field(default_factory=dict)  # Per-asset notional USD
    # Group-level exposure tracking (asset-timeframe-overlap window)
    group_notional: Dict[str, float] = field(default_factory=dict)  # group_id -> notional
    group_contracts: Dict[str, int] = field(default_factory=dict)  # group_id -> contracts
    # LEGACY REMOVAL (2026-06-XX): Removed asset_horizon_notional - production stack only trades 15m
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
        
        # CRITICAL FIX: Initialize equity from bankroll service to prevent $0.00 default
        # This fixes the "Equity is $0.00 but contracts=1 > 0" warning
        try:
            from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
            initial_equity = get_equity_for_risk_calc_sync()
            if initial_equity and initial_equity > 0:
                self._state.current_equity_usd = initial_equity
                self._state.peak_equity_usd = initial_equity
                logger.info("[KalshiRiskManager] Initialized with equity=%.2f from bankroll service", initial_equity)
            else:
                logger.warning("[KalshiRiskManager] Bankroll service returned invalid equity=%.2f, using default 0.0", initial_equity)
        except Exception as e:
            logger.warning("[KalshiRiskManager] Failed to initialize equity from bankroll service: %s", e)

        # CRITICAL FIX: Resync asset_notional from actual positions on startup
        # This prevents stale asset_notional values from previous sessions from blocking new orders
        try:
            self.resync_category_contracts_from_positions()
            logger.info("[KalshiRiskManager] Resynced asset_notional from actual positions on startup")
        except Exception as e:
            logger.warning("[KalshiRiskManager] Failed to resync asset_notional on startup: %s", e)

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
            timeframe: Timeframe bucket (15m only for production stack)
            group_id: Canonical group ID for overlap-window risk aggregation
            effective_equity_usd: Optional capped equity for portfolio limits (CT passes this)

        Returns:
            (allowed, reason) — True if order passes all checks
        """
        now = datetime.now(timezone.utc)
        # Normalize group_id to string for consistent key lookup
        gid = str(group_id) if group_id else None
        
        # AUDIT #5: Risk limit check tracking
        logger.info(
            "[RISK-LIMIT-CHECK] ticker=%s category=%s contracts=%d price_cents=%d asset=%s timeframe=%s group_id=%s existing_position=%d effective_equity_usd=%s",
            ticker,
            category,
            contracts,
            price_cents,
            asset,
            timeframe,
            gid,
            existing_position,
            f"{effective_equity_usd:.2f}" if effective_equity_usd else "N/A"
        )
        
        ok, reason, breach_type = self._check_order_locked(
            ticker, category, contracts, price_cents, edge, existing_position, now,
            asset=asset, timeframe=timeframe, group_id=gid,
            effective_equity_usd=effective_equity_usd
        )
        if not ok:
            logger.info(
                "[RISK-LIMIT-CHECK] REJECTED ticker=%s reason=%s breach_type=%s",
                ticker,
                reason,
                breach_type
            )
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
                
                # Drift detection: compare against risk envelope caps
                try:
                    from merid.monitoring.drift_metrics import get_drift_metrics_collector
                    from merid.risk.profiles.risk_envelope_service import get_risk_envelope_service
                    
                    drift_collector = get_drift_metrics_collector()
                    envelope = get_risk_envelope_service().get_config()
                    
                    # Check if approved order exceeds envelope caps
                    envelope_max_total_usd = envelope.max_total_notional_usd
                    envelope_max_single_usd = envelope.max_single_order_notional_usd
                    order_notional_usd = (contracts * price_cents) / 100
                    
                    drift_collector.collect_risk_envelope_drift(
                        envelope_max_notional_usd=envelope_max_total_usd,
                        realized_exposure_usd=_exp,
                        pending_orders_notional_usd=order_notional_usd,
                        epsilon=0.01  # 1% tolerance
                    )
                except Exception as e:
                    logger.debug(f"[DRIFT-METRICS] Failed to collect drift metrics in KalshiRiskManager: {e}")
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
            from merid.event_venues.kalshi.market_catalog import get_market_catalog
            
            # Only check crypto assets on 15m timeframe
            if asset and asset.upper() in ("BTC", "ETH", "SOL", "XRP", "DOGE") and timeframe == "15m":
                # Get market from catalog (should have normalized minutes_to_expiry from STAGE 1)
                catalog = get_market_catalog()
                market = catalog.get_market(ticker)
                
                # CRITICAL FIX: Use normalized minutes_to_expiry from catalog (canonical field)
                # This ensures we use the canonical expiry time from contract_normalization.py
                # which prioritizes close_ts over end_date for 15m contracts
                minutes_to_expiry = None
                if market and hasattr(market, 'minutes_to_expiry') and market.minutes_to_expiry is not None:
                    # Use normalized minutes_to_expiry (canonical field from catalog)
                    minutes_to_expiry = market.minutes_to_expiry
                elif market and hasattr(market, 'end_date') and market.end_date:
                    # Fallback for non-15m or legacy markets (should not happen for 15m crypto)
                    # This is a safety net, but indicates catalog normalization may not be working
                    logger.error(
                        "[RISK-LEGACY-FALLBACK] ticker=%s using end_date fallback (minutes_to_expiry not normalized). "
                        "This indicates catalog normalization may not be working correctly for 15m contracts.",
                        ticker
                    )
                    minutes_to_expiry = (market.end_date - now).total_seconds() / 60.0
                
                if minutes_to_expiry is not None:
                    edge_pct = edge * 100  # Convert decimal to percentage
                    
                    resolution = resolve_entry_window(
                        asset=asset,
                        minutes_to_expiry=minutes_to_expiry,
                        edge_pct=edge_pct,
                        ticker=ticker
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
            # Defensive: normalize max_single_order_contracts to handle dict format
            max_single_order = self._config.max_single_order_contracts
            if isinstance(max_single_order, dict):
                # Accept typical shapes: {"max_contracts": 500} or {"value": 500}
                if "max_contracts" in max_single_order:
                    max_single_order = max_single_order["max_contracts"]
                elif "value" in max_single_order:
                    max_single_order = max_single_order["value"]
                else:
                    logger.error(
                        "[RISK] Malformed max_single_order_contracts dict: %s; using default 1",
                        max_single_order,
                    )
                    max_single_order = 1
            if not isinstance(max_single_order, int):
                logger.warning(
                    "[RISK] Invalid max_single_order_contracts type (%r); using default 1",
                    max_single_order,
                )
                max_single_order = 1
            if contracts > max_single_order:
                reason = f"Order size {contracts} exceeds max {max_single_order}"
                self._log_breach("max_single_order_contracts", reason)
                return False, reason, "max_single_order_contracts"

            notional_usd = contracts * price_cents / 100.0
            logger.info("[RISK-NOTIONAL-CALC] ticker=%s contracts=%d price_cents=%d notional_usd=%.2f", ticker, contracts, price_cents, notional_usd)
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

            # 3b. Per-asset contract limit (from profile overrides)
            # 2026-07-09: DISABLED - global allocator handles allocation at grid level
            # The global allocator at agent grid level now manages edge-based allocation under venue cap
            # Per-asset contract limits are no longer enforced here to allow best edges to use available venue cap
            # if asset and self._config.per_asset_max_contracts:
            #     asset_key = asset.upper()
            #     if asset_key in self._config.per_asset_max_contracts:
            #         per_asset_cap = self._config.per_asset_max_contracts[asset_key]
            #         # Defensive: normalize per_asset_cap to handle dict format
            #         if isinstance(per_asset_cap, dict):
            #             # Accept typical shapes: {"max_contracts": 500} or {"value": 500}
            #             if "max_contracts" in per_asset_cap:
            #                 per_asset_cap = per_asset_cap["max_contracts"]
            #             elif "value" in per_asset_cap:
            #                 per_asset_cap = per_asset_cap["value"]
            #             else:
            #                 logger.error(
            #                     "[RISK] Malformed per_asset_max_contracts[%s] dict: %s; skipping per-asset cap check",
            #                     asset_key, per_asset_cap
            #                 )
            #                 per_asset_cap = None
            #         
            #         # If still not an int, skip the check for safety
            #         if not isinstance(per_asset_cap, int):
            #             logger.warning(
            #                 "[RISK] per_asset_max_contracts[%s] is not an int after normalization (type=%s, value=%s). Skipping per-asset cap check.",
            #                 asset_key, type(per_asset_cap), per_asset_cap
            #             )
            #         else:
            #             # Get current asset position from state
            #             asset_contracts = self._state.asset_contracts.get(asset_key, 0)
            #             new_asset_contracts = asset_contracts + contracts
            #             if new_asset_contracts > per_asset_cap:
            #                 reason = f"Asset '{asset_key}' contracts {new_asset_contracts} exceeds profile cap {per_asset_cap}"
            #                 self._log_breach("per_asset_contracts_cap", reason)
            #                 return False, reason, "per_asset_contracts_cap"

            # 3c. Per-asset notional cap (from RiskEnvelope with floor applied)
            # 2026-07-09: DISABLED - global allocator handles allocation at grid level
            # The global allocator at agent grid level now manages edge-based allocation under venue cap
            # Per-asset caps are no longer enforced here to allow best edges to use available venue cap
            # CRITICAL FIX (2026-06-27): Use asset_notional instead of category_notional proxy
            # This ensures per-asset exposure limits are correctly tracked per asset (BTC, ETH, etc.)
            # if asset and self._config.asset_max_notional_usd:
            #     asset_key = asset.upper()
            #     if asset_key in self._config.asset_max_notional_usd:
            #         asset_cap = self._config.asset_max_notional_usd[asset_key]
            #         if asset_cap > 0:
            #             # Get current asset notional from state (sum of all positions for this specific asset)
            #             current_asset_notional = self._state.asset_notional.get(asset_key, 0.0)
            #             new_asset_notional = current_asset_notional + notional_usd
            #             if new_asset_notional > asset_cap:
            #                 reason = f"Asset '{asset_key}' notional ${new_asset_notional:.2f} exceeds cap ${asset_cap:.2f}"
            #                 self._log_breach("asset_notional_cap", reason)
            #                 return False, reason, "asset_notional_cap"

            # 4. Category exposure (legacy — keep for backward compatibility)
            # FIX (2026-05-11): Skip category cap for crypto since it's the only category being traded
            # (BTC, ETH, SOL, XRP, DOGE on 15m timeframe). The category cap was blocking all trades
            # due to stale positions exceeding the cap on small accounts.
            # FIX (2026-05-27): Robust handling of malformed max_contracts (dict vs int)
            # FIX (2026-06-XX): RE-ENABLE crypto category cap enforcement - the skip was preventing proper risk control
            # Category cap should be enforced for all categories including crypto
            if category and category in self._config.category_limits:
                cat_limit = self._config.category_limits[category]
                if cat_limit.enabled:
                    cat_notional = self._state.category_notional.get(category, 0.0) + notional_usd
                    # ZERO-FIX: Skip if max_notional_usd is 0 (meaning derive from bankroll)
                    if cat_limit.max_notional_usd > 0 and cat_notional > cat_limit.max_notional_usd:
                        reason = f"Category '{category}' notional ${cat_notional:.2f} exceeds cap ${cat_limit.max_notional_usd:.2f}"
                        self._log_breach("category_notional_cap", reason)
                        return False, reason, "category_notional_cap"

                    cat_contracts = self._state.category_contracts.get(category, 0) + contracts
                    # Robust: normalize max_contracts to handle both int and dict formats
                    raw_max_contracts = getattr(cat_limit, "max_contracts", None)
                    
                    # If we somehow have a dict here, normalize it
                    if isinstance(raw_max_contracts, dict):
                        # Accept typical shapes: {"max_contracts": 500} or {"value": 500}
                        if "max_contracts" in raw_max_contracts:
                            raw_max_contracts = raw_max_contracts["max_contracts"]
                        elif "value" in raw_max_contracts:
                            raw_max_contracts = raw_max_contracts["value"]
                        else:
                            logger.error(
                                "[CATEGORY-LIMIT] Malformed max_contracts dict for category %s: %s; disabling category limit",
                                category,
                                raw_max_contracts,
                            )
                            raw_max_contracts = None
                    
                    # If still not an int, disable the limit for safety
                    if not isinstance(raw_max_contracts, int):
                        logger.warning(
                            "[CATEGORY-LIMIT] Invalid max_contracts type for category %s (%r); skipping category limit check",
                            category,
                            raw_max_contracts,
                        )
                    else:
                        if cat_contracts > raw_max_contracts:
                            reason = f"Category '{category}' contracts {cat_contracts} exceeds cap {raw_max_contracts}"
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
                if not isinstance(gid, str):
                    raise TypeError(f"group_id must normalize to str, got {type(gid)}")
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
                
                # LEGACY REMOVAL (2026-06-XX): Removed per-asset/timeframe cap check
                # Production stack only trades 15m timeframe, so asset_horizon_limits is not needed
                # Group-level caps (group_notional_cap_usd) provide sufficient risk control
                
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

            # Check bankroll cap
            if total > global_bankroll_cap_usd:
                logger.warning(
                    "[RISK-CHECK-BANKROLL] bankroll=%.2f cap_pct=%.4f cap=%.2f order_notional=%.2f result=REJECT ticker=%s",
                    bankroll_cents / 100.0, cap_pct, global_bankroll_cap_usd, total, ticker
                )
                return False, f"BANKROLL_CAP_EXCEEDED: ${total:.2f} > ${global_bankroll_cap_usd:.2f}", "bankroll_cap"

            logger.info(
                "[RISK-CHECK-BANKROLL] bankroll=%.2f cap_pct=%.4f cap=%.2f order_notional=%.2f result=PASS ticker=%s",
                bankroll_cents / 100.0, cap_pct, global_bankroll_cap_usd, total, ticker
            )

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
                try:
                    allocator = get_crypto15m_allocator()
                    if allocator.config.rollout_phase == "hard_gate":
                        logger.warning(f"[TFBUDGET] Check failed in hard_gate mode: {exc}")
                    else:
                        logger.debug(f"[TFBUDGET] Check failed (fail-open in {allocator.config.rollout_phase}): {exc}")
                except Exception:
                    # If allocator is unavailable, just log the exception
                    logger.debug(f"[TFBUDGET] Check failed (allocator unavailable): {exc}")

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
                try:
                    allocator = get_crypto15m_allocator()
                    if allocator.config.rollout_phase == "hard_gate":
                        logger.warning(f"[EXPIRYLIMIT] Check failed in hard_gate mode: {exc}")
                    else:
                        logger.debug(f"[EXPIRYLIMIT] Check failed (fail-open in {allocator.config.rollout_phase}): {exc}")
                except Exception:
                    # If allocator is unavailable, just log the exception
                    logger.debug(f"[EXPIRYLIMIT] Check failed (allocator unavailable): {exc}")

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
        
        # Track per-asset notional (for 5 crypto assets: BTC, ETH, SOL, XRP, DOGE)
        if asset:
            asset_key = asset.upper()
            self._state.asset_notional[asset_key] = (
                self._state.asset_notional.get(asset_key, 0.0) + notional
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

        # LEGACY REMOVAL (2026-06-XX): Removed asset/timeframe horizon tracking - production stack only trades 15m

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
        
        # Decrement per-asset notional on position close
        if asset:
            asset_key = asset.upper()
            self._state.asset_notional[asset_key] = max(
                0.0,
                self._state.asset_notional.get(asset_key, 0.0) - notional,
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

        # LEGACY REMOVAL (2026-06-XX): Removed asset/timeframe horizon tracking - production stack only trades 15m

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

    def reset_asset_notional(self) -> None:
        """Reset asset_notional to zero (emergency fix for incorrect accumulation)."""
        logger.warning(
            "EMERGENCY RESET: Clearing asset_notional state - was %s",
            {k: round(v, 2) for k, v in self._state.asset_notional.items()}
        )
        self._state.asset_notional.clear()
        self._state.asset_contracts.clear()
        logger.info("Asset notional reset complete - will be recalculated on next resync")

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
            old_asset_notional = dict(self._state.asset_notional)
            self._state.category_contracts.clear()
            self._state.category_notional.clear()
            self._state.asset_notional.clear()
            
            # Get computed net positions from fills_ledger (filters out manually closed positions)
            # Use 24-hour filter to exclude stale positions from previous sessions
            computed_positions = ledger.compute_net_positions(since_hours=24)
            
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
            
            # Recalculate asset_notional from actual positions (for 5 crypto assets)
            # CRITICAL FIX (2026-06-28): Cross-reference with position_cache to avoid stale fills_ledger data
            # Position cache is the source of truth for current open positions
            try:
                from config.kalshi_crypto_config import kalshi_ticker_to_asset
                from merid.event_venues.kalshi.position_cache import get_position_cache
                
                position_cache = get_position_cache()
                cache_positions = position_cache.get_all_positions()
                
                # Build set of assets that have open positions in position cache
                assets_with_positions = set()
                for market_id, pos in cache_positions.items():
                    asset = kalshi_ticker_to_asset(market_id)
                    if asset and asset.upper() in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
                        if pos.contracts != 0:
                            assets_with_positions.add(asset.upper())
                
                logger.debug("[ASSET-NOTIONAL-RESYNC] Assets with open positions in cache: %s", assets_with_positions)
                
                for ticker, pos in computed_positions.items():
                    contracts = pos.get("contracts", 0)
                    if contracts == 0:
                        continue
                    asset = kalshi_ticker_to_asset(ticker)
                    if asset and asset.upper() in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
                        asset_key = asset.upper()
                        # Only add notional if asset has open positions in position cache
                        if asset_key not in assets_with_positions:
                            logger.debug(
                                "[ASSET-NOTIONAL-RESYNC] Skipping %s (asset=%s) - no open position in cache",
                                ticker, asset_key
                            )
                            continue
                        avg_price_cents = pos.get("avg_price_cents", DEFAULT_KALSHI_PRICE_CENTS)
                        notional = abs(contracts) * avg_price_cents / 100.0
                        self._state.asset_notional[asset_key] = notional
                        logger.debug(
                            "[ASSET-NOTIONAL-DEBUG] %s | asset=%s | contracts=%d | notional=$%.2f",
                            ticker, asset_key, contracts, notional
                        )
            except Exception as e:
                logger.warning("[ASSET-NOTIONAL-RESYNC] Failed to resync asset_notional: %s", e)
            
            # Log the resync results (debug level - only useful for troubleshooting)
            # Normalize comparison to treat missing keys as zero (no data loss, just empty categories)
            all_contract_keys = set(old_contracts.keys()) | set(self._state.category_contracts.keys())
            all_notional_keys = set(old_notional.keys()) | set(self._state.category_notional.keys())
            all_asset_notional_keys = set(old_asset_notional.keys()) | set(self._state.asset_notional.keys())
            
            normalized_old_contracts = {k: old_contracts.get(k, 0) for k in all_contract_keys}
            normalized_new_contracts = {k: self._state.category_contracts.get(k, 0) for k in all_contract_keys}
            normalized_old_notional = {k: round(old_notional.get(k, 0.0), 2) for k in all_notional_keys}
            normalized_new_notional = {k: round(self._state.category_notional.get(k, 0.0), 2) for k in all_notional_keys}
            normalized_old_asset_notional = {k: round(old_asset_notional.get(k, 0.0), 2) for k in all_asset_notional_keys}
            normalized_new_asset_notional = {k: round(self._state.asset_notional.get(k, 0.0), 2) for k in all_asset_notional_keys}
            
            logger.debug(
                "CATEGORY_RESYNC contracts: old=%s new=%s total_positions=%d positions_with_contracts=%d | notional: old=%s new=%s | asset_notional: old=%s new=%s",
                normalized_old_contracts,
                normalized_new_contracts,
                len(computed_positions),
                positions_with_contracts,
                normalized_old_notional,
                normalized_new_notional,
                normalized_old_asset_notional,
                normalized_new_asset_notional
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
        # LEGACY REMOVAL (2026-06-XX): Removed asset_horizon_notional.clear() - field removed
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
        
        # SKIP BankrollServiceV2 during order submission to prevent blocking
        # Use cached equity (Source 2) instead for real-time order checks
        # BankrollServiceV2 is used for background updates, not for time-critical order paths
        
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
        """Derive bankroll cap percentage from config or environment.

        Priority order:
        1. self._config.bankroll_cap_pct (from profile venue.bankroll_cap_pct)
        2. MERID_BANKROLL_CAP_PCT env var (fallback)
        
        Clamps to safe range [1%, 5%] (increased from 2% to allow profile-driven 5%).
        Default is 2% if not configured.

        Returns:
            Cap percentage as fraction (e.g., 0.02 for 2% max)
        """
        # Source 1: Profile config (highest priority)
        if hasattr(self._config, 'bankroll_cap_pct') and self._config.bankroll_cap_pct > 0:
            raw_pct = self._config.bankroll_cap_pct * 100.0  # Convert fraction to percentage
            source = "profile_config"
        else:
            # Source 2: Environment variable (fallback)
            try:
                raw_pct = float(os.getenv("MERID_BANKROLL_CAP_PCT", "2.0"))
                source = "env_var"
            except (ValueError, TypeError):
                raw_pct = 2.0
                source = "env_var_default"

        # Clamp to safe range: 1% minimum, 5% maximum (increased from 2% for profile flexibility)
        clamped_pct = max(1.0, min(5.0, raw_pct))

        if clamped_pct != raw_pct:
            logger.warning(
                "[BANKROLL_CAP_PCT_CLAMP] value %.2f%% from %s clamped to %.2f%% (safe range 1%%-5%%)",
                raw_pct, source, clamped_pct
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

        PROFILE GATING: When kalshi_crypto_15m_v2 profile is active, this method
        returns static values from the profile instead of computing dynamic values
        based on bankroll. This ensures contract caps are config-only for 15m crypto.

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
        # PROFILE GATING: Return static profile values for kalshi_crypto_15m_v2
        # MARKET-AWARE: Calculate per-asset caps based on actual assets with markets in catalog
        try:
            from merid.risk.profiles.crypto_15m_profile import is_profile_active, get_active_profile
            if is_profile_active():
                adapter = get_active_profile()
                if adapter:
                    profile = adapter.profile
                    # Get actual assets with markets from catalog for market-aware risk caps
                    from merid.event_venues.kalshi.market_catalog import get_market_catalog
                    catalog = get_market_catalog()
                    assets_with_markets = set()
                    for cm in catalog.get_all_markets():
                        if cm.asset:
                            assets_with_markets.add(cm.asset.upper())
                    
                    # Use actual asset count, default to 3 if catalog empty (fallback)
                    asset_count = max(len(assets_with_markets), 3)
                    cluster_count = max(asset_count // 2, 2)  # Clusters are half of assets, min 2
                    
                    # Calculate market-aware per-asset and per-cluster caps
                    max_notional_per_asset = profile.venue_max_total_notional_usd / asset_count
                    max_notional_per_cluster = profile.venue_max_total_notional_usd / cluster_count
                    
                    logger.info(
                        "[MARKET-AWARE-RISK] asset_count=%d cluster_count=%d max_notional_per_asset=%.2f max_notional_per_cluster=%.2f",
                        asset_count,
                        cluster_count,
                        max_notional_per_asset,
                        max_notional_per_cluster,
                    )
                    
                    # Return market-aware values from profile
                    return (
                        profile.venue_max_total_notional_usd,  # max_notional_usd_total
                        max_notional_per_asset,  # market-aware per-asset cap
                        max_notional_per_cluster,  # market-aware per-cluster cap
                        5000,  # max_contracts_total (fixed from profile)
                        1750 // max(3, asset_count),  # max_contracts_per_asset (scaled by asset count)
                        750 // max(2, cluster_count),  # max_contracts_per_cluster (scaled by cluster count)
                        "PROFILE_STATIC_MARKET_AWARE",  # regime
                        1.0,  # ratio (static)
                    )
        except ImportError:
            # Profile module not available, proceed with legacy behavior
            pass

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

        PROFILE GATING: When kalshi_crypto_15m_v2 profile is active, this method
        syncs category limits from RiskEnvelope instead of computing from balance.
        The RiskEnvelope is the single source of truth for bankroll-derived values.
        """
        # PROFILE GATING: For kalshi_crypto_15m_v2 profile, sync from RiskEnvelope
        # instead of computing from balance directly
        try:
            from merid.risk.profiles.crypto_15m_profile import is_profile_active
            if is_profile_active():
                # Sync category limits from RiskEnvelope (single source of truth)
                try:
                    from merid.risk.profiles.risk_envelope_service import get_risk_envelope_service
                    service = get_risk_envelope_service()
                    service.refresh_if_stale(max_age_seconds=30.0)
                    config = service.get_config()
                    
                    # Update category limits from envelope
                    # The envelope computes category max_notional from live bankroll
                    with self._lock:
                        if "crypto" in self._config.category_limits:
                            # For crypto, use the envelope's asset_max_notional_usd sum as category cap
                            # This ensures category cap tracks the sum of per-asset caps
                            total_asset_cap = sum(config.asset_max_notional_usd.values()) if config.asset_max_notional_usd else 0.0
                            if total_asset_cap > 0:
                                self._config.category_limits["crypto"].max_notional_usd = total_asset_cap
                                logger.debug(
                                    "[KalshiRiskConfig] calibrate_from_balance() synced crypto category cap from RiskEnvelope: $%.2f",
                                    total_asset_cap
                                )
                except Exception as e:
                    logger.warning("[KalshiRiskConfig] Failed to sync category limits from RiskEnvelope: %s", e)
                return
        except ImportError:
            # Profile module not available, proceed with legacy behavior
            pass

        if balance_cents <= 0:
            return
        balance_usd = balance_cents / 100.0
        cfg = self._config

        # Load bankroll from bankroll_service_v2 for dynamic daily loss computation
        # CRITICAL FIX: Skip bankroll access during import time to prevent bankroll service initialization
        # This method is called during module import, before bankroll service is ready
        # Defer to runtime - will be updated during startup after bankroll service is ready
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

            # 2026 STANDARD: Load per-asset cluster stop-loss limits from profile
            risk_policy = profile_data.get('risk_policy', {})
            per_asset_sl = risk_policy.get('per_asset_cluster_stop_loss', {})
            if per_asset_sl:
                cfg.per_asset_cluster_stop_loss = per_asset_sl
                logger.info(
                    "kalshirisk per-asset-cluster-sl loaded: %s assets", len(per_asset_sl)
                )

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

        2026 STANDARD: Use per-asset cluster stop-loss limits instead of aggregate.
        Each asset (BTC/ETH/SOL/XRP/DOGE) has calibrated limits based on volatility/liquidity.

        Args:
            cluster_id: Cluster identifier (asset-timeframe)
            order_worst_case_loss_usd: Worst-case loss for candidate order

        Returns:
            Tuple of (allowed, reason, cluster_loss_usd, post_cluster_loss_usd)
        """
        cluster_unrealized_loss_usd = self._compute_cluster_unrealized_loss_usd(cluster_id)
        
        # 2026 STANDARD: Extract asset from cluster_id and use per-asset limits
        asset = self._extract_asset_from_cluster_id(cluster_id)
        per_asset_limits = getattr(self._config, 'per_asset_cluster_stop_loss', {})
        max_stop_loss_usd_per_cluster = per_asset_limits.get(asset, self._config.max_stop_loss_usd_per_cluster)
        
        # Fallback to aggregate limit if per-asset not configured
        if max_stop_loss_usd_per_cluster == 0.0:
            max_stop_loss_usd_per_cluster = self._config.max_stop_loss_usd_per_cluster

        # Compute post-order cluster loss
        post_cluster_loss = cluster_unrealized_loss_usd + order_worst_case_loss_usd

        logger.info(
            "kalshirisk stop-loss-check "
            "cluster=%s asset=%s "
            "cluster_loss=%.2f max_cluster_stop=%.2f "
            "order_worst=%.2f post_cluster_loss=%.2f",
            cluster_id,
            asset,
            cluster_unrealized_loss_usd,
            max_stop_loss_usd_per_cluster,
            order_worst_case_loss_usd,
            post_cluster_loss,
        )

        # Reject if cluster stop loss would be breached
        if post_cluster_loss > max_stop_loss_usd_per_cluster:
            return (False, f"CLUSTER_STOP_LOSS: ${post_cluster_loss:.2f} > ${max_stop_loss_usd_per_cluster:.2f} (asset={asset})", cluster_unrealized_loss_usd, post_cluster_loss)

        return (True, "OK", cluster_unrealized_loss_usd, post_cluster_loss)

    def _extract_asset_from_cluster_id(self, cluster_id: str) -> str:
        """Extract asset symbol from cluster_id (e.g., 'SOL' from 'SOL-15m')."""
        # Cluster_id format: {ASSET}-{timeframe} (e.g., SOL-15m, BTC-15m)
        parts = cluster_id.split("-")
        if parts:
            asset = parts[0].upper()
            return asset
        return "UNKNOWN"

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
    """Get or create the singleton KalshiRiskManager.
    
    PROFILE WIRING: When MERID_PROFILE=kalshi_crypto_15m_v2 is active,
    applies profile-based risk configuration from kalshi_crypto_15m.yaml.
    """
    global _risk
    logger.info("[PROFILE_WIRING] get_kalshi_risk() called, _risk is None: %s", _risk is None)
    if _risk is None:
        with _risk_lock:
            if _risk is None:
                logger.info("[PROFILE_WIRING] Acquired lock, checking _risk again")
                # Check if profile is active and apply profile config
                config = None
                import os
                profile_name = os.environ.get('MERID_PROFILE', '').strip()
                logger.info("[PROFILE_WIRING] MERID_PROFILE environment variable: '%s'", profile_name)
                try:
                    from merid.risk.profiles.crypto_15m_profile import is_profile_active, get_active_profile
                    is_active = is_profile_active()
                    logger.info("[PROFILE_WIRING] is_profile_active() returned: %s", is_active)
                    if is_active:
                        adapter = get_active_profile()
                        if adapter:
                            profile_config_dict = adapter.to_kalshi_risk_config()
                            # Create KalshiRiskConfig from profile values
                            logger.info(
                                "[PROFILE_WIRING] Profile config bankroll_cap_pct: %.4f",
                                profile_config_dict.get('bankroll_cap_pct', 'NOT_FOUND')
                            )
                            config = KalshiRiskConfig(**profile_config_dict)
                            logger.info(
                                "[PROFILE_WIRING] Applied kalshi_crypto_15m_v2 profile to KalshiRiskConfig: "
                                "max_single_order_notional_usd=%.2f, max_total_notional_usd=%.2f, bankroll_cap_pct=%.4f",
                                config.max_single_order_notional_usd,
                                config.max_total_notional_usd,
                                config.bankroll_cap_pct
                            )
                except ImportError:
                    # Profile module not available, use default config
                    pass
                except Exception as e:
                    logger.warning("[PROFILE_WIRING] Failed to apply profile config: %s. Using default config.", e)
                
                _risk = KalshiRiskManager(config=config)
                # CRITICAL FIX: Reset asset_notional on startup to clear stale exposure data from previous sessions
                _risk.reset_asset_notional()
    return _risk


def get_live_bankroll() -> float:
    """Get live bankroll from Kalshi balance API via unified service.
    
    CRITICAL: This is now a thin wrapper around the unified bankroll service.
    The unified service is the ONLY place that calls /portfolio/balance.
    
    Returns:
        Live bankroll in USD, or 0.0 if API call fails (fail-closed)
        
    Uses v2 unified bankroll service as single source of truth.
    """
    try:
        # CRITICAL FIX: Make bankroll access lazy to prevent import-time bankroll service initialization
        from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
        equity = get_equity_for_risk_calc_sync()
    except Exception as bankroll_exc:
        logger.warning(f"[LIVE-BANKROLL] Bankroll service unavailable during initialization: {bankroll_exc}")
        equity = None
    
    try:
        if equity is not None and equity > 0:
            return float(equity)
    except Exception as e:
        logger.critical("[LIVE_BANKROLL] Bankroll unavailable via v2 service: %s", e)
    
    # CRITICAL FIX: Return 0.0 only after startup is complete (bankroll service initialized)
    # During import time, log debug instead of critical to avoid noise
    import os
    from merid.event_venues.kalshi.bankroll_service_v2 import _BANKROLL_SERVICE_V2
    if _BANKROLL_SERVICE_V2 is None:
        logger.debug("[LIVE_BANKROLL] Bankroll service not initialized (import time) - returning 0.0")
    else:
        logger.critical("[LIVE_BANKROLL] Returning 0.0 (fail-closed)")
    return 0.0


def get_live_bankroll_async() -> float:
    """Async version of get_live_bankroll for use in async contexts.
    
    Returns:
        Live bankroll in USD, or 0.0 if API call fails (fail-closed)
    """
    # CRITICAL FIX: Skip bankroll access during import time to prevent bankroll service initialization
    # This function should only be called at runtime after bankroll service is ready
    logger.warning("[LIVE-BANKROLL-ASYNC] Skipping import-time bankroll fetch, will defer to runtime")
    return 0.0
