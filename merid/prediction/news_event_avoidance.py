"""
News Event Avoidance for 15m Kalshi Crypto Trading

2026 Industry Best Practice Implementation:
- Avoid trading 15 minutes before and after high-impact news
- Major economic releases (NFP, CPI, rate decisions) cause extreme volatility
- that invalidates technical analysis and increases risk
- Reference: https://www.binarybrokerhub.com/en/blog/5-minute-binary-options-strategy

Usage:
    from merid.prediction.news_event_avoidance import get_news_avoidance
    
    news_avoidance = get_news_avoidance()
    if news_avoidance.should_avoid_trading(now):
        # Skip trading due to news event
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Dict, List, Optional, Set

from utils.logger import get_logger

logger = get_logger("merid.prediction.news_event_avoidance")


class NewsEventSeverity(str, Enum):
    """Severity level of news events."""
    HIGH = "high"  # Major economic releases (NFP, CPI, FOMC)
    MEDIUM = "medium"  # Secondary economic indicators
    LOW = "low"  # Minor events


@dataclass
class NewsEvent:
    """Represents a scheduled news event."""
    event_type: str  # e.g., "NFP", "CPI", "FOMC"
    scheduled_time: datetime  # UTC time of event
    severity: NewsEventSeverity
    description: str = ""


@dataclass
class NewsAvoidanceConfig:
    """Configuration for news event avoidance."""
    
    # Avoidance window in minutes
    avoidance_window_min: int = 15  # Avoid trading 15 minutes before/after
    
    # High-impact events to avoid
    high_impact_events: Set[str] = field(default_factory=lambda: {
        "NFP",  # Non-Farm Payrolls
        "CPI",  # Consumer Price Index
        "FOMC",  # Federal Reserve rate decisions
        "GDP",  # Gross Domestic Product
        "PPI",  # Producer Price Index
        "Retail Sales",
        "ISM Manufacturing",
        "ISM Services"
    })
    
    # Enable/disable
    enabled: bool = True


@dataclass
class AvoidanceStatus:
    """Status of news event avoidance check."""
    should_avoid: bool
    reason: str
    upcoming_events: List[NewsEvent] = field(default_factory=list)
    time_until_next_event: Optional[timedelta] = None


class NewsEventAvoidance:
    """
    News event avoidance system for 15m binary options trading.
    
    Prevents trading during high-volatility periods around major economic releases.
    """
    
    def __init__(self, config: Optional[NewsAvoidanceConfig] = None):
        self.config = config or NewsAvoidanceConfig()
        
        # In production, this would load from an economic calendar API
        # For now, we use a static schedule of major events
        self._scheduled_events: List[NewsEvent] = []
        self._load_scheduled_events()
        
        logger.info(
            "[NEWS-AVOIDANCE-INIT] enabled=%s window=%dmin events=%d",
            self.config.enabled,
            self.config.avoidance_window_min,
            len(self._scheduled_events)
        )
    
    def _load_scheduled_events(self) -> None:
        """
        Load scheduled news events.
        
        In production, this would fetch from an economic calendar API.
        For now, we provide a placeholder implementation.
        """
        # Placeholder: In production, load from economic calendar API
        # Example events would be loaded dynamically based on current date
        logger.info("[NEWS-AVOIDANCE] Loading scheduled events from economic calendar")
        # TODO: Integrate with economic calendar API (e.g., Investing.com, ForexFactory)
    
    def add_scheduled_event(self, event: NewsEvent) -> None:
        """Add a scheduled news event."""
        self._scheduled_events.append(event)
        logger.info(
            "[NEWS-AVOIDANCE] Added event: type=%s time=%s severity=%s",
            event.event_type, event.scheduled_time, event.severity
        )
    
    def is_in_avoidance_window(self, event: NewsEvent, now: datetime) -> bool:
        """
        Check if current time is within avoidance window for an event.
        
        Args:
            event: News event to check
            now: Current UTC time
            
        Returns:
            True if within avoidance window
        """
        window = timedelta(minutes=self.config.avoidance_window_min)
        time_until_event = event.scheduled_time - now
        time_since_event = now - event.scheduled_time
        
        # Check if we're within window before or after event
        in_window_before = abs(time_until_event) <= window and time_until_event > timedelta(0)
        in_window_after = abs(time_since_event) <= window and time_since_event > timedelta(0)
        
        return in_window_before or in_window_after
    
    def should_avoid_trading(self, now: Optional[datetime] = None) -> AvoidanceStatus:
        """
        Check if trading should be avoided due to news events.
        
        Args:
            now: Current UTC time (default: current time)
            
        Returns:
            AvoidanceStatus with recommendation and reasoning
        """
        if not self.config.enabled:
            return AvoidanceStatus(
                should_avoid=False,
                reason="News event avoidance disabled",
                upcoming_events=[],
                time_until_next_event=None
            )
        
        if now is None:
            now = datetime.now(timezone.utc)
        
        # Check all scheduled events
        upcoming_events = []
        for event in self._scheduled_events:
            if self.is_in_avoidance_window(event, now):
                upcoming_events.append(event)
        
        # Sort by time
        upcoming_events.sort(key=lambda e: e.scheduled_time)
        
        if upcoming_events:
            next_event = upcoming_events[0]
            time_until = next_event.scheduled_time - now
            
            return AvoidanceStatus(
                should_avoid=True,
                reason=f"Within {self.config.avoidance_window_min}min window of {next_event.event_type}",
                upcoming_events=upcoming_events,
                time_until_next_event=time_until
            )
        
        # Check for upcoming events within next hour
        next_hour_events = [
            e for e in self._scheduled_events
            if timedelta(0) < (e.scheduled_time - now) <= timedelta(hours=1)
        ]
        
        if next_hour_events:
            next_event = min(next_hour_events, key=lambda e: e.scheduled_time - now)
            return AvoidanceStatus(
                should_avoid=False,
                reason="No immediate news, but event approaching",
                upcoming_events=[next_event],
                time_until_next_event=next_event.scheduled_time - now
            )
        
        return AvoidanceStatus(
            should_avoid=False,
            reason="No news events in avoidance window",
            upcoming_events=[],
            time_until_next_event=None
        )


# Global news avoidance instance
_news_avoidance: Optional[NewsEventAvoidance] = None


def get_news_avoidance() -> NewsEventAvoidance:
    """Get or create the global news avoidance instance."""
    global _news_avoidance
    if _news_avoidance is None:
        _news_avoidance = NewsEventAvoidance()
    return _news_avoidance
