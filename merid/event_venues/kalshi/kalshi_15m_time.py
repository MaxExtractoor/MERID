"""Shared time helper for Kalshi 15-minute crypto markets.

This module centralizes all time calculations and window logic
for Kalshi 15-minute crypto markets to ensure consistency across the
entire Kalshi venue layer.

CRITICAL TIME CONTRACT:
- Source of truth: Kalshi contract times are in Eastern Time (America/New_York)
- Internal clock: System runs in UTC, but ticker suffixes, expiry minutes, 
  and 15m buckets operate in ET with conversion at the edges
- Ticker suffixes use UTC (YYMMMDDHHMM-MM format) for API compatibility
- All window calculations (entry, trading, cutoff) use ET

The single source of truth for 15-minute market selection is the ET window helper.
All components (catalog, scheduler, agents) must use get_kalshi_15m_window().
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.kalshi_15m_time")

# 15-minute boundaries (UTC for ticker suffixes)
_MINUTE_BOUNDARIES = [0, 15, 30, 45]

# ET timezone
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo
ET = ZoneInfo('America/New_York')


@dataclass(frozen=True)
class ETWindow:
    """
    Represents a 15-minute ET window with start/end in Eastern Time.
    
    This is the canonical representation of a 15-minute market window
    for Kalshi 15-minute crypto markets based on ET trading hours.
    
    Attributes:
        start_et: Window start time in Eastern Time
        end_et: Window end time in Eastern Time
        start_utc: Window start time in UTC (for ticker suffix computation)
        end_utc: Window end time in UTC
        suffix: Ticker suffix in format YYMMMDDHHMM-MM (based on UTC start)
        minutes_to_expiry: Minutes remaining until window expiry (from now_utc)
    """
    start_et: datetime
    end_et: datetime
    start_utc: datetime
    end_utc: datetime
    suffix: str
    minutes_to_expiry: float
    
    def is_open(self, now_utc: Optional[datetime] = None) -> bool:
        """Check if the current time is within this window.
        
        Args:
            now_utc: Current time in UTC (defaults to now if None)
        
        Returns:
            True if start_utc <= now < end_utc
        """
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)
        return self.start_utc <= now_utc < self.end_utc


@dataclass(frozen=True)
class UTCWindow:
    """
    Represents a 15-minute UTC window with start/end in UTC.
    
    This is the canonical representation of a 15-minute market window
    for Kalshi 15-minute crypto markets based on UTC ticker formatting.
    
    Attributes:
        start_utc: Window start time in UTC
        end_utc: Window end time in UTC
        suffix: Ticker suffix in format YYMMMDDHHMM-MM (based on UTC start)
    """
    start_utc: datetime
    end_utc: datetime
    suffix: str
    
    def is_open(self, now_utc: Optional[datetime] = None) -> bool:
        """Check if the current time is within this window.
        
        Args:
            now_utc: Current time in UTC (defaults to now if None)
        
        Returns:
            True if start_utc <= now < end_utc
        """
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)
        return self.start_utc <= now_utc < self.end_utc
    
    def minutes_to_expiry(self, now_utc: Optional[datetime] = None) -> float:
        """
        Compute minutes remaining until window expiry.
        
        Args:
            now_utc: Current time in UTC (defaults to now if None)
        
        Returns:
            Minutes to expiry (can be negative if already expired)
        """
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)
        
        delta = self.end_utc - now_utc
        return delta.total_seconds() / 60.0


def _format_suffix(dt_utc: datetime) -> str:
    """
    Format a UTC datetime as a Kalshi ticker suffix.
    
    Format: YYMMMDDHHMM-MM (e.g., 26JUN111145-45)
    - YY: Year (2 digits)
    - MMM: Month (3-letter uppercase)
    - DD: Day (2 digits)
    - HHMM: Time in 24-hour format UTC
    - MM: Minute offset within 15-min window (00, 15, 30, 45)
    
    Args:
        dt_utc: Datetime in UTC (caller must pass the correct time - start or end)
    
    Returns:
        Ticker suffix string for the given datetime
    """
    year = dt_utc.strftime("%y")
    month = dt_utc.strftime("%b").upper()
    day = dt_utc.strftime("%d")
    time_hhmm = dt_utc.strftime("%H%M")
    minute_offset = f"{dt_utc.minute:02d}"
    
    return f"{year}{month}{day}{time_hhmm}-{minute_offset}"


def get_current_utc_window(now_utc: Optional[datetime] = None) -> UTCWindow:
    """
    Get the current 15-minute UTC window for a given UTC timestamp.
    
    This is used for ticker suffix computation since Kalshi tickers use UTC.
    
    Args:
        now_utc: Current time in UTC (defaults to now if None)
    
    Returns:
        UTCWindow struct for the current window
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    
    # Ensure UTC
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    
    # Find the current 15-minute boundary in UTC
    minute = now_utc.minute
    for boundary in reversed(_MINUTE_BOUNDARIES):
        if minute >= boundary:
            start_utc = now_utc.replace(minute=boundary, second=0, microsecond=0)
            break
    else:
        # No boundary in current hour, go to previous hour
        prev_hour = (now_utc - timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        start_utc = prev_hour.replace(minute=_MINUTE_BOUNDARIES[-1])
    
    end_utc = start_utc + timedelta(minutes=15)
    
    # Format suffix based on UTC start time
    suffix = _format_suffix(start_utc)
    
    return UTCWindow(
        start_utc=start_utc,
        end_utc=end_utc,
        suffix=suffix
    )


def get_next_utc_window(now_utc: Optional[datetime] = None) -> UTCWindow:
    """
    Get the next 15-minute UTC window after a given UTC timestamp.
    
    Args:
        now_utc: Current time in UTC (defaults to now if None)
    
    Returns:
        UTCWindow struct for the next window
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    
    # Ensure UTC
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    
    # Find the next 15-minute boundary in UTC
    minute = now_utc.minute
    for boundary in _MINUTE_BOUNDARIES:
        if minute < boundary:
            start_utc = now_utc.replace(minute=boundary, second=0, microsecond=0)
            break
    else:
        # No boundary in current hour, go to next hour
        next_hour = (now_utc + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        start_utc = next_hour.replace(minute=_MINUTE_BOUNDARIES[0])
    
    end_utc = start_utc + timedelta(minutes=15)
    
    # Format suffix based on UTC start time
    suffix = _format_suffix(start_utc)
    
    return UTCWindow(
        start_utc=start_utc,
        end_utc=end_utc,
        suffix=suffix
    )


def get_previous_utc_window(now_utc: Optional[datetime] = None) -> UTCWindow:
    """
    Get the previous 15-minute UTC window before a given UTC timestamp.
    
    Args:
        now_utc: Current time in UTC (defaults to now if None)
    
    Returns:
        UTCWindow struct for the previous window
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    
    # Ensure UTC
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    
    # Get current window first
    current_window = get_current_utc_window(now_utc)
    
    # Previous window is 15 minutes before current window start
    start_utc = current_window.start_utc - timedelta(minutes=15)
    end_utc = start_utc + timedelta(minutes=15)
    
    # Format suffix based on UTC start time
    suffix = _format_suffix(start_utc)
    
    return UTCWindow(
        start_utc=start_utc,
        end_utc=end_utc,
        suffix=suffix
    )


def get_kalshi_15m_window(now_utc: Optional[datetime] = None) -> ETWindow:
    """
    Get the current 15-minute ET window for Kalshi 15-minute crypto markets.
    
    This is the SINGLE SOURCE OF TRUTH for 15-minute market selection across
    the entire stack (catalog, scheduler, agents). All components must use this
    helper to ensure consistent window calculation.
    
    The function:
    1. Converts now_utc to ET
    2. Floors to 15-minute boundary in ET
    3. Computes window start/end in both ET and UTC
    4. Generates ticker suffix based on UTC start time
    5. Computes minutes to expiry
    
    Args:
        now_utc: Current time in UTC (defaults to now if None)
    
    Returns:
        ETWindow struct with ET/UTC times, suffix, and minutes_to_expiry
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    
    # CRITICAL FIX: Validate now_utc is reasonable (not extreme future/past)
    year = now_utc.year
    if year < 2020 or year > 2100:
        logger.warning(
            "[GET-15M-WINDOW] Invalid now_utc year=%s - using current time",
            year
        )
        now_utc = datetime.now(timezone.utc)
    
    # Ensure UTC
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    
    # Convert to ET
    now_et = now_utc.astimezone(ET)
    
    # Find the current 15-minute boundary in ET
    # CRITICAL FIX: Use `>` instead of `>=` to handle boundary minutes correctly
    # At exactly 12:15 ET, we should be in the 12:00-12:15 window (ending at 12:15),
    # not the 12:15-12:30 window (starting at 12:15)
    minute = now_et.minute
    for boundary in reversed(_MINUTE_BOUNDARIES):
        if minute > boundary:
            start_et = now_et.replace(minute=boundary, second=0, microsecond=0)
            break
    else:
        # No boundary in current hour, go to previous hour
        prev_hour = (now_et - timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        start_et = prev_hour.replace(minute=_MINUTE_BOUNDARIES[-1])
    
    end_et = start_et + timedelta(minutes=15)
    
    # Convert back to UTC for ticker suffix computation
    start_utc = start_et.astimezone(timezone.utc)
    end_utc = end_et.astimezone(timezone.utc)
    
    # Format suffix based on ET end time
    # CRITICAL FIX: Kalshi ticker suffixes use ET, not UTC
    # Evidence: Ticker 26JUN271445-45 (14:45) expires at 18:45:00 UTC = 14:45 ET (EDT is UTC-4)
    suffix = _format_suffix(end_et)
    
    # Compute minutes to expiry
    delta = end_utc - now_utc
    minutes_to_expiry = delta.total_seconds() / 60.0
    
    # CRITICAL FIX: If the current window has expired, advance to the next window
    # This happens when we're at a boundary minute (e.g., 15:15 ET) and the
    # > comparison keeps us in the expired window
    if minutes_to_expiry <= 0:
        # Advance to next 15-minute window
        start_et = start_et + timedelta(minutes=15)
        end_et = start_et + timedelta(minutes=15)
        start_utc = start_et.astimezone(timezone.utc)
        end_utc = end_et.astimezone(timezone.utc)
        suffix = _format_suffix(end_et)
        delta = end_utc - now_utc
        minutes_to_expiry = delta.total_seconds() / 60.0
        logger.debug(
            "[GET-15M-WINDOW] Current window expired (mte=%.1f), advanced to next window: %s to %s",
            delta.total_seconds() / 60.0, start_et, end_et
        )
    
    return ETWindow(
        start_et=start_et,
        end_et=end_et,
        start_utc=start_utc,
        end_utc=end_utc,
        suffix=suffix,
        minutes_to_expiry=minutes_to_expiry
    )


def compute_minutes_to_expiry(expiry_time: datetime, now: Optional[datetime] = None) -> float:
    """
    Compute minutes to expiry for a market.
    
    Args:
        expiry_time: Market expiry time (UTC)
        now: Current time (defaults to now if None)
    
    Returns:
        Minutes to expiry (can be negative if already expired)
    """
    if now is None:
        now = datetime.now(timezone.utc)
    
    # Ensure both times are UTC
    if expiry_time.tzinfo is None:
        expiry_time = expiry_time.replace(tzinfo=timezone.utc)
    elif expiry_time.tzinfo != timezone.utc:
        # Convert to UTC
        expiry_time = expiry_time.astimezone(timezone.utc)
    
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    
    # Compute minutes to expiry
    seconds_to_expiry = (expiry_time - now).total_seconds()
    return seconds_to_expiry / 60.0


def utc_to_et(utc_dt: datetime) -> datetime:
    """Convert UTC datetime to Eastern Time (for trading hours)."""
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    return utc_dt.astimezone(ET)


def et_to_utc(et_dt: datetime) -> datetime:
    """Convert Eastern Time datetime to UTC (for trading hours)."""
    if et_dt.tzinfo is None:
        # Assume ET if no timezone info
        et_dt = ET.localize(et_dt)
    return et_dt.astimezone(timezone.utc)


def is_tradeable(
    expiry_time: datetime,
    now_utc: Optional[datetime] = None,
    health_status: str = "ok",
) -> bool:
    """
    Determine if a market is tradeable (strategy-level check).
    
    CRITICAL REFACTOR: This is now for STRATEGY gating only, not catalog visibility.
    Catalog visibility uses select_live_markets_by_ts() instead.
    
    Strategy-level criteria:
    - Market is not expired (minutes_to_expiry > 0)
    - Market is within entry window (2-12 minutes to expiry)
    - Health status is acceptable (ok or expired for visibility)
    
    Args:
        expiry_time: Market expiry time (UTC)
        now_utc: Current time in UTC (defaults to now if None)
        health_status: Health status from normalization ("ok", "expired", "invalid_metadata")
    
    Returns:
        True if tradeable for strategy, False otherwise
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    
    # Ensure UTC
    if expiry_time.tzinfo is None:
        expiry_time = expiry_time.replace(tzinfo=timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    
    # Strategy-level checks
    not_expired = expiry_time > now_utc
    minutes_to_expiry = (expiry_time - now_utc).total_seconds() / 60
    within_entry_window = 2.0 <= minutes_to_expiry <= 12.0  # Entry window
    health_acceptable = health_status in {"ok", "expired"}  # Relaxed
    
    return not_expired and within_entry_window and health_acceptable


def is_market_live(
    expiry_time: datetime,
    now_utc: Optional[datetime] = None,
    health_status: str = "ok",
    max_window_min: Optional[float] = None,
) -> bool:
    """Determine if a market is LIVE for DATA / visibility purposes.

    DECOUPLED from entry-timing. This controls catalog visibility and WS
    subscription ONLY. It deliberately does NOT encode the entry window
    (e.g. 2-12 min). Entry timing is enforced independently and authoritatively
    by ``agent_grid_15m.check_autonomous_gate`` (profile guardrails
    ``min_entry_mins``/``max_entry_mins``) plus ``MIN_TIME_TO_EXPIRY_FOR_ENTRY_MIN``.

    Previously the catalog computed its ``tradeable`` flag from
    :func:`is_tradeable` (the 2-12 min entry window). That conflated a
    market-data concern with a trading-timing concern, so during minutes
    12-15 and 0-2 of every cycle the catalog reported "no markets", the WS
    forwarder unsubscribed (``desired_tickers=0``), MD went stale, and the
    loop tripped ``HALT_CRITICAL``. Keeping markets visible for the full
    ~15-minute window keeps market data flowing for entries, exits, and
    monitoring while the agent grid still gates *when* an entry may fire.

    A market is "live" if it is not expired, its metadata is healthy, and it
    falls inside the current ~15-minute Kalshi window.

    Args:
        expiry_time: Market expiry time (UTC)
        now_utc: Current time in UTC (defaults to now if None)
        health_status: Health status from normalization ("ok"/"expired"/"invalid_metadata")
        max_window_min: Upper bound on minutes-to-expiry for visibility. Defaults to
            env ``MERID_KALSHI_15M_DATA_WINDOW_MIN`` (15.5), giving a small margin
            above the 15-minute window for clock skew at window open.

    Returns:
        True if the market should be visible / subscribed, False otherwise.
    """
    import os

    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    # Ensure UTC
    if expiry_time.tzinfo is None:
        expiry_time = expiry_time.replace(tzinfo=timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    if max_window_min is None:
        try:
            max_window_min = float(os.getenv("MERID_KALSHI_15M_DATA_WINDOW_MIN", "15.5"))
        except (TypeError, ValueError):
            max_window_min = 15.5

    minutes_to_expiry = (expiry_time - now_utc).total_seconds() / 60
    within_data_window = 0 < minutes_to_expiry <= max_window_min
    health_acceptable = health_status in {"ok", "expired"}

    return within_data_window and health_acceptable


def select_live_markets_by_ts(
    markets: List[Any],
    min_minutes_to_expiry: float = 0.5,
    max_minutes_to_expiry: float = 15.0,
    now_utc: Optional[datetime] = None,
    require_exactly_one_per_asset: bool = False,
) -> List[Any]:
    """
    Canonical market selection using Kalshi's open_time and close_time.
    
    CRITICAL: Uses actual open_time from Kalshi API, NOT computed open_time.
    
    Selection criteria:
    - Uses open_time and close_time from Kalshi API (authoritative)
    - Market is "live" if: open_time <= now_utc < close_time
    - Market is "tradeable" if: min_minutes_to_expiry <= mte <= max_minutes_to_expiry
    - Defaults to 0.5-15 minute entry window (configurable, relaxed from 2.0 to allow full window trading)
    
    Args:
        markets: List of market objects (CatalogMarket or EventMarket)
        min_minutes_to_expiry: Minimum minutes to expiry (default 0.5 for entry window, relaxed from 2.0)
        max_minutes_to_expiry: Maximum minutes to expiry (default 15.0 for entry window)
        now_utc: Current time in UTC (defaults to now if None)
        require_exactly_one_per_asset: If True, raise error if >1 live market per asset
    
    Returns:
        List of markets that are currently live and within entry window
    
    Raises:
        ValueError: If require_exactly_one_per_asset=True and multiple live markets exist for an asset
    """
    # CRITICAL FIX: Validate min/max parameters are reasonable
    if min_minutes_to_expiry < 0 or max_minutes_to_expiry < 0:
        logger.warning(
            "[SELECT-LIVE] Invalid min=%s max=%s - using defaults 2.0/15.0",
            min_minutes_to_expiry, max_minutes_to_expiry
        )
        min_minutes_to_expiry = 2.0
        max_minutes_to_expiry = 15.0
    if min_minutes_to_expiry > max_minutes_to_expiry:
        logger.warning(
            "[SELECT-LIVE] min > max (%s > %s) - swapping values",
            min_minutes_to_expiry, max_minutes_to_expiry
        )
        min_minutes_to_expiry, max_minutes_to_expiry = max_minutes_to_expiry, min_minutes_to_expiry
    
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    
    live_markets = []
    markets_by_asset = {}
    
    logger.debug("[SELECT-LIVE] Input markets count=%d", len(markets))
    
    for market in markets:
        # Extract open_time and close_time from market object
        # Priority: market.open_time > market.market.open_time > computed from close_time
        open_time = None
        close_time = None
        
        if hasattr(market, 'open_time') and market.open_time:
            open_time = market.open_time
        elif hasattr(market, 'market') and hasattr(market.market, 'open_time') and market.market.open_time:
            open_time = market.market.open_time
        
        if hasattr(market, 'close_time') and market.close_time:
            close_time = market.close_time
        elif hasattr(market, 'expires_at') and market.expires_at:
            close_time = market.expires_at
        elif hasattr(market, 'market') and hasattr(market.market, 'close_time') and market.market.close_time:
            close_time = market.market.close_time
        elif hasattr(market, 'market') and hasattr(market.market, 'end_date') and market.market.end_date:
            close_time = market.market.end_date
        
        # TEMPORARY: Kalshi API doesn't provide open_time for 15m crypto markets
        # Assume market is live if it has a valid close_time and is within entry window
        if close_time is None:
            logger.warning(
                "[SELECT-LIVE] Skipping market=%s (missing close_time) - has close_time attr=%s",
                getattr(market, 'market_id', 'unknown'), hasattr(market, 'close_time')
            )
            continue
        
        # If open_time is missing, we'll skip the "is_live" check and rely on entry window only
        # This is a temporary workaround until Kalshi API provides open_time
        if open_time is None:
            logger.debug(
                "[SELECT-LIVE] market=%s missing open_time - will use entry window check only",
                getattr(market, 'market_id', 'unknown')
            )
        
        # Ensure UTC
        if open_time is not None and open_time.tzinfo is None:
            open_time = open_time.replace(tzinfo=timezone.utc)
        if close_time.tzinfo is None:
            close_time = close_time.replace(tzinfo=timezone.utc)
        
        # Check if market is currently live (Kalshi's trading window)
        # If open_time is missing, assume market is live and rely on entry window check
        if open_time is not None:
            is_live = open_time <= now_utc < close_time
        else:
            is_live = True  # Assume live if open_time not available
        
        # Check if within entry window
        minutes_to_expiry = (close_time - now_utc).total_seconds() / 60.0
        # CRITICAL FIX: Validate minutes_to_expiry is reasonable (not NaN or extreme)
        if not (-1000 <= minutes_to_expiry <= 10000):
            logger.warning(
                "[SELECT-LIVE] Skipping market=%s extreme minutes_to_expiry=%s",
                getattr(market, 'market_id', 'unknown'), minutes_to_expiry
            )
            continue
        within_entry_window = min_minutes_to_expiry <= minutes_to_expiry <= max_minutes_to_expiry
        
        if is_live and within_entry_window:
            live_markets.append(market)
            
            # Track by asset for exactly-one invariant check
            asset = getattr(market, 'asset', None)
            if asset:
                markets_by_asset.setdefault(asset, []).append(market)
    
    # Safety check: exactly one live market per asset
    if require_exactly_one_per_asset:
        for asset, asset_markets in markets_by_asset.items():
            if len(asset_markets) > 1:
                market_ids = [getattr(m, 'market_id', 'unknown') for m in asset_markets]
                raise ValueError(
                    f"DATA INTEGRITY ERROR: {len(asset_markets)} live markets for asset={asset}. "
                    f"Expected exactly 1. Market IDs: {market_ids}. "
                    f"This indicates overlapping trading windows or duplicate catalog entries."
                )
    
    return live_markets


async def get_kalshi_server_time() -> Optional[datetime]:
    """Fetch current server time from Kalshi API for clock skew detection.
    
    Returns:
        Server time in UTC if available, None otherwise
    """
    try:
        from merid.event_venues.kalshi.client import KalshiVenueClient
        client = KalshiVenueClient()
        
        # Kalshi GET /markets endpoint returns server time in response headers
        # Or use a dedicated time endpoint if available
        response = await client._session.get(
            f"{client.base_url}/markets",
            headers=client._get_headers()
        )
        
        # Check for Date header or custom server-time header
        server_time_str = response.headers.get("Date") or response.headers.get("X-Server-Time")
        if server_time_str:
            # Parse HTTP date format
            from email.utils import parsedate_to_datetime
            server_time = parsedate_to_datetime(server_time_str)
            if server_time.tzinfo is None:
                server_time = server_time.replace(tzinfo=timezone.utc)
            return server_time
    except Exception as e:
        logger.warning("[KALSHI-TIME] Failed to fetch server time: %s", e)
    
    return None


def detect_time_skew(max_allowed_seconds: float = 5.0) -> Dict[str, Any]:
    """Detect clock skew between local system and Kalshi server.
    
    Args:
        max_allowed_seconds: Maximum allowed skew in seconds (default 5.0)
    
    Returns:
        Dict with local time, server time, skew, and whether skew is acceptable
    """
    now_utc = datetime.now(timezone.utc)
    
    # This would be called async in practice
    # For now, return placeholder - actual async call needed in production
    return {
        "local_time": now_utc.isoformat(),
        "server_time": None,  # Would be populated by async call to get_kalshi_server_time()
        "skew_seconds": None,
        "skew_acceptable": True,
        "max_allowed_seconds": max_allowed_seconds
    }
