"""Dependency Health Model — aggregated health of all external dependencies.

Provides a unified view of dependency health that feeds into:
  1. Execution gate (check 5: dependency health)
  2. Kill switch (auto-trigger on critical dependency loss)
  3. /system/health API endpoint

Each dependency probe returns a DependencyStatus with:
  - name, status (healthy/degraded/down/unchecked), last_check, details

Usage:
    from core.dependency_health import check_all_dependencies, get_dependency_summary
    
    summary = check_all_dependencies()
    if summary["any_critical_down"]:
        # Block execution
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("core.dependency_health")


class DepStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    UNCHECKED = "unchecked"


@dataclass
class DependencyStatus:
    """Health status of a single dependency."""
    name: str
    status: DepStatus = DepStatus.UNCHECKED
    critical: bool = False  # If True, DOWN status blocks execution gate
    last_check: float = 0.0
    message: str = ""
    details: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "critical": self.critical,
            "last_check": self.last_check,
            "message": self.message,
            "details": self.details or {},
        }


# ── Dependency probes ──────────────────────────────────────────────────

def _probe_neo4j() -> DependencyStatus:
    """Check Neo4j graph database connectivity."""
    dep = DependencyStatus(name="neo4j", critical=False)
    try:
        from memory.neo4j_graph import get_neo4j_graph, is_neo4j_available
        if is_neo4j_available():
            dep.status = DepStatus.HEALTHY
            dep.message = "Connected"
        else:
            dep.status = DepStatus.DOWN
            dep.message = "Unavailable — running without graph memory"
    except ImportError:
        dep.status = DepStatus.DOWN
        dep.message = "neo4j package not installed"
    except Exception as exc:
        dep.status = DepStatus.DOWN
        dep.message = str(exc)[:200]
    dep.last_check = time.time()
    return dep


def _probe_twitter() -> DependencyStatus:
    """Check Twitter/X agent health.
    
    SOCIAL-TRUTH (2026-05-13): Twitter agent disabled for lean 15m Kalshi trading.
    Returns DOWN status to indicate disabled.
    """
    dep = DependencyStatus(name="twitter", critical=False)
    dep.status = DepStatus.DOWN
    dep.message = "Twitter agent disabled for lean 15m Kalshi stack"
    dep.last_check = time.time()
    return dep


def _probe_smtp() -> DependencyStatus:
    """Check SMTP/email notification channel configuration."""
    dep = DependencyStatus(name="smtp_email", critical=False)
    try:
        from notifications.channels import get_channel_manager, ChannelType
        mgr = get_channel_manager()
        email_ch = mgr.get_channel(ChannelType.EMAIL)
        if email_ch is None:
            dep.status = DepStatus.DOWN
            dep.message = "Email channel not registered"
        elif not email_ch.enabled:
            dep.status = DepStatus.DOWN
            dep.message = "Email channel disabled"
        elif not getattr(email_ch, "smtp_host", ""):
            dep.status = DepStatus.DEGRADED
            dep.message = "SMTP not configured — emails will be simulated"
        else:
            dep.status = DepStatus.HEALTHY
            dep.message = f"SMTP configured: {email_ch.smtp_host}:{email_ch.smtp_port}"
    except ImportError:
        dep.status = DepStatus.DOWN
        dep.message = "Notification channels module not available"
    except Exception as exc:
        dep.status = DepStatus.DOWN
        dep.message = str(exc)[:200]
    dep.last_check = time.time()
    return dep


def _probe_kalshi_client() -> DependencyStatus:
    """Check Kalshi REST client connectivity."""
    dep = DependencyStatus(name="kalshi_client", critical=True)
    try:
        from merid.event_venues.kalshi.client import get_kalshi_client
        client = get_kalshi_client()
        if client is None:
            dep.status = DepStatus.DOWN
            dep.message = "Kalshi client not initialized"
        elif hasattr(client, "_circuit_open") and client._circuit_open:
            dep.status = DepStatus.DEGRADED
            dep.message = "Kalshi client circuit breaker OPEN"
        else:
            dep.status = DepStatus.HEALTHY
            dep.message = "Kalshi client available"
    except ImportError:
        dep.status = DepStatus.DOWN
        dep.message = "Kalshi client module not available"
    except Exception as exc:
        dep.status = DepStatus.DOWN
        dep.message = str(exc)[:200]
    dep.last_check = time.time()
    return dep


def _probe_kalshi_ws() -> DependencyStatus:
    """Check Kalshi WebSocket bridge status."""
    dep = DependencyStatus(name="kalshi_websocket", critical=False)
    try:
        from merid.event_venues.kalshi.ws_bridge import get_ws_bridge
        bridge = get_ws_bridge()
        if bridge is None:
            dep.status = DepStatus.DOWN
            dep.message = "WebSocket bridge not initialized"
        elif bridge.is_running():
            # Check underlying WS connection state
            ws = getattr(bridge, "_ws", None)
            if ws and getattr(ws, "_running", False):
                dep.status = DepStatus.HEALTHY
                dep.message = "WebSocket connected and running"
            else:
                dep.status = DepStatus.DEGRADED
                dep.message = "Bridge running but underlying WS not connected"
        else:
            dep.status = DepStatus.DEGRADED
            dep.message = "WebSocket bridge not running — HTTP fallback active"
    except ImportError:
        dep.status = DepStatus.DOWN
        dep.message = "WebSocket bridge module not available"
    except Exception as exc:
        dep.status = DepStatus.DEGRADED
        dep.message = str(exc)[:200]
    dep.last_check = time.time()
    return dep


def _probe_market_catalog() -> DependencyStatus:
    """Check Kalshi market catalog availability."""
    dep = DependencyStatus(name="market_catalog", critical=True)
    try:
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        catalog = get_market_catalog()
        if catalog is None:
            dep.status = DepStatus.DOWN
            dep.message = "Market catalog not initialized"
        elif len(catalog._markets) > 0:
            dep.status = DepStatus.HEALTHY
            dep.message = f"{len(catalog._markets)} markets cached"
        else:
            dep.status = DepStatus.DEGRADED
            dep.message = "Market catalog empty — awaiting first refresh"
    except ImportError:
        dep.status = DepStatus.DOWN
        dep.message = "Market catalog module not available"
    except Exception as exc:
        dep.status = DepStatus.DOWN
        dep.message = str(exc)[:200]
    dep.last_check = time.time()
    return dep


def _probe_fills_ledger() -> DependencyStatus:
    """Check fills ledger health."""
    dep = DependencyStatus(name="fills_ledger", critical=True)
    try:
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        ledger = get_fills_ledger()
        summary = ledger.summary()
        recon = summary.get("reconciliation", {})
        recon_status = recon.get("status", "unknown")

        if recon_status == "broken":
            dep.status = DepStatus.DEGRADED
            dep.message = f"Reconciliation BROKEN — {recon.get('divergence_count', 0)} divergences"
        elif recon_status == "degraded":
            dep.status = DepStatus.DEGRADED
            dep.message = f"Reconciliation degraded — {recon.get('divergence_count', 0)} divergences"
        else:
            dep.status = DepStatus.HEALTHY
            dep.message = f"{summary.get('fills_total', 0)} fills tracked"
        dep.details = {"fills_total": summary.get("fills_total", 0), "reconciliation_status": recon_status}
    except Exception as exc:
        dep.status = DepStatus.DOWN
        dep.message = str(exc)[:200]
    dep.last_check = time.time()
    return dep


# ── Registry ───────────────────────────────────────────────────────────

_PROBES: List[Callable[[], DependencyStatus]] = [
    _probe_neo4j,
    _probe_twitter,
    _probe_smtp,
    _probe_kalshi_client,
    _probe_kalshi_ws,
    _probe_market_catalog,
    _probe_fills_ledger,
]

# Cache of last results
_last_results: Dict[str, DependencyStatus] = {}
_results_lock = threading.Lock()
_MIN_CHECK_INTERVAL = 10.0  # Don't re-check more than once per 10s


def check_all_dependencies(force: bool = False) -> Dict[str, Any]:
    """Run all dependency probes and return aggregated summary.

    Returns:
        dict with keys: dependencies (list), any_critical_down, healthy_count,
        degraded_count, down_count, timestamp
    """
    global _last_results
    now = time.time()

    with _results_lock:
        results: List[DependencyStatus] = []
        for probe in _PROBES:
            try:
                cached = _last_results.get(probe.__name__)
                if not force and cached and (now - cached.last_check) < _MIN_CHECK_INTERVAL:
                    results.append(cached)
                    continue
                dep = probe()
                _last_results[probe.__name__] = dep
                results.append(dep)
            except Exception as exc:
                logger.warning("Dependency probe %s failed: %s", probe.__name__, exc)
                results.append(DependencyStatus(
                    name=probe.__name__.replace("_probe_", ""),
                    status=DepStatus.DOWN,
                    message=f"Probe error: {exc}",
                    last_check=now,
                ))

    any_critical_down = any(
        d.status == DepStatus.DOWN and d.critical for d in results
    )
    healthy = sum(1 for d in results if d.status == DepStatus.HEALTHY)
    degraded = sum(1 for d in results if d.status == DepStatus.DEGRADED)
    down = sum(1 for d in results if d.status == DepStatus.DOWN)

    return {
        "dependencies": [d.to_dict() for d in results],
        "any_critical_down": any_critical_down,
        "healthy_count": healthy,
        "degraded_count": degraded,
        "down_count": down,
        "total": len(results),
        "timestamp": now,
    }


def get_dependency_summary() -> Dict[str, Any]:
    """Get cached dependency summary without forcing re-check."""
    return check_all_dependencies(force=False)


def get_dependency_status(name: str) -> Optional[DependencyStatus]:
    """Get status of a specific dependency by name."""
    with _results_lock:
        for dep in _last_results.values():
            if dep.name == name:
                return dep
    return None
