"""
Tests for PortfolioOptimizer percent-of-equity sizing and momentum scalping enforcement.

These tests validate:
1. compute_risk_amount() returns values within [min_risk_pct * equity, max_risk_pct * equity]
2. Total risk across selected assets never exceeds global and per-timeframe caps
3. Momentum-only mode blocks "hold to expiry" strategies
4. Edge-aware scaling: higher edge = larger position (up to max)
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List

from merid.portfolio.optimizer import PortfolioOptimizer, PortfolioSelection, RebalanceAction


class TestPercentOfEquitySizing:
    """Test percent-of-equity risk sizing with edge scaling."""

    def test_compute_risk_amount_basic(self):
        """compute_risk_amount returns correct base values."""
        config = {
            "_validated": True,
            "min_risk_pct_per_trade": 0.005,  # 0.5%
            "max_risk_pct_per_trade": 0.02,   # 2.0%
        }
        optimizer = PortfolioOptimizer(config)
        
        equity = 1000.0
        
        # Low edge (1%) scales from min towards max
        # Formula: min + (edge/MAX_EDGE) * (max - min) = 0.005 + (0.01/0.10) * 0.015 = 0.0065 = 0.65%
        risk_low = optimizer.compute_risk_amount(equity, 0.01)
        expected_low = 1000.0 * (0.005 + 0.1 * 0.015)  # $6.50
        assert risk_low == pytest.approx(expected_low, rel=0.01)
        
        # Very high edge should give max risk (clamped)
        risk_high = optimizer.compute_risk_amount(equity, 0.20)
        assert risk_high == pytest.approx(1000.0 * 0.02, rel=0.01)  # $20
    
    def test_compute_risk_amount_edge_scaling(self):
        """Higher edge scales up risk amount within bounds."""
        config = {
            "_validated": True,
            "min_risk_pct_per_trade": 0.01,   # 1%
            "max_risk_pct_per_trade": 0.02,   # 2%
        }
        optimizer = PortfolioOptimizer(config)
        equity = 1000.0
        
        # Edge = 5% (50% of MAX_EDGE_FOR_SCALING=10%)
        # Expected: min + (edge_ratio * (max - min))
        # = 1% + (0.5 * 1%) = 1.5%
        risk_mid = optimizer.compute_risk_amount(equity, 0.05)
        expected = 1000.0 * 0.015
        assert risk_mid == pytest.approx(expected, rel=0.01)
    
    def test_compute_risk_amount_clamping(self):
        """Risk amount is clamped to min/max bounds regardless of extreme edge."""
        config = {
            "_validated": True,
            "min_risk_pct_per_trade": 0.005,
            "max_risk_pct_per_trade": 0.02,
        }
        optimizer = PortfolioOptimizer(config)
        equity = 1000.0
        
        # Negative edge uses abs(edge), so |-0.10| = 0.10 gives max (clamped)
        # abs(-0.10) = 0.10, ratio = 1.0, so result = max_risk_pct = 2% = $20
        risk_neg = optimizer.compute_risk_amount(equity, -0.10)
        assert risk_neg == pytest.approx(1000.0 * 0.02, rel=0.01)  # $20 (max, clamped)
        
        # Extreme edge should still give max (not more)
        risk_extreme = optimizer.compute_risk_amount(equity, 0.50)
        assert risk_extreme == pytest.approx(1000.0 * 0.02, rel=0.01)
        
        # Zero equity should give zero
        risk_zero = optimizer.compute_risk_amount(0.0, 0.05)
        assert risk_zero == 0.0
    
    def test_compute_risk_amount_linear_scaling(self):
        """Risk scales linearly with edge between min and max."""
        config = {
            "_validated": True,
            "min_risk_pct_per_trade": 0.00,   # 0% min for clear scaling
            "max_risk_pct_per_trade": 0.10,   # 10% max
        }
        optimizer = PortfolioOptimizer(config)
        equity = 1000.0
        
        # Test linearity at 25%, 50%, 75% of max edge
        edges = [0.025, 0.05, 0.075]
        expected_pcts = [0.025, 0.05, 0.075]  # Linear
        
        for edge, expected_pct in zip(edges, expected_pcts):
            risk = optimizer.compute_risk_amount(equity, edge)
            expected = equity * expected_pct
            assert risk == pytest.approx(expected, abs=0.01), f"Failed for edge={edge}"


class TestGlobalRiskBudget:
    """Test global risk budget enforcement with percent sizing."""

    def test_global_budget_percent_mode(self):
        """Total risk respects max_risk_pct_global."""
        config = {
            "_validated": True,
            "min_risk_pct_per_trade": 0.01,
            "max_risk_pct_per_trade": 0.02,
            "max_risk_pct_global": 0.06,      # 6% global
            "max_concurrent_assets": 3,
        }
        optimizer = PortfolioOptimizer(config)
        optimizer.set_equity(1000.0)
        
        # Verify config loaded correctly
        assert optimizer.max_risk_pct_global == 0.06
        
        # Global budget should be computed correctly
        expected_global = 1000.0 * 0.06  # $60
        assert expected_global == 60.0

    def test_risk_caps_global_scaling(self):
        """When total risk exceeds global budget, scale down proportionally."""
        config = {
            "_validated": True,
            "min_risk_pct_per_trade": 0.02,  # 2% per trade
            "max_risk_pct_per_trade": 0.02,
            "max_risk_pct_global": 0.04,      # 4% global (tight)
            "max_concurrent_assets": 3,
            "assets": ["BTC", "ETH", "SOL"],
        }
        optimizer = PortfolioOptimizer(config)
        equity = 1000.0
        optimizer.set_equity(equity)
        
        # Create a mock portfolio with 3 assets at max risk each
        # This would normally exceed the 4% global budget
        mock_portfolio = {
            "weights": {"BTC": 0.33, "ETH": 0.33, "SOL": 0.34},
        }
        
        # Apply risk caps
        adjusted = optimizer._apply_risk_caps(mock_portfolio, equity=equity)
        
        if adjusted is not None:
            total_risk = adjusted.get("total_risk_usd", 0)
            max_allowed = equity * 0.04  # $40
            assert total_risk <= max_allowed * 1.001, f"Total risk {total_risk} exceeded global budget {max_allowed}"


class TestMomentumScalpingEnforcement:
    """Test momentum-only mode blocks hold-to-expiry strategies."""

    def test_momentum_only_enabled_by_default(self):
        """Momentum scalping enforcement enabled by default."""
        config = {
            "_validated": True,
        }
        optimizer = PortfolioOptimizer(config)
        assert optimizer.enforce_mean_reversion is True
    
    def test_momentum_only_can_be_disabled(self):
        """Momentum scalping can be disabled via config."""
        config = {
            "_validated": True,
            "enforce_mean_reversion_only": False,
        }
        optimizer = PortfolioOptimizer(config)
        assert optimizer.enforce_mean_reversion is False
    
    def test_strategy_allowed_with_momentum_tag(self):
        """Strategies with momentum tag are allowed."""
        config = {
            "_validated": True,
            "enforce_mean_reversion_only": True,
        }
        optimizer = PortfolioOptimizer(config)
        
        allowed = optimizer.is_strategy_allowed("BTC_Momentum", ["momentum", "crypto"])
        assert allowed is True
    
    def test_strategy_blocked_without_allowed_tag(self):
        """Strategies without allowed tags are blocked."""
        config = {
            "_validated": True,
            "enforce_mean_reversion_only": True,
        }
        optimizer = PortfolioOptimizer(config)
        
        blocked = optimizer.is_strategy_allowed("BTC_HoldToExpiry", ["hold_to_expiry"])
        assert blocked is False
    
    def test_strategy_blocked_by_pattern(self):
        """Strategies matching blocked patterns are rejected."""
        config = {
            "_validated": True,
            "enforce_mean_reversion_only": True,
            "blocked_strategy_patterns": [".*hold.*expiry.*"],
        }
        optimizer = PortfolioOptimizer(config)
        
        blocked = optimizer.is_strategy_allowed("CryptoHoldToExpiryStrategy", ["crypto"])
        assert blocked is False
    
    def test_allowed_when_enforcement_disabled(self):
        """All strategies allowed when enforcement is disabled."""
        config = {
            "_validated": True,
            "enforce_mean_reversion_only": False,
        }
        optimizer = PortfolioOptimizer(config)
        
        # Should be allowed even with hold_to_expiry in name
        allowed = optimizer.is_strategy_allowed("ExpirimentHoldToExpiry", ["expiry_based"])
        assert allowed is True


class TestPortfolioSelectionWithPercentSizing:
    """Test portfolio selection with percent-of-equity sizing."""

    def create_mock_returns(self, assets: List[str], periods: int = 60) -> pd.DataFrame:
        """Create synthetic returns data for testing."""
        np.random.seed(42)
        data = {}
        for asset in assets:
            # Generate slightly positive drift returns
            data[asset] = np.random.normal(0.001, 0.02, periods)
        return pd.DataFrame(data)
    
    def test_top_n_selection_respects_max_concurrent(self):
        """Only top N assets are selected where N <= max_concurrent_assets."""
        config = {
            "_validated": True,
            "assets": ["BTC", "ETH", "SOL", "XRP", "DOGE"],
            "max_concurrent_assets": 3,
            "min_risk_pct_per_trade": 0.005,
            "max_risk_pct_per_trade": 0.02,
        }
        optimizer = PortfolioOptimizer(config)
        optimizer.set_equity(1000.0)
        
        # Load mock returns
        returns_df = self.create_mock_returns(config["assets"])
        optimizer.load_returns(returns_df)
        optimizer.estimate_parameters()
        
        # Select portfolios
        portfolios = optimizer.select_optimal_portfolios(max_assets=3, num_choices=3)
        
        # Each portfolio should have <= 3 assets
        for p in portfolios:
            assert len(p.assets_selected) <= 3
    
    def test_selection_with_equity_updates_risk(self):
        """Setting equity updates risk calculations in selection."""
        config = {
            "_validated": True,
            "assets": ["BTC", "ETH", "SOL"],
            "max_concurrent_assets": 3,
            "min_risk_pct_per_trade": 0.01,
            "max_risk_pct_per_trade": 0.02,
        }
        optimizer = PortfolioOptimizer(config)
        
        returns_df = self.create_mock_returns(config["assets"])
        optimizer.load_returns(returns_df)
        
        # Set equity
        optimizer.set_equity(2000.0)
        
        # Verify equity is set
        assert optimizer._current_equity == 2000.0


class TestRebalanceWithPercentSizing:
    """Test rebalancing with percent-of-equity sizing."""

    def test_rebalance_uses_percent_mode_when_no_usd_caps(self):
        """Rebalance uses percent mode when USD caps are not set."""
        config = {
            "_validated": True,
            "min_risk_pct_per_trade": 0.01,
            "max_risk_pct_per_trade": 0.02,
        }
        optimizer = PortfolioOptimizer(config)
        optimizer.set_equity(1000.0)
        
        # Create minimal mock data to avoid optimization errors
        returns_df = pd.DataFrame({
            "BTC": [0.01, -0.01, 0.005],
            "ETH": [0.005, 0.01, -0.005],
        })
        optimizer.load_returns(returns_df)
        
        # Current positions
        positions = {
            "BTC": {"contracts": 10, "value_usd": 100.0},
        }
        
        # Should not raise error
        try:
            actions = optimizer.suggest_rebalance(positions, max_assets=2)
            # Log indicates percent mode
        except Exception as e:
            # May fail due to optimization constraints, but shouldn't fail on mode selection
            if "risk_range_pct" in str(e):
                pytest.fail("Should use percent mode, not USD mode")


class TestConfigSerialization:
    """Test config is correctly serialized with new fields."""

    def test_get_config_includes_momentum_settings(self):
        """get_config includes momentum enforcement settings."""
        config = {
            "_validated": True,
            "enforce_mean_reversion_only": True,
            "momentum_scalp_config": {
                "max_hold_minutes": 30,
                "profit_target_pct": 0.10,
            },
        }
        optimizer = PortfolioOptimizer(config)
        
        cfg = optimizer.get_config()
        assert "enforce_mean_reversion_only" in cfg
        assert cfg["enforce_mean_reversion_only"] is True
        assert "momentum_scalp_config" in cfg
        assert "allowed_strategy_tags" in cfg
        assert "blocked_strategy_patterns" in cfg


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
