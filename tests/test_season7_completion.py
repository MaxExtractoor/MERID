"""Season 7 completion tests — covers all S7 invariants and new modules.

Run:
    python -m pytest tests/test_season7_completion.py -v
"""

from __future__ import annotations

import collections
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ════════════════════════════════════════════════════════════════════
# S7-1: Per-agent latency SLOs + alert
# ════════════════════════════════════════════════════════════════════

class TestAgentLatencySLO:
    """Verify agent latency tracking and the SLO alert."""

    def test_agent_framework_has_latency_samples(self):
        src = (PROJECT_ROOT / "agents/agent_framework.py").read_text(encoding="utf-8")
        assert "_latency_samples" in src, "agent_framework.py must have _latency_samples deque"

    def test_agent_framework_tracks_p95(self):
        src = (PROJECT_ROOT / "agents/agent_framework.py").read_text(encoding="utf-8")
        assert "p95_latency_ms" in src, "agent_framework.py must compute p95_latency_ms"
        assert "average_latency_ms" in src, "agent_framework.py must compute average_latency_ms"

    def test_latency_slo_alert_class_exists(self):
        src = (PROJECT_ROOT / "web/api/system_observability.py").read_text(encoding="utf-8")
        assert "class AgentLatencySLOAlert" in src
        assert "AgentLatencySLOAlert()" in src

    def test_latency_slo_alert_thresholds(self):
        src = (PROJECT_ROOT / "web/api/system_observability.py").read_text(encoding="utf-8")
        assert "P95_WARN_MS" in src
        assert "P95_CRIT_MS" in src

    def test_ui_has_latency_column(self):
        src = (PROJECT_ROOT / "web/react/src/components/AgentPerformanceTable.tsx").read_text(encoding="utf-8")
        assert "p95_latency_ms" in src, "AgentPerformanceTable must have p95_latency_ms field"
        assert "P95 Lat" in src, "AgentPerformanceTable must have P95 Lat column header"
        assert "formatLatency" in src, "AgentPerformanceTable must have formatLatency helper"
        assert "getLatencyColor" in src, "AgentPerformanceTable must have getLatencyColor helper"


# ════════════════════════════════════════════════════════════════════
# S7-2: True equity series
# ════════════════════════════════════════════════════════════════════

class TestTrueEquitySeries:
    """Verify true equity = balance + unrealized - fees is tracked."""

    def test_portfolio_has_equity_snapshots(self):
        src = (PROJECT_ROOT / "trading/paper_trading.py").read_text(encoding="utf-8")
        assert "equity_snapshots" in src, "PaperPortfolio must have equity_snapshots"

    def test_get_portfolio_stats_has_true_equity(self):
        src = (PROJECT_ROOT / "trading/paper_trading.py").read_text(encoding="utf-8")
        assert '"true_equity"' in src, "get_portfolio_stats must include true_equity"

    def test_get_global_stats_has_true_equity(self):
        src = (PROJECT_ROOT / "trading/paper_trading.py").read_text(encoding="utf-8")
        assert "true_equity" in src

    def test_get_equity_series_method(self):
        src = (PROJECT_ROOT / "trading/paper_trading.py").read_text(encoding="utf-8")
        assert "def get_equity_series" in src

    def test_equity_snapshot_throttle(self):
        src = (PROJECT_ROOT / "trading/paper_trading.py").read_text(encoding="utf-8")
        assert "_equity_snapshot_interval" in src
        assert "_maybe_record_equity_snapshots" in src


# ════════════════════════════════════════════════════════════════════
# S7-3: Reconciliation staleness alert
# ════════════════════════════════════════════════════════════════════

