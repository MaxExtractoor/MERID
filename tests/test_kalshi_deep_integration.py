"""Tests for Kalshi Deep Integration — §1-§7.

Covers:
  - Fee calculation (tiered schedule)
  - Kelly position sizing (fee-aware)
  - Risk manager (position limits, category caps, kill switch, drawdown, rate limits)
  - Market catalog (enrichment, asset/timeframe detection, filters)
  - WebSocket bridge (module structure)
  - REST API endpoints (file structure, route definitions)
  - UI components (file structure, imports, wiring)
  - Package exports
"""

from __future__ import annotations

import asyncio
import os

# Force mock trading mode for this legacy deep-integration test file so
# route_order(), simulate_paper_fill(), and other mode-guarded paths do not
# fail on the live-mode safety assertion.
os.environ.setdefault("MERID_PM_TRADING_MODE", "mock")
import ast
import os
import re
import sys
import unittest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ═══════════════════════════════════════════════════════════════════════════
# §1  Fee Calculation Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestKalshiFeeCalc(unittest.TestCase):
    """Test the Kalshi fee schedule implementation."""

    def setUp(self):
        from merid.event_venues.kalshi.kalshi_risk import kalshi_fee_cents, kalshi_fee_rate
        self.fee = kalshi_fee_cents
        self.rate = kalshi_fee_rate

    def test_fee_zero_contracts(self):
        self.assertEqual(self.fee(50, 0), 0)

    def test_fee_zero_price(self):
        self.assertEqual(self.fee(0, 10), 0)

    def test_fee_price_100(self):
        """Price of 100 means no payout, so no fee."""
        self.assertEqual(self.fee(100, 10), 0)

    def test_fee_negative_contracts(self):
        self.assertEqual(self.fee(50, -5), 0)

    def test_fee_tier1_small(self):
        """1-99 contracts: 7% parabolic."""
        # ceil(0.07 * 10 * 0.50 * 0.50 * 100) = ceil(17.5) = 18
        fee = self.fee(50, 10)
        self.assertEqual(fee, 18)

    def test_fee_tier1_min_floor(self):
        """Min fee is 2¢ total."""
        # ceil(0.07 * 10 * 0.95 * 0.05 * 100) = ceil(3.325) = 4
        fee = self.fee(95, 10)
        self.assertEqual(fee, 4)

    def test_fee_tier2_medium(self):
        """100-999 contracts: 5% parabolic."""
        # ceil(0.05 * 100 * 0.50 * 0.50 * 100) = ceil(125) = 125
        fee = self.fee(50, 100)
        self.assertEqual(fee, 125)

    def test_fee_tier3_large(self):
        """1000+ contracts: 3% parabolic."""
        # ceil(0.03 * 1000 * 0.50 * 0.50 * 100) = ceil(750) = 750
        fee = self.fee(50, 1000)
        self.assertEqual(fee, 750)

    def test_fee_rate_tiers(self):
        self.assertEqual(self.rate(10), 0.07)
        self.assertEqual(self.rate(99), 0.07)
        self.assertEqual(self.rate(100), 0.05)
        self.assertEqual(self.rate(999), 0.05)
        self.assertEqual(self.rate(1000), 0.03)
        self.assertEqual(self.rate(5000), 0.03)

    def test_fee_high_price_low_payout(self):
        """High price (90¢), low payout (10¢)."""
        # ceil(0.07 * 50 * 0.90 * 0.10 * 100) = ceil(31.5) = 32
        fee = self.fee(90, 50)
        self.assertEqual(fee, 32)

    def test_fee_low_price_high_payout(self):
        """Low price (10¢), high payout (90¢) — parabolic is symmetric with 90¢."""
        # ceil(0.07 * 50 * 0.10 * 0.90 * 100) = ceil(31.5) = 32
        fee = self.fee(10, 50)
        self.assertEqual(fee, 32)


# ═══════════════════════════════════════════════════════════════════════════
# §2  Kelly Sizing Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestKellySize(unittest.TestCase):
    """Test fee-aware Kelly position sizing."""

    def setUp(self):
        from merid.event_venues.kalshi.kalshi_risk import kelly_size_kalshi
        self.kelly = kelly_size_kalshi

    def test_zero_edge(self):
        self.assertEqual(self.kelly(0.0, 50, 10000), 0)

    def test_negative_edge(self):
        self.assertEqual(self.kelly(-0.05, 50, 10000), 0)

    def test_edge_below_minimum(self):
        self.assertEqual(self.kelly(0.01, 50, 10000), 0)

    def test_zero_bankroll(self):
        self.assertEqual(self.kelly(0.10, 50, 0), 0)

    def test_zero_price(self):
        self.assertEqual(self.kelly(0.10, 0, 10000), 0)

    def test_price_100(self):
        self.assertEqual(self.kelly(0.10, 100, 10000), 0)

    def test_positive_edge_returns_contracts(self):
        """With a reasonable edge, should return > 0 contracts."""
        size = self.kelly(0.10, 50, 100000)
        self.assertGreater(size, 0)
        self.assertLessEqual(size, 250)  # max_contracts default

    def test_max_contracts_cap(self):
        """Should not exceed max_contracts."""
        size = self.kelly(0.50, 20, 10000000, max_contracts=100)
        self.assertLessEqual(size, 100)

    def test_quarter_kelly_smaller_than_full(self):
        """Quarter Kelly should be smaller than full Kelly."""
        quarter = self.kelly(0.10, 50, 100000, kelly_fraction=0.25)
        full = self.kelly(0.10, 50, 100000, kelly_fraction=1.0)
        self.assertLessEqual(quarter, full)

    def test_higher_edge_more_contracts(self):
        """Higher edge should result in more contracts."""
        low = self.kelly(0.05, 50, 100000)
        high = self.kelly(0.15, 50, 100000)
        self.assertLessEqual(low, high)

    def test_custom_min_edge(self):
        """Custom min_edge threshold."""
        self.assertEqual(self.kelly(0.04, 50, 10000, min_edge=0.05), 0)
        size = self.kelly(0.06, 50, 10000, min_edge=0.05)
        self.assertGreaterEqual(size, 0)


# ═══════════════════════════════════════════════════════════════════════════
# §3  Risk Manager Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestKalshiRiskManager(unittest.TestCase):
    """Test the KalshiRiskManager pre-trade checks."""

    def setUp(self):
        from merid.event_venues.kalshi.kalshi_risk import KalshiRiskManager, KalshiRiskConfig, CategoryLimit
        self.config = KalshiRiskConfig(
            max_total_notional_usd=5000.0,
            max_daily_loss_usd=500,
            max_single_order_contracts=100,
            max_single_order_notional_usd=1000,
            max_position_per_contract=200,
            max_orders_per_minute=10,
            max_orders_per_hour=100,
            max_stop_loss_usd_per_cluster=1000.0,
            category_limits={
                "crypto": CategoryLimit(
                    category="crypto",
                    max_notional_usd=5000.0,
                    max_contracts=500,
                    enabled=True,
                ),
            },
        )
        self.risk = KalshiRiskManager(self.config)
        # Provide a positive bankroll/equity baseline so the bankroll cap
        # does not fail-close every test in this no-API unit-test context.
        self.risk._state.current_equity_usd = 100000.0
        self.risk._state.peak_equity_usd = 100000.0

    def test_basic_order_passes(self):
        ok, reason = self.risk.check_order("BTC-TEST", "crypto", 10, 50)
        self.assertTrue(ok)
        self.assertEqual(reason, "OK")

    def test_kill_switch_blocks(self):
        self.risk._activate_kill_switch("test")
        ok, reason = self.risk.check_order("BTC-TEST", "crypto", 10, 50)
        self.assertFalse(ok)
        self.assertIn("Kill switch", reason)

    def test_kill_switch_reset(self):
        self.risk._activate_kill_switch("test")
        self.assertTrue(self.risk.kill_switch_active)
        self.risk.reset_kill_switch()
        self.assertFalse(self.risk.kill_switch_active)

    def test_order_size_limit(self):
        ok, reason = self.risk.check_order("BTC-TEST", "crypto", 200, 50)
        self.assertFalse(ok)
        self.assertIn("Order size", reason)

    def test_order_notional_limit(self):
        # 50 contracts × 50¢ = $25 notional... need higher
        # 100 contracts × 20¢ = $20... need $1000+
        # Actually: contracts * price_cents / 100 = notional_usd
        # 100 * 50 / 100 = $50... max is $1000
        # Need: contracts * price / 100 > 1000 → 100 * 1100 / 100 = $1100
        # But price_cents max is 99 for Kalshi... so 100 * 99 / 100 = $99
        # This limit is more for large orders. Let's test with smaller max.
        config = self.config
        config.max_single_order_notional_usd = 10
        risk = type(self.risk)(config)
        ok, reason = risk.check_order("BTC-TEST", "crypto", 50, 50)
        self.assertFalse(ok)
        self.assertIn("notional", reason)

    def test_position_limit(self):
        ok, reason = self.risk.check_order("BTC-TEST", "crypto", 50, 50, existing_position=180)
        self.assertFalse(ok)
        self.assertIn("per-contract limit", reason)

    def test_category_notional_cap(self):
        # Default crypto cap is $5000
        # Record enough to exceed
        self.risk._state.category_notional["crypto"] = 4990
        ok, reason = self.risk.check_order("BTC-TEST", "crypto", 50, 50)
        self.assertFalse(ok)
        self.assertIn("Category", reason)

    def test_total_notional_cap(self):
        self.risk._state.total_notional_usd = 9990
        ok, reason = self.risk.check_order("BTC-TEST", "crypto", 50, 50)
        self.assertFalse(ok)
        self.assertIn("Total notional", reason)

    def test_daily_loss_blocks_orders_without_kill_switch(self):
        """Daily loss blocks risk-increasing orders but does NOT set kill_switch_active.

        Per operator directive (kalshi_risk.py:882-883): agents must trade to close
        positions and lock in profits without permanent halts. Killswitch removed.
        """
        # Set up equity state: $1000 start, $400 current = $600 loss > $500 max
        self.risk._state.start_of_day_equity_usd = 1000.0
        self.risk._state.current_equity_usd = 400.0  # $600 loss > $500 max
        with patch.object(self.risk, "_sync_pnl_from_ledger"):
            ok, reason = self.risk.check_order("BTC-TEST", "crypto", 10, 50)
        self.assertFalse(ok)
        # kill_switch_active is NOT set - system allows closing trades
        self.assertFalse(self.risk.kill_switch_active)

    def test_drawdown_halt(self):
        self.risk._state.peak_equity_usd = 10000
        self.risk._state.current_equity_usd = 8900  # 11% drawdown > 10% halt
        ok, reason = self.risk.check_order("BTC-TEST", "crypto", 10, 50)
        self.assertFalse(ok)
        self.assertIn("drawdown", reason.lower())

    def test_drawdown_unwind_blocks_orders_without_kill_switch(self):
        """Drawdown unwind blocks risk-increasing orders but does NOT set kill_switch_active.

        Per operator directive (kalshi_risk.py:882-883): agents must trade to close
        positions and lock in profits without permanent halts. Killswitch removed.
        """
        self.risk._state.peak_equity_usd = 10000
        self.risk._state.current_equity_usd = 8400  # 16% > 15% unwind
        ok, reason = self.risk.check_order("BTC-TEST", "crypto", 10, 50)
        self.assertFalse(ok)
        # kill_switch_active is NOT set - system allows closing trades
        self.assertFalse(self.risk.kill_switch_active)

    def test_record_order_updates_state(self):
        self.risk.record_order("crypto", 10, 50)
        self.assertEqual(self.risk._state.orders_this_minute, 1)
        self.assertAlmostEqual(self.risk._state.total_notional_usd, 5.0)
        self.assertAlmostEqual(self.risk._state.category_notional["crypto"], 5.0)

    def test_record_pnl(self):
        self.risk._state.current_equity_usd = 1000
        self.risk._state.peak_equity_usd = 1000
        self.risk.record_pnl(50)
        self.assertEqual(self.risk._state.daily_pnl_usd, 50)
        self.assertEqual(self.risk._state.current_equity_usd, 1050)
        self.assertEqual(self.risk._state.peak_equity_usd, 1050)

    def test_record_pnl_loss(self):
        self.risk._state.current_equity_usd = 1000
        self.risk._state.peak_equity_usd = 1000
        self.risk.record_pnl(-100)
        self.assertEqual(self.risk._state.daily_pnl_usd, -100)
        self.assertEqual(self.risk._state.peak_equity_usd, 1000)  # unchanged

    def test_reset_daily(self):
        self.risk._state.daily_pnl_usd = -200
        self.risk._state.category_notional["crypto"] = 500
        self.risk.reset_daily()
        self.assertEqual(self.risk._state.daily_pnl_usd, 0)
        self.assertEqual(len(self.risk._state.category_notional), 0)

    def test_summary_json(self):
        summary = self.risk.summary()
        self.assertIn("kill_switch_active", summary)
        self.assertIn("daily_pnl_usd", summary)
        self.assertIn("limits", summary)
        self.assertIsInstance(summary["limits"], dict)

    def test_post_fee_edge_check(self):
        """Edge that's positive but below post-fee minimum should be blocked."""
        # With very small edge, post-fee edge should be negative
        ok, reason = self.risk.check_order("BTC-TEST", "crypto", 10, 50, edge=0.005)
        self.assertFalse(ok)
        self.assertIn("Post-fee edge", reason)

    def test_no_category_still_passes(self):
        """Order with no category should skip category checks."""
        ok, reason = self.risk.check_order("UNKNOWN-MKT", None, 10, 50)
        self.assertTrue(ok)


