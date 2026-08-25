"""Intent Validator - Signal-to-intent consistency verification.

This module provides midstream verification between signal snapshots and
order intents, ensuring no drift occurs during transformation.

Key validations:
- source_signal_id must exist in snapshot ledger
- source_signal_hash must match stored SignalSnapshot.signal_hash
- Intent fields must be consistent with signal (no silent drift)
- Intent stage transitions must follow proper sequence
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from enum import Enum

from utils.logger import get_logger

logger = get_logger("merid.validation.intent_validator")


class IntentValidationError(str, Enum):
    """Types of intent validation errors."""
    SIGNAL_NOT_FOUND = "signal_not_found"
    SIGNAL_HASH_MISMATCH = "signal_hash_mismatch"
    SIDE_DRIFT = "side_drift"
    ACTION_DRIFT = "action_drift"
    INTENT_TYPE_DRIFT = "intent_type_drift"
    MARKET_MISMATCH = "market_mismatch"
    MISSING_OVERRIDE_REASON = "missing_override_reason"
    INVALID_STAGE_TRANSITION = "invalid_stage_transition"
    MISSING_REQUIRED_FIELDS = "missing_required_fields"


@dataclass
class ValidationResult:
    """Result of intent validation."""
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    override_reason: Optional[str] = None
    
    def add_error(self, error_type: IntentValidationError, message: str) -> None:
        """Add an error to the validation result."""
        self.errors.append(f"[{error_type.value}] {message}")
        self.is_valid = False
    
    def add_warning(self, message: str) -> None:
        """Add a warning to the validation result."""
        self.warnings.append(message)


class IntentValidator:
    """Validates OrderIntent against source SignalSnapshot.
    
    This validator ensures that the intent being submitted for execution
    is consistent with the original signal that generated it. Any drift
    must be explicitly documented with an override reason.
    """
    
    # Valid stage transitions
    _VALID_TRANSITIONS = {
        "constructed": ["validated", "rejected"],
        "validated": ["submitted", "rejected"],
        "submitted": ["executed", "rejected", "cancelled"],
        "executed": [],  # Terminal state
        "rejected": [],  # Terminal state
        "cancelled": [],  # Terminal state
    }
    
    def __init__(self):
        # Lazy import to avoid circular dependency
        self._snapshot_ledger = None
    
    def _get_snapshot_ledger(self):
        """Get the signal snapshot ledger singleton."""
        if self._snapshot_ledger is None:
            from merid.validation.signal_snapshot import get_signal_snapshot_ledger
            self._snapshot_ledger = get_signal_snapshot_ledger()
        return self._snapshot_ledger
    
    def validate_intent(
        self,
        intent: Any,
        override_reason: Optional[str] = None,
    ) -> ValidationResult:
        """Validate an OrderIntent against its source signal.
        
        Args:
            intent: OrderIntent to validate
            override_reason: Optional reason for allowing intentional drift
        
        Returns:
            ValidationResult with errors/warnings
        """
        result = ValidationResult(is_valid=True, errors=[], warnings=[])
        
        # Check required hash chain fields
        if not intent.source_signal_id:
            result.add_error(
                IntentValidationError.MISSING_REQUIRED_FIELDS,
                "source_signal_id is required for intent verification"
            )
            return result
        
        if not intent.source_signal_hash:
            result.add_error(
                IntentValidationError.MISSING_REQUIRED_FIELDS,
                "source_signal_hash is required for intent verification"
            )
            return result
        
        # Verify signal exists in ledger
        ledger = self._get_snapshot_ledger()
        snapshots = ledger.get_by_signal_id(intent.source_signal_id)
        
        if not snapshots:
            result.add_error(
                IntentValidationError.SIGNAL_NOT_FOUND,
                f"Signal {intent.source_signal_id} not found in snapshot ledger"
            )
            return result
        
        # Get the latest snapshot
        latest_snapshot = ledger.get_latest_snapshot(intent.source_signal_id)
        
        if latest_snapshot is None:
            result.add_error(
                IntentValidationError.SIGNAL_NOT_FOUND,
                f"No valid snapshot found for signal {intent.source_signal_id}"
            )
            return result
        
        # Verify signal hash matches
        if latest_snapshot.signal_hash != intent.source_signal_hash:
            result.add_error(
                IntentValidationError.SIGNAL_HASH_MISMATCH,
                f"Signal hash mismatch: expected {latest_snapshot.signal_hash}, got {intent.source_signal_hash}"
            )
            return result
        
        # Check for drift between signal and intent
        self._check_market_consistency(intent, latest_snapshot, result, override_reason)
        self._check_side_consistency(intent, latest_snapshot, result, override_reason)
        self._check_action_consistency(intent, latest_snapshot, result, override_reason)
        self._check_intent_type_consistency(intent, latest_snapshot, result, override_reason)
        
        # Validate stage transition
        self._validate_stage_transition(intent, result)
        
        # Compute and set intent_hash if not already set
        if not intent.intent_hash:
            from merid.event_venues.kalshi.order_router import compute_intent_hash
            intent.intent_hash = compute_intent_hash(
                ticker=intent.ticker,
                side=intent.side,
                action=intent.action,
                price_cents=intent.price_cents,
                count=intent.count,
                order_type=intent.order_type,
                time_in_force=intent.time_in_force,
            )
            logger.debug(f"[INTENT-VALIDATOR] Computed intent_hash: {intent.intent_hash}")
        
        # Update intent stage
        if result.is_valid:
            intent.intent_stage = "validated"
            logger.info(
                f"[INTENT-VALIDATOR] Intent validated: intent_id={intent.intent_id} "
                f"signal_id={intent.source_signal_id} stage={intent.intent_stage}"
            )
        else:
            intent.intent_stage = "rejected"
            logger.warning(
                f"[INTENT-VALIDATOR] Intent rejected: intent_id={intent.intent_id} "
                f"signal_id={intent.source_signal_id} errors={result.errors}"
            )
        
        return result
    
    def _check_market_consistency(
        self,
        intent: Any,
        snapshot: Any,
        result: ValidationResult,
        override_reason: Optional[str],
    ) -> None:
        """Check that market/ticker is consistent between signal and intent."""
        # Signal has market_id, intent has ticker - they should match
        # Allow ticker to be more specific (e.g., market_id="KXBTC15M", ticker="KXBTC15M-26JUL201730-30")
        if not intent.ticker.startswith(snapshot.market_id):
            if override_reason:
                result.add_warning(
                    f"Market drift: signal market_id={snapshot.market_id}, "
                    f"intent ticker={intent.ticker} (override: {override_reason})"
                )
            else:
                result.add_error(
                    IntentValidationError.MARKET_MISMATCH,
                    f"Market drift without override: signal market_id={snapshot.market_id}, "
                    f"intent ticker={intent.ticker}"
                )
    
    def _check_side_consistency(
        self,
        intent: Any,
        snapshot: Any,
        result: ValidationResult,
        override_reason: Optional[str],
    ) -> None:
        """Check that side is consistent between signal and intent."""
        if intent.side != snapshot.side:
            if override_reason:
                result.add_warning(
                    f"Side drift: signal side={snapshot.side}, "
                    f"intent side={intent.side} (override: {override_reason})"
                )
            else:
                result.add_error(
                    IntentValidationError.SIDE_DRIFT,
                    f"Side drift without override: signal side={snapshot.side}, "
                    f"intent side={intent.side}"
                )
    
    def _check_action_consistency(
        self,
        intent: Any,
        snapshot: Any,
        result: ValidationResult,
        override_reason: Optional[str],
    ) -> None:
        """Check that action is consistent with signal intent type."""
        # Signal intent "open" should map to action "buy"
        # Signal intent "close" should map to action "sell"
        # Signal action should match intent action
        if intent.action != snapshot.action:
            if override_reason:
                result.add_warning(
                    f"Action drift: signal action={snapshot.action}, "
                    f"intent action={intent.action} (override: {override_reason})"
                )
            else:
                result.add_error(
                    IntentValidationError.ACTION_DRIFT,
                    f"Action drift without override: signal action={snapshot.action}, "
                    f"intent action={intent.action}"
                )
    
    def _check_intent_type_consistency(
        self,
        intent: Any,
        snapshot: Any,
        result: ValidationResult,
        override_reason: Optional[str],
    ) -> None:
        """Check that intent type (entry/exit) is consistent with signal intent."""
        # Signal intent "open" should be entry order
        # Signal intent "close" should be exit order
        # This is a higher-level check that may need additional context
        signal_intent = snapshot.intent  # "open", "close", "scale_in", "scale_out"
        
        # Map signal intent to expected entry_or_exit
        expected_direction = None
        if signal_intent in ("open", "scale_in"):
            expected_direction = "entry"
        elif signal_intent in ("close", "scale_out"):
            expected_direction = "exit"
        
        if expected_direction and intent.entry_or_exit:
            if intent.entry_or_exit != expected_direction:
                if override_reason:
                    result.add_warning(
                        f"Intent type drift: signal intent={signal_intent} (expected {expected_direction}), "
                        f"intent entry_or_exit={intent.entry_or_exit} (override: {override_reason})"
                    )
                else:
                    result.add_error(
                        IntentValidationError.INTENT_TYPE_DRIFT,
                        f"Intent type drift without override: signal intent={signal_intent} "
                        f"(expected {expected_direction}), intent entry_or_exit={intent.entry_or_exit}"
                    )
    
    def _validate_stage_transition(self, intent: Any, result: ValidationResult) -> None:
        """Validate that the intent stage transition is valid."""
        current_stage = intent.intent_stage
        target_stage = "validated"  # We're validating, so target is "validated"
        
        valid_transitions = self._VALID_TRANSITIONS.get(current_stage, [])
        
        if target_stage not in valid_transitions:
            result.add_error(
                IntentValidationError.INVALID_STAGE_TRANSITION,
                f"Invalid stage transition: {current_stage} -> {target_stage} "
                f"(valid: {valid_transitions})"
            )


# Global singleton instance
_validator: Optional[IntentValidator] = None


def get_intent_validator() -> IntentValidator:
    """Get the global intent validator singleton."""
    global _validator
    if _validator is None:
        _validator = IntentValidator()
    return _validator
