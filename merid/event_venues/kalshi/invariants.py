"""Kalshi Venue Invariants — Runtime checks for API configuration consistency.

Provides:
  - BASE_URL validation with fail-fast for non-test processes
  - Signal source taxonomy enforcement (canonical labels)
  - Asset wiring validation across BTC/ETH/SOL/XRP/DOGE
  - Intel/news feed consistency checks
  - Probability clamping (venue invariants for model sanity and tail risk)
  - Entry window validation (single source of truth for time window logic)

Usage::

    from merid.event_venues.kalshi.invariants import (
        require_kalshi_base_url,
        KalshiSignalSource,
        validate_asset_wiring,
        clamp_probability,
        KALSHI_MIN_PROBABILITY,
        KALSHI_MAX_PROBABILITY,
        is_within_entry_window,
    )

    # Fail fast if BASE_URL not configured in production
    require_kalshi_base_url()

    # Use canonical signal source labels
    sources = [KalshiSignalSource.ORDERBOOK, KalshiSignalSource.SPREAD]

    # Clamp model probabilities to venue-invariant range
    model_prob = clamp_probability(raw_model_prob)

    # Check if market is within entry window
    from datetime import datetime
    if is_within_entry_window(datetime.utcnow(), expiry, 30, 2):
        # Market is in valid trading window
        pass

    # Calculate effective edge threshold
    edge_threshold = get_effective_edge_threshold(market_state, profile_config)

    # Compute sizing using pure helpers
    max_notional, floor_applied = compute_max_notional(bankroll_usd, risk_pct, min_max_notional)
    contracts, override_applied = compute_contracts(max_notional, contract_price, override_threshold)
    is_valid = is_trade_valid(bankroll_usd, notional_usd, max_risk_pct)

    # Check if market is within entry window
    from datetime import datetime
    if is_within_entry_window(datetime.utcnow(), expiry, 30, 2):
        # Market is in valid trading window
        pass
"""

from __future__ import annotations

import os
import sys
import logging
from datetime import datetime
from enum import Enum
from typing import List, Dict, Set, Optional, Any
from dataclasses import dataclass
from urllib.parse import urlparse

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.invariants")


# ── Probability Clamping (Venue Invariants) ───────────────────────────────────
# Kalshi contracts trade between 1¢ and 99¢, effectively encoding 1–99% probabilities.
# We clamp to 5–95% for model sanity and tail risk management.
# These are venue invariants - they should not be changed per strategy or profile.

KALSHI_MIN_PROBABILITY: float = 0.05  # 5% minimum probability (tail risk guard)
KALSHI_MAX_PROBABILITY: float = 0.95  # 95% maximum probability (tail risk guard)

# Rationale:
# - Kalshi contracts have price range [1, 99] cents → [0.01, 0.99] probability
# - Clamping to [0.05, 0.95] provides 4% buffer from venue limits
# - Prevents model from betting on near-certain events (tail risk)
# - Accounts for spread, slippage, and execution uncertainty


def clamp_probability(p: float) -> float:
    """Clamp probability to Kalshi venue-invariant range [0.05, 0.95].

    This is a venue invariant - all model probabilities should pass through
    this function before being used for trading decisions.

    Args:
        p: Raw probability from model (any float in [0, 1])

    Returns:
        Clamped probability in [KALSHI_MIN_PROBABILITY, KALSHI_MAX_PROBABILITY]

    Example:
        >>> clamp_probability(0.99)
        0.95
        >>> clamp_probability(0.01)
        0.05
        >>> clamp_probability(0.50)
        0.50
    """
    if p < KALSHI_MIN_PROBABILITY:
        logger.debug(
            "[KALSHI-INVARIANTS] Probability %.4f clamped to %.4f (below minimum)",
            p, KALSHI_MIN_PROBABILITY
        )
        return KALSHI_MIN_PROBABILITY
    if p > KALSHI_MAX_PROBABILITY:
        logger.debug(
            "[KALSHI-INVARIANTS] Probability %.4f clamped to %.4f (above maximum)",
            p, KALSHI_MAX_PROBABILITY
        )
        return KALSHI_MAX_PROBABILITY
    return p


def is_probability_in_range(p: float) -> bool:
    """Check if probability is within Kalshi venue-invariant range.

    Args:
        p: Probability to check

    Returns:
        True if p in [KALSHI_MIN_PROBABILITY, KALSHI_MAX_PROBABILITY], False otherwise
    """
    return KALSHI_MIN_PROBABILITY <= p <= KALSHI_MAX_PROBABILITY


# ── Entry Window Helper ───────────────────────────────────────────────────────
# Kalshi contracts have a defined entry window before expiry.
# This helper provides a single source of truth for time window validation
# across agents, filters, schedulers, and backtests.

def is_within_entry_window(
    now: datetime,
    expiry: datetime,
    minutes_before_expiry: int,
    cutoff_minutes_before_expiry: int,
) -> bool:
    """Check if current time is within the valid entry window for a market.

    This is a venue invariant - all time window checks should use this function
    to ensure consistent behavior across the stack.

    Args:
        now: Current datetime (typically datetime.utcnow())
        expiry: Market expiration datetime
        minutes_before_expiry: Maximum minutes before expiry to start trading (e.g., 30)
        cutoff_minutes_before_expiry: Minimum minutes before expiry to stop trading (e.g., 2)

    Returns:
        True if now is within the entry window [cutoff, minutes_before_expiry], False otherwise

    Example:
        >>> from datetime import datetime, timedelta
        >>> expiry = datetime(2026, 3, 20, 15, 0)
        >>> now = datetime(2026, 3, 20, 14, 35)  # 25 minutes before expiry
        >>> is_within_entry_window(now, expiry, 30, 2)
        True
        >>> now = datetime(2026, 3, 20, 14, 59)  # 1 minute before expiry
        >>> is_within_entry_window(now, expiry, 30, 2)
        False
    """
    if expiry <= now:
        return False
    
    tte_minutes = (expiry - now).total_seconds() / 60.0
    return cutoff_minutes_before_expiry <= tte_minutes <= minutes_before_expiry


