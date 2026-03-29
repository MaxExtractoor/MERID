"""MERID Risk Management Module.

Provides hard safety controls for trading:
- Kill switches (global, daily loss, position limits)
- Risk status monitoring
- Event callbacks for alerts

Usage:
    from merid.risk import can_trade, emergency_stop, get_risk_status
    
    if not can_trade():
        logger.info("Trading halted!")
        logger.info(get_risk_status())
"""

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
from merid.risk.capital_engine import (
    AssetCapitalConfig,
    CapitalEngine,
    CapitalSnapshot,
    RiskBudget,
)

__all__ = [
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
]
