"""
Multi-agent risk controls beyond per-strategy limits.

Implements aggregate exposure caps, interaction risk limits, global throttles,
and kill switches to prevent multi-agent risk stacking and feedback loops.
"""

from utils.logger import get_logger
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict
from enum import Enum
import threading

from core.info_theory_metrics import get_info_theory_metrics
from core.strategy_versioning import StrategyVersion

logger = get_logger(__name__)


class KillSwitchLevel(Enum):
    """Kill switch activation level."""
    STRATEGY = "strategy"
    AGENT_CLASS = "agent_class"
    VENUE = "venue"
    ASSET = "asset"
    FIRM_WIDE = "firm_wide"


@dataclass
class AggregateExposureCap:
    """Aggregate exposure cap across multiple agents."""
    cap_id: str
    dimension: str
    entity: str
    max_notional: float
    max_leverage: float
    max_concentration_pct: float
    current_notional: float = 0.0
    current_leverage: float = 0.0
    current_concentration_pct: float = 0.0
    breached: bool = False
    breach_timestamp: Optional[datetime] = None


@dataclass
class InteractionRiskLimit:
    """Interaction risk limit to prevent feedback loops."""
    limit_id: str
    agent_group: List[str]
    max_correlated_actions: int
    time_window_seconds: int
    max_correlation_score: float
    current_correlated_actions: int = 0
    breached: bool = False
    breach_timestamp: Optional[datetime] = None


@dataclass
class GlobalThrottle:
    """Global throttle for order/cancel counts and notional turnover."""
    throttle_id: str
    scope: str
    max_orders_per_minute: int
    max_cancels_per_minute: int
    max_notional_turnover_per_hour: float
    current_orders: int = 0
    current_cancels: int = 0
    current_turnover: float = 0.0
    breached: bool = False
    breach_timestamp: Optional[datetime] = None


@dataclass
class KillSwitch:
    """Kill switch for immediate halt of trading activity."""
    switch_id: str
    level: KillSwitchLevel
    target: str
    activated: bool = False
    activated_by: Optional[str] = None
    activated_at: Optional[datetime] = None
    reason: Optional[str] = None
    cancel_open_orders: bool = False


