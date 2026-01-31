"""
Feed parity checker for multi-venue data quality observability.

Detects price divergence, missing symbols, and data quality issues across
multiple market data providers to ensure arbitrage and execution operate on
consistent views.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
import logging

logger = logging.getLogger(__name__)


@dataclass
class FeedSnapshot:
    venue: str
    symbol: str
    price: float
    volume: float
    timestamp: float
    bid: Optional[float] = None
    ask: Optional[float] = None


@dataclass
class ParityViolation:
    violation_id: str
    symbol: str
    venues: List[str]
    price_divergence_pct: float
    threshold_pct: float
    severity: str
    detected_at: datetime
    details: Dict[str, float]


class FeedParityChecker:
    """
    Monitors parity across multiple market data feeds.
    
    Features:
    - Cross-venue price divergence detection
    - Missing symbol alerts
    - Stale data detection
    - Historical parity tracking
    """
    
    def __init__(self, divergence_threshold_pct: float = 0.5):
        self.divergence_threshold_pct = divergence_threshold_pct
        self._snapshots: Dict[str, Dict[str, FeedSnapshot]] = {}  # symbol -> venue -> snapshot
        self._violations: List[ParityViolation] = []
        self._venue_symbols: Dict[str, Set[str]] = {}
    
    def ingest_snapshot(self, snapshot: FeedSnapshot) -> None:
        """Ingest market data snapshot from a venue."""
        symbol_feeds = self._snapshots.setdefault(snapshot.symbol, {})
        symbol_feeds[snapshot.venue] = snapshot
        
        venue_symbols = self._venue_symbols.setdefault(snapshot.venue, set())
        venue_symbols.add(snapshot.symbol)
    
    def check_parity(self, symbol: str) -> Optional[ParityViolation]:
        """Check price parity across all venues for a symbol."""
        feeds = self._snapshots.get(symbol, {})
        
        if len(feeds) < 2:
            return None
        
        prices = {venue: snap.price for venue, snap in feeds.items()}
        min_price = min(prices.values())
        max_price = max(prices.values())
        
        if min_price == 0:
            return None
        
        divergence_pct = ((max_price - min_price) / min_price) * 100
        
        if divergence_pct > self.divergence_threshold_pct:
            severity = (
                "critical" if divergence_pct > 2.0
                else "high" if divergence_pct > 1.0
                else "medium"
            )
            
            violation = ParityViolation(
                violation_id=f"parity_{symbol}_{int(time.time())}",
                symbol=symbol,
                venues=list(prices.keys()),
                price_divergence_pct=divergence_pct,
                threshold_pct=self.divergence_threshold_pct,
                severity=severity,
                detected_at=datetime.utcnow(),
                details=prices,
            )
            
            self._violations.append(violation)
            logger.warning(
                f"Parity violation: {symbol} divergence={divergence_pct:.2f}% "
                f"(threshold={self.divergence_threshold_pct}%)"
            )
            
            if len(self._violations) > 1000:
                self._violations = self._violations[-500:]
            
            return violation
        
        return None
    
    def check_missing_symbols(self) -> Dict[str, List[str]]:
        """Check for symbols missing from some venues."""
        all_symbols = set()
        for symbols in self._venue_symbols.values():
            all_symbols.update(symbols)
        
        missing = {}
        for venue, symbols in self._venue_symbols.items():
            missing_for_venue = all_symbols - symbols
            if missing_for_venue:
                missing[venue] = list(missing_for_venue)
        
        return missing
    
    def check_stale_data(self, max_age_seconds: float = 60.0) -> Dict[str, List[str]]:
        """Check for stale data across venues."""
        now = time.time()
        stale = {}
        
        for symbol, feeds in self._snapshots.items():
            for venue, snapshot in feeds.items():
                age = now - snapshot.timestamp
                if age > max_age_seconds:
                    venue_stale = stale.setdefault(venue, [])
                    venue_stale.append(f"{symbol} (age={age:.1f}s)")
        
        return stale
    
    def get_recent_violations(self, limit: int = 20) -> List[ParityViolation]:
        """Get recent parity violations."""
        return self._violations[-limit:]
    
    def get_parity_status(self) -> Dict[str, object]:
        """Get overall parity status."""
        recent_violations = [
            v for v in self._violations
            if v.detected_at > datetime.utcnow() - timedelta(hours=1)
        ]
        
        symbols_tracked = len(self._snapshots)
        venues_tracked = len(self._venue_symbols)
        
        avg_divergence = (
            sum(v.price_divergence_pct for v in recent_violations) / len(recent_violations)
            if recent_violations else 0.0
        )
        
        return {
            "divergence_threshold_pct": self.divergence_threshold_pct,
            "symbols_tracked": symbols_tracked,
            "venues_tracked": venues_tracked,
            "recent_violations_1h": len(recent_violations),
            "avg_divergence_pct": avg_divergence,
            "total_violations": len(self._violations),
            "missing_symbols": self.check_missing_symbols(),
            "stale_data": self.check_stale_data(),
        }


_feed_parity_checker: Optional[FeedParityChecker] = None


def get_feed_parity_checker() -> FeedParityChecker:
    """Get global FeedParityChecker instance."""
    global _feed_parity_checker
    if _feed_parity_checker is None:
        _feed_parity_checker = FeedParityChecker()
    return _feed_parity_checker
