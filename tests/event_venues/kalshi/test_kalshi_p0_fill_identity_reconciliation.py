"""P0 ``exchange_reconciliation`` seven-case regression suite (2026-10-31 audit).

These tests drive the real ``run_p0_preflight_checks`` exchange-reconciliation
check — the fill-identity comparison between REST ``/portfolio/fills`` and the
durable ``KalshiFillsLedger`` — against a real ledger bound to a temp DB.

Cases:
1. Normal fill (WS-internal + REST confirm) reconciles and is idempotent.
2. Partial fills on one order record only executed quantities.
3. A settlement-only ledger row produces no divergence.
4. A fill followed by its settlement row preserves correct position state.
5. Duplicate settlement ingestion is idempotent (one payout leg).
6. Restart/replay reloads durable rows once — no duplicated effects.
7. A genuine unexplained internal execution still fails the check (halt
   safeguard preserved).

The settlement exclusion under test is ``p0.py``'s triple predicate:
``fill_source != "settlement"``, ``fill_id`` not starting with ``settlement:``,
``ingestion_source != "settlement_rest"``.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

import pytest

from merid.event_venues.kalshi.fills_ledger import KalshiFill, KalshiFillsLedger
from merid.event_venues.kalshi.types import BalanceState
from merid.preflight.p0 import run_p0_preflight_checks

# Fill ids and tickers must look production-real: ``_is_test_fixture_fill``
# (exact ids f1..f5, ``fill-*``/``test_*`` prefixes) and ``_is_test_ticker``
# (``TEST`` in the symbol) are deliberately skipped by HTTP ingest.
TICKER = "KXBTC15M-26031-1800"
SETTLE_ROW_ID = "settlement:%s:yes" % TICKER


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeClient:
    """Client with just the surface ``run_p0_preflight_checks`` uses."""

    def __init__(
        self,
        fills: Optional[List[Dict[str, Any]]] = None,
        positions: Optional[List[Any]] = None,
        open_orders: Optional[List[Any]] = None,
    ) -> None:
        self._fills = list(fills or [])
        self._positions = list(positions or [])
        self._open_orders = list(open_orders or [])

    async def get_balance(self) -> Dict[str, Any]:
        return {"USD": Decimal("100.00")}

    async def get_positions(self) -> List[Any]:
        return list(self._positions)

    async def get_open_orders(self) -> List[Any]:
        return list(self._open_orders)

    async def get_fills(self, limit: int = 100, since_ts: Optional[int] = None):
        return list(self._fills)

    async def cancel_all_open_orders(self, dry_run: bool = False) -> Dict[str, Any]:
        return {"dry_run": dry_run, "would_cancel": [], "count": 0}


class _FakeBankroll:
    async def get_summary(self, caller_module: str = "") -> Any:
        return SimpleNamespace(state=BalanceState.FRESH, equity_usd=Decimal("100.0"))


class _FakeCatalog:
    def get_all_markets(self) -> List[Any]:
        return [SimpleNamespace(ticker=TICKER)]


class _FakePositionCache:
    """Stores exactly what ``sync_from_rest`` hands it, like the real cache's
    authoritative-sync contract."""

    def __init__(self) -> None:
        self._positions: Dict[str, Dict[str, Any]] = {}

    async def sync_from_rest(
        self,
        positions: List[Dict[str, Any]],
        rest_timestamp: float = 0.0,
        force: bool = False,
        open_orders: Optional[List[Dict[str, Any]]] = None,
        cleanup_stale: bool = False,
    ) -> None:
        self._positions = {p["market_id"]: p for p in positions}

    def get_all_positions(self, validate_freshness: bool = True) -> Dict[str, Any]:
        return dict(self._positions)


def _rti_adapter(asset: str) -> Any:
    return SimpleNamespace(
        execution_eligible=True,
        observed_ts_ms=int(time.time() * 1000),
    )


def _rest_fill(
    fill_id: str,
    order_id: str,
    *,
    ticker: str = TICKER,
    side: str = "yes",
    action: str = "buy",
    count_fp: str = "2.00",
    yes_price_dollars: str = "0.9400",
    created_time: Optional[datetime] = None,
) -> Dict[str, Any]:
    return {
        "fill_id": fill_id,
        "trade_id": fill_id,
        "order_id": order_id,
        "ticker": ticker,
        "side": side,
        "action": action,
        "count_fp": count_fp,
        "yes_price_dollars": yes_price_dollars,
        "no_price_dollars": "0.0600",
        "created_time": (created_time or datetime.now(timezone.utc)).isoformat(),
    }


def _internal_fill(
    fill_id: str,
    order_id: str,
    *,
    ticker: str = TICKER,
    side: str = "yes",
    action: str = "buy",
    count_fp: Decimal = Decimal("2"),
    leg_price_cents: int = 94,
    created_time: Optional[datetime] = None,
) -> KalshiFill:
    """A venue-evidenced internal fill as the WS path would record it."""
    signed = int(count_fp * 100)
    return KalshiFill(
        fill_id=fill_id,
        trade_id=fill_id,
        order_id=order_id,
        market_ticker=ticker,
        side=side,
        action=action,
        count_fp=count_fp,
        quantity_cc=signed,
        yes_price_dollars=Decimal("0.94"),
        canonical_position_side=side,
        canonical_position_action=action,
        canonical_leg_price_cents=leg_price_cents,
        canonical_yes_delta_cc=signed if action == "buy" and side == "yes" else -signed,
        canonicalization_state="TRUSTED_LIVE_V1",
        created_time=created_time or datetime.now(timezone.utc),
        ingestion_source="websocket",
        fill_source="alpha",
        is_live=True,
    )


def _run_check(results: List[Tuple[bool, str]], label: str) -> Tuple[bool, str]:
    for ok, msg in results:
        if label in msg:
            return ok, msg
    raise AssertionError(f"check {label!r} not emitted: {results}")


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


@pytest.fixture
def harness(tmp_path, monkeypatch):
    """Real KalshiFillsLedger on a temp DB + fakes for the rest of preflight."""

    monkeypatch.setattr(
        "merid.preflight.p0._check_uncertain_submissions",
        lambda: (True, "[PASS] uncertain_submission_recovery: isolated test"),
    )
    monkeypatch.setenv("MERID_ENV", "testing")
    monkeypatch.setenv("MERID_FILLS_DB_PATH", str(tmp_path / "fills.db"))
    monkeypatch.setenv(
        "MERID_FILLS_INTENT_INDEX_PATH", str(tmp_path / "intent_idx.json")
    )
    monkeypatch.setenv("MERID_CB_HTTP_WATERMARK_PATH", str(tmp_path / "cb.json"))

    ledger = KalshiFillsLedger()
    # Keep ingestion hermetic: an unmatched fill is still stored in the
    # ledger, but the halt/exchange-lookup path (which would call get_order
    # on the real venue and touch circuit-breaker state) is silenced.
    monkeypatch.setattr(ledger, "_maybe_halt_on_unmatched_fill", _no_halt)
    cache = _FakePositionCache()

    # The preflight imports these singletons inside the function body; patch
    # the module attributes so the call sites resolve to the test instances.
    monkeypatch.setattr(
        "merid.event_venues.kalshi.fills_ledger.get_fills_ledger",
        lambda *a, **k: ledger,
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.position_cache.get_position_cache",
        lambda: cache,
    )

    async def _funded(client, catalog):
        return SimpleNamespace(
            funded=True,
            summary=lambda: "stub funded",
            shard_balances={2: 100.0},
        )

    monkeypatch.setattr(
        "merid.event_venues.kalshi.shard_funding.ensure_trading_shard_funded",
        _funded,
    )

    async def run(rest_fills=None, positions=None, open_orders=None, use_ledger=None,
                  client_override=None):
        client = client_override or _FakeClient(
            fills=rest_fills, positions=positions, open_orders=open_orders,
        )
        if use_ledger is not None:
            monkeypatch.setattr(
                "merid.event_venues.kalshi.fills_ledger.get_fills_ledger",
                lambda *a, **k: use_ledger,
            )
        results = await run_p0_preflight_checks(
            client,
            _FakeBankroll(),
            _FakeCatalog(),
            rti_adapter=_rti_adapter,
            required_assets=["BTC"],
            max_wait_rti=1.0,
        )
        return _run_check(results, "exchange_reconciliation")

    return SimpleNamespace(ledger=ledger, cache=cache, run=run)


async def _no_halt(*args: Any, **kwargs: Any) -> None:
    """Silence the unmatched-fill halt/exchange-lookup path in tests; the fill
    is still stored and still participates in identity reconciliation."""
    return None


# ---------------------------------------------------------------------------
# 1. Normal fill
# ---------------------------------------------------------------------------


async def _seed_schema(ledger: KalshiFillsLedger) -> None:
    """Durable writes (settlement rows, reloads) need the SQLite schema;
    ``ensure_loaded`` initializes it."""
    await ledger.ensure_loaded()


@pytest.mark.asyncio
async def test_case1_normal_fill_reconciles_and_rerun_is_idempotent(harness) -> None:
    harness.ledger._fills["kf_a001"] = _internal_fill(
        "kf_a001", "ord1", count_fp=Decimal("2")
    )
    rest = [_rest_fill("kf_a001", "ord1")]

    ok, detail = await harness.run(rest_fills=rest)
    assert ok, detail
    assert "missing_external=0" in detail
    assert "extra_internal=0" in detail
    assert "problematic_internal=[]" in detail

    # Quantity accounting: the recorded fill carries the full executed count.
    fill = harness.ledger.get_fill_by_id("kf_a001")
    assert fill is not None
    assert fill.quantity_cc == 200
    assert fill.count_fp == Decimal("2")
    # REST re-delivery confirmed the same row rather than duplicating it.
    assert fill.confirmed_by_rest
    assert len([f for f in harness.ledger.get_fills() if f.fill_id == "kf_a001"]) == 1

    # Re-running reconciliation on the same inputs must not drift.
    ok2, detail2 = await harness.run(rest_fills=rest)
    assert ok2, detail2
    assert len(harness.ledger.get_fills()) == 1


# ---------------------------------------------------------------------------
# 2. Partial fills on one order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case2_partial_fills_record_executed_quantities(harness) -> None:
    # Two fractional executions on one order: 1 contract then 1 contract.
    harness.ledger._fills["kf_p101"] = _internal_fill(
        "kf_p101", "ordP", count_fp=Decimal("1")
    )
    harness.ledger._fills["kf_p102"] = _internal_fill(
        "kf_p102", "ordP", count_fp=Decimal("1")
    )
    rest = [
        _rest_fill("kf_p101", "ordP", count_fp="1.00"),
        _rest_fill("kf_p102", "ordP", count_fp="1.00"),
    ]

    ok, detail = await harness.run(rest_fills=rest)
    assert ok, detail
    assert "problematic_internal=[]" in detail

    # Each leg recorded only its executed portion; summed exposure is the
    # filled 2 contracts, not the requested amount.
    total_cc = sum(
        f.quantity_cc for f in harness.ledger.get_fills() if f.order_id == "ordP"
    )
    assert total_cc == 200
    assert harness.ledger.get_fill_by_id("kf_p101").count_fp == Decimal("1")
    assert harness.ledger.get_fill_by_id("kf_p102").count_fp == Decimal("1")


# ---------------------------------------------------------------------------
# 3. Settlement-only row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case3_settlement_only_row_creates_no_divergence(harness) -> None:
    await _seed_schema(harness.ledger)
    written = harness.ledger.record_settlement_proceeds(TICKER, "yes", yes_count=2.0)
    assert written == 1
    assert SETTLE_ROW_ID in harness.ledger._fills

    ok, detail = await harness.run(rest_fills=[])
    assert ok, detail
    # The pseudo-fill is excluded before the identity comparison entirely.
    assert "extra_internal=0" in detail
    assert "problematic_internal=[]" in detail

    row = harness.ledger.get_fill_by_id(SETTLE_ROW_ID)
    assert row.fill_source == "settlement"
    assert row.ingestion_source == "settlement_rest"
    assert row.fill_id.startswith("settlement:")


# ---------------------------------------------------------------------------
# 4. Fill followed by settlement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case4_fill_then_settlement_preserves_state(harness) -> None:
    await _seed_schema(harness.ledger)
    harness.ledger._fills["kf_a004"] = _internal_fill(
        "kf_a004", "ord4", count_fp=Decimal("2")
    )
    written = harness.ledger.record_settlement_proceeds(TICKER, "yes", yes_count=2.0)
    assert written == 1

    ok, detail = await harness.run(rest_fills=[_rest_fill("kf_a004", "ord4")])
    assert ok, detail
    assert "problematic_internal=[]" in detail

    # Accounting: entry bought +200 signed-YES cc; the settlement payout leg
    # books the equal-opposite delta so position state nets to flat.
    entry = harness.ledger.get_fill_by_id("kf_a004")
    settle = harness.ledger.get_fill_by_id(SETTLE_ROW_ID)
    assert entry.canonical_yes_delta_cc == 200
    assert settle.canonical_yes_delta_cc == -200
    assert entry.canonical_yes_delta_cc + settle.canonical_yes_delta_cc == 0
    # Exactly the two expected rows exist.
    assert len(harness.ledger.get_fills()) == 2


# ---------------------------------------------------------------------------
# 5. Duplicate settlement ingestion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case5_duplicate_settlement_ingestion_is_idempotent(harness) -> None:
    await _seed_schema(harness.ledger)
    w1 = harness.ledger.record_settlement_proceeds(TICKER, "yes", yes_count=2.0)
    w2 = harness.ledger.record_settlement_proceeds(TICKER, "yes", yes_count=2.0)
    assert w1 == 1
    assert w2 == 0  # INSERT OR IGNORE + in-memory guard: no second payout leg

    settlement_rows = [
        f for f in harness.ledger.get_fills() if f.fill_id.startswith("settlement:")
    ]
    assert len(settlement_rows) == 1
    # Payout booked exactly once.
    leg = settlement_rows[0]
    assert leg.proceeds_dollars == Decimal("2.0")

    ok, detail = await harness.run(rest_fills=[])
    assert ok, detail
    assert "problematic_internal=[]" in detail


# ---------------------------------------------------------------------------
# 6. Restart / replay
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case6_restart_replay_no_duplicate_effects(harness, monkeypatch) -> None:
    # Era A: one durable settlement row exists when the process stops.
    await _seed_schema(harness.ledger)
    w = harness.ledger.record_settlement_proceeds(TICKER, "yes", yes_count=2.0)
    assert w == 1

    # "Restart": a fresh ledger object over the same durable store.
    ledger_b = KalshiFillsLedger()
    monkeypatch.setattr(ledger_b, "_maybe_halt_on_unmatched_fill", _no_halt)
    loaded = await ledger_b.load_from_db()
    assert loaded == 1
    assert sorted(ledger_b._fills) == [SETTLE_ROW_ID]

    # Poller re-delivery post-restart must not book the payout twice.
    w_again = ledger_b.record_settlement_proceeds(TICKER, "yes", yes_count=2.0)
    assert w_again == 0
    settlement_rows = [
        f for f in ledger_b.get_fills() if f.fill_id.startswith("settlement:")
    ]
    assert len(settlement_rows) == 1

    # The exchange re-reports the era-A trade fill; ingesting it through the
    # real path adds exactly one row that reconciles by identity.
    ok, detail = await harness.run(
        rest_fills=[_rest_fill("kf_a004", "ord4")], use_ledger=ledger_b
    )
    assert ok, detail
    assert "missing_external=0" in detail
    assert "problematic_internal=[]" in detail
    assert len([f for f in ledger_b.get_fills() if f.fill_id == "kf_a004"]) == 1
    assert len(ledger_b.get_fills()) == 2


# ---------------------------------------------------------------------------
# 7. Genuine unexplained extra execution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case7_unexplained_extra_execution_fails_closed(harness) -> None:
    # An internal execution the exchange never reported: recent timestamp,
    # not a live_router_ provisional, not a settlement row.  This is exactly
    # the divergence class that must halt startup.
    harness.ledger._fills["rogue_exec_1"] = _internal_fill(
        "rogue_exec_1",
        "ord_rogue",
        count_fp=Decimal("6"),
        created_time=datetime.now(timezone.utc),
    )

    ok, detail = await harness.run(rest_fills=[])
    assert not ok, "unexplained internal execution passed reconciliation"
    assert "problematic_internal=['rogue_exec_1']" in detail

    # Sanity: the matched fill itself was fine — the failure is attributable
    # to the rogue row, not collateral noise.
    assert "missing_external=0" in detail
    assert "extra_internal=1" in detail


@pytest.mark.asyncio
async def test_failed_fills_query_cannot_pass_as_flat(harness) -> None:
    from merid.resilience.result import OperationResult

    class FailingClient(_FakeClient):
        async def get_fills(self, limit=100, since_ts=None):
            return OperationResult.fail(RuntimeError("fills unavailable"))

    ok, detail = await harness.run(client_override=FailingClient())
    assert not ok
    assert "fills incomplete" in detail


@pytest.mark.asyncio
async def test_failed_positions_query_cannot_pass_as_flat(harness) -> None:
    from merid.resilience.result import OperationResult

    class FailingClient(_FakeClient):
        async def get_positions_result(self):
            return OperationResult.fail(RuntimeError("positions unavailable"))

    ok, detail = await harness.run(client_override=FailingClient())
    assert not ok
    assert "positions incomplete" in detail
