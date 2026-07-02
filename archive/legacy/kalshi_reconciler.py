"""Kalshi Reconciliation — Deep position/order comparison.

Compares MERID's internal state against Kalshi venue snapshot to detect:
- Phantom positions (on venue, not in MERID)
- Missing positions (in MERID, not on venue)
- Quantity mismatches
- Price mismatches
- Stale orders (MERID thinks closed, venue shows open)

Usage::

    reconciler = get_kalshi_reconciler()
    report = await reconciler.reconcile()
    
    if report.severity == "CRITICAL":
        # Block new executions for prediction domain
        execution_guard.block_domain("prediction")
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from merid.event_venues.kalshi.venue_adapter import get_kalshi_venue_adapter
from merid.matching_engine import get_matching_engine, Order, OrderStatus
from merid.event_venues.base import VenuePosition, PlacedOrder
from utils.logger import get_logger

logger = get_logger("merid.reconciliation.kalshi")


# ── Enums ─────────────────────────────────────────────────────────────────

class IssueSeverity(str, Enum):
    """Severity level for reconciliation issues."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class IssueType(str, Enum):
    """Type of reconciliation discrepancy."""
    PHANTOM_POSITION = "phantom_position"      # On venue, not in MERID
    MISSING_POSITION = "missing_position"      # In MERID, not on venue
    QUANTITY_MISMATCH = "quantity_mismatch"    # Position size differs
    PRICE_MISMATCH = "price_mismatch"          # Entry price differs significantly
    STALE_ORDER = "stale_order"                # Order status mismatch
    UNKNOWN_ORDER = "unknown_order"            # Order on venue, not in MERID


# ── Data Models ───────────────────────────────────────────────────────────

@dataclass
class ReconciliationIssue:
    """Single reconciliation discrepancy."""
    issue_type: IssueType
    severity: IssueSeverity
    instrument_id: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "issue_type": self.issue_type.value,
            "severity": self.severity.value,
            "instrument_id": self.instrument_id,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp,
        }


@dataclass
class ReconciliationReport:
    """Aggregated reconciliation report with severity assessment."""
    venue: str
    domain: str
    timestamp: float
    issues: List[ReconciliationIssue] = field(default_factory=list)
    internal_position_count: int = 0
    venue_position_count: int = 0
    internal_order_count: int = 0
    venue_order_count: int = 0
    severity: str = "OK"  # OK, WARNING, CRITICAL
    summary: str = ""
    book_health_ok: bool = True
    auto_kill_suppressed_reason: str = ""

    def __post_init__(self):
        """Auto-compute severity and summary from issues."""
        if not self.issues:
            self.severity = "OK"
            self.summary = "All positions and orders reconciled successfully"
            return

        # Determine overall severity
        has_critical = any(i.severity == IssueSeverity.CRITICAL for i in self.issues)
        has_warning = any(i.severity == IssueSeverity.WARNING for i in self.issues)

        if has_critical:
            self.severity = "CRITICAL"
        elif has_warning:
            self.severity = "WARNING"
        else:
            self.severity = "INFO"

        # Generate summary
        issue_counts = {}
        for issue in self.issues:
            issue_counts[issue.issue_type.value] = issue_counts.get(issue.issue_type.value, 0) + 1

        parts = [f"{self.severity}: {len(self.issues)} issue(s)"]
        for issue_type, count in issue_counts.items():
            parts.append(f"{count} {issue_type}")
        self.summary = " — ".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "venue": self.venue,
            "domain": self.domain,
            "timestamp": self.timestamp,
            "severity": self.severity,
            "summary": self.summary,
            "internal_position_count": self.internal_position_count,
            "venue_position_count": self.venue_position_count,
            "internal_order_count": self.internal_order_count,
            "venue_order_count": self.venue_order_count,
            "issue_count": len(self.issues),
            "issues": [i.to_dict() for i in self.issues],
        }


# ── Reconciler ────────────────────────────────────────────────────────────

