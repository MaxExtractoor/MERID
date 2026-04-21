"""Per-Asset Risk Cap Tests — 24 tests

Covers AssetCap dataclass, ExecutionGuard integration,
pre_trade_check enforcement, and record_execution tracking.
"""

from __future__ import annotations

import pytest
import time
from dataclasses import fields

from merid.execution_guard import (
    AssetCap,
    ExecutionGuard,
    TradeVerdict,
    get_execution_guard,
)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. AssetCap Unit Tests (5)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAssetCapUnit:
    """Test AssetCap dataclass behavior."""

    def test_default_values(self):
        """AssetCap initializes with correct defaults."""
        cap = AssetCap(asset="BTC")
        assert cap.asset == "BTC"
        assert cap.max_daily_notional_usd == 4000.0
        assert cap.max_single_trade_usd == 1000.0
        assert cap.daily_notional_usd == 0.0
        assert cap.last_reset_date == ""

    def test_custom_values(self):
        """AssetCap accepts custom values."""
        cap = AssetCap(
            asset="ETH",
            max_daily_notional_usd=3000.0,
            max_single_trade_usd=750.0,
        )
        assert cap.max_daily_notional_usd == 3000.0
        assert cap.max_single_trade_usd == 750.0

    def test_record_trade_updates_daily(self):
        """record_trade() updates daily notional."""
        cap = AssetCap(asset="BTC")
        cap.record_trade(500.0)
        assert cap.daily_notional_usd == 500.0
        cap.record_trade(300.0)
        assert cap.daily_notional_usd == 800.0

    def test_remaining_notional_calculation(self):
        """remaining_notional() calculates correctly."""
        cap = AssetCap(asset="BTC", max_daily_notional_usd=1000.0)
        assert cap.remaining_notional() == 1000.0
        cap.record_trade(600.0)
        assert cap.remaining_notional() == 400.0
        cap.record_trade(500.0)
        assert cap.remaining_notional() == 0.0  # Can't go negative

    def test_utilization_pct_calculation(self):
        """utilization_pct() returns correct percentage."""
        cap = AssetCap(asset="BTC", max_daily_notional_usd=1000.0)
        assert cap.utilization_pct() == 0.0
        cap.record_trade(500.0)
        assert cap.utilization_pct() == 50.0
        cap.record_trade(500.0)
        assert cap.utilization_pct() == 100.0


# ═══════════════════════════════════════════════════════════════════════════════
# 2. ExecutionGuard Initialization (3)
# ═══════════════════════════════════════════════════════════════════════════════

class TestExecutionGuardInit:
    """Test ExecutionGuard asset cap initialization."""

    def test_asset_caps_dict_empty_by_default(self):
        """ExecutionGuard starts with empty asset caps dict."""
        guard = ExecutionGuard()
        assert guard._asset_caps == {}
        assert guard.get_asset_cap_status()["total_assets"] == 0

    def test_asset_caps_isolated_per_instance(self):
        """Each guard instance has isolated asset caps."""
        guard1 = ExecutionGuard()
        guard2 = ExecutionGuard()
        guard1.set_asset_cap("BTC", 4000, 1000)
        assert guard1.get_asset_cap("BTC") is not None
        assert guard2.get_asset_cap("BTC") is None

    def test_singleton_behavior(self):
        """get_execution_guard() returns same instance."""
        # Note: This test assumes clean state; may need isolation in CI
        guard1 = get_execution_guard()
        guard2 = get_execution_guard()
        assert guard1 is guard2


