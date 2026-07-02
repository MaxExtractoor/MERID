"""FifteenMinuteMarketLocator - Time-bucket-based market selection for Kalshi 15m crypto markets.

This module implements a deterministic market selection algorithm that computes the current
15-minute bucket from time and maps directly to expected Kalshi event/market IDs, replacing
the scan-and-filter approach that was causing issues with markets "days out".

CRITICAL DESIGN PRINCIPLES:
- Single active market per asset: Only the current 15-minute bucket is relevant
- Time-bucket → symbol mapping: Direct computation instead of search-and-filter
- Hard gating: Only the current bucket, no future windows or expired windows
- Deterministic: Same time always produces same market IDs

The architecture:
1. Normalize "now" to Kalshi time (UTC)
2. Compute the current 15-minute bucket (floor to 15-minute boundary)
3. Map bucket → Kalshi contract ID using deterministic formatter
4. Only trade that market, ignore all others
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.fifteen_minute_market_locator")

# ET timezone for Kalshi market display
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo
US_EASTERN = ZoneInfo('America/New_York')

# Series tickers for 5 crypto assets
SERIES_BY_ASSET = {
    "BTC": "KXBTC15M",
    "ETH": "KXETH15M",
    "SOL": "KXSOL15M",
    "XRP": "KXXRP15M",
    "DOGE": "KXDOGE15M",
}


@dataclass(frozen=True)
class MarketIds:
    """
    Kalshi market IDs for a single asset in the current 15-minute bucket.
    
    Attributes:
        event_id: The base event ID (e.g., "KXETH15M-26JUN241445")
        yes: Market ID for YES contract (e.g., "KXETH15M-26JUN241445-00")
        no: Market ID for NO contract (e.g., "KXETH15M-26JUN241445-01")
        start: Bucket start time in UTC
        end: Bucket end time in UTC
    """
    event_id: str
    yes: str
    no: str
    start: datetime
    end: datetime


def current_15m_bucket(now_utc: Optional[datetime] = None) -> tuple[datetime, datetime]:
    """
    Compute the current 15-minute bucket from UTC time.
    
    Args:
        now_utc: Current time in UTC (defaults to now if None)
    
    Returns:
        Tuple of (bucket_start, bucket_end) in UTC
    
    Example:
        At 2024-06-24 14:48:xx UTC, returns (14:45, 15:00)
        At 2024-06-24 14:59:xx UTC, returns (14:45, 15:00)
        At 2024-06-24 15:00:xx UTC, returns (15:00, 15:15)
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    
    # Ensure UTC
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    
    # Floor to 15-minute boundary
    minute = (now_utc.minute // 15) * 15
    bucket_start = now_utc.replace(minute=minute, second=0, microsecond=0)
    bucket_end = bucket_start + timedelta(minutes=15)
    
    return bucket_start, bucket_end


def format_kalshi_event(series_prefix: str, bucket_start_utc: datetime) -> str:
    """
    Format a Kalshi event ID from series prefix and bucket start time.
    
    Kalshi 15-minute crypto market IDs follow the pattern:
    - Series prefix: KXBTC15M, KXETH15M, etc.
    - Date/time suffix: DDMMMYYHHMM-MM (based on window END time in ET)
    
    Example from real Kalshi logs:
    - KXBTC15M-26JUN241515-15 (BTC market ending at 15:15 ET)
    
    The event ID is the base without the market type suffix (-00/-01).
    Market IDs are formed by appending -00 (YES) or -01 (NO) to the event ID.
    
    Args:
        series_prefix: Series prefix (e.g., "KXETH15M")
        bucket_start_utc: Bucket start time in UTC
    
    Returns:
        Event ID string (e.g., "KXETH15M-26JUN241445-45")
    """
    # Convert UTC to ET for Kalshi display format
    bucket_end_utc = bucket_start_utc + timedelta(minutes=15)
    bucket_end_et = bucket_end_utc.astimezone(US_EASTERN)
    
    # Format: DDMMMYYHHMM-MM (Kalshi uses window END time with minute offset)
    # Note: The actual pattern from logs is DDMMMYYHHMM-MM where:
    # - DD is day (26)
    # - MMM is month (JUN)
    # - YY is year (24)
    # - HHMM is time (1515)
    # - MM is minute offset (15)
    # CRITICAL: Use 2-digit year from the actual date, not from current time
    date_str = bucket_end_et.strftime("%d%b%y").upper()  # 26JUN24
    time_str = bucket_end_et.strftime("%H%M")  # 1515
    minute_offset = f"{bucket_end_et.minute:02d}"  # 15
    
    return f"{series_prefix}-{date_str}{time_str}-{minute_offset}"


class FifteenMinuteMarketLocator:
    """
    Locator for 15-minute Kalshi crypto markets using time-bucket mapping.
    
    This class replaces the scan-and-filter market selection approach with
    deterministic time-bucket → market ID mapping.
    
    Usage:
        locator = FifteenMinuteMarketLocator(series_by_asset=SERIES_BY_ASSET)
        markets = locator.current_market_ids(now_utc)
        # For each asset:
        #   fetch order book for markets[asset]["yes"] / ["no"]
        #   generate candidates
    """
    
    def __init__(self, series_by_asset: Optional[Dict[str, str]] = None):
        """
        Initialize the market locator.
        
        Args:
            series_by_asset: Mapping of asset names to series tickers.
                           Defaults to the 5 crypto assets (BTC, ETH, SOL, XRP, DOGE).
        """
        self.series_by_asset = series_by_asset or SERIES_BY_ASSET
        logger.info("[MARKET-LOCATOR-INIT] Initialized with %d assets: %s",
                   len(self.series_by_asset), list(self.series_by_asset.keys()))
    
    def current_market_ids(self, now_utc: Optional[datetime] = None) -> Dict[str, MarketIds]:
        """
        Get current market IDs for all assets based on the 15-minute bucket.
        
        Args:
            now_utc: Current time in UTC (defaults to now if None)
    
        Returns:
            Dict mapping asset names to MarketIds objects
        """
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)
        
        # Compute current 15-minute bucket
        bucket_start, bucket_end = current_15m_bucket(now_utc)
        
        # Safety sanity checks
        seconds_since_start = (now_utc - bucket_start).total_seconds()
        seconds_to_end = (bucket_end - now_utc).total_seconds()
        
        if not (0 <= seconds_since_start < 15 * 60):
            logger.warning(
                "[MARKET-LOCATOR] Invalid bucket start check: seconds_since_start=%s",
                seconds_since_start
            )
        
        if not (0 < seconds_to_end <= 15 * 60):
            logger.warning(
                "[MARKET-LOCATOR] Invalid bucket end check: seconds_to_end=%s",
                seconds_to_end
            )
        
        # Build market IDs for each asset
        ids = {}
        for asset, series in self.series_by_asset.items():
            event_id = format_kalshi_event(series, bucket_start)
            ids[asset] = MarketIds(
                event_id=event_id,
                yes=f"{event_id}-00",
                no=f"{event_id}-01",
                start=bucket_start,
                end=bucket_end,
            )
        
        logger.info(
            "[MARKET-LOCATOR] Current bucket: %s - %s (UTC), %d assets",
            bucket_start.strftime("%H:%M"),
            bucket_end.strftime("%H:%M"),
            len(ids)
        )
        
        return ids
    
    def get_market_ids_for_asset(self, asset: str, now_utc: Optional[datetime] = None) -> Optional[MarketIds]:
        """
        Get current market IDs for a specific asset.
        
        Args:
            asset: Asset name (e.g., "BTC")
            now_utc: Current time in UTC (defaults to now if None)
    
        Returns:
            MarketIds object if asset is configured, None otherwise
        """
        all_markets = self.current_market_ids(now_utc)
        return all_markets.get(asset)
    
    def minutes_to_expiry(self, now_utc: Optional[datetime] = None) -> float:
        """
        Compute minutes remaining until current bucket expiry.
        
        Args:
            now_utc: Current time in UTC (defaults to now if None)
    
        Returns:
            Minutes to expiry (0-15 range for current bucket)
        """
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)
        
        bucket_start, bucket_end = current_15m_bucket(now_utc)
        delta = bucket_end - now_utc
        return delta.total_seconds() / 60.0


# Singleton instance for convenience
_default_locator: Optional[FifteenMinuteMarketLocator] = None


def get_market_locator() -> FifteenMinuteMarketLocator:
    """Get the default market locator singleton."""
    global _default_locator
    if _default_locator is None:
        _default_locator = FifteenMinuteMarketLocator()
    return _default_locator
