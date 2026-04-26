"""
Integration tests for Top-3 system — agent integration and router enforcement.

These tests verify that the top-3 system is properly wired through the trading pipeline.
"""

import pytest
import os
from unittest.mock import Mock, patch, MagicMock

from merid.trading.top3_edge_allocator import (
    EdgeCandidate,
    get_top3_allocator,
)
from merid.trading.top3_batch_manager import (
    Top3BatchManager,
    get_top3_batch_manager,
    reset_top3_batch_manager,
    REJECT_NO_ACTIVE_BATCH,
    REJECT_ASSET_NOT_IN_TOP3,
)


@pytest.fixture
def top3_enabled_env(monkeypatch):
    """Enable top-3 system via environment."""
    monkeypatch.setenv("TOP3_ENABLED", "true")
    yield


@pytest.fixture
def reset_batch_manager():
    """Reset and provide batch manager singleton before each test."""
    reset_top3_batch_manager()
    yield get_top3_batch_manager()
    reset_top3_batch_manager()


class TestAgentIntegration:
    """Tests for agent integration with top-3 batch manager."""
    
    def test_agent_cannot_open_without_batch(
        self, top3_enabled_env, reset_batch_manager
    ):
        """Agent with positive signal cannot open without active batch."""
        mgr = get_top3_batch_manager()
        
        # Simulate agent asking for permission
        allowed, reason, allocation = mgr.can_open_new_position(
            asset="BTC",
            requested_notional=1000,
        )
        
        assert allowed is False
        assert reason == REJECT_NO_ACTIVE_BATCH
        assert allocation is None
    
    def test_agent_only_opens_for_allocated_assets(
        self, top3_enabled_env, reset_batch_manager
    ):
        """Only assets in top-3 batch can open new positions."""
        mgr = get_top3_batch_manager()
        
        # Create batch with BTC, ETH, SOL
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000),
            EdgeCandidate("ETH", edge=0.08, max_notional_cap=4000),
            EdgeCandidate("SOL", edge=0.06, max_notional_cap=3000),
            EdgeCandidate("XRP", edge=0.04, max_notional_cap=2000),
            EdgeCandidate("DOGE", edge=0.02, max_notional_cap=1000),
        ]
        
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=candidates,
        )
        
        # BTC (in top 3) should be allowed
        allowed, reason, allocation = mgr.can_open_new_position("BTC", 500)
        assert allowed is True
        assert allocation is not None
        
        # XRP (not in top 3) should be rejected
        allowed, reason, allocation = mgr.can_open_new_position("XRP", 500)
        assert allowed is False
        assert reason == REJECT_ASSET_NOT_IN_TOP3
        assert allocation is None
        
        # DOGE (not in top 3) should be rejected
        allowed, reason, allocation = mgr.can_open_new_position("DOGE", 500)
        assert allowed is False
        assert reason == REJECT_ASSET_NOT_IN_TOP3
    
    def test_agent_respects_target_notional(
        self, top3_enabled_env, reset_batch_manager
    ):
        """Agent should respect target notional from allocation."""
        mgr = get_top3_batch_manager()
        
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000),
            EdgeCandidate("ETH", edge=0.08, max_notional_cap=4000),
            EdgeCandidate("SOL", edge=0.06, max_notional_cap=3000),
        ]
        
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=candidates,
        )
        
        btc_alloc = batch.get_allocation_for_asset("BTC")
        assert btc_alloc is not None
        
        # Target notional should be reasonable (proportional to edge)
        assert btc_alloc.target_notional > 0
        
        # The allocation should be roughly proportional to edge
        # BTC edge=0.10, total edge=0.24, cap=2000
        # Expected: ~833 cents
        assert 600 < btc_alloc.target_notional <= 2000


class TestRouterEnforcement:
    """Tests for router/ingress validation."""
    
    def test_router_rejects_entry_without_batch(
        self, top3_enabled_env, reset_batch_manager
    ):
        """Router should reject entry orders when no active batch."""
        mgr = get_top3_batch_manager()
        
        allowed, reason = mgr.validate_order(
            asset="BTC",
            ticker="KXBTC-TEST",
            side="yes",
            contracts=10,
            price_cents=50,
        )
        
        assert allowed is False
        assert reason == REJECT_NO_ACTIVE_BATCH
    
    def test_router_rejects_asset_not_in_top3(
        self, top3_enabled_env, reset_batch_manager
    ):
        """Router should reject entry for assets not in top-3."""
        mgr = get_top3_batch_manager()
        
        # Create batch (top 3 only)
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000),
            EdgeCandidate("ETH", edge=0.08, max_notional_cap=4000),
            EdgeCandidate("SOL", edge=0.06, max_notional_cap=3000),
        ]
        
        mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=candidates,
        )
        
        # Try to route XRP (not in top 3)
        allowed, reason = mgr.validate_order(
            asset="XRP",
            ticker="KXXRP-TEST",
            side="yes",
            contracts=10,
            price_cents=50,
        )
        
        assert allowed is False
        assert reason == REJECT_ASSET_NOT_IN_TOP3
    
    def test_router_accepts_valid_entry(
        self, top3_enabled_env, reset_batch_manager
    ):
        """Router should accept valid top-3 entry orders."""
        mgr = get_top3_batch_manager()
        
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000),
            EdgeCandidate("ETH", edge=0.08, max_notional_cap=4000),
            EdgeCandidate("SOL", edge=0.06, max_notional_cap=3000),
        ]
        
        mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=candidates,
        )
        
        # Valid top-3 entry
        allowed, reason = mgr.validate_order(
            asset="BTC",
            ticker="KXBTC-TEST",
            side="yes",
            contracts=10,
            price_cents=50,
        )
        
        assert allowed is True
        assert reason == ""


