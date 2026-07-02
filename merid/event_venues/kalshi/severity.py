"""
Central severity classification for Kalshi 15m trading stack.

This module defines a unified severity enum for alarm classification across
all components (market health, duality validation, bankroll, risk).

Severity Levels:
- SEV_P0: Transport/data pipeline broken (no books, WS dead, bankroll unreachable)
- SEV_P1: Invariants violated (duality, corrupted state, API misalignment)
- SEV_P2: Illiquidity/wide spreads/extreme prices (market conditions, not plumbing)
- SEV_INFO: Noise, expected behavior (market closed, etc.)

Trading Enablement Rules:
- P0/P1 → Hard trading halt for that venue/profile
- P2 → Allow exits, block new entries or apply stricter sizing
- INFO → No trading impact
"""

from enum import Enum
from typing import Optional


class Severity(Enum):
    """Severity levels for Kalshi trading stack alarms."""
    
    P0 = "P0"  # Critical: transport/data pipeline broken
    P1 = "P1"  # High: invariants violated
    P2 = "P2"  # Medium: illiquidity/extreme prices
    INFO = "INFO"  # Low: informational only
    
    def should_halt_trading(self) -> bool:
        """Check if this severity should halt trading."""
        return self in (Severity.P0, Severity.P1)
    
    def should_restrict_entries(self) -> bool:
        """Check if this severity should restrict new entries."""
        return self in (Severity.P0, Severity.P1, Severity.P2)
    
    def allows_exits(self) -> bool:
        """Check if this severity allows exit orders."""
        return self in (Severity.P2, Severity.INFO)


class Alarm:
    """Structured alarm with severity and context."""
    
    def __init__(
        self,
        component: str,
        severity: Severity,
        message: str,
        ticker: Optional[str] = None,
        metrics: Optional[dict] = None,
    ):
        self.component = component
        self.severity = severity
        self.message = message
        self.ticker = ticker
        self.metrics = metrics or {}
        self.timestamp = None  # Set when raised
    
    def __str__(self) -> str:
        ticker_str = f"[{self.ticker}] " if self.ticker else ""
        metrics_str = f" | {self.metrics}" if self.metrics else ""
        return f"{self.severity.value} {self.component}: {ticker_str}{self.message}{metrics_str}"
    
    def to_dict(self) -> dict:
        """Convert to dictionary for logging/serialization."""
        return {
            "component": self.component,
            "severity": self.severity.value,
            "message": self.message,
            "ticker": self.ticker,
            "metrics": self.metrics,
            "timestamp": self.timestamp,
        }


# Convenience functions for creating common alarms

def create_p0_alarm(component: str, message: str, ticker: Optional[str] = None, **metrics) -> Alarm:
    """Create a P0 (critical) alarm."""
    return Alarm(component, Severity.P0, message, ticker, metrics)


def create_p1_alarm(component: str, message: str, ticker: Optional[str] = None, **metrics) -> Alarm:
    """Create a P1 (high) alarm."""
    return Alarm(component, Severity.P1, message, ticker, metrics)


def create_p2_alarm(component: str, message: str, ticker: Optional[str] = None, **metrics) -> Alarm:
    """Create a P2 (medium) alarm."""
    return Alarm(component, Severity.P2, message, ticker, metrics)


def create_info_alarm(component: str, message: str, ticker: Optional[str] = None, **metrics) -> Alarm:
    """Create an INFO (low) alarm."""
    return Alarm(component, Severity.INFO, message, ticker, metrics)
