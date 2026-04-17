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

    def test_kalshi_grid_nav_entry(self):
        src = self.SIDEBAR_PATH.read_text(encoding="utf-8")
        assert "'kalshi-grid'" in src or '"kalshi-grid"' in src

    def test_kalshi_grid_label(self):
        src = self.SIDEBAR_PATH.read_text(encoding="utf-8")
        assert "'Kalshi Grid'" in src or '"Kalshi Grid"' in src


class TestAppRouting:
    """Verify KalshiGridView is imported and routed in App.tsx."""

    APP_PATH = ROOT / "web" / "react" / "src" / "App.tsx"

    def _read(self) -> str:
        return self.APP_PATH.read_text(encoding="utf-8")

    def test_import_kalshi_grid_view(self):
        assert 'KalshiGridView' in self._read()

    def test_route_kalshi_grid(self):
        src = self._read()
        assert '"kalshi-grid"' in src
        assert '<KalshiGridView' in src


class TestKalshiGridViewComponent:
    """Verify KalshiGridView.tsx exists and has expected structure."""

    VIEW_PATH = ROOT / "web" / "react" / "src" / "views" / "KalshiGridView.tsx"

    def _read(self) -> str:
        return self.VIEW_PATH.read_text(encoding="utf-8")

    def test_file_exists(self):
        assert self.VIEW_PATH.exists()

    def test_exports_default_function(self):
        assert 'export default function KalshiGridView' in self._read()

    def test_uses_kalshi_grid_status(self):
        assert 'KALSHI_GRID_STATUS' in self._read()

    def test_uses_kalshi_grid_fills(self):
        assert 'KALSHI_GRID_FILLS' in self._read()

    def test_uses_kalshi_grid_agent_signals(self):
        assert 'KALSHI_GRID_AGENT_SIGNALS' in self._read()

    def test_uses_kalshi_grid_agent_orders(self):
        assert 'KALSHI_GRID_AGENT_ORDERS' in self._read()

    def test_has_start_button(self):
        assert 'Start Grid' in self._read()

    def test_has_stop_button(self):
        assert 'Stop Grid' in self._read()

    def test_has_pause_button(self):
        assert 'Pause All' in self._read()

    def test_has_resume_button(self):
        assert 'Resume All' in self._read()

    def test_has_kill_switch_reset(self):
        assert 'Reset Kill Switch' in self._read()

    def test_renders_asset_rows(self):
        src = self._read()
        for asset in ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']:
            assert f"'{asset}'" in src

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

    def test_signal_log_field(self):
        assert "signal_log" in self._read_source()

    def test_order_log_field(self):
        assert "order_log" in self._read_source()

    def test_fill_log_field(self):
        assert "fill_log" in self._read_source()

    def test_max_log_entries_constant(self):
        assert "_MAX_LOG_ENTRIES" in self._read_source()

    def test_record_signal_method(self):
        assert "def _record_signal(" in self._read_source()

    def test_get_signals_method(self):
        assert "def get_signals(" in self._read_source()

    def test_get_orders_method(self):
        assert "def get_orders(" in self._read_source()

    def test_get_fills_method(self):
        assert "def get_fills(" in self._read_source()

    def test_to_dict_includes_counts(self):
        src = self._read_source()
        assert '"signal_count"' in src
        assert '"order_count"' in src
        assert '"fill_count"' in src

    def test_ref_prices_captured(self):
        src = self._read_source()
        assert "ref_bid" in src
        assert "ref_ask" in src
        assert "ref_mid" in src

    def test_event_bus_emission(self):
        src = self._read_source()
        assert 'event_stream.publish("kalshi:order_filled"' in src


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

    def test_file_exists(self):
        assert (ROOT / "merid" / "prediction" / "social_broadcaster.py").exists()

    def test_class_defined(self):
        assert "class KalshiSocialBroadcaster" in self._read_source()

    def test_singleton_function(self):
        assert "def get_social_broadcaster" in self._read_source()

    def test_watched_events(self):
        src = self._read_source()
        assert "kalshi:order_filled" in src
        assert "kalshi:order_placed" in src
        assert "kalshi:market_resolved" in src

    def test_start_method(self):
        assert "async def start(" in self._read_source()

    def test_stop_method(self):
        assert "async def stop(" in self._read_source()

    def test_log_fill_method(self):
        assert "def _log_fill(" in self._read_source()

    def test_log_order_method(self):
        assert "def _log_order(" in self._read_source()

    def test_log_resolution_method(self):
        assert "def _log_resolution(" in self._read_source()

    def test_summary_method(self):
        assert "def summary(" in self._read_source()

    def test_twitter_format(self):
        assert "[SOCIAL:TWITTER]" in self._read_source()

    def test_telegram_format(self):
        assert "[SOCIAL:TELEGRAM]" in self._read_source()

    def test_messages_logged_counter(self):
        assert "messages_logged" in self._read_source()


