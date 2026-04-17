"""
Crypto Spot vs Kalshi API — Unified view of spot prices alongside Kalshi contract prices.

Provides:
  GET /api/v1/crypto/spot-vs-kalshi
    Per-asset (BTC, ETH, SOL, XRP, DOGE):
      - CoinGecko spot price (cached 15s)
      - Active Kalshi markets grouped by timeframe, sorted by expiry
      - Strike vs spot delta for each contract
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/crypto", tags=["crypto-spot-kalshi"])

ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]

# ── Spot price helper (CoinGecko, 15s cache) ────────────────────────────

_CG_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "XRP": "ripple",
    "DOGE": "dogecoin",
}
_spot_cache: Dict[str, tuple] = {}  # asset -> (price_float, fetched_at_mono)
_SPOT_CACHE_TTL = 15.0  # seconds


def _fetch_spots_sync() -> Dict[str, Optional[float]]:
    """Fetch spot prices for all crypto assets in a single CoinGecko call.

    Returns a dict like ``{"BTC": 84231.5, "ETH": 1923.1, ...}``.
    Cached for 15 seconds to avoid rate-limit issues.
    """
    global _spot_cache
    now = time.monotonic()

    # Check if all assets are still cached
    if _spot_cache and all(
        asset in _spot_cache and (now - _spot_cache[asset][1]) < _SPOT_CACHE_TTL
        for asset in ASSETS
    ):
        return {asset: _spot_cache[asset][0] for asset in ASSETS}

    # Batch fetch from CoinGecko
    ids_csv = ",".join(_CG_IDS[a] for a in ASSETS)
    try:
        api_key = os.environ.get("COINGECKO_API_KEY") or os.environ.get("COINGECKO_PRO_API_KEY", "")
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids_csv}&vs_currencies=usd"
        req = urllib.request.Request(url, headers={"accept": "application/json"})
        if api_key:
            req.add_header("x-cg-demo-api-key", api_key)
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())

        result: Dict[str, Optional[float]] = {}
        for asset in ASSETS:
            cg_id = _CG_IDS[asset]
            price = data.get(cg_id, {}).get("usd")
            result[asset] = float(price) if price is not None else None
            if price is not None:
                _spot_cache[asset] = (float(price), now)

        return result
    except Exception as exc:
        logger.warning("CoinGecko batch spot fetch failed: %s", exc)
        # Return whatever is still in cache
        return {
            asset: _spot_cache[asset][0] if asset in _spot_cache else None
            for asset in ASSETS
        }


# ── Kalshi market extraction ────────────────────────────────────────────

def _extract_market_info(cm: Any, spot: Optional[float]) -> Dict[str, Any]:
    """Extract a compact dict from a CatalogMarket for the API response.

    Merges catalog data (static: strike, expiry) with MarketStateStore live data
    (dynamic: yes/no prices, prob, volume from WS orderbook/quotes).

    Note: EventOutcome.best_ask / .price are stored as fractions (0–1) because
    _to_event_market divides the raw Kalshi cent values by 100.  We convert back
    to cents for the *_cents fields and keep the fraction for implied_prob.
    """
    mkt = cm.market
    ticker = mkt.market_id

    # Try to get live data from MarketStateStore first
    live_state = None
    try:
        from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
        store = get_kalshi_market_state_store()
        live_state = store.get(ticker)
    except Exception as e:
        logger.debug(f"Silent error: {e}")

    # Prices as fractions (0–1); prefer live WS data over catalog data
    yes_frac: Optional[float] = None
    no_frac: Optional[float] = None
    implied_prob: Optional[float] = None
    volume_24h: float = float(mkt.volume) if mkt.volume else 0.0
    open_interest: float = float(mkt.open_interest) if mkt.open_interest else 0.0

    if live_state:
        # Use live WS-derived data when available
        yes_frac = live_state.yes_bid  # bid is what you can sell for
        yes_ask_frac = live_state.yes_ask  # ask is what you can buy for
        if yes_frac is not None:
            implied_prob = live_state.prob
        # Derive no prices from yes (complementary)
        if yes_ask_frac is not None:
            no_frac = 1.0 - yes_ask_frac
        # Use live volume/OI if available
        if live_state.volume_24h:
            volume_24h = float(live_state.volume_24h)
        if live_state.open_interest:
            open_interest = float(live_state.open_interest)
    else:
        # Fallback to catalog data (may be stale)
        if mkt.outcomes:
            for o in mkt.outcomes:
                name = (o.outcome_name or "").lower()
                if name == "yes" or name == "":
                    yes_frac = float(o.best_ask) if o.best_ask is not None else (float(o.price) if o.price is not None else None)
                    if o.probability is not None:
                        implied_prob = float(o.probability)
                    elif yes_frac is not None:
                        # For catalog data, price is already in cents, convert to fraction
                        implied_prob = yes_frac / 100.0 if yes_frac > 1.0 else yes_frac
                elif name == "no":
                    no_frac = float(o.best_ask) if o.best_ask is not None else (float(o.price) if o.price is not None else None)

        # If we only have one outcome, derive the other
        # For WebSocket (fractional): prices sum to 1.0 → convert to cents
        # For catalog (fixed-point): prices sum to 100 cents
        if yes_frac is not None and no_frac is None:
            if live_state:
                # WebSocket: fractions sum to 1
                no_frac = 1.0 - yes_frac
            elif yes_frac <= 1.0:
                # Catalog data in fractional format (edge case)
                no_frac = 1.0 - yes_frac
            else:
                # Catalog data in cents (e.g., 55) → derive no in cents space
                no_frac = 100.0 - yes_frac  # 100 - 55 = 45 cents
        if no_frac is not None and yes_frac is None:
            if live_state:
                yes_frac = 1.0 - no_frac
            elif no_frac <= 1.0:
                yes_frac = 1.0 - no_frac
            else:
                # Catalog data in cents → derive yes in cents space
                yes_frac = 100.0 - no_frac

    # Convert to cents for the response fields
    # Note: By this point, yes_frac/no_frac may be:
    #   - fractions (0-1) from WebSocket → multiply by 100
    #   - cents (0-100) from catalog → use as-is (but still round)
    if live_state:
        # WebSocket data is fractions (0-1), convert to cents
        yes_cents = round(yes_frac * 100, 1) if yes_frac is not None else None
        no_cents = round(no_frac * 100, 1) if no_frac is not None else None
    else:
        # Catalog data: values are already in cents space (0-100), just round
        yes_cents = round(yes_frac, 1) if yes_frac is not None else None
        no_cents = round(no_frac, 1) if no_frac is not None else None

    # Strike vs spot delta
    strike = cm.strike_price
    delta_pct: Optional[float] = None
    if strike is not None and spot is not None and spot > 0:
        delta_pct = round(((strike - spot) / spot) * 100, 2)

    return {
        "ticker": ticker,
        "question": mkt.question[:120] if mkt.question else "",
        "yes_price_cents": yes_cents,
        "no_price_cents": no_cents,
        "implied_prob": round(implied_prob, 4) if implied_prob is not None else None,
        "strike": strike,
        "strike_vs_spot_pct": delta_pct,
        "volume": volume_24h,
        "open_interest": open_interest,
        "timeframe": cm.timeframe,
        "series_ticker": cm.series_ticker,
        "expires_at": cm.expires_at.isoformat() if cm.expires_at else None,
        "minutes_to_expiry": round(cm.minutes_to_expiry, 1) if cm.minutes_to_expiry is not None else None,
        # NEW: Include live source indicator for debugging
        "live_ws_data": live_state is not None,
    }


# ── Endpoint ────────────────────────────────────────────────────────────

@router.get("/spot-vs-kalshi")
async def get_spot_vs_kalshi() -> Dict[str, Any]:
    """Unified crypto spot + Kalshi contract prices.

    Returns per-asset:
      - spot_usd: current CoinGecko spot price
      - markets: list of active Kalshi contracts grouped by timeframe,
                 sorted by expiry (nearest first)
    """
    t0 = time.monotonic()

    # 1. Fetch spot prices off the event loop
    spots = await asyncio.to_thread(_fetch_spots_sync)

    # 2. Pull active Kalshi markets from the catalog
    try:
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        catalog = get_market_catalog()
    except Exception as exc:
        logger.warning("Could not get market catalog: %s", exc)
        catalog = None

    assets_data: Dict[str, Any] = {}
    for asset in ASSETS:
        spot = spots.get(asset)

        # Get Kalshi markets for this asset
        markets_raw: List[Any] = []
        if catalog:
            try:
                markets_raw = catalog.get_markets_by_asset(asset)
            except Exception as e:
                logger.debug(f"Silent error: {e}")

        # Filter to active, non-expired, sort by expiry
        now_utc = datetime.now(timezone.utc)
        active_markets = []
        for cm in markets_raw:
            if cm.expires_at and cm.expires_at < now_utc:
                continue
            if not cm.market.active:
                continue
            active_markets.append(cm)

        active_markets.sort(
            key=lambda cm: cm.expires_at or datetime.max.replace(tzinfo=timezone.utc)
        )

        # Group by timeframe
        by_tf: Dict[str, list] = {}
        for cm in active_markets:
            tf = cm.timeframe or "unknown"
            by_tf.setdefault(tf, []).append(_extract_market_info(cm, spot))

        # Summary stats
        total_contracts = len(active_markets)
        nearest_expiry = None
        if active_markets and active_markets[0].expires_at:
            nearest_expiry = active_markets[0].expires_at.isoformat()

        assets_data[asset] = {
            "spot_usd": round(spot, 2) if spot is not None else None,
            "total_contracts": total_contracts,
            "nearest_expiry": nearest_expiry,
            "by_timeframe": by_tf,
        }

    elapsed_ms = round((time.monotonic() - t0) * 1000, 1)
    return {
        "assets": assets_data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "latency_ms": elapsed_ms,
    }
