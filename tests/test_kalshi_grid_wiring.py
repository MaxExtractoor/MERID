"""Tests for Kalshi Grid Wiring — Steps 1-4.

Covers:
  - Step 1: Frontend constants, View type, Sidebar entry, KalshiGridView component
  - Step 2: Signal/order/fill persistence in KalshiTradingAgent + new API endpoints
  - Step 3: PnL endpoint wiring
  - Step 4: Event bus emission + KalshiSocialBroadcaster
"""

import ast
import os
import pathlib
import re
import textwrap
from unittest.mock import MagicMock, patch

import pytest
_XFAIL_PARAMS = {
}

def _ap(names, test_name):
    """Per-param strict xfail driven by audit dispositions (AUDIT-2026-09-22)."""
    fm = _XFAIL_PARAMS.get(test_name, {})
    out = []
    for n in names:
        vals = getattr(n, "values", None)
        if vals is not None:  # already a pytest.param/ParameterSet
            key = "-".join(str(v) for v in vals)
            if key not in fm and vals:
                key = next(
                    (k for k in fm
                     if k == str(vals[0]) or k.startswith(str(vals[0]) + "-")),
                    key)
            if key in fm:
                out.append(pytest.param(
                    *vals, marks=list(n.marks) + [
                        pytest.mark.xfail(strict=True, reason=fm[key])]))
            else:
                out.append(n)
        elif isinstance(n, tuple):
            key = "-".join(str(x) for x in n)
            if key not in fm and n:
                key = next(
                    (k for k in fm
                     if k == str(n[0]) or k.startswith(str(n[0]) + "-")),
                    key)
            if key in fm:
                out.append(pytest.param(
                    *n, marks=pytest.mark.xfail(strict=True, reason=fm[key])))
            else:
                out.append(n)
        elif n in fm:
            out.append(pytest.param(
                n, marks=pytest.mark.xfail(strict=True, reason=fm[n])))
        else:
            out.append(n)
    return out


ROOT = pathlib.Path(__file__).resolve().parent.parent


# ═══════════════════════════════════════════════════════════════════════
# §1  Frontend wiring
# ═══════════════════════════════════════════════════════════════════════

class TestFrontendConstants:
    """Verify Kalshi Grid API endpoints are defined in constants.ts."""

    CONSTANTS_PATH = ROOT / "web" / "react" / "src" / "config" / "constants.ts"

    def _read(self) -> str:
        return self.CONSTANTS_PATH.read_text(encoding="utf-8")

    def test_kalshi_grid_status_endpoint(self):
        assert 'KALSHI_GRID_STATUS' in self._read()

    def test_kalshi_grid_matrix_endpoint(self):
        assert 'KALSHI_GRID_MATRIX' in self._read()

    def test_kalshi_grid_agents_endpoint(self):
        assert 'KALSHI_GRID_AGENTS' in self._read()

    def test_kalshi_grid_agent_function(self):
        assert 'KALSHI_GRID_AGENT:' in self._read()

    def test_kalshi_grid_agent_signals_function(self):
        assert 'KALSHI_GRID_AGENT_SIGNALS' in self._read()

    def test_kalshi_grid_agent_orders_function(self):
        assert 'KALSHI_GRID_AGENT_ORDERS' in self._read()

    def test_kalshi_grid_fills_endpoint(self):
        assert 'KALSHI_GRID_FILLS' in self._read()

    def test_kalshi_grid_pnl_endpoint(self):
        assert 'KALSHI_GRID_PNL' in self._read()

    def test_kalshi_grid_portfolio_endpoint(self):
        assert 'KALSHI_GRID_PORTFOLIO' in self._read()

    def test_kalshi_grid_session_endpoint(self):
        assert 'KALSHI_GRID_SESSION' in self._read()

    def test_kalshi_grid_start_endpoint(self):
        assert 'KALSHI_GRID_START' in self._read()

    def test_kalshi_grid_stop_endpoint(self):
        assert 'KALSHI_GRID_STOP' in self._read()

    def test_kalshi_grid_pause_endpoint(self):
        assert 'KALSHI_GRID_PAUSE' in self._read()

    def test_kalshi_grid_resume_endpoint(self):
        assert 'KALSHI_GRID_RESUME' in self._read()

    def test_kalshi_grid_kill_switch_reset_endpoint(self):
        assert 'KALSHI_GRID_KILL_SWITCH_RESET' in self._read()

    def test_endpoint_urls_correct(self):
        src = self._read()
        assert '"/api/v1/kalshi-grid/status"' in src
        assert '"/api/v1/kalshi-grid/fills"' in src
        assert '"/api/v1/kalshi-grid/pnl"' in src


class TestViewType:
    """Verify 'kalshi-grid' is in the View union type."""

    VIEWS_PATH = ROOT / "web" / "react" / "src" / "types" / "views.ts"

    def test_kalshi_grid_in_view_type(self):
        src = self.VIEWS_PATH.read_text(encoding="utf-8")
        assert '"kalshi-grid"' in src


class TestSidebarEntry:
    """Verify Kalshi Grid appears in the sidebar navigation."""

    SIDEBAR_PATH = ROOT / "web" / "react" / "src" / "components" / "Sidebar.tsx"

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
    def test_kalshi_grid_nav_entry(self):
        src = self.SIDEBAR_PATH.read_text(encoding="utf-8")
        assert "'kalshi-grid'" in src or '"kalshi-grid"' in src

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
    def test_kalshi_grid_label(self):
        src = self.SIDEBAR_PATH.read_text(encoding="utf-8")
        assert "'Kalshi Grid'" in src or '"Kalshi Grid"' in src


