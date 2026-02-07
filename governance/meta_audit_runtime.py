"""Meta Audit Runtime implementing governance gating and audit trail primitives."""
from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.event_bus import event_stream
from core.persistence_manager import get_persistence_manager
from core.telemetry_manager import get_telemetry_manager
from agents.reflection_layer import reflection_layer
from utils.logger import get_logger

logger = get_logger("governance.meta_audit_runtime")


class PromotionDecision(Enum):
    APPROVE = "approve"
    REJECT = "reject"
    THROTTLE = "throttle"


@dataclass
class MetaAuditSystemSpec:
    system_id: str
    display_name: str
    owner: str
    risk_owner: str
    risk_tier: str
    lifecycle_stage: str
    environments: List[str]
    telemetry_bindings: Dict[str, Any]
    last_audit_at: Optional[float] = None
    policies: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PromotionEvidence:
    evidence_id: str
    strategy_id: str
    from_stage: str
    to_stage: str
    metrics: Dict[str, Any]
    criteria: Dict[str, bool]
    attachments: List[str]
    hash_root: str
    submitted_by: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class PromotionGateRequest:
    strategy_id: str
    from_stage: str
    to_stage: str
    risk_tier: str
    evidence_ids: List[str]
    criteria: Dict[str, bool]
    metrics: Dict[str, Any]
    requested_by: str
    change_ticket: Optional[str]
    context: Dict[str, Any] = field(default_factory=dict)
    override: bool = False


@dataclass
class PromotionGateDecision:
    decision: PromotionDecision
    severity: str
    rationale: str
    required_actions: List[str]
    signatures: List[str]
    directive_id: Optional[str]
    expires_at: float


@dataclass
class GovernanceDirective:
    directive_id: str
    directive_type: str
    severity: str
    description: str
    target: str
    issued_by: str
    issued_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    status: str = "active"


@dataclass
class MetaAuditIncident:
    incident_id: str
    system_id: str
    summary: str
    severity: str
    impact: str
    status: str
    opened_at: float = field(default_factory=time.time)
    closed_at: Optional[float] = None


@dataclass
class AuditLogEntry:
    entry_id: str
    timestamp: float
    action: str
    payload: Dict[str, Any]
    prev_hash: str
    entry_hash: str


@dataclass
class AuditProof:
    chain_head: str
    entry_count: int


@dataclass
class InventorySnapshot:
    systems: List[MetaAuditSystemSpec]
    directives: List[GovernanceDirective]
    incidents: List[MetaAuditIncident]


@dataclass
class MetaAuditKPIs:
    coverage_pct: float
    open_incidents: int
    promotion_block_rate: float
    audit_trail_length: int
    last_chain_head: str


class AuditTrail:
    """Append-only audit trail with hash chaining."""

    def __init__(self, storage_path: Path) -> None:
        self._storage_path = storage_path
        self._persistence = get_persistence_manager()
        self._lock = threading.RLock()
        self._entries: List[AuditLogEntry] = []
        self._load()

    def append(self, action: str, payload: Dict[str, Any]) -> AuditLogEntry:
        with self._lock:
            prev_hash = self._entries[-1].entry_hash if self._entries else "0" * 64
            entry_id = str(uuid.uuid4())
            timestamp = time.time()
            entry_hash = self._compute_hash(entry_id, timestamp, action, payload, prev_hash)
            entry = AuditLogEntry(
                entry_id=entry_id,
                timestamp=timestamp,
                action=action,
                payload=payload,
                prev_hash=prev_hash,
                entry_hash=entry_hash,
            )
            self._entries.append(entry)
            self._persist()
            return entry

    def verify(self, chain_head: str) -> bool:
        with self._lock:
            if not self._entries:
                return chain_head == ""
            return self._entries[-1].entry_hash == chain_head

    def proof(self) -> AuditProof:
        with self._lock:
            head = self._entries[-1].entry_hash if self._entries else ""
            return AuditProof(chain_head=head, entry_count=len(self._entries))

    def __len__(self) -> int:
        return len(self._entries)

    def _compute_hash(
        self,
        entry_id: str,
        timestamp: float,
        action: str,
        payload: Dict[str, Any],
        prev_hash: str,
    ) -> str:
        hasher = hashlib.sha256()
        hasher.update(entry_id.encode())
        hasher.update(str(timestamp).encode())
        hasher.update(action.encode())
        hasher.update(json.dumps(payload, sort_keys=True).encode())
        hasher.update(prev_hash.encode())
        return hasher.hexdigest()

    def _persist(self) -> None:
        data = [asdict(entry) for entry in self._entries]
        self._persistence.write_json(str(self._storage_path), data, immediate=False)

    def _load(self) -> None:
        try:
            data = self._persistence.read_json(str(self._storage_path))
        except FileNotFoundError:
            data = []
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to load meta audit trail: %s", exc)
            data = []
        for raw in data:
            self._entries.append(
                AuditLogEntry(
                    entry_id=raw["entry_id"],
                    timestamp=raw["timestamp"],
                    action=raw["action"],
                    payload=raw["payload"],
                    prev_hash=raw["prev_hash"],
                    entry_hash=raw["entry_hash"],
                )
            )


