"""Promotion Report — single-command readiness assessment for MERID.

Aggregates three concentric rings of validation:
  1. Blueprint checks  (architecture health)
  2. Paper matrix SLOs  (multi-asset paper behavior)
  3. Agent gauntlet     (per-agent quality gate)

Produces a unified PromotionReport that answers:
  - Which domains are eligible for live execution?
  - Which agents are promoted?
  - What is blocking promotion for each?

Usage:
  python -m merid.promotion_report              # human-readable
  python -m merid.promotion_report --json       # structured JSON
  python -m merid.promotion_report --fast       # 5-cycle gauntlet
"""

from __future__ import annotations

import asyncio
import json as _json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

import logging
logger = logging.getLogger("promotion_report")

logger = get_logger(__name__)


# ── Data Model ───────────────────────────────────────────────────────

@dataclass
class RingResult:
    """Result of one validation ring."""
    name: str
    passed: bool
    checks_passed: int = 0
    checks_total: int = 0
    failures: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    elapsed_s: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "checks_passed": self.checks_passed,
            "checks_total": self.checks_total,
            "pass_rate": round(self.checks_passed / self.checks_total, 2) if self.checks_total else 0,
            "failures": self.failures,
            "warnings": self.warnings,
            "elapsed_s": round(self.elapsed_s, 2),
        }


@dataclass
class DomainEligibility:
    """Live-execution eligibility for a single domain."""
    domain: str
    eligible: bool
    mode: str = "paper"
    blockers: List[str] = field(default_factory=list)
    instruments: int = 0
    reconciliation_venue: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "eligible": self.eligible,
            "mode": self.mode,
            "blockers": self.blockers,
            "instruments": self.instruments,
            "reconciliation_venue": self.reconciliation_venue,
        }


@dataclass
class AgentPromotion:
    """Promotion status for a single agent."""
    agent_id: str
    category: str
    promoted: bool
    slo_pass_rate: float = 0.0
    failed_slos: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "category": self.category,
            "promoted": self.promoted,
            "slo_pass_rate": round(self.slo_pass_rate, 2),
            "failed_slos": self.failed_slos,
        }


@dataclass
class PromotionReport:
    """Unified promotion report across all three rings."""
    timestamp: float = 0.0
    overall_eligible: bool = False
    rings: List[RingResult] = field(default_factory=list)
    domains: List[DomainEligibility] = field(default_factory=list)
    agents: List[AgentPromotion] = field(default_factory=list)
    elapsed_s: float = 0.0

    @property
    def all_rings_pass(self) -> bool:
        return all(r.passed for r in self.rings)

    @property
    def promoted_agents(self) -> List[str]:
        return [a.agent_id for a in self.agents if a.promoted]

    @property
    def blocked_agents(self) -> List[str]:
        return [a.agent_id for a in self.agents if not a.promoted]

    @property
    def eligible_domains(self) -> List[str]:
        return [d.domain for d in self.domains if d.eligible]

    @property
    def blocked_domains(self) -> List[str]:
        return [d.domain for d in self.domains if not d.eligible]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "overall_eligible": self.overall_eligible,
            "all_rings_pass": self.all_rings_pass,
            "rings": [r.to_dict() for r in self.rings],
            "domains": {
                "eligible": self.eligible_domains,
                "blocked": self.blocked_domains,
                "detail": [d.to_dict() for d in self.domains],
            },
            "agents": {
                "promoted": self.promoted_agents,
                "blocked": self.blocked_agents,
                "detail": [a.to_dict() for a in self.agents],
            },
            "elapsed_s": round(self.elapsed_s, 2),
        }


# ── Promotion Change Log ──────────────────────────────────────────────

@dataclass
class PromotionEvent:
    """Immutable record of a promotion status change."""
    timestamp: float
    entity_type: str          # "domain" or "agent"
    entity_id: str            # domain name or agent_id
    previous_status: str      # "eligible"/"blocked"/"unknown"
    new_status: str           # "eligible"/"blocked"
    reason: str = ""          # human-readable explanation
    report_timestamp: float = 0.0  # which report triggered this
    runbook_version: str = "1.0"
    source: str = "system"    # "automation", "operator", or "system"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "previous_status": self.previous_status,
            "new_status": self.new_status,
            "reason": self.reason,
            "report_timestamp": self.report_timestamp,
            "runbook_version": self.runbook_version,
            "source": self.source,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> PromotionEvent:
        return PromotionEvent(
            timestamp=d["timestamp"],
            entity_type=d["entity_type"],
            entity_id=d["entity_id"],
            previous_status=d["previous_status"],
            new_status=d["new_status"],
            reason=d.get("reason", ""),
            report_timestamp=d.get("report_timestamp", 0.0),
            runbook_version=d.get("runbook_version", "1.0"),
            source=d.get("source", "system"),
        )


