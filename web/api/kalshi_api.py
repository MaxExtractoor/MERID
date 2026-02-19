"""Kalshi Deep Integration API — /api/v1/kalshi/*

Endpoints:
  GET  /api/v1/kalshi/markets          — Browse all cataloged markets
  GET  /api/v1/kalshi/markets/{ticker}  — Single market detail
  GET  /api/v1/kalshi/catalog           — Catalog summary (categories, assets, timeframes)
  GET  /api/v1/kalshi/positions         — Current Kalshi positions
  GET  /api/v1/kalshi/orders            — Open orders
  GET  /api/v1/kalshi/fills             — Recent fills/trades
  GET  /api/v1/kalshi/markets/{t}/orderbook — Orderbook ladders
  GET  /api/v1/kalshi/events/{event}   — Markets for an event/series
  GET  /api/v1/kalshi/balance           — Account balance
  POST /api/v1/kalshi/orders           — Place an order (paper or live)
  GET  /api/v1/kalshi/pnl              — Portfolio PnL summary
  GET  /api/v1/kalshi/risk             — Risk manager status
  GET  /api/v1/kalshi/ws               — WebSocket bridge status
  GET  /api/v1/kalshi/health           — Comprehensive health check
  GET  /api/v1/kalshi/export           — CSV export of filtered markets
  POST /api/v1/kalshi/kill-switch      — Activate/reset kill switch
  POST /api/v1/kalshi/catalog/refresh  — Force catalog refresh
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from utils.logger import get_logger

logger = get_logger("web.api.kalshi_api")

router = APIRouter(prefix="/api/v1/kalshi", tags=["kalshi"])


# ── Lazy imports (with merid_core fallbacks) ─────────────────────────────

def _get_catalog():
    try:
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        return get_market_catalog()
    except (ImportError, ModuleNotFoundError):
        return None


def _get_risk():
    try:
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
        return get_kalshi_risk()
    except (ImportError, ModuleNotFoundError):
        return None


def _get_bridge():
    try:
        from merid.event_venues.kalshi.ws_bridge import get_ws_bridge
        return get_ws_bridge()
    except (ImportError, ModuleNotFoundError):
        return None


def _get_rest_client():
    """Get our working merid_core Kalshi REST client."""
    try:
        from merid.settings import settings
        key_id = settings.KALSHI_API_KEY_ID
        key_path = settings.KALSHI_PRIVATE_KEY_PATH
        env = "demo" if settings.KALSHI_USE_DEMO else "prod"
    except Exception:
        import os
        key_id = os.environ.get("KALSHI_API_KEY_ID")
        key_path = os.environ.get("KALSHI_PRIVATE_KEY_PATH")
        env = "demo" if os.environ.get("KALSHI_USE_DEMO", "false").lower() == "true" else "prod"
    if not key_id or not key_path or key_path == "change_me":
        return None
    try:
        from merid_core.kalshi.rest_client import get_rest_client
        return get_rest_client(key_id=key_id, private_key_path=key_path, env=env)
    except (ImportError, Exception) as exc:
        logger.warning(f"Failed to create merid_core REST client: {exc}")
        return None


def _get_client():
    """Try old venue client with settings-based config."""
    try:
        from merid.settings import settings
        from merid.event_venues.kalshi.client import KalshiVenueClient
        from merid.event_venues.kalshi.models import KalshiConfig
        key_path = settings.KALSHI_PRIVATE_KEY_PATH
        if key_path == "change_me":
            key_path = None
        config = KalshiConfig(
            api_key=settings.KALSHI_API_KEY_ID,
            private_key_path=key_path,
            private_key_pem=settings.KALSHI_PRIVATE_KEY_PEM,
            email=settings.KALSHI_EMAIL,
            password=settings.KALSHI_PASSWORD,
            use_demo=settings.KALSHI_USE_DEMO,
        )
        return KalshiVenueClient(config)
    except (ImportError, ModuleNotFoundError):
        return None


def _get_executor():
    """Return the module-level KalshiExecutor singleton."""
    try:
        from merid.execution.executors.kalshi import KalshiExecutor
        if not hasattr(_get_executor, "_instance"):
            _get_executor._instance = KalshiExecutor()
        return _get_executor._instance
    except Exception as exc:
        logger.warning(f"KalshiExecutor unavailable: {exc}")
        return None


def _get_volume_monitor():
    try:
        from merid.event_venues.kalshi.volume_monitor import get_volume_monitor
        return get_volume_monitor()
    except (ImportError, ModuleNotFoundError):
        return None


def _get_liquidity_monitor():
    try:
        from merid.event_venues.kalshi.liquidity_monitor import get_liquidity_monitor
        return get_liquidity_monitor()
    except (ImportError, ModuleNotFoundError):
        return None


def _get_position_sizer():
    try:
        from merid.event_venues.kalshi.position_sizer import get_position_sizer
        return get_position_sizer()
    except (ImportError, ModuleNotFoundError):
        return None


# ── Market browsing ──────────────────────────────────────────────────────

@router.get("/markets")
async def list_markets(
    category: Optional[str] = Query(None, description="Filter by category (crypto, politics, sports, culture, climate, economics, mentions, companies, financials, tech, science)"),
    asset: Optional[str] = Query(None, description="Filter by asset (BTC, ETH, CPI, etc.)"),
    timeframe: Optional[str] = Query(None, description="Filter by timeframe (15m, 1h, daily, etc.)"),
    search: Optional[str] = Query(None, description="Keyword search across question/ticker"),
    sort: Optional[str] = Query(None, description="Sort key: volume|expiry|trending"),
    live: Optional[bool] = Query(None, description="If true, return only active markets sorted by soonest expiry (live feed)"),
    limit: int = Query(100, ge=1, le=500),
) -> Dict[str, Any]:
    """Browse cataloged Kalshi markets with filters.

    Supports all Kalshi categories: crypto, politics, sports, culture, climate,
    economics, mentions, companies, financials, tech, science.
    Pass live=true for the 24/7 live events feed (active markets, soonest expiry first).
    Pass sort=trending for highest-volume markets across all categories.
    """
    # Try old catalog first
    catalog = _get_catalog()
    if catalog:
        try:
            # Start with the broadest matching set then narrow down
            if category:
                markets = catalog.get_markets_by_category(category, timeframe=timeframe, asset=asset)
            elif asset:
                markets = catalog.get_markets_by_asset(asset, timeframe=timeframe)
            elif timeframe:
                markets = catalog.get_markets_by_timeframe(timeframe)
            else:
                markets = catalog.get_all_markets()

            # Live feed: only active markets
            if live:
                markets = [m for m in markets if m.market.active]

            # Keyword search: filter on question text and ticker
            if search:
                q = search.lower()
                markets = [
                    m for m in markets
                    if q in (m.market.question or "").lower()
                    or q in (m.market.market_id or "").lower()
                    or q in (m.asset or "").lower()
                ]

            # Server-side sort
            if sort in ("volume", "trending"):
                markets = sorted(markets, key=lambda m: float(m.market.volume) if m.market.volume else 0, reverse=True)
            elif sort == "expiry" or live:
                # Live feed always sorted by soonest expiry for 24/7 real-time feel
                markets = sorted(markets, key=lambda m: m.minutes_to_expiry if m.minutes_to_expiry is not None else float("inf"))

            markets = markets[:limit]
            return {
                "count": len(markets),
                "markets": [
                    {
                        "ticker": m.market.market_id,
                        "question": m.market.question,
                        "category": m.category,
                        "asset": m.asset,
                        "timeframe": m.timeframe,
                        "market_type": m.market_type,
                        "active": m.market.active,
                        "volume": float(m.market.volume) if m.market.volume else 0,
                        "expires_at": m.expires_at.isoformat() if m.expires_at else None,
                        "minutes_to_expiry": round(m.minutes_to_expiry, 1) if m.minutes_to_expiry else None,
                        "outcomes": [
                            {
                                "id": o.outcome_id,
                                "name": o.outcome_name,
                                "price": float(o.price),
                                "bid": float(o.best_bid) if o.best_bid else None,
                                "ask": float(o.best_ask) if o.best_ask else None,
                            }
                            for o in m.market.outcomes
                        ],
                    }
                    for m in markets
                ],
            }
        except Exception as exc:
            logger.warning(f"Catalog market list failed: {exc}")

    # Fallback: hit Kalshi public API directly
    import os, requests as req
    env = os.environ.get("KALSHI_ENV", "demo")
    base = "https://demo-api.kalshi.co" if env == "demo" else "https://api.kalshi.com"
    try:
        params: Dict[str, Any] = {"limit": limit, "status": "open"}
        if search:
            params["series_ticker"] = search
        if category:
            params["category"] = category
        # Trending = sort by volume descending
        if sort in ("volume", "trending"):
            params["sort_by"] = "volume_24h"
            params["sort_order"] = "desc"
        elif sort == "expiry" or live:
            params["sort_by"] = "close_time"
            params["sort_order"] = "asc"
        resp = req.get(f"{base}/trade-api/v2/markets", params=params, timeout=10)
        resp.raise_for_status()
        raw_markets = resp.json().get("markets", [])
        def _extract_outcomes(m: Dict[str, Any]) -> List[Dict[str, Any]]:
            """Build outcomes list from Kalshi public API market object."""
            yes_bid = m.get("yes_bid")  # cents
            yes_ask = m.get("yes_ask")  # cents
            yes_price = m.get("last_price", m.get("yes_ask", 50))  # cents
            return [
                {
                    "id": "yes",
                    "name": "Yes",
                    "price": yes_price / 100.0 if yes_price else 0.5,
                    "bid": yes_bid / 100.0 if yes_bid else None,
                    "ask": yes_ask / 100.0 if yes_ask else None,
                },
                {
                    "id": "no",
                    "name": "No",
                    "price": (100 - yes_price) / 100.0 if yes_price else 0.5,
                    "bid": (100 - yes_ask) / 100.0 if yes_ask else None,
                    "ask": (100 - yes_bid) / 100.0 if yes_bid else None,
                },
            ]

        return {
            "count": len(raw_markets),
            "markets": [
                {
                    "ticker": m.get("ticker", ""),
                    "question": m.get("title", m.get("subtitle", "")),
                    "category": m.get("category", None),
                    "asset": None,
                    "timeframe": None,
                    "market_type": m.get("market_type", "binary"),
                    "active": m.get("status") == "open",
                    "volume": m.get("volume", 0),
                    "expires_at": m.get("close_time", None),
                    "minutes_to_expiry": None,
                    "outcomes": _extract_outcomes(m),
                }
                for m in raw_markets
            ],
        }
    except Exception as exc:
        logger.warning(f"Public API market list failed: {exc}")
        return {"count": 0, "markets": [], "error": str(exc)}


@router.get("/markets/{ticker}")
async def get_market_detail(ticker: str) -> Dict[str, Any]:
    """Get detailed info for a single market."""
    # Try old catalog first
    catalog = _get_catalog()
    if catalog:
        try:
            cm = catalog.get_market(ticker)
            if cm:
                m = cm.market
                return {
                    "ticker": m.market_id,
                    "question": m.question,
                    "description": m.description,
                    "category": cm.category,
                    "asset": cm.asset,
                    "timeframe": cm.timeframe,
                    "market_type": cm.market_type,
                    "active": m.active,
                    "volume": float(m.volume) if m.volume else 0,
                    "liquidity": float(m.liquidity) if m.liquidity else 0,
                    "expires_at": cm.expires_at.isoformat() if cm.expires_at else None,
                    "minutes_to_expiry": round(cm.minutes_to_expiry, 1) if cm.minutes_to_expiry else None,
                    "outcomes": [
                        {
                            "id": o.outcome_id,
                            "name": o.outcome_name,
                            "price": float(o.price),
                            "probability": float(o.probability) if o.probability else None,
                            "bid": float(o.best_bid) if o.best_bid else None,
                            "ask": float(o.best_ask) if o.best_ask else None,
                        }
                        for o in m.outcomes
                    ],
                    "tags": m.tags,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                    "resolved": m.resolved,
                    "resolution": m.resolution,
                    "open_interest": int(float(m.open_interest)) if getattr(m, "open_interest", None) else 0,
                    "liquidity_score": round(float(m.liquidity) / 1000.0, 2) if getattr(m, "liquidity", None) else 0.0,
                    "last_trade_price": float(m.last_price) / 100.0 if getattr(m, "last_price", None) else None,
                    "last_trade_ts": m.last_trade_ts.isoformat() if getattr(m, "last_trade_ts", None) else None,
                }
        except Exception as exc:
            logger.warning(f"Catalog market detail failed: {exc}")

    # Fallback: merid_core REST client or public API
    rest = _get_rest_client()
    if rest:
        try:
            m = rest.get_market(ticker)
            market = m.get("market", m)
            last_price_cents = market.get("last_price", market.get("yes_ask"))
            return {
                "ticker": market.get("ticker", ticker),
                "question": market.get("title", ""),
                "description": market.get("subtitle", ""),
                "category": market.get("category", None),
                "asset": None,
                "timeframe": None,
                "market_type": market.get("market_type", "binary"),
                "active": market.get("status") == "open",
                "volume": market.get("volume", 0),
                "liquidity": 0,
                "expires_at": market.get("close_time", None),
                "minutes_to_expiry": None,
                "outcomes": [],
                "tags": [],
                "created_at": None,
                "resolved": market.get("result", "") != "",
                "resolution": market.get("result", None),
                "open_interest": market.get("open_interest", 0),
                "liquidity_score": 0.0,
                "last_trade_price": last_price_cents / 100.0 if last_price_cents else None,
                "last_trade_ts": market.get("last_trade_ts", None),
            }
        except Exception as exc:
            logger.warning(f"merid_core market detail failed: {exc}")

    raise HTTPException(status_code=404, detail=f"Market {ticker} not found")


# ── Orderbook ─────────────────────────────────────────────────────────────

@router.get("/markets/{ticker}/orderbook")
async def get_orderbook(ticker: str) -> Dict[str, Any]:
    """Get normalized yes/no orderbook ladders for a market.

    Returns shape expected by KalshiOrderbookPanel:
      { ticker, yes_bids, yes_asks, no_bids, no_asks, spread_cents, midpoint }
    where each level is { price: float, quantity: int }.
    """
    def _to_levels(raw: List) -> List[Dict[str, Any]]:
        """Convert [[price_cents, qty], ...] or [[price_frac, qty], ...] to level dicts."""
        levels = []
        for item in raw:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                p, q = item[0], item[1]
                # Normalise: Kalshi REST returns cents (1-99), old client returns fractions
                price = p / 100.0 if p > 1 else float(p)
                levels.append({"price": round(price, 4), "quantity": int(q)})
        return levels

    # Try old venue client first
    client = _get_client()
    if client:
        try:
            await client.connect()
            ob = await client.get_orderbook(ticker)
            await client.close()
            if ob:
                yes_bids = [{"price": round(float(p), 4), "quantity": int(s)} for p, s in (ob.bids or [])]
                yes_asks = [{"price": round(float(p), 4), "quantity": int(s)} for p, s in (ob.asks or [])]
                spread = float(ob.spread) if ob.spread else None
                midpoint = float(ob.midpoint) if ob.midpoint else None
                spread_cents = round(spread * 100, 1) if spread is not None else None
                return {
                    "ticker": ticker,
                    "yes_bids": yes_bids,
                    "yes_asks": yes_asks,
                    "no_bids": [],
                    "no_asks": [],
                    "spread_cents": spread_cents,
                    "midpoint": midpoint,
                }
        except Exception as exc:
            logger.warning(f"Old client orderbook failed: {exc}")

    # Fallback: merid_core REST client
    rest = _get_rest_client()
    if rest:
        try:
            ob = rest.get_orderbook(ticker)
            orderbook = ob.get("orderbook", ob)
            raw_yes = orderbook.get("yes", [])  # [[price_cents, qty], ...]
            raw_no  = orderbook.get("no", [])

            yes_bids = _to_levels(raw_yes)
            no_bids  = _to_levels(raw_no)

            # yes_asks = implied from no_bids (no bid at p → yes ask at 1-p)
            yes_asks = [{"price": round(1.0 - l["price"], 4), "quantity": l["quantity"]} for l in no_bids]
            no_asks  = [{"price": round(1.0 - l["price"], 4), "quantity": l["quantity"]} for l in yes_bids]

            best_bid = yes_bids[0]["price"] if yes_bids else None
            best_ask = yes_asks[0]["price"] if yes_asks else None
            spread_cents = round((best_ask - best_bid) * 100, 1) if best_bid is not None and best_ask is not None else None
            midpoint = round((best_bid + best_ask) / 2, 4) if best_bid is not None and best_ask is not None else None

            return {
                "ticker": ticker,
                "yes_bids": yes_bids,
                "yes_asks": yes_asks,
                "no_bids": no_bids,
                "no_asks": no_asks,
                "spread_cents": spread_cents,
                "midpoint": midpoint,
            }
        except Exception as exc:
            logger.warning(f"merid_core orderbook failed: {exc}")
            return {"ticker": ticker, "yes_bids": [], "yes_asks": [], "no_bids": [], "no_asks": [], "spread_cents": None, "midpoint": None, "error": str(exc)}

    return {"ticker": ticker, "yes_bids": [], "yes_asks": [], "no_bids": [], "no_asks": [], "spread_cents": None, "midpoint": None, "error": "No Kalshi client configured"}


# ── Events ────────────────────────────────────────────────────────────────

@router.get("/events/{event_ticker}")
async def get_event(event_ticker: str) -> Dict[str, Any]:
    """Get all markets for a Kalshi event (series)."""
    catalog = _get_catalog()
    if catalog:
        try:
            markets = catalog.get_markets_by_event(event_ticker)
            return {
                "event_ticker": event_ticker,
                "market_count": len(markets),
                "markets": [
                    {
                        "ticker": m.market.market_id,
                        "question": m.market.question,
                        "category": m.category,
                        "asset": m.asset,
                        "volume": float(m.market.volume) if m.market.volume else 0,
                        "active": m.market.active,
                    }
                    for m in markets
                ],
            }
        except Exception as exc:
            logger.warning(f"Catalog event lookup failed: {exc}")

    return {"event_ticker": event_ticker, "market_count": 0, "markets": []}


# ── Catalog ──────────────────────────────────────────────────────────────

@router.get("/catalog")
async def catalog_summary() -> Dict[str, Any]:
    """Catalog summary: categories, assets, timeframes, counts."""
    catalog = _get_catalog()
    if catalog:
        try:
            return catalog.summary()
        except Exception as exc:
            logger.warning(f"Catalog summary failed: {exc}")
    return {"market_count": 0, "last_refresh": None, "refresh_count": 0, "categories": {}, "assets": {}, "timeframes": {}, "running": False}


@router.post("/catalog/refresh")
async def catalog_refresh() -> Dict[str, Any]:
    """Force a catalog refresh."""
    catalog = _get_catalog()
    if catalog:
        try:
            count = await catalog.refresh()
            return {"refreshed": True, "market_count": count}
        except Exception as exc:
            logger.warning(f"Catalog refresh failed: {exc}")
    return {"refreshed": False, "market_count": 0, "error": "Catalog not available"}


# ── Category trading config ──────────────────────────────────────────────
# Persisted to data/kalshi_categories.json; no merid_core dependency.

import json as _json
from pathlib import Path as _Path

_CATEGORIES_FILE = _Path(__file__).resolve().parent.parent.parent / "data" / "kalshi_categories.json"

_KNOWN_CATEGORIES = [
    "politics", "economics", "finance", "sports", "weather",
    "entertainment", "science", "technology", "health", "crypto",
]

_DEFAULT_CATEGORIES: Dict[str, str] = {cat: "read-only" for cat in _KNOWN_CATEGORIES}


def _load_categories() -> Dict[str, str]:
    try:
        if _CATEGORIES_FILE.exists():
            stored = _json.loads(_CATEGORIES_FILE.read_text())
            if isinstance(stored, dict):
                return {**_DEFAULT_CATEGORIES, **stored}
    except Exception:
        pass
    return dict(_DEFAULT_CATEGORIES)


def _save_categories(cats: Dict[str, str]) -> None:
    _CATEGORIES_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CATEGORIES_FILE.write_text(_json.dumps(cats))


@router.get("/categories")
async def get_categories() -> Dict[str, Any]:
    """Get per-category trading mode permissions.

    Returns shape expected by KillSwitchView:
      { categories: { <cat>: 'live'|'read-only'|'blocked' }, known: [<cat>, ...] }
    """
    cats = _load_categories()
    return {"categories": cats, "known": _KNOWN_CATEGORIES}


@router.put("/categories")
async def update_categories(body: Dict[str, Any]) -> Dict[str, Any]:
    """Update one or more category trading modes.

    Body: { <cat>: 'live'|'read-only'|'blocked', ... }
    """
    valid_modes = {"live", "read-only", "blocked"}
    cats = _load_categories()
    updated = []
    for cat, mode in body.items():
        if mode not in valid_modes:
            continue
        cats[cat] = mode
        updated.append(cat)
    _save_categories(cats)
    logger.info(f"categories_updated: {updated}")
    return {"categories": cats, "known": _KNOWN_CATEGORIES, "updated": updated}


# ── Account data ─────────────────────────────────────────────────────────

@router.get("/positions")
async def get_positions() -> Dict[str, Any]:
    """Get current Kalshi positions."""
    executor = _get_executor()
    if executor:
        try:
            positions = await executor.get_positions()
            return {
                "count": len(positions),
                "positions": [
                    {
                        "ticker": p.symbol,
                        "outcome": p.metadata.get("outcome", "yes"),
                        "size": float(p.size),
                        "avg_price": float(p.entry_price),
                        "unrealized_pnl": float(p.pnl),
                        "realized_pnl": 0.0,
                    }
                    for p in positions
                ],
            }
        except Exception as exc:
            logger.warning(f"Executor positions failed: {exc}")

    # Fallback: merid_core REST client
    rest = _get_rest_client()
    if rest:
        try:
            positions = rest.get_positions()
            return {
                "count": len(positions),
                "positions": [
                    {
                        "ticker": p.get("ticker", p.get("market_ticker", "")),
                        "outcome": p.get("side", "yes"),
                        "size": p.get("total_traded", p.get("position", 0)),
                        "avg_price": p.get("average_price", 0) / 100.0 if p.get("average_price") else 0,
                        "unrealized_pnl": p.get("market_exposure", 0) / 100.0 if p.get("market_exposure") else 0,
                        "realized_pnl": p.get("realized_pnl", 0) / 100.0 if p.get("realized_pnl") else 0,
                    }
                    for p in positions
                ],
            }
        except Exception as exc:
            logger.warning(f"merid_core positions failed: {exc}")
            return {"count": 0, "positions": [], "error": str(exc)}

    return {"count": 0, "positions": [], "error": "No Kalshi client configured"}


@router.get("/orders")
async def get_orders() -> Dict[str, Any]:
    """Get open Kalshi orders."""
    executor = _get_executor()
    if executor:
        try:
            raw = await executor.get_orders(status="resting")
            orders = [
                {
                    "order_id": o.get("order_id", ""),
                    "ticker": o.get("ticker", ""),
                    "side": o.get("side", ""),
                    "size": o.get("remaining_count", o.get("count", 0)),
                    "price": (o.get("yes_price") or o.get("no_price") or 0) / 100.0,
                    "filled": o.get("filled_count", 0),
                    "remaining": o.get("remaining_count", None),
                    "status": o.get("status", ""),
                    "created_at": o.get("created_time", None),
                }
                for o in raw
            ]
            return {"count": len(orders), "orders": orders}
        except Exception as exc:
            logger.warning(f"Executor orders failed: {exc}")

    # Fallback: merid_core REST client
    rest = _get_rest_client()
    if rest:
        try:
            orders = rest.get_orders(status="resting")
            return {
                "count": len(orders),
                "orders": [
                    {
                        "order_id": o.get("order_id", ""),
                        "ticker": o.get("ticker", ""),
                        "side": o.get("side", ""),
                        "size": o.get("remaining_count", o.get("count", 0)),
                        "price": (o.get("yes_price", o.get("no_price", 0))) / 100.0,
                        "filled": o.get("filled_count", 0),
                        "remaining": o.get("remaining_count", 0),
                        "status": o.get("status", ""),
                        "created_at": o.get("created_time", None),
                    }
                    for o in orders
                ],
            }
        except Exception as exc:
            logger.warning(f"merid_core orders failed: {exc}")
            return {"count": 0, "orders": [], "error": str(exc)}

    return {"count": 0, "orders": [], "error": "No Kalshi client configured"}


@router.get("/fills")
async def get_fills(limit: int = Query(50, ge=1, le=500)) -> Dict[str, Any]:
    """Get recent Kalshi fills/trades."""
    executor = _get_executor()
    if executor:
        try:
            raw = await executor.get_fills()
            fills = [
                {
                    "trade_id": f.get("trade_id", f.get("fill_id", "")),
                    "ticker": f.get("ticker", ""),
                    "order_id": f.get("order_id", ""),
                    "side": f.get("side", ""),
                    "size": f.get("count", 0),
                    "price": (f.get("yes_price") or f.get("no_price") or 0) / 100.0,
                    "fee": f.get("fee_paid", 0) / 100.0,
                    "timestamp": f.get("created_time", ""),
                }
                for f in raw[:limit]
            ]
            return {"count": len(fills), "fills": fills}
        except Exception as exc:
            logger.warning(f"Executor fills failed: {exc}")

    # Fallback: merid_core REST client (orders with status=filled)
    rest = _get_rest_client()
    if rest:
        try:
            orders = rest.get_orders(status="filled")
            fills = orders[:limit]
            return {
                "count": len(fills),
                "fills": [
                    {
                        "trade_id": f.get("order_id", ""),
                        "ticker": f.get("ticker", ""),
                        "order_id": f.get("order_id", ""),
                        "side": f.get("side", ""),
                        "size": f.get("filled_count", f.get("count", 0)),
                        "price": (f.get("yes_price", f.get("no_price", 0))) / 100.0,
                        "fee": 0,
                        "timestamp": f.get("updated_time", f.get("created_time", "")),
                    }
                    for f in fills
                ],
            }
        except Exception as exc:
            logger.warning(f"merid_core fills failed: {exc}")
            return {"count": 0, "fills": [], "error": str(exc)}

    return {"count": 0, "fills": [], "error": "No Kalshi client configured"}


@router.get("/balance")
async def get_balance() -> Dict[str, Any]:
    """Get Kalshi account balance."""
    executor = _get_executor()
    if executor:
        try:
            bal = await executor.get_balance()
            return {
                "usd": bal.get("usd_dollars", 0.0),
                "locked": bal.get("locked_dollars", 0.0),
                "available": bal.get("available_dollars", 0.0),
            }
        except Exception as exc:
            logger.warning(f"Executor balance failed: {exc}")

    # Fallback: merid_core REST client
    rest = _get_rest_client()
    if rest:
        try:
            bal = rest.get_balance()
            usd = bal.get("balance", 0) / 100.0  # Kalshi returns cents
            return {"usd": usd, "locked": 0, "available": usd}
        except Exception as exc:
            logger.warning(f"merid_core balance failed: {exc}")
            return {"usd": 0, "locked": 0, "available": 0, "error": str(exc)}

    return {"usd": 0, "locked": 0, "available": 0, "error": "No Kalshi client configured"}


# ── Order placement ──────────────────────────────────────────────────────

@router.post("/orders")
async def place_order(
    ticker: str,
    side: str,            # "yes" or "no"
    action: str,          # "buy" or "sell"
    count: int,
    price_cents: int,
    order_type: str = "limit",
    time_in_force: str = "gtc",
    mode: str = "paper",  # "paper" or "live"
) -> Dict[str, Any]:
    """Place a Kalshi order through MERID.

    Runs risk pre-check, then routes to KalshiVenueClient.
    In paper mode, returns a simulated fill without hitting Kalshi.
    """
    # Validate inputs
    if side not in ("yes", "no"):
        raise HTTPException(400, f"Invalid side: {side!r}, must be 'yes' or 'no'")
    if action not in ("buy", "sell"):
        raise HTTPException(400, f"Invalid action: {action!r}, must be 'buy' or 'sell'")
    if count <= 0:
        raise HTTPException(400, "count must be > 0")
    if not (1 <= price_cents <= 99):
        raise HTTPException(400, "price_cents must be 1-99")

    mode_value = mode.lower().strip()
    if mode_value not in ("mock", "paper", "live"):
        raise HTTPException(400, f"Invalid mode: {mode!r}, must be one of ['mock', 'paper', 'live']")

    # Kill switch hard gate — block live orders if trading is halted
    if mode_value == "live":
        try:
            from merid.risk.kill_switches import risk_controller
            if not risk_controller.can_trade():
                reason = risk_controller.get_kill_reason()
                raise HTTPException(403, f"Trading halted: {reason}")
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning(f"Kill switch check failed (proceeding cautiously): {exc}")

    # Risk pre-check (if risk manager available)
    risk = _get_risk()
    if risk:
        try:
            ok, reason = risk.check_order(ticker, None, count, price_cents)
            if not ok:
                return {"status": "rejected", "mode": mode_value, "reason": reason, "ticker": ticker}
        except Exception as exc:
            logger.warning(f"Risk check failed (proceeding): {exc}")

    # Try old order router first
    try:
        from merid.prediction.venue_gate import TradingMode
        from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async

        mode_map = {"mock": TradingMode.MOCK, "paper": TradingMode.PAPER, "live": TradingMode.LIVE}
        intent = OrderIntent(
            ticker=ticker, side=side, action=action, price_cents=price_cents,
            count=count, mode=mode_map[mode_value], order_type=order_type,
            time_in_force=time_in_force, source="api",
        )
        result = await route_order_async(intent)
        if result.status != "rejected" and risk:
            risk.record_order(None, count, price_cents)
        return {
            "status": result.status,
            "mode": getattr(result.mode, "value", str(result.mode)).lower(),
            "ticker": ticker, "side": side, "action": action,
            "price_cents": price_cents, "count": count,
            "fill": result.fill, "reason": result.reason,
            "latency_ms": round(result.latency_ms or 0.0, 1),
        }
    except (ImportError, ModuleNotFoundError):
        pass
    except Exception as exc:
        logger.error(f"Old order router failed: {exc}")

    # Fallback: merid_core REST client (paper = simulated, live = real)
    import uuid, time as _time
    if mode_value == "paper":
        return {
            "status": "filled", "mode": "paper", "ticker": ticker,
            "side": side, "action": action, "price_cents": price_cents, "count": count,
            "fill": {"price": price_cents, "count": count, "simulated": True},
            "reason": None, "latency_ms": 0.0,
        }

    rest = _get_rest_client()
    if not rest:
        raise HTTPException(500, "No Kalshi client configured for live orders")
    try:
        t0 = _time.time()
        result = rest.create_order(
            ticker=ticker, side=side, action=action, quantity=count,
            price=price_cents, client_order_id=str(uuid.uuid4()),
            order_type=order_type, time_in_force=time_in_force,
        )
        latency = (_time.time() - t0) * 1000
        order = result.get("order", {})
        return {
            "status": order.get("status", "submitted"), "mode": "live",
            "ticker": ticker, "side": side, "action": action,
            "price_cents": price_cents, "count": count,
            "fill": order, "reason": None, "latency_ms": round(latency, 1),
        }
    except Exception as exc:
        logger.error(f"merid_core order placement failed: {exc}")
        raise HTTPException(500, f"Order placement failed: {exc}")


# ── Order management (cancel / amend) ────────────────────────────────────

@router.delete("/orders/{order_id}")
async def cancel_order(order_id: str) -> Dict[str, Any]:
    """Cancel a single resting order by Kalshi order ID."""
    executor = _get_executor()
    if executor:
        try:
            ok = await executor.cancel_order(order_id)
            return {"status": "cancelled" if ok else "failed", "order_id": order_id}
        except Exception as exc:
            logger.error(f"Executor cancel order {order_id} failed: {exc}")
    rest = _get_rest_client()
    if not rest:
        raise HTTPException(500, "No Kalshi client configured")
    try:
        result = rest.cancel_order(order_id)
        return {"status": "cancelled", "order_id": order_id, "result": result}
    except Exception as exc:
        logger.error(f"Cancel order {order_id} failed: {exc}")
        raise HTTPException(500, f"Cancel failed: {exc}")


@router.patch("/orders/{order_id}")
async def amend_order(
    order_id: str,
    price_cents: Optional[int] = None,
    count: Optional[int] = None,
) -> Dict[str, Any]:
    """Amend a resting order's price and/or quantity (cancel-replace)."""
    if price_cents is None and count is None:
        raise HTTPException(400, "Must provide price_cents and/or count to amend")
    # Amend is not on KalshiExecutor interface — use REST client directly
    rest = _get_rest_client()
    if not rest:
        raise HTTPException(500, "No Kalshi client configured")
    try:
        result = rest.amend_order(order_id, price=price_cents, quantity=count)
        return {"status": "amended", "order_id": order_id, "result": result}
    except Exception as exc:
        logger.error(f"Amend order {order_id} failed: {exc}")
        raise HTTPException(500, f"Amend failed: {exc}")


