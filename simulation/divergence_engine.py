"""
Advanced Divergence Detection Engine for Shadow MERID

Multi-metric divergence calculation with:
- Consensus probability delta
- Agent score variance
- Reality gap drift
- Token balance mismatch
- Weighted scoring with PSO-tunable parameters

Thresholds:
- Alert at 3%
- Pause at 5%
- Lockdown at 10%
"""

from __future__ import annotations

import threading
import asyncio
import time
import statistics
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple
import math

from utils.logger import get_logger

logger = get_logger("simulation.divergence")


class DivergenceLevel(Enum):
    """Divergence severity levels."""
    NOMINAL = "nominal"
    ALERT = "alert"
    PAUSE = "pause"
    LOCKDOWN = "lockdown"


class DivergenceMetric(Enum):
    """Types of divergence metrics."""
    CONSENSUS_DELTA = "consensus_delta"
    AGENT_SCORE_VARIANCE = "agent_score_variance"
    REALITY_GAP_DRIFT = "reality_gap_drift"
    BALANCE_MISMATCH = "balance_mismatch"
    POSITION_DIVERGENCE = "position_divergence"
    PNL_DIVERGENCE = "pnl_divergence"


@dataclass
class DivergenceWeights:
    """Weights for multi-metric divergence calculation (PSO-tunable)."""
    consensus_weight: float = 0.25
    agent_variance_weight: float = 0.20
    reality_gap_weight: float = 0.20
    balance_weight: float = 0.15
    position_weight: float = 0.10
    pnl_weight: float = 0.10
    
    def normalize(self) -> None:
        """Normalize weights to sum to 1.0."""
        total = (
            self.consensus_weight + self.agent_variance_weight +
            self.reality_gap_weight + self.balance_weight +
            self.position_weight + self.pnl_weight
        )
        if total > 0:
            self.consensus_weight /= total
            self.agent_variance_weight /= total
            self.reality_gap_weight /= total
            self.balance_weight /= total
            self.position_weight /= total
            self.pnl_weight /= total


@dataclass
class DivergenceThresholds:
    """Thresholds for divergence actions."""
    alert_threshold: float = 0.03
    pause_threshold: float = 0.05
    lockdown_threshold: float = 0.10


@dataclass
class LiveState:
    """Snapshot of live MERID state."""
    timestamp: float = field(default_factory=time.time)
    consensus_probability: float = 0.0
    agent_scores: Dict[str, float] = field(default_factory=dict)
    reality_gap: float = 0.0
    balance: float = 0.0
    equity: float = 0.0
    positions: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    total_pnl: float = 0.0
    block_number: int = 0


@dataclass
class ShadowState:
    """Snapshot of shadow MERID state."""
    timestamp: float = field(default_factory=time.time)
    consensus_probability: float = 0.0
    agent_scores: Dict[str, float] = field(default_factory=dict)
    reality_gap: float = 0.0
    balance: float = 0.0
    equity: float = 0.0
    positions: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    total_pnl: float = 0.0
    block_number: int = 0


@dataclass
class DivergenceResult:
    """Result of divergence calculation."""
    timestamp: float = field(default_factory=time.time)
    total_score: float = 0.0
    level: DivergenceLevel = DivergenceLevel.NOMINAL
    
    metric_scores: Dict[DivergenceMetric, float] = field(default_factory=dict)
    metric_details: Dict[DivergenceMetric, str] = field(default_factory=dict)
    
    live_state: Optional[LiveState] = None
    shadow_state: Optional[ShadowState] = None
    
    action_required: str = "none"
    recommendations: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp,
            "total_score": self.total_score,
            "total_score_pct": f"{self.total_score * 100:.2f}%",
            "level": self.level.value,
            "metric_scores": {k.value: v for k, v in self.metric_scores.items()},
            "metric_details": {k.value: v for k, v in self.metric_details.items()},
            "action_required": self.action_required,
            "recommendations": self.recommendations,
        }


@dataclass
class DivergenceEvent:
    """Event emitted when divergence exceeds threshold."""
    event_id: str
    timestamp: float
    level: DivergenceLevel
    score: float
    block_number: int
    details: str
    auto_action_taken: str


