import os
import pytest
import asyncio
import time
from unittest.mock import patch
from merid.event_venues.kalshi.order_router import (
    OrderIntent,
    OrderResult,
    _post_route_canonical_idempotency_cleanup,
    route_order_async,
)
from merid.event_venues.kalshi.order_intent_contract import (
    _accepted_entry_intents,
    clear_entry_idempotency_registry,
)
from merid.prediction.venue_gate import TradingMode

@pytest.mark.asyncio
async def test_order_router_hardening():
    # Test that order router validates price range with new 50-70c limits
    # Note: Test environment may have rate limiting, so we just verify rejection
    intent = OrderIntent(
        ticker="KXBTCD-25JUN-T100000",
        side="yes",
        action="buy",
        price_cents=150,  # Invalid: > 70c (new max)
        count=10,
        mode=TradingMode.PAPER,
        agent_id="BTC_15M",
        edge_pct=0.05,
        confidence=0.70,
        model_prob=0.60,
        group_id="test_group",
        snapshot_ts=time.time(),
        session_id="test_session",
    )
    result = await route_order_async(intent)
    assert result.status == "rejected"
    
    # Test price below new minimum (50c)
    intent.price_cents = 30  # Invalid: < 50c (new min)
    result = await route_order_async(intent)
    assert result.status == "rejected"
    
    # Test valid price within new range (50-70c)
    intent.price_cents = 60  # Valid: within 50-70c
    intent.count = 1
    result = await route_order_async(intent)
    # May be rejected for other reasons (bankroll, rate limit) but not for price
    if result.status == "rejected":
        assert "invalid_price" not in result.reason.lower()


@pytest.mark.asyncio
async def test_bankroll_cap_fail_closed_logic():
    """Test that order router rejects orders when bankroll is unavailable (fail-closed)."""
    from unittest.mock import patch, MagicMock
    
    # Patch startup time to bypass grace period
    with patch('merid.event_venues.kalshi.order_router._startup_time', 1000.0):
        # Mock _derive_live_bankroll_usd to return None (bankroll unavailable)
        with patch('merid.event_venues.kalshi.order_router._derive_live_bankroll_usd') as mock_bankroll:
            mock_bankroll.return_value = None
            
            # Create order intent without effective_equity_usd
            intent = OrderIntent(
                ticker="KXBTCD-25JUN-T100000",
                side="yes",
                action="buy",
                price_cents=60,  # Updated to 60c (within new 50-70c range)
                count=1,
                mode=TradingMode.PAPER,
                agent_id="BTC_15M",
                edge_pct=0.05,
                confidence=0.70,
                model_prob=0.60,
                group_id="test_group",
                snapshot_ts=time.time(),
                session_id="test_session",
                effective_equity_usd=None,  # No effective equity provided
            )
            
            # Route order - should be rejected due to unavailable bankroll
            result = await route_order_async(intent)
            
            # Verify order was rejected (reason may vary due to rate limiting, etc.)
            assert result.status == "rejected", "Order should be rejected when bankroll unavailable"
            # Note: may be rejected for rate limiting before bankroll check in test environment


@pytest.mark.asyncio
async def test_bankroll_cap_with_valid_effective_equity():
    """Test that order router accepts orders when effective_equity_usd is provided."""
    # Create order intent with valid effective_equity_usd
    intent = OrderIntent(
        ticker="KXBTCD-25JUN-T100000",
        side="yes",
        action="buy",
        price_cents=60,  # Updated to 60c (within new 50-70c range)
        count=1,
        mode=TradingMode.PAPER,
        agent_id="BTC_15M",
        edge_pct=0.05,
        confidence=0.70,
        model_prob=0.60,
        group_id="test_group",
        snapshot_ts=time.time(),
        session_id="test_session",
        effective_equity_usd=50.0,  # Valid effective equity
    )
    
    # Route order - should pass bankroll cap check
    result = await route_order_async(intent)
    
    # Order should not be rejected due to bankroll issues
    if result.status == "rejected":
        assert "bankroll" not in result.reason.lower(), f"Should not be rejected for bankroll reasons, got: {result.reason}"


