#!/usr/bin/env python3
"""
Comprehensive Implementation Verification Script

Checks all files modified in Pass 12 for:
1. Syntax errors
2. Import availability
3. Function existence
4. Guard wiring
"""

import ast
import sys
from pathlib import Path


def check_syntax(filepath):
    """Check Python file for syntax errors."""
    try:
        with open(filepath, 'r') as f:
            source = f.read()
        ast.parse(source)
        return True, None
    except SyntaxError as e:
        return False, str(e)


def check_imports(filepath, required_imports):
    """Check if required imports exist in file."""
    with open(filepath, 'r') as f:
        source = f.read()
    
    missing = []
    for imp in required_imports:
        if imp not in source:
            missing.append(imp)
    return missing


def main():
    print("=" * 70)
    print("PASS 12 IMPLEMENTATION VERIFICATION")
    print("=" * 70)
    
    checks = []
    
    # Check 1: Syntax of all modified files
    print("\n1. SYNTAX CHECKS")
    print("-" * 70)
    
    files_to_check = [
        "web/api/kalshi_api.py",
        "web/api/kalshi_continuous_trader_api.py",
        "archive/__init__.py",
        "merid/config/unified_risk_enforcement.py",
        "merid/utils/structured_logging.py",
        "merid/metrics/kalshi_metrics.py",
        "merid/cli/status.py",
        "web/api/config_validation.py",
    ]
    
    for filepath in files_to_check:
        full_path = Path(filepath)
        if full_path.exists():
            ok, error = check_syntax(full_path)
            if ok:
                print(f"  ✓ {filepath}")
                checks.append((filepath, "syntax", True))
            else:
                print(f"  ✗ {filepath} - {error}")
                checks.append((filepath, "syntax", False))
        else:
            print(f"  ✗ {filepath} - FILE NOT FOUND")
            checks.append((filepath, "exists", False))
    
    # Check 2: Guard wiring
    print("\n2. GUARD WIRING CHECKS")
    print("-" * 70)
    
    # FIX guard
    with open("web/api/kalshi_api.py") as f:
        content = f.read()
    
    fix_checks = [
        ("get_structured_logger import", "from merid.utils.structured_logging import get_structured_logger" in content),
        ("record_guard_trip import", "from merid.metrics.kalshi_metrics import record_guard_trip" in content),
        ("json import", "import json" in content),
        ("log_guard_trip call", "_slogger.log_guard_trip(" in content),
        ("record_guard_trip call", "record_guard_trip(_guard_type" in content),
        ("HTTPException with json.dumps", "detail=json.dumps({" in content),
    ]
    
    for check_name, result in fix_checks:
        status = "✓" if result else "✗"
        print(f"  {status} FIX guard: {check_name}")
        checks.append(("FIX guard", check_name, result))
    
    # REST fallback guard
    rest_checks = [
        ("log_executor_failure call", "_slogger.log_executor_failure(" in content),
        ("log_kill_switch call", "_slogger.log_kill_switch(" in content),
        ("record_kill_switch call", "record_kill_switch(" in content),
    ]
    
    for check_name, result in rest_checks:
        status = "✓" if result else "✗"
        print(f"  {status} REST guard: {check_name}")
        checks.append(("REST guard", check_name, result))
    
    # CT guard
    with open("web/api/kalshi_continuous_trader_api.py") as f:
        ct_content = f.read()
    
    ct_checks = [
        ("log_guard_trip call", "slogger.log_guard_trip(" in ct_content or "_slogger.log_guard_trip(" in ct_content),
        ("record_guard_trip call", "record_guard_trip(" in ct_content),
        ("json.dumps in HTTPException", "json.dumps({" in ct_content),
    ]
    
    for check_name, result in ct_checks:
        status = "✓" if result else "✗"
        print(f"  {status} CT guard: {check_name}")
        checks.append(("CT guard", check_name, result))
    
    # Archive guard
    with open("archive/__init__.py") as f:
        archive_content = f.read()
    
    archive_checks = [
        ("log_guard_trip call", "slogger.log_guard_trip(" in archive_content or "_slogger.log_guard_trip(" in archive_content),
        ("record_guard_trip call", "record_guard_trip(" in archive_content),
    ]
    
    for check_name, result in archive_checks:
        status = "✓" if result else "✗"
        print(f"  {status} Archive guard: {check_name}")
        checks.append(("Archive guard", check_name, result))
    
    # Startup enforcement
    with open("merid/config/unified_risk_enforcement.py") as f:
        startup_content = f.read()
    
    startup_checks = [
        ("get_structured_logger import", "get_structured_logger" in startup_content),
        ("record_startup_enforcement import", "record_startup_enforcement" in startup_content),
        ("log_startup_enforcement call", "slogger.log_startup_enforcement(" in startup_content),
        ("log_risk_violation call", "slogger.log_risk_violation(" in startup_content),
    ]
    
    for check_name, result in startup_checks:
        status = "✓" if result else "✗"
        print(f"  {status} Startup: {check_name}")
        checks.append(("Startup enforcement", check_name, result))
    
    # Check 3: New modules
    print("\n3. NEW MODULE CHECKS")
    print("-" * 70)
    
    # Structured logging
    with open("merid/utils/structured_logging.py") as f:
        slog_content = f.read()
    
    slog_funcs = ["log_guard_trip", "log_mode_transition", "log_kill_switch", 
                  "log_risk_violation", "log_order_rejected", "log_startup_enforcement",
                  "log_executor_failure"]
    for func in slog_funcs:
        result = f"def {func}(" in slog_content
        status = "✓" if result else "✗"
        print(f"  {status} StructuredLogger.{func}")
        checks.append(("structured_logging", func, result))
    
    # Metrics
    with open("merid/metrics/kalshi_metrics.py") as f:
        metrics_content = f.read()
    
    metric_funcs = ["record_guard_trip", "record_kill_switch", "record_startup_enforcement",
                    "record_risk_violation", "start_metrics_server"]
    for func in metric_funcs:
        result = f"def {func}(" in metrics_content
        status = "✓" if result else "✗"
        print(f"  {status} Metrics.{func}")
        checks.append(("metrics", func, result))
    
    # Check 4: UX Components
    print("\n4. UX COMPONENT CHECKS")
    print("-" * 70)
    
    ux_files = [
        ("Mode banner template", "web/templates/components/mode_banner.html"),
        ("CLI status module", "merid/cli/status.py"),
        ("Config validation API", "web/api/config_validation.py"),
    ]
    
    for name, path in ux_files:
        exists = Path(path).exists()
        status = "✓" if exists else "✗"
        print(f"  {status} {name}: {path}")
        checks.append(("UX", name, exists))
    
    # Check CLI functions
    if Path("merid/cli/status.py").exists():
        with open("merid/cli/status.py") as f:
            cli_content = f.read()
        
        cli_funcs = ["show_mode_banner", "show_compact_mode", "confirm_live_operation", 
                     "show_risk_summary"]
        for func in cli_funcs:
            result = f"def {func}(" in cli_content
            status = "✓" if result else "✗"
            print(f"  {status} CLI.{func}")
            checks.append(("CLI", func, result))
    
    # Check 5: Runbooks
    print("\n5. RUNBOOK CHECKS")
    print("-" * 70)
    
    runbooks = [
        "docs/runbooks/README.md",
        "docs/runbooks/RB-01-fix-endpoint-guard.md",
        "docs/runbooks/RB-02-rest-fallback-failclosed.md",
        "docs/runbooks/RB-03-kill-switch-activation.md",
        "docs/runbooks/RB-04-config-violation.md",
        "docs/runbooks/RB-05-archive-import.md",
    ]
    
    for rb in runbooks:
        exists = Path(rb).exists()
        status = "✓" if exists else "✗"
        print(f"  {status} {rb}")
        checks.append(("runbook", rb, exists))
    
    # Check 6: CI/CD
    print("\n6. CI/CD CHECKS")
    print("-" * 70)
    
    ci_file = ".github/workflows/merid-safety-ci.yml"
    ci_exists = Path(ci_file).exists()
    status = "✓" if ci_exists else "✗"
    print(f"  {status} GitHub Actions workflow: {ci_file}")
    checks.append(("CI/CD", "workflow", ci_exists))
    
    if ci_exists:
        with open(ci_file) as f:
            ci_content = f.read()
        
        jobs = ["safety-checks", "tests"]
        for job in jobs:
            result = job in ci_content
            status = "✓" if result else "✗"
            print(f"  {status} Job: {job}")
            checks.append(("CI/CD job", job, result))
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    total = len(checks)
    passed = sum(1 for _, _, result in checks if result)
    failed = total - passed
    
    print(f"Total checks: {total}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Success rate: {passed/total*100:.1f}%")
    
    if failed > 0:
        print("\nFailed checks:")
        for category, name, result in checks:
            if not result:
                print(f"  - {category}: {name}")
        return 1
    else:
        print("\n✅ ALL CHECKS PASSED")
        return 0


if __name__ == "__main__":
    sys.exit(main())