class DivergenceEngine:
    """
    Advanced multi-metric divergence detection engine.
    
    Calculates weighted divergence score across multiple metrics:
    - Consensus probability delta
    - Agent score variance
    - Reality gap drift
    - Balance mismatch
    - Position divergence
    - PnL divergence
    """
    
    def __init__(
        self,
        weights: Optional[DivergenceWeights] = None,
        thresholds: Optional[DivergenceThresholds] = None,
    ) -> None:
        self.weights = weights or DivergenceWeights()
        self.weights.normalize()
        self.thresholds = thresholds or DivergenceThresholds()
        
        self._history: List[DivergenceResult] = []
        self._max_history = 1000
        
        self._events: List[DivergenceEvent] = []
        self._max_events = 500
        
        self._callbacks: Dict[DivergenceLevel, List[Callable[[DivergenceResult], None]]] = {
            DivergenceLevel.ALERT: [],
            DivergenceLevel.PAUSE: [],
            DivergenceLevel.LOCKDOWN: [],
        }
        
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None
        
        self._live_state: Optional[LiveState] = None
        self._shadow_state: Optional[ShadowState] = None
        
        logger.info(
            "DivergenceEngine initialized: alert=%.1f%%, pause=%.1f%%, lockdown=%.1f%%",
            self.thresholds.alert_threshold * 100,
            self.thresholds.pause_threshold * 100,
            self.thresholds.lockdown_threshold * 100,
        )
    
    def update_live_state(self, state: LiveState) -> None:
        """Update live MERID state snapshot."""
        self._live_state = state
    
    def update_shadow_state(self, state: ShadowState) -> None:
        """Update shadow MERID state snapshot."""
        self._shadow_state = state
    
    def calculate_divergence(
        self,
        live: Optional[LiveState] = None,
        shadow: Optional[ShadowState] = None,
    ) -> DivergenceResult:
        """
        Calculate multi-metric divergence score.
        
        Formula:
        Divergence = w1 * |live_consensus - shadow_consensus|
                   + w2 * std_dev(agent_scores_live vs shadow)
                   + w3 * |gap_live - gap_shadow|
                   + w4 * |balance_live - balance_shadow| / max(balance)
                   + w5 * position_divergence
                   + w6 * |pnl_live - pnl_shadow| / max(|pnl|)
        """
        live = live or self._live_state
        shadow = shadow or self._shadow_state
        
        result = DivergenceResult(
            live_state=live,
            shadow_state=shadow,
        )
        
        if not live or not shadow:
            return result
        
        consensus_div = self._calc_consensus_divergence(live, shadow)
        result.metric_scores[DivergenceMetric.CONSENSUS_DELTA] = consensus_div
        result.metric_details[DivergenceMetric.CONSENSUS_DELTA] = (
            f"Live: {live.consensus_probability:.3f}, Shadow: {shadow.consensus_probability:.3f}"
        )
        
        agent_var = self._calc_agent_variance(live, shadow)
        result.metric_scores[DivergenceMetric.AGENT_SCORE_VARIANCE] = agent_var
        result.metric_details[DivergenceMetric.AGENT_SCORE_VARIANCE] = (
            f"Score variance across {len(live.agent_scores)} agents"
        )
        
        gap_div = self._calc_reality_gap_drift(live, shadow)
        result.metric_scores[DivergenceMetric.REALITY_GAP_DRIFT] = gap_div
        result.metric_details[DivergenceMetric.REALITY_GAP_DRIFT] = (
            f"Live gap: {live.reality_gap:.4f}, Shadow gap: {shadow.reality_gap:.4f}"
        )
        
        balance_div = self._calc_balance_mismatch(live, shadow)
        result.metric_scores[DivergenceMetric.BALANCE_MISMATCH] = balance_div
        result.metric_details[DivergenceMetric.BALANCE_MISMATCH] = (
            f"Live: ${live.balance:,.2f}, Shadow: ${shadow.balance:,.2f}"
        )
        
        position_div = self._calc_position_divergence(live, shadow)
        result.metric_scores[DivergenceMetric.POSITION_DIVERGENCE] = position_div
        result.metric_details[DivergenceMetric.POSITION_DIVERGENCE] = (
            f"Live positions: {len(live.positions)}, Shadow: {len(shadow.positions)}"
        )
        
        pnl_div = self._calc_pnl_divergence(live, shadow)
        result.metric_scores[DivergenceMetric.PNL_DIVERGENCE] = pnl_div
        result.metric_details[DivergenceMetric.PNL_DIVERGENCE] = (
            f"Live PnL: ${live.total_pnl:,.2f}, Shadow: ${shadow.total_pnl:,.2f}"
        )
        
        result.total_score = (
            self.weights.consensus_weight * consensus_div +
            self.weights.agent_variance_weight * agent_var +
            self.weights.reality_gap_weight * gap_div +
            self.weights.balance_weight * balance_div +
            self.weights.position_weight * position_div +
            self.weights.pnl_weight * pnl_div
        )
        
        result.level = self._determine_level(result.total_score)
        result.action_required = self._determine_action(result.level)
        result.recommendations = self._generate_recommendations(result)
        
        self._history.append(result)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
        
        if result.level != DivergenceLevel.NOMINAL:
            self._emit_event(result, live.block_number if live else 0)
            self._trigger_callbacks(result)
        
        return result
    
    def _calc_consensus_divergence(self, live: LiveState, shadow: ShadowState) -> float:
        """Calculate consensus probability divergence."""
        return abs(live.consensus_probability - shadow.consensus_probability)
    
    def _calc_agent_variance(self, live: LiveState, shadow: ShadowState) -> float:
        """Calculate agent score variance between live and shadow."""
        if not live.agent_scores or not shadow.agent_scores:
            return 0.0
        
        common_agents = set(live.agent_scores.keys()) & set(shadow.agent_scores.keys())
        if not common_agents:
            return 0.0
        
        diffs = [
            abs(live.agent_scores[a] - shadow.agent_scores.get(a, 0))
            for a in common_agents
        ]
        
        if len(diffs) < 2:
            return sum(diffs) / len(diffs) if diffs else 0.0
        
        return statistics.stdev(diffs)
    
    def _calc_reality_gap_drift(self, live: LiveState, shadow: ShadowState) -> float:
        """Calculate reality gap drift."""
        return abs(live.reality_gap - shadow.reality_gap)
    
    def _calc_balance_mismatch(self, live: LiveState, shadow: ShadowState) -> float:
        """Calculate balance mismatch as percentage."""
        max_balance = max(abs(live.balance), abs(shadow.balance), 1.0)
        return abs(live.balance - shadow.balance) / max_balance
    
    def _calc_position_divergence(self, live: LiveState, shadow: ShadowState) -> float:
        """Calculate position divergence."""
        live_symbols = set(live.positions.keys())
        shadow_symbols = set(shadow.positions.keys())
        
        all_symbols = live_symbols | shadow_symbols
        if not all_symbols:
            return 0.0
        
        matching = live_symbols & shadow_symbols
        missing_in_live = shadow_symbols - live_symbols
        missing_in_shadow = live_symbols - shadow_symbols
        
        base_divergence = (len(missing_in_live) + len(missing_in_shadow)) / len(all_symbols)
        
        quantity_divergence = 0.0
        for symbol in matching:
            live_qty = live.positions[symbol].get("quantity", 0)
            shadow_qty = shadow.positions[symbol].get("quantity", 0)
            max_qty = max(abs(live_qty), abs(shadow_qty), 1.0)
            quantity_divergence += abs(live_qty - shadow_qty) / max_qty
        
        if matching:
            quantity_divergence /= len(matching)
        
        return (base_divergence + quantity_divergence) / 2
    
    def _calc_pnl_divergence(self, live: LiveState, shadow: ShadowState) -> float:
        """Calculate PnL divergence as percentage."""
        max_pnl = max(abs(live.total_pnl), abs(shadow.total_pnl), 1.0)
        return abs(live.total_pnl - shadow.total_pnl) / max_pnl
    
    def _determine_level(self, score: float) -> DivergenceLevel:
        """Determine divergence level from score."""
        if score >= self.thresholds.lockdown_threshold:
            return DivergenceLevel.LOCKDOWN
        elif score >= self.thresholds.pause_threshold:
            return DivergenceLevel.PAUSE
        elif score >= self.thresholds.alert_threshold:
            return DivergenceLevel.ALERT
        return DivergenceLevel.NOMINAL
    
    def _determine_action(self, level: DivergenceLevel) -> str:
        """Determine required action for level."""
        actions = {
            DivergenceLevel.NOMINAL: "none",
            DivergenceLevel.ALERT: "investigate",
            DivergenceLevel.PAUSE: "pause_trading",
            DivergenceLevel.LOCKDOWN: "full_lockdown",
        }
        return actions.get(level, "none")
    
    def _generate_recommendations(self, result: DivergenceResult) -> List[str]:
        """Generate recommendations based on divergence."""
        recommendations = []
        
        if result.metric_scores.get(DivergenceMetric.CONSENSUS_DELTA, 0) > 0.1:
            recommendations.append("Review consensus algorithm - significant probability drift")
        
        if result.metric_scores.get(DivergenceMetric.AGENT_SCORE_VARIANCE, 0) > 0.1:
            recommendations.append("Check agent scoring consistency - high variance detected")
        
        if result.metric_scores.get(DivergenceMetric.BALANCE_MISMATCH, 0) > 0.05:
            recommendations.append("Audit balance tracking - mismatch between live and shadow")
        
        if result.metric_scores.get(DivergenceMetric.POSITION_DIVERGENCE, 0) > 0.1:
            recommendations.append("Verify position sync - positions diverging between instances")
        
        if result.level == DivergenceLevel.LOCKDOWN:
            recommendations.insert(0, "CRITICAL: Initiate full system lockdown immediately")
        elif result.level == DivergenceLevel.PAUSE:
            recommendations.insert(0, "WARNING: Pause all trading operations")
        
        return recommendations
    
    def _emit_event(self, result: DivergenceResult, block_number: int) -> None:
        """Emit divergence event."""
        event = DivergenceEvent(
            event_id=f"div_{int(time.time() * 1000)}",
            timestamp=time.time(),
            level=result.level,
            score=result.total_score,
            block_number=block_number,
            details=f"Divergence {result.total_score:.2%} - {result.action_required}",
            auto_action_taken=result.action_required,
        )
        
        self._events.append(event)
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events:]
        
        logger.warning(
            "Divergence event: level=%s, score=%.2f%%, block=%d",
            result.level.value, result.total_score * 100, block_number
        )
    
    def _trigger_callbacks(self, result: DivergenceResult) -> None:
        """Trigger registered callbacks for divergence level."""
        callbacks = self._callbacks.get(result.level, [])
        for callback in callbacks:
            try:
                callback(result)
            except Exception as e:
                logger.error("Divergence callback error: %s", e)
    
    def register_callback(
        self,
        level: DivergenceLevel,
        callback: Callable[[DivergenceResult], None],
    ) -> None:
        """Register callback for divergence level."""
        if level in self._callbacks:
            self._callbacks[level].append(callback)
    
    def get_history(self, limit: int = 100) -> List[DivergenceResult]:
        """Get divergence history."""
        return self._history[-limit:]
    
    def get_events(self, limit: int = 50) -> List[DivergenceEvent]:
        """Get divergence events."""
        return self._events[-limit:]
    
    def get_current_score(self) -> float:
        """Get most recent divergence score."""
        if self._history:
            return self._history[-1].total_score
        return 0.0
    
    def get_status(self) -> Dict[str, Any]:
        """Get engine status."""
        current = self._history[-1] if self._history else None
        
        return {
            "running": self._running,
            "current_score": current.total_score if current else 0.0,
            "current_level": current.level.value if current else "nominal",
            "total_checks": len(self._history),
            "total_events": len(self._events),
            "thresholds": {
                "alert": self.thresholds.alert_threshold,
                "pause": self.thresholds.pause_threshold,
                "lockdown": self.thresholds.lockdown_threshold,
            },
            "weights": {
                "consensus": self.weights.consensus_weight,
                "agent_variance": self.weights.agent_variance_weight,
                "reality_gap": self.weights.reality_gap_weight,
                "balance": self.weights.balance_weight,
                "position": self.weights.position_weight,
                "pnl": self.weights.pnl_weight,
            },
        }
    
    async def start_monitoring(self, interval_seconds: float = 1.0) -> None:
        """Start continuous monitoring."""
        if self._running:
            return
        
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop(interval_seconds))
        logger.info("Divergence monitoring started (interval=%.1fs)", interval_seconds)
    
    async def stop_monitoring(self) -> None:
        """Stop monitoring."""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("Divergence monitoring stopped")
    
    async def _monitor_loop(self, interval: float) -> None:
        """Continuous monitoring loop."""
        while self._running:
            try:
                if self._live_state and self._shadow_state:
                    self.calculate_divergence()
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Monitoring loop error: %s", e)
                await asyncio.sleep(interval)


_divergence_engine: Optional[DivergenceEngine] = None
_divergence_engine_lock = threading.Lock()


def get_divergence_engine() -> DivergenceEngine:
    """Get or create global divergence engine."""
    global _divergence_engine
    if _divergence_engine is None:
        with _divergence_engine_lock:
            if _divergence_engine is None:
                _divergence_engine = DivergenceEngine()
    return _divergence_engine