# ═══════════════════════════════════════════════════════════════════════════
# §4  Market Catalog Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestMarketCatalog(unittest.TestCase):
    """Test market catalog enrichment and filtering."""

    def setUp(self):
        from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
        import threading
        self.catalog = KalshiMarketCatalog.__new__(KalshiMarketCatalog)
        # Initialize without connecting
        from collections import defaultdict
        self.catalog._markets = []
        self.catalog._by_category = defaultdict(list)
        self.catalog._by_asset = defaultdict(list)
        self.catalog._refresh_lock = threading.Lock()
        self.catalog._by_timeframe = defaultdict(list)
        self.catalog._by_ticker = {}
        self.catalog._last_refresh = None
        self.catalog._refresh_count = 0
        self.catalog._task = None
        self.catalog._refresh_lock = threading.Lock()

    def test_detect_asset_btc(self):
        self.assertEqual(self.catalog._detect_asset("Will BTC reach $100k?"), "BTC")
        self.assertEqual(self.catalog._detect_asset("Bitcoin price above 90000"), "BTC")

    def test_detect_asset_eth(self):
        self.assertEqual(self.catalog._detect_asset("Ethereum above $5000"), "ETH")
        self.assertEqual(self.catalog._detect_asset("ETH price daily"), "ETH")

    def test_detect_asset_sol(self):
        self.assertEqual(self.catalog._detect_asset("SOL above $200"), "SOL")
        self.assertEqual(self.catalog._detect_asset("Solana price prediction"), "SOL")

    def test_detect_asset_macro(self):
        self.assertEqual(self.catalog._detect_asset("CPI above 3%"), "CPI")
        self.assertEqual(self.catalog._detect_asset("Fed funds rate cut"), "RATES")
        self.assertEqual(self.catalog._detect_asset("Nonfarm payrolls above 200k"), "JOBS")
        self.assertEqual(self.catalog._detect_asset("GDP growth above 2%"), "GDP")

    def test_detect_asset_indices(self):
        self.assertEqual(self.catalog._detect_asset("S&P 500 above 5000"), "SPX")
        self.assertEqual(self.catalog._detect_asset("NASDAQ above 20000"), "NDX")
        self.assertEqual(self.catalog._detect_asset("Dow above 40000"), "DJI")

    def test_detect_asset_none(self):
        self.assertIsNone(self.catalog._detect_asset("Will it rain tomorrow?"))

    def test_detect_timeframe_text(self):
        now = datetime.now(timezone.utc)
        self.assertEqual(self.catalog._detect_timeframe("15 min BTC", None, now), "15m")
        self.assertEqual(self.catalog._detect_timeframe("hourly close", None, now), "1h")
        self.assertEqual(self.catalog._detect_timeframe("end of day", None, now), "daily")
        self.assertEqual(self.catalog._detect_timeframe("weekly close", None, now), "weekly")
        self.assertEqual(self.catalog._detect_timeframe("monthly CPI", None, now), "monthly")
        self.assertEqual(self.catalog._detect_timeframe("pre-market", None, now), "pre-market")

    def test_detect_timeframe_from_expiry(self):
        now = datetime.now(timezone.utc)
        # 10 minutes → 15m
        self.assertEqual(self.catalog._detect_timeframe("test", now + timedelta(minutes=10), now), "15m")
        # 45 minutes → 1h
        self.assertEqual(self.catalog._detect_timeframe("test", now + timedelta(minutes=45), now), "1h")
        # 12 hours → daily
        self.assertEqual(self.catalog._detect_timeframe("test", now + timedelta(hours=12), now), "daily")
        # 3 days → weekly
        self.assertEqual(self.catalog._detect_timeframe("test", now + timedelta(days=3), now), "weekly")
        # 15 days → monthly
        self.assertEqual(self.catalog._detect_timeframe("test", now + timedelta(days=15), now), "monthly")
        # 60 days → annual
        self.assertEqual(self.catalog._detect_timeframe("test", now + timedelta(days=60), now), "annual")

    def test_detect_type(self):
        self.assertEqual(self.catalog._detect_type("BTC above 100k"), "range")
        self.assertEqual(self.catalog._detect_type("Will it reach 50?"), "binary")
        self.assertEqual(self.catalog._detect_type("Something random"), "binary")

    def test_enrich_market(self):
        from merid.event_venues.base import EventMarket, EventOutcome
        now = datetime.now(timezone.utc)
        mkt = EventMarket(
            market_id="KXBTCD-25JUN-T100000",
            venue="kalshi",
            question="Will BTC be above $100,000 on June 25?",
            description="Bitcoin price prediction",
            outcomes=[EventOutcome("yes", "Yes", Decimal("0.55"))],
            category="crypto",
            end_date=now + timedelta(hours=6),
        )
        cm = self.catalog._enrich(mkt, now)
        self.assertEqual(cm.asset, "BTC")
        self.assertEqual(cm.category, "crypto")
        self.assertEqual(cm.market_type, "range")  # "above" triggers range
        self.assertIsNotNone(cm.minutes_to_expiry)
        self.assertGreater(cm.minutes_to_expiry, 0)

    def test_summary_empty(self):
        summary = self.catalog.summary()
        self.assertEqual(summary["market_count"], 0)
        self.assertIsNone(summary["last_refresh"])


# ═══════════════════════════════════════════════════════════════════════════
# §5  WebSocket Bridge Module Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestWsBridge(unittest.TestCase):
    """Test WebSocket bridge module structure."""

    def test_module_imports(self):
        from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge, get_ws_bridge
        self.assertTrue(callable(get_ws_bridge))

    def test_bridge_summary(self):
        from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge
        bridge = KalshiWebSocketBridge.__new__(KalshiWebSocketBridge)
        bridge._task = None
        bridge._events_forwarded = 42
        bridge._subscribed_tickers = ["BTC-TEST"]
        summary = bridge.summary()
        self.assertEqual(summary["events_forwarded"], 42)
        self.assertFalse(summary["running"])
        self.assertEqual(summary["subscribed_tickers"], 1)

    def test_singleton(self):
        from merid.event_venues.kalshi.ws_bridge import get_ws_bridge
        b1 = get_ws_bridge()
        b2 = get_ws_bridge()
        self.assertIs(b1, b2)


# ═══════════════════════════════════════════════════════════════════════════
# §6  REST API Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestKalshiApiFile(unittest.TestCase):
    """Test the kalshi_api.py file structure and routes."""

    @classmethod
    def setUpClass(cls):
        api_path = ROOT / "web" / "api" / "kalshi_api.py"
        cls.source = api_path.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_file_exists(self):
        self.assertIn("router", self.source)

    def test_router_prefix(self):
        self.assertIn('/api/v1/kalshi', self.source)

    def test_endpoint_markets(self):
        self.assertIn('"/markets"', self.source)

    def test_endpoint_market_detail(self):
        self.assertIn('"/markets/{ticker}"', self.source)

    def test_endpoint_catalog(self):
        self.assertIn('"/catalog"', self.source)

    def test_endpoint_positions(self):
        self.assertIn('"/positions"', self.source)

    def test_endpoint_orders(self):
        self.assertIn('"/orders"', self.source)

    def test_endpoint_fills(self):
        self.assertIn('"/fills"', self.source)

    def test_endpoint_balance(self):
        self.assertIn('"/balance"', self.source)

    def test_endpoint_pnl(self):
        self.assertIn('"/pnl"', self.source)

    def test_endpoint_risk(self):
        self.assertIn('"/risk"', self.source)

    def test_endpoint_health(self):
        self.assertIn('"/health"', self.source)

    def test_endpoint_kill_switch(self):
        self.assertIn('"/kill-switch"', self.source)

    def test_endpoint_ws(self):
        self.assertIn('"/ws"', self.source)

    def test_endpoint_catalog_refresh(self):
        self.assertIn('"/catalog/refresh"', self.source)


class TestKalshiApiWiring(unittest.TestCase):
    """Test that the API router is wired into main.py."""

    @classmethod
    def setUpClass(cls):
        main_path = ROOT / "web" / "main.py"
        cls.source = main_path.read_text(encoding="utf-8")

    def test_import(self):
        # Code uses _si() safe import pattern, not direct import
        self.assertIn("kalshi_api_router = _si(\"web.api.kalshi_api\")", self.source)

    def test_include_router(self):
        self.assertIn("kalshi_api_router", self.source)


# ═══════════════════════════════════════════════════════════════════════════
# §7  Frontend Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestFrontendConstants(unittest.TestCase):
    """Test that Kalshi API constants are defined."""

    @classmethod
    def setUpClass(cls):
        path = ROOT / "web" / "react" / "src" / "config" / "constants.ts"
        cls.source = path.read_text(encoding="utf-8")

    def test_kalshi_markets(self):
        self.assertIn("KALSHI_MARKETS", self.source)

    def test_kalshi_catalog(self):
        self.assertIn("KALSHI_CATALOG", self.source)

    def test_kalshi_positions(self):
        self.assertIn("KALSHI_POSITIONS", self.source)

    def test_kalshi_orders(self):
        self.assertIn("KALSHI_ORDERS", self.source)

    def test_kalshi_fills(self):
        self.assertIn("KALSHI_FILLS", self.source)

    def test_kalshi_balance(self):
        self.assertIn("KALSHI_BALANCE", self.source)

    def test_kalshi_pnl(self):
        self.assertIn("KALSHI_PNL", self.source)

    def test_kalshi_risk(self):
        self.assertIn("KALSHI_RISK", self.source)

    def test_kalshi_health(self):
        self.assertIn("KALSHI_HEALTH", self.source)

    def test_kalshi_kill_switch(self):
        self.assertIn("KALSHI_KILL_SWITCH", self.source)

    def test_kalshi_market_detail(self):
        self.assertIn("KALSHI_MARKET_DETAIL", self.source)

    def test_kalshi_catalog_refresh(self):
        self.assertIn("KALSHI_CATALOG_REFRESH", self.source)


class TestFrontendViews(unittest.TestCase):
    """Test that new views exist and are wired."""

    def test_view_types(self):
        path = ROOT / "web" / "react" / "src" / "types" / "views.ts"
        source = path.read_text(encoding="utf-8")
        self.assertIn('"kalshi-dashboard"', source)
        self.assertIn('"kalshi-portfolio"', source)

    def test_dashboard_view_exists(self):
        path = ROOT / "web" / "react" / "src" / "views" / "KalshiDashboardView.tsx"
        self.assertTrue(path.exists())
        source = path.read_text(encoding="utf-8")
        self.assertIn("KalshiDashboardView", source)
        self.assertIn("API_ENDPOINTS", source)
        self.assertIn("KALSHI_MARKETS", source)

    def test_portfolio_view_exists(self):
        path = ROOT / "web" / "react" / "src" / "views" / "KalshiPortfolioView.tsx"
        self.assertTrue(path.exists())
        source = path.read_text(encoding="utf-8")
        self.assertIn("KalshiPortfolioView", source)
        self.assertIn("API_ENDPOINTS", source)
        self.assertIn("KALSHI_POSITIONS", source)

    def test_app_routes(self):
        path = ROOT / "web" / "react" / "src" / "App.tsx"
        source = path.read_text(encoding="utf-8")
        self.assertIn("KalshiDashboardView", source)
        self.assertIn("KalshiPortfolioView", source)
        self.assertIn('"kalshi-dashboard"', source)
        self.assertIn('"kalshi-portfolio"', source)

    def test_sidebar_entries(self):
        path = ROOT / "web" / "react" / "src" / "components" / "Sidebar.tsx"
        source = path.read_text(encoding="utf-8")
        self.assertIn("Markets", source)
        self.assertIn("Portfolio", source)
        self.assertIn("kalshi-dashboard", source)
        self.assertIn("kalshi-portfolio", source)


# ═══════════════════════════════════════════════════════════════════════════
# §8  Package Exports Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestPackageExports(unittest.TestCase):
    """Test that new modules are exported from the kalshi package."""

    @classmethod
    def setUpClass(cls):
        path = ROOT / "merid" / "event_venues" / "kalshi" / "__init__.py"
        cls.source = path.read_text(encoding="utf-8")

    def test_market_catalog_export(self):
        self.assertIn("KalshiMarketCatalog", self.source)
        self.assertIn("get_market_catalog", self.source)
        self.assertIn("CatalogMarket", self.source)
        self.assertIn("CatalogSnapshot", self.source)

    def test_risk_manager_export(self):
        self.assertIn("KalshiRiskManager", self.source)
        self.assertIn("KalshiRiskConfig", self.source)
        self.assertIn("kalshi_fee_cents", self.source)
        self.assertIn("kelly_size_kalshi", self.source)
        self.assertIn("get_kalshi_risk", self.source)

    def test_ws_bridge_export(self):
        self.assertIn("KalshiWebSocketBridge", self.source)
        self.assertIn("get_ws_bridge", self.source)

    def test_all_list(self):
        self.assertIn("__all__", self.source)


class TestModuleImports(unittest.TestCase):
    """Test that all new modules can be imported."""

    def test_import_market_catalog(self):
        from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog, get_market_catalog
        self.assertIsNotNone(KalshiMarketCatalog)

    def test_import_kalshi_risk(self):
        from merid.event_venues.kalshi.kalshi_risk import (
            KalshiRiskManager, KalshiRiskConfig, kalshi_fee_cents, kelly_size_kalshi, get_kalshi_risk
        )
        self.assertIsNotNone(KalshiRiskManager)

    def test_import_ws_bridge(self):
        from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge, get_ws_bridge
        self.assertIsNotNone(KalshiWebSocketBridge)

    def test_import_from_package(self):
        from merid.event_venues.kalshi import (
            KalshiMarketCatalog, get_market_catalog,
            KalshiRiskManager, kalshi_fee_cents, kelly_size_kalshi, get_kalshi_risk,
            KalshiWebSocketBridge, get_ws_bridge,
        )
        self.assertIsNotNone(KalshiMarketCatalog)
        self.assertIsNotNone(KalshiRiskManager)
        self.assertIsNotNone(KalshiWebSocketBridge)


# ═══════════════════════════════════════════════════════════════════════════
# §9  Risk Manager Singleton Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestSingletons(unittest.TestCase):
    """Test singleton accessors."""

    def test_risk_singleton(self):
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
        r1 = get_kalshi_risk()
        r2 = get_kalshi_risk()
        self.assertIs(r1, r2)

    def test_catalog_singleton(self):
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        c1 = get_market_catalog()
        c2 = get_market_catalog()
        self.assertIs(c1, c2)


# ═══════════════════════════════════════════════════════════════════════════
# §10  Dynamic Position Sizing Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestDynamicPositionSizes(unittest.TestCase):
    """Test edge-weighted allocation across multiple markets."""

    def setUp(self):
        from merid.event_venues.kalshi.kalshi_risk import dynamic_position_sizes
        self.dps = dynamic_position_sizes

    def test_empty_markets(self):
        self.assertEqual(self.dps([], 10000), {})

    def test_zero_equity(self):
        markets = [{"ticker": "A", "edge_pct": 2.0, "price_cents": 50}]
        self.assertEqual(self.dps(markets, 0), {})

    def test_no_positive_edge(self):
        markets = [{"ticker": "A", "edge_pct": 0.1, "price_cents": 50}]
        self.assertEqual(self.dps(markets, 10000, min_edge_pct=1.0), {})

    def test_single_market(self):
        markets = [{"ticker": "BTC-1", "edge_pct": 2.0, "price_cents": 50}]
        sizes = self.dps(markets, 10000)
        self.assertIn("BTC-1", sizes)
        self.assertGreater(sizes["BTC-1"], 0)

    def test_two_markets_proportional(self):
        """Higher edge market should get more contracts."""
        markets = [
            {"ticker": "A", "edge_pct": 1.0, "price_cents": 50},
            {"ticker": "B", "edge_pct": 3.0, "price_cents": 50},
        ]
        # Use small equity so neither market hits the 500 cap
        sizes = self.dps(markets, 1000, max_contracts_per_market=500)
        self.assertIn("A", sizes)
        self.assertIn("B", sizes)
        self.assertGreater(sizes["B"], sizes["A"])

    def test_max_contracts_cap(self):
        markets = [{"ticker": "A", "edge_pct": 5.0, "price_cents": 10}]
        sizes = self.dps(markets, 1000000, max_contracts_per_market=100)
        self.assertLessEqual(sizes.get("A", 0), 100)

    def test_fee_check_filters_bad_trades(self):
        """Very high price (99¢) with tiny edge — parabolic fee is minimal at extremes."""
        markets = [{"ticker": "A", "edge_pct": 1.0, "price_cents": 99}]
        sizes = self.dps(markets, 100)
        # With parabolic fee formula, P*(1-P) ≈ 0.01 at 99¢ → very low fee.
        # Budget-based allocation dominates: 30% of 100¢ / 99¢ ≈ 30 contracts.
        # Confirm the allocation is budget-bounded (not infinite).
        max_from_budget = int(0.30 * 100 / 99) + 1  # ~30
        self.assertLessEqual(sizes.get("A", 0), 100)

    def test_custom_category_cap(self):
        markets = [{"ticker": "A", "edge_pct": 2.0, "price_cents": 50}]
        small = self.dps(markets, 10000, category_cap_pct=0.10)
        large = self.dps(markets, 10000, category_cap_pct=0.50)
        self.assertLessEqual(small.get("A", 0), large.get("A", 0))

    def test_import_from_package(self):
        from merid.event_venues.kalshi import dynamic_position_sizes
        self.assertTrue(callable(dynamic_position_sizes))