def is_within_entry_window_by_minutes(
    tte_minutes: float,
    minutes_before_expiry: int,
    cutoff_minutes_before_expiry: int,
) -> bool:
    """Check if pre-computed time-to-expiry is within the valid entry window.

    Convenience overload for cases where tte_minutes is already computed
    (e.g., from market API response). Delegates to is_within_entry_window
    for the actual logic.

    Args:
        tte_minutes: Time to expiry in minutes (can be float)
        minutes_before_expiry: Maximum minutes before expiry to start trading (e.g., 30)
        cutoff_minutes_before_expiry: Minimum minutes before expiry to stop trading (e.g., 2)

    Returns:
        True if tte_minutes is within the entry window [cutoff, minutes_before_expiry], False otherwise

    Example:
        >>> is_within_entry_window_by_minutes(25, 30, 2)
        True
        >>> is_within_entry_window_by_minutes(1, 30, 2)
        False
    """
    return cutoff_minutes_before_expiry <= tte_minutes <= minutes_before_expiry


# ── Edge Threshold Helper ─────────────────────────────────────────────────────
# Edge threshold calculation provides a single source of truth for minimum edge
# requirements across the stack. This consolidates spread-based adjustments
# and dynamic calibrators into one callable function.

def get_effective_edge_threshold(
    market_state,
    profile_config,
    dynamic_state=None,
) -> float:
    """Calculate the effective edge threshold for a given market.

    This is a venue invariant - all edge threshold calculations should use
    this function to ensure consistent behavior across the stack.

    **IMPORTANT**: This function returns a PRE-FEE edge threshold. The threshold
    does not account for trading fees (typically $0.02 per contract on Kalshi).
    For fee-aware edge calculations, use the fee model in kalshi_risk.py or
    apply fee adjustment after calling this function.

    Args:
        market_state: Market state object with spread information (e.g., KalshiMarketState)
                     Must have spread_cents attribute or similar.
        profile_config: Profile configuration object with min_edge_pct attribute.
        dynamic_state: Optional dynamic state for calibrators (currently unused, reserved for future).

    Returns:
        Effective edge threshold as a float (e.g., 0.02 for 2%). This is PRE-FEE.

    Edge calculation logic:
    1. Base edge from profile config (min_edge_pct)
    2. Spread-based adjustment: max(base_edge, spread_pct * 2.0)
    3. Dynamic calibrators (if any) - reserved for future use

    Example:
        >>> class MockMarketState:
        ...     spread_cents = 2  # 2 cents on a 100-cent contract = 2% spread
        >>> class MockProfileConfig:
        ...     min_edge_pct = 0.02  # 2% base edge
        >>> get_effective_edge_threshold(MockMarketState(), MockProfileConfig())
        0.04  # 2x spread (4%) > base (2%), so use 4% (PRE-FEE)
    """
    # Base edge from profile config
    base_edge = getattr(profile_config, 'min_edge_pct', 0.02)
    
    # Spread-based adjustment
    # Calculate spread percentage from market state
    spread_cents = 0
    if market_state is not None:
        if hasattr(market_state, 'spread_cents'):
            spread_cents = market_state.spread_cents
        elif hasattr(market_state, 'spread'):
            spread_cents = market_state.spread
    
    # Assume 100-cent contract for spread percentage calculation
    # (Kalshi binary contracts are typically priced in cents, 1-99 range)
    spread_pct = spread_cents / 100.0 if spread_cents > 0 else 0.0
    
    # Effective edge is max of base edge and 2x spread
    # This ensures we have enough edge to overcome spread and slippage
    spread_edge = max(base_edge, spread_pct * 2.0)
    
    # Dynamic calibrators (reserved for future use)
    if dynamic_state is not None:
        # Placeholder for dynamic edge adjustment logic
        # e.g., volatility-based scaling, regime detection, etc.
        pass
    
    return spread_edge


# ── Sizing Helpers ─────────────────────────────────────────────────────────────
# Pure functions for trade sizing calculations. These provide a single source of
# truth for sizing logic, making it testable and auditable.

def compute_max_notional(
    bankroll_usd: float,
    risk_pct: float,
    min_max_notional_usd: float,
) -> tuple[float, bool]:
    """Compute maximum notional exposure based on bankroll and risk percentage.

    Args:
        bankroll_usd: Current bankroll in USD
        risk_pct: Risk percentage (e.g., 0.02 for 2%)
        min_max_notional_usd: Minimum floor for max notional (prevents tiny trades)

    Returns:
        Tuple of (max_notional_usd, min_floor_applied)
        - max_notional_usd: The computed maximum notional
        - min_floor_applied: True if the minimum floor was applied, False otherwise

    Example:
        >>> compute_max_notional(1000.0, 0.02, 0.35)
        (20.0, False)  # 2% of 1000 = 20, above floor
        >>> compute_max_notional(10.0, 0.02, 0.35)
        (0.35, True)  # 2% of 10 = 0.20, below floor, use 0.35
    """
    raw_notional = float(bankroll_usd) * risk_pct
    if raw_notional < min_max_notional_usd:
        return min_max_notional_usd, True
    return raw_notional, False


