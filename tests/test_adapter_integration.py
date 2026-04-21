"""
Adapter-level integration tests with mock exchange responses (S7-02 hardening).

Validates:
- Mock adapters implement the full UnifiedVenueAdapter interface
- TradeRouter dispatches to mock adapters and returns correct results
- Order submission, cancellation, balances, positions, quotes, order book
- Error handling (adapter raises, returns error status)
- Multi-venue routing (crypto vs equity vs prediction)
- Health check integration
"""

import asyncio
import unittest
from decimal import Decimal
from typing import Dict, List, Optional

from merid.pipeline.adapter import AdapterRegistry, UnifiedVenueAdapter
from merid.pipeline.proposal import (
    ExecutionResult,
    OrderSide,
    OrderType,
    ProposalStatus,
    TradeDomain,
    TradeProposal,
)
from merid.pipeline.instruments import Instrument, InstrumentRegistry
from merid.pipeline.mode_manager import ModeManager, TradingMode, VenueConfig
from merid.pipeline.risk_manager import GlobalRiskManager
from merid.pipeline.router import TradeRouter
from core.order_sanity_check import OrderSanityChecker, OrderSanityConfig


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Mock Adapters ──────────────────────────────────────────────────


class MockCryptoAdapter(UnifiedVenueAdapter):
    """Mock Binance-US adapter returning canned responses."""

    @property
    def venue_name(self) -> str:
        return "binanceus"

    @property
    def domain(self) -> str:
        return "crypto"

    @property
    def supports_trading(self) -> bool:
        return True

    async def get_symbols(self) -> List[str]:
        return ["BTCUSD", "ETHUSD", "SOLUSD"]

    async def get_quote(self, native_symbol: str) -> Optional[Dict]:
        quotes = {
            "BTCUSD": {"bid": Decimal("49990"), "ask": Decimal("50010"), "last": Decimal("50000"), "volume": Decimal("1234")},
            "ETHUSD": {"bid": Decimal("3190"), "ask": Decimal("3210"), "last": Decimal("3200"), "volume": Decimal("5678")},
        }
        return quotes.get(native_symbol)

    async def get_order_book(self, native_symbol: str, depth: int = 5) -> Optional[Dict]:
        return {
            "bids": [(Decimal("49990"), Decimal("1.5")), (Decimal("49980"), Decimal("2.0"))],
            "asks": [(Decimal("50010"), Decimal("1.0")), (Decimal("50020"), Decimal("3.0"))],
        }

    async def submit_order(self, proposal: TradeProposal) -> ExecutionResult:
        return ExecutionResult(
            proposal_id=proposal.proposal_id,
            venue="binanceus",
            venue_order_id="MOCK-BN-001",
            status="filled",
            filled_qty=proposal.qty,
            avg_price=proposal.price or Decimal("50000"),
            fee=Decimal("0.50"),
            latency_ms=12.5,
        )

    async def cancel_order(self, venue_order_id: str, native_symbol: str = "") -> bool:
        return True

    async def get_balances(self) -> Dict[str, Decimal]:
        return {"USD": Decimal("10000"), "BTC": Decimal("0.5"), "ETH": Decimal("3.0")}

    async def get_positions(self) -> List[Dict]:
        return [
            {"symbol": "BTCUSD", "qty": Decimal("0.5"), "entry_price": Decimal("48000"), "unrealized_pnl": Decimal("1000"), "venue": "binanceus"},
        ]


class MockEquityAdapter(UnifiedVenueAdapter):
    """Mock Alpaca adapter."""

    @property
    def venue_name(self) -> str:
        return "alpaca"

    @property
    def domain(self) -> str:
        return "equity"

    @property
    def supports_trading(self) -> bool:
        return True

    async def get_symbols(self) -> List[str]:
        return ["AAPL", "TSLA", "SPY"]

    async def get_quote(self, native_symbol: str) -> Optional[Dict]:
        return {"bid": Decimal("175"), "ask": Decimal("175.50"), "last": Decimal("175.25"), "volume": Decimal("1000000")}

    async def get_order_book(self, native_symbol: str, depth: int = 5) -> Optional[Dict]:
        return {"bids": [(Decimal("175"), Decimal("100"))], "asks": [(Decimal("175.50"), Decimal("200"))]}

    async def submit_order(self, proposal: TradeProposal) -> ExecutionResult:
        return ExecutionResult(
            proposal_id=proposal.proposal_id,
            venue="alpaca",
            venue_order_id="MOCK-ALP-001",
            status="filled",
            filled_qty=proposal.qty,
            avg_price=proposal.price or Decimal("175.25"),
            fee=Decimal("0"),
            latency_ms=8.3,
        )

    async def cancel_order(self, venue_order_id: str, native_symbol: str = "") -> bool:
        return True

    async def get_balances(self) -> Dict[str, Decimal]:
        return {"USD": Decimal("25000")}

    async def get_positions(self) -> List[Dict]:
        return []


