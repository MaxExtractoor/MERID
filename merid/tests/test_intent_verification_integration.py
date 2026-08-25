"""Integration tests for intent verification layer.

Tests the complete flow from signal generation through intent validation
to order routing. These tests verify the end-to-end audit chain.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch

from merid.validation.signal_snapshot import (
    SignalSnapshot,
    create_signal_snapshot,
    get_signal_snapshot_ledger,
)
from merid.validation.intent_validator import (
    IntentValidator,
    ValidationResult,
    get_intent_validator,
)
from merid.event_venues.kalshi.order_router import OrderIntent, OrderResult


class TestSignalToIntentIntegration:
    """Integration tests for signal-to-intent flow."""
    
    def test_signal_snapshot_to_intent_flow(self):
        """Test complete flow from signal snapshot to intent creation."""
        # Step 1: Create a signal snapshot
        snapshot = create_signal_snapshot(
            signal_id="sig-1721476800-BTC",
            market_id="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            intent="open",
            edge=0.05,
            confidence=0.75,
            origin_agent="agent_grid_15m",
            origin_strategy="momentum_fvg",
            timeframe_label="15m",
            raw_features={"velocity": 0.01, "rsi": 50.0},
        )
        
        # Step 2: Create an OrderIntent with audit chain fields
        intent = OrderIntent(
            ticker="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            price_cents=42,
            count=1,
            source="merid.prediction.agent_grid_15m",
            agent_id="agent_grid_15m",
            # Audit chain fields
            source_signal_id=snapshot.signal_id,
            source_signal_hash=snapshot.signal_hash,
            intent_stage="constructed",
        )
        
        # Step 3: Verify intent has correct audit chain fields
        assert intent.source_signal_id == snapshot.signal_id
        assert intent.source_signal_hash == snapshot.signal_hash
        assert intent.intent_stage == "constructed"
    
    def test_intent_validation_with_real_snapshot(self):
        """Test intent validation against a real snapshot."""
        # Create a snapshot
        snapshot = create_signal_snapshot(
            signal_id="sig-1721476800-BTC",
            market_id="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            intent="open",
            edge=0.05,
            confidence=0.75,
            origin_agent="agent_grid_15m",
            origin_strategy="momentum_fvg",
            timeframe_label="15m",
            raw_features={},
        )
        
        # Create a matching intent
        intent = MagicMock()
        intent.source_signal_id = snapshot.signal_id
        intent.source_signal_hash = snapshot.signal_hash
        intent.intent_id = "intent_abc"
        intent.intent_stage = "constructed"
        intent.ticker = snapshot.market_id
        intent.side = snapshot.side
        intent.action = snapshot.action
        intent.entry_or_exit = "entry"
        intent.override_reason = None
        
        # Validate
        validator = get_intent_validator()
        result = validator.validate_intent(intent)
        
        # Should pass
        assert result.is_valid is True
        assert result.errors == []
    
    def test_intent_validation_with_hash_mismatch(self):
        """Test intent validation fails with hash mismatch."""
        # Create a snapshot
        snapshot = create_signal_snapshot(
            signal_id="sig-1721476800-BTC",
            market_id="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            intent="open",
            edge=0.05,
            confidence=0.75,
            origin_agent="agent_grid_15m",
            origin_strategy="momentum_fvg",
            timeframe_label="15m",
            raw_features={},
        )
        
        # Create an intent with wrong hash
        intent = MagicMock()
        intent.source_signal_id = snapshot.signal_id
        intent.source_signal_hash = "wrong_hash_1234567890abcdef"
        intent.intent_id = "intent_abc"
        intent.intent_stage = "constructed"
        intent.ticker = snapshot.market_id
        intent.side = snapshot.side
        intent.action = snapshot.action
        intent.entry_or_exit = "entry"
        intent.override_reason = None
        
        # Validate
        validator = get_intent_validator()
        result = validator.validate_intent(intent)
        
        # Should fail
        assert result.is_valid is False
        assert any("hash" in error.lower() for error in result.errors)
    
    def test_signal_correction_creates_new_snapshot(self):
        """Test that signal correction creates a new snapshot with link."""
        # Clear ledger to avoid interference from previous tests
        ledger = get_signal_snapshot_ledger()
        ledger._snapshots_by_id.clear()
        ledger._snapshots_by_hash.clear()
        ledger._snapshots_by_signal.clear()
        
        # Create original snapshot
        original = create_signal_snapshot(
            signal_id="sig-1721476800-BTC",
            market_id="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            intent="open",
            edge=0.05,
            confidence=0.75,
            origin_agent="agent_grid_15m",
            origin_strategy="momentum_fvg",
            timeframe_label="15m",
            raw_features={},
        )
        
        # Create correction
        correction = create_signal_snapshot(
            signal_id="sig-1721476800-BTC",
            market_id="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            intent="open",
            edge=0.06,  # Corrected edge
            confidence=0.80,
            origin_agent="agent_grid_15m",
            origin_strategy="momentum_fvg",
            timeframe_label="15m",
            raw_features={},
            previous_snapshot_id=original.snapshot_id,
        )
        
        # Verify correction links to original
        assert correction.previous_snapshot_id == original.snapshot_id
        assert correction.signal_hash != original.signal_hash
        
        # Verify both snapshots exist in ledger
        ledger = get_signal_snapshot_ledger()
        snapshots = ledger.get_by_signal_id("sig-1721476800-BTC")
        assert len(snapshots) == 2
        assert original in snapshots
        assert correction in snapshots


class TestOrderRouterValidationIntegration:
    """Integration tests for order_router validation."""
    
    def test_order_intent_with_audit_chain_fields(self):
        """Test that OrderIntent can be created with audit chain fields."""
        intent = OrderIntent(
            ticker="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            price_cents=42,
            count=1,
            source="merid.prediction.agent_grid_15m",
            agent_id="agent_grid_15m",
            # Audit chain fields
            source_signal_id="sig-1721476800-BTC",
            source_signal_hash="abc123def456",
            intent_hash="hash123",
            intent_stage="validated",
        )
        
        assert intent.source_signal_id == "sig-1721476800-BTC"
        assert intent.source_signal_hash == "abc123def456"
        assert intent.intent_hash == "hash123"
        assert intent.intent_stage == "validated"
    
    def test_compute_intent_hash_deterministic(self):
        """Test that compute_intent_hash is deterministic."""
        from merid.event_venues.kalshi.order_router import compute_intent_hash
        
        hash1 = compute_intent_hash(
            ticker="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            price_cents=42,
            count=1,
            order_type="limit",
            time_in_force="gtc",
        )
        hash2 = compute_intent_hash(
            ticker="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            price_cents=42,
            count=1,
            order_type="limit",
            time_in_force="gtc",
        )
        
        assert hash1 == hash2
    
    def test_compute_intent_hash_different_for_different_intents(self):
        """Test that compute_intent_hash differs for different intents."""
        from merid.event_venues.kalshi.order_router import compute_intent_hash
        
        hash1 = compute_intent_hash(
            ticker="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            price_cents=42,
            count=1,
            order_type="limit",
            time_in_force="gtc",
        )
        hash2 = compute_intent_hash(
            ticker="KXBTC15M-2026-07-20T14:00",
            side="no",  # Different side
            action="buy",
            price_cents=42,
            count=1,
            order_type="limit",
            time_in_force="gtc",
        )
        
        assert hash1 != hash2
    
    @pytest.mark.asyncio
    async def test_order_router_rejects_invalid_intent(self):
        """Test that order_router rejects intents that fail validation."""
        from merid.event_venues.kalshi.order_router import route_order_async
        
        # Create a snapshot
        snapshot = create_signal_snapshot(
            signal_id="sig-1721476800-BTC",
            market_id="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            intent="open",
            edge=0.05,
            confidence=0.75,
            origin_agent="agent_grid_15m",
            origin_strategy="momentum_fvg",
            timeframe_label="15m",
            raw_features={},
        )
        
        # Create intent with wrong hash
        intent = OrderIntent(
            ticker="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            price_cents=42,
            count=1,
            source="merid.prediction.agent_grid_15m",
            agent_id="agent_grid_15m",
            # Audit chain fields with wrong hash
            source_signal_id=snapshot.signal_id,
            source_signal_hash="wrong_hash_1234567890abcdef",
            intent_stage="constructed",
        )
        
        # Mock venue gate to allow order
        with patch('merid.event_venues.kalshi.order_router.get_venue_gate') as mock_gate:
            mock_gate.return_value.mode = "paper"
            mock_gate.return_value.should_simulate_fill.return_value = True
            
        with patch('merid.event_venues.kalshi.client.get_kalshi_client') as mock_client:
            mock_client.return_value = None
            
            # Route order
            result = await route_order_async(intent)
            
            # Should be rejected due to intent validation failure
            assert result.status == "rejected"
            assert "intent_validation_failed" in result.reason
    
    @pytest.mark.asyncio
    async def test_order_router_accepts_valid_intent(self):
        """Test that order_router accepts intents that pass validation."""
        from merid.event_venues.kalshi.order_router import route_order_async
        
        # Create a snapshot
        snapshot = create_signal_snapshot(
            signal_id="sig-1721476800-BTC",
            market_id="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            intent="open",
            edge=0.05,
            confidence=0.75,
            origin_agent="agent_grid_15m",
            origin_strategy="momentum_fvg",
            timeframe_label="15m",
            raw_features={},
        )
        
        # Create intent with correct hash
        intent = OrderIntent(
            ticker="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            price_cents=42,
            count=1,
            source="merid.prediction.agent_grid_15m",
            agent_id="agent_grid_15m",
            # Audit chain fields with correct hash
            source_signal_id=snapshot.signal_id,
            source_signal_hash=snapshot.signal_hash,
            intent_stage="constructed",
        )
        
        # Mock venue gate and client
        with patch('merid.event_venues.kalshi.order_router.get_venue_gate') as mock_gate:
            mock_gate.return_value.mode = "paper"
            mock_gate.return_value.should_simulate_fill.return_value = True
            
            with patch('merid.event_venues.kalshi.client.get_kalshi_client') as mock_client:
                mock_client.return_value = None  # Paper mode doesn't need client
                
                # Route order
                result = await route_order_async(intent)
                
                # Should not be rejected due to intent validation
                # (may be rejected for other reasons, but not intent validation)
                if result.status == "rejected":
                    assert "intent_validation_failed" not in result.reason


class TestEndToEndAuditChain:
    """End-to-end tests for the complete audit chain."""
    
    def test_complete_audit_chain_from_signal_to_fill(self):
        """Test complete audit chain: signal -> intent -> order -> fill."""
        # Step 1: Create signal snapshot
        snapshot = create_signal_snapshot(
            signal_id="sig-1721476800-BTC",
            market_id="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            intent="open",
            edge=0.05,
            confidence=0.75,
            origin_agent="agent_grid_15m",
            origin_strategy="momentum_fvg",
            timeframe_label="15m",
            raw_features={"velocity": 0.01},
        )
        
        # Step 2: Create intent with audit chain
        intent = OrderIntent(
            ticker="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            price_cents=42,
            count=1,
            source="merid.prediction.agent_grid_15m",
            agent_id="agent_grid_15m",
            source_signal_id=snapshot.signal_id,
            source_signal_hash=snapshot.signal_hash,
            intent_stage="validated",
        )
        
        # Step 3: Simulate order execution
        order_id = "order-xyz"
        fill_ids = ["fill-1", "fill-2"]
        
        # Step 4: Verify audit chain
        from merid.validation.reconciliation import get_intent_reconciler
        reconciler = get_intent_reconciler()
        
        result = reconciler.verify_audit_chain(
            signal_id=snapshot.signal_id,
            intent_id=intent.intent_id,
            order_id=order_id,
            fill_ids=fill_ids,
        )
        
        assert result.is_valid is True
        assert result.audit_chain["signal_id"] == snapshot.signal_id
        assert result.audit_chain["signal_hash"] == snapshot.signal_hash
        assert result.audit_chain["order_id"] == order_id
        assert result.audit_chain["fill_ids"] == fill_ids
        assert "fill_chain_hash" in result.audit_chain
    
    def test_audit_chain_detects_broken_link(self):
        """Test that audit chain detects broken links."""
        # Create snapshot
        snapshot = create_signal_snapshot(
            signal_id="sig-1721476800-BTC",
            market_id="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            intent="open",
            edge=0.05,
            confidence=0.75,
            origin_agent="agent_grid_15m",
            origin_strategy="momentum_fvg",
            timeframe_label="15m",
            raw_features={},
        )
        
        # Try to verify with wrong signal ID
        from merid.validation.reconciliation import get_intent_reconciler
        reconciler = get_intent_reconciler()
        
        result = reconciler.verify_audit_chain(
            signal_id="sig-wrong-id",  # Wrong signal ID
            intent_id="intent-abc",
        )
        
        assert result.is_valid is False
        assert any("not found" in error.lower() for error in result.errors)
