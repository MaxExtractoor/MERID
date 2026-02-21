"""Tests for Sprint 17 — UX Polish & Navigation Hardening.

Covers:
  1. CommandPalette component exists and covers all views
  2. ConnectionStatusIndicator component exists and uses API_ENDPOINTS
  3. Collapsible sidebar with collapsed/onToggleCollapse props
  4. SkeletonLoader component with variants
  5. No remaining hardcoded fetch URLs in components/
  6. CommandPalette wired in App.tsx
  7. TopBar uses API_ENDPOINTS (no hardcoded URLs)
  8. ApiDashboard uses API_ENDPOINTS (no hardcoded URLs)
  9. API_METRICS constant exists
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_REACT = ROOT / "web" / "react" / "src"
VIEWS_DIR = WEB_REACT / "views"
COMPONENTS_DIR = WEB_REACT / "components"


# ── 1. CommandPalette ──────────────────────────────────────────

class TestCommandPalette:
    """CommandPalette component exists and covers all sidebar views."""

    CP = COMPONENTS_DIR / "CommandPalette.tsx"

    def test_file_exists(self):
        assert self.CP.exists()

    def test_has_keyboard_shortcut(self):
        text = self.CP.read_text(encoding="utf-8")
        assert "ctrlKey" in text or "metaKey" in text

    def test_has_escape_close(self):
        text = self.CP.read_text(encoding="utf-8")
        assert "Escape" in text

    def test_has_arrow_navigation(self):
        text = self.CP.read_text(encoding="utf-8")
        assert "ArrowDown" in text
        assert "ArrowUp" in text

    def test_has_enter_select(self):
        text = self.CP.read_text(encoding="utf-8")
        assert "Enter" in text

    SIDEBAR_VIEWS = [
        "overview", "trading", "tradefloor", "positions", "orders",
        "wallet", "treasury", "predictions", "betting",
        "rewards", "social", "paper-trading", "cross-asset",
        "operator", "risk", "agents", "cognitive",
        "devswarm", "settings", "loop-orchestration", "observability",
        "health", "logs",
    ]

    @pytest.mark.parametrize("view_id", SIDEBAR_VIEWS)
    def test_command_covers_view(self, view_id: str):
        text = self.CP.read_text(encoding="utf-8")
        assert f"'{view_id}'" in text or f'"{view_id}"' in text, (
            f"CommandPalette missing view: {view_id}"
        )

    def test_wired_in_app(self):
        app = (WEB_REACT / "App.tsx").read_text(encoding="utf-8")
        assert "CommandPalette" in app


# ── 2. ConnectionStatusIndicator ───────────────────────────────

class TestConnectionStatusIndicator:
    """ConnectionStatusIndicator exists and uses centralized endpoints."""

    CSI = COMPONENTS_DIR / "ConnectionStatusIndicator.tsx"

    def test_file_exists(self):
        assert self.CSI.exists()

    def test_imports_api_endpoints(self):
        text = self.CSI.read_text(encoding="utf-8")
        assert "API_ENDPOINTS" in text

    def test_has_three_states(self):
        text = self.CSI.read_text(encoding="utf-8")
        assert "connected" in text
        assert "degraded" in text
        assert "disconnected" in text

    def test_shows_latency(self):
        text = self.CSI.read_text(encoding="utf-8")
        assert "latency" in text.lower()

    def test_wired_in_topbar(self):
        topbar = (COMPONENTS_DIR / "TopBar.tsx").read_text(encoding="utf-8")
        assert "ConnectionStatusIndicator" in topbar


# ── 3. Collapsible Sidebar ─────────────────────────────────────

class TestCollapsibleSidebar:
    """Sidebar supports collapsed mode with localStorage persistence."""

    SIDEBAR = COMPONENTS_DIR / "Sidebar.tsx"
    APP = WEB_REACT / "App.tsx"

    def test_sidebar_has_collapsed_prop(self):
        text = self.SIDEBAR.read_text(encoding="utf-8")
        assert "collapsed" in text

    def test_sidebar_has_toggle_callback(self):
        text = self.SIDEBAR.read_text(encoding="utf-8")
        assert "onToggleCollapse" in text

    def test_sidebar_hides_labels_when_collapsed(self):
        text = self.SIDEBAR.read_text(encoding="utf-8")
        assert "!collapsed" in text

    def test_sidebar_shows_tooltips_when_collapsed(self):
        text = self.SIDEBAR.read_text(encoding="utf-8")
        assert "title={collapsed" in text

    def test_app_persists_collapse_state(self):
        text = self.APP.read_text(encoding="utf-8")
        assert "merid-sidebar-collapsed" in text

    def test_app_passes_collapsed_to_sidebar(self):
        text = self.APP.read_text(encoding="utf-8")
        assert "collapsed={sidebarCollapsed}" in text


# ── 4. SkeletonLoader ──────────────────────────────────────────

class TestSkeletonLoader:
    """SkeletonLoader component provides content-shaped loading placeholders."""

    SK = COMPONENTS_DIR / "SkeletonLoader.tsx"

    def test_file_exists(self):
        assert self.SK.exists()

    def test_has_card_variant(self):
        text = self.SK.read_text(encoding="utf-8")
        assert "SkeletonCard" in text

    def test_has_table_variant(self):
        text = self.SK.read_text(encoding="utf-8")
        assert "SkeletonTable" in text

    def test_has_chart_variant(self):
        text = self.SK.read_text(encoding="utf-8")
        assert "SkeletonChart" in text

    def test_has_metric_row(self):
        text = self.SK.read_text(encoding="utf-8")
        assert "SkeletonMetricRow" in text

    def test_uses_animate_pulse(self):
        text = self.SK.read_text(encoding="utf-8")
        assert "animate-pulse" in text

    def test_default_export(self):
        text = self.SK.read_text(encoding="utf-8")
        assert "export default" in text
        assert "SkeletonLoader" in text


# ── 5. No hardcoded fetch URLs in components ───────────────────

class TestNoHardcodedFetchInAnyComponent:
    """No component uses hardcoded fetch('/api/...') calls (Sprint 18 full migration)."""

    def test_no_hardcoded_fetch_in_any_component(self):
        pattern = re.compile(r"""fetch\s*\(\s*['"]\/api""")
        violations = []
        for f in sorted(COMPONENTS_DIR.rglob("*.tsx")):
            if "__tests__" in str(f):
                continue
            text = f.read_text(encoding="utf-8")
            matches = pattern.findall(text)
            if matches:
                violations.append(f"{f.name}: {len(matches)} hardcoded fetch URL(s)")
        assert len(violations) == 0, (
            f"Found hardcoded fetch URLs in {len(violations)} component(s):\n"
            + "\n".join(violations)
        )


# ── 6. TopBar and ApiDashboard use constants ───────────────────

class TestTopBarApiDashboardConstants:
    """TopBar and ApiDashboard use API_ENDPOINTS, not hardcoded URLs."""

    def test_topbar_imports_api_endpoints(self):
        text = (COMPONENTS_DIR / "TopBar.tsx").read_text(encoding="utf-8")
        assert "API_ENDPOINTS" in text

    def test_api_dashboard_uses_api_metrics(self):
        text = (VIEWS_DIR / "ApiDashboard.tsx").read_text(encoding="utf-8")
        assert "API_ENDPOINTS.API_METRICS" in text

    def test_api_metrics_constant_exists(self):
        text = (WEB_REACT / "config" / "constants.ts").read_text(encoding="utf-8")
        assert "API_METRICS" in text


# ── 7. No hardcoded fetch URLs in views ────────────────────────

class TestNoHardcodedFetchInViews:
    """No view uses hardcoded fetch('/api/...') calls."""

    def test_no_hardcoded_fetch_in_views(self):
        pattern = re.compile(r"""fetch\s*\(\s*['"]\/api""")
        violations = []
        for f in sorted(VIEWS_DIR.glob("*.tsx")):
            if "__tests__" in str(f):
                continue
            text = f.read_text(encoding="utf-8")
            matches = pattern.findall(text)
            if matches:
                violations.append(f"{f.name}: {len(matches)} hardcoded fetch URL(s)")
        assert len(violations) == 0, (
            f"Found hardcoded fetch URLs in {len(violations)} view(s):\n"
            + "\n".join(violations)
        )


# ── 8. No hardcoded fetch URLs in hooks ────────────────────────

class TestNoHardcodedFetchInHooks:
    """No hook uses hardcoded fetch('/api/...') calls (generic hooks like useApiData excluded)."""

    HOOKS_DIR = WEB_REACT / "hooks"

    def test_no_hardcoded_fetch_in_hooks(self):
        pattern = re.compile(r"""fetch\s*\(\s*['"]\/api""")
        violations = []
        for f in sorted(self.HOOKS_DIR.glob("*.ts")):
            if "__tests__" in str(f):
                continue
            text = f.read_text(encoding="utf-8")
            matches = pattern.findall(text)
            if matches:
                violations.append(f"{f.name}: {len(matches)} hardcoded fetch URL(s)")
        assert len(violations) == 0, (
            f"Found hardcoded fetch URLs in {len(violations)} hook(s):\n"
            + "\n".join(violations)
        )

    def test_use_markets_data_uses_api_endpoints(self):
        text = (self.HOOKS_DIR / "useMarketsData.ts").read_text(encoding="utf-8")
        assert "API_ENDPOINTS" in text

    def test_use_risk_protections_uses_api_endpoints(self):
        text = (self.HOOKS_DIR / "useRiskProtections.ts").read_text(encoding="utf-8")
        assert "API_ENDPOINTS" in text