class MockFailingAdapter(UnifiedVenueAdapter):
    """Adapter that raises on submit_order."""

    @property
    def venue_name(self) -> str:
        return "failing_venue"

    @property
    def domain(self) -> str:
        return "crypto"

    @property
    def supports_trading(self) -> bool:
        return True

    async def get_symbols(self) -> List[str]:
        return []

    async def get_quote(self, native_symbol: str) -> Optional[Dict]:
        return None

    async def get_order_book(self, native_symbol: str, depth: int = 5) -> Optional[Dict]:
        return None

    async def submit_order(self, proposal: TradeProposal) -> ExecutionResult:
        raise ConnectionError("Exchange API timeout")

    async def cancel_order(self, venue_order_id: str, native_symbol: str = "") -> bool:
        return False

    async def get_balances(self) -> Dict[str, Decimal]:
        return {}

    async def get_positions(self) -> List[Dict]:
        return []


class MockPartialFillAdapter(UnifiedVenueAdapter):
    """Adapter that returns partial fills."""

    @property
    def venue_name(self) -> str:
        return "partial_venue"

    @property
    def domain(self) -> str:
        return "crypto"

    @property
    def supports_trading(self) -> bool:
        return True

    async def get_symbols(self) -> List[str]:
        return ["BTCUSD"]

    async def get_quote(self, native_symbol: str) -> Optional[Dict]:
        return {"bid": Decimal("50000"), "ask": Decimal("50010"), "last": Decimal("50005"), "volume": Decimal("100")}

    async def get_order_book(self, native_symbol: str, depth: int = 5) -> Optional[Dict]:
        return {"bids": [], "asks": []}

    async def submit_order(self, proposal: TradeProposal) -> ExecutionResult:
        return ExecutionResult(
            proposal_id=proposal.proposal_id,
            venue="partial_venue",
            venue_order_id="MOCK-PF-001",
            status="partially_filled",
            filled_qty=proposal.qty / 2,
            avg_price=proposal.price or Decimal("50005"),
            fee=Decimal("0.25"),
            latency_ms=45.0,
        )

    async def cancel_order(self, venue_order_id: str, native_symbol: str = "") -> bool:
        return True

    async def get_balances(self) -> Dict[str, Decimal]:
        return {"USD": Decimal("5000")}

    async def get_positions(self) -> List[Dict]:
        return []


# ── Helper ─────────────────────────────────────────────────────────


def _build_router_with_mocks():
    """Build a TradeRouter with mock adapters, permissive risk, and LIVE mode."""
    registry = AdapterRegistry()
    registry.register(MockCryptoAdapter())
    registry.register(MockEquityAdapter())
    registry.register(MockFailingAdapter())
    registry.register(MockPartialFillAdapter())

    instruments = InstrumentRegistry()
    instruments.register(Instrument(
        merid_symbol="BTC/USD", domain="crypto",
        venue_symbols={"binanceus": "BTCUSD"},
    ))
    instruments.register(Instrument(
        merid_symbol="ETH/USD", domain="crypto",
        venue_symbols={"binanceus": "ETHUSD"},
    ))
    instruments.register(Instrument(
        merid_symbol="AAPL", domain="equity",
        venue_symbols={"alpaca": "AAPL"},
    ))

    mock_venue_configs = [
        VenueConfig(venue="binanceus", domain="crypto", mode=TradingMode.LIVE),
        VenueConfig(venue="alpaca", domain="equity", mode=TradingMode.LIVE),
        VenueConfig(venue="failing_venue", domain="crypto", mode=TradingMode.LIVE),
        VenueConfig(venue="partial_venue", domain="crypto", mode=TradingMode.LIVE),
    ]
    mode_mgr = ModeManager(configs=mock_venue_configs)

    risk_mgr = GlobalRiskManager()

    sanity = OrderSanityChecker(OrderSanityConfig(
        max_order_pct_of_portfolio=1.0,
        max_order_notional_usd=1_000_000,
        max_daily_order_count=10000,
        max_order_notional_per_symbol_usd=1_000_000,
    ))

    return TradeRouter(
        registry=registry,
        instruments=instruments,
        mode_manager=mode_mgr,
        risk_manager=risk_mgr,
        sanity_checker=sanity,
    )


