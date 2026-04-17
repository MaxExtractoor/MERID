"""
Swarm Health Telemetry - First-Class Metrics

Tracks swarm behavior as observable metrics:
- Per-agent health (heartbeat, lag, error rate)
- Swarm-level metrics (consensus rate, opinion flow, disagreement)
- Latency tracking (price → opinion → consensus → trade)

Exportable to Prometheus/OpenTelemetry for dashboards.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Deque

from schemas.swarm_events import (
    StrategyOpinion,
    ConsensusDecision,
    TradeIntent,
    OrderEvent,
    AgentHeartbeat,
)
from utils.logger import get_logger

logger = get_logger("observability.swarm_telemetry")


@dataclass
class AgentMetrics:
    """Per-agent health metrics."""
    agent_id: str
    agent_type: str
    
    # Liveness
    last_heartbeat: float = 0.0
    heartbeat_interval_ms: float = 0.0
    status: str = "unknown"  # healthy, degraded, error, offline
    
    # Activity
    messages_processed: int = 0
    messages_per_minute: float = 0.0
    last_output_timestamp: float = 0.0
    
    # Performance
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    input_lag_ms: float = 0.0
    
    # Errors
    error_count: int = 0
    error_rate: float = 0.0
    last_error_timestamp: float = 0.0
    
    # Recent latencies for percentile calculation
    recent_latencies: Deque[float] = field(default_factory=lambda: deque(maxlen=100))


@dataclass
class SwarmMetrics:
    """System-level swarm health metrics."""
    # Opinion flow
    opinions_per_minute: float = 0.0
    opinions_by_symbol: Dict[str, int] = field(default_factory=dict)
    
    # Consensus
    consensus_decisions_per_minute: float = 0.0
    consensus_success_rate: float = 0.0  # Fraction of opinion windows yielding consensus
    consensus_windows_total: int = 0
    consensus_windows_successful: int = 0
    
    # Disagreement
    avg_disagreement_rate: float = 0.0  # Avg fraction of dissenting agents
    high_disagreement_count: int = 0  # Count of high-disagreement decisions
    
    # Latency (end-to-end pipeline)
    avg_price_to_opinion_ms: float = 0.0
    avg_opinion_to_consensus_ms: float = 0.0
    avg_consensus_to_trade_ms: float = 0.0
    avg_total_pipeline_ms: float = 0.0
    
    # Trade flow
    trades_per_minute: float = 0.0
    trade_success_rate: float = 0.0
    
    # Agent participation
    active_agents: int = 0
    total_agents: int = 0
    agent_participation_rate: float = 0.0


class SwarmTelemetry:
    """
    Collects and aggregates swarm health metrics.
    
    Provides observable metrics for:
    - Individual agent health
    - System-wide swarm behavior
    - End-to-end latency tracking
    """
    
    def __init__(self):
        # Agent tracking
        self._agent_metrics: Dict[str, AgentMetrics] = {}
        self._agent_last_seen: Dict[str, float] = {}
        
        # Event tracking for rate calculation
        self._opinion_timestamps: Deque[float] = deque(maxlen=1000)
        self._consensus_timestamps: Deque[float] = deque(maxlen=1000)
        self._trade_timestamps: Deque[float] = deque(maxlen=1000)
        
        # Opinion windows tracking
        self._opinion_windows: Dict[str, List[StrategyOpinion]] = defaultdict(list)
        self._consensus_outcomes: List[bool] = deque(maxlen=100)  # Success/failure
        
        # Disagreement tracking
        self._disagreement_ratios: Deque[float] = deque(maxlen=100)
        
        # Pipeline latency tracking
        self._price_to_opinion_latencies: Deque[float] = deque(maxlen=100)
        self._opinion_to_consensus_latencies: Deque[float] = deque(maxlen=100)
        self._consensus_to_trade_latencies: Deque[float] = deque(maxlen=100)
        
        logger.info("SwarmTelemetry initialized")
    
    def record_heartbeat(self, heartbeat: AgentHeartbeat) -> None:
        """Record an agent heartbeat."""
        agent_id = heartbeat.agent_id
        
        # Update or create agent metrics
        if agent_id not in self._agent_metrics:
            self._agent_metrics[agent_id] = AgentMetrics(
                agent_id=agent_id,
                agent_type=heartbeat.agent_type,
            )
        
        metrics = self._agent_metrics[agent_id]
        
        # Update liveness
        now = time.time()
        if metrics.last_heartbeat > 0:
            metrics.heartbeat_interval_ms = (now - metrics.last_heartbeat) * 1000
        metrics.last_heartbeat = now
        metrics.status = heartbeat.status
        
        # Update activity
        metrics.messages_processed = heartbeat.messages_processed_count
        metrics.last_output_timestamp = heartbeat.last_output_timestamp
        
        # Update performance
        metrics.input_lag_ms = heartbeat.input_lag_ms
        metrics.p50_latency_ms = heartbeat.processing_latency_p50_ms
        metrics.p99_latency_ms = heartbeat.processing_latency_p99_ms
        
        # Update errors
        if heartbeat.error_count > metrics.error_count:
            metrics.last_error_timestamp = now
        metrics.error_count = heartbeat.error_count
        
        # Track last seen
        self._agent_last_seen[agent_id] = now
    
    def record_opinion(self, opinion: StrategyOpinion) -> None:
        """Record a strategy opinion."""
        self._opinion_timestamps.append(opinion.timestamp)
        
        # Track by symbol for windowing
        key = f"{opinion.symbol}_{opinion.venue}"
        self._opinion_windows[key].append(opinion)
        
        # Clean old opinions (older than 5 minutes)
        cutoff = time.time() - 300
        self._opinion_windows[key] = [
            o for o in self._opinion_windows[key] if o.timestamp > cutoff
        ]
    
    def record_consensus(
        self,
        decision: ConsensusDecision,
        opinion_window_had_opinions: bool = True,
    ) -> None:
        """Record a consensus decision."""
        self._consensus_timestamps.append(decision.timestamp)
        
        # Track consensus success/failure
        self._consensus_outcomes.append(opinion_window_had_opinions)
        
        # Track disagreement
        self._disagreement_ratios.append(decision.dissent_ratio)
        
        # Track opinion→consensus latency if we have opinion window timing
        if decision.opinion_window_ms > 0:
            self._opinion_to_consensus_latencies.append(decision.opinion_window_ms)
    
    def record_trade_intent(
        self,
        intent: TradeIntent,
        consensus_timestamp: Optional[float] = None,
    ) -> None:
        """Record a trade intent."""
        self._trade_timestamps.append(intent.timestamp)
        
        # Track consensus→trade latency
        if consensus_timestamp:
            latency_ms = (intent.timestamp - consensus_timestamp) * 1000
            self._consensus_to_trade_latencies.append(latency_ms)
    
    def record_order_event(self, event: OrderEvent) -> None:
        """Record an order execution event."""
        # Could track fill latencies, slippage distribution, etc.
        pass
    
    def get_agent_metrics(self, agent_id: str) -> Optional[AgentMetrics]:
        """Get metrics for a specific agent."""
        return self._agent_metrics.get(agent_id)
    
    def get_all_agent_metrics(self) -> List[AgentMetrics]:
        """Get metrics for all agents."""
        return list(self._agent_metrics.values())
    
    def get_swarm_metrics(self) -> SwarmMetrics:
        """Get current swarm-level metrics."""
        now = time.time()
        
        # Calculate rates (events per minute)
        opinions_per_min = self._calculate_rate(self._opinion_timestamps, now, 60)
        consensus_per_min = self._calculate_rate(self._consensus_timestamps, now, 60)
        trades_per_min = self._calculate_rate(self._trade_timestamps, now, 60)
        
        # Calculate consensus success rate
        if len(self._consensus_outcomes) > 0:
            consensus_success_rate = sum(self._consensus_outcomes) / len(self._consensus_outcomes)
        else:
            consensus_success_rate = 0.0
        
        # Calculate average disagreement
        if len(self._disagreement_ratios) > 0:
            avg_disagreement = sum(self._disagreement_ratios) / len(self._disagreement_ratios)
            high_disagreement_count = sum(
                1 for r in self._disagreement_ratios if r > 0.3
            )
        else:
            avg_disagreement = 0.0
            high_disagreement_count = 0
        
        # Calculate latencies
        avg_opinion_to_consensus = (
            sum(self._opinion_to_consensus_latencies) / len(self._opinion_to_consensus_latencies)
            if self._opinion_to_consensus_latencies else 0.0
        )
        avg_consensus_to_trade = (
            sum(self._consensus_to_trade_latencies) / len(self._consensus_to_trade_latencies)
            if self._consensus_to_trade_latencies else 0.0
        )
        
        # Calculate agent participation
        active_agents = sum(
            1 for agent_id, last_seen in self._agent_last_seen.items()
            if now - last_seen < 60  # Active if seen in last 60s
        )
        total_agents = len(self._agent_metrics)
        participation_rate = active_agents / total_agents if total_agents > 0 else 0.0
        
        # Count opinions by symbol
        opinions_by_symbol = {}
        for key, opinions in self._opinion_windows.items():
            symbol = key.split('_')[0]
            opinions_by_symbol[symbol] = len(opinions)
        
        return SwarmMetrics(
            opinions_per_minute=opinions_per_min,
            opinions_by_symbol=opinions_by_symbol,
            consensus_decisions_per_minute=consensus_per_min,
            consensus_success_rate=consensus_success_rate,
            consensus_windows_total=len(self._consensus_outcomes),
            consensus_windows_successful=sum(self._consensus_outcomes),
            avg_disagreement_rate=avg_disagreement,
            high_disagreement_count=high_disagreement_count,
            avg_opinion_to_consensus_ms=avg_opinion_to_consensus,
            avg_consensus_to_trade_ms=avg_consensus_to_trade,
            avg_total_pipeline_ms=avg_opinion_to_consensus + avg_consensus_to_trade,
            trades_per_minute=trades_per_min,
            active_agents=active_agents,
            total_agents=total_agents,
            agent_participation_rate=participation_rate,
        )
    
    def _calculate_rate(
        self,
        timestamps: Deque[float],
        now: float,
        window_seconds: float,
    ) -> float:
        """Calculate event rate over a time window."""
        cutoff = now - window_seconds
        recent_count = sum(1 for ts in timestamps if ts > cutoff)
        return (recent_count / window_seconds) * 60  # Events per minute
    
    def check_agent_health(self, timeout_seconds: float = 60.0) -> Dict[str, str]:
        """
        Check health of all agents.
        
        Returns dict of {agent_id: status} for agents that need attention.
        """
        now = time.time()
        issues = {}
        
        for agent_id, metrics in self._agent_metrics.items():
            # Check heartbeat timeout
            if metrics.last_heartbeat > 0:
                time_since_heartbeat = now - metrics.last_heartbeat
                if time_since_heartbeat > timeout_seconds:
                    issues[agent_id] = f"offline (last seen {time_since_heartbeat:.0f}s ago)"
                    continue
            
            # Check error rate
            if metrics.error_rate > 0.1:  # >10% error rate
                issues[agent_id] = f"high_error_rate ({metrics.error_rate:.1%})"
                continue
            
            # Check input lag
            if metrics.input_lag_ms > 5000:  # >5s lag
                issues[agent_id] = f"high_lag ({metrics.input_lag_ms:.0f}ms)"
                continue
            
            # Check status
            if metrics.status not in ("healthy", "unknown"):
                issues[agent_id] = metrics.status
        
        return issues
    
    def get_prometheus_metrics(self) -> str:
        """
        Export metrics in Prometheus format.
        
        Returns metrics as text in Prometheus exposition format.
        """
        lines = []
        swarm = self.get_swarm_metrics()
        
        # Swarm-level metrics
        lines.append(f"# HELP merid_opinions_per_minute Rate of strategy opinions")
        lines.append(f"# TYPE merid_opinions_per_minute gauge")
        lines.append(f"merid_opinions_per_minute {swarm.opinions_per_minute}")
        
        lines.append(f"# HELP merid_consensus_per_minute Rate of consensus decisions")
        lines.append(f"# TYPE merid_consensus_per_minute gauge")
        lines.append(f"merid_consensus_per_minute {swarm.consensus_decisions_per_minute}")
        
        lines.append(f"# HELP merid_consensus_success_rate Fraction of opinion windows yielding consensus")
        lines.append(f"# TYPE merid_consensus_success_rate gauge")
        lines.append(f"merid_consensus_success_rate {swarm.consensus_success_rate}")
        
        lines.append(f"# HELP merid_disagreement_rate Average agent disagreement rate")
        lines.append(f"# TYPE merid_disagreement_rate gauge")
        lines.append(f"merid_disagreement_rate {swarm.avg_disagreement_rate}")
        
        lines.append(f"# HELP merid_agent_participation_rate Fraction of agents active")
        lines.append(f"# TYPE merid_agent_participation_rate gauge")
        lines.append(f"merid_agent_participation_rate {swarm.agent_participation_rate}")
        
        # Per-agent metrics
        for metrics in self._agent_metrics.values():
            labels = f'agent_id="{metrics.agent_id}",agent_type="{metrics.agent_type}"'
            
            lines.append(f"merid_agent_heartbeat{{{labels}}} {metrics.last_heartbeat}")
            lines.append(f"merid_agent_input_lag_ms{{{labels}}} {metrics.input_lag_ms}")
            lines.append(f"merid_agent_error_count{{{labels}}} {metrics.error_count}")
        
        return "\n".join(lines)
    
    def get_stats_dict(self) -> Dict[str, Any]:
        """Get telemetry stats as dictionary for API/UI."""
        swarm = self.get_swarm_metrics()
        agent_health = self.check_agent_health()
        
        return {
            "swarm": {
                "opinions_per_minute": swarm.opinions_per_minute,
                "consensus_per_minute": swarm.consensus_decisions_per_minute,
                "trades_per_minute": swarm.trades_per_minute,
                "consensus_success_rate": swarm.consensus_success_rate,
                "disagreement_rate": swarm.avg_disagreement_rate,
                "active_agents": swarm.active_agents,
                "total_agents": swarm.total_agents,
                "participation_rate": swarm.agent_participation_rate,
                "avg_pipeline_latency_ms": swarm.avg_total_pipeline_ms,
            },
            "agents": [
                {
                    "agent_id": m.agent_id,
                    "agent_type": m.agent_type,
                    "status": m.status,
                    "last_heartbeat": m.last_heartbeat,
                    "messages_processed": m.messages_processed,
                    "error_count": m.error_count,
                    "input_lag_ms": m.input_lag_ms,
                    "p99_latency_ms": m.p99_latency_ms,
                }
                for m in self.get_all_agent_metrics()
            ],
            "health_issues": agent_health,
        }


# Global instance
_swarm_telemetry: Optional[SwarmTelemetry] = None
_swarm_telemetry_lock = threading.Lock()


def get_swarm_telemetry() -> SwarmTelemetry:
    """Get or create global swarm telemetry instance."""
    global _swarm_telemetry
    if _swarm_telemetry is None:
        with _swarm_telemetry_lock:
            if _swarm_telemetry is None:
                _swarm_telemetry = SwarmTelemetry()
    return _swarm_telemetry
