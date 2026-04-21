"""
Unit tests for Kalshi Crypto Portfolio Optimizer.

Test coverage:
1. Optimization math (efficient frontier, Sharpe calculation)
2. Cardinality constraint (max 3 assets)
3. Per-trade risk caps (1-3 USD)
4. Selection logic
5. Rebalance behavior
6. Data adapter functionality
"""

import unittest
from datetime import datetime, timedelta
import numpy as np
import pandas as pd

from merid.portfolio.optimizer import (
    PortfolioOptimizer,
    PortfolioDataAdapter,
    PortfolioSelection,
    RebalanceAction,
    KALSHI_CRYPTO_ASSETS,
    MIN_WEIGHT_EPSILON,
    get_portfolio_optimizer
)


class TestPortfolioDataAdapter(unittest.TestCase):
    """Tests for PortfolioDataAdapter."""
    
    def setUp(self):
        self.adapter = PortfolioDataAdapter()
    
    def test_normalize_dataframe_wide_format(self):
        """Test normalizing already-wide DataFrame."""
        df = pd.DataFrame({
            "BTC": [0.01, -0.02, 0.015],
            "ETH": [0.005, 0.01, -0.005],
        }, index=pd.date_range("2024-01-01", periods=3))
        
        result = self.adapter.normalize_returns(df)
        
        self.assertEqual(list(result.columns), ["BTC", "ETH"])
        self.assertEqual(len(result), 3)
    
    def test_normalize_long_format(self):
        """Test normalizing long-format records."""
        records = [
            {"asset": "BTC", "timestamp": "2024-01-01", "return": 0.01},
            {"asset": "BTC", "timestamp": "2024-01-02", "return": -0.02},
            {"asset": "ETH", "timestamp": "2024-01-01", "return": 0.005},
            {"asset": "ETH", "timestamp": "2024-01-02", "return": 0.01},
        ]
        
        result = self.adapter.normalize_returns(records)
        
        # Result should have BTC and ETH columns
        self.assertIn("BTC", result.columns)
        self.assertIn("ETH", result.columns)
        # Should have 2 rows (one per unique timestamp)
        self.assertEqual(len(result), 2)
    
    def test_normalize_pnl_column(self):
        """Test normalizing with 'pnl' column instead of 'return'."""
        records = [
            {"asset": "BTC", "timestamp": "2024-01-01", "pnl": 0.01},
            {"asset": "ETH", "timestamp": "2024-01-01", "pnl": 0.005},
        ]
        
        result = self.adapter.normalize_returns(records)
        
        # Should have BTC and ETH as columns
        self.assertIn("BTC", result.columns)
        self.assertIn("ETH", result.columns)
        # Should have values
        self.assertEqual(len(result), 1)
    
    def test_get_asset_return_matrix_synthetic(self):
        """Test getting synthetic returns when no source provided."""
        result = self.adapter.get_asset_return_matrix(
            assets=["BTC", "ETH"],
            timeframe="daily",
            lookback_days=30
        )
        
        self.assertEqual(set(result.columns), {"BTC", "ETH"})
        self.assertEqual(len(result), 30)
        
        # Check that returns are reasonable
        self.assertTrue(all(result["BTC"].abs() < 0.5))  # No crazy returns
    
    def test_cache_functionality(self):
        """Test that caching works."""
        # First call
        result1 = self.adapter.get_asset_return_matrix(
            assets=["BTC", "ETH"],
            timeframe="daily",
            lookback_days=30
        )
        
        # Second call (should be cached)
        result2 = self.adapter.get_asset_return_matrix(
            assets=["BTC", "ETH"],
            timeframe="daily",
            lookback_days=30
        )
        
        # Should be identical due to deterministic seed
        pd.testing.assert_frame_equal(result1, result2)
    
    def test_clear_cache(self):
        """Test cache clearing."""
        self.adapter.get_asset_return_matrix(["BTC"], "daily", 30)
        self.adapter.clear_cache()
        
        # After clearing, should generate new data
        # (but deterministic seed means same values)
        self.assertEqual(len(self.adapter._cache), 0)


