"""
Kalshi 15-minute crypto market scheduler.

CRITICAL: This module now uses the shared ET time helper (kalshi_15m_time)
to ensure consistency across the entire Kalshi venue layer.

Kalshi 15m contracts roll every 15 minutes at :00, :15, :30, :45 ET (Eastern Time).
All window calculations are delegated to the shared helper to prevent drift.

This module provides:
- Prediction of next/previous market windows (via shared helper)
- Computation of minutes_to_expiry from market expiry time (via shared helper)
- Validation of 2-12 minute trading window (via shared helper)
"""

from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple
from dataclasses import dataclass
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.crypto_15m_scheduler")


@dataclass
class MarketWindow:
    """
    Represents a 15-minute market window.
    
    This is a thin wrapper around the shared ETWindow struct from kalshi_15m_time.
    It maintains backward compatibility with existing code while delegating
    to the shared helper for all time calculations.
    """
    start_utc: datetime  # When the market opens
    expiry_utc: datetime  # When the market expires
    ticker: str  # Expected ticker format (e.g., KXBTC15M-26MAY240045-45)
    
    @property
    def minutes_to_expiry(self) -> float:
        """Compute minutes remaining until expiry."""
        now = datetime.now(timezone.utc)
        delta = self.expiry_utc - now
        return max(0.0, delta.total_seconds() / 60.0)
    
    @property
    def is_open(self) -> bool:
        """Check if market is currently open (start <= now < expiry)."""
        now = datetime.now(timezone.utc)
        return self.start_utc <= now < self.expiry_utc
    
    def is_in_trading_window(self, min_minutes: int = 2, max_minutes: int = 12) -> bool:
        """Check if market is within the 2-12 minute trading window."""
        mte = self.minutes_to_expiry
        return min_minutes <= mte <= max_minutes


