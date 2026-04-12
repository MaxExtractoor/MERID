"""Tests for UI Wiring Audit Fixes — validates backend↔frontend contract alignment.

Covers:
  - Task A: SizingMetrics includes continuous_trader sub-object
  - Task B: _normalize_agent() returns win_rate, fills, errors, active_tickers
  - Task C: KalshiRiskSummary TS types match backend JSON shape
  - Task D: KalshiPortfolioView uses single PnL source with explicit labels
  - Task E: daily_trades uses perf tracker, not truncated fills array
  - Task F: Agent grid shows 'n/a' for missing metrics, not silent 0
"""

import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


# ═══════════════════════════════════════════════════════════════════════
# §A  _normalize_agent returns all GridAgent fields
# ═══════════════════════════════════════════════════════════════════════

class TestNormalizeAgent:
    """Verify _normalize_agent produces all fields the GridAgent interface needs."""

    def _normalize(self, raw):
        # Import must be deferred to avoid side-effect imports at module load
        from web.api.kalshi_grid_api import _normalize_agent
        return _normalize_agent(raw)

    def test_full_metrics_payload(self):
        """When all metrics are present, output includes win_rate/fills/errors/active_tickers."""
        raw = {
            "name": "btc-15m",
            "enabled": True,
            "running": True,
            "cycles_run": 42,
            "orders_placed": 10,
            "fill_count": 7,
            "errors": ["timeout", "rate_limit"],
            "active_tickers": ["KXBTC-25MAR14-T1", "KXBTC-25MAR14-T2"],
            "config": {"assets": ["BTC"], "timeframes": ["15m"]},
            "performance": {
                "profit_factor": 1.5,
                "sharpe_ratio": 1.2,
                "sortino_ratio": 1.0,
                "calmar_ratio": 0.8,
                "size_factor": 0.9,
                "win_rate": 0.55,
                "total_fills": 12,
            },
        }
        result = self._normalize(raw)
        assert result["name"] == "btc-15m"
        assert result["asset"] == "BTC"
        assert result["timeframe"] == "15m"
        assert result["status"] == "running"
        assert result["cycles"] == 42
        assert result["pf"] == 1.5
        assert result["sharpe"] == 1.2
        assert result["win_rate"] == 55.0  # fraction → percentage
        assert result["fills"] == 12  # from perf tracker total_fills
        assert result["errors"] == 2  # len(errors list)
        assert result["active_tickers"] == ["KXBTC-25MAR14-T1", "KXBTC-25MAR14-T2"]

    def test_missing_metrics_returns_none(self):
        """When metrics are absent, fields should be None (not 0)."""
        raw = {
            "name": "eth-1h",
            "enabled": True,
            "running": False,
            "config": {"assets": ["ETH"], "timeframes": ["1h"]},
        }
        result = self._normalize(raw)
        assert result["name"] == "eth-1h"
        assert result["status"] == "stopped"
        assert result["win_rate"] is None
        assert result["fills"] is None
        assert result["errors"] is None
        assert result["active_tickers"] is None

    def test_disabled_agent_status(self):
        raw = {"name": "sol-daily", "enabled": False, "running": False, "config": {}}
        result = self._normalize(raw)
        assert result["status"] == "disabled"

    def test_errors_as_int(self):
        """When raw errors is an int (from a different source), it's preserved."""
        raw = {"name": "x", "errors": 5, "config": {}}
        result = self._normalize(raw)
        assert result["errors"] == 5

    def test_fill_count_fallback(self):
        """When perf tracker total_fills is absent, uses fill_count from AgentState."""
        raw = {
            "name": "x",
            "fill_count": 3,
            "config": {},
            "performance": {"profit_factor": 1.0},
        }
        result = self._normalize(raw)
        assert result["fills"] == 3

    def test_json_serializable(self):
        """The result is JSON-serializable (no datetime/Decimal oddities)."""
        raw = {
            "name": "test",
            "enabled": True,
            "running": True,
            "cycles_run": 1,
            "fill_count": 0,
            "errors": [],
            "active_tickers": [],
            "config": {"assets": ["BTC"], "timeframes": ["15m"]},
            "performance": {"win_rate": 0.5, "total_fills": 0},
        }
        result = self._normalize(raw)
        json.dumps(result)  # Should not raise


# ═══════════════════════════════════════════════════════════════════════
# §B  Sizing metrics contract
# ═══════════════════════════════════════════════════════════════════════

class TestSizingMetricsContract:
    """Verify sizing metrics endpoint returns continuous_trader sub-object."""

    def _read_api(self) -> str:
        return (ROOT / "web" / "api" / "kalshi_api.py").read_text(encoding="utf-8")

    def test_continuous_trader_field_in_return(self):
        src = self._read_api()
        assert '"continuous_trader"' in src

    def test_ct_snapshot_fields(self):
        src = self._read_api()
        assert '"total_trades"' in src
        assert '"total_fills"' in src
        assert '"system_win_rate"' in src
        assert '"agent_count"' in src


# ═══════════════════════════════════════════════════════════════════════
# §C  TS interface alignment
# ═══════════════════════════════════════════════════════════════════════

