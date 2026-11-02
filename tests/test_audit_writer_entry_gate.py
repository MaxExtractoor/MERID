"""Entry-gate wiring for the decision-audit writer readiness probe (F0, 2026-11-01).

Proves the production entry-permission path consumes ``writer_health()``:
an unhealthy audit writer blocks new entries, a healthy one does not, and a
probe failure fails closed.  Exits, cancellation, and reconciliation never
consult ``_compute_allow_new_entries`` — they are unaffected by construction.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from merid.event_venues.kalshi.market_catalog import CatalogMarket
from merid.event_venues.kalshi.market_state import KalshiMarketStateStore
from merid.event_venues.kalshi.order_intent_contract import (
    clear_entry_idempotency_registry,
)


class FakeClock:
    def __init__(self, start: float = 1_000_000.0):
        self.t = start

    def monotonic(self) -> float:
        return self.t

    def time(self) -> float:
        return self.t


@dataclass
class WindowFixture:
    asset: str
    open_utc: datetime
    close_utc: datetime
    strike: int

    @property
    def market_id(self) -> str:
        dt = self.close_utc
        return f"KX{self.asset}15M-{dt:%y%b%d%H%M}-{self.strike:02d}".upper()

    def catalog_market(self) -> CatalogMarket:
        return CatalogMarket(
            market=SimpleNamespace(
                market_id=self.market_id,
                open_time=self.open_utc,
                close_time=self.close_utc,
            ),
            asset=self.asset,
            strike_price=float(self.strike),
            floor_strike=float(self.strike),
            cap_strike=float(self.strike) + 1,
            health_status="ok",
        )

    def rest_market_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.market_id,
            "expiration_time": self.close_utc.isoformat(),
            "expected_expiration_time": self.close_utc.isoformat(),
            "latest_expiration_time": self.close_utc.isoformat(),
            "volume_24h": 1000,
            "open_interest": 500,
            "notional_value": 0,
            "underlying": self.asset,
            "strike_price": float(self.strike),
            "floor_strike": float(self.strike),
            "cap_strike": float(self.strike) + 1,
            "status": "open",
        }


def _snapshot(ticker: str, yes: list, no: list) -> dict[str, Any]:
    return {"type": "orderbook_snapshot", "ticker": ticker, "yes": yes, "no": no}


@pytest.fixture(autouse=True)
def _enable_entry_idempotency(monkeypatch):
    monkeypatch.setenv("MERID_ENTRY_IDEMPOTENCY_ENABLED", "1")


def _healthy_loop(monkeypatch):
    """Healthy-loop harness mirroring test_window_transition_boundary."""
    from merid.loop_15m import Kalshi15mLoop

    fake_clock = FakeClock(start=1_000_000.0)
    monkeypatch.setattr(
        "merid.event_venues.kalshi.market_state.time.monotonic",
        fake_clock.monotonic,
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.market_state.time.time", fake_clock.time
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.kalshi_config.KALSHI_READY", True
    )
    monkeypatch.setattr("merid.loop_15m.markets_expected_now", lambda: True)
    # Gate under test is audit-writer health; pin the independent runtime
    # gates open so the baseline can reach it.
    monkeypatch.setattr("merid.loop_15m.can_submit_live_entry", lambda: True)
    monkeypatch.setattr("merid.loop_15m.is_observe_only", lambda: False)
    monkeypatch.setattr(
        "merid.event_venues.kalshi.canonical_portfolio.get_canonical_portfolio_store",
        lambda: SimpleNamespace(current=lambda: SimpleNamespace(
            is_authoritative=True, age_ms=0,
            reconciliation_status="MATCHED", reconciliation_reason="MATCHED",
        )),
    )

    loop = Kalshi15mLoop(
        agent_grid=MagicMock(),
        bankroll_service=MagicMock(),
        risk_config=MagicMock(),
    )
    store = KalshiMarketStateStore()
    loop.market_state_store = store
    loop._risk_envelope = None
    return loop, store


def _apply_active_window(store, monkeypatch, w: WindowFixture) -> str:
    store.apply_rest_market(w.rest_market_dict())
    store.apply_orderbook_message(
        _snapshot(w.market_id, [[0.55, 5]], [[0.45, 5]]), via="rest_bootstrap"
    )
    s = store.get(w.market_id)
    if s is not None:
        s.snapshot_complete = True

    def _current_for_asset(asset: str):
        return w.catalog_market() if asset == "BTC" else None

    monkeypatch.setattr(
        "merid.event_venues.kalshi.market_catalog.get_market_catalog",
        lambda: MagicMock(get_current_15m_market=_current_for_asset),
    )
    return w.market_id


def _writer_stub(unhealthy: bool, **overrides):
    stub = MagicMock()
    stub.writer_health.return_value = {
        "writer_started": True,
        "writer_alive": True,
        "queue_depth": 0,
        "oldest_queued_age_s": 0.0,
        "inflight_required": False,
        "inflight_age_s": None,
        "failed_required_writes": 0,
        "unhealthy": unhealthy,
        **overrides,
    }
    return stub


def test_audit_writer_health_ok_contract(monkeypatch):
    from merid import loop_15m

    monkeypatch.setattr(
        "merid.execution.decision_audit_ledger.get_decision_audit_ledger",
        lambda: _writer_stub(unhealthy=False),
    )
    assert loop_15m._audit_writer_health_ok() == (True, None)

    monkeypatch.setattr(
        "merid.execution.decision_audit_ledger.get_decision_audit_ledger",
        lambda: _writer_stub(unhealthy=True, queue_depth=9000,
                             oldest_queued_age_s=3600.0),
    )
    assert loop_15m._audit_writer_health_ok() == (False, "audit_writer_unhealthy")

    def _boom():
        raise RuntimeError("probe failed")

    monkeypatch.setattr(
        "merid.execution.decision_audit_ledger.get_decision_audit_ledger", _boom
    )
    ok, reason = loop_15m._audit_writer_health_ok()
    assert ok is False and reason == "audit_writer_health_error"


def test_unhealthy_audit_writer_blocks_entries(monkeypatch):
    loop, store = _healthy_loop(monkeypatch)
    clear_entry_idempotency_registry()
    w = WindowFixture(
        "BTC",
        datetime(2026, 8, 24, 23, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 24, 23, 15, 0, tzinfo=timezone.utc),
        15,
    )
    _apply_active_window(store, monkeypatch, w)

    monkeypatch.setattr(
        "merid.execution.decision_audit_ledger.get_decision_audit_ledger",
        lambda: _writer_stub(unhealthy=False),
    )
    assert loop._compute_allow_new_entries(cycle_bankroll=1000.0) is True

    monkeypatch.setattr(
        "merid.execution.decision_audit_ledger.get_decision_audit_ledger",
        lambda: _writer_stub(unhealthy=True, queue_depth=9000,
                             oldest_queued_age_s=3600.0),
    )
    clear_entry_idempotency_registry()
    assert loop._compute_allow_new_entries(cycle_bankroll=1000.0) is False
    assert loop._entries_block_reason == "audit_writer_unhealthy"


@pytest.mark.parametrize("unavailable", ["missing", "error"])
def test_unavailable_canonical_portfolio_blocks_entries(monkeypatch, unavailable):
    loop, store = _healthy_loop(monkeypatch)
    clear_entry_idempotency_registry()
    w = WindowFixture(
        "BTC",
        datetime(2026, 8, 24, 23, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 24, 23, 15, 0, tzinfo=timezone.utc),
        15,
    )
    _apply_active_window(store, monkeypatch, w)

    def current():
        if unavailable == "error":
            raise OSError("portfolio unavailable")
        return None

    monkeypatch.setattr(
        "merid.event_venues.kalshi.canonical_portfolio.get_canonical_portfolio_store",
        lambda: SimpleNamespace(current=current),
    )
    assert loop._compute_allow_new_entries(cycle_bankroll=1000.0) is False
    assert loop._entries_block_reason == "portfolio_unavailable"


@pytest.mark.parametrize("unavailable", ["missing", "error"])
def test_unavailable_ticker_cache_halt_check_blocks_entries(monkeypatch, unavailable):
    loop, store = _healthy_loop(monkeypatch)
    clear_entry_idempotency_registry()
    w = WindowFixture(
        "BTC",
        datetime(2026, 8, 24, 23, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 24, 23, 15, 0, tzinfo=timezone.utc),
        15,
    )
    _apply_active_window(store, monkeypatch, w)
    monkeypatch.setattr(
        "merid.execution.decision_audit_ledger.get_decision_audit_ledger",
        lambda: _writer_stub(unhealthy=False),
    )

    def unavailable_cache():
        if unavailable == "error":
            raise OSError("cache unavailable")
        return None

    monkeypatch.setattr(
        "merid.event_venues.kalshi.position_cache.get_position_cache",
        unavailable_cache,
    )
    assert loop._compute_allow_new_entries(cycle_bankroll=1000.0) is False
    assert loop._entries_block_reason == "reconciliation_halt_latch"
