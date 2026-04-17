"""
Debugging infrastructure with deterministic replay, debug views, and guardrail debugging.

Provides tools for debugging agent decisions, replaying scenarios, and analyzing
guardrail violations with full context.
"""

from utils.logger import get_logger
import threading
import json
import pickle
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import hashlib

logger = get_logger(__name__)


@dataclass
class DecisionSnapshot:
    """Snapshot of agent decision with full context."""
    timestamp: datetime
    agent_id: str
    strategy_id: str
    correlation_id: str
    trace_id: str
    inputs: Dict[str, Any]
    market_state: Dict[str, Any]
    agent_state: Dict[str, Any]
    decision: Dict[str, Any]
    alternatives: List[Dict[str, Any]]
    scores: Dict[str, float]
    entropy: float
    regime: str
    guardrails_checked: List[str]
    guardrails_passed: List[str]
    guardrails_failed: List[str]
    execution_result: Optional[Dict[str, Any]] = None


@dataclass
class ReplaySession:
    """Replay session for debugging."""
    session_id: str
    original_correlation_id: str
    snapshots: List[DecisionSnapshot]
    modifications: Dict[str, Any]
    replay_results: List[Dict[str, Any]]
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class GuardrailViolation:
    """Guardrail violation with context."""
    timestamp: datetime
    agent_id: str
    guardrail_name: str
    violation_type: str
    severity: str
    inputs: Dict[str, Any]
    expected: Any
    actual: Any
    context: Dict[str, Any]
    stack_trace: Optional[str] = None


@dataclass
class DebugView:
    """Debug view for specific component."""
    component_id: str
    view_type: str
    data: Dict[str, Any]
    filters: Dict[str, Any]
    created_at: datetime = field(default_factory=datetime.utcnow)


