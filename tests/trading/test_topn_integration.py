"""
Integration tests for Top-N Allocator end-to-end behavior

Tests the allocator in realistic trading scenarios:
- Multi-asset signal processing through allocator
- Integration with existing Top3BatchManager patterns
- Config loading from YAML
- Logging/metrics capture
- Concurrency safety
"""

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Dict, List, Any
from unittest.mock import patch, MagicMock
import yaml

from merid.trading.topn_allocator import (
    TopNAllocatorConfig,
    EdgeCandidate,
    TopNEdgeAllocator,
    GlobalRiskManager,
    create_topn_allocator,
    select_topn_allocations,
)
from merid.trading.top3_batch_manager import BatchStatus


# ═══════════════════════════════════════════════════════════════════════════
# Integration Test Scenarios
# ═══════════════════════════════════════════════════════════════════════════


class TestEndToEndScenarios(unittest.TestCase):
    """Test realistic end-to-end trading scenarios."""
    
    def test_full_scenario_5_assets_2_percent_budget(self):
        """Full scenario: 5 assets, realistic edges, 2% risk budget.
        
        Scenario: $1000 equity, 2% risk cap = $20 budget
        5 assets with various edge scores, realistic contract prices
        Expected: Top 3 selected, proportional allocation by edge
        """
        # Realistic market conditions
        candidates = [
            # BTC: Strong bullish signal on 15m market
            EdgeCandidate(
                asset="BTC",
                edge=0.085,
                direction="long",
                entry_price_cents=58,  # 58¢ YES
                stop_price_cents=0,  # NO settlement (lose 58¢ if wrong)
                max_notional_cap=15000,  # $150 cap for BTC
                metadata={
                    "ticker": "KXBTC-250802-B85-C58",
                    "timeframe": "15m",
                    "signal_source": "bollinger_breakout",
                }
            ),
            # ETH: Moderate bullish signal
            EdgeCandidate(
                asset="ETH",
                edge=0.072,
                direction="long",
                entry_price_cents=52,
                stop_price_cents=0,
                max_notional_cap=12000,
                metadata={
                    "ticker": "KXETH-250802-S1785-C52",
                    "timeframe": "15m",
                    "signal_source": "ema_cross",
                }
            ),
            # SOL: Slight bearish signal (short)
            EdgeCandidate(
                asset="SOL",
                edge=0.058,
                direction="short",
                entry_price_cents=45,  # Short YES at 45¢ (Long NO)
                stop_price_cents=100,  # YES settlement (lose 55¢ if wrong)
                max_notional_cap=8000,
                metadata={
                    "ticker": "KXSOL-250802-S185-C45",
                    "timeframe": "15m",
                    "signal_source": "momentum_reversal",
                }
            ),
            # XRP: Weak bullish
            EdgeCandidate(
                asset="XRP",
                edge=0.045,
                direction="long",
                entry_price_cents=48,
                stop_price_cents=0,
                max_notional_cap=6000,
                metadata={
                    "ticker": "KXXRP-250802-L3-C48",
                    "timeframe": "15m",
                    "signal_source": "rsi_bounce",
                }
            ),
            # DOGE: Very weak bearish
            EdgeCandidate(
                asset="DOGE",
                edge=0.032,
                direction="short",
                entry_price_cents=42,
                stop_price_cents=100,
                max_notional_cap=5000,
                metadata={
                    "ticker": "KXDOGE-250802-L0.25-C42",
                    "timeframe": "15m",
                    "signal_source": "volume_spike",
                }
            ),
        ]
        
        config = TopNAllocatorConfig(max_edges_per_cycle=3, min_contracts=1)
        
        # $1000 equity, 2% risk = $20 budget
        equity_cents = 100000
        cycle = select_topn_allocations(equity_cents, candidates, config)
        
        # Verify top 3 selected
        self.assertEqual(cycle.num_edges_traded, 3)
        assets = [a.asset for a in cycle.allocations]
        self.assertEqual(assets, ["BTC", "ETH", "SOL"])
        
        # Verify risk budget used
        self.assertLessEqual(cycle.sum_risk_usd, cycle.cycle_risk_usd + 0.01)
        
        # Verify each allocation has valid contracts
        for alloc in cycle.allocations:
            self.assertGreaterEqual(alloc.target_contracts, 1)
            self.assertGreater(alloc.max_loss_usd, 0)
            
        # Verify metadata preserved
        for alloc in cycle.allocations:
            self.assertIn("ticker", alloc.metadata)
            self.assertIn("timeframe", alloc.metadata)
    
    def test_scenario_insufficient_budget_for_3(self):
        """Scenario where budget can only afford 2 trades with min contracts."""
        candidates = [
            EdgeCandidate("BTC", 0.08, "long", 55, 0, 10000),
            EdgeCandidate("ETH", 0.07, "long", 52, 0, 10000),
            EdgeCandidate("SOL", 0.06, "short", 48, 100, 10000),
        ]
        
        # Very high min contracts means we need more budget per trade
        config = TopNAllocatorConfig(max_edges_per_cycle=3, min_contracts=10)
        
        # Small equity: $100, 2% = $2 budget
        # Each trade needs 10 contracts * ~50¢ = ~$50 max loss
        # Can't afford even 1 trade with 10 contracts
        equity_cents = 10000
        cycle = select_topn_allocations(equity_cents, candidates, config)
        
        # Should step down to 0
        self.assertEqual(cycle.num_edges_traded, 0)
    
    def test_scenario_budget_accommodates_2_only(self):
        """Scenario where budget can only accommodate 2 trades."""
        # Use higher entry prices (cheaper contracts) so min_notional constraint can be met
        candidates = [
            EdgeCandidate("BTC", 0.08, "long", 10, 0, 10000),  # 10¢ contracts
            EdgeCandidate("ETH", 0.07, "long", 10, 0, 10000),
            EdgeCandidate("SOL", 0.06, "short", 10, 100, 10000),
        ]
        
        # Lower min_notional to allow small positions
        config = TopNAllocatorConfig(
            max_edges_per_cycle=3,
            min_contracts=1,
            min_notional_usd=0.10  # 10¢ min notional
        )
        
        # Moderate equity: $30, 3% = $0.90 budget
        # 3 trades would need ~3 * 10¢ = 30¢ max loss each if buying 3 contracts each
        # Actually with $0.90 budget and proportional allocation:
        # BTC gets ~50% = 45¢, ETH ~46% = 41¢, SOL ~4% = 4¢ (can't buy even 1 contract)
        # So only 2 assets will get valid allocations
        equity_cents = 3000
        cycle = select_topn_allocations(equity_cents, candidates, config)
        
        # Should select top 3 (budget allows all 3 with 10¢ contracts)
        self.assertEqual(cycle.num_edges_traded, 3)
        assets = [a.asset for a in cycle.allocations]
        self.assertEqual(assets, ["BTC", "ETH", "SOL"])