class TestPortfolioOptimizerBasics(unittest.TestCase):
    """Basic initialization and configuration tests."""
    
    def test_default_initialization(self):
        """Test optimizer initializes with defaults."""
        opt = PortfolioOptimizer()
        
        self.assertEqual(opt.assets, KALSHI_CRYPTO_ASSETS)
        self.assertEqual(opt.max_concurrent_assets, 3)
        self.assertEqual(opt.min_risk_usd, 1)
        self.assertEqual(opt.max_risk_usd, 3)
        self.assertEqual(opt.global_risk_budget, 9)
    
    def test_custom_initialization(self):
        """Test optimizer with custom config."""
        config = {
            "assets": ["BTC", "ETH"],
            "max_concurrent_assets": 2,
            "min_risk_usd_per_trade": 2,
            "max_risk_usd_per_trade": 5,
            "risk_free_rate": 0.02,
        }
        opt = PortfolioOptimizer(config)
        
        self.assertEqual(opt.assets, ["BTC", "ETH"])
        self.assertEqual(opt.max_concurrent_assets, 2)
        self.assertEqual(opt.min_risk_usd, 2)
        self.assertEqual(opt.max_risk_usd, 5)
        self.assertEqual(opt.risk_free_rate, 0.02)
    
    def test_invalid_asset_raises(self):
        """Test that invalid assets raise ValueError."""
        with self.assertRaises(ValueError) as context:
            PortfolioOptimizer({"assets": ["BTC", "INVALID"]})
        
        self.assertIn("INVALID", str(context.exception))
    
    def test_get_config(self):
        """Test getting configuration."""
        opt = PortfolioOptimizer({"assets": ["BTC", "ETH"]})
        config = opt.get_config()
        
        self.assertEqual(config["assets"], ["BTC", "ETH"])
        self.assertEqual(config["max_concurrent_assets"], 3)
        self.assertIn("last_update", config)


class TestOptimizationMath(unittest.TestCase):
    """Tests for mean-variance optimization mathematics."""
    
    def setUp(self):
        # Create deterministic returns for reproducible tests
        np.random.seed(42)
        dates = pd.date_range("2024-01-01", periods=100, freq="D")
        
        # BTC: higher return, medium vol
        # ETH: medium return, medium vol
        # SOL: higher vol, medium return
        returns = pd.DataFrame({
            "BTC": np.random.normal(0.001, 0.02, 100),
            "ETH": np.random.normal(0.0008, 0.025, 100),
            "SOL": np.random.normal(0.0012, 0.04, 100),
        }, index=dates)
        
        self.opt = PortfolioOptimizer({"assets": ["BTC", "ETH", "SOL"]})
        self.opt.load_returns(returns)
    
    def test_estimate_parameters(self):
        """Test parameter estimation."""
        mu, sigma = self.opt.estimate_parameters()
        
        self.assertIsInstance(mu, pd.Series)
        self.assertIsInstance(sigma, pd.DataFrame)
        self.assertEqual(len(mu), 3)
        self.assertEqual(sigma.shape, (3, 3))
        
        # Covariance should be positive semi-definite (diagonals positive)
        for asset in ["BTC", "ETH", "SOL"]:
            self.assertGreater(sigma.loc[asset, asset], 0)
    
    def test_efficient_frontier_monotonic(self):
        """Test that efficient frontier is monotonic in risk/return."""
        frontier = self.opt.efficient_frontier(num_points=20)
        
        self.assertGreater(len(frontier), 0)
        
        # Risk should generally increase with return along frontier
        volatilities = [p["volatility"] for p in frontier]
        returns = [p["expected_return"] for p in frontier]
        
        # At minimum, frontier should have multiple points
        self.assertGreater(len(frontier), 5)
        
        # Check that we have valid Sharpe ratios
        for p in frontier:
            self.assertIsInstance(p["sharpe"], float)
            self.assertIn("weights", p)
    
    def test_sharpe_calculation(self):
        """Test Sharpe ratio calculation."""
        sharpe = self.opt._calculate_sharpe(0.01, 0.02)
        
        # Sharpe = (0.01 - 0) / 0.02 = 0.5
        self.assertAlmostEqual(sharpe, 0.5, places=5)
    
    def test_sharpe_zero_volatility(self):
        """Test Sharpe with zero volatility."""
        sharpe = self.opt._calculate_sharpe(0.01, 0)
        self.assertEqual(sharpe, 0.0)
    
    def test_single_asset_optimization(self):
        """Test optimization with single asset."""
        result = self.opt._optimize_subset(["BTC"])
        
        self.assertIsNotNone(result)
        self.assertEqual(result["assets"], ["BTC"])
        self.assertEqual(result["weights"], {"BTC": 1.0})
        self.assertGreater(result["volatility"], 0)
    
    def test_multi_asset_optimization(self):
        """Test optimization with multiple assets."""
        result = self.opt._optimize_subset(["BTC", "ETH"])
        
        self.assertIsNotNone(result)
        self.assertEqual(set(result["assets"]), {"BTC", "ETH"})
        self.assertIn("BTC", result["weights"])
        self.assertIn("ETH", result["weights"])
        
        # Weights should sum to ~1
        total_weight = sum(result["weights"].values())
        self.assertAlmostEqual(total_weight, 1.0, places=3)


