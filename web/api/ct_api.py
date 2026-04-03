"""Continuous Trader diagnostics API.

Exposes the KalshiContinuousTrader status — including per-cycle counters,
veto breakdown, and per-ticker edge diagnostics — so the dashboard can show
*why* CT is seeing 0 candidates or 0 approved intents rather than a blank state.

Endpoint
--------
GET /api/v1/ct/status
    Returns the live status() dict from the process-singleton trader, extended
    with last_cycle diagnostics.  Always returns 200; 'running' field is false
    when CT has not been started yet.
"""

from __future__ import annotations

from fastapi import APIRouter
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/ct", tags=["continuous-trader"])
logger = get_logger("web.api.ct")


@router.get("/status")
async def get_ct_status() -> dict:
    """Return Continuous Trader status including last-cycle diagnostics.

    Fields:
    - running: bool — whether CT task is active
    - candidate_count: int — candidates loaded from catalog
    - config: dict — active thresholds (min_edge, kelly_fraction, etc.)
    - risk: dict — daily risk accumulators (loss, trades, rejections)
    - filter: dict — volume-band filter stats from last candidate scan
    - last_cycle: dict — per-cycle counters and per-ticker veto breakdown:
        - candidates_seen
        - markets_with_any_edge
        - markets_after_risk_veto
        - vetoed_total
        - vetoed_by_reason: {reason: count}
        - ticker_diagnostics: [{ticker, asset, timeframe, implied_yes_prob,
                                model_win_prob, edge_bps, side, kelly_raw,
                                kelly_frac, veto_reason}]
        - cycle_ts: unix timestamp of last cycle
    """
    try:
        from merid.trading.kalshi_continuous_trader import get_continuous_trader
        trader = get_continuous_trader()
        return {"status": "ok", "data": trader.status()}
    except Exception as exc:
        logger.warning("CT status unavailable: %s", exc)
        return {
            "status": "unavailable",
            "data": {
                "running": False,
                "candidate_count": 0,
                "config": {},
                "risk": {},
                "filter": {},
                "last_cycle": {},
            },
        }