@router.delete("/orders")
async def batch_cancel_orders(
    ticker: Optional[str] = Query(None, description="Cancel only orders for this ticker; omit to cancel ALL"),
) -> Dict[str, Any]:
    """Cancel all resting orders, optionally scoped to a single market."""
    rest = _get_rest_client()
    if not rest:
        raise HTTPException(500, "No Kalshi client configured")
    try:
        result = rest.batch_cancel_orders(ticker=ticker)
        return {"status": "batch_cancelled", "ticker": ticker or "ALL", "result": result}
    except Exception as exc:
        logger.error(f"Batch cancel failed: {exc}")
        raise HTTPException(500, f"Batch cancel failed: {exc}")


# ── PnL ──────────────────────────────────────────────────────────────────

@router.get("/pnl")
async def get_pnl() -> Dict[str, Any]:
    """Portfolio PnL summary from risk manager."""
    risk = _get_risk()
    if risk:
        try:
            state = risk.state
            # Build per-category PnL from AgentPerformanceTracker
            category_pnl: Dict[str, float] = {}
            try:
                from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
                tracker = get_agent_performance_tracker()
                for agent_id, metrics in tracker._agent_metrics.items():
                    cat = agent_id.split("_")[0] if "_" in agent_id else agent_id
                    category_pnl[cat] = category_pnl.get(cat, 0.0) + float(metrics.total_pnl_usd)
            except Exception:
                pass
            return {
                "daily_pnl_usd": round(state.daily_pnl_usd, 2),
                "total_notional_usd": round(state.total_notional_usd, 2),
                "peak_equity_usd": round(state.peak_equity_usd, 2),
                "current_equity_usd": round(state.current_equity_usd, 2),
                "drawdown_pct": round(
                    (state.peak_equity_usd - state.current_equity_usd) / state.peak_equity_usd * 100
                    if state.peak_equity_usd > 0 else 0, 2,
                ),
                "category_pnl": {k: round(v, 2) for k, v in category_pnl.items()},
                "category_notional": {k: round(v, 2) for k, v in state.category_notional.items()},
            }
        except Exception as exc:
            logger.warning(f"PnL summary failed: {exc}")
    return {"daily_pnl_usd": 0, "total_notional_usd": 0, "peak_equity_usd": 0, "current_equity_usd": 0, "drawdown_pct": 0, "category_pnl": {}, "category_notional": {}}