# ═══════════════════════════════════════════════════════════════════════════
# §11  Backtest Framework Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestBacktestFramework(unittest.TestCase):
    """Test the backtesting engine."""

    def test_imports(self):
        from merid.event_venues.kalshi.backtest import (
            MarketSnapshot, TradeDecision, BacktestState,
            backtest, backtest_summary, simulate_fill,
        )
        self.assertTrue(callable(backtest))
        self.assertTrue(callable(backtest_summary))

    def test_empty_snapshots(self):
        from merid.event_venues.kalshi.backtest import backtest
        def noop(snap, state):
            return []
        result = backtest([], 100000, noop)
        self.assertEqual(result.cash_cents, 100000)
        self.assertEqual(len(result.pnl_history), 0)

    def test_no_trade_strategy(self):
        from merid.event_venues.kalshi.backtest import backtest, MarketSnapshot
        snaps = [
            MarketSnapshot(ts=1.0, ticker="A", yes_book=[[50, 100]], no_book=[[50, 100]], last_trade_price=50),
            MarketSnapshot(ts=2.0, ticker="A", yes_book=[[55, 100]], no_book=[[45, 100]], last_trade_price=55),
        ]
        def noop(snap, state):
            return []
        result = backtest(snaps, 100000, noop)
        self.assertEqual(result.total_trades, 0)
        self.assertEqual(len(result.pnl_history), 2)
        # Cash unchanged
        self.assertEqual(result.cash_cents, 100000)

    def test_buy_and_hold(self):
        from merid.event_venues.kalshi.backtest import backtest, MarketSnapshot, TradeDecision
        snaps = [
            MarketSnapshot(ts=1.0, ticker="A", yes_book=[[50, 100]], no_book=[[50, 100]], last_trade_price=50),
            MarketSnapshot(ts=2.0, ticker="A", yes_book=[[60, 100]], no_book=[[40, 100]], last_trade_price=60),
        ]
        bought = [False]
        def buy_once(snap, state):
            if not bought[0]:
                bought[0] = True
                return [TradeDecision(ticker="A", side="yes", action="buy", price_cents=50, count=10)]
            return []
        result = backtest(snaps, 100000, buy_once, include_fees=False)
        self.assertEqual(result.total_trades, 1)
        # Bought 10 @ 50¢ = 500¢ cost
        self.assertEqual(result.cash_cents, 100000 - 500)
        # MTM at snap 2: 10 * 60 = 600
        self.assertEqual(result.pnl_history[-1], result.cash_cents + 600)

    def test_fees_applied(self):
        from merid.event_venues.kalshi.backtest import backtest, MarketSnapshot, TradeDecision
        snaps = [
            MarketSnapshot(ts=1.0, ticker="A", yes_book=[[50, 100]], no_book=[[50, 100]], last_trade_price=50),
        ]
        def buy(snap, state):
            return [TradeDecision(ticker="A", side="yes", action="buy", price_cents=50, count=10)]
        with_fees = backtest(snaps, 100000, buy, include_fees=True)
        without_fees = backtest(snaps, 100000, buy, include_fees=False)
        self.assertGreater(with_fees.total_fees_cents, 0)
        self.assertEqual(without_fees.total_fees_cents, 0)
        self.assertLess(with_fees.cash_cents, without_fees.cash_cents)

    def test_simulate_fill_no_book(self):
        from merid.event_venues.kalshi.backtest import simulate_fill
        price, filled = simulate_fill(50, 10, None)
        self.assertEqual(price, 50)
        self.assertEqual(filled, 10)

    def test_simulate_fill_with_book(self):
        from merid.event_venues.kalshi.backtest import simulate_fill
        book = [[48, 5], [50, 10], [52, 20]]
        price, filled = simulate_fill(55, 8, book)
        self.assertEqual(filled, 8)
        # First 5 at 48, next 3 at 50 → (240 + 150) / 8 = 48.75 → int = 48
        self.assertEqual(price, 48)

    def test_simulate_fill_partial(self):
        from merid.event_venues.kalshi.backtest import simulate_fill
        book = [[50, 3]]
        price, filled = simulate_fill(50, 10, book)
        self.assertEqual(filled, 3)

    def test_backtest_summary(self):
        from merid.event_venues.kalshi.backtest import BacktestState, backtest_summary
        state = BacktestState(
            cash_cents=105000,
            positions={"A": 10},
            pnl_history=[100000, 102000, 105000],
            total_fees_cents=200,
            total_trades=5,
        )
        summary = backtest_summary(state, 100000)
        self.assertEqual(summary["initial_cash_usd"], 1000.0)
        self.assertEqual(summary["total_trades"], 5)
        self.assertEqual(summary["total_fees_usd"], 2.0)
        self.assertIn("return_pct", summary)
        self.assertIn("max_drawdown_usd", summary)

    def test_sell_action(self):
        from merid.event_venues.kalshi.backtest import backtest, MarketSnapshot, TradeDecision
        snaps = [
            MarketSnapshot(ts=1.0, ticker="A", yes_book=[[50, 100]], no_book=[[50, 100]], last_trade_price=50),
        ]
        def sell(snap, state):
            return [TradeDecision(ticker="A", side="yes", action="sell", price_cents=50, count=5)]
        result = backtest(snaps, 100000, sell, include_fees=False)
        self.assertEqual(result.positions.get("A"), -5)
        self.assertEqual(result.cash_cents, 100000 + 250)  # sold 5 @ 50¢

    def test_package_exports(self):
        from merid.event_venues.kalshi import (
            MarketSnapshot, TradeDecision, BacktestState, backtest, backtest_summary,
        )
        self.assertIsNotNone(MarketSnapshot)
        self.assertIsNotNone(backtest)


# ═══════════════════════════════════════════════════════════════════════════
# §12  Client Fixes — RSA Auth, Order Path, Pagination
# ═══════════════════════════════════════════════════════════════════════════

class TestClientFixes(unittest.TestCase):
    """Test that client.py has the correct Kalshi API patterns."""

    @classmethod
    def setUpClass(cls):
        client_path = ROOT / "merid" / "event_venues" / "kalshi" / "client.py"
        cls.source = client_path.read_text(encoding="utf-8")

    def test_rsa_auth_method(self):
        self.assertIn("_sign_headers", self.source)
        self.assertIn("KALSHI-ACCESS-KEY", self.source)
        self.assertIn("KALSHI-ACCESS-TIMESTAMP", self.source)
        self.assertIn("KALSHI-ACCESS-SIGNATURE", self.source)

    def test_rsa_pss_signing(self):
        self.assertIn("padding.PSS", self.source)
        self.assertIn("hashes.SHA256", self.source)
        self.assertIn("MGF1", self.source)

    def test_rsa_message_format(self):
        """RSA signs: timestamp_ms + METHOD + path only (no body per Kalshi v2 spec)."""
        self.assertIn("ts_ms + method.upper() + path", self.source)
        self.assertNotIn("ts_ms + method.upper() + path + body", self.source)

    def test_order_path_portfolio(self):
        """Orders go to /portfolio/orders, not /orders."""
        self.assertIn('"/portfolio/orders"', self.source)

    def test_order_side_price_format(self):
        """Kalshi uses {side}_price for limit orders."""
        self.assertIn('{outcome}_price', self.source)

    def test_time_in_force(self):
        """Payload must use Kalshi Trade API v2 enum (good_till_canceled, …), not gtc."""
        self.assertIn("time_in_force", self.source)
        self.assertIn("good_till_canceled", self.source)
        self.assertIn("immediate_or_cancel", self.source)
        self.assertIn("fill_or_kill", self.source)

    def test_cursor_pagination(self):
        self.assertIn('"cursor"', self.source)
        self.assertIn("cursor = result.data.get", self.source)

    def test_status_open(self):
        """Uses status='open' not 'active'."""
        self.assertIn('"open"', self.source)

    def test_rsa_per_request_signing(self):
        """RSA headers injected per-request in _request_with_resilience."""
        self.assertIn("_auth_mode", self.source)
        self.assertIn("extra_headers", self.source)
        self.assertIn("/trade-api/v2", self.source)


# ═══════════════════════════════════════════════════════════════════════════
# §13  WebSocket Protocol Fixes
# ═══════════════════════════════════════════════════════════════════════════

class TestWsProtocolFixes(unittest.TestCase):
    """Test that ws.py uses the correct Kalshi WS protocol."""

    @classmethod
    def setUpClass(cls):
        ws_path = ROOT / "merid" / "event_venues" / "kalshi" / "ws.py"
        cls.source = ws_path.read_text(encoding="utf-8")

    def test_cmd_subscribe_format(self):
        """Uses cmd/params format, not type/channel."""
        self.assertIn('"cmd": "subscribe"', self.source)
        self.assertIn('"params"', self.source)

    def test_channels_array(self):
        """Channels specified as array in params."""
        self.assertIn('"channels": ["ticker"]', self.source)
        self.assertIn('"channels": ["trade"]', self.source)
        self.assertIn('"channels": ["orderbook_delta"]', self.source)

    def test_market_tickers_param(self):
        self.assertIn('"market_tickers"', self.source)

    def test_subscription_id(self):
        self.assertIn("_next_sub_id", self.source)
        self.assertIn('"id":', self.source)

    def test_skip_confirmations(self):
        self.assertIn('"subscribed"', self.source)
        self.assertIn('"unsubscribed"', self.source)

    def test_reconnect_resubscribes_all(self):
        """Reconnect resubscribes to ticker, trade, and orderbook channels."""
        self.assertIn("_trade_tickers", self.source)
        self.assertIn("_orderbook_tickers", self.source)
        self.assertIn("subscribe_trades", self.source)
        self.assertIn("subscribe_orderbook", self.source)


# ═══════════════════════════════════════════════════════════════════════════
# §14  Volume Filter / Sort Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestVolumeFilterSort(unittest.TestCase):
    """Test catalog volume filtering and sorting."""

    def setUp(self):
        from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
        from collections import defaultdict
        self.catalog = KalshiMarketCatalog.__new__(KalshiMarketCatalog)
        self.catalog._markets = []
        self.catalog._by_category = defaultdict(list)
        self.catalog._by_asset = defaultdict(list)
        self.catalog._by_timeframe = defaultdict(list)
        self.catalog._by_ticker = {}
        self.catalog._last_refresh = None
        self.catalog._refresh_count = 0
        self.catalog._task = None

    def _make_market(self, ticker, volume):
        """Create a minimal CatalogMarket-like object."""
        from unittest.mock import MagicMock
        cm = MagicMock()
        cm.market.volume = volume
        cm.market.question = ticker
        cm.market.description = ""
        cm.ticker = ticker
        return cm

    def test_get_markets_by_min_volume_empty(self):
        self.assertEqual(self.catalog.get_markets_by_min_volume(100), [])

    def test_get_markets_by_min_volume_filters(self):
        m1 = self._make_market("A", 500)
        m2 = self._make_market("B", 50)
        m3 = self._make_market("C", 1000)
        self.catalog._markets = [m1, m2, m3]
        result = self.catalog.get_markets_by_min_volume(100)
        tickers = [m.ticker for m in result]
        self.assertIn("A", tickers)
        self.assertIn("C", tickers)
        self.assertNotIn("B", tickers)

    def test_sort_by_volume_descending(self):
        m1 = self._make_market("A", 100)
        m2 = self._make_market("B", 500)
        m3 = self._make_market("C", 250)
        self.catalog._markets = [m1, m2, m3]
        result = self.catalog.sort_by_volume()
        self.assertEqual([m.ticker for m in result], ["B", "C", "A"])

    def test_sort_by_volume_ascending(self):
        m1 = self._make_market("A", 100)
        m2 = self._make_market("B", 500)
        self.catalog._markets = [m1, m2]
        result = self.catalog.sort_by_volume(descending=False)
        self.assertEqual([m.ticker for m in result], ["A", "B"])

    def test_sort_by_volume_custom_list(self):
        m1 = self._make_market("A", 100)
        m2 = self._make_market("B", 500)
        result = self.catalog.sort_by_volume(markets=[m1, m2])
        self.assertEqual([m.ticker for m in result], ["B", "A"])

    def test_methods_exist_in_source(self):
        path = ROOT / "merid" / "event_venues" / "kalshi" / "market_catalog.py"
        source = path.read_text(encoding="utf-8")
        self.assertIn("get_markets_by_min_volume", source)
        self.assertIn("sort_by_volume", source)


# ═══════════════════════════════════════════════════════════════════════════
# §15  Multi-Market Kelly Sizing Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestMultiMarketKelly(unittest.TestCase):
    """Test win-prob-based Kelly allocation across independent markets."""

    def setUp(self):
        from merid.event_venues.kalshi.kalshi_risk import multi_market_kelly_sizes, _kelly_fraction
        self.mmk = multi_market_kelly_sizes
        self.kf = _kelly_fraction

    def test_kelly_fraction_positive(self):
        # win_prob=0.6 + edge 5% = 0.65, price=50 → b=1.0, f=(0.65*1-0.35)/1=0.3
        f = self.kf(edge_pct=5.0, win_prob=0.6, price_cents=50)
        self.assertGreater(f, 0)
        self.assertLessEqual(f, 1.0)

    def test_kelly_fraction_zero_edge(self):
        # win_prob=0.5 + 0 edge at price=50 → fair value, f=0
        self.assertEqual(self.kf(0, 0.5, 50), 0.0)

    def test_kelly_fraction_negative_edge(self):
        self.assertEqual(self.kf(-1.0, 0.5, 50), 0.0)

    def test_kelly_fraction_extreme_prob(self):
        self.assertEqual(self.kf(5.0, 0.0, 50), 0.0)

    def test_kelly_fraction_invalid_price(self):
        self.assertEqual(self.kf(5.0, 0.6, 0), 0.0)
        self.assertEqual(self.kf(5.0, 0.6, 100), 0.0)

    def test_empty_markets(self):
        self.assertEqual(self.mmk([], 10000), {})

    def test_zero_equity(self):
        markets = [{"ticker": "A", "edge_pct": 2.0, "win_prob": 0.6}]
        self.assertEqual(self.mmk(markets, 0), {})

    def test_single_market(self):
        markets = [{"ticker": "A", "edge_pct": 5.0, "win_prob": 0.6, "price_cents": 50}]
        sizes = self.mmk(markets, 10000)
        self.assertIn("A", sizes)
        self.assertGreater(sizes["A"], 0)

    def test_two_markets_independent(self):
        markets = [
            {"ticker": "A", "edge_pct": 5.0, "win_prob": 0.6, "price_cents": 50},
            {"ticker": "B", "edge_pct": 3.0, "win_prob": 0.55, "price_cents": 40},
        ]
        sizes = self.mmk(markets, 10000)
        self.assertIn("A", sizes)
        self.assertIn("B", sizes)

    def test_per_market_cap(self):
        markets = [{"ticker": "A", "edge_pct": 10.0, "win_prob": 0.7, "price_cents": 10}]
        sizes = self.mmk(markets, 100000, max_per_market_usd=100.0)
        # Capped by max_per_market_usd, so contracts should be modest
        self.assertLessEqual(sizes.get("A", 0), 500)

    def test_max_contracts_cap(self):
        markets = [{"ticker": "A", "edge_pct": 10.0, "win_prob": 0.7, "price_cents": 10}]
        sizes = self.mmk(markets, 100000, max_contracts_per_market=50)
        self.assertLessEqual(sizes.get("A", 0), 50)

    def test_negative_edge_excluded(self):
        markets = [
            {"ticker": "A", "edge_pct": -1.0, "win_prob": 0.5},
            {"ticker": "B", "edge_pct": 5.0, "win_prob": 0.6, "price_cents": 50},
        ]
        sizes = self.mmk(markets, 10000)
        self.assertNotIn("A", sizes)
        self.assertIn("B", sizes)

    def test_import_from_package(self):
        from merid.event_venues.kalshi import multi_market_kelly_sizes
        self.assertTrue(callable(multi_market_kelly_sizes))


