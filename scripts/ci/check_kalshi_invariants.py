#!/usr/bin/env python3
"""
Pass 8 CI Script: Kalshi Invariant Checks

Runs in CI to ensure no regressions in:
- Direct Kalshi client usage outside order_router
- Archive imports in production code
- requests.*kalshi calls

Exit codes:
    0: All checks passed
    1: Direct client usage found
    2: Archive import in production
    3: Raw HTTP calls detected
    4: Multiple violations
"""

import ast
import os
import re
import sys
from pathlib import Path
from typing import List, Tuple, Set

# Violation tracking
violations: List[Tuple[str, int, str, str]] = []  # file, line, type, message

# ═══════════════════════════════════════════════════════════════════════════════
# Check 1: No direct Kalshi client usage outside allowed modules
# ═══════════════════════════════════════════════════════════════════════════════

ALLOWED_KALSHI_CLIENT_MODULES = {
    "merid/event_venues/kalshi/order_router.py",
    "merid/prediction/kalshi_tools.py",
    "merid/event_venues/kalshi/kalshi_venue_client.py",
    "merid_core/kalshi/rest_client.py",  # Low-level client
    "merid/event_venues/kalshi/fix_client.py",  # Low-level client
    # 2026-10-18: the kalshi venue package is the transport tier itself
    # (client.py, venue_adapter.py, trading.py, kalshi_rest_client.py,
    # kalshi_15m_time.py, robustness_integration.py all own clients).
    "merid/event_venues/kalshi/",
    # Canonical 15m entrypoint wires a client for market data / fills.
    "web/main_15m_lean.py",
    # Legacy kalshi_api.py owns the sanctioned _get_client singleton and the
    # Wave-11 FIX 403 guard (verified by checks 5/6 below).
    "web/api/kalshi_api.py",
    # Venue-adapter tier wrapping the client.
    "core/venues/kalshi_adapter.py",
    # Read-only data-path clients (positions / settlement export / diagnostics).
    "merid/prediction/agent_grid_15m.py",
    "merid/analysis/settlement_outcome_exporter.py",
    "merid/diagnostics/__init__.py",
}

# 2026-10-18: only client *construction* is enforced here. Method-call
# patterns (`.submit_order(`, `.cancel_order(`, ...) were dropped because
# they cannot attribute-resolve receivers and produced 35+ false positives
# against the canonical router, the internal matching engine, and legacy
# harnesses. Instantiating a raw Kalshi client is the actual bypass vector;
# raw-HTTP bypasses are covered by check 3.
KALSHI_CLIENT_PATTERNS = [
    r"KalshiRestClient\(",
    r"KalshiFIXClient\(",
    r"KalshiVenueClient\(",
]


def check_direct_kalshi_clients():
    """Check for direct Kalshi client usage outside allowed modules."""
    merid_dir = Path("merid")
    web_dir = Path("web")
    core_dir = Path("core")
    
    for directory in [merid_dir, web_dir, core_dir]:
        if not directory.exists():
            continue
            
        for py_file in directory.rglob("*.py"):
            # Skip allowed modules
            rel_path = str(py_file).replace("\\", "/")
            if any(allowed in rel_path for allowed in ALLOWED_KALSHI_CLIENT_MODULES):
                continue
            
            content = py_file.read_text(encoding="utf-8")
            lines = content.split("\n")
            
            for i, line in enumerate(lines, 1):
                for pattern in KALSHI_CLIENT_PATTERNS:
                    if re.search(pattern, line):
                        # Skip imports and comments
                        if line.strip().startswith("#"):
                            continue
                        if "import" in line and ("KalshiRestClient" in line or "KalshiFIXClient" in line):
                            continue
                        
                        violations.append((
                            str(py_file),
                            i,
                            "DIRECT_KALSHI_CLIENT",
                            f"Pattern '{pattern}' found outside allowed module"
                        ))