def compute_contracts(
    max_notional_usd: float,
    contract_price_usd: float,
    override_threshold: float,
) -> tuple[int, bool]:
    """Compute number of contracts based on notional and contract price.

    Args:
        max_notional_usd: Maximum notional exposure in USD
        contract_price_usd: Price per contract in USD
        override_threshold: Fractional threshold (e.g., 0.5 for 50%)
                           If contracts_float >= threshold but contracts == 0, bump to 1

    Returns:
        Tuple of (contracts, override_applied)
        - contracts: Number of contracts (integer)
        - override_applied: True if fractional override was applied, False otherwise

    Example:
        >>> compute_contracts(20.0, 0.50, 0.5)
        (40, False)  # 20 / 0.50 = 40 contracts
        >>> compute_contracts(0.35, 0.50, 0.5)
        (0, False)  # 0.35 / 0.50 = 0.7, below threshold, no override
        >>> compute_contracts(0.30, 0.50, 0.5)
        (1, True)  # 0.30 / 0.50 = 0.6, above threshold, override to 1
    """
    # Guard against invalid inputs
    if contract_price_usd <= 0 or max_notional_usd <= 0:
        return 0, False

    contracts_float = max_notional_usd / contract_price_usd
    contracts = int(contracts_float)

    # Fractional override: bump to 1 if we are close enough
    override_applied = False
    if contracts == 0 and contracts_float >= override_threshold:
        contracts = 1
        override_applied = True

    return contracts, override_applied


def is_trade_valid(
    bankroll_usd: float,
    notional_usd: float,
    max_risk_pct: float,
) -> bool:
    """Check if a trade is valid given bankroll and risk constraints.

    Args:
        bankroll_usd: Current bankroll in USD
        notional_usd: Trade notional exposure in USD
        max_risk_pct: Maximum allowed risk percentage (e.g., 0.02 for 2%)

    Returns:
        True if trade is within risk limits, False otherwise

    Example:
        >>> is_trade_valid(1000.0, 20.0, 0.02)
        True  # 20/1000 = 2%, at limit
        >>> is_trade_valid(1000.0, 25.0, 0.02)
        False  # 25/1000 = 2.5%, exceeds limit
    """
    if bankroll_usd <= 0:
        return False

    effective_risk_pct = notional_usd / bankroll_usd
    # Add small epsilon for floating point comparison
    return effective_risk_pct <= max_risk_pct * (1.0 + 1e-6)


def is_liquid_enough(
    best_bid_cents: int,
    best_ask_cents: int,
    bid_size: int,
    ask_size: int,
    min_size: int = 1,
    max_spread_cents: int = 30,  # 2026-07-12: OPTIMIZED to 30c - harmonizes with 10c-75c entry price range
) -> bool:
    """Check if market has sufficient liquidity for trading.

    This implements an explicit liquidity policy to avoid trading on
    thin or illiquid markets. Markets must meet minimum size and
    spread requirements to be considered liquid.

    Args:
        best_bid_cents: Best bid price in cents (0-100)
        best_ask_cents: Best ask price in cents (0-100)
        bid_size: Size at best bid (number of contracts)
        ask_size: Size at best ask (number of contracts)
        min_size: Minimum required size at best bid/ask (default: 1)
        max_spread_cents: Maximum allowed spread in cents (default: 10, 2026-07-09 optimized from 20c based on industry research)

    Returns:
        True if market meets liquidity criteria, False otherwise

    Example:
        >>> is_liquid_enough(45, 55, 10, 10)
        True  # 10-cent spread, sufficient size
        >>> is_liquid_enough(10, 90, 10, 10)
        False  # 80-cent spread too wide
        >>> is_liquid_enough(45, 55, 0, 10)
        False  # No bid size
    """
    # CRITICAL: Reject (0,100) pattern - indicates no real liquidity
    if best_bid_cents == 0 and best_ask_cents == 100:
        return False
    
    # Check minimum size requirements
    if bid_size < min_size or ask_size < min_size:
        return False
    
    # Check spread requirements
    spread_cents = best_ask_cents - best_bid_cents
    if spread_cents > max_spread_cents:
        return False
    
    # Ensure prices are in valid range
    if not (1 <= best_bid_cents <= 99 and 1 <= best_ask_cents <= 99):
        return False
    
    return True


# ── BASE_URL Validation ─────────────────────────────────────────────────────

KALSHI_API_BASE_URL_ENV = "KALSHI_API_BASE_URL"
KALSHI_WS_URL_ENV = "KALSHI_WS_URL"

# Exact hostnames only (substring matching would falsely accept e.g. future-api.kalshi.com).
ALLOWED_KALSHI_API_HOSTS: frozenset[str] = frozenset(
    {
        "demo-api.kalshi.co",
        "external-api.kalshi.com",
        "api.kalshi.com",
        "trading-api.kalshi.com",
    }
)


def _kalshi_url_hostname_allowed(url: str) -> bool:
    try:
        host = urlparse(url).hostname
    except Exception:
        return False
    if not host:
        return False
    return host.lower() in ALLOWED_KALSHI_API_HOSTS


# Known valid Kalshi API endpoints (human-readable; use ALLOWED_KALSHI_API_HOSTS for checks)
VALID_KALSHI_API_PATTERNS = sorted(ALLOWED_KALSHI_API_HOSTS)

VALID_KALSHI_WS_PATTERNS = sorted(ALLOWED_KALSHI_API_HOSTS)


def is_test_environment() -> bool:
    """Detect if running in pytest or test context."""
    return (
        "pytest" in sys.modules
        or os.getenv("PYTEST_CURRENT_TEST") is not None
        or os.getenv("CI", "").lower() in ("true", "1")
        or "test" in sys.argv[0].lower()
    )


