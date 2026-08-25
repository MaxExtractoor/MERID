"""Unit tests for IntentValidator module.

Tests the intent-to-signal consistency validation logic.
Follows testing best practices: valid construction, invariant violations,
edge cases, and contract tests.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from merid.validation.intent_validator import (
    IntentValidator,
    IntentValidationError,
    ValidationResult,
    get_intent_validator,
)
from merid.validation.signal_snapshot import (
    SignalSnapshot,
    SignalSnapshotLedger,
    get_signal_snapshot_ledger,
)


class TestValidationResult:
    """Test ValidationResult dataclass."""
    
    def test_valid_result_construction(self):
        """Test valid result construction."""
        result = ValidationResult(is_valid=True, errors=[], warnings=[])
        
        assert result.is_valid is True
        assert result.errors == []
        assert result.warnings == []
    
    def test_invalid_result_construction(self):
        """Test invalid result construction with errors."""
        result = ValidationResult(
            is_valid=False,
            errors=["hash_mismatch", "side_drift"],
            warnings=["override_reason_missing"],
        )
        
        assert result.is_valid is False
        assert result.errors == ["hash_mismatch", "side_drift"]
        assert result.warnings == ["override_reason_missing"]
    
    def test_add_error(self):
        """Test adding an error to result."""
        result = ValidationResult(is_valid=True, errors=[], warnings=[])
        
        result.add_error(IntentValidationError.SIGNAL_NOT_FOUND, "new_error")
        
        assert result.is_valid is False
        assert "[signal_not_found] new_error" in result.errors
    
    def test_add_warning(self):
        """Test adding a warning to result."""
        result = ValidationResult(is_valid=True, errors=[], warnings=[])
        
        result.add_warning("new_warning")
        
        assert result.is_valid is True  # Warnings don't invalidate
        assert "new_warning" in result.warnings


class TestIntentValidator:
    """Test IntentValidator class."""
    
    def test_singleton_instance(self):
        """Validator should be a singleton."""
        validator1 = get_intent_validator()
        validator2 = get_intent_validator()
        
        assert validator1 is validator2
    
    def test_validate_intent_missing_signal_id(self):
        """Test validation fails when signal_id is missing."""
        validator = IntentValidator()
        
        # Create a mock OrderIntent without signal_id
        intent = MagicMock()
        intent.source_signal_id = None
        intent.source_signal_hash = "abc123"
        intent.intent_id = "intent_abc"
        intent.intent_stage = "constructed"
        
        result = validator.validate_intent(intent)
        
        assert result.is_valid is False
        assert any("signal_id" in error.lower() for error in result.errors)
    
    def test_validate_intent_missing_signal_hash(self):
        """Test validation fails when signal_hash is missing."""
        validator = IntentValidator()
        
        intent = MagicMock()
        intent.source_signal_id = "sig-123"
        intent.source_signal_hash = None
        intent.intent_id = "intent_abc"
        intent.intent_stage = "constructed"
        
        result = validator.validate_intent(intent)
        
        assert result.is_valid is False
        assert any("signal_hash" in error.lower() for error in result.errors)
    
    def test_validate_intent_signal_not_found_in_ledger(self):
        """Test validation fails when signal not found in ledger."""
        validator = IntentValidator()
        
        intent = MagicMock()
        intent.source_signal_id = "sig-unknown"
        intent.source_signal_hash = "abc123"
        intent.intent_id = "intent_abc"
        intent.intent_stage = "constructed"
        
        result = validator.validate_intent(intent)
        
        assert result.is_valid is False
        assert any("not found" in error.lower() for error in result.errors)
    
    def test_validate_intent_hash_mismatch(self):
        """Test validation fails when hash doesn't match."""
        validator = IntentValidator()
        
        # Create a snapshot with a specific hash
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
        
        # Add to global ledger
        ledger = get_signal_snapshot_ledger()
        ledger.record_snapshot(snapshot)
        
        # Create intent with wrong hash
        intent = MagicMock()
        intent.source_signal_id = "sig-123"
        intent.source_signal_hash = "wrong_hash_1234567890abcdef"
        intent.intent_id = "intent_abc"
        intent.intent_stage = "constructed"
        intent.entry_or_exit = "entry"
        
        result = validator.validate_intent(intent)
        
        assert result.is_valid is False
        assert any("hash" in error.lower() for error in result.errors)
    
    def test_validate_intent_market_drift_without_override(self):
        """Test validation fails when market drifts without override."""
        validator = IntentValidator()
        
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
        
        # Create intent with different market
        intent = MagicMock()
        intent.source_signal_id = "sig-123"
        intent.source_signal_hash = snapshot.signal_hash
        intent.intent_id = "intent_abc"
        intent.intent_stage = "constructed"
        intent.ticker = "KXETH15M-2026-07-20T14:00"  # Different market
        intent.side = "yes"
        intent.action = "buy"
        intent.entry_or_exit = "entry"
        intent.override_reason = None  # No override reason
        
        result = validator.validate_intent(intent)
        
        assert result.is_valid is False
        assert any("market" in error.lower() for error in result.errors)
    
    def test_validate_intent_market_drift_with_override(self):
        """Test validation passes when market drifts with override reason."""
        validator = IntentValidator()
        
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
        
        # Create intent with different market but with override
        intent = MagicMock()
        intent.source_signal_id = "sig-123"
        intent.source_signal_hash = snapshot.signal_hash
        intent.intent_id = "intent_abc"
        intent.intent_stage = "constructed"
        intent.ticker = "KXETH15M-2026-07-20T14:00"
        intent.side = "yes"
        intent.action = "buy"
        intent.entry_or_exit = "entry"
        intent.override_reason = "market_substitution"  # Valid override
        
        result = validator.validate_intent(intent, override_reason="market_substitution")
        
        assert result.is_valid is True
        assert any("market" in warning.lower() for warning in result.warnings)
    
    def test_validate_intent_side_drift_without_override(self):
        """Test validation fails when side drifts without override."""
        validator = IntentValidator()
        
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
        
        # Create intent with different side
        intent = MagicMock()
        intent.source_signal_id = "sig-123"
        intent.source_signal_hash = snapshot.signal_hash
        intent.intent_id = "intent_abc"
        intent.intent_stage = "constructed"
        intent.ticker = "KXBTC15M-2026-07-20T14:00"
        intent.side = "no"  # Different side
        intent.action = "buy"
        intent.entry_or_exit = "entry"
        intent.override_reason = None
        
        result = validator.validate_intent(intent)
        
        assert result.is_valid is False
        assert any("side" in error.lower() for error in result.errors)
    
    def test_validate_intent_action_drift_without_override(self):
        """Test validation fails when action drifts without override."""
        validator = IntentValidator()
        
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
        
        # Create intent with different action
        intent = MagicMock()
        intent.source_signal_id = "sig-123"
        intent.source_signal_hash = snapshot.signal_hash
        intent.intent_id = "intent_abc"
        intent.intent_stage = "constructed"
        intent.ticker = "KXBTC15M-2026-07-20T14:00"
        intent.side = "yes"
        intent.action = "sell"  # Different action
        intent.entry_or_exit = "entry"
        intent.override_reason = None
        
        result = validator.validate_intent(intent)
        
        assert result.is_valid is False
        assert any("action" in error.lower() for error in result.errors)
    
    def test_validate_intent_valid_construction(self):
        """Test validation passes for valid intent construction."""
        validator = IntentValidator()
        
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
        
        # Create valid intent
        intent = MagicMock()
        intent.source_signal_id = "sig-123"
        intent.source_signal_hash = snapshot.signal_hash
        intent.intent_id = "intent_abc"
        intent.intent_stage = "constructed"
        intent.ticker = "KXBTC15M-2026-07-20T14:00"
        intent.side = "yes"
        intent.action = "buy"
        intent.entry_or_exit = "entry"
        intent.override_reason = None
        
        result = validator.validate_intent(intent)
        
        assert result.is_valid is True
        assert result.errors == []
    
    def test_validate_stage_transition_constructed_to_validated(self):
        """Test valid stage transition: constructed -> validated."""
        validator = IntentValidator()
        
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
        
        intent = MagicMock()
        intent.source_signal_id = "sig-123"
        intent.source_signal_hash = snapshot.signal_hash
        intent.intent_id = "intent_abc"
        intent.intent_stage = "constructed"  # Current stage
        intent.ticker = "KXBTC15M-2026-07-20T14:00"
        intent.side = "yes"
        intent.action = "buy"
        intent.entry_or_exit = "entry"
        intent.override_reason = None
        
        # Simulate transition to validated by setting it after validation
        result = validator.validate_intent(intent)
        if result.is_valid:
            intent.intent_stage = "validated"
        
        assert result.is_valid is True
    
    def test_validate_stage_transition_invalid_skip(self):
        """Test invalid stage transition: constructed -> executed (skips validated)."""
        validator = IntentValidator()
        
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
        
        intent = MagicMock()
        intent.source_signal_id = "sig-123"
        intent.source_signal_hash = snapshot.signal_hash
        intent.intent_id = "intent_abc"
        intent.intent_stage = "executed"  # Invalid: skipped validated
        intent.ticker = "KXBTC15M-2026-07-20T14:00"
        intent.side = "yes"
        intent.action = "buy"
        intent.entry_or_exit = "entry"
        intent.override_reason = None
        
        result = validator.validate_intent(intent)
        
        assert result.is_valid is False
        assert any("stage" in error.lower() for error in result.errors)


class TestIntentValidationError:
    """Test IntentValidationError enum."""
    
    def test_error_values(self):
        """Test that error enum has expected values."""
        assert IntentValidationError.SIGNAL_NOT_FOUND.value == "signal_not_found"
        assert IntentValidationError.SIGNAL_HASH_MISMATCH.value == "signal_hash_mismatch"
        assert IntentValidationError.SIDE_DRIFT.value == "side_drift"
        assert IntentValidationError.ACTION_DRIFT.value == "action_drift"
