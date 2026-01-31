"""
Autonomous update safeguards with staging, validation, and change logging.

Ensures autonomous jobs that update baselines, thresholds, or metrics have
proper guardrails, validation, approval workflows, and audit trails.
"""

import logging
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json
from pathlib import Path
import hashlib

logger = logging.getLogger(__name__)


class UpdateType(Enum):
    """Type of autonomous update."""
    BASELINE = "baseline"
    THRESHOLD = "threshold"
    METRIC = "metric"
    SAMPLING_RATE = "sampling_rate"
    ALERT_RULE = "alert_rule"
    CONFIGURATION = "configuration"


class UpdateStatus(Enum):
    """Status of autonomous update."""
    PROPOSED = "proposed"
    STAGED = "staged"
    VALIDATED = "validated"
    APPROVED = "approved"
    APPLIED = "applied"
    REJECTED = "rejected"
    ROLLED_BACK = "rolled_back"


class ValidationResult(Enum):
    """Result of validation check."""
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"


@dataclass
class StagedUpdate:
    """Staged update awaiting validation and approval."""
    update_id: str
    update_type: UpdateType
    target: str
    
    before_value: Any
    after_value: Any
    
    proposed_by: str
    proposed_at: datetime
    
    justification: str
    impact_assessment: str
    
    validation_results: List[Dict[str, Any]] = field(default_factory=list)
    validation_status: Optional[ValidationResult] = None
    
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    
    applied_at: Optional[datetime] = None
    
    status: UpdateStatus = UpdateStatus.PROPOSED
    
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationCheck:
    """Validation check for autonomous updates."""
    check_id: str
    update_type: UpdateType
    description: str
    check_function: Callable[[Any, Any], Tuple[ValidationResult, str]]
    required_for_approval: bool


@dataclass
class ChangeLogEntry:
    """Change log entry for autonomous updates."""
    entry_id: str
    timestamp: datetime
    update_id: str
    update_type: UpdateType
    target: str
    
    before_value: Any
    after_value: Any
    
    initiator: str
    validator: Optional[str]
    approver: Optional[str]
    
    validation_results: List[Dict[str, Any]]
    
    status: UpdateStatus
    
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PurgeRecord:
    """Record of data purge operation."""
    purge_id: str
    timestamp: datetime
    data_type: str
    scope: str
    
    records_affected: int
    soft_deleted: bool
    restore_until: Optional[datetime]
    
    initiated_by: str
    approved_by: Optional[str]
    
    metadata: Dict[str, Any] = field(default_factory=dict)


