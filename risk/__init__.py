"""MERID Risk Management Module (Legacy re-export).

This package re-exports from merid.risk for backward compatibility.
New code should use: from merid.risk import ...
"""

# Re-export all risk components from the canonical merid.risk namespace
from merid.risk.agent_metrics import (
    AgentMetrics,
    AgentMetricsTracker,
    PerformanceSnapshot,
    get_agent_metrics_tracker,
)
from merid.risk.capital_engine import (
    AssetCapitalConfig,
    CapitalEngine,
    CapitalSnapshot,
    RiskBudget,
)
from merid.risk.kill_switches import (
    KillSwitchEvent,
    KillSwitchReason,
    KillSwitchState,
    RiskController,
    can_trade,
    emergency_stop,
    get_risk_status,
    risk_controller,
)
from merid.risk.portfolio_optimizer import PortfolioOptimizer
from merid.risk.position_sizing import PositionSizer
from merid.risk.risk_guard import RiskGuard
from merid.risk.risk_monitor import RiskMonitor

__all__ = [
    # Kill switches
    "KillSwitchEvent",
    "KillSwitchReason",
    "KillSwitchState",
    "RiskController",
    "can_trade",
    "emergency_stop",
    "get_risk_status",
    "risk_controller",
    # Capital engine
    "AssetCapitalConfig",
    "CapitalEngine",
    "CapitalSnapshot",
    "RiskBudget",
    # Agent metrics
    "AgentMetrics",
    "AgentMetricsTracker",
    "PerformanceSnapshot",
    "get_agent_metrics_tracker",
    # Portfolio and position sizing
    "PortfolioOptimizer",
    "PositionSizer",
    "RiskGuard",
    "RiskMonitor",
]