class MetaAuditRuntime:
    """Runtime that enforces promotion gates and audit logging."""

    def __init__(self, storage_dir: Path | None = None) -> None:
        base_dir = storage_dir or Path("data/meta_audit")
        base_dir.mkdir(parents=True, exist_ok=True)
        self._inventory_path = base_dir / "inventory.json"
        self._trail = AuditTrail(base_dir / "audit_trail.json")
        self._persistence = get_persistence_manager()
        self._lock = threading.RLock()
        self._systems: Dict[str, MetaAuditSystemSpec] = {}
        self._evidence: Dict[str, PromotionEvidence] = {}
        self._directives: Dict[str, GovernanceDirective] = {}
        self._incidents: Dict[str, MetaAuditIncident] = {}
        self._promotion_stats: Dict[str, int] = {"total": 0, "blocked": 0}
        self._load_inventory()
        self._telemetry = get_telemetry_manager()
        self._reflection = reflection_layer

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def register_system(self, system: MetaAuditSystemSpec) -> str:
        with self._lock:
            self._systems[system.system_id] = system
            self._persist_inventory()
        self._trail.append("register_system", asdict(system))
        self._log_meta_event(
            event_type="system_registered",
            message=f"System registered: {system.system_id}",
            fields={
                "system_id": system.system_id,
                "risk_tier": system.risk_tier,
                "lifecycle_stage": system.lifecycle_stage,
            },
        )
        logger.info("MetaAudit registered system %s", system.system_id)
        return system.system_id

    def record_evidence(self, evidence: PromotionEvidence) -> str:
        with self._lock:
            self._evidence[evidence.evidence_id] = evidence
            self._persist_inventory()
        self._trail.append("record_evidence", asdict(evidence))
        self._log_meta_event(
            event_type="evidence_recorded",
            message=f"Evidence recorded for {evidence.strategy_id}",
            fields={
                "strategy_id": evidence.strategy_id,
                "from_stage": evidence.from_stage,
                "to_stage": evidence.to_stage,
                "evidence_id": evidence.evidence_id,
            },
        )
        return evidence.evidence_id

    def review_promotion(self, request: PromotionGateRequest) -> PromotionGateDecision:
        with self._lock:
            self._promotion_stats["total"] += 1
            evidence = [self._evidence[eid] for eid in request.evidence_ids if eid in self._evidence]
            missing_controls = [name for name, ok in request.criteria.items() if not ok]
            missing_evidence = len(evidence) != len(request.evidence_ids)
            open_incidents = [inc for inc in self._incidents.values() if inc.system_id == request.strategy_id and inc.status == "open"]

        severity = "info"
        decision = PromotionDecision.APPROVE
        rationale_parts: List[str] = []
        actions: List[str] = []
        directive_id: Optional[str] = None

        if missing_evidence:
            decision = PromotionDecision.THROTTLE
            severity = "warning"
            rationale_parts.append("Evidence set incomplete")
            actions.append("Resubmit with complete evidence bundle")

        if missing_controls:
            decision = PromotionDecision.REJECT
            severity = "critical"
            rationale_parts.append(f"Controls failing: {', '.join(missing_controls)}")
            actions.append("Remediate failing controls and re-run promotion checklist")

        critical_incident = next((inc for inc in open_incidents if inc.severity in {"high", "critical"}), None)
        if critical_incident:
            decision = PromotionDecision.THROTTLE
            severity = "critical"
            rationale_parts.append(f"Open incident {critical_incident.incident_id} ({critical_incident.severity})")
            actions.append("Close incident or downgrade system before promotion")

        if request.override and decision != PromotionDecision.APPROVE:
            rationale_parts.append("Manual override requested but MAS veto maintained")

        if decision != PromotionDecision.APPROVE:
            self._promotion_stats["blocked"] += 1
            directive = self._auto_directive(request, severity, rationale_parts)
            directive_id = directive.directive_id
            actions.append(f"Follow directive {directive_id}")

        if not rationale_parts:
            rationale_parts.append("All MAS controls satisfied")

        decision_payload = {
            "request": asdict(request),
            "decision": decision.value,
            "severity": severity,
            "actions": actions,
        }
        self._trail.append("review_promotion", decision_payload)
        event_stream.publish_nowait(
            "meta_audit:promotion_decision",
            {
                "strategy_id": request.strategy_id,
                "decision": decision.value,
                "severity": severity,
                "rationale": " | ".join(rationale_parts),
            },
        )
        self._log_meta_event(
            event_type="promotion_decision",
            message=f"Promotion {decision.value} for {request.strategy_id}",
            fields={
                "strategy_id": request.strategy_id,
                "from_stage": request.from_stage,
                "to_stage": request.to_stage,
                "decision": decision.value,
                "severity": severity,
                "required_actions": actions,
            },
        )
        self._record_reflection_decision(request, decision, " | ".join(rationale_parts))
        self._record_metric(
            metric_name=f"meta_audit.promotion_decision",
            value=1.0,
            tags={"decision": decision.value, "severity": severity},
        )

        return PromotionGateDecision(
            decision=decision,
            severity=severity,
            rationale=" | ".join(rationale_parts),
            required_actions=actions,
            signatures=["meta_audit_runtime"],
            directive_id=directive_id,
            expires_at=time.time() + 3600,
        )

    def issue_directive(self, directive: GovernanceDirective) -> str:
        with self._lock:
            self._directives[directive.directive_id] = directive
            self._persist_inventory()
        self._trail.append("issue_directive", asdict(directive))
        event_stream.publish_nowait(
            "meta_audit:directive",
            {
                "directive_id": directive.directive_id,
                "severity": directive.severity,
                "target": directive.target,
                "description": directive.description,
            },
        )
        self._log_meta_event(
            event_type="directive_issued",
            message=f"Directive {directive.directive_type} issued",
            fields={
                "directive_id": directive.directive_id,
                "severity": directive.severity,
                "target": directive.target,
            },
        )
        self._record_metric(
            metric_name="meta_audit.directive",
            value=1.0,
            tags={"severity": directive.severity},
        )
        return directive.directive_id

    def log_incident(self, incident: MetaAuditIncident) -> str:
        with self._lock:
            self._incidents[incident.incident_id] = incident
            self._persist_inventory()
        self._trail.append("log_incident", asdict(incident))
        event_stream.publish_nowait(
            "meta_audit:incident",
            {
                "incident_id": incident.incident_id,
                "system_id": incident.system_id,
                "severity": incident.severity,
                "status": incident.status,
            },
        )
        self._log_meta_event(
            event_type="incident_logged",
            message=f"Incident {incident.incident_id} logged",
            fields={
                "incident_id": incident.incident_id,
                "system_id": incident.system_id,
                "severity": incident.severity,
                "status": incident.status,
            },
        )
        self._record_metric(
            metric_name="meta_audit.incident",
            value=1.0,
            tags={"severity": incident.severity, "status": incident.status},
        )
        return incident.incident_id

    def attest_audit_trail(self, proof: AuditProof) -> bool:
        valid = self._trail.verify(proof.chain_head)
        logger.info("MetaAudit audit trail attest %s", "passed" if valid else "failed")
        return valid

    def get_inventory_snapshot(self, risk_tier: Optional[str] = None) -> InventorySnapshot:
        with self._lock:
            systems = [spec for spec in self._systems.values() if not risk_tier or spec.risk_tier == risk_tier]
            directives = list(self._directives.values())
            incidents = list(self._incidents.values())
        return InventorySnapshot(systems=systems, directives=directives, incidents=incidents)

    def get_kpi_dashboard(self) -> MetaAuditKPIs:
        with self._lock:
            governed = len(self._systems)
            blocked = self._promotion_stats["blocked"]
            total = max(1, self._promotion_stats["total"])
        coverage = 100.0 if governed else 0.0
        proof = self._trail.proof()
        return MetaAuditKPIs(
            coverage_pct=coverage,
            open_incidents=sum(1 for inc in self._incidents.values() if inc.status == "open"),
            promotion_block_rate=blocked / total,
            audit_trail_length=proof.entry_count,
            last_chain_head=proof.chain_head,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _auto_directive(
        self,
        request: PromotionGateRequest,
        severity: str,
        rationale_parts: List[str],
    ) -> GovernanceDirective:
        directive = GovernanceDirective(
            directive_id=str(uuid.uuid4()),
            directive_type="promotion_block",
            severity=severity,
            description=" | ".join(rationale_parts),
            target=request.strategy_id,
            issued_by="meta_audit_runtime",
        )
        self.issue_directive(directive)
        return directive

    def _log_meta_event(self, event_type: str, message: str, fields: Dict[str, Any]) -> None:
        if not self._telemetry:
            return
        try:
            self._telemetry.log_structured(
                stream_name="meta_audit",
                level="INFO",
                event_type=event_type,
                message=message,
                fields=fields,
                agent_id="meta_audit_runtime",
                strategy_id=fields.get("strategy_id"),
            )
        except Exception:  # pragma: no cover
            logger.exception("Failed to emit meta audit telemetry for %s", event_type)

    def _record_metric(self, metric_name: str, value: float, tags: Optional[Dict[str, str]] = None) -> None:
        if not self._telemetry:
            return
        try:
            self._telemetry.record_metric(
                stream_name="meta_audit",
                metric_name=metric_name,
                value=value,
                tags=tags or {},
            )
        except Exception:  # pragma: no cover
            logger.exception("Failed to record meta audit metric %s", metric_name)

    def _record_reflection_decision(
        self,
        request: PromotionGateRequest,
        decision: PromotionDecision,
        rationale: str,
    ) -> None:
        energy_id = f"promotion::{request.strategy_id}::{request.to_stage}::{request.evidence_ids[0] if request.evidence_ids else 'none'}"
        confidence = 0.9 if decision == PromotionDecision.APPROVE else 0.2
        try:
            self._reflection.record_decision(
                agent_id="meta_audit_runtime",
                energy_id=energy_id,
                decision=decision.value,
                confidence=confidence,
                reasoning=rationale,
            )
            self._reflection.record_outcome(
                energy_id=energy_id,
                validated=decision == PromotionDecision.APPROVE,
                reality_gap=0.0,
            )
        except Exception:  # pragma: no cover
            logger.exception("Failed to record reflection for meta audit decision")

    def _persist_inventory(self) -> None:
        data = {
            "systems": [asdict(spec) for spec in self._systems.values()],
            "evidence": [asdict(ev) for ev in self._evidence.values()],
            "directives": [asdict(di) for di in self._directives.values()],
            "incidents": [asdict(inc) for inc in self._incidents.values()],
        }
        self._persistence.write_json(str(self._inventory_path), data, immediate=False)

    def _load_inventory(self) -> None:
        try:
            raw = self._persistence.read_json(str(self._inventory_path))
        except FileNotFoundError:
            return
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to load meta audit inventory: %s", exc)
            return
        for item in raw.get("systems", []):
            self._systems[item["system_id"]] = MetaAuditSystemSpec(**item)
        for item in raw.get("evidence", []):
            self._evidence[item["evidence_id"]] = PromotionEvidence(**item)
        for item in raw.get("directives", []):
            self._directives[item["directive_id"]] = GovernanceDirective(**item)
        for item in raw.get("incidents", []):
            self._incidents[item["incident_id"]] = MetaAuditIncident(**item)


_runtime: Optional[MetaAuditRuntime] = None


def get_meta_audit_runtime() -> MetaAuditRuntime:
    global _runtime
    if _runtime is None:
        _runtime = MetaAuditRuntime()
    return _runtime


__all__ = [
    "MetaAuditRuntime",
    "get_meta_audit_runtime",
    "MetaAuditSystemSpec",
    "PromotionEvidence",
    "PromotionGateRequest",
    "PromotionGateDecision",
    "PromotionDecision",
    "GovernanceDirective",
    "MetaAuditIncident",
    "MetaAuditKPIs",
    "InventorySnapshot",
    "AuditProof",
]
