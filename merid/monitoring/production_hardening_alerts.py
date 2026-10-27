"""
Production Hardening Monitoring & Alerts

Monitors for bypass attempts, unauthorized execution paths, and policy violations.
Part of Phase 6: Testing, verification, and hardening.
"""

import os
import time
import logging
from typing import Optional, Dict, Any, Set
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict

logger = logging.getLogger("merid.monitoring.hardening")


@dataclass
class BypassAlert:
    """Alert for potential execution bypass attempt."""
    timestamp: float
    alert_type: str
    component: str
    details: Dict[str, Any]
    severity: str = "critical"  # critical, warning, info


class ProductionHardeningMonitor:
    """
    Monitors the trading system for policy violations and bypass attempts.

    Responsibilities:
    - Track all order submissions by source and path
    - Alert on attempts to use disabled/bypass components
    - Monitor Top-3 batch gate enforcement
    - Track GlobalRiskGuard rejections
    - Alert on direct HTTP client instantiation
    """

    def __init__(self):
        self._alerts: list[BypassAlert] = []
        self._order_counts_by_source: Dict[str, int] = defaultdict(int)
        self._rejection_counts_by_reason: Dict[str, int] = defaultdict(int)
        self._last_reset_time = time.time()
        self._disabled_components: Set[str] = {"merid.kalshi.maker_bot_advanced"}
        self._canonical_path_only: bool = True

    def record_order_submission(
        self,
        source: str,
        path: str,  # "order_router", "direct_client", "bypass"
        ticker: str,
        action: str,
        caller: Optional[str] = None,
    ) -> None:
        """Record an order submission for monitoring.

        Args:
            source: Component submitting the order (e.g., "kalshi_continuous_trader")
            path: Execution path used (should always be "order_router")
            ticker: Market ticker
            action: "buy" or "sell"
            caller: Module path of caller
        """
        self._order_counts_by_source[source] += 1

        # Alert on non-canonical paths
        if path != "order_router":
            self._alert(
                "NON_CANONICAL_PATH",
                source,
                {"path": path, "ticker": ticker, "action": action, "caller": caller},
                "critical",
            )

        # Alert on disabled component usage attempt
        if source in self._disabled_components:
            self._alert(
                "DISABLED_COMPONENT_USAGE",
                source,
                {"ticker": ticker, "action": action, "caller": caller},
                "critical",
            )

    def record_gate_rejection(
        self,
        gate_type: str,  # "top3_batch", "global_risk_guard", "pre_trade", "sentiment_cap"
        ticker: str,
        reason: str,
        caller: Optional[str] = None,
    ) -> None:
        """Record a gate rejection.

        These are expected in normal operation - we track them for monitoring.
        """
        self._rejection_counts_by_reason[gate_type] += 1

        # Log for audit trail
        logger.info(
            "[HARDENING] Gate rejection: %s | ticker=%s | reason=%s | caller=%s",
            gate_type, ticker, reason, caller,
        )

    def record_bypass_attempt(
        self,
        component: str,
        bypass_type: str,  # "direct_http", "shadow_order", "legacy_client"
        details: Dict[str, Any],
    ) -> None:
        """Record an explicit bypass attempt.

        This is a critical security event requiring immediate attention.
        """
        self._alert(
            "BYPASS_ATTEMPT",
            component,
            {"bypass_type": bypass_type, **details},
            "critical",
        )

        # Log with stack trace for forensics
        logger.critical(
            "[HARDENING] BYPASS ATTEMPT DETECTED: component=%s, type=%s, details=%s",
            component, bypass_type, details,
            exc_info=True,
        )

    def check_disabled_component_import(self, module_name: str) -> bool:
        """Check if a module import should be blocked.

        Returns True if import should be allowed, False if blocked.
        """
        if module_name in self._disabled_components:
            # Check for explicit override
            env_var = f"MERID_ALLOW_{module_name.split('.')[-1].upper()}"
            if os.getenv(env_var, "").lower() in ("1", "true", "yes"):
                logger.warning(
                    "[HARDENING] Disabled component import allowed via %s: %s",
                    env_var, module_name,
                )
                return True

            logger.critical(
                "[HARDENING] BLOCKED import of disabled component: %s. "
                "Set %s=1 to override (not recommended).",
                module_name, env_var,
            )
            return False

        return True

    def get_metrics(self) -> Dict[str, Any]:
        """Get current hardening metrics."""
        return {
            "order_counts_by_source": dict(self._order_counts_by_source),
            "rejection_counts_by_reason": dict(self._rejection_counts_by_reason),
            "total_alerts": len(self._alerts),
            "critical_alerts": len([a for a in self._alerts if a.severity == "critical"]),
            "monitoring_uptime_seconds": time.time() - self._last_reset_time,
        }

    def reset_metrics(self) -> None:
        """Reset all counters (use with caution)."""
        self._order_counts_by_source.clear()
        self._rejection_counts_by_reason.clear()
        self._last_reset_time = time.time()

    def _alert(
        self,
        alert_type: str,
        component: str,
        details: Dict[str, Any],
        severity: str = "warning",
    ) -> None:
        """Create and store an alert."""
        alert = BypassAlert(
            timestamp=time.time(),
            alert_type=alert_type,
            component=component,
            details=details,
            severity=severity,
        )
        self._alerts.append(alert)

        # Log immediately
        log_func = logger.critical if severity == "critical" else (
            logger.warning if severity == "warning" else logger.info
        )
        log_func(
            "[HARDENING-ALERT] type=%s component=%s severity=%s details=%s",
            alert_type, component, severity, details,
        )


# Singleton instance
_monitor: Optional[ProductionHardeningMonitor] = None


def get_production_hardening_monitor() -> ProductionHardeningMonitor:
    """Get or create the singleton monitor instance."""
    global _monitor
    if _monitor is None:
        _monitor = ProductionHardeningMonitor()
    return _monitor


# Convenience functions for common monitoring calls
def record_order_submission(
    source: str,
    path: str,
    ticker: str,
    action: str,
    caller: Optional[str] = None,
) -> None:
    """Record an order submission."""
    get_production_hardening_monitor().record_order_submission(
        source, path, ticker, action, caller,
    )


def record_gate_rejection(
    gate_type: str,
    ticker: str,
    reason: str,
    caller: Optional[str] = None,
) -> None:
    """Record a gate rejection."""
    get_production_hardening_monitor().record_gate_rejection(
        gate_type, ticker, reason, caller,
    )


def record_bypass_attempt(
    component: str,
    bypass_type: str,
    details: Dict[str, Any],
) -> None:
    """Record a bypass attempt."""
    get_production_hardening_monitor().record_bypass_attempt(
        component, bypass_type, details,
    )


def check_disabled_component_import(module_name: str) -> bool:
    """Check if module import should be blocked."""
    return get_production_hardening_monitor().check_disabled_component_import(module_name)