class KalshiReconciler:
    """Reconciles MERID internal state with Kalshi venue snapshot.
    
    Compares:
    - Positions: quantity, entry price
    - Orders: status, filled quantity
    
    Generates ReconciliationReport with issues and severity.
    """

    def __init__(self):
        self._venue_adapter = get_kalshi_venue_adapter()
        self._matching_engine = None
        self._last_report: Optional[ReconciliationReport] = None

    @property
    def matching_engine(self):
        """Lazy-load matching engine for prediction domain."""
        if self._matching_engine is None:
            try:
                self._matching_engine = get_matching_engine("prediction")
            except Exception as exc:
                logger.warning(f"Matching engine not available: {exc}")
        return self._matching_engine

    async def reconcile(self, *, apply_domain_kill_switch: bool = False) -> ReconciliationReport:
        """Run full reconciliation between MERID and Kalshi.
        
        Args:
            apply_domain_kill_switch: If True, activate domain kill switch on CRITICAL.
        
        Returns:
            ReconciliationReport with issues and severity
        """
        now = time.time()
        issues: List[ReconciliationIssue] = []

        # Determine internal position source
        _internal_source = os.environ.get("MERID_REC_INTERNAL_SOURCE", "matching_engine")
        _fills_ledger_empty = False

        # Get internal state (supports fills_ledger or matching_engine)
        if _internal_source == "fills_ledger":
            try:
                from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
                _ledger = get_fills_ledger()
                internal_positions = _ledger.build_venue_positions_from_ledger()
                _fills_ledger_empty = not _ledger._fills
            except Exception as _le:
                logger.warning("Fills ledger unavailable: %s", _le)
                internal_positions = []
                _fills_ledger_empty = True
        else:
            internal_positions = await self._get_internal_positions()
        internal_orders = await self._get_internal_orders()

        # Get venue state
        venue_positions = await self._venue_adapter.get_positions()
        venue_orders = await self._venue_adapter.get_orders()

        logger.info(
            f"Reconciling: {len(internal_positions)} internal pos, "
            f"{len(venue_positions)} venue pos, "
            f"{len(internal_orders)} internal orders, "
            f"{len(venue_orders)} venue orders"
        )

        # Reconcile positions
        position_issues = self._reconcile_positions(internal_positions, venue_positions)
        issues.extend(position_issues)

        # Reconcile orders
        order_issues = self._reconcile_orders(internal_orders, venue_orders)
        issues.extend(order_issues)

        # Detect phantom scenario: empty fills ledger but venue has positions
        _suppress_reason = ""
        _book_ok = True
        if _fills_ledger_empty and len(venue_positions) > 0 and len(internal_positions) == 0:
            _suppress_reason = "empty_fills_ledger_with_venue_positions"
            _book_ok = False
            logger.warning(
                "[reconciler] Phantom detected: fills ledger empty but venue has %d positions — "
                "suppressing auto-kill (manual review required)",
                len(venue_positions),
            )

        # Detect matching_engine residual: ME has positions but venue is flat
        if _internal_source == "matching_engine" and len(internal_positions) > 0 and len(venue_positions) == 0:
            _suppress_reason = "internal_position_not_on_venue"
            _book_ok = False

        # Build report
        report = ReconciliationReport(
            venue="kalshi",
            domain="prediction",
            timestamp=now,
            issues=issues,
            internal_position_count=len(internal_positions),
            venue_position_count=len(venue_positions),
            internal_order_count=len(internal_orders),
            venue_order_count=len(venue_orders),
            book_health_ok=_book_ok,
            auto_kill_suppressed_reason=_suppress_reason,
        )

        self._last_report = report
        logger.info(f"Reconciliation complete: {report.summary}")

        if report.severity == "CRITICAL" and apply_domain_kill_switch:
            if _suppress_reason:
                logger.warning(
                    "[reconciler] CRITICAL severity but auto-kill suppressed: %s",
                    _suppress_reason,
                )
            else:
                try:
                    from merid.execution_guard import get_execution_guard
                    get_execution_guard().activate_domain_kill_switch(
                        "prediction",
                        reason=f"kalshi_reconciler_critical: {report.summary}",
                    )
                    logger.error(
                        "[reconciler] CRITICAL severity — activated prediction domain kill switch: %s",
                        report.summary,
                    )
                except Exception as _eg_exc:
                    logger.error(
                        "[reconciler] CRITICAL severity but failed to activate domain kill switch: %s",
                        _eg_exc,
                    )

        return report

    async def _get_internal_positions(self) -> List[VenuePosition]:
        """Get positions from MERID internal state (matching engine)."""
        if not self.matching_engine:
            return []

        # Aggregate positions from filled orders
        positions_map: Dict[str, VenuePosition] = {}
        for order in self.matching_engine._orders.values():
            if order.status != OrderStatus.FILLED or order.filled_quantity <= 0:
                continue

            key = order.instrument_id
            if key not in positions_map:
                positions_map[key] = VenuePosition(
                    market_id=order.instrument_id,
                    outcome_id=None,
                    size=Decimal("0"),
                    average_entry_price=Decimal("0"),
                    venue="kalshi",
                )

            pos = positions_map[key]
            qty = Decimal(str(order.filled_quantity))
            price = Decimal(str(order.filled_price))

            from merid.matching_engine import OrderSide
            if order.side == OrderSide.SELL:
                pos.size -= qty
            else:
                old_size = pos.size
                new_size = old_size + qty
                if new_size > 0:
                    pos.average_entry_price = (
                        (pos.average_entry_price * old_size + price * qty) / new_size
                    )
                pos.size = new_size

        return list(positions_map.values())

    async def _get_internal_orders(self) -> List[PlacedOrder]:
        """Get orders from MERID internal state."""
        if not self.matching_engine:
            return []

        orders = []
        for order in self.matching_engine._orders.values():
            orders.append(
                PlacedOrder(
                    order_id=order.order_id,
                    market_id=order.instrument_id,
                    side=order.side.value,
                    size=Decimal(str(order.quantity)),
                    price=Decimal(str(order.price)) if order.price > 0 else None,
                    filled_size=Decimal(str(order.filled_quantity)),
                    status=order.status.value,
                    venue="kalshi",
                )
            )
        return orders

    def _reconcile_positions(
        self,
        internal: List[VenuePosition],
        venue: List[VenuePosition],
    ) -> List[ReconciliationIssue]:
        """Compare internal vs venue positions.
        
        Detects:
        - Phantom positions (on venue, not internal)
        - Missing positions (internal, not on venue)
        - Quantity mismatches
        - Price mismatches
        """
        issues = []

        # Build lookup maps
        internal_map = {p.market_id: p for p in internal}
        venue_map = {p.market_id: p for p in venue}

        # Check for phantom positions (on venue, not internal)
        for market_id, venue_pos in venue_map.items():
            if market_id not in internal_map:
                issues.append(
                    ReconciliationIssue(
                        issue_type=IssueType.PHANTOM_POSITION,
                        severity=IssueSeverity.CRITICAL,
                        instrument_id=market_id,
                        message=f"Position exists on venue but not in MERID: {market_id}",
                        details={
                            "venue_size": float(venue_pos.size),
                            "venue_entry_price": float(venue_pos.average_entry_price),
                        },
                    )
                )

        # Check for missing positions (internal, not on venue)
        for market_id, internal_pos in internal_map.items():
            if market_id not in venue_map:
                # In paper mode, this is expected (venue may not have real positions)
                # CRITICAL if size is significant (venue may have closed/settled without MERID knowing)
                if internal_pos.size > Decimal("10"):
                    issues.append(
                        ReconciliationIssue(
                            issue_type=IssueType.MISSING_POSITION,
                            severity=IssueSeverity.CRITICAL,
                            instrument_id=market_id,
                            message=f"Position in MERID but not on venue: {market_id}",
                            details={
                                "internal_size": float(internal_pos.size),
                                "internal_entry_price": float(internal_pos.average_entry_price),
                            },
                        )
                    )
                continue

            # Check for quantity mismatch
            venue_pos = venue_map[market_id]
            qty_delta = abs(internal_pos.size - venue_pos.size)
            if qty_delta > Decimal("0.01"):  # Allow 0.01 contract tolerance
                severity = IssueSeverity.CRITICAL if qty_delta > Decimal("1.0") else IssueSeverity.WARNING
                issues.append(
                    ReconciliationIssue(
                        issue_type=IssueType.QUANTITY_MISMATCH,
                        severity=severity,
                        instrument_id=market_id,
                        message=f"Position size mismatch for {market_id}",
                        details={
                            "internal_size": float(internal_pos.size),
                            "venue_size": float(venue_pos.size),
                            "delta": float(qty_delta),
                        },
                    )
                )

            # Check for price mismatch (>5% difference)
            if internal_pos.average_entry_price > 0 and venue_pos.average_entry_price > 0:
                price_pct_diff = abs(
                    (internal_pos.average_entry_price - venue_pos.average_entry_price)
                    / venue_pos.average_entry_price
                ) * 100

                if price_pct_diff > 5.0:
                    issues.append(
                        ReconciliationIssue(
                            issue_type=IssueType.PRICE_MISMATCH,
                            severity=IssueSeverity.WARNING,
                            instrument_id=market_id,
                            message=f"Entry price differs by {price_pct_diff:.1f}% for {market_id}",
                            details={
                                "internal_price": float(internal_pos.average_entry_price),
                                "venue_price": float(venue_pos.average_entry_price),
                                "pct_diff": round(price_pct_diff, 2),
                            },
                        )
                    )

        return issues

    def _reconcile_orders(
        self,
        internal: List[PlacedOrder],
        venue: List[PlacedOrder],
    ) -> List[ReconciliationIssue]:
        """Compare internal vs venue orders.
        
        Detects:
        - Stale orders (status mismatch)
        - Unknown orders (on venue, not internal)
        """
        issues = []

        # Build lookup maps (by order_id when available, else by market_id)
        internal_map = {o.order_id: o for o in internal}
        venue_map = {o.order_id: o for o in venue}

        # Check for unknown orders on venue
        for order_id, venue_order in venue_map.items():
            if order_id not in internal_map:
                issues.append(
                    ReconciliationIssue(
                        issue_type=IssueType.UNKNOWN_ORDER,
                        severity=IssueSeverity.WARNING,
                        instrument_id=venue_order.market_id,
                        message=f"Order {order_id} exists on venue but not in MERID",
                        details={
                            "venue_status": venue_order.status,
                            "venue_size": float(venue_order.size),
                        },
                    )
                )

        # Check for stale orders (status mismatch)
        for order_id, internal_order in internal_map.items():
            if order_id not in venue_map:
                # Order not on venue (could be cancelled or filled)
                if internal_order.status in ("pending", "partially_filled"):
                    issues.append(
                        ReconciliationIssue(
                            issue_type=IssueType.STALE_ORDER,
                            severity=IssueSeverity.WARNING,
                            instrument_id=internal_order.market_id,
                            message=f"Order {order_id} is {internal_order.status} internally but not found on venue",
                            details={
                                "internal_status": internal_order.status,
                                "internal_size": float(internal_order.size),
                            },
                        )
                    )
                continue

            # Status mismatch
            venue_order = venue_map[order_id]
            if internal_order.status != venue_order.status:
                issues.append(
                    ReconciliationIssue(
                        issue_type=IssueType.STALE_ORDER,
                        severity=IssueSeverity.WARNING,
                        instrument_id=internal_order.market_id,
                        message=f"Order {order_id} status mismatch",
                        details={
                            "internal_status": internal_order.status,
                            "venue_status": venue_order.status,
                        },
                    )
                )

        return issues

    def get_last_report(self) -> Optional[ReconciliationReport]:
        """Get the most recent reconciliation report."""
        return self._last_report


# ── Singleton ─────────────────────────────────────────────────────────────

_reconciler: Optional[KalshiReconciler] = None
_reconciler_lock = threading.Lock()


def get_kalshi_reconciler() -> KalshiReconciler:
    """Get or create the singleton KalshiReconciler."""
    global _reconciler
    if _reconciler is None:
        with _reconciler_lock:
            if _reconciler is None:
                _reconciler = KalshiReconciler()
    return _reconciler


def reset_kalshi_reconciler() -> None:
    """Reset singleton (for testing)."""
    global _reconciler
    _reconciler = None