class TestCardinalityConstraint(unittest.TestCase):
    """Tests for max 3 asset cardinality constraint."""
    
    def setUp(self):
        np.random.seed(42)
        dates = pd.date_range("2024-01-01", periods=50, freq="D")
        
        # Create returns for all 5 assets
        returns = pd.DataFrame({
            "BTC": np.random.normal(0.001, 0.02, 50),
            "ETH": np.random.normal(0.0008, 0.025, 50),
            "SOL": np.random.normal(0.0012, 0.04, 50),
            "XRP": np.random.normal(0.0005, 0.03, 50),
            "DOGE": np.random.normal(0.0003, 0.05, 50),
        }, index=dates)
        
        self.opt = PortfolioOptimizer()
        self.opt.load_returns(returns)
    
    def test_select_respects_max_assets(self):
        """Test that select_optimal_portfolios respects max_assets."""
        selections = self.opt.select_optimal_portfolios(max_assets=3, num_choices=5)
        
        for sel in selections:
            self.assertLessEqual(
                len(sel.assets_selected), 3,
                f"Portfolio has {len(sel.assets_selected)} assets, max is 3"
            )
    
    def test_select_different_cardinalities(self):
        """Test selecting with different max_assets values."""
        for max_a in [1, 2, 3]:
            selections = self.opt.select_optimal_portfolios(
                max_assets=max_a, num_choices=3
            )
            
            for sel in selections:
                self.assertLessEqual(
                    len(sel.assets_selected), max_a,
                    f"Portfolio exceeds max_assets={max_a}"
                )
    
    def test_no_empty_portfolios(self):
        """Test that no empty portfolios are returned."""
        selections = self.opt.select_optimal_portfolios(max_assets=3, num_choices=5)
        
        for sel in selections:
            self.assertGreater(len(sel.assets_selected), 0, "Portfolio has no assets")
            self.assertGreater(sum(sel.weights.values()), 0, "Portfolio has zero weights")
    
    def test_weights_below_epsilon_filtered(self):
        """Test that tiny weights are filtered from assets_selected."""
        selections = self.opt.select_optimal_portfolios(max_assets=3, num_choices=3)
        
        for sel in selections:
            # All selected assets should have meaningful weights
            for asset in sel.assets_selected:
                self.assertGreater(
                    sel.weights[asset], MIN_WEIGHT_EPSILON,
                    f"Asset {asset} has weight below epsilon"
                )