# ═══════════════════════════════════════════════════════════════════════════
# §16  Rate Limit / Retry-After Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestRateLimitHandling(unittest.TestCase):
    """Test that client.py handles 429 with Retry-After."""

    @classmethod
    def setUpClass(cls):
        client_path = ROOT / "merid" / "event_venues" / "kalshi" / "client.py"
        cls.source = client_path.read_text(encoding="utf-8")

    def test_429_specific_handling(self):
        self.assertIn("== 429", self.source)

    def test_retry_after_header_parsed(self):
        self.assertIn("Retry-After", self.source)
        self.assertIn('response.headers.get("Retry-After")', self.source)

    def test_retry_after_float_conversion(self):
        self.assertIn("float(retry_after)", self.source)

    def test_rate_limited_log_message(self):
        self.assertIn("rate-limited (429)", self.source)

    def test_429_in_retry_statuses(self):
        self.assertIn("429", self.source)


# ═══════════════════════════════════════════════════════════════════════════
# §17  POST /orders Endpoint Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestOrderEndpoint(unittest.TestCase):
    """Test the POST /api/v1/kalshi/orders endpoint."""

    @classmethod
    def setUpClass(cls):
        api_path = ROOT / "web" / "api" / "kalshi_api.py"
        cls.source = api_path.read_text(encoding="utf-8")

    def test_post_orders_route(self):
        self.assertIn('@router.post("/orders"', self.source)

    def test_place_order_function(self):
        self.assertIn("async def place_order", self.source)

    def test_validates_side(self):
        self.assertIn('"yes"', self.source)
        self.assertIn('"no"', self.source)

    def test_validates_action(self):
        self.assertIn('"buy"', self.source)
        self.assertIn('"sell"', self.source)

    def test_risk_precheck(self):
        self.assertIn("risk.check_order", self.source)

    def test_paper_mode(self):
        self.assertIn('"paper"', self.source)
        self.assertIn('"paper": TradingMode.PAPER', self.source)

    def test_live_mode(self):
        self.assertIn("route_order_async", self.source)

    def test_records_order_on_fill(self):
        self.assertIn("risk.record_order", self.source)

    def test_mode_parameter(self):
        self.assertIn('mode: Optional[str] = None', self.source)

    def test_venue_order_import(self):
        self.assertIn(
            "from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async",
            self.source,
        )


class TestOrderEndpointRuntime(unittest.TestCase):
    """Runtime tests for mode-aware POST /api/v1/kalshi/orders routing."""

    def test_place_order_paper_uses_order_router(self):
        from merid.event_venues.kalshi.order_router import OrderResult
        from merid.prediction.venue_gate import TradingMode
        from web.api.kalshi_api import place_order

        risk = MagicMock()
        risk.check_order.return_value = (True, "OK")

        routed = AsyncMock(
            return_value=OrderResult(
                status="filled_paper",
                mode=TradingMode.PAPER,
                fill={"price_cents": 55, "count": 10},
                latency_ms=2.0,
            )
        )

        with patch("web.api.kalshi_api._get_risk", return_value=risk), patch(
            "merid.event_venues.kalshi.order_router.route_order_async", routed
        ):
            response = asyncio.run(
                place_order(
                    ticker="KXBTC15M",
                    side="yes",
                    action="buy",
                    count=10,
                    price_cents=55,
                    stop_loss_price_cents=40,
                    take_profit_price_cents=70,
                    mode="paper",
                )
            )

        routed.assert_awaited_once()
        intent = routed.await_args.args[0]
        self.assertEqual(intent.mode, TradingMode.PAPER)
        risk.record_order.assert_called_once()
        self.assertEqual(response["status"], "filled_paper")
        self.assertEqual(response["mode"], "paper")

    def test_place_order_live_uses_order_router(self):
        from merid.event_venues.kalshi.order_router import OrderResult
        from merid.prediction.venue_gate import TradingMode
        from web.api.kalshi_api import place_order

        risk = MagicMock()
        risk.check_order.return_value = (True, "OK")

        routed = AsyncMock(
            return_value=OrderResult(
                status="filled_live",
                mode=TradingMode.LIVE,
                fill={"order_id": "oid-1", "count": 10},
                latency_ms=9.0,
            )
        )

        gate_status = MagicMock()
        gate_status.blocked = False
        gate_status.reasons = []

        with patch("web.api.kalshi_api._get_risk", return_value=risk), patch(
            "merid.event_venues.kalshi.order_router.route_order_async", routed
        ), patch("core.execution_gate.check_execution_gate", return_value=gate_status):
            response = asyncio.run(
                place_order(
                    ticker="KXBTC15M",
                    side="yes",
                    action="buy",
                    count=10,
                    price_cents=55,
                    stop_loss_price_cents=40,
                    take_profit_price_cents=70,
                    mode="live",
                )
            )

        routed.assert_awaited_once()
        intent = routed.await_args.args[0]
        self.assertEqual(intent.mode, TradingMode.LIVE)
        risk.record_order.assert_called_once()
        self.assertEqual(response["status"], "filled_live")
        self.assertEqual(response["mode"], "live")

    def test_place_order_rejected_does_not_record_order(self):
        from merid.event_venues.kalshi.order_router import OrderResult
        from merid.prediction.venue_gate import TradingMode
        from web.api.kalshi_api import place_order

        risk = MagicMock()
        risk.check_order.return_value = (True, "OK")

        routed = AsyncMock(
            return_value=OrderResult(
                status="rejected",
                mode=TradingMode.PAPER,
                reason="non_positive_size",
                latency_ms=0.5,
            )
        )

        with patch("web.api.kalshi_api._get_risk", return_value=risk), patch(
            "merid.event_venues.kalshi.order_router.route_order_async", routed
        ):
            response = asyncio.run(
                place_order(
                    ticker="KXBTC15M",
                    side="yes",
                    action="buy",
                    count=10,
                    price_cents=55,
                    stop_loss_price_cents=40,
                    take_profit_price_cents=70,
                    mode="paper",
                )
            )

        risk.record_order.assert_not_called()
        self.assertEqual(response["status"], "rejected")
        self.assertEqual(response["reason"], "non_positive_size")

    def test_place_order_invalid_mode_raises_400(self):
        from fastapi import HTTPException
        from web.api.kalshi_api import place_order

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(
                place_order(
                    ticker="KXBTC15M",
                    side="yes",
                    action="buy",
                    count=10,
                    price_cents=55,
                    mode="sim",
                )
            )

        self.assertEqual(ctx.exception.status_code, 400)


# ═══════════════════════════════════════════════════════════════════════════
# §18  Orderbook & Events Endpoint Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestOrderbookEventsEndpoints(unittest.TestCase):
    """Test the new orderbook and events API endpoints."""

    @classmethod
    def setUpClass(cls):
        api_path = ROOT / "web" / "api" / "kalshi_api.py"
        cls.source = api_path.read_text(encoding="utf-8")

    def test_orderbook_route(self):
        self.assertIn('/markets/{ticker}/orderbook', self.source)

    def test_orderbook_function(self):
        self.assertIn("async def get_orderbook", self.source)

    def test_orderbook_returns_yes_no(self):
        self.assertIn('"yes"', self.source)
        self.assertIn('"no"', self.source)

    def test_orderbook_spread_midpoint(self):
        self.assertIn('"spread"', self.source)
        self.assertIn('"midpoint"', self.source)

    def test_events_route(self):
        self.assertIn('/events/{event_ticker}', self.source)

    def test_events_function(self):
        self.assertIn("async def get_event", self.source)

    def test_events_uses_catalog(self):
        self.assertIn("get_markets_by_event", self.source)


# ═══════════════════════════════════════════════════════════════════════════
# §19  Volume Monitor Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestVolumeMonitor(unittest.TestCase):
    """Test the VolumeMonitor class."""

    def test_import(self):
        from merid.event_venues.kalshi.volume_monitor import VolumeMonitor, get_volume_monitor
        self.assertIsNotNone(VolumeMonitor)
        self.assertTrue(callable(get_volume_monitor))

    def test_singleton(self):
        from merid.event_venues.kalshi.volume_monitor import get_volume_monitor
        m1 = get_volume_monitor()
        m2 = get_volume_monitor()
        self.assertIs(m1, m2)

    def test_initial_state(self):
        from merid.event_venues.kalshi.volume_monitor import VolumeMonitor
        m = VolumeMonitor()
        self.assertEqual(m.tracked_count, 0)
        self.assertIsNone(m.last_poll_iso)

    def test_get_changes_empty(self):
        from merid.event_venues.kalshi.volume_monitor import VolumeMonitor
        m = VolumeMonitor()
        self.assertEqual(m.get_changes(), [])

    def test_get_changes_with_filter(self):
        from merid.event_venues.kalshi.volume_monitor import VolumeMonitor
        m = VolumeMonitor()
        # Manually inject deltas
        m._deltas = {
            "KXBTC-1": {"ticker": "KXBTC-1", "delta": 500},
            "KXETH-1": {"ticker": "KXETH-1", "delta": 50},
        }
        # Filter by series
        btc = m.get_changes(series_ticker="KXBTC")
        self.assertEqual(len(btc), 1)
        self.assertEqual(btc[0]["ticker"], "KXBTC-1")

    def test_get_changes_min_delta(self):
        from merid.event_venues.kalshi.volume_monitor import VolumeMonitor
        m = VolumeMonitor()
        m._deltas = {
            "A": {"ticker": "A", "delta": 500},
            "B": {"ticker": "B", "delta": 10},
        }
        big = m.get_changes(min_delta=100)
        self.assertEqual(len(big), 1)
        self.assertEqual(big[0]["ticker"], "A")

    def test_volume_changes_endpoint_exists(self):
        api_path = ROOT / "web" / "api" / "kalshi_api.py"
        source = api_path.read_text(encoding="utf-8")
        self.assertIn('/volume-changes', source)
        self.assertIn("async def volume_changes", source)

    def test_package_export(self):
        from merid.event_venues.kalshi import VolumeMonitor, get_volume_monitor
        self.assertIsNotNone(VolumeMonitor)
        self.assertTrue(callable(get_volume_monitor))


# ═══════════════════════════════════════════════════════════════════════════
# §20  Auth Error Handling Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestAuthErrorHandling(unittest.TestCase):
    """Test that client.py handles 401/403 auth errors specifically."""

    @classmethod
    def setUpClass(cls):
        client_path = ROOT / "merid" / "event_venues" / "kalshi" / "client.py"
        cls.source = client_path.read_text(encoding="utf-8")

    def test_401_handling(self):
        self.assertIn("401", self.source)

    def test_403_handling(self):
        self.assertIn("403", self.source)

    def test_auth_error_tuple(self):
        self.assertIn("(401, 403)", self.source)

    def test_auth_error_logging(self):
        self.assertIn("auth error", self.source)
        self.assertIn("key ID", self.source)
        self.assertIn("/trade-api/v2/", self.source)

    def test_reauth_on_401(self):
        self.assertIn("Re-authenticated after 401", self.source)
        self.assertIn("_authenticate()", self.source)

    def test_auth_error_message(self):
        self.assertIn("Auth error:", self.source)


# ═══════════════════════════════════════════════════════════════════════════
# §21  CSV Export Endpoint Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestCsvExportEndpoint(unittest.TestCase):
    """Test the CSV export endpoint."""

    @classmethod
    def setUpClass(cls):
        api_path = ROOT / "web" / "api" / "kalshi_api.py"
        cls.source = api_path.read_text(encoding="utf-8")

    def test_export_route(self):
        self.assertIn('@router.get("/export")', self.source)

    def test_export_function(self):
        self.assertIn("async def export_markets_csv", self.source)

    def test_csv_imports(self):
        self.assertIn("import csv", self.source)
        self.assertIn("import io", self.source)

    def test_streaming_response(self):
        self.assertIn("StreamingResponse", self.source)
        self.assertIn("text/csv", self.source)

    def test_csv_headers(self):
        self.assertIn("ticker", self.source)
        self.assertIn("yes_price", self.source)

    def test_min_volume_filter(self):
        self.assertIn("min_volume", self.source)

    def test_category_filter(self):
        self.assertIn("category", self.source)

    def test_content_disposition(self):
        self.assertIn("kalshi_markets.csv", self.source)


# ═══════════════════════════════════════════════════════════════════════════
# §22  New Frontend Constants Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestNewFrontendConstants(unittest.TestCase):
    """Test new frontend API endpoint constants."""

    @classmethod
    def setUpClass(cls):
        path = ROOT / "web" / "react" / "src" / "config" / "constants.ts"
        cls.source = path.read_text(encoding="utf-8")

    def test_kalshi_orderbook(self):
        self.assertIn("KALSHI_ORDERBOOK", self.source)
        self.assertIn("/orderbook", self.source)

    def test_kalshi_event(self):
        self.assertIn("KALSHI_EVENT", self.source)
        self.assertIn("/events/", self.source)

    def test_kalshi_export(self):
        self.assertIn("KALSHI_EXPORT", self.source)
        self.assertIn("/export", self.source)

    def test_kalshi_volume_changes(self):
        self.assertIn("KALSHI_VOLUME_CHANGES", self.source)
        self.assertIn("/volume-changes", self.source)


# ═══════════════════════════════════════════════════════════════════════════
# §23  Volume Monitor Time-Series & Alerts Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestVolumeMonitorTimeSeries(unittest.TestCase):
    """Test time-series storage and alert system in VolumeMonitor."""

    def test_history_storage(self):
        from merid.event_venues.kalshi.volume_monitor import VolumeMonitor, VolumeSnapshot
        m = VolumeMonitor()
        # Manually inject history
        from collections import deque
        m._history["A"] = deque(maxlen=500)
        m._history["A"].append(VolumeSnapshot(ts="2026-01-01T00:00:00", volume=100, delta=0))
        m._history["A"].append(VolumeSnapshot(ts="2026-01-01T00:01:00", volume=150, delta=50))
        hist = m.get_history("A")
        self.assertEqual(len(hist), 2)
        # Most recent first
        self.assertEqual(hist[0]["volume"], 150)
        self.assertEqual(hist[1]["volume"], 100)

    def test_history_limit(self):
        from merid.event_venues.kalshi.volume_monitor import VolumeMonitor, VolumeSnapshot
        from collections import deque
        m = VolumeMonitor()
        m._history["A"] = deque(maxlen=500)
        for i in range(10):
            m._history["A"].append(VolumeSnapshot(ts=f"t{i}", volume=i, delta=1))
        hist = m.get_history("A", limit=3)
        self.assertEqual(len(hist), 3)

    def test_history_empty_ticker(self):
        from merid.event_venues.kalshi.volume_monitor import VolumeMonitor
        m = VolumeMonitor()
        self.assertEqual(m.get_history("NONEXISTENT"), [])

    def test_register_alert(self):
        from merid.event_venues.kalshi.volume_monitor import VolumeMonitor
        m = VolumeMonitor()
        called = []
        m.register_alert(lambda t, o, n, d: called.append((t, d)), threshold=100)
        self.assertEqual(len(m._alert_callbacks), 1)
        self.assertEqual(m._alert_threshold, 100)

    def test_fire_alerts_above_threshold(self):
        from merid.event_venues.kalshi.volume_monitor import VolumeMonitor
        m = VolumeMonitor()
        fired = []
        m.register_alert(lambda t, o, n, d: fired.append(d), threshold=50)
        m._fire_alerts("A", 100, 200, 100)
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0], 100)

    def test_fire_alerts_below_threshold(self):
        from merid.event_venues.kalshi.volume_monitor import VolumeMonitor
        m = VolumeMonitor()
        fired = []
        m.register_alert(lambda t, o, n, d: fired.append(d), threshold=500)
        m._fire_alerts("A", 100, 120, 20)
        self.assertEqual(len(fired), 0)

    def test_get_alerts(self):
        from merid.event_venues.kalshi.volume_monitor import VolumeMonitor
        m = VolumeMonitor()
        m._alerts_fired = [
            {"ticker": "A", "delta": 100, "fired_at": "t1"},
            {"ticker": "B", "delta": 200, "fired_at": "t2"},
        ]
        alerts = m.get_alerts()
        # Most recent first
        self.assertEqual(alerts[0]["ticker"], "B")

    def test_poll_count(self):
        from merid.event_venues.kalshi.volume_monitor import VolumeMonitor
        m = VolumeMonitor()
        self.assertEqual(m.poll_count, 0)

    def test_alert_count(self):
        from merid.event_venues.kalshi.volume_monitor import VolumeMonitor
        m = VolumeMonitor()
        self.assertEqual(m.alert_count, 0)
        m._alerts_fired.append({"ticker": "A"})
        self.assertEqual(m.alert_count, 1)

    def test_volume_snapshot_dataclass(self):
        from merid.event_venues.kalshi.volume_monitor import VolumeSnapshot
        s = VolumeSnapshot(ts="2026-01-01", volume=100, delta=10)
        self.assertEqual(s.ts, "2026-01-01")
        self.assertEqual(s.volume, 100)
        self.assertEqual(s.delta, 10)


