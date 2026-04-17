"""
Watchdog Agents - Autonomy and Correctness Monitoring

Dedicated agents that monitor other agents for:
- Liveness (heartbeat timeouts)
- Consensus health (stuck opinions, missing consensus)
- Mode violations (live broker calls in paper mode)
- Data staleness (trading on old state)

Watchdogs emit alerts as events for UI visibility.
"""

from __future__ import annotations

import threading
import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Deque

from schemas.swarm_events import (
    StrategyOpinion,
    ConsensusDecision,
    TradeIntent,
    AgentHeartbeat,
    TradingMode,
)
from observability.event_stream import publish_event
from observability.swarm_telemetry import get_swarm_telemetry
from utils.logger import get_logger

logger = get_logger("agents.watchdog")


@dataclass
class WatchdogAlert:
    """Alert from a watchdog agent."""
    alert_id: str
    watchdog_type: str
    severity: str  # info, warning, critical
    agent_id: Optional[str]
    symbol: Optional[str]
    message: str
    details: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self):
        return {
            "alert_id": self.alert_id,
            "watchdog_type": self.watchdog_type,
            "severity": self.severity,
            "agent_id": self.agent_id,
            "symbol": self.symbol,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp,
        }


class LivenessWatchdog:
    """
    Monitors agent heartbeats and alerts on timeout.
    
    Detects:
    - Agents that stop sending heartbeats
    - Agents with no output for extended periods
    - Agents stuck in error states
    """
    
    def __init__(
        self,
        heartbeat_timeout_seconds: float = 60.0,
        output_timeout_seconds: float = 120.0,
    ):
        self.heartbeat_timeout = heartbeat_timeout_seconds
        self.output_timeout = output_timeout_seconds
        self._agent_last_heartbeat: Dict[str, float] = {}
        self._agent_last_output: Dict[str, float] = {}
        self._agent_types: Dict[str, str] = {}
        self._alerted_agents: Set[str] = set()
        
    async def check_liveness(self) -> List[WatchdogAlert]:
        """Check all agents for liveness issues."""
        alerts = []
        now = time.time()
        telemetry = get_swarm_telemetry()
        
        for metrics in telemetry.get_all_agent_metrics():
            agent_id = metrics.agent_id
            
            # Check heartbeat timeout
            if metrics.last_heartbeat > 0:
                time_since_heartbeat = now - metrics.last_heartbeat
                
                if time_since_heartbeat > self.heartbeat_timeout:
                    if agent_id not in self._alerted_agents:
                        alert = WatchdogAlert(
                            alert_id=f"liveness_{agent_id}_{int(now)}",
                            watchdog_type="liveness",
                            severity="critical",
                            agent_id=agent_id,
                            symbol=None,
                            message=f"Agent {agent_id} heartbeat timeout",
                            details={
                                "agent_type": metrics.agent_type,
                                "time_since_heartbeat_seconds": time_since_heartbeat,
                                "threshold_seconds": self.heartbeat_timeout,
                            },
                        )
                        alerts.append(alert)
                        self._alerted_agents.add(agent_id)
                        logger.warning(f"Liveness alert: {alert.message}")
                else:
                    # Agent recovered
                    self._alerted_agents.discard(agent_id)
            
            # Check output timeout
            if metrics.last_output_timestamp > 0:
                time_since_output = now - metrics.last_output_timestamp
                
                if time_since_output > self.output_timeout:
                    alert = WatchdogAlert(
                        alert_id=f"output_{agent_id}_{int(now)}",
                        watchdog_type="liveness",
                        severity="warning",
                        agent_id=agent_id,
                        symbol=None,
                        message=f"Agent {agent_id} has not produced output",
                        details={
                            "agent_type": metrics.agent_type,
                            "time_since_output_seconds": time_since_output,
                            "threshold_seconds": self.output_timeout,
                        },
                    )
                    alerts.append(alert)
                    logger.warning(f"Output timeout: {alert.message}")
        
        return alerts


