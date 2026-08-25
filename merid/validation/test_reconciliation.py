"""Unit tests for IntentReconciler module.

Tests the reconciliation and audit chain validation logic.
Follows testing best practices: valid construction, invariant violations,
edge cases, and contract tests.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from merid.validation.reconciliation import (
    IntentReconciler,
    ReconciliationResult,
    get_intent_reconciler,
)
from merid.validation.signal_snapshot import (
    SignalSnapshot,
    SignalSnapshotLedger,
    get_signal_snapshot_ledger,
)


class TestReconciliationResult:
    """Test ReconciliationResult dataclass."""
    
    def test_valid_result_construction(self):
        """Test valid result construction."""
        result = ReconciliationResult(
            is_valid=True,
            errors=[],
            warnings=[],
            audit_chain={"signal_id": "sig-123"},
        )
        
        assert result.is_valid is True
        assert result.errors == []
        assert result.warnings == []
        assert result.audit_chain == {"signal_id": "sig-123"}
    
    def test_invalid_result_construction(self):
        """Test invalid result construction with errors."""
        result = ReconciliationResult(
            is_valid=False,
            errors=["signal_not_found", "hash_mismatch"],
            warnings=["order_id_missing"],
            audit_chain={},
        )
        
        assert result.is_valid is False
        assert result.errors == ["signal_not_found", "hash_mismatch"]
        assert result.warnings == ["order_id_missing"]
    
    def test_add_error(self):
        """Test adding an error to result."""
        result = ReconciliationResult(
            is_valid=True,
            errors=[],
            warnings=[],
            audit_chain={},
        )
        
        result.add_error("new_error")
        
        assert result.is_valid is False
        assert "new_error" in result.errors
    
    def test_add_warning(self):
        """Test adding a warning to result."""
        result = ReconciliationResult(
            is_valid=True,
            errors=[],
            warnings=[],
            audit_chain={},
        )
        
        result.add_warning("new_warning")
        
        assert result.is_valid is True  # Warnings don't invalidate
        assert "new_warning" in result.warnings


class TestIntentReconciler:
    """Test IntentReconciler class."""
    
    def test_singleton_instance(self):
        """Reconciler should be a singleton."""
        reconciler1 = get_intent_reconciler()
        reconciler2 = get_intent_reconciler()
        
        assert reconciler1 is reconciler2
    
    def test_verify_audit_chain_missing_signal(self):
        """Test verification fails when signal not found."""
        reconciler = IntentReconciler()
        
        result = reconciler.verify_audit_chain(
            signal_id="sig-unknown",
            intent_id="intent-abc",
        )
        
        assert result.is_valid is False
        assert any("not found" in error.lower() for error in result.errors)
    
    def test_verify_audit_chain_valid_signal(self):
        """Test verification passes for valid signal."""
        reconciler = IntentReconciler()
        
        # Create a snapshot
        snapshot = SignalSnapshot(
            snapshot_id="snap-123",
            signal_id="sig-123",
            signal_hash="abc123def4567890" * 4,
            market_id="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            intent="open",
            edge=0.05,
            confidence=0.75,
            origin_agent="agent_grid_15m",
            origin_strategy="momentum_fvg",
            timeframe_label="15m",
            created_ts=1721476800.0,
            raw_features={},
        )
        
        ledger = get_signal_snapshot_ledger()
        ledger.record_snapshot(snapshot)
        
        result = reconciler.verify_audit_chain(
            signal_id="sig-123",
            intent_id="intent-abc",
        )
        
        assert result.is_valid is True
        assert result.audit_chain["signal_id"] == "sig-123"
        assert result.audit_chain["signal_hash"] == snapshot.signal_hash
        assert result.audit_chain["snapshot_id"] == "snap-123"
    
    def test_verify_audit_chain_with_order_id(self):
        """Test verification with order ID."""
        reconciler = IntentReconciler()
        
        snapshot = SignalSnapshot(
            snapshot_id="snap-123",
            signal_id="sig-123",
            signal_hash="abc123def4567890" * 4,
            market_id="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            intent="open",
            edge=0.05,
            confidence=0.75,
            origin_agent="agent_grid_15m",
            origin_strategy="momentum_fvg",
            timeframe_label="15m",
            created_ts=1721476800.0,
            raw_features={},
        )
        
        ledger = get_signal_snapshot_ledger()
        ledger.record_snapshot(snapshot)
        
        result = reconciler.verify_audit_chain(
            signal_id="sig-123",
            intent_id="intent-abc",
            order_id="order-xyz",
        )
        
        assert result.is_valid is True
        assert result.audit_chain["order_id"] == "order-xyz"
    
    def test_verify_audit_chain_with_fill_ids(self):
        """Test verification with fill IDs."""
        reconciler = IntentReconciler()
        
        snapshot = SignalSnapshot(
            snapshot_id="snap-123",
            signal_id="sig-123",
            signal_hash="abc123def4567890" * 4,
            market_id="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            intent="open",
            edge=0.05,
            confidence=0.75,
            origin_agent="agent_grid_15m",
            origin_strategy="momentum_fvg",
            timeframe_label="15m",
            created_ts=1721476800.0,
            raw_features={},
        )
        
        ledger = get_signal_snapshot_ledger()
        ledger.record_snapshot(snapshot)
        
        result = reconciler.verify_audit_chain(
            signal_id="sig-123",
            intent_id="intent-abc",
            order_id="order-xyz",
            fill_ids=["fill-1", "fill-2"],
        )
        
        assert result.is_valid is True
        assert result.audit_chain["fill_ids"] == ["fill-1", "fill-2"]
    
    def test_verify_audit_chain_computes_fill_chain_hash(self):
        """Test that fill chain hash is computed when all components present."""
        reconciler = IntentReconciler()
        
        snapshot = SignalSnapshot(
            snapshot_id="snap-123",
            signal_id="sig-123",
            signal_hash="abc123def4567890" * 4,
            market_id="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            intent="open",
            edge=0.05,
            confidence=0.75,
            origin_agent="agent_grid_15m",
            origin_strategy="momentum_fvg",
            timeframe_label="15m",
            created_ts=1721476800.0,
            raw_features={},
        )
        
        ledger = get_signal_snapshot_ledger()
        ledger.record_snapshot(snapshot)
        
        result = reconciler.verify_audit_chain(
            signal_id="sig-123",
            intent_id="intent-abc",
            order_id="order-xyz",
            fill_ids=["fill-1", "fill-2"],
        )
        
        assert result.is_valid is True
        assert "fill_chain_hash" in result.audit_chain
        assert len(result.audit_chain["fill_chain_hash"]) == 64  # SHA256 hex
    
    def test_verify_audit_chain_warning_no_order_id(self):
        """Test warning when order ID is missing."""
        reconciler = IntentReconciler()
        
        snapshot = SignalSnapshot(
            snapshot_id="snap-123",
            signal_id="sig-123",
            signal_hash="abc123def4567890" * 4,
            market_id="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            intent="open",
            edge=0.05,
            confidence=0.75,
            origin_agent="agent_grid_15m",
            origin_strategy="momentum_fvg",
            timeframe_label="15m",
            created_ts=1721476800.0,
            raw_features={},
        )
        
        ledger = get_signal_snapshot_ledger()
        ledger.record_snapshot(snapshot)
        
        result = reconciler.verify_audit_chain(
            signal_id="sig-123",
            intent_id="intent-abc",
        )
        
        assert result.is_valid is True
        assert any("order" in warning.lower() for warning in result.warnings)
    
    def test_query_round_trips_with_intent_drift_no_monitor(self):
        """Test query returns empty when monitor not available."""
        reconciler = IntentReconciler()
        
        # Mock the monitor to return None
        with patch.object(reconciler, '_get_round_trip_monitor', return_value=None):
            drifted = reconciler.query_round_trips_with_intent_drift()
            
            assert drifted == []
    
    def test_query_policy_violation_exits_no_monitor(self):
        """Test query returns empty when monitor not available."""
        reconciler = IntentReconciler()
        
        # Mock the monitor to return None
        with patch.object(reconciler, '_get_round_trip_monitor', return_value=None):
            violations = reconciler.query_policy_violation_exits()
            
            assert violations == []
    
    def test_detect_structural_errors_no_monitor(self):
        """Test detection returns empty when monitor not available."""
        reconciler = IntentReconciler()
        
        # Mock the monitor to return None
        with patch.object(reconciler, '_get_round_trip_monitor', return_value=None):
            errors = reconciler.detect_structural_errors()
            
            assert errors == []
    
    def test_detect_structural_errors_no_fills_ledger(self):
        """Test detection continues when fills ledger not available."""
        reconciler = IntentReconciler()
        
        # Mock both to return None
        with patch.object(reconciler, '_get_round_trip_monitor', return_value=None):
            with patch.object(reconciler, '_get_fills_ledger', return_value=None):
                errors = reconciler.detect_structural_errors()
                
                assert errors == []
    
    def test_separate_strategy_vs_plumbing_errors(self):
        """Test separation of strategy and plumbing errors."""
        reconciler = IntentReconciler()
        
        # Mock to return empty lists
        with patch.object(reconciler, 'query_policy_violation_exits', return_value=[]):
            with patch.object(reconciler, 'query_round_trips_with_intent_drift', return_value=[]):
                with patch.object(reconciler, 'detect_structural_errors', return_value=[]):
                    strategy_errors, plumbing_errors = reconciler.separate_strategy_vs_plumbing_errors()
                    
                    assert strategy_errors == []
                    assert plumbing_errors == []
    
    def test_separate_strategy_vs_plumbing_with_data(self):
        """Test separation with actual error data."""
        reconciler = IntentReconciler()
        
        # Mock to return sample data
        policy_violations = [
            {"type": "policy_violation", "asset": "BTC", "realized_pnl_cents": -50}
        ]
        
        intent_drifts = [
            {"type": "intent_drift", "asset": "ETH", "realized_pnl_cents": -30}
        ]
        
        structural_errors = [
            {"type": "structural_error", "intent_id": "intent-abc"}
        ]
        
        with patch.object(reconciler, 'query_policy_violation_exits', return_value=policy_violations):
            with patch.object(reconciler, 'query_round_trips_with_intent_drift', return_value=intent_drifts):
                with patch.object(reconciler, 'detect_structural_errors', return_value=structural_errors):
                    strategy_errors, plumbing_errors = reconciler.separate_strategy_vs_plumbing_errors()
                    
                    assert len(strategy_errors) == 2  # policy + drift
                    assert len(plumbing_errors) == 1  # structural
                    # The actual implementation returns the original types, not wrapped
                    assert all(e["type"] in ["policy_violation", "intent_drift"] for e in strategy_errors)
                    assert all(e["type"] == "structural_error" for e in plumbing_errors)