@dataclass
class RiskEvent:
    """Risk control event for audit trail."""
    timestamp: datetime
    event_type: str
    control_id: str
    agent_id: Optional[str]
    description: str
    severity: str
    action_taken: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class MultiAgentRiskControls:
    """
    Multi-agent risk controls system.
    
    Implements:
    - Aggregate exposure caps by asset, sector, factor, venue, agent class
    - Interaction risk limits to prevent feedback loops
    - Global throttles for order/cancel/turnover rates
    - Kill switches at multiple levels
    """
    
    def __init__(self):
        self.info_metrics = get_info_theory_metrics()
        self._social_limits: Dict[str, Dict[str, Any]] = {
            "max_social_exposure_pct": 10.0,
            "max_social_assets": 3,
            "max_asset_allocation_pct": 2.0,
            "correlation_threshold": 0.7,
            "drawdown_kill_switch_pct": 5.0,
        }
        
        self._exposure_caps: Dict[str, AggregateExposureCap] = {}
        self._interaction_limits: Dict[str, InteractionRiskLimit] = {}
        self._throttles: Dict[str, GlobalThrottle] = {}
        self._kill_switches: Dict[str, KillSwitch] = {}
        
        self._risk_events: List[RiskEvent] = []
        
        self._agent_positions: Dict[str, Dict[str, float]] = defaultdict(dict)
        self._agent_actions: Dict[str, List[Tuple[datetime, str, Dict[str, Any]]]] = defaultdict(list)
        self._social_trade_history: List[Dict[str, Any]] = []
        
        self._lock = threading.Lock()
        
        self._initialize_default_controls()
    
    def _initialize_default_controls(self) -> None:
        """Initialize default risk controls."""
        self.register_exposure_cap(
            cap_id="firm_total_notional",
            dimension="firm",
            entity="all",
            max_notional=1000000.0,
            max_leverage=5.0,
            max_concentration_pct=0.30,
        )
        
        self.register_exposure_cap(
            cap_id="crypto_total",
            dimension="asset_class",
            entity="crypto",
            max_notional=500000.0,
            max_leverage=3.0,
            max_concentration_pct=0.50,
        )
        
        self.register_throttle(
            throttle_id="firm_wide_throttle",
            scope="firm",
            max_orders_per_minute=1000,
            max_cancels_per_minute=2000,
            max_notional_turnover_per_hour=5000000.0,
        )
        
        logger.info("Initialized default multi-agent risk controls")
    
    def register_exposure_cap(
        self,
        cap_id: str,
        dimension: str,
        entity: str,
        max_notional: float,
        max_leverage: float,
        max_concentration_pct: float,
    ) -> AggregateExposureCap:
        """Register an aggregate exposure cap."""
        cap = AggregateExposureCap(
            cap_id=cap_id,
            dimension=dimension,
            entity=entity,
            max_notional=max_notional,
            max_leverage=max_leverage,
            max_concentration_pct=max_concentration_pct,
        )
        
        self._exposure_caps[cap_id] = cap
        
        logger.info(
            f"Registered exposure cap '{cap_id}': {dimension}={entity}, "
            f"max_notional=${max_notional:,.0f}, max_leverage={max_leverage}x"
        )
        
        return cap
    
    def register_interaction_limit(
        self,
        limit_id: str,
        agent_group: List[str],
        max_correlated_actions: int,
        time_window_seconds: int,
        max_correlation_score: float,
    ) -> InteractionRiskLimit:
        """Register an interaction risk limit."""
        limit = InteractionRiskLimit(
            limit_id=limit_id,
            agent_group=agent_group,
            max_correlated_actions=max_correlated_actions,
            time_window_seconds=time_window_seconds,
            max_correlation_score=max_correlation_score,
        )
        
        self._interaction_limits[limit_id] = limit
        
        logger.info(
            f"Registered interaction limit '{limit_id}': "
            f"{len(agent_group)} agents, max_correlated={max_correlated_actions}"
        )
        
        return limit
    
    def register_throttle(
        self,
        throttle_id: str,
        scope: str,
        max_orders_per_minute: int,
        max_cancels_per_minute: int,
        max_notional_turnover_per_hour: float,
    ) -> GlobalThrottle:
        """Register a global throttle."""
        throttle = GlobalThrottle(
            throttle_id=throttle_id,
            scope=scope,
            max_orders_per_minute=max_orders_per_minute,
            max_cancels_per_minute=max_cancels_per_minute,
            max_notional_turnover_per_hour=max_notional_turnover_per_hour,
        )
        
        self._throttles[throttle_id] = throttle
        
        logger.info(
            f"Registered throttle '{throttle_id}': scope={scope}, "
            f"max_orders={max_orders_per_minute}/min"
        )
        
        return throttle
    
    def register_kill_switch(
        self,
        switch_id: str,
        level: KillSwitchLevel,
        target: str,
        cancel_open_orders: bool = False,
    ) -> KillSwitch:
        """Register a kill switch."""
        switch = KillSwitch(
            switch_id=switch_id,
            level=level,
            target=target,
            cancel_open_orders=cancel_open_orders,
        )
        
        self._kill_switches[switch_id] = switch
        
        logger.info(
            f"Registered kill switch '{switch_id}': level={level.value}, "
            f"target={target}, cancel_orders={cancel_open_orders}"
        )
        
        return switch
    
    def check_exposure_caps(
        self,
        agent_id: str,
        proposed_position: Dict[str, float],
    ) -> Tuple[bool, List[str]]:
        """
        Check if proposed position would breach aggregate exposure caps.
        
        Returns:
            (approved, violations)
        """
        with self._lock:
            violations = []
            
            for cap_id, cap in self._exposure_caps.items():
                projected_notional = self._calculate_projected_notional(
                    cap, agent_id, proposed_position
                )
                
                if projected_notional > cap.max_notional:
                    violations.append(
                        f"Exposure cap '{cap_id}' would be breached: "
                        f"${projected_notional:,.0f} > ${cap.max_notional:,.0f}"
                    )
                    
                    if not cap.breached:
                        cap.breached = True
                        cap.breach_timestamp = datetime.utcnow()
                        
                        self._record_risk_event(
                            event_type="exposure_cap_breach",
                            control_id=cap_id,
                            agent_id=agent_id,
                            description=f"Aggregate exposure cap breached for {cap.dimension}={cap.entity}",
                            severity="ERROR",
                            action_taken="rejected_position",
                            metadata={
                                "projected_notional": projected_notional,
                                "max_notional": cap.max_notional,
                            },
                        )
            
            approved = len(violations) == 0
            
            return approved, violations
    
    def check_interaction_limits(
        self,
        agent_id: str,
        proposed_action: Dict[str, Any],
    ) -> Tuple[bool, List[str]]:
        """
        Check if proposed action would breach interaction risk limits.
        
        Returns:
            (approved, violations)
        """
        with self._lock:
            violations = []
            
            for limit_id, limit in self._interaction_limits.items():
                if agent_id not in limit.agent_group:
                    continue
                
                recent_actions = self._get_recent_actions(
                    limit.agent_group,
                    limit.time_window_seconds,
                )
                
                if len(recent_actions) >= limit.max_correlated_actions:
                    correlation_score = self._calculate_action_correlation(
                        recent_actions + [(agent_id, proposed_action)]
                    )
                    
                    if correlation_score > limit.max_correlation_score:
                        violations.append(
                            f"Interaction limit '{limit_id}' would be breached: "
                            f"correlation={correlation_score:.3f} > {limit.max_correlation_score:.3f}"
                        )
                        
                        if not limit.breached:
                            limit.breached = True
                            limit.breach_timestamp = datetime.utcnow()
                            
                            self._record_risk_event(
                                event_type="interaction_limit_breach",
                                control_id=limit_id,
                                agent_id=agent_id,
                                description=f"Interaction risk limit breached for agent group",
                                severity="WARNING",
                                action_taken="rejected_action",
                                metadata={
                                    "correlation_score": correlation_score,
                                    "max_correlation": limit.max_correlation_score,
                                    "agent_group": limit.agent_group,
                                },
                            )
            
            approved = len(violations) == 0
            
            return approved, violations
    
    def check_throttles(
        self,
        action_type: str,
        notional: float = 0.0,
    ) -> Tuple[bool, List[str]]:
        """
        Check if action would breach global throttles.
        
        Returns:
            (approved, violations)
        """
        with self._lock:
            violations = []
            
            for throttle_id, throttle in self._throttles.items():
                if action_type == "order" and throttle.current_orders >= throttle.max_orders_per_minute:
                    violations.append(
                        f"Throttle '{throttle_id}' breached: "
                        f"{throttle.current_orders} orders/min >= {throttle.max_orders_per_minute}"
                    )
                
                elif action_type == "cancel" and throttle.current_cancels >= throttle.max_cancels_per_minute:
                    violations.append(
                        f"Throttle '{throttle_id}' breached: "
                        f"{throttle.current_cancels} cancels/min >= {throttle.max_cancels_per_minute}"
                    )
                
                elif notional > 0 and throttle.current_turnover + notional > throttle.max_notional_turnover_per_hour:
                    violations.append(
                        f"Throttle '{throttle_id}' breached: "
                        f"turnover ${throttle.current_turnover + notional:,.0f}/hr > "
                        f"${throttle.max_notional_turnover_per_hour:,.0f}"
                    )
                
                if violations and not throttle.breached:
                    throttle.breached = True
                    throttle.breach_timestamp = datetime.utcnow()
                    
                    self._record_risk_event(
                        event_type="throttle_breach",
                        control_id=throttle_id,
                        agent_id=None,
                        description=f"Global throttle breached",
                        severity="WARNING",
                        action_taken="rejected_action",
                        metadata={
                            "action_type": action_type,
                            "notional": notional,
                        },
                    )
            
            approved = len(violations) == 0
            
            return approved, violations
    
    def activate_kill_switch(
        self,
        switch_id: str,
        activated_by: str,
        reason: str,
    ) -> KillSwitch:
        """Activate a kill switch."""
        if switch_id not in self._kill_switches:
            raise ValueError(f"Kill switch '{switch_id}' not found")
        
        switch = self._kill_switches[switch_id]
        
        if switch.activated:
            logger.warning(f"Kill switch '{switch_id}' already activated")
            return switch
        
        switch.activated = True
        switch.activated_by = activated_by
        switch.activated_at = datetime.utcnow()
        switch.reason = reason
        
        self._record_risk_event(
            event_type="kill_switch_activated",
            control_id=switch_id,
            agent_id=None,
            description=f"Kill switch activated: {reason}",
            severity="CRITICAL",
            action_taken="halt_trading",
            metadata={
                "level": switch.level.value,
                "target": switch.target,
                "activated_by": activated_by,
                "cancel_open_orders": switch.cancel_open_orders,
            },
        )
        
        logger.critical(
            f"KILL SWITCH ACTIVATED: '{switch_id}' by {activated_by} - {reason}"
        )
        
        return switch
    
    def deactivate_kill_switch(
        self,
        switch_id: str,
        deactivated_by: str,
        reason: str,
    ) -> KillSwitch:
        """Deactivate a kill switch."""
        if switch_id not in self._kill_switches:
            raise ValueError(f"Kill switch '{switch_id}' not found")
        
        switch = self._kill_switches[switch_id]
        
        if not switch.activated:
            logger.warning(f"Kill switch '{switch_id}' not activated")
            return switch
        
        switch.activated = False
        
        self._record_risk_event(
            event_type="kill_switch_deactivated",
            control_id=switch_id,
            agent_id=None,
            description=f"Kill switch deactivated: {reason}",
            severity="INFO",
            action_taken="resume_trading",
            metadata={
                "deactivated_by": deactivated_by,
                "was_activated_by": switch.activated_by,
                "activation_duration_seconds": (
                    datetime.utcnow() - switch.activated_at
                ).total_seconds() if switch.activated_at else 0,
            },
        )
        
        logger.info(
            f"Kill switch deactivated: '{switch_id}' by {deactivated_by} - {reason}"
        )
        
        return switch
    
    def is_kill_switch_active(
        self,
        level: Optional[KillSwitchLevel] = None,
        target: Optional[str] = None,
    ) -> bool:
        """Check if any kill switch is active."""
        for switch in self._kill_switches.values():
            if not switch.activated:
                continue
            
            if level and switch.level != level:
                continue
            
            if target and switch.target != target:
                continue
            
            return True
        
        return False
    
    def _calculate_projected_notional(
        self,
        cap: AggregateExposureCap,
        agent_id: str,
        proposed_position: Dict[str, float],
    ) -> float:
        """Calculate projected notional for exposure cap."""
        current_total = sum(
            sum(positions.values())
            for positions in self._agent_positions.values()
        )
        
        proposed_total = sum(proposed_position.values())
        
        return current_total + proposed_total

    def register_social_trade(
        self,
        agent_id: str,
        strategy_id: str,
        asset: str,
        size_usd: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Register a social-driven trade for tracking."""
        record = {
            "timestamp": datetime.utcnow(),
            "agent_id": agent_id,
            "strategy_id": strategy_id,
            "asset": asset.upper(),
            "size_usd": size_usd,
            "metadata": metadata or {},
        }
        self._social_trade_history.append(record)
        if len(self._social_trade_history) > 1000:
            self._social_trade_history = self._social_trade_history[-500:]

    def validate_social_constraints(
        self,
        strategy: StrategyVersion,
        sizing_result: Dict[str, Any],
    ) -> Tuple[bool, List[str]]:
        """Validate social-specific constraints before allowing trade."""
        violations: List[str] = []
        constraints = sizing_result.get("constraints", {})

        if not sizing_result.get("allowed"):
            violations.append(sizing_result.get("reason", "Social sizing rejected"))

        if not constraints.get("confirmation_available", False):
            violations.append("No market confirmation available for social strategy")
        if not constraints.get("data_fresh", False):
            violations.append("Social data is stale for requested asset")

        if constraints.get("kill_switch_active"):
            violations.append(f"Social kill switch active: {constraints.get('kill_switch_reason', 'unknown')}")

        asset_exposure_pct = constraints.get("asset_exposure", 0.0) / max(1.0, sizing_result.get("portfolio_value", 1.0)) * 100
        if asset_exposure_pct > self._social_limits["max_asset_allocation_pct"]:
            violations.append(
                f"Asset exposure {asset_exposure_pct:.2f}% exceeds max "
                f"{self._social_limits['max_asset_allocation_pct']:.2f}%"
            )

        remaining_pct = sizing_result.get("remaining_social_budget", 0.0) / max(1.0, sizing_result.get("portfolio_value", 1.0)) * 100
        if remaining_pct < 0:
            violations.append("Total social exposure limit exceeded")

        assets = strategy.social_assets if strategy.is_social_strategy else []
        if len(assets) > self._social_limits["max_social_assets"]:
            violations.append(
                f"Strategy targets {len(assets)} social assets exceeds max "
                f"{self._social_limits['max_social_assets']}"
            )

        approved = len(violations) == 0
        return approved, violations
    
    def _get_recent_actions(
        self,
        agent_group: List[str],
        time_window_seconds: int,
    ) -> List[Tuple[str, Dict[str, Any]]]:
        """Get recent actions for agent group."""
        cutoff = datetime.utcnow() - timedelta(seconds=time_window_seconds)
        
        recent = []
        for agent_id in agent_group:
            for timestamp, action_type, action_data in self._agent_actions[agent_id]:
                if timestamp >= cutoff:
                    recent.append((agent_id, action_data))
        
        return recent
    
    def _calculate_action_correlation(
        self,
        actions: List[Tuple[str, Dict[str, Any]]],
    ) -> float:
        """Calculate correlation score for actions using entropy."""
        if len(actions) < 2:
            return 0.0
        
        action_types = [a[1].get("action_type", "unknown") for a in actions]
        sides = [a[1].get("side", "unknown") for a in actions]
        assets = [a[1].get("asset", "unknown") for a in actions]
        
        type_entropy = self._calculate_distribution_entropy(action_types)
        side_entropy = self._calculate_distribution_entropy(sides)
        asset_entropy = self._calculate_distribution_entropy(assets)
        
        avg_entropy = (type_entropy + side_entropy + asset_entropy) / 3.0
        
        correlation_score = 1.0 - avg_entropy
        
        return correlation_score
    
    def _calculate_distribution_entropy(self, values: List[str]) -> float:
        """Calculate normalized entropy of value distribution."""
        if not values:
            return 1.0
        
        counts = {}
        for v in values:
            counts[v] = counts.get(v, 0) + 1
        
        import numpy as np
        probs = np.array(list(counts.values())) / len(values)
        entropy = -np.sum(probs * np.log2(probs + 1e-10))
        
        max_entropy = np.log2(len(counts)) if len(counts) > 1 else 1.0
        
        return entropy / max_entropy if max_entropy > 0 else 0.0
    
    def _record_risk_event(
        self,
        event_type: str,
        control_id: str,
        agent_id: Optional[str],
        description: str,
        severity: str,
        action_taken: str,
        metadata: Dict[str, Any],
    ) -> None:
        """Record risk control event."""
        event = RiskEvent(
            timestamp=datetime.utcnow(),
            event_type=event_type,
            control_id=control_id,
            agent_id=agent_id,
            description=description,
            severity=severity,
            action_taken=action_taken,
            metadata=metadata,
        )
        
        self._risk_events.append(event)
    
    def get_risk_events(
        self,
        event_type: Optional[str] = None,
        severity: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[RiskEvent]:
        """Query risk control events."""
        events = self._risk_events
        
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        
        if severity:
            events = [e for e in events if e.severity == severity]
        
        if since:
            events = [e for e in events if e.timestamp >= since]
        
        return events[-limit:]
    
    def get_control_summary(self) -> Dict[str, Any]:
        """Get summary of all risk controls."""
        return {
            "exposure_caps": {
                "total": len(self._exposure_caps),
                "breached": sum(1 for c in self._exposure_caps.values() if c.breached),
            },
            "interaction_limits": {
                "total": len(self._interaction_limits),
                "breached": sum(1 for l in self._interaction_limits.values() if l.breached),
            },
            "throttles": {
                "total": len(self._throttles),
                "breached": sum(1 for t in self._throttles.values() if t.breached),
            },
            "kill_switches": {
                "total": len(self._kill_switches),
                "active": sum(1 for s in self._kill_switches.values() if s.activated),
            },
            "risk_events": {
                "total": len(self._risk_events),
                "critical": len([e for e in self._risk_events if e.severity == "CRITICAL"]),
                "errors": len([e for e in self._risk_events if e.severity == "ERROR"]),
                "warnings": len([e for e in self._risk_events if e.severity == "WARNING"]),
            },
        }


_multi_agent_risk_controls: Optional[MultiAgentRiskControls] = None
_multi_agent_risk_controls_lock = threading.Lock()


def get_multi_agent_risk_controls() -> MultiAgentRiskControls:
    """Get global MultiAgentRiskControls instance."""
    global _multi_agent_risk_controls
    if _multi_agent_risk_controls is None:
        with _multi_agent_risk_controls_lock:
            if _multi_agent_risk_controls is None:
                _multi_agent_risk_controls = MultiAgentRiskControls()
    return _multi_agent_risk_controls