class TestReconciliationStaleness:
    """Verify reconciliation staleness tracking and alert."""

    def test_reconciliation_has_timestamp(self):
        src = (PROJECT_ROOT / "merid/reconciliation.py").read_text(encoding="utf-8")
        assert "_last_reconciliation_ts" in src
        assert "def get_last_reconciliation_ts" in src

    def test_reconciliation_stale_alert_exists(self):
        src = (PROJECT_ROOT / "web/api/system_observability.py").read_text(encoding="utf-8")
        assert "class ReconciliationStaleAlert" in src
        assert "ReconciliationStaleAlert()" in src

    def test_reconciliation_stale_alert_thresholds(self):
        src = (PROJECT_ROOT / "web/api/system_observability.py").read_text(encoding="utf-8")
        assert "STALE_WARN_S" in src
        assert "STALE_CRIT_S" in src

    def test_reconciliation_ts_updated_on_reconcile(self):
        src = (PROJECT_ROOT / "merid/reconciliation.py").read_text(encoding="utf-8")
        assert "_last_reconciliation_ts = time.time()" in src


# ════════════════════════════════════════════════════════════════════
# S7-4: Per-venue exposure caps in execution guard
# ════════════════════════════════════════════════════════════════════

class TestVenueExposureCaps:
    """Verify per-venue exposure caps in execution guard."""

    def test_venue_exposure_cap_class(self):
        src = (PROJECT_ROOT / "merid/execution_guard.py").read_text(encoding="utf-8")
        assert "class VenueExposureCap" in src
        assert "max_exposure_usd" in src
        assert "current_exposure_usd" in src

    def test_venue_caps_in_guard(self):
        src = (PROJECT_ROOT / "merid/execution_guard.py").read_text(encoding="utf-8")
        assert "_venue_caps" in src
        assert "venue_exposure_cap" in src

    def test_venue_cap_check_in_pre_trade(self):
        src = (PROJECT_ROOT / "merid/execution_guard.py").read_text(encoding="utf-8")
        assert "4.5 Per-venue exposure cap" in src

    def test_venue_caps_in_summary(self):
        src = (PROJECT_ROOT / "merid/execution_guard.py").read_text(encoding="utf-8")
        assert '"venue_caps"' in src

    def test_venue_cap_functional(self):
        from merid.execution_guard import VenueExposureCap
        cap = VenueExposureCap(venue="test", max_exposure_usd=1000.0, current_exposure_usd=800.0)
        assert cap.remaining() == 200.0
        assert cap.would_breach(300.0) is True
        assert cap.would_breach(100.0) is False
        cap.record(100.0)
        assert cap.current_exposure_usd == 900.0
        cap.release(200.0)
        assert cap.current_exposure_usd == 700.0

    def test_guard_venue_param_in_pre_trade(self):
        src = (PROJECT_ROOT / "merid/execution_guard.py").read_text(encoding="utf-8")
        assert 'venue: str = ""' in src or "venue: str = ''" in src

    def test_sync_venue_exposure(self):
        from merid.execution_guard import ExecutionGuard
        guard = ExecutionGuard()
        guard.sync_venue_exposure("binance", 5000.0)
        cap = guard.get_venue_cap("binance")
        assert cap is not None
        assert cap.current_exposure_usd == 5000.0


# ════════════════════════════════════════════════════════════════════
# S7-5: WS channel health + event freshness alert
# ════════════════════════════════════════════════════════════════════

class TestWsChannelFreshness:
    """Verify WS channel event freshness tracking and alert."""

    def test_channel_freshness_tracking_exists(self):
        src = (PROJECT_ROOT / "web/api/live_stream.py").read_text(encoding="utf-8")
        assert "record_channel_event" in src
        assert "get_channel_freshness" in src
        assert "_channel_last_event_ts" in src

    def test_shared_ws_helper_records_events(self):
        src = (PROJECT_ROOT / "web/api/live_stream.py").read_text(encoding="utf-8")
        assert "_run_ws_endpoint" in src, "Shared WS helper must exist"
        assert src.count("_run_ws_endpoint") >= 5  # def + 4 endpoint calls
        assert "record_channel_event" in src, "Freshness tracking must be in shared helper"

    def test_ws_channel_stale_alert_exists(self):
        src = (PROJECT_ROOT / "web/api/system_observability.py").read_text(encoding="utf-8")
        assert "class WsChannelStaleAlert" in src
        assert "WsChannelStaleAlert()" in src

    def test_ws_channel_stale_alert_threshold(self):
        src = (PROJECT_ROOT / "web/api/system_observability.py").read_text(encoding="utf-8")
        assert "CHANNEL_THRESHOLDS" in src
        assert "DEFAULT_THRESHOLD_S" in src
        assert '"market_data"' in src
        assert '"news"' in src
        assert '"agent_output"' in src


