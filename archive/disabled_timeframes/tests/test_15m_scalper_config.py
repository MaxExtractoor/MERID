"""Test suite for 15m scalper mode configuration consistency.

This test validates that all configuration files and code are aligned
for 15m momentum scalping mode with 3%/8% unified risk regime across all modes.

Usage:
    py -m pytest tests/test_15m_scalper_config.py -v
"""

import os
import pytest
from decimal import Decimal


class Test15mScalperConfig:
    """Validate 15m scalper configuration across all components."""

    def test_strategy_mode_env_var_set(self):
        """STRATEGY_MODE must be set to MOMENTUM_SCALPER for scalper mode."""
        mode = os.getenv("STRATEGY_MODE", "").upper()
        assert mode == "MOMENTUM_SCALPER", \
            f"STRATEGY_MODE must be MOMENTUM_SCALPER, got: {mode}"

    def test_max_cycle_risk_pct_is_3_percent(self):
        """MAX_CYCLE_RISK_PCT should be 0.03 (3%) - unified across all modes."""
        from core.settings import MAX_CYCLE_RISK_PCT
        assert MAX_CYCLE_RISK_PCT == 0.03, \
            f"MAX_CYCLE_RISK_PCT should be 3% (0.03), got: {MAX_CYCLE_RISK_PCT}"

    def test_scalper15m_bankroll_pct_is_3_percent(self):
        """SCALPER15M_BANKROLL_PCT should be 3% - unified with MAX_CYCLE_RISK_PCT."""
        from core.settings import SCALPER15M_BANKROLL_PCT
        assert SCALPER15M_BANKROLL_PCT == 0.03, \
            f"SCALPER15M_BANKROLL_PCT should be 3% (0.03), got: {SCALPER15M_BANKROLL_PCT}"

    def test_kalshi_distance_min_edge_near(self):
        """BTC near edge should be <= 3% for scalper mode."""
        from merid.prediction.kalshi_distance_config import get_min_edge
        btc_near = get_min_edge("BTC", is_far=False)
        assert btc_near <= 0.030, \
            f"BTC near edge too high: {btc_near} (expected <= 0.030)"

    def test_sizing_constraints_use_3_percent(self):
        """Sizing constraints should use 3% exposure - unified with MAX_CYCLE_RISK_PCT."""
        from merid.prediction.config_validator import ScalperConfig
        cfg = ScalperConfig()
        assert cfg.sizing_constraints.max_15m_exposure_pct == 3.0, \
            f"max_15m_exposure_pct should be 3%, got: {cfg.sizing_constraints.max_15m_exposure_pct}"

    def test_crypto_threshold_matrix_15m_edge(self):
        """15m edge threshold should be relaxed for scalper mode."""
        from merid.prediction.crypto_threshold_matrix import get_crypto_threshold_row
        row = get_crypto_threshold_row("BTC", "15m", "directional")
        edge = float(row.get("directional_min_edge", 0.04))
        assert edge <= 0.035, \
            f"BTC 15m edge too high: {edge} (expected <= 0.035 for scalper)"

    def test_trader_config_risk_pct(self):
        """CT trader config should use 3% risk - unified with MAX_CYCLE_RISK_PCT."""
        from merid.trading.kalshi_continuous_trader import TraderConfig
        config = TraderConfig.from_env()
        assert config.max_risk_per_trade_pct == 0.03, \
            f"CT max_risk_per_trade_pct should be 3%, got: {config.max_risk_per_trade_pct}"

    def test_topn_allocator_config(self):
        """TopN allocator should use 3% cycle risk - unified with MAX_CYCLE_RISK_PCT."""
        from merid.trading.topn_allocator import TopNAllocatorConfig
        config = TopNAllocatorConfig.from_env()
        assert config.max_cycle_risk_pct == 0.03, \
            f"TopN max_cycle_risk_pct should be 3%, got: {config.max_cycle_risk_pct}"

    def test_env_vars_present(self):
        """All critical env vars should be present."""
        required = [
            "STRATEGY_MODE",
            "MAX_CYCLE_RISK_PCT",
            "MAX_CONTRACTS_PER_TF_CRYPTO_15M",
            "TOPN_MAX_CYCLE_RISK_PCT",
        ]
        missing = [var for var in required if not os.getenv(var)]
        assert not missing, f"Missing required env vars: {missing}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