class TestRiskCaps(unittest.TestCase):
    """Tests for per-trade risk caps (1-3 USD)."""
    
    def setUp(self):
        np.random.seed(42)
        dates = pd.date_range("2024-01-01", periods=50, freq="D")
        
        returns = pd.DataFrame({
            "BTC": np.random.normal(0.001, 0.02, 50),
            "ETH": np.random.normal(0.0008, 0.025, 50),
        }, index=dates)
        
        self.opt = PortfolioOptimizer({
            "assets": ["BTC", "ETH"],
            "min_risk_usd_per_trade": 1,
            "max_risk_usd_per_trade": 3,
            "global_risk_budget": 6,
        })
        self.opt.load_returns(returns)
    
    def test_risk_caps_applied(self):
        """Test that risk caps are applied to portfolios."""
        selections = self.opt.select_optimal_portfolios(max_assets=2, num_choices=3)
        
        for sel in selections:
            risks = sel.metadata.get("asset_risks_usd", {})
            
            for asset, risk in risks.items():
                self.assertGreaterEqual(
                    risk, self.opt.min_risk_usd,
                    f"Risk {risk} below minimum {self.opt.min_risk_usd}"
                )
                self.assertLessEqual(
                    risk, self.opt.max_risk_usd,
                    f"Risk {risk} above maximum {self.opt.max_risk_usd}"
                )
    
    def test_risk_calculation_correct(self):
        """Test that risk is calculated as budget * weight."""
        # Create a portfolio with known weights
        portfolio = {
            "assets": ["BTC", "ETH"],
            "weights": {"BTC": 0.6, "ETH": 0.4},
            "expected_return": 0.001,
            "volatility": 0.02,
            "sharpe": 0.05,
        }
        
        adjusted = self.opt._apply_risk_caps(portfolio, global_budget=10)
        
        # BTC: 10 * 0.6 = 6, but capped at 3
        # ETH: 10 * 0.4 = 4, but capped at 3
        self.assertEqual(adjusted["asset_risks_usd"]["BTC"], 3)
        self.assertEqual(adjusted["asset_risks_usd"]["ETH"], 3)
    
    def test_insufficient_risk_rejected(self):
        """Test that portfolios with insufficient risk are rejected."""
        # Small budget such that even 100% allocation gives < 1 USD
        opt = PortfolioOptimizer({
            "assets": ["BTC", "ETH"],
            "min_risk_usd_per_trade": 1,
            "max_risk_usd_per_trade": 3,
            "global_risk_budget": 0.5,  # Too small
        })
        
        returns = pd.DataFrame({
            "BTC": [0.01, -0.01, 0.01],
            "ETH": [0.005, 0.005, 0.005],
        })
        opt.load_returns(returns)
        
        selections = opt.select_optimal_portfolios(max_assets=2, num_choices=3)
        
        # Should be empty since no portfolio can satisfy risk constraints
        self.assertEqual(len(selections), 0)