# ════════════════════════════════════════════════════════════════════
# S7-6: End-to-end loop integration test
# ════════════════════════════════════════════════════════════════════

class TestEndToEndLoopIntegration:
    """Verify the execution guard → paper engine → reconciliation pipeline."""

    def test_execution_guard_blocks_kill_switch(self):
        from merid.execution_guard import ExecutionGuard
        guard = ExecutionGuard()
        guard.activate_kill_switch("test")
        verdict = guard.pre_trade_check("test-1", "BTC/USD", "crypto", 1000.0)
        assert not verdict.allowed
        assert "kill switch" in verdict.reason.lower()
        guard.deactivate_kill_switch()

    def test_execution_guard_allows_after_deactivation(self):
        from merid.execution_guard import ExecutionGuard
        guard = ExecutionGuard()
        guard.activate_kill_switch("test")
        guard.deactivate_kill_switch()
        # Need to bypass cooldown
        guard._last_execution_at = 0.0
        verdict = guard.pre_trade_check("test-2", "BTC/USD", "crypto", 500.0)
        assert verdict.allowed

    def test_execution_guard_venue_cap_blocks(self):
        from merid.execution_guard import ExecutionGuard
        guard = ExecutionGuard()
        guard._last_execution_at = 0.0
        guard.set_venue_cap("test_venue", 100.0)
        guard.sync_venue_exposure("test_venue", 100.0)
        verdict = guard.pre_trade_check("test-3", "BTC/USD", "crypto", 500.0, venue="test_venue")
        assert not verdict.allowed
        assert "venue exposure cap" in verdict.reason.lower()

    def test_execution_guard_venue_cap_clamps(self):
        from merid.execution_guard import ExecutionGuard
        guard = ExecutionGuard()
        guard._last_execution_at = 0.0
        guard.set_venue_cap("clamp_venue", 500.0)
        guard.sync_venue_exposure("clamp_venue", 400.0)
        verdict = guard.pre_trade_check("test-4", "BTC/USD", "crypto", 200.0, venue="clamp_venue")
        assert verdict.allowed
        assert verdict.adjusted_size_usd <= 100.0

    def test_execution_guard_cooldown_blocks(self):
        from merid.execution_guard import ExecutionGuard
        guard = ExecutionGuard()
        guard._last_execution_at = time.time()  # Just executed
        verdict = guard.pre_trade_check("test-5", "BTC/USD", "crypto", 500.0)
        assert not verdict.allowed
        assert "cooldown" in verdict.reason.lower()

    def test_reconciliation_ts_functional(self):
        from merid.reconciliation import get_last_reconciliation_ts
        ts = get_last_reconciliation_ts()
        assert isinstance(ts, float)

    def test_guard_summary_includes_venue_caps(self):
        from merid.execution_guard import ExecutionGuard
        guard = ExecutionGuard()
        summary = guard.summary()
        assert "venue_caps" in summary
        assert "domain_caps" in summary
        assert "global_kill_switch" in summary


# ════════════════════════════════════════════════════════════════════
# S7-7: Mock adapter safety guard
# ════════════════════════════════════════════════════════════════════

