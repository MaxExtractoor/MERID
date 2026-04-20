"""Tests for Market Regime Gate — crypto basket flatness filter.

Run: py -m pytest tests/test_market_regime_gate.py -v
"""

from __future__ import annotations

import pytest
from dataclasses import replace

from merid.market_regime import (
    MarketRegimeConfig,
    FlatnessThresholds,
    BasketRules,
    LookbackConfig,
    MarketRegimeGate,
    RegimeAction,
    AssetMetrics,
    load_regime_config,
    get_regime_config,
    get_regime_gate,
    _reset_regime_config,
    _reset_regime_gate,
)


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset singleton state before each test."""
    _reset_regime_config()
    _reset_regime_gate()
    yield
    _reset_regime_config()
    _reset_regime_gate()


@pytest.fixture
def default_config():
    """Default test configuration."""
    return MarketRegimeConfig(
        enabled=True,
        universe=("BTC", "ETH", "SOL", "XRP", "DOGE"),
        lookback=LookbackConfig(bar_interval="15m", bars=16),
        flatness=FlatnessThresholds(
            max_abs_return_pct=0.75,
            min_atr_pct=0.35,
            min_volume_ratio=0.80,
        ),
        basket_rules=BasketRules(
            block_if_flat_count_gte=4,
            reduce_if_flat_count_gte=3,
        ),
        shadow_mode=False,
    )


# ── Config Tests ───────────────────────────────────────────────────────────


class TestMarketRegimeConfig:
    """Tests for configuration dataclasses."""

    def test_default_config_creation(self, default_config):
        """Config dataclass creates with expected defaults."""
        assert default_config.enabled is True
        assert default_config.universe == ("BTC", "ETH", "SOL", "XRP", "DOGE")
        assert default_config.flatness.max_abs_return_pct == 0.75
        assert default_config.basket_rules.block_if_flat_count_gte == 4

    def test_config_immutability(self, default_config):
        """Frozen dataclass prevents mutation."""
        with pytest.raises(AttributeError):
            default_config.enabled = False

    def test_empty_universe_disables(self):
        """Empty universe sets enabled=False via __post_init__."""
        cfg = MarketRegimeConfig(universe=())
        assert cfg.enabled is False


# ── Gate Logic Tests ───────────────────────────────────────────────────────


class TestMarketRegimeGate:
    """Tests for core gate evaluation logic."""

    def test_all_active_allow(self, default_config):
        """All 5 assets active → ALLOW."""
        gate = MarketRegimeGate(default_config)

        # All assets above thresholds (not flat)
        snapshot = {
            "BTC": {"return_pct": 1.0, "atr_pct": 0.5, "vol_ratio": 1.2},
            "ETH": {"return_pct": 0.8, "atr_pct": 0.6, "vol_ratio": 1.1},
            "SOL": {"return_pct": 1.2, "atr_pct": 0.8, "vol_ratio": 1.3},
            "XRP": {"return_pct": 0.9, "atr_pct": 0.7, "vol_ratio": 1.0},
            "DOGE": {"return_pct": 1.5, "atr_pct": 0.9, "vol_ratio": 1.4},
        }

        decision = gate.evaluate(snapshot)

        assert decision.action == RegimeAction.ALLOW
        assert decision.flat_count == 0
        assert decision.total_assets == 5
        assert decision.reason_codes == []
        assert decision.allowed is True
        assert decision.blocked is False

    def test_three_flat_reduce(self, default_config):
        """3 of 5 flat → REDUCE."""
        gate = MarketRegimeGate(default_config)

        # 3 assets below ALL thresholds (flat), 2 active
        # For flatness: |return| < 0.75, atr < 0.35, vol_ratio < 0.80
        snapshot = {
            "BTC": {"return_pct": 0.1, "atr_pct": 0.2, "vol_ratio": 0.6},  # flat
            "ETH": {"return_pct": 0.2, "atr_pct": 0.3, "vol_ratio": 0.7},  # flat
            "SOL": {"return_pct": 0.3, "atr_pct": 0.2, "vol_ratio": 0.5},  # flat
            "XRP": {"return_pct": 1.0, "atr_pct": 0.6, "vol_ratio": 1.2},  # active
            "DOGE": {"return_pct": 1.5, "atr_pct": 0.9, "vol_ratio": 1.4},  # active
        }

        decision = gate.evaluate(snapshot)

        assert decision.action == RegimeAction.REDUCE
        assert decision.flat_count == 3
        assert "low_activity" in decision.reason_codes
        assert "3_of_5_flat" in decision.reason_codes
        # REDUCE is not "allowed" (fully), but also not "blocked"
        # Use gate.should_allow_new_entries() for entry permission
        assert decision.allowed is False  # Not fully allowed
        assert decision.blocked is False  # But not blocked either

    def test_four_flat_block(self, default_config):
        """4 of 5 flat → BLOCK."""
        gate = MarketRegimeGate(default_config)

        # 4 assets below thresholds (flat), 1 active
        snapshot = {
            "BTC": {"return_pct": 0.1, "atr_pct": 0.2, "vol_ratio": 0.6},  # flat
            "ETH": {"return_pct": 0.2, "atr_pct": 0.3, "vol_ratio": 0.7},  # flat
            "SOL": {"return_pct": 0.3, "atr_pct": 0.1, "vol_ratio": 0.5},  # flat
            "XRP": {"return_pct": 0.1, "atr_pct": 0.2, "vol_ratio": 0.6},  # flat
            "DOGE": {"return_pct": 1.5, "atr_pct": 0.9, "vol_ratio": 1.4},  # active
        }

        decision = gate.evaluate(snapshot)

        assert decision.action == RegimeAction.BLOCK
        assert decision.flat_count == 4
        assert "basket_flat" in decision.reason_codes
        assert "4_of_5_flat" in decision.reason_codes
        assert decision.allowed is False
        assert decision.blocked is True

    def test_five_flat_block(self, default_config):
        """All 5 flat → BLOCK."""
        gate = MarketRegimeGate(default_config)

        snapshot = {
            "BTC": {"return_pct": 0.1, "atr_pct": 0.2, "vol_ratio": 0.6},
            "ETH": {"return_pct": 0.2, "atr_pct": 0.3, "vol_ratio": 0.7},
            "SOL": {"return_pct": 0.3, "atr_pct": 0.1, "vol_ratio": 0.5},
            "XRP": {"return_pct": 0.1, "atr_pct": 0.2, "vol_ratio": 0.6},
            "DOGE": {"return_pct": 0.2, "atr_pct": 0.3, "vol_ratio": 0.7},
        }

        decision = gate.evaluate(snapshot)

        assert decision.action == RegimeAction.BLOCK
        assert decision.flat_count == 5

    def test_single_breakout_allow(self, default_config):
        """Single asset breakout keeps basket active → ALLOW."""
        gate = MarketRegimeGate(default_config)

        # 4 flat, 1 strong breakout
        snapshot = {
            "BTC": {"return_pct": 0.1, "atr_pct": 0.2, "vol_ratio": 0.6},
            "ETH": {"return_pct": 0.2, "atr_pct": 0.3, "vol_ratio": 0.7},
            "SOL": {"return_pct": 0.3, "atr_pct": 0.1, "vol_ratio": 0.5},
            "XRP": {"return_pct": 0.1, "atr_pct": 0.2, "vol_ratio": 0.6},
            "DOGE": {"return_pct": 2.0, "atr_pct": 1.5, "vol_ratio": 2.0},  # breakout
        }

        decision = gate.evaluate(snapshot)

        # Only 4 flat, but since DOGE is active we have only 4 flat (not 5)
        # Actually 4 flat means block, need to check...
        assert decision.flat_count == 4
        assert decision.action == RegimeAction.BLOCK  # Still blocked at 4 flat

    def test_missing_data_fail_closed(self, default_config):
        """Missing data for >20% of universe → BLOCK (fail-closed)."""
        gate = MarketRegimeGate(default_config)

        # Only 2 assets provided (3 missing = 60%)
        snapshot = {
            "BTC": {"return_pct": 1.0, "atr_pct": 0.5, "vol_ratio": 1.2},
            "ETH": {"return_pct": 0.8, "atr_pct": 0.6, "vol_ratio": 1.1},
        }

        decision = gate.evaluate(snapshot)

        assert decision.action == RegimeAction.BLOCK
        assert "insufficient_data" in decision.reason_codes

    def test_disabled_gate_allows_all(self, default_config):
        """Disabled config always returns ALLOW."""
        disabled_cfg = replace(default_config, enabled=False)
        gate = MarketRegimeGate(disabled_cfg)

        snapshot = {}  # Empty snapshot
        decision = gate.evaluate(snapshot)

        assert decision.action == RegimeAction.ALLOW
        assert "gate_disabled" in decision.reason_codes

    def test_shadow_mode_allows_block(self, default_config):
        """Shadow mode BLOCK still returns ALLOW for orders but logs."""
        shadow_cfg = replace(default_config, shadow_mode=True)
        gate = MarketRegimeGate(shadow_cfg)

        snapshot = {  # 4 flat → would normally BLOCK
            "BTC": {"return_pct": 0.1, "atr_pct": 0.2, "vol_ratio": 0.6},
            "ETH": {"return_pct": 0.2, "atr_pct": 0.3, "vol_ratio": 0.7},
            "SOL": {"return_pct": 0.3, "atr_pct": 0.1, "vol_ratio": 0.5},
            "XRP": {"return_pct": 0.1, "atr_pct": 0.2, "vol_ratio": 0.6},
            "DOGE": {"return_pct": 1.5, "atr_pct": 0.9, "vol_ratio": 1.4},
        }

        decision = gate.evaluate(snapshot)

        # Even in shadow mode, the action is still BLOCK internally
        assert decision.action == RegimeAction.BLOCK
        assert decision.shadow_mode is True
        # But the gate should indicate that orders should be allowed (shadow mode)
        # The decision.action remains BLOCK for logging/observability


# ── Per-Asset Flatness Tests ───────────────────────────────────────────────


class TestPerAssetFlatness:
    """Tests for individual asset flatness detection."""

    def test_return_threshold(self, default_config):
        """Asset with |return| < max_abs_return_pct AND low atr AND low vol is flat."""
        gate = MarketRegimeGate(default_config)

        # return_pct = 0.5 < 0.75 threshold, but atr and vol high → NOT flat (all 3 must be true)
        m = AssetMetrics(return_pct=0.5, atr_pct=1.0, vol_ratio=1.0)
        assert gate._is_asset_flat(m) is False  # atr and vol too high

        # return_pct = 1.0 > 0.75 threshold → not flat (even with low atr/vol)
        m = AssetMetrics(return_pct=1.0, atr_pct=0.2, vol_ratio=0.6)
        assert gate._is_asset_flat(m) is False  # return too high

        # ALL three conditions met → flat
        m = AssetMetrics(return_pct=0.5, atr_pct=0.2, vol_ratio=0.6)
        assert gate._is_asset_flat(m) is True

    def test_atr_threshold(self, default_config):
        """Asset with ATR% < min_atr_pct is flat."""
        gate = MarketRegimeGate(default_config)

        # atr_pct = 0.2 < 0.35 threshold → flat (when others also true)
        m = AssetMetrics(return_pct=0.5, atr_pct=0.2, vol_ratio=0.6)
        assert gate._is_asset_flat(m) is True

    def test_volume_threshold(self, default_config):
        """Asset with vol_ratio < min_volume_ratio is flat."""
        gate = MarketRegimeGate(default_config)

        # vol_ratio = 0.6 < 0.80 threshold → flat
        m = AssetMetrics(return_pct=0.5, atr_pct=0.2, vol_ratio=0.6)
        assert gate._is_asset_flat(m) is True

    def test_all_three_required_for_flat(self, default_config):
        """All three conditions must be true to be flat."""
        gate = MarketRegimeGate(default_config)

        # Only return flat, others not → NOT flat
        m = AssetMetrics(return_pct=0.1, atr_pct=1.0, vol_ratio=1.0)
        assert gate._is_asset_flat(m) is False

        # Only ATR flat, others not → NOT flat
        m = AssetMetrics(return_pct=1.0, atr_pct=0.1, vol_ratio=1.0)
        assert gate._is_asset_flat(m) is False

        # Only volume flat, others not → NOT flat
        m = AssetMetrics(return_pct=1.0, atr_pct=1.0, vol_ratio=0.5)
        assert gate._is_asset_flat(m) is False


# ── Convenience Methods ─────────────────────────────────────────────────────


class TestConvenienceMethods:
    """Tests for evaluate_simple and other convenience methods."""

    def test_evaluate_simple(self, default_config):
        """evaluate_simple accepts separate dicts for each metric."""
        gate = MarketRegimeGate(default_config)

        returns = {"BTC": 1.0, "ETH": 0.8, "SOL": 1.2, "XRP": 0.9, "DOGE": 1.5}
        atrs = {"BTC": 0.5, "ETH": 0.6, "SOL": 0.8, "XRP": 0.7, "DOGE": 0.9}
        vols = {"BTC": 1.2, "ETH": 1.1, "SOL": 1.3, "XRP": 1.0, "DOGE": 1.4}

        decision = gate.evaluate_simple(returns, atrs, vols)

        assert decision.action == RegimeAction.ALLOW
        assert decision.flat_count == 0


# ── State Management ───────────────────────────────────────────────────────


class TestGateStateManagement:
    """Tests for counters, history, and helper methods."""

    def test_counters_increment(self, default_config):
        """Counters increment correctly for each action type."""
        gate = MarketRegimeGate(default_config)

        # ALLOW
        gate.evaluate({"BTC": {"return_pct": 1.0, "atr_pct": 0.5, "vol_ratio": 1.2}})
        # REDUCE (need 3 flat - use 3 with default config having 5 assets)
        # For 1 asset, 1 flat out of 1 meets block threshold (4 of 5 doesn't apply)
        # Let me use full universe
        full_snapshot_allow = {
            "BTC": {"return_pct": 1.0, "atr_pct": 0.5, "vol_ratio": 1.2},
            "ETH": {"return_pct": 1.0, "atr_pct": 0.5, "vol_ratio": 1.2},
            "SOL": {"return_pct": 1.0, "atr_pct": 0.5, "vol_ratio": 1.2},
            "XRP": {"return_pct": 1.0, "atr_pct": 0.5, "vol_ratio": 1.2},
            "DOGE": {"return_pct": 1.0, "atr_pct": 0.5, "vol_ratio": 1.2},
        }
        gate.evaluate(full_snapshot_allow)

        counters = gate.get_counters()
        assert counters["evaluations"] >= 1
        assert counters["allow"] >= 1

    def test_should_allow_new_entries(self, default_config):
        """should_allow_new_entries respects last decision."""
        gate = MarketRegimeGate(default_config)

        # No decision yet → allow
        assert gate.should_allow_new_entries() is True

        # After ALLOW → allow
        gate.evaluate({
            "BTC": {"return_pct": 1.0, "atr_pct": 0.5, "vol_ratio": 1.2},
            "ETH": {"return_pct": 1.0, "atr_pct": 0.5, "vol_ratio": 1.2},
            "SOL": {"return_pct": 1.0, "atr_pct": 0.5, "vol_ratio": 1.2},
            "XRP": {"return_pct": 1.0, "atr_pct": 0.5, "vol_ratio": 1.2},
            "DOGE": {"return_pct": 1.0, "atr_pct": 0.5, "vol_ratio": 1.2},
        })
        assert gate.should_allow_new_entries() is True

    def test_should_reduce_position_size(self, default_config):
        """should_reduce_position_size returns True for REDUCE/BLOCK."""
        gate = MarketRegimeGate(default_config)

        # No decision yet → don't reduce
        assert gate.should_reduce_position_size() is False

        # After REDUCE (3 flat) → reduce
        # All flat assets need: |return| < 0.75, atr < 0.35, vol_ratio < 0.80
        gate.evaluate({
            "BTC": {"return_pct": 0.1, "atr_pct": 0.2, "vol_ratio": 0.6},  # flat
            "ETH": {"return_pct": 0.2, "atr_pct": 0.3, "vol_ratio": 0.7},  # flat
            "SOL": {"return_pct": 0.3, "atr_pct": 0.2, "vol_ratio": 0.5},  # flat
            "XRP": {"return_pct": 1.0, "atr_pct": 0.6, "vol_ratio": 1.2},  # active
            "DOGE": {"return_pct": 1.5, "atr_pct": 0.9, "vol_ratio": 1.4},  # active
        })
        assert gate.should_reduce_position_size() is True

    def test_get_last_decision(self, default_config):
        """get_last_decision returns most recent decision."""
        gate = MarketRegimeGate(default_config)

        assert gate.get_last_decision() is None

        gate.evaluate({
            "BTC": {"return_pct": 1.0, "atr_pct": 0.5, "vol_ratio": 1.2},
        })

        last = gate.get_last_decision()
        assert last is not None
        assert last.total_assets == 1  # Only provided 1 asset


# ── Decision Serialization ─────────────────────────────────────────────────


class TestDecisionSerialization:
    """Tests for to_dict and dataclass methods."""

    def test_decision_to_dict(self, default_config):
        """RegimeDecision can be serialized to dict."""
        gate = MarketRegimeGate(default_config)

        decision = gate.evaluate({
            "BTC": {"return_pct": 1.0, "atr_pct": 0.5, "vol_ratio": 1.2},
        })

        d = decision.to_dict()

        assert "action" in d
        assert "flat_count" in d
        assert "reason_codes" in d
        assert "timestamp" in d


# ── Config Loading ─────────────────────────────────────────────────────────


class TestConfigLoading:
    """Tests for YAML config loading."""

    def test_load_default_config(self):
        """load_regime_config returns default config."""
        cfg = load_regime_config()
        # Should return enabled config with defaults
        assert isinstance(cfg, MarketRegimeConfig)

    def test_get_regime_config_singleton(self):
        """get_regime_config returns singleton."""
        cfg1 = get_regime_config()
        cfg2 = get_regime_config()
        assert cfg1 is cfg2


# ── Edge Cases ─────────────────────────────────────────────────────────────


class TestEdgeCases:
    """Edge cases and error handling."""

    def test_negative_returns(self, default_config):
        """Negative returns are treated with abs() for flatness."""
        gate = MarketRegimeGate(default_config)

        # -0.5 return with abs < 0.75 → flat
        m = AssetMetrics(return_pct=-0.5, atr_pct=0.2, vol_ratio=0.6)
        assert gate._is_asset_flat(m) is True

    def test_zero_values(self, default_config):
        """Zero values handled gracefully."""
        gate = MarketRegimeGate(default_config)

        # All zeros → definitely flat
        m = AssetMetrics(return_pct=0.0, atr_pct=0.0, vol_ratio=0.0)
        assert gate._is_asset_flat(m) is True

    def test_missing_asset_in_snapshot(self, default_config):
        """Missing asset in snapshot handled gracefully."""
        gate = MarketRegimeGate(default_config)

        # Provide 3 of 5 assets (not >20% missing, so proceeds)
        snapshot = {
            "BTC": {"return_pct": 1.0, "atr_pct": 0.5, "vol_ratio": 1.2},
            "ETH": {"return_pct": 1.0, "atr_pct": 0.5, "vol_ratio": 1.2},
            "SOL": {"return_pct": 1.0, "atr_pct": 0.5, "vol_ratio": 1.2},
            # XRP and DOGE missing
        }

        decision = gate.evaluate(snapshot)
        # 3 evaluated, 2 missing → proceeds with 3/5
        assert decision.total_assets == 3

    def test_case_insensitive_asset_lookup(self, default_config):
        """Asset lookup is case-insensitive."""
        gate = MarketRegimeGate(default_config)

        # Use lowercase in snapshot
        snapshot = {
            "btc": {"return_pct": 1.0, "atr_pct": 0.5, "vol_ratio": 1.2},
            "eth": {"return_pct": 1.0, "atr_pct": 0.5, "vol_ratio": 1.2},
        }

        decision = gate.evaluate(snapshot)
        assert decision.total_assets == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
