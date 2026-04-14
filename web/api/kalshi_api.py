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

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from utils.logger import get_logger

logger = get_logger("web.api.kalshi_api")

router = APIRouter(prefix="/api/v1/kalshi", tags=["kalshi"])


# ── Shared helpers ────────────────────────────────────────────────────────

def _minutes_to_expiry_from_str(close_time_str: Optional[str]) -> Optional[float]:
    """Compute minutes until expiry from an ISO-8601 close_time string."""
    if not close_time_str:
        return None
    try:
        import datetime as _dt
        ct = _dt.datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
        delta = (ct - _dt.datetime.now(_dt.timezone.utc)).total_seconds() / 60.0
        return round(delta, 1) if delta > 0 else None
    except Exception:
        return None


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


# ── Ticker-prefix enrichment (shared with catalog) ───────────────────────

def _enrich_from_ticker(ticker: str) -> Dict[str, Any]:
    """Detect category/asset from Kalshi event_ticker prefix.

    Returns dict with keys: category, asset, timeframe.
    Used by fallback paths when catalog is unavailable.
    """
    try:
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        catalog = get_market_catalog()
        entry = catalog.get_market(ticker)
        if entry:
            return {"category": getattr(entry, "category", None), "asset": getattr(entry, "asset", None), "timeframe": None}
    except Exception as _e:
        logger.debug("_classify_ticker catalog lookup skipped for %s: %s", ticker, _e)
    # Inline prefix-based fallback
    _PREFIX_MAP = {
        "KXBTC": ("crypto", "BTC"), "KXETH": ("crypto", "ETH"), "KXSOL": ("crypto", "SOL"),
        "KXAVAX": ("crypto", "AVAX"), "INXD": ("equity", "SPX"), "NASDAQ": ("equity", "NDX"),
        "FED": ("macro", "FED"), "CPI": ("macro", "CPI"), "GDP": ("macro", "GDP"),
        "PRES": ("politics", "PRES"), "HOUSE": ("politics", "HOUSE"), "SENATE": ("politics", "SENATE"),
    }
    upper = ticker.upper()
    for prefix, (cat, asset) in _PREFIX_MAP.items():
        if upper.startswith(prefix):
            return {"category": cat, "asset": asset, "timeframe": None}
    return {"category": None, "asset": None, "timeframe": None}


# ── Market browsing ──────────────────────────────────────────────────────

@router.get("/markets",
    summary="List Kalshi Markets",
    description="Browse cataloged Kalshi markets with filters for category, asset, timeframe, and search keywords.",
    response_description="List of markets with volume, prices, and expiry info",
    tags=["kalshi", "markets"],
)
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
    base = os.getenv("KALSHI_API_BASE_URL", "https://api.elections.kalshi.com")
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
                    **_enrich_from_ticker(m.get("event_ticker", m.get("ticker", ""))),
                    "market_type": m.get("market_type", "binary"),
                    "active": m.get("status") == "open",
                    "volume": m.get("volume", 0),
                    "expires_at": m.get("close_time", None),
                    "minutes_to_expiry": _minutes_to_expiry_from_str(m.get("close_time")),
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
            enriched = _enrich_from_ticker(market.get("event_ticker", ticker))
            return {
                "ticker": market.get("ticker", ticker),
                "question": market.get("title", ""),
                "description": market.get("subtitle", ""),
                "category": enriched["category"],
                "asset": enriched["asset"],
                "timeframe": enriched["timeframe"],
                "market_type": market.get("market_type", "binary"),
                "active": market.get("status") == "open",
                "volume": market.get("volume", 0),
                "liquidity": 0,
                "expires_at": market.get("close_time", None),
                "outcomes": [],
                "tags": [],
                "created_at": None,
                "resolved": market.get("result", "") != "",
                "resolution": market.get("result", None),
                "open_interest": market.get("open_interest", 0),
                "liquidity_score": 0.0,
                "last_trade_price": last_price_cents / 100.0 if last_price_cents else None,
                "last_trade_ts": market.get("last_trade_ts", None),
                "minutes_to_expiry": _minutes_to_expiry_from_str(market.get("close_time")),
            }
        except Exception as exc:
            logger.warning(f"merid_core market detail failed: {exc}")

    raise HTTPException(status_code=404, detail=f"Market {ticker} not found")


# ── Orderbook ─────────────────────────────────────────────────────────────

from fastapi.responses import StreamingResponse
import asyncio

@router.get("/markets/{ticker}/orderbook/stream")
async def stream_orderbook(
    ticker: str,
    max_updates: int = Query(1000, ge=1, le=10000, description="Max updates before auto-close"),
    heartbeat_interval: int = Query(30, ge=5, le=300, description="Heartbeat interval in seconds"),
) -> StreamingResponse:
    """Stream real-time orderbook updates via Server-Sent Events.

    Uses Kalshi WebSocket under the hood to receive snapshot+delta updates
    and streams them to the client as SSE events.

    Events:
      - snapshot: Full orderbook state
      - delta: Incremental price level update
      - heartbeat: Periodic keepalive
      - error: Error message

    Query params:
      - max_updates: Auto-close after N updates (prevents runaway connections)
      - heartbeat_interval: Seconds between heartbeats

    Example:
      curl -N "http://localhost:8000/api/v1/kalshi/markets/KXBTC-24DEC-ABOVE-60000/orderbook/stream"
    """
    from merid.event_venues.kalshi.ws import KalshiWebSocket
    from merid.event_venues.kalshi.orderbook import LocalOrderbook

    async def event_generator():
        ws = KalshiWebSocket()
        ob = LocalOrderbook(ticker)
        update_count = 0
        last_heartbeat = asyncio.get_running_loop().time()

        try:
            await ws.connect()
            await ws.subscribe_orderbook(ticker)

            # Send initial connecting event
            yield f"event: connecting\ndata: {ticker}\n\n"

            async def message_handler(msg):
                nonlocal update_count, last_heartbeat
                msg_type = msg.get("type", "")

                if msg_type == "orderbook_snapshot":
                    ob.apply_snapshot(msg.get("data", {}))
                    update_count += 1
                    yield f"event: snapshot\ndata: {ob.to_dict()}\n\n"

                elif msg_type == "orderbook_delta":
                    ob.apply_delta(msg.get("data", {}))
                    update_count += 1
                    delta_data = {
                        "ticker": ticker,
                        "side": msg.get("data", {}).get("side"),
                        "price": msg.get("data", {}).get("price"),
                        "size_delta": msg.get("data", {}).get("size_delta"),
                        "best_bid": ob.get_best_bid(),
                        "best_ask": ob.get_best_ask(),
                        "spread_cents": ob.get_spread(),
                    }
                    yield f"event: delta\ndata: {delta_data}\n\n"

                elif msg_type == "trade":
                    # Trade updates affect book indirectly
                    trade_data = {
                        "ticker": msg.get("ticker", ""),
                        "price": msg.get("price"),
                        "count": msg.get("count"),
                        "side": msg.get("side"),
                    }
                    yield f"event: trade\ndata: {trade_data}\n\n"

                # Check heartbeat
                now = asyncio.get_running_loop().time()
                if now - last_heartbeat >= heartbeat_interval:
                    yield f"event: heartbeat\ndata: {{'ts': {now}, 'updates': {update_count}}}\n\n"
                    last_heartbeat = now

                # Auto-close after max updates
                if update_count >= max_updates:
                    yield f"event: closing\ndata: {{'reason': 'max_updates_reached', 'count': {update_count}}}\n\n"
                    return

            # Start listening
            try:
                await ws.listen(lambda msg: asyncio.create_task(message_handler(msg)))
            except Exception as e:
                yield f"event: error\ndata: {{'error': '{str(e)}'}}\n\n"

        except Exception as e:
            yield f"event: error\ndata: {{'error': 'Connection failed: {str(e)}'}}\n\n"
        finally:
            try:
                await ws.close()
            except Exception:
                pass
            yield f"event: closed\ndata: {{'ticker': '{ticker}'}}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.get("/order-groups/stream")
async def stream_order_group_updates(
    group_ids: Optional[str] = Query(None, description="Comma-separated group IDs to watch (None = all)"),
    max_updates: int = Query(1000, ge=1, le=10000, description="Max updates before auto-close"),
    heartbeat_interval: int = Query(30, ge=5, le=300, description="Heartbeat interval in seconds"),
) -> StreamingResponse:
    """Stream real-time order group updates via Server-Sent Events.

    Uses Kalshi WebSocket order_group_updates channel to receive lifecycle
    and usage updates for order groups.

    Events:
      - snapshot: Full group state (first message per group)
      - delta: Incremental update
      - triggered: Group triggered (auto-cancel occurred)
      - heartbeat: Periodic keepalive
      - error: Error message

    Query params:
      - group_ids: Filter to specific groups (comma-separated)
      - max_updates: Auto-close after N updates
      - heartbeat_interval: Seconds between heartbeats

    Example:
      curl -N "http://localhost:8000/api/v1/kalshi/order-groups/stream?group_ids=og-1,og-2"
    """
    from merid.event_venues.kalshi.ws import KalshiWebSocket

    async def event_generator():
        ws = KalshiWebSocket()
        update_count = 0
        last_heartbeat = asyncio.get_running_loop().time()

        # Parse watched groups
        watched_groups = set(group_ids.split(",")) if group_ids else None

        try:
            await ws.connect()

            # Subscribe to order_group_updates
            await ws.subscribe_order_group_updates()

            # Set watched groups filter if specified
            if watched_groups:
                ws.set_watched_groups(list(watched_groups))

            # Send initial connecting event
            yield f"event: connecting\ndata: {{'watched_groups': {list(watched_groups) if watched_groups else 'all'}}}\n\n"

            async def message_handler(msg):
                nonlocal update_count, last_heartbeat

                channel = msg.get("channel") or msg.get("type")
                if channel != "order_group_updates":
                    return

                data = msg.get("data", msg)
                group_id = data.get("order_group_id") or data.get("group_id")
                update_type = data.get("_update_type", "delta")
                status = data.get("status")

                update_count += 1

                # Build event data
                event_data = {
                    "order_group_id": group_id,
                    "status": status,
                    "contracts_limit": data.get("contracts_limit"),
                    "matched_contracts": data.get("matched_contracts"),
                    "used_contracts": data.get("used_contracts"),
                    "filled_cost": data.get("filled_cost"),
                    "remaining_cost": data.get("remaining_cost"),
                    "update_type": update_type,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }

                # Send appropriate event type
                if status == "triggered":
                    yield f"event: triggered\ndata: {event_data}\n\n"
                elif update_type == "snapshot":
                    yield f"event: snapshot\ndata: {event_data}\n\n"
                else:
                    yield f"event: delta\ndata: {event_data}\n\n"

                # Check heartbeat
                now = asyncio.get_running_loop().time()
                if now - last_heartbeat >= heartbeat_interval:
                    yield f"event: heartbeat\ndata: {{'ts': {now}, 'updates': {update_count}}}\n\n"
                    last_heartbeat = now

                # Auto-close after max updates
                if update_count >= max_updates:
                    yield f"event: closing\ndata: {{'reason': 'max_updates_reached', 'count': {update_count}}}\n\n"
                    return

            # Start listening
            try:
                await ws.listen(lambda msg: asyncio.create_task(message_handler(msg)))
            except Exception as e:
                yield f"event: error\ndata: {{'error': '{str(e)}'}}\n\n"

        except Exception as e:
            yield f"event: error\ndata: {{'error': 'Connection failed: {str(e)}'}}\n\n"
        finally:
            try:
                await ws.close()
            except Exception:
                pass
            yield f"event: closed\ndata: {{'updates_total': {update_count}}}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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


# ── Health ───────────────────────────────────────────────────────────────

@router.get("/health")
async def kalshi_health() -> Dict[str, Any]:
    """Kalshi system health — delegates to grid health for the full shape.

    Returns the shape expected by KalshiDashboardView:
      { status, issues, catalog, ws, rate_limits, risk, venue, session, metrics }
    where risk = { kill_switch, daily_pnl, drawdown_pct }.
    """
    try:
        from web.api.kalshi_grid_api import grid_health
        return await grid_health()
    except Exception as exc:
        logger.warning(f"Kalshi health delegation failed: {exc}")
        return {
            "status": "unknown",
            "issues": [str(exc)],
            "catalog": {"market_count": 0, "last_refresh": None, "categories": 0},
            "ws": {"running": False, "events_forwarded": 0, "subscribed_tickers": 0},
            "rate_limits": {"orders_this_minute": 0, "max_per_minute": 30, "orders_this_hour": 0, "max_per_hour": 600},
            "risk": {"kill_switch": False, "daily_pnl": 0.0, "drawdown_pct": 0.0},
            "venue": {},
            "session": {},
            "metrics": {},
        }


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
    except Exception as _e:
        logger.debug("_load_categories: file read failed, using defaults: %s", _e)
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
    """Get current Kalshi positions.

    Primary source: the reconciled ``KalshiPositionCache`` (updated in real-time
    from WebSocket fills and reconciliation cycles).  REST positions are fetched
    as a diagnostic supplement and discrepancies are logged.
    """
    # ── Primary: reconciled position cache ───────────────────────────────────
    reconciled_positions: List[Dict[str, Any]] = []
    cache_error: Optional[str] = None
    try:
        from merid.event_venues.kalshi.position_cache import get_position_cache
        cache = get_position_cache()
        for pos in cache.get_all_positions().values():
            reconciled_positions.append({
                "ticker": pos.market_id,
                "outcome": pos.side,
                "size": pos.contracts,
                "avg_price": pos.avg_price_cents / 100.0,
                "unrealized_pnl": float(pos.unrealized_pnl_usd),
                "realized_pnl": float(pos.realized_pnl_usd),
                "source": "reconciled",
            })
    except Exception as exc:
        cache_error = str(exc)
        logger.warning("Position cache unavailable: %s", exc)

    # ── Diagnostic: REST positions ────────────────────────────────────────────
    rest_positions: List[Dict[str, Any]] = []
    rest_error: Optional[str] = None

    executor = _get_executor()
    if executor:
        try:
            raw = await executor.get_positions()
            for p in raw:
                rest_positions.append({
                    "ticker": p.symbol,
                    "outcome": p.metadata.get("outcome", "yes"),
                    "size": float(p.size),
                    "avg_price": float(p.entry_price),
                    "unrealized_pnl": float(p.pnl),
                    "realized_pnl": 0.0,
                })
        except Exception as exc:
            rest_error = str(exc)
            logger.warning("Executor positions failed: %s", exc)
    else:
        rest = _get_rest_client()
        if rest:
            try:
                raw_rest = rest.get_positions()
                for p in raw_rest:
                    rest_positions.append({
                        "ticker": p.get("ticker", p.get("market_ticker", "")),
                        "outcome": p.get("side", "yes"),
                        "size": p.get("total_traded", p.get("position", 0)),
                        "avg_price": p.get("average_price", 0) / 100.0 if p.get("average_price") else 0,
                        "unrealized_pnl": p.get("market_exposure", 0) / 100.0 if p.get("market_exposure") else 0,
                        "realized_pnl": p.get("realized_pnl", 0) / 100.0 if p.get("realized_pnl") else 0,
                    })
            except Exception as exc:
                rest_error = str(exc)
                logger.warning("merid_core positions failed: %s", exc)

    # ── Discrepancy detection ─────────────────────────────────────────────────
    reconciled_count = len(reconciled_positions)
    rest_count = len(rest_positions)
    in_sync = reconciled_count == rest_count
    if not in_sync:
        reconciled_tickers = {p["ticker"] for p in reconciled_positions}
        rest_tickers = {p["ticker"] for p in rest_positions}
        logger.warning(
            "kalshi.position_discrepancy reconciled=%d rest=%d "
            "only_reconciled=%s only_rest=%s",
            reconciled_count, rest_count,
            list(reconciled_tickers - rest_tickers)[:5],
            list(rest_tickers - reconciled_tickers)[:5],
        )

    response: Dict[str, Any] = {
        "count": reconciled_count,
        "positions": reconciled_positions,
        "diagnostics": {
            "reconciled_count": reconciled_count,
            "rest_count": rest_count,
            "in_sync": in_sync,
            "raw_rest_positions": rest_positions,
        },
    }
    if cache_error:
        response["cache_error"] = cache_error
    if rest_error:
        response["diagnostics"]["rest_error"] = rest_error
    return response


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
                    "source": o.get("source", o.get("client_order_id", "")),
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
                        "source": o.get("source", o.get("client_order_id", "")),
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


