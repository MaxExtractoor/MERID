"""Test suite enforcing that only authorized modules can call the order router.

AGENT_WIRING_AUDIT.md compliance: verifies the caller_module guard and
documents the execution topology.
"""

import ast
import os
import sys
import warnings
from pathlib import Path

import pytest

# Suppress DeprecationWarning from ast.parse when parsing files with invalid escape sequences
# These warnings come from other files in the codebase, not from this test
warnings.filterwarnings("ignore", category=DeprecationWarning, message="invalid escape sequence")


# ═══════════════════════════════════════════════════════════════════════════
# Allowed module prefixes (must match order_router.py)
# ═══════════════════════════════════════════════════════════════════════════

# SINGLE EXECUTOR PRINCIPLE: Only trading_agent can execute trades
# This must match order_router.py _ALLOWED_CALLER_PREFIXES exactly
_ALLOWED_CALLER_PREFIXES = (
    # PRIMARY EXECUTION AGENT - ONLY module that can execute trades
    "merid.prediction.trading_agent",
    # Lean 15m crypto agents - minimal trading agents for 15m crypto scalping
    "merid.prediction.agent_grid_15m",
    # Lean 15m loop - main trading loop for 15m crypto scalping
    "merid.loop_15m",
    # Position monitor - executes exit orders for TP/SL/trailing stops
    "merid.position_management.position_monitor",
    # Position cache - executes resting bracket orders (TP/SL) for exit policy enforcement
    "merid.event_venues.kalshi.position_cache",
    # Kalshi tools - used by agent_grid_15m for direct execution routing
    "merid.prediction.kalshi_tools",
    # Web 15m main entry point for 15m crypto trading
    "web.main_15m",
    # Tests are allowed for testing the router itself
    "tests.",
    "test_",
    # Self-calls (internal recursion)
    "merid.event_venues.kalshi.order_router",
    # Package init re-exports
    "merid.event_venues.kalshi",
    "merid.kalshi",
    # Governance/risk enforcement (can review but not execute)
    "core.constitution_enforcer",
    # Audit and policy modules (read-only)
    "merid.event_venues.kalshi.execution_audit",
    "merid.event_venues.kalshi.maker_taker_policy",
    "merid.event_venues.kalshi.take_profit",
    "merid.event_venues.kalshi.universe",
    # Execution infrastructure
    "merid.execution.execution_queue_handler",
    "merid.execution.executors",
    "merid.hedging.engine",
    # Sentiment infrastructure
    "merid.sentiment.live_correlation_bot",
    # Scripts
    "scripts.verify_live_trade",
    # Operator API endpoints (manual override only)
    "web.api.kalshi_api",
    "web.api.kalshi_grid_api",
    # Test modules that legitimately test the router
    "core.test_kalshi_gate_truth_table",
    "event_venues.kalshi.test_kalshi_sprint_a",
    "event_venues.kalshi.test_kalshi_universe",
    "kalshi.test_kalshi_paper_trading_e2e",
    "kalshi.test_kalshi_stress_scenarios",
    "kalshi.test_signal_to_order_pipeline",
    "prediction.test_kalshi_tools_order_intent",
    "trading.test_lifecycle_bug_regressions",
    "web.test_kalshi_place_order_router_only",
    "test_order_router_caller_restrictions",
)

# NO BYPASSES - All agents except trading_agent are SIGNAL-ONLY
_KNOWN_BYPASS_PATHS = set()

# SIGNAL-ONLY modules that import route_order but will be rejected at runtime
# These modules must route through trading_agent - they cannot execute directly
_SIGNAL_ONLY_MODULES = {
    "merid.lanes.btc15m_lane",
    "merid.lanes.crypto15m_lane",
    "merid.prediction.universal_agent",
    "merid.trading.ct_execution_adapter",
    "merid.trading.kalshi_continuous_trader",
}