# ═══════════════════════════════════════════════════════════════════════════════
# Check 2: No archive imports in production (merid/, web/, core/)
# ═══════════════════════════════════════════════════════════════════════════════

ARCHIVE_IMPORT_PATTERNS = [
    r"^from archive\.",
    r"^import archive",
    r"from archive import",
]

ALLOWED_ARCHIVE_IMPORTS = {
    # These files are allowed to import archive (analytics/reporting)
    "web/api/archive.py",  # Archive API endpoints (post-trade analytics)
    # Orphaned legacy orchestrator: not imported by the canonical 15m stack
    # (only by its own test file). Its `from archive import ...` symbols no
    # longer exist, so the module is already unimportable dead code.
    "core/system_orchestrator.py",
}


def check_archive_imports():
    """Check for archive imports in production code."""
    for directory in ["merid", "web", "core"]:
        dir_path = Path(directory)
        if not dir_path.exists():
            continue
            
        for py_file in dir_path.rglob("*.py"):
            rel_path = str(py_file).replace("\\", "/")
            
            # Skip allowed files
            if any(allowed in rel_path for allowed in ALLOWED_ARCHIVE_IMPORTS):
                continue
            
            content = py_file.read_text(encoding="utf-8")
            lines = content.split("\n")
            
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                for pattern in ARCHIVE_IMPORT_PATTERNS:
                    if re.match(pattern, stripped):
                        violations.append((
                            str(py_file),
                            i,
                            "ARCHIVE_IMPORT",
                            f"Archive import in production code: {stripped[:50]}"
                        ))


# ═══════════════════════════════════════════════════════════════════════════════
# Check 3: No raw HTTP calls to Kalshi in scripts or API files
# ═══════════════════════════════════════════════════════════════════════════════

RAW_HTTP_PATTERNS = [
    r'requests\.(get|post|put|delete|patch)\(.*kalshi',
    r'requests\.(get|post|put|delete|patch)\(.*\.kalshi\.com',
    r'http\.client.*kalshi',
    r'urllib.*kalshi',
]

ALLOWED_HTTP_MODULES = {
    # These are allowed to make HTTP calls (low-level clients)
    "merid_core/kalshi/rest_client.py",
    "merid/event_venues/kalshi/kalshi_http_client.py",
    # ws.py performs an unauthenticated GET on a public Kalshi endpoint purely
    # to read the server Date header for WS-auth clock-skew compensation. It
    # never touches the order path, so it belongs to the venue transport tier.
    "merid/event_venues/kalshi/ws.py",
}


def check_raw_http_calls():
    """Check for raw HTTP calls to Kalshi."""
    self_path = Path(__file__).name
    for directory in ["merid", "web", "core", "scripts"]:
        dir_path = Path(directory)
        if not dir_path.exists():
            continue

        for py_file in dir_path.rglob("*.py"):
            rel_path = str(py_file).replace("\\", "/")

            # Skip allowed modules
            if any(allowed in rel_path for allowed in ALLOWED_HTTP_MODULES):
                continue

            # Skip this checker (its regex string literals self-match),
            # the repo's legacy-scripts dir, and underscore scratch scripts.
            if py_file.name == self_path or rel_path.startswith("scripts/legacy/") or py_file.name.startswith("_"):
                continue
            
            content = py_file.read_text(encoding="utf-8")
            lines = content.split("\n")
            
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                    
                for pattern in RAW_HTTP_PATTERNS:
                    if re.search(pattern, stripped, re.IGNORECASE):
                        violations.append((
                            str(py_file),
                            i,
                            "RAW_HTTP_KALSHI",
                            f"Raw HTTP call to Kalshi: {stripped[:60]}"
                        ))


# ═══════════════════════════════════════════════════════════════════════════════
# Check 4: Verify archive/__init__.py has import guard
# ═══════════════════════════════════════════════════════════════════════════════