# ── Risk ─────────────────────────────────────────────────────────────────

@router.get("/risk")
async def get_risk() -> Dict[str, Any]:
    """Risk manager status and limits, supplemented with live performance metrics."""
    base: Dict[str, Any] = {
        "kill_switch_active": False, "kill_switch_reason": None,
        "daily_pnl_usd": 0, "daily_realized_pnl_usd": 0, "daily_total_pnl_usd": 0,
        "total_unrealized_pnl_usd": 0, "total_notional_usd": 0,
        "drawdown_pct": 0, "daily_trades": 0, "daily_fees_usd": 0,
        "open_market_count": 0, "category_notional": {}, "category_contracts": {},
        "recent_breaches": [], "limits": {},
        "win_rate_pct": 0, "profit_factor": 0, "sharpe_ratio": 0,
        "sortino_ratio": 0, "calmar_ratio": 0,
    }
    risk = _get_risk()
    if risk:
        try:
            base.update(risk.summary())
        except Exception as exc:
            logger.warning(f"Risk summary failed: {exc}")

    # Supplement always-zero perf metrics from AgentPerformanceTracker
    if base.get("win_rate_pct", 0) == 0 or base.get("daily_trades", 0) == 0:
        try:
            from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
            tracker = get_agent_performance_tracker()
            sys_summary = tracker.get_system_summary()
            if base.get("win_rate_pct", 0) == 0:
                base["win_rate_pct"] = round(sys_summary.get("system_win_rate", 0) * 100, 1)
            if base.get("daily_trades", 0) == 0:
                base["daily_trades"] = sys_summary.get("total_closes", 0)
            top = tracker.get_top_agents(metric="sharpe_ratio", limit=1)
            if top:
                if base.get("sharpe_ratio", 0) == 0:
                    base["sharpe_ratio"] = round(top[0].get("sharpe_ratio", 0), 2)
                if base.get("profit_factor", 0) == 0:
                    re = top[0].get("avg_realized_edge", 0)
                    pe = max(top[0].get("avg_predicted_edge", 0.001), 0.001)
                    base["profit_factor"] = round(re / pe, 2)
        except Exception:
            pass

    return base


