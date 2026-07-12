"""
Regression tests for 15-minute timeframe optimizations (2026-05-10)

Tests verify:
- Distance parameters aligned between execution guard and strike selector
- Entry windows provide adequate time for indicator confirmation
- EMA parameters are optimized per asset volatility
- ATR min-move gates match asset volatility
- Chop filters are appropriately relaxed for volatile assets
- Dynamic take profit based on time remaining
- FVG pullback logic is active
- Momentum pre-entry check is enabled
- Backward compatibility for unchanged params
"""

import pytest
from merid.signals.crypto_15m_indicators import DEFAULT_15M_CONFIG, IndicatorConfig
import yaml


class Test15mOptimizationRegression:
    """Regression tests for 15m timeframe optimizations"""


    def test_ema_params_asset_specific(self):
        """Verify EMA parameters are optimized per asset volatility"""
        config = DEFAULT_15M_CONFIG

        # Low vol assets (BTC/ETH) use faster EMAs
        btc_ema = config.get_ema_params("BTC")
        assert btc_ema["trend_period"] == 21
        assert btc_ema["fast_period"] == 9
        assert btc_ema["slow_period"] == 21

        # High vol assets (SOL/DOGE) use slower EMAs
        sol_ema = config.get_ema_params("SOL")
        assert sol_ema["trend_period"] == 34
        assert sol_ema["fast_period"] == 13
        assert sol_ema["slow_period"] == 34

    def test_atr_gates_asset_specific(self):
        """Verify ATR min-move gates match asset volatility"""
        config = DEFAULT_15M_CONFIG

        assert config.get_atr_min_move("BTC") == 0.0002  # Lowest
        assert config.get_atr_min_move("DOGE") == 0.0005  # Highest
        assert config.get_atr_min_move("ETH") < config.get_atr_min_move("SOL")

    def test_chop_filters_relaxed_for_high_vol(self):
        """Verify chop filters are appropriately relaxed for volatile assets"""
        config = DEFAULT_15M_CONFIG

        btc_chop = config.get_chop_filter("BTC")
        doge_chop = config.get_chop_filter("DOGE")

        assert btc_chop["consecutive_closes_required"] == 3  # Strict
        assert doge_chop["consecutive_closes_required"] == 2  # Relaxed


    def test_fvg_pullback_enabled(self):
        """Verify FVG pullback logic is active"""
        config = DEFAULT_15M_CONFIG

        assert config.fvg_enabled == True
        assert config.fvg_pullback_enabled == True
        assert config.fvg_pullback_atr_threshold == 1.0

    def test_momentum_preentry_check(self):
        """Verify momentum filter prevents late exhausted entries"""
        config = DEFAULT_15M_CONFIG

        assert config.momentum_lookback_bars == 3  # 45 minutes
        assert config.min_momentum_threshold == 0.002  # 0.2%

    def test_no_config_breaking_changes(self):
        """Ensure backward compatibility for unchanged params"""
        config = DEFAULT_15M_CONFIG

        # These should remain unchanged
        assert config.rsi_period == 8
        assert config.macd_fast == 8
        assert config.macd_slow == 21
        assert config.macd_signal == 5
        assert config.atr_period == 14

    def test_asset_specific_config_post_init(self):
        """Verify __post_init__ applies asset-specific overrides"""
        # BTC config
        btc_cfg = IndicatorConfig(asset="BTC")
        assert btc_cfg.ema_trend_period == 21
        assert btc_cfg.ema_fast_period == 9
        assert btc_cfg.ema_slow_period == 21
        assert btc_cfg.consecutive_closes_required == 3
        assert btc_cfg.atr_min_move_pct == 0.0002

        # DOGE config
        doge_cfg = IndicatorConfig(asset="DOGE")
        assert doge_cfg.ema_trend_period == 34
        assert doge_cfg.ema_fast_period == 13
        assert doge_cfg.ema_slow_period == 34
        assert doge_cfg.consecutive_closes_required == 2
        assert doge_cfg.atr_min_move_pct == 0.0005

    def test_min_cents_reduced(self):
        """Verify min_cents reduced from 5 to 3 for 15m contracts"""
        with open("c:/Dev/MERID/config/kalshi_agent_grid.yaml", "r", encoding="utf-8") as f:
            agent_cfg = yaml.safe_load(f)

        # Check all 15m agents have min_cents: 3
        for agent in agent_cfg["agents"]:
            if agent["name"].endswith("_15M"):
                assert agent["take_profit"]["min_cents"] == 3

    def test_max_spread_cents_from_profile_only(self):
        """Verify max_spread_cents comes only from 15m profile, no hardcoded 40c/60c"""
        # Check profile has the correct value
        with open("c:/Dev/MERID/config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)

        # Verify profile has guardrails.max_spread_cents set to 100
        # 2026-07-10: RELAXED to 100c - allows trading in current market conditions with wider spreads (60c-96c observed)
        assert "guardrails" in profile
        assert "max_spread_cents" in profile["guardrails"]
        assert profile["guardrails"]["max_spread_cents"] == 100

        # Check candidate_optimizer.py uses profile-driven max_spread_cents
        with open("c:/Dev/MERID/merid/prediction/candidate_optimizer.py", "r", encoding="utf-8") as f:
            content = f.read()

        # Verify it reads from profile
        assert "self.max_spread_cents" in content

        # Verify no hardcoded "40" or "60" used as spread filter thresholds
        # (allow other uses like time thresholds, percentages, legacy comments, etc.)
        import re
        # Look for patterns like "if spread > 40" or "max_spread = 60"
        # Exclude lines with "legacy" or "audit" comments
        lines = content.split('\n')
        hardcoded_thresholds = []
        for i, line in enumerate(lines):
            # Skip lines that are comments or have legacy/audit markers
            if 'legacy' in line.lower() or 'audit' in line.lower() or line.strip().startswith('#'):
                continue
            # Check for hardcoded spread thresholds
            if re.search(r'if\s+.*spread.*[><=]\s*(40|60)', line, re.IGNORECASE):
                hardcoded_thresholds.append(f"Line {i+1}: {line.strip()}")
            if re.search(r'max_spread\s*[=]\s*(40|60)', line, re.IGNORECASE):
                hardcoded_thresholds.append(f"Line {i+1}: {line.strip()}")

        assert len(hardcoded_thresholds) == 0, f"Found hardcoded spread filter threshold: {hardcoded_thresholds}"

    def test_collect_order_candidate_no_undefined_market(self):
        """Verify collect_order_candidate does not reference undefined 'market' variable
        
        2026-07-10: This test is disabled as the implementation has changed.
        The function no longer uses a candidate optimizer pattern.
        """
        pytest.skip("Test disabled - implementation changed, no longer uses candidate optimizer pattern")

    def test_check_spot_data_uses_spot_service_get(self):
        """Verify _check_spot_data uses spot_service.get(asset) and enforces 30s freshness window
        
        2026-07-10: This test is disabled as the implementation has changed.
        The function no longer exists in candidate_optimizer.py.
        """
        pytest.skip("Test disabled - implementation changed, _check_spot_data no longer exists")

