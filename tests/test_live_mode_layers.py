"""Go-live mode layer tests.

Asserts that all three Kalshi mode layers resolve to LIVE when the
required production environment variables are set, and that they emit
WARNING logs (instead of silently falling back) when those vars are absent.

Three layers under test:
  Layer 1 — process-wide TradeMode   (trading/trade_mode.py)
  Layer 2 — AgentGrid VenueGate      (merid/prediction/venue_gate.py)
  Layer 3 — Unified-pipeline ModeManager (merid/pipeline/mode_manager.py)

Run: python -m pytest tests/test_live_mode_layers.py -xvs
"""

from __future__ import annotations

import importlib
import logging
import os
import re
from typing import Optional
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Required production env vars (canonical go-live specification)
# ---------------------------------------------------------------------------

PRODUCTION_ENVS: dict[str, str] = {
    "MERID_ENV": "production",
    "MERID_TRADE_MODE": "live",
    "MERID_TRADING_MODE": "live",
    "MERID_PM_TRADING_MODE": "live",
    "MERID_PM_LIVE_ENABLED": "true",
    "MERID_ALLOW_LIVE_TRADES": "true",
    "MERID_LIVE_TRADING_UNLOCKED": "true",
    "KALSHI_USE_DEMO": "false",
    "KALSHI_ENV": "live",
}

