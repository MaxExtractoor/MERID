"""
Position State Desync Monitor

Monitors for desynchronization between Position.size and PositionCache.contracts.
This is a critical monitoring component to detect the bug that was fixed in
position_monitor.py where position.size was being updated directly instead of
via fill callbacks.

The monitor periodically checks:
1. Position.size vs PositionCache.contracts for all open positions
2. Logs warnings if desync is detected
3. Tracks desync metrics over time
4. Alerts if desync exceeds threshold

Usage:
    from merid.monitoring.position_state_monitor import get_position_state_monitor
    
    monitor = get_position_state_monitor()
    monitor.start()  # Start monitoring
    monitor.stop()   # Stop monitoring
"""

import asyncio
import logging
from typing import Dict, Optional, List
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class DesyncEvent:
    """Record of a position state desync event."""
    position_id: str
    asset: str
    position_size: int
    cache_contracts: int
    desync_amount: int
    timestamp: datetime = field(default_factory=datetime.utcnow)
    resolved: bool = False
    resolved_at: Optional[datetime] = None


@dataclass
class DesyncMetrics:
    """Metrics for position state desync monitoring."""
    total_desyncs: int = 0
    active_desyncs: int = 0
    resolved_desyncs: int = 0
    max_desync_amount: int = 0
    desyncs_by_asset: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    last_desync_time: Optional[datetime] = None