class Crypto15mScheduler:
    """
    Scheduler for 15-minute crypto markets on Kalshi.
    
    CRITICAL: All ET window calculations are delegated to the shared helper
    (kalshi_15m_time) to ensure consistency with market_catalog and other
    Kalshi venue components.
    """
    
    def __init__(self):
        self._cache: dict = {}  # series_ticker -> MarketWindow
    
    def _format_ticker(self, series_ticker: str, start_et: datetime) -> str:
        """
        Format expected ticker for a market window.
        
        Kalshi ticker format: KXBTCD-26APR22H12-T60000
        - Series: KXBTCD (canonical format for daily crypto)
        - Date: 26APR22 (YYMMMDD)
        - Time: H12 (hour-quarter in ET) - THIS IS THE START TIME IN ET, NOT UTC
        - Strike: T60000 (threshold price)
        
        CRITICAL: Kalshi uses ET for ticker formatting, not UTC.
        For 15m contracts, ticker has ET start time (e.g., H12 for 12:00 ET).
        """
        date_str = start_et.strftime("%y%b%d").upper()
        # Format hour-quarter: H00, H15, H30, H45
        hour_quarter = f"H{start_et.strftime('%H%M')}"
        # For 15m markets, we need to construct the full ticker with threshold
        # The actual threshold comes from the market data, not predicted
        # For now, return a format that matches the series
        return f"{series_ticker}-{date_str}{hour_quarter}"
    
    def get_current_window(self, series_ticker: str, catalog_ticker: Optional[str] = None) -> Optional[MarketWindow]:
        """
        Get the currently open market window for a series.
        
        CRITICAL: This now uses the shared ET helper (get_kalshi_15m_window)
        to ensure consistency with market_catalog and the new ET-based time contract.
        
        Args:
            series_ticker: The series ticker (e.g., KXBTCD)
            catalog_ticker: Optional actual ticker from catalog (e.g., KXBTCD-26APR22H12-T60000)
                          If provided, this overrides the predicted ticker format
        
        Returns None if no market is currently open.
        """
        from merid.event_venues.kalshi.kalshi_15m_time import get_kalshi_15m_window
        
        now_utc = datetime.now(timezone.utc)
        
        # Use shared ET helper to get current window
        et_window = get_kalshi_15m_window(now_utc)
        
        logger.debug(
            f"[SCHEDULER-DEBUG] now_utc={now_utc} et_window.start_et={et_window.start_et} "
            f"et_window.end_et={et_window.end_et} et_window.suffix={et_window.suffix}"
        )
        
        # Use catalog ticker if provided, otherwise predict format using UTC start time
        ticker = catalog_ticker if catalog_ticker else self._format_ticker(series_ticker, et_window.start_utc)
        
        logger.debug(f"[SCHEDULER-DEBUG] series_ticker={series_ticker} catalog_ticker={catalog_ticker} predicted_ticker={ticker}")
        
        window = MarketWindow(
            start_utc=et_window.start_utc,
            expiry_utc=et_window.end_utc,
            ticker=ticker
        )
        
        # Check if we're currently in this window
        if et_window.is_open:
            self._cache[series_ticker] = window
            return window
        
        return None
    
    def get_next_window(self, series_ticker: str) -> MarketWindow:
        """
        Get the next upcoming market window for a series.
        
        CRITICAL: This now uses the shared ET helper (get_kalshi_15m_window)
        to ensure consistency with market_catalog
        """
        from merid.event_venues.kalshi.kalshi_15m_time import get_kalshi_15m_window
        
        now_utc = datetime.now(timezone.utc)
        
        # Use shared ET helper to get next window
        et_window = get_kalshi_15m_window(now_utc)
        
        # Get next window by adding 15 minutes to current window start
        next_start_utc = et_window.start_utc + timedelta(minutes=15)
        next_end_utc = et_window.end_utc + timedelta(minutes=15)
        
        return MarketWindow(
            start_utc=next_start_utc,
            expiry_utc=next_end_utc,
            ticker=self._format_ticker(series_ticker, next_start_utc)
        )
    
    def get_previous_window(self, series_ticker: str) -> MarketWindow:
        """
        Get the previous market window for a series.
        
        CRITICAL: This now uses the shared ET helper (get_kalshi_15m_window)
        to ensure consistency with market_catalog and the new ET-based time contract.
        """
        from merid.event_venues.kalshi.kalshi_15m_time import get_kalshi_15m_window
        
        now_utc = datetime.now(timezone.utc)
        
        # Use shared ET helper to get current window, then subtract 15 minutes
        et_window = get_kalshi_15m_window(now_utc)
        
        # Get previous window by subtracting 15 minutes from current window start
        prev_start_utc = et_window.start_utc - timedelta(minutes=15)
        prev_end_utc = et_window.end_utc - timedelta(minutes=15)
        
        return MarketWindow(
            start_utc=prev_start_utc,
            expiry_utc=prev_end_utc,
            ticker=self._format_ticker(series_ticker, prev_start_utc)
        )
    
    def compute_minutes_to_expiry(self, expiry_utc: datetime) -> float:
        """
        Compute minutes to expiry from a market's expiry time.
        
        CRITICAL: This now uses the shared UTC helper (compute_minutes_to_expiry)
        to ensure consistency with market_catalog and Kalshi's UTC-based ticker format.
        
        This is the internal computation that replaces reliance on API data.
        """
        from merid.event_venues.kalshi.kalshi_15m_time import compute_minutes_to_expiry
        
        return compute_minutes_to_expiry(expiry_utc)
    
    def should_trade_now(self, series_ticker: str, min_minutes: int = 1, max_minutes: int = 14, catalog_ticker: Optional[str] = None) -> Tuple[bool, Optional[MarketWindow], str]:
        """
        Determine if we should trade a series right now.
        
        Args:
            series_ticker: Series ticker (e.g. KXBTC15M)
            min_minutes: Minimum minutes to expiry to allow trading
            max_minutes: Maximum minutes to expiry to allow trading
            catalog_ticker: Optional actual market ticker from catalog. When provided,
                window.ticker uses this real Kalshi ticker rather than the predicted
                format. Required for market state store lookups since the predicted
                format does not match Kalshi's actual ticker convention (Kalshi uses
                YYMMMDD + ET, this scheduler's format helper uses DDMMMYY + UTC).
        
        Returns:
            (should_trade, market_window, reason)
        """
        window = self.get_current_window(series_ticker, catalog_ticker=catalog_ticker)
        
        if window is None:
            # No market currently open, check when next one opens
            next_window = self.get_next_window(series_ticker)
            minutes_until_open = (next_window.start_utc - datetime.now(timezone.utc)).total_seconds() / 60.0
            return False, next_window, f"No market open. Next opens in {minutes_until_open:.1f} minutes"
        
        if not window.is_in_trading_window(min_minutes, max_minutes):
            mte = window.minutes_to_expiry
            if mte < min_minutes:
                return False, window, f"Market too close to expiry ({mte:.1f} min < {min_minutes} min)"
            else:
                return False, window, f"Market too far from expiry ({mte:.1f} min > {max_minutes} min)"
        
        # Drift detection: compare scheduler tradability vs catalog tradability
        scheduler_tradable = True
        catalog_tradable = True
        
        try:
            from merid.monitoring.drift_metrics import get_drift_metrics_collector
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            
            drift_collector = get_drift_metrics_collector()
            market_state_store = get_kalshi_market_state_store()
            
            # Get catalog/market state view of tradability
            market_state = market_state_store.get_state(window.ticker)
            if market_state:
                catalog_tradable = market_state.is_trading_enabled()
                
                # Collect drift metric if views differ
                drift_collector.collect_scheduler_catalog_mismatch(
                    market_id=window.ticker,
                    scheduler_tradable=scheduler_tradable,
                    catalog_tradable=catalog_tradable
                )
        except Exception as e:
            logger.debug(f"[DRIFT-METRICS] Failed to collect drift metrics in scheduler: {e}")
        
        return True, window, f"Market in trading window ({window.minutes_to_expiry:.1f} min to expiry)"


# Global scheduler instance
_scheduler: Optional[Crypto15mScheduler] = None


def get_crypto_15m_scheduler() -> Crypto15mScheduler:
    """Get the global 15m scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = Crypto15mScheduler()
    return _scheduler
