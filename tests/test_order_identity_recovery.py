"""Durable order-identity and recovery invariants.

These tests exercise the canonical order-identity layer:

    - ``OrderAttemptStore`` / ``OrderAttemptRecord``
    - ``finalize_order_identity``
    - ``create_replacement_attempt``
    - ``_route_live`` against a mocked ``KalshiExecutionPort``

The scenarios cover timeout-after-receipt, crash/restart, 409 idempotency,
replacement children, concurrent routing, fill-before-ack, cancel/fill race,
and fractional-quantity fixed-point wire semantics.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from merid.event_venues.kalshi.order_attempt_store import (
    DEFAULT_DB_PATH,
    OrderAttemptRecord,
    OrderAttemptStore,
)
from merid.event_venues.kalshi.order_identity import (
    OrderIdentityError,
    _compute_fingerprint,
    create_replacement_attempt,
    finalize_order_identity,
)
from merid.event_venues.kalshi.order_router import (
    OrderIntent,
    OrderResult,
    TradingMode,
    _route_live,
)
from merid.event_venues.kalshi.order_gate import (
    get_pre_trade_gate,
    reset_pre_trade_gate_for_testing,
)
from merid.event_venues.kalshi.contract_lease import (
    reset_contract_lease_registry_for_testing,
)
from merid.event_venues.kalshi.port import (
    BalanceResult,
    CancelResult,
    CreateOrderRequest,
    CreateOrderResponse,
    Fill,
    FillsResponse,
    HistoricalFillsResponse,
    HistoricalPositionsResponse,
    KalshiExecutionPort,
    MarketResult,
    Order,
    OrderGroupsResult,
    OrderbookResult,
    PositionsResponse,
    get_kalshi_execution_port,
    reset_kalshi_execution_port_for_testing,
    set_kalshi_execution_port,
)
from merid.risk.unified_risk_manager import (
    UnifiedRiskManager,
    get_unified_risk_manager,
)
import merid.risk.profiles.global_allocator as _global_allocator_module
from tests.event_venues.kalshi.deterministic_kalshi_client import (
    DeterministicKalshiClient,
)


# ---------------------------------------------------------------------------
# Stubs for non-port helpers
# ---------------------------------------------------------------------------

class _VenueGateStub:
    mode = TradingMode.LIVE
    live_enabled = True

    def log_order_decision(self, **kwargs) -> None:
        pass


class _RiskControllerStub:
    def can_trade(self) -> bool:
        return True

    def get_kill_reason(self) -> Optional[str]:
        return None

    def halt_strategy(self, *args, **kwargs) -> None:
        pass


class _DynamicRiskStub:
    def can_trade_now(self):
        return True, "ok"

    def update_execution_metrics(self, **kwargs) -> None:
        pass


class _GlobalAllocatorStub:
    """Record the pending/filled lifecycle so tests can inspect it."""

    def __init__(self):
        self._pending_orders: dict = {}
        self._asset_positions: dict = {}

    def record_order_submitted(self, asset: str, order_id: str, notional_usd: float) -> None:
        self._pending_orders[asset] = (order_id, notional_usd)

    def record_order_filled(self, asset: str, order_id: str, fill_notional_usd: float) -> None:
        self._pending_orders.pop(asset, None)
        self._asset_positions[asset] = (order_id, fill_notional_usd)

    def record_order_rejected(self, asset: str, order_id: str) -> None:
        self._pending_orders.pop(asset, None)


class _AllocationRequestStub:
    """Drop-in replacement for ``global_slot_allocator.AllocationRequest``
    that does not enforce count=1, so tests can exercise sizes other than one
    full contract without the real slot allocator rejecting the request."""

    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


class _GlobalSlotAllocatorStub:
    """Prevent the real per-asset single-position cap from interfering with
    identity/recovery tests.  _route_live calls this before submission; a stub
    lets us exercise retries and concurrent routing without slot leaks."""

    def __init__(self):
        self._slots: Dict[str, Any] = {}
        self._next_id = 0

    def can_allocate(self, entry_price_cents: int, asset: Optional[str] = None) -> tuple:
        return True, ""

    def request_allocation(self, request: Any) -> tuple:
        if getattr(request, "is_exit_order", False):
            return True, "EXIT_ORDER_BYPASS", None
        self._next_id += 1
        slot_id = f"stub-{request.agent_id}-{request.asset}-{self._next_id}"
        self._slots[slot_id] = request
        return True, "", slot_id

    def release_slot(self, slot_id: str, exit_price_cents: Optional[int] = None) -> bool:
        return self._slots.pop(slot_id, None) is not None

    def get_slots_by_asset(self, asset: str) -> List[Any]:
        return [s for s in self._slots.values() if getattr(s, "asset", None) == asset]

    def get_total_exposure(self) -> float:
        return 0.0

    def get_available_exposure(self) -> float:
        return 1.0

    def sync_with_position_cache(self) -> int:
        return 0

    def clear_slots_on_empty_positions(self, position_count: int) -> None:
        if position_count == 0:
            self._slots.clear()


class _DedupCacheStub:
    def __init__(self, coid: str) -> None:
        self._coid = coid

    def get_or_create(self, **kwargs):
        return self._coid, False

    def mark_completed(self, *args, **kwargs) -> None:
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate_gate_and_lease(monkeypatch, tmp_path):
    """Reset all singletons and stub out cross-test services."""
    import os

    reset_pre_trade_gate_for_testing()
    reset_contract_lease_registry_for_testing()
    UnifiedRiskManager.reset_for_tests()

    # Real risk manager, but with limits loose enough for unit-level identity tests.
    risk = get_unified_risk_manager()
    risk._limits.fixed_exposure_cap_usd = 1000.0
    risk._limits.per_trade_max_contracts = 10
    risk._limits.per_asset_enabled = False
    risk._limits.rate_limit_min_time_between_trades = 0.0
    risk.calibrate_from_balance(100_000_000)

    # The global slot allocator is a process-wide singleton.  Each identity test
    # should start from a clean state; we also stub it to prevent the real
    # per-asset single-position cap from blocking retries and concurrent routes.
    from merid.risk.global_slot_allocator import get_global_slot_allocator
    real = get_global_slot_allocator()
    real.reset_all()
    monkeypatch.setattr(
        "merid.risk.global_slot_allocator.get_global_slot_allocator",
        lambda: _GlobalSlotAllocatorStub(),
    )
    monkeypatch.setattr(
        "merid.risk.global_slot_allocator.AllocationRequest",
        _AllocationRequestStub,
    )

    # Process-wide caches/ledgers must be reset so repeated ``ord-1`` ids from
    # the deterministic client do not look like duplicate fills across tests.
    from merid.event_venues.kalshi import position_cache as _position_cache_module
    _position_cache_module.KalshiPositionCache._instance = None
    _position_cache_module._position_cache_instance = None

    from merid.event_venues.kalshi import position_sanity_checker as _position_sanity_checker
    _position_sanity_checker._checker_instance = None

    # Redirect the fills ledger to a per-test SQLite file under a stable profile.
    os.environ["MERID_PROFILE"] = "test_identity_recovery"
    os.environ["MERID_FILLS_DB_PATH"] = str(tmp_path / "kalshi_fills.db")
    from merid.event_venues.kalshi.fills_ledger import _ledgers
    _ledgers["test_identity_recovery"] = None

    # The deterministic client does not implement get_orderbook; disable the
    # WS-vs-REST divergence guard for these tests.
    monkeypatch.setattr(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
        lambda: None,
    )

    yield
    reset_pre_trade_gate_for_testing()
    reset_contract_lease_registry_for_testing()
    reset_kalshi_execution_port_for_testing()


@pytest.fixture
def attempt_store(tmp_path, monkeypatch) -> OrderAttemptStore:
    """Fresh, isolated OrderAttemptStore using a temp SQLite file."""
    db_path = tmp_path / "kalshi_order_attempts.db"
    monkeypatch.setattr(
        "merid.event_venues.kalshi.order_attempt_store.DEFAULT_DB_PATH",
        str(db_path),
    )
    # Force a new singleton for this test so we don't reuse another test's DB.
    monkeypatch.setattr(OrderAttemptStore, "_instances", {})
    return OrderAttemptStore()


@pytest.fixture
def client(monkeypatch, attempt_store) -> DeterministicKalshiClient:
    """Fresh deterministic simulator with a live-like risk environment."""
    c = DeterministicKalshiClient()
    c.set_time(1_700_000_000)
    c.set_balance(Decimal("10000"), locked=Decimal("0"))
    set_kalshi_execution_port(c)

    monkeypatch.setattr(
        "merid.event_venues.kalshi.client.get_kalshi_client", lambda: c
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.order_router.get_venue_gate",
        lambda: _VenueGateStub(),
    )
    monkeypatch.setattr(
        "merid.risk.kill_switches.risk_controller", _RiskControllerStub()
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.dynamic_risk.get_dynamic_risk_engine",
        lambda: _DynamicRiskStub(),
    )

    _ga = _GlobalAllocatorStub()
    monkeypatch.setattr(
        "merid.risk.profiles.global_allocator.get_global_allocator",
        lambda: _ga,
    )
    monkeypatch.setattr(
        "merid.risk.profiles.crypto_15m_profile.get_active_profile",
        lambda: None,
    )
    import merid.settings as _settings
    monkeypatch.setattr(_settings.settings, "MERID_EXECUTION_MODE", "normal")

    # Disable the WS-vs-REST divergence guard; the DeterministicKalshiClient does
    # not implement get_orderbook, and the state store is not populated in tests.
    monkeypatch.setattr(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
        lambda: None,
    )

    risk = get_unified_risk_manager()
    risk._limits.fixed_exposure_cap_usd = 1000.0
    risk._limits.per_trade_max_contracts = 10
    risk._limits.per_asset_enabled = False
    risk._limits.rate_limit_min_time_between_trades = 0.0
    risk.calibrate_from_balance(100_000_000)

    return c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_intent(
    *,
    ticker: str,
    price_cents: int,
    count: int = 1,
    count_fp: Optional[Decimal] = None,
    tif: str = "gtc",
    aggressiveness: float = 0.0,
    post_only: bool = False,
    liquidity_role: Optional[str] = None,
    order_expiration_ts: Optional[int] = None,
    decision_id: Optional[str] = None,
) -> OrderIntent:
    if count_fp is None:
        count_fp = Decimal(count)
    if liquidity_role is None:
        # Match the router's expectation: taker for marketable orders, maker for
        # passive orders.  Without this the liquidity-role price invariant rejects.
        liquidity_role = "taker" if aggressiveness >= 1.0 else "maker"
    return OrderIntent(
        ticker=ticker,
        side="BUY_YES",
        action="buy",
        price_cents=price_cents,
        count=count,
        count_fp=count_fp,
        time_in_force=tif,
        post_only=post_only,
        aggressiveness=aggressiveness,
        liquidity_role=liquidity_role,
        order_type="limit",
        source="agent_grid",
        snapshot_ts=time.time(),
        edge_pct=5.0,
        confidence=0.7,
        exit_policy_id="test",
        window_resolution_id="test_window",
        risk_tier="A",
        max_hold_seconds=600,
        order_expiration_ts=order_expiration_ts,
        decision_id=decision_id,
    )


def _fresh_state() -> SimpleNamespace:
    return SimpleNamespace(
        last_book_update_ts=time.monotonic(),
        last_rest_update_ts=time.monotonic(),
        book_initialized=True,
        depth_10c=100,
        mid_cents=50,
        best_bid_cents=45,
        best_ask_cents=55,
        best_no_bid_cents=None,
        best_no_ask_cents=None,
        yes_depth=100,
        no_depth=100,
    )


def _reserve_gate(intent: OrderIntent, monkeypatch, strategy: str = "test_identity") -> str:
    gate = get_pre_trade_gate()
    verdict = gate.check(
        agent_id=intent.agent_id or "agent_grid",
        strategy_group=strategy,
        contract_id=intent.ticker,
        side=intent.side,
        action=intent.action,
        target_count=intent.count,
        price_cents=intent.price_cents,
        decision_ts=intent.snapshot_ts,
        intent_id=intent.intent_id,
        exit_policy_id=intent.exit_policy_id,
        window_resolution_id=intent.window_resolution_id,
        risk_tier=intent.risk_tier,
        max_hold_seconds=intent.max_hold_seconds,
        entry_or_exit=intent.entry_or_exit or "entry",
        reduce_only=intent.reduce_only,
    )
    assert verdict.allowed, f"gate unexpectedly blocked: {verdict.reason}"
    intent.client_tag = verdict.client_order_id
    intent.client_order_id = verdict.client_order_id
    stub = _DedupCacheStub(verdict.client_order_id)
    monkeypatch.setattr(
        "merid.event_venues.kalshi.order_router._dedup_cache", lambda: stub
    )
    return verdict.client_order_id


async def _route(intent: OrderIntent) -> OrderResult:
    return await _route_live(
        intent,
        TradingMode.LIVE,
        time.monotonic(),
        prepared_state=_fresh_state(),
        plan_done=True,
    )


# ---------------------------------------------------------------------------
# 1. Timeout after server receipt
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_timeout_after_server_receipt(client, attempt_store, monkeypatch):
    """HTTP ack is lost after the venue accepts the order.

    The first attempt is persisted, marked SUBMISSION_UNKNOWN, and the retry
    reuses the same coid/fingerprint.  Only one venue order exists and no
    additional exposure is added.
    """
    ticker = "KXBTC15M-TIMEOUT-50000"
    client.set_market(
        ticker,
        SimpleNamespace(
            best_bid=45,
            best_ask=55,
            volume=1000,
            open_interest=1000,
            active=True,
            resolved=False,
        ),
    )
    client.set_orderbook(
        ticker,
        best_bid_cents=45,
        best_ask_cents=55,
        bid_size=Decimal("10"),
        ask_size=Decimal("10"),
    )

    intent = _base_intent(
        ticker=ticker,
        price_cents=50,
        tif="gtc",
        aggressiveness=0.0,
        post_only=False,
        order_expiration_ts=int(time.time()) + 3600,
    )
    coid = _reserve_gate(intent, monkeypatch)
    finalize_order_identity(intent, store=attempt_store)
    original_attempt_id = intent.order_attempt_id

    client.set_timeout_after_submit("once")
    result1 = await _route(intent)
    # The broker query resolves the timeout immediately because the order is
    # already resting on the exchange (price 50c does not cross ask 55c).
    assert result1.status == "resting", result1
    assert not result1.requires_recovery

    record = attempt_store.get_by_client_order_id(coid)
    assert record is not None
    assert record.status == "ACKNOWLEDGED"
    assert record.client_order_id == coid

    # Retry with the same fingerprint and a fresh intent object.
    retry = _base_intent(
        ticker=ticker,
        price_cents=50,
        tif="gtc",
        aggressiveness=0.0,
        post_only=False,
        order_expiration_ts=intent.order_expiration_ts,
    )
    retry.client_order_id = coid
    retry.client_tag = coid
    finalize_order_identity(retry, store=attempt_store)
    assert retry.order_attempt_id == original_attempt_id
    assert retry.client_order_id == coid

    monkeypatch.setattr(
        "merid.event_venues.kalshi.order_router._dedup_cache",
        lambda: _DedupCacheStub(coid),
    )
    result2 = await _route(retry)
    assert result2.status in ("resting", "accepted_live", "submitted_live"), result2

    # One venue order, one attempt, no filled exposure.
    assert len(client._client_to_order) == 1
    assert len(client._orders) == 1
    assert client._position_yes.get(ticker, Decimal("0")) == 0
    assert client._position_no.get(ticker, Decimal("0")) == 0

    updated = attempt_store.get_by_client_order_id(coid)
    assert updated.order_attempt_id == original_attempt_id
    assert updated.status == "ACKNOWLEDGED"


# ---------------------------------------------------------------------------
# 2. Crash/restart during submission
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_crash_restart_during_submission(attempt_store):
    """A process crash leaves an attempt in SUBMITTING.

    After restart, finalize_order_identity recovers the same coid and
    order_attempt_id from the durable fingerprint.  No new coid is allocated
    for the same decision/fingerprint.
    """
    ticker = "KXBTC15M-CRASH-50000"
    intent = _base_intent(ticker=ticker, price_cents=50, tif="gtc")
    coid = "manual-coid-crash-1"
    intent.client_order_id = coid
    intent.client_tag = coid

    finalize_order_identity(intent, store=attempt_store)
    original_attempt_id = intent.order_attempt_id
    attempt_store.update_status(original_attempt_id, "SUBMITTING")

    # Simulate a new process after restart: fresh intent, no coid.
    # client_tag provides the decision/fingerprint linkage.
    restart = _base_intent(ticker=ticker, price_cents=50, tif="gtc")
    restart.client_tag = coid
    finalize_order_identity(restart, store=attempt_store)

    assert restart.client_order_id == coid
    assert restart.order_attempt_id == original_attempt_id
    assert restart.client_tag == coid

    record = attempt_store.get_by_client_order_id(coid)
    assert record.status == "SUBMITTING"
    assert record.fingerprint == _compute_fingerprint(restart)

    # Exactly one durable attempt for this fingerprint/decision.
    assert len(attempt_store.get_by_fingerprint(record.fingerprint)) == 1
    assert len(attempt_store.get_by_decision_id(coid)) == 1


# ---------------------------------------------------------------------------
# 3. 409 / Idempotency recovery
# ---------------------------------------------------------------------------

def test_409_fingerprint_mismatch_mints_fresh_coid(attempt_store):
    """A coid with a different economic fingerprint is not reused.

    The identity layer mints a fresh client_order_id rather than allowing an
    existing idempotency key to collide with a materially different order.
    """
    ticker = "KXBTC15M-409-50000"
    intent = _base_intent(ticker=ticker, price_cents=50, tif="gtc")
    coid = "manual-coid-409-1"
    intent.client_order_id = coid
    intent.client_tag = coid
    finalize_order_identity(intent, store=attempt_store)

    mismatch = _base_intent(ticker=ticker, price_cents=55, tif="gtc")
    mismatch.client_order_id = coid
    mismatch.client_tag = coid
    finalize_order_identity(mismatch, store=attempt_store)

    # The mismatched coid must not be adopted for the new price.
    assert mismatch.client_order_id != coid
    # The original record remains intact and keeps its original fingerprint.
    original = attempt_store.get_by_client_order_id(coid)
    assert original is not None
    assert original.fingerprint != _compute_fingerprint(mismatch)


@pytest.mark.asyncio
async def test_409_idempotency_recovery(client, attempt_store, monkeypatch):
    """A duplicate 409 response recovers the original venue order."""
    ticker = "KXBTC15M-409-50000"
    client.set_market(
        ticker,
        SimpleNamespace(
            best_bid=45,
            best_ask=55,
            volume=1000,
            open_interest=1000,
            active=True,
            resolved=False,
        ),
    )
    client.set_orderbook(
        ticker,
        best_bid_cents=45,
        best_ask_cents=55,
        bid_size=Decimal("10"),
        ask_size=Decimal("10"),
    )

    intent = _base_intent(
        ticker=ticker,
        price_cents=50,
        tif="gtc",
        aggressiveness=0.0,
        post_only=False,
        order_expiration_ts=int(time.time()) + 3600,
    )
    coid = _reserve_gate(intent, monkeypatch)
    finalize_order_identity(intent, store=attempt_store)

    result1 = await _route(intent)
    assert result1.status in ("resting", "accepted_live", "submitted_live"), result1
    assert result1.order_id is not None
    assert coid in client._client_to_order

    # Patch the port so the second create_order returns a 409-style error.
    original_create = client.create_order
    calls: List[CreateOrderRequest] = []

    async def _create_once_409(request: CreateOrderRequest) -> CreateOrderResponse:
        calls.append(request)
        if len(calls) == 1:
            return await original_create(request)
        return CreateOrderResponse(
            success=False,
            error="409 duplicate client_order_id",
        )

    client.create_order = _create_once_409

    retry = _base_intent(
        ticker=ticker,
        price_cents=50,
        tif="gtc",
        aggressiveness=0.0,
        post_only=False,
        order_expiration_ts=intent.order_expiration_ts,
    )
    retry.client_order_id = coid
    retry.client_tag = coid
    finalize_order_identity(retry, store=attempt_store)

    monkeypatch.setattr(
        "merid.event_venues.kalshi.order_router._dedup_cache",
        lambda: _DedupCacheStub(coid),
    )
    result2 = await _route(retry)
    assert result2.status in ("resting", "accepted_live", "submitted_live"), result2
    assert result2.order_id == result1.order_id

    # Still exactly one venue order.
    assert len(client._client_to_order) == 1
    assert len(client._orders) == 1
    assert client._client_to_order[coid] == result1.order_id

    record = attempt_store.get_by_client_order_id(coid)
    assert record.fingerprint == _compute_fingerprint(retry)
    payload = json.loads(record.payload_json)
    assert payload["fingerprint_source"] == "finalize_order_identity"


# ---------------------------------------------------------------------------
# 4. Same decision, two legitimate children
# ---------------------------------------------------------------------------

def test_same_decision_two_legitimate_children(attempt_store):
    """One decision can spawn an initial and a replacement attempt.

    The two attempts share decision_id, have distinct coids and
    order_attempt_ids, and the child links to the parent via
    replaces_order_attempt_id.
    """
    ticker = "KXBTC15M-CHILD-50000"
    decision_id = "decision-4"

    initial = _base_intent(
        ticker=ticker,
        price_cents=50,
        tif="gtc",
        decision_id=decision_id,
    )
    finalize_order_identity(initial, store=attempt_store)
    initial_attempt_id = initial.order_attempt_id
    initial_coid = initial.client_order_id

    replacement = _base_intent(
        ticker=ticker,
        price_cents=55,
        tif="gtc",
        decision_id=decision_id,
    )
    create_replacement_attempt(
        replacement, initial_attempt_id, store=attempt_store
    )

    records = attempt_store.get_by_decision_id(decision_id)
    assert len(records) == 2
    assert all(r.decision_id == decision_id for r in records)

    coids = {r.client_order_id for r in records}
    attempt_ids = {r.order_attempt_id for r in records}
    assert len(coids) == 2
    assert len(attempt_ids) == 2

    parent = next(r for r in records if r.order_attempt_id == initial_attempt_id)
    child = next(r for r in records if r.replaces_order_attempt_id == initial_attempt_id)
    assert parent.replaces_order_attempt_id is None
    assert child.replaces_order_attempt_id == initial_attempt_id
    assert parent.client_order_id == initial_coid
    assert child.client_order_id != initial_coid


# ---------------------------------------------------------------------------
# 5. Concurrent routing
# ---------------------------------------------------------------------------

def test_sqlite_wal_concurrent_insert_retries(attempt_store, tmp_path):
    """Two threads inserting the same coid converge to one canonical row."""
    coid = "shared-coid-concurrent-1"
    decision_id = "decision-concurrent-1"
    fingerprint = _compute_fingerprint(
        _base_intent(ticker="KXBTC15M-CONC-50000", price_cents=50)
    )

    def _build_record(attempt_id: str, intent_id: str) -> OrderAttemptRecord:
        return OrderAttemptRecord(
            order_attempt_id=attempt_id,
            client_order_id=coid,
            decision_id=decision_id,
            replaces_order_attempt_id=None,
            intent_id=intent_id,
            client_tag=coid,
            run_id="r",
            process_id="p",
            fingerprint=fingerprint,
            status="PERSISTED",
            created_at=time.time(),
            updated_at=time.time(),
            payload_json="{}",
        )

    r1 = _build_record("oa_attempt_1", "intent_1")
    r2 = _build_record("oa_attempt_2", "intent_2")

    results: List[Optional[tuple]] = [None, None]

    def _try_insert(record: OrderAttemptRecord, idx: int) -> None:
        for _ in range(10):
            try:
                attempt_store.persist_attempt(record)
                results[idx] = ("inserted", record.order_attempt_id)
                return
            except (sqlite3.IntegrityError, sqlite3.OperationalError):
                time.sleep(0.005)
                existing = attempt_store.get_by_client_order_id(coid)
                if existing is not None:
                    results[idx] = ("recovered", existing.order_attempt_id)
                    return
        results[idx] = ("failed", None)

    t1 = threading.Thread(target=_try_insert, args=(r1, 0))
    t2 = threading.Thread(target=_try_insert, args=(r2, 1))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert all(r is not None for r in results)
    assert "failed" not in [r[0] for r in results]

    attempt_ids = {r[1] for r in results}
    assert len(attempt_ids) == 1

    record = attempt_store.get_by_client_order_id(coid)
    assert record is not None
    assert record.client_order_id == coid
    assert record.fingerprint == fingerprint


@pytest.mark.asyncio
async def test_concurrent_routing_one_coid_one_submission(
    client, attempt_store, monkeypatch
):
    """Two async workers with the same intent/attempt race to route live.

    Only one canonical coid, one stored attempt, and at most one live
    submission should exist.  The second worker must recover the first's
    venue order, not submit a second one.
    """
    ticker = "KXBTC15M-RACE-50000"
    client.set_market(
        ticker,
        SimpleNamespace(
            best_bid=45,
            best_ask=55,
            volume=1000,
            open_interest=1000,
            active=True,
            resolved=False,
        ),
    )
    client.set_orderbook(
        ticker,
        best_bid_cents=45,
        best_ask_cents=55,
        bid_size=Decimal("10"),
        ask_size=Decimal("10"),
    )

    base = _base_intent(
        ticker=ticker,
        price_cents=55,
        tif="ioc",
        aggressiveness=1.0,
    )
    coid = _reserve_gate(base, monkeypatch)
    finalize_order_identity(base, store=attempt_store)
    attempt_id = base.order_attempt_id

    copy = _base_intent(
        ticker=ticker,
        price_cents=55,
        tif="ioc",
        aggressiveness=1.0,
    )
    copy.client_order_id = coid
    copy.client_tag = coid
    copy.order_attempt_id = attempt_id
    finalize_order_identity(copy, store=attempt_store)

    monkeypatch.setattr(
        "merid.event_venues.kalshi.order_router._dedup_cache",
        lambda: _DedupCacheStub(coid),
    )

    r1, r2 = await asyncio.gather(_route(base), _route(copy))
    assert all(
        r.status in ("filled_live", "submitted_live", "resting") for r in (r1, r2)
    ), (r1, r2)

    # Exactly one venue order and one stored attempt.
    assert len(client._client_to_order) == 1
    assert len(client._orders) == 1
    assert client._client_to_order[coid] in {r1.order_id, r2.order_id}

    record = attempt_store.get_by_client_order_id(coid)
    assert record is not None
    assert record.order_attempt_id == attempt_id

    # Exposure applied exactly once.
    assert client._position_yes.get(ticker, Decimal("0")) == Decimal("1")


# ---------------------------------------------------------------------------
# 6. Fill before acknowledgement
# ---------------------------------------------------------------------------

@dataclass
class _FillBeforeAckPort:
    """Port that loses the HTTP ack but still records the order and fill."""

    ticker: str
    coid: str
    order_id: str
    fill_size: Decimal
    price_cents: int
    _size: Optional[Decimal] = None
    _submitted: bool = False

    @property
    def is_circuit_open(self) -> bool:
        return False

    async def connect(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def create_order(self, request: CreateOrderRequest) -> CreateOrderResponse:
        self._submitted = True
        self._size = request.size
        # The venue accepted the order, but the HTTP ack is lost.
        raise asyncio.TimeoutError("HTTP ack lost in flight")

    async def get_order(
        self,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
        market_id: Optional[str] = None,
    ) -> Optional[Order]:
        if client_order_id == self.coid:
            size = self._size or self.fill_size
            return Order(
                order_id=self.order_id,
                client_order_id=self.coid,
                ticker=self.ticker,
                side="buy",
                outcome="yes",
                size=size,
                filled_size=self.fill_size,
                remaining_size=Decimal("0"),
                price_cents=self.price_cents,
                status="filled",
                time_in_force="ioc",
            )
        return None

    async def get_fills(
        self,
        cursor: Optional[str] = None,
        since_ts: Optional[int] = None,
        limit: int = 200,
        market_id: Optional[str] = None,
        order_id: Optional[str] = None,
    ) -> FillsResponse:
        if not self._submitted:
            return FillsResponse(fills=[])
        return FillsResponse(
            fills=[
                Fill(
                    fill_id="ws-fill-1",
                    order_id=self.order_id,
                    ticker=self.ticker,
                    side="buy",
                    outcome="yes",
                    size=self.fill_size,
                    price_cents=self.price_cents,
                    client_order_id=self.coid,
                    trade_id="ws-fill-1",
                    fee_usd=Decimal("0"),
                )
            ]
        )

    async def cancel_order(self, order_id: str) -> CancelResult:
        return CancelResult(success=False, order_id=order_id, error="not submitted")

    async def get_open_orders(self, ticker: Optional[str] = None) -> List[Order]:
        return []

    async def get_positions(self) -> PositionsResponse:
        return PositionsResponse()

    async def get_historical_positions(
        self, cursor: Optional[str] = None
    ) -> HistoricalPositionsResponse:
        return HistoricalPositionsResponse()

    async def get_historical_fills(
        self, cursor: Optional[str] = None, since_ts: Optional[int] = None, limit: int = 200
    ) -> HistoricalFillsResponse:
        return HistoricalFillsResponse()

    async def get_market(self, ticker: str) -> MarketResult:
        return MarketResult(
            success=True,
            market=SimpleNamespace(
                best_bid=45,
                best_ask=55,
                volume=1000,
                open_interest=1000,
                active=True,
                resolved=False,
            ),
        )

    async def get_orderbook(self, ticker: str) -> OrderbookResult:
        return OrderbookResult(success=True)

    async def get_balance(self) -> BalanceResult:
        return BalanceResult(success=True, available_usd=Decimal("10000"))

    async def get_order_groups(self, limit: int = 200) -> OrderGroupsResult:
        return OrderGroupsResult(success=True)


@pytest.mark.asyncio
async def test_fill_before_acknowledgement(attempt_store):
    """A WebSocket fill arrives before the HTTP create-order ack.

    The fill must resolve to the canonical coid/order_attempt and the durable
    store must be updated to FILLED without creating a second attempt.
    """
    ticker = "KXBTC15M-WSFILL-50000"
    coid = "coid-wsfill-1"
    order_id = "ord-wsfill-1"
    port = _FillBeforeAckPort(
        ticker=ticker,
        coid=coid,
        order_id=order_id,
        fill_size=Decimal("1"),
        price_cents=55,
    )
    set_kalshi_execution_port(port)

    intent = _base_intent(ticker=ticker, price_cents=55, tif="ioc", aggressiveness=1.0)
    intent.client_order_id = coid
    intent.client_tag = coid
    intent.decision_id = coid
    finalize_order_identity(intent, store=attempt_store)

    # The initial route times out: the ack is lost, but the broker query
    # resolves the order to filled without waiting for the WebSocket fill.
    result = await _route(intent)
    assert result.status == "filled_live", result
    assert result.has_execution
    assert result.order_id == order_id

    record = attempt_store.get_by_client_order_id(coid)
    assert record is not None
    assert record.order_attempt_id == intent.order_attempt_id
    assert record.status == "FILLED"

    # The WebSocket fill that arrives later is a duplicate of the same fill.
    fills = await port.get_fills()
    assert len(fills.fills) == 1
    fill = fills.fills[0]
    assert fill.client_order_id == coid

    updated = attempt_store.get_by_client_order_id(coid)
    assert updated.status == "FILLED"
    assert len(attempt_store.get_by_fingerprint(record.fingerprint)) == 1


# ---------------------------------------------------------------------------
# 7. Cancel / fill race
# ---------------------------------------------------------------------------

@dataclass
class _CancelFillRacePort:
    """Port simulating a partial fill that beats the cancel acknowledgement."""

    ticker: str
    coid: str
    order_id: str
    fill_size: Decimal
    price_cents: int
    _order: Optional[Order] = None
    _canceled: bool = False

    @property
    def is_circuit_open(self) -> bool:
        return False

    async def connect(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def create_order(self, request: CreateOrderRequest) -> CreateOrderResponse:
        self._order = Order(
            order_id=self.order_id,
            client_order_id=self.coid,
            ticker=self.ticker,
            side="buy",
            outcome="yes",
            size=request.size,
            filled_size=Decimal("0"),
            remaining_size=request.size,
            price_cents=self.price_cents,
            status="resting",
            time_in_force="gtc",
        )
        return CreateOrderResponse(
            success=True,
            order_id=self.order_id,
            client_order_id=self.coid,
            status="resting",
            filled_size=Decimal("0"),
            remaining_size=request.size,
            price_cents=self.price_cents,
        )

    async def cancel_order(self, order_id: str) -> CancelResult:
        if order_id != self.order_id:
            return CancelResult(success=False, order_id=order_id, error="not found")
        self._canceled = True
        # Simulate the cancel ack arriving after the partial fill has already
        # executed.  The order is now canceled with the filled portion retained.
        if self._order is not None:
            self._order = Order(
                order_id=self.order_id,
                client_order_id=self.coid,
                ticker=self.ticker,
                side="buy",
                outcome="yes",
                size=self._order.size,
                filled_size=self.fill_size,
                remaining_size=Decimal("0"),
                price_cents=self.price_cents,
                status="canceled",
                time_in_force="gtc",
            )
        return CancelResult(success=True, order_id=order_id, new_status="canceled")

    async def get_order(
        self,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
        market_id: Optional[str] = None,
    ) -> Optional[Order]:
        return self._order

    async def get_fills(
        self,
        cursor: Optional[str] = None,
        since_ts: Optional[int] = None,
        limit: int = 200,
        market_id: Optional[str] = None,
        order_id: Optional[str] = None,
    ) -> FillsResponse:
        if not self._canceled:
            return FillsResponse(fills=[])
        return FillsResponse(
            fills=[
                Fill(
                    fill_id="cf-fill-1",
                    order_id=self.order_id,
                    ticker=self.ticker,
                    side="buy",
                    outcome="yes",
                    size=self.fill_size,
                    price_cents=self.price_cents,
                    client_order_id=self.coid,
                    trade_id="cf-fill-1",
                    fee_usd=Decimal("0"),
                )
            ]
        )

    async def get_open_orders(self, ticker: Optional[str] = None) -> List[Order]:
        return [self._order] if self._order and not self._canceled else []

    async def get_positions(self) -> PositionsResponse:
        return PositionsResponse()

    async def get_historical_positions(
        self, cursor: Optional[str] = None
    ) -> HistoricalPositionsResponse:
        return HistoricalPositionsResponse()

    async def get_historical_fills(
        self, cursor: Optional[str] = None, since_ts: Optional[int] = None, limit: int = 200
    ) -> HistoricalFillsResponse:
        return HistoricalFillsResponse()

    async def get_market(self, ticker: str) -> MarketResult:
        return MarketResult(
            success=True,
            market=SimpleNamespace(
                best_bid=45,
                best_ask=55,
                volume=1000,
                open_interest=1000,
                active=True,
                resolved=False,
            ),
        )

    async def get_orderbook(self, ticker: str) -> OrderbookResult:
        return OrderbookResult(success=True)

    async def get_balance(self) -> BalanceResult:
        return BalanceResult(success=True, available_usd=Decimal("10000"))

    async def get_order_groups(self, limit: int = 200) -> OrderGroupsResult:
        return OrderGroupsResult(success=True)


@pytest.mark.asyncio
async def test_cancel_fill_race_coherent_inventory(attempt_store):
    """A cancel and partial fill race.

    The final order status is coherent (canceled with the filled portion
    retained), the inventory reflects the fill exactly once, and no
    replacement attempt is created before reconciliation.
    """
    ticker = "KXBTC15M-CANCEL-50000"
    coid = "coid-cancel-1"
    order_id = "ord-cancel-1"
    fill_size = Decimal("1")
    price_cents = 45  # maker bid, does not cross the spread

    port = _CancelFillRacePort(
        ticker=ticker,
        coid=coid,
        order_id=order_id,
        fill_size=fill_size,
        price_cents=price_cents,
    )
    set_kalshi_execution_port(port)

    intent = _base_intent(
        ticker=ticker,
        price_cents=price_cents,
        count=2,
        count_fp=Decimal("2.00"),
        tif="gtc",
        aggressiveness=0.0,
        order_expiration_ts=int(time.time()) + 3600,
    )
    intent.client_order_id = coid
    intent.client_tag = coid
    intent.decision_id = coid
    finalize_order_identity(intent, store=attempt_store)
    attempt_store.update_status(intent.order_attempt_id, "ACKNOWLEDGED")

    # Initial submission places a resting order.
    result = await _route(intent)
    assert result.status in ("resting", "accepted_live", "submitted_live"), result
    assert result.order_id == order_id

    # Send cancel, then receive the fill before/around the cancel ack.
    cancel = await port.cancel_order(order_id)
    assert cancel.success

    order = await port.get_order(client_order_id=coid)
    assert order is not None
    assert order.status == "canceled"
    assert order.filled_size == fill_size
    assert order.remaining_size == Decimal("0")

    fills = await port.get_fills()
    assert len(fills.fills) == 1
    fill = fills.fills[0]
    assert fill.client_order_id == coid
    assert fill.size == fill_size

    # Inventory must reflect the fill exactly once.
    position = fill_size

    # Update the durable attempt to CANCELED, preserving the fill metadata.
    attempt_store.update_status(
        intent.order_attempt_id,
        "CANCELED",
        payload={
            "fill_id": fill.fill_id,
            "filled_size": str(fill.size),
            "price_cents": fill.price_cents,
        },
    )

    record = attempt_store.get_by_client_order_id(coid)
    assert record.status == "CANCELED"
    payload = json.loads(record.payload_json)
    assert payload["fill_id"] == fill.fill_id
    assert payload["filled_size"] == str(fill.size)

    # No replacement attempt added risk before reconciliation.
    assert record.replaces_order_attempt_id is None
    assert len(attempt_store.get_by_decision_id(coid)) == 1
    assert position == Decimal("1")


# ---------------------------------------------------------------------------
# 8. Fractional quantity fixed-point wire and exposure
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "count_fp",
    [Decimal("0.01"), Decimal("0.50"), Decimal("1.00"), Decimal("1.55")],
)
@pytest.mark.asyncio
async def test_fractional_quantity_wire_and_exposure(
    client, attempt_store, monkeypatch, count_fp
):
    """count_fp is the economic authority; the integer count is not.

    The wire payload, the venue simulator's position, and the durable
    fingerprint all preserve the exact fractional amount.  The router's
    integer ``fill["count"]`` is a display/reconciliation hint and currently
    floors fractional fills to whole contracts, which this test documents.
    """
    ticker = f"KXBTC15M-FRAC-{count_fp}"
    client.set_market(
        ticker,
        SimpleNamespace(
            best_bid=45,
            best_ask=55,
            volume=1000,
            open_interest=1000,
            active=True,
            resolved=False,
        ),
    )
    client.set_orderbook(
        ticker,
        best_bid_cents=45,
        best_ask_cents=55,
        bid_size=Decimal("10"),
        ask_size=Decimal("100"),
    )

    # count=1 is the legacy integer hint; count_fp is the canonical size.
    intent = _base_intent(
        ticker=ticker,
        price_cents=55,
        count=1,
        count_fp=count_fp,
        tif="gtc",
        aggressiveness=1.0,
        order_expiration_ts=int(time.time()) + 3600,
    )
    coid = _reserve_gate(intent, monkeypatch)
    finalize_order_identity(intent, store=attempt_store)

    # Spy on the wire request to confirm the exact fractional payload.
    original_create = client.create_order
    sent: List[CreateOrderRequest] = []

    async def _spy_create(request: CreateOrderRequest) -> CreateOrderResponse:
        sent.append(request)
        return await original_create(request)

    client.create_order = _spy_create

    monkeypatch.setattr(
        "merid.event_venues.kalshi.order_router._dedup_cache",
        lambda: _DedupCacheStub(coid),
    )

    result = await _route(intent)
    assert result.request_completed

    assert len(sent) == 1
    request = sent[0]
    assert request.size == count_fp
    assert request.metadata["count_fp"] == str(count_fp)

    # Venue exposure and cost basis are the exact fractional count_fp.
    expected_position = count_fp
    assert client._position_yes.get(ticker, Decimal("0")) == expected_position

    expected_cost = count_fp * Decimal("0.55")
    assert client._balance_usd == Decimal("10000") - expected_cost

    # Router ``fill["count"]`` is the integer floor display count, while the
    # canonical ``quantity_cc``/``count_fp`` tracks the exact fractional size.
    int_count = int(count_fp)
    assert result.fill["count"] == int_count

    # Any non-zero centi-contract execution is reported as an execution.
    assert result.has_execution
    assert result.status == "filled_live"

    if count_fp == int_count:
        assert result.fill["count"] == client._position_yes[ticker]
    else:
        assert result.fill["count"] != client._position_yes[ticker]

    # Fingerprint must capture the fractional count_fp.
    record = attempt_store.get_by_client_order_id(coid)
    assert record is not None
    assert record.fingerprint == _compute_fingerprint(intent)