class TestMockAdapterSafetyGuard:
    """Verify stub adapters raise NotImplementedError in live mode."""

    def test_venue_adapter_has_is_stub(self):
        src = (PROJECT_ROOT / "core/venue_adapter.py").read_text(encoding="utf-8")
        assert "_is_stub" in src
        assert "_place_order_impl" in src

    def test_all_stub_adapters_marked(self):
        venues_dir = PROJECT_ROOT / "core/venues"
        stub_files = [
            "alpaca_adapter.py", "binanceus_adapter.py", "bitget_adapter.py",
            "coinbase_advanced_adapter.py", "gateio_adapter.py", "gemini_adapter.py",
            "htx_adapter.py", "ibkr_adapter.py", "kalshi_adapter.py",
            "kraken_adapter.py", "kucoin_adapter.py", "mexc_adapter.py",
            "okx_adapter.py",
        ]
        for fname in stub_files:
            src = (venues_dir / fname).read_text(encoding="utf-8")
            assert "_is_stub = True" in src, f"{fname} must have _is_stub = True"
            assert "_place_order_impl" in src, f"{fname} must use _place_order_impl"

    def test_merid_sim_not_stub(self):
        src = (PROJECT_ROOT / "core/venues/merid_sim_adapter.py").read_text(encoding="utf-8")
        assert "_is_stub = True" not in src, "merid_sim_adapter must NOT be a stub"
        assert "_place_order_impl" in src, "merid_sim_adapter must use _place_order_impl"

    @pytest.mark.asyncio
    async def test_stub_adapter_raises_on_live(self):
        from decimal import Decimal
        from core.venue_adapter import VenueAdapter, OrderSide, OrderType

        class FakeStub(VenueAdapter):
            _is_stub = True

            async def connect(self): return True
            async def disconnect(self): return True
            async def get_market_data(self, symbol): return None
            async def _place_order_impl(self, symbol, side, order_type, amount, price=None):
                return {"status": "filled"}
            async def cancel_order(self, order_id, symbol): return {}
            async def get_order_status(self, order_id, symbol): return None
            async def get_open_orders(self, symbol=None): return []
            async def get_positions(self): return []
            async def get_balance(self): return {}

        stub = FakeStub("fake", paper=False)
        with pytest.raises(NotImplementedError, match="stub adapter"):
            await stub.place_order("BTC/USD", OrderSide.BUY, OrderType.MARKET, Decimal("1"))

    @pytest.mark.asyncio
    async def test_stub_adapter_allows_paper(self):
        from decimal import Decimal
        from core.venue_adapter import VenueAdapter, OrderSide, OrderType

        class FakeStub(VenueAdapter):
            _is_stub = True

            async def connect(self): return True
            async def disconnect(self): return True
            async def get_market_data(self, symbol): return None
            async def _place_order_impl(self, symbol, side, order_type, amount, price=None):
                return {"status": "filled"}
            async def cancel_order(self, order_id, symbol): return {}
            async def get_order_status(self, order_id, symbol): return None
            async def get_open_orders(self, symbol=None): return []
            async def get_positions(self): return []
            async def get_balance(self): return {}

        stub = FakeStub("fake", paper=True)
        result = await stub.place_order("BTC/USD", OrderSide.BUY, OrderType.MARKET, Decimal("1"))
        assert result["status"] == "filled"


# ════════════════════════════════════════════════════════════════════
# Cross-cutting: All S7 alerts registered in ALERT_RULES
# ════════════════════════════════════════════════════════════════════

class TestS7AlertsRegistered:
    """Verify all Season 7 alerts are registered in ALERT_RULES."""

    def test_all_s7_alerts_in_rules(self):
        src = (PROJECT_ROOT / "web/api/system_observability.py").read_text(encoding="utf-8")
        s7_alerts = [
            "AgentLatencySLOAlert()",
            "ReconciliationStaleAlert()",
            "WsChannelStaleAlert()",
        ]
        for alert in s7_alerts:
            assert alert in src, f"{alert} must be in ALERT_RULES"

    def test_total_alert_count_minimum(self):
        src = (PROJECT_ROOT / "web/api/system_observability.py").read_text(encoding="utf-8")
        # Count entries in ALERT_RULES by counting instances of "Alert(),"
        # (all entries except the last end with a comma)
        import re
        alert_instances = re.findall(r"Alert\(\),?\n", src)
        assert len(alert_instances) >= 30, f"Expected >=30 alerts, got {len(alert_instances)}"


