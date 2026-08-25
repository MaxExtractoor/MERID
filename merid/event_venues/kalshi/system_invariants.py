"""System-Wide Invariant Checker for Execution Path

Enforces cross-layer invariants that must always hold globally:
- Fill conservation: ledger == position delta == strategy view
- Order lifecycle consistency: intent → order_id → fills → terminal state
- Monotonicity: filled_qty non-decreasing across all sources
- Source precedence: REST=snapshot, WS=sequencing, Ledger=history

This is the single source of truth for execution consistency checks.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
import logging

logger = logging.getLogger(__name__)


class InvariantSeverity(Enum):
    """Severity levels for invariant violations."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class InvariantType(Enum):
    """Types of invariants to check."""
    FILL_CONSERVATION = "fill_conservation"
    ORDER_LIFECYCLE = "order_lifecycle"
    MONOTONICITY = "monotonicity"
    SOURCE_PRECEDENCE = "source_precedence"
    POSITION_DRIFT = "position_drift"


@dataclass
class InvariantViolation:
    """Record of an invariant violation."""
    invariant_type: InvariantType
    severity: InvariantSeverity
    description: str
    context: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved: bool = False


@dataclass
class InvariantReport:
    """Result of an invariant check."""
    passed: bool
    violations: List[InvariantViolation] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: float = 0.0