class TestSocialBroadcasterWiring:
    """Verify broadcaster is wired into AgentGrid lifecycle."""

    def _read_grid(self) -> str:
        return (ROOT / "merid" / "prediction" / "agent_grid.py").read_text(encoding="utf-8")

    def test_import_broadcaster(self):
        assert "social_broadcaster" in self._read_grid()

    def test_broadcaster_created(self):
        assert "get_social_broadcaster()" in self._read_grid()

    def test_broadcaster_started(self):
        assert "self._broadcaster.start()" in self._read_grid()

    def test_broadcaster_stopped(self):
        assert "self._broadcaster.stop()" in self._read_grid()

    def test_broadcaster_in_summary(self):
        assert '"social_broadcaster"' in self._read_grid()


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

class TestSocialBroadcasterUnit:
    """Unit tests for KalshiSocialBroadcaster (no async, no event bus)."""

    def test_instantiation(self):
        from merid.prediction.social_broadcaster import KalshiSocialBroadcaster
        b = KalshiSocialBroadcaster()
        assert b._messages_logged == 0
        assert b._task is None

    def test_summary_when_stopped(self):
        from merid.prediction.social_broadcaster import KalshiSocialBroadcaster
        b = KalshiSocialBroadcaster()
        s = b.summary()
        assert s["running"] is False
        assert s["messages_logged"] == 0
        assert "kalshi:order_filled" in s["watched_events"]

    def test_dispatch_fill(self):
        from merid.prediction.social_broadcaster import KalshiSocialBroadcaster
        b = KalshiSocialBroadcaster()
        payload = {
            "agent": "btc-15m",
            "side": "yes",
            "action": "buy",
            "market_id": "KXBTC-25FEB14-T1",
            "price_cents": 55,
            "contracts": 3,
            "simulated": True,
        }
        b._dispatch("kalshi:order_filled", payload)
        assert b._messages_logged == 1

    def test_dispatch_order(self):
        from merid.prediction.social_broadcaster import KalshiSocialBroadcaster
        b = KalshiSocialBroadcaster()
        b._dispatch("kalshi:order_placed", {"market_id": "X", "side": "no", "action": "sell", "price_cents": 40, "contracts": 1})
        assert b._messages_logged == 1

    def test_dispatch_resolution(self):
        from merid.prediction.social_broadcaster import KalshiSocialBroadcaster
        b = KalshiSocialBroadcaster()
        b._dispatch("kalshi:market_resolved", {"market_id": "X", "result": "yes"})
        assert b._messages_logged == 1

    def test_dispatch_unknown_ignored(self):
        from merid.prediction.social_broadcaster import KalshiSocialBroadcaster
        b = KalshiSocialBroadcaster()
        b._dispatch("unknown:event", {})
        assert b._messages_logged == 0

    def test_singleton(self):
        from merid.prediction.social_broadcaster import get_social_broadcaster
        a = get_social_broadcaster()
        b = get_social_broadcaster()
        assert a is b


class TestAgentStateLogFields:
    """Verify AgentState dataclass has the new log fields."""

    def test_signal_log_default(self):
        from merid.prediction.trading_agent import AgentState
        s = AgentState(name="test")
        assert s.signal_log == []

    def test_order_log_default(self):
        from merid.prediction.trading_agent import AgentState
        s = AgentState(name="test")
        assert s.order_log == []

    def test_fill_log_default(self):
        from merid.prediction.trading_agent import AgentState
        s = AgentState(name="test")
        assert s.fill_log == []

    def test_to_dict_includes_counts(self):
        from merid.prediction.trading_agent import AgentState
        s = AgentState(name="test")
        d = s.to_dict()
        assert d["signal_count"] == 0
        assert d["order_count"] == 0
        assert d["fill_count"] == 0

    def test_to_dict_counts_reflect_data(self):
        from merid.prediction.trading_agent import AgentState
        s = AgentState(name="test")
        s.signal_log.append({"ts": "2026-01-01T00:00:00Z"})
        s.order_log.extend([{"ts": "a"}, {"ts": "b"}])
        s.fill_log.extend([{"ts": "x"}, {"ts": "y"}, {"ts": "z"}])
        d = s.to_dict()
        assert d["signal_count"] == 1
        assert d["order_count"] == 2
        assert d["fill_count"] == 3
