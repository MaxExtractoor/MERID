"""Continuous Trader diagnostics API.

Exposes the KalshiContinuousTrader status — including per-cycle counters,
veto breakdown, and per-ticker edge diagnostics — so the dashboard can show
*why* CT is seeing 0 candidates or 0 approved intents rather than a blank state.

Endpoints
---------
GET /api/v1/ct/status
    Returns the live status() dict from the process-singleton trader, extended
    with last_cycle diagnostics.  Always returns 200; 'running' field is false
    when CT has not been started yet.

GET /api/v1/ct/market-states
    Returns candidate market states from CT's last scan.
    Supports optional ``assets`` query param (comma-separated, e.g. ``BTC,ETH``)
    to filter results.  AUDIT-13.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Query
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


@router.get("/market-states")
async def get_ct_market_states(
    assets: Optional[str] = Query(
        None,
        description=(
            "Comma-separated asset filter, e.g. 'BTC,ETH'.  "
            "When omitted, all tracked assets are returned.  AUDIT-13."
        ),
    ),
    timeframe: Optional[str] = Query(None, description="Filter by timeframe, e.g. '15m', '1h'."),
) -> dict:
    """Return per-candidate market states from CT's last discovery scan.

    Supports optional ``assets`` and ``timeframe`` filters so dashboards and
    monitoring tools can pull only the markets they care about, avoiding the
    overhead of retrieving all 25 (asset × timeframe) markets.

    AUDIT-13: Adding assets= filtering here (and to the list_markets endpoint)
    prevents dashboards from pulling irrelevant markets.
    """
    try:
        from merid.trading.kalshi_continuous_trader import get_continuous_trader
        trader = get_continuous_trader()
        status = trader.status()
        candidates = status.get("candidates", [])

        # Build the allowed-assets set from the query param
        allowed_assets: Optional[set] = None
        if assets:
            allowed_assets = {a.strip().upper() for a in assets.split(",") if a.strip()}

        filtered = []
        for c in candidates:
            asset = (c.get("underlying") or c.get("asset") or "").upper()
            tf = (c.get("timeframe") or "").lower()
            if allowed_assets and asset not in allowed_assets:
                continue
            if timeframe and tf != timeframe.lower():
                continue
            filtered.append(c)

        return {
            "status": "ok",
            "assets_filter": sorted(allowed_assets) if allowed_assets else None,
            "timeframe_filter": timeframe,
            "count": len(filtered),
            "market_states": filtered,
        }
    except Exception as exc:
        logger.warning("CT market-states unavailable: %s", exc)
        return {
            "status": "unavailable",
            "assets_filter": None,
            "timeframe_filter": None,
            "count": 0,
            "market_states": [],
        }
