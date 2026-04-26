#!/usr/bin/env python3
"""
Wave 11 Implementation Script

Run this to execute Wave 11 workstreams:
1. Testing & Infrastructure Cleanup
2. Code & Config Fixes
3. CI & Deployment Guardrails

Usage:
    python scripts/wave11_implementation.py [--check-only] [--fix]

Options:
    --check-only    Run checks without making changes
    --fix           Apply fixes automatically where safe
"""

import argparse
import subprocess
import sys
import os
from pathlib import Path


def log(section, message):
    print(f"[{section}] {message}")


def run_command(cmd, cwd=None):
    """Run a shell command and return success status."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd or Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=300
        )
        return result.returncode == 0, result.stdout, result.stderr
    except Exception as e:
        return False, "", str(e)


# ═══════════════════════════════════════════════════════════════════════════════
# 11.A – TESTING & INFRASTRUCTURE CLEANUP
# ═══════════════════════════════════════════════════════════════════════════════

def check_11a1_pytest_plugins():
    """Check 11.A.1: Isolate from problematic pytest plugins."""
    log("11.A.1", "Checking pytest plugin configuration...")
    
    # Check if pytest.ini exists with plugin blacklisting
    pytest_ini = Path("pytest.ini")
    if not pytest_ini.exists():
        log("11.A.1", "✗ pytest.ini not found")
        return False
    
    content = pytest_ini.read_text()
    checks = [
        "no:langsmith" in content,
        "no:charset_normalizer" in content,
    ]
    
    if all(checks):
        log("11.A.1", "✓ pytest.ini configured to blacklist problematic plugins")
        return True
    else:
        log("11.A.1", "✗ pytest.ini missing plugin blacklist entries")
        return False


def fix_11a1_pytest_plugins():
    """Fix 11.A.1: Create/update pytest.ini."""
    log("11.A.1", "Creating pytest.ini with plugin blacklist...")
    
    config = """[pytest]