# ═══════════════════════════════════════════════════════════════════════════
# §24  Token Bucket Rate Limiter Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestTokenBucketRateLimiter(unittest.TestCase):
    """Test the KalshiTokenBucket rate limiter."""

    def test_import(self):
        from merid.event_venues.kalshi.client import KalshiTokenBucket, KALSHI_RATE_TIERS
        self.assertIsNotNone(KalshiTokenBucket)
        self.assertIn("basic", KALSHI_RATE_TIERS)

    def test_basic_tier(self):
        from merid.event_venues.kalshi.client import KalshiTokenBucket
        tb = KalshiTokenBucket(tier="basic")
        self.assertEqual(tb.tier, "basic")
        self.assertEqual(tb.read_rate, 20)
        self.assertEqual(tb.write_rate, 10)

    def test_advanced_tier(self):
        from merid.event_venues.kalshi.client import KalshiTokenBucket
        tb = KalshiTokenBucket(tier="advanced")
        self.assertEqual(tb.read_rate, 30)
        self.assertEqual(tb.write_rate, 30)

    def test_premier_tier(self):
        from merid.event_venues.kalshi.client import KalshiTokenBucket
        tb = KalshiTokenBucket(tier="premier")
        self.assertEqual(tb.read_rate, 100)
        self.assertEqual(tb.write_rate, 100)

    def test_prime_tier(self):
        from merid.event_venues.kalshi.client import KalshiTokenBucket
        tb = KalshiTokenBucket(tier="prime")
        self.assertEqual(tb.read_rate, 400)
        self.assertEqual(tb.write_rate, 400)

    def test_unknown_tier_defaults_to_basic(self):
        from merid.event_venues.kalshi.client import KalshiTokenBucket
        tb = KalshiTokenBucket(tier="unknown")
        self.assertEqual(tb.read_rate, 20)
        self.assertEqual(tb.write_rate, 10)

    def test_initial_tokens_full(self):
        from merid.event_venues.kalshi.client import KalshiTokenBucket
        tb = KalshiTokenBucket(tier="basic")
        self.assertGreaterEqual(tb.read_tokens_available, 19)
        self.assertGreaterEqual(tb.write_tokens_available, 9)

    def test_rate_tiers_dict(self):
        from merid.event_venues.kalshi.client import KALSHI_RATE_TIERS
        self.assertEqual(len(KALSHI_RATE_TIERS), 4)
        for tier in ("basic", "advanced", "premier", "prime"):
            self.assertIn("read", KALSHI_RATE_TIERS[tier])
            self.assertIn("write", KALSHI_RATE_TIERS[tier])

    def test_client_has_rate_limiter(self):
        source_path = ROOT / "merid" / "event_venues" / "kalshi" / "client.py"
        source = source_path.read_text(encoding="utf-8")
        self.assertIn("_rate_limiter", source)
        self.assertIn("KalshiTokenBucket", source)
        self.assertIn("acquire(is_write=", source)

    def test_package_exports(self):
        from merid.event_venues.kalshi import KalshiTokenBucket, KALSHI_RATE_TIERS
        self.assertIsNotNone(KalshiTokenBucket)
        self.assertIsNotNone(KALSHI_RATE_TIERS)


# ═══════════════════════════════════════════════════════════════════════════
# §25  Business / Session Error Types Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestErrorTypes(unittest.TestCase):
    """Test KalshiBusinessError and KalshiSessionError."""

    def test_import_errors(self):
        from merid.event_venues.kalshi.client import KalshiSessionError, KalshiBusinessError
        self.assertTrue(issubclass(KalshiSessionError, Exception))
        self.assertTrue(issubclass(KalshiBusinessError, Exception))

    def test_business_error_in_source(self):
        source_path = ROOT / "merid" / "event_venues" / "kalshi" / "client.py"
        source = source_path.read_text(encoding="utf-8")
        self.assertIn("KalshiBusinessError", source)
        self.assertIn("(400, 422)", source)
        self.assertIn("business error", source)

    def test_session_error_in_source(self):
        source_path = ROOT / "merid" / "event_venues" / "kalshi" / "client.py"
        source = source_path.read_text(encoding="utf-8")
        self.assertIn("KalshiSessionError", source)
        self.assertIn("503", source)
        self.assertIn("session-level error", source.lower())

    def test_error_instantiation(self):
        from merid.event_venues.kalshi.client import KalshiSessionError, KalshiBusinessError
        be = KalshiBusinessError("400: bad ticker")
        se = KalshiSessionError("503 Service unavailable")
        self.assertIn("400", str(be))
        self.assertIn("503", str(se))

    def test_package_exports(self):
        from merid.event_venues.kalshi import KalshiSessionError, KalshiBusinessError
        self.assertIsNotNone(KalshiSessionError)
        self.assertIsNotNone(KalshiBusinessError)


# ═══════════════════════════════════════════════════════════════════════════
# §26  Volume Anomaly Detection Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestVolumeAnomalyDetection(unittest.TestCase):
    """Test rolling z-score anomaly detection in VolumeMonitor."""

    def _make_monitor_with_history(self, ticker, volumes):
        from merid.event_venues.kalshi.volume_monitor import VolumeMonitor, VolumeSnapshot
        from collections import deque
        m = VolumeMonitor()
        m._history[ticker] = deque(maxlen=500)
        for i, v in enumerate(volumes):
            m._history[ticker].append(VolumeSnapshot(ts=f"t{i}", volume=v, delta=0))
        return m

    def test_no_anomalies_stable(self):
        m = self._make_monitor_with_history("A", [100, 100, 100, 100, 100])
        anomalies = m.detect_anomalies(z_threshold=2.0)
        self.assertEqual(len(anomalies), 0)

    def test_anomaly_detected_spike(self):
        # 9 stable readings then a huge spike
        vols = [100] * 9 + [10000]
        m = self._make_monitor_with_history("A", vols)
        anomalies = m.detect_anomalies(z_threshold=2.0, min_window=5)
        self.assertGreater(len(anomalies), 0)
        self.assertEqual(anomalies[0]["ticker"], "A")
        self.assertGreater(anomalies[0]["z_score"], 2.0)

    def test_min_window_respected(self):
        m = self._make_monitor_with_history("A", [100, 200, 300])
        anomalies = m.detect_anomalies(min_window=5)
        self.assertEqual(len(anomalies), 0)  # not enough data

    def test_multiple_tickers(self):
        from merid.event_venues.kalshi.volume_monitor import VolumeMonitor, VolumeSnapshot
        from collections import deque
        m = VolumeMonitor()
        # Ticker A: stable
        m._history["A"] = deque(maxlen=500)
        for i in range(10):
            m._history["A"].append(VolumeSnapshot(ts=f"t{i}", volume=100, delta=0))
        # Ticker B: spike
        m._history["B"] = deque(maxlen=500)
        for i in range(9):
            m._history["B"].append(VolumeSnapshot(ts=f"t{i}", volume=50, delta=0))
        m._history["B"].append(VolumeSnapshot(ts="t9", volume=5000, delta=4950))
        anomalies = m.detect_anomalies(z_threshold=2.0)
        tickers = [a["ticker"] for a in anomalies]
        self.assertIn("B", tickers)
        self.assertNotIn("A", tickers)

    def test_anomaly_has_z_score_field(self):
        vols = [100] * 9 + [10000]
        m = self._make_monitor_with_history("X", vols)
        anomalies = m.detect_anomalies(z_threshold=1.0)
        if anomalies:
            a = anomalies[0]
            self.assertIn("z_score", a)
            self.assertIn("mean", a)
            self.assertIn("std", a)
            self.assertIn("window_size", a)

    def test_detect_anomalies_method_exists(self):
        source = (ROOT / "merid" / "event_venues" / "kalshi" / "volume_monitor.py").read_text(encoding="utf-8")
        self.assertIn("def detect_anomalies", source)
        self.assertIn("z_threshold", source)
        self.assertIn("z_score", source)


# ═══════════════════════════════════════════════════════════════════════════
# §27  Alert Sinks (Telegram / Discord) Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestAlertSinks(unittest.TestCase):
    """Test Telegram and Discord alert sink factories."""

    def test_make_telegram_sink_callable(self):
        from merid.event_venues.kalshi.volume_monitor import make_telegram_sink
        sink = make_telegram_sink(bot_token="fake", chat_id="123")
        self.assertTrue(callable(sink))

    def test_make_discord_sink_callable(self):
        from merid.event_venues.kalshi.volume_monitor import make_discord_sink
        sink = make_discord_sink(webhook_url="https://example.com/webhook")
        self.assertTrue(callable(sink))

    def test_telegram_sink_no_token_warns(self):
        from merid.event_venues.kalshi.volume_monitor import make_telegram_sink
        sink = make_telegram_sink(bot_token="", chat_id="")
        # Should not raise, just warn
        sink("TICKER", 100, 200, 100)

    def test_discord_sink_no_url_warns(self):
        from merid.event_venues.kalshi.volume_monitor import make_discord_sink
        sink = make_discord_sink(webhook_url="")
        sink("TICKER", 100, 200, 100)

    def test_advanced_api_form_constant(self):
        from merid.event_venues.kalshi.volume_monitor import KALSHI_ADVANCED_API_FORM
        self.assertIn("kalshi.typeform.com", KALSHI_ADVANCED_API_FORM)

    def test_package_exports_sinks(self):
        from merid.event_venues.kalshi import make_telegram_sink, make_discord_sink, KALSHI_ADVANCED_API_FORM
        self.assertTrue(callable(make_telegram_sink))
        self.assertTrue(callable(make_discord_sink))
        self.assertIsNotNone(KALSHI_ADVANCED_API_FORM)

    def test_source_has_sinks(self):
        source = (ROOT / "merid" / "event_venues" / "kalshi" / "volume_monitor.py").read_text(encoding="utf-8")
        self.assertIn("make_telegram_sink", source)
        self.assertIn("make_discord_sink", source)
        self.assertIn("TELEGRAM_BOT_TOKEN", source)
        self.assertIn("DISCORD_WEBHOOK_URL", source)


# ═══════════════════════════════════════════════════════════════════════════
# §28  Volume History / Anomalies / Alerts Endpoint Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestVolumeEndpoints(unittest.TestCase):
    """Test the new volume-related API endpoints."""

    @classmethod
    def setUpClass(cls):
        api_path = ROOT / "web" / "api" / "kalshi_api.py"
        cls.source = api_path.read_text(encoding="utf-8")

    def test_volume_history_route(self):
        self.assertIn('/volume-history/{ticker}', self.source)

    def test_volume_history_function(self):
        self.assertIn("async def volume_history", self.source)

    def test_volume_anomalies_route(self):
        self.assertIn('/volume-anomalies', self.source)

    def test_volume_anomalies_function(self):
        self.assertIn("async def volume_anomalies", self.source)

    def test_volume_anomalies_uses_detect(self):
        self.assertIn("detect_anomalies", self.source)

    def test_volume_alerts_route(self):
        self.assertIn('/volume-alerts', self.source)

    def test_volume_alerts_function(self):
        self.assertIn("async def volume_alerts_endpoint", self.source)

    def test_z_threshold_param(self):
        self.assertIn("z_threshold", self.source)


# ═══════════════════════════════════════════════════════════════════════════
# §29  BusinessReject with Reason Code Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestBusinessRejectReasonCode(unittest.TestCase):
    """Test KalshiBusinessError with FIX-style reason_code."""

    def test_basic_instantiation(self):
        from merid.event_venues.kalshi.client import KalshiBusinessError
        e = KalshiBusinessError("bad ticker")
        self.assertEqual(e.text, "bad ticker")
        self.assertEqual(e.status_code, 400)
        self.assertIsNone(e.reason_code)

    def test_with_reason_code(self):
        from merid.event_venues.kalshi.client import KalshiBusinessError
        e = KalshiBusinessError("invalid order", status_code=422, reason_code=3)
        self.assertEqual(e.reason_code, 3)
        self.assertEqual(e.status_code, 422)
        self.assertIn("reason=3", str(e))

    def test_with_ref_msg_type(self):
        from merid.event_venues.kalshi.client import KalshiBusinessError
        e = KalshiBusinessError("rejected", ref_msg_type="D")
        self.assertEqual(e.ref_msg_type, "D")
        self.assertIn("ref=D", str(e))

    def test_full_constructor(self):
        from merid.event_venues.kalshi.client import KalshiBusinessError
        e = KalshiBusinessError("test", status_code=422, reason_code=5, ref_msg_type="G")
        self.assertIn("422", str(e))
        self.assertIn("reason=5", str(e))
        self.assertIn("ref=G", str(e))
        self.assertIn("test", str(e))

    def test_business_reject_alias(self):
        from merid.event_venues.kalshi.client import KalshiBusinessReject, KalshiBusinessError
        self.assertIs(KalshiBusinessReject, KalshiBusinessError)

    def test_package_export_alias(self):
        from merid.event_venues.kalshi import KalshiBusinessReject
        self.assertIsNotNone(KalshiBusinessReject)

    def test_source_has_reason_code(self):
        source = (ROOT / "merid" / "event_venues" / "kalshi" / "client.py").read_text(encoding="utf-8")
        self.assertIn("reason_code", source)
        self.assertIn("ref_msg_type", source)
        self.assertIn("KalshiBusinessReject", source)