_LOG_FILE = Path(os.environ.get(
    "MERID_PROMOTION_LOG",
    Path(__file__).parent.parent / "data" / "promotion_log.json",
))

_LOG_MAX_EVENTS = int(os.environ.get("MERID_PROMOTION_LOG_MAX_EVENTS", "10000"))


class PromotionLog:
    """Append-only promotion change log with JSON file persistence."""

    def __init__(self, log_file: Optional[Path] = None, max_events: Optional[int] = None):
        self._file = log_file or _LOG_FILE
        self._events: List[PromotionEvent] = []
        self._loaded = False
        self._max_events = max_events if max_events is not None else _LOG_MAX_EVENTS

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            if self._file.exists():
                with open(self._file, "r") as f:
                    raw = _json.load(f)
                self._events = [PromotionEvent.from_dict(e) for e in raw]
                logger.info(f"promotion_log: loaded {len(self._events)} events from {self._file}")
        except Exception as exc:
            logger.warning(f"promotion_log: failed to load {self._file}: {exc}")
            self._events = []

    def _persist(self) -> None:
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._file, "w") as f:
                _json.dump([e.to_dict() for e in self._events], f, indent=2)
        except Exception as exc:
            logger.warning(f"promotion_log: failed to persist: {exc}")

    def append(self, event: PromotionEvent) -> None:
        self._ensure_loaded()
        self._events.append(event)
        # Rotate if over cap
        if len(self._events) > self._max_events:
            trim = len(self._events) - self._max_events
            self._events = self._events[trim:]
            logger.info(f"promotion_log: rotated {trim} oldest events (cap={self._max_events})")
        self._persist()
        logger.info(
            f"promotion_log: {event.entity_type} '{event.entity_id}' "
            f"{event.previous_status} -> {event.new_status}"
        )
        # Governance notification: operator overrides always notify,
        # automation events notify only for real transitions (not initial baseline)
        should_notify = (
            event.source == "operator"
            or (event.source == "automation" and event.previous_status != "unknown")
        )
        if should_notify:
            try:
                from merid.governance_notifier import get_governance_notifier
                get_governance_notifier().notify(event.to_dict())
            except Exception as exc:
                logger.warning(f"promotion_log: governance notify failed: {exc}")

    def events(
        self,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 100,
    ) -> List[PromotionEvent]:
        self._ensure_loaded()
        out = self._events
        if entity_type:
            out = [e for e in out if e.entity_type == entity_type]
        if entity_id:
            out = [e for e in out if e.entity_id == entity_id]
        if source:
            out = [e for e in out if e.source == source]
        return out[-limit:]

    def latest_for(self, entity_type: str, entity_id: str) -> Optional[PromotionEvent]:
        matches = [e for e in self.events() if e.entity_type == entity_type and e.entity_id == entity_id]
        return matches[-1] if matches else None

    def clear(self) -> None:
        self._events = []
        self._loaded = True
        self._persist()

    def __len__(self) -> int:
        self._ensure_loaded()
        return len(self._events)


# Module-level singleton
_promotion_log: Optional[PromotionLog] = None


def get_promotion_log() -> PromotionLog:
    global _promotion_log
    if _promotion_log is None:
        _promotion_log = PromotionLog()
    return _promotion_log


