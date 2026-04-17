"""test_duplicate_route_regressions.py

Regression tests for the 22 duplicate-route removals and diagnostic
script improvements made in the silent-failure diagnostic sprint.

These tests use static analysis only — no server needed.

FIX-1  missing_endpoints.py  — 20 duplicate route handlers removed
FIX-2  agents_real.py        — /api/agents/summary + /api/agents/activity removed
FIX-3  system_endpoints.py   — /api/agents/summary removed
FIX-4  diagnostic script     — false-positive reduction for useEffect + JSX prose markers
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_API = ROOT / "web" / "api"
FE_SRC = ROOT / "web" / "react" / "src"
DIAG_SCRIPT = ROOT / "scripts" / "diagnose_silent_failures.py"

# ─── Regex that matches any FastAPI route decorator ───────────────────────────
ROUTE_RE = re.compile(
    r"^@\w+\.(get|post|put|delete|patch|websocket)\(\s*\"([^\"]+)\"",
    re.MULTILINE,
)

# ─── Helper: collect all (METHOD, path, file, line) tuples ────────────────────

def _collect_routes() -> List[Tuple[str, str, str, int]]:
    """Parse all @router.<method>("/path") decorators from web/api/*.py."""
    routes: List[Tuple[str, str, str, int]] = []
    for fpath in sorted(WEB_API.glob("*.py")):
        text = fpath.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            m = ROUTE_RE.match(line)
            if m:
                method = m.group(1).upper()
                path = m.group(2)
                routes.append((method, path, fpath.name, i))
    return routes


def _find_duplicates() -> Dict[str, List[Tuple[str, int]]]:
    """Return {METHOD path: [(file, line), ...]} for full-path routes defined in >1 file.

    Only considers routes starting with /api/ — these are fully-qualified paths
    that will conflict regardless of router prefix.  Short relative paths like
    /agents or /start are disambiguated by the prefix assigned in main.py and
    are not real duplicates.
    """
    routes = _collect_routes()
    by_key: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
    for method, path, fname, lineno in routes:
        if not path.startswith("/api"):
            continue
        by_key[f"{method} {path}"].append((fname, lineno))
    return {k: v for k, v in by_key.items() if len({f for f, _ in v}) > 1}


# ===========================================================================
# 1. Global: No duplicate routes across API files
# ===========================================================================
class TestNoDuplicateRoutes:
    """Ensure no backend route is defined in more than one API file."""

    def test_zero_cross_file_duplicate_routes(self):
        dupes = _find_duplicates()
        if dupes:
            lines = []
            for key, locations in sorted(dupes.items()):
                files = " | ".join(f"{f}:{ln}" for f, ln in locations)
                lines.append(f"  {key}  →  {files}")
            msg = f"Found {len(dupes)} cross-file duplicate route(s):\n" + "\n".join(lines)
            pytest.fail(msg)

    def test_duplicate_count_is_zero(self):
        """Paranoid double-check that the count is exactly 0."""
        assert len(_find_duplicates()) == 0, "Expected 0 duplicate routes"


# ===========================================================================
# 2. FIX-1: missing_endpoints.py must not contain any of the 20 removed routes
# ===========================================================================
# These are the exact routes that were removed from missing_endpoints.py
REMOVED_FROM_MISSING = [
    "/api/v1/wallet/balances",
    "/api/v1/consensus/plans",
    "/api/v1/consensus/metrics",
    "/api/v1/consensus/opinions",
    "/api/v1/risk-metrics/agents/{agent_id}",
    "/api/v1/risk-metrics/agents/{agent_id}/drawdown-history",
    "/api/v1/risk-metrics/agents/{agent_id}/equity-history",
    "/api/v1/swarm/status",
    "/api/v1/arbitrage/scanner",
    "/api/v1/system/mode-safety",
    "/api/v1/system/session-log",
    "/api/v1/logs",
    "/api/v1/system/decisions/recent",
    "/api/operator/audit-trail",
    "/api/v1/signals/sentiment",
    "/api/v1/blockchain/health",
    "/api/v1/risk/metrics",
    "/api/v1/system/health",
    "/api/v1/agents",
    "/api/v1/agents/health",
]


class TestFix1MissingEndpointsCleanup:
    """Verify the 20 duplicate routes were removed from missing_endpoints.py."""

    @pytest.fixture(autouse=True)
    def _load_file(self):
        self.text = (WEB_API / "missing_endpoints.py").read_text(encoding="utf-8")
        self.routes_in_file: Set[str] = set()
        for m in ROUTE_RE.finditer(self.text):
            self.routes_in_file.add(m.group(2))

    @pytest.mark.parametrize("route", REMOVED_FROM_MISSING)
    def test_route_not_in_missing_endpoints(self, route: str):
        assert route not in self.routes_in_file, (
            f"Route {route!r} should have been removed from missing_endpoints.py "
            "to eliminate the duplicate-route conflict."
        )

    def test_file_still_has_unique_routes(self):
        """missing_endpoints.py should still have other endpoints (not empty)."""
        assert len(self.routes_in_file) > 0, "missing_endpoints.py is unexpectedly empty"

    def test_file_is_syntactically_valid(self):
        """missing_endpoints.py must still compile after route removal."""
        compile(self.text, "missing_endpoints.py", "exec")


# ===========================================================================
# 3. FIX-2: agents_real.py must not contain /api/agents/summary or /activity
# ===========================================================================
REMOVED_FROM_AGENTS_REAL = [
    "/api/agents/summary",
    "/api/agents/activity",
]


class TestFix2AgentsRealCleanup:
    """Verify duplicate summary + activity routes removed from agents_real.py."""

    @pytest.fixture(autouse=True)
    def _load_file(self):
        self.text = (WEB_API / "agents_real.py").read_text(encoding="utf-8")
        self.routes_in_file: Set[str] = set()
        for m in ROUTE_RE.finditer(self.text):
            self.routes_in_file.add(m.group(2))

    @pytest.mark.parametrize("route", REMOVED_FROM_AGENTS_REAL)
    def test_route_not_in_agents_real(self, route: str):
        assert route not in self.routes_in_file, (
            f"Route {route!r} should have been removed from agents_real.py "
            "(real_data_endpoints.py is registered first and has the canonical handler)."
        )

    def test_agent_detail_still_exists(self):
        """agents_real.py must still have /api/agents/{agent_id} (unique endpoint)."""
        assert "/api/agents/{agent_id}" in self.routes_in_file

    def test_agent_command_still_exists(self):
        """agents_real.py must still have /api/agents/{agent_id}/command (unique endpoint)."""
        assert "/api/agents/{agent_id}/command" in self.routes_in_file

    def test_options_preflight_removed(self):
        """The OPTIONS /api/agents/summary handler should also be gone."""
        assert "options_agents_summary" not in self.text, (
            "The OPTIONS preflight for /api/agents/summary is dead code and should be removed."
        )

    def test_file_is_syntactically_valid(self):
        compile(self.text, "agents_real.py", "exec")


# ===========================================================================
# 4. FIX-3: system_endpoints.py must not contain /api/agents/summary
# ===========================================================================
class TestFix3SystemEndpointsCleanup:
    """Verify /api/agents/summary removed from system_endpoints.py."""

    @pytest.fixture(autouse=True)
    def _load_file(self):
        self.text = (WEB_API / "system_endpoints.py").read_text(encoding="utf-8")
        self.routes_in_file: Set[str] = set()
        for m in ROUTE_RE.finditer(self.text):
            self.routes_in_file.add(m.group(2))

    def test_agents_summary_not_in_system_endpoints(self):
        assert "/api/agents/summary" not in self.routes_in_file, (
            "Route /api/agents/summary should have been removed from system_endpoints.py "
            "(real_data_endpoints.py has the canonical handler)."
        )

    def test_system_health_still_exists(self):
        """system_endpoints.py must still have /api/v1/system/health (canonical)."""
        assert "/api/v1/system/health" in self.routes_in_file

    def test_file_is_syntactically_valid(self):
        compile(self.text, "system_endpoints.py", "exec")


# ===========================================================================
# 5. Canonical routes still exist in their expected files
# ===========================================================================
CANONICAL_ROUTES = {
    "real_data_endpoints.py": [
        "/api/agents/activity",
        "/api/agents/summary",
        "/api/v1/consensus/plans",
        "/api/v1/consensus/opinions",
        "/api/v1/consensus/metrics",
        "/api/v1/agents",
        "/api/v1/agents/health",
        "/api/v1/wallet/balances",
        "/api/v1/risk/metrics",
        "/api/v1/swarm/status",
        "/api/v1/logs",
    ],
    "system_endpoints.py": [
        "/api/v1/system/health",
        "/api/v1/system/mode-safety",
        "/api/v1/system/session-log",
    ],
}


class TestCanonicalRoutesExist:
    """Verify canonical route handlers still exist in the correct files."""

    @pytest.mark.parametrize(
        "filename,route",
        [(f, r) for f, routes in CANONICAL_ROUTES.items() for r in routes],
        ids=[f"{f}:{r}" for f, routes in CANONICAL_ROUTES.items() for r in routes],
    )
    def test_canonical_route_present(self, filename: str, route: str):
        text = (WEB_API / filename).read_text(encoding="utf-8")
        routes_in_file = {m.group(2) for m in ROUTE_RE.finditer(text)}
        assert route in routes_in_file, (
            f"Canonical route {route!r} missing from {filename} — "
            "it may have been accidentally deleted."
        )


# ===========================================================================
# 6. FIX-4: Diagnostic script false-positive reduction
# ===========================================================================
class TestDiagnosticScriptAccuracy:
    """Verify the diagnostic script's FP-reduction logic is present."""

    @pytest.fixture(autouse=True)
    def _load_script(self):
        self.text = DIAG_SCRIPT.read_text(encoding="utf-8")

    def test_script_exists_and_compiles(self):
        """diagnose_silent_failures.py must exist and be syntactically valid."""
        assert DIAG_SCRIPT.exists()
        compile(self.text, str(DIAG_SCRIPT), "exec")

    def test_jsx_prose_filter_present(self):
        """Diagnostic must filter out BUG/TODO markers in JSX prose."""
        assert "is_jsx_prose" in self.text, (
            "JSX prose filter for BUG/TODO markers is missing from diagnostic script"
        )

    def test_clock_tick_useeffect_filter_present(self):
        """Diagnostic must skip setInterval(() => setXxx(Date.now())) as safe."""
        assert "is_clock_tick" in self.text, (
            "Clock-tick useEffect safe-pattern filter is missing from diagnostic script"
        )

    def test_fetch_interval_useeffect_filter_present(self):
        """Diagnostic must skip setInterval(fetchFn, N) as safe."""
        assert "is_fetch_interval" in self.text, (
            "Fetch-interval useEffect safe-pattern filter is missing from diagnostic script"
        )

    def test_static_syntax_check_not_importlib(self):
        """Python import health must use compile(), not importlib.import_module()."""
        # The script should NOT contain importlib.import_module for the health check
        assert "importlib.import_module" not in self.text, (
            "Diagnostic still uses importlib.import_module — should use compile() "
            "for static syntax checking to avoid side effects."
        )


# ===========================================================================
# 7. Structural: web/api/*.py files are all syntactically valid Python
# ===========================================================================
class TestAllApiFilesSyntaxValid:
    """Every Python file in web/api/ must compile without SyntaxError."""

    @pytest.mark.parametrize(
        "filename",
        [f.name for f in sorted(WEB_API.glob("*.py"))],
    )
    def test_api_file_compiles(self, filename: str):
        fpath = WEB_API / filename
        text = fpath.read_text(encoding="utf-8")
        try:
            compile(text, filename, "exec")
        except SyntaxError as e:
            pytest.fail(f"{filename} has syntax error: {e}")