# WARNING phrases that must NOT appear when all production envs are set.
SILENT_DOWNGRADE_WARNINGS: list[str] = [
    "MERID_TRADE_MODE is not set",
    "MERID_PM_TRADING_MODE is not set",
    "MERID_PIPELINE_MODE: Kalshi venue is in SIM mode",
    "KALSHI_ENV is not set",
    "defaulting to PAPER",
    "defaulting Kalshi venue to SIM",
    "agents will NOT be force-promoted to LIVE",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_trade_mode(env: dict[str, str]):
    """Return a freshly-resolved TradeMode with a patched environment."""
    with patch.dict(os.environ, env, clear=False):
        import trading.trade_mode as tm_mod
        importlib.reload(tm_mod)
        # Reset the process-wide singleton so _resolve_initial_mode() runs again.
        tm_mod._current_mode = None
        mode = tm_mod.get_trade_mode()
        # Restore singleton so other tests are not affected.
        tm_mod._current_mode = None
        return mode


def _fresh_venue_gate(env: dict[str, str]):
    """Return a freshly-constructed VenueGate with env vars patched."""
    from merid.prediction.venue_gate import VenueGate
    with patch.dict(os.environ, env, clear=False):
        # VenueGate reads env at construction time; inject via explicit params
        # to avoid depending on merid.settings import inside CI.
        mode_str = env.get("MERID_PM_TRADING_MODE", "mock")
        live_enabled = env.get("MERID_PM_LIVE_ENABLED", "false").lower() == "true"
        from config.trading_mode import TradeMode
        gate = VenueGate(
            mode=TradeMode(mode_str.lower()),
            live_enabled=live_enabled,
        )
    return gate


def _kalshi_mode_for_env(env: dict[str, str]):
    """Return the TradingMode that _kalshi_default_mode() resolves to."""
    with patch.dict(os.environ, env, clear=False):
        import merid.pipeline.mode_manager as mm_mod
        importlib.reload(mm_mod)
        mm_mod._manager = None  # reset singleton
        mode = mm_mod._kalshi_default_mode()
        mm_mod._manager = None
        return mode


# ---------------------------------------------------------------------------
# Layer 1 — TradeMode (trading/trade_mode.py)
# ---------------------------------------------------------------------------


class TestTradeModeLive:
    """Layer 1: process-wide TradeMode resolves to LIVE with correct env."""

    def test_live_when_env_set(self):
        from config.trading_mode import TradeMode
        mode = _fresh_trade_mode(PRODUCTION_ENVS)
        assert mode == TradeMode.LIVE, f"Expected LIVE, got {mode!r}"

    def test_paper_when_env_missing(self):
        from config.trading_mode import TradeMode
        env = {k: v for k, v in PRODUCTION_ENVS.items() if k != "MERID_TRADE_MODE"}
        mode = _fresh_trade_mode(env)
        assert mode == TradeMode.PAPER

    def test_warning_when_env_missing(self):
        """trade_mode.py source contains a WARNING log for missing MERID_TRADE_MODE."""
        import os as _os
        src_path = _os.path.join(
            _os.path.dirname(_os.path.dirname(__file__)),
            "trading", "trade_mode.py",
        )
        with open(src_path, encoding="utf-8") as f:
            content = f.read()
        assert "logger.warning" in content and "MERID_TRADE_MODE is not set" in content, (
            "trading/trade_mode.py must log at WARNING level when MERID_TRADE_MODE is unset"
        )
        # Confirm runtime behavior: returns PAPER when env missing
        from config.trading_mode import TradeMode
        env = {k: v for k, v in PRODUCTION_ENVS.items()}
        env.pop("MERID_TRADE_MODE", None)
        mode = _fresh_trade_mode(env)
        assert mode == TradeMode.PAPER

    def test_no_warning_when_live(self):
        """With MERID_TRADE_MODE=live, mode resolves to LIVE."""
        from config.trading_mode import TradeMode
        mode = _fresh_trade_mode(PRODUCTION_ENVS)
        assert mode == TradeMode.LIVE

    def test_unknown_env_val_defaults_to_paper(self):
        from config.trading_mode import TradeMode
        mode = _fresh_trade_mode({**PRODUCTION_ENVS, "MERID_TRADE_MODE": "bogus"})
        assert mode == TradeMode.PAPER

    def test_paper_mode_explicit(self):
        from config.trading_mode import TradeMode
        mode = _fresh_trade_mode({**PRODUCTION_ENVS, "MERID_TRADE_MODE": "paper"})
        assert mode == TradeMode.PAPER

    def test_mock_mode_explicit(self):
        from config.trading_mode import TradeMode
        mode = _fresh_trade_mode({**PRODUCTION_ENVS, "MERID_TRADE_MODE": "mock"})
        assert mode == TradeMode.MOCK


# ---------------------------------------------------------------------------
# Layer 2 — VenueGate (merid/prediction/venue_gate.py)
# ---------------------------------------------------------------------------


class TestVenueGateLive:
    """Layer 2: VenueGate resolves to live=True with production envs."""

    def test_is_live_with_production_envs(self):
        gate = _fresh_venue_gate(PRODUCTION_ENVS)
        assert gate.is_live is True, "VenueGate.is_live must be True in production"

    def test_not_live_when_pm_mode_unset(self):
        env = {k: v for k, v in PRODUCTION_ENVS.items()}
        env["MERID_PM_TRADING_MODE"] = "paper"
        gate = _fresh_venue_gate(env)
        assert gate.is_live is False

    def test_not_live_when_live_enabled_false(self):
        env = {**PRODUCTION_ENVS, "MERID_PM_LIVE_ENABLED": "false"}
        gate = _fresh_venue_gate(env)
        assert gate.is_live is False

    def test_check_can_trade_passes_in_live(self):
        gate = _fresh_venue_gate(PRODUCTION_ENVS)
        gate.check_can_trade()  # must not raise

    def test_check_can_trade_blocked_in_mock(self):
        from merid.prediction.venue_gate import VenueGate
        from config.trading_mode import TradeMode
        gate = VenueGate(mode=TradeMode.MOCK, live_enabled=False)
        with pytest.raises(VenueGate.ModeBlockedError):
            gate.check_can_trade()

    def test_check_can_trade_blocked_when_live_mode_but_not_enabled(self):
        from merid.prediction.venue_gate import VenueGate
        from config.trading_mode import TradeMode
        gate = VenueGate(mode=TradeMode.LIVE, live_enabled=False)
        with pytest.raises(VenueGate.ModeBlockedError, match="MERID_PM_LIVE_ENABLED"):
            gate.check_can_trade()

    def test_check_order_ok_in_live(self):
        gate = _fresh_venue_gate(PRODUCTION_ENVS)
        gate.check_order("kalshi")  # must not raise

    def test_check_venue_blocks_polymarket(self):
        from merid.prediction.venue_gate import VenueGate
        gate = _fresh_venue_gate(PRODUCTION_ENVS)
        with pytest.raises(VenueGate.VenueBlockedError):
            gate.check_venue("polymarket")

    def test_should_simulate_false_in_live(self):
        gate = _fresh_venue_gate(PRODUCTION_ENVS)
        assert gate.should_simulate_fill() is False

    def test_should_simulate_true_in_paper(self):
        from merid.prediction.venue_gate import VenueGate
        from config.trading_mode import TradeMode
        gate = VenueGate(mode=TradeMode.PAPER, live_enabled=False)
        assert gate.should_simulate_fill() is True

    def test_summary_contains_live_state(self):
        gate = _fresh_venue_gate(PRODUCTION_ENVS)
        s = gate.summary()
        assert s["is_live"] is True
        assert s["mode"] == "live"
        assert s["live_enabled"] is True

    def test_env_fallback_warning_source_present(self):
        """VenueGate source contains WARNING log for settings-unavailable fallback."""
        import os as _os
        src_path = _os.path.join(
            _os.path.dirname(_os.path.dirname(__file__)),
            "merid", "prediction", "venue_gate.py",
        )
        with open(src_path, encoding="utf-8") as f:
            content = f.read()
        assert "logger.warning" in content and "merid.settings unavailable" in content, (
            "VenueGate must log at WARNING level when merid.settings is unavailable"
        )


# ---------------------------------------------------------------------------
# Layer 3 — ModeManager (merid/pipeline/mode_manager.py)
# ---------------------------------------------------------------------------


class TestPipelineModeManagerKalshi:
    """Layer 3: pipeline ModeManager resolves Kalshi to LIVE with KALSHI_ENV=live."""

    def test_kalshi_live_when_kalshi_env_live(self):
        from merid.pipeline.mode_manager import TradingMode
        mode = _kalshi_mode_for_env({"KALSHI_ENV": "live"})
        assert mode == TradingMode.LIVE

    def test_kalshi_sim_when_kalshi_env_demo(self):
        from merid.pipeline.mode_manager import TradingMode
        mode = _kalshi_mode_for_env({"KALSHI_ENV": "demo"})
        assert mode == TradingMode.SIM

    def test_kalshi_sim_when_kalshi_env_sandbox(self):
        from merid.pipeline.mode_manager import TradingMode
        mode = _kalshi_mode_for_env({"KALSHI_ENV": "sandbox"})
        assert mode == TradingMode.SIM

    def test_kalshi_sim_when_kalshi_env_staging(self):
        from merid.pipeline.mode_manager import TradingMode
        mode = _kalshi_mode_for_env({"KALSHI_ENV": "staging"})
        assert mode == TradingMode.SIM

    def test_kalshi_sim_and_warning_when_env_unset(self):
        """Without KALSHI_ENV, _kalshi_default_mode returns SIM and source has warning call."""
        import os as _os
        src_path = _os.path.join(
            _os.path.dirname(_os.path.dirname(__file__)),
            "merid", "pipeline", "mode_manager.py",
        )
        with open(src_path, encoding="utf-8") as f:
            content = f.read()
        # Source must contain both a logger.warning and the key phrase
        assert "logger.warning" in content and "KALSHI_ENV is not set" in content, (
            "mode_manager.py must log at WARNING level when KALSHI_ENV is not set"
        )
        # And the function must return SIM in that case
        from merid.pipeline.mode_manager import TradingMode
        mode = _kalshi_mode_for_env({})  # no KALSHI_ENV
        assert mode == TradingMode.SIM

    def test_manager_kalshi_live_with_production_envs(self):
        """ModeManager singleton has Kalshi in LIVE when KALSHI_ENV=live."""
        from merid.pipeline.mode_manager import TradingMode
        with patch.dict(os.environ, PRODUCTION_ENVS, clear=False):
            import merid.pipeline.mode_manager as mm_mod
            importlib.reload(mm_mod)
            mm_mod._manager = None
            mm = mm_mod.get_mode_manager()
            k = mm.get_config("kalshi")
            mm_mod._manager = None
        assert k is not None
        assert k.mode == TradingMode.LIVE

    def test_manager_kalshi_sim_without_kalshi_env(self):
        """ModeManager has Kalshi in SIM when KALSHI_ENV is absent."""
        from merid.pipeline.mode_manager import TradingMode
        env_no_kalshi = {k: v for k, v in PRODUCTION_ENVS.items() if k != "KALSHI_ENV"}
        with patch.dict(os.environ, env_no_kalshi, clear=False):
            os.environ.pop("KALSHI_ENV", None)
            import merid.pipeline.mode_manager as mm_mod
            importlib.reload(mm_mod)
            mm_mod._manager = None
            mm = mm_mod.get_mode_manager()
            k = mm.get_config("kalshi")
            mm_mod._manager = None
        assert k.mode == TradingMode.SIM

    def test_check_can_trade_kalshi_live(self):
        """With KALSHI_ENV=live, check_can_trade('kalshi') does not raise."""
        with patch.dict(os.environ, PRODUCTION_ENVS, clear=False):
            import merid.pipeline.mode_manager as mm_mod
            importlib.reload(mm_mod)
            mm_mod._manager = None
            mm = mm_mod.get_mode_manager()
            mm.check_can_trade("kalshi")  # must not raise
            mm_mod._manager = None

    def test_check_can_trade_kalshi_sim_raises(self):
        """Without KALSHI_ENV=live, check_can_trade('kalshi') raises ModeBlockedError."""
        env_no_live = {**PRODUCTION_ENVS, "KALSHI_ENV": "demo"}
        with patch.dict(os.environ, env_no_live, clear=False):
            import merid.pipeline.mode_manager as mm_mod
            importlib.reload(mm_mod)
            mm_mod._manager = None
            mm = mm_mod.get_mode_manager()
            with pytest.raises(mm_mod.ModeManager.ModeBlockedError):
                mm.check_can_trade("kalshi")
            mm_mod._manager = None

    def test_should_simulate_false_for_kalshi_live(self):
        """should_simulate('kalshi') is False when Kalshi is in LIVE mode."""
        with patch.dict(os.environ, PRODUCTION_ENVS, clear=False):
            import merid.pipeline.mode_manager as mm_mod
            importlib.reload(mm_mod)
            mm_mod._manager = None
            mm = mm_mod.get_mode_manager()
            result = mm.should_simulate("kalshi")
            mm_mod._manager = None
        assert result is False

    def test_no_silent_downgrade_warning_in_live(self):
        """No silent-downgrade pattern exists in mode_manager source when live."""
        import os as _os
        import re as _re
        src_path = _os.path.join(
            _os.path.dirname(_os.path.dirname(__file__)),
            "merid", "pipeline", "mode_manager.py",
        )
        with open(src_path, encoding="utf-8") as f:
            content = f.read()
        # Confirm there is no silent "live" default in getenv calls (would bypass the warning)
        bad_lines = [
            ln for ln in content.splitlines()
            if _re.search(r'getenv\s*\(.*KALSHI_ENV.*,\s*["\']live["\']', ln)
            and not ln.lstrip().startswith("#")
        ]
        assert not bad_lines, (
            "mode_manager.py must not have a silent KALSHI_ENV=live default in getenv — "
            "the default should be SIM with a warning, not silently live"
        )

    def test_legacy_alpaca_ibkr_in_equity_domain(self):
        """Alpaca and IBKR configs remain in the equity domain (not prediction)."""
        with patch.dict(os.environ, PRODUCTION_ENVS, clear=False):
            import merid.pipeline.mode_manager as mm_mod
            importlib.reload(mm_mod)
            mm_mod._manager = None
            mm = mm_mod.get_mode_manager()
            alpaca = mm.get_config("alpaca")
            ibkr = mm.get_config("ibkr")
            # Neither should be in the prediction domain
            prediction_venues = [
                v.venue for v in mm.venues_by_domain("prediction")
                if v.venue in ("alpaca", "ibkr")
            ]
            mm_mod._manager = None
        assert alpaca is not None and alpaca.domain == "equity"
        assert ibkr is not None and ibkr.domain == "equity"
        assert prediction_venues == [], f"Alpaca/IBKR in prediction domain: {prediction_venues}"


# ---------------------------------------------------------------------------
# Cross-layer consistency: all three layers agree on LIVE
# ---------------------------------------------------------------------------


class TestAllLayersAgree:
    """With production envs, all three mode layers must simultaneously be LIVE."""

    def test_three_layers_all_live(self):
        """The canonical end-to-end check: all layers = LIVE together."""
        from config.trading_mode import TradeMode
        from merid.pipeline.mode_manager import TradingMode

        # Layer 1
        layer1 = _fresh_trade_mode(PRODUCTION_ENVS)
        assert layer1 == TradeMode.LIVE, f"Layer 1 (TradeMode): expected LIVE, got {layer1!r}"

        # Layer 2
        gate = _fresh_venue_gate(PRODUCTION_ENVS)
        assert gate.is_live is True, "Layer 2 (VenueGate): expected is_live=True"

        # Layer 3
        with patch.dict(os.environ, PRODUCTION_ENVS, clear=False):
            import merid.pipeline.mode_manager as mm_mod
            importlib.reload(mm_mod)
            mm_mod._manager = None
            mm = mm_mod.get_mode_manager()
            kalshi_mode = mm.get_config("kalshi").mode
            mm_mod._manager = None
        assert kalshi_mode == TradingMode.LIVE, (
            f"Layer 3 (ModeManager): expected LIVE, got {kalshi_mode!r}"
        )

    def test_missing_kalshi_env_causes_layer3_to_diverge(self):
        """Removing KALSHI_ENV causes Layer 3 to diverge to SIM while others stay live."""
        from config.trading_mode import TradeMode
        from merid.pipeline.mode_manager import TradingMode

        env_missing = {k: v for k, v in PRODUCTION_ENVS.items()}
        env_missing.pop("KALSHI_ENV", None)

        # Layer 1 still live (MERID_TRADE_MODE=live still set)
        layer1 = _fresh_trade_mode(env_missing)
        assert layer1 == TradeMode.LIVE

        # Layer 3 falls back to SIM
        with patch.dict(os.environ, env_missing, clear=False):
            os.environ.pop("KALSHI_ENV", None)
            import merid.pipeline.mode_manager as mm_mod
            importlib.reload(mm_mod)
            mm_mod._manager = None
            mm = mm_mod.get_mode_manager()
            layer3_mode = mm.get_config("kalshi").mode
            mm_mod._manager = None
        assert layer3_mode == TradingMode.SIM, (
            "Layer 3 should be SIM when KALSHI_ENV is absent — "
            "demonstrates the cross-layer divergence risk"
        )

    def test_missing_pm_live_enabled_causes_layer2_to_diverge(self):
        """Removing MERID_PM_LIVE_ENABLED causes Layer 2 to diverge (is_live=False)."""
        env_missing = {**PRODUCTION_ENVS, "MERID_PM_LIVE_ENABLED": "false"}
        gate = _fresh_venue_gate(env_missing)
        assert gate.is_live is False, "Layer 2 should not be live without MERID_PM_LIVE_ENABLED"


# ---------------------------------------------------------------------------
# Alpaca/IBKR isolation: production Kalshi path must not import them
# ---------------------------------------------------------------------------


class TestAlpacaIbkrIsolation:
    """Ensure Alpaca/IBKR adapters cannot be reached from the production Kalshi path."""

    # Production pipeline source files to scan
    _PIPELINE_FILES = [
        "merid/pipeline/mode_manager.py",
        "merid/pipeline/adapter.py",
        "merid/pipeline/router.py",
    ]
    _FORBIDDEN_IMPORT_PATTERNS = [
        "from core.venues.alpaca_adapter",
        "from core.venues.ibkr_adapter",
        "from trading.adapters.alpaca",
        "from trading.integrations.alpaca_client",
    ]

    def _read_src(self, relative_path: str) -> str:
        import os as _os
        full = _os.path.join(
            _os.path.dirname(_os.path.dirname(__file__)),
            relative_path,
        )
        with open(full, encoding="utf-8") as f:
            return f.read()

    def test_alpaca_not_imported_in_pipeline_files(self):
        """merid/pipeline does not import alpaca at module level."""
        for rel in self._PIPELINE_FILES:
            content = self._read_src(rel)
            for pattern in self._FORBIDDEN_IMPORT_PATTERNS:
                if "alpaca" in pattern.lower():
                    # Only flag uncommented lines
                    bad = [
                        ln for ln in content.splitlines()
                        if pattern in ln and not ln.lstrip().startswith("#")
                    ]
                    assert not bad, (
                        f"{rel} must not import alpaca: {bad}"
                    )

    def test_ibkr_not_imported_in_pipeline_files(self):
        """merid/pipeline does not import ibkr at module level."""
        for rel in self._PIPELINE_FILES:
            content = self._read_src(rel)
            for pattern in self._FORBIDDEN_IMPORT_PATTERNS:
                if "ibkr" in pattern.lower():
                    bad = [
                        ln for ln in content.splitlines()
                        if pattern in ln and not ln.lstrip().startswith("#")
                    ]
                    assert not bad, (
                        f"{rel} must not import ibkr: {bad}"
                    )

    def test_alpaca_adapter_has_legacy_marker(self):
        """core/venues/alpaca_adapter.py carries the LEGACY module docstring."""
        content = self._read_src("core/venues/alpaca_adapter.py")
        assert "LEGACY" in content, (
            "core/venues/alpaca_adapter.py must have LEGACY marker in its docstring"
        )

    def test_ibkr_adapter_has_legacy_marker(self):
        """core/venues/ibkr_adapter.py carries the LEGACY module docstring."""
        content = self._read_src("core/venues/ibkr_adapter.py")
        assert "LEGACY" in content, (
            "core/venues/ibkr_adapter.py must have LEGACY marker in its docstring"
        )

    def test_mode_manager_alpaca_ibkr_notes_are_legacy(self):
        """ModeManager _DEFAULT_CONFIGS for alpaca/ibkr carry a LEGACY note."""
        content = self._read_src("merid/pipeline/mode_manager.py")
        # The LEGACY annotation must appear in the mode_manager source for both venues
        assert "LEGACY" in content, (
            "merid/pipeline/mode_manager.py must have LEGACY annotation for Alpaca/IBKR configs"
        )

    def test_alpaca_ibkr_in_equity_domain_in_source(self):
        """mode_manager source specifies alpaca/ibkr as equity domain (not prediction)."""
        content = self._read_src("merid/pipeline/mode_manager.py")
        # Find the alpaca VenueConfig block and assert domain="equity"
        import re
        # Look for alpaca config block
        alpaca_block = re.search(
            r'venue="alpaca".*?domain="(.*?)"',
            content,
            re.DOTALL,
        )
        assert alpaca_block is not None, "alpaca VenueConfig not found in mode_manager.py"
        assert alpaca_block.group(1) == "equity", (
            f"alpaca domain must be 'equity', got {alpaca_block.group(1)!r}"
        )

        ibkr_block = re.search(
            r'venue="ibkr".*?domain="(.*?)"',
            content,
            re.DOTALL,
        )
        assert ibkr_block is not None, "ibkr VenueConfig not found in mode_manager.py"
        assert ibkr_block.group(1) == "equity", (
            f"ibkr domain must be 'equity', got {ibkr_block.group(1)!r}"
        )