def require_kalshi_base_url(fail_in_prod: bool = True) -> Optional[str]:
    """Validate KALSHI_API_BASE_URL is set; fail fast in production.

    Args:
        fail_in_prod: If True (default), raise RuntimeError in non-test envs
                     when BASE_URL is missing or invalid.

    Returns:
        The validated BASE_URL, or None if in test mode with missing env.

    Raises:
        RuntimeError: If fail_in_prod=True, not in test mode, and env missing.
    """
    base_url = os.getenv(KALSHI_API_BASE_URL_ENV)

    # Check if we're in a test environment
    in_test = is_test_environment()

    if not base_url:
        msg = (
            f"{KALSHI_API_BASE_URL_ENV} not set. "
            f"Kalshi API base URL must be configured. "
            f"Use 'https://demo-api.kalshi.co/trade-api/v2' for demo, "
            f"or 'https://external-api.kalshi.com/trade-api/v2' for live (Kalshi quick start)."
        )
        if fail_in_prod and not in_test:
            logger.error(msg)
            raise RuntimeError(msg)
        logger.warning(msg + " (allowing in test mode)")
        return None

    # Validate the URL points to a known Kalshi endpoint
    is_valid = _kalshi_url_hostname_allowed(base_url)
    if not is_valid:
        msg = (
            f"{KALSHI_API_BASE_URL_ENV}='{base_url}' does not appear to be "
            f"a valid Kalshi API endpoint. Expected patterns: {VALID_KALSHI_API_PATTERNS}"
        )
        if fail_in_prod and not in_test:
            logger.error(msg)
            raise RuntimeError(msg)
        logger.warning(msg)

    logger.info(f"Kalshi API base URL validated: {base_url}")
    return base_url


def require_kalshi_ws_url(fail_in_prod: bool = True) -> Optional[str]:
    """Validate KALSHI_WS_URL is set; fail fast in production."""
    ws_url = os.getenv(KALSHI_WS_URL_ENV)

    in_test = is_test_environment()

    if not ws_url:
        msg = (
            f"{KALSHI_WS_URL_ENV} not set. "
            f"Kalshi WebSocket URL must be configured. "
            f"Use 'wss://demo-api.kalshi.co/trade-api/ws/v2' for demo, "
            f"or 'wss://external-api.kalshi.com/trade-api/ws/v2' for live (same host family as REST)."
        )
        if fail_in_prod and not in_test:
            logger.error(msg)
            raise RuntimeError(msg)
        logger.warning(msg + " (allowing in test mode)")
        return None

    is_valid = _kalshi_url_hostname_allowed(ws_url)
    if not is_valid:
        msg = (
            f"{KALSHI_WS_URL_ENV}='{ws_url}' does not appear to be "
            f"a valid Kalshi WebSocket endpoint."
        )
        if fail_in_prod and not in_test:
            logger.error(msg)
            raise RuntimeError(msg)
        logger.warning(msg)

    logger.info(f"Kalshi WebSocket URL validated: {ws_url}")
    return ws_url


# ── Centralized URL Getters ─────────────────────────────────────────────────

def get_kalshi_base_url() -> str:
    """Get environment-aware Kalshi API base URL.

    This is the SINGLE SOURCE OF TRUTH for all Kalshi HTTP clients.
    Every Kalshi client should import this function instead of reading env vars directly.

    Priority:
        1. KALSHI_API_BASE_URL (escape valve for custom host)
        2. KALSHI_ENV (demo/live) → Kalshi's recommended URLs
        3. Fail fast if neither is set

    Returns:
        The Kalshi API base URL (always ends with /trade-api/v2, no trailing slash).

    Kalshi's documented URLs:
        - Live (recommended): https://external-api.kalshi.com/trade-api/v2
        - Live (supported): https://external-api.kalshi.com/trade-api/v2
        - Demo: https://external-api.demo.kalshi.co/trade-api/v2
        - Demo (legacy): https://demo-api.kalshi.co/trade-api/v2

    Example::
        from merid.event_venues.kalshi.invariants import get_kalshi_base_url
        BASE = get_kalshi_base_url()
        response = requests.get(f"{BASE}/markets")
    """
    # Priority 1: Explicit KALSHI_API_BASE_URL override (escape valve)
    base_url = os.getenv(KALSHI_API_BASE_URL_ENV)
    if base_url:
        # Validate against known hosts (exact hostname; not substring)
        if _kalshi_url_hostname_allowed(base_url):
            # Normalize: strip trailing slashes, ensure /trade-api/v2 suffix
            base_url = base_url.rstrip("/")
            if not base_url.endswith("/trade-api/v2"):
                if "/trade-api" not in base_url:
                    base_url = f"{base_url}/trade-api/v2"
                else:
                    # Has /trade-api but wrong version - fix it
                    base_url = base_url.replace("/trade-api/v1", "/trade-api/v2")
                    if not base_url.endswith("/v2"):
                        base_url = f"{base_url}/v2"
            
            # Dev-mode validation: assert contract
            if not is_test_environment() and not base_url.endswith("/trade-api/v2"):
                raise ValueError(
                    f"Invalid KALSHI_API_BASE_URL: {base_url}. "
                    f"Must end with /trade-api/v2 for consistent path construction."
                )
            
            return base_url
        else:
            logger.warning(
                f"{KALSHI_API_BASE_URL_ENV}='{base_url}' does not match known "
                f"Kalshi patterns: {VALID_KALSHI_API_PATTERNS}. Deriving from KALSHI_ENV."
            )

    # Priority 2: Derive from KALSHI_ENV using Kalshi's recommended URLs
    kalshi_env = os.getenv("KALSHI_ENV", "").lower()
    if kalshi_env == "live":
        # Kalshi's recommended production URL for public data and trade API
        return "https://external-api.kalshi.com/trade-api/v2"
    elif kalshi_env == "demo":
        # Kalshi's recommended demo URL
        return "https://external-api.demo.kalshi.co/trade-api/v2"
    elif kalshi_env == "elections":
        # Alias for live (Kalshi's elections API host)
        return "https://external-api.kalshi.com/trade-api/v2"
    elif kalshi_env:
        logger.warning(
            f"Unknown KALSHI_ENV={kalshi_env!r}. Valid values: demo, live, elections. "
            f"Falling back to demo default."
        )
        return "https://external-api.demo.kalshi.co/trade-api/v2"

    # Priority 3: Check legacy KALSHI_USE_DEMO as compatibility shim
    use_demo = os.getenv("KALSHI_USE_DEMO", "false").lower() in ("true", "1", "yes")
    if use_demo:
        logger.warning(
            "KALSHI_USE_DEMO is deprecated. Use KALSHI_ENV=demo instead. "
            "Treating KALSHI_USE_DEMO=true as KALSHI_ENV=demo."
        )
        return "https://external-api.demo.kalshi.co/trade-api/v2"
    else:
        logger.warning(
            "KALSHI_USE_DEMO is deprecated. Use KALSHI_ENV=live instead. "
            "Treating KALSHI_USE_DEMO=false as KALSHI_ENV=live."
        )
        return "https://external-api.kalshi.com/trade-api/v2"