class AutonomousUpdateSafeguards:
    """
    Safeguards for autonomous updates and purges.
    
    Implements:
    - Staging configs before applying
    - Validation checks (no extreme jumps)
    - Human/governance approval workflows
    - Change logging with before/after values
    - Soft-delete and restore for purges
    - Allow-lists for critical data
    """
    
    def __init__(self, change_log_file: str = "governance/autonomous_change_log.json"):
        self.change_log_file = Path(change_log_file)
        self.change_log_file.parent.mkdir(parents=True, exist_ok=True)
        
        self._staged_updates: Dict[str, StagedUpdate] = {}
        self._validation_checks: Dict[str, List[ValidationCheck]] = {}
        self._change_log: List[ChangeLogEntry] = []
        self._purge_records: List[PurgeRecord] = []
        
        self._critical_data_allowlist = {
            "trade_history",
            "compliance_records",
            "audit_trail",
            "governance_actions",
            "risk_events",
        }
        
        self._initialize_validation_checks()
        self._load_change_log()
    
    def _initialize_validation_checks(self) -> None:
        """Initialize validation checks for different update types."""
        self.register_validation_check(
            check_id="baseline_extreme_jump",
            update_type=UpdateType.BASELINE,
            description="Check for extreme jumps in baseline values",
            check_function=self._check_baseline_jump,
            required_for_approval=True,
        )
        
        self.register_validation_check(
            check_id="threshold_reasonable_range",
            update_type=UpdateType.THRESHOLD,
            description="Check threshold is in reasonable range",
            check_function=self._check_threshold_range,
            required_for_approval=True,
        )
        
        self.register_validation_check(
            check_id="sampling_rate_valid",
            update_type=UpdateType.SAMPLING_RATE,
            description="Check sampling rate is between 0 and 1",
            check_function=self._check_sampling_rate,
            required_for_approval=True,
        )
        
        logger.info("Initialized validation checks for autonomous updates")
    
    def register_validation_check(
        self,
        check_id: str,
        update_type: UpdateType,
        description: str,
        check_function: Callable[[Any, Any], Tuple[ValidationResult, str]],
        required_for_approval: bool,
    ) -> ValidationCheck:
        """Register a validation check."""
        check = ValidationCheck(
            check_id=check_id,
            update_type=update_type,
            description=description,
            check_function=check_function,
            required_for_approval=required_for_approval,
        )
        
        if update_type not in self._validation_checks:
            self._validation_checks[update_type] = []
        
        self._validation_checks[update_type].append(check)
        
        logger.info(
            f"Registered validation check '{check_id}' for {update_type.value}"
        )
        
        return check
    
    def propose_update(
        self,
        update_type: UpdateType,
        target: str,
        before_value: Any,
        after_value: Any,
        proposed_by: str,
        justification: str,
        impact_assessment: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> StagedUpdate:
        """Propose an autonomous update (writes to staging)."""
        update_id = hashlib.md5(
            f"{update_type.value}_{target}_{datetime.utcnow().isoformat()}".encode()
        ).hexdigest()[:16]
        
        update = StagedUpdate(
            update_id=update_id,
            update_type=update_type,
            target=target,
            before_value=before_value,
            after_value=after_value,
            proposed_by=proposed_by,
            proposed_at=datetime.utcnow(),
            justification=justification,
            impact_assessment=impact_assessment,
            status=UpdateStatus.PROPOSED,
            metadata=metadata or {},
        )
        
        self._staged_updates[update_id] = update
        
        logger.info(
            f"Proposed autonomous update '{update_id}': {update_type.value} "
            f"for {target} by {proposed_by}"
        )
        
        return update
    
    def validate_update(
        self,
        update_id: str,
        validator: str,
    ) -> StagedUpdate:
        """Run validation checks on staged update."""
        if update_id not in self._staged_updates:
            raise ValueError(f"Update '{update_id}' not found")
        
        update = self._staged_updates[update_id]
        
        if update.status != UpdateStatus.PROPOSED:
            raise ValueError(
                f"Update '{update_id}' cannot be validated in status {update.status.value}"
            )
        
        checks = self._validation_checks.get(update.update_type, [])
        
        all_passed = True
        has_required_failure = False
        
        for check in checks:
            result, message = check.check_function(update.before_value, update.after_value)
            
            validation_result = {
                "check_id": check.check_id,
                "description": check.description,
                "result": result.value,
                "message": message,
                "required": check.required_for_approval,
                "timestamp": datetime.utcnow().isoformat(),
                "validator": validator,
            }
            
            update.validation_results.append(validation_result)
            
            if result == ValidationResult.FAILED:
                all_passed = False
                if check.required_for_approval:
                    has_required_failure = True
        
        if has_required_failure:
            update.validation_status = ValidationResult.FAILED
            update.status = UpdateStatus.REJECTED
        elif all_passed:
            update.validation_status = ValidationResult.PASSED
            update.status = UpdateStatus.VALIDATED
        else:
            update.validation_status = ValidationResult.WARNING
            update.status = UpdateStatus.STAGED
        
        logger.info(
            f"Validated update '{update_id}': {update.validation_status.value} "
            f"by {validator}"
        )
        
        return update
    
    def approve_update(
        self,
        update_id: str,
        approver: str,
        notes: Optional[str] = None,
    ) -> StagedUpdate:
        """Approve a validated update."""
        if update_id not in self._staged_updates:
            raise ValueError(f"Update '{update_id}' not found")
        
        update = self._staged_updates[update_id]
        
        if update.status not in [UpdateStatus.VALIDATED, UpdateStatus.STAGED]:
            raise ValueError(
                f"Update '{update_id}' cannot be approved in status {update.status.value}"
            )
        
        if update.validation_status == ValidationResult.FAILED:
            raise ValueError(
                f"Update '{update_id}' failed validation and cannot be approved"
            )
        
        update.approved_by = approver
        update.approved_at = datetime.utcnow()
        update.status = UpdateStatus.APPROVED
        
        if notes:
            update.metadata["approval_notes"] = notes
        
        logger.info(f"Approved update '{update_id}' by {approver}")
        
        return update
    
    def apply_update(
        self,
        update_id: str,
    ) -> StagedUpdate:
        """Apply an approved update."""
        if update_id not in self._staged_updates:
            raise ValueError(f"Update '{update_id}' not found")
        
        update = self._staged_updates[update_id]
        
        if update.status != UpdateStatus.APPROVED:
            raise ValueError(
                f"Update '{update_id}' must be approved before applying "
                f"(current status={update.status.value})"
            )
        
        update.applied_at = datetime.utcnow()
        update.status = UpdateStatus.APPLIED
        
        self._log_change(update)
        
        logger.info(f"Applied update '{update_id}'")
        
        return update
    
    def reject_update(
        self,
        update_id: str,
        rejected_by: str,
        reason: str,
    ) -> StagedUpdate:
        """Reject a proposed or staged update."""
        if update_id not in self._staged_updates:
            raise ValueError(f"Update '{update_id}' not found")
        
        update = self._staged_updates[update_id]
        
        update.status = UpdateStatus.REJECTED
        update.metadata["rejected_by"] = rejected_by
        update.metadata["rejected_at"] = datetime.utcnow().isoformat()
        update.metadata["rejection_reason"] = reason
        
        self._log_change(update)
        
        logger.warning(f"Rejected update '{update_id}' by {rejected_by}: {reason}")
        
        return update
    
    def rollback_update(
        self,
        update_id: str,
        rolled_back_by: str,
        reason: str,
    ) -> StagedUpdate:
        """Rollback an applied update."""
        if update_id not in self._staged_updates:
            raise ValueError(f"Update '{update_id}' not found")
        
        update = self._staged_updates[update_id]
        
        if update.status != UpdateStatus.APPLIED:
            raise ValueError(
                f"Update '{update_id}' cannot be rolled back (status={update.status.value})"
            )
        
        update.status = UpdateStatus.ROLLED_BACK
        update.metadata["rolled_back_by"] = rolled_back_by
        update.metadata["rolled_back_at"] = datetime.utcnow().isoformat()
        update.metadata["rollback_reason"] = reason
        
        self._log_change(update)
        
        logger.warning(f"Rolled back update '{update_id}' by {rolled_back_by}: {reason}")
        
        return update
    
    def soft_delete_data(
        self,
        data_type: str,
        scope: str,
        records_affected: int,
        initiated_by: str,
        restore_days: int = 30,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PurgeRecord:
        """Soft-delete data with restore window."""
        if data_type in self._critical_data_allowlist:
            raise ValueError(
                f"Data type '{data_type}' is on critical allowlist and cannot be purged"
            )
        
        purge_id = hashlib.md5(
            f"{data_type}_{scope}_{datetime.utcnow().isoformat()}".encode()
        ).hexdigest()[:16]
        
        record = PurgeRecord(
            purge_id=purge_id,
            timestamp=datetime.utcnow(),
            data_type=data_type,
            scope=scope,
            records_affected=records_affected,
            soft_deleted=True,
            restore_until=datetime.utcnow() + timedelta(days=restore_days),
            initiated_by=initiated_by,
            metadata=metadata or {},
        )
        
        self._purge_records.append(record)
        
        logger.info(
            f"Soft-deleted {records_affected} records of {data_type} "
            f"(restore until {record.restore_until.isoformat()})"
        )
        
        return record
    
    def restore_purged_data(
        self,
        purge_id: str,
        restored_by: str,
    ) -> PurgeRecord:
        """Restore soft-deleted data."""
        record = next((r for r in self._purge_records if r.purge_id == purge_id), None)
        if not record:
            raise ValueError(f"Purge record '{purge_id}' not found")
        
        if not record.soft_deleted:
            raise ValueError(f"Purge '{purge_id}' was not soft-deleted")
        
        if record.restore_until and datetime.utcnow() > record.restore_until:
            raise ValueError(f"Restore window expired for purge '{purge_id}'")
        
        record.metadata["restored_by"] = restored_by
        record.metadata["restored_at"] = datetime.utcnow().isoformat()
        
        logger.info(f"Restored purged data from '{purge_id}' by {restored_by}")
        
        return record
    
    def _check_baseline_jump(
        self,
        before: Any,
        after: Any,
    ) -> Tuple[ValidationResult, str]:
        """Check for extreme jumps in baseline values."""
        try:
            if isinstance(before, (int, float)) and isinstance(after, (int, float)):
                if before == 0:
                    return ValidationResult.WARNING, "Cannot validate jump from zero baseline"
                
                change_pct = abs((after - before) / before)
                
                if change_pct > 0.5:
                    return ValidationResult.FAILED, f"Extreme jump: {change_pct:.1%} change"
                elif change_pct > 0.25:
                    return ValidationResult.WARNING, f"Large jump: {change_pct:.1%} change"
                else:
                    return ValidationResult.PASSED, f"Acceptable change: {change_pct:.1%}"
            
            return ValidationResult.WARNING, "Cannot validate non-numeric baseline"
        
        except Exception as e:
            return ValidationResult.FAILED, f"Validation error: {str(e)}"
    
    def _check_threshold_range(
        self,
        before: Any,
        after: Any,
    ) -> Tuple[ValidationResult, str]:
        """Check threshold is in reasonable range."""
        try:
            if isinstance(after, (int, float)):
                if after < 0:
                    return ValidationResult.FAILED, "Threshold cannot be negative"
                elif after > 1000:
                    return ValidationResult.WARNING, f"Very high threshold: {after}"
                else:
                    return ValidationResult.PASSED, f"Threshold in valid range: {after}"
            
            return ValidationResult.WARNING, "Cannot validate non-numeric threshold"
        
        except Exception as e:
            return ValidationResult.FAILED, f"Validation error: {str(e)}"
    
    def _check_sampling_rate(
        self,
        before: Any,
        after: Any,
    ) -> Tuple[ValidationResult, str]:
        """Check sampling rate is between 0 and 1."""
        try:
            if isinstance(after, (int, float)):
                if after < 0 or after > 1:
                    return ValidationResult.FAILED, f"Sampling rate must be 0-1, got {after}"
                else:
                    return ValidationResult.PASSED, f"Valid sampling rate: {after}"
            
            return ValidationResult.FAILED, "Sampling rate must be numeric"
        
        except Exception as e:
            return ValidationResult.FAILED, f"Validation error: {str(e)}"
    
    def _log_change(self, update: StagedUpdate) -> None:
        """Log change to audit trail."""
        entry_id = hashlib.md5(
            f"{update.update_id}_{datetime.utcnow().isoformat()}".encode()
        ).hexdigest()[:16]
        
        entry = ChangeLogEntry(
            entry_id=entry_id,
            timestamp=datetime.utcnow(),
            update_id=update.update_id,
            update_type=update.update_type,
            target=update.target,
            before_value=update.before_value,
            after_value=update.after_value,
            initiator=update.proposed_by,
            validator=update.metadata.get("validator"),
            approver=update.approved_by,
            validation_results=update.validation_results,
            status=update.status,
            metadata=update.metadata,
        )
        
        self._change_log.append(entry)
        self._save_change_log()
    
    def get_pending_updates(self) -> List[StagedUpdate]:
        """Get updates pending approval."""
        return [
            update for update in self._staged_updates.values()
            if update.status in [UpdateStatus.PROPOSED, UpdateStatus.VALIDATED, UpdateStatus.STAGED]
        ]
    
    def get_change_log(
        self,
        update_type: Optional[UpdateType] = None,
        target: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[ChangeLogEntry]:
        """Query change log."""
        entries = self._change_log
        
        if update_type:
            entries = [e for e in entries if e.update_type == update_type]
        
        if target:
            entries = [e for e in entries if e.target == target]
        
        if since:
            entries = [e for e in entries if e.timestamp >= since]
        
        return entries[-limit:]
    
    def get_safeguards_summary(self) -> Dict[str, Any]:
        """Get safeguards summary."""
        return {
            "staged_updates": len(self._staged_updates),
            "pending_approval": len(self.get_pending_updates()),
            "change_log_entries": len(self._change_log),
            "purge_records": len(self._purge_records),
            "validation_checks": sum(len(checks) for checks in self._validation_checks.values()),
            "critical_data_protected": len(self._critical_data_allowlist),
        }
    
    def _load_change_log(self) -> None:
        """Load change log from disk."""
        if not self.change_log_file.exists():
            return
        
        try:
            with open(self.change_log_file, 'r') as f:
                data = json.load(f)
            
            for entry_data in data.get("change_log", []):
                entry = ChangeLogEntry(
                    entry_id=entry_data["entry_id"],
                    timestamp=datetime.fromisoformat(entry_data["timestamp"]),
                    update_id=entry_data["update_id"],
                    update_type=UpdateType(entry_data["update_type"]),
                    target=entry_data["target"],
                    before_value=entry_data["before_value"],
                    after_value=entry_data["after_value"],
                    initiator=entry_data["initiator"],
                    validator=entry_data.get("validator"),
                    approver=entry_data.get("approver"),
                    validation_results=entry_data["validation_results"],
                    status=UpdateStatus(entry_data["status"]),
                    metadata=entry_data.get("metadata", {}),
                )
                self._change_log.append(entry)
            
            logger.info(f"Loaded change log: {len(self._change_log)} entries")
        
        except Exception as e:
            logger.error(f"Failed to load change log: {e}")
    
    def _save_change_log(self) -> None:
        """Save change log to disk."""
        try:
            data = {
                "change_log": [
                    {
                        "entry_id": entry.entry_id,
                        "timestamp": entry.timestamp.isoformat(),
                        "update_id": entry.update_id,
                        "update_type": entry.update_type.value,
                        "target": entry.target,
                        "before_value": entry.before_value,
                        "after_value": entry.after_value,
                        "initiator": entry.initiator,
                        "validator": entry.validator,
                        "approver": entry.approver,
                        "validation_results": entry.validation_results,
                        "status": entry.status.value,
                        "metadata": entry.metadata,
                    }
                    for entry in self._change_log
                ],
            }
            
            with open(self.change_log_file, 'w') as f:
                json.dump(data, f, indent=2)
        
        except Exception as e:
            logger.error(f"Failed to save change log: {e}")


_autonomous_update_safeguards: Optional[AutonomousUpdateSafeguards] = None


def get_autonomous_update_safeguards() -> AutonomousUpdateSafeguards:
    """Get global AutonomousUpdateSafeguards instance."""
    global _autonomous_update_safeguards
    if _autonomous_update_safeguards is None:
        _autonomous_update_safeguards = AutonomousUpdateSafeguards()
    return _autonomous_update_safeguards