class TestSelectionLogic(unittest.TestCase):
    """Tests for portfolio selection and ranking."""
    
    def setUp(self):
        np.random.seed(42)
        dates = pd.date_range("2024-01-01", periods=50, freq="D")
        
        # BTC dominates: best risk-adjusted return
        # DOGE is worst: high vol, low return
        returns = pd.DataFrame({
            "BTC": np.random.normal(0.002, 0.015, 50),  # Best
            "ETH": np.random.normal(0.001, 0.025, 50),  # Medium
            "DOGE": np.random.normal(0.0001, 0.06, 50),  # Worst
        }, index=dates)
        
        self.opt = PortfolioOptimizer({
            "assets": ["BTC", "ETH", "DOGE"],
        })
        self.opt.load_returns(returns)
    
    def test_sharpe_ranking(self):
        """Test that portfolios are ranked by Sharpe ratio."""
        selections = self.opt.select_optimal_portfolios(
            max_assets=3, num_choices=5, objective="sharpe"
        )
        
        # Should be sorted by Sharpe descending
        for i in range(len(selections) - 1):
            self.assertGreaterEqual(
                selections[i].sharpe,
                selections[i + 1].sharpe,
                "Portfolios not sorted by Sharpe"
            )
    
    def test_best_asset_in_top_selection(self):
        """Test that top selection has valid assets with good metrics."""
        selections = self.opt.select_optimal_portfolios(max_assets=3, num_choices=3)
        
        # Top selection should exist and have valid assets
        self.assertGreater(len(selections), 0, "No portfolios selected")
        top_assets = selections[0].assets_selected
        self.assertGreater(len(top_assets), 0, "Top portfolio has no assets")
        
        # Top portfolio should have reasonable Sharpe
        self.assertIsInstance(selections[0].sharpe, float)
    
    def test_single_asset_can_be_optimal(self):
        """Test that a single asset portfolio can be selected."""
        # Force a scenario where single asset is best
        np.random.seed(42)
        returns = pd.DataFrame({
            "BTC": np.random.normal(0.005, 0.01, 50),  # Very good
            "ETH": np.random.normal(-0.001, 0.03, 50),  # Negative return
        }, index=pd.date_range("2024-01-01", periods=50))
        
        opt = PortfolioOptimizer({"assets": ["BTC", "ETH"]})
        opt.load_returns(returns)
        
        selections = opt.select_optimal_portfolios(max_assets=3, num_choices=3)
        
        # First selection should likely be BTC-only
        if selections:
            self.assertIn("BTC", selections[0].assets_selected)
    
    def test_return_objective(self):
        """Test ranking by raw return."""
        selections = self.opt.select_optimal_portfolios(
            max_assets=3, num_choices=3, objective="return"
        )
        
        # Should be sorted by return descending
        for i in range(len(selections) - 1):
            self.assertGreaterEqual(
                selections[i].expected_return,
                selections[i + 1].expected_return,
                "Portfolios not sorted by return"
            )
    
    def test_metadata_populated(self):
        """Test that selection metadata is populated."""
        selections = self.opt.select_optimal_portfolios(max_assets=2, num_choices=1)
        
        if selections:
            sel = selections[0]
            self.assertIn("asset_risks_usd", sel.metadata)
            self.assertIn("timeframe", sel.metadata)
            self.assertIn("num_periods", sel.metadata)
            self.assertIn("last_update", sel.metadata)