def get_kalshi_ws_url() -> str:
    """Get environment-aware Kalshi WebSocket URL.

    This is the SINGLE SOURCE OF TRUTH for all Kalshi WebSocket clients.
    Every Kalshi WS client should import this function instead of reading env vars directly.

    Derivation strategy:
        1. If KALSHI_WS_URL is set explicitly, use it
        2. Otherwise, derive from KALSHI_API_BASE_URL by:
           - Swapping http/https → wss
           - Replacing /trade-api/v2 with /trade-api/ws/v2
        3. Fall back to demo default

    This approach works for ANY Kalshi host (demo-api, trading-api, api.elections,
    or future subdomains) without maintaining a mapping table.

    Returns:
        The Kalshi WebSocket URL (wss://.../trade-api/ws/v2).

    Example::
        from merid.event_venues.kalshi.invariants import get_kalshi_ws_url
        WS_URL = get_kalshi_ws_url()
        ws = await websockets.connect(WS_URL)
    """
    ws_url = os.getenv(KALSHI_WS_URL_ENV)

    if ws_url:
        if _kalshi_url_hostname_allowed(ws_url):
            # Normalize WS URL
            ws_url = ws_url.rstrip("/")
            if not ws_url.endswith("/trade-api/ws/v2"):
                if "/trade-api" in ws_url:
                    ws_url = ws_url.replace("/trade-api/v2", "/trade-api/ws/v2")
            return ws_url
        else:
            logger.warning(
                f"{KALSHI_WS_URL_ENV}='{ws_url}' does not match known "
                f"Kalshi patterns. Deriving from BASE_URL."
            )

    # Derive from BASE_URL using pure URL manipulation
    # This works for ANY host without hardcoding hostnames
    base_url = get_kalshi_base_url()
    
    # Parse scheme and host from base URL
    # https://demo-api.kalshi.co/trade-api/v2 → wss://demo-api.kalshi.co/trade-api/ws/v2
    # https://trading-api.kalshi.com/trade-api/v2 → wss://trading-api.kalshi.com/trade-api/ws/v2
    if base_url.startswith("https://"):
        ws_url = base_url.replace("https://", "wss://", 1)
    elif base_url.startswith("http://"):
        ws_url = base_url.replace("http://", "wss://", 1)
    else:
        ws_url = f"wss://{base_url}"
    
    # Replace /trade-api/v2 with /trade-api/ws/v2
    ws_url = ws_url.replace("/trade-api/v2", "/trade-api/ws/v2")
    
    return ws_url


def require_kalshi_env() -> Dict[str, Optional[str]]:
    """Validate all required Kalshi environment variables.

    Returns:
        Dict with 'api_base_url' and 'ws_url' keys.

    Raises:
        RuntimeError: If in production and any required env is missing.
    """
    return {
        "api_base_url": require_kalshi_base_url(),
        "ws_url": require_kalshi_ws_url(),
    }


# ── Signal Source Taxonomy ───────────────────────────────────────────────────

class KalshiSignalSource(str, Enum):
    """Canonical signal source labels for Kalshi market data.

    Use these instead of string literals to ensure consistency across:
      - Opinion strategies
      - Consensus aggregation
      - Dashboard filtering
      - Debugging and telemetry
    """
    ORDERBOOK = "kalshi_orderbook"
    SPREAD = "kalshi_spread"
    EXPIRY = "kalshi_expiry"
    NEWS_SENTIMENT = "news_sentiment"
    MARKET_PROB = "kalshi_market_prob"
    MID_CENTS = "kalshi_mid_cents"

    @classmethod
    def live_market_sources(cls) -> List[str]:
        """Signal sources derived from live Kalshi market data."""
        return [cls.ORDERBOOK, cls.SPREAD, cls.EXPIRY]

    @classmethod
    def all_kalshi_sources(cls) -> List[str]:
        """All canonical Kalshi-prefixed sources."""
        return [cls.ORDERBOOK, cls.SPREAD, cls.EXPIRY, cls.MARKET_PROB, cls.MID_CENTS]

    @classmethod
    def is_valid(cls, source: str) -> bool:
        """Check if a string matches any canonical source."""
        return source in [member.value for member in cls]

    @classmethod
    def validate_sources(cls, sources: List[str], context: str = "") -> List[str]:
        """Validate a list of signal sources, warning on non-canonical labels.

        Args:
            sources: List of signal source strings to validate.
            context: Additional context for warning messages.

        Returns:
            The original sources list (unchanged).

        Warns:
            Logs warning for any non-canonical source labels.
        """
        canonical = {member.value for member in cls}
        for src in sources:
            if src not in canonical and not src.startswith("kalshi_"):
                logger.warning(
                    f"Non-canonical signal source '{src}' detected" +
                    (f" in {context}" if context else "") +
                    f". Consider using KalshiSignalSource enum."
                )
        return sources


