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

    def test_distance_params_aligned(self):
        """Verify max_delta_pct matches strike selector ranges"""
        with open("c:/Dev/MERID/config/kalshi_distance.yaml", "r", encoding="utf-8") as f:
            distance_cfg = yaml.safe_load(f)

        assert distance_cfg["max_delta_pct"]["BTC"] == 0.04
        assert distance_cfg["max_delta_pct"]["ETH"] == 0.05
        assert distance_cfg["max_delta_pct"]["SOL"] == 0.06
        assert distance_cfg["max_delta_pct"]["DOGE"] == 0.065

    def test_entry_window_expanded(self):
        """Verify entry windows provide adequate time for indicator confirmation"""
        with open("c:/Dev/MERID/config/kalshi_agent_grid.yaml", "r", encoding="utf-8") as f:
            agent_cfg = yaml.safe_load(f)

        # Find BTC_15M agent
        btc_agent = next((a for a in agent_cfg["agents"] if a["name"] == "BTC_15M"), None)
        assert btc_agent is not None

        # BTC/ETH should have 9min window (12-3)
        btc_window = (
            btc_agent["entry_window"]["minutes_before_expiry"]
            - btc_agent["entry_window"]["cutoff_minutes_before_expiry"]
        )
        assert btc_window == 9

        # Find SOL_15M agent
        sol_agent = next((a for a in agent_cfg["agents"] if a["name"] == "SOL_15M"), None)
        assert sol_agent is not None

        # SOL/XRP/DOGE should have 10min window (13-3)
        sol_window = (
            sol_agent["entry_window"]["minutes_before_expiry"]
            - sol_agent["entry_window"]["cutoff_minutes_before_expiry"]
        )
        assert sol_window == 10

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

    def test_take_profit_dynamic_by_time(self):
        """Verify dynamic TP based on time remaining"""
        with open("c:/Dev/MERID/config/kalshi_agent_grid.yaml", "r", encoding="utf-8") as f:
            agent_cfg = yaml.safe_load(f)

        # Find BTC_15M agent
        btc_agent = next((a for a in agent_cfg["agents"] if a["name"] == "BTC_15M"), None)
        assert btc_agent is not None

        tp = btc_agent["take_profit"]["time_based_r_multiple"]

        assert tp["over_7_min"] > tp["between_4_7_min"] > tp["under_4_min"]
        assert tp["under_4_min"] == 0.15  # Fast exit near expiry

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

    def test_trailing_activation_reduced(self):
        """Verify trailing activation R-multiple reduced from 0.5 to 0.3"""
        with open("c:/Dev/MERID/config/kalshi_agent_grid.yaml", "r", encoding="utf-8") as f:
            agent_cfg = yaml.safe_load(f)

        # Check all 15m agents have trailing_activation_r_multiple: 0.3
        for agent in agent_cfg["agents"]:
            if agent["name"].endswith("_15M"):
                assert agent["take_profit"]["trailing_activation_r_multiple"] == 0.3
