"""Tests for core.execution_gate — unified execution gate and staleness config."""

import time
from datetime import datetime
from unittest.mock import patch, MagicMock
import pytest

from core.execution_gate import (
    check_execution_gate,
    check_price_feed_staleness,
    check_pnl_consistency,
    SymbolGroupConfig,
    set_staleness_config,
    get_staleness_config,
    _get_threshold_for_symbol,
    _update_blocked_state,
    BlockReason,
    ExecutionGateStatus,
    DEFAULT_STALENESS_THRESHOLD,
)

# Isolate gate tests from live dependency probes (SMTP, WS, catalog, etc.).
_EXEC_GATE_DEP_OK = {
    "dependencies": [],
    "any_critical_down": False,
    "healthy_count": 0,
    "degraded_count": 0,
    "down_count": 0,
    "total": 0,
    "timestamp": 0.0,
}


# ── ExecutionGateStatus tests ───────────────────────────────────────


class TestExecutionGateStatus:
    def test_to_dict_empty(self):
        status = ExecutionGateStatus(blocked=False, safe_to_trade=True)
        d = status.to_dict()
        assert d["blocked"] is False
        assert d["safe_to_trade"] is True
        assert d["reasons"] == []

    def test_to_dict_with_reasons(self):
        status = ExecutionGateStatus(
            blocked=True,
            safe_to_trade=False,
            reasons=[
                BlockReason(source="kill_switch", severity="critical", message="Kill switch engaged"),
                BlockReason(source="pnl_consistency", severity="warning", message="PnL diverges", details="$7.50"),
            ],
        )
        d = status.to_dict()
        assert d["blocked"] is True
        assert len(d["reasons"]) == 2
        assert d["reasons"][0]["source"] == "kill_switch"
        assert d["reasons"][1]["details"] == "$7.50"


# ── Staleness config tests ──────────────────────────────────────────


class TestStalenessConfig:
    def setup_method(self):
        # Reset to default config before each test
        set_staleness_config([
            SymbolGroupConfig(
                name="major_crypto",
                symbols={"BTC/USDT", "ETH/USDT", "SOL/USDT"},
                threshold_seconds=60,
                critical=True,
            ),
            SymbolGroupConfig(
                name="alt_crypto",
                symbols={"DOGE/USDT", "LINK/USDT"},
                threshold_seconds=120,
                critical=False,
            ),
        ])

    def test_get_threshold_major(self):
        threshold, critical, group = _get_threshold_for_symbol("BTC/USDT")
        assert threshold == 60
        assert critical is True
        assert group == "major_crypto"

    def test_get_threshold_alt(self):
        threshold, critical, group = _get_threshold_for_symbol("DOGE/USDT")
        assert threshold == 120
        assert critical is False
        assert group == "alt_crypto"

    def test_get_threshold_unknown_symbol(self):
        threshold, critical, group = _get_threshold_for_symbol("OBSCURE/USDT")
        assert threshold == DEFAULT_STALENESS_THRESHOLD
        assert critical is False
        assert group == "default"

    def test_set_staleness_config(self):
        custom = [
            SymbolGroupConfig(name="equities", symbols={"AAPL", "MSFT"}, threshold_seconds=30, critical=True),
        ]
        set_staleness_config(custom)
        cfg = get_staleness_config()
        assert len(cfg) == 1
        assert cfg[0].name == "equities"

        threshold, critical, group = _get_threshold_for_symbol("AAPL")
        assert threshold == 30
        assert critical is True

    def test_config_is_copy(self):
        """get_staleness_config returns a copy, not the internal list."""
        cfg = get_staleness_config()
        cfg.clear()
        assert len(get_staleness_config()) > 0


# ── Price feed staleness check tests ────────────────────────────────


