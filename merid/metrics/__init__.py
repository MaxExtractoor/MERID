"""merid.metrics — Forecast calibration, realized edge tracking, and outcome resolution.

Sprint A: Brier calibration + realized edge tracking.
Unlocks weighted consensus (Sprint C) and heterogeneous forecasters (Sprint B).
"""

from merid.metrics.calibration import (
    BrierStats,
    ForecastRecord,
    CalibrationStore,
    get_calibration_store,
)
from merid.metrics.realized_edge import (
    TradeEdgeRecord,
    EdgeStats,
    RealizedEdgeStore,
    get_realized_edge_store,
)
from merid.metrics.outcome_resolver import (
    OutcomeResolver,
    get_outcome_resolver,
)

__all__ = [
    "BrierStats",
    "ForecastRecord",
    "CalibrationStore",
    "get_calibration_store",
    "TradeEdgeRecord",
    "EdgeStats",
    "RealizedEdgeStore",
    "get_realized_edge_store",
    "OutcomeResolver",
    "get_outcome_resolver",
]
