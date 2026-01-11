"""
MERID-FIN Execution Intelligence

Phase 4 of Master Build Directive

This package contains:
- Optimal execution algorithms (Almgren-Chriss, VWAP, TWAP)
- MEV and manipulation defense
- Queue position estimation
- Market impact modeling
"""

from trading.execution.optimal import (
    get_optimal_executor,
    OptimalExecutionEngine,
    ExecutionStrategy,
    AlmgrenChriss,
    VWAP,
    TWAP,
)

from trading.execution.defense import (
    get_mev_defense,
    MEVDefenseEngine,
    ManipulationDetector,
)

__all__ = [
    "get_optimal_executor",
    "OptimalExecutionEngine",
    "ExecutionStrategy",
    "AlmgrenChriss",
    "VWAP",
    "TWAP",
    "get_mev_defense",
    "MEVDefenseEngine",
    "ManipulationDetector",
]