def check_archive_guard_present():
    """Verify archive import guard is in place when the package exists."""
    archive_init = Path("archive/__init__.py")

    if not archive_init.exists():
        # 2026-10-18: the Pass-8 guarded `archive` package was reduced to
        # archive/legacy/ with no __init__.py. There is no package left to
        # guard; check 2 still polices `from archive import` in prod code.
        return
    
    content = archive_init.read_text(encoding="utf-8")
    
    guard_indicators = [
        "PASS 8",
        "_enforce_archive_import_guard",
        "ImportError",
        "blocked in",
    ]
    
    if not any(indicator in content for indicator in guard_indicators):
        violations.append((
            str(archive_init),
            0,
            "MISSING_ARCHIVE_GUARD",
            "archive/__init__.py missing import guard (Pass 8)"
        ))


# ═══════════════════════════════════════════════════════════════════════════════
# Check 5: Verify FIX endpoint guard (Wave 11)
# ═══════════════════════════════════════════════════════════════════════════════

def check_fix_endpoint_guard():
    """Verify FIX endpoint guard exists and is correct."""
    kalshi_api = Path("web/api/kalshi_api.py")
    if not kalshi_api.exists():
        violations.append((
            str(kalshi_api),
            0,
            "MISSING_FIX_GUARD",
            "kalshi_api.py not found - cannot verify FIX guard"
        ))
        return
    
    content = kalshi_api.read_text(encoding="utf-8")
    
    required_elements = [
        ("PASS 8 P0: Hard disable FIX endpoint", "PASS 8 marker"),
        ('if _mode in ("live", "paper")', "mode check"),
        ("403", "HTTP 403 status"),
        ("canonical executor", "error message reference"),
    ]
    
    for element, description in required_elements:
        if element not in content:
            violations.append((
                str(kalshi_api),
                0,
                "MISSING_FIX_GUARD",
                f"FIX endpoint guard missing: {description}"
            ))


# ═══════════════════════════════════════════════════════════════════════════════
# Check 6: Verify REST fallback fail-closed guard (Wave 11)
# ═══════════════════════════════════════════════════════════════════════════════

def check_rest_fallback_guard():
    """Verify REST fallback is fail-closed."""
    kalshi_api = Path("web/api/kalshi_api.py")
    if not kalshi_api.exists():
        violations.append((
            str(kalshi_api),
            0,
            "MISSING_REST_FALLBACK_GUARD",
            "kalshi_api.py not found - cannot verify REST fallback guard"
        ))
        return
    
    content = kalshi_api.read_text(encoding="utf-8")
    
    required_elements = [
        ("PASS 8 P0: FAIL CLOSED", "PASS 8 marker"),
        ("503", "HTTP 503 status"),
        ("kill_switch", "kill switch trigger"),
    ]
    
    for element, description in required_elements:
        if element not in content:
            violations.append((
                str(kalshi_api),
                0,
                "MISSING_REST_FALLBACK_GUARD",
                f"REST fallback guard missing: {description}"
            ))


# ═══════════════════════════════════════════════════════════════════════════════
# Check 7: Verify CT API module guard (Wave 11)
# ═══════════════════════════════════════════════════════════════════════════════

def check_ct_api_guard():
    """Verify CT API module guard exists (module retired in doc cleanup)."""
    ct_api = Path("web/api/kalshi_continuous_trader_api.py")
    if not ct_api.exists():
        # Module was retired; nothing to guard. Re-flag only if it returns
        # without the guard.
        return
    
    content = ct_api.read_text(encoding="utf-8")
    
    required_elements = [
        ("PASS 8 P0: Module-level guard", "PASS 8 marker"),
        ("403", "HTTP 403 status"),
    ]
    
    for element, description in required_elements:
        if element not in content:
            violations.append((
                str(ct_api),
                0,
                "MISSING_CT_GUARD",
                f"CT API guard missing: {description}"
            ))


# ═══════════════════════════════════════════════════════════════════════════════
# Check 8: Verify startup enforcement wiring (Wave 11)
# ═══════════════════════════════════════════════════════════════════════════════

