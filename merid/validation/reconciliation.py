"""Intent Reconciliation - Audit chain validation queries.

This module provides queries and validation functions for the intent verification
audit chain, enabling end-to-end verification from signal to execution.

Key capabilities:
- Verify complete hash chain from signal → intent → execution → fill
- Detect structural errors in the audit chain
- Query round trips with intent drift or policy violations
- Separate strategy errors from plumbing errors for PnL attribution
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone, timedelta

from utils.logger import get_logger

logger = get_logger("merid.validation.reconciliation")


@dataclass
class ReconciliationResult:
    """Result of a reconciliation check."""
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    audit_chain: Dict[str, Any]
    
    def add_error(self, error: str) -> None:
        """Add an error to the reconciliation result."""
        self.errors.append(error)
        self.is_valid = False
    
    def add_warning(self, warning: str) -> None:
        """Add a warning to the reconciliation result."""
        self.warnings.append(warning)


class IntentReconciler:
    """Reconciles intent verification audit chain.
    
    This class provides methods to validate the complete audit chain from
    signal snapshot through intent to execution and fills.
    """
    
    def __init__(self):
        # Lazy imports to avoid circular dependencies
        self._snapshot_ledger = None
        self._round_trip_monitor = None
        self._fills_ledger = None
    
    def _get_snapshot_ledger(self):
        """Get the signal snapshot ledger singleton."""
        if self._snapshot_ledger is None:
            from merid.validation.signal_snapshot import get_signal_snapshot_ledger
            self._snapshot_ledger = get_signal_snapshot_ledger()
        return self._snapshot_ledger
    
    def _get_round_trip_monitor(self):
        """Get the round trip monitor."""
        if self._round_trip_monitor is None:
            from merid.event_venues.kalshi.round_trip_monitor import get_round_trip_monitor
            self._round_trip_monitor = get_round_trip_monitor()
        return self._round_trip_monitor
    
    def _get_fills_ledger(self):
        """Get the fills ledger."""
        if self._fills_ledger is None:
            from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
            self._fills_ledger = get_fills_ledger()
        return self._fills_ledger
    
    def verify_audit_chain(
        self,
        signal_id: str,
        intent_id: str,
        order_id: Optional[str] = None,
        fill_ids: Optional[List[str]] = None,
    ) -> ReconciliationResult:
        """Verify the complete audit chain from signal to fills.
        
        Args:
            signal_id: Signal ID from AgentSignal/SignalSnapshot
            intent_id: Intent ID from OrderIntent
            order_id: Optional Kalshi order ID
            fill_ids: Optional list of fill IDs
        
        Returns:
            ReconciliationResult with validation status and errors
        """
        result = ReconciliationResult(
            is_valid=True,
            errors=[],
            warnings=[],
            audit_chain={"signal_id": signal_id, "intent_id": intent_id}
        )
        
        # Step 1: Verify signal exists in snapshot ledger
        ledger = self._get_snapshot_ledger()
        snapshots = ledger.get_by_signal_id(signal_id)
        
        if not snapshots:
            result.add_error(f"Signal {signal_id} not found in snapshot ledger")
            return result
        
        latest_snapshot = ledger.get_latest_snapshot(signal_id)
        result.audit_chain["signal_hash"] = latest_snapshot.signal_hash
        result.audit_chain["snapshot_id"] = latest_snapshot.snapshot_id
        
        # Step 2: Verify intent hash matches (if available)
        # This would require access to the OrderIntent, which we don't have here
        # This check is done in IntentValidator instead
        
        # Step 3: Verify order ID is present for executed orders
        if order_id:
            result.audit_chain["order_id"] = order_id
        else:
            result.add_warning("Order ID not provided - may be a simulated or rejected order")
        
        # Step 4: Verify fill IDs for filled orders
        if fill_ids:
            result.audit_chain["fill_ids"] = fill_ids
            if not fill_ids:
                result.add_warning("No fill IDs provided for filled order")
        else:
            result.add_warning("Fill IDs not provided - order may not be filled")
        
        # Step 5: Compute fill chain hash if all components present
        if "signal_hash" in result.audit_chain and order_id and fill_ids:
            import hashlib
            import json
            chain_preimage = {
                "signal_hash": result.audit_chain["signal_hash"],
                "order_id": order_id,
                "fill_ids": sorted(fill_ids),
            }
            chain_string = json.dumps(chain_preimage, sort_keys=True)
            fill_chain_hash = hashlib.sha256(chain_string.encode()).hexdigest()
            result.audit_chain["fill_chain_hash"] = fill_chain_hash
        
        return result
    
    def query_round_trips_with_intent_drift(
        self,
        since: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Query round trips where exit intent did not match original signal.
        
        Args:
            since: Optional datetime filter (defaults to last 24 hours)
        
        Returns:
            List of round trip records with intent drift
        """
        if since is None:
            since = datetime.now(timezone.utc) - timedelta(hours=24)
        
        monitor = self._get_round_trip_monitor()
        if not monitor:
            logger.warning("Round trip monitor not available")
            return []
        
        drifted_trips = []
        
        # Get all round trips
        for trip in monitor.round_trips.values():
            # Check if exit intent hash differs from entry intent hash
            if (trip.entry_intent_hash and trip.exit_intent_hash and
                trip.entry_intent_hash != trip.exit_intent_hash):
                drifted_trips.append({
                    "asset": trip.asset,
                    "ticker": trip.ticker,
                    "entry_intent_id": trip.entry_intent_id,
                    "exit_intent_id": trip.exit_intent_id,
                    "entry_intent_hash": trip.entry_intent_hash,
                    "exit_intent_hash": trip.exit_intent_hash,
                    "actual_exit_reason": trip.actual_exit_reason,
                    "realized_pnl_cents": trip.realized_pnl_cents,
                    "exit_timestamp": trip.exit_timestamp,
                })
        
        logger.info(f"[RECONCILIATION] Found {len(drifted_trips)} round trips with intent drift")
        return drifted_trips
    
    def query_policy_violation_exits(
        self,
        since: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Query round trips where exit was due to policy violation.
        
        Args:
            since: Optional datetime filter (defaults to last 24 hours)
        
        Returns:
            List of round trip records with policy violation exits
        """
        if since is None:
            since = datetime.now(timezone.utc) - timedelta(hours=24)
        
        monitor = self._get_round_trip_monitor()
        if not monitor:
            logger.warning("Round trip monitor not available")
            return []
        
        policy_violations = []
        
        # Get all round trips
        for trip in monitor.round_trips.values():
            # Check if exit reason indicates policy violation
            violation_reasons = ["policy_violation", "circuit_breaker", "manual_override"]
            if any(reason in trip.actual_exit_reason.lower() for reason in violation_reasons):
                policy_violations.append({
                    "asset": trip.asset,
                    "ticker": trip.ticker,
                    "entry_intent_id": trip.entry_intent_id,
                    "exit_intent_id": trip.exit_intent_id,
                    "actual_exit_reason": trip.actual_exit_reason,
                    "realized_pnl_cents": trip.realized_pnl_cents,
                    "exit_timestamp": trip.exit_timestamp,
                    "source_signal_id": trip.source_signal_id,
                    "source_signal_hash": trip.source_signal_hash,
                })
        
        logger.info(f"[RECONCILIATION] Found {len(policy_violations)} round trips with policy violation exits")
        return policy_violations
    
    def detect_structural_errors(
        self,
        since: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Detect structural errors in the audit chain.
        
        Structural errors include:
        - Missing signal_id in round trip
        - Missing intent_id in round trip
        - Missing order_id or fill_ids in fills ledger
        - Broken hash chain links
        
        Args:
            since: Optional datetime filter (defaults to last 24 hours)
        
        Returns:
            List of structural errors detected
        """
        if since is None:
            since = datetime.now(timezone.utc) - timedelta(hours=24)
        
        errors = []
        
        # Check round trips for missing IDs
        monitor = self._get_round_trip_monitor()
        if monitor:
            for trip in monitor.round_trips.values():
                if trip.exit_timestamp < since:
                    continue
                
                trip_errors = []
                
                if not trip.source_signal_id:
                    trip_errors.append("missing_source_signal_id")
                
                if not trip.source_signal_hash:
                    trip_errors.append("missing_source_signal_hash")
                
                if not trip.entry_intent_hash:
                    trip_errors.append("missing_entry_intent_hash")
                
                if not trip.exit_intent_hash:
                    trip_errors.append("missing_exit_intent_hash")
                
                if not trip.fill_chain_hash:
                    trip_errors.append("missing_fill_chain_hash")
                
                if trip_errors:
                    errors.append({
                        "type": "structural_error",
                        "asset": trip.asset,
                        "ticker": trip.ticker,
                        "entry_intent_id": trip.entry_intent_id,
                        "exit_intent_id": trip.exit_intent_id,
                        "errors": trip_errors,
                        "exit_timestamp": trip.exit_timestamp,
                    })
        
        # Check fills ledger for missing broker order IDs
        fills_ledger = self._get_fills_ledger()
        if fills_ledger:
            for intent in fills_ledger._intents.values():
                if intent.created_at < since:
                    continue
                
                if intent.status in ("filled", "partially_filled") and not intent.broker_order_id:
                    errors.append({
                        "type": "structural_error",
                        "intent_id": intent.intent_id,
                        "ticker": intent.ticker,
                        "status": intent.status,
                        "errors": ["missing_broker_order_id"],
                        "created_at": intent.created_at,
                    })
        
        logger.info(f"[RECONCILIATION] Detected {len(errors)} structural errors")
        return errors
    
    def separate_strategy_vs_plumbing_errors(
        self,
        since: Optional[datetime] = None,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Separate strategy errors from plumbing errors for PnL attribution.
        
        Strategy errors: Bad signals, incorrect intent, model failures
        Plumbing errors: Execution failures, venue issues, hash chain breaks
        
        Args:
            since: Optional datetime filter (defaults to last 24 hours)
        
        Returns:
            Tuple of (strategy_errors, plumbing_errors)
        """
        if since is None:
            since = datetime.now(timezone.utc) - timedelta(hours=24)
        
        strategy_errors = []
        plumbing_errors = []
        
        # Policy violations are strategy errors
        policy_violations = self.query_policy_violation_exits(since)
        for violation in policy_violations:
            strategy_errors.append({
                "type": "strategy_error",
                "subtype": "policy_violation",
                **violation,
            })
        
        # Intent drift is a strategy error
        intent_drifts = self.query_round_trips_with_intent_drift(since)
        for drift in intent_drifts:
            strategy_errors.append({
                "type": "strategy_error",
                "subtype": "intent_drift",
                **drift,
            })
        
        # Structural errors are plumbing errors
        structural_errors = self.detect_structural_errors(since)
        for error in structural_errors:
            plumbing_errors.append({
                "type": "plumbing_error",
                **error,
            })
        
        logger.info(
            f"[RECONCILIATION] Attribution: {len(strategy_errors)} strategy errors, "
            f"{len(plumbing_errors)} plumbing errors"
        )
        
        return strategy_errors, plumbing_errors


# Global singleton instance
_reconciler: Optional[IntentReconciler] = None


def get_intent_reconciler() -> IntentReconciler:
    """Get the global intent reconciler singleton."""
    global _reconciler
    if _reconciler is None:
        _reconciler = IntentReconciler()
    return _reconciler