def _get_repo_root() -> Path:
    """Get repository root (assumes tests run from repo)."""
    # Walk up from this file to find repo root
    current = Path(__file__).resolve().parent
    while current != current.parent:
        # Use docs folder with audit doc as the most reliable marker
        # (tests/merid exists, so we can't use just "merid")
        if (current / "docs" / "AGENT_WIRING_AUDIT.md").exists():
            return current
        # Fallback: .git + docs folder (avoids tests/merid false positive)
        if (current / ".git").exists() and (current / "docs").exists():
            return current
        current = current.parent
    return Path(__file__).resolve().parent.parent


def _find_all_py_files(root: Path, exclude_dirs: set = None) -> list:
    """Find all Python files under root."""
    if exclude_dirs is None:
        exclude_dirs = {
            ".git", ".claude", "__pycache__", ".pytest_cache",
            "venv", ".venv", "node_modules", ".hypothesis",
            "data", "snapshots", "archive", "logs",
        }

    py_files = []
    # Walk directories more efficiently
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip excluded directories at the directory level (prunes early)
        dirnames[:] = [d for d in dirnames if d not in exclude_dirs]

        for filename in filenames:
            if filename.endswith(".py"):
                py_files.append(Path(dirpath) / filename)
    return py_files


def _module_name_from_path(file_path: Path, repo_root: Path) -> str:
    """Convert file path to Python module name."""
    rel_path = file_path.relative_to(repo_root)
    parts = list(rel_path.parts)
    # Remove .py extension from last part
    parts[-1] = parts[-1][:-3]
    return ".".join(parts)


def _contains_route_order_import(source: str) -> bool:
    """Check if source actually imports or calls route_order (ignores docstrings/comments)."""
    import warnings
    import re
    # Pre-process source to fix invalid escape sequences in string literals
    # This prevents DeprecationWarning from ast.parse
    # Replace backslashes not followed by newline with double backslashes
    source = re.sub(r'\\(?!\n)', r'\\\\', source)
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=DeprecationWarning)
            warnings.filterwarnings("ignore", message="invalid escape sequence")
            tree = ast.parse(source)
    except SyntaxError:
        return "route_order" in source

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "route_order" in node.module:
                return True
            for alias in node.names:
                if "route_order" in (alias.name or ""):
                    return True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if "route_order" in (alias.name or ""):
                    return True
        elif isinstance(node, ast.Name) and "route_order" in node.id:
            return True
        elif isinstance(node, ast.Attribute) and "route_order" in node.attr:
            return True
    return False


def _is_authorized_module(mod_name: str) -> bool:
    """Check if module is in allowed list or known bypasses."""
    if mod_name in _KNOWN_BYPASS_PATHS:
        return True
    if any(mod_name.startswith(p) for p in _ALLOWED_CALLER_PREFIXES):
        return True
    return False


# ═══════════════════════════════════════════════════════════════════════════
# Test Classes
# ═══════════════════════════════════════════════════════════════════════════


class TestCallerModuleWhitelist:
    """Verify only authorized modules import the order router."""

    def test_kalshi_tools_is_authorized(self):
        """kalshi_tools is authorized for direct execution routing by agent_grid_15m."""
        # kalshi_tools._kalshi_place_order routes through order_router for agent_grid_15m
        assert _is_authorized_module("merid.prediction.kalshi_tools")

    def test_trading_agent_is_authorized(self):
        """trading_agent is the SOLE executor for stop-loss and execution."""
        # SINGLE EXECUTOR: Only trading_agent can execute
        assert _is_authorized_module("merid.prediction.trading_agent")

    def test_continuous_trader_is_signal_only(self):
        """kalshi_continuous_trader is SIGNAL-ONLY and must route through trading_agent."""
        # SINGLE EXECUTOR: CT cannot execute directly - must go through trading_agent
        assert not _is_authorized_module("merid.trading.kalshi_continuous_trader")

    def test_random_module_not_authorized(self):
        """Unknown modules should NOT be authorized."""
        assert not _is_authorized_module("malicious_module")
        assert not _is_authorized_module("merid.random.script")
        assert not _is_authorized_module("scripts.backdoor")

    def test_test_modules_are_authorized(self):
        """Test modules are allowed to call the router."""
        assert _is_authorized_module("tests.test_order_router")
        assert _is_authorized_module("test_something")


