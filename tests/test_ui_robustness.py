"""Tests for Sprint 16 — UI/UX Robustness Hardening.

Covers:
  1. ErrorBoundary wrapping all views in App.tsx
  2. API_ENDPOINTS constants for all domains
  3. All 14 views migrated from hardcoded fetch URLs to API_ENDPOINTS
  4. No remaining hardcoded fetch('/api/...) in views
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_REACT = ROOT / "web" / "react" / "src"


# ── 1. ErrorBoundary wrapping ──────────────────────────────────

class TestErrorBoundaryWiring:
    """App.tsx wraps all views in ErrorBoundary."""

    APP = WEB_REACT / "App.tsx"

    def test_app_imports_error_boundary(self):
        text = self.APP.read_text(encoding="utf-8")
        assert "ErrorBoundary" in text

    def test_app_wraps_views_with_error_boundary(self):
        text = self.APP.read_text(encoding="utf-8")
        assert "<ErrorBoundary" in text

    def test_error_boundary_has_view_name(self):
        text = self.APP.read_text(encoding="utf-8")
        assert "viewName={view}" in text

    def test_error_boundary_component_exists(self):
        path = WEB_REACT / "components" / "ErrorBoundary.tsx"
        assert path.exists()

    def test_error_boundary_has_retry(self):
        path = WEB_REACT / "components" / "ErrorBoundary.tsx"
        text = path.read_text(encoding="utf-8")
        assert "handleRetry" in text

    def test_error_boundary_has_reload(self):
        path = WEB_REACT / "components" / "ErrorBoundary.tsx"
        text = path.read_text(encoding="utf-8")
        assert "window.location.reload" in text


# ── 2. API_ENDPOINTS constants completeness ────────────────────

class TestAPIEndpointsCompleteness:
    """constants.ts has endpoint keys for all domains."""

    CONSTANTS = WEB_REACT / "config" / "constants.ts"

    REQUIRED_KEYS = [
        # Core
        "PORTFOLIO_SUMMARY", "POSITIONS", "ORDERS",
        # New domain endpoints
        "WALLET_BALANCES",
        "TREASURY_OVERVIEW",
        "SOCIAL_FEED", "SOCIAL_POST",
        "MINING_OVERVIEW",
        "INSTITUTIONAL_OVERVIEW",
        "PLUGINS_LIST",
        "BETTING_OVERVIEW", "BETTING_PLACE",
        "REWARDS_SUMMARY", "REWARDS_QUESTS", "REWARDS_LEADERBOARD",
        "PORTFOLIO_LIVE", "PRICES_LIVE", "ORDERS_RECENT", "EQUITY_SERIES",
        "TRADING_PORTFOLIO_SUMMARY", "TRADING_ORDERS_OPEN",
        "PREDICTION_MARKETS_SUMMARY", "PREDICTION_DRIFT_SIGNALS",
        "SPECTATOR_RECORD", "SPECTATOR_LIVE",
        # Existing
        "RISK_METRICS", "RISK_EXPOSURE",
        "SYSTEM_HEALTH_V2",
        "LOGS_STATS", "LOGS_CLEAR",
        "USER_PROFILE", "USER_SETTINGS",
        "BETTING_CONSENSUS_METRICS",
        "PAPER_PORTFOLIO", "PAPER_POSITIONS",
    ]

    @pytest.fixture(autouse=True)
    def _load(self):
        self.text = self.CONSTANTS.read_text(encoding="utf-8")

    @pytest.mark.parametrize("key", REQUIRED_KEYS)
    def test_endpoint_key_present(self, key: str):
        assert key in self.text, f"Missing endpoint key: {key}"


# ── 3. Views use API_ENDPOINTS (no hardcoded URLs) ─────────────

class TestNoHardcodedFetchURLs:
    """No view file uses hardcoded fetch('/api/...) calls."""

    VIEWS_DIR = WEB_REACT / "views"

    def _view_files(self):
        return [f for f in self.VIEWS_DIR.glob("*.tsx") if "__tests__" not in str(f)]

    def test_no_hardcoded_fetch_in_any_view(self):
        pattern = re.compile(r"""fetch\s*\(\s*['"]\/api""")
        violations = []
        for f in self._view_files():
            text = f.read_text(encoding="utf-8")
            matches = pattern.findall(text)
            if matches:
                violations.append(f"{f.name}: {len(matches)} hardcoded fetch URL(s)")
        assert len(violations) == 0, (
            f"Found hardcoded fetch URLs in {len(violations)} view(s):\n"
            + "\n".join(violations)
        )


MIGRATED_VIEWS = [
    "Wallet.tsx",
    "Treasury.tsx",
    "Social.tsx",
    "Mining.tsx",
    "Institutional.tsx",
    "Plugins.tsx",
    "Betting.tsx",
    "Health.tsx",
    "Positions.tsx",
    "Orders.tsx",
    "TradeFloor.tsx",
    "Rewards.tsx",
    "Overview.tsx",
    "Predictions.tsx",
    "Logs.tsx",
    "Settings.tsx",
]


class TestMigratedViewsImportConstants:
    """Each migrated view imports API_ENDPOINTS."""

    VIEWS_DIR = WEB_REACT / "views"

    @pytest.mark.parametrize("filename", MIGRATED_VIEWS)
    def test_view_imports_api_endpoints(self, filename: str):
        path = self.VIEWS_DIR / filename
        assert path.exists(), f"{filename} not found"
        text = path.read_text(encoding="utf-8")
        assert "API_ENDPOINTS" in text, f"{filename} does not import API_ENDPOINTS"


# ── 4. Sidebar + App.tsx consistency ───────────────────────────

class TestSidebarAppConsistency:
    """Sidebar and App.tsx View types match."""

    APP = WEB_REACT / "App.tsx"
    SIDEBAR = WEB_REACT / "components" / "Sidebar.tsx"

    def _extract_view_type(self, path: Path) -> set:
        text = path.read_text(encoding="utf-8")
        m = re.search(r'type View\s*=\s*(.+?);', text)
        if not m:
            return set()
        raw = m.group(1)
        return set(re.findall(r'"([^"]+)"', raw))

    def test_view_types_match(self):
        app_views = self._extract_view_type(self.APP)
        sidebar_views = self._extract_view_type(self.SIDEBAR)
        assert app_views, "Could not extract View type from App.tsx"
        assert sidebar_views, "Could not extract View type from Sidebar.tsx"
        assert sidebar_views == app_views, (
            f"View type mismatch:\n"
            f"  In Sidebar but not App: {sidebar_views - app_views}\n"
            f"  In App but not Sidebar: {app_views - sidebar_views}"
        )

    def test_cross_asset_in_both(self):
        for path in [self.APP, self.SIDEBAR]:
            text = path.read_text(encoding="utf-8")
            assert "cross-asset" in text, f"cross-asset missing from {path.name}"
