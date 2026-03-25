"""Tests for position cache mode isolation (BUG-001 fix verification).

Verifies that live and paper position caches are completely isolated
and that fills from the wrong mode are rejected to prevent confusion.
"""

import pytest
from decimal import Decimal

from merid.event_venues.kalshi.position_cache import (
    CachedPosition,
    KalshiPositionCache,
    get_position_cache,
    clear_all_caches,
)
from trading.trade_mode import TradeMode


class TestPositionCacheModeIsolation:
    """Test suite for mode-isolated position cache."""

    def setup_method(self):
        """Clear all caches before each test."""
        clear_all_caches()

    def test_separate_cache_instances_per_mode(self):
        """Each mode gets its own cache instance."""
        live_cache = get_position_cache(TradeMode.LIVE)
        paper_cache = get_position_cache(TradeMode.PAPER)
        mock_cache = get_position_cache(TradeMode.MOCK)

        # Different instances
        assert live_cache is not paper_cache
        assert live_cache is not mock_cache
        assert paper_cache is not mock_cache

        # Each instance knows its mode
        assert live_cache.mode == TradeMode.LIVE
        assert paper_cache.mode == TradeMode.PAPER
        assert mock_cache.mode == TradeMode.MOCK

    def test_same_mode_returns_same_instance(self):
        """Multiple calls for same mode return same instance (singleton per mode)."""
        live_cache_1 = get_position_cache(TradeMode.LIVE)
        live_cache_2 = get_position_cache(TradeMode.LIVE)

        assert live_cache_1 is live_cache_2

        paper_cache_1 = get_position_cache(TradeMode.PAPER)
        paper_cache_2 = get_position_cache(TradeMode.PAPER)

        assert paper_cache_1 is paper_cache_2

    def test_paper_fill_does_not_contaminate_live_cache(self):
        """Paper fills should only appear in paper cache, not live cache."""
        live_cache = get_position_cache(TradeMode.LIVE)
        paper_cache = get_position_cache(TradeMode.PAPER)

        # Add paper fill
        paper_cache.on_fill(
            market_id="KXBTC-TEST",
            contracts=10,
            price_cents=5500,
            fee_cents=7,
            side="yes",
            mode=TradeMode.PAPER,
        )

        # Paper position exists
        paper_pos = paper_cache.get_position("KXBTC-TEST")
        assert paper_pos is not None
        assert paper_pos.contracts == 10
        assert paper_pos.mode == TradeMode.PAPER

        # Live cache is still empty
        live_pos = live_cache.get_position("KXBTC-TEST")
        assert live_pos is None

    def test_live_fill_does_not_contaminate_paper_cache(self):
        """Live fills should only appear in live cache, not paper cache."""
        live_cache = get_position_cache(TradeMode.LIVE)
        paper_cache = get_position_cache(TradeMode.PAPER)

        # Add live fill
        live_cache.on_fill(
            market_id="KXBTC-TEST",
            contracts=20,
            price_cents=6000,
            fee_cents=14,
            side="no",
            mode=TradeMode.LIVE,
        )

        # Live position exists
        live_pos = live_cache.get_position("KXBTC-TEST")
        assert live_pos is not None
        assert live_pos.contracts == 20
        assert live_pos.mode == TradeMode.LIVE

        # Paper cache is still empty
        paper_pos = paper_cache.get_position("KXBTC-TEST")
        assert paper_pos is None

    def test_wrong_mode_fill_rejected_by_cache(self):
        """Cache rejects fills from wrong mode."""
        live_cache = get_position_cache(TradeMode.LIVE)

        # Attempt to add paper fill to live cache
        with pytest.raises(ValueError, match="Cannot apply PAPER fill to LIVE cache"):
            live_cache.on_fill(
                market_id="KXBTC-TEST",
                contracts=10,
                price_cents=5500,
                fee_cents=7,
                side="yes",
                mode=TradeMode.PAPER,  # WRONG MODE
            )

        # Cache should still be empty
        assert live_cache.get_position("KXBTC-TEST") is None

    def test_wrong_mode_fill_rejected_by_position(self):
        """Position rejects fills from wrong mode."""
        paper_cache = get_position_cache(TradeMode.PAPER)

        # Add initial paper position
        paper_cache.on_fill(
            market_id="KXBTC-TEST",
            contracts=10,
            price_cents=5500,
            fee_cents=7,
            side="yes",
            mode=TradeMode.PAPER,
        )

        position = paper_cache.get_position("KXBTC-TEST")
        assert position is not None

        # Attempt to apply live fill to paper position
        with pytest.raises(
            ValueError,
            match="Mode mismatch: position is paper, fill is live"
        ):
            position.apply_fill(
                contracts=5,
                price_cents=6000,
                fee_cents=5,
                side="yes",
                fill_mode=TradeMode.LIVE,  # WRONG MODE
            )

    def test_mode_tagged_position_state(self):
        """Position dataclass includes mode field."""
        cache = get_position_cache(TradeMode.LIVE)

        cache.on_fill(
            market_id="KXBTC-TEST",
            contracts=10,
            price_cents=5500,
            fee_cents=7,
            side="yes",
            mode=TradeMode.LIVE,
        )

        position = cache.get_position("KXBTC-TEST")
        assert position is not None
        assert hasattr(position, "mode")
        assert position.mode == TradeMode.LIVE

    def test_sync_from_rest_requires_matching_mode(self):
        """sync_from_rest rejects positions from wrong mode."""
        live_cache = get_position_cache(TradeMode.LIVE)

        positions = [
            {
                "market_id": "KXBTC-TEST",
                "contracts": 10,
                "side": "yes",
                "avg_price_cents": 5500,
                "realized_pnl": 100,
                "unrealized_pnl": 50,
            }
        ]

        # Attempt to sync paper positions to live cache
        with pytest.raises(ValueError, match="Cannot sync PAPER positions to LIVE cache"):
            live_cache.sync_from_rest(positions, mode=TradeMode.PAPER)

        # Cache should still be empty
        assert len(live_cache.get_all_positions()) == 0

    def test_sync_from_rest_with_matching_mode(self):
        """sync_from_rest succeeds with matching mode."""
        live_cache = get_position_cache(TradeMode.LIVE)

        positions = [
            {
                "market_id": "KXBTC-TEST",
                "contracts": 10,
                "side": "yes",
                "avg_price_cents": 5500,
                "realized_pnl": 100,
                "unrealized_pnl": 50,
            }
        ]

        live_cache.sync_from_rest(positions, mode=TradeMode.LIVE)

        # Position exists with correct mode
        position = live_cache.get_position("KXBTC-TEST")
        assert position is not None
        assert position.mode == TradeMode.LIVE
        assert position.contracts == 10

    def test_clear_all_caches_clears_all_modes(self):
        """clear_all_caches() clears live, paper, and mock caches."""
        live_cache = get_position_cache(TradeMode.LIVE)
        paper_cache = get_position_cache(TradeMode.PAPER)
        mock_cache = get_position_cache(TradeMode.MOCK)

        # Add positions to each cache
        for cache, mode in [
            (live_cache, TradeMode.LIVE),
            (paper_cache, TradeMode.PAPER),
            (mock_cache, TradeMode.MOCK),
        ]:
            cache.on_fill(
                market_id=f"KXBTC-TEST-{mode.value}",
                contracts=10,
                price_cents=5500,
                fee_cents=7,
                side="yes",
                mode=mode,
            )

        # Verify positions exist
        assert len(live_cache.get_all_positions()) == 1
        assert len(paper_cache.get_all_positions()) == 1
        assert len(mock_cache.get_all_positions()) == 1

        # Clear all
        clear_all_caches()

        # All caches empty
        assert len(live_cache.get_all_positions()) == 0
        assert len(paper_cache.get_all_positions()) == 0
        assert len(mock_cache.get_all_positions()) == 0

    def test_concurrent_fills_to_different_modes(self):
        """Multiple fills to different modes remain isolated."""
        live_cache = get_position_cache(TradeMode.LIVE)
        paper_cache = get_position_cache(TradeMode.PAPER)

        # Simulate concurrent trading in both modes
        for i in range(5):
            live_cache.on_fill(
                market_id=f"KXBTC-TEST-{i}",
                contracts=10 + i,
                price_cents=5500 + i * 100,
                fee_cents=7,
                side="yes",
                mode=TradeMode.LIVE,
            )

            paper_cache.on_fill(
                market_id=f"KXBTC-TEST-{i}",
                contracts=20 + i,
                price_cents=6000 + i * 100,
                fee_cents=14,
                side="no",
                mode=TradeMode.PAPER,
            )

        # Verify isolation
        live_positions = live_cache.get_all_positions()
        paper_positions = paper_cache.get_all_positions()

        assert len(live_positions) == 5
        assert len(paper_positions) == 5

        # Verify position details
        for i in range(5):
            live_pos = live_cache.get_position(f"KXBTC-TEST-{i}")
            paper_pos = paper_cache.get_position(f"KXBTC-TEST-{i}")

            assert live_pos is not None
            assert paper_pos is not None

            assert live_pos.mode == TradeMode.LIVE
            assert paper_pos.mode == TradeMode.PAPER

            assert live_pos.contracts == 10 + i
            assert paper_pos.contracts == 20 + i

            assert live_pos.side == "yes"
            assert paper_pos.side == "no"

    def test_mode_logged_in_cache_operations(self, caplog):
        """Mode is included in cache log messages."""
        import logging
        caplog.set_level(logging.INFO)

        cache = get_position_cache(TradeMode.LIVE)

        cache.on_fill(
            market_id="KXBTC-TEST",
            contracts=10,
            price_cents=5500,
            fee_cents=7,
            side="yes",
            mode=TradeMode.LIVE,
        )

        # Check logs include mode
        assert "mode=live" in caplog.text.lower()