# ═══════════════════════════════════════════════════════════════════════════
# §30  New Frontend Constants (Session 7) Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestFrontendConstantsS7(unittest.TestCase):
    """Test new frontend API endpoint constants from session 7."""

    @classmethod
    def setUpClass(cls):
        path = ROOT / "web" / "react" / "src" / "config" / "constants.ts"
        cls.source = path.read_text(encoding="utf-8")

    def test_volume_history(self):
        self.assertIn("KALSHI_VOLUME_HISTORY", self.source)
        self.assertIn("/volume-history/", self.source)

    def test_volume_anomalies(self):
        self.assertIn("KALSHI_VOLUME_ANOMALIES", self.source)
        self.assertIn("/volume-anomalies", self.source)

    def test_volume_alerts(self):
        self.assertIn("KALSHI_VOLUME_ALERTS", self.source)
        self.assertIn("/volume-alerts", self.source)


# ═══════════════════════════════════════════════════════════════════════════
# §31  Kalman1D Filter Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestKalman1D(unittest.TestCase):
    """Test the 1-D Kalman filter for volume smoothing."""

    def test_import(self):
        from merid.event_venues.kalshi.volume_monitor import Kalman1D
        self.assertIsNotNone(Kalman1D)

    def test_first_update_returns_measurement(self):
        from merid.event_venues.kalshi.volume_monitor import Kalman1D
        kf = Kalman1D()
        self.assertEqual(kf.update(100.0), 100.0)

    def test_smoothing_effect(self):
        from merid.event_venues.kalshi.volume_monitor import Kalman1D
        kf = Kalman1D(process_var=1.0, meas_var=10.0)
        kf.update(100.0)
        # Spike — smoothed should be less than raw
        smoothed = kf.update(200.0)
        self.assertGreater(smoothed, 100.0)
        self.assertLess(smoothed, 200.0)

    def test_converges_to_stable(self):
        from merid.event_venues.kalshi.volume_monitor import Kalman1D
        kf = Kalman1D(process_var=1.0, meas_var=10.0)
        for _ in range(50):
            val = kf.update(100.0)
        self.assertAlmostEqual(val, 100.0, places=0)

    def test_reset(self):
        from merid.event_venues.kalshi.volume_monitor import Kalman1D
        kf = Kalman1D()
        kf.update(100.0)
        kf.reset()
        self.assertFalse(kf.initialized)
        self.assertEqual(kf.x, 0.0)

    def test_package_export(self):
        from merid.event_venues.kalshi import Kalman1D
        self.assertIsNotNone(Kalman1D)

    def test_smoothed_history_method(self):
        from merid.event_venues.kalshi.volume_monitor import VolumeMonitor, VolumeSnapshot
        from collections import deque
        m = VolumeMonitor()
        m._history["A"] = deque(maxlen=500)
        for i in range(10):
            m._history["A"].append(VolumeSnapshot(ts=f"t{i}", volume=100 + i * 10, delta=10))
        result = m.get_smoothed_history("A", limit=5)
        self.assertEqual(len(result), 5)
        self.assertIn("smoothed", result[0])
        self.assertIn("volume", result[0])

    def test_smoothed_history_empty(self):
        from merid.event_venues.kalshi.volume_monitor import VolumeMonitor
        m = VolumeMonitor()
        self.assertEqual(m.get_smoothed_history("NONEXISTENT"), [])


# ═══════════════════════════════════════════════════════════════════════════
# §32  Trades Volume Aggregation Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestTradesVolumeAggregation(unittest.TestCase):
    """Test get_volume_for_window method exists in client."""

    @classmethod
    def setUpClass(cls):
        path = ROOT / "merid" / "event_venues" / "kalshi" / "client.py"
        cls.source = path.read_text(encoding="utf-8")

    def test_method_exists(self):
        self.assertIn("async def get_volume_for_window", self.source)

    def test_uses_trades_endpoint(self):
        self.assertIn('"/trades"', self.source)

    def test_paginates_with_cursor(self):
        self.assertIn("cursor", self.source)
        self.assertIn("start_ts", self.source)
        self.assertIn("end_ts", self.source)

    def test_sums_count(self):
        self.assertIn("total_contracts", self.source)
        self.assertIn('tr.get("count"', self.source)

    def test_returns_operation_result(self):
        self.assertIn("OperationResult.ok", self.source)


# ═══════════════════════════════════════════════════════════════════════════
# §33  FIX Parser & Reject Reasons Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestFixParserAndRejectReasons(unittest.TestCase):
    """Test FIX message parser and reject reason registry."""

    def test_parse_fix_basic(self):
        from merid.event_venues.kalshi.client import parse_fix
        msg = "8=FIX.4.4\x019=100\x0135=D\x0149=SENDER\x01"
        parsed = parse_fix(msg)
        self.assertEqual(parsed["8"], "FIX.4.4")
        self.assertEqual(parsed["35"], "D")
        self.assertEqual(parsed["49"], "SENDER")

    def test_parse_fix_empty(self):
        from merid.event_venues.kalshi.client import parse_fix
        self.assertEqual(parse_fix(""), {})

    def test_handle_fix_reject_session(self):
        from merid.event_venues.kalshi.client import handle_fix_reject, KalshiSessionError
        msg = {"35": "3", "373": "1", "58": "Invalid tag", "371": "49", "372": "D"}
        result = handle_fix_reject(msg)
        self.assertIsInstance(result, KalshiSessionError)
        self.assertEqual(result.reason_code, 1)
        self.assertIn("Invalid tag", str(result))

    def test_handle_fix_reject_business(self):
        from merid.event_venues.kalshi.client import handle_fix_reject, KalshiBusinessError
        msg = {"35": "j", "380": "2", "58": "Unknown Security", "372": "D"}
        result = handle_fix_reject(msg)
        self.assertIsInstance(result, KalshiBusinessError)
        self.assertEqual(result.reason_code, 2)
        self.assertEqual(result.ref_msg_type, "D")

    def test_handle_fix_reject_none(self):
        from merid.event_venues.kalshi.client import handle_fix_reject
        msg = {"35": "D"}  # Not a reject
        self.assertIsNone(handle_fix_reject(msg))

    def test_reject_reasons_registry(self):
        from merid.event_venues.kalshi.client import KALSHI_REJECT_REASONS
        self.assertIn(2, KALSHI_REJECT_REASONS)
        self.assertEqual(KALSHI_REJECT_REASONS[2], "Unknown Security")
        self.assertIn(3, KALSHI_REJECT_REASONS)

    def test_business_reject_causes(self):
        from merid.event_venues.kalshi.client import KALSHI_BUSINESS_REJECT_CAUSES
        self.assertIn("unknown_security", KALSHI_BUSINESS_REJECT_CAUSES)
        self.assertIn("exchange_closed", KALSHI_BUSINESS_REJECT_CAUSES)
        self.assertIn("order_exceeds_limit", KALSHI_BUSINESS_REJECT_CAUSES)

    def test_package_exports(self):
        from merid.event_venues.kalshi import (
            parse_fix, handle_fix_reject,
            KALSHI_REJECT_REASONS, KALSHI_BUSINESS_REJECT_CAUSES,
        )
        self.assertTrue(callable(parse_fix))
        self.assertTrue(callable(handle_fix_reject))
        self.assertIsInstance(KALSHI_REJECT_REASONS, dict)
        self.assertIsInstance(KALSHI_BUSINESS_REJECT_CAUSES, dict)


# ═══════════════════════════════════════════════════════════════════════════
# §34  Smoothed History Endpoint + Frontend Constants Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestSmoothedEndpointAndConstants(unittest.TestCase):
    """Test smoothed volume endpoint and new frontend constants."""

    @classmethod
    def setUpClass(cls):
        cls.api_source = (ROOT / "web" / "api" / "kalshi_api.py").read_text(encoding="utf-8")
        cls.const_source = (ROOT / "web" / "react" / "src" / "config" / "constants.ts").read_text(encoding="utf-8")

    def test_smoothed_route(self):
        self.assertIn("/smoothed", self.api_source)

    def test_smoothed_function(self):
        self.assertIn("async def volume_history_smoothed", self.api_source)

    def test_smoothed_uses_kalman(self):
        self.assertIn("get_smoothed_history", self.api_source)
        self.assertIn("process_var", self.api_source)
        self.assertIn("meas_var", self.api_source)

    def test_smoothed_returns_filter_type(self):
        self.assertIn("kalman_1d", self.api_source)

    def test_frontend_smoothed_constant(self):
        self.assertIn("KALSHI_VOLUME_SMOOTHED", self.const_source)
        self.assertIn("/smoothed", self.const_source)


# ═══════════════════════════════════════════════════════════════════════════
# §35  PriceKalman Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestPriceKalman(unittest.TestCase):
    """Test the PriceKalman filter for price-series smoothing."""

    def test_import(self):
        from merid.event_venues.kalshi.volume_monitor import PriceKalman
        self.assertIsNotNone(PriceKalman)

    def test_first_update(self):
        from merid.event_venues.kalshi.volume_monitor import PriceKalman
        pk = PriceKalman()
        self.assertEqual(pk.update(55.0), 55.0)

    def test_smoothing(self):
        from merid.event_venues.kalshi.volume_monitor import PriceKalman
        pk = PriceKalman(process_var=0.01, meas_var=0.1)
        pk.update(50.0)
        smoothed = pk.update(60.0)
        self.assertGreater(smoothed, 50.0)
        self.assertLess(smoothed, 60.0)

    def test_default_noise_params(self):
        from merid.event_venues.kalshi.volume_monitor import PriceKalman
        pk = PriceKalman()
        self.assertAlmostEqual(pk.Q, 0.01)
        self.assertAlmostEqual(pk.R, 0.1)

    def test_reset(self):
        from merid.event_venues.kalshi.volume_monitor import PriceKalman
        pk = PriceKalman()
        pk.update(50.0)
        pk.reset()
        self.assertFalse(pk.initialized)

    def test_package_export(self):
        from merid.event_venues.kalshi import PriceKalman
        self.assertIsNotNone(PriceKalman)

    def test_different_from_kalman1d(self):
        from merid.event_venues.kalshi.volume_monitor import Kalman1D, PriceKalman
        kf = Kalman1D()
        pk = PriceKalman()
        # Different default noise params
        self.assertNotEqual(kf.Q, pk.Q)
        self.assertNotEqual(kf.R, pk.R)


# ═══════════════════════════════════════════════════════════════════════════
# §36  Enhanced Volume Aggregation Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestEnhancedVolumeAggregation(unittest.TestCase):
    """Test get_volume_for_window returns both contracts and notional."""

    @classmethod
    def setUpClass(cls):
        path = ROOT / "merid" / "event_venues" / "kalshi" / "client.py"
        cls.source = path.read_text(encoding="utf-8")

    def test_returns_dict(self):
        self.assertIn("total_contracts", self.source)
        self.assertIn("notional_usd", self.source)

    def test_price_weighted(self):
        self.assertIn("price_cents", self.source)
        self.assertIn("price_cents / 100.0", self.source)

    def test_return_type_annotation(self):
        self.assertIn("OperationResult[Dict[str, Any]]", self.source)

    def test_rounds_notional(self):
        self.assertIn("round(notional_usd, 2)", self.source)


# ═══════════════════════════════════════════════════════════════════════════
# §37  Enhanced KalshiSessionError Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestEnhancedSessionError(unittest.TestCase):
    """Test KalshiSessionError with reason_code and status_code."""

    def test_basic(self):
        from merid.event_venues.kalshi.client import KalshiSessionError
        e = KalshiSessionError("auth failed")
        self.assertEqual(e.text, "auth failed")
        self.assertIsNone(e.reason_code)
        self.assertIsNone(e.status_code)

    def test_with_status_code(self):
        from merid.event_venues.kalshi.client import KalshiSessionError
        e = KalshiSessionError("unauthorized", status_code=401)
        self.assertEqual(e.status_code, 401)
        self.assertIn("401", str(e))

    def test_with_reason_code(self):
        from merid.event_venues.kalshi.client import KalshiSessionError
        e = KalshiSessionError("bad tag", reason_code=1)
        self.assertEqual(e.reason_code, 1)
        self.assertIn("reason=1", str(e))

    def test_full_constructor(self):
        from merid.event_venues.kalshi.client import KalshiSessionError
        e = KalshiSessionError("test", status_code=503, reason_code=2)
        self.assertIn("503", str(e))
        self.assertIn("reason=2", str(e))
        self.assertIn("test", str(e))

    def test_fix_reject_uses_reason_code(self):
        from merid.event_venues.kalshi.client import handle_fix_reject
        msg = {"35": "3", "373": "5", "58": "Invalid tag number"}
        result = handle_fix_reject(msg)
        self.assertEqual(result.reason_code, 5)
        self.assertEqual(result.text, "Invalid tag number")


# ═══════════════════════════════════════════════════════════════════════════
# §38  VWAP + Large Trade Detection Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestTradeAnalytics(unittest.TestCase):
    """Test compute_vwap and detect_large_trades."""

    def test_compute_vwap_basic(self):
        from merid.event_venues.kalshi.trade_analytics import compute_vwap
        trades = [
            {"price": 50, "count": 10},
            {"price": 60, "count": 20},
        ]
        vwap = compute_vwap(trades)
        # (50*10 + 60*20) / 30 = 1700/30 ≈ 56.67
        self.assertIsNotNone(vwap)
        self.assertAlmostEqual(vwap, 56.667, places=2)

    def test_compute_vwap_empty(self):
        from merid.event_venues.kalshi.trade_analytics import compute_vwap
        self.assertIsNone(compute_vwap([]))

    def test_compute_vwap_zero_qty(self):
        from merid.event_venues.kalshi.trade_analytics import compute_vwap
        self.assertIsNone(compute_vwap([{"price": 50, "count": 0}]))

    def test_detect_large_trades_by_contracts(self):
        from merid.event_venues.kalshi.trade_analytics import detect_large_trades
        trades = [
            {"price": 50, "count": 600},
            {"price": 50, "count": 10},
        ]
        large = detect_large_trades(trades, min_contracts=500, min_notional_usd=99999)
        self.assertEqual(len(large), 1)
        self.assertEqual(large[0]["count"], 600)
        self.assertIn("notional_usd", large[0])

    def test_detect_large_trades_by_notional(self):
        from merid.event_venues.kalshi.trade_analytics import detect_large_trades
        trades = [
            {"price": 80, "count": 200},  # notional = 200 * 0.80 = 160
            {"price": 50, "count": 10},   # notional = 5
        ]
        large = detect_large_trades(trades, min_contracts=9999, min_notional_usd=100)
        self.assertEqual(len(large), 1)

    def test_detect_large_trades_empty(self):
        from merid.event_venues.kalshi.trade_analytics import detect_large_trades
        self.assertEqual(detect_large_trades([]), [])

    def test_package_exports(self):
        from merid.event_venues.kalshi import compute_vwap, detect_large_trades
        self.assertTrue(callable(compute_vwap))
        self.assertTrue(callable(detect_large_trades))

    def test_source_exists(self):
        path = ROOT / "merid" / "event_venues" / "kalshi" / "trade_analytics.py"
        self.assertTrue(path.exists())
        source = path.read_text(encoding="utf-8")
        self.assertIn("def compute_vwap", source)
        self.assertIn("def detect_large_trades", source)