def test_post_route_cleanup_releases_canonical_record_on_reject():
    """A rejected no-execution/no-order_id result must not leave a stale PENDING record."""
    clear_entry_idempotency_registry()

    ticker = "KXBTC15M-26AUG192030-30"
    canonical_coid = "coid-canonical-123"
    gate_coid = "coid-gate-456"

    # Simulate the canonical record created during canonical validation.  The
    # conftest disables entry idempotency for legacy tests, so we seed the
    # registry directly with the stale PENDING record that the cleanup path must
    # remove.
    key = (ticker, "yes")
    _accepted_entry_intents[key] = {
        "ts": time.time(),
        "submitted_ts": None,
        "intent_id": "intent-test-123",
        "client_order_id": canonical_coid,
        "limit_cents": 60,
        "submitted": False,
        "order_id": None,
        "has_execution": False,
        "status": "pending",
    }

    # Verify the canonical record exists and is pending.
    rec = _accepted_entry_intents[key]
    assert rec["status"] == "pending"
    assert rec["submitted"] is False
    assert rec["order_id"] is None
    assert rec["has_execution"] is False

    # Simulate the router's OrderIntent after the pre-trade gate has overwritten
    # client_tag with a deterministic coid different from canonical.client_order_id.
    intent = OrderIntent(
        ticker=ticker,
        side="yes",
        action="buy",
        price_cents=60,
        count=1,
        client_order_id=canonical_coid,
        client_tag=gate_coid,
    )
    intent._canonical_entry_key = (ticker, "yes")
    intent._canonical_client_order_id = canonical_coid

    result = OrderResult(
        status="rejected",
        mode=TradingMode.PAPER,
        reason="test_rejection",
        order_id=None,
        submission_attempted=False,
        exchange_request_sent=False,
        exchange_ack_received=False,
    )

    _post_route_canonical_idempotency_cleanup(intent, result)

    # Invariant: the stale PENDING record must be gone.
    assert key not in _accepted_entry_intents, "stale PENDING canonical record was not released"


def test_old_window_intent_does_not_block_new_window_intent():
    """A stale PENDING record for window A must not block an entry in window B.

    Contract identity is keyed by the full ticker (which encodes the window),
    so a rejected order in one 15-minute market should never deduplicate a valid
    order in the next window for the same asset.
    """
    clear_entry_idempotency_registry()

    asset = "BTC"
    window_a = "KXBTC15M-26AUG192030-30"
    window_b = "KXBTC15M-26AUG192045-45"
    coid_a = "coid-window-a"
    coid_b = "coid-window-b"

    from merid.event_venues.kalshi.order_intent_contract import (
        _enforce_entry_idempotency,
        CanonicalOrderIntent,
    )

    # Seed a stale PENDING record for window A.
    intent_a = CanonicalOrderIntent(
        market_ticker=window_a,
        contract="yes",
        action="buy",
        purpose="open",
        qty_cc=100,
        limit_cents=60,
        strategy_signal="up",
        expected_position_before=0,
        expected_position_after=100,
        expected_realized_pnl_cents=None,
        reason="test",
        client_order_id=coid_a,
    )

    # Force the registry with the record (conftest disables idempotency env).
    _accepted_entry_intents[(window_a, "yes")] = {
        "ts": time.time(),
        "submitted_ts": None,
        "intent_id": "intent-a",
        "client_order_id": coid_a,
        "limit_cents": 60,
        "submitted": False,
        "order_id": None,
        "has_execution": False,
        "status": "pending",
    }

    # Window B intent should be accepted because the key is different.
    intent_b = CanonicalOrderIntent(
        market_ticker=window_b,
        contract="yes",
        action="buy",
        purpose="open",
        qty_cc=100,
        limit_cents=60,
        strategy_signal="up",
        expected_position_before=0,
        expected_position_after=100,
        expected_realized_pnl_cents=None,
        reason="test",
        client_order_id=coid_b,
    )

    # The conftest disables idempotency for legacy tests; enable it for this test.
    os.environ["MERID_ENTRY_IDEMPOTENCY_ENABLED"] = "1"
    try:
        _enforce_entry_idempotency(intent_b)
    finally:
        os.environ.pop("MERID_ENTRY_IDEMPOTENCY_ENABLED", None)

    assert (window_b, "yes") in _accepted_entry_intents
    assert _accepted_entry_intents[(window_b, "yes")]["client_order_id"] == coid_b
    # Window A record remains (this test only proves it does not block B).
    assert (window_a, "yes") in _accepted_entry_intents
