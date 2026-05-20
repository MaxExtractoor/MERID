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

    def test_crypto_15m_assets_constant(self):
        """Test CRYPTO_15M_ASSETS includes all 5 crypto assets."""
        from merid.signals.arbitrage import CRYPTO_15M_ASSETS
        
        self.assertEqual(len(CRYPTO_15M_ASSETS), 5)
        self.assertIn("BTC", CRYPTO_15M_ASSETS)
        self.assertIn("ETH", CRYPTO_15M_ASSETS)
        self.assertIn("SOL", CRYPTO_15M_ASSETS)
        self.assertIn("XRP", CRYPTO_15M_ASSETS)
        self.assertIn("DOGE", CRYPTO_15M_ASSETS)

    def test_scan_filters_non_crypto_symbols(self):
        """Test that scan() filters out non-crypto symbols."""
        from merid.signals.arbitrage import DislocationScanner, CRYPTO_15M_ASSETS, VenuePrice
        
        scanner = DislocationScanner()
        
        # Add prices for crypto assets
        for asset in CRYPTO_15M_ASSETS:
            scanner.ingest_price(VenuePrice(
                venue="coinbase", symbol=asset,
                bid=100.0, ask=100.1, mid=100.05,
                timestamp=time.time()
            ))
            scanner.ingest_price(VenuePrice(
                venue="binance", symbol=asset,
                bid=100.05, ask=100.15, mid=100.10,
                timestamp=time.time()
            ))
        
        # Add non-crypto prices (should be filtered)
        scanner.ingest_price(VenuePrice(
            venue="coinbase", symbol="AAPL",
            bid=150.0, ask=150.1, mid=150.05,
            timestamp=time.time()
        ))
        scanner.ingest_price(VenuePrice(
            venue="binance", symbol="AAPL",
            bid=150.05, ask=150.15, mid=150.10,
            timestamp=time.time()
        ))
        
        # Scan should only process crypto assets
        signals = scanner.scan()
        
        # All signals should be for crypto assets only
        for sig in signals:
            base_symbol = sig.symbol.replace("/USD", "").replace("-USD", "").upper()
            self.assertIn(base_symbol, CRYPTO_15M_ASSETS,
                         f"Non-crypto symbol {sig.symbol} should be filtered")

    def test_synthetic_scan_disabled_by_default(self):
        """Test synthetic_scan returns empty list by default."""
        from merid.signals.arbitrage import DislocationScanner
        import os
        
        scanner = DislocationScanner()
        
        # Ensure env var is not set
        if "MERID_ENABLE_SYNTHETIC_ARB" in os.environ:
            del os.environ["MERID_ENABLE_SYNTHETIC_ARB"]
        
        signals = scanner.synthetic_scan()
        self.assertEqual(len(signals), 0)

    def test_chunked_expire_signals_doesnt_block(self):
        """Test _expire_signals completes without blocking."""
        from merid.signals.arbitrage import DislocationScanner, DislocationSignal, DislocationStatus
        
        scanner = DislocationScanner()
        
        # Add many signals to test chunked processing
        for i in range(150):
            sig = DislocationSignal(
                symbol=f"TEST{i}",
                status=DislocationStatus.EXPIRED.value,
                detected_at=time.time() - 1000  # Old signal
            )
            scanner._signals.append(sig)
        
        start = time.time()
        scanner._expire_signals(time.time())
        elapsed = time.time() - start
        
        # Should complete quickly with GIL yields (under 500ms for 150 items)
        self.assertLess(elapsed, 0.5, "_expire_signals took too long")

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

    def test_crypto_venue_bridge_imports(self):
        """Test CryptoVenueBridge can be imported."""
        from merid.signals.crypto_venue_bridge import (
            CryptoVenueBridge, get_crypto_venue_bridge, VenuePriceUpdate
        )
        
        bridge = get_crypto_venue_bridge()
        self.assertIsInstance(bridge, CryptoVenueBridge)
        self.assertEqual(bridge._assets, ["BTC", "ETH", "SOL", "XRP", "DOGE"])

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