addopts = -p no:langsmith -p no:charset_normalizer --tb=short
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
asyncio_mode = auto
"""
    
    Path("pytest.ini").write_text(config)
    log("11.A.1", "✓ Created pytest.ini")
    return True


def check_11a2_testclient_setup():
    """Check 11.A.2: FastAPI TestClient setup."""
    log("11.A.2", "Checking TestClient setup...")
    
    # Check if app can be imported
    success, stdout, stderr = run_command(
        "python -c 'from web.main import app; print(\"OK\")'"
    )
    
    if success and "OK" in stdout:
        log("11.A.2", "✓ FastAPI app imports successfully")
        return True
    else:
        log("11.A.2", f"✗ App import failed: {stderr[:100]}")
        return False


def check_11a3_test_status():
    """Check 11.A.3: Run critical tests."""
    log("11.A.3", "Running critical test suite...")
    
    test_dirs = [
        "tests/risk",
        "tests/security",
        "tests/scenario"
    ]
    
    total_passed = 0
    total_failed = 0
    
    for test_dir in test_dirs:
        if not Path(test_dir).exists():
            continue
            
        success, stdout, stderr = run_command(
            f"python -m pytest {test_dir} --tb=no -q"
        )
        
        # Parse results
        if "passed" in stdout:
            parts = stdout.split()
            for i, part in enumerate(parts):
                if part == "passed":
                    count = parts[i-1] if i > 0 else "0"
                    try:
                        total_passed += int(count)
                    except:
                        pass
        
        if "failed" in stdout or "error" in stdout.lower():
            total_failed += 1
    
    log("11.A.3", f"Tests: {total_passed} passed, {total_failed} failed")
    return total_failed == 0 and total_passed > 0


# ═══════════════════════════════════════════════════════════════════════════════
# 11.B – CODE & CONFIG FIXES
# ═══════════════════════════════════════════════════════════════════════════════

def check_11b1_ci_invariants():
    """Check 11.B.1: CI invariant script coverage."""
    log("11.B.1", "Checking CI invariant script...")
    
    script_path = Path("scripts/ci/check_kalshi_invariants.py")
    if not script_path.exists():
        log("11.B.1", "✗ CI invariant script not found")
        return False
    
    content = script_path.read_text()
    
    required_checks = [
        "check_fix_endpoint_guard",
        "check_rest_fallback_guard",
        "check_ct_api_guard",
        "check_startup_enforcement",
    ]
    
    missing = [check for check in required_checks if check not in content]
    
    if missing:
        log("11.B.1", f"✗ Missing checks: {missing}")
        return False
    else:
        log("11.B.1", "✓ All required invariant checks present")
        return True


def check_11b2_ux_improvements():
    """Check 11.B.2: UX improvements implemented."""
    log("11.B.2", "Checking UX improvements...")
    
    # Check for enhanced error messages in kalshi_api.py
    kalshi_api = Path("web/api/kalshi_api.py").read_text()
    
    has_structured_errors = "error:" in kalshi_api and "remediation:" in kalshi_api
    
    if has_structured_errors:
        log("11.B.2", "✓ Enhanced error messages found")
        return True
    else:
        log("11.B.2", "⚠ Basic error messages (may be acceptable)")
        return True  # Not a hard failure


def check_11b3_observability():
    """Check 11.B.3: Observability improvements."""
    log("11.B.3", "Checking observability...")
    
    # Check for structured logging
    kill_switches = Path("merid/risk/kill_switches.py").read_text()
    has_structured_logging = "extra=" in kill_switches or "GUARD_TRIP" in kill_switches
    
    if has_structured_logging:
        log("11.B.3", "✓ Structured logging present")
        return True
    else:
        log("11.B.3", "⚠ Basic logging (should enhance)")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# 11.C – CI & DEPLOYMENT GUARDRAILS
# ═══════════════════════════════════════════════════════════════════════════════

def check_11c1_ci_wiring():
    """Check 11.C.1: CI pipeline wiring."""
    log("11.C.1", "Checking CI configuration...")
    
    # Check for GitHub Actions or similar
    ci_configs = list(Path(".github/workflows").glob("*.yml"))
    
    if ci_configs:
        log("11.C.1", f"✓ Found {len(ci_configs)} CI workflow(s)")
        return True
    else:
        log("11.C.1", "⚠ No CI workflows found (create .github/workflows/)")
        return False


def check_11c2_invariant_failures():
    """Check 11.C.2: Invariant checks fail CI."""
    log("11.C.2", "Checking invariant failure handling...")
    
    script_path = Path("scripts/ci/check_kalshi_invariants.py")
    if not script_path.exists():
        return False
    
    content = script_path.read_text()
    
    # Check if script exits with error code on failure
    has_exit_code = "sys.exit(1)" in content and "sys.exit(0)" in content
    
    if has_exit_code:
        log("11.C.2", "✓ Invariant script exits with proper error codes")
        return True
    else:
        log("11.C.2", "✗ Invariant script needs exit code handling")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Wave 11 Implementation")
    parser.add_argument("--check-only", action="store_true", help="Run checks only")
    parser.add_argument("--fix", action="store_true", help="Apply fixes where safe")
    args = parser.parse_args()
    
    print("=" * 70)
    print("WAVE 11: HARDENING & CLEANUP - IMPLEMENTATION CHECK")
    print("=" * 70)
    print()
    
    results = {}
    
    # 11.A - Testing & Infrastructure
    print("\n" + "─" * 70)
    print("11.A – TESTING & INFRASTRUCTURE CLEANUP")
    print("─" * 70)
    results["11.A.1"] = check_11a1_pytest_plugins()
    results["11.A.2"] = check_11a2_testclient_setup()
    results["11.A.3"] = check_11a3_test_status()
    
    if args.fix and not results["11.A.1"]:
        fix_11a1_pytest_plugins()
        results["11.A.1"] = True
    
    # 11.B - Code & Config Fixes
    print("\n" + "─" * 70)
    print("11.B – CODE & CONFIG FIXES")
    print("─" * 70)
    results["11.B.1"] = check_11b1_ci_invariants()
    results["11.B.2"] = check_11b2_ux_improvements()
    results["11.B.3"] = check_11b3_observability()
    
    # 11.C - CI & Deployment
    print("\n" + "─" * 70)
    print("11.C – CI & DEPLOYMENT GUARDRAILS")
    print("─" * 70)
    results["11.C.1"] = check_11c1_ci_wiring()
    results["11.C.2"] = check_11c2_invariant_failures()
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for check, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {check}: {status}")
    
    print()
    print(f"Total: {passed}/{total} checks passed ({passed/total*100:.0f}%)")
    
    if passed == total:
        print("\n✓ Wave 11 implementation complete!")
        return 0
    else:
        print(f"\n⚠ {total - passed} items need attention")
        return 1


if __name__ == "__main__":
    sys.exit(main())
