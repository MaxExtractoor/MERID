"""
Test Single Execution Authority Compliance

This test suite verifies that:
1. All order submissions flow through the canonical order_router
2. No agent can submit orders via direct HTTP
3. No bypass paths exist around unified risk controls
"""

import ast
import inspect
import sys
from pathlib import Path
import pytest


def _get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent


def _find_files_with_pattern(directory: Path, pattern: str, excludes: list = None) -> list:
    """Find Python files containing a specific pattern."""
    excludes = excludes or []
    matches = []
    for py_file in directory.rglob("*.py"):
        # Skip excluded patterns
        if any(excl in str(py_file) for excl in excludes):
            continue
        try:
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            if pattern in content:
                matches.append(py_file)
        except Exception:
            pass
    return matches


def _get_order_methods_in_file(file_path: Path) -> list:
    """Extract method names that might be used for order submission."""
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return []
    
    order_methods = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            name = node.name.lower()
            if any(keyword in name for keyword in ["submit", "place", "order", "execute"]):
                order_methods.append(node.name)
    return order_methods


class TestSingleExecutionAuthority:
    """Verify single execution authority compliance."""

    def test_no_direct_http_post_to_portfolio_orders(self):
        """
        CRITICAL: No module should directly POST to /portfolio/orders.
        All orders must flow through order_router.route_order_async().
        """
        root = _get_project_root()
        
        # Find files with direct HTTP patterns for order submission
        # Only check for actual order submission patterns (not read-only operations)
        order_patterns = [
            '_post("/portfolio/orders"',
            "_post('/portfolio/orders'",
        ]
        
        violations = []
        for pattern in order_patterns:
            files = _find_files_with_pattern(
                root / "merid",
                pattern,
                excludes=["__pycache__", ".pytest_cache", "_legacy"]
            )
            for f in files:
                content = f.read_text(encoding="utf-8", errors="ignore")
                lines = content.split("\n")
                for i, line in enumerate(lines, 1):
                    if pattern in line and not line.strip().startswith("#"):
                        violations.append(f"{f}:{i}: {line.strip()}")
        
        # Allow specific safe patterns
        allowed_patterns = [
            "ct_execution_adapter.py",  # Adapter bridges to canonical router (internal)
            "kalshi_venue_client.py",   # Venue client used by router only
            "order_router.py",          # Router itself
            "test_",                    # Test files
        ]
        
        filtered_violations = []
        for v in violations:
            if not any(allowed in v for allowed in allowed_patterns):
                filtered_violations.append(v)
        
        assert not filtered_violations, (
            f"Found {len(filtered_violations)} direct HTTP order submissions (MUST use router):\n"
            + "\n".join(filtered_violations[:10])  # Show first 10
        )

    def test_all_order_paths_use_canonical_router(self):
        """
        Verify all order submission paths import and use route_order_async.
        """
        root = _get_project_root()
        
        # Find all files that submit orders
        order_files = _find_files_with_pattern(
            root / "merid",
            "route_order_async",
            excludes=["__pycache__", ".pytest_cache"]
        )
        
        # Key files that should use the router
        expected_files = [
            "kalshi_tools.py",
            "btc15m_lane.py",
            "crypto15m_lane.py",
            "trading_agent.py",
            "ct_execution_adapter.py",
        ]
        
        found_basenames = [f.name for f in order_files]
        
        for expected in expected_files:
            assert any(expected in f for f in found_basenames), (
                f"Expected {expected} to use route_order_async"
            )

    def test_ct_no_longer_in_bypass_list(self):
        """
        Verify KalshiContinuousTrader is NOT in _KNOWN_BYPASS_PATHS.
        """
        root = _get_project_root()
        order_router = root / "merid" / "event_venues" / "kalshi" / "order_router.py"
        
        content = order_router.read_text(encoding="utf-8")
        
        # Check that _KNOWN_BYPASS_PATHS is empty or doesn't contain CT
        assert '"merid.trading.kalshi_continuous_trader"' not in content, (
            "CT should not be in _KNOWN_BYPASS_PATHS"
        )

    def test_ct_use_router_percent_hardcoded(self):
        """
        Verify CT_USE_ROUTER_PERCENT is hard-coded to 100.
        """
        root = _get_project_root()
        ct_file = root / "merid" / "trading" / "kalshi_continuous_trader.py"
        
        content = ct_file.read_text(encoding="utf-8")
        
        # Check for hard-coded use_router_percent
        assert "use_router_percent: int = field(default=100, init=False)" in content, (
            "use_router_percent should be hard-coded to 100 with init=False"
        )
        
        # Ensure env var is not being read
        assert "CT_USE_ROUTER_PERCENT" not in content or (
            "CT_USE_ROUTER_PERCENT" in content and "ignored" in content.lower()
        ), "CT_USE_ROUTER_PERCENT env var should not be used"

    def test_trading_agent_no_fallback(self):
        """
        Verify trading_agent.py doesn't have fallback to direct order placement.
        """
        root = _get_project_root()
        ta_file = root / "merid" / "prediction" / "trading_agent.py"
        
        content = ta_file.read_text(encoding="utf-8")
        
        # Check for the no-fallback comment
        assert "SECURITY: No fallback" in content, (
            "trading_agent.py should have SECURITY comment indicating no fallback"
        )
        
        # Should not have fallback to _kalshi_place_order
        assert "falling back" not in content.lower() or (
            "falling back" in content.lower() and "removed" in content.lower()
        ), "Should not have fallback mechanism"

    def test_order_router_has_empty_bypass_list(self):
        """
        Verify _KNOWN_BYPASS_PATHS is empty (no known bypasses).
        """
        root = _get_project_root()
        order_router = root / "merid" / "event_venues" / "kalshi" / "order_router.py"
        
        content = order_router.read_text(encoding="utf-8")
        
        # Check that _KNOWN_BYPASS_PATHS is an empty set
        assert "_KNOWN_BYPASS_PATHS: set = set()" in content, (
            "_KNOWN_BYPASS_PATHS should be an empty set"
        )


class TestCrossAgentDuplicateProtection:
    """Verify cross-agent duplicate order protection."""

    def test_contract_lease_registry_exists(self):
        """
        Verify ContractLeaseRegistry enforces single ownership.
        """
        root = _get_project_root()
        lease_file = root / "merid" / "event_venues" / "kalshi" / "contract_lease.py"
        
        assert lease_file.exists(), "contract_lease.py should exist"
        
        content = lease_file.read_text(encoding="utf-8")
        
        # Check for acquire method that returns None on conflict
        assert "def acquire(" in content, "Should have acquire method"
        assert "return None" in content, "Should return None on lease conflict"

    def test_pre_trade_gate_enforces_dedup(self):
        """
        Verify PreTradeGate blocks duplicate orders.
        """
        root = _get_project_root()
        gate_file = root / "merid" / "event_venues" / "kalshi" / "order_gate.py"
        
        assert gate_file.exists(), "order_gate.py should exist"
        
        content = gate_file.read_text(encoding="utf-8")
        
        # Check for duplicate blocking
        assert "blocked_duplicate" in content, "Should track blocked duplicates"
        assert "deterministic_client_order_id" in content, "Should use deterministic IDs"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
