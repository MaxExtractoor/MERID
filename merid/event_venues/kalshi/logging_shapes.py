"""Structured logging shapes for Kalshi lane hot paths.

Provides LogShape dataclass to enforce compile-time-ish contracts on log lines
and bans ad-hoc f-strings in performance-critical code paths.
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Any

MISSING_MARKER = "MISSING"


@dataclass(frozen=True)
class LogShape:
    """Structured log payload; bans ad-hoc f-strings in hot paths."""

    agent_name: str
    series_resolved: List[str]
    asset: Optional[str] = None
    timeframe: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for structlog/extra= usage.

        Returns:
            Dict with explicit MISSING_MARKER for undefined values.
        """
        return {
            "agent": self.agent_name,
            "series": self.series_resolved or MISSING_MARKER,
            "asset": self.asset or MISSING_MARKER,
            "timeframe": self.timeframe or MISSING_MARKER,
        }
