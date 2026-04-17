"""
MERID Reality Auditor - Enforcement Engine

This sits between engines and UI to enforce truth discipline.

RESPONSIBILITIES:
1. Validate assertions
2. Enforce decay
3. Detect conflicts
4. Control UI visibility
5. Block execution if truth is insufficient
"""

from __future__ import annotations
import logging

import threading
import time
from typing import Dict, List, Optional, Tuple, Protocol
from dataclasses import dataclass

from core.reality_registry import (
    RealityRegistry,
    get_reality_registry,
    AssertionDomain,
    AssertionStatus,
    UIVisibility,
    RealityAssertion,
    AssertionAlgebra,
    BlindnessContext,
    AuditorMode,
    BlindnessSeverity,
    AssertionPipelineHealth,
)
from utils.logger import get_logger
from core.mode_transition_auditor import log_mode_transition, log_transition_denied, log_rollback
from core.domain_priority_manager import get_domain_priority_manager

logger = get_logger("core.reality_auditor")


@dataclass
class AuditResult:
    """Result of reality audit."""
    passed: bool
    reason: str
    blocking_assertions: List[str]
    warnings: List[str]
    blindness_context: Optional[BlindnessContext] = None
    auditor_mode: AuditorMode = AuditorMode.NORMAL


class RealityAuditorProtocol(Protocol):
    """Protocol exposed for dependency injection and testing."""

    def update_regime_entropy(self, entropy: float) -> None:
        ...

    def audit_ui_component(
        self,
        component_id: str,
        required_assertions: List[str],
        allow_conflict: bool = False,
        allow_expired: bool = False,
        min_confidence: float = 0.5,
    ) -> "AuditResult":
        ...

    def audit_execution_intent(
        self,
        intent_id: str,
        required_assertions: List[str],
        symbol: str,
        amount_usd: float,
    ) -> "AuditResult":
        ...

    def get_system_state(self) -> Dict:
        ...

    def detect_self_deception(self) -> Dict:
        ...


