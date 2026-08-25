"""
Tests for entry-provenance snapshot store and REST provenance recovery.

These tests verify that:
- Entry provenance snapshots are durable and keyed by client_order_id.
- Snapshots can be linked to fills via order_id and fill_id.
- REST positions resolve provenance by client_order_id, order_id, or fill_id.
- Missing policy/fills produce explicit unresolved states.
"""

import os
import json
import pytest
import tempfile
import shutil
from pathlib import Path
from dataclasses import dataclass


ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]


@pytest.fixture
def provenance_store(tmp_path):
    from merid.position_management.entry_provenance import (
        EntryProvenanceStore,
        EntryProvenanceSnapshot,
    )

    # Reset singleton so tests get an isolated store.
    EntryProvenanceStore._instance = None
    store = EntryProvenanceStore(path=tmp_path / "entry_provenance_snapshots.json")
    store._snapshots.clear()
    store._by_ticker.clear()
    store._by_order_id.clear()
    store._by_fill_id.clear()
    return store


@dataclass
class FakeFill:
    client_order_id: str
    order_id: str
    fill_id: str
    quantity_cc: int
    canonical_position_side: str
    canonical_leg_price_cents: int = 50


@pytest.mark.parametrize("asset", ASSETS)
def test_store_registers_and_resolves_snapshot(asset, provenance_store):
    from merid.position_management.entry_provenance import (
        EntryProvenanceSnapshot,
    )

    coid = f"order-{asset}-001"
    snapshot = EntryProvenanceSnapshot(
        snapshot_id=f"eps_{asset}_001",
        client_order_id=coid,
        ticker=f"KX{asset}15M-TEST",
        asset=asset,
        outcome_side="yes",
        tp_policy_id="tp_policy",
        sl_policy_id="sl_policy",
        tp_price_cents=75,
        sl_price_cents=25,
        edge_decay_model="kalshi_crypto_15m",
    )
    provenance_store.register(snapshot)

    resolved = provenance_store.get(coid)
    assert resolved is not None
    assert resolved.tp_price_cents == 75
    assert resolved.sl_price_cents == 25
    assert resolved.asset == asset


@pytest.mark.parametrize("asset", ASSETS)
def test_store_resolves_by_order_id_and_fill_id(asset, provenance_store):
    from merid.position_management.entry_provenance import (
        EntryProvenanceSnapshot,
    )

    coid = f"order-{asset}-002"
    snapshot = EntryProvenanceSnapshot(
        snapshot_id=f"eps_{asset}_002",
        client_order_id=coid,
        ticker=f"KX{asset}15M-TEST",
        asset=asset,
        outcome_side="yes",
    )
    provenance_store.register(snapshot)

    fill = FakeFill(
        client_order_id=coid,
        order_id=f"kalshi-order-{asset}-002",
        fill_id=f"fill-{asset}-002",
        quantity_cc=100,
        canonical_position_side="yes",
    )
    provenance_store.register_fill_linkage(
        client_order_id=coid,
        order_id=fill.order_id,
        fill_id=fill.fill_id,
    )

    assert provenance_store.get_by_order_id(fill.order_id) is not None
    assert provenance_store.get_by_fill_id(fill.fill_id) is not None


@pytest.mark.parametrize("asset", ASSETS)
def test_resolve_provenance_requires_matching_fills(asset, provenance_store):
    from merid.position_management.entry_provenance import (
        EntryProvenanceSnapshot,
        ProvenanceState,
    )

    coid = f"order-{asset}-003"
    snapshot = EntryProvenanceSnapshot(
        snapshot_id=f"eps_{asset}_003",
        client_order_id=coid,
        ticker=f"KX{asset}15M-TEST",
        asset=asset,
        outcome_side="yes",
        tp_policy_id="tp_policy",
        sl_policy_id="sl_policy",
        tp_price_cents=75,
        sl_price_cents=25,
        edge_decay_model="kalshi_crypto_15m",
        market_close_time=__import__('datetime').datetime.utcnow(),
        entry_fill_time=__import__('datetime').datetime.utcnow(),
    )
    provenance_store.register(snapshot)

    fill = FakeFill(
        client_order_id=coid,
        order_id=f"kalshi-order-{asset}-003",
        fill_id=f"fill-{asset}-003",
        quantity_cc=100,
        canonical_position_side="yes",
        canonical_leg_price_cents=50,
    )

    resolution = provenance_store.resolve_provenance(
        ticker=f"KX{asset}15M-TEST",
        position_qty_cc=100,
        position_side="yes",
        fills=[fill],
        client_order_id=coid,
    )
    assert resolution.complete
    assert resolution.state == ProvenanceState.PROVENANCE_RECOVERED
    assert resolution.tp_resolved
    assert resolution.sl_resolved


@pytest.mark.parametrize("asset", ASSETS)
def test_resolve_provenance_detects_side_mismatch(asset, provenance_store):
    from merid.position_management.entry_provenance import ProvenanceState

    fill = FakeFill(
        client_order_id=f"order-{asset}-004",
        order_id=f"kalshi-order-{asset}-004",
        fill_id=f"fill-{asset}-004",
        quantity_cc=100,
        canonical_position_side="no",
    )

    resolution = provenance_store.resolve_provenance(
        ticker=f"KX{asset}15M-TEST",
        position_qty_cc=100,
        position_side="yes",
        fills=[fill],
        client_order_id=f"order-{asset}-004",
    )
    assert resolution.state == ProvenanceState.PROVENANCE_MISSING_POLICY


@pytest.mark.parametrize("asset", ASSETS)
def test_unknown_provenance_does_not_invent_tp_sl(asset, provenance_store):
    """An unresolved position must not invent TP/SL/edge-decay metadata."""
    from merid.position_management.entry_provenance import ProvenanceState

    resolution = provenance_store.resolve_provenance(
        ticker=f"KX{asset}15M-TEST",
        position_qty_cc=100,
        position_side="yes",
        fills=[],
    )
    assert not resolution.complete
    assert resolution.state == ProvenanceState.PROVENANCE_MISSING_FILLS
    assert resolution.snapshot is None