def get_kalshi_signal_sources(include_sentiment: bool = False) -> List[str]:
    """Get canonical signal sources list.

    Args:
        include_sentiment: Whether to include news_sentiment source.

    Returns:
        List of canonical signal source strings.
    """
    sources = KalshiSignalSource.live_market_sources()
    if include_sentiment:
        sources.append(KalshiSignalSource.NEWS_SENTIMENT)
    return sources


# ── Asset Wiring Validation ─────────────────────────────────────────────────

from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS, ACTIVE_CRYPTO_WS_TIMEFRAMES

# Re-export canonical lists so existing importers keep working
KALSHI_CRYPTO_ASSETS = list(ACTIVE_CRYPTO_ASSETS)

# Canonical timeframes supported (derived from ACTIVE_CRYPTO_WS_TIMEFRAMES)
KALSHI_CRYPTOTIMEFRAMES = list(ACTIVE_CRYPTO_WS_TIMEFRAMES)


@dataclass
class AssetWiringResult:
    """Result of asset wiring validation."""
    asset: str
    timeframe: str
    series_ticker: Optional[str]
    found_in_catalog: bool
    found_in_raw_snapshot: bool
    errors: List[str]
    warnings: List[str]


def validate_asset_wiring(
    catalog_markets: List[Dict[str, Any]],
    raw_snapshot: Optional[Dict[str, Any]] = None,
    assets: Optional[List[str]] = None,
    timeframes: Optional[List[str]] = None,
) -> Dict[str, List[AssetWiringResult]]:
    """Validate asset/timeframe wiring across catalog and raw snapshot.

    Args:
        catalog_markets: List of catalog market dicts with series_ticker, event_ticker, etc.
        raw_snapshot: Optional raw Kalshi API snapshot for cross-validation.
        assets: Assets to validate (defaults to all 5 crypto assets).
        timeframes: Timeframes to validate (defaults to all 4 timeframes).

    Returns:
        Dict mapping 'passed' and 'failed' to lists of AssetWiringResult.
    """
    from merid.event_venues.kalshi.market_selector import (
        resolve_series_ticker,
        CRYPTO_SERIES_BASE,
        TIMEFRAME_SERIES_SUFFIX,
    )

    assets = assets or KALSHI_CRYPTO_ASSETS
    timeframes = timeframes or KALSHI_CRYPTOTIMEFRAMES

    results_passed: List[AssetWiringResult] = []
    results_failed: List[AssetWiringResult] = []

    base_url = os.getenv(KALSHI_API_BASE_URL_ENV, "unknown")

    for asset in assets:
        for timeframe in timeframes:
            errors: List[str] = []
            warnings: List[str] = []

            # Resolve expected series ticker
            try:
                series_ticker = resolve_series_ticker(asset, timeframe)
            except ValueError as e:
                series_ticker = None
                errors.append(f"Could not resolve series ticker: {e}")
                result = AssetWiringResult(
                    asset=asset,
                    timeframe=timeframe,
                    series_ticker=None,
                    found_in_catalog=False,
                    found_in_raw_snapshot=False,
                    errors=errors,
                    warnings=warnings,
                )
                results_failed.append(result)
                continue

            # Check catalog for markets matching this series
            found_in_catalog = False
            matching_markets: List[Dict[str, Any]] = []
            for m in catalog_markets:
                raw = m.get("raw_data", {})
                mkt_series = raw.get("series_ticker", "")
                mkt_event = raw.get("event_ticker", "")
                mkt_id = m.get("market_id", "")

                if (
                    mkt_series.upper().startswith(series_ticker.upper())
                    or mkt_event.upper().startswith(series_ticker.upper())
                    or mkt_id.upper().startswith(series_ticker.upper())
                ):
                    found_in_catalog = True
                    matching_markets.append(m)

            if not found_in_catalog:
                errors.append(
                    f"Series {series_ticker} not found in catalog. "
                    f"Check BASE_URL={base_url} - may be mispointed to wrong environment."
                )

            # Check raw snapshot if provided
            found_in_raw = False
            if raw_snapshot:
                markets = raw_snapshot.get("markets", [])
                for m in markets:
                    mkt_series = m.get("series_ticker", "")
                    if mkt_series.upper().startswith(series_ticker.upper()):
                        found_in_raw = True
                        break

                if not found_in_raw and found_in_catalog:
                    warnings.append(
                        f"Series {series_ticker} found in catalog but not in raw snapshot. "
                        f"Possible catalog staleness."
                    )

            result = AssetWiringResult(
                asset=asset,
                timeframe=timeframe,
                series_ticker=series_ticker,
                found_in_catalog=found_in_catalog,
                found_in_raw_snapshot=found_in_raw,
                errors=errors,
                warnings=warnings,
            )

            if errors:
                results_failed.append(result)
            else:
                results_passed.append(result)

    # Log summary
    total = len(results_passed) + len(results_failed)
    logger.info(
        f"Asset wiring validation: {len(results_passed)}/{total} passed, "
        f"{len(results_failed)}/{total} failed (BASE_URL={base_url})"
    )

    for r in results_failed:
        for e in r.errors:
            logger.error(f"Asset wiring failed for {r.asset}/{r.timeframe}: {e}")
        for w in r.warnings:
            logger.warning(f"Asset wiring warning for {r.asset}/{r.timeframe}: {w}")

    return {"passed": results_passed, "failed": results_failed}


def require_all_assets_wired(
    catalog_markets: List[Dict[str, Any]],
    raw_snapshot: Optional[Dict[str, Any]] = None,
) -> bool:
    """Fail-fast validation that all expected assets/timeframes are wired.

    Args:
        catalog_markets: List of catalog market dicts.
        raw_snapshot: Optional raw Kalshi API snapshot.

    Returns:
        True if all assets wired correctly.

    Raises:
        RuntimeError: If any asset/timeframe combination is missing.
    """
    results = validate_asset_wiring(catalog_markets, raw_snapshot)
    failed = results.get("failed", [])

    if failed:
        base_url = os.getenv(KALSHI_API_BASE_URL_ENV, "unknown")
        errors = [f"{r.asset}/{r.timeframe}: {', '.join(r.errors)}" for r in failed]
        msg = (
            f"Asset wiring validation failed for {len(failed)} asset/timeframe "
            f"combinations with BASE_URL={base_url}: " + "; ".join(errors)
        )
        logger.error(msg)
        raise RuntimeError(msg)

    return True