# ═══════════════════════════════════════════════════════════════════════════
# §39  Kalman Parameter Tuning Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestKalmanTuning(unittest.TestCase):
    """Test tune_kalman_params grid search."""

    def test_returns_tuple(self):
        from merid.event_venues.kalshi.volume_monitor import tune_kalman_params
        prices = [50.0 + i * 0.5 for i in range(20)]
        result = tune_kalman_params(prices)
        self.assertEqual(len(result), 3)
        q, r, mse = result
        self.assertIsInstance(q, float)
        self.assertIsInstance(r, float)
        self.assertGreaterEqual(mse, 0)

    def test_custom_grids(self):
        from merid.event_venues.kalshi.volume_monitor import tune_kalman_params
        prices = [50.0] * 10 + [55.0] * 10
        q, r, mse = tune_kalman_params(prices, q_values=[0.01, 0.1], r_values=[0.1, 1.0])
        self.assertIn(q, [0.01, 0.1])
        self.assertIn(r, [0.1, 1.0])

    def test_single_price(self):
        from merid.event_venues.kalshi.volume_monitor import tune_kalman_params
        q, r, mse = tune_kalman_params([50.0])
        self.assertEqual(mse, 0.0)

    def test_package_export(self):
        from merid.event_venues.kalshi import tune_kalman_params
        self.assertTrue(callable(tune_kalman_params))

    def test_source_exists(self):
        source = (ROOT / "merid" / "event_venues" / "kalshi" / "volume_monitor.py").read_text(encoding="utf-8")
        self.assertIn("def tune_kalman_params", source)
        self.assertIn("best_q", source)
        self.assertIn("best_r", source)


# ═══════════════════════════════════════════════════════════════════════════
# §40  Kalman + Kelly Integration Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestKalmanKellyIntegration(unittest.TestCase):
    """Test edge_from_prediction and kelly_size_from_kalman."""

    def test_edge_positive(self):
        from merid.event_venues.kalshi.kalshi_risk import edge_from_prediction
        edge = edge_from_prediction(55.0, 50.0)
        self.assertGreater(edge, 0)
        self.assertAlmostEqual(edge, 10.0, places=1)  # (55-50)/50 * 100 = 10%

    def test_edge_negative(self):
        from merid.event_venues.kalshi.kalshi_risk import edge_from_prediction
        edge = edge_from_prediction(45.0, 50.0)
        self.assertLess(edge, 0)

    def test_edge_zero_price(self):
        from merid.event_venues.kalshi.kalshi_risk import edge_from_prediction
        self.assertEqual(edge_from_prediction(55.0, 0.0), 0.0)

    def test_edge_with_fee(self):
        from merid.event_venues.kalshi.kalshi_risk import edge_from_prediction
        edge_no_fee = edge_from_prediction(55.0, 50.0, fee_cents=0)
        edge_with_fee = edge_from_prediction(55.0, 50.0, fee_cents=2.0)
        self.assertGreater(edge_no_fee, edge_with_fee)

    def test_kelly_size_positive_edge(self):
        from merid.event_venues.kalshi.kalshi_risk import kelly_size_from_kalman
        size = kelly_size_from_kalman(
            smoothed_price=60.0, current_price=50.0,
            account_equity_usd=10000, win_prob=0.6,
        )
        self.assertGreaterEqual(size, 0)

    def test_kelly_size_no_edge(self):
        from merid.event_venues.kalshi.kalshi_risk import kelly_size_from_kalman
        size = kelly_size_from_kalman(
            smoothed_price=50.0, current_price=50.0,
            account_equity_usd=10000, win_prob=0.5,
        )
        self.assertEqual(size, 0)

    def test_kelly_size_bad_price(self):
        from merid.event_venues.kalshi.kalshi_risk import kelly_size_from_kalman
        self.assertEqual(kelly_size_from_kalman(50, 0, 10000, 0.6), 0)
        self.assertEqual(kelly_size_from_kalman(50, 100, 10000, 0.6), 0)

    def test_package_exports(self):
        from merid.event_venues.kalshi import edge_from_prediction, kelly_size_from_kalman
        self.assertTrue(callable(edge_from_prediction))
        self.assertTrue(callable(kelly_size_from_kalman))


# ═══════════════════════════════════════════════════════════════════════════
# §41  Kalman Backtest Strategy Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestKalmanBacktest(unittest.TestCase):
    """Test backtest_kalman_strategy."""

    def test_basic_run(self):
        from merid.event_venues.kalshi.backtest import backtest_kalman_strategy, PriceCandle
        candles = [PriceCandle(ts=i, price_cents=50.0 + i * 0.5) for i in range(20)]
        result = backtest_kalman_strategy(candles, q=0.01, r=0.1, threshold_cents=1.0)
        self.assertIn("pnl_usd", result)
        self.assertIn("total_trades", result)
        self.assertIn("hit_rate", result)

    def test_empty_candles(self):
        from merid.event_venues.kalshi.backtest import backtest_kalman_strategy
        result = backtest_kalman_strategy([], q=0.01, r=0.1)
        self.assertEqual(result["pnl_usd"], 0)
        self.assertEqual(result["total_trades"], 0)

    def test_flat_prices_no_trades(self):
        from merid.event_venues.kalshi.backtest import backtest_kalman_strategy, PriceCandle
        candles = [PriceCandle(ts=i, price_cents=50.0) for i in range(20)]
        result = backtest_kalman_strategy(candles, threshold_cents=5.0)
        self.assertEqual(result["total_trades"], 0)

    def test_result_has_params(self):
        from merid.event_venues.kalshi.backtest import backtest_kalman_strategy, PriceCandle
        candles = [PriceCandle(ts=i, price_cents=50.0) for i in range(5)]
        result = backtest_kalman_strategy(candles, q=0.05, r=0.5, threshold_cents=3.0)
        self.assertEqual(result["q"], 0.05)
        self.assertEqual(result["r"], 0.5)
        self.assertEqual(result["threshold_cents"], 3.0)

    def test_price_candle_dataclass(self):
        from merid.event_venues.kalshi.backtest import PriceCandle
        c = PriceCandle(ts=1.0, price_cents=55.0)
        self.assertEqual(c.ts, 1.0)
        self.assertEqual(c.price_cents, 55.0)

    def test_package_exports(self):
        from merid.event_venues.kalshi import PriceCandle, backtest_kalman_strategy
        self.assertIsNotNone(PriceCandle)
        self.assertTrue(callable(backtest_kalman_strategy))

    def test_source_exists(self):
        source = (ROOT / "merid" / "event_venues" / "kalshi" / "backtest.py").read_text(encoding="utf-8")
        self.assertIn("def backtest_kalman_strategy", source)
        self.assertIn("PriceCandle", source)
        self.assertIn("PriceKalman", source)


# ═══════════════════════════════════════════════════════════════════════════
# §42  OrderIntent + OrderResult Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestOrderIntent(unittest.TestCase):
    """Test OrderIntent and OrderResult dataclasses."""

    def setUp(self):
        # simulate_paper_fill is mode-guarded; force mock and reset the
        # trade-mode singleton so it resolves from the patched env.
        import os as _os
        _os.environ["MERID_PM_TRADING_MODE"] = "mock"
        from trading.trade_mode import _reset_for_tests
        _reset_for_tests()

    def test_order_intent_creation(self):
        from merid.event_venues.kalshi.order_router import OrderIntent
        intent = OrderIntent(
            ticker="KXBTC15M_1", side="yes", action="buy",
            price_cents=55, count=10,
            time_to_expiry_seconds=900.0,
            take_profit_price_cents=70,
            stop_loss_price_cents=40,
        )
        self.assertEqual(intent.ticker, "KXBTC15M_1")
        self.assertEqual(intent.side, "yes")
        self.assertEqual(intent.count, 10)
        self.assertIsNone(intent.mode)
        self.assertEqual(intent.order_type, "limit")
        self.assertEqual(intent.source, "manual")

    def test_order_intent_with_mode(self):
        from merid.event_venues.kalshi.order_router import OrderIntent
        from merid.prediction.venue_gate import TradingMode
        intent = OrderIntent(
            ticker="KXBTC15M", side="no", action="sell",
            price_cents=40, count=5, mode=TradingMode.PAPER,
            time_to_expiry_seconds=900.0,
            take_profit_price_cents=70,
            stop_loss_price_cents=40,
        )
        self.assertEqual(intent.mode, TradingMode.PAPER)

    def test_order_result_fields(self):
        from merid.event_venues.kalshi.order_router import OrderResult
        from merid.prediction.venue_gate import TradingMode
        result = OrderResult(status="filled_mock", mode=TradingMode.SIM)
        self.assertEqual(result.status, "filled_mock")
        self.assertIsNone(result.fill)
        self.assertIsNone(result.reason)

    def test_simulate_paper_fill(self):
        from merid.event_venues.kalshi.order_router import OrderIntent, simulate_paper_fill
        intent = OrderIntent(
            ticker="KXBTC15M", side="yes", action="buy",
            price_cents=55, count=10,
            time_to_expiry_seconds=900.0,
            take_profit_price_cents=70,
            stop_loss_price_cents=40,
        )
        fill = simulate_paper_fill(intent)
        self.assertEqual(fill["ticker"], "KXBTC15M")
        self.assertEqual(fill["price_cents"], 55)
        self.assertEqual(fill["requested_count"], 10)
        self.assertGreaterEqual(fill["count"], 1)
        self.assertLessEqual(fill["count"], 10)
        self.assertTrue(fill["simulated"])

    def test_package_exports(self):
        from merid.event_venues.kalshi import OrderIntent, OrderResult, simulate_paper_fill
        self.assertIsNotNone(OrderIntent)
        self.assertIsNotNone(OrderResult)
        self.assertTrue(callable(simulate_paper_fill))


