"""
Timestamp Manager for Kalshi WebSocket Stack - Phase 3 Implementation.

Centralizes timestamp handling and provides consistent data freshness calculations.
Fixes stale data issues by establishing clear timestamp authority hierarchy.

NOTE: This module is currently DORMANT for Kalshi WebSocket usage.
────────────────────────────────────────────────────────────────────────────
Kalshi WebSocket orderbook_delta and orderbook_snapshot messages do NOT include
exchange timestamp fields (no "ts", "timestamp", "updated_at", etc. in the message
payloads). Therefore, this TimestampManager is not currently integrated into the
WebSocket message processing path in market_state.py.

The current system uses time.monotonic() for staleness tracking, which is
appropriate given the lack of exchange timestamps in WS messages. See the
regime-aware staleness implementation in market_state.py for the current approach:
- StalenessRegime enum (RELAXED/NORMAL/STRICT) based on time-to-expiry
- WS connection health watchdog (separate from data staleness)
- REST updated_time cross-check for detecting true WS lag

This module is kept for future use if Kalshi adds timestamp fields to WebSocket
messages. The parsing logic and data structures are ready to be integrated when
such fields become available.
"""

import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any, NamedTuple
from dataclasses import dataclass

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.timestamp_manager")


@dataclass
class TimestampInfo:
    """Comprehensive timestamp information for market data."""
    # Exchange timestamps (from Kalshi)
    exchange_ts: Optional[float] = None  # Unix timestamp from exchange
    exchange_ts_str: Optional[str] = None  # Original ISO string from exchange
    
    # Local timestamps (our system)
    received_ts: float = 0.0  # When we received the message
    processed_ts: float = 0.0  # When we processed the message
    
    # Source information
    source: str = "unknown"  # "websocket", "rest", "rest_fallback"
    message_type: str = "unknown"  # "orderbook_delta", "orderbook_snapshot", "ticker"
    
    # Validation flags
    has_exchange_ts: bool = False
    is_timestamp_valid: bool = True
    
    def __post_init__(self):
        if self.received_ts == 0.0:
            self.received_ts = time.time()
        if self.processed_ts == 0.0:
            self.processed_ts = time.time()
        if self.exchange_ts_str and not self.exchange_ts:
            self.exchange_ts = self._parse_exchange_timestamp()
            self.has_exchange_ts = bool(self.exchange_ts is not None)
        elif self.exchange_ts:
            self.has_exchange_ts = True
        else:
            self.has_exchange_ts = False
    
    def _parse_exchange_timestamp(self) -> Optional[float]:
        """Parse exchange timestamp from ISO string."""
        if not self.exchange_ts_str:
            return None
        
        try:
            # Handle various Kalshi timestamp formats
            ts_str = self.exchange_ts_str
            
            # Remove Z suffix if present
            if ts_str.endswith('Z'):
                ts_str = ts_str[:-1] + '+00:00'
            elif ts_str.endswith('.Z'):
                ts_str = ts_str[:-2] + '+00:00'
            
            # Parse with timezone awareness
            dt = datetime.fromisoformat(ts_str)
            return dt.timestamp()
        except Exception as e:
            logger.debug(f"Failed to parse exchange timestamp '{self.exchange_ts_str}': {e}")
            return None
    
    def get_age_seconds(self, reference_ts: Optional[float] = None) -> float:
        """Get age of data in seconds relative to reference timestamp."""
        if reference_ts is None:
            reference_ts = time.time()
        
        # Prefer exchange timestamp for true data age
        if self.has_exchange_ts and self.exchange_ts:
            return reference_ts - self.exchange_ts
        
        # Fall back to received timestamp
        return reference_ts - self.received_ts
    
    def get_processing_latency_ms(self) -> float:
        """Get processing latency in milliseconds."""
        return (self.processed_ts - self.received_ts) * 1000.0
    
    def is_fresh(self, max_age_seconds: float = 30.0, reference_ts: Optional[float] = None) -> bool:
        """Check if data is fresh within specified age threshold.
        
        Args:
            max_age_seconds: Maximum age in seconds to be considered fresh
            reference_ts: Reference timestamp for age calculation (defaults to current time)
        
        Returns:
            True if data is fresh, False otherwise
        """
        return self.get_age_seconds(reference_ts) <= max_age_seconds
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/debugging."""
        return {
            "exchange_ts": self.exchange_ts,
            "exchange_ts_str": self.exchange_ts_str,
            "received_ts": self.received_ts,
            "processed_ts": self.processed_ts,
            "source": self.source,
            "message_type": self.message_type,
            "has_exchange_ts": self.has_exchange_ts,
            "is_timestamp_valid": self.is_timestamp_valid,
            "age_seconds": self.get_age_seconds(),
            "processing_latency_ms": self.get_processing_latency_ms(),
            "is_fresh": self.is_fresh()
        }


class TimestampManager:
    """
    Centralized timestamp management for Kalshi market data.
    
    Provides consistent timestamp handling and data freshness calculations
    across the entire WebSocket stack.
    """
    
    def __init__(self):
        # Timestamp authority hierarchy
        self._timestamp_priority = [
            "exchange",  # Kalshi exchange timestamp (most authoritative)
            "received",  # When we received the message
            "processed"  # When we processed the message
        ]
        
        # Tracking for diagnostics
        self._last_timestamp_update: Dict[str, float] = {}
        self._timestamp_source_counts: Dict[str, int] = {}
        self._stale_data_events: int = 0
        self._total_events: int = 0
        
        # Configuration - load from profile YAML or fallback to defaults
        self._max_age_seconds = self._load_max_age_seconds()
        self._clock_skew_tolerance_seconds = self._load_clock_skew_tolerance()
    
    def _load_max_age_seconds(self) -> float:
        """Load max age threshold from profile YAML or fallback to default."""
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            adapter = get_active_profile()
            if adapter is not None and hasattr(adapter, 'profile') and adapter.profile is not None:
                if hasattr(adapter.profile, 'clock_drift'):
                    return getattr(adapter.profile.clock_drift, 'max_age_seconds', 30.0)
        except Exception:
            pass
        return 30.0  # Fallback default
    
    def _load_clock_skew_tolerance(self) -> float:
        """Load clock skew tolerance from profile YAML or fallback to default."""
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            adapter = get_active_profile()
            if adapter is not None and hasattr(adapter, 'profile') and adapter.profile is not None:
                if hasattr(adapter.profile, 'clock_drift'):
                    return getattr(adapter.profile.clock_drift, 'clock_skew_tolerance_seconds', 5.0)
        except Exception:
            pass
        return 5.0  # Fallback default
    
    def extract_timestamp_info(self, data: Dict[str, Any], source: str) -> TimestampInfo:
        """
        Extract comprehensive timestamp information from market data.
        
        Args:
            data: Raw market data message
            source: Source of the data ("websocket", "rest", "rest_fallback")
            
        Returns:
            TimestampInfo with all available timestamp information
        """
        now = time.time()
        
        # Determine message type
        message_type = data.get("type", data.get("channel", "unknown"))
        
        # Extract exchange timestamp
        exchange_ts = None
        exchange_ts_str = None
        
        # Try various timestamp fields that Kalshi might send
        timestamp_fields = ["ts", "timestamp", "created_at", "updated_at", "time"]
        
        for field in timestamp_fields:
            if field in data and data[field]:
                exchange_ts_str = str(data[field])
                break
        
        # Create timestamp info
        ts_info = TimestampInfo(
            exchange_ts=exchange_ts,
            exchange_ts_str=exchange_ts_str,
            received_ts=now,
            processed_ts=now,
            source=source,
            message_type=message_type,
            has_exchange_ts=bool(exchange_ts_str),
            is_timestamp_valid=True
        )
        
        # Validate timestamp
        ts_info.is_timestamp_valid = self._validate_timestamp(ts_info)
        
        # Update tracking
        self._update_tracking(ts_info)
        
        return ts_info
    
    def _validate_timestamp(self, ts_info: TimestampInfo) -> bool:
        """Validate timestamp for reasonableness."""
        now = time.time()
        
        # Check if exchange timestamp is in reasonable range
        if ts_info.has_exchange_ts and ts_info.exchange_ts:
            # Exchange timestamp should not be too far in the future
            if ts_info.exchange_ts > now + self._clock_skew_tolerance_seconds:
                logger.warning(
                    f"[TIMESTAMP] Exchange timestamp too far in future: "
                    f"exchange_ts={ts_info.exchange_ts}, now={now}, "
                    f"source={ts_info.source}, type={ts_info.message_type}"
                )
                return False
            
            # Exchange timestamp should not be too far in the past (older than 1 hour)
            if ts_info.exchange_ts < now - 3600:
                logger.warning(
                    f"[TIMESTAMP] Exchange timestamp too old: "
                    f"exchange_ts={ts_info.exchange_ts}, now={now}, "
                    f"source={ts_info.source}, type={ts_info.message_type}"
                )
                return False
        
        return True
    
    def _update_tracking(self, ts_info: TimestampInfo) -> None:
        """Update internal tracking for diagnostics."""
        # Update source counts
        self._timestamp_source_counts[ts_info.source] = self._timestamp_source_counts.get(ts_info.source, 0) + 1
        
        # Update total events
        self._total_events += 1
        
        # Track stale data events
        if not ts_info.is_fresh(self._max_age_seconds):
            self._stale_data_events += 1
        
        # Update last timestamp per market
        ticker = self._extract_ticker_from_data(ts_info)
        if ticker:
            self._last_timestamp_update[ticker] = ts_info.processed_ts
    
    def _extract_ticker_from_data(self, ts_info: TimestampInfo) -> Optional[str]:
        """Extract ticker from timestamp info (placeholder - would need data access)."""
        # This would need access to the original data to extract ticker
        # For now, return None - this would be implemented with proper data flow
        return None
    
    def get_freshness_status(self, ticker: str, max_age_seconds: Optional[float] = None) -> Dict[str, Any]:
        """
        Get comprehensive freshness status for a market.
        
        Args:
            ticker: Market ticker
            max_age_seconds: Override default staleness threshold
            
        Returns:
            Dictionary with freshness status information
        """
        if max_age_seconds is None:
            max_age_seconds = self._max_age_seconds
        
        now = time.time()
        last_update = self._last_timestamp_update.get(ticker, 0)
        
        if last_update == 0:
            return {
                "ticker": ticker,
                "has_data": False,
                "age_seconds": float('inf'),
                "is_fresh": False,
                "status": "no_data"
            }
        
        age_seconds = now - last_update
        is_fresh = age_seconds <= max_age_seconds
        
        status = "fresh" if is_fresh else "stale"
        if age_seconds > 300:  # 5 minutes
            status = "very_stale"
        elif age_seconds > 120:  # 2 minutes
            status = "stale"
        elif age_seconds > 60:   # 1 minute
            status = "slightly_stale"
        
        return {
            "ticker": ticker,
            "has_data": True,
            "age_seconds": age_seconds,
            "is_fresh": is_fresh,
            "status": status,
            "last_update": last_update
        }
    
    def get_system_statistics(self) -> Dict[str, Any]:
        """Get system-wide timestamp statistics."""
        return {
            "total_events": self._total_events,
            "stale_data_events": self._stale_data_events,
            "stale_data_rate": self._stale_data_events / max(1, self._total_events),
            "timestamp_sources": dict(self._timestamp_source_counts),
            "markets_tracked": len(self._last_timestamp_update),
            "max_age_seconds": self._max_age_seconds,
            "clock_skew_tolerance_seconds": self._clock_skew_tolerance_seconds
        }
    
    def set_max_age_seconds(self, max_age_seconds: float) -> None:
        """Update maximum age threshold for freshness checks."""
        self._max_age_seconds = max_age_seconds
        logger.info(f"[TIMESTAMP] Updated max age threshold to {max_age_seconds} seconds")
    
    def set_clock_skew_tolerance(self, tolerance_seconds: float) -> None:
        """Update clock skew tolerance for timestamp validation."""
        self._clock_skew_tolerance_seconds = tolerance_seconds
        logger.info(f"[TIMESTAMP] Updated clock skew tolerance to {tolerance_seconds} seconds")
    
    def reset_statistics(self) -> None:
        """Reset all tracking statistics."""
        self._last_timestamp_update.clear()
        self._timestamp_source_counts.clear()
        self._stale_data_events = 0
        self._total_events = 0
        logger.info("[TIMESTAMP] Reset all tracking statistics")


# Global singleton instance
_timestamp_manager: Optional[TimestampManager] = None


def get_timestamp_manager() -> TimestampManager:
    """Get the global timestamp manager singleton."""
    global _timestamp_manager
    if _timestamp_manager is None:
        _timestamp_manager = TimestampManager()
    return _timestamp_manager
