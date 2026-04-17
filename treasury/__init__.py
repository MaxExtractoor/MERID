"""
MERID-TREASURY Module

Capital & Yield Preservation - "How do we not die?"

Phase 3 of Master Build Directive - CAPITAL GEOMETRY

Treasury principal is sacred.

Components:
- Portfolio Geometry: Fractional Kelly, HRP, Copula tail dependency
- Capital Thermodynamics: Temperature, turnover heat, correlation stress, cooling
- Vault Architecture: Multi-sig, time-locks, capital firewalls
- Yield Strategies: Agent competition, simulation sandbox
- Drawdown Governor: Auto-rebalancing, emergency unwind
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

from treasury.portfolio_geometry import (
    PortfolioGeometryEngine,
    KellyCriterion,
    HierarchicalRiskParity,
    CopulaTailDependency,
    RiskRegime,
    PositionSizeResult,
    PortfolioState,
    get_portfolio_geometry,
)

from treasury.capital_thermodynamics import (
    CapitalThermodynamicsEngine,
    TemperatureState,
    CoolingMechanism,
    ThermodynamicState,
    TurnoverHeatCalculator,
    CorrelationHeatCalculator,
    LeverageHeatCalculator,
    CoolingSystem,
    get_capital_thermodynamics,
)

from treasury.vaults import (
    VaultManager,
    Vault,
    VaultType,
    WithdrawalIntent,
    WithdrawalStatus,
    Signer,
    SignerRole,
    MultiSigManager,
    TimelockManager,
    CapitalFirewall,
    get_vault_manager,
)
from treasury.profit_receiver import (
    ProfitReceiver,
    ProfitRecord,
    DepositStatus,
    AllocationStrategy,
    AllocationRule,
    get_profit_receiver,
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
    # Portfolio Geometry
    "PortfolioGeometryEngine",
    "KellyCriterion",
    "HierarchicalRiskParity",
    "CopulaTailDependency",
    "RiskRegime",
    "PositionSizeResult",
    "PortfolioState",
    "get_portfolio_geometry",
    # Capital Thermodynamics
    "CapitalThermodynamicsEngine",
    "TemperatureState",
    "CoolingMechanism",
    "ThermodynamicState",
    "TurnoverHeatCalculator",
    "CorrelationHeatCalculator",
    "LeverageHeatCalculator",
    "CoolingSystem",
    "get_capital_thermodynamics",
    # Vaults
    "VaultManager",
    "Vault",
    "VaultType",
    "WithdrawalIntent",
    "WithdrawalStatus",
    "Signer",
    "SignerRole",
    "MultiSigManager",
    "TimelockManager",
    "CapitalFirewall",
    "get_vault_manager",
    # Profit Receiver
    "ProfitReceiver",
    "ProfitRecord",
    "DepositStatus",
    "AllocationStrategy",
    "AllocationRule",
    "get_profit_receiver",
]