@router.post("/kill-switch")
async def toggle_kill_switch(activate: bool = True) -> Dict[str, Any]:
    """Activate or reset the Kalshi kill switch."""
    risk = _get_risk()
    if not risk:
        return {"kill_switch": False, "action": "unavailable", "error": "Risk manager not available"}
    if activate:
        risk._activate_kill_switch("Manual operator activation")
        return {"kill_switch": True, "action": "activated"}
    else:
        risk.reset_kill_switch()
        return {"kill_switch": False, "action": "reset"}


# ── WebSocket bridge ─────────────────────────────────────────────────────

@router.get("/ws")
async def ws_status() -> Dict[str, Any]:
    """WebSocket bridge status."""
    bridge = _get_bridge()
    if bridge:
        try:
            return bridge.summary()
        except Exception as exc:
            logger.warning(f"WS bridge summary failed: {exc}")
    return {"running": False, "events_forwarded": 0, "subscribed_tickers": 0}


# ── Health ───────────────────────────────────────────────────────────────

@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """Comprehensive Kalshi integration health check.

    Verifies:
      - Catalog freshness
      - Risk manager state
      - WS bridge connectivity
      - REST client connectivity
      - Rate limit headroom
    """
    issues: List[str] = []

    # Catalog
    catalog_data = {"market_count": 0, "last_refresh": None, "categories": 0}
    catalog = _get_catalog()
    if catalog:
        try:
            cs = catalog.summary()
            catalog_data = {
                "market_count": int(cs.get("market_count", 0)),
                "last_refresh": cs.get("last_refresh"),
                "categories": len(cs.get("categories", {})),
            }
        except Exception:
            pass
    if catalog_data["market_count"] == 0:
        issues.append("catalog_empty")

    # Risk
    risk_data = {"kill_switch": False, "daily_pnl": 0, "drawdown_pct": 0}
    risk_summary: Dict[str, Any] = {}
    risk = _get_risk()
    if risk:
        try:
            risk_summary = risk.summary()
            risk_data = {
                "kill_switch": bool(risk_summary.get("kill_switch_active", False)),
                "daily_pnl": float(risk_summary.get("daily_pnl_usd", risk_summary.get("daily_total_pnl_usd", 0))),
                "drawdown_pct": float(risk_summary.get("drawdown_pct", 0)),
            }
        except Exception:
            pass
    if risk_data["kill_switch"]:
        issues.append("kill_switch_active")

    # WS bridge (optional - not required for healthy status)
    ws_data: Dict[str, Any] = {"running": False, "events_forwarded": 0, "subscribed_tickers": 0}
    bridge = _get_bridge()
    if bridge:
        try:
            ws_data = bridge.summary()
        except Exception:
            pass
    # WS not running is just informational, not an error
    # Real-time updates still work via HTTP polling

    # API connectivity check via executor (REQUIRED for healthy status)
    rest_ok = False
    executor = _get_executor()
    if executor:
        try:
            rest_ok = await executor.authenticate()
            if not rest_ok:
                issues.append("rest_auth_failed")
        except Exception as exc:
            logger.warning(f"Executor auth check failed: {exc}")
            issues.append("rest_auth_failed")
    else:
        # Fallback: merid_core REST client
        rest = _get_rest_client()
        if rest:
            try:
                rest.get_balance()
                rest_ok = True
            except Exception as exc:
                logger.warning(f"REST connectivity check failed: {exc}")
                issues.append("rest_auth_failed")
        else:
            issues.append("rest_not_configured")

    # Rate limits
    orders_this_minute = float(risk_summary.get("orders_this_minute", 0))
    orders_this_hour = float(risk_summary.get("orders_this_hour", 0))
    max_per_minute = 30
    max_per_hour = 300
    try:
        if risk:
            max_per_minute = risk.config.max_orders_per_minute
            max_per_hour = risk.config.max_orders_per_hour
    except Exception:
        pass
    if orders_this_minute >= max_per_minute * 0.8:
        issues.append("rate_limit_warning")

    # Overall status - REST is required, WS is optional
    if "kill_switch_active" in issues:
        status = "halted"
    elif not rest_ok:
        status = "disconnected"
    elif not issues or (len(issues) == 1 and "rate_limit_warning" in issues):
        status = "healthy"
    else:
        status = "degraded"

    return {
        "status": status,
        "issues": issues,
        "catalog": catalog_data,
        "risk": risk_data,
        "ws": ws_data,
        "rest_connected": rest_ok,
        "rate_limits": {
            "orders_this_minute": orders_this_minute,
            "max_per_minute": max_per_minute,
            "orders_this_hour": orders_this_hour,
            "max_per_hour": max_per_hour,
        },
    }


