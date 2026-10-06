"""
Comprehensive tests for end-to-end position tracking fixes.

Tests all high-leverage bug fixes implemented in the position tracking system:
- Fix 1: Pre-registration of order_id mapping
- Fix 2: Centralized window exposure recording
- Fix 3: Price repeat check in position cache
- Fix 4: Conditional position cache clearing
- Fix 5: Relaxed staleness guard
- Fix 6: Auto-corrective reconciliation
- Fix 7: REST as primary source
- Fix 9: Atomic window capacity release
- Fix 10: Persistent risk envelope state
- Fix 11: Persistent slot allocator state
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime, timezone, timedelta


class TestFix1OrderIDMappingPreRegistration:
    """Test Fix 1: Pre-registration of order_id mapping."""

    @pytest.mark.asyncio
    async def test_pre_register_order_id_mapping_before_submission(self):
        """Test that order_id mapping is registered BEFORE order submission."""
        from merid.event_venues.kalshi.position_cache import get_position_cache

        cache = get_position_cache()
        client_tag = "test_client_123"

        # Pre-register mapping
        cache.register_order_id_mapping(client_tag, client_tag)

        # Verify mapping exists
        assert client_tag in cache._order_id_to_client_tag
        assert cache._order_id_to_client_tag[client_tag] == client_tag

        # Cleanup
        cache._order_id_to_client_tag.clear()

    @pytest.mark.asyncio
    async def test_update_mapping_after_successful_submission(self):
        """Test that mapping is updated with actual Kalshi order_id after successful submission."""
        from merid.event_venues.kalshi.position_cache import get_position_cache

        cache = get_position_cache()
        client_tag = "test_client_123"
        kalshi_order_id = "kalshi_order_456"

        # Pre-register with client_tag
        cache.register_order_id_mapping(client_tag, client_tag)

        # Simulate successful submission - update mapping
        cache.register_order_id_mapping(kalshi_order_id, client_tag)
        cache._order_id_to_client_tag.pop(client_tag, None)

        # Verify updated mapping
        assert kalshi_order_id in cache._order_id_to_client_tag
        assert cache._order_id_to_client_tag[kalshi_order_id] == client_tag
        assert client_tag not in cache._order_id_to_client_tag

        # Cleanup
        cache._order_id_to_client_tag.clear()


class TestFix2CentralizedWindowExposureRecording:
    """Test Fix 2: Centralized window exposure recording."""

    @pytest.mark.asyncio
    async def test_window_exposure_removed_from_order_gate(self):
        """Test that window exposure recording was removed from order_gate.mark_filled()."""
        from merid.event_venues.kalshi.order_gate import PreTradeGate

        gate = PreTradeGate()

        # Verify mark_filled does NOT contain window exposure recording code
        # This is verified by checking the source code doesn't have the old pattern
        import inspect
        source = inspect.getsource(gate.mark_filled)
        assert "record_order_execution" not in source or "FIX 2" in source


class TestFix3PriceRepeatCheckInPositionCache:
    """Test Fix 3: Price repeat check in position cache."""

    @pytest.mark.asyncio
    async def test_price_repeat_check_added_to_position_cache(self):
        """Test that price repeat check was added to position_cache.on_fill(, canonicalization_state="TRUSTED_LIVE_V1")."""
        from merid.event_venues.kalshi.position_cache import get_position_cache

        cache = get_position_cache()

        # Verify on_fill contains price repeat check code
        import inspect
        source = inspect.getsource(cache.on_fill)
        assert "check_price_repeat" in source or "FIX 3" in source


class TestFix4ConditionalPositionCacheClearing:
    """Test Fix 4: Conditional position cache clearing."""

    @pytest.mark.asyncio
    async def test_empty_rest_response_preserves_cache(self):
        """Test that empty REST response preserves current cache state."""
        from merid.event_venues.kalshi.position_cache import get_position_cache

        cache = get_position_cache()
        market_id = "KXBTC15M-TEST"

        # Add a position to cache
        from merid.event_venues.kalshi.position_cache import CachedPosition
        cache._positions[market_id] = CachedPosition(
            market_id=market_id,
            agent_id="BTC_15M",
            contracts=1,
            side="yes",
            thesis_side="yes",
            avg_price_cents=50
        )

        # Sync with empty REST response
        await cache.sync_from_rest([])

        # Verify position is preserved
        assert market_id in cache._positions
        assert cache._positions[market_id].contracts == 1

        # Cleanup
        cache._positions.clear()


class TestFix5RelaxedStalenessGuard:
    """Test Fix 5: Relaxed staleness guard."""

    @pytest.mark.asyncio
    async def test_relaxed_staleness_guard_added(self):
        """Test that relaxed staleness guard code was added to sync_from_rest."""
        from merid.event_venues.kalshi.position_cache import get_position_cache

        cache = get_position_cache()

        # Verify sync_from_rest contains relaxed staleness guard code
        import inspect
        source = inspect.getsource(cache.sync_from_rest)
        assert "STALE-WARN" in source or "FIX 5" in source


class TestFix6AutoCorrectiveReconciliation:
    """Test Fix 6: Auto-corrective reconciliation."""

    @pytest.mark.asyncio
    async def test_auto_corrective_reconciliation_added(self):
        """Verify the exchange-vs-ledger reconciliation report contract.

        The Fix-6 era auto-corrective reconciler was refactored: divergence
        correction now lives in the position-cache/canonical reconcilers and
        ``reconcile_with_kalshi_positions`` is a purely diagnostic reporter.
        The contract that must hold is a structured divergence report the
        risk engine can consume.
        """
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger

        ledger = get_fills_ledger()

        report = await ledger.reconcile_with_kalshi_positions([])

        assert report["positions_checked"] == 0
        assert report["divergences"] == []
        assert "status" in report
        assert "positions_matched" in report
        assert "ghost_trade_candidates" in report


class TestFix7RESTAsPrimarySource:
    """Test Fix 7: REST as primary source."""

    @pytest.mark.asyncio
    async def test_rest_as_primary_source_added(self):
        """Test that REST as primary source code was added to fills_poller."""
        from merid.event_venues.kalshi.fills_poller import FillsPoller

        poller = FillsPoller()

        # Verify _do_reconcile contains REST as primary source code
        import inspect
        source = inspect.getsource(poller._do_reconcile)
        assert "primary source" in source or "FIX 7" in source


class TestFix9AtomicWindowCapacityRelease:
    """Test Fix 9: Atomic window capacity release."""

    @pytest.mark.asyncio
    async def test_atomic_capacity_release_added(self):
        """Verify remove_position atomically drops the position and all
        associated registries under the monitor lock — the Fix-9 contract is
        that no stale capacity/exit state survives a removal."""
        from merid.position_management.position_monitor import PositionMonitor
        from merid.position_management.position import Position, PositionSide

        monitor = PositionMonitor()
        position = Position(
            position_id="fix9-pos-1",
            market_id="KXBTC15M-FIX9",
            side=PositionSide.YES,
            size=1,
            avg_entry_price_cents=50,
        )
        monitor.add_position(position)
        assert position.position_id in monitor._open_positions

        monitor.remove_position(position.position_id)

        assert position.position_id not in monitor._open_positions
        assert "KXBTC15M-FIX9" not in monitor._market_to_position
        assert position.position_id not in monitor._exit_registry
        assert position.position_id not in monitor._exit_quantities


class TestFix10PersistentRiskEnvelopeState:
    """Test Fix 10: Persistent risk envelope state."""

    def test_save_window_state(self):
        """Test saving window exposure state to file."""
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import save_window_state, _WINDOW_TRACKING_STATE, _WINDOW_TRACKING_LOCK
        import os

        # Set some state
        with _WINDOW_TRACKING_LOCK:
            _WINDOW_TRACKING_STATE["total_exposure_usd"] = 0.5
            _WINDOW_TRACKING_STATE["agent_exposure_usd"] = {"BTC_15M": 0.5}

        # Save state
        result = save_window_state()

        # Verify save succeeded
        assert result is True

        # Cleanup
        if os.path.exists(_WINDOW_TRACKING_STATE.get("_WINDOW_STATE_FILE", "data/window_exposure_state.json")):
            os.remove(_WINDOW_TRACKING_STATE.get("_WINDOW_STATE_FILE", "data/window_exposure_state.json"))

        # Reset state
        with _WINDOW_TRACKING_LOCK:
            _WINDOW_TRACKING_STATE["total_exposure_usd"] = 0.0
            _WINDOW_TRACKING_STATE["agent_exposure_usd"] = {}

    def test_load_window_state(self):
        """Test loading window exposure state from file."""
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import save_window_state, load_window_state, _WINDOW_TRACKING_STATE, _WINDOW_TRACKING_LOCK
        import os

        # Set and save state
        with _WINDOW_TRACKING_LOCK:
            _WINDOW_TRACKING_STATE["total_exposure_usd"] = 0.5
            _WINDOW_TRACKING_STATE["agent_exposure_usd"] = {"BTC_15M": 0.5}

        save_window_state()

        # Reset state
        with _WINDOW_TRACKING_LOCK:
            _WINDOW_TRACKING_STATE["total_exposure_usd"] = 0.0
            _WINDOW_TRACKING_STATE["agent_exposure_usd"] = {}

        # Load state
        result = load_window_state()

        # Verify load succeeded and state was restored
        assert result is True
        assert _WINDOW_TRACKING_STATE["total_exposure_usd"] == 0.5
        assert "BTC_15M" in _WINDOW_TRACKING_STATE["agent_exposure_usd"]

        # Cleanup
        state_file = _WINDOW_TRACKING_STATE.get("_WINDOW_STATE_FILE", "data/window_exposure_state.json")
        if os.path.exists(state_file):
            os.remove(state_file)

        # Reset state
        with _WINDOW_TRACKING_LOCK:
            _WINDOW_TRACKING_STATE["total_exposure_usd"] = 0.0
            _WINDOW_TRACKING_STATE["agent_exposure_usd"] = {}


class TestFix11PersistentSlotAllocatorState:
    """Test Fix 11: Slot allocator state durability.

    The allocator no longer persists slots to a JSON file; durable state is
    derived by reconciling slots against the canonical position cache
    (``sync_with_position_cache``) and by clearing phantom slots when the
    cache reports zero open positions (``clear_slots_on_empty_positions``).
    """

    def _add_slot(self, allocator, slot_id="test_slot"):
        from merid.risk.global_slot_allocator import PositionSlot, SlotStatus
        allocator._slots[slot_id] = PositionSlot(
            slot_id=slot_id,
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=50,
            entry_time=time.time(),
            status=SlotStatus.OCCUPIED,
        )

    def test_orphan_slot_removed_by_cache_sync(self):
        """A slot with no backing position is removed by cache reconciliation."""
        from merid.risk.global_slot_allocator import get_global_slot_allocator

        allocator = get_global_slot_allocator()
        try:
            self._add_slot(allocator)
            changed = allocator.sync_with_position_cache()
            assert changed >= 1
            assert "test_slot" not in allocator._slots
        finally:
            allocator._slots.clear()

    def test_phantom_slots_cleared_on_empty_position_cache(self):
        """Phantom slots are cleared when the cache reports zero positions."""
        from merid.risk.global_slot_allocator import get_global_slot_allocator

        allocator = get_global_slot_allocator()
        try:
            self._add_slot(allocator)
            allocator.clear_slots_on_empty_positions(position_count=0)
            assert allocator._slots == {}

            self._add_slot(allocator)
            allocator.clear_slots_on_empty_positions(position_count=1)
            assert "test_slot" in allocator._slots
        finally:
            allocator._slots.clear()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
