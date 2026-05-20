"""24h rolling tracker for sentiment floor blocks and contrarian strategy outcomes.

PRODUCTION FIX v8 (2026-04-30): Provides observability into how often contrarian
strategies are blocked by sentiment floors vs other reasons, enabling data-driven
tuning of contrarian_sentiment_min threshold.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, Optional

from utils.logger import get_logger

logger = get_logger("merid.prediction.sentiment_floor_tracker")


@dataclass
class ContrarianAttempt:
    """Record of a contrarian strategy evaluation attempt."""
    timestamp: float
    market_id: str
    local_sentiment: Optional[float]
    sentiment_min: float
    blocked: bool
    block_reason: Optional[str] = None


class SentimentFloorTracker:
    """Tracks 24h rolling statistics for contrarian sentiment floor blocks.
    
    This enables operators to:
    1. See how many contrarian opportunities were considered in last 24h
    2. See how many were blocked solely by sentiment floor
    3. Tune contrarian_sentiment_min based on real market data
    
    Usage:
        tracker = get_sentiment_floor_tracker()
        tracker.record_attempt(market_id="KXBTC-15M-...", local_sentiment=15.0, 
                              sentiment_min=35.0, blocked=True, 
                              block_reason="sentiment_below_contrarian_floor")
        stats = tracker.get_24h_stats()
        print(f"Contrarian blocks due to floor: {stats.blocks_due_to_floor}")
    """
    
    _instance: Optional["SentimentFloorTracker"] = None
    # TEMPORARILY DISABLED: threading.Lock causing deadlock during startup
    # TODO: Re-enable lock after startup is stable and investigate proper async synchronization
    # _lock: threading.Lock = threading.Lock()
    _lock: Optional[threading.Lock] = None  # Disabled to prevent startup hang
    
    def __new__(cls) -> "SentimentFloorTracker":
        if cls._instance is None:
            if cls._lock is not None:
                with cls._lock:
                    if cls._instance is None:
                        cls._instance = super().__new__(cls)
                        cls._instance._initialized = False
            else:
                # Lock disabled - direct initialization (startup workaround)
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
        return cls._instance
    
    def __init__(self) -> None:
        if self._initialized:
            return
        if self._lock is not None:
            with self._lock:
                if self._initialized:
                    return
                self._24h_seconds = 24 * 60 * 60  # 24 hours in seconds
                self._attempts: deque[ContrarianAttempt] = deque()
                self._initialized = True
        else:
            # Lock disabled - direct initialization (startup workaround)
            self._24h_seconds = 24 * 60 * 60  # 24 hours in seconds
            self._attempts: deque[ContrarianAttempt] = deque()
            self._initialized = True
    
    def record_attempt(
        self,
        market_id: str,
        local_sentiment: Optional[float],
        sentiment_min: float,
        blocked: bool,
        block_reason: Optional[str] = None,
    ) -> None:
        """Record a contrarian evaluation attempt.
        
        Args:
            market_id: The ticker/market identifier
            local_sentiment: The local sentiment score (0-100) or None
            sentiment_min: The configured contrarian_sentiment_min threshold
            blocked: Whether the contrarian signal was blocked
            block_reason: Why it was blocked (e.g., "sentiment_below_contrarian_floor")
        """
        now = time.time()
        
        with self._lock:
            # Clean up old entries (>24h)
            cutoff = now - self._24h_seconds
            while self._attempts and self._attempts[0].timestamp < cutoff:
                self._attempts.popleft()
            
            # Record new attempt
            attempt = ContrarianAttempt(
                timestamp=now,
                market_id=market_id,
                local_sentiment=local_sentiment,
                sentiment_min=sentiment_min,
                blocked=blocked,
                block_reason=block_reason,
            )
            self._attempts.append(attempt)
            
            # Log summary every 50 attempts
            if len(self._attempts) % 50 == 0:
                self._log_summary()
    
    def get_24h_stats(self) -> Dict:
        """Get 24h rolling statistics for contrarian attempts.
        
        Returns:
            Dict with keys:
                - total_attempts: Total contrarian evaluations in last 24h
                - total_blocked: Total blocked in last 24h
                - blocks_due_to_floor: Blocked specifically due to sentiment floor
                - pass_rate: Percentage that passed (0.0-1.0)
                - avg_sentiment_when_blocked: Average sentiment of blocked attempts
                - floor_efficiency: Floor blocks / total attempts (0.0-1.0)
        """
        with self._lock:
            now = time.time()
            cutoff = now - self._24h_seconds
            
            # Filter to last 24h
            recent = [a for a in self._attempts if a.timestamp >= cutoff]
            
            if not recent:
                return {
                    "total_attempts": 0,
                    "total_blocked": 0,
                    "blocks_due_to_floor": 0,
                    "pass_rate": 0.0,
                    "avg_sentiment_when_blocked": 0.0,
                    "floor_efficiency": 0.0,
                }
            
            total = len(recent)
            blocked = sum(1 for a in recent if a.blocked)
            floor_blocks = sum(
                1 for a in recent 
                if a.blocked and a.block_reason == "sentiment_below_contrarian_floor"
            )
            
            # Average sentiment of blocked attempts
            blocked_sentiments = [
                a.local_sentiment for a in recent 
                if a.blocked and a.local_sentiment is not None
            ]
            avg_sentiment = sum(blocked_sentiments) / len(blocked_sentiments) if blocked_sentiments else 0.0
            
            return {
                "total_attempts": total,
                "total_blocked": blocked,
                "blocks_due_to_floor": floor_blocks,
                "pass_rate": (total - blocked) / total if total > 0 else 0.0,
                "avg_sentiment_when_blocked": avg_sentiment,
                "floor_efficiency": floor_blocks / total if total > 0 else 0.0,
            }
    
    def _log_summary(self) -> None:
        """Log a summary of 24h contrarian statistics."""
        stats = self.get_24h_stats()
        if stats["total_attempts"] > 0:
            logger.info(
                "[CONTRARIAN_24H_STATS] attempts=%d blocked=%d floor_blocks=%d "
                "pass_rate=%.1f%% avg_blocked_sentiment=%.1f",
                stats["total_attempts"],
                stats["total_blocked"],
                stats["blocks_due_to_floor"],
                stats["pass_rate"] * 100,
                stats["avg_sentiment_when_blocked"],
            )


def get_sentiment_floor_tracker() -> SentimentFloorTracker:
    """Get the singleton SentimentFloorTracker instance."""
    return SentimentFloorTracker()
