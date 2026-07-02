"""
Market Data Age Computation Helpers

Centralized, timebase-consistent MD age computation with proper error handling
and status classification. Replaces scattered ad-hoc age calculations.

Used by:
- agent_grid_15m.py (MD-HEALTH-INVARIANT, SIGNAL-GATE)
- loop_15m.py (execution guardrails)
- Any code needing MD age/freshness checks
"""

import time
from dataclasses import dataclass
from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)

# Constants
STALE_THRESHOLD_SECONDS = 120.0  # Default stale threshold (configurable)
MAX_AGE_SECONDS = 3600.0  # Maximum reasonable age (1 hour)
DEBUG_AGE_THRESHOLD = 600.0  # Log debug info for ages > 10 minutes

@dataclass
class MDAgeResult:
    """Result of MD age computation with status classification."""
    age_s: float
    status: str  # "no_data", "fresh", "stale", "impossible"
    reason: str
    now_mono: float
    last_update_mono: float
    
    def is_fresh(self) -> bool:
        return self.status == "fresh"
    
    def is_stale(self) -> bool:
        return self.status in ["stale", "impossible", "no_data"]
    
    def has_data(self) -> bool:
        return self.status != "no_data"

def compute_md_age(state, now_mono: Optional[float] = None, 
                   stale_threshold: float = STALE_THRESHOLD_SECONDS) -> MDAgeResult:
    """
    Compute market data age using consistent monotonic timebase.
    
    Args:
        state: Market state object with last_book_update_ts field
        now_mono: Current monotonic time (uses time.monotonic() if None)
        stale_threshold: Age in seconds to consider data stale
        
    Returns:
        MDAgeResult with age, status, and diagnostic information
        
    Status Categories:
    - "no_data": No state or no timestamp (never received MD)
    - "fresh": Age < stale_threshold and reasonable
    - "stale": Age > stale_threshold but reasonable
    - "impossible": Negative age or age > MAX_AGE_SECONDS
    """
    if now_mono is None:
        now_mono = time.monotonic()
    
    # Case 1: No state at all
    if not state:
        return MDAgeResult(
            age_s=-1.0,
            status="no_data",
            reason="NO_STATE",
            now_mono=now_mono,
            last_update_mono=0.0
        )
    
    # Case 2: State exists but no timestamp field
    if not hasattr(state, 'last_book_update_ts'):
        logger.warning("[MD-AGE-NO-DATA] ticker=unknown state has no last_book_update_ts field")
        return MDAgeResult(
            age_s=-1.0,
            status="no_data",
            reason="NO_TIMESTAMP_FIELD",
            now_mono=now_mono,
            last_update_mono=0.0
        )
    
    # Case 3: Timestamp field exists but never set (zero)
    last_update_mono = state.last_book_update_ts
    if last_update_mono == 0.0:
        logger.info("[MD-AGE-NO-DATA] ticker=unknown never received book updates")
        return MDAgeResult(
            age_s=-1.0,
            status="no_data",
            reason="NEVER_UPDATED",
            now_mono=now_mono,
            last_update_mono=0.0
        )
    
    # Case 4: Compute age with proper monotonic timebase
    age_s = now_mono - last_update_mono
    
    # VERIFICATION: Debug log for large ages to catch timebase regressions
    if abs(age_s) > DEBUG_AGE_THRESHOLD:
        logger.debug(
            "[MD-AGE-DIAGNOSTIC] now_mono=%.3f last_update_mono=%.3f age_s=%.3f "
            "timebase_check=monotonic_vs_monotonic",
            now_mono, last_update_mono, age_s
        )
    
    # Case 5: Check for impossible ages (timebase mismatch or corruption)
    if age_s < 0 or age_s > MAX_AGE_SECONDS:
        logger.error(
            "[MD-HEALTH-INVARIANT] impossible age=%.1fs now=%.1f last_update=%.1f - marking stale",
            age_s, now_mono, last_update_mono
        )
        return MDAgeResult(
            age_s=max(0, min(age_s, MAX_AGE_SECONDS)),  # Clamp for logging
            status="impossible",
            reason=f"IMPOSSIBLE_AGE ({age_s:.1f}s)",
            now_mono=now_mono,
            last_update_mono=last_update_mono
        )
    
    # Case 6: Normal age computation
    if age_s > stale_threshold:
        return MDAgeResult(
            age_s=age_s,
            status="stale",
            reason=f"AGE_{age_s:.1f}s > {stale_threshold}s",
            now_mono=now_mono,
            last_update_mono=last_update_mono
        )
    else:
        return MDAgeResult(
            age_s=age_s,
            status="fresh",
            reason="FRESH",
            now_mono=now_mono,
            last_update_mono=last_update_mono
        )

def validate_md_timebase_consistency(result: MDAgeResult) -> bool:
    """
    Validate that both timestamps are monotonic floats.
    
    Args:
        result: MDAgeResult to validate
        
    Returns:
        True if timebase appears consistent, False otherwise
    """
    # Check that timestamps are finite numbers
    if not (isinstance(result.now_mono, (int, float)) and 
            isinstance(result.last_update_mono, (int, float))):
        return False
    
    if not (math.isfinite(result.now_mono) and math.isfinite(result.last_update_mono)):
        return False
    
    # Check that timestamps are in reasonable range for monotonic time
    # Monotonic time should be < 10^9 (seconds since boot) and > 0
    if not (0 <= result.now_mono < 1_000_000_000 and 
            0 <= result.last_update_mono < 1_000_000_000):
        return False
    
    return True

import math