class PositionStateMonitor:
    """
    Monitors position state synchronization between Position.size and PositionCache.contracts.
    
    This is a singleton service that runs in the background and periodically checks
    for desynchronization between position.size and PositionCache.contracts.
    """
    
    _instance: Optional['PositionStateMonitor'] = None
    
    def __init__(self, check_interval_seconds: float = 30.0):
        """
        Initialize position state monitor.
        
        Args:
            check_interval_seconds: Interval between desync checks (default 30s)
        """
        self._check_interval = check_interval_seconds
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
        # Tracking
        self._desync_events: List[DesyncEvent] = []
        self._metrics = DesyncMetrics()
        self._active_desyncs: Dict[str, DesyncEvent] = {}
        
        # Thresholds
        self._desync_threshold = 1  # Alert if desync >= 1 contract
        self._max_history = 1000  # Keep last 1000 desync events
    
    @classmethod
    def get_instance(cls) -> 'PositionStateMonitor':
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    async def start(self) -> None:
        """Start monitoring position state synchronization."""
        if self._running:
            logger.warning("[POSITION-STATE-MONITOR] Already running")
            return
        
        logger.info("[POSITION-STATE-MONITOR] Starting position state desync monitor")
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
    
    async def stop(self) -> None:
        """Stop monitoring position state synchronization."""
        if not self._running:
            return
        
        logger.info("[POSITION-STATE-MONITOR] Stopping position state desync monitor")
        self._running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
    
    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                await self._check_desync()
                await asyncio.sleep(self._check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[POSITION-STATE-MONITOR] Monitor loop error: {e}", exc_info=True)
                await asyncio.sleep(self._check_interval)
    
    async def _check_desync(self) -> None:
        """Check for position state desynchronization."""
        try:
            # Get positions from position monitor
            from merid.position_management.position_monitor import get_position_monitor
            monitor = get_position_monitor()
            
            if monitor is None:
                logger.debug("[POSITION-STATE-MONITOR] Position monitor not available")
                return
            
            positions = monitor.get_open_positions()
            
            # Get position cache
            from merid.event_venues.kalshi.position_cache import get_position_cache
            cache = get_position_cache()
            
            if cache is None:
                logger.debug("[POSITION-STATE-MONITOR] Position cache not available")
                return
            
            # Check each position
            for position in positions:
                try:
                    # Get cache entry for this position
                    cache_position = cache.get_position(position.position_id)
                    
                    if cache_position is None:
                        continue
                    
                    # Compare position.size with cache.contracts
                    position_size = position.size
                    cache_contracts = cache_position.contracts if hasattr(cache_position, 'contracts') else 0
                    
                    desync_amount = abs(position_size - cache_contracts)
                    
                    if desync_amount >= self._desync_threshold:
                        await self._handle_desync(position, position_size, cache_contracts, desync_amount)
                    else:
                        # Check if this was an active desync that's now resolved
                        if position.position_id in self._active_desyncs:
                            await self._resolve_desync(position.position_id)
                            
                except Exception as e:
                    logger.error(f"[POSITION-STATE-MONITOR] Error checking position {position.position_id}: {e}")
                    
        except Exception as e:
            logger.error(f"[POSITION-STATE-MONITOR] Desync check error: {e}", exc_info=True)
    
    async def _handle_desync(self, position, position_size: int, cache_contracts: int, desync_amount: int) -> None:
        """Handle detected desynchronization."""
        # Extract asset from position
        asset = self._extract_asset(position)
        
        # Create desync event
        event = DesyncEvent(
            position_id=position.position_id,
            asset=asset,
            position_size=position_size,
            cache_contracts=cache_contracts,
            desync_amount=desync_amount,
        )
        
        # Track if this is a new desync
        is_new = position.position_id not in self._active_desyncs
        
        if is_new:
            # New desync detected
            self._active_desyncs[position.position_id] = event
            self._desync_events.append(event)
            
            # Update metrics
            self._metrics.total_desyncs += 1
            self._metrics.active_desyncs += 1
            self._metrics.max_desync_amount = max(self._metrics.max_desync_amount, desync_amount)
            self._metrics.desyncs_by_asset[asset] += 1
            self._metrics.last_desync_time = event.timestamp
            
            # Trim history
            if len(self._desync_events) > self._max_history:
                self._desync_events = self._desync_events[-self._max_history:]
            
            # Log warning
            logger.warning(
                "[POSITION-STATE-MONITOR] DESYNC DETECTED: position=%s asset=%s position_size=%d cache_contracts=%d desync=%d",
                position.position_id[:8],
                asset,
                position_size,
                cache_contracts,
                desync_amount,
            )
        else:
            # Existing desync still active - update metrics
            self._active_desyncs[position.position_id] = event
            logger.debug(
                "[POSITION-STATE-MONITOR] DESYNC PERSISTING: position=%s asset=%s desync=%d",
                position.position_id[:8],
                asset,
                desync_amount,
            )
    
    async def _resolve_desync(self, position_id: str) -> None:
        """Mark desync as resolved."""
        if position_id not in self._active_desyncs:
            return
        
        event = self._active_desyncs[position_id]
        event.resolved = True
        event.resolved_at = datetime.utcnow()
        
        # Update metrics
        self._metrics.active_desyncs -= 1
        self._metrics.resolved_desyncs += 1
        
        # Remove from active
        del self._active_desyncs[position_id]
        
        logger.info(
            "[POSITION-STATE-MONITOR] DESYNC RESOLVED: position=%s asset=%s",
            position_id[:8],
            event.asset,
        )
    
    def _extract_asset(self, position) -> str:
        """Extract asset symbol from position."""
        if hasattr(position, 'series_ticker') and position.series_ticker:
            ticker_upper = position.series_ticker.upper()
            for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                if asset in ticker_upper:
                    return asset
        
        if hasattr(position, 'market_id') and position.market_id:
            market_upper = position.market_id.upper()
            for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                if asset in market_upper:
                    return asset
        
        return "UNKNOWN"
    
    def get_metrics(self) -> DesyncMetrics:
        """Get current desync metrics."""
        return self._metrics
    
    def get_active_desyncs(self) -> List[DesyncEvent]:
        """Get list of active desync events."""
        return list(self._active_desyncs.values())
    
    def get_desync_history(self, limit: int = 100) -> List[DesyncEvent]:
        """Get recent desync history."""
        return self._desync_events[-limit:]


def get_position_state_monitor() -> PositionStateMonitor:
    """Get singleton position state monitor instance."""
    return PositionStateMonitor.get_instance()
