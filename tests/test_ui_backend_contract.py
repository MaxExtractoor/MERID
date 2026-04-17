"""CI contract test: every frontend API_ENDPOINTS constant must resolve to a
registered FastAPI route.

How it works
------------
1. Loads ``web/api/generated/endpoints.json`` (produced by
   ``scripts/generate_endpoints_contract.py``).
2. Boots the FastAPI app via ``create_app()`` and collects all registered
   ``{method, path}`` pairs from ``app.routes``.
3. Asserts that every frontend entry has a matching backend route.

Run:
    pytest tests/test_ui_backend_contract.py -v

Regenerate the contract after changing constants.ts:
    python scripts/generate_endpoints_contract.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Set, Tuple

import pytest

REPO = Path(__file__).resolve().parent.parent
CONTRACT_FILE = REPO / "web" / "api" / "generated" / "endpoints.json"

# ── Whitelist: frontend entries that are known NOT to match a FastAPI route ──
# Each tuple is (METHOD, path_pattern).  Use these sparingly — every entry
# here is technical debt.  Add a comment explaining *why* it's whitelisted.
WHITELIST: Set[Tuple[str, str]] = {
    # Non-/api prefixed debate routes served by a different service / proxy
    ("GET", "/debates/alerts"),
    ("GET", "/debates/correlation"),
    ("GET", "/debates/historical-contribution"),
    ("GET", "/debates/rollups"),
    ("GET", "/debates/health/overview"),
    # X-bot routes on /api/x/* (non-v1 prefix, separate auth)
    ("GET", "/api/x/status"),
    ("POST", "/api/x/post"),

    # ── Router import failures in test env ────────────────────────────
    # notification_api.py fails to import (missing notification_worker dep)
    ("GET", "/api/v1/notifications/status"),
    ("GET", "/api/v1/notifications/recent-alerts"),
    ("POST", "/api/v1/notifications/telegram/send"),
    ("GET", "/api/v1/notifications/telegram/status"),

    # risk_routes.py legacy stubs (superseded by risk_metrics_api.py implementations)
    # Agent endpoints now implemented in risk_metrics_api.py:
    # - GET /api/v1/risk/agents/{agentId}/drawdown-history ✓
    # - GET /api/v1/risk/agents/{agentId}/equity-history ✓
    # - GET /api/v1/risk/agents/{agentId}/metrics ✓
    # - POST /api/v1/risk/alerts/acknowledge-all ✓ (implemented in risk_metrics_api.py)
    ("POST", "/api/v1/risk/alerts/{alertId}/acknowledge"),  # Not yet implemented
    ("POST", "/api/v1/risk/downsize-all"),  # Not yet implemented
    ("DELETE", "/api/v1/risk/kill-switch"),  # Not yet implemented - use POST /api/v1/risk/resume instead

    # dev_swarm_routes.py — gated behind _kalshi_only in full profile
    # but may fail to import in minimal test environments
    ("POST", "/api/dev-swarm/pause"),
    ("POST", "/api/dev-swarm/resume"),
    ("POST", "/api/dev-swarm/shutdown"),

    # ── Gated behind `not _kalshi_only` (missing_endpoints / real_data routers)
    # These routers serve stub/fallback data and are suppressed in kalshi-only profile.
    ("GET", "/api/v1/data/freshness"),
    ("GET", "/api/v1/logs"),
    ("POST", "/api/v1/logs/clear"),
    ("GET", "/api/v1/logs/stats"),
    ("GET", "/api/v1/notifications"),
    ("POST", "/api/v1/notifications/read-all"),
    ("GET", "/api/v1/notifications/telegram/log"),
    ("POST", "/api/v1/notifications/{id}/read"),
    ("GET", "/api/v1/pipeline/venues"),
    ("GET", "/api/v1/risk/alerts"),
    ("GET", "/api/v1/risk/position-limits"),
    ("GET", "/api/v1/user/profile"),
    ("PUT", "/api/v1/user/settings"),

    # ── Method mismatch ────────────────────────────────────────────────
    # CALIBRATION_RESOLVE: frontend declares as GET but backend is POST (action endpoint)
    ("GET", "/api/v1/kalshi/calibration/resolve"),

    # ── Dead / stub constants (no backend implementation) ─────────────
    # auth/refresh — JWT refresh not implemented yet
    ("POST", "/api/v1/auth/refresh"),
    # paper-trading portfolio — legacy constant, paper-trading gated
    ("GET", "/api/v1/paper-trading/{portfolioId}"),
    # pipeline venue routes — legacy crypto pipeline, not Kalshi
    ("GET", "/api/v1/pipeline/venue/mode"),
    ("POST", "/api/v1/pipeline/venue/{action}"),
    ("GET", "/api/v1/pipeline/venues/{venue}/pnl"),
}


def _normalize_fastapi_path(path: str) -> str:
    """Normalize a FastAPI route path for comparison.

    FastAPI uses ``{param}`` for path parameters, which matches the format
    our contract generator already produces.  We just strip trailing slashes.
    """
    return path.rstrip("/")


def _normalize_contract_path(path: str) -> str:
    """Normalize a contract path for comparison."""
    return path.rstrip("/")


def _parameterized_to_regex(path: str) -> re.Pattern:
    """Convert ``/api/v1/kalshi/markets/{ticker}`` into a regex that matches
    any concrete FastAPI route with the same structure.

    This handles the case where the contract has ``{ticker}`` but the
    FastAPI route might use a differently-named parameter like ``{market_id}``.
    """
    # Escape everything except {param} segments
    parts = re.split(r"\{[^}]+\}", path)
    escaped = [re.escape(p) for p in parts]
    return re.compile("^" + r"[^/]+" .join(escaped) + "$")


def _load_contract() -> list[dict]:
    """Load the frontend contract file."""
    if not CONTRACT_FILE.exists():
        pytest.skip(
            f"Contract file not found: {CONTRACT_FILE}\n"
            "Run: python scripts/generate_endpoints_contract.py"
        )
    return json.loads(CONTRACT_FILE.read_text(encoding="utf-8"))


def _build_backend_routes(app) -> Set[Tuple[str, str]]:
    """Extract all (METHOD, path) pairs from the FastAPI app."""
    routes: Set[Tuple[str, str]] = set()
    for route in app.routes:
        # APIRoute has .methods and .path
        if hasattr(route, "methods") and hasattr(route, "path"):
            path = _normalize_fastapi_path(route.path)
            for method in route.methods:
                routes.add((method.upper(), path))
        # Sub-applications (mounted routers) — recurse
        if hasattr(route, "app") and hasattr(route.app, "routes"):
            for sub in route.app.routes:
                if hasattr(sub, "methods") and hasattr(sub, "path"):
                    prefix = _normalize_fastapi_path(route.path)
                    sub_path = _normalize_fastapi_path(sub.path)
                    full = prefix + sub_path if not sub_path.startswith(prefix) else sub_path
                    for method in sub.methods:
                        routes.add((method.upper(), full))
    return routes


def _path_matches(contract_path: str, backend_routes_paths: Set[str]) -> bool:
    """Check if a contract path matches any backend route path.

    Handles parameterized paths: ``/api/v1/kalshi/markets/{ticker}`` should
    match ``/api/v1/kalshi/markets/{ticker}`` even if parameter names differ.
    """
    norm = _normalize_contract_path(contract_path)
    if norm in backend_routes_paths:
        return True

    # If the contract path has parameters, try regex matching
    if "{" in norm:
        pattern = _parameterized_to_regex(norm)
        return any(pattern.match(bp) for bp in backend_routes_paths)

    return False


# ═══════════════════════════════════════════════════════════════════════
# Test
# ═══════════════════════════════════════════════════════════════════════


class TestUIBackendContract:
    """Frontend API_ENDPOINTS must all resolve to registered FastAPI routes."""

    @pytest.fixture(scope="class")
    def app(self):
        """Create the FastAPI app (no lifespan — just route registration)."""
        import asyncio

        async def _noop_lifespan(app):
            yield

        from web.main import create_app
        return create_app(lifespan=_noop_lifespan)

    @pytest.fixture(scope="class")
    def backend_routes(self, app) -> Set[Tuple[str, str]]:
        return _build_backend_routes(app)

    @pytest.fixture(scope="class")
    def backend_paths_by_method(self, backend_routes) -> dict[str, Set[str]]:
        """Group backend paths by HTTP method for efficient lookup."""
        result: dict[str, Set[str]] = {}
        for method, path in backend_routes:
            result.setdefault(method, set()).add(path)
        return result

    @pytest.fixture(scope="class")
    def backend_all_paths(self, backend_routes) -> Set[str]:
        """All backend paths regardless of method — for method-mismatch detection."""
        return {path for _, path in backend_routes}

    @pytest.fixture(scope="class")
    def contract(self) -> list[dict]:
        return _load_contract()

    def test_contract_file_exists(self):
        """endpoints.json must be present (regenerate if stale)."""
        assert CONTRACT_FILE.exists(), (
            f"Missing {CONTRACT_FILE}. Run: python scripts/generate_endpoints_contract.py"
        )

    def test_contract_not_empty(self, contract):
        """Contract must have a meaningful number of entries."""
        assert len(contract) > 100, f"Contract suspiciously small: {len(contract)} entries"

    def test_all_frontend_endpoints_have_backend_routes(
        self, contract, backend_paths_by_method, backend_all_paths
    ):
        """Every frontend endpoint must map to a registered FastAPI route.

        On failure, prints the exact missing {method, path, key} triples so
        you can jump straight to implementing or removing them.
        """
        missing: list[dict] = []
        for entry in contract:
            method = entry["method"].upper()
            path = _normalize_contract_path(entry["path"])

            # Skip whitelisted entries
            if (method, path) in WHITELIST:
                continue

            # Check if this method+path exists in backend
            method_paths = backend_paths_by_method.get(method, set())
            if not _path_matches(path, method_paths):
                # Also check if ANY method serves this path (method mismatch)
                if _path_matches(path, backend_all_paths):
                    missing.append({
                        **entry,
                        "issue": "METHOD_MISMATCH",
                        "note": f"Path exists but not with {method}",
                    })
                else:
                    missing.append({**entry, "issue": "MISSING_ROUTE"})

        if missing:
            # Pretty-print for easy debugging
            lines = [
                f"\n{'='*72}",
                f"  UI-BACKEND CONTRACT FAILURES: {len(missing)} endpoint(s) missing",
                f"{'='*72}",
            ]
            for m in sorted(missing, key=lambda x: x["path"]):
                issue = m.get("issue", "MISSING_ROUTE")
                note = m.get("note", "")
                lines.append(f"  {issue:16s}  {m['method']:6s}  {m['path']}")
                lines.append(f"  {'':16s}  key: {m['key']}")
                if note:
                    lines.append(f"  {'':16s}  note: {note}")
            lines.append(f"{'='*72}")
            lines.append("")
            lines.append("Fix options:")
            lines.append("  1. Implement the missing backend route")
            lines.append("  2. Remove the dead frontend constant from API_ENDPOINTS")
            lines.append("  3. Add to WHITELIST in this test (last resort)")
            lines.append("")

            pytest.fail("\n".join(lines))

    def test_backend_route_count_sanity(self, backend_routes):
        """Backend should have a reasonable number of routes."""
        assert len(backend_routes) > 50, (
            f"Only {len(backend_routes)} backend routes found — app may not have loaded correctly"
        )

    def test_no_orphaned_api_v1_routes(self, contract, backend_routes):
        """Optional: flag backend /api/v1/* routes not referenced by the frontend.

        This is informational — it helps find dead backend routes.  It does NOT
        fail the test; it only prints a warning.
        """
        frontend_paths: Set[str] = {
            _normalize_contract_path(entry["path"]) for entry in contract
        }
        frontend_generic: Set[str] = {
            re.sub(r"\{[^}]+\}", "{_}", p) for p in frontend_paths
        }

        orphaned = []
        for method, path in sorted(backend_routes):
            if not path.startswith("/api/v1/"):
                continue
            generic = re.sub(r"\{[^}]+\}", "{_}", path)
            if generic not in frontend_generic:
                orphaned.append(f"  {method:6s}  {path}")

        if orphaned:
            import warnings
            warnings.warn(
                f"\n{len(orphaned)} backend /api/v1/* routes not referenced by frontend:\n"
                + "\n".join(orphaned[:30])
                + ("\n  ... and more" if len(orphaned) > 30 else ""),
                stacklevel=2,
            )

    def test_whitelist_cap(self):
        """Soft guardrail: WHITELIST should trend downward, not grow unbounded.

        If this fails, shrink the whitelist by fixing import failures or
        removing dead frontend constants instead of raising the cap.
        """
        max_allowed = 45
        assert len(WHITELIST) <= max_allowed, (
            f"WHITELIST has {len(WHITELIST)} entries (cap: {max_allowed}). "
            f"Fix the underlying issues instead of adding more exemptions."
        )
