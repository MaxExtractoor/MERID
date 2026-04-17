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
from merid.metrics.cell_metrics import (
    CellMetrics,
    record_candidate,
    record_order,
    record_fill,
    record_veto,
    snapshot,
    get_cell,
    reset_for_tests,
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
    # cell_metrics (BUG-016)
    "CellMetrics",
    "record_candidate",
    "record_order",
    "record_fill",
    "record_veto",
    "snapshot",
    "get_cell",
    "reset_for_tests",
]
