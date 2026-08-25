"""
Phantom Detection Rules and Automated Resolution Path

Defines rules for detecting phantom positions (internal has position, external doesn't)
and provides an automated resolution path for handling them.

Phantom positions can occur due to:
- API latency (external position not yet visible)
- Fill ingestion lag (internal fill not yet synced to external)
- API errors (external position query failed)
- Data corruption (position lost in external system)

Resolution Path:
1. Detect phantom position
2. Classify phantom type (latency vs true phantom)
3. Apply resolution strategy (wait, retry, or flag)
4. Track resolution outcome
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime, timedelta, timezone
import logging

logger = logging.getLogger(__name__)


class PhantomType(str, Enum):
    """Types of phantom positions."""
    LATENCY = "latency"  # Temporary lag, will resolve automatically
    TRUE_PHANTOM = "true_phantom"  # Actual discrepancy, requires investigation
    API_ERROR = "api_error"  # External API failed to return position
    INGESTION_LAG = "ingestion_lag"  # Internal fill not yet synced


class ResolutionAction(str, Enum):
    """Automated resolution actions."""
    WAIT = "wait"  # Wait for position to sync (latency case)
    RETRY = "retry"  # Retry external position query
    FLAG = "flag"  # Flag for manual investigation
    IGNORE = "ignore"  # Ignore (safe to skip)


@dataclass
class PhantomPosition:
    """A detected phantom position."""
    
    market_id: str
    internal_yes_qty: int
    internal_no_qty: int
    external_yes_qty: int  # Should be 0 for phantom
    external_no_qty: int   # Should be 0 for phantom
    detected_at: datetime
    last_external_query_time: Optional[datetime] = None
    fill_timestamp: Optional[datetime] = None
    resolution_action: Optional[ResolutionAction] = None
    resolved_at: Optional[datetime] = None
    resolution_notes: Optional[str] = None


@dataclass
class PhantomDetectionConfig:
    """Configuration for phantom detection rules."""
    
    # Time thresholds
    LATENCY_THRESHOLD_SECONDS: int = 60  # Position expected within 60s for 15m crypto
    INGESTION_LAG_THRESHOLD_SECONDS: int = 30  # Fill ingestion expected within 30s
    MAX_WAIT_SECONDS: int = 300  # Max wait before flagging (5 minutes)
    
    # Retry configuration
    MAX_RETRIES: int = 3
    RETRY_DELAY_SECONDS: int = 10
    
    # Classification rules
    AUTO_CLASSIFY_LATENCY: bool = True  # Auto-classify as latency if recent fill
    AUTO_CLASSIFY_API_ERROR: bool = True  # Auto-classify as API error if query failed


class PhantomDetector:
    """Detects and classifies phantom positions."""
    
    def __init__(self, config: Optional[PhantomDetectionConfig] = None):
        self.config = config or PhantomDetectionConfig()
        self._detected_phantoms: Dict[str, PhantomPosition] = {}
    
    def detect_phantom(
        self,
        market_id: str,
        internal_yes_qty: int,
        internal_no_qty: int,
        external_yes_qty: int,
        external_no_qty: int,
        fill_timestamp: Optional[datetime] = None,
        external_query_time: Optional[datetime] = None,
    ) -> Optional[PhantomPosition]:
        """
        Detect if this is a phantom position.
        
        Args:
            market_id: Market identifier
            internal_yes_qty: Internal YES quantity
            internal_no_qty: Internal NO quantity
            external_yes_qty: External YES quantity
            external_no_qty: External NO quantity
            fill_timestamp: Timestamp of the fill that created the position
            external_query_time: Timestamp of the external position query
        
        Returns:
            PhantomPosition if phantom detected, None otherwise
        """
        # Check if this is a phantom (internal has position, external doesn't)
        internal_total = internal_yes_qty + internal_no_qty
        external_total = external_yes_qty + external_no_qty
        
        if internal_total == 0:
            # No internal position, not a phantom
            return None
        
        if external_total > 0:
            # External has position, not a phantom
            return None
        
        # This is a phantom position
        phantom = PhantomPosition(
            market_id=market_id,
            internal_yes_qty=internal_yes_qty,
            internal_no_qty=internal_no_qty,
            external_yes_qty=external_yes_qty,
            external_no_qty=external_no_qty,
            detected_at=datetime.now(timezone.utc),
            last_external_query_time=external_query_time or datetime.now(timezone.utc),
            fill_timestamp=fill_timestamp,
        )
        
        # Classify phantom type
        phantom.resolution_action = self._classify_and_resolve(phantom)
        
        # Track phantom
        self._detected_phantoms[market_id] = phantom
        
        return phantom
    
    def _classify_and_resolve(self, phantom: PhantomPosition) -> ResolutionAction:
        """
        Classify phantom type and determine resolution action.
        
        Args:
            phantom: Detected phantom position
        
        Returns:
            ResolutionAction: Automated resolution action
        """
        now = datetime.now(timezone.utc)
        
        # Check for recent fill (latency case)
        if phantom.fill_timestamp:
            time_since_fill = (now - phantom.fill_timestamp).total_seconds()
            if time_since_fill < self.config.LATENCY_THRESHOLD_SECONDS:
                logger.debug(
                    f"Phantom position {phantom.market_id} classified as LATENCY "
                    f"(fill {time_since_fill:.0f}s ago)"
                )
                return ResolutionAction.WAIT
        
        # Check for recent external query (API error case)
        if phantom.last_external_query_time:
            time_since_query = (now - phantom.last_external_query_time).total_seconds()
            if time_since_query < self.config.INGESTION_LAG_THRESHOLD_SECONDS:
                logger.debug(
                    f"Phantom position {phantom.market_id} classified as API_ERROR "
                    f"(query {time_since_query:.0f}s ago)"
                )
                return ResolutionAction.RETRY
        
        # Check if we've waited too long
        if phantom.fill_timestamp:
            time_since_fill = (now - phantom.fill_timestamp).total_seconds()
            if time_since_fill > self.config.MAX_WAIT_SECONDS:
                logger.warning(
                    f"Phantom position {phantom.market_id} classified as TRUE_PHANTOM "
                    f"(fill {time_since_fill:.0f}s ago, exceeded threshold)"
                )
                return ResolutionAction.FLAG
        
        # Default: wait for sync
        return ResolutionAction.WAIT
    
    def resolve_phantom(
        self,
        market_id: str,
        resolution_action: ResolutionAction,
        notes: Optional[str] = None,
    ) -> bool:
        """
        Mark a phantom as resolved.
        
        Args:
            market_id: Market identifier
            resolution_action: Resolution action taken
            notes: Optional notes about resolution
        
        Returns:
            bool: True if phantom was resolved, False if not found
        """
        if market_id not in self._detected_phantoms:
            return False
        
        phantom = self._detected_phantoms[market_id]
        phantom.resolution_action = resolution_action
        phantom.resolved_at = datetime.now(timezone.utc)
        phantom.resolution_notes = notes
        
        logger.info(
            f"Phantom position {market_id} resolved with action {resolution_action.value}"
        )
        
        # Remove from active tracking
        del self._detected_phantoms[market_id]
        
        return True
    
    def get_active_phantoms(self) -> List[PhantomPosition]:
        """Get all currently active (unresolved) phantom positions."""
        return list(self._detected_phantoms.values())
    
    def get_phantom_summary(self) -> Dict[str, Any]:
        """Get summary of phantom detection activity."""
        active = self.get_active_phantoms()
        
        # Count by resolution action
        action_counts = {}
        for phantom in active:
            action = phantom.resolution_action.value if phantom.resolution_action else "pending"
            action_counts[action] = action_counts.get(action, 0) + 1
        
        return {
            "active_phantoms": len(active),
            "action_counts": action_counts,
            "phantoms": [
                {
                    "market_id": p.market_id,
                    "internal_qty": p.internal_yes_qty + p.internal_no_qty,
                    "detected_at": p.detected_at.isoformat(),
                    "action": p.resolution_action.value if p.resolution_action else "pending",
                }
                for p in active
            ],
        }


def automated_resolution_path(
    phantom: PhantomPosition,
    config: Optional[PhantomDetectionConfig] = None,
) -> Dict[str, Any]:
    """
    Execute automated resolution path for a phantom position.
    
    Args:
        phantom: Detected phantom position
        config: Optional configuration
    
    Returns:
        Dict with resolution steps and outcome
    """
    if config is None:
        config = PhantomDetectionConfig()
    
    steps = []
    detector = PhantomDetector(config)
    
    # Step 1: Classify phantom type
    action = detector._classify_and_resolve(phantom)
    steps.append({"step": "classify", "action": action.value})
    
    # Step 2: Execute resolution action
    if action == ResolutionAction.WAIT:
        steps.append({"step": "wait", "details": "Waiting for position to sync"})
        outcome = "waiting"
    
    elif action == ResolutionAction.RETRY:
        steps.append({"step": "retry", "details": "Retry external position query"})
        outcome = "retrying"
    
    elif action == ResolutionAction.FLAG:
        steps.append({"step": "flag", "details": "Flagged for manual investigation"})
        outcome = "flagged"
    
    elif action == ResolutionAction.IGNORE:
        steps.append({"step": "ignore", "details": "Ignored (safe to skip)"})
        outcome = "ignored"
    
    else:
        steps.append({"step": "unknown", "details": "Unknown action"})
        outcome = "unknown"
    
    return {
        "phantom_market_id": phantom.market_id,
        "resolution_action": action.value,
        "steps": steps,
        "outcome": outcome,
    }
