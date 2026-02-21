"""Order Group Error Recovery — Patterns for common order group failures.

Provides error classification, remediation strategies, and recovery
actions for order group lifecycle management.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set
from enum import Enum, auto
from datetime import datetime, timezone

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.order_group_recovery")


class ErrorCode(Enum):
    """Order group error codes from Kalshi API."""
    INVALID_LIMIT = "invalid_limit"
    ORDER_GROUP_NOT_FOUND = "order_group_not_found"
    GROUP_TRIGGERED = "group_triggered"
    GROUP_ALREADY_ACTIVE = "group_already_active"
    ORDER_PLACEMENT_BLOCKED = "order_placement_blocked"
    CONTRACTS_LIMIT_EXCEEDED = "contracts_limit_exceeded"
    UNKNOWN_ERROR = "unknown_error"


class RecoveryAction(Enum):
    """Possible recovery actions."""
    REFRESH_GROUPS = auto()
    RESET_GROUP = auto()
    CREATE_NEW_GROUP = auto()
    RETRY_WITH_BACKOFF = auto()
    SKIP_AND_CONTINUE = auto()
    HALT_AND_ALERT = auto()


@dataclass
class ErrorClassification:
    """Classified error with metadata."""
    code: ErrorCode
    message: str
    is_retryable: bool
    suggested_action: RecoveryAction
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class RecoveryResult:
    """Result of a recovery attempt."""
    success: bool
    action_taken: RecoveryAction
    error_resolved: bool
    new_group_id: Optional[str] = None
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


class OrderGroupErrorClassifier:
    """Classifies order group errors and suggests remediation."""

    # Error patterns to codes
    ERROR_PATTERNS = {
        "invalid_limit": ErrorCode.INVALID_LIMIT,
        "contracts_limit": ErrorCode.INVALID_LIMIT,
        "order_group_not_found": ErrorCode.ORDER_GROUP_NOT_FOUND,
        "group not found": ErrorCode.ORDER_GROUP_NOT_FOUND,
        "unknown order group": ErrorCode.ORDER_GROUP_NOT_FOUND,
        "group_triggered": ErrorCode.GROUP_TRIGGERED,
        "already triggered": ErrorCode.GROUP_TRIGGERED,
        "group_already_active": ErrorCode.GROUP_ALREADY_ACTIVE,
        "already active": ErrorCode.GROUP_ALREADY_ACTIVE,
        "order_placement_blocked": ErrorCode.ORDER_PLACEMENT_BLOCKED,
        "blocked": ErrorCode.ORDER_PLACEMENT_BLOCKED,
        "contracts_limit_exceeded": ErrorCode.CONTRACTS_LIMIT_EXCEEDED,
        "limit exceeded": ErrorCode.CONTRACTS_LIMIT_EXCEEDED,
    }

    @classmethod
    def classify(cls, error_message: str, status_code: Optional[int] = None) -> ErrorClassification:
        """Classify an error message into a known error type.

        Args:
            error_message: Raw error message
            status_code: HTTP status code if available

        Returns:
            ErrorClassification with code and suggested action
        """
        msg_lower = error_message.lower()

        # Pattern matching
        for pattern, code in cls.ERROR_PATTERNS.items():
            if pattern in msg_lower:
                return cls._classification_for_code(code, error_message, status_code)

        # Status code fallback
        if status_code == 404:
            return cls._classification_for_code(ErrorCode.ORDER_GROUP_NOT_FOUND, error_message, status_code)
        elif status_code == 400:
            return cls._classification_for_code(ErrorCode.INVALID_LIMIT, error_message, status_code)
        elif status_code == 409:
            return cls._classification_for_code(ErrorCode.GROUP_TRIGGERED, error_message, status_code)

        return ErrorClassification(
            code=ErrorCode.UNKNOWN_ERROR,
            message=error_message,
            is_retryable=False,
            suggested_action=RecoveryAction.HALT_AND_ALERT,
        )

    @classmethod
    def _classification_for_code(
        cls,
        code: ErrorCode,
        message: str,
        status_code: Optional[int],
    ) -> ErrorClassification:
        """Get classification details for a known error code."""

        classifications = {
            ErrorCode.INVALID_LIMIT: ErrorClassification(
                code=code,
                message=message,
                is_retryable=False,
                suggested_action=RecoveryAction.SKIP_AND_CONTINUE,
                details={"status_code": status_code, "fix": "Clamp limit to valid range [1, 1_000_000]"},
            ),
            ErrorCode.ORDER_GROUP_NOT_FOUND: ErrorClassification(
                code=code,
                message=message,
                is_retryable=True,
                suggested_action=RecoveryAction.REFRESH_GROUPS,
                details={"status_code": status_code, "fix": "Refresh group list and use valid group ID"},
            ),
            ErrorCode.GROUP_TRIGGERED: ErrorClassification(
                code=code,
                message=message,
                is_retryable=False,
                suggested_action=RecoveryAction.RESET_GROUP,
                details={"status_code": status_code, "fix": "Reset group to re-arm before reuse"},
            ),
            ErrorCode.GROUP_ALREADY_ACTIVE: ErrorClassification(
                code=code,
                message=message,
                is_retryable=False,
                suggested_action=RecoveryAction.SKIP_AND_CONTINUE,
                details={"status_code": status_code, "fix": "Group is already active, no action needed"},
            ),
            ErrorCode.ORDER_PLACEMENT_BLOCKED: ErrorClassification(
                code=code,
                message=message,
                is_retryable=True,
                suggested_action=RecoveryAction.RETRY_WITH_BACKOFF,
                details={"status_code": status_code, "fix": "Retry with exponential backoff"},
            ),
            ErrorCode.CONTRACTS_LIMIT_EXCEEDED: ErrorClassification(
                code=code,
                message=message,
                is_retryable=False,
                suggested_action=RecoveryAction.SKIP_AND_CONTINUE,
                details={"status_code": status_code, "fix": "Reduce order size or create new group"},
            ),
            ErrorCode.UNKNOWN_ERROR: ErrorClassification(
                code=code,
                message=message,
                is_retryable=False,
                suggested_action=RecoveryAction.HALT_AND_ALERT,
                details={"status_code": status_code, "fix": "Manual intervention required"},
            ),
        }

        return classifications.get(code, classifications[ErrorCode.UNKNOWN_ERROR])


class OrderGroupRecoveryManager:
    """Manages error recovery for order groups.

    Provides automatic remediation for common order group errors.
    """

    def __init__(self, client):
        self.client = client
        self.classifier = OrderGroupErrorClassifier()
        self._recovery_attempts: Dict[str, int] = {}
        self._max_recovery_attempts = 3
        self._on_recovery_callbacks: List[Callable[[ErrorClassification, RecoveryResult], None]] = []

    # ═══════════════════════════════════════════════════════════════════════
    # Recovery Actions
    # ═══════════════════════════════════════════════════════════════════════

    async def attempt_recovery(
        self,
        group_id: Optional[str],
        error_message: str,
        status_code: Optional[int] = None,
    ) -> RecoveryResult:
        """Attempt to recover from an order group error.

        Args:
            group_id: Order group ID (if applicable)
            error_message: Raw error message
            status_code: HTTP status code

        Returns:
            RecoveryResult with action taken and outcome
        """
        # Classify the error
        classification = self.classifier.classify(error_message, status_code)

        # Track recovery attempts
        attempt_key = f"{group_id or 'unknown'}:{classification.code.value}"
        self._recovery_attempts[attempt_key] = self._recovery_attempts.get(attempt_key, 0) + 1

        if self._recovery_attempts[attempt_key] > self._max_recovery_attempts:
            return RecoveryResult(
                success=False,
                action_taken=RecoveryAction.HALT_AND_ALERT,
                error_resolved=False,
                message=f"Max recovery attempts ({self._max_recovery_attempts}) exceeded",
            )

        # Execute suggested action
        action = classification.suggested_action
        result = await self._execute_action(action, group_id, classification)

        # Notify callbacks
        for callback in self._on_recovery_callbacks:
            try:
                callback(classification, result)
            except Exception as e:
                logger.error(f"Error in recovery callback: {e}")

        return result

    async def _execute_action(
        self,
        action: RecoveryAction,
        group_id: Optional[str],
        classification: ErrorClassification,
    ) -> RecoveryResult:
        """Execute a recovery action."""

        action_handlers = {
            RecoveryAction.REFRESH_GROUPS: self._refresh_groups,
            RecoveryAction.RESET_GROUP: self._reset_group,
            RecoveryAction.CREATE_NEW_GROUP: self._create_new_group,
            RecoveryAction.RETRY_WITH_BACKOFF: self._retry_with_backoff,
            RecoveryAction.SKIP_AND_CONTINUE: self._skip_and_continue,
            RecoveryAction.HALT_AND_ALERT: self._halt_and_alert,
        }

        handler = action_handlers.get(action, self._halt_and_alert)
        return await handler(group_id, classification)

    async def _refresh_groups(
        self,
        group_id: Optional[str],
        classification: ErrorClassification,
    ) -> RecoveryResult:
        """Refresh group list and return new available groups."""
        try:
            result = await self.client.get_order_groups(limit=200)
            if result.success:
                groups = result.data or []
                return RecoveryResult(
                    success=True,
                    action_taken=RecoveryAction.REFRESH_GROUPS,
                    error_resolved=True,
                    message=f"Refreshed {len(groups)} groups from API",
                    details={"group_count": len(groups)},
                )
            else:
                return RecoveryResult(
                    success=False,
                    action_taken=RecoveryAction.REFRESH_GROUPS,
                    error_resolved=False,
                    message=f"Failed to refresh groups: {result.error}",
                )
        except Exception as e:
            return RecoveryResult(
                success=False,
                action_taken=RecoveryAction.REFRESH_GROUPS,
                error_resolved=False,
                message=f"Exception during refresh: {e}",
            )

    async def _reset_group(
        self,
        group_id: Optional[str],
        classification: ErrorClassification,
    ) -> RecoveryResult:
        """Reset a triggered group to re-arm it."""
        if not group_id:
            return RecoveryResult(
                success=False,
                action_taken=RecoveryAction.RESET_GROUP,
                error_resolved=False,
                message="Cannot reset: no group_id provided",
            )

        try:
            result = await self.client.reset_order_group_endpoint(group_id)
            if result.success:
                return RecoveryResult(
                    success=True,
                    action_taken=RecoveryAction.RESET_GROUP,
                    error_resolved=True,
                    message=f"Successfully reset group {group_id}",
                )
            else:
                return RecoveryResult(
                    success=False,
                    action_taken=RecoveryAction.RESET_GROUP,
                    error_resolved=False,
                    message=f"Failed to reset group: {result.error}",
                )
        except Exception as e:
            return RecoveryResult(
                success=False,
                action_taken=RecoveryAction.RESET_GROUP,
                error_resolved=False,
                message=f"Exception during reset: {e}",
            )

    async def _create_new_group(
        self,
        group_id: Optional[str],
        classification: ErrorClassification,
    ) -> RecoveryResult:
        """Create a new order group as fallback."""
        try:
            result = await self.client.create_order_group(
                name=f"auto_created_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
                max_cost_cents=100000,  # Default $1000
            )
            if result.success:
                new_group_id = result.data
                return RecoveryResult(
                    success=True,
                    action_taken=RecoveryAction.CREATE_NEW_GROUP,
                    error_resolved=True,
                    new_group_id=new_group_id,
                    message=f"Created new group {new_group_id}",
                )
            else:
                return RecoveryResult(
                    success=False,
                    action_taken=RecoveryAction.CREATE_NEW_GROUP,
                    error_resolved=False,
                    message=f"Failed to create new group: {result.error}",
                )
        except Exception as e:
            return RecoveryResult(
                success=False,
                action_taken=RecoveryAction.CREATE_NEW_GROUP,
                error_resolved=False,
                message=f"Exception during create: {e}",
            )

    async def _retry_with_backoff(
        self,
        group_id: Optional[str],
        classification: ErrorClassification,
    ) -> RecoveryResult:
        """Suggest retry with exponential backoff."""
        import asyncio

        attempt = self._recovery_attempts.get(f"{group_id or 'unknown'}:{classification.code.value}", 1)
        delay = min(2 ** attempt, 60)  # Exponential backoff capped at 60s

        await asyncio.sleep(delay)

        return RecoveryResult(
            success=True,
            action_taken=RecoveryAction.RETRY_WITH_BACKOFF,
            error_resolved=False,  # Caller should retry
            message=f"Waited {delay}s before retry",
            details={"retry_delay_seconds": delay, "attempt": attempt},
        )

    async def _skip_and_continue(
        self,
        group_id: Optional[str],
        classification: ErrorClassification,
    ) -> RecoveryResult:
        """Skip this operation and continue with next."""
        return RecoveryResult(
            success=True,
            action_taken=RecoveryAction.SKIP_AND_CONTINUE,
            error_resolved=True,  # Resolved by skipping
            message="Skipped operation and continuing",
        )

    async def _halt_and_alert(
        self,
        group_id: Optional[str],
        classification: ErrorClassification,
    ) -> RecoveryResult:
        """Halt operations and alert for manual intervention."""
        logger.critical(
            f"[order-group-recovery] HALT: Unrecoverable error for group {group_id}: "
            f"{classification.message}"
        )
        return RecoveryResult(
            success=False,
            action_taken=RecoveryAction.HALT_AND_ALERT,
            error_resolved=False,
            message="Halted for manual intervention",
            details={"classification": classification},
        )

    # ═══════════════════════════════════════════════════════════════════════
    # Utility Methods
    # ═══════════════════════════════════════════════════════════════════════

    def on_recovery(
        self,
        callback: Callable[[ErrorClassification, RecoveryResult], None],
    ) -> None:
        """Register callback for recovery attempts.

        Args:
            callback: Function(classification, result) to call
        """
        self._on_recovery_callbacks.append(callback)

    def reset_attempt_counter(self, group_id: Optional[str] = None) -> None:
        """Reset recovery attempt counter for a group.

        Args:
            group_id: Group to reset (None = reset all)
        """
        if group_id:
            keys_to_remove = [k for k in self._recovery_attempts if k.startswith(f"{group_id}:")]
            for key in keys_to_remove:
                del self._recovery_attempts[key]
        else:
            self._recovery_attempts.clear()

    def get_recovery_stats(self) -> Dict[str, Any]:
        """Get recovery attempt statistics."""
        return {
            "total_attempts": sum(self._recovery_attempts.values()),
            "attempts_by_group": dict(self._recovery_attempts),
            "max_attempts": self._max_recovery_attempts,
        }