def _diff_and_log(
    previous: Optional[PromotionReport],
    current: PromotionReport,
) -> List[PromotionEvent]:
    """Compare two reports and emit PromotionEvents for any status changes."""
    log = get_promotion_log()
    events: List[PromotionEvent] = []
    now = time.time()

    # Build previous state maps
    prev_domains: Dict[str, bool] = {}
    prev_agents: Dict[str, bool] = {}
    if previous:
        prev_domains = {d.domain: d.eligible for d in previous.domains}
        prev_agents = {a.agent_id: a.promoted for a in previous.agents}

    # Domain transitions
    for d in current.domains:
        prev_eligible = prev_domains.get(d.domain)
        if prev_eligible is None:
            prev_status = "unknown"
        else:
            prev_status = "eligible" if prev_eligible else "blocked"
        new_status = "eligible" if d.eligible else "blocked"

        if prev_status != new_status:
            reason = ""
            if new_status == "blocked" and d.blockers:
                reason = "; ".join(d.blockers)
            elif new_status == "eligible":
                reason = "all rings passing, domain meets requirements"

            event = PromotionEvent(
                timestamp=now,
                entity_type="domain",
                entity_id=d.domain,
                previous_status=prev_status,
                new_status=new_status,
                reason=reason,
                report_timestamp=current.timestamp,
                source="automation",
            )
            log.append(event)
            events.append(event)

    # Agent transitions
    for a in current.agents:
        prev_promoted = prev_agents.get(a.agent_id)
        if prev_promoted is None:
            prev_status = "unknown"
        else:
            prev_status = "eligible" if prev_promoted else "blocked"
        new_status = "eligible" if a.promoted else "blocked"

        if prev_status != new_status:
            reason = ""
            if new_status == "blocked" and a.failed_slos:
                reason = f"failed SLOs: {', '.join(a.failed_slos)}"
            elif new_status == "eligible":
                reason = f"all SLOs passing ({a.slo_pass_rate:.0%})"

            event = PromotionEvent(
                timestamp=now,
                entity_type="agent",
                entity_id=a.agent_id,
                previous_status=prev_status,
                new_status=new_status,
                reason=reason,
                report_timestamp=current.timestamp,
                source="automation",
            )
            log.append(event)
            events.append(event)

    if events:
        logger.info(f"promotion_log: {len(events)} status changes detected")

    return events


def manual_promote(
    entity_type: str,
    entity_id: str,
    reason: str = "",
    operator: str = "unknown",
) -> PromotionEvent:
    """Record an operator-initiated promotion event.

    This does NOT change the underlying report — it records the operator's
    intent in the change log so the audit trail distinguishes manual
    overrides from automated transitions.
    """
    log = get_promotion_log()
    prev = log.latest_for(entity_type, entity_id)
    prev_status = prev.new_status if prev else "unknown"

    event = PromotionEvent(
        timestamp=time.time(),
        entity_type=entity_type,
        entity_id=entity_id,
        previous_status=prev_status,
        new_status="eligible",
        reason=reason or f"manual promotion by {operator}",
        source="operator",
    )
    log.append(event)
    return event


def manual_demote(
    entity_type: str,
    entity_id: str,
    reason: str = "",
    operator: str = "unknown",
) -> PromotionEvent:
    """Record an operator-initiated demotion event.

    This does NOT change the underlying report — it records the operator's
    intent in the change log so the audit trail distinguishes manual
    overrides from automated transitions.
    """
    log = get_promotion_log()
    prev = log.latest_for(entity_type, entity_id)
    prev_status = prev.new_status if prev else "unknown"

    event = PromotionEvent(
        timestamp=time.time(),
        entity_type=entity_type,
        entity_id=entity_id,
        previous_status=prev_status,
        new_status="blocked",
        reason=reason or f"manual demotion by {operator}",
        source="operator",
    )
    log.append(event)
    return event


# ── Ring 1: Blueprint Checks ────────────────────────────────────────

def _run_blueprint_checks() -> RingResult:
    """Run CI blueprint checks and parse results."""
    t0 = time.time()
    try:
        from scripts.ci_blueprint_checks import run_all_checks
        results = run_all_checks()

        passed = sum(1 for r in results if r["status"] == "pass")
        total = len(results)
        failures = [r["name"] for r in results if r["status"] == "fail"]
        warnings = [r["name"] for r in results if r["status"] == "warn"]

        return RingResult(
            name="blueprint",
            passed=len(failures) == 0,
            checks_passed=passed,
            checks_total=total,
            failures=failures,
            warnings=warnings,
            elapsed_s=time.time() - t0,
        )
    except ImportError:
        # Fallback: run as subprocess
        try:
            result = subprocess.run(
                [sys.executable, "scripts/ci_blueprint_checks.py", "--json"],
                capture_output=True, text=True, timeout=30,
            )
            import json
            data = json.loads(result.stdout)
            checks = data.get("checks", [])
            passed = sum(1 for c in checks if c.get("status") == "pass")
            failures = [c["name"] for c in checks if c.get("status") == "fail"]
            warnings = [c["name"] for c in checks if c.get("status") == "warn"]
            return RingResult(
                name="blueprint",
                passed=result.returncode == 0,
                checks_passed=passed,
                checks_total=len(checks),
                failures=failures,
                warnings=warnings,
                elapsed_s=time.time() - t0,
            )
        except Exception as e:
            return RingResult(
                name="blueprint", passed=False,
                failures=[f"could not run: {e}"],
                elapsed_s=time.time() - t0,
            )
    except Exception as e:
        return RingResult(
            name="blueprint", passed=False,
            failures=[str(e)],
            elapsed_s=time.time() - t0,
        )