class ConsensusWatchdog:
    """
    Monitors consensus formation health.
    
    Detects:
    - Opinions flowing but no consensus formed
    - Consensus with too few agents
    - High correlation (all agents agree suspiciously)
    - High disagreement that blocks action
    """
    
    def __init__(
        self,
        min_agents_for_consensus: int = 3,
        max_correlation_threshold: float = 0.95,
        high_disagreement_threshold: float = 0.4,
        opinion_timeout_seconds: float = 300.0,
    ):
        self.min_agents = min_agents_for_consensus
        self.max_correlation = max_correlation_threshold
        self.high_disagreement = high_disagreement_threshold
        self.opinion_timeout = opinion_timeout_seconds
        
        # Track opinions waiting for consensus
        self._pending_opinions: Dict[str, List[StrategyOpinion]] = defaultdict(list)
        self._last_consensus: Dict[str, float] = {}
        
    async def track_opinion(self, opinion: StrategyOpinion) -> None:
        """Track an opinion for consensus monitoring."""
        key = f"{opinion.symbol}_{opinion.venue}"
        self._pending_opinions[key].append(opinion)
        
        # Clean old opinions
        cutoff = time.time() - self.opinion_timeout
        self._pending_opinions[key] = [
            o for o in self._pending_opinions[key] if o.timestamp > cutoff
        ]
    
    async def track_consensus(self, decision: ConsensusDecision) -> None:
        """Track a consensus decision."""
        key = f"{decision.symbol}_{decision.venue}"
        self._last_consensus[key] = decision.timestamp
        
        # Clear pending opinions for this symbol
        if key in self._pending_opinions:
            del self._pending_opinions[key]
    
    async def check_consensus_health(self) -> List[WatchdogAlert]:
        """Check consensus formation health."""
        alerts = []
        now = time.time()
        
        # Check for stale opinion windows (opinions but no consensus)
        for key, opinions in self._pending_opinions.items():
            if len(opinions) >= self.min_agents:
                oldest_opinion = min(o.timestamp for o in opinions)
                age_seconds = now - oldest_opinion
                
                if age_seconds > 60:  # Opinions older than 1 minute
                    symbol = key.split('_')[0]
                    alert = WatchdogAlert(
                        alert_id=f"consensus_stuck_{key}_{int(now)}",
                        watchdog_type="consensus",
                        severity="warning",
                        agent_id=None,
                        symbol=symbol,
                        message=f"Opinions pending consensus for {symbol}",
                        details={
                            "symbol": symbol,
                            "opinion_count": len(opinions),
                            "age_seconds": age_seconds,
                            "agent_ids": [o.agent_id for o in opinions],
                        },
                    )
                    alerts.append(alert)
                    logger.warning(f"Consensus stuck: {alert.message}")
        
        return alerts
    
    async def check_decision_quality(
        self,
        decision: ConsensusDecision,
    ) -> List[WatchdogAlert]:
        """Check quality of a consensus decision."""
        alerts = []
        now = time.time()
        
        # Check for too few agents
        if len(decision.participating_agents) < self.min_agents:
            alert = WatchdogAlert(
                alert_id=f"consensus_quorum_{decision.decision_id}",
                watchdog_type="consensus",
                severity="warning",
                agent_id=None,
                symbol=decision.symbol,
                message=f"Consensus formed with only {len(decision.participating_agents)} agents",
                details={
                    "symbol": decision.symbol,
                    "participating_agents": decision.participating_agents,
                    "required_minimum": self.min_agents,
                },
            )
            alerts.append(alert)
            logger.warning(f"Low quorum: {alert.message}")
        
        # Check for suspiciously high agreement (potential groupthink)
        if decision.confidence > self.max_correlation and len(decision.dissenters) == 0:
            alert = WatchdogAlert(
                alert_id=f"consensus_groupthink_{decision.decision_id}",
                watchdog_type="consensus",
                severity="info",
                agent_id=None,
                symbol=decision.symbol,
                message=f"Unusually high agreement for {decision.symbol}",
                details={
                    "symbol": decision.symbol,
                    "confidence": decision.confidence,
                    "participating_agents": decision.participating_agents,
                    "note": "May indicate correlated agents or groupthink",
                },
            )
            alerts.append(alert)
            logger.info(f"High correlation: {alert.message}")
        
        # Check for high disagreement
        if decision.dissent_ratio > self.high_disagreement:
            alert = WatchdogAlert(
                alert_id=f"consensus_disagreement_{decision.decision_id}",
                watchdog_type="consensus",
                severity="warning",
                agent_id=None,
                symbol=decision.symbol,
                message=f"High disagreement ({decision.dissent_ratio:.1%}) for {decision.symbol}",
                details={
                    "symbol": decision.symbol,
                    "dissent_ratio": decision.dissent_ratio,
                    "dissenters": decision.dissenters,
                    "decision": decision.decision.value,
                },
            )
            alerts.append(alert)
            logger.warning(f"High disagreement: {alert.message}")
        
        return alerts