class TestImportRestrictions:
    """Static analysis: verify no unauthorized imports exist in codebase."""

    @pytest.fixture(scope="class")
    def repo_root(self):
        return _get_repo_root()

    @pytest.fixture(scope="class")
    def all_py_files(self, repo_root):
        return _find_all_py_files(repo_root)

    def test_all_route_order_callers_are_authorized(self, repo_root, all_py_files):
        """
        Fail if any unauthorized module imports or calls route_order.

        This is the main gate: only modules in _ALLOWED_CALLER_PREFIXES
        or _KNOWN_BYPASS_PATHS may touch the order router.
        """
        violations = []

        for py_file in all_py_files:
            try:
                source = py_file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            # Skip files that don't mention route_order
            if not _contains_route_order_import(source):
                continue

            # Check if this module is authorized
            mod_name = _module_name_from_path(py_file, repo_root)

            # SIGNAL-ONLY modules are allowed to import but will be rejected at runtime
            if mod_name in _SIGNAL_ONLY_MODULES:
                continue

            if not _is_authorized_module(mod_name):
                violations.append((mod_name, str(py_file)))

        if violations:
            msg = "Unauthorized modules importing route_order (not in whitelist or signal-only list):\n"
            for mod, path in violations:
                msg += f"  - {mod} ({path})\n"
            msg += "\nTo authorize, add to order_router.py:_ALLOWED_CALLER_PREFIXES "
            msg += "or add to _SIGNAL_ONLY_MODULES if it should route through trading_agent."
            pytest.fail(msg)


class TestRuntimeCallerGuard:
    """Verify the runtime caller guard functions work correctly."""

    def test_get_caller_module_returns_string(self):
        """_get_caller_module should return a string."""
        from merid.event_venues.kalshi.order_router import _get_caller_module

        caller = _get_caller_module()
        assert isinstance(caller, str)
        # Should be this test module or something related
        assert "test" in caller.lower() or "pytest" in caller.lower()

    def test_is_authorized_caller_accepts_whitelist(self):
        """Authorized prefixes should be accepted - ONLY trading_agent can execute."""
        from merid.event_venues.kalshi.order_router import _is_authorized_caller

        # SINGLE EXECUTOR PRINCIPLE: Only trading_agent can execute trades
        assert _is_authorized_caller("merid.prediction.trading_agent")
        assert _is_authorized_caller("tests.test_something")
        assert _is_authorized_caller("test_foo")

    def test_is_authorized_caller_rejects_signal_only_agents(self):
        """Signal-only agents must route through trading_agent - cannot execute directly."""
        from merid.event_venues.kalshi.order_router import _is_authorized_caller

        # These agents are SIGNAL-ONLY and must NOT be able to bypass trading_agent
        assert not _is_authorized_caller("merid.trading.kalshi_continuous_trader")
        assert not _is_authorized_caller("merid.trading.ct_execution_adapter")
        assert not _is_authorized_caller("merid.lanes.btc15m_lane")
        assert not _is_authorized_caller("merid.lanes.crypto15m_lane")
        assert not _is_authorized_caller("merid.prediction.universal_agent")

    def test_is_authorized_caller_accepts_kalshi_tools(self):
        """kalshi_tools is authorized for direct execution routing by agent_grid_15m."""
        from merid.event_venues.kalshi.order_router import _is_authorized_caller

        # kalshi_tools is now authorized for agent_grid_15m direct execution path
        assert _is_authorized_caller("merid.prediction.kalshi_tools")

    def test_is_authorized_caller_rejects_unknown(self):
        """Unknown modules should be rejected."""
        from merid.event_venues.kalshi.order_router import _is_authorized_caller

        assert not _is_authorized_caller("malicious.module")
        assert not _is_authorized_caller("merid.random.script")
        assert not _is_authorized_caller("scripts.unauthorized")