# ── Ring 2: Paper Matrix SLOs ───────────────────────────────────────

def _run_paper_matrix() -> RingResult:
    """Run paper trading matrix tests and parse results."""
    t0 = time.time()
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest",
             "tests/test_paper_trading_matrix.py",
             "-v", "--tb=line", "-q"],
            capture_output=True, text=True, timeout=120,
        )
        output = result.stdout + result.stderr

        # Parse pytest summary line: "X passed, Y failed, Z skipped"
        passed = 0
        failed = 0
        total = 0
        failures = []

        for line in output.splitlines():
            if "passed" in line and ("failed" in line or "warning" in line or "skipped" in line or line.strip().startswith("=")):
                import re
                m_pass = re.search(r"(\d+) passed", line)
                m_fail = re.search(r"(\d+) failed", line)
                if m_pass:
                    passed = int(m_pass.group(1))
                if m_fail:
                    failed = int(m_fail.group(1))
                total = passed + failed

            if "FAILED" in line:
                # Extract test name
                test_name = line.split("FAILED")[-1].strip() if "FAILED" in line else line
                # Clean up: get just the test function name
                if "::" in test_name:
                    test_name = test_name.split("::")[-1].strip()
                if test_name:
                    failures.append(test_name)

        if total == 0:
            total = passed

        return RingResult(
            name="paper_matrix",
            passed=result.returncode == 0 or (failed == 0 and passed > 0),
            checks_passed=passed,
            checks_total=max(total, passed),
            failures=failures,
            elapsed_s=time.time() - t0,
        )
    except Exception as e:
        return RingResult(
            name="paper_matrix", passed=False,
            failures=[str(e)],
            elapsed_s=time.time() - t0,
        )


# ── Ring 3: Agent Gauntlet ──────────────────────────────────────────

def _run_agent_gauntlet(cycles: int = 10) -> tuple:
    """Run agent gauntlet and return (RingResult, List[AgentPromotion])."""
    t0 = time.time()
    coro = None
    try:
        from merid.agent_gauntlet import run_gauntlet, gauntlet_summary, GauntletResult

        coro = run_gauntlet(cycles=cycles)
        verdicts = asyncio.run(coro)
        coro = None
        summary = gauntlet_summary(verdicts)

        agent_promotions = []
        for v in verdicts:
            agent_promotions.append(AgentPromotion(
                agent_id=v.agent_id,
                category=v.category,
                promoted=v.promoted,
                slo_pass_rate=v.pass_rate,
                failed_slos=[c.name for c in v.checks if not c.passed],
            ))

        failures = [v.agent_id for v in verdicts if v.result == GauntletResult.FAIL]

        ring = RingResult(
            name="gauntlet",
            passed=summary["failed"] == 0,
            checks_passed=summary["passed"],
            checks_total=summary["total_agents"],
            failures=failures,
            elapsed_s=time.time() - t0,
        )
        return ring, agent_promotions

    except Exception as e:
        if coro is not None:
            coro.close()
        ring = RingResult(
            name="gauntlet", passed=False,
            failures=[str(e)],
            elapsed_s=time.time() - t0,
        )
        return ring, []


# ── Domain Eligibility ──────────────────────────────────────────────

def _assess_domains(rings_pass: bool) -> List[DomainEligibility]:
    """Assess per-domain live eligibility."""
    try:
        from merid.paper_config import DOMAIN_CONFIGS, instruments_for_domain
    except ImportError:
        return []

    domains = []
    for name, dc in DOMAIN_CONFIGS.items():
        blockers = []

        if not dc.enabled:
            blockers.append("domain disabled")
        if not rings_pass:
            blockers.append("validation rings not all passing")
        if dc.mode.value != "paper":
            blockers.append(f"mode is {dc.mode.value}, not paper")

        # Check instrument coverage
        instruments = instruments_for_domain(name)
        if len(instruments) == 0:
            blockers.append("no instruments registered")

        # Check reconciliation for domains that need it
        if name in ("crypto", "equity") and not dc.reconciliation_venue:
            blockers.append("no reconciliation venue configured")

        # Check matching engine for prediction
        if name == "prediction":
            try:
                from merid.matching_engine import get_matching_engine
                engine = get_matching_engine("prediction")
                if not engine.enabled:
                    blockers.append("matching engine disabled")
            except Exception:
                blockers.append("matching engine not available")

        domains.append(DomainEligibility(
            domain=name,
            eligible=len(blockers) == 0,
            mode=dc.mode.value,
            blockers=blockers,
            instruments=len(instruments),
            reconciliation_venue=dc.reconciliation_venue,
        ))

    return domains