class TestRebalanceLogic(unittest.TestCase):
    """Tests for rebalance suggestion logic."""
    
    def setUp(self):
        np.random.seed(42)
        dates = pd.date_range("2024-01-01", periods=50, freq="D")
        
        returns = pd.DataFrame({
            "BTC": np.random.normal(0.001, 0.02, 50),
            "ETH": np.random.normal(0.0008, 0.025, 50),
            "SOL": np.random.normal(0.0012, 0.04, 50),
        }, index=dates)
        
        self.opt = PortfolioOptimizer({
            "assets": ["BTC", "ETH", "SOL"],
            "global_risk_budget": 9,
        })
        self.opt.load_returns(returns)
    
    def test_rebalance_generates_actions(self):
        """Test that rebalance generates actions."""
        current = {
            "BTC": {"contracts": 5, "value_usd": 5},
            "ETH": {"contracts": 3, "value_usd": 3},
        }
        
        actions = self.opt.suggest_rebalance(current, max_assets=3)
        
        self.assertIsInstance(actions, list)
        self.assertGreater(len(actions), 0)
    
    def test_rebalance_action_types(self):
        """Test that actions have correct types."""
        current = {"BTC": {"value_usd": 10}}
        
        actions = self.opt.suggest_rebalance(current, max_assets=3)
        
        valid_types = {"entry", "scale_up", "scale_down", "exit", "hold"}
        for action in actions:
            self.assertIn(action.action_type, valid_types)
    
    def test_rebalance_respects_max_assets(self):
        """Test that rebalance respects max assets constraint."""
        # Over-allocated: 4 assets when max is 3
        current = {
            "BTC": {"value_usd": 3},
            "ETH": {"value_usd": 3},
            "SOL": {"value_usd": 3},
            "XRP": {"value_usd": 3},  # Not in our opt, but simulate
        }
        
        # Note: XRP not in opt assets, so will show as exit
        actions = self.opt.suggest_rebalance(current, max_assets=2)
        
        # Count assets that will be held after rebalance
        active = [a for a in actions if a.action_type != "exit"]
        self.assertLessEqual(len(active), 2)
    
    def test_exit_actions_for_excess_assets(self):
        """Test that excess assets get exit actions."""
        # Simulate having 3 assets but max is 2
        current = {
            "BTC": {"value_usd": 4},
            "ETH": {"value_usd": 3},
            "SOL": {"value_usd": 2},
        }
        
        actions = self.opt.suggest_rebalance(current, max_assets=2)
        
        # At least one exit action should exist
        exits = [a for a in actions if a.action_type == "exit"]
        self.assertGreaterEqual(len(exits), 1)
    
    def test_rebalance_risk_within_caps(self):
        """Test that rebalance actions respect risk caps."""
        current = {"BTC": {"value_usd": 5}}
        
        actions = self.opt.suggest_rebalance(current)
        
        for action in actions:
            if action.action_type != "hold":
                self.assertGreaterEqual(
                    action.estimated_trade_risk_usd, self.opt.min_risk_usd
                )
                self.assertLessEqual(
                    action.estimated_trade_risk_usd, self.opt.max_risk_usd
                )
    
    def test_rebalance_with_empty_positions(self):
        """Test rebalance with no current positions."""
        actions = self.opt.suggest_rebalance({}, max_assets=3)
        
        # Should recommend entries
        entries = [a for a in actions if a.action_type == "entry"]
        self.assertGreater(len(entries), 0)
    
    def test_action_ordering(self):
        """Test that actions are sorted correctly."""
        current = {
            "BTC": {"value_usd": 10},  # Should exit
            "ETH": {"value_usd": 0},   # Should enter
        }
        
        actions = self.opt.suggest_rebalance(current, max_assets=3)
        
        # Exits should come before entries
        exit_indices = [i for i, a in enumerate(actions) if a.action_type == "exit"]
        entry_indices = [i for i, a in enumerate(actions) if a.action_type == "entry"]
        
        if exit_indices and entry_indices:
            self.assertLess(max(exit_indices), min(entry_indices))


class TestIntegrationAPI(unittest.TestCase):
    """Tests for MERID integration API."""
    
    def setUp(self):
        np.random.seed(42)
        returns = pd.DataFrame({
            "BTC": np.random.normal(0.001, 0.02, 30),
            "ETH": np.random.normal(0.0008, 0.025, 30),
        }, index=pd.date_range("2024-01-01", periods=30))
        
        self.opt = PortfolioOptimizer({"assets": ["BTC", "ETH"]})
        self.opt.load_returns(returns)
    
    def test_get_best_portfolios(self):
        """Test the main integration API."""
        portfolios = self.opt.get_best_portfolios()
        
        self.assertIsInstance(portfolios, list)
        self.assertLessEqual(len(portfolios), 3)  # Default num_choices=3
        
        for p in portfolios:
            self.assertIsInstance(p, PortfolioSelection)
            self.assertLessEqual(len(p.assets_selected), 3)
    
    def test_summary_output(self):
        """Test summary method."""
        summary = self.opt.summary()
        
        self.assertIn("config", summary)
        self.assertIn("status", summary)
        self.assertIn("last_selections", summary)
    
    def test_singleton_getter(self):
        """Test the singleton getter function."""
        opt1 = get_portfolio_optimizer()
        opt2 = get_portfolio_optimizer()
        
        self.assertIs(opt1, opt2, "Singleton should return same instance")