# ── CSV Export ────────────────────────────────────────────────────────────

@router.get("/export")
async def export_markets_csv(
    min_volume: float = Query(0, description="Minimum volume filter"),
    category: Optional[str] = Query(None, description="Category filter"),
) -> Any:
    """Export filtered markets as CSV.

    Returns a streaming CSV response with columns:
    ticker, title, category, asset, volume, yes_price, active
    """
    import csv
    import io
    from fastapi.responses import StreamingResponse

    catalog = _get_catalog()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["ticker", "title", "category", "asset", "volume", "yes_price", "active"])

    if catalog:
        try:
            markets = catalog.get_all_markets()
            if min_volume > 0:
                markets = [m for m in markets if (float(m.market.volume) if m.market.volume else 0) >= min_volume]
            if category:
                markets = [m for m in markets if m.category == category]
            markets = sorted(markets, key=lambda m: float(m.market.volume) if m.market.volume else 0, reverse=True)
            for m in markets:
                yes_price = ""
                if m.market.outcomes:
                    yes_price = float(m.market.outcomes[0].price)
                writer.writerow([m.market.market_id, m.market.question, m.category or "", m.asset or "", float(m.market.volume) if m.market.volume else 0, yes_price, m.market.active])
        except Exception as exc:
            logger.warning(f"CSV export failed: {exc}")

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=kalshi_markets.csv"},
    )


# ── Volume Monitor ────────────────────────────────────────────────────────

@router.get("/volume-changes")
async def volume_changes(
    series_ticker: Optional[str] = Query(None, description="Filter by series ticker"),
    min_delta: float = Query(0, description="Minimum volume change to include"),
) -> Dict[str, Any]:
    """Get recent volume changes across markets.

    Compares current catalog volumes against the volume monitor's
    last-known values and returns deltas.
    """
    monitor = _get_volume_monitor()
    if not monitor:
        return {"changes": [], "total_markets_tracked": 0, "last_poll": None, "error": "Volume monitor not available"}
    try:
        changes = monitor.get_changes(series_ticker=series_ticker, min_delta=min_delta)
        return {"changes": changes, "total_markets_tracked": monitor.tracked_count, "last_poll": monitor.last_poll_iso}
    except Exception as exc:
        return {"changes": [], "total_markets_tracked": 0, "last_poll": None, "error": str(exc)}


@router.get("/volume-history/{ticker}")
async def volume_history(
    ticker: str,
    limit: int = Query(100, ge=1, le=500, description="Max snapshots to return"),
) -> Dict[str, Any]:
    """Chart-ready time-series volume data for a single market.

    Returns snapshots with ts, volume, delta — most recent first.
    """
    monitor = _get_volume_monitor()
    if not monitor:
        return {"ticker": ticker, "points": 0, "history": [], "error": "Volume monitor not available"}
    try:
        history = monitor.get_history(ticker, limit=limit)
        return {"ticker": ticker, "points": len(history), "history": history}
    except Exception as exc:
        return {"ticker": ticker, "points": 0, "history": [], "error": str(exc)}


@router.get("/volume-history/{ticker}/smoothed")
async def volume_history_smoothed(
    ticker: str,
    limit: int = Query(100, ge=1, le=500, description="Max snapshots to return"),
    process_var: float = Query(1.0, description="Kalman process noise variance"),
    meas_var: float = Query(10.0, description="Kalman measurement noise variance"),
) -> Dict[str, Any]:
    """Kalman-smoothed volume time-series for charting.

    Returns raw + smoothed volume per snapshot (most recent first).
    """
    monitor = _get_volume_monitor()
    if not monitor:
        return {"ticker": ticker, "points": 0, "filter": "kalman_1d", "history": [], "error": "Volume monitor not available"}
    try:
        history = monitor.get_smoothed_history(ticker, limit=limit, process_var=process_var, meas_var=meas_var)
        # Frontend reads data.smoothed — return under both keys for compatibility
        return {"ticker": ticker, "points": len(history), "filter": "kalman_1d", "process_var": process_var, "meas_var": meas_var, "smoothed": history, "history": history}
    except Exception as exc:
        return {"ticker": ticker, "points": 0, "filter": "kalman_1d", "smoothed": [], "history": [], "error": str(exc)}


@router.get("/volume-anomalies")
async def volume_anomalies(
    z_threshold: float = Query(3.0, description="Minimum z-score to flag"),
    min_window: int = Query(5, ge=2, description="Minimum history points for scoring"),
) -> Dict[str, Any]:
    """Detect volume anomalies using rolling z-score.

    Returns markets where the latest volume reading deviates from
    the rolling mean by more than ``z_threshold`` standard deviations.
    """
    monitor = _get_volume_monitor()
    if not monitor:
        return {"anomalies": [], "count": 0, "z_threshold": z_threshold, "tracked_markets": 0, "error": "Volume monitor not available"}
    try:
        anomalies = monitor.detect_anomalies(z_threshold=z_threshold, min_window=min_window)
        return {"anomalies": anomalies, "count": len(anomalies), "z_threshold": z_threshold, "tracked_markets": monitor.tracked_count}
    except Exception as exc:
        return {"anomalies": [], "count": 0, "z_threshold": z_threshold, "tracked_markets": 0, "error": str(exc)}


@router.get("/volume-alerts")
async def volume_alerts_endpoint(
    limit: int = Query(50, ge=1, le=200, description="Max alerts to return"),
) -> Dict[str, Any]:
    """Recent volume alerts fired by the monitor."""
    monitor = _get_volume_monitor()
    if not monitor:
        return {"alerts": [], "total_fired": 0, "poll_count": 0, "error": "Volume monitor not available"}
    try:
        return {"alerts": monitor.get_alerts(limit=limit), "total_fired": monitor.alert_count, "poll_count": monitor.poll_count}
    except Exception as exc:
        return {"alerts": [], "total_fired": 0, "poll_count": 0, "error": str(exc)}


# ── Liquidity Monitor ────────────────────────────────────────────────────

@router.get("/liquidity-alerts")
async def liquidity_alerts_endpoint(
    limit: int = Query(50, ge=1, le=200, description="Max alerts to return"),
) -> Dict[str, Any]:
    """Recent liquidity alerts (wide spread, thin book, spread spike, depth drop)."""
    monitor = _get_liquidity_monitor()
    if not monitor:
        return {"alerts": [], "summary": {}, "error": "Liquidity monitor not available"}
    try:
        return {"alerts": monitor.recent_alerts(limit=limit), "summary": monitor.summary()}
    except Exception as exc:
        return {"alerts": [], "summary": {}, "error": str(exc)}


@router.get("/liquidity-health/{market_id}")
async def liquidity_health_endpoint(market_id: str) -> Dict[str, Any]:
    """Current liquidity health snapshot for a single market.

    Returns shape expected by KalshiDashboardView:
      { ticker, spread_cents, book_depth, thin_book, wide_spread, health_score, recommendation }
    """
    monitor = _get_liquidity_monitor()
    if not monitor:
        return {
            "ticker": market_id,
            "spread_cents": None,
            "book_depth": 0,
            "thin_book": False,
            "wide_spread": False,
            "health_score": 0.5,
            "recommendation": "Liquidity monitor not available",
        }
    try:
        raw = monitor.market_health(market_id)
        # raw keys: market_id, status, spread, depth, avg_spread, avg_depth, mid, snapshots
        spread = raw.get("spread")  # fraction (0-1)
        depth = raw.get("depth", 0)
        status = raw.get("status", "no_data")

        spread_cents = round(spread * 100, 1) if spread is not None else None
        thin_book = depth < monitor.min_depth
        wide_spread = (spread is not None and spread > monitor.max_spread)

        # health_score: 1.0 = perfect, 0.0 = critical
        if status == "critical":
            health_score = 0.1
        elif status == "thin":
            health_score = 0.4
        elif status == "degraded":
            health_score = 0.5
        elif status == "no_data":
            health_score = 0.5
        else:
            health_score = 1.0

        if status == "critical":
            recommendation = "Avoid trading — wide spread and thin book"
        elif status == "thin":
            recommendation = "Use limit orders — book depth is low"
        elif status == "degraded":
            recommendation = "Expect slippage — spread is wide"
        elif status == "no_data":
            recommendation = "No orderbook data yet"
        else:
            recommendation = "Market is liquid"

        return {
            "ticker": market_id,
            "spread_cents": spread_cents,
            "book_depth": int(depth),
            "thin_book": thin_book,
            "wide_spread": wide_spread,
            "health_score": round(health_score, 2),
            "recommendation": recommendation,
        }
    except Exception as exc:
        return {
            "ticker": market_id,
            "spread_cents": None,
            "book_depth": 0,
            "thin_book": False,
            "wide_spread": False,
            "health_score": 0.5,
            "recommendation": str(exc),
        }


# ── Sizing Metrics ───────────────────────────────────────────────────────