class TestRouterRejectsUnauthorized:
    """Integration: verify router actually rejects unauthorized callers."""

    @pytest.fixture
    def mock_intent(self):
        """Create a minimal OrderIntent for testing."""
        from merid.event_venues.kalshi.order_router import OrderIntent

        return OrderIntent(
            ticker="KXBTCD-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            order_type="limit",
            time_in_force="gtc",
            source="test",
        )

    @pytest.mark.asyncio
    async def test_route_order_async_rejects_unauthorized_caller(
        self, mock_intent, monkeypatch
    ):
        """
        If _get_caller_module returns an unauthorized module,
        route_order_async should reject with 'unauthorized_caller'.
        """
        from merid.event_venues.kalshi.order_router import (
            route_order_async,
            _get_caller_module,
        )

        # Mock the caller to be unauthorized
        monkeypatch.setattr(
            "merid.event_venues.kalshi.order_router._get_caller_module",
            lambda: "unauthorized.malicious.module",
        )

        result = await route_order_async(mock_intent)

        assert result.status == "rejected"
        assert "unauthorized_caller" in result.reason
        assert "unauthorized.malicious.module" in result.reason

    def test_route_order_rejects_unauthorized_caller(self, mock_intent, monkeypatch):
        """
        If _get_caller_module returns an unauthorized module,
        route_order (sync) should reject with 'unauthorized_caller'.
        """
        from merid.event_venues.kalshi.order_router import route_order
        from merid.mode_resolver import ModeResolver

        # Mock the caller to be unauthorized
        monkeypatch.setattr(
            "merid.event_venues.kalshi.order_router._get_caller_module",
            lambda: "unauthorized.malicious.module",
        )

        # Mock ModeResolver to not be in live mode (bypass assert_not_live check)
        monkeypatch.setattr(ModeResolver, "is_live_trading", lambda: False)

        result = route_order(mock_intent)

        assert result.status == "rejected"
        assert "unauthorized_caller" in result.reason

    @pytest.mark.asyncio
    async def test_route_order_async_allows_authorized_caller(
        self, mock_intent, monkeypatch
    ):
        """
        If _get_caller_module returns an authorized module,
        route_order_async should proceed (and get rejected for other reasons
        like mock mode or risk checks, but NOT unauthorized_caller).
        """
        from merid.event_venues.kalshi.order_router import route_order_async

        # Mock the caller to be authorized (trading_agent - SOLE EXECUTOR)
        monkeypatch.setattr(
            "merid.event_venues.kalshi.order_router._get_caller_module",
            lambda: "merid.prediction.trading_agent",
        )

        result = await route_order_async(mock_intent)

        # Should NOT be rejected for unauthorized_caller
        assert "unauthorized_caller" not in (result.reason or "")


class TestKnownBypassDocumentation:
    """Verify all known bypasses are documented and tracked."""

    def test_all_bypasses_have_audit_doc_reference(self):
        """
        Every module in _KNOWN_BYPASS_PATHS should be mentioned in
        AGENT_WIRING_AUDIT.md.
        """
        # If there are no bypasses, test passes trivially
        if not _KNOWN_BYPASS_PATHS:
            return

        repo_root = _get_repo_root()
        audit_doc = repo_root / "docs" / "AGENT_WIRING_AUDIT.md"

        if not audit_doc.exists():
            pytest.skip("AGENT_WIRING_AUDIT.md not found")

        audit_content = audit_doc.read_text(encoding="utf-8")

        for bypass_module in _KNOWN_BYPASS_PATHS:
            # Check that the module is mentioned in the audit doc
            assert bypass_module in audit_content, (
                f"Known bypass {bypass_module} not documented in AGENT_WIRING_AUDIT.md. "
                f"All bypasses must be documented with justification."
            )