# ═══════════════════════════════════════════════════════════════════════════════
# 3. set_asset_cap Runtime Updates (4)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSetAssetCap:
    """Test runtime asset cap configuration."""

    def test_set_asset_cap_creates_new(self):
        """set_asset_cap() creates new AssetCap entry."""
        guard = ExecutionGuard()
        guard.set_asset_cap("BTC", 4000, 1000)
        cap = guard.get_asset_cap("BTC")
        assert cap is not None
        assert cap.max_daily_notional_usd == 4000.0
        assert cap.max_single_trade_usd == 1000.0

    def test_set_asset_cap_updates_existing(self):
        """set_asset_cap() updates existing AssetCap."""
        guard = ExecutionGuard()
        guard.set_asset_cap("BTC", 4000, 1000)
        guard.set_asset_cap("BTC", 5000, 1200)
        cap = guard.get_asset_cap("BTC")
        assert cap.max_daily_notional_usd == 5000.0
        assert cap.max_single_trade_usd == 1200.0

    def test_case_normalization(self):
        """Asset symbols are case-normalized to uppercase."""
        guard = ExecutionGuard()
        guard.set_asset_cap("btc", 4000, 1000)
        assert guard.get_asset_cap("BTC") is not None
        assert guard.get_asset_cap("btc") is not None  # Both work

    def test_get_asset_cap_status_structure(self):
        """get_asset_cap_status() returns expected structure."""
        guard = ExecutionGuard()
        guard.set_asset_cap("BTC", 4000, 1000)
        guard.set_asset_cap("ETH", 3000, 750)
        status = guard.get_asset_cap_status()
        assert status["total_assets"] == 2
        assert "BTC" in status["assets"]
        assert "ETH" in status["assets"]
        assert isinstance(status["assets_at_limit"], list)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. pre_trade_check Enforcement (6)
# ═══════════════════════════════════════════════════════════════════════════════

class TestPreTradeCheckAssetCap:
    """Test asset cap enforcement in pre_trade_check."""

    def _guard_with_promo_disabled(self):
        """Create guard with promotion enforcement and kill switch disabled for tests."""
        guard = ExecutionGuard()
        guard.enforce_promotion = False  # Disable to test asset caps in isolation
        # Clear any persisted kill switch state from disk
        if guard.kill_switch_active:
            guard.deactivate_kill_switch()
        # Also clear risk_controller kill switch (separate system)
        try:
            from merid.risk.kill_switches import risk_controller
            if hasattr(risk_controller, '_global_kill') and risk_controller._global_kill:
                risk_controller._global_kill = False
                risk_controller._kill_reason = ""
        except Exception:
            pass
        # Set high CQI (1.0) to avoid throttling in tests
        guard.update_cqi("crypto", 1.0)
        # Disable cooldown between trades for tests
        guard._cooldown_seconds = 0.0
        guard._last_execution_at = 0.0
        return guard

    def test_no_asset_skips_check(self):
        """Empty asset parameter skips asset cap check."""
        guard = self._guard_with_promo_disabled()
        guard.set_asset_cap("BTC", 4000, 1000)
        # Should not block even though cap exists
        verdict = guard.pre_trade_check(
            plan_id="test1",
            symbol="BTC/USD",
            domain="crypto",
            size_usd=5000,  # Exceeds cap
            asset="",  # No asset specified
        )
        assert verdict.allowed  # Not blocked because no asset specified

    def test_no_cap_for_asset_skips_check(self):
        """Asset specified but no cap configured - skip check."""
        guard = self._guard_with_promo_disabled()
        # No asset caps configured
        verdict = guard.pre_trade_check(
            plan_id="test2",
            symbol="BTC/USD",
            domain="crypto",
            size_usd=999999,
            asset="BTC",
        )
        assert verdict.allowed  # Not blocked because no cap configured

    def test_trade_allowed_under_cap(self):
        """Trade within cap limits is allowed."""
        guard = self._guard_with_promo_disabled()
        guard.set_asset_cap("BTC", 4000, 1000)
        verdict = guard.pre_trade_check(
            plan_id="test3",
            symbol="BTC/USD",
            domain="crypto",
            size_usd=500,
            asset="BTC",
        )
        assert verdict.allowed
        assert "asset_notional_cap" in verdict.checks_passed

    def test_trade_clamped_to_remaining(self):
        """Trade exceeding remaining cap is clamped."""
        guard = self._guard_with_promo_disabled()
        guard.set_asset_cap("BTC", 1000, 500)
        # Pre-seed some usage
        guard.record_execution("crypto", 700, asset="BTC")
        verdict = guard.pre_trade_check(
            plan_id="test4",
            symbol="BTC/USD",
            domain="crypto",
            size_usd=500,  # Would exceed remaining 300
            asset="BTC",
        )
        assert verdict.allowed  # Still allowed but clamped
        assert verdict.adjusted_size_usd == 300.0  # Clamped to remaining
        assert "asset_notional_cap_clamped" in verdict.checks_passed

    def test_trade_blocked_when_cap_exhausted(self):
        """Trade blocked when daily cap exhausted."""
        guard = self._guard_with_promo_disabled()
        guard.set_asset_cap("BTC", 1000, 500)
        # Exhaust the cap
        guard.record_execution("crypto", 1000, asset="BTC")
        verdict = guard.pre_trade_check(
            plan_id="test5",
            symbol="BTC/USD",
            domain="crypto",
            size_usd=100,
            asset="BTC",
        )
        assert not verdict.allowed
        assert "daily asset notional cap exhausted for BTC" in verdict.reason
        assert "asset_notional_cap" in verdict.checks_failed

    def test_single_trade_cap_clamped(self):
        """Single trade ceiling enforced per asset."""
        guard = self._guard_with_promo_disabled()
        guard.set_asset_cap("BTC", 4000, 500)  # Low single trade max
        verdict = guard.pre_trade_check(
            plan_id="test6",
            symbol="BTC/USD",
            domain="crypto",
            size_usd=1000,  # Exceeds single trade max
            asset="BTC",
        )
        assert verdict.allowed
        assert verdict.adjusted_size_usd == 500.0  # Clamped to single trade max
        assert "asset_single_trade_cap_clamped" in verdict.checks_passed