# ── Tests ──────────────────────────────────────────────────────────


class TestMockAdapterInterface(unittest.TestCase):
    """Mock adapters implement the full UnifiedVenueAdapter interface."""

    def test_crypto_adapter_symbols(self):
        adapter = MockCryptoAdapter()
        symbols = _run(adapter.get_symbols())
        self.assertIn("BTCUSD", symbols)

    def test_crypto_adapter_quote(self):
        adapter = MockCryptoAdapter()
        quote = _run(adapter.get_quote("BTCUSD"))
        self.assertIsNotNone(quote)
        self.assertIn("bid", quote)
        self.assertIn("ask", quote)

    def test_crypto_adapter_order_book(self):
        adapter = MockCryptoAdapter()
        book = _run(adapter.get_order_book("BTCUSD"))
        self.assertIn("bids", book)
        self.assertIn("asks", book)

    def test_crypto_adapter_balances(self):
        adapter = MockCryptoAdapter()
        balances = _run(adapter.get_balances())
        self.assertIn("USD", balances)
        self.assertIn("BTC", balances)

    def test_crypto_adapter_positions(self):
        adapter = MockCryptoAdapter()
        positions = _run(adapter.get_positions())
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0]["symbol"], "BTCUSD")

    def test_equity_adapter_symbols(self):
        adapter = MockEquityAdapter()
        symbols = _run(adapter.get_symbols())
        self.assertIn("AAPL", symbols)

    def test_health_check(self):
        adapter = MockCryptoAdapter()
        health = _run(adapter.health_check())
        self.assertEqual(health["venue"], "binanceus")
        self.assertEqual(health["status"], "ok")


class TestRouterWithMockAdapters(unittest.TestCase):
    """TradeRouter dispatches to mock adapters correctly."""

    def setUp(self):
        self.router = _build_router_with_mocks()

    def test_crypto_order_filled(self):
        proposal = TradeProposal(
            domain=TradeDomain.CRYPTO,
            venue="binanceus",
            instrument_id="BTC/USD",
            side=OrderSide.BUY,
            qty=Decimal("0.1"),
            price=Decimal("50000"),
        )
        result = _run(self.router.submit(proposal))
        self.assertEqual(result.status, ProposalStatus.FILLED)
        self.assertEqual(result.execution_result.venue_order_id, "MOCK-BN-001")
        self.assertEqual(result.execution_result.filled_qty, Decimal("0.1"))

    def test_equity_order_filled(self):
        proposal = TradeProposal(
            domain=TradeDomain.EQUITY,
            venue="alpaca",
            instrument_id="AAPL",
            side=OrderSide.BUY,
            qty=Decimal("10"),
            price=Decimal("175"),
        )
        result = _run(self.router.submit(proposal))
        self.assertEqual(result.status, ProposalStatus.FILLED)
        self.assertEqual(result.execution_result.venue, "alpaca")

    def test_failing_adapter_returns_failed(self):
        proposal = TradeProposal(
            domain=TradeDomain.CRYPTO,
            venue="failing_venue",
            native_symbol="BTCUSD",
            side=OrderSide.BUY,
            qty=Decimal("0.1"),
            price=Decimal("50000"),
        )
        result = _run(self.router.submit(proposal))
        self.assertEqual(result.status, ProposalStatus.FAILED)
        self.assertIn("timeout", result.execution_result.error.lower())

    def test_partial_fill(self):
        proposal = TradeProposal(
            domain=TradeDomain.CRYPTO,
            venue="partial_venue",
            native_symbol="BTCUSD",
            side=OrderSide.BUY,
            qty=Decimal("0.02"),
            price=Decimal("50000"),
        )
        result = _run(self.router.submit(proposal))
        self.assertEqual(result.status, ProposalStatus.PARTIALLY_FILLED)
        self.assertEqual(result.execution_result.filled_qty, Decimal("0.01"))

    def test_unknown_venue_rejected(self):
        proposal = TradeProposal(
            domain=TradeDomain.CRYPTO,
            venue="nonexistent",
            native_symbol="BTCUSD",
            side=OrderSide.BUY,
            qty=Decimal("0.01"),
            price=Decimal("50000"),
        )
        result = _run(self.router.submit(proposal))
        # ModeManager rejects unknown venues before adapter lookup
        self.assertEqual(result.status, ProposalStatus.RISK_REJECTED)