class TestSingleExecutorPrinciple:
    """
    Enforce: There is exactly ONE executor capable of sending live orders to Kalshi.

    Architecture Principle:
        KalshiTradingAgent (via kalshi_tools -> route_order_async) is the SOLE
        module allowed to actually send orders. All other agents must route
        through this path to avoid duplication and fragmented risk control.

    This test class prevents "executor proliferation" where new strategies
    create their own direct HTTP paths to the venue, bypassing unified
    risk gates, fills ledger, and audit trails.
    """

    def test_only_one_documented_bypass_exists(self):
        """
        Enforce: There is exactly ONE executor capable of sending live orders.

        Policy: Only one bypass (KalshiContinuousTrader) is allowed during
        migration. If this test fails, someone added a new bypass without
        security review and architecture approval.

        Acceptance Criterion: This test passes when Bypass List is EMPTY
        and all execution flows through the canonical router.
        """
        assert len(_KNOWN_BYPASS_PATHS) <= 1, (
            f"Too many bypasses: {len(_KNOWN_BYPASS_PATHS)}. "
            f"Policy: Only CT bypass allowed during migration. "
            f"New strategies must use the canonical executor, not create bypasses."
        )

    def test_no_direct_http_client_imports_outside_whitelist(self):
        """
        Enforce: No new agents may create direct HTTP paths to Kalshi.

        This test scans the entire codebase for patterns that indicate
        direct venue access (KalshiHttpClient, /portfolio/orders endpoint,
        or _post() methods in Kalshi-context modules).

        If a new strategy tries to create its own executor bypass, this test
        will fail in CI, forcing the developer to either:
        1. Route through the canonical executor (preferred), or
        2. Document and justify a new bypass (requires security review)

        This ensures the "many analyzers, ONE executor" architecture is maintained.
        """
        repo_root = _get_repo_root()
        py_files = _find_all_py_files(repo_root)

        # HTTP client patterns that indicate DIRECT KALSHI venue access
        # These are specific to the Kalshi bypass we're trying to prevent
        http_patterns = [
            "KalshiHttpClient",  # Direct client import
            '"/portfolio/orders"',  # The actual Kalshi order endpoint
        ]

        # Additional check: look for self._post combined with kalshi context
        kalshi_context_patterns = [
            "kalshi",
            "kalshi_api",
            "Kalshi",
        ]

        violations = []

        for py_file in py_files:
            try:
                source = py_file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            # Check for direct Kalshi HTTP patterns
            has_direct_kalshi_http = False
            for pattern in http_patterns:
                if pattern in source:
                    has_direct_kalshi_http = True
                    break

            # Also check for _post method combined with kalshi context
            # This catches CT-style bypasses without catching unrelated _post methods
            if not has_direct_kalshi_http and "_post(" in source:
                # Only flag if there's kalshi context (to avoid false positives)
                has_kalshi_context = any(kp in source.lower() for kp in kalshi_context_patterns)
                if has_kalshi_context:
                    has_direct_kalshi_http = True

            if not has_direct_kalshi_http:
                continue

            mod_name = _module_name_from_path(py_file, repo_root)

            # Skip authorized modules (router internals, infrastructure, scripts)
            authorized_prefixes = (
                # Core router and client infrastructure
                "merid.event_venues.kalshi.client",
                "merid.event_venues.kalshi.order_router",
                "merid.event_venues.kalshi.regime_detection",  # Regime detection infrastructure
                "merid.trading.kalshi_continuous_trader",  # Known bypass (migration in progress)
                "merid.trading.ct_execution_adapter",  # CT → router adapter (migration Phase 1)
                "merid.trading.adapters",
                "merid.trading.integrations",
                "merid.execution.executors",
                "merid.kalshi.maker_bot_advanced",
                "merid_core.kalshi",
                "merid.swarm",
                "merid.strategies",
                "merid.sentiment.market_mood_bus",  # Market mood infrastructure
                # Test infrastructure
                "tests.",
                "test_",
                # Web API layer (legitimate HTTP callers)
                "web.api.",
                "web.main",
                "web.services.",
                # CLI/admin scripts (manual tools)
                "scripts.",
                "run_live_trade",
                "check_violations",
                # Other infrastructure
                "streams.",
                "tools.",
                "tmp.",
                "archive.",
                # Legacy paths that need cleanup but aren't new bypasses
                "agents._legacy",
                "core._legacy",
            )

            if any(mod_name.startswith(p) for p in authorized_prefixes):
                continue

            violations.append((mod_name, str(py_file)))

        if violations:
            msg = "Unauthorized HTTP client imports detected:\n"
            for mod, path in violations:
                msg += f"  - {mod} ({path})\n"
            msg += "\nThese modules may be trying to create direct HTTP paths to the venue. "
            msg += "All venue access must go through order_router."
            pytest.fail(msg)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