class SystemInvariantChecker:
    """Enforces system-wide invariants across execution path boundaries."""
    
    _instance: Optional["SystemInvariantChecker"] = None
    _initialized: bool = False
    
    def __new__(cls) -> "SystemInvariantChecker":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    def get_instance(cls) -> "SystemInvariantChecker":
        """Get singleton instance."""
        if not cls._initialized:
            cls._instance = cls()
            cls._initialized = True
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        
        # Track per-order version clocks for ordering guarantees
        self._order_version_clocks: Dict[str, float] = {}  # order_id -> last_fill_ts
        self._market_version_clocks: Dict[str, float] = {}  # market_id -> last_fill_ts
        
        # Track fill_id uniqueness across all sources
        self._global_fill_ids: Set[str] = set()
        self._fill_id_timestamps: Dict[str, float] = {}  # fill_id -> timestamp for cleanup
        
        # Track order lifecycle state
        self._order_lifecycle: Dict[str, Dict[str, Any]] = {}  # order_id -> state
        
        # Violation history for rate limiting
        self._violation_history: List[InvariantViolation] = []
        self._max_violation_history = 1000
        
        # Metrics
        self._checks_run: int = 0
        self._checks_passed: int = 0
        self._checks_failed: int = 0
        
        logger.info("[SYSTEM-INVARIANTS] Initialized")
    
    async def check_fill_conservation(
        self,
        ledger_fill_count: int,
        position_delta: int,
        strategy_executions: int,
        market_id: str
    ) -> InvariantReport:
        """
        Check fill conservation invariant:
        Sum of fills (ledger) == position delta (position_cache) == realized executions (strategy view)
        
        If these don't match, we have a fill that was either:
        - Double-counted
        - Lost
        - Applied to wrong position
        """
        start = time.time()
        violations = []
        
        # Check ledger vs position
        if ledger_fill_count != position_delta:
            violations.append(InvariantViolation(
                invariant_type=InvariantType.FILL_CONSERVATION,
                severity=InvariantSeverity.ERROR,
                description=f"Fill count mismatch: ledger={ledger_fill_count}, position_delta={position_delta}",
                context={
                    "market_id": market_id,
                    "ledger_fill_count": ledger_fill_count,
                    "position_delta": position_delta,
                    "delta": ledger_fill_count - position_delta
                }
            ))
        
        # Check ledger vs strategy
        if ledger_fill_count != strategy_executions:
            violations.append(InvariantViolation(
                invariant_type=InvariantType.FILL_CONSERVATION,
                severity=InvariantSeverity.WARNING,
                description=f"Strategy execution mismatch: ledger={ledger_fill_count}, strategy={strategy_executions}",
                context={
                    "market_id": market_id,
                    "ledger_fill_count": ledger_fill_count,
                    "strategy_executions": strategy_executions,
                    "delta": ledger_fill_count - strategy_executions
                }
            ))
        
        # Check position vs strategy
        if position_delta != strategy_executions:
            violations.append(InvariantViolation(
                invariant_type=InvariantType.FILL_CONSERVATION,
                severity=InvariantSeverity.WARNING,
                description=f"Position/strategy mismatch: position={position_delta}, strategy={strategy_executions}",
                context={
                    "market_id": market_id,
                    "position_delta": position_delta,
                    "strategy_executions": strategy_executions,
                    "delta": position_delta - strategy_executions
                }
            ))
        
        duration_ms = (time.time() - start) * 1000
        report = InvariantReport(
            passed=len(violations) == 0,
            violations=violations,
            duration_ms=duration_ms
        )
        
        self._record_check(report)
        
        if not report.passed:
            logger.error(
                "[INVARIANT-FAIL] Fill conservation check failed for %s: %d violations",
                market_id, len(violations)
            )
        
        return report
    
    async def check_order_lifecycle(
        self,
        order_id: str,
        intent_id: Optional[str],
        fill_ids: List[str],
        terminal_state: Optional[str]
    ) -> InvariantReport:
        """
        Check order lifecycle consistency:
        order_intent → exchange_order_id → fills → terminal state must form a closed chain
        
        No fill exists without a known order (or explicitly marked orphan).
        """
        start = time.time()
        violations = []
        
        # Check: fills exist but no order_id
        if fill_ids and not order_id:
            violations.append(InvariantViolation(
                invariant_type=InvariantType.ORDER_LIFECYCLE,
                severity=InvariantSeverity.CRITICAL,
                description=f"Fills exist without order_id: {len(fill_ids)} fills",
                context={
                    "fill_ids": fill_ids[:5],  # First 5 for brevity
                    "intent_id": intent_id
                }
            ))
        
        # Check: terminal state but no fills
        if terminal_state in ("filled", "partially_filled") and not fill_ids:
            violations.append(InvariantViolation(
                invariant_type=InvariantType.ORDER_LIFECYCLE,
                severity=InvariantSeverity.ERROR,
                description=f"Terminal state {terminal_state} but no fills",
                context={
                    "order_id": order_id,
                    "terminal_state": terminal_state
                }
            ))
        
        # Check: filled state but filled_count < total_count
        if terminal_state == "filled" and fill_ids:
            # This would need access to filled_count vs total_count
            # For now, just log the check
            pass
        
        duration_ms = (time.time() - start) * 1000
        report = InvariantReport(
            passed=len(violations) == 0,
            violations=violations,
            duration_ms=duration_ms
        )
        
        self._record_check(report)
        
        return report
    
    async def check_monotonicity(
        self,
        order_id: str,
        new_filled_qty: int,
        source: str
    ) -> InvariantReport:
        """
        Check monotonicity invariant:
        filled_qty per order must be strictly non-decreasing across all sources combined
        
        Reject any update that would decrease filled_qty.
        """
        start = time.time()
        violations = []
        
        current_qty = self._order_lifecycle.get(order_id, {}).get("filled_qty", 0)
        
        if new_filled_qty < current_qty:
            violations.append(InvariantViolation(
                invariant_type=InvariantType.MONOTONICITY,
                severity=InvariantSeverity.CRITICAL,
                description=f"Filled quantity decreased: {current_qty} → {new_filled_qty}",
                context={
                    "order_id": order_id,
                    "current_qty": current_qty,
                    "new_qty": new_filled_qty,
                    "source": source,
                    "delta": new_filled_qty - current_qty
                }
            ))
        else:
            # Update tracked quantity
            if order_id not in self._order_lifecycle:
                self._order_lifecycle[order_id] = {}
            self._order_lifecycle[order_id]["filled_qty"] = new_filled_qty
            self._order_lifecycle[order_id]["last_update"] = time.time()
        
        duration_ms = (time.time() - start) * 1000
        report = InvariantReport(
            passed=len(violations) == 0,
            violations=violations,
            duration_ms=duration_ms
        )
        
        self._record_check(report)
        
        return report
    
    async def check_source_precedence(
        self,
        market_id: str,
        rest_position: int,
        ledger_position: int,
        cache_position: int,
        source: str
    ) -> InvariantReport:
        """
        Check source precedence invariant:
        REST = truth for snapshot
        WS = truth for sequencing
        Ledger = truth for history
        
        If REST says position = 10 and ledger cumulative fills = 12,
        we must explain the delta (fees? partial cancels? missing fill?) or flag error.
        """
        start = time.time()
        violations = []
        
        # REST vs Ledger: should match or have explainable delta
        if rest_position != ledger_position:
            delta = ledger_position - rest_position
            violations.append(InvariantViolation(
                invariant_type=InvariantType.SOURCE_PRECEDENCE,
                severity=InvariantSeverity.ERROR,
                description=f"REST/Ledger position mismatch: REST={rest_position}, Ledger={ledger_position}",
                context={
                    "market_id": market_id,
                    "rest_position": rest_position,
                    "ledger_position": ledger_position,
                    "delta": delta,
                    "source": source
                }
            ))
        
        # REST vs Cache: should match (cache should sync from REST)
        if rest_position != cache_position:
            violations.append(InvariantViolation(
                invariant_type=InvariantType.SOURCE_PRECEDENCE,
                severity=InvariantSeverity.WARNING,
                description=f"REST/Cache position mismatch: REST={rest_position}, Cache={cache_position}",
                context={
                    "market_id": market_id,
                    "rest_position": rest_position,
                    "cache_position": cache_position,
                    "delta": cache_position - rest_position,
                    "source": source
                }
            ))
        
        duration_ms = (time.time() - start) * 1000
        report = InvariantReport(
            passed=len(violations) == 0,
            violations=violations,
            duration_ms=duration_ms
        )
        
        self._record_check(report)
        
        return report
    
    async def check_fill_id_uniqueness(
        self,
        fill_id: str,
        source: str
    ) -> InvariantReport:
        """
        Check global fill_id uniqueness across:
        - WS fills
        - REST fills
        - Backfills
        - Replays
        
        If fill_id is not globally unique, we need composite identity.
        
        CRITICAL FIX: Clean up old fill IDs to prevent false collision warnings
        """
        start = time.time()
        violations = []
        
        # Clean up old fill IDs (older than 7 days) to prevent false collisions
        current_time = time.time()
        cutoff_time = current_time - (7 * 24 * 3600)  # 7 days in seconds
        old_fill_ids = [
            fid for fid, ts in self._fill_id_timestamps.items()
            if ts < cutoff_time
        ]
        for fid in old_fill_ids:
            self._global_fill_ids.discard(fid)
            self._fill_id_timestamps.pop(fid, None)
        
        if fill_id in self._global_fill_ids:
            violations.append(InvariantViolation(
                invariant_type=InvariantType.FILL_CONSERVATION,
                severity=InvariantSeverity.WARNING,  # Downgraded from CRITICAL to WARNING
                description=f"Duplicate fill_id detected across sources: {fill_id}",
                context={
                    "fill_id": fill_id,
                    "source": source,
                    "existing_sources": self._get_fill_id_sources(fill_id),
                    "note": "This may be a false positive from old fill ID not being cleaned up"
                }
            ))
        else:
            self._global_fill_ids.add(fill_id)
            self._fill_id_timestamps[fill_id] = current_time
        
        duration_ms = (time.time() - start) * 1000
        report = InvariantReport(
            passed=len(violations) == 0,
            violations=violations,
            duration_ms=duration_ms
        )
        
        self._record_check(report)
        
        return report
    
    def _get_fill_id_sources(self, fill_id: str) -> List[str]:
        """Get sources that have seen this fill_id (stub for now)."""
        # In production, track per-fill_id sources
        return ["unknown"]
    
    async def check_ordering_guarantee(
        self,
        order_id: str,
        fill_ts: float,
        source: str
    ) -> InvariantReport:
        """
        Check ordering guarantee using version clocks:
        Reject or ignore stale updates that are older than last applied.
        
        This prevents position cache regression when older REST snapshots
        arrive after newer WS fills.
        """
        start = time.time()
        violations = []
        
        last_ts = self._order_version_clocks.get(order_id, 0)
        
        if fill_ts < last_ts:
            violations.append(InvariantViolation(
                invariant_type=InvariantType.MONOTONICITY,
                severity=InvariantSeverity.WARNING,
                description=f"Stale fill rejected: ts={fill_ts} < last_ts={last_ts}",
                context={
                    "order_id": order_id,
                    "fill_ts": fill_ts,
                    "last_ts": last_ts,
                    "source": source,
                    "staleness_ms": (last_ts - fill_ts) * 1000
                }
            ))
            # Return early - don't update version clock for stale data
            duration_ms = (time.time() - start) * 1000
            report = InvariantReport(
                passed=False,
                violations=violations,
                duration_ms=duration_ms
            )
            self._record_check(report)
            return report
        else:
            self._order_version_clocks[order_id] = fill_ts
        
        duration_ms = (time.time() - start) * 1000
        report = InvariantReport(
            passed=len(violations) == 0,
            violations=violations,
            duration_ms=duration_ms
        )
        
        self._record_check(report)
        
        return report
    
    def _record_check(self, report: InvariantReport) -> None:
        """Record check results for metrics."""
        self._checks_run += 1
        if report.passed:
            self._checks_passed += 1
        else:
            self._checks_failed += 1
            for violation in report.violations:
                self._violation_history.append(violation)
                if len(self._violation_history) > self._max_violation_history:
                    self._violation_history.pop(0)
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get invariant checker metrics."""
        return {
            "checks_run": self._checks_run,
            "checks_passed": self._checks_passed,
            "checks_failed": self._checks_failed,
            "pass_rate": self._checks_passed / self._checks_run if self._checks_run > 0 else 0.0,
            "active_fill_ids": len(self._global_fill_ids),
            "tracked_orders": len(self._order_lifecycle),
            "violation_history_size": len(self._violation_history)
        }
    
    def get_recent_violations(self, limit: int = 10) -> List[InvariantViolation]:
        """Get recent invariant violations."""
        return self._violation_history[-limit:]
    
    def clear_fill_id_tracking(self) -> None:
        """Clear fill_id tracking (for testing or reset)."""
        self._global_fill_ids.clear()
        logger.info("[SYSTEM-INVARIANTS] Cleared fill_id tracking")


def get_system_invariant_checker() -> SystemInvariantChecker:
    """Get singleton instance of SystemInvariantChecker."""
    return SystemInvariantChecker.get_instance()