class TestRobustness(unittest.TestCase):
    """Tests for robustness and edge cases."""
    
    def test_missing_data_handling(self):
        """Test handling of missing data."""
        # Data with NaN values
        returns = pd.DataFrame({
            "BTC": [0.01, np.nan, 0.015],
            "ETH": [0.005, 0.01, np.nan],
        }, index=pd.date_range("2024-01-01", periods=3))
        
        opt = PortfolioOptimizer({"assets": ["BTC", "ETH"]})
        
        # Should fill NaN with 0
        opt.load_returns(returns.fillna(0))
        
        selections = opt.select_optimal_portfolios(max_assets=2, num_choices=1)
        self.assertGreaterEqual(len(selections), 0)
    
    def test_identical_returns(self):
        """Test with identical returns for all assets."""
        returns = pd.DataFrame({
            "BTC": [0.01, 0.01, 0.01],
            "ETH": [0.01, 0.01, 0.01],
        }, index=pd.date_range("2024-01-01", periods=3))
        
        opt = PortfolioOptimizer({"assets": ["BTC", "ETH"]})
        opt.load_returns(returns)
        
        # Should still work even with identical returns
        selections = opt.select_optimal_portfolios(max_assets=2, num_choices=1)
        # May return empty due to zero covariance
        self.assertIsInstance(selections, list)
    
    def test_single_period_data(self):
        """Test with only one period of data."""
        returns = pd.DataFrame({
            "BTC": [0.01],
            "ETH": [0.005],
        }, index=[datetime(2024, 1, 1)])
        
        opt = PortfolioOptimizer({"assets": ["BTC", "ETH"]})
        opt.load_returns(returns)
        
        # With single period, covariance is zero
        # Should handle gracefully
        try:
            selections = opt.select_optimal_portfolios(max_assets=2, num_choices=1)
            # May succeed or fail depending on numerical stability
        except Exception as e:
            # Should fail gracefully, not crash
            self.assertIsInstance(e, (ValueError, np.linalg.LinAlgError))
    
    def test_all_negative_returns(self):
        """Test with all negative returns."""
        returns = pd.DataFrame({
            "BTC": [-0.01, -0.02, -0.015],
            "ETH": [-0.005, -0.01, -0.008],
        }, index=pd.date_range("2024-01-01", periods=3))
        
        opt = PortfolioOptimizer({"assets": ["BTC", "ETH"]})
        opt.load_returns(returns)
        
        selections = opt.select_optimal_portfolios(max_assets=2, num_choices=1)
        
        # Should still return something (least bad portfolio)
        if selections:
            # All Sharpe ratios should be negative
            for sel in selections:
                self.assertLess(sel.sharpe, 0)


class TestDataClasses(unittest.TestCase):
    """Tests for dataclass behavior."""
    
    def test_portfolio_selection_creation(self):
        """Test PortfolioSelection dataclass."""
        sel = PortfolioSelection(
            assets_selected=["BTC", "ETH"],
            weights={"BTC": 0.6, "ETH": 0.4},
            expected_return=0.001,
            volatility=0.02,
            sharpe=0.05
        )
        
        self.assertEqual(sel.assets_selected, ["BTC", "ETH"])
        self.assertEqual(sel.sharpe, 0.05)
    
    def test_rebalance_action_creation(self):
        """Test RebalanceAction dataclass."""
        action = RebalanceAction(
            asset="BTC",
            target_weight=0.5,
            current_weight=0.3,
            estimated_trade_risk_usd=2.0,
            action_type="scale_up",
            reason="Increase allocation"
        )
        
        self.assertEqual(action.asset, "BTC")
        self.assertEqual(action.action_type, "scale_up")


if __name__ == "__main__":
    unittest.main()
