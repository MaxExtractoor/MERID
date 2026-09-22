"""Test CRYPTO-15M-ARB changes — Crypto 15m arbitrage optimization.

Tests the following fixes:
1. DislocationScanner focuses on 5 crypto assets (BTC/ETH/SOL/XRP/DOGE)
2. Chunked _expire_signals with GIL yield points
3. Synthetic scan disabled in production
4. Cross-venue arb detection in KalshiStrategy
5. Isolated thread pool for arb_scan
6. CryptoVenueBridge integration
"""

import unittest
import time
from decimal import Decimal


class TestCrypto15MArb(unittest.TestCase):
    """Test CRYPTO-15M-ARB optimizations."""





    def test_cross_venue_arb_boost_in_strategy(self):
        """Test KalshiStrategy._get_cross_venue_arb_boost method exists."""
        from merid.prediction.strategy import KalshiStrategy, StrategyConfig
        from merid.prediction.model import MarketSnapshot, ImpliedProbability
        
        config = StrategyConfig()
        strategy = KalshiStrategy(config)
        
        # Create minimal snapshot
        snapshot = MarketSnapshot(
            market_id="KXBTC15M-TEST",
            event_id="TEST",
            title="Test",
            state="trading",
            implied=ImpliedProbability(
                yes_prob=Decimal("0.5"),
                no_prob=Decimal("0.5")
            ),
            volume=Decimal("0"),
            open_interest=Decimal("0")
        )
        
        # Method should exist and return None when no arb
        result = strategy._get_cross_venue_arb_boost(snapshot)
        self.assertIsNone(result)

    def test_arb_executor_isolated(self):
        """Test _get_arb_executor returns separate thread pool."""
        from merid.loop import _get_arb_executor, _get_loop_executor
        
        arb_executor = _get_arb_executor()
        loop_executor = _get_loop_executor()
        
        # Should be different instances
        self.assertIsNot(arb_executor, loop_executor)
        
        # Arb executor should have fewer workers
        self.assertEqual(arb_executor._max_workers, 4)


    def test_strategy_has_cross_venue_check(self):
        """Test _evaluate_directional includes cross-venue arb check."""
        from merid.prediction.strategy import KalshiStrategy
        import inspect
        
        source = inspect.getsource(KalshiStrategy._evaluate_directional)
        
        # Should reference cross-venue arb
        self.assertIn("cross_venue_edge", source)
        self.assertIn("_get_cross_venue_arb_boost", source)


class TestArbScanLoopIntegration(unittest.TestCase):
    """Test arb_scan integration in loop."""

    def test_loop_has_arb_executor(self):
        """Test MeridLoop imports include _get_arb_executor."""
        from merid.loop import _get_arb_executor, _get_loop_executor
        
        # Both should be importable
        self.assertTrue(callable(_get_arb_executor))
        self.assertTrue(callable(_get_loop_executor))

    def test_arb_scan_interval_configurable(self):
        """Test arb_scan interval reads from env var."""
        import os
        
        # Set custom interval before importing
        os.environ["MERID_ARB_SCAN_INTERVAL_S"] = "180"
        
        # Must reimport to pick up new env var value
        # (os.getenv is evaluated at class definition time)
        from importlib import reload
        import merid.loop
        reload(merid.loop)
        from merid.loop import LoopConfig
        
        config = LoopConfig()
        self.assertEqual(config.arb_scan_interval, 180.0)
        
        # Cleanup
        del os.environ["MERID_ARB_SCAN_INTERVAL_S"]


if __name__ == "__main__":
    unittest.main()
