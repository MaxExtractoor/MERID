"""Tests for the Crypto Spot vs Kalshi API and frontend component."""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
from decimal import Decimal
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ═══════════════════════════════════════════════════════════════════════
# Backend Tests
# ═══════════════════════════════════════════════════════════════════════

class TestModuleImport(unittest.TestCase):
    """Verify the API module loads cleanly."""

    def test_import_module(self):
        from web.api.crypto_spot_kalshi_api import router
        self.assertIsNotNone(router)

    def test_route_registered(self):
        from web.api.crypto_spot_kalshi_api import router
        paths = [r.path for r in router.routes]
        self.assertTrue(
            any("/spot-vs-kalshi" in p for p in paths),
            f"Expected /spot-vs-kalshi in {paths}",
        )

    def test_assets_list(self):
        from web.api.crypto_spot_kalshi_api import ASSETS
        self.assertEqual(ASSETS, ["BTC", "ETH", "SOL", "XRP", "DOGE"])

    def test_cg_ids_complete(self):
        from web.api.crypto_spot_kalshi_api import ASSETS, _CG_IDS
        for asset in ASSETS:
            self.assertIn(asset, _CG_IDS)


class TestFetchSpots(unittest.TestCase):
    """Tests for _fetch_spots_sync helper."""

    def setUp(self):
        from web.api.crypto_spot_kalshi_api import _spot_cache
        _spot_cache.clear()

    @patch("web.api.crypto_spot_kalshi_api.urllib.request.urlopen")
    def test_success(self, mock_urlopen):
        from web.api.crypto_spot_kalshi_api import _fetch_spots_sync

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "bitcoin": {"usd": 84231.50},
            "ethereum": {"usd": 1923.10},
            "solana": {"usd": 135.42},
            "ripple": {"usd": 0.5123},
            "dogecoin": {"usd": 0.0821},
        }).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = _fetch_spots_sync()
        self.assertAlmostEqual(result["BTC"], 84231.50)
        self.assertAlmostEqual(result["ETH"], 1923.10)
        self.assertAlmostEqual(result["SOL"], 135.42)
        self.assertAlmostEqual(result["XRP"], 0.5123)
        self.assertAlmostEqual(result["DOGE"], 0.0821)

    @patch("web.api.crypto_spot_kalshi_api.urllib.request.urlopen")
    def test_partial_response(self, mock_urlopen):
        from web.api.crypto_spot_kalshi_api import _fetch_spots_sync

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "bitcoin": {"usd": 84000.0},
        }).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = _fetch_spots_sync()
        self.assertAlmostEqual(result["BTC"], 84000.0)
        self.assertIsNone(result["ETH"])
        self.assertIsNone(result["SOL"])

    @patch("web.api.crypto_spot_kalshi_api.urllib.request.urlopen")
    def test_failure_returns_empty(self, mock_urlopen):
        from web.api.crypto_spot_kalshi_api import _fetch_spots_sync

        mock_urlopen.side_effect = Exception("Network error")
        result = _fetch_spots_sync()
        # All should be None when cache is empty and fetch fails
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            self.assertIsNone(result[asset])

    @patch("web.api.crypto_spot_kalshi_api.urllib.request.urlopen")
    def test_cache_hit(self, mock_urlopen):
        """Second call within TTL should not re-fetch."""
        from web.api.crypto_spot_kalshi_api import _fetch_spots_sync

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "bitcoin": {"usd": 84000.0},
            "ethereum": {"usd": 1900.0},
            "solana": {"usd": 130.0},
            "ripple": {"usd": 0.50},
            "dogecoin": {"usd": 0.08},
        }).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        _fetch_spots_sync()  # first call populates cache
        _fetch_spots_sync()  # second call should use cache
        self.assertEqual(mock_urlopen.call_count, 1)


class TestExtractMarketInfo(unittest.TestCase):
    """Tests for _extract_market_info helper."""

    def _make_catalog_market(self, ticker="KXBTC-T84000", strike=84000.0,
                              yes_price=55, timeframe="15m"):
        from merid.event_venues.base import EventMarket, EventOutcome

        outcome = EventOutcome(
            outcome_id="yes",
            outcome_name="Yes",
            price=Decimal(str(yes_price)),
            best_ask=Decimal(str(yes_price)),
            best_bid=Decimal(str(yes_price - 2)),
        )
        mkt = EventMarket(
            market_id=ticker,
            venue="kalshi",
            question=f"Will BTC be above ${strike}?",
            description="Test market",
            outcomes=[outcome],
            volume=Decimal("1500"),
            open_interest=Decimal("300"),
        )
        cm = MagicMock()
        cm.market = mkt
        cm.strike_price = strike
        cm.timeframe = timeframe
        cm.series_ticker = "KXBTC"
        cm.expires_at = datetime(2026, 3, 22, 13, 0, tzinfo=timezone.utc)
        cm.minutes_to_expiry = 30.0
        return cm

    def test_basic_extraction(self):
        from web.api.crypto_spot_kalshi_api import _extract_market_info

        cm = self._make_catalog_market()
        info = _extract_market_info(cm, spot=84500.0)

        self.assertEqual(info["ticker"], "KXBTC-T84000")
        self.assertEqual(info["yes_price_cents"], 55)
        self.assertEqual(info["no_price_cents"], 45)
        self.assertEqual(info["strike"], 84000.0)
        self.assertEqual(info["timeframe"], "15m")
        self.assertEqual(info["volume"], 1500.0)
        # strike_vs_spot_pct: (84000 - 84500) / 84500 * 100 = -0.59%
        self.assertAlmostEqual(info["strike_vs_spot_pct"], -0.59, places=1)

    def test_no_spot_price(self):
        from web.api.crypto_spot_kalshi_api import _extract_market_info

        cm = self._make_catalog_market()
        info = _extract_market_info(cm, spot=None)
        self.assertIsNone(info["strike_vs_spot_pct"])

    def test_no_strike(self):
        from web.api.crypto_spot_kalshi_api import _extract_market_info

        cm = self._make_catalog_market()
        cm.strike_price = None
        info = _extract_market_info(cm, spot=84500.0)
        self.assertIsNone(info["strike_vs_spot_pct"])

    def test_question_truncated(self):
        from web.api.crypto_spot_kalshi_api import _extract_market_info

        cm = self._make_catalog_market()
        cm.market.question = "A" * 200
        info = _extract_market_info(cm, spot=84500.0)
        self.assertEqual(len(info["question"]), 120)