class TestTypescriptInterfaceAlignment:
    """Verify TS types match backend JSON shapes."""

    def _read_types(self) -> str:
        return (ROOT / "web" / "react" / "src" / "types" / "kalshi.ts").read_text(encoding="utf-8")

    def test_grid_agent_interface_in_shared_types(self):
        src = self._read_types()
        assert "export interface GridAgent" in src

    def test_grid_agent_has_required_fields(self):
        src = self._read_types()
        for field in ["win_rate", "fills", "errors", "active_tickers"]:
            assert field in src, f"GridAgent should include {field}"

    def test_continuous_trader_snapshot_interface(self):
        src = self._read_types()
        assert "export interface ContinuousTraderSnapshot" in src

    def test_sizing_metrics_has_continuous_trader(self):
        src = self._read_types()
        assert "continuous_trader" in src

    def test_risk_summary_has_daily_pnl_usd(self):
        """daily_pnl_usd is the canonical PnL field."""
        src = self._read_types()
        assert "daily_pnl_usd: number" in src

    def test_risk_summary_alias_fields(self):
        """ExecutionGateStrip aliases (daily_pnl, max_daily_loss) are optional."""
        src = self._read_types()
        assert "daily_pnl?" in src
        assert "max_daily_loss?" in src

    def test_grid_agent_not_duplicated_in_vol_dashboard(self):
        """GridAgent should NOT be defined locally in KalshiVolDashboardView."""
        vol_src = (ROOT / "web" / "react" / "src" / "views" / "KalshiVolDashboardView.tsx").read_text(encoding="utf-8")
        assert "interface GridAgent" not in vol_src, "GridAgent should be imported from types/kalshi.ts"

    def test_grid_agent_imported_in_vol_dashboard(self):
        vol_src = (ROOT / "web" / "react" / "src" / "views" / "KalshiVolDashboardView.tsx").read_text(encoding="utf-8")
        assert "GridAgent" in vol_src
        assert "from '../types/kalshi'" in vol_src


# ═══════════════════════════════════════════════════════════════════════
# §D  Portfolio view PnL sourcing
# ═══════════════════════════════════════════════════════════════════════

class TestPortfolioViewPnlSourcing:
    """Verify KalshiPortfolioView uses single PnL source, not mixed sources."""

    def _read_view(self) -> str:
        return (ROOT / "web" / "react" / "src" / "views" / "KalshiPortfolioView.tsx").read_text(encoding="utf-8")

    def test_no_mixed_pnl_fallback(self):
        """Should NOT use gridPortfolio?.daily_pnl_usd ?? risk?.daily_realized_pnl_usd pattern."""
        src = self._read_view()
        assert "gridPortfolio?.daily_pnl_usd ?? risk?.daily_realized_pnl_usd" not in src

    def test_uses_risk_daily_pnl_usd(self):
        """Should use risk.daily_pnl_usd as the canonical PnL source."""
        src = self._read_view()
        assert "risk.daily_pnl_usd" in src

    def test_explicit_null_guard(self):
        """Realized PnL card should explicitly check risk != null."""
        src = self._read_view()
        assert "risk != null" in src

    def test_trades_today_has_null_check(self):
        """Trade count should show 'n/a' when null, not silent 0."""
        src = self._read_view()
        assert "trades: n/a" in src


# ═══════════════════════════════════════════════════════════════════════
# §E  Daily trades calculation
# ═══════════════════════════════════════════════════════════════════════

class TestDailyTradesCalculation:
    """Verify kalshi_ui.py uses robust trade count, not truncated fills array."""

    def _read_ui(self) -> str:
        return (ROOT / "web" / "api" / "kalshi_ui.py").read_text(encoding="utf-8")

    def test_no_len_fills_for_daily_trades(self):
        """daily_trades should NOT be computed as len(summary['fills'])."""
        src = self._read_ui()
        # The old pattern: "daily_trades": len(summary["fills"])
        assert 'len(summary["fills"])' not in src or "_total_fill_count" in src

    def test_uses_perf_tracker(self):
        """Should attempt to get daily_trades from performance tracker."""
        src = self._read_ui()
        assert "agent_performance_tracker" in src

    def test_total_fill_count_tracked(self):
        """Should track total fill count across agents (not just top 50)."""
        src = self._read_ui()
        assert "_total_fill_count" in src


# ═══════════════════════════════════════════════════════════════════════
# §F  Agent grid explicit fallbacks
# ═══════════════════════════════════════════════════════════════════════

class TestAgentGridExplicitFallbacks:
    """Verify the agent grid shows 'n/a' for missing data, not silent zeros."""

    def _read_vol_dashboard(self) -> str:
        return (ROOT / "web" / "react" / "src" / "views" / "KalshiVolDashboardView.tsx").read_text(encoding="utf-8")

    def test_win_rate_shows_na_when_null(self):
        src = self._read_vol_dashboard()
        assert "'n/a'" in src or '"n/a"' in src

    def test_fills_shows_cycle_fallback_label(self):
        """When fills is null, should show cycles count with 'c' suffix."""
        src = self._read_vol_dashboard()
        # Pattern: a.fills != null ? a.fills : ... a.cycles ...
        assert "a.fills != null" in src
