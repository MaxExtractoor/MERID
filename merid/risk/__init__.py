"""MERID Risk Management Module.

Provides hard safety controls for trading:
- Kill switches (global, daily loss, position limits)
- Risk status monitoring
- Event callbacks for alerts
- Capital engine (three-bucket capital model)
- Agent metrics and performance tracking
- Portfolio optimization and position sizing

Usage:
    from merid.risk import can_trade, emergency_stop, get_risk_status
    
    if not can_trade():
        logger.info("Trading halted!")
        logger.info(get_risk_status())
"""

from merid.risk.agent_metrics import (
    AgentMetrics,
    AgentMetricsTracker,
    PerformanceSnapshot,
    get_agent_metrics_tracker,
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

# Heavy imports (pandas/numpy) are deferred via __getattr__ to avoid a 5+s
# cold-import penalty that blocks tests and startup.  No caller imports
# these symbols from merid.risk — they all use direct module imports.
_LAZY_IMPORTS = {
    "PortfolioOptimizer": "merid.risk.portfolio_optimizer",
    "PositionSizer": "merid.risk.position_sizing",
    "RiskGuard": "merid.risk.risk_guard",
    "RiskMonitor": "merid.risk.risk_monitor",
}


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        import importlib
        mod = importlib.import_module(_LAZY_IMPORTS[name])
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
    # LEGACY REMOVAL: capital_engine moved to archive/legacy/ during 15m stack cleanup
    # "AssetCapitalConfig",
    # "CapitalEngine",
    # "CapitalSnapshot",
    # "RiskBudget",
    # Agent metrics
    "AgentMetrics",
    "AgentMetricsTracker",
    "PerformanceSnapshot",
    "get_agent_metrics_tracker",
    # Portfolio and position sizing (lazy)
    "PortfolioOptimizer",
    "PositionSizer",
    "RiskGuard",
    "RiskMonitor",
]