class TestPriceFeedStaleness:
    def setup_method(self):
        set_staleness_config([
            SymbolGroupConfig(
                name="major",
                symbols={"BTC/USDT", "ETH/USDT"},
                threshold_seconds=60,
                critical=True,
            ),
            SymbolGroupConfig(
                name="alt",
                symbols={"DOGE/USDT"},
                threshold_seconds=120,
                critical=False,
            ),
        ])

    def _make_price_data(self, symbol: str, age_seconds: float):
        """Create a mock PriceData with a timestamp `age_seconds` in the past."""
        mock = MagicMock()
        mock.timestamp = datetime.fromtimestamp(time.time() - age_seconds)
        return mock

    @patch("data.live_price_feed.get_live_price_feed")
    def test_all_fresh_safe(self, mock_feed_fn):
        feed = MagicMock()
        feed.price_cache = {
            "BTC/USDT": self._make_price_data("BTC/USDT", 10),
            "ETH/USDT": self._make_price_data("ETH/USDT", 20),
            "DOGE/USDT": self._make_price_data("DOGE/USDT", 30),
        }
        mock_feed_fn.return_value = feed

        result = check_price_feed_staleness()
        assert result["safe_to_trade"] is True
        assert result["critical_count"] == 0
        assert result["total_checked"] == 3
        assert len(result["stale_symbols"]) == 0

    @patch("data.live_price_feed.get_live_price_feed")
    def test_major_stale_blocks(self, mock_feed_fn):
        feed = MagicMock()
        feed.price_cache = {
            "BTC/USDT": self._make_price_data("BTC/USDT", 90),  # 90s > 60s threshold
            "ETH/USDT": self._make_price_data("ETH/USDT", 10),
        }
        mock_feed_fn.return_value = feed

        result = check_price_feed_staleness()
        assert result["safe_to_trade"] is False
        assert result["critical_count"] == 1
        assert result["stale_symbols"][0]["symbol"] == "BTC/USDT"
        assert result["stale_symbols"][0]["critical"] is True

    @patch("data.live_price_feed.get_live_price_feed")
    def test_alt_stale_does_not_block(self, mock_feed_fn):
        feed = MagicMock()
        feed.price_cache = {
            "BTC/USDT": self._make_price_data("BTC/USDT", 10),
            "DOGE/USDT": self._make_price_data("DOGE/USDT", 200),  # 200s > 120s
        }
        mock_feed_fn.return_value = feed

        result = check_price_feed_staleness()
        assert result["safe_to_trade"] is True  # alt stale is not critical
        assert result["critical_count"] == 0
        assert len(result["stale_symbols"]) == 1
        assert result["stale_symbols"][0]["critical"] is False

    @patch("data.live_price_feed.get_live_price_feed")
    def test_empty_cache_is_safe(self, mock_feed_fn):
        feed = MagicMock()
        feed.price_cache = {}
        mock_feed_fn.return_value = feed

        result = check_price_feed_staleness()
        assert result["safe_to_trade"] is True
        assert result["total_checked"] == 0

    @patch("data.live_price_feed.get_live_price_feed")
    def test_groups_in_response(self, mock_feed_fn):
        feed = MagicMock()
        feed.price_cache = {}
        mock_feed_fn.return_value = feed

        result = check_price_feed_staleness()
        assert len(result["groups"]) == 2
        assert result["groups"][0]["name"] == "major"
        assert result["groups"][0]["critical"] is True


# ── Execution gate integration tests ────────────────────────────────


