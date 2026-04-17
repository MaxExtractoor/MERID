"""
Drift-Driven Reward Loop

Connects drift_monitor outputs to learning systems (MARL, regime adapter)
and governor for automatic de-risking with explainability.

Flow:
1. DriftMonitor emits DriftEvent
2. DriftRewardLoop receives event
3. Computes reward penalty based on severity
4. Updates MARL reward signals
5. Triggers regime adapter if drift indicates regime shift
6. Notifies governor for potential governance action
7. Records explanation for audit trail
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from core.drift_monitor import DriftEvent, DriftMonitor, DriftSeverity, get_drift_monitor
from core.explainability import ExplanationContext, ExplanationType, get_explainability_service
from utils.logger import get_logger

logger = get_logger("core.drift_reward_loop")


class DeRiskAction(str, Enum):
    """De-risking actions triggered by drift."""
    NONE = "none"
    REDUCE_POSITION_SIZE = "reduce_position_size"
    INCREASE_STOP_LOSS = "increase_stop_loss"
    PAUSE_STRATEGY = "pause_strategy"
    SWITCH_REGIME = "switch_regime"
    EMERGENCY_EXIT = "emergency_exit"


@dataclass
class DeRiskDecision:
    """Decision to de-risk based on drift."""
    action: DeRiskAction
    severity: DriftSeverity
    target_component: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class RewardAdjustment:
    """Adjustment to learning reward based on drift."""
    component_id: str
    original_reward: float
    adjusted_reward: float
    penalty_factor: float
    drift_event_id: str
    timestamp: float = field(default_factory=time.time)


class DriftRewardLoop:
    """
    Connects drift monitoring to learning systems for automatic de-risking.
    
    Responsibilities:
    - Subscribe to drift events
    - Compute reward penalties based on drift severity
    - Update MARL/bandit reward signals
    - Trigger regime adaptation when drift indicates regime shift
    - Notify governor for governance actions
    - Record explanations for all de-risk decisions
    """
    
    # Penalty factors by severity
    SEVERITY_PENALTIES = {
        DriftSeverity.INFO: 0.0,
        DriftSeverity.WARNING: 0.15,
        DriftSeverity.CRITICAL: 0.40,
    }
    
    # De-risk action thresholds
    ACTION_THRESHOLDS = {
        DeRiskAction.REDUCE_POSITION_SIZE: DriftSeverity.WARNING,
        DeRiskAction.INCREASE_STOP_LOSS: DriftSeverity.WARNING,
        DeRiskAction.PAUSE_STRATEGY: DriftSeverity.CRITICAL,
        DeRiskAction.SWITCH_REGIME: DriftSeverity.WARNING,
        DeRiskAction.EMERGENCY_EXIT: DriftSeverity.CRITICAL,
    }
    
    def __init__(self) -> None:
        self._drift_monitor = get_drift_monitor()
        self._explainability = get_explainability_service()
        
        # Callbacks for integration
        self._marl_reward_callback: Optional[Callable[[str, float], None]] = None
        self._regime_callback: Optional[Callable[[str, float], None]] = None
        self._governor_callback: Optional[Callable[[DeRiskDecision], None]] = None
        
        # State tracking
        self._processed_events: List[str] = []
        self._reward_adjustments: List[RewardAdjustment] = []
        self._derisk_decisions: List[DeRiskDecision] = []
        
        # Component risk multipliers (reduced when drifting)
        self._risk_multipliers: Dict[str, float] = {}
        
        # Drift accumulation per component
        self._drift_accumulation: Dict[str, float] = {}
        self._accumulation_decay = 0.95  # Decay factor per evaluation
        
        logger.info("DriftRewardLoop initialized")
    
    def register_marl_callback(
        self,
        callback: Callable[[str, float], None],
    ) -> None:
        """Register callback to update MARL rewards."""
        self._marl_reward_callback = callback
        logger.info("MARL reward callback registered")
    
    def register_regime_callback(
        self,
        callback: Callable[[str, float], None],
    ) -> None:
        """Register callback for regime adaptation."""
        self._regime_callback = callback
        logger.info("Regime adaptation callback registered")
    
    def register_governor_callback(
        self,
        callback: Callable[[DeRiskDecision], None],
    ) -> None:
        """Register callback for governor notifications."""
        self._governor_callback = callback
        logger.info("Governor callback registered")
    
    def process_drift_event(self, event: DriftEvent) -> Optional[DeRiskDecision]:
        """
        Process a drift event and take appropriate action.
        
        Returns DeRiskDecision if action taken, None otherwise.
        """
        if event.event_id in self._processed_events:
            return None
        
        self._processed_events.append(event.event_id)
        
        # Update drift accumulation
        self._update_drift_accumulation(event)
        
        # Compute reward penalty
        penalty = self._compute_penalty(event)
        
        # Update risk multiplier for component
        self._update_risk_multiplier(event.component, penalty)
        
        # Determine de-risk action
        decision = self._determine_derisk_action(event)
        
        if decision.action != DeRiskAction.NONE:
            self._derisk_decisions.append(decision)
            
            # Notify callbacks
            self._notify_callbacks(event, decision, penalty)
            
            # Record explanation
            self._record_derisk_explanation(event, decision, penalty)
            
            logger.warning(
                "De-risk action: %s for %s (severity=%s, penalty=%.2f)",
                decision.action.value,
                event.component,
                event.severity.value,
                penalty,
            )
        
        return decision if decision.action != DeRiskAction.NONE else None
    
    def _update_drift_accumulation(self, event: DriftEvent) -> None:
        """Update accumulated drift for component."""
        component = event.component
        
        # Decay existing accumulation
        if component in self._drift_accumulation:
            self._drift_accumulation[component] *= self._accumulation_decay
        else:
            self._drift_accumulation[component] = 0.0
        
        # Add new drift signal
        severity_weight = {
            DriftSeverity.INFO: 0.1,
            DriftSeverity.WARNING: 0.3,
            DriftSeverity.CRITICAL: 0.6,
        }
        self._drift_accumulation[component] += severity_weight.get(event.severity, 0.1)
    
    def _compute_penalty(self, event: DriftEvent) -> float:
        """Compute reward penalty based on drift event."""
        base_penalty = self.SEVERITY_PENALTIES.get(event.severity, 0.0)
        
        # Scale by number of signals
        signal_factor = min(len(event.signals) / 3.0, 1.0)
        
        # Scale by accumulated drift
        accumulation = self._drift_accumulation.get(event.component, 0.0)
        accumulation_factor = min(accumulation, 1.0)
        
        # Combined penalty
        penalty = base_penalty * (1 + signal_factor * 0.5 + accumulation_factor * 0.5)
        
        return min(penalty, 0.8)  # Cap at 80% penalty
    
    def _update_risk_multiplier(self, component: str, penalty: float) -> None:
        """Update risk multiplier for component."""
        current = self._risk_multipliers.get(component, 1.0)
        
        # Reduce multiplier based on penalty
        new_multiplier = current * (1 - penalty * 0.5)
        
        # Clamp to reasonable range
        self._risk_multipliers[component] = max(0.1, min(1.0, new_multiplier))
    
    def _determine_derisk_action(self, event: DriftEvent) -> DeRiskDecision:
        """Determine appropriate de-risk action."""
        accumulation = self._drift_accumulation.get(event.component, 0.0)
        
        # Check for emergency conditions
        if event.severity == DriftSeverity.CRITICAL and accumulation > 0.8:
            return DeRiskDecision(
                action=DeRiskAction.EMERGENCY_EXIT,
                severity=event.severity,
                target_component=event.component,
                parameters={"exit_pct": 1.0},
                reason=f"Critical drift with high accumulation ({accumulation:.2f})",
            )
        
        # Check for pause conditions
        if event.severity == DriftSeverity.CRITICAL:
            return DeRiskDecision(
                action=DeRiskAction.PAUSE_STRATEGY,
                severity=event.severity,
                target_component=event.component,
                parameters={"pause_duration_seconds": 3600},
                reason=f"Critical drift detected: {event.message}",
            )
        
        # Check for regime shift indicators
        if self._indicates_regime_shift(event):
            return DeRiskDecision(
                action=DeRiskAction.SWITCH_REGIME,
                severity=event.severity,
                target_component=event.component,
                parameters={"trigger_adaptation": True},
                reason="Drift signals indicate potential regime shift",
            )
        
        # Warning level actions
        if event.severity == DriftSeverity.WARNING:
            # Reduce position size
            risk_mult = self._risk_multipliers.get(event.component, 1.0)
            return DeRiskDecision(
                action=DeRiskAction.REDUCE_POSITION_SIZE,
                severity=event.severity,
                target_component=event.component,
                parameters={"new_risk_multiplier": risk_mult},
                reason=f"Warning drift: reducing risk to {risk_mult:.2f}x",
            )
        
        return DeRiskDecision(
            action=DeRiskAction.NONE,
            severity=event.severity,
            target_component=event.component,
        )
    
    def _indicates_regime_shift(self, event: DriftEvent) -> bool:
        """Check if drift signals indicate a regime shift."""
        regime_indicators = {"sharpe_ratio", "volatility", "correlation", "trend_strength"}
        
        for signal in event.signals:
            if signal.metric_name in regime_indicators:
                # Large deviation suggests regime change
                deviation_ratio = abs(signal.value - signal.reference) / (signal.threshold + 1e-6)
                if deviation_ratio > 2.0:
                    return True
        
        return False
    
    def _notify_callbacks(
        self,
        event: DriftEvent,
        decision: DeRiskDecision,
        penalty: float,
    ) -> None:
        """Notify registered callbacks."""
        # MARL reward adjustment
        if self._marl_reward_callback:
            try:
                self._marl_reward_callback(event.component, -penalty)
            except Exception as e:
                logger.error("MARL callback failed: %s", e)
        
        # Regime adaptation
        if self._regime_callback and decision.action == DeRiskAction.SWITCH_REGIME:
            try:
                self._regime_callback(event.component, penalty)
            except Exception as e:
                logger.error("Regime callback failed: %s", e)
        
        # Governor notification
        if self._governor_callback and decision.action in {
            DeRiskAction.PAUSE_STRATEGY,
            DeRiskAction.EMERGENCY_EXIT,
        }:
            try:
                self._governor_callback(decision)
            except Exception as e:
                logger.error("Governor callback failed: %s", e)
    
    def _record_derisk_explanation(
        self,
        event: DriftEvent,
        decision: DeRiskDecision,
        penalty: float,
    ) -> None:
        """Record explanation for de-risk decision."""
        context = ExplanationContext(
            inputs={
                "drift_event_id": event.event_id,
                "severity": event.severity.value,
                "signals": [
                    {
                        "metric": s.metric_name,
                        "value": s.value,
                        "reference": s.reference,
                        "threshold": s.threshold,
                    }
                    for s in event.signals
                ],
            },
            agent_id=event.component,
            strategy=None,
            constraints={
                "penalty_factor": penalty,
                "risk_multiplier": self._risk_multipliers.get(event.component, 1.0),
                "drift_accumulation": self._drift_accumulation.get(event.component, 0.0),
            },
            expected_effect={
                "action": decision.action.value,
                "parameters": decision.parameters,
            },
            environment_flags={},
        )
        
        self._explainability.record_explanation(
            explanation_type=ExplanationType.RISK_ADJUSTMENT,
            summary=f"De-risk: {decision.action.value} for {event.component}",
            context=context,
            expert_notes=decision.reason,
        )
    
    def adjust_reward(
        self,
        component_id: str,
        original_reward: float,
    ) -> float:
        """
        Adjust reward based on current drift state.
        
        Called by MARL/bandit systems to get drift-adjusted rewards.
        """
        risk_mult = self._risk_multipliers.get(component_id, 1.0)
        accumulation = self._drift_accumulation.get(component_id, 0.0)
        
        # Penalty based on accumulated drift
        penalty_factor = 1.0 - (accumulation * 0.3)
        penalty_factor = max(0.2, penalty_factor)
        
        adjusted_reward = original_reward * risk_mult * penalty_factor
        
        # Record adjustment
        adjustment = RewardAdjustment(
            component_id=component_id,
            original_reward=original_reward,
            adjusted_reward=adjusted_reward,
            penalty_factor=penalty_factor,
            drift_event_id=f"accumulated_{component_id}",
        )
        self._reward_adjustments.append(adjustment)
        
        return adjusted_reward
    
    def poll_and_process(self) -> List[DeRiskDecision]:
        """
        Poll drift monitor for new events and process them.
        
        Returns list of de-risk decisions made.
        """
        events = self._drift_monitor.get_events(limit=100)
        decisions = []
        
        for event in events:
            decision = self.process_drift_event(event)
            if decision:
                decisions.append(decision)
        
        return decisions
    
    def get_risk_multiplier(self, component_id: str) -> float:
        """Get current risk multiplier for component."""
        return self._risk_multipliers.get(component_id, 1.0)
    
    def get_drift_accumulation(self, component_id: str) -> float:
        """Get accumulated drift for component."""
        return self._drift_accumulation.get(component_id, 0.0)
    
    def reset_component(self, component_id: str) -> None:
        """Reset drift state for a component."""
        self._risk_multipliers.pop(component_id, None)
        self._drift_accumulation.pop(component_id, None)
        logger.info("Reset drift state for %s", component_id)
    
    def get_status(self) -> Dict[str, Any]:
        """Get loop status."""
        return {
            "processed_events": len(self._processed_events),
            "reward_adjustments": len(self._reward_adjustments),
            "derisk_decisions": len(self._derisk_decisions),
            "components_tracked": len(self._risk_multipliers),
            "risk_multipliers": {k: round(v, 4) for k, v in self._risk_multipliers.items()},
            "drift_accumulation": {k: round(v, 4) for k, v in self._drift_accumulation.items()},
        }
    
    def get_recent_decisions(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent de-risk decisions."""
        return [
            {
                "action": d.action.value,
                "severity": d.severity.value,
                "target": d.target_component,
                "parameters": d.parameters,
                "reason": d.reason,
                "timestamp": d.timestamp,
            }
            for d in self._derisk_decisions[-limit:]
        ]


# Singleton instance
_drift_reward_loop: Optional[DriftRewardLoop] = None
_drift_reward_loop_lock = threading.Lock()


def get_drift_reward_loop() -> DriftRewardLoop:
    """Get the singleton drift reward loop."""
    global _drift_reward_loop
    if _drift_reward_loop is None:
        with _drift_reward_loop_lock:
            if _drift_reward_loop is None:
                _drift_reward_loop = DriftRewardLoop()
    return _drift_reward_loop