# ── Main Runner ──────────────────────────────────────────────────────

def generate_promotion_report(gauntlet_cycles: int = 10) -> PromotionReport:
    """Run all three rings and produce a unified promotion report."""
    t0 = time.time()
    report = PromotionReport(timestamp=time.time())

    logger.info("Promotion report: starting Ring 1 (blueprint checks)")
    ring1 = _run_blueprint_checks()
    report.rings.append(ring1)

    logger.info("Promotion report: starting Ring 2 (paper matrix SLOs)")
    ring2 = _run_paper_matrix()
    report.rings.append(ring2)

    logger.info(f"Promotion report: starting Ring 3 (agent gauntlet, {gauntlet_cycles} cycles)")
    ring3, agent_promotions = _run_agent_gauntlet(cycles=gauntlet_cycles)
    report.rings.append(ring3)
    report.agents = agent_promotions

    # Assess domain eligibility
    report.domains = _assess_domains(report.all_rings_pass)

    # Overall verdict
    report.overall_eligible = (
        report.all_rings_pass
        and len(report.eligible_domains) > 0
        and len(report.promoted_agents) > 0
    )

    report.elapsed_s = time.time() - t0

    logger.info(
        f"Promotion report complete: "
        f"rings={'ALL PASS' if report.all_rings_pass else 'FAIL'}, "
        f"domains={len(report.eligible_domains)}/{len(report.domains)} eligible, "
        f"agents={len(report.promoted_agents)}/{len(report.agents)} promoted, "
        f"{report.elapsed_s:.1f}s"
    )

    return report


# ── Lightweight version for API polling ──────────────────────────────

_cached_report: Optional[PromotionReport] = None
_cached_at: float = 0.0
_CACHE_TTL_S = 60.0  # 1 minute


def get_cached_promotion_report(gauntlet_cycles: int = 5) -> PromotionReport:
    """Return cached report if fresh, otherwise regenerate."""
    global _cached_report, _cached_at
    if _cached_report and (time.time() - _cached_at) < _CACHE_TTL_S:
        return _cached_report
    previous = _cached_report
    _cached_report = generate_promotion_report(gauntlet_cycles=gauntlet_cycles)
    _cached_at = time.time()
    _diff_and_log(previous, _cached_report)
    return _cached_report


def invalidate_cache():
    """Force regeneration on next call."""
    global _cached_report, _cached_at
    _cached_report = None
    _cached_at = 0.0


# ── Promotion Checklist (runbook as data) ────────────────────────────