# ════════════════════════════════════════════════════════════════════
# S8-4: WS sender/receiver DRY refactor
# ════════════════════════════════════════════════════════════════════

class TestWsDryRefactor:
    """Verify the WS DRY refactor: shared helper replaces duplicated code."""

    def test_shared_helper_exists(self):
        src = (PROJECT_ROOT / "web/api/live_stream.py").read_text(encoding="utf-8")
        assert "async def _run_ws_endpoint(" in src

    def test_all_endpoints_use_shared_helper(self):
        src = (PROJECT_ROOT / "web/api/live_stream.py").read_text(encoding="utf-8")
        # def + 4 endpoint calls = at least 5
        assert src.count("_run_ws_endpoint") >= 5

    def test_no_duplicate_receiver(self):
        src = (PROJECT_ROOT / "web/api/live_stream.py").read_text(encoding="utf-8")
        # Only 1 _receiver definition inside the shared helper
        assert src.count("async def _receiver()") == 1

    def test_no_duplicate_sender(self):
        src = (PROJECT_ROOT / "web/api/live_stream.py").read_text(encoding="utf-8")
        # Only 1 _sender definition inside the shared helper
        assert src.count("async def _sender()") == 1

    def test_file_line_count_reduced(self):
        src = (PROJECT_ROOT / "web/api/live_stream.py").read_text(encoding="utf-8")
        line_count = len(src.splitlines())
        assert line_count < 250, f"Expected <250 lines after DRY refactor, got {line_count}"


# ════════════════════════════════════════════════════════════════════
# S8-8: Venue Exposure Dashboard Card
# ════════════════════════════════════════════════════════════════════

class TestVenueExposureCard:
    """Verify VenueExposureCard is wired into OperatorDashboard."""

    def test_component_exists(self):
        src = (PROJECT_ROOT / "web/react/src/components/VenueExposureCard.tsx").read_text(encoding="utf-8")
        assert "VenueExposureCard" in src
        assert "GUARD_STATUS" in src
        assert "utilization_pct" in src

    def test_component_has_bar_visualization(self):
        src = (PROJECT_ROOT / "web/react/src/components/VenueExposureCard.tsx").read_text(encoding="utf-8")
        assert "barColor" in src
        assert "remaining" in src

    def test_operator_dashboard_imports_card(self):
        src = (PROJECT_ROOT / "web/react/src/views/OperatorDashboard.tsx").read_text(encoding="utf-8")
        assert "VenueExposureCard" in src
        assert "<VenueExposureCard" in src

    def test_guard_status_endpoint_constant(self):
        src = (PROJECT_ROOT / "web/react/src/config/constants.ts").read_text(encoding="utf-8")
        assert "GUARD_STATUS" in src
        assert "/api/v1/loop/guard/status" in src

    def test_component_uses_error_bar(self):
        src = (PROJECT_ROOT / "web/react/src/components/VenueExposureCard.tsx").read_text(encoding="utf-8")
        assert "ErrorBar" in src


# ════════════════════════════════════════════════════════════════════
# S8-5: Stage 0 Venue Adapter Wiring (Alpaca, Kalshi, Coinbase)
# ════════════════════════════════════════════════════════════════════

