"""Tests for the trading circuit breaker and order-identity enforcement."""

import os
import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from merid.event_venues.kalshi.order_router import (
    OrderIntent,
    _validate_order_identity,
)
from merid.governance.trading_circuit_breaker import (
    TradingCircuitBreaker,
    get_trading_circuit_breaker,
    trading_halt,
)


@pytest.fixture(autouse=True)
def reset_breaker():
    """Each test gets a fresh breaker state."""
    breaker = get_trading_circuit_breaker()
    breaker.resume()
    yield
    breaker.resume()


class TestTradingCircuitBreaker:
    def test_singleton(self):
        a = TradingCircuitBreaker()
        b = TradingCircuitBreaker()
        assert a is b

    def test_halt_blocks_orders(self):
        breaker = get_trading_circuit_breaker()
        breaker.halt("test", metadata={"ticker": "KXBTC15M"})

        intent = OrderIntent(
            ticker="KXBTC15M-26AUG111830-30",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
        )
        assert not breaker.is_order_allowed(intent)

    def test_manual_emergency_close_allowed_after_halt(self):
        breaker = get_trading_circuit_breaker()
        breaker.halt("test")

        os.environ["MERID_MANUAL_EMERGENCY_TOKEN"] = "test_token"
        intent = OrderIntent(
            ticker="KXBTC15M-26AUG111830-30",
            side="yes",
            action="sell",
            price_cents=50,
            count=1,
            is_manual_emergency_close=True,
            approval_token="test_token",
        )
        assert breaker.is_order_allowed(intent)

    def test_resume_clears_halt(self):
        breaker = get_trading_circuit_breaker()
        breaker.halt("test")
        assert breaker.halted
        breaker.resume()
        assert not breaker.halted

    def test_halt_info_round_trip(self):
        breaker = get_trading_circuit_breaker()
        breaker.halt("unmatched_live_fill", metadata={"order_id": "abc"})
        info = breaker.halt_info
        assert info["halted"] is True
        assert info["reason"] == "unmatched_live_fill"
        assert info["metadata"]["order_id"] == "abc"


class TestLiveFillHalt:
    class FakeFill:
        def __init__(self, created_time, source, **kw):
            self.fill_id = "fid"
            self.order_id = "oid"
            self.client_order_id = None
            self.market_ticker = "KXETH15M-26AUG111830-30"
            self.created_time = created_time
            self.ingested_at = datetime.now(timezone.utc)
            self.ingestion_source = source

    def test_websocket_fill_always_live(self):
        breaker = get_trading_circuit_breaker()
        fill = self.FakeFill(
            created_time=datetime.now(timezone.utc) - timedelta(days=7),
            source="websocket",
        )
        breaker.require_live_fill_identity(fill)
        assert breaker.halted

    def test_http_fill_newer_than_watermark_is_live(self):
        breaker = get_trading_circuit_breaker()
        breaker.resume()
        breaker._initialize_watermark()
        # Set watermark in the past so a recent fill is strictly newer.
        breaker._http_fill_watermark = datetime.now(timezone.utc) - timedelta(days=1)
        fill = self.FakeFill(
            created_time=datetime.now(timezone.utc) - timedelta(seconds=10),
            source="http_poller",
        )
        breaker.require_live_fill_identity(fill)
        assert breaker.halted

    def test_http_fill_older_than_watermark_is_historical(self):
        breaker = get_trading_circuit_breaker()
        breaker.resume()
        breaker._initialize_watermark()
        breaker._http_fill_watermark = datetime.now(timezone.utc)
        fill = self.FakeFill(
            created_time=datetime.now(timezone.utc) - timedelta(days=1),
            source="http_poller",
        )
        breaker.require_live_fill_identity(fill)
        assert not breaker.halted

    def test_unmatched_fill_with_pending_intent_does_not_halt(self):
        breaker = get_trading_circuit_breaker()
        breaker.resume()
        breaker._initialize_watermark()
        breaker._http_fill_watermark = datetime.now(timezone.utc) - timedelta(days=1)

        class FakeLookup:
            def lookup(self, *, client_order_id=None, order_id=None, lookback_seconds=30):
                return client_order_id == "known_coid" or order_id == "known_oid"

        fill = self.FakeFill(
            created_time=datetime.now(timezone.utc),
            source="http_poller",
        )
        fill.order_id = "known_oid"
        breaker.require_live_fill_identity(fill, intent_lookup=FakeLookup())
        assert not breaker.halted


class TestOrderIdentityValidation:
    def test_valid_intent_passes(self):
        intent = OrderIntent(
            ticker="KXBTC15M-26AUG111830-30",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            client_order_id="client_abc",
            intent_id="intent_abc",
            run_id="run_1",
            process_id="pid_1",
            reason="entry",
        )
        result = _validate_order_identity(intent, time.monotonic())
        assert result is None

    def test_missing_client_order_id_rejected(self):
        intent = OrderIntent(
            ticker="KXBTC15M-26AUG111830-30",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
        )
        intent.client_order_id = ""
        result = _validate_order_identity(intent, time.monotonic())
        assert result is not None
        assert "client_order_id" in result.reason

    def test_missing_intent_id_rejected(self):
        intent = OrderIntent(
            ticker="KXBTC15M-26AUG111830-30",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
        )
        intent.intent_id = ""
        result = _validate_order_identity(intent, time.monotonic())
        assert result is not None
        assert "intent_id" in result.reason

    def test_trading_halt_rejects_order(self):
        trading_halt("test_halt")
        intent = OrderIntent(
            ticker="KXBTC15M-26AUG111830-30",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            client_order_id="client_abc",
            intent_id="intent_abc",
            run_id="run_1",
            process_id="pid_1",
            reason="entry",
        )
        result = _validate_order_identity(intent, time.monotonic())
        assert result is not None
        assert "trading_halted" in result.reason

    def test_manual_emergency_close_bypasses_halt(self):
        trading_halt("test_halt")
        os.environ["MERID_MANUAL_EMERGENCY_TOKEN"] = "test_token"
        intent = OrderIntent(
            ticker="KXBTC15M-26AUG111830-30",
            side="yes",
            action="sell",
            price_cents=50,
            count=1,
            client_order_id="client_abc",
            intent_id="intent_abc",
            run_id="run_1",
            process_id="pid_1",
            reason="manual_close",
            is_manual_emergency_close=True,
            approval_token="test_token",
        )
        result = _validate_order_identity(intent, time.monotonic())
        assert result is None
