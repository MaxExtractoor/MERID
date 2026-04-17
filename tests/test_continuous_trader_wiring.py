"""Regression tests for Kalshi Continuous Trader UI/UX wiring.

Tests cover:
  1. BankrollManager: cycle_history ring buffer, record_cycle_snapshot()
  2. status_snapshot(): all expected keys present, cycle_history included
  3. API module: router exists, endpoints defined, run_in_executor usage
  4. Frontend constants: CONTINUOUS_TRADER_STATUS / STOP exist
  5. Frontend component: KalshiBankrollPanel exists, imports Sparkline
  6. View wiring: BankrollPanel imported in all 5 target views
  7. sidebar_config.py: continuous-trader endpoint registered on correct views
  8. SizingMetrics type: continuous_trader field present
  9. /sizing-metrics endpoint: continuous_trader merge block exists
 10. Standalone script parity: record_cycle_snapshot + _cycle_history
"""

import ast
import os
import re
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _read(relpath: str) -> str:
    p = Path(PROJECT_ROOT) / relpath
    return p.read_text(encoding="utf-8") if p.exists() else ""


# ═══════════════════════════════════════════════════════════════════════════
# 1. BankrollManager unit tests
# ═══════════════════════════════════════════════════════════════════════════

class TestBankrollManagerCycleHistory(unittest.TestCase):
    """Test the cycle history ring buffer and record_cycle_snapshot."""

    @classmethod
    def setUpClass(cls):
        from merid.trading.kalshi_continuous_trader import BankrollManager, TraderConfig
        cls.BankrollManager = BankrollManager
        cls.TraderConfig = TraderConfig

    def _make_bm(self, **overrides):
        cfg = self.TraderConfig(**overrides)
        return self.BankrollManager(cfg)

    def test_cycle_history_deque_exists(self):
        bm = self._make_bm()
        self.assertTrue(hasattr(bm, "_cycle_history"))
        self.assertEqual(bm._cycle_history.maxlen, 60)

    def test_cycle_history_starts_empty(self):
        bm = self._make_bm()
        self.assertEqual(len(bm._cycle_history), 0)

    def test_record_cycle_snapshot_appends(self):
        bm = self._make_bm()
        bm.record_cycle_snapshot(1000)
        self.assertEqual(len(bm._cycle_history), 1)
        bm.record_cycle_snapshot(1050)
        self.assertEqual(len(bm._cycle_history), 2)

    def test_record_cycle_snapshot_keys(self):
        bm = self._make_bm()
        bm.record_cycle_snapshot(1000)
        snap = bm._cycle_history[0]
        expected_keys = {"cycle", "drawdown_pct", "fee_drag_pct", "pnl_cents", "balance_cents", "vol_pct"}
        self.assertEqual(set(snap.keys()), expected_keys)

    def test_record_cycle_snapshot_values(self):
        bm = self._make_bm(initial_bankroll_cents=1000)
        bm.update_peak(1000)
        bm.record_cycle_snapshot(900)
        snap = bm._cycle_history[0]
        self.assertEqual(snap["balance_cents"], 900)
        self.assertGreater(snap["drawdown_pct"], 0)
        self.assertIsInstance(snap["fee_drag_pct"], float)
        self.assertIsInstance(snap["vol_pct"], float)

    def test_cycle_history_maxlen_respected(self):
        bm = self._make_bm()
        for i in range(100):
            bm.record_cycle_snapshot(1000 + i)
        self.assertEqual(len(bm._cycle_history), 60)
        # First entry should be from cycle 40 (100 - 60)
        self.assertEqual(bm._cycle_history[0]["balance_cents"], 1040)

    def test_advance_cycle_increments_cycle_in_snapshot(self):
        bm = self._make_bm()
        bm.advance_cycle()
        bm.advance_cycle()
        bm.record_cycle_snapshot(1000)
        self.assertEqual(bm._cycle_history[0]["cycle"], 2)


# ═══════════════════════════════════════════════════════════════════════════
# 2. status_snapshot() tests
# ═══════════════════════════════════════════════════════════════════════════

class TestStatusSnapshot(unittest.TestCase):
    """Test that status_snapshot returns all expected keys."""

    def test_status_snapshot_method_exists(self):
        src = _read("merid/trading/kalshi_continuous_trader.py")
        self.assertIn("def status_snapshot(self)", src)

    def test_status_snapshot_has_cycle_history(self):
        src = _read("merid/trading/kalshi_continuous_trader.py")
        self.assertIn('"cycle_history"', src)
        self.assertIn("list(bm._cycle_history)", src)

    def test_status_snapshot_expected_keys(self):
        """Verify the snapshot dict includes all critical keys."""
        src = _read("merid/trading/kalshi_continuous_trader.py")
        required_keys = [
            "running", "cycle", "dry_run", "interval_seconds",
            "balance_cents", "portfolio_cents", "total_value_cents",
            "peak_balance_cents", "drawdown_pct", "halted", "halt_reason",
            "total_trades", "total_wins", "total_losses", "win_rate_pct",
            "total_pnl_cents", "total_fees_cents",
            "fee_drag_pct", "fee_drag_tightening", "fee_drag_window",
            "vol_band", "annualized_vol_pct",
            "eff_max_orders_per_cycle", "eff_max_exposure_pct",
            "config", "orders_placed", "orders_filled", "orders_cancelled",
            "resting_orders", "cycle_history",
            "active_assets", "asset_series_map",
        ]
        for key in required_keys:
            self.assertIn(f'"{key}"', src, f"status_snapshot missing key: {key}")