class ModeWatchdog:
    """
    Monitors trading mode compliance.
    
    Detects:
    - Live broker calls in PAPER/SIM mode
    - Mode mismatches between components
    - Unauthorized live trading attempts
    """
    
    def __init__(self, expected_mode: TradingMode = TradingMode.MOCK):
        self.expected_mode = expected_mode
        self._mode_violations: Deque[WatchdogAlert] = deque(maxlen=100)
        
    async def check_trade_intent_mode(
        self,
        intent: TradeIntent,
    ) -> List[WatchdogAlert]:
        """Verify trade intent matches expected mode."""
        alerts = []
        
        if intent.mode != self.expected_mode:
            alert = WatchdogAlert(
                alert_id=f"mode_mismatch_{intent.intent_id}",
                watchdog_type="mode",
                severity="critical",
                agent_id=None,
                symbol=intent.symbol,
                message=f"Mode mismatch: intent is {intent.mode.value}, expected {self.expected_mode.value}",
                details={
                    "intent_id": intent.intent_id,
                    "intent_mode": intent.mode.value,
                    "expected_mode": self.expected_mode.value,
                    "symbol": intent.symbol,
                },
            )
            alerts.append(alert)
            self._mode_violations.append(alert)
            logger.critical(f"MODE VIOLATION: {alert.message}")
        
        # Check if live trading without proper authorization
        if intent.mode == TradingMode.LIVE:
            alert = WatchdogAlert(
                alert_id=f"live_attempt_{intent.intent_id}",
                watchdog_type="mode",
                severity="critical",
                agent_id=None,
                symbol=intent.symbol,
                message=f"LIVE TRADING ATTEMPT for {intent.symbol}",
                details={
                    "intent_id": intent.intent_id,
                    "symbol": intent.symbol,
                    "side": intent.side,
                    "quantity": intent.quantity,
                    "risk_checked": intent.risk_checked,
                },
            )
            alerts.append(alert)
            logger.critical(f"LIVE TRADING: {alert.message}")
        
        return alerts
    
    def get_violation_history(self) -> List[WatchdogAlert]:
        """Get history of mode violations."""
        return list(self._mode_violations)