@router.get("/sizing-metrics")
async def sizing_metrics_endpoint() -> Dict[str, Any]:
    """Current position sizing metrics: Kelly, vol-target, drawdown tier.

    Aggregates data from PositionSizer and KalshiRiskManager to give
    a unified view of the current sizing regime.
    """
    risk = _get_risk()
    risk_summary = risk.summary() if risk else {}

    # Compute drawdown tier from current drawdown
    dd_pct = risk_summary.get("drawdown_pct", 0)
    dd_thresholds = {"warning": 5.0, "downsize": 10.0, "halt": 15.0}
    if dd_pct >= dd_thresholds["halt"]:
        tier = "halt"
    elif dd_pct >= dd_thresholds["downsize"]:
        tier = "downsize"
    elif dd_pct >= dd_thresholds["warning"]:
        tier = "warning"
    else:
        tier = "normal"

    # Try to get sizer metrics
    try:
        sizer = _get_position_sizer()
        kelly_f = sizer.kelly_fraction
        effective = sizer.effective_fraction
        vol_scale = sizer.vol_scale
        target_vol = sizer.target_vol
        realized_vol = sizer.realized_vol
        atr_val = sizer.atr_value
        atr_frac = sizer.atr_fraction
        kelly_util = sizer.kelly_utilization_pct
    except Exception:
        # Fallback: derive from live risk state instead of paper hardcodes
        live_equity = risk_summary.get("current_equity_usd", 0)
        live_notional = risk_summary.get("total_notional_usd", 0)
        kelly_f = 0.25
        effective = 0.25
        vol_scale = 1.0
        target_vol = 0.02
        realized_vol = 0.02  # will be overwritten by PortfolioRiskAgent sync
        atr_val = 0.0
        atr_frac = 0.0
        kelly_util = (live_notional / live_equity * 100) if live_equity > 0 else 0.0

    # PF / WR / ratios — prefer live performance tracker over risk summary zeros
    trades_today = risk_summary.get("daily_trades", 0)
    win_rate = risk_summary.get("win_rate_pct", 0)
    pf = risk_summary.get("profit_factor", 0)
    sharpe = risk_summary.get("sharpe_ratio", 0)
    sortino = risk_summary.get("sortino_ratio", 0)
    calmar = risk_summary.get("calmar_ratio", 0)

    # Supplement with live performance tracker when risk summary has no data
    if win_rate == 0 or pf == 0:
        try:
            from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
            tracker = get_agent_performance_tracker()
            sys = tracker.get_system_summary()
            if win_rate == 0:
                win_rate = round(sys.get("system_win_rate", 0) * 100, 1)
            if trades_today == 0:
                trades_today = sys.get("total_closes", 0)
            top = tracker.get_top_agents(metric="sharpe_ratio", limit=1)
            if top and sharpe == 0:
                sharpe = top[0].get("sharpe_ratio", 0)
            if top and pf == 0:
                pf = top[0].get("avg_realized_edge", 0) / max(top[0].get("avg_predicted_edge", 1), 0.001)
        except Exception:
            pass

    return {
        "kelly_fraction": round(kelly_f, 4),
        "kelly_utilization_pct": round(kelly_util, 1),
        "vol_scale": round(vol_scale, 3),
        "target_vol": round(target_vol, 4),
        "realized_vol": round(realized_vol, 4),
        "atr_fraction": round(atr_frac, 4),
        "atr_value": round(atr_val, 2),
        "effective_fraction": round(effective, 5),
        "drawdown_tier": tier,
        "drawdown_pct": round(dd_pct, 2),
        "drawdown_thresholds": dd_thresholds,
        "sharpe_ratio": round(sharpe, 2),
        "sortino_ratio": round(sortino, 2),
        "calmar_ratio": round(calmar, 2),
        "win_rate_pct": round(win_rate, 1),
        "profit_factor": round(pf, 2),
        "trades_today": trades_today,
    }


# ── PnL History ──────────────────────────────────────────────────────────

@router.get("/pnl-history")
async def pnl_history_endpoint(
    limit: int = Query(100, ge=1, le=500, description="Max data points"),
) -> Dict[str, Any]:
    """Equity curve + PnL time series for the KalshiPnlChart component.

    Returns the most recent ``limit`` equity snapshots with:
      - equity: running account equity in USD
      - daily_pnl: PnL for that snapshot interval
      - cumulative_pnl: total PnL from session start
      - category: Kalshi market category (crypto / politics / economics)
      - realized_vol / target_vol: volatility metrics
    Also returns breach events for overlay markers.
    """
    risk = _get_risk()
    history = []
    risk_summary: Dict[str, Any] = {}
    if risk:
        try:
            history = risk.get_pnl_history(limit=limit)
            risk_summary = risk.summary()
        except (AttributeError, TypeError):
            pass

    # Build cumulative PnL from equity deltas if not already present
    points = []
    cumulative = 0.0
    prev_equity: Optional[float] = None
    for p in history:
        equity = round(float(p.get("equity", 0)), 2)
        if prev_equity is not None:
            daily_pnl = round(equity - prev_equity, 2)
        else:
            daily_pnl = round(float(p.get("daily_pnl", 0)), 2)
        cumulative = round(cumulative + daily_pnl, 2)
        prev_equity = equity
        points.append({
            "ts": p.get("ts", ""),
            "equity": equity,
            "daily_pnl": p.get("daily_pnl", daily_pnl),
            "cumulative_pnl": p.get("cumulative_pnl", cumulative),
            "category": p.get("category", p.get("asset", "")),
            "realized_vol": round(float(p.get("realized_vol", 0)), 4),
            "target_vol": round(float(p.get("target_vol", 0.02)), 4),
        })

    # Breach events for chart overlay markers
    breaches = [
        {
            "ts": b.get("ts", ""),
            "check": b.get("check", ""),
            "reason": b.get("reason", ""),
        }
        for b in risk_summary.get("recent_breaches", [])
    ]

    return {"points": points, "breaches": breaches}


# ── Edge / EV Signals ────────────────────────────────────────────────────

@router.get("/edge")
async def edge_signals_endpoint(
    tickers: Optional[str] = Query(None, description="Comma-separated tickers to evaluate"),
) -> Dict[str, Any]:
    """Per-market edge/EV signals for card-level display.

    For each market returns:
      - implied_prob: mid price (market implied probability)
      - model_prob: our model's fair probability estimate
      - ev_cents: EV per contract in cents  ((model - implied) * 100)
      - edge_pct: edge as percentage of implied
      - confidence: 0-1 signal confidence (low/medium/high bucket)
      - sizing_tier: normal / reduced / boosted relative to baseline
    """
    catalog = _get_catalog()
    risk = _get_risk()
    risk_summary = risk.summary() if risk else {}

    # Determine which tickers to evaluate
    if tickers:
        ticker_list = [t.strip() for t in tickers.split(",") if t.strip()]
    elif catalog:
        try:
            all_markets = catalog.get_all_markets()
            ticker_list = [m.market.market_id for m in all_markets if m.market.active][:200]
        except Exception:
            ticker_list = []
    else:
        ticker_list = []

    # Get sizer for sizing tier context
    try:
        sizer = _get_position_sizer()
        base_kelly = sizer.kelly_fraction
        effective = sizer.effective_fraction
    except Exception:
        base_kelly = 0.10
        effective = 0.01

    dd_pct = risk_summary.get("drawdown_pct", 0)
    dd_thresholds = {"warning": 5.0, "downsize": 10.0, "halt": 15.0}

    signals: Dict[str, Any] = {}
    for ticker in ticker_list:
        cm = catalog.get_market(ticker) if catalog else None
        if not cm or not cm.market.outcomes:
            continue

        m = cm.market
        yes_outcome = m.outcomes[0] if m.outcomes else None
        if not yes_outcome:
            continue

        implied_prob = float(yes_outcome.price) if yes_outcome.price else 0.5
        bid = float(yes_outcome.best_bid) if yes_outcome.best_bid else None
        ask = float(yes_outcome.best_ask) if yes_outcome.best_ask else None

        # Model probability: try to get from prediction engine, fall back to heuristic
        model_prob = implied_prob  # default: no edge
        confidence = 0.0
        try:
            from merid.prediction.edge_model import get_edge_model
            edge_model = get_edge_model()
            result = edge_model.predict(ticker, cm.asset, cm.timeframe)
            if result:
                model_prob = result.get("probability", implied_prob)
                confidence = result.get("confidence", 0.0)
        except (ImportError, AttributeError, Exception):
            # No edge model available — use spread-based heuristic
            if bid is not None and ask is not None:
                spread = ask - bid
                # Tighter spread → slightly higher confidence in mid price
                confidence = max(0.0, min(1.0, 1.0 - spread * 10))
                # Simple mean-reversion heuristic: bias toward 0.5
                reversion_strength = 0.05
                model_prob = implied_prob + reversion_strength * (0.5 - implied_prob)
            else:
                confidence = 0.0
                model_prob = implied_prob

        ev_cents = round((model_prob - implied_prob) * 100, 1)
        edge_pct = round((model_prob - implied_prob) / max(implied_prob, 0.01) * 100, 1)

        # Confidence bucket
        if confidence >= 0.7:
            conf_bucket = "high"
        elif confidence >= 0.4:
            conf_bucket = "medium"
        else:
            conf_bucket = "low"

        # Sizing tier based on drawdown + asset volatility
        # NOTE: check halt (15%) before downsize (10%) — halt is the stricter threshold
        if dd_pct >= dd_thresholds["halt"]:
            sizing_tier = "halted"
        elif dd_pct >= dd_thresholds["downsize"]:
            sizing_tier = "reduced"
        elif abs(ev_cents) > 5 and confidence >= 0.5:
            sizing_tier = "boosted"
        else:
            sizing_tier = "normal"

        signals[ticker] = {
            "implied_prob": round(implied_prob, 4),
            "model_prob": round(model_prob, 4),
            "ev_cents": ev_cents,
            "edge_pct": edge_pct,
            "confidence": round(confidence, 3),
            "confidence_bucket": conf_bucket,
            "sizing_tier": sizing_tier,
            "bid": round(bid, 4) if bid is not None else None,
            "ask": round(ask, 4) if ask is not None else None,
        }

    return {
        "signals": signals,
        "count": len(signals),
        "kelly_fraction": round(base_kelly, 4),
        "effective_fraction": round(effective, 5),
        "drawdown_pct": round(dd_pct, 2),
    }


# ── Risk Events ─────────────────────────────────────────────────────────