class TestStage0AdapterStructure:
    """Verify all 3 Stage 0 adapters have real API wiring, not mock data."""

    _ADAPTERS = {
        "alpaca": "core/venues/alpaca_adapter.py",
        "kalshi": "core/venues/kalshi_adapter.py",
        "coinbase": "core/venues/coinbase_advanced_adapter.py",
    }

    def test_adapters_still_stub(self):
        """All 3 adapters remain _is_stub = True until manual smoke run."""
        for name, path in self._ADAPTERS.items():
            src = (PROJECT_ROOT / path).read_text(encoding="utf-8")
            assert "_is_stub = True" in src, f"{name} should still be _is_stub = True"

    def test_alpaca_uses_sdk(self):
        src = (PROJECT_ROOT / self._ADAPTERS["alpaca"]).read_text(encoding="utf-8")
        assert "TradingClient" in src, "Alpaca must use alpaca-py TradingClient"
        assert "asyncio.to_thread" in src, "Alpaca SDK calls must be wrapped in to_thread"

    def test_kalshi_uses_httpx_jwt(self):
        src = (PROJECT_ROOT / self._ADAPTERS["kalshi"]).read_text(encoding="utf-8")
        assert "httpx" in src, "Kalshi must use httpx"
        assert "_build_jwt" in src, "Kalshi must use JWT auth"
        assert "RS256" in src, "Kalshi JWT must use RS256"

    def test_coinbase_uses_hmac(self):
        src = (PROJECT_ROOT / self._ADAPTERS["coinbase"]).read_text(encoding="utf-8")
        assert "httpx" in src, "Coinbase must use httpx"
        assert "hmac" in src, "Coinbase must use HMAC signing"
        assert "CB-ACCESS-SIGN" in src, "Coinbase must set CB-ACCESS-SIGN header"

    def test_all_have_has_credentials(self):
        for name, path in self._ADAPTERS.items():
            src = (PROJECT_ROOT / path).read_text(encoding="utf-8")
            assert "_has_credentials" in src, f"{name} must have _has_credentials property"

    def test_all_have_graceful_no_creds_connect(self):
        """connect() must return False (not crash) when no credentials are set."""
        for name, path in self._ADAPTERS.items():
            src = (PROJECT_ROOT / path).read_text(encoding="utf-8")
            assert "no_credentials" in src or "running in stub mode" in src, \
                f"{name} connect() must handle missing credentials gracefully"

    def test_no_hardcoded_mock_returns(self):
        """Adapters must not return hardcoded mock data in core methods."""
        mock_signals = [
            '"filled"',       # hardcoded filled status
            "Decimal(\"150",  # fake stock price
            "Decimal(\"0.55", # fake prediction price
            "Decimal(\"50050", # fake BTC price
        ]
        for name, path in self._ADAPTERS.items():
            src = (PROJECT_ROOT / path).read_text(encoding="utf-8")
            for signal in mock_signals:
                assert signal not in src, \
                    f"{name} still has hardcoded mock data: {signal}"

    def test_env_var_merid_prefix_supported(self):
        """Alpaca and Coinbase adapters must support MERID_ prefix env vars."""
        for name in ("alpaca", "coinbase"):
            src = (PROJECT_ROOT / self._ADAPTERS[name]).read_text(encoding="utf-8")
            assert "MERID_" in src, f"{name} must support MERID_ prefix env vars"

    def test_integration_tests_exist(self):
        """Each venue has an integration test file."""
        assert (PROJECT_ROOT / "tests/test_integration_alpaca_paper.py").exists()
        assert (PROJECT_ROOT / "tests/test_integration_kalshi.py").exists()
        assert (PROJECT_ROOT / "tests/test_integration_coinbase.py").exists()


# ════════════════════════════════════════════════════════════════════
# S8-6: Settings alignment for Stage 0 venues
# ════════════════════════════════════════════════════════════════════