# ── New Portfolio & Risk Endpoints ──────────────────────────────────────

@router.get("/portfolio/summary")
async def get_portfolio_summary() -> Dict[str, Any]:
    """Get comprehensive portfolio summary with balance + positions.

    Returns:
        balance, portfolio_value, and per-event exposure breakdown.
    """
    client = _get_client()
    if not client:
        raise HTTPException(status_code=503, detail="Kalshi client not configured")

    try:
        await client.connect()
        result = await client.get_portfolio_summary()
        await client.close()

        if not result.success:
            raise HTTPException(status_code=502, detail=str(result.error))

        data = result.data
        return {
            "balance_usd": float(data["balance"]),
            "portfolio_value_usd": float(data["portfolio_value"]),
            "by_event": {
                et: {
                    "exposure_usd": float(stats["exposure"]),
                    "realized_pnl_usd": float(stats["realized_pnl"]),
                    "fees_usd": float(stats["fees"]),
                }
                for et, stats in data["by_event"].items()
            },
            "latency_ms": result.latency_ms,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Portfolio summary failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/portfolio/risk")
async def get_portfolio_risk(
    nonzero: bool = Query(True, description="Only include positions with non-zero exposure"),
) -> Dict[str, Any]:
    """Calculate portfolio risk metrics (VaR-style exposure, PnL, fees).

    Returns:
        Total exposure, realized PnL, fees, and per-event breakdown.
    """
    client = _get_client()
    if not client:
        raise HTTPException(status_code=503, detail="Kalshi client not configured")

    try:
        await client.connect()
        filters = {"nonzero": "position"} if nonzero else {}
        result = await client.compute_portfolio_risk(filters)
        await client.close()

        if not result.success:
            raise HTTPException(status_code=502, detail=str(result.error))

        data = result.data
        return {
            "total_exposure_cents": float(data["total_exposure"]),
            "total_exposure_usd": float(data["total_exposure"]) / 100,
            "total_realized_pnl_usd": float(data["total_realized_pnl"]) / 100,
            "total_fees_usd": float(data["total_fees"]) / 100,
            "net_realized_pnl_usd": float(data["net_realized_pnl"]) / 100,
            "event_count": data["event_count"],
            "by_event": {
                et: {
                    "exposure_usd": float(risk["exposure"]) / 100,
                    "realized_pnl_usd": float(risk["realized_pnl"]) / 100,
                    "fees_usd": float(risk["fees"]) / 100,
                }
                for et, risk in data["by_event"].items()
            },
            "latency_ms": result.latency_ms,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Portfolio risk calculation failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/portfolio/var")
async def get_portfolio_var(
    alpha: float = Query(0.1, ge=0.01, le=1.0, description="VaR shock fraction (e.g., 0.1 = 10%)"),
) -> Dict[str, Any]:
    """Compute simple delta-style Value at Risk.

    Uses per-event exposure multiplied by shock fraction (alpha).
    This is a simplified VaR approximation.
    """
    client = _get_client()
    if not client:
        raise HTTPException(status_code=503, detail="Kalshi client not configured")

    try:
        await client.connect()
        result = await client.compute_var(alpha=alpha)
        await client.close()

        if not result.success:
            raise HTTPException(status_code=502, detail=str(result.error))

        data = result.data
        return {
            "alpha": data["alpha"],
            "portfolio_var_usd": float(data["portfolio_var_usd"]),
            "portfolio_var_cents": float(data["portfolio_var_cents"]),
            "var_by_event_usd": {
                et: float(var_cents) / 100
                for et, var_cents in data["var_by_event_cents"].items()
            },
            "latency_ms": result.latency_ms,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"VaR calculation failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/portfolio/pnl")
async def get_portfolio_pnl(
    tickers: Optional[List[str]] = Query(None, description="Filter by specific tickers"),
) -> Dict[str, Any]:
    """Calculate mark-to-market PnL using current market prices.

    Returns:
        Total PnL and per-market breakdown.
    """
    client = _get_client()
    if not client:
        raise HTTPException(status_code=503, detail="Kalshi client not configured")

    try:
        await client.connect()
        result = await client.compute_market_pnl(tickers=tickers)
        await client.close()

        if not result.success:
            raise HTTPException(status_code=502, detail=str(result.error))

        data = result.data
        return {
            "total_pnl_usd": float(data["total_pnl_usd"]),
            "total_pnl_cents": float(data["total_pnl_cents"]),
            "pnl_by_market_usd": {
                t: float(pnl) / 100
                for t, pnl in data["pnl_by_market_cents"].items()
            },
            "latency_ms": result.latency_ms,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"PnL calculation failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/portfolio/subaccounts")
async def get_subaccount_breakdown() -> Dict[str, Any]:
    """Get aggregated positions by subaccount.

    Returns:
        Per-subaccount exposure, cost, PnL, and fees.
    """
    client = _get_client()
    if not client:
        raise HTTPException(status_code=503, detail="Kalshi client not configured")

    try:
        await client.connect()
        result = await client.aggregate_positions_by_subaccount()
        await client.close()

        if not result.success:
            raise HTTPException(status_code=502, detail=str(result.error))

        data = result.data
        return {
            "subaccounts": {
                sub: {
                    "event_exposure_usd": float(stats["event_exposure"]) / 100,
                    "total_cost_usd": float(stats["total_cost"]) / 100,
                    "realized_pnl_usd": float(stats["realized_pnl"]) / 100,
                    "fees_paid_usd": float(stats["fees_paid"]) / 100,
                    "market_count": stats["market_count"],
                    "event_count": stats["event_count"],
                }
                for sub, stats in data.items()
            },
            "latency_ms": result.latency_ms,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Subaccount aggregation failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/portfolio/fills")
async def get_portfolio_fills(
    limit: int = Query(200, ge=1, le=500),
    since_ts: Optional[int] = Query(None, description="Minimum timestamp filter"),
) -> Dict[str, Any]:
    """Get paginated fills with optional time filter."""
    client = _get_client()
    if not client:
        raise HTTPException(status_code=503, detail="Kalshi client not configured")

    try:
        await client.connect()
        result = await client.get_fills(limit=limit, since_ts=since_ts)
        await client.close()

        if not result.success:
            raise HTTPException(status_code=502, detail=str(result.error))

        fills = result.data
        return {
            "count": len(fills),
            "fills": [
                {
                    "fill_id": f.get("fill_id", f.get("trade_id", "")),
                    "ticker": f.get("market_ticker", f.get("ticker", "")),
                    "side": f.get("side", ""),
                    "contracts": f.get("contracts", f.get("count", 0)),
                    "price_cents": f.get("price", 0),
                    "price_usd": f.get("price", 0) / 100.0,
                    "fee_usd": f.get("fee", 0) / 100.0,
                    "timestamp": f.get("created_at", f.get("timestamp", "")),
                }
                for f in fills
            ],
            "latency_ms": result.latency_ms,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Fills fetch failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/portfolio/history")
async def get_portfolio_history(
    limit: int = Query(200, ge=1, le=1000),
) -> Dict[str, Any]:
    """Get portfolio history with PnL aggregation.

    Returns:
        Aggregated realized PnL, fees, and net PnL.
    """
    client = _get_client()
    if not client:
        raise HTTPException(status_code=503, detail="Kalshi client not configured")

    try:
        await client.connect()
        result = await client.get_portfolio_history(limit=limit)
        await client.close()

        if not result.success:
            raise HTTPException(status_code=502, detail=str(result.error))

        data = result.data
        return {
            "entries_count": data["entries_count"],
            "realized_pnl_usd": float(data["realized_pnl"]) / 100,
            "fees_paid_usd": float(data["fees_paid"]) / 100,
            "net_pnl_usd": float(data["net_pnl"]) / 100,
            "latency_ms": result.latency_ms,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Portfolio history failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/client/metrics")
async def get_client_metrics() -> Dict[str, Any]:
    """Get Kalshi client internal metrics.

    Returns:
        Circuit breaker status, rate limiter state, and request stats.
    """
    client = _get_client()
    if not client:
        raise HTTPException(status_code=503, detail="Kalshi client not configured")

    try:
        circuit_status = client.get_circuit_status()

        # Use public rate limiter accessor if available, fall back gracefully
        if hasattr(client, 'get_rate_limiter_status'):
            rl_status = client.get_rate_limiter_status()
        elif hasattr(client, 'rate_limiter'):
            rl = client.rate_limiter
            rl_status = {
                "tier": getattr(rl, "tier", "unknown"),
                "read_tokens_available": getattr(rl, "read_tokens_available", 0),
                "write_tokens_available": getattr(rl, "write_tokens_available", 0),
                "read_rate": getattr(rl, "read_rate", 0),
                "write_rate": getattr(rl, "write_rate", 0),
            }
        else:
            rl = getattr(client, "_rate_limiter", None)
            rl_status = {
                "tier": getattr(rl, "tier", "unknown"),
                "read_tokens_available": getattr(rl, "read_tokens_available", 0),
                "write_tokens_available": getattr(rl, "write_tokens_available", 0),
                "read_rate": getattr(rl, "read_rate", 0),
                "write_rate": getattr(rl, "write_rate", 0),
            } if rl else {}

        import os as _os
        concurrency_limit = int(_os.getenv("KALSHI_MAX_CONCURRENT_REQUESTS", "10"))

        return {
            "circuit_breaker": circuit_status,
            "rate_limiter": rl_status,
            "concurrency_limit": concurrency_limit,
        }
    except Exception as exc:
        logger.error(f"Metrics fetch failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# ── Order placement ──────────────────────────────────────────────────────

def _get_default_order_mode() -> str:
    """Get the default order mode from settings."""
    try:
        from merid.settings import settings
        if settings.MERID_PM_LIVE_ENABLED and settings.MERID_PM_TRADING_MODE == "live":
            return "live"
        return settings.MERID_PM_TRADING_MODE or "paper"
    except Exception:
        return "paper"


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
    Defaults to paper mode if not specified.
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

    # Unified execution gate — block live orders when any safety check fails
    if mode_value == "live":
        try:
            from core.execution_gate import check_execution_gate
            gate = check_execution_gate()
            if gate.blocked:
                reasons = "; ".join(r.message for r in gate.reasons)
                raise HTTPException(403, f"Trading halted: {reasons}")
        except HTTPException:
            raise
        except Exception as exc:
            # Fall back to kill switch only if gate import fails
            try:
                from merid.risk.kill_switches import risk_controller
                if not risk_controller.can_trade():
                    reason = risk_controller.get_kill_reason()
                    raise HTTPException(403, f"Trading halted: {reason}")
            except HTTPException:
                raise
            except Exception:
                logger.warning(f"Execution gate + kill switch check failed (proceeding cautiously): {exc}")

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


@router.post("/orders/batch",
    summary="Batch Place Orders",
    description="Batch place up to 20 orders in a single API call. More efficient than individual orders and reduces rate limit pressure.",
    response_description="Batch order results with placed orders and latency",
    tags=["kalshi", "orders"],
)
async def batch_place_orders(
    orders: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Batch place up to 20 orders in a single API call.

    Each order dict must contain:
      - ticker: Market ticker (required)
      - side: "yes" or "no" (required)
      - action: "buy" or "sell" (default: "buy")
      - count: Number of contracts (required)
      - yes_price or no_price: Price in cents (required for limit orders)
      - type: "limit" or "market" (default: "limit")

    Optional fields:
      - time_in_force: "gtc", "ioc", or "fok" (default: "gtc")
      - subaccount: Subaccount number
      - post_only: bool
      - reduce_only: bool
      - client_order_id: Custom order ID
    """
    if not orders:
        raise HTTPException(400, "No orders provided")

    if len(orders) > 20:
        raise HTTPException(400, f"Max 20 orders per batch, received {len(orders)}")

    client = _get_client()
    if not client:
        raise HTTPException(503, "Kalshi client not configured")

    try:
        await client.connect()
        result = await client.batch_place_orders(order_specs=orders)
        await client.close()

        if not result.success:
            raise HTTPException(502, str(result.error))

        placed_orders = result.data
        return {
            "status": "success",
            "count": len(placed_orders),
            "orders": placed_orders,
            "latency_ms": result.latency_ms,
        }
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        logger.error(f"Batch place orders failed: {exc}")
        raise HTTPException(500, f"Batch place failed: {exc}")


@router.patch("/orders/{order_id}/amend")
async def amend_order_endpoint(
    order_id: str,
    yes_price: Optional[int] = None,
    no_price: Optional[int] = None,
    count: Optional[int] = None,
) -> Dict[str, Any]:
    """Amend a resting order's price and/or quantity.

    Uses Kalshi's amend endpoint: POST /portfolio/orders/{order_id}/amend
    Only resting orders can be amended.
    """
    if yes_price is None and no_price is None and count is None:
        raise HTTPException(400, "Must provide yes_price, no_price, or count to amend")

    client = _get_client()
    if not client:
        raise HTTPException(503, "Kalshi client not configured")

    try:
        await client.connect()
        result = await client.amend_order(
            order_id=order_id,
            yes_price=yes_price,
            no_price=no_price,
            new_count=count,
        )
        await client.close()

        if not result.success:
            raise HTTPException(502, str(result.error))

        return {
            "status": "amended",
            "order_id": order_id,
            "order": result.data,
            "latency_ms": result.latency_ms,
        }
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        logger.error(f"Amend order {order_id} failed: {exc}")
        raise HTTPException(500, f"Amend failed: {exc}")


@router.post("/orders/{order_id}/decrease")
async def decrease_order_endpoint(
    order_id: str,
    reduce_by: Optional[int] = None,
    reduce_to: Optional[int] = None,
) -> Dict[str, Any]:
    """Decrease a resting order's contract count.

    Uses Kalshi's decrease endpoint: POST /portfolio/orders/{order_id}/decrease
    Reduces contracts by reduce_by or to reduce_to (mutually exclusive).
    """
    if reduce_by is None and reduce_to is None:
        raise HTTPException(400, "Must provide reduce_by or reduce_to")
    if reduce_by is not None and reduce_to is not None:
        raise HTTPException(400, "Cannot specify both reduce_by and reduce_to - choose one")

    client = _get_client()
    if not client:
        raise HTTPException(503, "Kalshi client not configured")

    try:
        await client.connect()
        result = await client.decrease_order(
            order_id=order_id,
            reduce_by=reduce_by,
            reduce_to=reduce_to,
        )
        await client.close()

        if not result.success:
            raise HTTPException(502, str(result.error))

        return {
            "status": "decreased",
            "order_id": order_id,
            "order": result.data,
            "latency_ms": result.latency_ms,
        }
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        logger.error(f"Decrease order {order_id} failed: {exc}")
        raise HTTPException(500, f"Decrease failed: {exc}")


# ── Order Groups ─────────────────────────────────────────────────────────

@router.post("/order-groups")
async def create_order_group_endpoint(
    name: str,
    max_cost_cents: int,
) -> Dict[str, Any]:
    """Create an order group for aggregate risk management.

    Order groups allow setting aggregate limits and triggers across
    multiple orders. Assign orders via order_group_id field.
    """
    client = _get_client()
    if not client:
        raise HTTPException(503, "Kalshi client not configured")

    try:
        await client.connect()
        result = await client.create_order_group(
            name=name,
            max_cost_cents=max_cost_cents,
        )
        await client.close()

        if not result.success:
            raise HTTPException(502, str(result.error))

        return {
            "status": "created",
            "order_group_id": result.data,
            "name": name,
            "max_cost_cents": max_cost_cents,
            "latency_ms": result.latency_ms,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Create order group failed: {exc}")
        raise HTTPException(500, f"Create order group failed: {exc}")


@router.put("/order-groups/{group_id}/limit")
async def set_order_group_limit_endpoint(
    group_id: str,
    max_cost_cents: int,
) -> Dict[str, Any]:
    """Update the cost limit for an order group."""
    client = _get_client()
    if not client:
        raise HTTPException(503, "Kalshi client not configured")

    try:
        await client.connect()
        result = await client.set_order_group_limit(
            group_id=group_id,
            max_cost_cents=max_cost_cents,
        )
        await client.close()

        if not result.success:
            raise HTTPException(502, str(result.error))

        return {
            "status": "updated",
            "order_group_id": group_id,
            "max_cost_cents": max_cost_cents,
            "latency_ms": result.latency_ms,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Set order group limit failed: {exc}")
        raise HTTPException(500, f"Set order group limit failed: {exc}")


@router.put("/order-groups/{group_id}/trigger")
async def trigger_order_group_endpoint(
    group_id: str,
) -> Dict[str, Any]:
    """Trigger an order group (e.g., for OCO or conditional orders)."""
    client = _get_client()
    if not client:
        raise HTTPException(503, "Kalshi client not configured")

    try:
        await client.connect()
        result = await client.trigger_order_group(
            group_id=group_id,
        )
        await client.close()

        if not result.success:
            raise HTTPException(502, str(result.error))

        return {
            "status": "triggered",
            "order_group_id": group_id,
            "latency_ms": result.latency_ms,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Trigger order group failed: {exc}")
        raise HTTPException(500, f"Trigger order group failed: {exc}")


@router.get("/order-groups")
async def get_order_groups_endpoint(
    limit: int = Query(200, ge=1, le=1000, description="Max groups to return"),
) -> Dict[str, Any]:
    """List all order groups with pagination."""
    client = _get_client()
    if not client:
        raise HTTPException(503, "Kalshi client not configured")

    try:
        await client.connect()
        result = await client.get_order_groups(limit=limit)
        await client.close()

        if not result.success:
            raise HTTPException(502, str(result.error))

        groups = result.data or []
        return {
            "groups": groups,
            "count": len(groups),
            "latency_ms": result.latency_ms,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Get order groups failed: {exc}")
        raise HTTPException(500, f"Get order groups failed: {exc}")


@router.get("/order-groups/{group_id}")
async def get_order_group_endpoint(group_id: str) -> Dict[str, Any]:
    """Get a single order group by ID."""
    client = _get_client()
    if not client:
        raise HTTPException(503, "Kalshi client not configured")

    try:
        await client.connect()
        result = await client.get_order_group(group_id)
        await client.close()

        if not result.success:
            raise HTTPException(502, str(result.error))

        return {
            "group": result.data,
            "latency_ms": result.latency_ms,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Get order group {group_id} failed: {exc}")
        raise HTTPException(500, f"Get order group failed: {exc}")


@router.put("/order-groups/{group_id}/reset")
async def reset_order_group_endpoint(group_id: str) -> Dict[str, Any]:
    """Reset an order group (clear matched contracts counter)."""
    client = _get_client()
    if not client:
        raise HTTPException(503, "Kalshi client not configured")

    try:
        await client.connect()
        result = await client.reset_order_group_endpoint(group_id)
        await client.close()

        if not result.success:
            raise HTTPException(502, str(result.error))

        return {
            "status": "reset",
            "order_group_id": group_id,
            "latency_ms": result.latency_ms,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Reset order group {group_id} failed: {exc}")
        raise HTTPException(500, f"Reset order group failed: {exc}")


@router.delete("/order-groups/{group_id}")
async def delete_order_group_endpoint(group_id: str) -> Dict[str, Any]:
    """Delete an order group and cancel all its orders."""
    client = _get_client()
    if not client:
        raise HTTPException(503, "Kalshi client not configured")

    try:
        await client.connect()
        result = await client.delete_order_group_and_sync(group_id)
        await client.close()

        if result.get("error"):
            raise HTTPException(502, str(result["error"]))

        return {
            "status": "deleted" if result["deleted"] else "not_found",
            "order_group_id": group_id,
            "orders_remaining": len(result.get("orders", [])),
            "positions": len(result.get("positions", [])),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Delete order group {group_id} failed: {exc}")
        raise HTTPException(500, f"Delete order group failed: {exc}")


@router.get("/order-groups/dashboard")
async def get_order_groups_dashboard() -> Dict[str, Any]:
    """Get comprehensive order groups dashboard data.

    Returns aggregated status, usage statistics, and alerts for all order groups.
    Suitable for real-time monitoring UI.
    """
    client = _get_client()
    if not client:
        raise HTTPException(503, "Kalshi client not configured")

    try:
        await client.connect()

        # Fetch all order groups
        result = await client.get_order_groups(limit=200)
        if not result.success:
            raise HTTPException(502, str(result.error))

        groups = result.data or []

        # Aggregate statistics
        total_groups = len(groups)
        active_groups = 0
        triggered_groups = 0
        canceled_groups = 0
        pending_groups = 0

        # Calculate total usage
        total_contracts_limit = 0
        total_matched_contracts = 0
        total_used_contracts = 0
        total_filled_cost = 0
        total_remaining_cost = 0

        # Build enriched group list
        enriched_groups = []
        alerts = []

        for og in groups:
            og_id = og.get("order_group_id") or og.get("id", "unknown")
            status = og.get("status", "unknown")
            contracts_limit = og.get("contracts_limit", 0)
            matched = og.get("matched_contracts", 0)
            used = og.get("used_contracts", 0)
            filled_cost = og.get("filled_cost", 0)
            remaining_cost = og.get("remaining_cost", 0)

            # Count by status
            if status == "active":
                active_groups += 1
            elif status == "triggered":
                triggered_groups += 1
            elif status == "canceled":
                canceled_groups += 1
            elif status == "pending":
                pending_groups += 1

            # Sum totals
            total_contracts_limit += contracts_limit
            total_matched_contracts += matched
            total_used_contracts += used
            total_filled_cost += filled_cost
            total_remaining_cost += remaining_cost

            # Calculate utilization
            utilization_pct = 0.0
            if contracts_limit > 0:
                utilization_pct = round((used / contracts_limit) * 100, 2)

            # Build enriched group entry
            enriched_groups.append({
                "order_group_id": og_id,
                "name": og.get("name", ""),
                "status": status,
                "subaccount": og.get("subaccount", 0),
                "contracts_limit": contracts_limit,
                "matched_contracts": matched,
                "used_contracts": used,
                "remaining_contracts": max(0, contracts_limit - used),
                "utilization_pct": utilization_pct,
                "filled_cost": filled_cost,
                "remaining_cost": remaining_cost,
                "max_cost": og.get("max_cost", 0),
            })

            # Generate alerts for high utilization or triggered groups
            if status == "triggered":
                alerts.append({
                    "level": "warning",
                    "type": "group_triggered",
                    "order_group_id": og_id,
                    "message": f"Order group {og_id} triggered - orders auto-canceled",
                })
            elif contracts_limit > 0 and utilization_pct >= 90:
                alerts.append({
                    "level": "warning",
                    "type": "high_utilization",
                    "order_group_id": og_id,
                    "message": f"Order group {og_id} at {utilization_pct}% utilization",
                })

        await client.close()

        return {
            "summary": {
                "total_groups": total_groups,
                "active": active_groups,
                "triggered": triggered_groups,
                "canceled": canceled_groups,
                "pending": pending_groups,
            },
            "usage": {
                "total_contracts_limit": total_contracts_limit,
                "total_matched_contracts": total_matched_contracts,
                "total_used_contracts": total_used_contracts,
                "total_filled_cost": total_filled_cost,
                "total_remaining_cost": total_remaining_cost,
                "overall_utilization_pct": round(
                    (total_used_contracts / total_contracts_limit) * 100, 2
                ) if total_contracts_limit > 0 else 0.0,
            },
            "groups": enriched_groups,
            "alerts": alerts,
            "latency_ms": result.latency_ms,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Order groups dashboard failed: {exc}")
        raise HTTPException(500, f"Order groups dashboard failed: {exc}")


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
                for agent_id, m in tracker.get_all_metrics().items():
                    cat = agent_id.split("_")[0] if "_" in agent_id else agent_id
                    category_pnl[cat] = category_pnl.get(cat, 0.0) + float(m.total_pnl_usd)
            except Exception as _e:
                logger.debug("category_pnl tracker skipped: %s", _e)
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

    # Overlay global risk_controller state (authoritative kill-switch + daily PnL)
    try:
        from merid.risk.kill_switches import risk_controller as _rc
        _rc_status = _rc.get_status()
        if not _rc_status.get("can_trade", True):
            base["kill_switch_active"] = True
            base["kill_switch_reason"] = _rc_status.get("kill_reason")
        _rc_pnl = float(_rc_status.get("daily_pnl", 0.0))
        if _rc_pnl != 0.0:
            base["daily_pnl_usd"] = _rc_pnl
            base["daily_realized_pnl_usd"] = _rc_pnl
            base["daily_total_pnl_usd"] = _rc_pnl
    except Exception as _e:
        logger.debug("risk_controller pnl supplement skipped: %s", _e)

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
        except Exception as _e:
            logger.debug("perf tracker supplement skipped: %s", _e)

    # Add ExecutionGateStrip field aliases so the component's near-limit
    # calculations work: total_exposure, max_exposure, daily_pnl, max_daily_loss
    base.setdefault("total_exposure", base.get("total_notional_usd", 0))
    base.setdefault("max_exposure", base.get("limits", {}).get("max_notional_usd", 10000))
    base.setdefault("daily_pnl", base.get("daily_pnl_usd", 0))
    _max_daily_loss = base.get("limits", {}).get("daily_loss_limit", 0.0)
    if not _max_daily_loss:
        try:
            from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk as _gkr_r
            _max_daily_loss = float(_gkr_r().config.max_daily_loss_usd)
        except Exception as _e:
            logger.debug("max_daily_loss lookup skipped: %s", _e)
            _max_daily_loss = 0.0
    base.setdefault("max_daily_loss", _max_daily_loss)
    base.setdefault("position_count", base.get("open_market_count", 0))
    base.setdefault("max_positions", base.get("limits", {}).get("max_open_markets", 20))

    return base


@router.post("/kill-switch")
async def toggle_kill_switch(activate: bool = True) -> Dict[str, Any]:
    """Activate or reset the Kalshi kill switch."""
    risk = _get_risk()
    if not risk:
        return {"kill_switch": False, "action": "unavailable", "error": "Risk manager not available"}
    if activate:
        risk.fire_kill_switch("Manual operator activation")
    else:
        risk.reset_kill_switch()
    # Also sync global risk_controller
    try:
        from merid.risk.kill_switches import risk_controller as _rc
        if activate:
            _rc.emergency_stop("Manual operator activation via API")
        else:
            _rc.reset(operator="api")
    except Exception as _e:
        logger.warning("kill_switch toggle failed: %s", _e)
    return {"kill_switch": activate, "action": "activated" if activate else "reset"}


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

@router.get("/health",
    summary="Kalshi Integration Health Check",
    description="Comprehensive health check covering catalog freshness, risk manager state, WebSocket bridge connectivity, REST client connectivity, and rate limit headroom.",
    response_description="Health status, issues list, and component states",
    tags=["kalshi", "health"],
)
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
        except Exception as _e:
            logger.debug("catalog summary skipped: %s", _e)
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
        except Exception as _e:
            logger.debug("risk summary skipped: %s", _e)
    if risk_data["kill_switch"]:
        issues.append("kill_switch_active")

    # WS bridge (optional - not required for healthy status)
    ws_data: Dict[str, Any] = {"running": False, "events_forwarded": 0, "subscribed_tickers": 0}
    bridge = _get_bridge()
    if bridge:
        try:
            ws_data = bridge.summary()
        except Exception as _e:
            logger.debug("ws_bridge summary skipped: %s", _e)
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
    except Exception as _e:
        logger.debug("rate limit config lookup skipped: %s", _e)
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
    except Exception as _e:
        logger.debug("position sizer metrics skipped, using live risk fallback: %s", _e)
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

    # Continuous trader snapshot — authoritative source for trade counts
    ct_snapshot: Dict[str, Any] = {}
    try:
        from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
        tracker = get_agent_performance_tracker()
        sys = tracker.get_system_summary()
        ct_snapshot = {
            "total_trades": sys.get("total_closes", 0),
            "total_fills": sys.get("total_fills", 0),
            "system_win_rate": round(sys.get("system_win_rate", 0) * 100, 1),
            "agent_count": sys.get("total_agents", 0),
        }
        # Prefer CT trade count over risk summary (which may be truncated)
        ct_trades = sys.get("total_closes", 0)
        if ct_trades > 0 and (trades_today == 0 or ct_trades > trades_today):
            logger.debug("sizing_metrics: using CT trade count %d (risk_summary had %d)", ct_trades, trades_today)
            trades_today = ct_trades
        if win_rate == 0:
            win_rate = round(sys.get("system_win_rate", 0) * 100, 1)
        top = tracker.get_top_agents(metric="sharpe_ratio", limit=1)
        if top and sharpe == 0:
            sharpe = top[0].get("sharpe_ratio", 0)
        if top and pf == 0:
            pf = top[0].get("avg_realized_edge", 0) / max(top[0].get("avg_predicted_edge", 1), 0.001)
    except Exception as _e:
        logger.warning("sizing_metrics: performance tracker unavailable, using risk summary fallback: %s", _e)

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
        "continuous_trader": ct_snapshot,
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
        except Exception as _e:
            logger.debug("catalog ticker_list skipped: %s", _e)
            ticker_list = []
    else:
        ticker_list = []

    # Get sizer for sizing tier context
    try:
        sizer = _get_position_sizer()
        base_kelly = sizer.kelly_fraction
        effective = sizer.effective_fraction
    except Exception as _e:
        logger.debug("position sizer kelly lookup skipped: %s", _e)
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

    # Drawdown tier events — thresholds from risk config
    dd = summary.get("drawdown_pct", 0)
    _dd_warn = 5.0
    _dd_down = 10.0
    _dd_halt = 15.0
    try:
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk as _gkr_ev
        _krc = _gkr_ev().config
        _dd_halt = round(float(_krc.drawdown_halt_pct) * 100, 1)
        _dd_down = round(_dd_halt * 0.667, 1)
        _dd_warn = round(_dd_halt * 0.333, 1)
    except Exception as _e:
        logger.debug("drawdown thresholds lookup skipped: %s", _e)
    if dd >= _dd_down:
        events.append({
            "id": "dd-critical",
            "ts": ts,
            "severity": "critical",
            "category": "drawdown",
            "title": f"Drawdown at {dd:.1f}% — DOWNSIZE tier",
            "detail": f"Position sizes automatically reduced. Halt at {_dd_halt:.1f}%.",
        })
    elif dd >= _dd_warn:
        events.append({
            "id": "dd-warning",
            "ts": ts,
            "severity": "warning",
            "category": "drawdown",
            "title": f"Drawdown at {dd:.1f}% — WARNING tier",
            "detail": f"Approaching downsize threshold ({_dd_down:.1f}%). Monitor closely.",
        })

    # Rate limit proximity — limits from risk config
    rate_min = summary.get("orders_this_minute", 0)
    _rate_limit = 30
    try:
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk as _gkr_rl
        _rate_limit = int(_gkr_rl().config.max_orders_per_minute)
    except Exception as _e:
        logger.debug("rate_limit config lookup skipped: %s", _e)
    _rate_crit = int(_rate_limit * 0.833)
    _rate_warn = int(_rate_limit * 0.667)
    if rate_min >= _rate_crit:
        events.append({
            "id": "rate-critical",
            "ts": ts,
            "severity": "critical",
            "category": "rate_limit",
            "title": f"Rate limit critical: {rate_min}/{_rate_limit} orders this minute",
        })
    elif rate_min >= _rate_warn:
        events.append({
            "id": "rate-warning",
            "ts": ts,
            "severity": "warning",
            "category": "rate_limit",
            "title": f"Rate limit approaching: {rate_min}/{_rate_limit} orders this minute",
        })

    # Daily loss cap check
    daily_pnl = summary.get("daily_pnl_usd", 0)
    _max_loss_fallback = 0.0
    try:
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk as _gkr_ml
        _max_loss_fallback = float(_gkr_ml().config.max_daily_loss_usd)
    except Exception as _e:
        logger.debug("max_daily_loss_fallback lookup skipped: %s", _e)
    max_loss = summary.get("limits", {}).get("max_daily_loss_usd") or _max_loss_fallback
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
            except Exception as _e:
                logger.debug("WS broadcast skipped (best-effort): %s", _e)

    return {"events": events[:limit]}


# ── BTC 15m risk singleton ────────────────────────────────────────────────
# Shared across all /risk/btc15m/* endpoints so daily PnL, open exposure,
# and phase promotion state persist across requests.
_btc15m_risk_manager = None

def _get_btc15m_risk_manager():
    """Return the module-level CryptoSwarmRiskBTC15m singleton, creating it on first call."""
    global _btc15m_risk_manager
    if _btc15m_risk_manager is None:
        try:
            from merid.risk.crypto_swarm_risk_btc15m import CryptoSwarmRiskBTC15m, RiskPhase
            _initial_equity = 0.0
            try:
                from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk as _gkr_btc
                _initial_equity = float(_gkr_btc().state.current_equity_usd or 0)
            except Exception as _e:
                logger.debug("initial_equity from kalshi_risk skipped: %s", _e)
            if _initial_equity <= 0:
                try:
                    from merid.settings import settings as _s_btc
                    _initial_equity = float(getattr(_s_btc, 'PAPER_STARTING_BALANCE', 0))
                except Exception:
                    _initial_equity = 0.0
            _btc15m_risk_manager = CryptoSwarmRiskBTC15m(
                current_equity=_initial_equity,
                phase=RiskPhase.PHASE_0,
            )
        except Exception as exc:
            logger.error(f"Failed to initialise BTC15m risk singleton: {exc}")
            raise
    return _btc15m_risk_manager


@router.post("/risk/btc15m/evaluate")
async def btc15m_risk_evaluate_endpoint(
    proposal: Dict[str, Any],
) -> Dict[str, Any]:
    """Evaluate a trade proposal through the BTC 15m risk layer.
    
    This is the single entry point for agent trade proposals. It routes
    proposals through the CryptoSwarmRiskBTC15m layer which implements:
    - Live vs Paper routing (Phase 0: only BTC 15m goes live)
    - Per-trade cost caps (0.25 base, 0.30 hard)
    - Daily loss limits (-0.50 soft, -1.00 hard)
    - Max open exposure (0.50 live)
    - Fear/greed size multipliers
    - BTC 15m microstructure filters
    
    Request body:
        {
            "asset": "BTC",
            "timeframe": "15m",
            "side": "yes",
            "price_cents": 35,
            "intent_risk": 0.25,
            "tags": ["trending", "volatile"],
            "fear_greed": 72,
            "spread_ticks": 3,
            "volume_24h": 50000,
            "minutes_to_expiry": 10,
            "session_stable": true
        }
    
    Returns:
        {
            "mode": "live" | "paper" | "blocked",
            "final_size": 0.25,
            "reason": "Approved live: size=$0.25",
            "adjustments": {...},
            "blocked_reason": null
        }
    """
    try:
        from merid.risk.crypto_swarm_risk_btc15m import TradeProposal, TradeMode
        risk_manager = _get_btc15m_risk_manager()
        
        # Update fear/greed if provided
        if "fear_greed" in proposal:
            risk_manager.update_fear_greed(proposal["fear_greed"])
        
        # Build trade proposal
        trade_proposal = TradeProposal(
            asset=proposal.get("asset", ""),
            timeframe=proposal.get("timeframe", ""),
            side=proposal.get("side", "yes"),
            price_cents=proposal.get("price_cents", 50),
            intent_risk=proposal.get("intent_risk", 0.25),
            tags=proposal.get("tags", []),
            fear_greed=proposal.get("fear_greed"),
            spread_ticks=proposal.get("spread_ticks"),
            volume_24h=proposal.get("volume_24h"),
            minutes_to_expiry=proposal.get("minutes_to_expiry"),
            session_stable=proposal.get("session_stable", True),
        )
        
        # Evaluate through risk layer
        decision = risk_manager.evaluate_proposal(trade_proposal)
        
        return {
            "mode": decision.mode.value,
            "final_size": decision.final_size,
            "reason": decision.reason,
            "adjustments": decision.adjustments,
            "blocked_reason": decision.blocked_reason,
            "risk_status": risk_manager.get_status_summary(),
        }
    except Exception as exc:
        logger.error(f"BTC 15m risk evaluation failed: {exc}")
        raise HTTPException(500, f"Risk evaluation failed: {exc}")


@router.get("/risk/btc15m/status")
async def btc15m_risk_status_endpoint() -> Dict[str, Any]:
    """Get current BTC 15m risk layer status.
    
    Returns the complete risk state including:
    - Current phase and equity
    - Daily PnL and loss limit status
    - Open exposure and position count
    - Fear/greed reading
    - Phase promotion eligibility
    """
    try:
        risk_manager = _get_btc15m_risk_manager()
        return risk_manager.get_status_summary()
    except Exception as exc:
        logger.error(f"BTC 15m risk status failed: {exc}")
        return {
            "error": str(exc),
            "phase": "unknown",
            "equity": 0,
        }


# ── Multi-TF Drawdown Guard ────────────────────────────────────────────

@router.get("/risk/dd-guard")
async def get_dd_guard_status() -> Dict[str, Any]:
    """
    Return per-timeframe and global drawdown brake state.

    Fields per key (e.g. 'BTC:15m', 'GLOBAL'):
      equity, peak, drawdown (0..1), limit (0..1), allowed (bool)

    Use this endpoint to surface drawdown brake status in the UI and
    to alert when a lane is approaching its DD limit.
    """
    try:
        from merid.risk.multi_tf_drawdown import get_multi_tf_drawdown_guard
        guard = get_multi_tf_drawdown_guard()
        status = guard.get_status()
        return {
            "ok": True,
            "lanes": status,
            "global_allowed": guard.global_allowed(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.warning("dd-guard status failed: %s", exc)
        return {"ok": False, "error": str(exc)}


# ── Market Mood Bus ────────────────────────────────────────────────────

def _fg_regime_str(fg_index: int) -> str:
    """Map a 0-100 fear/greed index to a regime string."""
    if fg_index <= 20:
        return "extreme_fear"
    if fg_index <= 40:
        return "fear"
    if fg_index <= 60:
        return "neutral"
    if fg_index <= 80:
        return "greed"
    return "extreme_greed"


@router.get("/mood/{asset}/{timeframe}")
async def get_market_mood(
    asset: str,
    timeframe: str,
) -> Dict[str, Any]:
    """Get unified market mood context for an asset/timeframe.
    
    Returns the SentimentContext with fear/greed, social/news sentiment,
    trend scores, volatility regime, and Kalshi market data.
    """
    try:
        from merid.swarm.market_mood_bus import get_market_mood_bus
        bus = get_market_mood_bus()
        context = bus.get_context(asset, timeframe)
        
        if not context:
            return {
                "asset": asset,
                "timeframe": timeframe,
                "error": "No context available",
            }
        
        return {
            "asset": context.asset,
            "timeframe": context.timeframe,
            "timestamp": context.timestamp.isoformat(),
            "fg_index": context.fg_index,
            "social_sentiment": context.social_sentiment,
            "news_sentiment": context.news_sentiment,
            "kalshi_sentiment": context.kalshi_sentiment,
            "sentiment_confidence": context.sentiment_confidence.value,
            "trend_score": context.trend_score,
            "volatility_regime": context.volatility_regime.value,
            "price_momentum_1h": context.price_momentum_1h,
            "kalshi_price": context.kalshi_price,
            "kalshi_spread_bps": context.kalshi_spread_bps,
            "tags": context.tags,
            "swarm_consensus": {
                "prob": context.swarm_consensus_prob,
                "direction": context.swarm_consensus_direction,
                "confidence": context.swarm_confidence,
                "agents_voting": context.swarm_agents_voting,
            } if context.swarm_consensus_prob else None,
            "risk_status": {
                "regime": context.risk_regime,
                "daily_pnl": context.daily_pnl_usd,
                "open_exposure": context.open_exposure_usd,
            },
        }
    except Exception as exc:
        logger.error(f"Market mood fetch failed: {exc}")
        return {"error": str(exc), "asset": asset, "timeframe": timeframe}


@router.get("/mood/all")
async def get_all_market_moods() -> Dict[str, Any]:
    """Get all current market mood contexts."""
    try:
        from merid.swarm.market_mood_bus import get_market_mood_bus
        bus = get_market_mood_bus()
        contexts = bus.get_all_contexts()
        
        return {
            "count": len(contexts),
            "moods": {
                key: {
                    "asset": ctx.asset,
                    "timeframe": ctx.timeframe,
                    "fg_index": ctx.fg_index,
                    "social_sentiment": ctx.social_sentiment,
                    "volatility_regime": ctx.volatility_regime.value,
                    "tags": ctx.tags,
                }
                for key, ctx in contexts.items()
            },
        }
    except Exception as exc:
        logger.error(f"All market moods fetch failed: {exc}")
        return {"error": str(exc)}


@router.get("/mood/fear-greed/{asset}")
async def get_mood_fear_greed(asset: str) -> Dict[str, Any]:
    """Get current fear/greed index for an asset from the MarketMoodBus."""
    try:
        from merid.swarm.market_mood_bus import get_market_mood_bus
        bus = get_market_mood_bus()
        ctx = bus.get_context(asset.upper(), "15m")
        if ctx:
            return {
                "asset": asset.upper(),
                "fg_index": ctx.fg_index,
                "regime": _fg_regime_str(ctx.fg_index),
                "social_sentiment": ctx.social_sentiment,
                "volatility_regime": ctx.volatility_regime.value,
                "tags": ctx.tags,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        # Fallback to CFGI if no mood bus context
        from merid.sentiment.cfgi_client import get_cfgi_client
        data = get_cfgi_client().get_fear_greed(asset.upper())
        return {
            "asset": data.asset,
            "fg_index": data.fgi,
            "regime": data.classification.value,
            "is_synthetic": data.is_synthetic,
            "timestamp": data.timestamp.isoformat(),
        }
    except Exception as exc:
        logger.warning(f"mood/fear-greed GET failed for {asset}: {exc}")
        return {"asset": asset.upper(), "fg_index": 50, "regime": "neutral", "error": str(exc)}


@router.post("/mood/fear-greed/{asset}")
async def update_fear_greed(
    asset: str,
    value: int = Query(..., ge=0, le=100),
) -> Dict[str, Any]:
    """Update fear/greed index for an asset."""
    try:
        from merid.swarm.market_mood_bus import get_market_mood_bus
        bus = get_market_mood_bus()
        bus.update_fear_greed(asset, value)
        return {"updated": True, "asset": asset, "fg_index": value}
    except Exception as exc:
        logger.error(f"Fear/greed update failed: {exc}")
        raise HTTPException(500, str(exc))


# ── Swarm Consensus ─────────────────────────────────────────────────────

@router.get("/consensus/{asset}/{timeframe}")
async def get_swarm_consensus(
    asset: str,
    timeframe: str,
) -> Dict[str, Any]:
    """Get swarm consensus for an asset/timeframe.
    
    Returns the aggregated consensus view including direction,
    probability, confidence, size band, and agent breakdown.
    """
    try:
        from merid.swarm.consensus_aggregator import get_consensus_aggregator
        aggregator = get_consensus_aggregator()
        consensus = aggregator.get_consensus(asset, timeframe)
        
        if not consensus:
            return {
                "asset": asset,
                "timeframe": timeframe,
                "status": "no_consensus",
            }
        
        return {
            "asset": consensus.asset,
            "timeframe": consensus.timeframe,
            "timestamp": consensus.timestamp.isoformat(),
            "status": consensus.status.value,
            "consensus_direction": consensus.consensus_direction,
            "consensus_probability": consensus.consensus_probability,
            "consensus_confidence": consensus.consensus_confidence,
            "total_agents": consensus.total_agents,
            "voting_agents": consensus.voting_agents,
            "direction_breakdown": consensus.direction_breakdown,
            "size_band": consensus.size_band,
            "size_rationale": consensus.size_rationale,
            "confidence_factors": consensus.confidence_factors,
            "disagreement_flags": consensus.disagreement_flags,
        }
    except Exception as exc:
        logger.error(f"Consensus fetch failed: {exc}")
        return {"error": str(exc), "asset": asset, "timeframe": timeframe}


@router.get("/consensus/all")
async def get_all_consensus() -> Dict[str, Any]:
    """Get all current swarm consensus views.

    Returns a flat ``{key: ConsensusView}`` dict so the frontend can
    consume it directly as ``Record<string, ConsensusView>``.
    """
    try:
        from merid.swarm.consensus_aggregator import get_consensus_aggregator
        aggregator = get_consensus_aggregator()
        views = aggregator.get_all_consensus()

        def _serialize(v) -> Dict[str, Any]:
            return {
                "asset": v.asset,
                "timeframe": v.timeframe,
                "timestamp": v.timestamp.isoformat() if hasattr(v.timestamp, "isoformat") else str(v.timestamp),
                "status": v.status.value if hasattr(v.status, "value") else str(v.status),
                "consensus_direction": v.consensus_direction,
                "consensus_probability": v.consensus_probability,
                "consensus_confidence": v.consensus_confidence,
                "total_agents": v.total_agents,
                "voting_agents": v.voting_agents,
                "direction_breakdown": dict(v.direction_breakdown) if v.direction_breakdown else {},
                "size_band": v.size_band,
                "size_rationale": v.size_rationale,
                "confidence_factors": list(v.confidence_factors) if v.confidence_factors else [],
                "disagreement_flags": list(v.disagreement_flags) if v.disagreement_flags else [],
                "raw_proposals": [
                    {
                        "agent_id": p.agent_id,
                        "asset": p.asset,
                        "timeframe": p.timeframe,
                        "direction": p.direction,
                        "probability": p.probability,
                        "confidence": p.confidence,
                        "size_preference": p.size_preference,
                        "rationale": p.rationale,
                        "edge_estimate": p.edge_estimate,
                        "agent_archetype": p.agent_archetype,
                        "agent_track_record": p.agent_track_record,
                    }
                    for p in (v.raw_proposals or [])
                ],
            }

        return {
            key: _serialize(v)
            for key, v in views.items()
        }
    except Exception as exc:
        logger.error(f"All consensus fetch failed: {exc}")
        return {"error": str(exc)}


# ── Insights / Swarm Journal ────────────────────────────────────────────

@router.get("/insights")
async def get_swarm_insights(
    asset: Optional[str] = None,
    timeframe: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
) -> Dict[str, Any]:
    """Get recent swarm insights for the journal.
    
    Returns InsightObjects showing what the swarm believed,
    market context at decision time, and outcomes.
    """
    try:
        from merid.swarm.market_mood_bus import get_market_mood_bus
        bus = get_market_mood_bus()
        insights = bus.get_recent_insights(
            asset=asset,
            timeframe=timeframe,
            limit=limit,
        )
        
        return {
            "count": len(insights),
            "insights": [
                {
                    "id": i.insight_id,
                    "timestamp": i.timestamp.isoformat(),
                    "asset": i.asset,
                    "timeframe": i.timeframe,
                    "swarm_direction": i.swarm_direction,
                    "swarm_probability": i.swarm_probability,
                    "swarm_confidence": i.swarm_confidence,
                    "size_band": i.swarm_size_band,
                    "headline": i.headline,
                    "rationale": i.rationale,
                    "key_factors": i.key_factors,
                    "final_mode": i.final_mode,
                    "trade_executed": i.trade_executed,
                    "entry_price": i.entry_price,
                    "realized_pnl": i.realized_pnl,
                    "prediction_correct": i.prediction_correct,
                    "lessons": i.lessons,
                }
                for i in insights
            ],
        }
    except Exception as exc:
        logger.error(f"Insights fetch failed: {exc}")
        return {"error": str(exc)}


@router.post("/risk/btc15m/fear-greed")
async def btc15m_update_fear_greed(
    value: int = Query(..., ge=0, le=100, description="Fear/greed index 0-100"),
) -> Dict[str, Any]:
    """Update the cached fear/greed reading."""
    try:
        risk_manager = _get_btc15m_risk_manager()
        risk_manager.update_fear_greed(value)
        
        return {
            "updated": True,
            "value": value,
            "zone": risk_manager.fear_greed_cache.zone if risk_manager.fear_greed_cache else None,
        }
    except Exception as exc:
        logger.error(f"Fear/greed update failed: {exc}")
        raise HTTPException(500, f"Update failed: {exc}")


@router.post("/risk/btc15m/record-result")
async def btc15m_record_result(
    ticker: str = Query(...),
    realized_pnl: float = Query(..., description="Realized PnL for the trade"),
    mode: str = Query(..., description="Trade mode: live or paper"),
) -> Dict[str, Any]:
    """Record a trade result for daily tracking."""
    try:
        from merid.risk.crypto_swarm_risk_btc15m import TradeMode
        risk_manager = _get_btc15m_risk_manager()
        trade_mode = TradeMode.LIVE if mode == "live" else TradeMode.PAPER
        risk_manager.record_trade_result(ticker, realized_pnl, trade_mode)
        
        return {
            "recorded": True,
            "ticker": ticker,
            "realized_pnl": realized_pnl,
            "mode": mode,
            "daily_state": {
                "realized_pnl": risk_manager.daily_state.realized_pnl,
                "trades_today": risk_manager.daily_state.trades_today,
                "soft_stop_triggered": risk_manager.daily_state.soft_stop_triggered,
                "hard_stop_triggered": risk_manager.daily_state.hard_stop_triggered,
            },
        }
    except Exception as exc:
        logger.error(f"Record result failed: {exc}")
        raise HTTPException(500, f"Failed: {exc}")


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
    now_ts = datetime.now(timezone.utc).isoformat()

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
    except Exception as _e:
        logger.debug("insight agent performance probe skipped: %s", _e)

    # ── 4. PositionSizer vol overshoot ────────────────────────────────────
    try:
        from merid.event_venues.kalshi.position_sizer import get_position_sizer
        sizer = get_position_sizer()
        state = sizer.vol_state if hasattr(sizer, 'vol_state') else getattr(sizer, '_vol_state', None)
        rvol = float(getattr(state, "realized_vol", 0)) if state else 0.0
        tvol = float(getattr(state, "target_vol", 0.15)) if state else 0.15
        if rvol > 0 and tvol > 0 and rvol > tvol * 1.5:
            _ins(kind="warning", insight_type="risk", severity="warning",
                 title=f"Realized vol {rvol*100:.1f}% exceeds target {tvol*100:.1f}%",
                 body="Vol scaling will auto-reduce position sizes. No action needed unless persistent.",
                 details=f"Realized: {rvol*100:.1f}%. Target: {tvol*100:.1f}%. Scale factor will be reduced.")
    except Exception as _e:
        logger.debug("insight vol overshoot probe skipped: %s", _e)

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
    except Exception as _e:
        logger.debug("insight consensus signals probe skipped: %s", _e)

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
    except Exception as _e:
        logger.debug("insight liquidity probe skipped: %s", _e)

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
        _dispatch = getattr(pipeline, 'dispatch', None) or getattr(pipeline, '_dispatch', None)
        if _dispatch:
            await _dispatch(insight)
        return {"ok": True, "ticker": ticker, "category": category}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Favorites / Watchlist ────────────────────────────────────────────────

_FAVORITES_FILE = _Path(__file__).resolve().parent.parent.parent / "data" / "kalshi_favorites.json"


def _load_favorites() -> List[str]:
    try:
        if _FAVORITES_FILE.exists():
            return _json.loads(_FAVORITES_FILE.read_text())
    except Exception as _e:
        logger.debug("_load_favorites: file read failed: %s", _e)
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

        # Get consensus rate from logger (safely — not all loggers have get_metrics)
        try:
            metrics = engine.consensus_logger.get_metrics()
            total = metrics.get("total_rounds", 0)
            successful = metrics.get("successful", 0)
            consensus_rate = round(successful / total, 3) if total > 0 else 0.0
        except (AttributeError, TypeError):
            consensus_rate = 0.0

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


# ── FIX API ─────────────────────────────────────────────────────────────

_fix_client: Optional[Any] = None

def _get_fix_client() -> Optional[Any]:
    """Get or create FIX client singleton."""
    global _fix_client
    if _fix_client is None:
        try:
            from merid.event_venues.kalshi.fix_client import KalshiFIXClient
            from merid.settings import settings
            sender_comp_id = getattr(settings, 'KALSHI_FIX_SENDER_COMP_ID', 'MERID')
            _fix_client = KalshiFIXClient(
                sender_comp_id=sender_comp_id,
                host=getattr(settings, 'KALSHI_FIX_HOST', '127.0.0.1'),
                port=getattr(settings, 'KALSHI_FIX_PORT', 98228),
            )
        except Exception as exc:
            logger.warning(f"FIX client initialization failed: {exc}")
            return None
    return _fix_client


@router.get("/fix/status")
async def fix_status() -> Dict[str, Any]:
    """Get FIX connection status."""
    fix = _get_fix_client()
    if not fix:
        return {"connected": False, "logged_on": False, "error": "FIX client not configured"}
    
    return {
        "connected": fix.is_connected,
        "logged_on": fix._logged_on if hasattr(fix, '_logged_on') else False,
        "pending_orders": len(fix.get_pending_orders()) if hasattr(fix, 'get_pending_orders') else 0,
        "sender_comp_id": fix.sender_comp_id if hasattr(fix, 'sender_comp_id') else None,
    }


@router.post("/fix/connect")
async def fix_connect() -> Dict[str, Any]:
    """Connect and logon to FIX session."""
    fix = _get_fix_client()
    if not fix:
        raise HTTPException(503, "FIX client not configured")
    
    try:
        success = await fix.connect()
        return {
            "connected": success,
            "status": "logged_on" if success else "failed",
        }
    except Exception as exc:
        logger.error(f"FIX connect failed: {exc}")
        raise HTTPException(500, f"FIX connection failed: {exc}")


@router.post("/fix/disconnect")
async def fix_disconnect() -> Dict[str, Any]:
    """Logout and disconnect from FIX session."""
    fix = _get_fix_client()
    if not fix:
        return {"disconnected": True, "was_connected": False}
    
    try:
        was_connected = fix.is_connected
        await fix.disconnect()
        return {
            "disconnected": True,
            "was_connected": was_connected,
        }
    except Exception as exc:
        logger.error(f"FIX disconnect error: {exc}")
        raise HTTPException(500, f"FIX disconnect failed: {exc}")


@router.post("/fix/orders")
async def fix_submit_order(
    ticker: str,
    side: str,  # "buy" or "sell"
    quantity: int,
    price: Optional[int] = None,
    ord_type: str = "limit",
    time_in_force: str = "gtc",
) -> Dict[str, Any]:
    """Submit order via FIX protocol.
    
    Args:
        ticker: Market ticker symbol
        side: "buy" or "sell"
        quantity: Number of contracts
        price: Price in cents (required for limit orders)
        ord_type: "limit" or "market"
        time_in_force: "gtc", "day", "ioc", or "fok"
    """
    fix = _get_fix_client()
    if not fix:
        raise HTTPException(503, "FIX client not configured")
    
    if not fix.is_connected:
        raise HTTPException(503, "FIX not connected - connect first via POST /fix/connect")
    
    try:
        cl_ord_id = await fix.submit_order(
            ticker=ticker,
            side=side,
            quantity=quantity,
            price=price,
            ord_type=ord_type,
            time_in_force=time_in_force,
        )
        return {
            "status": "submitted",
            "cl_ord_id": cl_ord_id,
            "ticker": ticker,
            "side": side,
            "quantity": quantity,
            "price": price,
        }
    except Exception as exc:
        logger.error(f"FIX order submission failed: {exc}")
        raise HTTPException(500, f"Order submission failed: {exc}")


@router.delete("/fix/orders/{cl_ord_id}")
async def fix_cancel_order(cl_ord_id: str) -> Dict[str, Any]:
    """Cancel an order via FIX."""
    fix = _get_fix_client()
    if not fix:
        raise HTTPException(503, "FIX client not configured")
    
    if not fix.is_connected:
        raise HTTPException(503, "FIX not connected")
    
    try:
        await fix.cancel_order(cl_ord_id)
        return {
            "status": "cancel_requested",
            "cl_ord_id": cl_ord_id,
        }
    except Exception as exc:
        logger.error(f"FIX cancel failed: {exc}")
        raise HTTPException(500, f"Cancel failed: {exc}")


@router.get("/fix/executions")
async def fix_executions(
    limit: int = Query(100, ge=1, le=500),
    cl_ord_id: Optional[str] = Query(None, description="Filter by client order ID"),
) -> Dict[str, Any]:
    """Get FIX execution report history."""
    fix = _get_fix_client()
    if not fix:
        raise HTTPException(503, "FIX client not configured")
    
    try:
        history = fix.get_exec_history(limit=limit)
        
        # Filter by cl_ord_id if provided
        if cl_ord_id:
            history = [e for e in history if getattr(e, 'cl_ord_id', '') == cl_ord_id]
        
        return {
            "count": len(history),
            "executions": [
                {
                    "order_id": e.order_id,
                    "cl_ord_id": e.cl_ord_id,
                    "exec_id": e.exec_id,
                    "exec_type": e.exec_type,
                    "ord_status": e.ord_status,
                    "price": e.price,
                    "quantity": e.quantity,
                    "leaves_qty": e.leaves_qty,
                    "cum_qty": e.cum_qty,
                    "last_qty": e.last_qty,
                    "last_px": e.last_px,
                    "text": e.text,
                    "timestamp": e.timestamp,
                }
                for e in history
            ],
        }
    except Exception as exc:
        logger.error(f"FIX executions fetch failed: {exc}")
        raise HTTPException(500, f"Failed to fetch executions: {exc}")


@router.get("/fix/pending")
async def fix_pending_orders() -> Dict[str, Any]:
    """Get list of pending orders in FIX."""
    fix = _get_fix_client()
    if not fix:
        raise HTTPException(503, "FIX client not configured")
    
    try:
        pending = fix.get_pending_orders()
        return {
            "count": len(pending),
            "orders": [
                {
                    "cl_ord_id": o.cl_ord_id,
                    "ticker": o.ticker,
                    "side": "buy" if o.side == "1" else "sell" if o.side == "2" else o.side,
                    "ord_type": "limit" if o.ord_type == "2" else "market" if o.ord_type == "1" else o.ord_type,
                    "price": o.price,
                    "quantity": o.quantity,
                }
                for o in pending
            ],
        }
    except Exception as exc:
        logger.error(f"FIX pending orders fetch failed: {exc}")
        raise HTTPException(500, f"Failed to fetch pending orders: {exc}")


# ── Lane Sentiment Snapshot ───────────────────────────────────────────

@router.get("/sentiment/lane-snapshot")
async def get_lane_sentiment_snapshot() -> Dict[str, Any]:
    """
    Return the BTC15m lane's live cached_sentiment dict — the exact signal
    that drives every risk decision in the current cycle.

    Fields returned (all from lane._cached_sentiment + computed extras):
      twitter, reddit, fg_index, fg_regime, fg_is_synthetic,
      combined_raw, combined_fib, combined_smoothed, confidence,
      vader_signal, kalshi_prob_adj, kalman_gain, timestamp,
      sentiment_age_seconds, sentiment_stale,
      fg_clamp_breakdown (rules_fired, sizing_multiplier, fg_filter_blocked)

    Use this endpoint to power the BTC15m sentiment strip in the UI.
    """
    try:
        from merid.lanes.btc15m_lane import get_btc15m_lane
        lane = get_btc15m_lane()
        status = lane.get_status()
        cached = status.get("cached_sentiment") or {}
        age = status.get("sentiment_age_seconds")
        stale = status.get("sentiment_stale", True)
        fg_synthetic = status.get("fg_is_synthetic", False)
    except Exception as exc:
        logger.warning("sentiment/lane-snapshot: lane unavailable — %s", exc)
        cached = {}
        age = None
        stale = True
        fg_synthetic = False

    # Compute FG clamp breakdown for UI display
    fg_breakdown: Dict[str, Any] = {}
    try:
        from merid.sentiment.btc_risk_dial import FGState, fg_clamp_breakdown
        equity = 0.0
        try:
            from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk as _gkr_fg
            equity = float(_gkr_fg().state.current_equity_usd or 0)
        except Exception as _e:
            logger.debug("fg_equity from kalshi_risk skipped: %s", _e)
        if equity <= 0:
            try:
                from merid.settings import settings as _s_fg
                equity = float(getattr(_s_fg, "PAPER_STARTING_BALANCE", 0) or 0)
            except Exception:
                equity = 0.0
        fg = FGState(
            value=int(cached.get("fg_index", 50)),
            combined=cached.get("combined_smoothed", 0.0),
            confidence=cached.get("confidence", 0.5),
            is_synthetic=fg_synthetic,
        )
        fg_breakdown = fg_clamp_breakdown(equity, fg)
    except Exception as exc:
        logger.debug("fg_clamp_breakdown unavailable: %s", exc)

    return {
        **cached,
        "sentiment_age_seconds": age,
        "sentiment_stale": stale,
        "fg_is_synthetic": fg_synthetic,
        "fg_clamp_breakdown": fg_breakdown,
        "timestamp_fetched": datetime.now(timezone.utc).isoformat(),
    }


# ── CFGI Fear/Greed Sentiment API ────────────────────────────────────
# NOTE: market-summary MUST be registered before /{asset} so FastAPI
# does not capture the literal string "market-summary" as the {asset} param.

@router.get("/sentiment/fear-greed/market-summary")
async def get_cfgi_market_summary() -> Dict[str, Any]:
    """Get CFGI fear/greed summary across major assets (BTC, ETH, SOL).

    Response shape consumed by KALSHI_FEAR_GREED_SUMMARY constant:
      timestamp, assets{fgi, classification, is_extreme, risk_multiplier},
      average_fgi, extreme_count
    """
    try:
        from merid.sentiment.cfgi_client import get_cfgi_client
        return get_cfgi_client().get_market_summary()
    except Exception as exc:
        logger.warning(f"CFGI market summary failed: {exc}")
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "assets": {},
            "average_fgi": 50,
            "extreme_count": 0,
            "error": str(exc),
        }


@router.get("/sentiment/fear-greed/{asset}")
async def get_cfgi_fear_greed(asset: str) -> Dict[str, Any]:
    """Get CFGI fear/greed index for an asset.

    Primary source: CFGI API (requires CFGI_API_KEY env var).
    Fallback: synthetic sin-wave value (marked is_synthetic=True).

    Response shape consumed by KALSHI_FEAR_GREED constant:
      asset, fgi, regime, classification, is_synthetic,
      risk_multiplier, contrarian_signal, timestamp
    """
    try:
        from merid.sentiment.cfgi_client import get_cfgi_client
        data = get_cfgi_client().get_fear_greed(asset.upper())
        return {
            **data.to_dict(),
            "regime": data.classification.value,
            "risk_multiplier": data.get_risk_multiplier(),
            "contrarian_signal": data.get_contrarian_signal(),
            "is_extreme": data.is_extreme(),
        }
    except Exception as exc:
        logger.warning(f"CFGI fear-greed fetch failed for {asset}: {exc}")
        return {
            "asset": asset.upper(),
            "fgi": 50,
            "regime": "neutral",
            "classification": "neutral",
            "is_synthetic": True,
            "risk_multiplier": 1.0,
            "contrarian_signal": "neutral",
            "is_extreme": False,
            "error": str(exc),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ── Sentiment API ─────────────────────────────────────────────────────

@router.get("/sentiment/twitter/{asset}")
async def get_twitter_sentiment(
    asset: str,
    minutes: int = Query(15, ge=5, le=60, description="Lookback window in minutes"),
) -> Dict[str, Any]:
    """Get Twitter sentiment analysis for an asset.
    
    Args:
        asset: Asset symbol (BTC, ETH, SOL, etc.)
        minutes: Recent tweets window (5-60 min)
    
    Returns:
        score: Sentiment score -1.0 to +1.0
        confidence: 0.0 to 1.0 based on volume/engagement
        volume: Number of tweets analyzed
        avg_engagement: Average tweet engagement (likes+retweets)
        timestamp: Analysis timestamp
    """
    try:
        from merid.sentiment.twitter_fetcher import get_twitter_sentiment_service
        service = get_twitter_sentiment_service()
        result = service.get_sentiment(asset, minutes=minutes)
        
        return {
            "asset": asset,
            "score": round(result.score, 4),
            "confidence": round(result.confidence, 3),
            "volume": result.volume,
            "avg_engagement": round(result.avg_engagement, 1),
            "timestamp": result.timestamp.isoformat(),
            "source": "twitter",
            "window_minutes": minutes,
        }
    except Exception as exc:
        logger.warning(f"Twitter sentiment fetch failed for {asset}: {exc}")
        return {
            "asset": asset,
            "score": 0.0,
            "confidence": 0.0,
            "volume": 0,
            "avg_engagement": 0.0,
            "error": str(exc),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "twitter",
        }


@router.get("/sentiment/reddit/{asset}")
async def get_reddit_sentiment(
    asset: str,
    time_filter: str = Query("hour", description="hour, day, or week"),
) -> Dict[str, Any]:
    """Get Reddit sentiment analysis for an asset.
    
    Polls r/Bitcoin, r/CryptoCurrency, r/Kalshi and other relevant subs.
    
    Args:
        asset: Asset symbol (BTC, ETH, SOL, etc.)
        time_filter: Recent posts window (hour, day, week)
    
    Returns:
        score: Sentiment score -1.0 to +1.0
        confidence: 0.0 to 1.0 based on volume/engagement
        volume: Number of posts analyzed
        subreddit_breakdown: Per-subreddit stats
        timestamp: Analysis timestamp
    """
    try:
        from merid.sentiment.reddit_scraper import get_reddit_sentiment_service
        service = get_reddit_sentiment_service()
        result = service.get_sentiment(asset, time_filter=time_filter)
        
        return {
            "asset": asset,
            "score": round(result.score, 4),
            "confidence": round(result.confidence, 3),
            "volume": result.volume,
            "avg_engagement": round(result.avg_engagement, 1),
            "subreddit_breakdown": result.subreddit_breakdown,
            "timestamp": result.timestamp.isoformat(),
            "source": "reddit",
            "time_filter": time_filter,
        }
    except Exception as exc:
        logger.warning(f"Reddit sentiment fetch failed for {asset}: {exc}")
        return {
            "asset": asset,
            "score": 0.0,
            "confidence": 0.0,
            "volume": 0,
            "avg_engagement": 0.0,
            "subreddit_breakdown": {},
            "error": str(exc),
        }


@router.get("/sentiment/bundle/{asset}")
async def get_sentiment_bundle_endpoint(
    asset: str,
) -> Dict[str, Any]:
    """Get SentimentBundle for a single asset."""
    try:
        from merid.sentiment import get_bundle
        bundle = get_bundle(asset.upper())
        return {
            "bundle": bundle.to_dict(),
            "formatted": str(bundle),
            "is_contrarian": getattr(bundle, 'is_contrarian', False),
            "size_multiplier": getattr(bundle, 'size_multiplier', 1.0),
        }
    except Exception as exc:
        logger.warning(f"SentimentBundle failed for {asset}: {exc}")
        return {"error": str(exc), "asset": asset}


@router.get("/sentiment/backtest")
async def sentiment_backtest_endpoint(
    asset: str = Query(..., description="Asset symbol e.g. BTC"),
    days: int = Query(30, ge=7, le=90, description="Lookback days"),
) -> Dict[str, Any]:
    """Run a sentiment threshold backtest for an asset."""
    try:
        from merid.sentiment import run_backtest
        result = run_backtest(asset.upper(), days=days)
        return result
    except Exception as exc:
        logger.warning(f"Sentiment backtest failed for {asset}: {exc}")
        return {
            "asset": asset,
            "days": days,
            "error": str(exc),
            "best": {"pos_th": 0.0, "neg_th": 0.0, "sharpe": 0.0, "max_drawdown": 0.0, "win_rate": 0.0, "trades": 0},
            "top_5": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


@router.get("/sentiment/bundle-multi")
async def get_multi_bundle_endpoint(
    assets: str = Query(..., description="Comma-separated assets")
) -> Dict[str, Any]:
    """Get SentimentBundle for multiple assets."""
    try:
        from merid.sentiment import get_multi_bundle
        asset_list = [a.strip().upper() for a in assets.split(",")]
        bundles = get_multi_bundle(asset_list)
        return {
            "bundles": {asset: b.to_dict() for asset, b in bundles.items()},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/sentiment/decide-btc-15m")
async def decide_btc_15m_endpoint(
    base_prob: float = Query(..., ge=0.01, le=0.99),
) -> Dict[str, Any]:
    """Get BTC 15m decision with sentiment."""
    try:
        from merid.sentiment import decide_btc_15m
        result = decide_btc_15m(None, base_prob)
        return result
    except Exception as exc:
        logger.error(f"BTC 15m decision failed: {exc}")
        raise HTTPException(500, f"Decision failed: {exc}")


# ── Threshold Optimizer API ──────────────────────────────────────────

@router.get("/sentiment/thresholds/status")
async def get_thresholds_status() -> Dict[str, Any]:
    """Get current VADER threshold optimization status across all tracked assets."""
    try:
        from merid.sentiment import get_threshold_status
        return get_threshold_status()
    except Exception as exc:
        logger.warning(f"Thresholds status unavailable: {exc}")
        return {
            "assets": {},
            "last_optimized": None,
            "error": str(exc),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


@router.post("/sentiment/optimize-thresholds/{asset}")
async def optimize_vader_thresholds(
    asset: str,
    days: int = Query(30, ge=7, le=90),
) -> Dict[str, Any]:
    """Optimize VADER thresholds for sentiment trading."""
    try:
        from merid.sentiment import run_threshold_optimization
        result = run_threshold_optimization(asset, days)
        return result
    except Exception as exc:
        logger.error(f"Threshold optimization failed: {exc}")
        raise HTTPException(500, f"Optimization failed: {exc}")


@router.get("/sentiment/unified/{asset}")
async def get_unified_sentiment(
    asset: str,
) -> Dict[str, Any]:
    """Get unified sentiment view combining Twitter + Reddit + Fear/Greed.
    
    This is the primary sentiment endpoint for agents and UI.
    
    Args:
        asset: Asset symbol (BTC, ETH, SOL, etc.)
    
    Returns:
        asset: Symbol
        timestamp: ISO timestamp
        twitter_score: Twitter sentiment (-1 to +1)
        reddit_score: Reddit sentiment (-1 to +1)
        combined_score: Weighted average
        fear_greed: Fear/greed index (0-100)
        trend_regime: extreme_fear/fear/neutral/greed/extreme_greed
        should_reduce_size: Risk signal flag
        contrarian_opportunity: Contrarian setup flag
    """
    try:
        from merid.sentiment.sentiment_bus import get_social_context
        context = get_social_context(asset)
        
        return {
            "asset": context["asset"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "twitter_score": context["twitter"],
            "reddit_score": context["reddit"],
            "combined_score": context["social_sentiment"],
            "fear_greed": context["fear_greed"],
            "trend_regime": context["trend_regime"],
            "confidence": context["confidence"],
            "should_reduce_size": context["should_reduce_size"],
            "contrarian_opportunity": context["contrarian_opportunity"],
        }
    except Exception as exc:
        logger.warning(f"Unified sentiment fetch failed for {asset}: {exc}")
        return {
            "asset": asset,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "twitter_score": 0.0,
            "reddit_score": 0.0,
            "combined_score": 0.0,
            "fear_greed": 50,
            "trend_regime": "neutral",
            "confidence": "low",
            "should_reduce_size": False,
            "contrarian_opportunity": False,
            "error": str(exc),
        }


@router.get("/sentiment/multi")
async def get_multi_sentiment(
    assets: str = Query(..., description="Comma-separated assets (BTC,ETH,SOL)"),
) -> Dict[str, Any]:
    """Get unified sentiment for multiple assets at once.
    
    Args:
        assets: Comma-separated list of symbols
    
    Returns:
        results: Dict keyed by asset symbol
    """
    asset_list = [a.strip().upper() for a in assets.split(",")]
    results = {}
    
    for asset in asset_list:
        try:
            from merid.sentiment.sentiment_bus import get_social_context
            context = get_social_context(asset)
            results[asset] = {
                "combined_score": context["social_sentiment"],
                "fear_greed": context["fear_greed"],
                "trend_regime": context["trend_regime"],
                "confidence": context["confidence"],
            }
        except Exception as exc:
            logger.debug(f"Sentiment failed for {asset}: {exc}")
            results[asset] = {"error": str(exc)}
    
    return {
        "assets": asset_list,
        "results": results,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/sentiment/refresh/{asset}")
async def refresh_sentiment(asset: str) -> Dict[str, Any]:
    """Force immediate sentiment refresh for an asset.
    
    Bypasses cache and fetches fresh data from Twitter/Reddit.
    """
    try:
        from merid.sentiment.sentiment_bus import get_sentiment_bus
        bus = get_sentiment_bus()
        success = bus.force_refresh(asset)
        
        return {
            "asset": asset,
            "refreshed": success,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.warning(f"Sentiment refresh failed for {asset}: {exc}")
        raise HTTPException(500, f"Refresh failed: {exc}")


# ---------------------------------------------------------------------------
# Lane observability + control
# ---------------------------------------------------------------------------

@router.get("/lane/status")
async def get_lane_status() -> Dict[str, Any]:
    """
    Return full status for all active BTC15MLane instances.

    Includes: mode, lane_live, lifecycle state, equity, DD, FG, ATR regime,
    loss streak, Kalman state, promotion phase, kill switch, and last sentiment.
    """
    try:
        from merid.lanes.btc15m_lane import get_btc15m_lane
        lane = get_btc15m_lane()
        status = lane.get_status()
    except Exception as exc:
        logger.warning("lane/status: could not get lane — %s", exc)
        status = {}

    try:
        from merid.risk.kill_switches import risk_controller
        kill = {
            "can_trade": risk_controller.can_trade(),
            "state": risk_controller.get_state().value,
            "reason": risk_controller.get_kill_reason() if not risk_controller.can_trade() else None,
        }
    except Exception:
        kill = {"can_trade": True, "state": "unknown", "reason": None}

    try:
        from merid.trading.trade_mode import get_trade_mode
        trade_mode = get_trade_mode().value
    except Exception:
        trade_mode = "unknown"

    return {
        "lane": status,
        "kill_switch": kill,
        "trade_mode": trade_mode,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# In-memory confirm tokens for destructive actions: {token: (action, expires_ts)}
import hashlib as _hashlib
import time as _time
_CONFIRM_TOKENS: Dict[str, tuple] = {}
_CONFIRM_TTL = 60.0  # seconds


def _issue_confirm_token(action: str) -> str:
    """Issue a short-lived confirmation token for a destructive action."""
    import secrets
    token = secrets.token_hex(8)
    _CONFIRM_TOKENS[token] = (action, _time.monotonic() + _CONFIRM_TTL)
    # Prune expired tokens
    expired = [t for t, (_, exp) in _CONFIRM_TOKENS.items() if _time.monotonic() > exp]
    for t in expired:
        _CONFIRM_TOKENS.pop(t, None)
    return token


def _consume_confirm_token(token: str, action: str) -> bool:
    """Validate and consume a confirmation token. Returns True if valid."""
    entry = _CONFIRM_TOKENS.pop(token, None)
    if entry is None:
        return False
    expected_action, expires = entry
    if _time.monotonic() > expires:
        return False
    return expected_action == action


# Actions that require a two-step confirm_token flow
_DESTRUCTIVE_ACTIONS = {"set_trade_mode_live", "disable_paper"}


@router.post("/lane/control")
async def lane_control(body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Control the BTC15m lane and global risk state.

    Supported actions (body.action):
      - "start"             — start the lane if not running
      - "stop"              — stop the lane
      - "kill_switch_on"    — activate global kill switch
      - "kill_switch_off"   — reset global kill switch
      - "set_paper"         — force lane into paper mode (lane_live=False)
      - "set_trade_mode"    — set global TradeMode (body.mode = "live"|"paper")

    Two-step confirmation for destructive actions (set_trade_mode=live):
      Step 1: POST {action: "set_trade_mode", mode: "live"}
              → returns {ok: false, confirm_required: true, confirm_token: "<tok>"}
      Step 2: POST {action: "set_trade_mode", mode: "live", confirm_token: "<tok>"}
              → executes and returns {ok: true}
      Token expires after 60 seconds.
    """
    action = body.get("action", "")
    result: Dict[str, Any] = {"action": action, "ok": False, "detail": ""}

    try:
        if action == "start":
            from merid.lanes.btc15m_lane import get_btc15m_lane
            lane = get_btc15m_lane()
            if not getattr(lane, 'running', getattr(lane, '_running', False)):
                import asyncio
                asyncio.create_task(lane.start())
                result.update(ok=True, detail="lane start task created")
            else:
                result.update(ok=True, detail="lane already running")

        elif action == "stop":
            from merid.lanes.btc15m_lane import get_btc15m_lane
            lane = get_btc15m_lane()
            await lane.stop()
            result.update(ok=True, detail="lane stopped")

        elif action == "kill_switch_on":
            from merid.risk.kill_switches import risk_controller
            reason_str = body.get("reason", "operator_ui")
            risk_controller.emergency_stop(reason_str)
            logger.warning("KILL SWITCH ACTIVATED via API | reason=%s", reason_str)
            result.update(ok=True, detail=f"kill switch activated: {reason_str}")

        elif action == "kill_switch_off":
            from merid.risk.kill_switches import risk_controller
            risk_controller.reset()
            logger.info("Kill switch RESET via API")
            result.update(ok=True, detail="kill switch reset")

        elif action == "set_paper":
            from merid.lanes.btc15m_lane import get_btc15m_lane
            lane = get_btc15m_lane()
            lane.lane_live = False
            lane.config.paper_mode = True
            logger.warning("Lane forced to PAPER mode via API")
            result.update(ok=True, detail="lane forced to paper mode")

        elif action == "set_trade_mode":
            mode_str = body.get("mode", "paper").lower()
            if mode_str == "live":
                # Two-step confirmation required
                confirm_token = body.get("confirm_token", "")
                if not confirm_token:
                    token = _issue_confirm_token("set_trade_mode_live")
                    result.update(
                        ok=False,
                        confirm_required=True,
                        confirm_token=token,
                        detail=(
                            "Enabling LIVE mode requires confirmation. "
                            f"Re-submit with confirm_token='{token}' within {int(_CONFIRM_TTL)}s."
                        ),
                    )
                elif not _consume_confirm_token(confirm_token, "set_trade_mode_live"):
                    result.update(
                        ok=False,
                        detail="Invalid or expired confirm_token. Request a new one.",
                    )
                else:
                    from merid.trading.trade_mode import set_trade_mode, TradeMode
                    set_trade_mode(TradeMode.LIVE)
                    logger.warning("TradeMode set to LIVE via API (confirmed)")
                    result.update(ok=True, detail="TradeMode set to live")
            else:
                from merid.trading.trade_mode import set_trade_mode, TradeMode
                set_trade_mode(TradeMode.PAPER)
                logger.info("TradeMode set to PAPER via API")
                result.update(ok=True, detail="TradeMode set to paper")

        else:
            result.update(detail=f"unknown action: {action!r}")

    except Exception as exc:
        logger.error("lane/control error: %s", exc)
        result.update(detail=str(exc))

    result["timestamp"] = datetime.now(timezone.utc).isoformat()
    return result


@router.get("/lane/metrics")
async def get_lane_metrics() -> Dict[str, Any]:
    """
    Return per-lane trading metrics: cycle counts, block rates, order counts,
    avg/max size, latency, API error counts, and block-reason histogram.

    Suitable for wiring into a Grafana dashboard or Telegram /status command.
    """
    try:
        from merid.lanes.lane_metrics import all_lane_metrics
        lanes = {lid: m.to_dict() for lid, m in all_lane_metrics().items()}
    except Exception as exc:
        logger.warning("lane/metrics unavailable: %s", exc)
        lanes = {}

    return {
        "lanes": lanes,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/sentiment/compare")
async def compare_sentiment_sources(
    asset: str = Query(..., description="Asset to compare"),
) -> Dict[str, Any]:
    """Compare Twitter vs Reddit sentiment divergence for analysis.
    
    Useful for identifying when social sources disagree.
    """
    try:
        from merid.sentiment.reddit_scraper import compare_sentiment_sources
        comparison = compare_sentiment_sources(asset)
        
        return {
            "asset": asset,
            "twitter": comparison["twitter"],
            "reddit": comparison["reddit"],
            "difference": comparison["difference"],
            "agreement": comparison["agreement"],
            "interpretation": (
                "High divergence - verify with other sources"
                if comparison["difference"] > 0.5
                else "Sources aligned"
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.warning(f"Sentiment comparison failed for {asset}: {exc}")
        return {
            "asset": asset,
            "error": str(exc),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ── Sentiment Context ────────────────────────────────────────────────────

@router.get("/sentiment/context/{asset}")
async def get_sentiment_context(asset: str) -> Dict[str, Any]:
    """Full sentiment context for an asset from SentimentBusV2.

    Returns combined scores, fear/greed, social, news, and confidence.
    """
    try:
        from merid.sentiment.sentiment_bus_v2 import get_sentiment_bus
        bus = get_sentiment_bus()
        ctx = None
        if hasattr(bus, "get_asset_context"):
            ctx = bus.get_asset_context(asset)
        if ctx is None:
            return {"asset": asset, "context": None, "source": "sentiment_bus_v2"}
        return {
            "asset": asset,
            "context": ctx if isinstance(ctx, dict) else (ctx.__dict__ if hasattr(ctx, "__dict__") else str(ctx)),
            "source": "sentiment_bus_v2",
        }
    except Exception as exc:
        logger.warning("sentiment/context/%s failed: %s", asset, exc)
        return {"asset": asset, "context": None, "error": str(exc)}


# ── VADER Signal ──────────────────────────────────────────────────────────

@router.get("/sentiment/vader/signal")
async def get_vader_signal(
    compound: float = Query(..., ge=-1.0, le=1.0, description="VADER compound score"),
    volume: int = Query(100, ge=0, description="Tweet/post volume for confidence"),
) -> Dict[str, Any]:
    """Compute VADER-based trading signal and confidence from a compound score."""
    try:
        from merid.sentiment.vader_utils import vader_signal, vader_confidence
        signal = vader_signal(compound)
        confidence = vader_confidence(compound, volume)
        return {
            "compound": compound,
            "signal": signal,
            "confidence": round(confidence, 4),
            "volume": volume,
        }
    except Exception as exc:
        logger.warning("vader/signal failed: %s", exc)
        return {"compound": compound, "signal": "neutral", "confidence": 0.0, "error": str(exc)}


@router.get("/sentiment/vader/kalshi-adjustment")
async def get_vader_kalshi_adjustment(
    compound: float = Query(..., ge=-1.0, le=1.0, description="VADER compound score"),
    fg_index: int = Query(50, ge=0, le=100, description="Fear/Greed index (0-100)"),
) -> Dict[str, Any]:
    """Compute VADER-based Kalshi probability adjustment."""
    try:
        from merid.sentiment.vader_utils import vader_to_kalshi_adjustment
        adjustment = vader_to_kalshi_adjustment(compound, fg_index)
        return {
            "compound": compound,
            "fg_index": fg_index,
            "adjustment": round(adjustment, 4),
        }
    except Exception as exc:
        logger.warning("vader/kalshi-adjustment failed: %s", exc)
        return {"compound": compound, "fg_index": fg_index, "adjustment": 0.0, "error": str(exc)}


# ── Twitter Streaming ─────────────────────────────────────────────────────

@router.post("/sentiment/twitter/stream/start")
async def start_twitter_stream(
    assets: str = Query("BTC,ETH,SOL", description="Comma-separated assets to track"),
) -> Dict[str, Any]:
    """Start the Twitter streaming handler for live sentiment."""
    try:
        from merid.sentiment.twitter_fetcher import get_twitter_stream_handler
        handler = get_twitter_stream_handler()
        asset_list = [a.strip().upper() for a in assets.split(",") if a.strip()]
        handler.start(asset_list)
        return {"started": True, "assets": asset_list}
    except Exception as exc:
        logger.warning("twitter/stream/start failed: %s", exc)
        return {"started": False, "error": str(exc)}


@router.post("/sentiment/twitter/stream/stop")
async def stop_twitter_stream() -> Dict[str, Any]:
    """Stop the Twitter streaming handler."""
    try:
        from merid.sentiment.twitter_fetcher import get_twitter_stream_handler
        handler = get_twitter_stream_handler()
        handler.stop()
        return {"stopped": True}
    except Exception as exc:
        logger.warning("twitter/stream/stop failed: %s", exc)
        return {"stopped": False, "error": str(exc)}


@router.get("/sentiment/twitter/stream/rolling/{asset}")
async def get_twitter_stream_rolling(
    asset: str,
    window: int = Query(50, ge=5, le=500, description="Rolling window size"),
) -> Dict[str, Any]:
    """Get rolling average sentiment from the Twitter stream for an asset."""
    try:
        from merid.sentiment.twitter_fetcher import get_twitter_stream_handler
        handler = get_twitter_stream_handler()
        return handler.get_rolling_sentiment(asset.upper(), window)
    except Exception as exc:
        logger.warning("twitter/stream/rolling/%s failed: %s", asset, exc)
        return {"asset": asset, "count": 0, "rolling_compound": 0.0, "error": str(exc)}


# ── Global Risk Status ────────────────────────────────────────────────────────

# In-memory ring buffer for state transitions (max 200 entries).
import collections as _collections
import datetime as _dt_mod

_STATE_TRANSITIONS: "collections.deque[Dict[str, Any]]" = _collections.deque(maxlen=200)


def _record_state_transition(event_type: str, detail: str, extra: Optional[Dict[str, Any]] = None) -> None:
    """Append a timestamped entry to the state-transitions ring buffer."""
    entry: Dict[str, Any] = {
        "ts": _dt_mod.datetime.now(_dt_mod.timezone.utc).isoformat(),
        "event_type": event_type,
        "detail": detail,
    }
    if extra:
        entry.update(extra)
    _STATE_TRANSITIONS.append(entry)


@router.get("/global-risk-status")
async def get_global_risk_status() -> Dict[str, Any]:
    """Aggregated risk snapshot for the GlobalRiskStatus dashboard widget.

    Returns:
        drawdown_pct, zone, zone_multiplier — from DrawdownZoneManager.
        profit_lock_state, locked_profit_usd, giveback_remaining_usd — from ProfitLockEngine.
        error_budget_used, error_budget_threshold — from RiskController.
        drawdown_halt_active, manual_halt_active — halt flags.
    """
    import datetime as _dt_local

    result: Dict[str, Any] = {
        "ts": _dt_local.datetime.now(_dt_local.timezone.utc).isoformat(),
        # Drawdown zone
        "drawdown_pct": 0.0,
        "zone": "green",
        "zone_multiplier": 1.0,
        # Profit-lock
        "profit_lock_state": "safe",
        "profit_lock_multiplier": 1.0,
        "locked_profit_usd": 0.0,
        "giveback_remaining_usd": 0.0,
        "session_high_usd": 0.0,
        # Combined effective multiplier
        "effective_multiplier": 1.0,
        # Error budget
        "error_budget_used": 0,
        "error_budget_threshold": 50,
        "error_budget_pct": 0.0,
        # Halt flags
        "drawdown_halt_active": False,
        "manual_halt_active": False,
        "kill_switch_active": False,
        "kill_switch_reason": None,
    }

    # --- Drawdown zone --------------------------------------------------
    try:
        from merid.risk.drawdown_zones import get_drawdown_zone_manager
        dzm = get_drawdown_zone_manager()
        dz_status = dzm.get_status()
        dd_pct = dz_status.get("current_drawdown_pct", 0.0)
        zone_str = dz_status.get("current_zone", "green")
        mults = dz_status.get("multipliers", {})
        zone_mult = mults.get(zone_str, 1.0)
        result["drawdown_pct"] = round(dd_pct, 2)
        result["zone"] = zone_str
        result["zone_multiplier"] = round(zone_mult, 4)
    except Exception as _e:
        logger.debug("global_risk_status: drawdown zone lookup failed: %s", _e)

    # --- Profit-lock ----------------------------------------------------
    try:
        from merid.risk.profit_lock import get_profit_lock_engine
        pl = get_profit_lock_engine()
        pl_status = pl.get_status()
        pl_state = pl_status.get("state", "safe")
        pl_mult = pl_status.get("size_multiplier", 1.0)
        locked = pl_status.get("locked_profit", 0.0)
        headroom = pl_status.get("headroom", 0.0)
        session_high = pl_status.get("session_high", 0.0)
        result["profit_lock_state"] = pl_state
        result["profit_lock_multiplier"] = round(pl_mult, 4)
        result["locked_profit_usd"] = round(locked, 2)
        result["giveback_remaining_usd"] = round(max(0.0, headroom), 2)
        result["session_high_usd"] = round(session_high, 2)
    except Exception as _e:
        logger.debug("global_risk_status: profit lock lookup failed: %s", _e)

    # --- Effective combined multiplier ----------------------------------
    result["effective_multiplier"] = round(
        result["zone_multiplier"] * result["profit_lock_multiplier"], 4
    )

    # --- Error budget ---------------------------------------------------
    try:
        from merid.risk.kill_switches import risk_controller as _rc
        eb = _rc.get_error_budget_metrics()
        result["error_budget_used"] = eb.get("error_count", 0)
        result["error_budget_threshold"] = eb.get("error_threshold", 50)
        result["error_budget_pct"] = round(eb.get("budget_used_pct", 0.0), 1)
    except Exception as _e:
        logger.debug("global_risk_status: error budget lookup failed: %s", _e)

    # --- Halt flags / kill switch ---------------------------------------
    try:
        from merid.risk.kill_switches import risk_controller as _rc
        rc_status = _rc.get_status()
        result["drawdown_halt_active"] = bool(rc_status.get("drawdown_halt_active", False))
        result["kill_switch_active"] = bool(rc_status.get("kill_switch_active", False))
        result["kill_switch_reason"] = rc_status.get("kill_reason")
    except Exception as _e:
        logger.debug("global_risk_status: kill switch lookup failed: %s", _e)

    try:
        from core.automated_risk_controls import get_risk_coordinator
        coord = get_risk_coordinator()
        result["manual_halt_active"] = bool(coord.halt_manager.is_halted)
    except Exception as _e:
        logger.debug("global_risk_status: manual halt lookup failed: %s", _e)

    return result


@router.get("/risk/state-transitions")
async def get_risk_state_transitions(limit: int = Query(50, ge=1, le=200)) -> Dict[str, Any]:
    """Return the most recent risk state transition log entries.

    Entries are added by the backend whenever zone, profit-lock state,
    drawdown halt, or kill-switch state changes.  The buffer holds up to
    200 entries (FIFO ring buffer).
    """
    entries = list(_STATE_TRANSITIONS)[-limit:]
    entries.reverse()  # newest first

    # Supplement with live state so the UI always has at least one entry
    if not entries:
        try:
            from merid.risk.drawdown_zones import get_drawdown_zone_manager
            dzm = get_drawdown_zone_manager()
            dz = dzm.get_status()
            entries.append({
                "ts": _dt_mod.datetime.now(_dt_mod.timezone.utc).isoformat(),
                "event_type": "current_state",
                "detail": f"Zone: {dz.get('current_zone', 'green').upper()} "
                          f"(DD {dz.get('current_drawdown_pct', 0.0):.1f}%)",
            })
        except Exception:
            pass

    return {"transitions": entries, "total": len(_STATE_TRANSITIONS)}


@router.get("/risk/effective-config")
async def get_effective_risk_config() -> Dict[str, Any]:
    """Return the live effective risk configuration (read-only mirror).

    Exposes drawdown thresholds, profit-lock settings, kill-switch params,
    and CT time-boxing config so operators never need to grep YAML.
    """
    cfg: Dict[str, Any] = {
        "drawdown": {
            "green_pct": 10.0,
            "soft_pct": 15.0,
            "hard_pct": 20.0,
            "halt_pct": 20.0,
            "multipliers": {
                "green": 1.0,
                "yellow": 0.625,
                "orange": 0.30,
                "red": 0.0,
            },
        },
        "profit_lock": {
            "lock_fraction": 0.60,
            "max_giveback_fraction": 0.40,
            "caution_threshold": 0.50,
            "states": {
                "safe": {"multiplier": 1.0, "description": "Full sizing"},
                "caution": {"multiplier": 0.5, "description": "50% sizing"},
                "frozen": {"multiplier": 0.0, "description": "No new entries"},
            },
        },
        "kill_switch": {
            "error_budget_threshold": 50,
            "dedup_window_secs": 60.0,
            "warn_pct": 0.70,
            "limit_pct": 0.90,
            "exempt_classes": [],
            "note": "Drawdown rejects do NOT consume error budget",
        },
        "ct_timebox": {
            "taper_start_minutes_before_expiry": 2.0,
            "expired_skip": True,
            "description": "CT orders skip if market expires in < 2 min",
        },
    }

    # Override from live objects when available
    try:
        from merid.risk.drawdown_zones import get_drawdown_zone_manager
        dzm = get_drawdown_zone_manager()
        dz_status = dzm.get_status()
        thresholds = dz_status.get("thresholds", {})
        mults = dz_status.get("multipliers", {})
        cfg["drawdown"]["green_pct"] = round(thresholds.get("green_pct", 0.10) * 100, 1)
        cfg["drawdown"]["soft_pct"] = round(thresholds.get("soft_pct", 0.15) * 100, 1)
        cfg["drawdown"]["hard_pct"] = round(thresholds.get("hard_pct", 0.20) * 100, 1)
        cfg["drawdown"]["halt_pct"] = cfg["drawdown"]["hard_pct"]
        cfg["drawdown"]["multipliers"]["green"] = mults.get("green", 1.0)
        cfg["drawdown"]["multipliers"]["yellow"] = mults.get("yellow", 0.625)
        cfg["drawdown"]["multipliers"]["orange"] = mults.get("orange", 0.30)
        cfg["drawdown"]["multipliers"]["red"] = mults.get("red", 0.0)
    except Exception as _e:
        logger.debug("effective_config: drawdown zone config lookup failed: %s", _e)

    try:
        from merid.risk.profit_lock import get_profit_lock_engine
        pl = get_profit_lock_engine()
        cfg["profit_lock"]["lock_fraction"] = pl.lock_fraction
        cfg["profit_lock"]["max_giveback_fraction"] = pl.max_giveback_fraction
        cfg["profit_lock"]["caution_threshold"] = pl.caution_threshold
    except Exception as _e:
        logger.debug("effective_config: profit lock config lookup failed: %s", _e)

    try:
        from merid.risk.kill_switches import risk_controller as _rc
        cfg["kill_switch"]["error_budget_threshold"] = _rc.error_threshold
        cfg["kill_switch"]["dedup_window_secs"] = float(getattr(_rc, "dedup_window_secs", 60.0))
        exempt = list(getattr(_rc, "error_exempt_classes", set()))
        cfg["kill_switch"]["exempt_classes"] = sorted(exempt)
    except Exception as _e:
        logger.debug("effective_config: kill switch config lookup failed: %s", _e)

    try:
        from merid.event_venues.kalshi.kalshi_risk import KalshiRiskManager
        cfg["ct_timebox"]["taper_start_minutes_before_expiry"] = getattr(
            KalshiRiskManager, "CT_TAPER_MINUTES", 2.0
        )
    except Exception:
        pass

    return cfg


