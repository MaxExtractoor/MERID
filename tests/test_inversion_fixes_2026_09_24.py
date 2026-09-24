"""
Regression tests for the 2026-09-24 "immediate loss exit" inversion.

Live incident: a BUY NO@70c entry was sold at SELL NO@60c ~22s later for a
real loss, and the local position cache briefly held a phantom 1.9-contract
NO position with a YES-space 31c basis that read +51.3c unrealized PnL.

Root causes fixed:
1. ``eps.entry_fill_price_cents`` persisted the raw execution-side price
   (YES leg) for counterparty-form fills, poisoning the monitor's entry basis
   for NO positions.  It must persist the position-side (held outcome) price.
2. Edge-realization (``current >= model_fair``) fired on UNDERWATER
   convergence — the model's fair value fell to a falling bid and the
   position was cut <1s after entry at a locked-in loss.  Edge-realization
   is a profit capture and now requires ``unrealized_pnl_cents > 0``;
   underwater invalidation is deferred to EDGE_DECAY (hold + confirmations).
"""

import asyncio
import pytest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

from merid.event_venues.kalshi.position_cache import (
    KalshiPositionCache,
    ENTRY_PROVENANCE_AVAILABLE,
)
from merid.position_management.position import Position, PositionSide
from merid.position_management.position_monitor import PositionMonitor


@pytest.fixture(autouse=True)
async def _clear_cache(monkeypatch):
    """Reset the singleton cache and neutralize environment checks."""
    monkeypatch.setattr("merid.event_venues.kalshi.position_cache._is_expired_ticker", lambda t: False)
    monkeypatch.setattr("merid.event_venues.kalshi.position_cache._is_test_ticker", lambda t: False)
    cache = KalshiPositionCache()
    await cache.clear()
    cache._last_sync = None
    cache._last_rest_sync_timestamp = 0.0
    yield
    await cache.clear()
    cache._last_sync = None
    cache._last_rest_sync_timestamp = 0.0


class TestEntryProvenancePositionSidePrice:
    """Counterparty-form fills must persist the held-side price as entry basis."""

    @pytest.mark.asyncio
    async def test_sell_yes_form_buy_no_persists_no_leg_as_basis(self):
        """A BUY NO fill reported as SELL YES@31 must write 69c, not 31c."""
        if not ENTRY_PROVENANCE_AVAILABLE:
            pytest.skip("entry provenance store unavailable")

        from merid.event_venues.kalshi.position_cache import (
            EntryProvenanceSnapshot,
            get_entry_provenance_store,
        )

        cache = KalshiPositionCache()
        market_id = "KXXRP15M-INVERSION-NO"
        client_order_id = "test-inv-no-01"

        store = get_entry_provenance_store()
        snapshot = EntryProvenanceSnapshot(
            snapshot_id="snap-inv-no-01",
            client_order_id=client_order_id,
            ticker=market_id,
            asset="XRP",
            outcome_side="no",
        )
        store.register(snapshot)

        # Counterparty-form fill: exchange reports SELL YES@31 for a BUY NO.
        await cache.on_fill(
            market_id=market_id,
            contracts=1,
            quantity_cc=90,
            price_cents=31,
            fee_cents=0,
            side="yes",
            action="sell",
            client_order_id=client_order_id,
            fill_id="fill-inv-no-01",
            is_exit=False,
            canonicalization_state="TRUSTED_LIVE_V1",
            yes_price_cents=31,
            no_price_cents=69,
        )

        pos = cache._positions[market_id]
        # The fresh signed position is long NO at the NO leg price.
        assert pos.side == "no"
        assert pos.avg_price_cents == 69

        # The durable provenance basis must be the NO-space price too —
        # 31c here produced the phantom +51.3c PnL that triggered the bad exit.
        eps = store.get(client_order_id)
        assert eps.entry_fill_price_cents == 69, (
            f"provenance basis must be NO-space 69c, got {eps.entry_fill_price_cents}"
        )


class TestEdgeRealizationProfitGate:
    """Edge-realization may only fire while the position is in profit."""

    def _monitor(self) -> PositionMonitor:
        return PositionMonitor()

    def _position(self, **kwargs) -> Position:
        entry_price = kwargs.get("avg_entry_price_cents", 50)
        defaults = {
            "risk_params_state": "original_persisted",
            "risk_params_schema_version": 2,
            "client_order_id": "test-client",
            "entry_fill_id": "test-fill",
            "fill_source": "test",
            "entry_book_capture_quality": "AT_FILL",
            "entry_executable_bid_cents": entry_price - 1,
            "entry_executable_ask_cents": entry_price + 1,
            "entry_fill_price_cents": entry_price,
        }
        defaults.update(kwargs)
        return Position(**defaults)

    def _stub_fair_value(self, monkeypatch, fair_cents: int):
        """Point the monitor's fair-value lookup at a fixed value."""
        monkeypatch.setattr(
            "merid.position_management.position_monitor._get_fair_value_cents",
            lambda state, held: fair_cents,
        )
        # The lookup requires a non-None unified/kalshi market state.
        stub_state = SimpleNamespace()
        stub_store = SimpleNamespace(
            get_unified=lambda market_id: stub_state,
            get=lambda market_id: stub_state,
        )
        monkeypatch.setattr(
            "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
            lambda: stub_store,
        )

    def test_underwater_convergence_does_not_exit(self, monkeypatch):
        """NO@70 entry, bid 62, model fair 50 (NO space): bid >= fair holds but
        the position is underwater — the loss lock must be suppressed."""
        monitor = self._monitor()
        self._stub_fair_value(monkeypatch, 50)  # fair_no=50 <= bid 62

        callback = Mock()
        monitor.register_exit_intent_callback(callback)

        position = self._position(
            market_id="KXXRP15M-INV-UW",
            series_ticker="KXXRP15M",
            side=PositionSide.NO,
            size=1,
            avg_entry_price_cents=70,
            all_in_entry_basis_cents=70,
        )
        monitor.add_position(position)

        result = asyncio.run(monitor._legacy_check_position(position, 62))

        # No CURRENT_EDGE_REVERSAL candidate may be emitted underwater.
        from merid.position_management.exit_policy import ExitReason
        assert result is None or result.reason != ExitReason.CURRENT_EDGE_REVERSAL
        callback.assert_not_called()

    def test_in_profit_convergence_still_exits(self, monkeypatch):
        """The profit path is preserved: bid >= fair while in profit still
        produces the edge-realization candidate."""
        monitor = self._monitor()
        self._stub_fair_value(monkeypatch, 55)

        # Prevent the emitted intent from touching external systems.
        emitted = []

        async def _capture(position, reason, exit_price_cents, **kwargs):
            emitted.append((reason, exit_price_cents))

        monkeypatch.setattr(monitor, "_emit_exit_intent", _capture)

        position = self._position(
            market_id="KXBTC15M-INV-TP",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=1,
            avg_entry_price_cents=50,
            all_in_entry_basis_cents=50,
            # Lift the auto-derived TP above the test bid so the resolver does
            # not prefer TAKE_PROFIT (priority 55) over CURRENT_EDGE_REVERSAL.
            take_profit_price_cents=80,
        )
        monitor.add_position(position)

        result = asyncio.run(monitor._legacy_check_position(position, 62))

        from merid.position_management.exit_policy import ExitReason
        assert result is not None
        assert result.reason == ExitReason.CURRENT_EDGE_REVERSAL
        assert emitted and emitted[0][0] == ExitReason.CURRENT_EDGE_REVERSAL