class TestSettingsVenueAlignment:
    """Verify settings.py supports all 3 Stage 0 venues."""

    def test_merid_prefix_env_vars_in_settings(self):
        src = (PROJECT_ROOT / "merid/settings.py").read_text(encoding="utf-8")
        for var in ("MERID_ALPACA_API_KEY", "MERID_ALPACA_API_SECRET",
                     "MERID_COINBASE_API_KEY", "MERID_COINBASE_API_SECRET"):
            assert var in src, f"{var} must be in settings.py"

    def test_validate_venue_credentials_covers_all(self):
        src = (PROJECT_ROOT / "merid/settings.py").read_text(encoding="utf-8")
        for venue in ("kalshi", "alpaca", "coinbase_advanced"):
            assert venue in src, f"validate_venue_credentials must cover {venue}"

    def test_go_live_defaults_include_stage0_venues(self):
        src = (PROJECT_ROOT / "merid/settings.py").read_text(encoding="utf-8")
        assert '"kalshi"' in src
        assert '"alpaca"' in src
        assert '"coinbase_advanced"' in src


# ════════════════════════════════════════════════════════════════════
# Pre-Live Benchmark System
# ════════════════════════════════════════════════════════════════════

class TestBenchmarkModule:
    """Verify the benchmark system is properly wired."""

    def test_benchmark_module_exists(self):
        src = (PROJECT_ROOT / "merid/benchmarks.py").read_text(encoding="utf-8")
        assert "class BenchmarkCollector" in src
        assert "class BenchmarkTargets" in src
        assert "class BenchmarkResult" in src
        assert "class BenchmarkStatus" in src

    def test_benchmark_5_categories(self):
        src = (PROJECT_ROOT / "merid/benchmarks.py").read_text(encoding="utf-8")
        assert "_check_latency" in src
        assert "_check_data_quality" in src
        assert "_check_risk" in src
        assert "_check_alert_hygiene" in src
        assert "_check_swarm" in src

    def test_benchmark_targets_defined(self):
        from merid.benchmarks import TARGETS
        assert TARGETS.loop_cycle_max_ms > 0
        assert TARGETS.agent_p95_warn_ms > 0
        assert TARGETS.ws_channel_max_age_s > 0
        assert TARGETS.recon_max_age_s > 0
        assert TARGETS.venue_cap_warn_pct > 0
        assert TARGETS.max_firing_alerts == 0

    def test_benchmark_collector_returns_report(self):
        from merid.benchmarks import BenchmarkCollector
        collector = BenchmarkCollector()
        report = collector.collect_all()
        assert "overall" in report
        assert "summary" in report
        assert "benchmarks" in report
        assert "go_live_ready" in report
        assert isinstance(report["benchmarks"], list)
        assert report["summary"]["total"] > 0

    def test_benchmark_result_to_dict(self):
        from merid.benchmarks import BenchmarkResult, BenchmarkStatus
        r = BenchmarkResult(
            name="test", category="test_cat",
            status=BenchmarkStatus.PASS, value=42,
            target="≤100", detail="ok",
        )
        d = r.to_dict()
        assert d["name"] == "test"
        assert d["status"] == "pass"
        assert d["value"] == 42

    def test_benchmark_api_exists(self):
        src = (PROJECT_ROOT / "web/api/benchmarks_api.py").read_text(encoding="utf-8")
        assert "get_benchmark_report" in src
        assert "/report" in src
        assert "/targets" in src

    def test_benchmark_api_wired(self):
        src = (PROJECT_ROOT / "web/main.py").read_text(encoding="utf-8")
        assert "benchmarks_router" in src

    def test_benchmark_dashboard_card_exists(self):
        src = (PROJECT_ROOT / "web/react/src/components/BenchmarkCard.tsx").read_text(encoding="utf-8")
        assert "BenchmarkCard" in src
        assert "BENCHMARKS_REPORT" in src
        assert "go_live_ready" in src

    def test_benchmark_card_wired_into_dashboard(self):
        src = (PROJECT_ROOT / "web/react/src/views/OperatorDashboard.tsx").read_text(encoding="utf-8")
        assert "BenchmarkCard" in src
        assert "<BenchmarkCard" in src

    def test_benchmark_endpoint_constant(self):
        src = (PROJECT_ROOT / "web/react/src/config/constants.ts").read_text(encoding="utf-8")
        assert "BENCHMARKS_REPORT" in src
        assert "/api/v1/benchmarks/report" in src
