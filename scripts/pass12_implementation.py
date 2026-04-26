#!/usr/bin/env python3
"""
Pass 12 Implementation Script

Executes Pass 12 workstreams:
1. FastAPI test verification in clean environment
2. UX/Ops implementation
3. Observability deployment
4. Final GO/NO-GO assessment

Usage:
    python scripts/pass12_implementation.py [--check] [--fix]
"""

import argparse
import subprocess
import sys
import os
from pathlib import Path


def log(section, message):
    print(f"[{section}] {message}")


def run_command(cmd, cwd=None, timeout=300):
    """Run a shell command and return success status."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd or Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.returncode == 0, result.stdout, result.stderr
    except Exception as e:
        return False, "", str(e)


# ═══════════════════════════════════════════════════════════════════════════════
# 12.A – FASTAPI TEST VERIFICATION
# ═══════════════════════════════════════════════════════════════════════════════

def check_clean_environment():
    """Check if clean test environment is available."""
    log("12.A", "Checking for clean test environment...")
    
    # Check for venv_pass12
    venv_path = Path("venv_pass12")
    if venv_path.exists():
        log("12.A", "✓ Clean environment exists (venv_pass12)")
        return True
    
    log("12.A", "⚠ Clean environment not found - will create")
    return False


def create_clean_environment():
    """Create isolated test environment."""
    log("12.A", "Creating clean test environment...")
    
    commands = [
        "python -m venv venv_pass12",
        "venv_pass12\\Scripts\\pip install -e .",
        "venv_pass12\\Scripts\\pip install pytest fastapi httpx pydantic pytest-asyncio",
    ]
    
    for cmd in commands:
        success, stdout, stderr = run_command(cmd)
        if not success:
            log("12.A", f"✗ Failed: {cmd}")
            log("12.A", f"  Error: {stderr[:200]}")
            return False
    
    log("12.A", "✓ Clean environment created")
    return True


def run_fastapi_tests():
    """Run the 5 pending FastAPI endpoint tests."""
    log("12.A", "Running FastAPI endpoint tests...")
    
    test_cases = [
        "tests/scenario/test_pass9_scenarios.py::TestScenarioB_ExecutorFailure::test_fail_closed_returns_503",
        "tests/scenario/test_pass9_scenarios.py::TestScenarioB_ExecutorFailure::test_no_rest_fallback_in_live",
        "tests/scenario/test_pass9_scenarios.py::TestScenarioB_ExecutorFailure::test_kill_switch_triggered",
        "tests/scenario/test_pass9_scenarios.py::TestScenarioD_RogueAgentBypass::test_fix_endpoint_blocked_in_live",
        "tests/scenario/test_pass9_scenarios.py::TestScenarioD_RogueAgentBypass::test_ct_api_blocked_in_live",
    ]
    
    passed = 0
    failed = 0
    
    for test_case in test_cases:
        # Run with clean environment
        cmd = f"venv_pass12\\Scripts\\pytest {test_case} -v --tb=short"
        success, stdout, stderr = run_command(cmd)
        
        test_name = test_case.split("::")[-1]
        if success and "PASSED" in stdout:
            log("12.A", f"  ✓ {test_name}")
            passed += 1
        else:
            log("12.A", f"  ✗ {test_name}")
            if "FAILED" in stdout or "ERROR" in stdout:
                # Extract error
                lines = stdout.split("\n")
                for line in lines:
                    if "FAILED" in line or "Error" in line:
                        log("12.A", f"    {line[:80]}")
                        break
            failed += 1
    
    log("12.A", f"Results: {passed}/5 passed, {failed}/5 failed")
    return failed == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 12.B – UX/OPS IMPLEMENTATION CHECKS
# ═══════════════════════════════════════════════════════════════════════════════

def check_ux_implementations():
    """Check if UX enhancements are implemented."""
    log("12.B", "Checking UX implementations...")
    
    checks = {
        "Mode banner template": Path("web/templates/components/mode_banner.html").exists(),
        "CLI mode indicator": "show_mode_banner" in Path("merid/cli/status.py").read_text() if Path("merid/cli/status.py").exists() else False,
        "Config validation endpoint": Path("web/api/config_validation.py").exists(),
    }
    
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    
    for check, status in checks.items():
        symbol = "✓" if status else "✗"
        log("12.B", f"  {symbol} {check}")
    
    log("12.B", f"UX Implementation: {passed}/{total}")
    return passed == total


# ═══════════════════════════════════════════════════════════════════════════════
# 12.C – OBSERVABILITY CHECKS
# ═══════════════════════════════════════════════════════════════════════════════

def check_observability():
    """Check if observability components are implemented."""
    log("12.C", "Checking observability implementations...")
    
    checks = {
        "Structured logging module": Path("merid/utils/structured_logging.py").exists(),
        "Metrics module": Path("merid/metrics/kalshi_metrics.py").exists(),
        "Runbook docs": Path("docs/runbooks").exists(),
    }
    
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    
    for check, status in checks.items():
        symbol = "✓" if status else "✗"
        log("12.C", f"  {symbol} {check}")
    
    log("12.C", f"Observability: {passed}/{total}")
    return passed == total


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Pass 12 Implementation")
    parser.add_argument("--check", action="store_true", help="Check current status")
    parser.add_argument("--fix", action="store_true", help="Apply fixes where possible")
    args = parser.parse_args()
    
    print("=" * 70)
    print("PASS 12: FINAL INTEGRATION + VALIDATION")
    print("=" * 70)
    print()
    
    results = {}
    
    # 12.A - FastAPI Tests
    print("\n" + "─" * 70)
    print("12.A – FASTAPI TEST VERIFICATION")
    print("─" * 70)
    
    if args.fix and not check_clean_environment():
        create_clean_environment()
    
    results["12.A"] = run_fastapi_tests()
    
    # 12.B - UX
    print("\n" + "─" * 70)
    print("12.B – UX/OPS IMPLEMENTATION")
    print("─" * 70)
    results["12.B"] = check_ux_implementations()
    
    # 12.C - Observability
    print("\n" + "─" * 70)
    print("12.C – OBSERVABILITY & RUNBOOKS")
    print("─" * 70)
    results["12.C"] = check_observability()
    
    # Summary
    print("\n" + "=" * 70)
    print("PASS 12 SUMMARY")
    print("=" * 70)
    
    for section, status in results.items():
        symbol = "✓ PASS" if status else "✗ FAIL"
        print(f"  {section}: {symbol}")
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    print()
    print(f"Progress: {passed}/{total} sections complete ({passed/total*100:.0f}%)")
    
    # GO/NO-GO Assessment
    print("\n" + "=" * 70)
    print("GO/NO-GO ASSESSMENT")
    print("=" * 70)
    
    if all(results.values()):
        print("\n✓ SIM: GO - All critical items complete")
        print("⚠ PAPER: GO with monitoring - Run 24hr observation")
        print("❌ LIVE: NO-GO - Needs 7-day PAPER observation")
        return 0
    else:
        print("\n⚠ SIM: PENDING - Complete 12.A tests first")
        print("❌ PAPER: NO-GO - Pending SIM GO")
        print("❌ LIVE: NO-GO - Pending all prerequisites")
        return 1


if __name__ == "__main__":
    sys.exit(main())
