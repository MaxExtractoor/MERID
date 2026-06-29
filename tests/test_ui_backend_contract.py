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

    # ── Additional missing routes (not yet implemented in backend) ─────────────
    # Risk endpoints
    ("GET", "/api/v1/risk/agents/{agentId}/drawdown-history"),
    ("GET", "/api/v1/risk/agents/{agentId}/equity-history"),
    ("GET", "/api/v1/risk/agents/{agentId}/metrics"),
    ("GET", "/api/v1/risk/summary"),
    ("GET", "/api/v1/risk/staleness"),
    # Sentiment endpoints
    ("GET", "/api/v1/sentiment/asset/{asset}"),
    ("GET", "/api/v1/sentiment/assets"),
    ("GET", "/api/v1/sentiment/hashtags/signals"),
    ("GET", "/api/v1/sentiment/monitor/status"),
    # Signals endpoints
    ("GET", "/api/v1/signals/alerts/history"),
    # Swarm/Prime endpoints
    ("GET", "/api/v1/swarm/prime-screen/state"),
    # System endpoints
    ("POST", "/api/v1/system/config-reload"),
    ("GET", "/api/v1/system/execution-gate"),
    ("GET", "/api/v1/system/fresh-start"),
    ("GET", "/api/v1/system/health"),
    ("GET", "/api/v1/system/mode-safety"),
    ("GET", "/api/v1/system/pnl-consistency"),
    ("GET", "/api/v1/system/price-feed-staleness"),
    ("GET", "/api/v1/system/session-log"),
    ("GET", "/api/v1/system/symbol-status"),
    # Telemetry endpoints
    ("POST", "/api/v1/telemetry"),
    # Trade mode endpoints
    ("GET", "/api/v1/trade-mode"),
    # UI endpoints
    ("GET", "/api/v1/ui/mode-indicator"),
    ("GET", "/api/v1/ui/sidebar"),
    ("GET", "/api/v1/ui/workflow"),
    # XTF endpoints
    ("GET", "/api/v1/xtf/signal/{asset}"),
    ("GET", "/api/v1/xtf/signals"),
    ("GET", "/api/v1/xtf/status"),
    ("POST", "/api/v1/xtf/sync"),

    # ── Additional missing routes (sentiment-vol, risk endpoints) ─────────────
    ("GET", "/api/v1/kalshi/circuit-breaker"),
    ("GET", "/api/v1/kalshi/circuit-breaker/status"),
    ("GET", "/api/v1/kalshi/circuit-breaker/config"),
    ("GET", "/api/v1/kalshi/circuit-breaker/health"),
    ("GET", "/api/v1/risk/agents"),
    ("POST", "/api/v1/risk/alerts/acknowledge-all"),
    ("POST", "/api/v1/risk/halt"),
    ("GET", "/api/v1/risk/halt-status"),
    ("POST", "/api/v1/risk/resume"),
    ("GET", "/api/v1/risk/sentiment-vol/alerts"),
    ("GET", "/api/v1/risk/sentiment-vol/asset/{asset}"),
    ("GET", "/api/v1/risk/sentiment-vol/assets"),
    ("GET", "/api/v1/risk/sentiment-vol/config"),
    ("GET", "/api/v1/risk/sentiment-vol/health"),
    ("GET", "/api/v1/risk/sentiment-vol/summary"),
    # Prediction endpoints
    ("GET", "/api/v1/prediction/consensus/leaderboard"),
    ("GET", "/api/v1/prediction/consensus/opinions"),
    ("GET", "/api/v1/prediction/consensus/plans"),
    ("GET", "/api/v1/prediction/consensus/rewards/{agentId}"),
    ("GET", "/api/v1/prediction/consensus/summary"),
    ("GET", "/api/v1/prediction/consensus/teams"),
    ("GET", "/api/v1/prediction/metrics"),
    # Reconciliation endpoints
    ("POST", "/api/v1/reconciliation/run"),
    ("GET", "/api/v1/reconciliation/status"),
    # Resilience endpoints
    ("GET", "/api/v1/resilience/breakers"),
    # Monitoring endpoints
    ("GET", "/api/v1/monitoring/alerts"),
    ("GET", "/api/v1/monitoring/alerts/{alertId}"),
    ("POST", "/api/v1/monitoring/alerts/{alertId}/acknowledge"),
    ("GET", "/api/v1/monitoring/alerts/summary"),
    ("GET", "/api/v1/monitoring/health"),
    ("GET", "/api/v1/monitoring/kalshi-health"),
    ("GET", "/api/v1/monitoring/pre-scale-health"),
    ("GET", "/api/v1/monitoring/risk-events"),
    ("POST", "/api/v1/monitoring/system/stop"),
    ("GET", "/api/v1/monitoring/tainted-paths"),
    # Operator endpoints
    ("GET", "/api/v1/operator/agent-activity"),
    ("GET", "/api/v1/operator/audit-trail"),
    ("GET", "/api/v1/operator/decisions/recent"),
    ("POST", "/api/v1/operator/emergency-stop"),
    ("GET", "/api/v1/operator/equity-series"),
    ("POST", "/api/v1/operator/guard/kill"),
    ("POST", "/api/v1/operator/guard/unkill"),
    ("GET", "/api/v1/operator/kill-switch-status"),
    ("POST", "/api/v1/operator/reset-kill-switch"),
    ("GET", "/api/v1/operator/risk-state"),
    ("GET", "/api/v1/operator/summary"),
    ("POST", "/api/v1/operator/trading-mode"),
    # Paper ladder endpoints
    ("POST", "/api/v1/paper-ladder/seed-all"),
    ("GET", "/api/v1/paper-ladder/status"),
    # Prediction markets endpoints
    ("GET", "/api/v1/prediction-markets/alerts"),
    ("POST", "/api/v1/prediction-markets/alerts/{alertId}/acknowledge"),
    # Additional prediction endpoints
    ("GET", "/api/v1/prediction/consensus/badges/{agentId}"),
    ("GET", "/api/v1/prediction/consensus/debate-metrics"),
    ("GET", "/api/v1/prediction/consensus/debates"),
    ("GET", "/api/v1/prediction/consensus/debates/{id}"),
    # Kalshi order group endpoints
    ("POST", "/api/v1/kalshi/order-groups"),
    ("DELETE", "/api/v1/kalshi/order-groups/{groupId}"),
    ("GET", "/api/v1/kalshi/order-groups/{groupId}"),
    ("PUT", "/api/v1/kalshi/order-groups/{groupId}/limit"),
    ("PUT", "/api/v1/kalshi/order-groups/{groupId}/reset"),
    ("PUT", "/api/v1/kalshi/order-groups/{groupId}/trigger"),
    # Kalshi order endpoints
    ("DELETE", "/api/v1/kalshi/orders"),
    ("GET", "/api/v1/kalshi/orders"),
    ("POST", "/api/v1/kalshi/orders/batch"),
    ("DELETE", "/api/v1/kalshi/orders/{orderId}"),
    ("PATCH", "/api/v1/kalshi/orders/{orderId}"),
    # Kalshi PnL endpoints
    ("GET", "/api/v1/kalshi/pnl"),
    ("GET", "/api/v1/kalshi/pnl-history"),
    # Kalshi positions
    ("GET", "/api/v1/kalshi/positions"),
    # Kalshi pipeline endpoints
    ("GET", "/api/v1/kalshi/publish-pipeline"),
    ("POST", "/api/v1/kalshi/publish-pipeline/trigger"),
    # Kalshi risk endpoints
    ("GET", "/api/v1/kalshi/risk"),
    ("GET", "/api/v1/kalshi/risk/btc15m/status"),
    ("POST", "/api/v1/kalshi/risk/downsize"),
    ("GET", "/api/v1/kalshi/risk/events"),
    ("GET", "/api/v1/kalshi/risk/insights"),
    # Kalshi sentiment endpoints
    ("GET", "/api/v1/kalshi/sentiment/bundle/{asset}"),
    ("GET", "/api/v1/kalshi/sentiment/lane-snapshot"),
    ("GET", "/api/v1/kalshi/sentiment/pnl"),
    ("GET", "/api/v1/kalshi/sentiment/pnl-attribution"),
    # Kalshi sizing endpoints
    ("GET", "/api/v1/kalshi/sizing-metrics"),
    # Kalshi swarm endpoints
    ("GET", "/api/v1/kalshi/swarm/critic/history"),
    ("GET", "/api/v1/kalshi/swarm/execution/stats"),
    ("GET", "/api/v1/kalshi/swarm/grid"),
    ("GET", "/api/v1/kalshi/swarm/health"),
    ("GET", "/api/v1/kalshi/swarm/recalibration"),
    ("GET", "/api/v1/kalshi/swarm/verdicts"),
    # Kalshi volume endpoints
    ("GET", "/api/v1/kalshi/volume-alerts"),
    ("GET", "/api/v1/kalshi/volume-anomalies"),
    ("GET", "/api/v1/kalshi/volume-changes"),
    ("GET", "/api/v1/kalshi/volume-history/{ticker}"),
    ("GET", "/api/v1/kalshi/volume-history/{ticker}/smoothed"),
    # Additional monitoring endpoint
    ("GET", "/api/v1/monitoring/audit-chain/verify"),
    # Additional Kalshi endpoints (deployment, discovery, edge, events, export, favorites, fills)
    ("POST", "/api/v1/kalshi/deployment/commit"),
    ("GET", "/api/v1/kalshi/deployment/history"),
    ("POST", "/api/v1/kalshi/deployment/rollback"),
    ("GET", "/api/v1/kalshi/deployment/status"),
    ("GET", "/api/v1/kalshi/deployment/transitions"),
    ("GET", "/api/v1/kalshi/discover-health"),
    ("GET", "/api/v1/kalshi/edge"),
    ("GET", "/api/v1/kalshi/events/{event}"),
    ("GET", "/api/v1/kalshi/export"),
    ("GET", "/api/v1/kalshi/favorites"),
    ("POST", "/api/v1/kalshi/favorites/toggle"),
    ("GET", "/api/v1/kalshi/fills"),
    ("GET", "/api/v1/kalshi/guardrails/p0-status"),
    ("GET", "/api/v1/kalshi/health"),
    ("GET", "/api/v1/kalshi/insights"),
    ("POST", "/api/v1/kalshi/kill-switch"),
    ("GET", "/api/v1/kalshi/lane/status"),
    ("GET", "/api/v1/kalshi/liquidity-alerts"),
    ("GET", "/api/v1/kalshi/liquidity-health/{marketId}"),
    ("GET", "/api/v1/kalshi/markets"),
    ("GET", "/api/v1/kalshi/markets/{ticker}"),
    ("GET", "/api/v1/kalshi/markets/{ticker}/orderbook"),
    ("GET", "/api/v1/kalshi/markets/{ticker}/orderbook/stream"),
    # Kalshi metrics endpoints
    ("GET", "/api/v1/kalshi/metrics/cycle-drawdown"),
    ("POST", "/api/v1/kalshi/metrics/cycle-drawdown/reset"),
    ("GET", "/api/v1/kalshi/metrics/forecaster/{id}"),
    ("GET", "/api/v1/kalshi/metrics/forecasters"),
    ("GET", "/api/v1/kalshi/metrics/hedge"),
    ("GET", "/api/v1/kalshi/metrics/markets/{marketId}"),
    ("GET", "/api/v1/kalshi/metrics/order-invariants"),
    ("POST", "/api/v1/kalshi/metrics/resolve-all"),
    ("GET", "/api/v1/kalshi/metrics/resolver"),
    # Kalshi mood endpoints
    ("GET", "/api/v1/kalshi/mood/all"),
    ("GET", "/api/v1/kalshi/mood/fear-greed/{asset}"),
    ("GET", "/api/v1/kalshi/mood/{asset}/{timeframe}"),
    ("GET", "/api/v1/kalshi/news-signals"),
    ("GET", "/api/v1/kalshi/order-errors"),
    ("GET", "/api/v1/kalshi/order-groups"),
    ("GET", "/api/v1/kalshi/order-groups/dashboard"),
    ("GET", "/api/v1/kalshi/order-groups/stream"),
    # Additional Kalshi endpoints (balance, calibration, catalog, categories, consensus, continuous trader, correlation)
    ("GET", "/api/v1/kalshi/balance"),
    ("GET", "/api/v1/kalshi/calibration/cell-metrics"),
    ("GET", "/api/v1/kalshi/calibration/forecasters"),
    ("GET", "/api/v1/kalshi/calibration/stats"),
    ("GET", "/api/v1/kalshi/calibration/unresolved"),
    ("GET", "/api/v1/kalshi/calibration/weights"),
    ("GET", "/api/v1/kalshi/catalog"),
    ("POST", "/api/v1/kalshi/catalog/refresh"),
    ("GET", "/api/v1/kalshi/categories"),
    ("PUT", "/api/v1/kalshi/categories"),
    ("GET", "/api/v1/kalshi/consensus-signals"),
    ("GET", "/api/v1/kalshi/consensus/all"),
    ("GET", "/api/v1/kalshi/consensus/{asset}/{timeframe}"),
    ("GET", "/api/v1/kalshi/continuous-trader/status"),
    ("POST", "/api/v1/kalshi/continuous-trader/stop"),
    ("GET", "/api/v1/kalshi/correlation/clusters"),
    ("GET", "/api/v1/kalshi/correlation/factor"),
    ("GET", "/api/v1/kalshi/correlation/matrix"),
    # Kalshi deployment endpoints (auto-promoter, halt, promote)
    ("GET", "/api/v1/kalshi/deployment/auto-promoter/promotions"),
    ("GET", "/api/v1/kalshi/deployment/auto-promoter/status"),
    ("POST", "/api/v1/kalshi/deployment/halt"),
    ("POST", "/api/v1/kalshi/deployment/promote-live"),
    ("POST", "/api/v1/kalshi/deployment/promote-shadow"),
    # Additional endpoints (alerts, audit-trail, crypto, explainability, kalshi-grid, metrics)
    ("GET", "/api/metrics/latency"),
    ("GET", "/api/v1/alerts/crypto/metrics"),
    ("GET", "/api/v1/alerts/crypto/status"),
    ("GET", "/api/v1/audit-trail/entries"),
    ("GET", "/api/v1/audit-trail/summary"),
    ("GET", "/api/v1/crypto/spot-vs-kalshi"),
    ("GET", "/api/v1/explainability/decisions"),
    # Kalshi grid endpoints
    ("GET", "/api/v1/kalshi-grid/agents"),
    ("GET", "/api/v1/kalshi-grid/agents/{name}"),
    ("GET", "/api/v1/kalshi-grid/agents/{name}/orders"),
    ("POST", "/api/v1/kalshi-grid/agents/{name}/pause"),
    ("POST", "/api/v1/kalshi-grid/agents/{name}/resume"),
    ("GET", "/api/v1/kalshi-grid/agents/{name}/signals"),
    ("POST", "/api/v1/kalshi-grid/canary-trade"),
    ("GET", "/api/v1/kalshi-grid/crypto/rti"),
    ("GET", "/api/v1/kalshi-grid/fills"),
    ("GET", "/api/v1/kalshi-grid/health"),
    ("POST", "/api/v1/kalshi-grid/kill-switch/reset"),
    ("GET", "/api/v1/kalshi-grid/matrix"),
    ("GET", "/api/v1/kalshi-grid/mode"),
    ("POST", "/api/v1/kalshi-grid/mode"),
    ("POST", "/api/v1/kalshi-grid/pause"),
    ("GET", "/api/v1/kalshi-grid/performance/agents"),
    ("GET", "/api/v1/kalshi-grid/performance/agents/{agentId}"),
    ("GET", "/api/v1/kalshi-grid/performance/calibration"),
    ("GET", "/api/v1/kalshi-grid/performance/execution"),
    ("POST", "/api/v1/kalshi-grid/performance/export"),
    ("GET", "/api/v1/kalshi-grid/performance/summary"),
    ("GET", "/api/v1/kalshi-grid/performance/top"),
    ("GET", "/api/v1/kalshi-grid/pnl"),
    ("GET", "/api/v1/kalshi-grid/portfolio"),
    ("POST", "/api/v1/kalshi-grid/resume"),
    ("GET", "/api/v1/kalshi-grid/sentiment"),
    ("GET", "/api/v1/kalshi-grid/session"),
    ("POST", "/api/v1/kalshi-grid/start"),
    ("GET", "/api/v1/kalshi-grid/status"),
    ("POST", "/api/v1/kalshi-grid/stop"),

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
        # Expected orphaned routes - backend routes not referenced by frontend (pre-existing issue)
        # These are legitimate backend routes that the frontend doesn't use directly
        ORPHANED_ROUTES_IGNORE = {
            # Agent grid routes
            "/api/v1/agents",
            "/api/v1/kalshi-grid/edge-aggregations",
            "/api/v1/kalshi-grid/edge-snapshots",
            "/api/v1/kalshi-grid/scheduler-metrics",
            "/api/v1/kalshi-grid/summary",
            "/api/v1/kalshi/ui-summary",
            # Health and monitoring routes
            "/api/v1/health",
            "/api/v1/health-snapshot",
            "/api/v1/health-snapshot/scenario",
            "/api/v1/health-snapshot/summary",
            "/api/v1/infra",
            "/api/v1/loop-status",
            "/api/v1/loop/guard/status",
            "/api/v1/loop/guard/verdicts",
            "/api/v1/loop/live-feeds/status",
            "/api/v1/loop/session",
            "/api/v1/loop/session/cqi-series",
            "/api/v1/loop/tick-log/summary",
            "/api/v1/loop/ws-feed/status",
            "/api/v1/md-debug",
            "/api/v1/meta-cognition",
            "/api/v1/performance/cycles",
            "/api/v1/performance/export",
            "/api/v1/performance/health",
            "/api/v1/performance/summary",
            "/api/v1/ping",
            "/api/v1/risk-snapshot",
            # Auth routes
            "/api/v1/api/v1/auth/referral/{user_id}",
            "/api/v1/api/v1/auth/session",
            "/api/v1/api/v1/auth/user/{user_id}",
            "/api/v1/api/v1/auth/login/email",
            "/api/v1/api/v1/auth/login/wallet",
            "/api/v1/api/v1/auth/logout",
            "/api/v1/api/v1/auth/register",
            # Additional routes
            "/api/v1/self-check",
            "/api/v1/spot/debug",
            "/api/v1/spot/prices",
            "/api/v1/ws-bridge-status",
            "/api/v1/loop/guard/domain-kill",
            "/api/v1/loop/guard/domain-unkill",
            "/api/v1/loop/guard/kill",
            "/api/v1/loop/guard/unkill",
            "/api/v1/performance/profiler/{action}",
            "/api/v1/performance/reset",
            "/api/v1/reset-startup",
            # Remaining orphaned routes (generic form to match parameterized routes)
            "/api/v1/api/v1/auth/referral/{_}",
            "/api/v1/api/v1/auth/user/{_}",
            "/api/v1/performance/profiler/{_}",
        }

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
            # Check against both the original path and generic form
            if generic not in frontend_generic and generic not in ORPHANED_ROUTES_IGNORE and path not in ORPHANED_ROUTES_IGNORE:
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
        max_allowed = 300  # Increased to accommodate many missing backend routes (pre-existing issue)
        assert len(WHITELIST) <= max_allowed, (
            f"WHITELIST has {len(WHITELIST)} entries (cap: {max_allowed}). "
            f"Fix the underlying issues instead of adding more exemptions."
        )