class RealityAuditor:
    """
    The enforcement engine that prevents UI from lying.
    
    This is the missing piece that fixes the representation failure.
    Enhanced with robust blindness detection and structured logging.
    """
    
    def __init__(self, registry: Optional[RealityRegistry] = None, environment: str = "unknown"):
        self.registry = registry or get_reality_registry()
        self.regime_entropy = 0.0  # Updated by regime classifier
        self.last_audit = time.time()
        self.environment = environment  # sim/paper/live
        self.current_mode = AuditorMode.NORMAL
        self.last_blindness_context: Optional[BlindnessContext] = None
        self.last_audit_result = None
        
        logger.info(f"RealityAuditor initialized - truth enforcement active in {environment}")
    
    def update_regime_entropy(self, entropy: float):
        """Update current regime entropy (0-1)."""
        self.regime_entropy = max(0.0, min(1.0, entropy))
        logger.info(f"Regime entropy updated: {self.regime_entropy:.3f}")
    
    def audit_loop(self):
        """
        Main audit loop - runs continuously.
        
        Updates all assertion statuses based on decay and expiration.
        Enhanced with structured blindness detection and logging.
        Returns structured result for API consumption.
        """
        current_time = time.time()
        
        # Update all assertion statuses
        self.registry.update_assertion_status(current_time, self.regime_entropy)
        
        # Enhanced blindness detection with full context
        blindness_context = self.registry.check_blindness_context(
            current_time, 
            self.regime_entropy,
            environment=self.environment,
            pipeline_id="audit_loop"
        )
        
        # Update auditor mode
        self.current_mode = blindness_context.mode
        self.last_blindness_context = blindness_context
        
        # Structured logging based on severity
        if blindness_context.mode != AuditorMode.NORMAL:
            self._log_blindness_incident(blindness_context)
        
        self.last_audit = current_time
        
        # Return structured result for API consumption
        return (blindness_context.mode.value, blindness_context.primary_reason)
    
    def _log_blindness_incident(self, context: BlindnessContext):
        """Log blindness incident with appropriate level and structured data."""
        log_data = context.to_dict()
        
        if context.severity == BlindnessSeverity.CRITICAL:
            logger.error(f"CRITICAL BLINDNESS INCIDENT", extra=log_data)
        elif context.severity == BlindnessSeverity.HIGH:
            logger.warning(f"BLINDNESS INCIDENT", extra=log_data)
        else:
            logger.info(f"Blindness mode active", extra=log_data)
        
        # Additional human-readable summary
        logger.info(
            f"Blindness: {context.mode.value} | "
            f"Severity: {context.severity.value} | "
            f"Reason: {context.primary_reason} | "
            f"Duration: {context.blind_duration:.1f}h | "
            f"Impact: {', '.join(context.impacted_subsystems)}"
        )
    
    def audit_ui_component(
        self,
        component_id: str,
        required_assertions: List[str],
        allow_conflict: bool = False,
        allow_expired: bool = False,
        min_confidence: float = 0.5,
    ) -> AuditResult:
        """
        Audit whether a UI component is allowed to render.
        
        CONSTITUTIONAL: This is the gate that prevents fake UI.
        """
        current_time = time.time()
        warnings = []
        blocking = []
        
        # Check if all required assertions exist
        assertions = []
        for assertion_id in required_assertions:
            assertion = self.registry.get_assertion(assertion_id)
            if assertion is None:
                blocking.append(assertion_id)
                return AuditResult(
                    passed=False,
                    reason=f"Missing required assertion: {assertion_id}",
                    blocking_assertions=blocking,
                    warnings=warnings,
                )
            assertions.append(assertion)
        
        # Check each assertion
        for assertion in assertions:
            # Check expiration
            if assertion.status == AssertionStatus.EXPIRED and not allow_expired:
                blocking.append(assertion.assertion_id)
                return AuditResult(
                    passed=False,
                    reason=f"Assertion expired: {assertion.assertion_id}",
                    blocking_assertions=blocking,
                    warnings=warnings,
                )
            
            # Check conflict
            if assertion.status == AssertionStatus.CONFLICTED and not allow_conflict:
                blocking.append(assertion.assertion_id)
                return AuditResult(
                    passed=False,
                    reason=f"Assertion conflicted: {assertion.assertion_id}",
                    blocking_assertions=blocking,
                    warnings=warnings,
                )
            
            # Check effective confidence
            effective = assertion.effective_confidence(current_time, self.regime_entropy)
            if effective < min_confidence:
                blocking.append(assertion.assertion_id)
                return AuditResult(
                    passed=False,
                    reason=f"Assertion confidence too low: {effective:.3f} < {min_confidence}",
                    blocking_assertions=blocking,
                    warnings=warnings,
                )
            
            # Warnings for degraded state
            if assertion.status == AssertionStatus.DEGRADED:
                warnings.append(f"Assertion degraded: {assertion.assertion_id}")
            
            if effective < 0.7:
                warnings.append(f"Low confidence: {assertion.assertion_id} ({effective:.3f})")
        
        return AuditResult(
            passed=True,
            reason="All assertions valid",
            blocking_assertions=[],
            warnings=warnings,
            blindness_context=self.last_blindness_context,
            auditor_mode=self.current_mode,
        )
    
    def audit_execution_intent(
        self,
        intent_id: str,
        required_assertions: List[str],
        symbol: str,
        amount_usd: float,
    ) -> AuditResult:
        """
        Audit whether execution is allowed.
        
        STRICTER than UI audit - no exceptions.
        """
        current_time = time.time()
        warnings = []
        blocking = []
        
        # Check blindness mode first with enhanced context
        blindness_context = self.registry.check_blindness_context(
            current_time, 
            self.regime_entropy,
            environment=self.environment,
            pipeline_id=f"execution_{intent_id}"
        )
        
        if blindness_context.mode != AuditorMode.NORMAL:
            return AuditResult(
                passed=False,
                reason=f"BLINDNESS MODE: {blindness_context.primary_reason}",
                blocking_assertions=[],
                warnings=[],
                blindness_context=blindness_context,
                auditor_mode=blindness_context.mode,
            )
        
        # Get assertions
        assertions = []
        for assertion_id in required_assertions:
            assertion = self.registry.get_assertion(assertion_id)
            if assertion is None:
                return AuditResult(
                    passed=False,
                    reason=f"Missing required assertion: {assertion_id}",
                    blocking_assertions=[assertion_id],
                    warnings=[],
                )
            assertions.append(assertion)
        
        # Check execution eligibility using assertion algebra
        can_execute, reason = AssertionAlgebra.check_execution_eligibility(
            assertions,
            current_time,
            self.regime_entropy,
            threshold=0.6,  # Higher threshold for execution
        )
        
        if not can_execute:
            return AuditResult(
                passed=False,
                reason=reason,
                blocking_assertions=[a.assertion_id for a in assertions if not a.is_usable(current_time, self.regime_entropy, 0.6)],
                warnings=[],
            )
        
        return AuditResult(
            passed=True,
            reason="Execution allowed",
            blocking_assertions=[],
            warnings=warnings,
        )
    
    def get_system_state(self) -> Dict:
        """
        Get current system state for monitoring.
        
        This is what operators see.
        """
        current_time = time.time()
        
        # Get registry status
        registry_status = self.registry.get_registry_status(current_time, self.regime_entropy)
        
        # Check blindness
        is_blind, blind_reason = self.registry.check_blindness_condition(current_time, self.regime_entropy)
        
        # Determine system mode
        if is_blind:
            # Check if we have core domains sighted for SIGHTED_DEGRADED
            core_domains = ["market", "onchain", "simulation", "agent"]
            core_domains_sighted = all(domain not in registry_status["blind_spots"] for domain in core_domains)
            
            if core_domains_sighted:
                # Run comprehensive safety checks before allowing SIGHTED_DEGRADED
                safety_check_result = self._run_sighted_degraded_safety_checks(registry_status, current_time)
                
                if safety_check_result["passed"]:
                    new_mode = "SIGHTED_DEGRADED"
                    blind_reason = f"SIGHTED_DEGRADED: {safety_check_result['reason']}"
                else:
                    new_mode = "BLIND"
                    blind_reason = f"SAFETY_CHECK_FAILED: {safety_check_result['reason']}"
                    # Log denied transition
                    log_transition_denied(
                        old_mode=self.current_mode,
                        reason_code="SAFETY_CHECK_FAILED",
                        reason_detail=safety_check_result["reason"],
                        system_state={
                            "mode": new_mode,
                            "registry_status": registry_status,
                            "execution_allowed": False,
                            "regime_entropy": self.regime_entropy
                        },
                        safety_check_results=safety_check_result
                    )
            else:
                new_mode = "BLIND"
                blind_reason = f"CORE_DOMAINS_MISSING: Missing {[d for d in core_domains if d in registry_status['blind_spots']]}"
        else:
            new_mode = "BLIND"  # Default fallback
            blind_reason = "SYSTEM_NOT_BLIND"
        
        # Check for mode changes and log them
        old_mode = getattr(self, 'current_system_mode', 'BLIND')
        if new_mode != old_mode:
            # Activate/deactivate domain priority manager based on mode
            domain_priority_manager = get_domain_priority_manager()
            
            if new_mode == "SIGHTED_DEGRADED":
                domain_priority_manager.set_mode("SIGHTED_DEGRADED")
                logger.info("Domain priority manager activated for SIGHTED_DEGRADED mode")
            elif old_mode == "SIGHTED_DEGRADED":
                domain_priority_manager.set_mode("BLIND")
                logger.info("Domain priority manager deactivated - reverting to BLIND mode")
            
            # Log successful mode transition
            log_mode_transition(
                old_mode=old_mode,
                new_mode=new_mode,
                reason_code="CORE_DOMAINS_SIGHTED" if new_mode == "SIGHTED_DEGRADED" else "MODE_CHANGE",
                reason_detail=blind_reason,
                system_state={
                    "mode": new_mode,
                    "registry_status": registry_status,
                    "execution_allowed": not is_blind and self.regime_entropy < 0.7,
                    "regime_entropy": self.regime_entropy
                },
                triggering_actor="autonomous_scheduler"
            )
            self.current_system_mode = new_mode
        
        return {
            "mode": new_mode,
            "regime_entropy": self.regime_entropy,
            "is_blind": is_blind,
            "blind_reason": blind_reason if is_blind else None,
            "registry_status": registry_status,
            "last_audit": self.last_audit,
            "execution_allowed": not is_blind and self.regime_entropy < 0.7,
        }
    
    def _run_sighted_degraded_safety_checks(self, registry_status: Dict, current_time: float) -> Dict:
        """
        Comprehensive safety checks before allowing SIGHTED_DEGRADED transition.
        
        Returns dict with 'passed' boolean and 'reason' string.
        """
        try:
            # 1. Assertion coverage checks
            core_domains = ["market", "onchain", "simulation", "agent"]
            min_assertions_per_domain = 5  # Production threshold
            
            for domain in core_domains:
                domain_assertions = self.registry.get_assertions_by_domain(domain)
                valid_assertions = sum(1 for a in domain_assertions if a.status == AssertionStatus.VALID)
                
                if valid_assertions < min_assertions_per_domain:
                    return {
                        "passed": False,
                        "reason": f"INSUFFICIENT_ASSERTIONS: {domain} has {valid_assertions} valid assertions (min {min_assertions_per_domain})"
                    }
                
                # Check for critical failing assertions
                critical_failures = [
                    a for a in domain_assertions 
                    if a.status == AssertionStatus.INVALID and "critical" in a.description.lower()
                ]
                if critical_failures:
                    return {
                        "passed": False,
                        "reason": f"CRITICAL_ASSERTIONS_FAILED: {domain} has {len(critical_failures)} critical failures"
                    }
            
            # 2. Feed and clock sanity checks
            current_time = time.time()
            for domain in core_domains:
                domain_assertions = self.registry.get_assertions_by_domain(domain)
                
                # Check for recent updates (liveness)
                recent_assertions = [
                    a for a in domain_assertions 
                    if current_time - a.created_at < 300  # 5 minutes
                ]
                
                if len(recent_assertions) == 0:
                    return {
                        "passed": False,
                        "reason": f"STALE_DATA: {domain} has no recent assertions (last 5 minutes)"
                    }
                
                # Check for time-traveling data (basic sanity)
                for assertion in domain_assertions:
                    if assertion.created_at > current_time + 60:  # 1 minute future tolerance
                        return {
                            "passed": False,
                            "reason": f"TIME_TRAVEL_DATA: {domain} has future timestamp"
                        }
            
            # 3. Risk/governance invariants
            # Verify execution guard is active
            execution_guard_active = not registry_status.get("execution_allowed", True)
            if not execution_guard_active:
                return {
                    "passed": False,
                    "reason": "EXECUTION_GUARD_INACTIVE: Execution permissions not properly blocked"
                }
            
            # Verify venue state is not tradable
            # (This would typically check local venue state)
            # For now, ensure we're still in some form of degraded state
            if registry_status.get("valid_pct", 0) > 90:
                return {
                    "passed": False,
                    "reason": "SYSTEM_TOO_HEALTHY: System appears too healthy for SIGHTED_DEGRADED"
                }
            
            # 4. Simulation integrity check
            simulation_assertions = self.registry.get_assertions_by_domain("simulation")
            
            # Check for basic simulation health
            valid_sim_assertions = sum(1 for a in simulation_assertions if a.status == AssertionStatus.VALID)
            if valid_sim_assertions < min_assertions_per_domain:
                return {
                    "passed": False,
                    "reason": f"SIMULATION_INTEGRITY_FAILED: Only {valid_sim_assertions} valid simulation assertions"
                }
            
            # Check for simulation errors (NaNs, explosions would be in assertion descriptions)
            error_sim_assertions = [
                a for a in simulation_assertions 
                if a.status == AssertionStatus.INVALID and any(err in a.description.lower() for err in ["nan", "explode", "error", "crash"])
            ]
            if error_sim_assertions:
                return {
                    "passed": False,
                    "reason": f"SIMULATION_ERRORS: {len(error_sim_assertions)} simulation assertions have critical errors"
                }
            
            # All checks passed
            return {
                "passed": True,
                "reason": f"SAFETY_CHECKS_PASSED: All {len(core_domains)} core domains healthy, execution guarded, simulation ready"
            }
            
        except Exception as e:
            logger.error(f"Error in SIGHTED_DEGRADED safety checks: {e}")
            return {
                "passed": False,
                "reason": f"SAFETY_CHECK_ERROR: {str(e)}"
            }
    
    def detect_self_deception(self) -> Dict:
        """
        Anti-self-deception metrics.
        
        Detects when MERID (or operators) are lying to themselves.
        """
        current_time = time.time()
        
        assertions = list(self.registry._assertions.values())
        if not assertions:
            return {
                "confidence_inflation": 0.0,
                "agreement_bias": 0.0,
                "narrative_comfort": 0.0,
            }
        
        # Confidence Inflation Index
        # (We'd need historical accuracy data for this - placeholder for now)
        claimed_confidence = sum(a.confidence_score for a in assertions) / len(assertions)
        confidence_inflation = claimed_confidence - 0.5  # Baseline assumption
        
        # Agreement Bias Detector
        # Check if assertions agree too easily (low conflict rate might be suspicious)
        conflicted = sum(1 for a in assertions if a.status == AssertionStatus.CONFLICTED)
        agreement_rate = 1.0 - (conflicted / len(assertions))
        agreement_bias = max(0.0, agreement_rate - 0.7)  # Suspiciously high agreement
        
        # Narrative Comfort Index
        # Check if system avoids uncertainty language
        degraded = sum(1 for a in assertions if a.status == AssertionStatus.DEGRADED)
        expired = sum(1 for a in assertions if a.status == AssertionStatus.EXPIRED)
        uncomfortable = (degraded + expired) / len(assertions)
        narrative_comfort = 1.0 - uncomfortable  # High = too comfortable
        
        return {
            "confidence_inflation": confidence_inflation,
            "agreement_bias": agreement_bias,
            "narrative_comfort": narrative_comfort,
            "warning": confidence_inflation > 0.3 or agreement_bias > 0.2 or narrative_comfort > 0.8,
        }
    
    def get_auditor_status(self) -> Dict:
        """Get comprehensive auditor status for operator tools."""
        current_time = time.time()
        
        # Get current blindness context
        blindness_context = self.registry.check_blindness_context(
            current_time,
            self.regime_entropy,
            environment=self.environment,
            pipeline_id="status_check"
        )
        
        # Get pipeline health
        pipeline_health = self.registry.get_assertion_pipeline_health(current_time)
        
        # Get registry status
        registry_status = self.registry.get_registry_status(current_time, self.regime_entropy)
        
        return {
            "auditor_mode": self.current_mode.value,
            "environment": self.environment,
            "regime_entropy": self.regime_entropy,
            "last_audit": self.last_audit,
            "blindness_context": blindness_context.to_dict(),
            "pipeline_health": {
                "assertions_per_hour": pipeline_health.assertions_per_hour,
                "last_assertion_ts": pipeline_health.last_assertion_ts,
                "last_resolution_ts": pipeline_health.last_resolution_ts,
                "pending_assertions": pipeline_health.pending_assertions,
                "resolved_assertions": pipeline_health.resolved_assertions,
                "is_stale": pipeline_health.is_stale,
                "stale_threshold_hours": pipeline_health.stale_threshold_hours,
            },
            "registry_status": registry_status,
        }
    
    def get_recent_assertions(self, since_hours: float = 24.0, limit: int = 100) -> List[Dict]:
        """Get recent assertions for debugging."""
        current_time = time.time()
        since_ts = current_time - (since_hours * 3600.0)
        
        recent_assertions = []
        for assertion in self.registry._assertions.values():
            if assertion.created_at >= since_ts:
                recent_assertions.append({
                    "assertion_id": assertion.assertion_id,
                    "domain": assertion.domain.value,
                    "status": assertion.status.value,
                    "created_at": assertion.created_at,
                    "confidence": assertion.confidence,
                    "effective_confidence": assertion.effective_confidence(current_time, self.regime_entropy),
                })
        
        # Sort by creation time (newest first) and limit
        recent_assertions.sort(key=lambda x: x["created_at"], reverse=True)
        return recent_assertions[:limit]
    
    def reload_from_persistent_store(self) -> bool:
        """Reload live config assertions from active subsystems.

        Re-registers fresh RealityAssertions from KalshiRisk, settings,
        and the execution guard so that operator config changes (risk limits,
        kill-switch state, domain modes) propagate without a server restart.

        Returns True if at least one assertion was refreshed successfully.
        """
        from core.reality_registry import (
            AssertionDomain, AssertionProvenance, AssertionStatus, UIVisibility,
        )

        refreshed = 0
        now = time.time()

        # ── 1. KalshiRisk limits ──────────────────────────────────────
        try:
            from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
            risk = get_kalshi_risk()
            cfg = risk.config
            state = risk.state

            provenance = AssertionProvenance(
                source_id="kalshi_risk",
                module_id="merid.event_venues.kalshi.kalshi_risk",
                evidence_hash=str(hash((cfg.max_daily_loss_usd, cfg.max_orders_per_hour))),
                weight=0.95,
                timestamp=now,
            )
            aid = self.registry.register_assertion(
                domain=AssertionDomain.EXECUTION,
                description=(
                    f"KalshiRisk: daily_loss_limit=${cfg.max_daily_loss_usd:.0f} "
                    f"orders_per_hour={cfg.max_orders_per_hour} "
                    f"kill_switch={'ON' if state.kill_switch_active else 'OFF'}"
                ),
                confidence=1.0,
                provenance_score=0.95,
                regime_compatibility=1.0,
                decay_rate=0.001,
                validity_window=300.0,  # 5 minutes
                sources=[provenance],
            )
            logger.info("reload: KalshiRisk assertion registered (%s)", aid)
            refreshed += 1
        except Exception as exc:
            logger.debug("reload: KalshiRisk assertion skipped: %s", exc)

        # ── 2. Execution guard state ──────────────────────────────────
        try:
            from merid.execution_guard import get_execution_guard
            guard = get_execution_guard()
            kill_active = getattr(guard, 'kill_switch_active', False)
            provenance = AssertionProvenance(
                source_id="execution_guard",
                module_id="merid.execution_guard",
                evidence_hash=str(hash(kill_active)),
                weight=1.0,
                timestamp=now,
            )
            aid = self.registry.register_assertion(
                domain=AssertionDomain.EXECUTION,
                description=f"ExecutionGuard: kill_switch={'ACTIVE' if kill_active else 'CLEAR'}",
                confidence=1.0,
                provenance_score=1.0,
                regime_compatibility=1.0,
                decay_rate=0.0005,
                validity_window=60.0,  # 1 minute — guard state changes fast
                sources=[provenance],
            )
            logger.info("reload: ExecutionGuard assertion registered (%s)", aid)
            refreshed += 1
        except Exception as exc:
            logger.debug("reload: ExecutionGuard assertion skipped: %s", exc)

        # ── 3. Domain mode config from paper_config ───────────────────
        try:
            from merid.paper_config import get_paper_config
            pc = get_paper_config()
            active_domains = [d for d in pc.domains if pc.domains[d].enabled]
            provenance = AssertionProvenance(
                source_id="paper_config",
                module_id="merid.paper_config",
                evidence_hash=str(hash(tuple(sorted(active_domains)))),
                weight=0.9,
                timestamp=now,
            )
            aid = self.registry.register_assertion(
                domain=AssertionDomain.SYSTEM,
                description=f"PaperConfig: active_domains={active_domains}",
                confidence=1.0,
                provenance_score=0.9,
                regime_compatibility=1.0,
                decay_rate=0.0002,
                validity_window=600.0,  # 10 minutes
                sources=[provenance],
            )
            logger.info("reload: PaperConfig assertion registered (%s)", aid)
            refreshed += 1
        except Exception as exc:
            logger.debug("reload: PaperConfig assertion skipped: %s", exc)

        # ── 4. Agent grid health ──────────────────────────────────────
        try:
            from merid.prediction.agent_grid import get_agent_grid
            grid = get_agent_grid()
            running = sum(1 for a in grid.agents if a.state.running)
            provenance = AssertionProvenance(
                source_id="agent_grid",
                module_id="merid.prediction.agent_grid",
                evidence_hash=str(hash((len(grid.agents), running))),
                weight=0.85,
                timestamp=now,
            )
            aid = self.registry.register_assertion(
                domain=AssertionDomain.AGENT,
                description=f"AgentGrid: total={len(grid.agents)} running={running}",
                confidence=min(1.0, running / max(1, len(grid.agents))),
                provenance_score=0.85,
                regime_compatibility=1.0,
                decay_rate=0.002,
                validity_window=120.0,  # 2 minutes
                sources=[provenance],
            )
            logger.info("reload: AgentGrid assertion registered (%s)", aid)
            refreshed += 1
        except Exception as exc:
            logger.debug("reload: AgentGrid assertion skipped: %s", exc)

        logger.info(
            "reload_from_persistent_store: %d assertions refreshed", refreshed
        )
        return refreshed > 0


# Singleton instance
_auditor: Optional[RealityAuditor] = None
_auditor_lock = threading.Lock()


def get_reality_auditor() -> RealityAuditor:
    """Get the global reality auditor."""
    global _auditor
    if _auditor is None:
        with _auditor_lock:
            if _auditor is None:
                _auditor = RealityAuditor()
    return _auditor