# ═══════════════════════════════════════════════════════════════════════════
# 3. API module tests
# ═══════════════════════════════════════════════════════════════════════════

class TestContinuousTraderApi(unittest.TestCase):
    """Test the API module structure."""

    def test_api_file_exists(self):
        self.assertTrue(
            Path(PROJECT_ROOT, "web/api/kalshi_continuous_trader_api.py").exists()
        )

    def test_api_has_status_endpoint(self):
        src = _read("web/api/kalshi_continuous_trader_api.py")
        self.assertIn('@router.get("/status")', src)

    def test_api_has_stop_endpoint(self):
        src = _read("web/api/kalshi_continuous_trader_api.py")
        self.assertIn('@router.post("/stop")', src)

    def test_api_uses_run_in_executor(self):
        """status_snapshot() is blocking — must be wrapped in executor."""
        src = _read("web/api/kalshi_continuous_trader_api.py")
        self.assertIn("run_in_executor", src)
        self.assertIn("import asyncio", src)

    def test_api_has_correct_prefix(self):
        src = _read("web/api/kalshi_continuous_trader_api.py")
        self.assertIn('prefix="/api/v1/kalshi/continuous-trader"', src)

    def test_api_wired_in_main(self):
        src = _read("web/main.py")
        self.assertIn("kalshi_continuous_trader", src)


# ═══════════════════════════════════════════════════════════════════════════
# 4. Frontend constants tests
# ═══════════════════════════════════════════════════════════════════════════

class TestFrontendConstants(unittest.TestCase):
    """Test that the frontend constants are defined."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read("web/react/src/config/constants.ts")

    def test_status_constant(self):
        self.assertIn("KALSHI_CONTINUOUS_TRADER_STATUS", self.src)
        self.assertIn("/api/v1/kalshi/continuous-trader/status", self.src)

    def test_stop_constant(self):
        self.assertIn("KALSHI_CONTINUOUS_TRADER_STOP", self.src)
        self.assertIn("/api/v1/kalshi/continuous-trader/stop", self.src)


# ═══════════════════════════════════════════════════════════════════════════
# 5. KalshiBankrollPanel component tests
# ═══════════════════════════════════════════════════════════════════════════

class TestBankrollPanelComponent(unittest.TestCase):
    """Test the BankrollPanel component structure."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read("web/react/src/components/KalshiBankrollPanel.tsx")

    def test_file_exists(self):
        self.assertTrue(
            Path(PROJECT_ROOT, "web/react/src/components/KalshiBankrollPanel.tsx").exists()
        )

    def test_exports_default(self):
        self.assertIn("export default function KalshiBankrollPanel", self.src)

    def test_has_sparkline_component(self):
        self.assertIn("function Sparkline(", self.src)

    def test_sparkline_has_threshold_lines(self):
        self.assertIn("warnThreshold", self.src)
        self.assertIn("dangerThreshold", self.src)

    def test_sparkline_has_trend_indicator(self):
        self.assertRegex(self.src, r"trend.*[▲▼─]|[▲▼─].*trend")

    def test_uses_status_api(self):
        self.assertIn("KALSHI_CONTINUOUS_TRADER_STATUS", self.src)

    def test_uses_stop_api(self):
        self.assertIn("KALSHI_CONTINUOUS_TRADER_STOP", self.src)

    def test_has_cycle_history_type(self):
        self.assertIn("cycle_history:", self.src)

    def test_stat_accepts_sparkline_prop(self):
        self.assertIn("sparkline?:", self.src)

    def test_drawdown_sparkline_wired(self):
        self.assertIn("h.drawdown_pct", self.src)

    def test_fee_drag_sparkline_wired(self):
        self.assertIn("h.fee_drag_pct", self.src)


# ═══════════════════════════════════════════════════════════════════════════
# 6. View wiring tests — BankrollPanel in all 5 views
# ═══════════════════════════════════════════════════════════════════════════

