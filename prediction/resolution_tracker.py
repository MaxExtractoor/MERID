"""
Event Resolution Clock Tracker.

Tracks when prediction market events are scheduled to resolve
and monitors the resolution process for timing opportunities.

Version: 1.0.0
"""

from __future__ import annotations

import asyncio
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone

from utils.logger import get_logger

logger = get_logger("prediction.resolution_tracker")


class ResolutionStatus(Enum):
    """Status of event resolution."""
    PENDING = "pending"
    RESOLVING = "resolving"
    DISPUTED = "disputed"
    RESOLVED = "resolved"
    VOIDED = "voided"


class MarketPlatform(Enum):
    """Prediction market platforms."""
    POLYMARKET = "polymarket"
    KALSHI = "kalshi"
    PREDICTIT = "predictit"
    MANIFOLD = "manifold"
    METACULUS = "metaculus"
    AUGUR = "augur"


@dataclass
class ResolutionEvent:
    """A prediction market resolution event."""
    event_id: str
    platform: MarketPlatform
    market_id: str
    question: str
    
    # Timing
    scheduled_resolution: float  # Unix timestamp
    actual_resolution: Optional[float] = None
    
    # Status
    status: ResolutionStatus = ResolutionStatus.PENDING
    outcome: Optional[str] = None
    
    # Pricing
    yes_price_at_schedule: float = 0.5
    yes_price_current: float = 0.5
    yes_price_at_resolution: Optional[float] = None
    
    # Metadata
    category: str = ""
    volume_usd: float = 0.0
    liquidity_usd: float = 0.0
    
    # Tracking
    created_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)
    
    def time_to_resolution_seconds(self) -> float:
        """Seconds until scheduled resolution."""
        return max(0, self.scheduled_resolution - time.time())
    
    def time_to_resolution_hours(self) -> float:
        """Hours until scheduled resolution."""
        return self.time_to_resolution_seconds() / 3600
    
    def is_imminent(self, threshold_hours: float = 1.0) -> bool:
        """Check if resolution is imminent."""
        return self.time_to_resolution_hours() <= threshold_hours
    
    def resolution_delay_seconds(self) -> Optional[float]:
        """Delay between scheduled and actual resolution."""
        if self.actual_resolution is None:
            return None
        return self.actual_resolution - self.scheduled_resolution
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "platform": self.platform.value,
            "market_id": self.market_id,
            "question": self.question,
            "scheduled_resolution": self.scheduled_resolution,
            "scheduled_resolution_iso": datetime.fromtimestamp(
                self.scheduled_resolution, tz=timezone.utc
            ).isoformat(),
            "actual_resolution": self.actual_resolution,
            "status": self.status.value,
            "outcome": self.outcome,
            "yes_price_at_schedule": self.yes_price_at_schedule,
            "yes_price_current": self.yes_price_current,
            "yes_price_at_resolution": self.yes_price_at_resolution,
            "category": self.category,
            "volume_usd": self.volume_usd,
            "liquidity_usd": self.liquidity_usd,
            "time_to_resolution_hours": self.time_to_resolution_hours(),
            "is_imminent": self.is_imminent(),
            "resolution_delay_seconds": self.resolution_delay_seconds(),
        }


@dataclass
class ResolutionPattern:
    """Statistical pattern of resolution timing for a platform."""
    platform: MarketPlatform
    category: str
    
    # Timing statistics
    avg_delay_seconds: float = 0.0
    min_delay_seconds: float = 0.0
    max_delay_seconds: float = 0.0
    std_dev_seconds: float = 0.0
    
    # Resolution patterns
    early_resolution_pct: float = 0.0  # % resolved before scheduled
    on_time_resolution_pct: float = 0.0  # % resolved within 1 hour
    late_resolution_pct: float = 0.0  # % resolved after 1 hour
    
    # Sample info
    sample_count: int = 0
    last_updated: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "platform": self.platform.value,
            "category": self.category,
            "avg_delay_seconds": self.avg_delay_seconds,
            "min_delay_seconds": self.min_delay_seconds,
            "max_delay_seconds": self.max_delay_seconds,
            "std_dev_seconds": self.std_dev_seconds,
            "early_resolution_pct": self.early_resolution_pct,
            "on_time_resolution_pct": self.on_time_resolution_pct,
            "late_resolution_pct": self.late_resolution_pct,
            "sample_count": self.sample_count,
        }