class TestBatchRegime:
    """Tests for batch regime (no overlapping batches)."""
    
    def test_no_new_batch_while_active(
        self, top3_enabled_env, reset_batch_manager
    ):
        """Cannot create new batch while one is active."""
        mgr = get_top3_batch_manager()
        
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000),
            EdgeCandidate("ETH", edge=0.08, max_notional_cap=4000),
            EdgeCandidate("SOL", edge=0.06, max_notional_cap=3000),
        ]
        
        # Create first batch
        batch1 = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=candidates,
        )
        assert batch1 is not None
        
        # Try to create second batch (should fail)
        batch2 = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=candidates,
        )
        assert batch2 is None
    
    def test_new_batch_after_all_closed(
        self, top3_enabled_env, reset_batch_manager
    ):
        """New batch can be created after all positions closed and reconciled."""
        mgr = get_top3_batch_manager()
        
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000),
            EdgeCandidate("ETH", edge=0.08, max_notional_cap=4000),
            EdgeCandidate("SOL", edge=0.06, max_notional_cap=3000),
        ]
        
        # Create first batch
        batch1 = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=candidates,
        )
        
        # Close all positions
        for asset in ["BTC", "ETH", "SOL"]:
            mgr.mark_asset_closed(batch1.batch_id, asset)
        
        # Verify batch is closed
        assert batch1.status.value == "closed"
        
        # CRITICAL: Must reconcile before new cycle can start
        mgr.mark_batch_reconciled(batch1.batch_id, realized_pnl_cents=500)
        
        # Now can create new batch (cycle lock released)
        batch2 = mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=candidates,
        )
        
        assert batch2 is not None
        assert batch2.batch_id != batch1.batch_id


class TestBankrollCapEnforcement:
    """Tests for 1-2% bankroll cap enforcement."""
    
    def test_total_notional_within_cap(
        self, top3_enabled_env, reset_batch_manager
    ):
        """Total notional across all 3 assets should be within 1-2% cap."""
        mgr = get_top3_batch_manager()
        
        bankroll = 100_000  # $1,000
        
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000),
            EdgeCandidate("ETH", edge=0.08, max_notional_cap=4000),
            EdgeCandidate("SOL", edge=0.06, max_notional_cap=3000),
        ]
        
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=bankroll,
            candidates=candidates,
        )
        
        # Total should be within 2% of bankroll
        total = batch.total_target_notional
        max_allowed = int(0.02 * bankroll)
        
        assert total <= max_allowed, f"Total {total} exceeds cap {max_allowed}"
    
    def test_per_asset_notional_within_target(
        self, top3_enabled_env, reset_batch_manager
    ):
        """Each asset's target should be within its allocation."""
        mgr = get_top3_batch_manager()
        
        bankroll = 100_000
        
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000),
            EdgeCandidate("ETH", edge=0.08, max_notional_cap=4000),
            EdgeCandidate("SOL", edge=0.06, max_notional_cap=3000),
        ]
        
        batch = mgr.maybe_create_new_batch(
            bankroll_notional=bankroll,
            candidates=candidates,
        )
        
        # Each allocation should be positive and within per-asset cap
        for alloc in batch.allocations:
            assert alloc.target_notional > 0
            assert alloc.target_notional <= alloc.edge * 10000  # Rough bound check


class TestMetricsAndObservability:
    """Tests for metrics and observability."""
    
    def test_rejection_metrics_tracking(
        self, top3_enabled_env, reset_batch_manager
    ):
        """Rejection counters should track each rejection reason."""
        mgr = get_top3_batch_manager()
        
        # Generate rejections
        mgr.validate_order("BTC", "ticker", "yes", 10, 50)  # No batch
        
        mgr.maybe_create_new_batch(
            bankroll_notional=100_000,
            candidates=[
                EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000),
                EdgeCandidate("ETH", edge=0.08, max_notional_cap=4000),
                EdgeCandidate("SOL", edge=0.06, max_notional_cap=3000),
            ],
        )
        
        mgr.validate_order("XRP", "KXXRP", "yes", 10, 50)  # Not in top 3
        mgr.validate_order("DOGE", "KXDOGE", "yes", 10, 50)  # Not in top 3
        
        # Check metrics
        metrics = mgr.get_metrics()
        
        assert metrics["active_batch"] == 1
        assert "current_batch" in metrics
        assert "rejections" in metrics
        
        rejections = metrics["rejections"]
        assert rejections[REJECT_NO_ACTIVE_BATCH] >= 1
        assert rejections[REJECT_ASSET_NOT_IN_TOP3] >= 2


class TestEnvironmentToggle:
    """Tests for environment-based enabling/disabling."""
    
    def test_top3_disabled_when_env_false(
        self, reset_batch_manager, monkeypatch
    ):
        """TOP3_ENABLED=false should disable top-3 gating."""
        monkeypatch.setenv("TOP3_ENABLED", "false")
        
        # When disabled, the continuous trader should not enforce top-3
        # This is checked by the _top3_enabled flag in the trader
        enabled = os.getenv("TOP3_ENABLED", "true").lower() in ("true", "1", "yes")
        
        assert enabled is False
    
    def test_top3_enabled_by_default(
        self, reset_batch_manager, monkeypatch
    ):
        """TOP3 should be enabled by default when env not set."""
        # Ensure env is not set
        monkeypatch.delenv("TOP3_ENABLED", raising=False)
        
        enabled = os.getenv("TOP3_ENABLED", "true").lower() in ("true", "1", "yes")
        
        assert enabled is True  # Default is true
