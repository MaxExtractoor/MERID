"""Unresolved exchange orders keep their deduplication reservation."""

import time

import pytest

from merid.event_venues.kalshi.order_gate import (
    IdempotentOrderStore,
    OrderRecord,
    OrderStatus,
    PreTradeGate,
    deterministic_client_order_id,
)


def _record(coid, status):
    return OrderRecord(
        client_order_id=coid, agent_id="BTC_15M", strategy_group="btc_15m",
        contract_id="KXBTC15M-TEST", side="yes", action="buy",
        target_count=1, target_qty_cc=100, price_cents=50,
        status=status, updated_at=time.time() - 3600,
    )


@pytest.mark.asyncio
async def test_unknown_coid_is_blocked_by_sync_and_async_gate():
    args = dict(
        agent_id="BTC_15M", strategy_group="btc_15m", contract_id="KXBTC15M-TEST",
        side="yes", action="buy", target_count=1, price_cents=50, decision_ts=1000,
    )
    coid = deterministic_client_order_id(
        agent_id=args["agent_id"], strategy_group=args["strategy_group"],
        contract_id=args["contract_id"], side=args["side"], target_qty=100,
        decision_ts=args["decision_ts"], price_cents=args["price_cents"],
    )
    store = IdempotentOrderStore()
    store.insert_if_absent(_record(coid, OrderStatus.SUBMISSION_UNKNOWN))
    gate = PreTradeGate(store)
    for verdict in (gate.check(**args), await gate.async_check(**args)):
        assert not verdict.allowed
        assert verdict.reason == "duplicate:submission_unknown"


@pytest.mark.parametrize(
    "status",
    [OrderStatus.SUBMITTED, OrderStatus.SUBMISSION_UNKNOWN, OrderStatus.LIVE, OrderStatus.PARTIAL],
)
def test_sent_orders_block_identical_new_coid_even_when_old(status):
    store = IdempotentOrderStore()
    record = _record("existing", status)
    store.insert_if_absent(record)
    assert store.find_resting_duplicate(
        contract_id=record.contract_id, side=record.side, action=record.action,
        price_cents=record.price_cents, target_qty_cc=record.target_qty_cc,
        exclude_coid="new-coid",
    ) is record