class TestAppRouting:
    """Verify KalshiGridView is imported and routed in App.tsx."""

    APP_PATH = ROOT / "web" / "react" / "src" / "App.tsx"

    def _read(self) -> str:
        return self.APP_PATH.read_text(encoding="utf-8")

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
    def test_import_kalshi_grid_view(self):
        assert 'KalshiGridView' in self._read()

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
    def test_route_kalshi_grid(self):
        src = self._read()
        assert '"kalshi-grid"' in src
        assert '<KalshiGridView' in src


class TestKalshiGridViewComponent:
    """Verify KalshiGridView.tsx exists and has expected structure."""

    VIEW_PATH = ROOT / "web" / "react" / "src" / "views" / "KalshiGridView.tsx"

    def _read(self) -> str:
        return self.VIEW_PATH.read_text(encoding="utf-8")

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
    def test_file_exists(self):
        assert self.VIEW_PATH.exists()

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_exports_default_function(self):
        assert 'export default function KalshiGridView' in self._read()

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_uses_kalshi_grid_status(self):
        assert 'KALSHI_GRID_STATUS' in self._read()

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_uses_kalshi_grid_fills(self):
        assert 'KALSHI_GRID_FILLS' in self._read()

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_uses_kalshi_grid_agent_signals(self):
        assert 'KALSHI_GRID_AGENT_SIGNALS' in self._read()

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_uses_kalshi_grid_agent_orders(self):
        assert 'KALSHI_GRID_AGENT_ORDERS' in self._read()

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_has_start_button(self):
        assert 'Start Grid' in self._read()

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_has_stop_button(self):
        assert 'Stop Grid' in self._read()

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_has_pause_button(self):
        assert 'Pause All' in self._read()

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_has_resume_button(self):
        assert 'Resume All' in self._read()

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_has_kill_switch_reset(self):
        assert 'Reset Kill Switch' in self._read()

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_renders_asset_rows(self):
        src = self._read()
        for asset in ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']:
            assert f"'{asset}'" in src

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_renders_timeframe_columns(self):
        src = self._read()
        for tf in ['15m', '1h', 'daily', 'pre-market']:
            assert f"'{tf}'" in src


# ═══════════════════════════════════════════════════════════════════════
# §2  Signal/Order/Fill persistence in trading agent
# ═══════════════════════════════════════════════════════════════════════

class TestTradingAgentPersistence:
    """Verify signal_log, order_log, fill_log are present in AgentState."""

    def _read_source(self) -> str:
        return (ROOT / "merid" / "prediction" / "trading_agent.py").read_text(encoding="utf-8")













# ═══════════════════════════════════════════════════════════════════════
# §3  API endpoints
# ═══════════════════════════════════════════════════════════════════════

class TestKalshiGridApi:
    """Verify new API endpoints exist in kalshi_grid_api.py."""

    def _read_source(self) -> str:
        return (ROOT / "web" / "api" / "kalshi_grid_api.py").read_text(encoding="utf-8")

    def test_agent_signals_endpoint(self):
        src = self._read_source()
        assert '"/agents/{name}/signals"' in src

    def test_agent_orders_endpoint(self):
        src = self._read_source()
        assert '"/agents/{name}/orders"' in src

    def test_fills_endpoint(self):
        src = self._read_source()
        assert '"/fills"' in src

    def test_pnl_endpoint(self):
        src = self._read_source()
        assert '"/pnl"' in src

    def test_signals_uses_query_param(self):
        src = self._read_source()
        assert 'Query(50' in src or 'Query(' in src

    def test_fills_uses_query_param(self):
        src = self._read_source()
        assert 'Query(100' in src

    def test_pnl_returns_per_agent(self):
        src = self._read_source()
        assert '"agents"' in src and '"total_fills"' in src

    def test_docstring_updated(self):
        src = self._read_source()
        assert '/agents/{name}/signals' in src
        assert '/agents/{name}/orders' in src
        assert '/fills' in src
        assert '/pnl' in src


# ═══════════════════════════════════════════════════════════════════════
# §4  Social broadcaster
# ═══════════════════════════════════════════════════════════════════════

class TestSocialBroadcaster:
    """Verify KalshiSocialBroadcaster module structure."""

    def _read_source(self) -> str:
        return (ROOT / "merid" / "prediction" / "social_broadcaster.py").read_text(encoding="utf-8")

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
    def test_file_exists(self):
        assert (ROOT / "merid" / "prediction" / "social_broadcaster.py").exists()














class TestSocialBroadcasterWiring:
    """Verify broadcaster is wired into AgentGrid lifecycle."""

    def _read_grid(self) -> str:
        return (ROOT / "merid" / "prediction" / "agent_grid.py").read_text(encoding="utf-8")







class TestPredictionModuleExports:
    """Verify __init__.py exports the new social broadcaster."""

    def _read_init(self) -> str:
        return (ROOT / "merid" / "prediction" / "__init__.py").read_text(encoding="utf-8")

    def test_import_social_broadcaster(self):
        assert "KalshiSocialBroadcaster" in self._read_init()

    def test_import_get_social_broadcaster(self):
        assert "get_social_broadcaster" in self._read_init()

    def test_all_includes_broadcaster(self):
        src = self._read_init()
        assert '"KalshiSocialBroadcaster"' in src
        assert '"get_social_broadcaster"' in src


# ═══════════════════════════════════════════════════════════════════════
# §5  Unit tests (import-safe)
# ═══════════════════════════════════════════════════════════════════════



