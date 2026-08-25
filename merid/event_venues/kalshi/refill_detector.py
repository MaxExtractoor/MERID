"""Refill Time Detector — Detect toxic vs uninformed flow in sparse liquidity.

Based on Electronic Trading Hub research (2023):
- Fast refill (milliseconds) = uninformed flow (participant exiting position)
- Slow refill (seconds/minutes) = toxic flow (informed participant moved the book)
- This is observable in real time without modeling latent variables

Key insight: In thin books, OFI (Order Flow Imbalance) of zero doesn't mean equilibrium.
It means the metric is stale. Refill time is the real-time classifier that works on sparse books.

Implementation:
- Track when liquidity is depleted (depth drops to zero)
- Measure time until liquidity returns (refill time)
- Classify as toxic if refill time exceeds threshold
- Apply penalty to signal generation during toxic periods
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional, Tuple

from utils.logger import get_logger

from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot

logger = get_logger("merid.event_venues.kalshi.refill_detector")


@dataclass
class RefillEvent:
    """Record of a liquidity depletion and refill event."""
    ticker: str
    side: str  # "yes" or "no"
    depletion_ts: float  # When depth dropped to zero
    refill_ts: Optional[float] = None  # When depth returned
    refill_time_ms: Optional[float] = None  # Time to refill in milliseconds
    is_toxic: bool = False  # Whether refill was slow (toxic)
    
    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "side": self.side,
            "depletion_ts": self.depletion_ts,
            "refill_ts": self.refill_ts,
            "refill_time_ms": self.refill_time_ms,
            "is_toxic": self.is_toxic,
        }


@dataclass
class RefillState:
    """Per-market, per-side refill tracking state."""
    last_depth: int = 0
    depletion_start_ts: Optional[float] = None
    recent_refill_times: Deque[float] = field(default_factory=lambda: deque(maxlen=20))
    toxic_event_count: int = 0
    total_event_count: int = 0


class RefillDetector:
    """Detects toxic vs uninformed flow using refill time dynamics.
    
    Based on research from Electronic Trading Hub (2023):
    - Refill time is the real-time classifier for sparse books
    - Fast refill = uninformed flow (safe to trade)
    - Slow refill = toxic flow (informed participant, should suppress signals)
    
    Args:
        toxic_threshold_ms: Refill time threshold (ms) above which flow is toxic
        window_ms: Time window to track refill times (for moving average)
        min_samples: Minimum samples before computing statistics
    """
    
    def __init__(
        self,
        toxic_threshold_ms: float = 1000.0,  # 1 second = toxic
        window_ms: float = 60000.0,  # 1 minute window
        min_samples: int = 3,
    ):
        self.toxic_threshold_ms = toxic_threshold_ms
        self.window_ms = window_ms
        self.min_samples = min_samples
        
        # Per-market, per-side state
        self._state: Dict[str, Dict[str, RefillState]] = {}
        
        # Event history for analysis
        self._event_history: Deque[RefillEvent] = deque(maxlen=1000)
        
    def _get_state(self, ticker: str, side: str) -> RefillState:
        """Get or create state for a market/side."""
        if ticker not in self._state:
            self._state[ticker] = {}
        if side not in self._state[ticker]:
            self._state[ticker][side] = RefillState()
        return self._state[ticker][side]
    
    def process(self, ob: OrderbookSnapshot) -> Tuple[bool, Optional[RefillEvent]]:
        """Process an orderbook snapshot and detect refill events.
        
        Args:
            ob: Canonical OrderbookSnapshot from unified_market_state
            
        Returns:
            Tuple of (is_toxic, event) where:
            - is_toxic: True if current state indicates toxic flow
            - event: RefillEvent if a refill was just detected, else None
        """
        events = []
        
        # Process YES side
        yes_toxic, yes_event = self._process_side(ob, "yes")
        if yes_event:
            events.append(yes_event)
        
        # Process NO side
        no_toxic, no_event = self._process_side(ob, "no")
        if no_event:
            events.append(no_event)
        
        # Store events
        for event in events:
            self._event_history.append(event)
        
        # Return overall toxicity (toxic if either side is toxic)
        is_toxic = yes_toxic or no_toxic
        
        # Return the most recent event if any
        recent_event = events[-1] if events else None
        
        return is_toxic, recent_event
    
    def _process_side(self, ob: OrderbookSnapshot, side: str) -> Tuple[bool, Optional[RefillEvent]]:
        """Process a single side (YES or NO)."""
        state = self._get_state(ob.ticker, side)
        
        # Get current depth for this side
        if side == "yes":
            current_depth = sum(lv.size for lv in ob.yes_bids) if ob.yes_bids else 0
        else:  # no
            current_depth = sum(lv.size for lv in ob.no_bids) if ob.no_bids else 0
        
        event = None
        is_toxic = False
        
        # Detect depletion (depth went from >0 to 0)
        if state.last_depth > 0 and current_depth == 0:
            state.depletion_start_ts = time.time()
            logger.debug(
                f"[REFILL-DETECTOR] {ob.ticker} {side.upper()} depleted at {state.depletion_start_ts}"
            )
        
        # Detect refill (depth went from 0 to >0)
        elif state.last_depth == 0 and current_depth > 0:
            refill_ts = time.time()
            
            # If we have a depletion timestamp, use it
            # Otherwise, this is the first snapshot with depth (no refill event)
            if state.depletion_start_ts is not None:
                refill_time_ms = (refill_ts - state.depletion_start_ts) * 1000.0
                
                # Classify as toxic if refill was slow
                is_toxic = refill_time_ms > self.toxic_threshold_ms
                
                event = RefillEvent(
                    ticker=ob.ticker,
                    side=side,
                    depletion_ts=state.depletion_start_ts,
                    refill_ts=refill_ts,
                    refill_time_ms=refill_time_ms,
                    is_toxic=is_toxic,
                )
                
                # Update state
                state.recent_refill_times.append(refill_time_ms)
                state.total_event_count += 1
                if is_toxic:
                    state.toxic_event_count += 1
                
                # Log the event
                if is_toxic:
                    logger.warning(
                        f"[REFILL-DETECTOR] {ob.ticker} {side.upper()} TOXIC refill: "
                        f"{refill_time_ms:.0f}ms > {self.toxic_threshold_ms}ms threshold"
                    )
                else:
                    logger.debug(
                        f"[REFILL-DETECTOR] {ob.ticker} {side.upper()} safe refill: "
                        f"{refill_time_ms:.0f}ms"
                    )
                
                # Reset depletion tracking
                state.depletion_start_ts = None
            else:
                # No depletion timestamp - this is the first snapshot with depth
                # Don't create an event, just update the depth
                pass
        
        # Update last depth
        state.last_depth = current_depth
        
        # Determine if current state is toxic based on recent history
        # If we have enough samples and high toxic ratio, mark as toxic
        if len(state.recent_refill_times) >= self.min_samples:
            toxic_ratio = state.toxic_event_count / state.total_event_count
            if toxic_ratio > 0.5:  # More than 50% of refills are toxic
                is_toxic = True
        
        return is_toxic, event
    
    def get_refill_stats(self, ticker: str, side: str) -> dict:
        """Get refill statistics for a market/side."""
        state = self._get_state(ticker, side)
        
        if not state.recent_refill_times:
            return {
                "ticker": ticker,
                "side": side,
                "sample_count": 0,
                "avg_refill_time_ms": None,
                "toxic_ratio": None,
            }
        
        avg_refill_time = sum(state.recent_refill_times) / len(state.recent_refill_times)
        toxic_ratio = state.toxic_event_count / state.total_event_count if state.total_event_count > 0 else 0.0
        
        return {
            "ticker": ticker,
            "side": side,
            "sample_count": len(state.recent_refill_times),
            "avg_refill_time_ms": avg_refill_time,
            "toxic_ratio": toxic_ratio,
            "total_events": state.total_event_count,
            "toxic_events": state.toxic_event_count,
        }
    
    def get_recent_events(self, limit: int = 10) -> list:
        """Get recent refill events."""
        return [e.to_dict() for e in list(self._event_history)[-limit:]]