# ═══════════════════════════════════════════════════════════════════════════════
# 5. record_execution Tracking (3)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRecordExecution:
    """Test asset cap usage tracking via record_execution."""

    def test_record_without_asset_updates_domain_only(self):
        """record_execution without asset only updates domain cap."""
        guard = ExecutionGuard()
        guard.set_asset_cap("BTC", 4000, 1000)
        initial = guard.get_asset_cap("BTC").daily_notional_usd
        guard.record_execution("crypto", 500.0, asset="")
        assert guard.get_asset_cap("BTC").daily_notional_usd == initial

    def test_record_with_asset_updates_both(self):
        """record_execution with asset updates domain and asset caps."""
        guard = ExecutionGuard()
        guard.set_asset_cap("BTC", 4000, 1000)
        guard.record_execution("crypto", 500.0, asset="BTC")
        assert guard.get_asset_cap("BTC").daily_notional_usd == 500.0

    def test_record_with_unknown_asset_updates_domain_only(self):
        """record_execution with unknown asset only updates domain."""
        guard = ExecutionGuard()
        # No BTC cap configured
        guard.record_execution("crypto", 500.0, asset="BTC")
        # Should not crash
        assert guard.get_asset_cap("BTC") is None


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Integration Scenarios (3)
# ═══════════════════════════════════════════════════════════════════════════════

