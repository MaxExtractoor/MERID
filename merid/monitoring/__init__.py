"""MERID Monitoring Module.

Provides monitoring and alerting capabilities:
- Heartbeat monitoring with alerting
- Integrity monitoring
- Health snapshots
- Drift metrics
- Rejection monitoring
- Production hardening alerts

Usage:
    from merid.monitoring import get_heartbeat_monitor
    
    heartbeat = get_heartbeat_monitor()
    await heartbeat.start()
"""

from merid.monitoring.heartbeat_monitor import (
    HeartbeatMonitor,
    AlertManager,
    Alert,
    AlertSeverity,
    AlertChannel,
    get_heartbeat_monitor,
)
from merid.monitoring.integrity_monitor import (
    start_integrity_monitoring,
    stop_integrity_monitoring,
)

__all__ = [
    # Heartbeat monitoring
    "HeartbeatMonitor",
    "AlertManager",
    "Alert",
    "AlertSeverity",
    "AlertChannel",
    "get_heartbeat_monitor",
    # Integrity monitoring
    "start_integrity_monitoring",
    "stop_integrity_monitoring",
]