def check_startup_enforcement():
    """Verify startup enforcement is wired in the canonical 15m entrypoint.

    2026-10-18: this check previously targeted web/main.py (the quarantined
    legacy entrypoint) and looked for Wave-11 markers that only exist there.
    The production entrypoint is web/main_15m_lean.py, whose live startup
    preflight state machine is defined by AGENTS.md (STARTING ->
    PREFLIGHT_RUNNING -> LIVE_ENTRIES_ENABLED/HALTED).
    """
    main_py = Path("web/main_15m_lean.py")
    if not main_py.exists():
        violations.append((
            str(main_py),
            0,
            "MISSING_STARTUP_ENFORCEMENT",
            "web/main_15m_lean.py not found - cannot verify startup enforcement"
        ))
        return

    content = main_py.read_text(encoding="utf-8")

    required_elements = [
        ("run_p0_preflight_checks", "P0 preflight checks call"),
        ("PREFLIGHT_RUNNING", "preflight state-machine transition"),
        ("LIVE_ENTRIES_", "live entries state"),
    ]
    
    for element, description in required_elements:
        if element not in content:
            violations.append((
                str(main_py),
                0,
                "MISSING_STARTUP_ENFORCEMENT",
                f"Startup enforcement missing: {description}"
            ))


# ═══════════════════════════════════════════════════════════════════════════════
# Main execution
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 80)
    print("Wave 11 CI: Kalshi Invariant Checks")
    print("=" * 80)
    
    print("\n[1/8] Checking direct Kalshi client usage...")
    check_direct_kalshi_clients()
    
    print("[2/8] Checking archive imports in production...")
    check_archive_imports()
    
    print("[3/8] Checking raw HTTP calls to Kalshi...")
    check_raw_http_calls()
    
    print("[4/8] Checking archive import guard...")
    check_archive_guard_present()
    
    print("[5/8] Checking FIX endpoint guard (Wave 11)...")
    check_fix_endpoint_guard()
    
    print("[6/8] Checking REST fallback guard (Wave 11)...")
    check_rest_fallback_guard()
    
    print("[7/8] Checking CT API guard (Wave 11)...")
    check_ct_api_guard()
    
    print("[8/8] Checking startup enforcement (Wave 11)...")
    check_startup_enforcement()
    
    # Report results
    print("\n" + "=" * 80)
    print(f"Results: {len(violations)} violations found")
    print("=" * 80)
    
    if violations:
        # Group by type
        by_type: dict = {}
        for file, line, vtype, msg in violations:
            by_type.setdefault(vtype, []).append((file, line, msg))
        
        for vtype, items in sorted(by_type.items()):
            print(f"\n{vtype} ({len(items)}):")
            print("-" * 60)
            for file, line, msg in items[:10]:  # Show first 10 per type
                print(f"  {file}:{line} - {msg}")
            if len(items) > 10:
                print(f"  ... and {len(items) - 10} more")
        
        print("\n" + "=" * 80)
        print("❌ FAIL: Invariant violations detected")
        print("=" * 80)
        
        # Determine exit code
        exit_code = 0
        if "DIRECT_KALSHI_CLIENT" in by_type:
            exit_code |= 1
        if "ARCHIVE_IMPORT" in by_type:
            exit_code |= 2
        if "RAW_HTTP_KALSHI" in by_type:
            exit_code |= 4
        if "MISSING_ARCHIVE_GUARD" in by_type:
            exit_code |= 8
        if "MISSING_FIX_GUARD" in by_type:
            exit_code |= 16
        if "MISSING_REST_FALLBACK_GUARD" in by_type:
            exit_code |= 32
        if "MISSING_CT_GUARD" in by_type:
            exit_code |= 64
        if "MISSING_STARTUP_ENFORCEMENT" in by_type:
            exit_code |= 128
        
        return exit_code if exit_code != 0 else 4
    
    print("\n" + "=" * 80)
    print("✅ PASS: All invariants verified")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