class TestCheckExecutionGate:
    def setup_method(self):
        _update_blocked_state(True)  # reset

    @pytest.mark.p0_live_blocker
    @pytest.mark.kalshi_live_ready
    @patch("core.dependency_health.check_all_dependencies", return_value=_EXEC_GATE_DEP_OK)
    @patch("core.execution_gate.check_pnl_consistency", return_value={"consistent": True, "max_divergence_usd": 0, "threshold_usd": 5})
    @patch("core.execution_gate.check_price_feed_staleness", return_value={"safe_to_trade": True, "stale_symbols": [], "critical_count": 0})
    def test_gate_open_when_all_clear(self, mock_stale, mock_pnl, _mock_deps):
        # Mask live-only env flags so RTI/WS/exchange checks don't fire
        env_overrides = {
            "KALSHI_ENV": "",
            "MERID_ALLOW_LIVE_TRADES": "0",
            "MERID_PM_TRADING_MODE": "paper",
            "MERID_PM_LIVE_ENABLED": "false",
            "KALSHI_USE_DEMO": "true",
            "MERID_EXEC_GATE_REQUIRE_KALSHI_WS": "0",
            "MERID_EXEC_GATE_RTI_FEED_UP": "0",
        }
        # Mock kill switch as not triggered
        mock_rc = MagicMock()
        mock_rc._global_kill = False
        mock_kalshi_recon = MagicMock()
        mock_kalshi_recon.has_critical_discrepancies = MagicMock(return_value=False)
        with patch.dict("os.environ", env_overrides, clear=False):
            with patch.dict("sys.modules", {"merid.risk.kill_switches": MagicMock(risk_controller=mock_rc),
                                            "merid.reconciliation": mock_kalshi_recon}):
                # Mock reconciliation as OK
                mock_recon = MagicMock()
                mock_recon.has_critical_discrepancies = MagicMock(return_value=False)
                mock_recon._has_ever_completed = True
                with patch.dict("sys.modules", {"trading.reconciliation": mock_recon}):
                    result = check_execution_gate()

        assert result.blocked is False
        assert result.safe_to_trade is True
        # Only warn-level reasons (like reconciliation first-run) are acceptable
        critical = [r for r in result.reasons if r.severity == "critical"]
        assert len(critical) == 0, f"Unexpected critical reasons: {critical}"

    @pytest.mark.p0_live_blocker
    @pytest.mark.kalshi_live_ready
    @patch("core.dependency_health.check_all_dependencies", return_value=_EXEC_GATE_DEP_OK)
    @patch("core.execution_gate.check_pnl_consistency", return_value={"consistent": True, "max_divergence_usd": 0, "threshold_usd": 5})
    @patch("core.execution_gate.check_price_feed_staleness", return_value={"safe_to_trade": False, "stale_symbols": [{"symbol": "BTC/USDT"}], "critical_count": 1})
    def test_gate_blocked_on_stale_feeds(self, mock_stale, mock_pnl, _mock_deps):
        mock_rc = MagicMock()
        mock_rc._global_kill = False
        mock_kalshi_recon = MagicMock()
        mock_kalshi_recon.has_critical_discrepancies = MagicMock(return_value=False)
        # Unset MERID_PROFILE so we're not in kalshi-only mode (which skips price feed checks)
        with patch.dict("os.environ", {"MERID_PROFILE": "", "EXECUTION_MODE": ""}, clear=False):
            with patch.dict("sys.modules", {"merid.risk.kill_switches": MagicMock(risk_controller=mock_rc),
                                            "merid.reconciliation": mock_kalshi_recon}):
                mock_recon = MagicMock()
                mock_recon.has_critical_discrepancies = MagicMock(return_value=False)
                mock_recon._has_ever_completed = True
                with patch.dict("sys.modules", {"trading.reconciliation": mock_recon}):
                    result = check_execution_gate()

        assert result.blocked is True
        feed_reasons = [r for r in result.reasons if r.source == "price_feed"]
        assert len(feed_reasons) == 1
        assert "stale" in feed_reasons[0].message.lower()

    @pytest.mark.p0_live_blocker
    @pytest.mark.kalshi_live_ready
    @patch("core.dependency_health.check_all_dependencies", return_value=_EXEC_GATE_DEP_OK)
    @patch("core.execution_gate.check_pnl_consistency", return_value={"consistent": True, "max_divergence_usd": 0, "threshold_usd": 5})
    @patch("core.execution_gate.check_price_feed_staleness", return_value={"safe_to_trade": True, "stale_symbols": [], "critical_count": 0})
    def test_gate_blocked_on_kill_switch(self, mock_stale, mock_pnl, _mock_deps):
        mock_rc = MagicMock()
        mock_rc._global_kill = True
        mock_rc._kill_details = "Manual stop"
        mock_rc._kill_reason = "manual"
        mock_kalshi_recon = MagicMock()
        mock_kalshi_recon.has_critical_discrepancies = MagicMock(return_value=False)
        with patch.dict("sys.modules", {"merid.risk.kill_switches": MagicMock(risk_controller=mock_rc),
                                        "merid.reconciliation": mock_kalshi_recon}):
            mock_recon = MagicMock()
            mock_recon.has_critical_discrepancies = MagicMock(return_value=False)
            mock_recon._has_ever_completed = True
            with patch.dict("sys.modules", {"trading.reconciliation": mock_recon}):
                result = check_execution_gate()

        assert result.blocked is True
        kill_reasons = [r for r in result.reasons if r.source == "kill_switch"]
        assert len(kill_reasons) == 1
        assert "kill switch" in kill_reasons[0].message.lower()

    @patch("core.dependency_health.check_all_dependencies", return_value=_EXEC_GATE_DEP_OK)
    @patch("core.execution_gate.check_pnl_consistency", return_value={"consistent": False, "max_divergence_usd": 12.5, "threshold_usd": 5})
    @patch("core.execution_gate.check_price_feed_staleness", return_value={"safe_to_trade": True, "stale_symbols": [], "critical_count": 0})
    def test_pnl_divergence_is_warning_not_block(self, mock_stale, mock_pnl, _mock_deps):
        """PnL divergence is severity=warning, so gate should NOT be blocked (only critical blocks)."""
        env_overrides = {
            "KALSHI_ENV": "",
            "MERID_PM_TRADING_MODE": "paper",
            "MERID_PM_LIVE_ENABLED": "false",
            "KALSHI_USE_DEMO": "true",
            "MERID_EXEC_GATE_REQUIRE_KALSHI_WS": "0",
            "MERID_EXEC_GATE_RTI_FEED_UP": "0",
        }
        mock_rc = MagicMock()
        mock_rc._global_kill = False
        mock_kalshi_recon = MagicMock()
        mock_kalshi_recon.has_critical_discrepancies = MagicMock(return_value=False)
        with patch.dict("os.environ", env_overrides, clear=False):
            with patch.dict("sys.modules", {"merid.risk.kill_switches": MagicMock(risk_controller=mock_rc),
                                            "merid.reconciliation": mock_kalshi_recon}):
                mock_recon = MagicMock()
                mock_recon.has_critical_discrepancies = MagicMock(return_value=False)
                mock_recon._has_ever_completed = True
                with patch.dict("sys.modules", {"trading.reconciliation": mock_recon}):
                    result = check_execution_gate()

        assert result.blocked is False  # warning-only doesn't block
        pnl_reasons = [r for r in result.reasons if r.source == "pnl_consistency"]
        assert len(pnl_reasons) == 1
        assert pnl_reasons[0].severity == "warning"


