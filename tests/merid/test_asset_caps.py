"""Tests for per-asset cap logic in merid/execution_guard.py.

Run with:
  pytest tests/merid/test_asset_caps.py -v
"""
from __future__ import annotations

import time

import pytest

from merid.execution_guard import AssetCap, ExecutionGuard


class TestAssetCap:
    def test_initial_state(self):
        cap = AssetCap(asset="BTC", max_daily_notional_usd=4000, max_single_trade_usd=1000)
        assert cap.remaining_notional() == 4000.0
        assert cap.utilization_pct() == 0.0

    def test_record_trade_reduces_remaining(self):
        cap = AssetCap(asset="ETH", max_daily_notional_usd=3000, max_single_trade_usd=750)
        cap.record_trade(500)
        assert cap.remaining_notional() == 2500.0
        assert cap.daily_trade_count == 1

    def test_remaining_never_negative(self):
        cap = AssetCap(asset="SOL", max_daily_notional_usd=100, max_single_trade_usd=50)
        cap.record_trade(200)
        assert cap.remaining_notional() == 0.0

    def test_utilization_pct(self):
        cap = AssetCap(asset="XRP", max_daily_notional_usd=1000, max_single_trade_usd=250)
        cap.record_trade(800)
        assert cap.utilization_pct() == 80.0

    def test_to_dict_structure(self):
        cap = AssetCap(asset="DOGE", max_daily_notional_usd=500, max_single_trade_usd=125)
        cap.record_trade(100)
        d = cap.to_dict()
        assert d["asset"] == "DOGE"
        assert d["remaining_notional_usd"] == 400.0
        assert d["utilization_pct"] == 20.0


class TestExecutionGuardAssetCapInit:
    def test_default_assets_present(self):
        guard = ExecutionGuard()
        assert set(guard._asset_caps.keys()) == {"BTC", "ETH", "SOL", "XRP", "DOGE"}

    def test_default_limits_ordered(self):
        guard = ExecutionGuard()
        assert guard._asset_caps["BTC"].max_daily_notional_usd > guard._asset_caps["DOGE"].max_daily_notional_usd

    def test_summary_contains_asset_caps(self):
        guard = ExecutionGuard()
        s = guard.summary()
        assert "asset_caps" in s
        assert set(s["asset_caps"].keys()) == {"BTC", "ETH", "SOL", "XRP", "DOGE"}


class TestSetAssetCap:
    def test_update_existing_asset(self):
        guard = ExecutionGuard()
        guard.set_asset_cap("BTC", 9000, 2000)
        assert guard._asset_caps["BTC"].max_daily_notional_usd == 9000

    def test_create_new_asset(self):
        guard = ExecutionGuard()
        guard.set_asset_cap("ADA", 800)
        assert "ADA" in guard._asset_caps
        assert guard._asset_caps["ADA"].max_single_trade_usd == 200.0

    def test_case_normalised(self):
        guard = ExecutionGuard()
        guard.set_asset_cap("eth", 2500, 600)
        assert "ETH" in guard._asset_caps

    def test_get_asset_cap_status_returns_all(self):
        guard = ExecutionGuard()
        status = guard.get_asset_cap_status()
        assert "BTC" in status
        assert "remaining_notional_usd" in status["BTC"]


class TestPreTradeCheckAssetCap:
    def _make_guard(self):
        guard = ExecutionGuard()
        guard._cooldown_seconds = 0
        return guard

    def test_trade_within_asset_cap_allowed(self):
        guard = self._make_guard()
        guard._asset_caps["BTC"].max_daily_notional_usd = 500
        verdict = guard.pre_trade_check(
            plan_id="p1", symbol="KXBTC", domain="crypto", size_usd=400, asset="BTC",
        )
        assert verdict.allowed
        assert "asset_notional_cap" in verdict.checks_passed

    def test_trade_exceeds_daily_cap_clamped(self):
        guard = self._make_guard()
        guard._asset_caps["ETH"].max_daily_notional_usd = 200
        guard._asset_caps["ETH"].max_single_trade_usd = 1000
        verdict = guard.pre_trade_check(
            plan_id="p2", symbol="KXETH", domain="crypto", size_usd=500, asset="ETH",
        )
        assert verdict.allowed
        assert verdict.adjusted_size_usd == 200.0
        assert "asset_notional_cap_clamped" in verdict.checks_passed

    def test_trade_blocked_when_cap_exhausted(self):
        guard = self._make_guard()
        today = time.strftime("%Y-%m-%d")
        guard._asset_caps["SOL"].max_daily_notional_usd = 100
        guard._asset_caps["SOL"].daily_notional_usd = 100
        guard._asset_caps["SOL"].last_reset_date = today
        verdict = guard.pre_trade_check(
            plan_id="p3", symbol="KXSOL", domain="crypto", size_usd=10, asset="SOL",
        )
        assert not verdict.allowed
        assert "asset_notional_cap" in verdict.checks_failed
        assert "SOL" in verdict.reason

    def test_asset_single_trade_ceiling(self):
        guard = self._make_guard()
        guard._asset_caps["XRP"].max_daily_notional_usd = 5000
        guard._asset_caps["XRP"].max_single_trade_usd = 100
        verdict = guard.pre_trade_check(
            plan_id="p4", symbol="KXXRP", domain="crypto", size_usd=300, asset="XRP",
        )
        assert verdict.allowed
        assert verdict.adjusted_size_usd == 100.0
        assert "asset_single_trade_cap_clamped" in verdict.checks_passed

    def test_asset_cap_not_applied_for_non_crypto(self):
        guard = self._make_guard()
        guard._asset_caps["BTC"].max_daily_notional_usd = 1
        verdict = guard.pre_trade_check(
            plan_id="p5", symbol="BTC-FUT", domain="prediction", size_usd=200, asset="BTC",
        )
        assert "asset_notional_cap" not in verdict.checks_failed

    def test_asset_cap_skipped_when_no_asset(self):
        guard = self._make_guard()
        verdict = guard.pre_trade_check(
            plan_id="p6", symbol="KXBTC", domain="crypto", size_usd=100,
        )
        assert "asset_notional_cap" not in verdict.checks_passed
        assert "asset_notional_cap" not in verdict.checks_failed

    def test_unknown_asset_allowed(self):
        guard = self._make_guard()
        verdict = guard.pre_trade_check(
            plan_id="p7", symbol="KXLINK", domain="crypto", size_usd=100, asset="LINK",
        )
        assert verdict.allowed


class TestRecordExecutionAsset:
    def test_record_updates_asset_cap(self):
        guard = ExecutionGuard()
        guard.record_execution(domain="crypto", notional_usd=500, asset="BTC")
        assert guard._asset_caps["BTC"].daily_notional_usd == 500.0

    def test_record_ignores_asset_for_non_crypto(self):
        guard = ExecutionGuard()
        guard.record_execution(domain="prediction", notional_usd=100, asset="BTC")
        assert guard._asset_caps["BTC"].daily_notional_usd == 0.0

    def test_record_without_asset_safe(self):
        guard = ExecutionGuard()
        guard.record_execution(domain="crypto", notional_usd=200)
        assert all(c.daily_notional_usd == 0.0 for c in guard._asset_caps.values())

    def test_record_unknown_asset_safe(self):
        guard = ExecutionGuard()
        guard.record_execution(domain="crypto", notional_usd=50, asset="ADA")