@router.get("/risk/events")
async def risk_events_endpoint(
    limit: int = Query(50, ge=1, le=200, description="Max events to return"),
) -> Dict[str, Any]:
    """Live risk event stream for the dashboard risk feed.

    Generates events from current risk state: kill switch, drawdown tiers,
    rate limits, and any active breaches.
    """
    risk = _get_risk()
    summary = risk.summary() if risk else {}
    events: List[Dict[str, Any]] = []
    ts = ""  # Will be populated by frontend with fetch time

    # Kill switch event
    if summary.get("kill_switch_active"):
        events.append({
            "id": "kill-switch",
            "ts": ts,
            "severity": "critical",
            "category": "circuit_breaker",
            "title": f"Kill switch ACTIVE: {summary.get('kill_switch_reason', 'unknown')}",
            "detail": "All trading halted. Reset from portfolio Risk tab.",
        })

    # Drawdown tier events
    dd = summary.get("drawdown_pct", 0)
    if dd >= 10:
        events.append({
            "id": "dd-critical",
            "ts": ts,
            "severity": "critical",
            "category": "drawdown",
            "title": f"Drawdown at {dd:.1f}% — DOWNSIZE tier",
            "detail": "Position sizes automatically reduced. Halt at 15%.",
        })
    elif dd >= 5:
        events.append({
            "id": "dd-warning",
            "ts": ts,
            "severity": "warning",
            "category": "drawdown",
            "title": f"Drawdown at {dd:.1f}% — WARNING tier",
            "detail": "Approaching downsize threshold (10%). Monitor closely.",
        })

    # Rate limit proximity
    rate_min = summary.get("orders_this_minute", 0)
    if rate_min >= 25:
        events.append({
            "id": "rate-critical",
            "ts": ts,
            "severity": "critical",
            "category": "rate_limit",
            "title": f"Rate limit critical: {rate_min}/30 orders this minute",
        })
    elif rate_min >= 20:
        events.append({
            "id": "rate-warning",
            "ts": ts,
            "severity": "warning",
            "category": "rate_limit",
            "title": f"Rate limit approaching: {rate_min}/30 orders this minute",
        })

    # Daily loss cap check
    daily_pnl = summary.get("daily_pnl_usd", 0)
    max_loss = summary.get("limits", {}).get("max_daily_loss_usd", 50)
    if daily_pnl < 0 and abs(daily_pnl) >= max_loss * 0.8:
        events.append({
            "id": "loss-cap",
            "ts": ts,
            "severity": "critical" if abs(daily_pnl) >= max_loss else "warning",
            "category": "loss_cap",
            "title": f"Daily loss ${abs(daily_pnl):.2f} / ${max_loss:.2f} cap",
            "detail": "Approaching or exceeded daily loss limit.",
        })

    # Recent breaches
    for i, breach in enumerate(summary.get("recent_breaches", [])[:5]):
        events.append({
            "id": f"breach-{i}",
            "ts": breach.get("ts", ts),
            "severity": "warning",
            "category": "general",
            "title": f"Breach: {breach.get('check', 'unknown')}",
            "detail": breach.get("reason", ""),
        })

    # Push critical/warning events to WS subscribers
    for evt in events:
        if evt.get("severity") in ("critical", "warning"):
            try:
                from web.api.ws_trade_events import publish_risk_alert
                await publish_risk_alert(
                    title=evt.get("title", ""),
                    severity=evt["severity"],
                    category=evt.get("category", "general"),
                    detail=evt.get("detail"),
                    extra={"event_id": evt.get("id")},
                )
            except Exception:
                pass  # WS broadcast is best-effort

    return {"events": events[:limit]}


@router.post("/risk/downsize")
async def risk_downsize_endpoint(
    asset: Optional[str] = Query(None, description="Asset to downsize (BTC, ETH, SOL)"),
    factor: float = Query(0.5, ge=0.1, le=1.0, description="Reduction factor (0.5 = halve)"),
) -> Dict[str, Any]:
    """One-click position downsizing from risk feed.

    Reduces effective Kelly fraction for the specified asset by the given factor.
    """
    try:
        sizer = _get_position_sizer()
        old_fraction = sizer.effective_fraction
        # Apply reduction
        sizer.apply_manual_override(factor=factor, asset=asset)
        new_fraction = sizer.effective_fraction
        logger.info(f"Risk downsize: asset={asset} factor={factor} old={old_fraction:.4f} new={new_fraction:.4f}")
        return {
            "success": True,
            "asset": asset,
            "factor": factor,
            "old_effective": round(old_fraction, 5),
            "new_effective": round(new_fraction, 5),
        }
    except Exception as exc:
        logger.warning(f"Risk downsize failed: {exc}")
        return {"success": False, "error": str(exc)}


# ── AI Insights ──────────────────────────────────────────────────────────

@router.get("/risk/insights")
async def risk_insights_endpoint() -> Dict[str, Any]:
    """AI-generated risk insights from live risk state, agent performance, and swarm consensus."""
    import datetime as _dt
    now_ts = _dt.datetime.utcnow().isoformat()

    risk = _get_risk()
    risk_summary = risk.summary() if risk else {}

    insights: List[Dict[str, Any]] = []
    iid = 0

    def _ins(**kw: Any) -> None:
        nonlocal iid
        iid += 1
        kw.setdefault("ts", now_ts)
        kw.setdefault("severity", "info")
        kw.setdefault("insight_type", "risk")
        insights.append({"id": f"insight-{iid}", **kw})

    # ── 1. Kill switch ────────────────────────────────────────────────────
    if risk_summary.get("kill_switch_active"):
        _ins(kind="warning", insight_type="risk", severity="critical",
             title="Kill switch is ACTIVE",
             body=f"Reason: {risk_summary.get('kill_switch_reason', 'unknown')}. All trading halted.",
             details="Reset via Kill Switch panel after investigating the trigger cause.")

    # ── 2. Drawdown ───────────────────────────────────────────────────────
    dd = float(risk_summary.get("drawdown_pct", 0))
    halt_pct = float(risk_summary.get("limits", {}).get("drawdown_halt_pct", 0.15)) * 100
    if dd >= halt_pct * 0.9:
        _ins(kind="warning", insight_type="risk", severity="critical",
             title=f"Drawdown near halt threshold ({dd:.1f}% / {halt_pct:.0f}%)",
             body="Auto-halt will trigger soon. Reduce positions immediately.",
             details=f"Current: {dd:.1f}%. Halt at: {halt_pct:.0f}%.",
             action_label="Pause agents")
    elif dd >= halt_pct * 0.6:
        _ins(kind="suggestion", insight_type="risk", severity="warning",
             title=f"Drawdown at {dd:.1f}% — approaching warning zone",
             body=f"Auto-downsizing activates at {halt_pct*0.67:.0f}%. Monitor closely.")

    # ── 3. Profit factor from AgentPerformanceTracker ─────────────────────
    try:
        from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
        tracker = get_agent_performance_tracker()
        sys_summary = tracker.get_system_summary()
        total_closes = sys_summary.get("total_closes", 0)
        win_rate = float(sys_summary.get("system_win_rate", 0))
        brier = tracker.compute_brier_score()

        if total_closes >= 10:
            # Win rate insight
            if win_rate < 0.45:
                _ins(kind="warning", insight_type="performance", severity="warning",
                     title=f"Win rate below 45% ({win_rate*100:.1f}%)",
                     body=f"System win rate is {win_rate*100:.1f}% over {total_closes} trades. Edge may be degrading.",
                     details="Consider reducing Kelly fraction or pausing underperforming agents.")
            elif win_rate >= 0.60:
                _ins(kind="fact", insight_type="performance", severity="info",
                     title=f"Strong win rate: {win_rate*100:.1f}%",
                     body=f"System is winning {win_rate*100:.1f}% of {total_closes} closed trades.")

            # Calibration (Brier score)
            if brier is not None and brier > 0.30:
                _ins(kind="suggestion", insight_type="performance", severity="warning",
                     title=f"Calibration degraded (Brier={brier:.3f})",
                     body="Agent confidence scores are poorly calibrated. Predicted edge diverging from realized.",
                     details="Brier score >0.25 = worse than random. Review agent signal quality.")

        # Top agent opportunity
        top = tracker.get_top_agents(metric="sharpe_ratio", limit=1)
        if top:
            t = top[0]
            if t.get("sharpe_ratio", 0) >= 1.5:
                _ins(kind="opportunity", insight_type="opportunity", severity="info",
                     title=f"Top agent Sharpe={t['sharpe_ratio']:.2f}: {t['agent_id']}",
                     body=f"WR={t.get('win_rate',0)*100:.1f}%, {t.get('total_closes',0)} trades. Consider increasing allocation.",
                     link_view="kalshi-grid")

        # Bottom agent drag
        bottom = tracker.get_top_agents(metric="total_pnl_usd", limit=5)
        if bottom:
            worst = min(bottom, key=lambda x: float(x.get("total_pnl_usd", 0)), default=None)
            if worst and float(worst.get("total_pnl_usd", 0)) < -20:
                _ins(kind="suggestion", insight_type="performance", severity="warning",
                     title=f"Agent {worst['agent_id']} losing ${abs(float(worst['total_pnl_usd'])):.2f}",
                     body="This agent is dragging overall PnL. Consider pausing or reducing its size factor.",
                     action_label="Pause agent")
    except Exception:
        pass

    # ── 4. PositionSizer vol overshoot ────────────────────────────────────
    try:
        from merid.event_venues.kalshi.position_sizer import get_position_sizer
        sizer = get_position_sizer()
        state = sizer._vol_state
        rvol = float(getattr(state, "realized_vol", 0))
        tvol = float(getattr(state, "target_vol", 0.15))
        if rvol > 0 and tvol > 0 and rvol > tvol * 1.5:
            _ins(kind="warning", insight_type="risk", severity="warning",
                 title=f"Realized vol {rvol*100:.1f}% exceeds target {tvol*100:.1f}%",
                 body="Vol scaling will auto-reduce position sizes. No action needed unless persistent.",
                 details=f"Realized: {rvol*100:.1f}%. Target: {tvol*100:.1f}%. Scale factor will be reduced.")
    except Exception:
        pass

    # ── 5. Consensus engine — high-confidence signals ─────────────────────
    try:
        from core.consensus_engine import get_consensus_engine
        engine = get_consensus_engine()
        high_conf = [
            v for v in engine.pending_votes.values()
            if v.confidence >= 0.80 and (v.agent_id.startswith("kalshi") or "kalshi" in v.proposal.lower())
        ]
        if high_conf:
            tickers = list({v.proposal.split(":")[0] for v in high_conf[:3]})
            _ins(kind="opportunity", insight_type="opportunity", severity="info",
                 title=f"{len(high_conf)} high-confidence swarm signal{'s' if len(high_conf) > 1 else ''}",
                 body=f"Tickers: {', '.join(tickers[:3])}. Confidence ≥80%. Swarm is aligned.",
                 link_view="kalshi-vol-dashboard")
    except Exception:
        pass

    # ── 6. Rate limit proximity ───────────────────────────────────────────
    rate_min = risk_summary.get("orders_this_minute", 0)
    max_min = risk_summary.get("limits", {}).get("max_orders_per_minute", 30)
    if isinstance(max_min, (int, float)) and max_min > 0 and rate_min >= max_min * 0.75:
        _ins(kind="warning", insight_type="risk", severity="warning",
             title="Rate limit approaching",
             body=f"Orders this minute: {rate_min}/{max_min}. Throttle agents to avoid 429 errors.")

    # ── 7. No activity ────────────────────────────────────────────────────
    if risk_summary.get("daily_trades", 0) == 0:
        _ins(kind="fact", insight_type="performance", severity="info",
             title="No trades executed today",
             body="Agents have not filled any orders yet. Check grid status, market conditions, and kill switch.",
             link_view="kalshi-grid")

    # ── 8. Liquidity opportunity from alerts ─────────────────────────────
    try:
        from merid.event_venues.kalshi.liquidity_monitor import get_liquidity_monitor
        lm = get_liquidity_monitor()
        good_markets = [
            m for m in (lm.get_liquid_markets() if hasattr(lm, "get_liquid_markets") else [])
            if m.get("spread_pct", 1) < 0.03
        ]
        if good_markets:
            _ins(kind="opportunity", insight_type="liquidity", severity="info",
                 title=f"{len(good_markets)} tight-spread markets available",
                 body=f"Top: {good_markets[0].get('ticker', '')} spread={good_markets[0].get('spread_pct', 0)*100:.1f}%",
                 link_view="kalshi-terminal")
    except Exception:
        pass

    return {"insights": insights}