class TestIntegration:
    """End-to-end integration scenarios."""

    def _guard_with_promo_disabled(self):
        """Create guard with promotion enforcement and kill switch disabled for tests."""
        guard = ExecutionGuard()
        guard.enforce_promotion = False
        # Clear any persisted kill switch state from disk
        if guard.kill_switch_active:
            guard.deactivate_kill_switch()
        # Also clear risk_controller kill switch (separate system)
        try:
            from merid.risk.kill_switches import risk_controller
            if hasattr(risk_controller, '_global_kill') and risk_controller._global_kill:
                risk_controller._global_kill = False
                risk_controller._kill_reason = ""
        except Exception:
            pass
        # Set high CQI (1.0) to avoid throttling in tests
        guard.update_cqi("crypto", 1.0)
        # Disable cooldown between trades for tests
        guard._cooldown_seconds = 0.0
        guard._last_execution_at = 0.0
        return guard

    def test_full_trade_flow_tracks_usage(self):
        """Complete trade flow: check, execute, record updates usage."""
        guard = self._guard_with_promo_disabled()
        guard.set_asset_cap("ETH", 3000, 750)
        # Trade 1: $500
        verdict1 = guard.pre_trade_check(
            plan_id="flow1", symbol="ETH/USD", domain="crypto",
            size_usd=500, asset="ETH"
        )
        if verdict1.allowed:
            guard.record_execution("crypto", verdict1.adjusted_size_usd, asset="ETH")
        assert guard.get_asset_cap("ETH").daily_notional_usd == 500.0
        # Trade 2: $500
        verdict2 = guard.pre_trade_check(
            plan_id="flow2", symbol="ETH/USD", domain="crypto",
            size_usd=500, asset="ETH"
        )
        if verdict2.allowed:
            guard.record_execution("crypto", verdict2.adjusted_size_usd, asset="ETH")
        assert guard.get_asset_cap("ETH").daily_notional_usd == 1000.0

    def test_summary_includes_asset_caps(self):
        """summary() output includes asset_caps key."""
        guard = ExecutionGuard()
        guard.set_asset_cap("BTC", 4000, 1000)
        guard.set_asset_cap("ETH", 3000, 750)
        summary = guard.summary()
        assert "asset_caps" in summary
        assert "BTC" in summary["asset_caps"]
        assert "ETH" in summary["asset_caps"]

    def test_multiple_assets_isolated(self):
        """Usage is isolated per asset."""
        guard = ExecutionGuard()
        guard.set_asset_cap("BTC", 4000, 1000)
        guard.set_asset_cap("ETH", 3000, 750)
        # Trade BTC only
        guard.record_execution("crypto", 2000, asset="BTC")
        assert guard.get_asset_cap("BTC").daily_notional_usd == 2000.0
        assert guard.get_asset_cap("ETH").daily_notional_usd == 0.0
        # Trade ETH only
        guard.record_execution("crypto", 1500, asset="ETH")
        assert guard.get_asset_cap("BTC").daily_notional_usd == 2000.0
        assert guard.get_asset_cap("ETH").daily_notional_usd == 1500.0

    @pytest.mark.kalshi_live_ready
    @pytest.mark.p0_live_blocker
    def test_multi_timeframe_aggregation(self):
        """Daily cap aggregates across timeframes (M5 + M15 + H1)."""
        guard = self._guard_with_promo_disabled()
        guard.set_asset_cap("BTC", 2000, 500)  # Daily cap

        # Simulate multiple small M5 trades
        for i in range(4):
            verdict = guard.pre_trade_check(
                plan_id=f"m5_{i}", symbol="BTC/USD", domain="crypto",
                size_usd=200, asset="BTC"
            )
            if verdict.allowed:
                guard.record_execution("crypto", verdict.adjusted_size_usd, asset="BTC")

        # Should have used $800 (4 * $200)
        assert guard.get_asset_cap("BTC").daily_notional_usd == 800.0

        # Simulate M15 trade (will be clamped to single trade max of $500)
        verdict = guard.pre_trade_check(
            plan_id="m15", symbol="BTC/USD", domain="crypto",
            size_usd=600, asset="BTC"
        )
        assert verdict.adjusted_size_usd == 500.0  # Clamped to single trade max
        if verdict.allowed:
            guard.record_execution("crypto", verdict.adjusted_size_usd, asset="BTC")

        # Now at $1300 total (800 + 500)
        assert guard.get_asset_cap("BTC").daily_notional_usd == 1300.0

        # Try large H1 trade that would exceed remaining $700
        verdict = guard.pre_trade_check(
            plan_id="h1_large", symbol="BTC/USD", domain="crypto",
            size_usd=1000, asset="BTC"
        )
        # Clamped to single trade max $500 (which is <= remaining $700)
        assert verdict.adjusted_size_usd == 500.0

        if verdict.allowed:
            guard.record_execution("crypto", verdict.adjusted_size_usd, asset="BTC")

        # After 3 trades: 800 + 500 + 500 = 1800 used, 200 remaining
        assert guard.get_asset_cap("BTC").daily_notional_usd == 1800.0
        assert guard.get_asset_cap("BTC").remaining_notional() == 200.0

        # Final small trade should be allowed (200 <= remaining 200)
        final_verdict = guard.pre_trade_check(
            plan_id="final", symbol="BTC/USD", domain="crypto",
            size_usd=200, asset="BTC"
        )
        assert final_verdict.allowed
        assert final_verdict.adjusted_size_usd == 200.0


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Config Sync and Consistency (3)
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfigSync:
    """Test config-driven asset cap population."""

    def test_apply_from_dict_config(self):
        """Sync asset caps from dict-style config."""
        guard = ExecutionGuard()
        fake_config = {
            "asset_caps": {
                "BTC": {"max_daily_notional_usd": 4000, "max_single_trade_usd": 1000},
                "ETH": {"max_daily_notional_usd": 3000, "max_single_trade_usd": 750},
            }
        }
        guard.apply_asset_caps_from_config(fake_config)

        assert guard.get_asset_cap("BTC").max_daily_notional_usd == 4000.0
        assert guard.get_asset_cap("BTC").max_single_trade_usd == 1000.0
        assert guard.get_asset_cap("ETH").max_daily_notional_usd == 3000.0

    def test_apply_from_object_config(self):
        """Sync asset caps from object-style config."""
        from dataclasses import dataclass

        @dataclass
        class AssetCapConfig:
            max_daily_notional_usd: float
            max_single_trade_usd: float

        @dataclass
        class RiskConfig:
            asset_caps: dict

        guard = ExecutionGuard()
        fake_config = RiskConfig(
            asset_caps={
                "SOL": AssetCapConfig(2000, 500),
                "XRP": AssetCapConfig(1500, 375),
            }
        )
        guard.apply_asset_caps_from_config(fake_config)

        assert guard.get_asset_cap("SOL").max_daily_notional_usd == 2000.0
        assert guard.get_asset_cap("XRP").max_daily_notional_usd == 1500.0

    def test_ensure_core_assets_passes_when_all_present(self):
        """ensure_core_assets_caps passes when all assets configured."""
        guard = ExecutionGuard()
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            guard.set_asset_cap(asset, 1000, 500)

        # Should not raise
        guard.ensure_core_assets_caps()
        assert not guard.kill_switch_active

    def test_ensure_core_assets_raises_when_missing(self):
        """ensure_core_assets_caps raises and kills switch when missing."""
        guard = ExecutionGuard()
        guard.set_asset_cap("BTC", 4000, 1000)
        guard.set_asset_cap("ETH", 3000, 750)
        # Missing: SOL, XRP, DOGE

        with pytest.raises(RuntimeError) as exc_info:
            guard.ensure_core_assets_caps()

        assert "SOL" in str(exc_info.value)
        assert "XRP" in str(exc_info.value)
        assert "DOGE" in str(exc_info.value)
        assert guard.kill_switch_active  # Kill switch activated

    def test_config_consistency_end_to_end(self):
        """Full config→guard→status consistency check."""
        guard = ExecutionGuard()
        fake_risk_config = {
            "asset_caps": {
                "BTC": {"max_daily_notional_usd": 4000, "max_single_trade_usd": 1000},
                "ETH": {"max_daily_notional_usd": 3000, "max_single_trade_usd": 750},
                "SOL": {"max_daily_notional_usd": 2000, "max_single_trade_usd": 500},
                "XRP": {"max_daily_notional_usd": 1500, "max_single_trade_usd": 375},
                "DOGE": {"max_daily_notional_usd": 500, "max_single_trade_usd": 125},
            }
        }

        guard.apply_asset_caps_from_config(fake_risk_config)
        guard.ensure_core_assets_caps()

        status = guard.get_asset_cap_status()
        for asset, cfg in fake_risk_config["asset_caps"].items():
            asset_status = status["assets"][asset]
            assert asset_status["max_daily_notional_usd"] == cfg["max_daily_notional_usd"]
            assert asset_status["max_single_trade_usd"] == cfg["max_single_trade_usd"]


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Configuration Consistency Meta-Tests (1)
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfigConsistency:
    """Meta-tests to prevent configuration drift."""

    def test_settings_includes_all_core_assets(self):
        """Assert settings.get_dynamic_asset_caps() includes all 5 core assets.
        
        This test mirrors ensure_core_assets_caps() logic to catch
        accidental config edits before runtime startup.
        """
        from merid.settings import settings
        
        core_assets = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
        configured_assets = set(settings.get_dynamic_asset_caps().keys())
        
        missing = core_assets - configured_assets
        assert not missing, f"Core assets missing from settings.get_dynamic_asset_caps(): {missing}"

    def test_settings_asset_caps_have_valid_limits(self):
        """Assert all configured asset caps have positive limits."""
        from merid.settings import settings
        
        for asset, cap in settings.get_dynamic_asset_caps().items():
            assert cap.max_daily_notional_usd > 0, f"{asset} has invalid daily limit"
            assert cap.max_single_trade_usd > 0, f"{asset} has invalid single-trade limit"
            assert cap.max_single_trade_usd <= cap.max_daily_notional_usd, \
                f"{asset} single-trade limit exceeds daily limit"
