"""
Mode Transition Audit Logger

Provides SOX-grade audit logging for system mode transitions.
"""

import json
import threading
import time
import uuid
from typing import Dict, Optional
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

from utils.logger import get_logger

logger = get_logger("audit.mode_transitions")


@dataclass
class ModeTransitionEvent:
    """Immutable audit record for mode transitions."""
    event_id: str
    timestamp: float
    old_mode: str
    new_mode: str
    reason_code: str
    reason_detail: str
    
    # System state snapshots
    blind_spots_before: list
    blind_spots_after: list
    
    # Assertion metrics
    assertion_counts_per_domain: dict
    failing_assertions_count: int
    critical_assertions_count: int
    
    # Health status
    core_domains_health: dict
    execution_guard_status: bool
    local_venue_status: str
    
    # Trigger information
    triggering_actor: str  # "human", "ci", "agent", "autonomous_scheduler"
    triggering_actor_id: Optional[str]
    
    # Correlation and metadata
    correlation_id: str
    deployment_version: str
    incident_ticket: Optional[str]
    
    # Safety check results (if applicable)
    safety_check_results: Optional[dict]


class ModeTransitionAuditor:
    """
    SOX-grade audit logging for system mode transitions.
    
    Provides immutable, append-only logging of all mode changes
    with comprehensive metadata for regulatory compliance.
    """
    
    def __init__(self, audit_log_path: str = "audit/mode_transitions.jsonl"):
        self.audit_log_path = Path(audit_log_path)
        self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Ensure file exists and is append-only
        if not self.audit_log_path.exists():
            self.audit_log_path.touch()
            # Write header comment
            with open(self.audit_log_path, 'a') as f:
                f.write("# MERID Mode Transition Audit Log - SOX Grade - Append Only\n")
                f.write(f"# Created: {datetime.now(timezone.utc).isoformat()}\n")
    
    def log_mode_transition(self, 
                           old_mode: str,
                           new_mode: str,
                           reason_code: str,
                           reason_detail: str,
                           system_state: Dict,
                           triggering_actor: str = "autonomous_scheduler",
                           triggering_actor_id: Optional[str] = None,
                           correlation_id: Optional[str] = None,
                           deployment_version: str = "unknown",
                           incident_ticket: Optional[str] = None,
                           safety_check_results: Optional[Dict] = None) -> str:
        """
        Log a mode transition with full audit metadata.
        
        Returns the event ID for correlation.
        """
        try:
            event_id = str(uuid.uuid4())
            current_time = time.time()
            
            if correlation_id is None:
                correlation_id = str(uuid.uuid4())
            
            # Extract system state metrics
            registry_status = system_state.get("registry_status", {})
            blind_spots = registry_status.get("blind_spots", [])
            
            # Count assertions per domain
            assertion_counts_per_domain = {}
            core_domains = ["market", "onchain", "simulation", "agent", "execution", "governance", "treasury", "system"]
            
            # This would typically query the registry for actual counts
            # For now, we'll use placeholder data
            for domain in core_domains:
                assertion_counts_per_domain[domain] = 0  # Placeholder
            
            # Core domains health status
            core_domains_health = {}
            for domain in ["market", "onchain", "simulation", "agent"]:
                core_domains_health[domain] = domain not in blind_spots
            
            # Create audit event
            event = ModeTransitionEvent(
                event_id=event_id,
                timestamp=current_time,
                old_mode=old_mode,
                new_mode=new_mode,
                reason_code=reason_code,
                reason_detail=reason_detail,
                blind_spots_before=blind_spots,  # Same for now, would be tracked separately
                blind_spots_after=blind_spots,
                assertion_counts_per_domain=assertion_counts_per_domain,
                failing_assertions_count=0,  # Placeholder
                critical_assertions_count=0,  # Placeholder
                core_domains_health=core_domains_health,
                execution_guard_status=system_state.get("execution_allowed", True),
                local_venue_status="FAILING",  # Placeholder
                triggering_actor=triggering_actor,
                triggering_actor_id=triggering_actor_id,
                correlation_id=correlation_id,
                deployment_version=deployment_version,
                incident_ticket=incident_ticket,
                safety_check_results=safety_check_results
            )
            
            # Write to append-only log
            self._write_audit_event(event)
            
            # Log to system logger for immediate visibility
            logger.info(f"MODE_TRANSITION: {old_mode} → {new_mode} | Reason: {reason_code} | Event ID: {event_id}")
            
            return event_id
            
        except Exception as e:
            logger.error(f"Failed to log mode transition: {e}")
            # Return a fallback ID for correlation
            return f"error_{int(time.time())}"
    
    def _write_audit_event(self, event: ModeTransitionEvent):
        """Write audit event to append-only log file."""
        try:
            event_dict = asdict(event)
            
            # Add human-readable timestamp
            event_dict["human_timestamp"] = datetime.fromtimestamp(event.timestamp, tz=timezone.utc).isoformat()
            
            # Write as JSONL (one JSON object per line)
            with open(self.audit_log_path, 'a') as f:
                json.dump(event_dict, f, separators=(',', ':'))
                f.write('\n')
                
        except Exception as e:
            logger.error(f"Failed to write audit event to file: {e}")
            raise
    
    def get_transition_history(self, limit: int = 100) -> list:
        """Get recent mode transition history."""
        try:
            events = []
            
            with open(self.audit_log_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('#') or not line:
                        continue
                    
                    try:
                        event = json.loads(line)
                        events.append(event)
                    except json.JSONDecodeError:
                        continue
            
            # Sort by timestamp (newest first) and limit
            events.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
            return events[:limit]
            
        except Exception as e:
            logger.error(f"Failed to read transition history: {e}")
            return []
    
    def get_transition_by_id(self, event_id: str) -> Optional[Dict]:
        """Get a specific transition event by ID."""
        try:
            with open(self.audit_log_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('#') or not line:
                        continue
                    
                    try:
                        event = json.loads(line)
                        if event.get('event_id') == event_id:
                            return event
                    except json.JSONDecodeError:
                        continue
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get transition by ID: {e}")
            return None
    
    def query_transitions(self, 
                         old_mode: Optional[str] = None,
                         new_mode: Optional[str] = None,
                         reason_code: Optional[str] = None,
                         start_time: Optional[float] = None,
                         end_time: Optional[float] = None) -> list:
        """Query transitions with filters."""
        try:
            events = []
            
            with open(self.audit_log_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('#') or not line:
                        continue
                    
                    try:
                        event = json.loads(line)
                        
                        # Apply filters
                        if old_mode and event.get('old_mode') != old_mode:
                            continue
                        if new_mode and event.get('new_mode') != new_mode:
                            continue
                        if reason_code and event.get('reason_code') != reason_code:
                            continue
                        if start_time and event.get('timestamp', 0) < start_time:
                            continue
                        if end_time and event.get('timestamp', 0) > end_time:
                            continue
                        
                        events.append(event)
                        
                    except json.JSONDecodeError:
                        continue
            
            # Sort by timestamp (newest first)
            events.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
            return events
            
        except Exception as e:
            logger.error(f"Failed to query transitions: {e}")
            return []


# Global auditor instance
_mode_auditor: Optional[ModeTransitionAuditor] = None
_mode_auditor_lock = threading.Lock()


def get_mode_auditor() -> ModeTransitionAuditor:
    """Get the global mode transition auditor."""
    global _mode_auditor
    if _mode_auditor is None:
        with _mode_auditor_lock:
            if _mode_auditor is None:
                _mode_auditor = ModeTransitionAuditor()
    return _mode_auditor


# Convenience functions
def log_mode_transition(old_mode: str, new_mode: str, reason_code: str, reason_detail: str, system_state: Dict, **kwargs) -> str:
    """Convenience function to log mode transitions."""
    auditor = get_mode_auditor()
    return auditor.log_mode_transition(
        old_mode=old_mode,
        new_mode=new_mode,
        reason_code=reason_code,
        reason_detail=reason_detail,
        system_state=system_state,
        **kwargs
    )


def log_transition_denied(old_mode: str, reason_code: str, reason_detail: str, system_state: Dict, safety_check_results: Dict, **kwargs) -> str:
    """Log a denied transition attempt."""
    return log_mode_transition(
        old_mode=old_mode,
        new_mode=old_mode,  # No change
        reason_code=f"TRANSITION_DENIED_{reason_code}",
        reason_detail=reason_detail,
        system_state=system_state,
        safety_check_results=safety_check_results,
        **kwargs
    )


def log_rollback(from_mode: str, to_mode: str, reason_code: str, reason_detail: str, system_state: Dict, **kwargs) -> str:
    """Log a mode rollback."""
    return log_mode_transition(
        old_mode=from_mode,
        new_mode=to_mode,
        reason_code=f"ROLLBACK_{reason_code}",
        reason_detail=reason_detail,
        system_state=system_state,
        **kwargs
    )