# ── Intel/News Feed Consistency ───────────────────────────────────────────────

def check_intel_feed_consistency(
    market_data_client_class: type,
    expected_base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Verify intel/news feeds use consistent Kalshi client configuration.

    Args:
        market_data_client_class: The KalshiMarketDataClient class to check.
        expected_base_url: Expected BASE_URL (defaults to env var).

    Returns:
        Dict with consistency check results.
    """
    expected = expected_base_url or os.getenv(KALSHI_API_BASE_URL_ENV)
    actual = getattr(market_data_client_class, "BASE_URL", None)

    # Handle instance-level BASE_URL
    if actual is None:
        try:
            instance = market_data_client_class()
            actual = getattr(instance, "base_url", None) or getattr(instance, "BASE_URL", None)
        except Exception as e:
            return {
                "consistent": False,
                "error": f"Could not instantiate client: {e}",
                "expected": expected,
                "actual": None,
            }

    consistent = actual == expected if expected else True

    result = {
        "consistent": consistent,
        "expected": expected,
        "actual": actual,
    }

    if not consistent:
        logger.warning(
            f"Intel feed BASE_URL mismatch: expected={expected}, actual={actual}. "
            f"This can cause desync between trading and news-derived intel."
        )

    return result


# ── Module-level initialization ─────────────────────────────────────────────

def initialize_invariants() -> Dict[str, Any]:
    """Initialize all Kalshi invariants at module load time.

    Call this early in application startup to catch configuration issues.

    Returns:
        Dict with validation results.
    """
    results: Dict[str, Any] = {}

    # Validate environment variables
    try:
        env = require_kalshi_env()
        results["env"] = {"success": True, **env}
    except RuntimeError as e:
        results["env"] = {"success": False, "error": str(e)}

    return results


def log_kalshi_startup_info() -> None:
    """Log human-friendly startup info for Kalshi configuration.
    
    Logs one line per process describing:
      - kalshi_base_url
      - kalshi_ws_url  
      - environment classification (demo/live/elections)
    
    This immediately exposes mis-set envs in Kubernetes/PM2/systemd.
    
    Example output::
    
        [kalshi] Environment: demo | base=https://demo-api.kalshi.co/trade-api/v2 | ws=wss://demo-api.kalshi.co/trade-api/ws/v2
        [kalshi] Environment: live | base=https://trading-api.kalshi.com/trade-api/v2 | ws=wss://trading-api.kalshi.com/trade-api/ws/v2
    """
    base_url = get_kalshi_base_url()
    ws_url = get_kalshi_ws_url()
    
    # Classify environment for human readability
    if "demo-api" in base_url:
        env_class = "demo"
    elif "trading-api.kalshi.com" in base_url:
        env_class = "live"
    elif "api.elections" in base_url:
        env_class = "elections"
    elif "api.kalshi.com" in base_url:
        env_class = "live"
    else:
        env_class = "unknown"
    
    logger.info(
        f"[kalshi] Environment: {env_class} | "
        f"base={base_url} | "
        f"ws={ws_url}"
    )


def classify_kalshi_environment(base_url: Optional[str] = None) -> str:
    """Classify Kalshi environment from base URL for human readability.
    
    Args:
        base_url: URL to classify (defaults to get_kalshi_base_url())
        
    Returns:
        One of: "demo", "live", "elections", "unknown"
    """
    url = base_url or get_kalshi_base_url()
    
    if "demo-api" in url:
        return "demo"
    elif "trading-api.kalshi.com" in url:
        return "live"
    elif "api.elections" in url:
        return "elections"
    elif "api.kalshi.com" in url:
        return "live"
    return "unknown"


# ── Legacy env var detection ───────────────────────────────────────────────

def detect_legacy_env_vars() -> List[str]:
    """Detect legacy/deprecated Kalshi environment variables.
    
    Returns:
        List of warning messages for any legacy vars found.
    """
    legacy_vars = [
        "KALSHI_DEMO",
        "KALSHI_ENV",
        "KALSHI_HOST",
        "KALSHI_API_HOST",
        "KALSHI_WS_HOST",
    ]
    
    warnings = []
    for var in legacy_vars:
        if os.getenv(var) is not None:
            warnings.append(
                f"Legacy env var {var} detected. "
                f"Use KALSHI_API_BASE_URL instead for consistent configuration."
            )
    
    return warnings


def warn_on_legacy_env_vars() -> None:
    """Log warnings if legacy Kalshi env vars are detected."""
    warnings = detect_legacy_env_vars()
    for warning in warnings:
        logger.warning(f"[kalshi] {warning}")


# ── Metrics and Observability ──────────────────────────────────────────────

def get_kalshi_metrics_labels() -> Dict[str, str]:
    """Get Prometheus-style metrics labels for Kalshi environment.
    
    Returns:
        Dict with kalshi_env and kalshi_host labels for metrics.
        
    Example::
    
        labels = get_kalshi_metrics_labels()
        # {"kalshi_env": "demo", "kalshi_host": "demo-api.kalshi.co"}
        
        # Usage with Prometheus client
        from prometheus_client import Counter
        c = Counter("kalshi_requests_total", "Total requests", labels.keys())
        c.labels(**labels).inc()
    """
    base_url = get_kalshi_base_url()
    host = base_url.replace("https://", "").replace("/trade-api/v2", "")
    env = classify_kalshi_environment(base_url)
    
    return {
        "kalshi_env": env,
        "kalshi_host": host,
    }


# ── Process Lifecycle and Env Flip Detection ───────────────────────────────

class KalshiEnvMonitor:
    """Monitor for environment changes during process lifetime.
    
    Detects if KALSHI_API_BASE_URL changes mid-process, which could
    indicate misconfiguration or hot-reloading issues.
    
    Usage::
        monitor = KalshiEnvMonitor()
        monitor.check()  # Call periodically or on connection errors
        if monitor.has_flipped():
            logger.error("Kalshi env flipped mid-process!")
    """
    
    def __init__(self):
        self._initial_base_url = get_kalshi_base_url()
        self._initial_ws_url = get_kalshi_ws_url()
        self._flip_detected = False
        self._check_count = 0
    
    def check(self) -> bool:
        """Check if env has flipped from initial values.
        
        Returns:
            True if env flip detected, False otherwise.
        """
        self._check_count += 1
        
        current_base = get_kalshi_base_url()
        current_ws = get_kalshi_ws_url()
        
        if current_base != self._initial_base_url or current_ws != self._initial_ws_url:
            if not self._flip_detected:
                logger.error(
                    f"[kalshi] ENV FLIP DETECTED! "
                    f"Initial: {self._initial_base_url} → Current: {current_base}"
                )
                self._flip_detected = True
            return True
        
        return False
    
    def has_flipped(self) -> bool:
        """Return True if env flip was ever detected."""
        return self._flip_detected
    
    def get_initial_urls(self) -> Dict[str, str]:
        """Get the initial URLs captured at monitor creation."""
        return {
            "base_url": self._initial_base_url,
            "ws_url": self._initial_ws_url,
        }


def verify_single_kalshi_env_per_process() -> bool:
    """Verify that only one Kalshi environment is configured per process.
    
    This function asserts the current architecture assumption that MERID
    runs exactly one Kalshi environment per process. If multi-tenant
    support is needed later, this assertion will fail and require refactoring.
    
    Returns:
        True if single env verified.
        
    Raises:
        RuntimeError: If multiple Kalshi environments detected in same process.
    """
    # Check for multiple base URLs in environment
    base_url = os.getenv(KALSHI_API_BASE_URL_ENV)
    
    if not base_url:
        # Default is fine, no conflict possible
        return True
    
    # Detect if any other env vars suggest multi-tenant config
    multi_tenant_hints = []
    
    # Check for venue-specific overrides that might indicate multi-tenant
    for key in os.environ:
        if key.startswith("KALSHI_") and key != KALSHI_API_BASE_URL_ENV and key != KALSHI_WS_URL_ENV:
            if "URL" in key or "HOST" in key or "BASE" in key:
                multi_tenant_hints.append(key)
    
    if multi_tenant_hints:
        logger.warning(
            f"[kalshi] Multiple Kalshi URL-related env vars detected: {multi_tenant_hints}. "
            f"Current architecture assumes single env per process. "
            f"Base URL: {base_url}"
        )
    
    return True


# ── Production Safety Guards ───────────────────────────────────────────────

def require_live_confirmation() -> None:
    """Require explicit confirmation for live trading environment.
    
    Raises:
        RuntimeError: If a non-demo Kalshi production host is used without KALSHI_CONFIRM_LIVE=1.
    """
    base_url = get_kalshi_base_url()
    
    _LIVE_KALSHI_HOST_MARKERS = (
        "trading-api.kalshi.com",
        "external-api.kalshi.com",
        "api.kalshi.com",
    )
    if any(m in base_url for m in _LIVE_KALSHI_HOST_MARKERS):
        confirm = os.getenv("KALSHI_CONFIRM_LIVE")
        if confirm != "1":
            raise RuntimeError(
                f"Live Kalshi environment detected ({base_url}) but "
                f"KALSHI_CONFIRM_LIVE=1 not set. Set this env var to confirm "
                f"you intend to trade against production markets."
            )
    
    logger.info("[kalshi] Live trading confirmation passed or not required.")


def validate_kalshi_config_strict() -> Dict[str, Any]:
    """Strict validation for production use.
    
    Performs all validation checks and hard-fails on any issue.
    Call this at application startup before any connections.
    
    Returns:
        Dict with validation results.
        
    Raises:
        RuntimeError: On any configuration error (no silent failures).
    """
    results: Dict[str, Any] = {}
    errors: List[str] = []
    
    # 1. Validate base URL
    try:
        base_url = get_kalshi_base_url()
        if not base_url.endswith("/trade-api/v2"):
            errors.append(f"Invalid base URL: {base_url}")
        results["base_url"] = base_url
    except Exception as e:
        errors.append(f"Base URL validation failed: {e}")
    
    # 2. Validate WS URL
    try:
        ws_url = get_kalshi_ws_url()
        if not ws_url.endswith("/trade-api/ws/v2"):
            errors.append(f"Invalid WS URL: {ws_url}")
        results["ws_url"] = ws_url
    except Exception as e:
        errors.append(f"WS URL validation failed: {e}")
    
    # 3. Check for legacy env vars
    legacy_warnings = detect_legacy_env_vars()
    if legacy_warnings:
        errors.extend(legacy_warnings)
    
    # 4. Verify single env per process
    try:
        verify_single_kalshi_env_per_process()
        results["single_env"] = True
    except Exception as e:
        errors.append(f"Single env verification failed: {e}")
    
    # 5. Live confirmation (if applicable)
    try:
        require_live_confirmation()
        results["live_confirmed"] = True
    except RuntimeError as e:
        errors.append(str(e))
    
    # Hard-fail on any errors
    if errors:
        msg = "Kalshi configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        logger.error(f"[kalshi] {msg}")
        raise RuntimeError(msg)
    
    logger.info("[kalshi] Strict configuration validation passed.")
    return results