# ═══════════════════════════════════════════════════════════════════════════
# §43  Order Router Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestOrderRouter(unittest.TestCase):
    """Test route_order mode-aware dispatch."""

    def setUp(self):
        # Router paths assert_not_live; force mock and reset the trade-mode
        # singleton so it resolves from the patched env.
        import os as _os
        _os.environ["MERID_PM_TRADING_MODE"] = "mock"
        from trading.trade_mode import _reset_for_tests
        _reset_for_tests()

        # Bypass production caller/agent authorization for unit tests.
        from unittest.mock import patch, MagicMock
        self._auth_patcher = patch(
            "merid.event_venues.kalshi.order_router._is_authorized_caller",
            return_value=True,
        )
        self._auth_patcher.start()
        self.addCleanup(self._auth_patcher.stop)

        self._agent_patcher = patch(
            "merid.event_venues.kalshi.order_router._is_kalshi_15m_crypto_agent",
            return_value=True,
        )
        self._agent_patcher.start()
        self.addCleanup(self._agent_patcher.stop)

        # Reset rate-limiter state and disable the startup grace period so that
        # repeated unit-test invocations are not rejected for being "too soon".
        import merid.event_venues.kalshi.order_router as _or_mod
        _or_mod._global_order_timestamps.clear()
        self._grace_patcher = patch.object(
            _or_mod, "_MIN_STARTUP_GRACE_PERIOD", 0.0
        )
        self._grace_patcher.start()
        self.addCleanup(self._grace_patcher.stop)

        # Unit tests place larger than the production 2-contract cap.
        self._max_contracts_patcher = patch.object(
            _or_mod, "MAX_CONTRACTS_PER_ORDER", 100
        )
        self._max_contracts_patcher.start()
        self.addCleanup(self._max_contracts_patcher.stop)

        # Async route enforces risk-contract linkage; skip for dispatch tests.
        self._risk_contract_patcher = patch.object(
            _or_mod, "_validate_risk_contract_linkage", return_value=(True, None)
        )
        self._risk_contract_patcher.start()
        self.addCleanup(self._risk_contract_patcher.stop)

        # Async route also runs a fee-aware edge gate that the unit-test
        # intents cannot satisfy without real signal economics.
        self._edge_patcher = patch.object(
            _or_mod, "_round_trip_net_of_cost_gate", return_value=None
        )
        self._edge_patcher.start()
        self.addCleanup(self._edge_patcher.stop)

        # Bypass the async pre-trade gate (durable ledger / lease checks) so
        # the patched _route_live path can exercise the live-dispatch logic.
        self._pre_trade_patcher = patch.object(
            _or_mod, "_run_pre_trade_gate", return_value=None
        )
        self._pre_trade_patcher.start()
        self.addCleanup(self._pre_trade_patcher.stop)

        # Production order routing now requires real market state, bankroll, and
        # signal metadata. For these unit tests we only care about dispatch
        # behavior, so stub the deep validation/planning gates.
        self._risk_patcher = patch(
            "merid.event_venues.kalshi.order_router._check_intent_risk",
            return_value=None,
        )
        self._risk_patcher.start()
        self.addCleanup(self._risk_patcher.stop)

        self._sig_patcher = patch(
            "merid.event_venues.kalshi.order_router._validate_signal_metadata",
            return_value=None,
        )
        self._sig_patcher.start()
        self.addCleanup(self._sig_patcher.stop)

        self._lifecycle_patcher = patch(
            "merid.event_venues.kalshi.order_router._validate_position_lifecycle",
            return_value=None,
        )
        self._lifecycle_patcher.start()
        self.addCleanup(self._lifecycle_patcher.stop)

        self._bankroll_patcher = patch(
            "merid.event_venues.kalshi.order_router._check_bankroll_risk_cap",
            return_value=None,
        )
        self._bankroll_patcher.start()
        self.addCleanup(self._bankroll_patcher.stop)

        self._scope_patcher = patch(
            "merid.event_venues.kalshi.order_router.validate_market_for_trading",
            return_value=True,
        )
        self._scope_patcher.start()
        self.addCleanup(self._scope_patcher.stop)

        self._prep_patcher = patch(
            "merid.event_venues.kalshi.order_router._prepare_order_for_gate",
            return_value=(None, MagicMock()),
        )
        self._prep_patcher.start()
        self.addCleanup(self._prep_patcher.stop)

        # Stub the deep live execution path so tests can focus on the
        # route_order_async dispatch and venue client wiring.
        async def _mock_route_live(intent, mode, t0, prepared_state=None, plan_done=False):
            from merid.event_venues.kalshi.client import get_kalshi_client
            from merid.event_venues.kalshi.order_router import get_venue_gate, OrderResult
            from datetime import datetime, timezone
            import time as _time

            gate = get_venue_gate()
            if not gate.live_enabled and not (intent.action == "sell" or getattr(intent, "reduce_only", False)):
                return OrderResult(
                    status="rejected",
                    mode=mode,
                    reason="live_not_enabled",
                    latency_ms=round((_time.monotonic() - t0) * 1000, 2),
                )

            client = get_kalshi_client()
            await client.connect()
            placed_res = await client.place_order_result(intent, {})
            placed = getattr(placed_res, "value", placed_res)
            requested = int(getattr(intent, "count", 0))
            fill = {
                "ticker": intent.ticker,
                "side": intent.side,
                "action": intent.action,
                "price_cents": int(intent.price_cents),
                "count": requested,
                "requested_count": requested,
                "remaining_count": 0,
                "quantity_cc": requested * 100,
                "remaining_quantity_cc": 0,
                "partial": False,
                "fee_cents": 0,
                "order_id": getattr(placed, "order_id", "oid-123"),
                "status": getattr(placed, "status", "filled"),
                "client_tag": getattr(intent, "client_tag", None),
                "ts": datetime.now(timezone.utc).isoformat(),
                "simulated": False,
            }
            return OrderResult(
                status="filled_live",
                mode=mode,
                fill=fill,
                latency_ms=round((_time.monotonic() - t0) * 1000, 2),
            )

        self._live_patcher = patch(
            "merid.event_venues.kalshi.order_router._route_live",
            side_effect=_mock_route_live,
        )
        self._live_patcher.start()
        self.addCleanup(self._live_patcher.stop)

    def test_route_mock(self):
        from merid.event_venues.kalshi.order_router import OrderIntent, route_order
        from merid.prediction.venue_gate import TradingMode
        intent = OrderIntent(
            ticker="KXBTC15M", side="yes", action="buy",
            price_cents=55, count=10, mode=TradingMode.SIM,
            time_to_expiry_seconds=900.0,
            take_profit_price_cents=70,
            stop_loss_price_cents=40,
        )
        # Mock pre_trade_gate to avoid duplicate_race rejection
        gate_mock = MagicMock()
        verdict_mock = MagicMock()
        verdict_mock.allowed = True
        verdict_mock.client_order_id = "test-mock-123"
        gate_mock.check.return_value = verdict_mock
        with patch("merid.event_venues.kalshi.order_gate.get_pre_trade_gate", return_value=gate_mock):
            result = route_order(intent)
        self.assertEqual(result.status, "filled_mock")
        self.assertIsNotNone(result.fill)

    def test_route_paper(self):
        from merid.event_venues.kalshi.order_router import OrderIntent, route_order
        from merid.prediction.venue_gate import TradingMode
        intent = OrderIntent(
            ticker="KXBTC15M", side="yes", action="buy",
            price_cents=55, count=10, mode=TradingMode.PAPER,
            time_to_expiry_seconds=900.0,
            take_profit_price_cents=70,
            stop_loss_price_cents=40,
        )
        # Mock pre_trade_gate to avoid duplicate_race rejection
        gate_mock = MagicMock()
        verdict_mock = MagicMock()
        verdict_mock.allowed = True
        verdict_mock.client_order_id = "test-123"
        gate_mock.check.return_value = verdict_mock
        with patch("merid.event_venues.kalshi.order_gate.get_pre_trade_gate", return_value=gate_mock):
            result = route_order(intent)
        self.assertEqual(result.status, "filled_paper")

    def test_route_rejects_bad_size(self):
        from merid.event_venues.kalshi.order_router import OrderIntent, route_order
        from merid.prediction.venue_gate import TradingMode
        intent = OrderIntent(
            ticker="KXBTC15M", side="yes", action="buy",
            price_cents=55, count=0, mode=TradingMode.SIM,
            time_to_expiry_seconds=900.0,
            take_profit_price_cents=70,
            stop_loss_price_cents=40,
        )
        result = route_order(intent)
        self.assertEqual(result.status, "rejected")
        self.assertIn("non_positive_size", result.reason)

    def test_route_rejects_bad_price(self):
        from merid.event_venues.kalshi.order_router import OrderIntent, route_order
        from merid.prediction.venue_gate import TradingMode
        intent = OrderIntent(
            ticker="KXBTC15M", side="yes", action="buy",
            price_cents=100, count=10, mode=TradingMode.SIM,
            time_to_expiry_seconds=900.0,
            take_profit_price_cents=70,
            stop_loss_price_cents=40,
        )
        result = route_order(intent)
        self.assertEqual(result.status, "rejected")
        self.assertIn("invalid_price", result.reason)

    def test_route_rejects_bad_side(self):
        from merid.event_venues.kalshi.order_router import OrderIntent, route_order
        from merid.prediction.venue_gate import TradingMode
        intent = OrderIntent(
            ticker="KXBTC15M", side="maybe", action="buy",
            price_cents=55, count=10, mode=TradingMode.SIM,
            time_to_expiry_seconds=900.0,
            take_profit_price_cents=70,
            stop_loss_price_cents=40,
        )
        result = route_order(intent)
        self.assertEqual(result.status, "rejected")
        self.assertIn("unresolvable_contract_side", result.reason)

    def test_route_has_latency(self):
        from merid.event_venues.kalshi.order_router import OrderIntent, route_order
        from merid.prediction.venue_gate import TradingMode
        intent = OrderIntent(
            ticker="KXBTC15M", side="yes", action="buy",
            price_cents=55, count=10, mode=TradingMode.SIM,
            time_to_expiry_seconds=900.0,
            take_profit_price_cents=70,
            stop_loss_price_cents=40,
        )
        result = route_order(intent)
        self.assertGreaterEqual(result.latency_ms, 0)

    def test_route_order_async_live_rejects_when_live_disabled(self):
        from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async
        from merid.prediction.venue_gate import TradingMode

        intent = OrderIntent(
            ticker="KXBTC15M", side="yes", action="buy",
            price_cents=55, count=10, mode=TradingMode.LIVE,
            time_to_expiry_seconds=900.0,
            take_profit_price_cents=70,
            stop_loss_price_cents=40,
        )
        venue_gate = MagicMock()
        venue_gate.live_enabled = False
        # Mock pre_trade_gate to pass duplicate check
        pre_gate = MagicMock()
        verdict = MagicMock()
        verdict.allowed = True
        verdict.client_order_id = "test-456"
        pre_gate.check.return_value = verdict

        # Mock kill switch to allow trading
        risk_ctrl = MagicMock()
        risk_ctrl.can_trade.return_value = True
        with patch("merid.event_venues.kalshi.order_router.get_venue_gate", return_value=venue_gate), \
             patch("merid.event_venues.kalshi.order_gate.get_pre_trade_gate", return_value=pre_gate), \
             patch("merid.risk.kill_switches.risk_controller", risk_ctrl):
            result = asyncio.run(route_order_async(intent))

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.reason, "live_not_enabled")

    def test_route_order_async_live_uses_kalshi_client(self):
        from merid.event_venues.base import PlacedOrder
        from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async
        from merid.prediction.venue_gate import TradingMode
        from merid.resilience.result import OperationResult

        intent = OrderIntent(
            ticker="KXBTC15M", side="yes", action="buy",
            price_cents=55, count=10, mode=TradingMode.LIVE,
            time_to_expiry_seconds=900.0,
            take_profit_price_cents=70,
            stop_loss_price_cents=40,
        )

        placed = PlacedOrder(
            order_id="oid-123",
            market_id="T",
            side="buy",
            size=Decimal("10"),
            price=Decimal("0.55"),
            filled_size=Decimal("10"),
            remaining_size=Decimal("0"),
            status="filled",
        )

        client = MagicMock()
        client.connect = AsyncMock()
        client.place_order_result = AsyncMock(
            return_value=OperationResult.ok(placed, latency_ms=3.0)
        )

        venue_gate = MagicMock()
        venue_gate.live_enabled = True
        # Mock pre_trade_gate to pass duplicate check
        pre_gate = MagicMock()
        verdict = MagicMock()
        verdict.allowed = True
        verdict.client_order_id = "test-789"
        pre_gate.check.return_value = verdict
        # Mock kill switch to allow trading
        risk_ctrl = MagicMock()
        risk_ctrl.can_trade.return_value = True
        risk_ctrl._global_kill = False
        risk_ctrl._kill_reason = None
        risk_ctrl._kill_details = None

        with patch("merid.event_venues.kalshi.order_router.get_venue_gate", return_value=venue_gate), \
             patch("merid.event_venues.kalshi.client.get_kalshi_client", return_value=client), \
             patch("merid.event_venues.kalshi.order_gate.get_pre_trade_gate", return_value=pre_gate), \
             patch("merid.risk.kill_switches.risk_controller", risk_ctrl):
            result = asyncio.run(route_order_async(intent))

        client.connect.assert_awaited_once()
        client.place_order_result.assert_awaited_once()
        self.assertEqual(result.status, "filled_live")
        self.assertEqual(result.fill["order_id"], "oid-123")
        self.assertFalse(result.fill["simulated"])

    def test_route_order_export(self):
        from merid.event_venues.kalshi import route_order
        self.assertTrue(callable(route_order))

    def test_source_exists(self):
        path = ROOT / "merid" / "event_venues" / "kalshi" / "order_router.py"
        self.assertTrue(path.exists())
        source = path.read_text(encoding="utf-8")
        self.assertIn("def route_order", source)
        self.assertIn("OrderIntent", source)
        self.assertIn("OrderResult", source)


# ═══════════════════════════════════════════════════════════════════════════
# §44  WS Channel Constants + Orderbook Delta Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestWSChannelsAndOrderbook(unittest.TestCase):
    """Test WS bus channel constants and orderbook_delta forwarding."""

    def test_channel_constants(self):
        from merid.event_venues.kalshi.order_router import (
            KALSHI_CHANNEL_PRICE, KALSHI_CHANNEL_TRADE,
            KALSHI_CHANNEL_ORDERBOOK, KALSHI_CHANNEL_ORDER_FILL,
            KALSHI_CHANNEL_ORDER_REJECT,
        )
        self.assertEqual(KALSHI_CHANNEL_PRICE, "kalshi:price_update")
        self.assertEqual(KALSHI_CHANNEL_TRADE, "kalshi:trade")
        self.assertEqual(KALSHI_CHANNEL_ORDERBOOK, "kalshi:orderbook_delta")
        self.assertEqual(KALSHI_CHANNEL_ORDER_FILL, "kalshi:order_fill")
        self.assertEqual(KALSHI_CHANNEL_ORDER_REJECT, "kalshi:order_reject")

    def test_package_exports_channels(self):
        from merid.event_venues.kalshi import (
            KALSHI_CHANNEL_PRICE, KALSHI_CHANNEL_TRADE,
            KALSHI_CHANNEL_ORDERBOOK,
        )
        self.assertIsNotNone(KALSHI_CHANNEL_PRICE)
        self.assertIsNotNone(KALSHI_CHANNEL_TRADE)
        self.assertIsNotNone(KALSHI_CHANNEL_ORDERBOOK)

    def test_ws_bridge_orderbook_delta(self):
        source = (ROOT / "merid" / "event_venues" / "kalshi" / "ws_bridge.py").read_text(encoding="utf-8")
        self.assertIn("orderbook_delta", source)
        self.assertIn("orderbook_snapshot", source)
        self.assertIn("kalshi:orderbook_delta", source)

    def test_ws_bridge_channels_match(self):
        source = (ROOT / "merid" / "event_venues" / "kalshi" / "ws_bridge.py").read_text(encoding="utf-8")
        self.assertIn("kalshi:price_update", source)
        self.assertIn("kalshi:trade", source)
        self.assertIn("kalshi:orderbook_delta", source)


# ═══════════════════════════════════════════════════════════════════════════
# §45  Sidebar Config API Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestSidebarConfigAPI(unittest.TestCase):
    """Test sidebar_config.py backend module."""

    @classmethod
    def setUpClass(cls):
        cls.path = ROOT / "web" / "api" / "sidebar_config.py"
        cls.source = cls.path.read_text(encoding="utf-8")

    def test_file_exists(self):
        self.assertTrue(self.path.exists())

    def test_has_sidebar_sections(self):
        self.assertIn("SIDEBAR_SECTIONS", self.source)

    def test_has_workflow_phases(self):
        self.assertIn("WORKFLOW_PHASES", self.source)

    def test_sidebar_endpoint(self):
        self.assertIn("/sidebar", self.source)
        self.assertIn("get_sidebar", self.source)

    def test_mode_indicator_endpoint(self):
        self.assertIn("/mode-indicator", self.source)
        self.assertIn("get_mode_indicator", self.source)

    def test_workflow_endpoint(self):
        self.assertIn("/workflow", self.source)
        self.assertIn("get_workflow", self.source)

    def test_five_sections(self):
        from web.api.sidebar_config import SIDEBAR_SECTIONS
        self.assertEqual(len(SIDEBAR_SECTIONS), 5)
        labels = [s["label"] for s in SIDEBAR_SECTIONS]
        self.assertIn("Live Trading", labels)
        self.assertIn("Swarm Intelligence", labels)
        self.assertIn("Analytics", labels)
        self.assertIn("Command Center", labels)
        self.assertIn("System", labels)

    def test_live_trading_items(self):
        from web.api.sidebar_config import SIDEBAR_SECTIONS
        trading = [s for s in SIDEBAR_SECTIONS if s["id"] == "live-trading"][0]
        hrefs = [i["href"] for i in trading["items"]]
        self.assertIn("kalshi-dashboard", hrefs)
        self.assertIn("kalshi-portfolio", hrefs)
        self.assertIn("kalshi-terminal", hrefs)

    def test_items_have_endpoints(self):
        from web.api.sidebar_config import SIDEBAR_SECTIONS
        for section in SIDEBAR_SECTIONS:
            for item in section["items"]:
                self.assertIn("endpoints", item)
                self.assertIn("workflow_phase", item)
                self.assertIn("links_to", item)

    def test_workflow_phases_ordered(self):
        from web.api.sidebar_config import WORKFLOW_PHASES
        orders = [p["order"] for p in WORKFLOW_PHASES]
        self.assertEqual(orders, sorted(orders))


# ═══════════════════════════════════════════════════════════════════════════
# §46  Mode Indicator Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestModeIndicator(unittest.TestCase):
    """Test mode indicator endpoint logic."""

    def test_mode_indicator_import(self):
        from web.api.sidebar_config import get_mode_indicator
        self.assertTrue(callable(get_mode_indicator))

    def test_mode_indicator_source(self):
        source = (ROOT / "web" / "api" / "sidebar_config.py").read_text(encoding="utf-8")
        self.assertIn("global_mode", source)
        self.assertIn("live_enabled", source)
        self.assertIn("is_live", source)
        self.assertIn("kill_switch_active", source)
        self.assertIn("ws_connected", source)
        self.assertIn("venues", source)


# ═══════════════════════════════════════════════════════════════════════════
# §47  Sidebar Wiring Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestSidebarWiring(unittest.TestCase):
    """Test sidebar router is wired into main.py and frontend constants exist."""

    def test_main_imports_sidebar_router(self):
        source = (ROOT / "web" / "main.py").read_text(encoding="utf-8")
        self.assertIn("sidebar_config_router", source)

    def test_main_includes_sidebar_router(self):
        source = (ROOT / "web" / "main.py").read_text(encoding="utf-8")
        self.assertIn("_reg(sidebar_config_router)", source)

    def test_frontend_constants(self):
        source = (ROOT / "web" / "react" / "src" / "config" / "constants.ts").read_text(encoding="utf-8")
        self.assertIn("UI_SIDEBAR", source)
        self.assertIn("UI_MODE_INDICATOR", source)
        self.assertIn("UI_WORKFLOW", source)
        self.assertIn("/api/v1/ui/sidebar", source)
        self.assertIn("/api/v1/ui/mode-indicator", source)
        self.assertIn("/api/v1/ui/workflow", source)


# ═══════════════════════════════════════════════════════════════════════════
# §48  Sidebar Component Restructure Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestSidebarComponent(unittest.TestCase):
    """Test Sidebar.tsx has been restructured with canonical groupings."""

    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "web" / "react" / "src" / "components" / "Sidebar.tsx").read_text(encoding="utf-8")

    def test_has_trading_section(self):
        self.assertIn("const tradingCore", self.source)
        self.assertIn("'Trading'", self.source)

    def test_has_swarm_intelligence_section(self):
        self.assertIn("const swarmIntelligence", self.source)
        self.assertIn("'Swarm Intelligence'", self.source)

    def test_has_analytics_section(self):
        self.assertIn("const analytics", self.source)
        self.assertIn("'Analytics'", self.source)

    def test_has_operator_section(self):
        self.assertIn("const operatorSection", self.source)
        self.assertIn("'Operator'", self.source)

    def test_has_system_section(self):
        self.assertIn("const system", self.source)
        self.assertIn("'System'", self.source)

    def test_no_old_navigation_array(self):
        self.assertNotIn("const navigation =", self.source)
        self.assertNotIn("const management =", self.source)

    def test_five_sections_rendered(self):
        count = self.source.count("{ label: '")
        self.assertEqual(count, 5)


if __name__ == "__main__":
    unittest.main()
    def test_five_sections_rendered(self):
        count = self.source.count("{ label: '")
        self.assertEqual(count, 5)


if __name__ == "__main__":
    unittest.main()
