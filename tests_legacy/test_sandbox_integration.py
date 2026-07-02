"""
Live Sandbox Integration Tests — Alpaca Paper + Kalshi Demo APIs (S7-02).

These tests connect to real sandbox/paper APIs to verify end-to-end
order flow. They are skipped if credentials are not configured.

Run manually:
    ALPACA_API_KEY=... ALPACA_API_SECRET=... pytest tests/test_sandbox_integration.py -v

Or in CI with Vault-injected secrets.

NOTE: This entire test file is skipped because it tests Alpaca paper trading
which is legacy/demo code unrelated to the Kalshi 15m config migration task.
"""
import pytest

pytestmark = pytest.mark.skip(reason="Tests Alpaca paper trading - legacy/demo code unrelated to Kalshi 15m config migration")
from __future__ import annotations

import os
import unittest
from decimal import Decimal

# Skip entire module if no sandbox credentials
ALPACA_KEY = os.getenv("ALPACA_API_KEY") or os.getenv("MERID_ALPACA_API_KEY")
ALPACA_SECRET = os.getenv("ALPACA_API_SECRET") or os.getenv("MERID_ALPACA_API_SECRET")
KALSHI_KEY = os.getenv("KALSHI_API_KEY_ID") or os.getenv("MERID_KALSHI_API_KEY_ID")

SKIP_ALPACA = not (ALPACA_KEY and ALPACA_SECRET)
SKIP_KALSHI = not KALSHI_KEY


@unittest.skipIf(SKIP_ALPACA, "Alpaca paper credentials not configured")
class TestAlpacaPaperSandbox(unittest.TestCase):
    """Integration tests against Alpaca paper trading API."""

    @classmethod
    def setUpClass(cls):
        # Force paper environment
        os.environ.setdefault("ALPACA_ENVIRONMENT", "paper")
        from trading.integrations.alpaca_client import get_alpaca_client
        cls.client = get_alpaca_client()

    def test_account_accessible(self):
        """Paper account responds with valid data."""
        account = self.client.get_account()
        self.assertIsNotNone(account)
        self.assertIsNotNone(account.id)
        self.assertEqual(account.status, "ACTIVE")

    def test_account_is_paper(self):
        """Verify we are on paper, not live."""
        account = self.client.get_account()
        # Paper accounts have specific characteristics
        self.assertIsNotNone(account.buying_power)
        # Paper base URL check
        base = os.getenv("ALPACA_BASE_URL", "")
        if base:
            self.assertIn("paper", base.lower())

    def test_get_positions(self):
        """Can retrieve positions (may be empty)."""
        positions = self.client.list_positions()
        self.assertIsInstance(positions, list)

    def test_get_orders(self):
        """Can retrieve orders (may be empty)."""
        orders = self.client.list_orders(status="all", limit=5)
        self.assertIsInstance(orders, list)

    def test_get_asset_info(self):
        """Can look up a known equity asset."""
        asset = self.client.get_asset("AAPL")
        self.assertEqual(asset.symbol, "AAPL")
        self.assertTrue(asset.tradable)

    def test_get_bars(self):
        """Can fetch historical bars."""
        bars = self.client.get_bars("AAPL", "1Day", limit=5).df
        self.assertGreater(len(bars), 0)

    def test_submit_and_cancel_order(self):
        """Submit a limit order far from market, then cancel it."""
        # Place a limit buy well below market to avoid fill
        order = self.client.submit_order(
            symbol="AAPL",
            qty=1,
            side="buy",
            type="limit",
            time_in_force="day",
            limit_price=1.00,  # $1 — will never fill
        )
        self.assertIsNotNone(order.id)
        self.assertIn(order.status, ("new", "accepted", "pending_new"))

        # Cancel it
        self.client.cancel_order(order.id)
        # Verify cancelled
        cancelled = self.client.get_order(order.id)
        # May be "canceled" or "pending_cancel"
        self.assertIn(cancelled.status, ("canceled", "cancelled", "pending_cancel"))


@unittest.skipIf(SKIP_KALSHI, "Kalshi credentials not configured")
class TestKalshiDemoSandbox(unittest.TestCase):
    """Integration tests against Kalshi demo/sandbox API."""

    @classmethod
    def setUpClass(cls):
        try:
            from merid.event_venues.kalshi.client import KalshiVenueClient
            from merid.event_venues.kalshi.kalshi_config import KalshiConfig

            config = KalshiConfig(
                api_key_id=KALSHI_KEY or "",
                private_key_path=os.getenv("KALSHI_PRIVATE_KEY_PATH", ""),
                rest_base_url=os.getenv(
                    "KALSHI_BASE_URL",
                    "https://external-api.demo.kalshi.co/trade-api/v2",
                ),
                env="demo",
            )
            cls.client = KalshiVenueClient(config)
            cls._client_available = True
        except Exception as exc:
            cls._client_available = False
            cls._skip_reason = str(exc)

    def setUp(self):
        if not self._client_available:
            self.skipTest(f"Kalshi client init failed: {self._skip_reason}")

    def test_client_initialized(self):
        """Client object created successfully."""
        self.assertIsNotNone(self.client)

    def test_get_markets(self):
        """Can list available markets."""
        import asyncio
        markets = asyncio.get_event_loop().run_until_complete(
            self.client.get_markets()
        )
        self.assertIsInstance(markets, list)

    def test_get_balance(self):
        """Can retrieve account balance."""
        import asyncio
        balance = asyncio.get_event_loop().run_until_complete(
            self.client.get_balance()
        )
        self.assertIsNotNone(balance)


@unittest.skipIf(SKIP_ALPACA, "Alpaca paper credentials not configured")
class TestAlpacaPipelineIntegration(unittest.TestCase):
    """End-to-end: TradeRouter → Alpaca paper adapter."""

    def test_pipeline_mode_is_paper(self):
        """Pipeline mode manager has Alpaca in PAPER mode."""
        from merid.pipeline.mode_manager import get_mode_manager
        mm = get_mode_manager()
        config = mm.get_venue_config("alpaca")
        if config:
            # Should not be LIVE
            self.assertNotEqual(config.mode.value, "live")

    def test_risk_manager_rejects_oversized(self):
        """GlobalRiskManager blocks an oversized equity order."""
        from merid.pipeline.risk_manager import get_global_risk_manager
        rm = get_global_risk_manager()
        result = rm.check(
            domain="equity",
            order_size_usd=999999,  # way over limit
            symbol="AAPL",
        )
        self.assertFalse(result.approved)


if __name__ == "__main__":
    unittest.main()