class TestMainRouterWiring(unittest.TestCase):
    """Verify the router is wired into web/main.py."""

    def test_main_imports_router(self):
        import importlib
        spec = importlib.util.find_spec("web.api.crypto_spot_kalshi_api")
        self.assertIsNotNone(spec, "Module web.api.crypto_spot_kalshi_api not found")

    def test_main_py_has_registration(self):
        with open(os.path.join(os.path.dirname(__file__), "..", "web", "main.py"), encoding="utf-8") as f:
            content = f.read()
        self.assertIn("crypto_spot_kalshi_router", content)
        self.assertIn("crypto_spot_kalshi_api", content)


# ═══════════════════════════════════════════════════════════════════════
# Frontend Tests (file-level)
# ═══════════════════════════════════════════════════════════════════════

class TestFrontendComponent(unittest.TestCase):
    """Verify frontend files exist and contain expected content."""

    def _read_file(self, relpath):
        root = os.path.join(os.path.dirname(__file__), "..")
        with open(os.path.join(root, relpath), encoding="utf-8") as f:
            return f.read()

    def test_component_file_exists(self):
        content = self._read_file("web/react/src/components/CryptoSpotKalshiPanel.tsx")
        self.assertIn("CryptoSpotKalshiPanel", content)

    def test_component_imports_endpoint(self):
        content = self._read_file("web/react/src/components/CryptoSpotKalshiPanel.tsx")
        self.assertIn("CRYPTO_SPOT_VS_KALSHI", content)

    def test_component_renders_all_assets(self):
        content = self._read_file("web/react/src/components/CryptoSpotKalshiPanel.tsx")
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            self.assertIn(asset, content)

    def test_component_has_spot_display(self):
        content = self._read_file("web/react/src/components/CryptoSpotKalshiPanel.tsx")
        self.assertIn("spot_usd", content)
        self.assertIn("Spot", content)

    def test_component_has_contract_table(self):
        content = self._read_file("web/react/src/components/CryptoSpotKalshiPanel.tsx")
        self.assertIn("yes_price_cents", content)
        self.assertIn("no_price_cents", content)
        self.assertIn("strike_vs_spot_pct", content)

    def test_component_has_timeframe_grouping(self):
        content = self._read_file("web/react/src/components/CryptoSpotKalshiPanel.tsx")
        self.assertIn("by_timeframe", content)

    def test_component_has_auto_refresh(self):
        content = self._read_file("web/react/src/components/CryptoSpotKalshiPanel.tsx")
        self.assertIn("setInterval", content)
        self.assertIn("15_000", content)


class TestConstantsWiring(unittest.TestCase):
    """Verify constants.ts has the new endpoint."""

    def test_constants_has_endpoint(self):
        root = os.path.join(os.path.dirname(__file__), "..")
        with open(os.path.join(root, "web/react/src/config/constants.ts"), encoding="utf-8") as f:
            content = f.read()
        self.assertIn("CRYPTO_SPOT_VS_KALSHI", content)
        self.assertIn("/api/v1/crypto/spot-vs-kalshi", content)

    def test_setup_tests_has_mock(self):
        root = os.path.join(os.path.dirname(__file__), "..")
        with open(os.path.join(root, "web/react/src/setupTests.ts"), encoding="utf-8") as f:
            content = f.read()
        self.assertIn("CRYPTO_SPOT_VS_KALSHI", content)


class TestViewWiring(unittest.TestCase):
    """Verify the panel is wired into views."""

    def _read_file(self, relpath):
        root = os.path.join(os.path.dirname(__file__), "..")
        with open(os.path.join(root, relpath), encoding="utf-8") as f:
            return f.read()

    def test_terminal_view_imports_panel(self):
        content = self._read_file("web/react/src/views/KalshiTerminalView.tsx")
        self.assertIn("CryptoSpotKalshiPanel", content)

    def test_terminal_view_renders_panel(self):
        content = self._read_file("web/react/src/views/KalshiTerminalView.tsx")
        self.assertIn("<CryptoSpotKalshiPanel", content)

    def test_dashboard_view_imports_panel(self):
        content = self._read_file("web/react/src/views/KalshiDashboardView.tsx")
        self.assertIn("CryptoSpotKalshiPanel", content)

    def test_dashboard_view_renders_panel(self):
        content = self._read_file("web/react/src/views/KalshiDashboardView.tsx")
        self.assertIn("<CryptoSpotKalshiPanel", content)


if __name__ == "__main__":
    unittest.main()