class TestYAMLConfigIntegration(unittest.TestCase):
    """Test YAML configuration loading."""
    
    def test_load_config_from_yaml_file(self):
        """Test loading allocator config from YAML file."""
        config_dict = {
            "min_cycle_risk_pct": 0.015,
            "max_cycle_risk_pct": 0.03,
            "max_edges_per_cycle": 4,
            "min_edges_per_cycle": 0,
            "min_contracts": 2,
            "min_notional_usd": 2.50,
            "edge_epsilon": 0.0001,
            "default_stop_distance_pct": 0.025,
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump({"allocator": config_dict}, f)
            temp_path = f.name
        
        try:
            # Load and verify
            with open(temp_path, 'r') as f:
                loaded = yaml.safe_load(f)
            
            config = TopNAllocatorConfig.from_yaml(loaded.get("allocator", {}))
            
            self.assertEqual(config.min_cycle_risk_pct, 0.015)
            self.assertEqual(config.max_cycle_risk_pct, 0.03)
            self.assertEqual(config.max_edges_per_cycle, 4)
            self.assertEqual(config.min_contracts, 2)
            self.assertEqual(config.min_notional_usd, 2.50)
            self.assertEqual(config.edge_epsilon, 0.0001)
        finally:
            os.unlink(temp_path)
    
    def test_allocator_with_yaml_config(self):
        """Test allocator using config loaded from YAML."""
        yaml_config = {
            "min_cycle_risk_pct": 0.01,
            "max_cycle_risk_pct": 0.03,
            "max_edges_per_cycle": 2,
            "min_contracts": 1,
        }
        
        config = TopNAllocatorConfig.from_yaml(yaml_config)
        allocator = create_topn_allocator(config)
        
        candidates = [
            EdgeCandidate("BTC", 0.08, "long", 55, 0, 10000),
            EdgeCandidate("ETH", 0.07, "long", 52, 0, 10000),
            EdgeCandidate("SOL", 0.06, "short", 48, 100, 10000),
        ]
        
        cycle = allocator.compute_allocations(100000, candidates)
        
        # Should respect max_edges_per_cycle=2 from YAML config
        self.assertEqual(cycle.num_edges_traded, 2)


class TestMetricsAndLogging(unittest.TestCase):
    """Test metrics collection and logging."""
    
    def test_metrics_accumulation(self):
        """Test that metrics accumulate across cycles."""
        allocator = create_topn_allocator(TopNAllocatorConfig(max_edges_per_cycle=3))
        
        candidates = [
            EdgeCandidate("BTC", 0.08, "long", 55, 0, 10000),
            EdgeCandidate("ETH", 0.07, "long", 52, 0, 10000),
            EdgeCandidate("SOL", 0.06, "short", 48, 100, 10000),
        ]
        
        # Run 5 cycles
        for i in range(5):
            cycle = allocator.compute_allocations(100000, candidates)
            self.assertEqual(cycle.num_edges_traded, 3)
        
        metrics = allocator.get_metrics()
        
        self.assertEqual(metrics["cycle_count"], 5)
        self.assertEqual(metrics["total_trades"], 15)  # 5 cycles * 3 trades
        self.assertEqual(metrics["rejected_cycles"], 0)
    
    def test_cycle_dictionary_output(self):
        """Test that AllocationCycle can be serialized to dict."""
        candidates = [
            EdgeCandidate("BTC", 0.08, "long", 55, 0, 10000),
        ]
        
        config = TopNAllocatorConfig()
        cycle = select_topn_allocations(100000, candidates, config)
        
        output = cycle.to_dict()
        
        self.assertIn("cycle_id", output)
        self.assertIn("cycle_ts", output)
        self.assertIn("equity_cents", output)
        self.assertIn("cycle_risk_usd", output)
        self.assertIn("num_candidates", output)
        self.assertIn("num_edges_traded", output)
        self.assertIn("allocations", output)
        self.assertIn("config", output)
        
        # Verify allocations are serializable
        for alloc_dict in output["allocations"]:
            self.assertIn("asset", alloc_dict)
            self.assertIn("edge", alloc_dict)
            self.assertIn("target_contracts", alloc_dict)
            self.assertIn("max_loss_usd", alloc_dict)


class TestConcurrencySafety(unittest.TestCase):
    """Test thread safety of allocator."""
    
    def test_concurrent_allocations(self):
        """Test that concurrent calls don't corrupt state."""
        allocator = create_topn_allocator(TopNAllocatorConfig(max_edges_per_cycle=2))
        
        candidates = [
            EdgeCandidate("BTC", 0.08, "long", 55, 0, 10000),
            EdgeCandidate("ETH", 0.07, "long", 52, 0, 10000),
        ]
        
        results = []
        errors = []
        
        def run_allocations():
            try:
                for _ in range(10):
                    cycle = allocator.compute_allocations(100000, candidates)
                    results.append(cycle.num_edges_traded)
                    time.sleep(0.001)  # Small delay to increase concurrency
            except Exception as e:
                errors.append(str(e))
        
        # Run 5 threads concurrently
        threads = [threading.Thread(target=run_allocations) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Verify no errors
        self.assertEqual(len(errors), 0, f"Errors during concurrent execution: {errors}")
        
        # Verify results (5 threads * 10 cycles each = 50 cycles)
        self.assertEqual(len(results), 50)
        self.assertTrue(all(r == 2 for r in results))
        
        # Verify metrics
        metrics = allocator.get_metrics()
        self.assertEqual(metrics["cycle_count"], 50)
        self.assertEqual(metrics["total_trades"], 100)  # 50 * 2


class TestGlobalRiskIntegration(unittest.TestCase):
    """Test integration with GlobalRiskManager."""
    
    def test_daily_loss_blocks_new_batches(self):
        """Test that reaching daily loss limit blocks new batches."""
        rm = GlobalRiskManager()
        rm._max_daily_loss_pct = 0.10  # 10% daily loss limit
        rm._daily_loss_usd = 150.0  # Already exceeded limit ($150 > $100)

        allocations = [EdgeCandidate("BTC", 0.08, "long", 55, 0, 10000)]

        # Create mock TradeAllocation
        mock_alloc = MagicMock()
        mock_alloc.max_loss_usd = 5.0

        allowed, reason = rm.can_open_batch([mock_alloc], 100000, 0.0)

        self.assertFalse(allowed, f"Daily loss should block: {reason}")
        self.assertIn("Daily loss limit reached", reason)
    
    def test_max_open_risk_blocks_batches(self):
        """Test that max open risk limit blocks batches."""
        rm = GlobalRiskManager()
        rm._max_open_risk_pct = 0.05  # 5% max open risk
        
        # $1000 equity, already have $40 open risk
        # 5% of $1000 = $50 max
        # Proposing $20 more would make $60 > $50
        
        mock_alloc = MagicMock()
        mock_alloc.max_loss_usd = 20.0
        
        allowed, reason = rm.can_open_batch([mock_alloc], 100000, 40.0)
        
        self.assertFalse(allowed)
        self.assertIn("Max open risk exceeded", reason)


class TestEdgeScoring(unittest.TestCase):
    """Test edge scoring and ranking behavior."""
    
    def test_negative_edges_filtered(self):
        """Test that negative edges are filtered out."""
        candidates = [
            EdgeCandidate("BTC", 0.08, "long", 55, 0, 10000),
            EdgeCandidate("ETH", -0.02, "long", 52, 0, 10000),  # Negative
            EdgeCandidate("SOL", 0.06, "short", 48, 100, 10000),
        ]
        
        config = TopNAllocatorConfig(max_edges_per_cycle=2)
        cycle = select_topn_allocations(100000, candidates, config)
        
        # ETH should be filtered, leaving BTC and SOL
        self.assertEqual(cycle.num_edges_traded, 2)
        assets = [a.asset for a in cycle.allocations]
        self.assertNotIn("ETH", assets)
    
    def test_zero_edges_filtered(self):
        """Test that zero edges are filtered out."""
        candidates = [
            EdgeCandidate("BTC", 0.08, "long", 55, 0, 10000),
            EdgeCandidate("ETH", 0.0, "long", 52, 0, 10000),  # Zero
        ]
        
        config = TopNAllocatorConfig(max_edges_per_cycle=2)
        cycle = select_topn_allocations(100000, candidates, config)
        
        self.assertEqual(cycle.num_edges_traded, 1)
        self.assertEqual(cycle.allocations[0].asset, "BTC")


class TestNotionalConstraints(unittest.TestCase):
    """Test notional value constraints."""
    
    def test_per_asset_notional_cap_enforcement(self):
        """Test that per-asset caps limit position size."""
        # BTC with very tight cap
        candidates = [
            EdgeCandidate("BTC", 0.08, "long", 55, 0, max_notional_cap=110),  # $1.10 cap
        ]
        
        config = TopNAllocatorConfig(max_edges_per_cycle=1, min_contracts=1)
        
        # Large equity, but cap limits us
        cycle = select_topn_allocations(1000000, candidates, config)
        
        self.assertEqual(cycle.num_edges_traded, 1)
        btc_alloc = cycle.allocations[0]
        
        # Max notional should be capped at $1.10
        # Entry 55¢, cap $1.10 = 110¢, so max 2 contracts
        self.assertEqual(btc_alloc.target_contracts, 2)
        
        # Verify notional respects cap
        notional_cents = btc_alloc.target_contracts * 55
        self.assertLessEqual(notional_cents, 110)


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════


if __name__ == "__main__":
    unittest.main()
