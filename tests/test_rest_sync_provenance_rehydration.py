"""
Tests for REST-sync provenance rehydration and quarantine recovery.

These verify that a position discovered via REST sync can recover its original
exit plan from the durable EntryProvenanceStore and that the quarantine is
lifted once provenance is recovered.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from merid.position_management.entry_provenance import (
    EntryProvenanceStore,
    EntryProvenanceSnapshot,
    ProvenanceState,
)
from merid.position_management.exit_policy import (
    has_trusted_exit_provenance,
    is_position_quarantined,
)
from merid.position_management.position import Position, PositionSide, RiskParamsState


@pytest.fixture
def store(tmp_path):
    """Isolated entry-provenance store."""
    EntryProvenanceStore._instance = None
    s = EntryProvenanceStore(path=tmp_path / "entry_provenance_snapshots.json")
    s._snapshots.clear()
    s._by_ticker.clear()
    s._by_order_id.clear()
    s._by_fill_id.clear()
    return s


def _make_snapshot(
    ticker="KXETH15M-TEST",
    side="no",
    client_order_id="coid-eth-001",
    tp=60,
    sl=45,
    book_quality="UNKNOWN",
):
    return EntryProvenanceSnapshot(
        snapshot_id="eps_eth_001",
        client_order_id=client_order_id,
        ticker=ticker,
        asset="ETH",
        outcome_side=side,
        order_intent_id=client_order_id,
        exit_policy_id="crypto_15m_v2",
        tp_policy_id="tp_v2",
        sl_policy_id="sl_v2",
        tp_price_cents=tp,
        sl_price_cents=sl,
        stop_loss_enabled=sl is not None,
        entry_price_cents=50,
        entry_fill_price_cents=50,
        entry_fill_timestamp=datetime.now(timezone.utc),
        entry_executable_bid_cents=49,
        entry_executable_ask_cents=51,
        entry_book_capture_quality=book_quality,
        entry_book_timestamp=datetime.now(timezone.utc),
        entry_edge=0.05,
        entry_fair_value=0.60,
        entry_market_value=0.55,
        created_at=datetime.now(timezone.utc).timestamp(),
    )


def test_rehydrate_for_position_by_ticker_side(store):
    """A REST position with no client_order_id can be rehydrated by ticker+side."""
    snap = _make_snapshot(book_quality="AT_FILL")
    store.register(snap)

    resolution = store.rehydrate_for_position(
        ticker="KXETH15M-TEST",
        position_side="no",
        client_order_id=None,
        fill_id=None,
        order_id=None,
        position_qty_cc=100,
        fills=None,
    )

    assert resolution.complete
    assert resolution.state == ProvenanceState.PROVENANCE_RECOVERED
    assert resolution.snapshot is not None
    assert resolution.snapshot.tp_price_cents == 60
    assert resolution.snapshot.sl_price_cents == 45


def test_rehydrate_for_position_by_client_order_id(store):
    """A REST position carrying a client_order_id links directly to the snapshot."""
    snap = _make_snapshot(client_order_id="coid-direct")
    store.register(snap)

    resolution = store.rehydrate_for_position(
        ticker="KXETH15M-TEST",
        position_side="no",
        client_order_id="coid-direct",
    )

    assert resolution.complete
    assert resolution.snapshot.client_order_id == "coid-direct"


def test_rehydrate_for_position_unknown_is_unresolved(store):
    """A REST position with no matching snapshot remains unresolved."""
    resolution = store.rehydrate_for_position(
        ticker="KXXRP15M-TEST",
        position_side="yes",
    )

    assert not resolution.complete
    assert resolution.state == ProvenanceState.PROVENANCE_MISSING_POLICY
    assert resolution.snapshot is None


def test_rehydrate_for_position_incomplete_without_cost_basis(store):
    """A snapshot with neither fill price nor entry price cannot be marked complete."""
    snap = _make_snapshot()
    snap.entry_fill_price_cents = None
    snap.entry_price_cents = None
    store.register(snap)

    resolution = store.rehydrate_for_position(
        ticker="KXETH15M-TEST",
        position_side="no",
        client_order_id=snap.client_order_id,
    )

    assert not resolution.complete
    assert resolution.state == ProvenanceState.PROVENANCE_LEGACY_UNRESOLVED


def test_quarantine_lifted_for_recovered_rest_sync_position(store):
    """A rest_sync position with recovered provenance is no longer quarantined."""
    snap = _make_snapshot(book_quality="AT_FILL")
    store.register(snap)

    resolution = store.rehydrate_for_position(
        ticker="KXETH15M-TEST",
        position_side="no",
        client_order_id=snap.client_order_id,
    )

    position = Position(
        position_id="KXETH15M-TEST",
        market_id="KXETH15M-TEST",
        series_ticker="KXETH15M",
        side=PositionSide.NO,
        size=1,
        avg_entry_price_cents=50,
        take_profit_price_cents=resolution.snapshot.tp_price_cents,
        stop_loss_enabled=resolution.snapshot.stop_loss_enabled,
        stop_loss_price_cents=resolution.snapshot.sl_price_cents,
        risk_params_state="original_persisted",
        risk_params_schema_version=2,
        client_order_id=snap.client_order_id,
        fill_source="rest_sync",
        entry_fill_price_cents=resolution.snapshot.entry_fill_price_cents,
        entry_executable_bid_cents=49,
        entry_executable_ask_cents=51,
        entry_book_capture_quality="AT_FILL",
        entry_model_probability=0.60,
        entry_market_probability=0.55,
        entry_edge=0.05,
        entry_signal_id=snap.client_order_id,
        provenance_state="PROVENANCE_RECOVERED",
        entry_provenance_snapshot_id=snap.snapshot_id,
    )

    assert has_trusted_exit_provenance(position)
    assert not is_position_quarantined(position)
    assert position.risk_params_state == RiskParamsState.ORIGINAL_PERSISTED


def test_quarantine_kept_for_untrusted_rest_sync_position(store):
    """A rest_sync position without recovered provenance stays quarantined."""
    position = Position(
        position_id="KXETH15M-TEST",
        market_id="KXETH15M-TEST",
        series_ticker="KXETH15M",
        side=PositionSide.NO,
        size=1,
        avg_entry_price_cents=50,
        take_profit_price_cents=60,
        stop_loss_enabled=False,
        stop_loss_price_cents=None,
        risk_params_state="unknown",
        risk_params_schema_version=1,
        client_order_id=None,
        fill_source="rest_sync",
    )

    assert not has_trusted_exit_provenance(position)
    assert is_position_quarantined(position)


def test_recovered_position_without_at_fill_book_is_not_quarantined(store):
    """A recovered rest_sync position without an AT_FILL book is not quarantined,
    but still cannot act on a model exit because _can_act_on_model_exit checks
    the AT_FILL book separately."""
    snap = _make_snapshot(book_quality="UNKNOWN")
    store.register(snap)

    resolution = store.rehydrate_for_position(
        ticker="KXETH15M-TEST",
        position_side="no",
        client_order_id=snap.client_order_id,
    )

    position = Position(
        position_id="KXETH15M-TEST",
        market_id="KXETH15M-TEST",
        series_ticker="KXETH15M",
        side=PositionSide.NO,
        size=1,
        avg_entry_price_cents=50,
        take_profit_price_cents=resolution.snapshot.tp_price_cents,
        stop_loss_enabled=False,
        stop_loss_price_cents=None,
        risk_params_state="original_persisted",
        risk_params_schema_version=2,
        client_order_id=snap.client_order_id,
        fill_source="rest_sync",
        entry_fill_price_cents=resolution.snapshot.entry_fill_price_cents,
        entry_book_capture_quality="UNKNOWN",
        entry_model_probability=0.60,
        entry_market_probability=0.55,
        entry_edge=0.05,
        provenance_state="PROVENANCE_RECOVERED",
        entry_provenance_snapshot_id=snap.snapshot_id,
    )

    assert not is_position_quarantined(position)