class ResolutionTracker:
    """
    Tracks prediction market resolution timing.
    
    Monitors when events are scheduled to resolve and tracks
    the actual resolution process to identify timing patterns
    that can be exploited.
    """
    
    def __init__(self):
        self.logger = get_logger("prediction.resolution_tracker")
        
        # Active events
        self._events: Dict[str, ResolutionEvent] = {}
        
        # Historical events (for pattern analysis)
        self._history: List[ResolutionEvent] = []
        self._max_history: int = 10000
        
        # Resolution patterns
        self._patterns: Dict[str, ResolutionPattern] = {}
        
        # Callbacks for imminent resolutions
        self._callbacks: List[callable] = []
        
        # Running state
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None
    
    async def start(self) -> None:
        """Start resolution tracking."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._track_loop())
        self.logger.info("Resolution tracker started")
    
    async def stop(self) -> None:
        """Stop resolution tracking."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.logger.info("Resolution tracker stopped")
    
    async def _track_loop(self) -> None:
        """Main tracking loop."""
        while self._running:
            try:
                # Update event statuses
                await self._update_events()
                
                # Check for imminent resolutions
                self._check_imminent_resolutions()
                
                # Update patterns
                self._update_patterns()
                
                await asyncio.sleep(60)  # Check every minute
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Track error: {e}")
                await asyncio.sleep(60)
    
    async def _update_events(self) -> None:
        """Update status of tracked events."""
        for event_id, event in list(self._events.items()):
            try:
                # In production, fetch actual status from platform APIs
                # Simulated for now
                
                if event.status == ResolutionStatus.PENDING:
                    # Check if past scheduled resolution
                    if time.time() > event.scheduled_resolution:
                        event.status = ResolutionStatus.RESOLVING
                
                elif event.status == ResolutionStatus.RESOLVING:
                    # In production, this would poll the actual platform API
                    # Events stay in RESOLVING state until real resolution data arrives
                    # No fake random outcomes - real data required
                    pass
                
                event.last_updated = time.time()
                
            except Exception as e:
                self.logger.debug(f"Event update error for {event_id}: {e}")
    
    def _check_imminent_resolutions(self) -> None:
        """Check for and notify about imminent resolutions."""
        imminent = self.get_imminent_events(threshold_hours=1.0)
        
        for event in imminent:
            for callback in self._callbacks:
                try:
                    callback(event)
                except Exception as e:
                    self.logger.error(f"Callback error: {e}")
    
    def _update_patterns(self) -> None:
        """Update resolution patterns from history."""
        # Group by platform and category
        groups: Dict[str, List[ResolutionEvent]] = {}
        
        for event in self._history:
            if event.status != ResolutionStatus.RESOLVED:
                continue
            if event.resolution_delay_seconds() is None:
                continue
            
            key = f"{event.platform.value}_{event.category}"
            if key not in groups:
                groups[key] = []
            groups[key].append(event)
        
        # Calculate patterns
        for key, events in groups.items():
            if len(events) < 5:  # Need minimum samples
                continue
            
            platform_str, category = key.split("_", 1)
            platform = MarketPlatform(platform_str)
            
            delays = [e.resolution_delay_seconds() for e in events]
            delays.sort()
            
            early = sum(1 for d in delays if d < 0) / len(delays)
            on_time = sum(1 for d in delays if 0 <= d <= 3600) / len(delays)
            late = sum(1 for d in delays if d > 3600) / len(delays)
            
            self._patterns[key] = ResolutionPattern(
                platform=platform,
                category=category,
                avg_delay_seconds=sum(delays) / len(delays),
                min_delay_seconds=min(delays),
                max_delay_seconds=max(delays),
                std_dev_seconds=self._std_dev(delays),
                early_resolution_pct=early * 100,
                on_time_resolution_pct=on_time * 100,
                late_resolution_pct=late * 100,
                sample_count=len(delays),
            )
    
    def _std_dev(self, values: List[float]) -> float:
        """Calculate standard deviation."""
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return variance ** 0.5
    
    def add_event(self, event: ResolutionEvent) -> None:
        """Add an event to track."""
        self._events[event.event_id] = event
        self.logger.info(f"Tracking event: {event.event_id} - {event.question[:50]}...")
    
    def remove_event(self, event_id: str) -> None:
        """Remove an event from tracking."""
        if event_id in self._events:
            del self._events[event_id]
    
    def get_event(self, event_id: str) -> Optional[ResolutionEvent]:
        """Get a tracked event."""
        return self._events.get(event_id)
    
    def get_all_events(self) -> List[ResolutionEvent]:
        """Get all tracked events."""
        return list(self._events.values())
    
    def get_imminent_events(self, threshold_hours: float = 1.0) -> List[ResolutionEvent]:
        """Get events with imminent resolution."""
        return [
            e for e in self._events.values()
            if e.is_imminent(threshold_hours) and e.status == ResolutionStatus.PENDING
        ]
    
    def get_pattern(self, platform: MarketPlatform, category: str) -> Optional[ResolutionPattern]:
        """Get resolution pattern for platform/category."""
        key = f"{platform.value}_{category}"
        return self._patterns.get(key)
    
    def add_callback(self, callback: callable) -> None:
        """Add callback for imminent resolution notifications."""
        self._callbacks.append(callback)
    
    def get_status(self) -> Dict[str, Any]:
        """Get tracker status."""
        return {
            "running": self._running,
            "active_events": len(self._events),
            "history_count": len(self._history),
            "patterns_count": len(self._patterns),
            "imminent_count": len(self.get_imminent_events()),
            "events": [e.to_dict() for e in self._events.values()],
            "patterns": {k: v.to_dict() for k, v in self._patterns.items()},
        }


# Singleton
_resolution_tracker: Optional[ResolutionTracker] = None


def get_resolution_tracker() -> ResolutionTracker:
    """Get or create the Resolution Tracker singleton."""
    global _resolution_tracker
    if _resolution_tracker is None:
        _resolution_tracker = ResolutionTracker()
    return _resolution_tracker
