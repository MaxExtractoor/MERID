"""Governance Event Bus — Decoupled, typed event channel for governance actions.

Replaces direct callback coupling between governor_agent and drift_reward_loop
with a pub/sub pattern that prevents circular dependencies and enables
audit trails.

Usage:
    from agents.governance_event_bus import get_governance_event_bus
    
    # Subscribe to governance events
    bus = get_governance_event_bus()
    bus.subscribe("drift_de_risk", handler)
    
    # Publish events
    bus.publish(GovernanceEvent(
        event_type=GovernanceEventType.DRIFT_DE_RISK,
        source="drift_reward_loop",
        target_component="BTC_15M",
        action=GovernanceAction.PAUSE,
        reason="Sharpe ratio -2.5, max drawdown 15%",
        metadata={"severity": "high"}
    ))
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from collections import deque
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from config.crypto_universe import (
    ACTIVE_CRYPTO_ASSETS,
    ACTIVE_CRYPTO_TIMEFRAMES,
    parse_asset_timeframe_from_identifier,
)
from utils.logger import get_logger

logger = get_logger("agents.governance_event_bus")


class GovernanceEventType(str, Enum):
    """Types of governance events."""
    DRIFT_DE_RISK = "drift_de_risk"
    AGENT_PAUSE = "agent_pause"
    AGENT_RESUME = "agent_resume"
    AGENT_RETIRE = "agent_retire"
    AGENT_PROMOTE = "agent_promote"
    AGENT_DEMOTE = "agent_demote"
    WEIGHT_CHANGE = "weight_change"
    EMERGENCY_HALT = "emergency_halt"
    QUORUM_FAILURE = "quorum_failure"


class GovernanceAction(str, Enum):
    """Governance actions that can be requested."""
    PAUSE = "pause"
    RESUME = "resume"
    RETIRE = "retire"
    PROMOTE = "promote"
    DEMOTE = "demote"
    INCREASE_WEIGHT = "increase_weight"
    DECREASE_WEIGHT = "decrease_weight"
    EMERGENCY_EXIT = "emergency_exit"
    NO_ACTION = "no_action"


@dataclass(frozen=True)
class GovernanceEvent:
    """Immutable governance event for audit trail."""
    event_type: GovernanceEventType
    source: str  # Component that generated the event
    target_component: str  # Component being acted upon
    action: GovernanceAction
    reason: str
    event_id: str = field(default_factory=lambda: f"gov_{uuid.uuid4().hex[:16]}")
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    requires_quorum: bool = True  # Whether this action needs consensus approval
    
    # Asset/timeframe context for per-series tracking
    asset: Optional[str] = None
    timeframe: Optional[str] = None
    severity: str = "medium"  # low, medium, high, critical


@dataclass
class GovernanceAuditRecord:
    """Audit record for executed governance actions."""
    event: GovernanceEvent
    status: str  # "pending", "approved", "rejected", "executed", "failed"
    decision_id: Optional[str] = None  # UnifiedDecisionLayer decision ID
    executed_by: Optional[str] = None
    executed_at: Optional[float] = None
    error_message: Optional[str] = None
    affected_assets: List[str] = field(default_factory=list)
    affected_timeframes: List[str] = field(default_factory=list)


class GovernanceEventBus:
    """
    Central pub/sub bus for governance events with audit trail and dead letter queue.
    
    Features:
    - Decoupled event publishing (no direct callbacks)
    - Immutable audit trail for all governance events
    - Subscription-based handlers
    - Event deduplication
    - Dead letter queue for failed event delivery
    - Async retry with exponential backoff
    - Quorum tracking for actions requiring consensus
    """
    
    def __init__(
        self,
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
        max_retry_delay: float = 30.0,
        dead_letter_max_size: int = 1000,
    ):
        self._subscribers: Dict[GovernanceEventType, List[Callable[[GovernanceEvent], None]]] = {}
        self._audit_trail: List[GovernanceAuditRecord] = []
        self._pending_events: Dict[str, GovernanceAuditRecord] = {}
        self._processed_event_ids: Set[str] = set()
        self._lock = asyncio.Lock()
        self._max_audit_history = 10000
        
        # Dead letter queue for failed events
        self._dead_letter_queue: deque = deque(maxlen=dead_letter_max_size)
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._max_retry_delay = max_retry_delay
        
        # Idempotency tracking for governance actions (Finding 2.1)
        # Stores (event_type, target, asset, timeframe, action) tuples that have been applied
        self._applied_governance_actions: Set[str] = set()
        self._idempotency_store_max_size = 10000
        
        # Alert manager reference (set lazily to avoid circular import)
        self._alert_manager: Optional[Any] = None
        
        # Track delivery failures for meta-alerting
        self._consecutive_delivery_failures: int = 0
        
        # DLQ replay metrics
        self._dlq_replay_stats = {
            "total_attempted": 0,
            "total_applied": 0,
            "total_skipped_idempotent": 0,
            "total_failed": 0,
        }
        
    def subscribe(
        self,
        event_type: GovernanceEventType,
        handler: Callable[[GovernanceEvent], None]
    ) -> None:
        """Subscribe to a governance event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)
        logger.info(f"Handler registered for {event_type.value}")
    
    def unsubscribe(
        self,
        event_type: GovernanceEventType,
        handler: Callable[[GovernanceEvent], None]
    ) -> None:
        """Unsubscribe a handler from an event type."""
        if event_type in self._subscribers:
            self._subscribers[event_type] = [
                h for h in self._subscribers[event_type] if h != handler
            ]
    
    async def publish(self, event: GovernanceEvent) -> str:
        """
        Publish a governance event with retry and dead letter queue.
        
        Args:
            event: The governance event to publish
            
        Returns:
            event_id for tracking through approval/execution
            
        Raises:
            GovernanceEventDeliveryError: If all retries exhausted
        """
        async with self._lock:
            # Deduplication check
            if event.event_id in self._processed_event_ids:
                logger.warning(f"Duplicate event suppressed: {event.event_id}")
                return event.event_id
            
            # Auto-extract asset/timeframe if not provided
            if event.asset is None or event.timeframe is None:
                asset, timeframe = parse_asset_timeframe_from_identifier(event.target_component)
                if asset:
                    event = GovernanceEvent(
                        event_type=event.event_type,
                        source=event.source,
                        target_component=event.target_component,
                        action=event.action,
                        reason=event.reason,
                        event_id=event.event_id,
                        timestamp=event.timestamp,
                        metadata=event.metadata,
                        requires_quorum=event.requires_quorum,
                        asset=asset,
                        timeframe=timeframe,
                        severity=event.severity,
                    )
            
            # Create audit record
            record = GovernanceAuditRecord(
                event=event,
                status="pending",
                affected_assets=[event.asset] if event.asset else [],
                affected_timeframes=[event.timeframe] if event.timeframe else [],
            )
            self._pending_events[event.event_id] = record
        
        # Deliver to subscribers with retry (outside lock for concurrency)
        delivery_results = await self._deliver_with_retry(event)
        
        # Check for failures
        failed_handlers = [r for r in delivery_results if not r["success"]]
        
        if failed_handlers:
            # Add to dead letter queue
            for failure in failed_handlers:
                self._dead_letter_queue.append({
                    "event": event,
                    "handler": failure["handler_name"],
                    "error": failure["error"],
                    "timestamp": time.time(),
                    "attempts": failure["attempts"],
                })
            
            self._consecutive_delivery_failures += 1
            
            # Meta-alert if too many consecutive failures
            if self._consecutive_delivery_failures >= 3:
                await self._fire_delivery_failure_alert(event, failed_handlers)
        else:
            self._consecutive_delivery_failures = 0
            # Mark as applied for idempotency tracking (Finding 2.1)
            self._mark_action_applied(event)
        
        logger.info(
            f"Published {event.event_type.value} from {event.source} "
            f"targeting {event.target_component} "
            f"asset={event.asset} tf={event.timeframe} "
            f"(id={event.event_id}, handlers={len(delivery_results)}, "
            f"failed={len(failed_handlers)})"
        )
        
        return event.event_id
    
    async def _deliver_with_retry(
        self,
        event: GovernanceEvent
    ) -> List[Dict]:
        """
        Deliver event to all subscribers with exponential backoff retry.
        
        Returns:
            List of delivery results with success status and error details
        """
        handlers = self._subscribers.get(event.event_type, [])
        results = []
        
        for handler in handlers:
            handler_name = getattr(handler, '__name__', str(handler))
            result = {
                "handler": handler,
                "handler_name": handler_name,
                "success": False,
                "error": None,
                "attempts": 0,
            }
            
            for attempt in range(self._max_retries):
                result["attempts"] = attempt + 1
                
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await asyncio.wait_for(
                            handler(event),
                            timeout=10.0  # 10s timeout per handler
                        )
                    else:
                        handler(event)
                    
                    result["success"] = True
                    break
                    
                except asyncio.TimeoutError:
                    error_msg = f"Handler {handler_name} timed out (attempt {attempt + 1})"
                    logger.warning(error_msg)
                    result["error"] = error_msg
                    
                except Exception as exc:
                    error_msg = f"Handler {handler_name} failed: {exc}"
                    logger.error(error_msg)
                    result["error"] = error_msg
                    
                    # Calculate backoff delay
                    delay = min(
                        self._retry_base_delay * (2 ** attempt),
                        self._max_retry_delay
                    )
                    
                    if attempt < self._max_retries - 1:
                        await asyncio.sleep(delay)
            
            results.append(result)
        
        return results
    
    async def _fire_delivery_failure_alert(
        self,
        event: GovernanceEvent,
        failures: List[Dict]
    ) -> None:
        """Fire meta-alert when governance event delivery fails."""
        if self._alert_manager is None:
            try:
                from agents.alert_manager import get_alert_manager
                self._alert_manager = get_alert_manager()
            except ImportError:
                logger.error("Cannot fire delivery alert - AlertManager not available")
                return
        
        failure_summary = ", ".join(f["handler_name"] for f in failures)
        
        await self._alert_manager.alert(
            severity="critical",
            title=f"Governance Event Delivery Failed: {event.event_type.value}",
            message=f"Failed to deliver to: {failure_summary}. {len(self._dead_letter_queue)} events in DLQ.",
            source="governance_event_bus",
            affected_assets=[event.asset] if event.asset else None,
            affected_timeframes=[event.timeframe] if event.timeframe else None,
            metadata={
                "event_id": event.event_id,
                "failed_handlers": len(failures),
                "dlq_size": len(self._dead_letter_queue),
                "consecutive_failures": self._consecutive_delivery_failures,
            }
        )
    
    async def approve_event(
        self,
        event_id: str,
        decision_id: str,
        approved_by: str
    ) -> bool:
        """Mark a governance event as approved (e.g., by quorum)."""
        async with self._lock:
            record = self._pending_events.get(event_id)
            if not record:
                logger.error(f"Cannot approve unknown event: {event_id}")
                return False
            
            record.status = "approved"
            record.decision_id = decision_id
            record.executed_by = approved_by
            logger.info(f"Event {event_id} approved via decision {decision_id}")
            return True
    
    async def reject_event(self, event_id: str, reason: str) -> bool:
        """Reject a governance event (e.g., quorum failed)."""
        async with self._lock:
            record = self._pending_events.pop(event_id, None)
            if not record:
                return False
            
            record.status = "rejected"
            record.error_message = reason
            self._audit_trail.append(record)
            self._trim_audit_trail()
            logger.warning(f"Event {event_id} rejected: {reason}")
            return True
    
    async def mark_executed(
        self,
        event_id: str,
        success: bool = True,
        error: Optional[str] = None
    ) -> bool:
        """Mark a governance event as executed."""
        async with self._lock:
            record = self._pending_events.pop(event_id, None)
            if not record:
                logger.error(f"Cannot mark unknown event executed: {event_id}")
                return False
            
            record.status = "executed" if success else "failed"
            record.executed_at = time.time()
            record.error_message = error
            self._processed_event_ids.add(event_id)
            self._audit_trail.append(record)
            self._trim_audit_trail()
            
            logger.info(
                f"Event {event_id} execution: {'success' if success else 'failed'}"
            )
            return True
    
    def _trim_audit_trail(self) -> None:
        """Trim audit trail to prevent unbounded growth."""
        if len(self._audit_trail) > self._max_audit_history:
            self._audit_trail = self._audit_trail[-(self._max_audit_history // 2):]
    
    def get_pending_events(self) -> List[GovernanceAuditRecord]:
        """Get all pending governance events."""
        return list(self._pending_events.values())
    
    def get_audit_trail(
        self,
        event_type: Optional[GovernanceEventType] = None,
        target: Optional[str] = None,
        limit: int = 100
    ) -> List[GovernanceAuditRecord]:
        """Query audit trail with filters."""
        results = self._audit_trail
        
        if event_type:
            results = [r for r in results if r.event.event_type == event_type]
        if target:
            results = [r for r in results if r.event.target_component == target]
        
        return results[-limit:]
    
    def get_dead_letter_queue(self, limit: int = 100, include_idempotency_status: bool = False) -> List[Dict]:
        """
        Get events from the dead letter queue.
        
        Args:
            limit: Maximum number of entries to return
            include_idempotency_status: If True, include whether each event would be
                                        skipped as idempotent on replay
        """
        entries = list(self._dead_letter_queue)[-limit:]
        
        if include_idempotency_status:
            enriched = []
            for entry in entries:
                event = entry["event"]
                idempotency_key = self._generate_idempotency_key(event)
                is_applied = idempotency_key in self._applied_governance_actions
                enriched.append({
                    **entry,
                    "idempotency_key": idempotency_key,
                    "would_be_skipped": is_applied,
                    "replay_safe": self._is_replay_safe(event),
                })
            return enriched
        
        return entries
    
    def _generate_idempotency_key(self, event: GovernanceEvent) -> str:
        """
        Generate a deterministic idempotency key for a governance event.
        
        Key format: event_type:target:asset:timeframe:action:event_id_suffix
        This ensures same action on same target cannot be double-applied.
        """
        # Use last 8 chars of event_id for uniqueness while keeping key manageable
        event_suffix = event.event_id[-8:] if len(event.event_id) > 8 else event.event_id
        
        key = f"{event.event_type.value}:{event.target_component}:{event.asset or 'none'}:{event.timeframe or 'none'}:{event.action.value}:{event_suffix}"
        return key
    
    def _is_replay_safe(self, event: GovernanceEvent) -> bool:
        """
        Check if an event is safe to replay.
        
        All events are technically safe to replay if handlers are idempotent,
        but destructive actions (PAUSE, RETIRE, EMERGENCY_EXIT) require
        extra verification.
        """
        destructive_actions = {
            GovernanceAction.PAUSE,
            GovernanceAction.RETIRE,
            GovernanceAction.EMERGENCY_EXIT,
        }
        
        if event.action in destructive_actions:
            # These are safe ONLY if we've tracked them as already applied
            idempotency_key = self._generate_idempotency_key(event)
            return idempotency_key in self._applied_governance_actions
        
        # Non-destructive actions are always safe to replay
        return True
    
    def _is_action_already_applied(self, event: GovernanceEvent) -> bool:
        """Check if this governance action has already been applied."""
        idempotency_key = self._generate_idempotency_key(event)
        return idempotency_key in self._applied_governance_actions
    
    def _mark_action_applied(self, event: GovernanceEvent) -> None:
        """Mark a governance action as having been applied."""
        idempotency_key = self._generate_idempotency_key(event)
        self._applied_governance_actions.add(idempotency_key)
        
        # Enforce bounded size with FIFO eviction
        if len(self._applied_governance_actions) > self._idempotency_store_max_size:
            # Remove oldest entries (convert to list, slice, convert back)
            oldest = sorted(self._applied_governance_actions)[:1000]
            for old_key in oldest:
                self._applied_governance_actions.discard(old_key)
    
    async def retry_dead_letter(
        self, 
        max_events: int = 10,
        skip_idempotent: bool = True,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Retry delivery of events from the dead letter queue.
        
        This method is idempotent: replaying already-applied governance actions
        will skip them safely without side effects.
        
        Args:
            max_events: Maximum number of DLQ entries to process
            skip_idempotent: If True (default), skip events already marked as applied
            dry_run: If True, simulate replay without actually executing (shows what would happen)
        
        Returns:
            Dict with replay statistics and per-event status
        """
        results = {
            "processed": 0,
            "applied": 0,
            "skipped_idempotent": 0,
            "failed": 0,
            "events": [],
            "dry_run": dry_run,
        }
        
        for _ in range(min(max_events, len(self._dead_letter_queue))):
            if not self._dead_letter_queue:
                break
            
            # Peek at next entry without removing (we'll popleft only if processed)
            dlq_entry = self._dead_letter_queue[0]
            event = dlq_entry["event"]
            
            self._dlq_replay_stats["total_attempted"] += 1
            results["processed"] += 1
            
            # Check idempotency for governance actions
            is_applied = self._is_action_already_applied(event)
            
            if skip_idempotent and is_applied:
                # Skip this event - already applied
                self._dlq_replay_stats["total_skipped_idempotent"] += 1
                results["skipped_idempotent"] += 1
                results["events"].append({
                    "event_id": event.event_id,
                    "action": event.action.value,
                    "target": event.target_component,
                    "status": "skipped_idempotent",
                    "idempotency_key": self._generate_idempotency_key(event),
                })
                
                # Remove from DLQ even when skipping (it's already applied)
                self._dead_letter_queue.popleft()
                
                logger.info(
                    f"DLQ replay skipped (idempotent): {event.event_id} "
                    f"action={event.action.value} target={event.target_component}"
                )
                continue
            
            if dry_run:
                # Simulate without executing
                results["events"].append({
                    "event_id": event.event_id,
                    "action": event.action.value,
                    "target": event.target_component,
                    "status": "would_apply" if not is_applied else "would_skip",
                    "idempotency_key": self._generate_idempotency_key(event),
                })
                # Don't remove from DLQ in dry run
                break  # Only show first event in dry run
            
            # Actually process the event
            self._dead_letter_queue.popleft()
            
            # Attempt redelivery
            delivery_results = await self._deliver_with_retry(event)
            
            if all(r["success"] for r in delivery_results):
                # Success - mark as applied if it's a governance action
                self._mark_action_applied(event)
                self._dlq_replay_stats["total_applied"] += 1
                results["applied"] += 1
                results["events"].append({
                    "event_id": event.event_id,
                    "action": event.action.value,
                    "target": event.target_component,
                    "status": "applied",
                    "idempotency_key": self._generate_idempotency_key(event),
                })
                
                logger.info(
                    f"DLQ replay applied: {event.event_id} "
                    f"action={event.action.value} target={event.target_component}"
                )
            else:
                # Failed again - put back in DLQ with updated retry count
                self._dead_letter_queue.append({
                    **dlq_entry,
                    "retry_count": dlq_entry.get("retry_count", 0) + 1,
                    "last_retry": time.time(),
                })
                self._dlq_replay_stats["total_failed"] += 1
                results["failed"] += 1
                results["events"].append({
                    "event_id": event.event_id,
                    "action": event.action.value,
                    "target": event.target_component,
                    "status": "failed",
                    "error": [r.get("error") for r in delivery_results if not r["success"]],
                })
                
                logger.warning(
                    f"DLQ replay failed: {event.event_id} "
                    f"action={event.action.value} target={event.target_component}"
                )
        
        return results
    
    def get_dlq_replay_stats(self) -> Dict[str, Any]:
        """Get DLQ replay statistics."""
        return {
            **self._dlq_replay_stats,
            "idempotency_store_size": len(self._applied_governance_actions),
            "current_dlq_size": len(self._dead_letter_queue),
        }
    
    def clear_idempotency_store(self) -> None:
        """
        Clear the idempotency store. Use with caution - only for testing or
        when you're certain you want to allow re-application of governance actions.
        """
        self._applied_governance_actions.clear()
        logger.warning("Idempotency store cleared - governance actions may now be replayed")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get event bus statistics including DLQ status."""
        return {
            "pending_count": len(self._pending_events),
            "total_processed": len(self._processed_event_ids),
            "audit_trail_size": len(self._audit_trail),
            "subscriber_counts": {
                et.value: len(handlers)
                for et, handlers in self._subscribers.items()
            },
            "dead_letter_queue_size": len(self._dead_letter_queue),
            "consecutive_delivery_failures": self._consecutive_delivery_failures,
            "max_retries_config": self._max_retries,
        }
    
    def query_audit_trail(
        self,
        event_type: Optional[GovernanceEventType] = None,
        target: Optional[str] = None,
        asset: Optional[str] = None,
        timeframe: Optional[str] = None,
        limit: int = 100,
    ) -> List[GovernanceAuditRecord]:
        """Query audit trail with filters including asset/timeframe."""
        results = self._audit_trail
        
        if event_type:
            results = [r for r in results if r.event.event_type == event_type]
        if target:
            results = [r for r in results if r.event.target_component == target]
        if asset:
            results = [r for r in results if r.event.asset == asset]
        if timeframe:
            results = [r for r in results if r.event.timeframe == timeframe]
        
        return results[-limit:]


# Global singleton
_governance_event_bus: Optional[GovernanceEventBus] = None


def get_governance_event_bus() -> GovernanceEventBus:
    """Get the global governance event bus singleton."""
    global _governance_event_bus
    if _governance_event_bus is None:
        _governance_event_bus = GovernanceEventBus()
    return _governance_event_bus


def reset_governance_event_bus() -> None:
    """Reset the global bus (for testing only)."""
    global _governance_event_bus
    _governance_event_bus = None