class TestAdapterCancellation(unittest.TestCase):
    """Order cancellation through mock adapters."""

    def test_cancel_succeeds(self):
        adapter = MockCryptoAdapter()
        result = _run(adapter.cancel_order("MOCK-BN-001", "BTCUSD"))
        self.assertTrue(result)

    def test_cancel_fails_on_failing_adapter(self):
        adapter = MockFailingAdapter()
        result = _run(adapter.cancel_order("MOCK-FAIL-001"))
        self.assertFalse(result)


class TestMultiVenueRouting(unittest.TestCase):
    """Router correctly dispatches to different venues."""

    def setUp(self):
        self.router = _build_router_with_mocks()

    def test_crypto_goes_to_binance(self):
        proposal = TradeProposal(
            domain=TradeDomain.CRYPTO,
            venue="binanceus",
            instrument_id="BTC/USD",
            side=OrderSide.BUY,
            qty=Decimal("0.01"),
            price=Decimal("50000"),
        )
        result = _run(self.router.submit(proposal))
        self.assertEqual(result.execution_result.venue, "binanceus")

    def test_equity_goes_to_alpaca(self):
        proposal = TradeProposal(
            domain=TradeDomain.EQUITY,
            venue="alpaca",
            instrument_id="AAPL",
            side=OrderSide.BUY,
            qty=Decimal("5"),
            price=Decimal("175"),
        )
        result = _run(self.router.submit(proposal))
        self.assertEqual(result.execution_result.venue, "alpaca")

    def test_batch_submit(self):
        proposals = [
            TradeProposal(domain=TradeDomain.CRYPTO, venue="binanceus", instrument_id="BTC/USD", side=OrderSide.BUY, qty=Decimal("0.01"), price=Decimal("50000")),
            TradeProposal(domain=TradeDomain.EQUITY, venue="alpaca", instrument_id="AAPL", side=OrderSide.BUY, qty=Decimal("5"), price=Decimal("175")),
        ]
        results = _run(self.router.submit_batch(proposals))
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].execution_result.venue, "binanceus")
        self.assertEqual(results[1].execution_result.venue, "alpaca")


class TestAdapterRegistry(unittest.TestCase):
    """AdapterRegistry with mock adapters."""

    def setUp(self):
        self.registry = AdapterRegistry()
        self.registry.register(MockCryptoAdapter())
        self.registry.register(MockEquityAdapter())

    def test_list_venues(self):
        venues = self.registry.list_venues()
        self.assertIn("binanceus", venues)
        self.assertIn("alpaca", venues)

    def test_by_domain_crypto(self):
        adapters = self.registry.by_domain("crypto")
        self.assertEqual(len(adapters), 1)
        self.assertEqual(adapters[0].venue_name, "binanceus")

    def test_by_domain_equity(self):
        adapters = self.registry.by_domain("equity")
        self.assertEqual(len(adapters), 1)
        self.assertEqual(adapters[0].venue_name, "alpaca")

    def test_summary(self):
        summary = self.registry.summary()
        self.assertEqual(len(summary), 2)
        venues = {s["venue"] for s in summary}
        self.assertEqual(venues, {"binanceus", "alpaca"})


class TestExecutionResultDetails(unittest.TestCase):
    """Execution results carry correct details from mock adapters."""

    def setUp(self):
        self.router = _build_router_with_mocks()

    def test_fee_recorded(self):
        proposal = TradeProposal(
            domain=TradeDomain.CRYPTO, venue="binanceus", instrument_id="BTC/USD",
            side=OrderSide.BUY, qty=Decimal("0.1"), price=Decimal("50000"),
        )
        result = _run(self.router.submit(proposal))
        self.assertEqual(result.execution_result.fee, Decimal("0.50"))

    def test_latency_recorded(self):
        proposal = TradeProposal(
            domain=TradeDomain.CRYPTO, venue="binanceus", instrument_id="BTC/USD",
            side=OrderSide.BUY, qty=Decimal("0.1"), price=Decimal("50000"),
        )
        result = _run(self.router.submit(proposal))
        self.assertGreater(result.execution_result.latency_ms, 0)

    def test_venue_order_id_present(self):
        proposal = TradeProposal(
            domain=TradeDomain.EQUITY, venue="alpaca", instrument_id="AAPL",
            side=OrderSide.BUY, qty=Decimal("10"), price=Decimal("175"),
        )
        result = _run(self.router.submit(proposal))
        self.assertTrue(result.execution_result.venue_order_id.startswith("MOCK-"))


if __name__ == "__main__":
    unittest.main()
