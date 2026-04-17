"""Quorum Failure Tracker — Prevents event storms from persistent quorum failures

Addresses Finding 6.2: Event storm risk on persistent QUORUM_FAILED conditions.

Tracks quorum failures per asset/timeframe and throttles alerts to prevent:
- Alert fatigue from repeated quorum failures
- Event bus overload from retry loops
- Duplicate governance actions

Usage:
    from agents.quorum_failure_tracker import get_quorum_failure_tracker
    
    # Check if we should alert on quorum failure
    should_alert = tracker.record_failure("BTC", "15m", "consensus")
    if should_alert:
        await alert_manager.alert(...)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict

from utils.logger import get_logger

logger = get_logger("agents.quorum_failure_tracker")


@dataclass
class QuorumFailureRecord:
    """Record of a quorum failure occurrence."""
    asset: str
    timeframe: str
    decision_type: str
    first_failure: float
    last_failure: float
    count: int = 1
    consecutive_failures: int = 1
    agents_available: List[str] = field(default_factory=list)
    agents_required: int = 0


class QuorumFailureTracker:
    """
    Tracks quorum failures to prevent event storms and enable throttling.
    
    Features:
    - Per-asset/timeframe failure tracking
    - Exponential backoff for repeated failures
    - Automatic recovery detection
    - Summary alerts for persistent failures
    """
    
    def __init__(
        self,
        alert_cooldown_seconds: float = 60.0,
        summary_threshold: int = 10,
        max_history: int = 1000,
    ):
        self._failures: Dict[Tuple[str, str, str], QuorumFailureRecord] = {}
        self._alert_cooldown = alert_cooldown_seconds
        self._summary_threshold = summary_threshold
        self._max_history = max_history
        
        # Track last alert time per key
        self._last_alert_time: Dict[Tuple[str, str, str], float] = {}
        
        # Track recovery events
        self._recovery_events: List[Dict] = []
    
    def record_failure(
        self,
        asset: str,
        timeframe: str,
        decision_type: str,
        agents_available: Optional[List[str]] = None,
        agents_required: int = 0,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Record a quorum failure and determine if alert should fire.
        
        Args:
            asset: Asset symbol (BTC, ETH, etc.)
            timeframe: Timeframe (15m, 1h, etc.)
            decision_type: Type of decision (consensus, governance, etc.)
            agents_available: List of agent IDs that were available
            agents_required: Number of agents required for quorum
        
        Returns:
            Tuple of (should_alert, context_dict)
            - should_alert: True if this failure should trigger an alert
            - context: Dict with failure statistics and recommendations
        """
        key = (asset.upper(), timeframe.lower(), decision_type)
        now = time.time()
        
        if key not in self._failures:
            # First failure for this combination
            self._failures[key] = QuorumFailureRecord(
                asset=asset.upper(),
                timeframe=timeframe.lower(),
                decision_type=decision_type,
                first_failure=now,
                last_failure=now,
                count=1,
                consecutive_failures=1,
                agents_available=agents_available or [],
                agents_required=agents_required,
            )
            self._last_alert_time[key] = now
            
            return True, {
                "is_new": True,
                "consecutive_count": 1,
                "duration_seconds": 0,
                "recommendation": "initial_alert",
            }
        
        record = self._failures[key]
        record.count += 1
        record.consecutive_failures += 1
        record.last_failure = now
        record.agents_available = agents_available or record.agents_available
        record.agents_required = agents_required or record.agents_required
        
        duration = now - record.first_failure
        
        # Check if we should send an alert (throttling logic)
        last_alert = self._last_alert_time.get(key, 0)
        time_since_last_alert = now - last_alert
        
        # Calculate dynamic cooldown based on consecutive failures
        # More failures = longer cooldown to prevent spam
        dynamic_cooldown = self._alert_cooldown * (1 + record.consecutive_failures // 5)
        
        should_alert = time_since_last_alert >= dynamic_cooldown
        
        if should_alert:
            self._last_alert_time[key] = now
        
        # Determine recommendation
        if record.consecutive_failures >= self._summary_threshold:
            recommendation = "send_summary"
        elif record.consecutive_failures >= 5:
            recommendation = "escalate"
        else:
            recommendation = "standard_alert"
        
        return should_alert, {
            "is_new": False,
            "consecutive_count": record.consecutive_failures,
            "total_count": record.count,
            "duration_seconds": duration,
            "duration_minutes": duration / 60,
            "time_since_last_alert_seconds": time_since_last_alert,
            "dynamic_cooldown_seconds": dynamic_cooldown,
            "agents_available": len(record.agents_available),
            "agents_required": record.agents_required,
            "recommendation": recommendation,
        }
    
    def record_recovery(
        self,
        asset: str,
        timeframe: str,
        decision_type: str,
        agents_now_available: List[str],
    ) -> Optional[Dict[str, Any]]:
        """
        Record quorum recovery after failure.
        
        Returns:
            Recovery stats if there was a previous failure, None otherwise
        """
        key = (asset.upper(), timeframe.lower(), decision_type)
        
        if key not in self._failures:
            return None
        
        record = self._failures[key]
        now = time.time()
        
        recovery_info = {
            "asset": asset.upper(),
            "timeframe": timeframe.lower(),
            "decision_type": decision_type,
            "failure_count": record.count,
            "consecutive_failures": record.consecutive_failures,
            "failure_duration_seconds": now - record.first_failure,
            "failure_duration_minutes": (now - record.first_failure) / 60,
            "agents_available_before": len(record.agents_available),
            "agents_available_after": len(agents_now_available),
            "recovered_at": now,
        }
        
        self._recovery_events.append(recovery_info)
        
        # Trim recovery history
        if len(self._recovery_events) > self._max_history:
            self._recovery_events = self._recovery_events[-(self._max_history // 2):]
        
        # Clear the failure record
        del self._failures[key]
        if key in self._last_alert_time:
            del self._last_alert_time[key]
        
        logger.info(
            f"Quorum recovered for {asset}-{timeframe} {decision_type}: "
            f"{recovery_info['failure_count']} failures over "
            f"{recovery_info['failure_duration_minutes']:.1f}min"
        )
        
        return recovery_info
    
    def get_failure_report(
        self,
        asset: Optional[str] = None,
        timeframe: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get current failure status for asset/timeframe.
        
        Returns:
            Dict with active failures and statistics
        """
        active_failures = []
        now = time.time()
        
        for key, record in self._failures.items():
            key_asset, key_timeframe, key_type = key
            
            # Filter by asset/timeframe if specified
            if asset and key_asset != asset.upper():
                continue
            if timeframe and key_timeframe != timeframe.lower():
                continue
            
            active_failures.append({
                "asset": key_asset,
                "timeframe": key_timeframe,
                "decision_type": key_type,
                "consecutive_failures": record.consecutive_failures,
                "total_failures": record.count,
                "duration_seconds": now - record.first_failure,
                "duration_minutes": (now - record.first_failure) / 60,
                "agents_available": len(record.agents_available),
                "agents_required": record.agents_required,
            })
        
        # Sort by severity (most consecutive failures first)
        active_failures.sort(key=lambda x: x["consecutive_failures"], reverse=True)
        
        return {
            "generated_at": now,
            "total_active_failures": len(active_failures),
            "by_asset": self._group_by_asset(active_failures),
            "by_timeframe": self._group_by_timeframe(active_failures),
            "most_critical": active_failures[:5] if active_failures else [],
            "recent_recoveries": self._recovery_events[-5:],
        }
    
    def _group_by_asset(self, failures: List[Dict]) -> Dict[str, int]:
        """Group failures by asset."""
        counts = defaultdict(int)
        for f in failures:
            counts[f["asset"]] += f["consecutive_failures"]
        return dict(counts)
    
    def _group_by_timeframe(self, failures: List[Dict]) -> Dict[str, int]:
        """Group failures by timeframe."""
        counts = defaultdict(int)
        for f in failures:
            counts[f["timeframe"]] += f["consecutive_failures"]
        return dict(counts)
    
    def should_throttle(
        self,
        asset: str,
        timeframe: str,
        decision_type: str,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Check if alert/action should be throttled for this asset/timeframe.
        
        Returns:
            Tuple of (should_throttle, context)
        """
        key = (asset.upper(), timeframe.lower(), decision_type)
        
        if key not in self._failures:
            return False, {"status": "no_active_failure"}
        
        record = self._failures[key]
        now = time.time()
        last_alert = self._last_alert_time.get(key, 0)
        
        dynamic_cooldown = self._alert_cooldown * (1 + record.consecutive_failures // 5)
        time_since_last = now - last_alert
        
        should_throttle = time_since_last < dynamic_cooldown
        
        return should_throttle, {
            "status": "active_failure",
            "should_throttle": should_throttle,
            "consecutive_failures": record.consecutive_failures,
            "time_since_last_alert_seconds": time_since_last,
            "cooldown_seconds": dynamic_cooldown,
            "seconds_until_next_alert": max(0, dynamic_cooldown - time_since_last),
        }
    
    def get_throttling_summary(self) -> Dict[str, Any]:
        """Get summary of all throttled alerts."""
        throttled = []
        now = time.time()
        
        for key in self._failures:
            is_throttled, context = self.should_throttle(key[0], key[1], key[2])
            if is_throttled:
                throttled.append({
                    "asset": key[0],
                    "timeframe": key[1],
                    "decision_type": key[2],
                    **context,
                })
        
        return {
            "total_throttled": len(throttled),
            "throttled_alerts": throttled,
            "total_active_failures": len(self._failures),
        }


# Global instance
_quorum_failure_tracker: Optional[QuorumFailureTracker] = None


def get_quorum_failure_tracker() -> QuorumFailureTracker:
    """Get global quorum failure tracker."""
    global _quorum_failure_tracker
    if _quorum_failure_tracker is None:
        _quorum_failure_tracker = QuorumFailureTracker()
    return _quorum_failure_tracker


def reset_quorum_failure_tracker() -> None:
    """Reset global tracker (testing only)."""
    global _quorum_failure_tracker
    _quorum_failure_tracker = None
