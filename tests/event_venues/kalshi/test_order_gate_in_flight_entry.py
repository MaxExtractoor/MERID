"""Regression tests for the in-flight entry race guard added to ``PreTradeGate``.

Observed bug (2026-08-30): two approved ENTRY intents on the same contract+side
submitted ~5s apart (e.g. NO@43 then NO@41).  ``position_cache`` only reflects
fills and ``resting_order_monitor`` only tracks GTC orders, so an aggressive IOC
entry is invisible to both during its in-flight window and the trailing intent
passed every gate.  The guard added in ``PreTradeGate.check`` / ``async_check``
blocks a second entry on the same contract+side while a prior entry is still
unresolved (PENDING/SUBMITTED/LIVE/PARTIAL).  FILLED is terminal, so once the
first entry fills, re-entry is governed by the normal position/scaling gates.
"""

from __future__ import annotations

import pytest

from merid.event_venues.kalshi.order_gate import (
    IdempotentOrderStore,
    OrderRecord,
    OrderStatus,
    PreTradeGate,
)


def _entry_record(coid: str, contract: str, side: str, status: OrderStatus, price_cents: int) -> OrderRecord:
    return OrderRecord(
        client_order_id=coid,
        agent_id="agent",
        strategy_group="grp",
        contract_id=contract,
        side=side,
        action="buy",
        target_count=1,
        price_cents=price_cents,
        status=status,
    )


class TestHasInFlightOrderForSide:
    def test_pending_matches(self):
        store = IdempotentOrderStore()
        store._orders["c1"] = _entry_record("c1", "C", "no", OrderStatus.PENDING, 43)
        assert store.has_in_flight_order_for_side("C", "no") is True

    def test_filled_does_not_match(self):
        store = IdempotentOrderStore()
        store._orders["c1"] = _entry_record("c1", "C", "no", OrderStatus.FILLED, 43)
        assert store.has_in_flight_order_for_side("C", "no") is False

    def test_other_side_does_not_match(self):
        store = IdempotentOrderStore()
        store._orders["c1"] = _entry_record("c1", "C", "yes", OrderStatus.PENDING, 43)
        assert store.has_in_flight_order_for_side("C", "no") is False

    def test_other_contract_does_not_match(self):
        store = IdempotentOrderStore()
        store._orders["c1"] = _entry_record("c1", "OTHER", "no", OrderStatus.PENDING, 43)
        assert store.has_in_flight_order_for_side("C", "no") is False


class TestInFlightEntryGate:
    def _gate(self) -> PreTradeGate:
        return PreTradeGate(IdempotentOrderStore())

    def test_second_entry_blocked_while_first_in_flight(self):
        gate = self._gate()
        gate._store._orders["c1"] = _entry_record("c1", "KXBTC15M-X", "no", OrderStatus.PENDING, 43)

        verdict = gate.check(
            agent_id="agent",
            strategy_group="grp",
            contract_id="KXBTC15M-X",
            side="no",
            action="buy",
            target_count=1,
            price_cents=41,  # different (cheaper) price - the race that slipped through
            decision_ts=1000.0,
            intent_id="intent-2",
            entry_or_exit="entry",
        )

        assert verdict.allowed is False
        assert verdict.reason == "in_flight_entry_exists"
        assert verdict.is_duplicate is True

    def test_exit_not_blocked_by_in_flight_gate(self):
        gate = self._gate()
        # An in-flight entry on the same contract+side must not block an EXIT.
        gate._store._orders["c1"] = _entry_record("c1", "KXBTC15M-X", "no", OrderStatus.LIVE, 43)

        verdict = gate.check(
            agent_id="agent",
            strategy_group="grp",
            contract_id="KXBTC15M-X",
            side="no",
            action="sell",
            target_count=1,
            price_cents=50,
            decision_ts=1000.0,
            intent_id="exit-1",
            entry_or_exit="exit",
            reduce_only=True,
        )

        assert verdict.reason != "in_flight_entry_exists"

    def test_entry_allowed_after_first_filled(self):
        gate = self._gate()
        gate._store._orders["c1"] = _entry_record("c1", "KXBTC15M-X", "no", OrderStatus.FILLED, 43)

        verdict = gate.check(
            agent_id="agent",
            strategy_group="grp",
            contract_id="KXBTC15M-X",
            side="no",
            action="buy",
            target_count=1,
            price_cents=30,  # strictly cheaper so price_repeat allows scaling in
            decision_ts=1000.0,
            intent_id="intent-3",
            entry_or_exit="entry",
        )

        # The in-flight guard must not fire once the prior entry is terminal.
        assert verdict.reason != "in_flight_entry_exists"