class DebugInfrastructure:
    """
    Debugging infrastructure for MERID trading swarm.
    
    Capabilities:
    - Deterministic replay of decision flows
    - Debug views for agents, strategies, guardrails
    - Guardrail violation analysis
    - Layered debugging (agent -> strategy -> model -> data)
    - Snapshot and restore for debugging
    """
    
    def __init__(self, snapshot_dir: str = "debug_snapshots"):
        self.snapshot_dir = Path(snapshot_dir)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        
        self._snapshots: Dict[str, DecisionSnapshot] = {}
        self._replay_sessions: Dict[str, ReplaySession] = {}
        self._guardrail_violations: List[GuardrailViolation] = []
        self._debug_views: Dict[str, DebugView] = {}
        
        self._replay_mode = False
        self._replay_overrides: Dict[str, Any] = {}
    
    def capture_decision_snapshot(
        self,
        agent_id: str,
        strategy_id: str,
        correlation_id: str,
        trace_id: str,
        inputs: Dict[str, Any],
        market_state: Dict[str, Any],
        agent_state: Dict[str, Any],
        decision: Dict[str, Any],
        alternatives: List[Dict[str, Any]],
        scores: Dict[str, float],
        entropy: float,
        regime: str,
        guardrails_checked: List[str],
        guardrails_passed: List[str],
        guardrails_failed: List[str],
    ) -> DecisionSnapshot:
        """Capture a complete decision snapshot for replay."""
        snapshot = DecisionSnapshot(
            timestamp=datetime.utcnow(),
            agent_id=agent_id,
            strategy_id=strategy_id,
            correlation_id=correlation_id,
            trace_id=trace_id,
            inputs=self._sanitize_for_storage(inputs),
            market_state=self._sanitize_for_storage(market_state),
            agent_state=self._sanitize_for_storage(agent_state),
            decision=self._sanitize_for_storage(decision),
            alternatives=alternatives,
            scores=scores,
            entropy=entropy,
            regime=regime,
            guardrails_checked=guardrails_checked,
            guardrails_passed=guardrails_passed,
            guardrails_failed=guardrails_failed,
        )
        
        self._snapshots[correlation_id] = snapshot
        
        self._save_snapshot_to_disk(snapshot)
        
        logger.debug(f"Captured decision snapshot: {correlation_id}")
        
        return snapshot
    
    def _sanitize_for_storage(self, data: Any) -> Any:
        """Remove non-serializable data."""
        if isinstance(data, dict):
            return {k: self._sanitize_for_storage(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._sanitize_for_storage(v) for v in data]
        elif isinstance(data, (str, int, float, bool, type(None))):
            return data
        else:
            return str(data)
    
    def _save_snapshot_to_disk(self, snapshot: DecisionSnapshot) -> None:
        """Save snapshot to disk for persistence."""
        filename = f"{snapshot.correlation_id}_{snapshot.timestamp.strftime('%Y%m%d_%H%M%S')}.json"
        filepath = self.snapshot_dir / filename
        
        try:
            with open(filepath, 'w') as f:
                json.dump({
                    "timestamp": snapshot.timestamp.isoformat(),
                    "agent_id": snapshot.agent_id,
                    "strategy_id": snapshot.strategy_id,
                    "correlation_id": snapshot.correlation_id,
                    "trace_id": snapshot.trace_id,
                    "inputs": snapshot.inputs,
                    "market_state": snapshot.market_state,
                    "agent_state": snapshot.agent_state,
                    "decision": snapshot.decision,
                    "alternatives": snapshot.alternatives,
                    "scores": snapshot.scores,
                    "entropy": snapshot.entropy,
                    "regime": snapshot.regime,
                    "guardrails_checked": snapshot.guardrails_checked,
                    "guardrails_passed": snapshot.guardrails_passed,
                    "guardrails_failed": snapshot.guardrails_failed,
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save snapshot to disk: {e}")
    
    def load_snapshot(self, correlation_id: str) -> Optional[DecisionSnapshot]:
        """Load snapshot from memory or disk."""
        if correlation_id in self._snapshots:
            return self._snapshots[correlation_id]
        
        for filepath in self.snapshot_dir.glob(f"{correlation_id}_*.json"):
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)
                
                snapshot = DecisionSnapshot(
                    timestamp=datetime.fromisoformat(data["timestamp"]),
                    agent_id=data["agent_id"],
                    strategy_id=data["strategy_id"],
                    correlation_id=data["correlation_id"],
                    trace_id=data["trace_id"],
                    inputs=data["inputs"],
                    market_state=data["market_state"],
                    agent_state=data["agent_state"],
                    decision=data["decision"],
                    alternatives=data["alternatives"],
                    scores=data["scores"],
                    entropy=data["entropy"],
                    regime=data["regime"],
                    guardrails_checked=data["guardrails_checked"],
                    guardrails_passed=data["guardrails_passed"],
                    guardrails_failed=data["guardrails_failed"],
                )
                
                self._snapshots[correlation_id] = snapshot
                return snapshot
            except Exception as e:
                logger.error(f"Failed to load snapshot from {filepath}: {e}")
        
        return None
    
    def start_replay_session(
        self,
        correlation_id: str,
        modifications: Optional[Dict[str, Any]] = None,
    ) -> ReplaySession:
        """Start a replay session for debugging."""
        snapshot = self.load_snapshot(correlation_id)
        if not snapshot:
            raise ValueError(f"Snapshot not found: {correlation_id}")
        
        session_id = hashlib.md5(
            f"{correlation_id}_{datetime.utcnow().isoformat()}".encode()
        ).hexdigest()[:16]
        
        session = ReplaySession(
            session_id=session_id,
            original_correlation_id=correlation_id,
            snapshots=[snapshot],
            modifications=modifications or {},
            replay_results=[],
        )
        
        self._replay_sessions[session_id] = session
        
        logger.info(f"Started replay session: {session_id} for {correlation_id}")
        
        return session
    
    def replay_decision(
        self,
        session_id: str,
        replay_function: Callable,
    ) -> Dict[str, Any]:
        """
        Replay a decision with modifications.
        
        Args:
            session_id: Replay session ID
            replay_function: Function to execute replay (receives snapshot and modifications)
            
        Returns:
            Replay result
        """
        session = self._replay_sessions.get(session_id)
        if not session:
            raise ValueError(f"Replay session not found: {session_id}")
        
        snapshot = session.snapshots[0]
        
        self._replay_mode = True
        self._replay_overrides = session.modifications
        
        try:
            result = replay_function(snapshot, session.modifications)
            
            session.replay_results.append({
                "timestamp": datetime.utcnow().isoformat(),
                "result": result,
                "modifications": session.modifications,
            })
            
            logger.info(f"Replay completed for session: {session_id}")
            
            return result
        finally:
            self._replay_mode = False
            self._replay_overrides = {}
    
    def record_guardrail_violation(
        self,
        agent_id: str,
        guardrail_name: str,
        violation_type: str,
        severity: str,
        inputs: Dict[str, Any],
        expected: Any,
        actual: Any,
        context: Dict[str, Any],
        stack_trace: Optional[str] = None,
    ) -> GuardrailViolation:
        """Record a guardrail violation for analysis."""
        violation = GuardrailViolation(
            timestamp=datetime.utcnow(),
            agent_id=agent_id,
            guardrail_name=guardrail_name,
            violation_type=violation_type,
            severity=severity,
            inputs=self._sanitize_for_storage(inputs),
            expected=expected,
            actual=actual,
            context=self._sanitize_for_storage(context),
            stack_trace=stack_trace,
        )
        
        self._guardrail_violations.append(violation)
        
        logger.warning(
            f"Guardrail violation: {guardrail_name} for {agent_id} "
            f"(severity={severity}, type={violation_type})"
        )
        
        return violation
    
    def get_guardrail_violations(
        self,
        agent_id: Optional[str] = None,
        guardrail_name: Optional[str] = None,
        severity: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[GuardrailViolation]:
        """Query guardrail violations."""
        violations = self._guardrail_violations
        
        if agent_id:
            violations = [v for v in violations if v.agent_id == agent_id]
        
        if guardrail_name:
            violations = [v for v in violations if v.guardrail_name == guardrail_name]
        
        if severity:
            violations = [v for v in violations if v.severity == severity]
        
        if since:
            violations = [v for v in violations if v.timestamp >= since]
        
        return violations[-limit:]
    
    def create_debug_view(
        self,
        component_id: str,
        view_type: str,
        data: Dict[str, Any],
        filters: Optional[Dict[str, Any]] = None,
    ) -> DebugView:
        """Create a debug view for a component."""
        view = DebugView(
            component_id=component_id,
            view_type=view_type,
            data=data,
            filters=filters or {},
        )
        
        view_id = f"{component_id}_{view_type}"
        self._debug_views[view_id] = view
        
        logger.debug(f"Created debug view: {view_id}")
        
        return view
    
    def get_debug_view(
        self,
        component_id: str,
        view_type: str,
    ) -> Optional[DebugView]:
        """Get debug view."""
        view_id = f"{component_id}_{view_type}"
        return self._debug_views.get(view_id)
    
    def analyze_decision_flow(
        self,
        correlation_id: str,
    ) -> Dict[str, Any]:
        """
        Analyze a complete decision flow with layered debugging.
        
        Layers:
        1. Agent layer: decision logic, alternatives
        2. Strategy layer: parameters, regime
        3. Model layer: scores, entropy
        4. Data layer: inputs, market state
        5. Guardrail layer: checks, violations
        """
        snapshot = self.load_snapshot(correlation_id)
        if not snapshot:
            return {"error": "Snapshot not found"}
        
        analysis = {
            "correlation_id": correlation_id,
            "timestamp": snapshot.timestamp.isoformat(),
            "layers": {
                "agent": {
                    "agent_id": snapshot.agent_id,
                    "decision": snapshot.decision,
                    "alternatives": snapshot.alternatives,
                    "state": snapshot.agent_state,
                },
                "strategy": {
                    "strategy_id": snapshot.strategy_id,
                    "regime": snapshot.regime,
                },
                "model": {
                    "scores": snapshot.scores,
                    "entropy": snapshot.entropy,
                },
                "data": {
                    "inputs": snapshot.inputs,
                    "market_state": snapshot.market_state,
                },
                "guardrails": {
                    "checked": snapshot.guardrails_checked,
                    "passed": snapshot.guardrails_passed,
                    "failed": snapshot.guardrails_failed,
                },
            },
        }
        
        violations = self.get_guardrail_violations(
            agent_id=snapshot.agent_id,
            since=snapshot.timestamp,
            limit=10,
        )
        
        if violations:
            analysis["layers"]["guardrails"]["recent_violations"] = [
                {
                    "guardrail": v.guardrail_name,
                    "type": v.violation_type,
                    "severity": v.severity,
                    "timestamp": v.timestamp.isoformat(),
                }
                for v in violations
            ]
        
        return analysis
    
    def get_debug_summary(self) -> Dict[str, Any]:
        """Get debugging infrastructure summary."""
        return {
            "total_snapshots": len(self._snapshots),
            "total_replay_sessions": len(self._replay_sessions),
            "total_violations": len(self._guardrail_violations),
            "total_debug_views": len(self._debug_views),
            "snapshot_dir": str(self.snapshot_dir),
            "replay_mode": self._replay_mode,
            "recent_violations": [
                {
                    "agent_id": v.agent_id,
                    "guardrail": v.guardrail_name,
                    "severity": v.severity,
                    "timestamp": v.timestamp.isoformat(),
                }
                for v in self._guardrail_violations[-10:]
            ],
        }


_debug_infrastructure: Optional[DebugInfrastructure] = None
_debug_infrastructure_lock = threading.Lock()


def get_debug_infrastructure() -> DebugInfrastructure:
    """Get global DebugInfrastructure instance."""
    global _debug_infrastructure
    if _debug_infrastructure is None:
        with _debug_infrastructure_lock:
            if _debug_infrastructure is None:
                _debug_infrastructure = DebugInfrastructure()
    return _debug_infrastructure