def promotion_checklist(domain: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return the promotion runbook as a machine-readable checklist.

    Each step has: name, status (pass/fail/unknown), command, detail.
    Optionally filter to a specific domain.
    """
    report = get_cached_promotion_report(gauntlet_cycles=5)
    steps: List[Dict[str, Any]] = []

    # Step 1: Blueprint checks
    ring_bp = next((r for r in report.rings if r.name == "blueprint"), None)
    steps.append({
        "step": 1,
        "name": "Blueprint Checks",
        "command": "make blueprint-check",
        "status": "pass" if (ring_bp and ring_bp.passed) else "fail" if ring_bp else "unknown",
        "detail": f"{ring_bp.checks_passed}/{ring_bp.checks_total} checks passed" if ring_bp else "not run",
        "failures": ring_bp.failures if ring_bp else [],
    })

    # Step 2: Paper matrix SLOs
    ring_pm = next((r for r in report.rings if r.name == "paper_matrix"), None)
    steps.append({
        "step": 2,
        "name": "Paper Trading Matrix",
        "command": "make paper-matrix-test",
        "status": "pass" if (ring_pm and ring_pm.passed) else "fail" if ring_pm else "unknown",
        "detail": f"{ring_pm.checks_passed}/{ring_pm.checks_total} tests passed" if ring_pm else "not run",
        "failures": ring_pm.failures if ring_pm else [],
    })

    # Step 3: Agent gauntlet
    ring_g = next((r for r in report.rings if r.name == "gauntlet"), None)
    steps.append({
        "step": 3,
        "name": "Agent Gauntlet",
        "command": "make gauntlet",
        "status": "pass" if (ring_g and ring_g.passed) else "fail" if ring_g else "unknown",
        "detail": f"{ring_g.checks_passed}/{ring_g.checks_total} agents passed" if ring_g else "not run",
        "failures": ring_g.failures if ring_g else [],
    })

    # Step 4: Promotion report verdict
    steps.append({
        "step": 4,
        "name": "Promotion Report",
        "command": "make promotion-report",
        "status": "pass" if report.all_rings_pass else "fail",
        "detail": f"{'ALL PASS' if report.all_rings_pass else 'FAIL'} — "
                  f"{len(report.eligible_domains)}/{len(report.domains)} domains, "
                  f"{len(report.promoted_agents)}/{len(report.agents)} agents",
        "failures": [],
    })

    # Step 5: Domain eligibility (filtered if domain specified)
    target_domains = report.domains
    if domain:
        target_domains = [d for d in report.domains if d.domain == domain]

    for de in target_domains:
        steps.append({
            "step": 5,
            "name": f"Domain Eligible: {de.domain}",
            "command": f"make promotion-report  # check {de.domain} row",
            "status": "pass" if de.eligible else "fail",
            "detail": f"{de.instruments} instruments, mode={de.mode}, "
                      f"recon={de.reconciliation_venue or 'none'}",
            "failures": de.blockers,
        })

    # Step 6: Guard sync
    guard_synced = False
    try:
        from merid.execution_guard import get_execution_guard
        guard = get_execution_guard()
        guard_synced = guard._promotion_report_ts > 0
        eligible_in_guard = sorted(guard._promotion_eligible_domains) if guard._promotion_eligible_domains else []
    except Exception:
        eligible_in_guard = []

    steps.append({
        "step": 6,
        "name": "Guard Synced",
        "command": "curl -X POST .../api/operator/promotion-report/refresh",
        "status": "pass" if guard_synced else "unknown",
        "detail": f"eligible in guard: {eligible_in_guard}" if guard_synced else "guard not synced yet",
        "failures": [],
    })

    return steps


# ── CLI ──────────────────────────────────────────────────────────────

if __name__ == "__main__":

    json_mode = "--json" in sys.argv
    fast = "--fast" in sys.argv
    cycles = 5 if fast else 10

    report = generate_promotion_report(gauntlet_cycles=cycles)

    if json_mode:
        logger.info(json.dumps(report.to_dict(), indent=2))
    else:
        d = report.to_dict()
        logger.info(f"\n{'=' * 70}")
        logger.info(f"MERID Promotion Report")
        logger.info(f"{'=' * 70}")
        # Rings
        logger.info(f"\n  Validation Rings:")
        for r in report.rings:
            icon = "PASS" if r.passed else "FAIL"
            print(f"    [{icon}] {r.name:20s}  "
                  f"{r.checks_passed}/{r.checks_total} checks  "
                  f"({r.elapsed_s:.1f}s)")
            for f in r.failures:
                logger.error(f"           -> FAIL: {f}")
            for w in r.warnings:
                logger.warning(f"           -> WARN: {w}")
        # Domains
        logger.info(f"\n  Domain Eligibility:")
        for de in report.domains:
            icon = "ELIGIBLE" if de.eligible else "BLOCKED "
            print(f"    [{icon}] {de.domain:15s}  "
                  f"{de.instruments} instruments  "
                  f"mode={de.mode}  "
                  f"recon={de.reconciliation_venue or 'none'}")
            for b in de.blockers:
                logger.info(f"               -> {b}")
        # Agents
        logger.info(f"\n  Agent Promotion:")
        for ap in report.agents:
            icon = "PROMOTED" if ap.promoted else "BLOCKED "
            print(f"    [{icon}] {ap.agent_id:35s}  "
                  f"({ap.category})  "
                  f"SLO {ap.slo_pass_rate:.0%}")
            for s in ap.failed_slos:
                logger.error(f"               -> failed: {s}")
        # Summary
        logger.info(f"\n{'=' * 70}")
        overall = "ELIGIBLE FOR LIVE" if report.overall_eligible else "NOT ELIGIBLE"
        logger.info(f"  Overall: {overall}")
        logger.info(f"  Domains: {len(report.eligible_domains)}/{len(report.domains)} eligible")
        logger.info(f"  Agents:  {len(report.promoted_agents)}/{len(report.agents)} promoted")
        logger.info(f"  Time:    {report.elapsed_s:.1f}s")
        logger.info(f"{'=' * 70}")
    sys.exit(0 if report.all_rings_pass else 1)