# ── Publish Pipeline ─────────────────────────────────────────────────────

@router.get("/publish-pipeline")
async def publish_pipeline_status() -> Dict[str, Any]:
    """Status of the Kalshi → consensus → News/X publishing pipeline."""
    try:
        from merid.publishing.kalshi_insight_pipeline import get_insight_pipeline
        pipeline = get_insight_pipeline()
        pipeline_summary = pipeline.summary()
    except Exception as exc:
        pipeline_summary = {"running": False, "error": str(exc)}

    try:
        from merid.publishing.kalshi_news_agent import get_kalshi_news_agent
        news_agent = get_kalshi_news_agent()
        news_summary = news_agent.summary()
    except Exception as exc:
        news_summary = {"error": str(exc)}

    try:
        from agents.twitter_agent import get_twitter_agent
        tw = get_twitter_agent()
        twitter_status = {
            "enabled": tw.enabled,
            "recent_tweets": len(tw.recent_tweets),
            "last_post_time": tw.last_post_time,
        }
    except Exception:
        twitter_status = {"enabled": False}

    try:
        from agents.telegram_agent import get_telegram_agent
        tg = get_telegram_agent()
        telegram_status = {
            "enabled": tg.enabled,
            "recent_messages": len(tg.recent_messages),
        }
    except Exception:
        telegram_status = {"enabled": False}

    return {
        "pipeline": pipeline_summary,
        "news_agent": news_summary,
        "twitter": twitter_status,
        "telegram": telegram_status,
    }


@router.post("/publish-pipeline/trigger")
async def trigger_pipeline_insight(
    ticker: str,
    category: str = "Trending",
) -> Dict[str, Any]:
    """Manually trigger an insight for a specific ticker (operator tool)."""
    try:
        from merid.publishing.kalshi_insight_pipeline import (
            get_insight_pipeline, InsightObject, CATEGORY_TAGS
        )
        from datetime import datetime, timezone
        pipeline = get_insight_pipeline()
        insight = InsightObject(
            source="kalshi",
            category=category,
            ticker=ticker,
            question=f"Manual trigger: {ticker}",
            kalshi_prob=0.50,
            swarm_prob=0.50,
            swarm_confidence=0.60,
            change_24h=0.0,
            timestamp=datetime.now(timezone.utc).isoformat(),
            narrative="Manually triggered by operator.",
            action="update",
            market_url=f"https://kalshi.com/markets/{ticker}",
            volume=0,
            open_interest=0,
            tags=CATEGORY_TAGS.get(category, ["#Kalshi"]),
        )
        await pipeline._dispatch(insight)
        return {"ok": True, "ticker": ticker, "category": category}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Favorites / Watchlist ────────────────────────────────────────────────

_FAVORITES_FILE = _Path(__file__).resolve().parent.parent.parent / "data" / "kalshi_favorites.json"


def _load_favorites() -> List[str]:
    try:
        if _FAVORITES_FILE.exists():
            return _json.loads(_FAVORITES_FILE.read_text())
    except Exception:
        pass
    return []


def _save_favorites(tickers: List[str]) -> None:
    _FAVORITES_FILE.parent.mkdir(parents=True, exist_ok=True)
    _FAVORITES_FILE.write_text(_json.dumps(tickers))


@router.get("/favorites")
async def get_favorites() -> Dict[str, Any]:
    """Get the user's favorite/watchlist tickers."""
    favs = _load_favorites()
    return {"favorites": favs, "count": len(favs)}


@router.get("/news-signals")
async def get_news_signals(limit: int = Query(20, ge=1, le=100)) -> Dict[str, Any]:
    """Get recent news signals mapped to Kalshi market categories.

    Reads from the NewsMonitorAgent's recent posts and maps each news item
    to relevant Kalshi asset/category keywords so the dashboard can surface
    news-driven market opportunities.

    Returns:
        signals: list of { title, source, importance, published_at, assets, categories, url }
        count: number of signals
        monitor_running: whether the news monitor is active
    """
    # Asset and category keyword mappings
    _ASSET_KEYWORDS: Dict[str, List[str]] = {
        "BTC": ["bitcoin", "btc", "satoshi", "halving"],
        "ETH": ["ethereum", "eth", "ether", "vitalik"],
        "SOL": ["solana", "sol"],
        "XRP": ["ripple", "xrp"],
        "DOGE": ["dogecoin", "doge"],
        "FED": ["federal reserve", "fed rate", "fomc", "powell", "interest rate"],
        "CPI": ["inflation", "cpi", "consumer price", "pce"],
        "SPX": ["s&p 500", "spx", "stock market", "nasdaq", "dow jones"],
        "OIL": ["crude oil", "opec", "brent", "wti"],
        "GOLD": ["gold", "xau", "precious metal"],
    }
    _CATEGORY_KEYWORDS: Dict[str, List[str]] = {
        "crypto": ["bitcoin", "ethereum", "crypto", "blockchain", "defi", "nft", "web3"],
        "economics": ["inflation", "gdp", "fed", "interest rate", "recession", "unemployment"],
        "politics": ["election", "president", "congress", "senate", "vote", "policy"],
        "financials": ["stock", "equity", "earnings", "ipo", "market cap", "s&p"],
        "tech": ["ai", "artificial intelligence", "tech", "software", "hardware"],
        "climate": ["climate", "carbon", "energy", "oil", "renewable"],
    }

    try:
        from web.startup_agents import get_orchestrator_manager
        manager = get_orchestrator_manager()
        monitor = manager.news_monitor
        monitor_running = monitor is not None and monitor.running

        raw_items = monitor.get_recent_posts(limit=limit) if monitor else []

        signals = []
        for item in raw_items:
            title_lower = item.title.lower()

            # Map to assets
            matched_assets = [
                asset for asset, keywords in _ASSET_KEYWORDS.items()
                if any(kw in title_lower for kw in keywords)
            ]

            # Map to categories
            matched_categories = [
                cat for cat, keywords in _CATEGORY_KEYWORDS.items()
                if any(kw in title_lower for kw in keywords)
            ]

            signals.append({
                "title": item.title,
                "source": item.source,
                "url": item.url,
                "importance": item.importance,
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "posted_twitter": item.posted_twitter,
                "posted_telegram": item.posted_telegram,
                "assets": matched_assets,
                "categories": matched_categories,
            })

        return {
            "signals": signals,
            "count": len(signals),
            "monitor_running": monitor_running,
        }

    except Exception as exc:
        logger.warning(f"News signals unavailable: {exc}")
        return {
            "signals": [],
            "count": 0,
            "monitor_running": False,
            "error": str(exc),
        }


@router.get("/consensus-signals")
async def get_consensus_signals() -> Dict[str, Any]:
    """Get current Kalshi market consensus signals from the agent grid.

    Reads pending votes from the ConsensusEngine that originated from Kalshi
    trading agents (venue='kalshi') and aggregates them per ticker.

    Returns:
        signals: list of { ticker, direction, confidence, vote_count, agents }
        pending_votes: total pending votes in engine
        consensus_rate: historical consensus success rate
    """
    try:
        from core.consensus_engine import get_consensus_engine
        engine = get_consensus_engine()

        # Aggregate votes by ticker (from Kalshi agents only)
        ticker_votes: Dict[str, List[Dict]] = {}
        for vote in engine.pending_votes.values():
            # Only include Kalshi-sourced votes (agent_id starts with "kalshi-")
            if not (vote.agent_id.startswith("kalshi") or "kalshi" in vote.proposal.lower()):
                continue
            ticker = vote.proposal.split(":")[0] if ":" in vote.proposal else vote.proposal
            if ticker not in ticker_votes:
                ticker_votes[ticker] = []
            ticker_votes[ticker].append({
                "agent_id": vote.agent_id,
                "signal": vote.signal,
                "confidence": vote.confidence,
                "weight": vote.weight,
            })

        # Build per-ticker consensus summary
        signals = []
        for ticker, votes in ticker_votes.items():
            total_weight = sum(v["weight"] for v in votes)
            bull_weight = sum(v["weight"] for v in votes if v["signal"] == "bullish")
            bear_weight = sum(v["weight"] for v in votes if v["signal"] == "bearish")
            direction = "bullish" if bull_weight > bear_weight else "bearish" if bear_weight > bull_weight else "neutral"
            avg_conf = sum(v["confidence"] for v in votes) / len(votes) if votes else 0.0
            signals.append({
                "ticker": ticker,
                "direction": direction,
                "confidence": round(avg_conf, 3),
                "vote_count": len(votes),
                "bull_weight": round(bull_weight, 3),
                "bear_weight": round(bear_weight, 3),
                "agents": [v["agent_id"] for v in votes],
            })

        # Sort by confidence descending
        signals.sort(key=lambda s: s["confidence"], reverse=True)

        # Get consensus rate from logger
        metrics = engine.consensus_logger.get_metrics()
        total = metrics.get("total_rounds", 0)
        successful = metrics.get("successful", 0)
        consensus_rate = round(successful / total, 3) if total > 0 else 0.0

        return {
            "signals": signals,
            "count": len(signals),
            "pending_votes": len(engine.pending_votes),
            "consensus_rate": consensus_rate,
            "engine_running": engine.running,
        }
    except Exception as exc:
        logger.warning(f"Consensus signals unavailable: {exc}")
        return {
            "signals": [],
            "count": 0,
            "pending_votes": 0,
            "consensus_rate": 0.0,
            "engine_running": False,
            "error": str(exc),
        }


@router.put("/favorites")
async def set_favorites(
    body: Dict[str, Any],
) -> Dict[str, Any]:
    """Replace the favorites list with the provided tickers."""
    tickers = body.get("favorites", [])
    if not isinstance(tickers, list):
        return {"error": "favorites must be a list of ticker strings"}
    clean = [str(t) for t in tickers if isinstance(t, str)]
    _save_favorites(clean)
    return {"favorites": clean, "count": len(clean)}


@router.post("/favorites/toggle")
async def toggle_favorite(
    ticker: str = Query(..., description="Ticker to add/remove"),
) -> Dict[str, Any]:
    """Toggle a single ticker in the favorites list."""
    favs = _load_favorites()
    if ticker in favs:
        favs.remove(ticker)
        action = "removed"
    else:
        favs.append(ticker)
        action = "added"
    _save_favorites(favs)
    return {"ticker": ticker, "action": action, "favorites": favs, "count": len(favs)}
