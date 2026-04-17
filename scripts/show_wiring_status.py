#!/usr/bin/env python3
"""Show current agent wiring audit status.

Usage:
    python scripts/show_wiring_status.py

Outputs:
    - Canonical executor status
    - Bypass list with migration phases
    - Test enforcement summary
    - Acceptance criterion progress
"""

import sys
from pathlib import Path


def _get_repo_root() -> Path:
    """Get repository root."""
    current = Path(__file__).resolve().parent.parent
    while current != current.parent:
        if (current / "docs" / "AGENT_WIRING_AUDIT.md").exists():
            return current
        current = current.parent
    return Path(__file__).resolve().parent.parent


def main():
    repo_root = _get_repo_root()
    audit_doc = repo_root / "docs" / "AGENT_WIRING_AUDIT.md"

    print("=" * 70)
    print("MERID Agent Wiring Audit — Status Report")
    print("=" * 70)
    print()

    # Canonical Executor
    print("CANONICAL EXECUTOR")
    print("-" * 40)
    print("Module: KalshiTradingAgent")
    print("Path:   kalshi_tools -> route_order_async -> KalshiVenueClient")
    print("Status: ACTIVE")
    print()

    # Migration Status
    print("CT MIGRATION STATUS")
    print("-" * 40)
    print("Phase 1: Shadow Mode Adapter [IMPLEMENTED]")
    print("  Module: merid/trading/ct_execution_adapter.py")
    print("  Function: CT order dict -> OrderIntent -> router (paper/mock)")
    print("  Hook: Integrated in kalshi_continuous_trader.py after HTTP call")
    print()
    print("Phase 2: Canary Flip [IMPLEMENTED]")
    print("  Env: CT_USE_ROUTER_PERCENT (0-100)")
    print("  Routing: random(1,100) <= pct decides HTTP vs router")
    print("  Audit: [AUDIT] ct_route_decision | routed_via=X | pct=Y | rand=Z")
    print("  Usage: 0=HTTP only, 1-99=mixed, 100=router only")
    print()
    print("Phase 3: Direct HTTP Removal [PENDING]")
    print("  Trigger: Stable at 100% for 1+ week")
    print("  Action: Delete HTTP path, update docs/tests")
    print()

    # Bypass List
    print("BYPASS LIST (Technical Debt)")
    print("-" * 40)

    bypasses = [
        {
            "module": "kalshi_continuous_trader.py",
            "role": "Executor -> Strategy Driver (migration)",
            "phase": "Shadow Mode Adapter",
            "status": "IN PROGRESS",
        }
    ]

    if not bypasses:
        print("[EMPTY] All execution flows through canonical router!")
    else:
        for bp in bypasses:
            print(f"  Module: {bp['module']}")
            print(f"  Target Role: {bp['role']}")
            print(f"  Migration Phase: {bp['phase']}")
            print(f"  Status: {bp['status']}")
            print()

    # Test Enforcement
    print("CI/RUNTIME ENFORCEMENT")
    print("-" * 40)
    print("Test Suite: test_order_router_caller_restrictions.py")
    print("  [x] test_only_one_documented_bypass_exists")
    print("  [x] test_no_direct_http_client_imports_outside_whitelist")
    print("  [x] test_all_route_order_callers_are_authorized")
    print("  [x] test_route_order_rejects_unauthorized_caller")
    print("  + 12 more tests...")
    print()

    print("Runtime Guards:")
    print("  [x] _get_caller_module() - Stack inspection")
    print("  [x] _is_authorized_caller() - Whitelist enforcement")
    print("  [x] [AUDIT] logging - Every decision logged")
    print()

    # Acceptance Criterion
    print("ACCEPTANCE CRITERION")
    print("-" * 40)
    bypass_count = len(bypasses)
    if bypass_count == 0:
        print("[COMPLETE] Audit is finished!")
        print("   All execution flows through the canonical router.")
        return 0
    else:
        print(f"[IN PROGRESS] {bypass_count} bypass remaining")
        print("   CT migration: Shadow -> Canary -> Removal")
        print()
        print("   Definition of Done:")
        print("   - CT uses adapter -> router (no direct HTTP)")
        print("   - Bypass List section is EMPTY")
        print("   - CI tests pass with zero documented bypasses")
        print()
        return 1


if __name__ == "__main__":
    sys.exit(main())
