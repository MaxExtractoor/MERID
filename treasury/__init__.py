"""
MERID Treasury Module - Phase 22

Full treasury automation with:
- Yield strategy agent competition
- Treasury-only simulation sandbox
- Drawdown governor independent of trading
- Auto-rebalancing across yield sources
- Emergency unwind logic for DeFi protocols
"""

from treasury.yield_strategies import (
    get_yield_registry,
    get_strategy_competition,
    get_simulation_sandbox,
    YieldSourceRegistry,
    StrategyCompetition,
    TreasurySimulationSandbox,
    YieldSource,
    YieldStrategy,
    StrategyProposal,
    YieldStrategyAgent,
    YieldProtocol,
    RiskTier,
    StrategyStatus,
)

from treasury.drawdown_governor import (
    get_drawdown_governor,
    get_auto_rebalancer,
    get_emergency_unwind,
    DrawdownGovernor,
    AutoRebalancer,
    EmergencyUnwindManager,
    DrawdownState,
    DrawdownAction,
    DrawdownLimits,
    DrawdownEvent,
)

__all__ = [
    # Yield strategies
    "get_yield_registry",
    "get_strategy_competition",
    "get_simulation_sandbox",
    "YieldSourceRegistry",
    "StrategyCompetition",
    "TreasurySimulationSandbox",
    "YieldSource",
    "YieldStrategy",
    "StrategyProposal",
    "YieldStrategyAgent",
    "YieldProtocol",
    "RiskTier",
    "StrategyStatus",
    # Drawdown governor
    "get_drawdown_governor",
    "get_auto_rebalancer",
    "get_emergency_unwind",
    "DrawdownGovernor",
    "AutoRebalancer",
    "EmergencyUnwindManager",
    "DrawdownState",
    "DrawdownAction",
    "DrawdownLimits",
    "DrawdownEvent",
]
