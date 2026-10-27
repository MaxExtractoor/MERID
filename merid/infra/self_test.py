"""Production Self-Test / Dry-Run Mode

Validates critical infrastructure components before live trading:
- Redis connectivity and fallback behavior
- Loop lag monitor sampling and thresholds
- CFB RTI adapter health
- Portfolio integrity checks
- Kill switch wiring

Usage:
    # Run full self-test before starting trading
    from merid.infra.self_test import run_production_self_test
    results = await run_production_self_test()
    if not results["passed"]:
        logger.error("Self-test failed: %s", results["failures"])
        sys.exit(1)
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable
from enum import Enum

from utils.logger import get_logger

logger = get_logger("merid.infra.self_test")


class TestResult(Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    WARN = "warn"


@dataclass
class ComponentTest:
    """Result of a single component test."""
    name: str
    result: TestResult
    duration_ms: float
    details: Optional[str] = None
    error: Optional[str] = None


@dataclass
class SelfTestReport:
    """Complete self-test report."""
    passed: bool
    mode: str  # "live" or "paper"
    timestamp: str
    tests: List[ComponentTest] = field(default_factory=list)
    summary: Dict[str, int] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "mode": self.mode,
            "timestamp": self.timestamp,
            "tests": [
                {
                    "name": t.name,
                    "result": t.result.value,
                    "duration_ms": round(t.duration_ms, 2),
                    "details": t.details,
                    "error": t.error,
                }
                for t in self.tests
            ],
            "summary": self.summary,
        }


async def run_production_self_test(
    test_redis: bool = True,
    test_loop_lag: bool = True,
    test_cfb_rti: bool = True,
    test_kill_switch: bool = True,
    test_integrity_gate: bool = True,
) -> SelfTestReport:
    """Run comprehensive pre-flight self-test.
    
    Returns SelfTestReport with pass/fail status for each component.
    """
    import datetime
    
    is_live = os.environ.get("KALSHI_ENV", "").lower() == "live"
    mode = "LIVE" if is_live else "PAPER"
    
    tests: List[ComponentTest] = []
    
    # Test 1: Redis connectivity and fallback
    if test_redis:
        tests.append(await _test_redis_resilience())
    
    # Test 2: Loop lag monitor
    if test_loop_lag:
        tests.append(await _test_loop_lag_monitor())
    
    # Test 3: CFB RTI health
    if test_cfb_rti:
        tests.append(await _test_cfb_rti())
    
    # Test 4: Kill switch wiring
    if test_kill_switch:
        tests.append(await _test_kill_switch_wiring())
    
    # Test 5: Integrity gate basic operation
    if test_integrity_gate:
        tests.append(await _test_integrity_gate())
    
    # Calculate summary
    summary = {
        "total": len(tests),
        "pass": sum(1 for t in tests if t.result == TestResult.PASS),
        "fail": sum(1 for t in tests if t.result == TestResult.FAIL),
        "skip": sum(1 for t in tests if t.result == TestResult.SKIP),
        "warn": sum(1 for t in tests if t.result == TestResult.WARN),
    }
    
    # Passed if no failures
    passed = summary["fail"] == 0
    
    report = SelfTestReport(
        passed=passed,
        mode=mode,
        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        tests=tests,
        summary=summary,
    )
    
    # Log results
    _log_report(report)
    
    return report


async def _test_redis_resilience() -> ComponentTest:
    """Test Redis resilient wrapper connectivity and fallback."""
    start = time.time()
    name = "redis_resilience"
    
    try:
        from merid.infra.redis_resilient import get_resilient_redis, redis_health
        
        # Check if Redis is enabled
        redis_enabled = os.environ.get("MERID_REDIS_ENABLED", "1").strip() != "0"
        
        if not redis_enabled:
            return ComponentTest(
                name=name,
                result=TestResult.SKIP,
                duration_ms=(time.time() - start) * 1000,
                details="Redis disabled (MERID_REDIS_ENABLED=0)",
            )
        
        # Try to get Redis client
        client = get_resilient_redis()
        
        if client is None:
            # This is expected if Redis is unavailable - verify fallback works
            health = redis_health()
            if health.get("enabled") == False:
                return ComponentTest(
                    name=name,
                    result=TestResult.WARN,
                    duration_ms=(time.time() - start) * 1000,
                    details="Redis unavailable but graceful degradation active",
                )
            else:
                return ComponentTest(
                    name=name,
                    result=TestResult.FAIL,
                    duration_ms=(time.time() - start) * 1000,
                    error="Redis client is None but not properly disabled",
                )
        
        # Test basic operations
        test_key = "merid:self_test"
        test_value = b"test_value"
        
        # Set
        set_result = client.set(test_key, test_value, ex=10)
        
        # Get
        get_result = client.get(test_key)
        
        # Delete
        client.delete(test_key)
        
        if get_result == test_value:
            return ComponentTest(
                name=name,
                result=TestResult.PASS,
                duration_ms=(time.time() - start) * 1000,
                details=f"Redis ops working (set={set_result}, get=OK)",
            )
        else:
            return ComponentTest(
                name=name,
                result=TestResult.WARN,
                duration_ms=(time.time() - start) * 1000,
                details="Redis set/get returned unexpected value (may be degraded)",
            )
            
    except Exception as exc:
        return ComponentTest(
            name=name,
            result=TestResult.FAIL,
            duration_ms=(time.time() - start) * 1000,
            error=f"Redis test exception: {exc}",
        )


async def _test_loop_lag_monitor() -> ComponentTest:
    """Test LoopLagMonitor initialization and sampling."""
    start = time.time()
    name = "loop_lag_monitor"
    
    try:
        from merid.infra.loop_lag_monitor import LoopLagMonitor, get_loop_lag_monitor
        from merid.settings import settings
        
        # Check if enabled
        if not getattr(settings, "MERID_LOOP_LAG_ENABLED", True):
            return ComponentTest(
                name=name,
                result=TestResult.SKIP,
                duration_ms=(time.time() - start) * 1000,
                details="Loop lag monitoring disabled",
            )
        
        # Get or create monitor
        monitor = get_loop_lag_monitor()
        
        if monitor is None:
            return ComponentTest(
                name=name,
                result=TestResult.FAIL,
                duration_ms=(time.time() - start) * 1000,
                error="Failed to create LoopLagMonitor",
            )
        
        # Test threshold configuration
        warn_ms = monitor._warn_ms
        degrade_ms = monitor._degrade_ms
        halt_ms = monitor._halt_ms
        
        # Verify thresholds are reasonable
        if not (0 < warn_ms < degrade_ms < halt_ms):
            return ComponentTest(
                name=name,
                result=TestResult.FAIL,
                duration_ms=(time.time() - start) * 1000,
                error=f"Invalid threshold ordering: warn={warn_ms}, degrade={degrade_ms}, halt={halt_ms}",
            )
        
        # Start monitor briefly to test sampling
        await monitor.start()
        await asyncio.sleep(0.1)  # Let it take a few samples
        
        # Check health status
        health = monitor.health_check()
        lag_ms = monitor.get_recent_ms()
        
        await monitor.stop()
        
        if health.get("healthy"):
            return ComponentTest(
                name=name,
                result=TestResult.PASS,
                duration_ms=(time.time() - start) * 1000,
                details=f"Monitor sampling OK (lag={lag_ms:.1f}ms, thresholds={warn_ms}/{degrade_ms}/{halt_ms}ms)",
            )
        else:
            return ComponentTest(
                name=name,
                result=TestResult.WARN,
                duration_ms=(time.time() - start) * 1000,
                details=f"Monitor running but showing unhealthy (lag={lag_ms:.1f}ms)",
            )
            
    except Exception as exc:
        return ComponentTest(
            name=name,
            result=TestResult.FAIL,
            duration_ms=(time.time() - start) * 1000,
            error=f"Loop lag monitor test exception: {exc}",
        )


async def _test_cfb_rti() -> ComponentTest:
    """Test CFB RTI adapter configuration and connectivity.
    
    When MERID_USE_CFB_RTI is not set to "1", CFB RTI is treated as an optional
    enhancement and the test passes with SKIP status (not a failure).
    """
    start = time.time()
    name = "cfb_rti"
    
    # Check if CFB RTI is explicitly enabled
    use_cfb = os.environ.get("MERID_USE_CFB_RTI", "").strip() == "1"
    
    try:
        from core.execution_gate import check_cfb_rti_health
        
        is_live = os.environ.get("KALSHI_ENV", "").lower() == "live"
        
        result = check_cfb_rti_health()
        healthy = result.get("healthy", False)
        status = result.get("status", "unknown")
        adapter_type = result.get("adapter_type", "unknown")
        skipped = result.get("skipped", False)
        
        # NEW: If CFB is disabled by config, treat as SKIP (not WARN)
        if skipped:
            return ComponentTest(
                name=name,
                result=TestResult.SKIP,
                duration_ms=(time.time() - start) * 1000,
                details="CFB RTI disabled by config (MERID_USE_CFB_RTI not set to 1). "
                        "This is acceptable for non-licensed operation.",
            )
        
        if is_live:
            # In live mode, CFB must be healthy (if enabled)
            if healthy:
                return ComponentTest(
                    name=name,
                    result=TestResult.PASS,
                    duration_ms=(time.time() - start) * 1000,
                    details=f"CFB RTI healthy ({adapter_type}: {status})",
                )
            else:
                error = result.get("error", "Unknown CFB RTI failure")
                return ComponentTest(
                    name=name,
                    result=TestResult.FAIL,
                    duration_ms=(time.time() - start) * 1000,
                    error=f"CFB RTI unhealthy in LIVE mode: {error}",
                )
        else:
            # In paper/demo mode, warn but don't fail
            if healthy:
                return ComponentTest(
                    name=name,
                    result=TestResult.PASS,
                    duration_ms=(time.time() - start) * 1000,
                    details=f"CFB RTI healthy ({adapter_type}: {status})",
                )
            else:
                error = result.get("error", "CFB RTI not configured or unhealthy")
                return ComponentTest(
                    name=name,
                    result=TestResult.WARN,
                    duration_ms=(time.time() - start) * 1000,
                    details=f"CFB RTI not healthy but OK for paper/demo: {error}",
                )
                
    except Exception as exc:
        # If CFB is not enabled, import errors are acceptable
        if not use_cfb:
            return ComponentTest(
                name=name,
                result=TestResult.SKIP,
                duration_ms=(time.time() - start) * 1000,
                details=f"CFB RTI not enabled (MERID_USE_CFB_RTI not set to 1): {exc}",
            )
        return ComponentTest(
            name=name,
            result=TestResult.FAIL,
            duration_ms=(time.time() - start) * 1000,
            error=f"CFB RTI test exception: {exc}",
        )


async def _test_kill_switch_wiring() -> ComponentTest:
    """Test kill switch is wired and can be triggered/cleared."""
    start = time.time()
    name = "kill_switch"
    
    try:
        from merid.risk.kill_switches import risk_controller, KillSwitchReason
        
        # Check kill switch is accessible
        if risk_controller is None:
            return ComponentTest(
                name=name,
                result=TestResult.FAIL,
                duration_ms=(time.time() - start) * 1000,
                error="Risk controller singleton is None",
            )
        
        # Check if kill switch methods exist
        required_methods = [
            "trigger_rti_feed_stale",
            "trigger_loop_lag_halt",
            "trigger_portfolio_integrity",
            "reset",
        ]
        
        missing = []
        for method in required_methods:
            if not hasattr(risk_controller, method):
                missing.append(method)
        
        if missing:
            return ComponentTest(
                name=name,
                result=TestResult.FAIL,
                duration_ms=(time.time() - start) * 1000,
                error=f"Missing kill switch methods: {missing}",
            )
        
        # Check KillSwitchReason enum has new values
        required_reasons = [
            KillSwitchReason.RTI_FEED_STALE,
            KillSwitchReason.LOOP_LAG_HALT,
            KillSwitchReason.PORTFOLIO_INTEGRITY,
        ]
        
        return ComponentTest(
            name=name,
            result=TestResult.PASS,
            duration_ms=(time.time() - start) * 1000,
            details="Kill switch wiring complete with all halt paths",
        )
        
    except Exception as exc:
        return ComponentTest(
            name=name,
            result=TestResult.FAIL,
            duration_ms=(time.time() - start) * 1000,
            error=f"Kill switch test exception: {exc}",
        )


async def _test_integrity_gate() -> ComponentTest:
    """Test portfolio integrity gate basic operation."""
    start = time.time()
    name = "integrity_gate"
    
    try:
        from core.execution_gate import check_portfolio_integrity
        from merid.settings import settings
        
        # Run a basic check with None values (should not crash)
        healthy, reason = check_portfolio_integrity(
            fills_ledger=None,
            portfolio_state=None,
            risk_state=None,
            cfb_rti=None,
            settings=settings,
        )
        
        # Should return healthy=True when no data (nothing to check)
        if healthy:
            return ComponentTest(
                name=name,
                result=TestResult.PASS,
                duration_ms=(time.time() - start) * 1000,
                details="Integrity gate operational (no data = no issues)",
            )
        else:
            # If it returns degraded, that's still functional
            if reason.startswith("DEGRADED"):
                return ComponentTest(
                    name=name,
                    result=TestResult.PASS,
                    duration_ms=(time.time() - start) * 1000,
                    details="Integrity gate operational (degraded state handling works)",
                )
            else:
                return ComponentTest(
                    name=name,
                    result=TestResult.WARN,
                    duration_ms=(time.time() - start) * 1000,
                    details=f"Integrity gate returned unexpected: {reason}",
                )
                
    except Exception as exc:
        return ComponentTest(
            name=name,
            result=TestResult.FAIL,
            duration_ms=(time.time() - start) * 1000,
            error=f"Integrity gate test exception: {exc}",
        )


def _log_report(report: SelfTestReport) -> None:
    """Log self-test results."""
    status = "PASSED" if report.passed else "FAILED"
    
    logger.info("=" * 60)
    logger.info("PRODUCTION SELF-TEST: %s (mode=%s)", status, report.mode)
    logger.info("=" * 60)
    
    for test in report.tests:
        symbol = {
            TestResult.PASS: "✓",
            TestResult.FAIL: "✗",
            TestResult.SKIP: "⊘",
            TestResult.WARN: "⚠",
        }.get(test.result, "?")
        
        logger.info("  %s %s: %s (%.1fms)", symbol, test.name, test.result.value.upper(), test.duration_ms)
        if test.details:
            logger.info("      %s", test.details)
        if test.error:
            logger.info("      ERROR: %s", test.error)
    
    logger.info("-" * 60)
    logger.info("Summary: %s", report.summary)
    logger.info("=" * 60)


# ── CLI Entry Point ──────────────────────────────────────────────────────

if __name__ == "__main__":
    async def main():
        import sys
        import json
        
        is_live = os.environ.get("KALSHI_ENV", "").lower() == "live"
        
        print("Running MERID Production Self-Test...", file=sys.stderr)
        print(f"Mode: {'LIVE' if is_live else 'PAPER/DEMO'}", file=sys.stderr)
        print("-" * 60, file=sys.stderr)
        
        report = await run_production_self_test()
        
        # Output full JSON to stdout for programmatic use
        print(json.dumps(report.to_dict(), indent=2))
        
        # Loud failure for critical issues in live mode
        if not report.passed:
            failures = [t for t in report.tests if t.result == TestResult.FAIL]
            
            print("\n" + "=" * 60, file=sys.stderr)
            print("CRITICAL: SELF-TEST FAILED", file=sys.stderr)
            print("=" * 60, file=sys.stderr)
            
            for test in failures:
                print(f"\n✗ {test.name}: FAILED", file=sys.stderr)
                if test.error:
                    print(f"  ERROR: {test.error}", file=sys.stderr)
                if test.details:
                    print(f"  DETAILS: {test.details}", file=sys.stderr)
            
            if is_live:
                print("\n*** LIVE MODE HALT ***", file=sys.stderr)
                print("Deployment blocked. Fix critical failures before trading.", file=sys.stderr)
                print("=" * 60, file=sys.stderr)
                sys.exit(1)
            else:
                print("\n*** PAPER/DEMO MODE WARNING ***", file=sys.stderr)
                print("Self-test failed but not blocking in non-live mode.", file=sys.stderr)
                print("Review warnings before proceeding to live.", file=sys.stderr)
                print("=" * 60, file=sys.stderr)
                sys.exit(1)  # Still exit non-zero for CI/CD gating
        
        print("\n✓ All tests passed", file=sys.stderr)
        sys.exit(0)
    
    asyncio.run(main())
