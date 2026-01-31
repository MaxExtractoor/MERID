"""
Clock synchronization monitor for MERID data quality observability.

Tracks NTP drift, timestamp validation, and clock skew across data sources to
ensure time-sensitive operations (execution, MEV defense, arbitrage) operate
on accurate time references.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class ClockDriftMeasurement:
    source: str
    local_timestamp: float
    source_timestamp: float
    drift_ms: float
    measured_at: datetime


@dataclass
class ClockSyncAlert:
    alert_id: str
    source: str
    drift_ms: float
    threshold_ms: float
    severity: str
    detected_at: datetime


class ClockSyncMonitor:
    """
    Monitors clock synchronization and detects drift.
    
    Features:
    - NTP drift tracking
    - Per-source timestamp validation
    - Drift alerts when thresholds exceeded
    - Historical drift tracking
    """
    
    def __init__(self, drift_threshold_ms: float = 100.0):
        self.drift_threshold_ms = drift_threshold_ms
        self._measurements: List[ClockDriftMeasurement] = []
        self._alerts: List[ClockSyncAlert] = []
        self._source_drift: Dict[str, float] = {}
    
    def measure_drift(
        self,
        source: str,
        source_timestamp: float,
        local_timestamp: Optional[float] = None,
    ) -> ClockDriftMeasurement:
        """Measure clock drift between local and source timestamp."""
        local_ts = local_timestamp or time.time()
        drift_ms = abs(local_ts - source_timestamp) * 1000
        
        measurement = ClockDriftMeasurement(
            source=source,
            local_timestamp=local_ts,
            source_timestamp=source_timestamp,
            drift_ms=drift_ms,
            measured_at=datetime.utcnow(),
        )
        
        self._measurements.append(measurement)
        self._source_drift[source] = drift_ms
        
        if drift_ms > self.drift_threshold_ms:
            self._emit_alert(source, drift_ms)
        
        if len(self._measurements) > 10000:
            self._measurements = self._measurements[-5000:]
        
        return measurement
    
    def _emit_alert(self, source: str, drift_ms: float) -> None:
        """Emit clock drift alert."""
        severity = "critical" if drift_ms > 1000 else "high" if drift_ms > 500 else "medium"
        
        alert = ClockSyncAlert(
            alert_id=f"clock_drift_{source}_{int(time.time())}",
            source=source,
            drift_ms=drift_ms,
            threshold_ms=self.drift_threshold_ms,
            severity=severity,
            detected_at=datetime.utcnow(),
        )
        
        self._alerts.append(alert)
        logger.warning(
            f"Clock drift alert: {source} drift={drift_ms:.2f}ms (threshold={self.drift_threshold_ms}ms)"
        )
    
    def get_source_drift(self, source: str) -> Optional[float]:
        """Get latest drift measurement for source."""
        return self._source_drift.get(source)
    
    def get_recent_alerts(self, limit: int = 20) -> List[ClockSyncAlert]:
        """Get recent clock drift alerts."""
        return self._alerts[-limit:]
    
    def validate_timestamp(
        self,
        timestamp: float,
        max_age_seconds: float = 60.0,
        max_future_seconds: float = 5.0,
    ) -> bool:
        """
        Validate timestamp is within acceptable bounds.
        
        Returns True if timestamp is valid (not too old, not too far in future).
        """
        now = time.time()
        age = now - timestamp
        
        if age > max_age_seconds:
            logger.warning(f"Timestamp too old: age={age:.2f}s")
            return False
        
        if age < -max_future_seconds:
            logger.warning(f"Timestamp in future: future={-age:.2f}s")
            return False
        
        return True
    
    def get_sync_status(self) -> Dict[str, object]:
        """Get overall clock sync status."""
        recent_measurements = [
            m for m in self._measurements
            if m.measured_at > datetime.utcnow() - timedelta(minutes=5)
        ]
        
        avg_drift = (
            sum(m.drift_ms for m in recent_measurements) / len(recent_measurements)
            if recent_measurements else 0.0
        )
        
        max_drift = max((m.drift_ms for m in recent_measurements), default=0.0)
        
        return {
            "drift_threshold_ms": self.drift_threshold_ms,
            "sources_tracked": len(self._source_drift),
            "avg_drift_ms": avg_drift,
            "max_drift_ms": max_drift,
            "recent_alerts": len([
                a for a in self._alerts
                if a.detected_at > datetime.utcnow() - timedelta(hours=1)
            ]),
            "total_measurements": len(self._measurements),
        }


_clock_sync_monitor: Optional[ClockSyncMonitor] = None


def get_clock_sync_monitor() -> ClockSyncMonitor:
    """Get global ClockSyncMonitor instance."""
    global _clock_sync_monitor
    if _clock_sync_monitor is None:
        _clock_sync_monitor = ClockSyncMonitor()
    return _clock_sync_monitor