class StalenessWatchdog:
    """
    Monitors data freshness and state staleness.
    
    Detects:
    - Trading on stale prices
    - Non-monotonic state versions
    - Excessive lag between price and decision
    """
    
    def __init__(
        self,
        max_age_seconds: float = 10.0,
        max_lag_seconds: float = 5.0,
    ):
        self.max_age = max_age_seconds
        self.max_lag = max_lag_seconds
        self._latest_state_versions: Dict[str, str] = {}
        
    async def check_opinion_freshness(
        self,
        opinion: StrategyOpinion,
        current_price: float,
        current_timestamp: float,
    ) -> List[WatchdogAlert]:
        """Check if opinion is based on stale data."""
        alerts = []
        
        # Check age
        age_seconds = current_timestamp - opinion.timestamp
        if age_seconds > self.max_age:
            alert = WatchdogAlert(
                alert_id=f"stale_opinion_{opinion.opinion_id}",
                watchdog_type="staleness",
                severity="warning",
                agent_id=opinion.agent_id,
                symbol=opinion.symbol,
                message=f"Stale opinion from {opinion.agent_id}",
                details={
                    "opinion_id": opinion.opinion_id,
                    "age_seconds": age_seconds,
                    "max_age_seconds": self.max_age,
                    "price_at_opinion": opinion.price_at_opinion,
                    "current_price": current_price,
                },
            )
            alerts.append(alert)
            logger.warning(f"Stale opinion: {alert.message}")
        
        return alerts
    
    async def check_trade_intent_freshness(
        self,
        intent: TradeIntent,
        current_timestamp: float,
    ) -> List[WatchdogAlert]:
        """Check if trade intent is based on fresh consensus."""
        alerts = []
        
        # Check lag between consensus and trade
        lag_seconds = current_timestamp - intent.timestamp
        if lag_seconds > self.max_lag:
            alert = WatchdogAlert(
                alert_id=f"stale_trade_{intent.intent_id}",
                watchdog_type="staleness",
                severity="warning",
                agent_id=None,
                symbol=intent.symbol,
                message=f"Trade intent has {lag_seconds:.1f}s lag",
                details={
                    "intent_id": intent.intent_id,
                    "lag_seconds": lag_seconds,
                    "max_lag_seconds": self.max_lag,
                },
            )
            alerts.append(alert)
            logger.warning(f"Stale trade: {alert.message}")
        
        return alerts


class WatchdogCoordinator:
    """
    Coordinates all watchdog agents and publishes alerts.
    
    Runs periodic checks and emits alerts as events.
    """
    
    def __init__(
        self,
        expected_mode: TradingMode = TradingMode.MOCK,
        check_interval_seconds: float = 30.0,
    ):
        self.liveness = LivenessWatchdog()
        self.consensus = ConsensusWatchdog()
        self.mode = ModeWatchdog(expected_mode)
        self.staleness = StalenessWatchdog()
        
        self.check_interval = check_interval_seconds
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
        logger.info(f"WatchdogCoordinator initialized (mode={expected_mode.value})")
    
    async def start(self) -> None:
        """Start periodic watchdog checks."""
        if self._running:
            logger.warning("WatchdogCoordinator already running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="watchdog-coordinator")
        def _task_done_cb(task: asyncio.Task) -> None:
            if not task.cancelled() and task.exception():
                logger.error("Watchdog coordinator task crashed: %s", task.exception())
        self._task.add_done_callback(_task_done_cb)
        logger.info("WatchdogCoordinator started")
    
    async def stop(self) -> None:
        """Stop periodic checks."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("WatchdogCoordinator stopped")
    
    async def _run_loop(self) -> None:
        """Main watchdog loop."""
        while self._running:
            try:
                # Run all checks
                alerts = await self._run_checks()
                
                # Publish alerts
                for alert in alerts:
                    await publish_event("watchdog_alert", alert.to_dict())
                
                # Wait for next check
                await asyncio.sleep(self.check_interval)
                
            except Exception as e:
                logger.error(f"Watchdog check error: {e}", exc_info=True)
                await asyncio.sleep(self.check_interval)
    
    async def _run_checks(self) -> List[WatchdogAlert]:
        """Run all watchdog checks."""
        alerts = []
        
        # Liveness checks
        liveness_alerts = await self.liveness.check_liveness()
        alerts.extend(liveness_alerts)
        
        # Consensus checks
        consensus_alerts = await self.consensus.check_consensus_health()
        alerts.extend(consensus_alerts)
        
        return alerts


# Global instance
_watchdog_coordinator: Optional[WatchdogCoordinator] = None
_watchdog_coordinator_lock = threading.Lock()


def get_watchdog_coordinator(
    expected_mode: TradingMode = TradingMode.MOCK,
) -> WatchdogCoordinator:
    """Get or create global watchdog coordinator."""
    global _watchdog_coordinator
    if _watchdog_coordinator is None:
        with _watchdog_coordinator_lock:
            if _watchdog_coordinator is None:
                _watchdog_coordinator = WatchdogCoordinator(expected_mode)
    return _watchdog_coordinator
