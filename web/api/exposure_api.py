"""
Exposure API Endpoint

Provides per-asset and per-timeframe exposure metrics for real-time risk monitoring.
Exposes the internal exposure state used by risk checks to enable operational visibility.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from utils.logger import get_logger

logger = get_logger("web.api.exposure_api")

router = APIRouter(prefix="/api/v1/exposure", tags=["exposure"])


class AssetTimeframeExposure(BaseModel):
    """Exposure metrics for a specific asset and timeframe combination."""
    asset: str
    timeframe: str
    net_exposure_usd: float
    gross_exposure_usd: float
    contracts_long: int
    contracts_short: int
    cap_used_pct: float
    cap_max_usd: float


@router.get("/by-asset-timeframe")
async def get_exposure_by_asset_timeframe(
    asset: Optional[str] = Query(None, description="Filter by specific asset (BTC/ETH/SOL/XRP/DOGE)"),
    timeframe: Optional[str] = Query(None, description="Filter by timeframe (15m/1h/4h/1d)"),
) -> List[AssetTimeframeExposure]:
    """
    Get exposure metrics broken down by asset and timeframe.

    Returns exposure data used internally by risk checks, providing visibility into:
    - Net and gross exposure per asset/timeframe
    - Long/short contract counts
    - Cap utilization percentage

    Query parameters:
    - asset: Filter to specific asset (optional)
    - timeframe: Filter to specific timeframe (optional)

    Returns:
        List of AssetTimeframeExposure objects with current exposure metrics
    """
    try:
        from merid.event_venues.kalshi.venue_adapter import get_kalshi_venue_adapter
        from merid.trading.kalshi_continuous_trader import get_kalshi_continuous_trader

        # Try to get exposure from Kalshi continuous trader first
        try:
            trader = get_kalshi_continuous_trader()
            if hasattr(trader, 'get_exposure_snapshot'):
                snapshot = trader.get_exposure_snapshot()
                if snapshot:
                    exposures = _process_trader_snapshot(snapshot, asset, timeframe)
                    if exposures:
                        return exposures
        except Exception as trader_exc:
            logger.debug(f"Could not get exposure from continuous trader: {trader_exc}")

        # Fallback: Get positions from venue adapter
        adapter = get_kalshi_venue_adapter()
        positions = await adapter.get_positions()

        # Group positions by asset and timeframe
        exposure_map: Dict[tuple, Dict[str, Any]] = {}

        for pos in positions:
            # Parse ticker to extract asset and timeframe
            parsed = _parse_ticker(pos.symbol)
            if not parsed:
                continue

            pos_asset = parsed.get("asset", "UNKNOWN")
            pos_timeframe = parsed.get("timeframe", "1d")

            # Apply filters
            if asset and pos_asset != asset.upper():
                continue
            if timeframe and pos_timeframe != timeframe:
                continue

            key = (pos_asset, pos_timeframe)

            if key not in exposure_map:
                exposure_map[key] = {
                    "asset": pos_asset,
                    "timeframe": pos_timeframe,
                    "net_exposure_usd": 0.0,
                    "gross_exposure_usd": 0.0,
                    "contracts_long": 0,
                    "contracts_short": 0,
                }

            # Aggregate exposure
            size_usd = pos.size * pos.mark_price if hasattr(pos, 'mark_price') else pos.size
            if pos.side == "long":
                exposure_map[key]["contracts_long"] += abs(int(pos.size))
                exposure_map[key]["net_exposure_usd"] += size_usd
                exposure_map[key]["gross_exposure_usd"] += abs(size_usd)
            else:
                exposure_map[key]["contracts_short"] += abs(int(pos.size))
                exposure_map[key]["net_exposure_usd"] -= size_usd
                exposure_map[key]["gross_exposure_usd"] += abs(size_usd)

        # Get caps and calculate cap_used_pct
        caps = _get_exposure_caps()

        result = []
        for (pos_asset, pos_timeframe), exp in exposure_map.items():
            cap_key = f"{pos_asset}_{pos_timeframe}"
            cap_max = caps.get(cap_key, 5000.0)

            cap_used_pct = (exp["gross_exposure_usd"] / cap_max * 100) if cap_max > 0 else 0.0

            result.append(AssetTimeframeExposure(
                asset=pos_asset,
                timeframe=pos_timeframe,
                net_exposure_usd=round(exp["net_exposure_usd"], 2),
                gross_exposure_usd=round(exp["gross_exposure_usd"], 2),
                contracts_long=exp["contracts_long"],
                contracts_short=exp["contracts_short"],
                cap_used_pct=round(cap_used_pct, 2),
                cap_max_usd=cap_max,
            ))

        # If no positions found, return zero exposure for configured assets/timeframes
        if not result and not asset and not timeframe:
            result = _get_zero_exposures()

        return result

    except Exception as exc:
        logger.error(f"Failed to get exposure by asset/timeframe: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get exposure: {str(exc)}")


def _parse_ticker(ticker: str) -> Optional[Dict[str, str]]:
    """Parse Kalshi ticker to extract asset and timeframe.

    Examples:
        KXBTC-26MAR25-T95000 -> {asset: BTC, timeframe: 1d}
        KXBTC-15M-26MAR25-T95000 -> {asset: BTC, timeframe: 15m}
        KXETH-D1-26MAR25-T3500 -> {asset: ETH, timeframe: 1d}
    """
    if not ticker or not ticker.startswith("KX"):
        return None

    parts = ticker.split("-")
    if len(parts) < 2:
        return None

    # Extract asset from first part (e.g., KXBTC -> BTC)
    asset_part = parts[0]
    if asset_part.startswith("KX"):
        asset = asset_part[2:]  # Remove "KX" prefix
    else:
        return None

    # Detect timeframe from second part
    timeframe = "1d"  # Default
    if len(parts) >= 3:
        second_part = parts[1]
        if second_part == "15M":
            timeframe = "15m"
        elif second_part == "1H":
            timeframe = "1h"
        elif second_part == "4H":
            timeframe = "4h"
        elif second_part == "D1":
            timeframe = "1d"

    return {"asset": asset, "timeframe": timeframe}


def _get_exposure_caps() -> Dict[str, float]:
    """Get exposure caps for each asset/timeframe combination.

    Returns a map of "ASSET_TIMEFRAME" -> cap_usd
    """
    # Try to load from settings
    try:
        from merid.settings import settings
        # Look for cap configuration
        caps = {}

        # Default caps per asset/timeframe
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        timeframes = ["15m", "1h", "4h", "1d"]

        for asset in assets:
            for tf in timeframes:
                key = f"{asset}_{tf}"
                # Use smaller caps for shorter timeframes
                if tf == "15m":
                    caps[key] = getattr(settings, f"MERID_MAX_EXPOSURE_{asset}_15M", 2000.0)
                elif tf == "1h":
                    caps[key] = getattr(settings, f"MERID_MAX_EXPOSURE_{asset}_1H", 3000.0)
                elif tf == "4h":
                    caps[key] = getattr(settings, f"MERID_MAX_EXPOSURE_{asset}_4H", 4000.0)
                else:  # 1d
                    caps[key] = getattr(settings, f"MERID_MAX_EXPOSURE_{asset}_1D", 5000.0)

        return caps
    except Exception as exc:
        logger.debug(f"Could not load caps from settings: {exc}")
        # Return sensible defaults
        return {
            "BTC_15m": 2000.0, "BTC_1h": 3000.0, "BTC_4h": 4000.0, "BTC_1d": 5000.0,
            "ETH_15m": 2000.0, "ETH_1h": 3000.0, "ETH_4h": 4000.0, "ETH_1d": 5000.0,
            "SOL_15m": 1500.0, "SOL_1h": 2000.0, "SOL_4h": 3000.0, "SOL_1d": 4000.0,
            "XRP_15m": 1500.0, "XRP_1h": 2000.0, "XRP_4h": 3000.0, "XRP_1d": 4000.0,
            "DOGE_15m": 1000.0, "DOGE_1h": 1500.0, "DOGE_4h": 2000.0, "DOGE_1d": 3000.0,
        }


def _get_zero_exposures() -> List[AssetTimeframeExposure]:
    """Return zero exposures for all configured asset/timeframe combinations."""
    caps = _get_exposure_caps()
    result = []

    for key, cap_max in caps.items():
        asset, timeframe = key.split("_")
        result.append(AssetTimeframeExposure(
            asset=asset,
            timeframe=timeframe,
            net_exposure_usd=0.0,
            gross_exposure_usd=0.0,
            contracts_long=0,
            contracts_short=0,
            cap_used_pct=0.0,
            cap_max_usd=cap_max,
        ))

    return sorted(result, key=lambda x: (x.asset, x.timeframe))


def _process_trader_snapshot(snapshot: Any, asset: Optional[str], timeframe: Optional[str]) -> List[AssetTimeframeExposure]:
    """Process exposure snapshot from continuous trader."""
    # This is a placeholder for future integration with continuous trader's exposure tracking
    # For now, return empty to fall back to position-based calculation
    return []