def test_execution_gate_module_import_does_not_raise():
    """P-C3: globals must exist at module load so first check_execution_gate() call
    does not raise NameError on _ws_stale_count/_ws_healthy_count/_ws_was_stale."""
    import importlib
    import core.execution_gate as eg
    importlib.reload(eg)  # forces fresh module load
    # Access the globals directly — they must exist
    assert hasattr(eg, "_ws_stale_count"), "_ws_stale_count not defined at module level"
    assert hasattr(eg, "_ws_healthy_count"), "_ws_healthy_count not defined at module level"
    assert hasattr(eg, "_ws_was_stale"), "_ws_was_stale not defined at module level"
    assert isinstance(eg._ws_stale_count, int)
    assert isinstance(eg._ws_healthy_count, int)
    assert isinstance(eg._ws_was_stale, bool)


def test_execution_guard_and_risk_controller_use_same_kill_file():
    """P-H1: both modules must read/write the same kill-switch file path
    when MERID_RISK_KS_FILE env var is not set."""
    import os
    import merid.risk.kill_switches as ks_mod
    import merid.execution_guard as eg_mod

    # Remove env override to test default behavior
    env_backup = os.environ.pop("MERID_RISK_KS_FILE", None)
    try:
        ks_path = str(ks_mod._get_kill_switch_path())
        eg_path = eg_mod._get_risk_kill_switch_path()
        assert ks_path == eg_path, (
            f"Kill switch path mismatch:\n"
            f"  kill_switches uses: {ks_path!r}\n"
            f"  execution_guard uses: {eg_path!r}"
        )
    finally:
        if env_backup is not None:
            os.environ["MERID_RISK_KS_FILE"] = env_backup