class TestViewWiring(unittest.TestCase):
    """BankrollPanel must be imported and rendered in all target views."""

    VIEWS = {
        "KalshiTerminalView": "web/react/src/views/KalshiTerminalView.tsx",
        "KalshiPortfolioView": "web/react/src/views/KalshiPortfolioView.tsx",
        "KalshiRiskScreen": "web/react/src/views/KalshiRiskScreen.tsx",
        "KalshiVolDashboardView": "web/react/src/views/KalshiVolDashboardView.tsx",
        "KalshiGridView": "web/react/src/views/KalshiGridView.tsx",
    }

    def test_bankroll_panel_imported(self):
        for view_name, path in self.VIEWS.items():
            src = _read(path)
            self.assertIn(
                "import KalshiBankrollPanel from",
                src,
                f"KalshiBankrollPanel not imported in {view_name}",
            )

    def test_bankroll_panel_rendered(self):
        for view_name, path in self.VIEWS.items():
            src = _read(path)
            self.assertIn(
                "<KalshiBankrollPanel",
                src,
                f"<KalshiBankrollPanel /> not rendered in {view_name}",
            )


# ═══════════════════════════════════════════════════════════════════════════
# 7. sidebar_config.py tests
# ═══════════════════════════════════════════════════════════════════════════

class TestSidebarConfig(unittest.TestCase):
    """Verify continuous trader endpoint registered in sidebar config."""

    @classmethod
    def setUpClass(cls):
        from web.api.sidebar_config import SIDEBAR_SECTIONS
        cls.sections = SIDEBAR_SECTIONS
        cls.items = []
        for sec in SIDEBAR_SECTIONS:
            cls.items.extend(sec.get("items", []))

    def _endpoints_for(self, item_id: str):
        for item in self.items:
            if item["id"] == item_id:
                return item.get("endpoints", [])
        return []

    def test_terminal_has_continuous_trader_endpoint(self):
        eps = self._endpoints_for("kalshi-terminal")
        self.assertIn("/api/v1/kalshi/continuous-trader/status", eps)

    def test_portfolio_has_continuous_trader_endpoint(self):
        eps = self._endpoints_for("kalshi-portfolio")
        self.assertIn("/api/v1/kalshi/continuous-trader/status", eps)

    def test_grid_has_continuous_trader_endpoint(self):
        eps = self._endpoints_for("kalshi-grid")
        self.assertIn("/api/v1/kalshi/continuous-trader/status", eps)

    def test_vol_dashboard_has_continuous_trader_endpoint(self):
        eps = self._endpoints_for("kalshi-vol-dashboard")
        self.assertIn("/api/v1/kalshi/continuous-trader/status", eps)

    def test_kalshi_risk_entry_exists(self):
        ids = {item["id"] for item in self.items}
        self.assertIn("kalshi-risk", ids)

    def test_kalshi_risk_has_continuous_trader_endpoint(self):
        eps = self._endpoints_for("kalshi-risk")
        self.assertIn("/api/v1/kalshi/continuous-trader/status", eps)


# ═══════════════════════════════════════════════════════════════════════════
# 8. SizingMetrics TypeScript type
# ═══════════════════════════════════════════════════════════════════════════

class TestSizingMetricsType(unittest.TestCase):
    """SizingMetrics TS type must include continuous_trader field."""

    def test_continuous_trader_field_in_type(self):
        src = _read("web/react/src/types/kalshi.ts")
        self.assertIn("continuous_trader?:", src)

    def test_continuous_trader_field_has_vol_band(self):
        src = _read("web/react/src/types/kalshi.ts")
        self.assertIn("vol_band: string", src)

    def test_continuous_trader_field_has_fee_drag(self):
        src = _read("web/react/src/types/kalshi.ts")
        self.assertIn("fee_drag_pct: number", src)


# ═══════════════════════════════════════════════════════════════════════════
# 9. /sizing-metrics endpoint merge
# ═══════════════════════════════════════════════════════════════════════════

class TestSizingMetricsEndpointMerge(unittest.TestCase):
    """The sizing-metrics endpoint must merge continuous trader state."""

    def test_sizing_metrics_imports_continuous_trader(self):
        src = _read("web/api/kalshi_api.py")
        self.assertIn("from merid.trading.kalshi_continuous_trader import get_continuous_trader", src)

    def test_sizing_metrics_has_continuous_trader_key(self):
        src = _read("web/api/kalshi_api.py")
        self.assertIn('result["continuous_trader"]', src)


# ═══════════════════════════════════════════════════════════════════════════
# 10. Standalone script parity
# ═══════════════════════════════════════════════════════════════════════════

class TestStandaloneScriptParity(unittest.TestCase):
    """Standalone script should have the same cycle history features."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read("scripts/kalshi_continuous_trader.py")

    def test_has_cycle_history_deque(self):
        self.assertIn("_cycle_history", self.src)
        self.assertIn("maxlen=60", self.src)

    def test_has_record_cycle_snapshot(self):
        self.assertIn("def record_cycle_snapshot(self", self.src)

    def test_record_cycle_snapshot_called_in_run_cycle(self):
        self.assertIn("bankroll.record_cycle_snapshot(", self.src)

    def test_record_cycle_snapshot_keys_match(self):
        """Same keys in standalone as in async module."""
        for key in ["drawdown_pct", "fee_drag_pct", "pnl_cents", "balance_cents", "vol_pct"]:
            self.assertIn(f'"{key}"', self.src, f"Standalone script missing key: {key}")


if __name__ == "__main__":
    unittest.main()
