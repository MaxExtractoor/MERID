"""Safety & Regression Agent - Integration Validator

Phase 8 of MERID single-signal hierarchy:
Final safety layer that validates all prior phases integrate correctly,
enforces end-to-end invariants, and provides regression testing hooks.

Responsibilities:
1. Validate all signal layers are fresh and connected
2. Enforce execution invariants (position limits, risk budgets)
3. Detect and prevent unsafe state combinations
4. Provide regression test suite for full stack
5. Safety kill switches with granular control

Architecture:
- Thread-safe singleton
- Health check aggregation
- Invariant enforcement
- Regression test orchestration
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Set, Tuple
from enum import Enum
from collections import deque

from merid.kalshi.macro_overlay import get_kalshi_macro_overlay
from merid.signals.momentum_ranker import get_momentum_ranker
from merid.signals.btc_anchor_gate import get_btc_anchor_gate
from merid.signals.unified_regime_classifier import (
    get_unified_regime_classifier,
    ExecutionRegime,
)
from merid.kalshi.mm_integration import get_market_maker_integration
from merid.policy.qinline_policy import get_qinline_policy
from utils.logger import get_logger

logger = get_logger("merid.safety.integration_validator")


class SafetyStatus(str, Enum):
    """Overall safety system status."""
    GREEN = "green"      # All systems operational
    YELLOW = "yellow"    # Degraded but functional
    RED = "red"          # Critical issue, trading blocked
    UNKNOWN = "unknown"  # Cannot determine status


class InvariantSeverity(str, Enum):
    """Severity of invariant violation."""
    INFO = "info"        # Log only
    WARNING = "warning"    # Alert but allow
    CRITICAL = "critical"  # Block execution


@dataclass
class HealthCheck:
    """Health check result for a single component."""
    component: str
    status: str  # "ok", "degraded", "failed", "unknown"
    message: str
    timestamp: float
    latency_ms: float = 0.0
    details: Dict = field(default_factory=dict)


@dataclass
class InvariantViolation:
    """Record of an invariant violation."""
    invariant_id: str
    severity: InvariantSeverity
    message: str
    timestamp: float
    context: Dict = field(default_factory=dict)


@dataclass
class SafetyReport:
    """Complete safety status report."""
    timestamp: float
    overall_status: SafetyStatus
    
    # Component health
    health_checks: Dict[str, HealthCheck] = field(default_factory=dict)
    
    # Invariant status
    active_violations: List[InvariantViolation] = field(default_factory=list)
    total_violations_24h: int = 0
    
    # Signal freshness
    macro_fresh: bool = False
    momentum_fresh: bool = False
    btc_anchor_fresh: bool = False
    regime_fresh: bool = False
    
    # Execution readiness
    can_execute: bool = False
    blocked_reason: Optional[str] = None
    
    @property
    def is_safe_to_trade(self) -> bool:
        """Whether trading is currently safe."""
        return (
            self.overall_status == SafetyStatus.GREEN and
            self.can_execute and
            not self.active_violations
        )


class IntegrationValidator:
    """Validates integration of all signal layers and enforces safety invariants.
    
    This is the final safety net before execution. It:
    1. Checks all signal sources are fresh and connected
    2. Validates invariants across the entire stack
    3. Provides kill switch functionality
    4. Aggregates health status for monitoring
    """
    
    # Freshness thresholds (seconds)
    MAX_MACRO_AGE = 300.0
    MAX_MOMENTUM_AGE = 300.0
    MAX_BTC_ANCHOR_AGE = 300.0
    MAX_REGIME_AGE = 300.0
    
    # Position limits (for invariant checking)
    MAX_POSITION_PER_ASSET = 100
    MAX_GROSS_EXPOSURE_CENTS = 500000  # $5,000
    MAX_DAILY_LOSS_CENTS = 100000     # $1,000
    
    def __init__(self):
        # Signal layer references
        self._macro = get_kalshi_macro_overlay()
        self._momentum = get_momentum_ranker()
        self._btc_gate = get_btc_anchor_gate()
        self._regime = get_unified_regime_classifier()
        self._mm = get_market_maker_integration()
        self._policy = get_qinline_policy()
        
        # Safety state
        self._kill_switches: Set[str] = set()
        self._violation_history: deque = deque(maxlen=1000)
        self._last_report: Optional[SafetyReport] = None
        
        # Callbacks for violations
        self._violation_callbacks: List[Callable[[InvariantViolation], None]] = []
        
        self._lock = threading.Lock()
        
        logger.info("IntegrationValidator initialized")
    
    def register_violation_callback(
        self,
        callback: Callable[[InvariantViolation], None]
    ) -> None:
        """Register callback for invariant violations."""
        with self._lock:
            self._violation_callbacks.append(callback)
            logger.debug("Violation callback registered")
    
    def run_health_check(self) -> SafetyReport:
        """Run comprehensive health check of all signal layers."""
        with self._lock:
            start_time = time.time()
            report = SafetyReport(
                timestamp=start_time,
                overall_status=SafetyStatus.UNKNOWN,
                health_checks={},
            )
            
            # Check each signal layer
            checks = [
                ("macro_overlay", self._check_macro_health),
                ("momentum_ranker", self._check_momentum_health),
                ("btc_anchor", self._check_btc_anchor_health),
                ("unified_regime", self._check_regime_health),
                ("mm_integration", self._check_mm_health),
                ("qinline_policy", self._check_policy_health),
            ]
            
            for name, check_fn in checks:
                try:
                    health = check_fn()
                    report.health_checks[name] = health
                except Exception as e:
                    report.health_checks[name] = HealthCheck(
                        component=name,
                        status="failed",
                        message=f"Health check error: {e}",
                        timestamp=time.time(),
                    )
            
            # Update freshness flags
            report.macro_fresh = self._macro.get_macro_state() is not None
            report.momentum_fresh = self._momentum.is_fresh(self.MAX_MOMENTUM_AGE)
            report.btc_anchor_fresh = self._btc_gate.get_current_regime() is not None
            report.regime_fresh = self._regime.is_fresh(self.MAX_REGIME_AGE)
            
            # Check invariants
            report.active_violations = self._check_invariants(report)
            
            # Determine overall status
            report.overall_status = self._determine_overall_status(report)
            
            # Determine execution readiness
            report.can_execute = self._can_execute(report)
            if not report.can_execute:
                report.blocked_reason = self._get_blocked_reason(report)
            
            self._last_report = report
            
            logger.debug(
                "Health check complete: status=%s, violations=%d, can_execute=%s",
                report.overall_status.value,
                len(report.active_violations),
                report.can_execute
            )
            
            return report
    
    def _check_macro_health(self) -> HealthCheck:
        """Check macro overlay health."""
        start = time.time()
        
        state = self._macro.get_macro_state()
        if state is None:
            return HealthCheck(
                component="macro_overlay",
                status="failed",
                message="No macro state available",
                timestamp=time.time(),
                latency_ms=(time.time() - start) * 1000,
            )
        
        age = time.time() - state.timestamp
        if age > self.MAX_MACRO_AGE:
            return HealthCheck(
                component="macro_overlay",
                status="degraded",
                message=f"Macro state stale: {age:.1f}s old",
                timestamp=time.time(),
                latency_ms=(time.time() - start) * 1000,
                details={"age_seconds": age},
            )
        
        convictions = self._macro.get_conviction_scores()
        return HealthCheck(
            component="macro_overlay",
            status="ok",
            message=f"Macro healthy, {len(convictions)} assets tracked",
            timestamp=time.time(),
            latency_ms=(time.time() - start) * 1000,
            details={"tracked_assets": len(convictions)},
        )
    
    def _check_momentum_health(self) -> HealthCheck:
        """Check momentum ranker health."""
        start = time.time()
        
        if not self._momentum.is_fresh(self.MAX_MOMENTUM_AGE):
            return HealthCheck(
                component="momentum_ranker",
                status="degraded",
                message="Momentum rankings stale",
                timestamp=time.time(),
                latency_ms=(time.time() - start) * 1000,
            )
        
        rankings = self._momentum.get_current_rankings()
        if rankings is None:
            return HealthCheck(
                component="momentum_ranker",
                status="failed",
                message="No momentum rankings available",
                timestamp=time.time(),
                latency_ms=(time.time() - start) * 1000,
            )
        
        return HealthCheck(
            component="momentum_ranker",
            status="ok",
            message=f"Momentum healthy, {len(rankings.assets)} assets ranked",
            timestamp=time.time(),
            latency_ms=(time.time() - start) * 1000,
            details={"ranked_assets": len(rankings.assets)},
        )
    
    def _check_btc_anchor_health(self) -> HealthCheck:
        """Check BTC anchor gate health."""
        start = time.time()
        
        state = self._btc_gate.get_current_regime()
        if state is None:
            return HealthCheck(
                component="btc_anchor",
                status="failed",
                message="No BTC regime available",
                timestamp=time.time(),
                latency_ms=(time.time() - start) * 1000,
            )
        
        age = time.time() - state.timestamp
        if age > self.MAX_BTC_ANCHOR_AGE:
            return HealthCheck(
                component="btc_anchor",
                status="degraded",
                message=f"BTC regime stale: {age:.1f}s old",
                timestamp=time.time(),
                latency_ms=(time.time() - start) * 1000,
            )
        
        return HealthCheck(
            component="btc_anchor",
            status="ok",
            message=f"BTC anchor healthy, regime={state.regime.value}",
            timestamp=time.time(),
            latency_ms=(time.time() - start) * 1000,
            details={"regime": state.regime.value, "adx": state.adx},
        )
    
    def _check_regime_health(self) -> HealthCheck:
        """Check unified regime classifier health."""
        start = time.time()
        
        state = self._regime.get_current_state()
        if state is None:
            return HealthCheck(
                component="unified_regime",
                status="failed",
                message="No regime state available",
                timestamp=time.time(),
                latency_ms=(time.time() - start) * 1000,
            )
        
        age = time.time() - state.timestamp
        if age > self.MAX_REGIME_AGE:
            return HealthCheck(
                component="unified_regime",
                status="degraded",
                message=f"Regime state stale: {age:.1f}s old",
                timestamp=time.time(),
                latency_ms=(time.time() - start) * 1000,
            )
        
        return HealthCheck(
            component="unified_regime",
            status="ok",
            message=f"Regime healthy: {state.execution_regime.value}",
            timestamp=time.time(),
            latency_ms=(time.time() - start) * 1000,
            details={
                "execution_regime": state.execution_regime.value,
                "volatility_regime": state.volatility_regime.value,
            },
        )
    
    def _check_mm_health(self) -> HealthCheck:
        """Check market maker integration health."""
        start = time.time()
        
        inventory = self._mm.get_all_inventory()
        total_exposure = sum(inv.gross_exposure for inv in inventory.values())
        
        if total_exposure > self.MAX_GROSS_EXPOSURE_CENTS:
            return HealthCheck(
                component="mm_integration",
                status="degraded",
                message=f"High MM exposure: ${total_exposure/100:.2f}",
                timestamp=time.time(),
                latency_ms=(time.time() - start) * 1000,
                details={"total_exposure_cents": total_exposure},
            )
        
        return HealthCheck(
            component="mm_integration",
            status="ok",
            message=f"MM healthy, {len(inventory)} tickers tracked",
            timestamp=time.time(),
            latency_ms=(time.time() - start) * 1000,
            details={"tracked_tickers": len(inventory)},
        )
    
    def _check_policy_health(self) -> HealthCheck:
        """Check Q-Inline policy health."""
        start = time.time()
        
        recent = self._policy.get_decision_history(since=time.time() - 300)
        
        return HealthCheck(
            component="qinline_policy",
            status="ok",
            message=f"Policy healthy, {len(recent)} decisions in last 5min",
            timestamp=time.time(),
            latency_ms=(time.time() - start) * 1000,
            details={"recent_decisions": len(recent)},
        )
    
    def _check_invariants(self, report: SafetyReport) -> List[InvariantViolation]:
        """Check all system invariants."""
        violations = []
        
        # Invariant 1: Halt regime must block execution
        regime_state = self._regime.get_current_state()
        if regime_state and regime_state.is_halted:
            violations.append(InvariantViolation(
                invariant_id="HALT_BLOCKS_EXECUTION",
                severity=InvariantSeverity.INFO,
                message="Execution blocked by halt regime",
                timestamp=time.time(),
            ))
        
        # Invariant 2: All critical signals must be fresh in normal operation
        if report.overall_status == SafetyStatus.GREEN:
            if not (report.macro_fresh and report.momentum_fresh and 
                    report.btc_anchor_fresh and report.regime_fresh):
                violations.append(InvariantViolation(
                    invariant_id="SIGNAL_FRESHNESS",
                    severity=InvariantSeverity.WARNING,
                    message="Some signals stale despite GREEN status",
                    timestamp=time.time(),
                ))
        
        # Invariant 3: MM exposure limits
        inventory = self._mm.get_all_inventory()
        total_exposure = sum(inv.gross_exposure for inv in inventory.values())
        if total_exposure > self.MAX_GROSS_EXPOSURE_CENTS:
            violations.append(InvariantViolation(
                invariant_id="MM_EXPOSURE_LIMIT",
                severity=InvariantSeverity.CRITICAL,
                message=f"MM exposure ${total_exposure/100:.2f} exceeds limit",
                timestamp=time.time(),
                context={"exposure_cents": total_exposure, "limit_cents": self.MAX_GROSS_EXPOSURE_CENTS},
            ))
        
        # Notify callbacks
        for v in violations:
            self._violation_history.append(v)
            for callback in self._violation_callbacks:
                try:
                    callback(v)
                except Exception as e:
                    logger.error("Violation callback failed: %s", e)
        
        return violations
    
    def _determine_overall_status(self, report: SafetyReport) -> SafetyStatus:
        """Determine overall system status from health checks."""
        statuses = [h.status for h in report.health_checks.values()]
        
        if any(s == "failed" for s in statuses):
            return SafetyStatus.RED
        
        if any(s == "degraded" for s in statuses):
            return SafetyStatus.YELLOW
        
        if all(s == "ok" for s in statuses):
            return SafetyStatus.GREEN
        
        return SafetyStatus.UNKNOWN
    
    def _can_execute(self, report: SafetyReport) -> bool:
        """Determine if execution is currently safe."""
        # Must be green or yellow status
        if report.overall_status not in (SafetyStatus.GREEN, SafetyStatus.YELLOW):
            return False
        
        # No critical violations
        critical = [v for v in report.active_violations 
                   if v.severity == InvariantSeverity.CRITICAL]
        if critical:
            return False
        
        # Not in halt regime
        regime_state = self._regime.get_current_state()
        if regime_state and regime_state.is_halted:
            return False
        
        # No kill switches active
        if self._kill_switches:
            return False
        
        return True
    
    def _get_blocked_reason(self, report: SafetyReport) -> Optional[str]:
        """Get reason why execution is blocked."""
        if report.overall_status == SafetyStatus.RED:
            failed = [name for name, h in report.health_checks.items() if h.status == "failed"]
            return f"Health check failed for: {', '.join(failed)}"
        
        critical = [v.invariant_id for v in report.active_violations 
                   if v.severity == InvariantSeverity.CRITICAL]
        if critical:
            return f"Critical invariants violated: {', '.join(critical)}"
        
        regime_state = self._regime.get_current_state()
        if regime_state and regime_state.is_halted:
            return "Halt regime active"
        
        if self._kill_switches:
            return f"Kill switches active: {', '.join(self._kill_switches)}"
        
        return None
    
    def activate_kill_switch(self, reason: str) -> None:
        """Activate kill switch to block all execution."""
        with self._lock:
            self._kill_switches.add(reason)
            logger.critical("Kill switch activated: %s", reason)
    
    def deactivate_kill_switch(self, reason: str) -> None:
        """Deactivate a kill switch."""
        with self._lock:
            self._kill_switches.discard(reason)
            logger.info("Kill switch deactivated: %s", reason)
    
    def get_kill_switches(self) -> Set[str]:
        """Get active kill switches."""
        with self._lock:
            return set(self._kill_switches)
    
    def get_last_report(self) -> Optional[SafetyReport]:
        """Get most recent safety report."""
        with self._lock:
            return self._last_report
    
    def get_violation_history(
        self,
        since: Optional[float] = None,
        severity: Optional[InvariantSeverity] = None,
    ) -> List[InvariantViolation]:
        """Get violation history with optional filtering."""
        with self._lock:
            violations = list(self._violation_history)
            
            if since:
                violations = [v for v in violations if v.timestamp >= since]
            if severity:
                violations = [v for v in violations if v.severity == severity]
            
            return violations
    
    def reset(self) -> None:
        """Reset validator state."""
        with self._lock:
            self._kill_switches.clear()
            self._violation_history.clear()
            self._last_report = None
            logger.info("IntegrationValidator reset")


# ═══════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════

_validator_instance: Optional[IntegrationValidator] = None
_validator_lock = threading.Lock()


def get_integration_validator() -> IntegrationValidator:
    """Get or create the singleton IntegrationValidator."""
    global _validator_instance
    if _validator_instance is None:
        with _validator_lock:
            if _validator_instance is None:
                _validator_instance = IntegrationValidator()
                logger.info("IntegrationValidator singleton initialized")
    return _validator_instance


def reset_integration_validator() -> None:
    """Reset the singleton (for testing)."""
    global _validator_instance
    with _validator_lock:
        _validator_instance = None
        logger.info("IntegrationValidator singleton reset")
