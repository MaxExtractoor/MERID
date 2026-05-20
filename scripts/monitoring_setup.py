"""Monitoring setup for Kalshi 15m crypto go-live.

This script integrates all health monitoring components:
- Kalshi API health (error rates, latency)
- RestingOrderMonitor health (poll loop liveness, missing data)
- Scope violation monitoring (universe drift detection)

Usage:
    from scripts.monitoring_setup import run_all_health_checks
    
    # Run all health checks
    health_report = run_all_health_checks()
    print(health_report)
    
    # Or integrate into a monitoring loop
    import asyncio
    asyncio.run(monitoring_loop())
"""

import asyncio
from datetime import datetime
from typing import Dict, Any, Optional
from utils.logger import get_logger

logger = get_logger("scripts.monitoring_setup")


def run_all_health_checks() -> Dict[str, Any]:
    """Run all health checks and return a consolidated report.
    
    Returns:
        Dict with health status for all monitoring components
    """
    report = {
        "timestamp": datetime.utcnow().isoformat(),
        "checks": {},
        "overall_status": "healthy"
    }
    
    # 1. Kalshi API Health
    try:
        from merid.event_venues.kalshi.api_health_monitor import get_kalshi_api_health_monitor
        
        api_monitor = get_kalshi_api_health_monitor()
        api_health = api_monitor.check_all_endpoints()
        
        # check_all_endpoints() returns a dict, not a HealthCheckResult object
        if isinstance(api_health, dict):
            is_healthy = all(
                endpoint_result.get("healthy", False) 
                for endpoint_result in api_health.values()
            )
            report["checks"]["api_health"] = {
                "status": "healthy" if is_healthy else "degraded",
                "details": api_health
            }
        else:
            # Fallback for older interface
            report["checks"]["api_health"] = {
                "status": "healthy" if getattr(api_health, "healthy", False) else "degraded",
                "details": api_health.summary if hasattr(api_health, "summary") else str(api_health)
            }
        
        if report["checks"]["api_health"]["status"] != "healthy":
            report["overall_status"] = "degraded"
            logger.warning(f"API health degraded: {api_health}")
        
        # Log health summary
        try:
            api_monitor.log_health_summary()
        except Exception as e:
            logger.debug(f"Could not log API health summary: {e}")
        
    except Exception as e:
        logger.error(f"Failed to check API health: {e}")
        report["checks"]["api_health"] = {
            "status": "error",
            "error": str(e)
        }
        report["overall_status"] = "error"
    
    # 2. RestingOrderMonitor Health
    try:
        from merid.event_venues.kalshi.resting_order_monitor import get_resting_order_monitor
        
        rom = get_resting_order_monitor()
        rom_health = rom.check_health()
        
        # If poll loop not running, that's expected in standalone check - treat as healthy
        if not rom_health["running"] and rom_health["resting_orders_count"] == 0:
            rom_health["healthy"] = True
            rom_health["issues"] = []
            rom_health["note"] = "Poll loop not running (expected when no orders)"
        
        report["checks"]["resting_order_monitor"] = {
            "status": "healthy" if rom_health["healthy"] else "degraded",
            "details": rom_health
        }
        
        if not rom_health["healthy"]:
            report["overall_status"] = "degraded"
            logger.warning(f"RestingOrderMonitor degraded: {rom_health}")
        
    except Exception as e:
        logger.error(f"Failed to check RestingOrderMonitor health: {e}")
        report["checks"]["resting_order_monitor"] = {
            "status": "error",
            "error": str(e)
        }
        report["overall_status"] = "error"
    
    # 3. Scope Violation Monitoring
    try:
        from merid.prediction.dynamic_entry_window import run_scope_violation_monitoring_check
        
        # Check with 5% threshold
        violations = run_scope_violation_monitoring_check(threshold_pct=0.05)
        
        report["checks"]["scope_violations"] = {
            "status": "healthy" if len(violations) == 0 else "warning",
            "violations_count": len(violations),
            "violations": list(violations)[:10] if violations else [],  # Limit to first 10, convert to list
            "threshold_pct": 0.05
        }
        
        if violations:
            report["overall_status"] = "warning"
            logger.warning(f"Scope violations detected: {len(violations)} assets exceeding threshold")
        
    except Exception as e:
        logger.error(f"Failed to check scope violations: {e}")
        report["checks"]["scope_violations"] = {
            "status": "error",
            "error": str(e)
        }
        # Don't set overall_status to error for scope violations - it's not critical
    
    # 4. Kill Switch Status
    try:
        from merid.risk.kill_switches import get_risk_status
        
        risk_status = get_risk_status()
        
        report["checks"]["kill_switch"] = {
            "status": "active" if risk_status["can_trade"] else "triggered",
            "details": risk_status
        }
        
        if not risk_status["can_trade"]:
            report["overall_status"] = "critical"
            logger.error(f"Kill switch triggered: {risk_status}")
        
    except Exception as e:
        logger.error(f"Failed to check kill switch status: {e}")
        report["checks"]["kill_switch"] = {
            "status": "error",
            "error": str(e)
        }
        report["overall_status"] = "error"
    
    return report


def log_health_report(report: Dict[str, Any]) -> None:
    """Log a structured health report.
    
    Args:
        report: Health report from run_all_health_checks()
    """
    logger.info("=" * 80)
    logger.info("KALSHI 15M CRYPTO HEALTH MONITORING REPORT")
    logger.info("=" * 80)
    logger.info(f"Timestamp: {report['timestamp']}")
    logger.info(f"Overall Status: {report['overall_status'].upper()}")
    logger.info("")
    
    for check_name, check_result in report["checks"].items():
        logger.info(f"[{check_name.upper()}]")
        logger.info(f"  Status: {check_result['status'].upper()}")
        
        if "details" in check_result:
            details = check_result["details"]
            if isinstance(details, dict):
                for key, value in details.items():
                    logger.info(f"    {key}: {value}")
            else:
                logger.info(f"    {details}")
        
        if "error" in check_result:
            logger.info(f"  Error: {check_result['error']}")
        
        logger.info("")
    
    logger.info("=" * 80)


async def monitoring_loop(interval_seconds: int = 60) -> None:
    """Run health checks in a continuous loop.
    
    Args:
        interval_seconds: Seconds between health checks
    """
    logger.info(f"Starting monitoring loop (interval: {interval_seconds}s)")
    
    while True:
        try:
            report = run_all_health_checks()
            log_health_report(report)
            
            # If critical status, consider alerting
            if report["overall_status"] == "critical":
                logger.error("CRITICAL: Health check failed - immediate attention required")
                # TODO: Send alert via notification channel
            
        except Exception as e:
            logger.error(f"Monitoring loop error: {e}")
        
        await asyncio.sleep(interval_seconds)


def main() -> None:
    """Run a single health check and log the report."""
    report = run_all_health_checks()
    log_health_report(report)
    
    # Exit with non-zero if not healthy
    if report["overall_status"] in ["error", "critical"]:
        exit(1)
    elif report["overall_status"] == "degraded":
        exit(2)
    else:
        exit(0)


if __name__ == "__main__":
    main()
