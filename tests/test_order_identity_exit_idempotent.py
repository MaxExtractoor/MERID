"""Exit order identity must be idempotent across reprices and resubmits."""

from __future__ import annotations

import os
import sqlite3
import time
from decimal import Decimal

import pytest

from merid.event_venues.kalshi.order_attempt_store import OrderAttemptStore
from merid.event_venues.kalshi.order_identity import (
    _compute_fingerprint,
    derive_exit_client_order_id,
    derive_exit_intent_id,
    finalize_order_identity,
)
from merid.event_venues.kalshi.order_router import OrderIntent


def _exit_intent(
    *,
    client_order_id: str,
    intent_id: str,
    price_cents: int,
    count_fp: Decimal,
    ticker: str = "KXBTC15M-TEST",
) -> OrderIntent:
    return OrderIntent(
        ticker=ticker,
        side="SELL_YES",
        action="sell",
        price_cents=price_cents,
        count=int(count_fp),
        count_fp=count_fp,
        order_type="limit",
        time_in_force="ioc",
        source="position_monitor_exit",
        agent_id="BTC_15M",
        reduce_only=True,
        entry_or_exit="exit",
        exit_reason="stop_loss",
        pre_position_size=1,
        expected_post_position_size=0,
        pre_position_fp=count_fp * 100,
        expected_post_position_fp=Decimal("0"),
        client_order_id=client_order_id,
        client_tag=client_order_id,
        intent_id=intent_id,
    )


@pytest.fixture
def attempt_store(tmp_path, monkeypatch):
    db_path = tmp_path / "order_attempts.db"
    monkeypatch.setenv("MERID_KALSHI_ORDER_ATTEMPT_DB", str(db_path))
    return OrderAttemptStore(str(db_path))


def test_derive_exit_client_order_id_ignores_resubmit_count():
    """A resubmit must not change the client_order_id for the same exit decision."""
    parent = "fill_abc123"
    reason = "stop_loss"
    coid0 = derive_exit_client_order_id(parent, reason, resubmit_count=0)
    coid1 = derive_exit_client_order_id(parent, reason, resubmit_count=1)
    coid2 = derive_exit_client_order_id(parent, reason, resubmit_count=2)
    assert coid0 == coid1 == coid2
    assert coid0 != derive_exit_client_order_id(parent, "take_profit")


def test_finalize_order_identity_reuses_coid_through_exit_reprice(attempt_store):
    """A repriced retry of the same exit keeps the same client_order_id/order_attempt_id."""
    parent = "fill_abc123"
    reason = "stop_loss"
    intent_id = derive_exit_intent_id(parent, reason)
    coid = derive_exit_client_order_id(parent, reason, resubmit_count=0)

    # First attempt at 52c.
    intent1 = _exit_intent(
        client_order_id=coid,
        intent_id=intent_id,
        price_cents=52,
        count_fp=Decimal("1"),
    )
    finalize_order_identity(intent1, store=attempt_store)
    original_attempt_id = intent1.order_attempt_id
    assert intent1.client_order_id == coid
    record1 = attempt_store.get_by_client_order_id(coid)
    assert record1 is not None
    assert record1.intent_id == intent_id

    # Repriced retry at 48c (exit guard reprice) for the same exit decision.
    intent2 = _exit_intent(
        client_order_id=coid,
        intent_id=intent_id,
        price_cents=48,
        count_fp=Decimal("1"),
    )
    finalize_order_identity(intent2, store=attempt_store)
    assert intent2.client_order_id == coid
    assert intent2.order_attempt_id == original_attempt_id

    # Only one attempt record exists; the durable identity was reused, not replaced.
    records = attempt_store.get_by_intent_id(intent_id)
    assert len(records) == 1


def test_finalize_order_identity_rejects_coid_for_different_exit(attempt_store):
    """A coid already bound to one exit must not be recycled for a different exit."""
    parent = "fill_def456"
    reason = "stop_loss"
    intent_id = derive_exit_intent_id(parent, reason)
    coid = derive_exit_client_order_id(parent, reason, resubmit_count=0)

    intent1 = _exit_intent(
        client_order_id=coid,
        intent_id=intent_id,
        price_cents=52,
        count_fp=Decimal("1"),
    )
    finalize_order_identity(intent1, store=attempt_store)

    # A different exit decision with the same coid is disallowed.
    intent2 = _exit_intent(
        client_order_id=coid,
        intent_id=derive_exit_intent_id(parent, "take_profit"),
        price_cents=55,
        count_fp=Decimal("1"),
    )
    finalize_order_identity(intent2, store=attempt_store)
    assert intent2.client_order_id != coid
    assert intent2.order_attempt_id != intent1.order_attempt_id
