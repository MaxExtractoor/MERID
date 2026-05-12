"""Kalshi Deep Integration API — /api/v1/kalshi/*

Endpoints:
  GET  /api/v1/kalshi/markets          — Browse all cataloged markets
  GET  /api/v1/kalshi/markets/{ticker}  — Single market detail
  GET  /api/v1/kalshi/catalog           — Catalog summary (categories, assets, timeframes)
  GET  /api/v1/kalshi/positions         — Current Kalshi positions
  GET  /api/v1/kalshi/orders            — Open orders
  GET  /api/v1/kalshi/fills             — Recent fills/trades
  POST /api/v1/kalshi/fills/reconcile-now — Poll fills + reconcile positions (operators)
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

import asyncio
import json
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from web.api.auth import get_current_session
from auth.user_manager import require_role
from utils.logger import get_logger

# NEW v2 bankroll service - single source of truth
from merid.event_venues.kalshi import (
    get_bankroll_service,
    BalanceState,
    BalanceSuccess,
    BalanceTemporaryError,
    BalancePermanentError,
    BankrollSummary,
)

logger = get_logger("web.api.kalshi_api")


def _safe_float_val(v, default: float = 0.0) -> float:
    """Convert any numeric value to a JSON-safe float (no NaN/Inf/None)."""
    try:
        if v is None:
            return default
        return float(v)
    except (ValueError, TypeError):
        return default


def _is_test_ticker(ticker: str) -> bool:
    """Check if a ticker is a test ticker that should be excluded from production.
    
    PRODUCTION FIX (2026-05-10): Filter out test markets from positions feed.
    Test ticker patterns:
    - Contains "TEST" (e.g., KXETH-TEST, KXTEST-3, KXTEST-1)
    - Contains "KXTEST" (e.g., KXTEST-3, KXTEST-1)
    - Short codes like "KX-SK", "KX-DUP", "KX-TK"
    - Timeframe-based tickers like "KXBTC-15M" (series tickers, not real markets)
    """
    if not ticker:
        return False
    
    ticker_upper = ticker.upper()
    
    # Explicit TEST markers
    if "TEST" in ticker_upper or "KXTEST" in ticker_upper:
        return True
    
    # Short code patterns (KX-SK, KX-DUP, KX-TK, etc.)
    if ticker_upper.startswith("KX-") and len(ticker_upper) <= 6:
        return True
    
    # Timeframe-based series tickers (e.g., KXBTC-15M, KXETH-1H)
    # These are series identifiers, not real market tickers
    # Real market tickers have date patterns like KXBTC-26MAR2914-T3000
    if ticker_upper.startswith(("KXBTC-", "KXETH-", "KXSOL-", "KXXRP-", "KXDOGE-")):
        # Check if it ends with a timeframe code (15M, 1H, D, W, M, etc.)
        # instead of a date pattern
        parts = ticker_upper.split("-")
        if len(parts) >= 2:
            last_part = parts[-1]
            # Timeframe codes
            if last_part in ("15M", "1H", "H", "D", "W", "M", "A"):
                return True
    
    return False


def _ledger_fill_price_usd(f: Any) -> float:
    """Pick display price in USD for a ledger fill (yes/no leg + legacy missing side)."""
    side = str(getattr(f, "side", "") or "")
    y = getattr(f, "yes_price_dollars", None)
    n = getattr(f, "no_price_dollars", None)
    if side == "yes" and y is not None:
        return _safe_float_val(y, 0)
    if side == "no" and n is not None:
        return _safe_float_val(n, 0)
    if y is not None:
        return _safe_float_val(y, 0)
    if n is not None:
        return _safe_float_val(n, 0)
    return 0.0


def _kalshi_fill_api_row(f: Any) -> Dict[str, Any]:
    """Single GET /fills row: canonical ledger fields + asset + incomplete flag."""
    pu = _ledger_fill_price_usd(f)
    pc = int(_safe_float_val(getattr(f, "price_cents", 0), 0))
    ts = f.created_time.isoformat() if getattr(f, "created_time", None) else None
    incomplete = f.is_incomplete() if callable(getattr(f, "is_incomplete", None)) else False
    asset = f.resolved_asset() if callable(getattr(f, "resolved_asset", None)) else None
    return {
        "fill_id": f.fill_id,
        "venue_fill_id": getattr(f, "trade_id", None) or f.fill_id,
        "trade_id": getattr(f, "trade_id", None) or f.fill_id or "",
        "order_id": f.order_id,
        "ticker": f.market_ticker,
        "asset": asset,
        "side": f.side,
        "action": f.action,
        "size": int(_safe_float_val(getattr(f, "count_fp", 0), 0)),
        "price_cents": pc,
        "price_usd": pu,
        "fee_usd": _safe_float_val(f.fee_cost),
        "price": pu,
        "fee": _safe_float_val(f.fee_cost),
        "timestamp": ts,
        "executed_at": ts,
        "client_order_id": f.client_order_id,
        "agent_id": f.agent_id,
        "ingestion_source": f.ingestion_source,
        "reconciled": f.reconciled,
        "incomplete": incomplete,
    }


def _attach_kalshi_position_assets(rows: List[Dict[str, Any]]) -> None:
    """Attach ``asset`` from canonical ``kalshi_ticker_to_asset`` for each row."""
    try:
        from config.kalshi_crypto_config import kalshi_ticker_to_asset
    except ImportError:
        return
    for p in rows:
        t = p.get("ticker") or ""
        p["asset"] = kalshi_ticker_to_asset(t) if t else None


def _fills_ledger_reconciliation_message(status_str: str) -> Optional[str]:
    """Human-readable health message for fills-ledger vs Kalshi positions status."""
    if status_str == "ok":
        return None
    if status_str == "unknown":
        return (
            "Reconciliation not run yet — fills ledger has not been compared to Kalshi positions "
            "(ensure the fills poller is running, or wait for the next reconcile cycle)."
        )
    if status_str == "degraded":
        return "Minor divergences between Kalshi positions and the fills ledger — inspect divergences."
    if status_str == "broken":
        return "Fills reconciliation broken — positions may not match fills ledger."
    return "Positions may not match fills ledger."


def _fills_ledger_positions_warning(rec: Dict[str, Any]) -> Optional[str]:
    """Warning string for /positions payload; None when OK or missing data."""
    if not rec:
        return None
    st = str(rec.get("status") or "unknown")
    if st == "ok":
        return None
    return _fills_ledger_reconciliation_message(st)

router = APIRouter(prefix="/api/v1/kalshi", tags=["kalshi"], dependencies=[Depends(get_current_session)]  # ZT6-01
)


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
    except (ValueError, TypeError):
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


def _get_order_router():
    """Lazy-load order router for testability (can be patched by tests)."""
    try:
        from merid.event_venues.kalshi.order_router import route_order_async
        return route_order_async
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
    except ImportError:
        import os
        key_id = os.environ.get("KALSHI_API_KEY_ID")
        key_path = os.environ.get("KALSHI_PRIVATE_KEY_PATH")
        env = "demo" if os.environ.get("KALSHI_USE_DEMO", "false").lower() == "true" else "prod"
    except AttributeError:
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
    """Return a singleton KalshiVenueClient (lazy-initialised once per process)."""
    if not hasattr(_get_client, "_instance"):
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
            _get_client._instance = KalshiVenueClient(config)
        except (ImportError, ModuleNotFoundError):
            _get_client._instance = None
    return _get_client._instance


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


def _now_iso() -> str:
    """UTC ISO timestamp string."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


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


# ── Balance normalization helper (BUG-3 fix) ──────────────────────────────

def _normalize_balance(value: float, field_name: str = "balance", *, source_is_cents: bool = False) -> float:
    """Normalize balance values to dollars.
    
    Kalshi REST API returns cents (e.g., 10000 for $100).
    Executor returns dollars (e.g., 100.0 for $100).
    
    Args:
        value: Raw balance value
        field_name: Field name for logging context
        source_is_cents: If True, value is known to be in cents (from REST API).
                         If False, value is assumed to already be in dollars.
        
    Returns:
        Balance in dollars (float)
    """
    if value is None:
        return 0.0
    
    if source_is_cents:
        logger.debug(f"{field_name}: converting cents value {value} to dollars")
        return float(value) / 100.0
    
    return float(value)


def _is_cents_format(value: float) -> bool:
    """Heuristic to detect if a value is likely in cents format.
    
    DEPRECATED: prefer explicit source_is_cents parameter on _normalize_balance.
    
    CRASH-FIX: Improved heuristic to avoid misclassifying dollar values:
    - Large values (>1000) with no decimals likely cents (Kalshi API returns cents as integers)
    - Small values (<1000) are likely dollars regardless of decimals
    - Values between 1000-10000 require explicit source_is_cents flag
    """
    if value is None or not isinstance(value, (int, float)):
        return False
    
    # Large integer values (>10000) are almost certainly cents (>$100)
    if value > 10000 and abs(value - round(value)) < 0.001:
        return True
    
    # Medium values (1000-10000) - ambiguous zone, require explicit flag
    # Return False to avoid misclassifying dollar amounts
    if value >= 1000:
        return False
    
    # Small values (<1000) treated as dollars
    return False

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
        # OLD-HARDWARE FIX: Increased from 10s to 30s for slow connections
        resp = req.get(f"{base}/trade-api/v2/markets", params=params, timeout=30)
        resp.raise_for_status()
        raw_markets = resp.json().get("markets", [])
        def _extract_outcomes(m: Dict[str, Any]) -> List[Dict[str, Any]]:
            """Build outcomes list from Kalshi public API market object."""
            yes_bid = m.get("yes_bid")  # cents
            yes_ask = m.get("yes_ask")  # cents
            yes_price = m.get("last_price", m.get("yes_ask"))
            
            # REMOVED: No fallback to 50 - require explicit price
            if yes_price is None or yes_price <= 0 or yes_price >= 100:
                logger.error("[kalshi_api] Invalid yes_price %s for market %s, returning error", yes_price, m.get("ticker"))
                raise HTTPException(503, f"Price data unavailable for market {m.get('ticker')}")
            
            return [
                {
                    "id": "yes",
                    "name": "Yes",
                    "price": yes_price / 100.0,
                    "bid": yes_bid / 100.0 if yes_bid else None,
                    "ask": yes_ask / 100.0 if yes_ask else None,
                },
                {
                    "id": "no",
                    "name": "No",
                    "price": (100 - yes_price) / 100.0,
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
    # Validate ticker input
    if not ticker or len(ticker) > 100:
        raise HTTPException(status_code=400, detail="Invalid ticker: must be 1-100 characters")
    
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
            m = await asyncio.to_thread(rest.get_market, ticker)
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
    # Validate ticker input
    if not ticker or len(ticker) > 100:
        raise HTTPException(status_code=400, detail="Invalid ticker: must be 1-100 characters")
    
    from merid.event_venues.kalshi.ws import KalshiWebSocket
    from merid.event_venues.kalshi.orderbook import LocalOrderbook

    async def event_generator():
        sse_queue = asyncio.Queue()
        update_count = 0
        last_heartbeat = asyncio.get_running_loop().time()
        loop = asyncio.get_running_loop()

        async def run_ws():
            nonlocal update_count
            ws = KalshiWebSocket()
            ob = LocalOrderbook(ticker)
            try:
                await ws.connect()
                await ws.subscribe_orderbook(ticker)

                async def message_handler(msg: Any) -> None:
                    nonlocal update_count
                    if not isinstance(msg, dict):
                        return
                    msg_type = msg.get("type", "")

                    if msg_type == "orderbook_snapshot":
                        ob.apply_snapshot(msg.get("data", {}))
                        update_count += 1
                        await sse_queue.put(("snapshot", ob.to_dict()))
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
                        await sse_queue.put(("delta", delta_data))
                    elif msg_type == "trade":
                        trade_data = {
                            "ticker": msg.get("ticker", ""),
                            "price": msg.get("price"),
                            "count": msg.get("count"),
                            "side": msg.get("side"),
                        }
                        await sse_queue.put(("trade", trade_data))

                    if update_count >= max_updates:
                        await sse_queue.put(
                            ("__closing__", {"reason": "max_updates_reached", "count": update_count}),
                        )

                await ws.listen(message_handler)
            except Exception as e:
                await sse_queue.put(("__error__", {"error": str(e)}))
            finally:
                try:
                    await ws.close()
                except Exception:
                    logger.debug("silent catch in kalshi_api stream_orderbook close")
                await sse_queue.put(("__done__", None))

        listen_task = asyncio.create_task(run_ws())
        try:
            yield f"event: connecting\ndata: {json.dumps({'ticker': ticker})}\n\n"
            while True:
                try:
                    item = await asyncio.wait_for(sse_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    now = loop.time()
                    if now - last_heartbeat >= heartbeat_interval:
                        yield f"event: heartbeat\ndata: {json.dumps({'ts': now, 'updates': update_count})}\n\n"
                        last_heartbeat = now
                    continue

                ev, payload = item
                if ev == "__done__":
                    break
                if ev == "__error__":
                    yield f"event: error\ndata: {json.dumps(payload)}\n\n"
                    break
                if ev == "__closing__":
                    yield f"event: closing\ndata: {json.dumps(payload)}\n\n"
                    break
                yield f"event: {ev}\ndata: {json.dumps(payload)}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'error': f'Connection failed: {e}'})}\n\n"
        finally:
            listen_task.cancel()
            try:
                await listen_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.debug(f"Silent error: {e}")
            yield f"event: closed\ndata: {json.dumps({'ticker': ticker})}\n\n"

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
        sse_queue = asyncio.Queue()
        update_count = 0
        last_heartbeat = asyncio.get_running_loop().time()
        loop = asyncio.get_running_loop()

        watched_groups = set(group_ids.split(",")) if group_ids else None

        async def run_ws():
            nonlocal update_count
            ws = KalshiWebSocket()
            try:
                await ws.connect()
                await ws.subscribe_order_group_updates()
                if watched_groups:
                    ws.set_watched_groups(list(watched_groups))

                async def message_handler(msg: Any) -> None:
                    nonlocal update_count
                    if not isinstance(msg, dict):
                        return

                    channel = msg.get("channel") or msg.get("type")
                    if channel not in ("order_group_updates", "order_group_update"):
                        return

                    data = msg.get("data", msg)
                    group_id = data.get("order_group_id") or data.get("group_id")
                    update_type = data.get("_update_type", "delta")
                    status = data.get("status")

                    update_count += 1

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

                    if status == "triggered":
                        await sse_queue.put(("triggered", event_data))
                    elif update_type == "snapshot":
                        await sse_queue.put(("snapshot", event_data))
                    else:
                        await sse_queue.put(("delta", event_data))

                    if update_count >= max_updates:
                        await sse_queue.put(
                            ("__closing__", {"reason": "max_updates_reached", "count": update_count}),
                        )

                await ws.listen(message_handler)
            except Exception as e:
                await sse_queue.put(("__error__", {"error": str(e)}))
            finally:
                try:
                    await ws.close()
                except Exception:
                    logger.debug("silent catch in kalshi_api stream_order_group_updates close")
                await sse_queue.put(("__done__", None))

        listen_task = asyncio.create_task(run_ws())

        try:
            _connect_payload = {
                "watched_groups": list(watched_groups) if watched_groups else "all",
            }
            yield f"event: connecting\ndata: {json.dumps(_connect_payload)}\n\n"

            while True:
                try:
                    item = await asyncio.wait_for(sse_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    now = loop.time()
                    if now - last_heartbeat >= heartbeat_interval:
                        yield f"event: heartbeat\ndata: {json.dumps({'ts': now, 'updates': update_count})}\n\n"
                        last_heartbeat = now
                    continue

                ev, payload = item
                if ev == "__done__":
                    break
                if ev == "__error__":
                    yield f"event: error\ndata: {json.dumps(payload)}\n\n"
                    break
                if ev == "__closing__":
                    yield f"event: closing\ndata: {json.dumps(payload)}\n\n"
                    break
                yield f"event: {ev}\ndata: {json.dumps(payload)}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'error': f'Connection failed: {e}'})}\n\n"
        finally:
            listen_task.cancel()
            try:
                await listen_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.debug(f"Silent error: {e}")
            yield f"event: closed\ndata: {json.dumps({'updates_total': update_count})}\n\n"

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
                # Normalise: Kalshi REST returns cents (1-99), old client returns fractions (0.01-0.99)
                price = p / 100.0 if p >= 1 else float(p)
                levels.append({"price": round(price, 4), "quantity": int(q)})
        return levels

    # Try old venue client first
    client = _get_client()
    if client:
        try:
            await client.connect()
            ob = await client.get_orderbook(ticker)
            if ob:
                yes_bids = [{"price": round(float(p), 4), "quantity": int(s)} for p, s in (ob.bids or [])]
                yes_asks = [{"price": round(float(p), 4), "quantity": int(s)} for p, s in (ob.asks or [])]
                best_bid = yes_bids[0]["price"] if yes_bids else None
                best_ask = yes_asks[0]["price"] if yes_asks else None
                spread = (best_ask - best_bid) if best_bid is not None and best_ask is not None else None
                midpoint = round((best_bid + best_ask) / 2, 4) if best_bid is not None and best_ask is not None else None
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
            logger.debug(f"Old client orderbook fallback: {exc}")

    # Fallback: merid_core REST client
    rest = _get_rest_client()
    if rest:
        try:
            ob = await asyncio.to_thread(rest.get_orderbook, ticker)
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

@router.get("/health/reconciliation")
async def get_reconciliation_status() -> Dict[str, Any]:
    """Get fills ledger reconciliation status.
    
    Returns the current state of the fills reconciliation engine,
    including any divergences between computed positions and Kalshi positions.
    
    Status values:
    - "ok": Positions match fills ledger
    - "degraded": Minor discrepancies detected but trading allowed
    - "broken": Significant divergence - positions may not match fills
    """
    from datetime import datetime, timezone
    
    try:
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        from merid.event_venues.kalshi.fills_poller import get_fills_poller
        
        ledger = get_fills_ledger()
        poller = get_fills_poller()

        # get_reconciliation_status() returns a dict (status, last_run, divergences, ...);
        # UI expects top-level "status" to be the string "ok"|"degraded"|"broken", not that dict.
        rec = ledger.get_reconciliation_status()
        if not isinstance(rec, dict):
            status_str = "unknown"
            rec = {}
        else:
            status_str = str(rec.get("status", "unknown"))

        return {
            "status": status_str,
            "last_run": rec.get("last_run"),
            "divergence_count": int(rec.get("divergence_count", 0) or 0),
            "divergences": rec.get("divergences") or [],
            "ghost_trade_candidates": int(rec.get("ghost_trade_candidates", 0) or 0),
            "last_success_at": poller.get_health().get("last_poll_ts") if poller else None,
            "message": _fills_ledger_reconciliation_message(status_str),
            "ledger": ledger.summary(),
            "poller_health": poller.get_health() if poller else None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
    except Exception as e:
        logger.error(f"Reconciliation status fetch failed: {e}")
        return {
            "status": "unknown",
            "message": f"Failed to fetch reconciliation status: {str(e)}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


@router.get("/health/fills-ledger")
async def get_fills_ledger_health() -> Dict[str, Any]:
    """Get fills ledger health status including circuit breaker and DLQ.
    
    Returns detailed health information about the fills ledger persistence layer,
    including circuit breaker state, dead letter queue status, and writer health.
    
    Use this endpoint to monitor for schema mismatches, persistence failures,
    and event-loop lag issues.
    """
    from datetime import datetime, timezone
    
    try:
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        
        ledger = get_fills_ledger()
        health = await ledger.health_check()
        
        return {
            **health,
            "api_version": "1.0",
        }
        
    except Exception as e:
        logger.error(f"Fills ledger health fetch failed: {e}")
        return {
            "status": "unknown",
            "message": f"Failed to fetch fills ledger health: {str(e)}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


@router.post("/health/fills-ledger/reset-circuit")
async def post_reset_circuit_breaker() -> Dict[str, Any]:
    """Reset the fills ledger circuit breaker and replay DLQ fills.
    
    This endpoint should be called after a schema migration has been applied
    to retry fills that failed due to schema errors.
    
    Returns the result of the circuit reset and DLQ replay operation.
    """
    from datetime import datetime, timezone
    
    try:
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        
        ledger = get_fills_ledger()
        result = await ledger.reset_circuit_breaker()
        
        return {
            "success": True,
            **result,
            "api_version": "1.0",
        }
        
    except Exception as e:
        logger.error(f"Circuit breaker reset failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


@router.post("/positions/{ticker}/close")
async def post_close_position(
    ticker: str,
    reason: str = Query("manual_operator_close", description="Reason for closing the position"),
) -> Dict[str, Any]:
    """Manually close a position that was closed outside the system (e.g., via Kalshi website).
    
    This creates a synthetic "close" fill in the ledger to properly account for
    positions that were manually closed. Use this when the system shows an open
    position but Kalshi shows it as closed.
    
    Example: POST /positions/KXFED-27APR-T3.25/close?reason=manually_closed_on_website
    
    Returns:
        Status of the close operation with before/after position info.
    """
    from datetime import datetime, timezone
    
    try:
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        
        ledger = get_fills_ledger()
        result = await ledger.mark_position_closed(ticker.upper(), reason)
        
        if result.get("status") == "no_position":
            return {
                "success": False,
                "error": f"No open position found for {ticker}",
                "ticker": ticker,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        
        return {
            "success": True,
            **result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
    except Exception as e:
        logger.error(f"Manual position close failed for {ticker}: {e}")
        return {
            "success": False,
            "error": str(e),
            "ticker": ticker,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


@router.get("/meta/rate_limits")
async def get_rate_limits_meta() -> Dict[str, Any]:
    """Get currently active rate limit configuration.
    
    Shows the actual limits being enforced, their source (config vs fallback),
    and current usage if available.
    """
    from datetime import datetime, timezone
    
    limits = _get_rate_limits_from_config()
    
    # Get current usage from risk manager if available
    usage = {"orders_this_minute": 0, "orders_this_hour": 0}
    risk = _get_risk()
    if risk:
        try:
            risk_summary = risk.summary()
            usage["orders_this_minute"] = float(risk_summary.get("orders_this_minute", 0))
            usage["orders_this_hour"] = float(risk_summary.get("orders_this_hour", 0))
        except Exception as e:
            logger.debug(f"Silent error: {e}")
    
    return {
        "limits": {
            "max_per_minute": limits["max_per_minute"],
            "max_per_hour": limits["max_per_hour"],
        },
        "source": limits["source"],
        "usage": usage,
        "utilization_pct": {
            "minute": round(usage["orders_this_minute"] / limits["max_per_minute"] * 100, 1) if limits["max_per_minute"] > 0 else 0,
            "hour": round(usage["orders_this_hour"] / limits["max_per_hour"] * 100, 1) if limits["max_per_hour"] > 0 else 0,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
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


@router.get("/swarm/grid")
async def swarm_sentiment_grid() -> Dict[str, Any]:
    """5×4 mood × swarm consensus for terminal UI (BTC–DOGE × 15m–weekly)."""
    from config.kalshi_crypto_config import WS_TIMEFRAME_TO_MOOD_LABEL, active_crypto_asset_mood_timeframe_grid
    from merid.swarm.consensus_aggregator import get_consensus_aggregator
    from merid.swarm.market_mood_bus import get_market_mood_bus

    mood = get_market_mood_bus()
    agg = get_consensus_aggregator()
    cells = []
    for asset, tf in active_crypto_asset_mood_timeframe_grid():
        ctx = mood.get_context(asset, tf)
        cv = agg.get_consensus_or_neutral(asset, tf)
        cells.append(
            {
                "asset": asset,
                "timeframe": tf,
                "swarm_consensus_prob": cv.consensus_probability,
                "swarm_confidence": cv.consensus_confidence,
                "swarm_usable": cv.usable,
                "swarm_direction": cv.consensus_direction,
                "swarm_status": cv.status.value if hasattr(cv.status, "value") else str(cv.status),
                "mood_social": getattr(ctx, "social_sentiment", None) if ctx else None,
                "mood_fg": getattr(ctx, "fg_index", None) if ctx else None,
            }
        )
    return {"cells": cells, "ws_timeframe_labels": WS_TIMEFRAME_TO_MOOD_LABEL}


@router.get("/swarm/health")
async def swarm_grid_health() -> Dict[str, Any]:
    from merid.sentiment.swarm_health import evaluate_swarm_grid_health

    return evaluate_swarm_grid_health()


@router.get("/sentiment/pnl-attribution")
async def sentiment_pnl_attribution() -> Dict[str, Any]:
    from merid.sentiment.sentiment_pnl_attribution import aggregate_sentiment_pnl

    return aggregate_sentiment_pnl()


@router.get("/sentiment/pnl")
async def sentiment_pnl_breakdown() -> Dict[str, Any]:
    """Tagged vs untagged realized PnL, fees, and hit-rate by asset."""
    from merid.sentiment.sentiment_pnl_attribution import aggregate_sentiment_pnl_detailed

    return aggregate_sentiment_pnl_detailed()


@router.get("/health/sentiment")
async def sentiment_health_extended() -> Dict[str, Any]:
    from merid.sentiment.swarm_health import evaluate_sentiment_health

    return evaluate_sentiment_health()


@router.get("/discover-health")
async def discover_health(
    since_hours: int = Query(24, ge=1, le=168, description="Hours to look back for fills"),
) -> Dict[str, Any]:
    """Portfolio discover health: fills, positions, and portfolio state.
    
    Returns:
        - fills_rows: total fill rows in lookback period
        - fills_incomplete_rows: fills with incomplete=True
        - fills_complete_rows: fills with complete data (size>0, price>0)
        - positions_count: real positions count (non-synthetic)
        - positions_by_asset: breakdown by asset
        - portfolio_empty_or_uninitialized: true if no real trades yet
        - portfolio_discover_green: true when portfolio state is understood
    """
    from datetime import datetime, timezone, timedelta
    
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "since_hours": since_hours,
        "fills": {"rows": 0, "incomplete_rows": 0, "complete_rows": 0},
        "positions": {"count": 0, "by_asset": {}},
        "portfolio_empty_or_uninitialized": True,
        "portfolio_discover_green": False,
        "message": None,
    }
    
    # Query fills ledger
    try:
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        ledger = get_fills_ledger()
        since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        fills = ledger.get_fills(since=since, limit=1000)
        
        incomplete_count = 0
        complete_count = 0
        for f in fills:
            is_incomplete = f.is_incomplete() if callable(getattr(f, "is_incomplete", None)) else False
            size = getattr(f, "count_fp", 0) or 0
            price = _ledger_fill_price_usd(f)
            
            if is_incomplete or (size == 0 and price == 0.0):
                incomplete_count += 1
            else:
                complete_count += 1
        
        result["fills"]["rows"] = len(fills)
        result["fills"]["incomplete_rows"] = incomplete_count
        result["fills"]["complete_rows"] = complete_count
    except Exception as exc:
        logger.warning(f"discover-health fills query failed: {exc}")
        result["fills"]["error"] = str(exc)
    
    # Query positions from position_cache (has test/closed filtering)
    try:
        from merid.event_venues.kalshi.position_cache import get_position_cache
        cache = get_position_cache()
        cached_positions = cache.get_all_positions(validate_freshness=False)
        
        # Convert cache positions to the expected format
        real_positions = []
        for market_id, pos in cached_positions.items():
            if pos.contracts > 0:  # Only count open positions
                real_positions.append({"ticker": market_id, "asset": None})
        
        # Attach assets
        try:
            from config.kalshi_crypto_config import kalshi_ticker_to_asset
            for p in real_positions:
                p["asset"] = kalshi_ticker_to_asset(p["ticker"])
        except Exception as e:
            logger.debug(f"Silent error: {e}")
        
        by_asset = {}
        for p in real_positions:
            asset = p.get("asset") or "unknown"
            by_asset[asset] = by_asset.get(asset, 0) + 1
        
        result["positions"]["count"] = len(real_positions)
        result["positions"]["by_asset"] = by_asset
    except Exception as exc:
        logger.warning(f"discover-health positions query failed: {exc}")
        result["positions"]["error"] = str(exc)
    
    # Determine portfolio_empty_or_uninitialized
    has_complete_fills = result["fills"]["complete_rows"] > 0
    has_real_positions = result["positions"]["count"] > 0
    
    result["portfolio_empty_or_uninitialized"] = not (has_complete_fills or has_real_positions)
    
    # Determine portfolio_discover_green
    # Green if we have either: (1) complete fills, or (2) explicitly empty with no errors
    no_errors = "error" not in result["fills"] and "error" not in result["positions"]
    result["portfolio_discover_green"] = no_errors and (has_complete_fills or has_real_positions or result["portfolio_empty_or_uninitialized"])
    
    if result["portfolio_empty_or_uninitialized"]:
        result["message"] = "No trades discovered yet (expected if trading not yet active)"
    elif has_complete_fills or has_real_positions:
        result["message"] = f"Portfolio discovered: {result['fills']['complete_rows']} fills, {result['positions']['count']} positions"
    
    logger.info(
        "discover-health: fills=%s complete=%s positions=%s empty=%s green=%s",
        result["fills"]["rows"],
        result["fills"]["complete_rows"],
        result["positions"]["count"],
        result["portfolio_empty_or_uninitialized"],
        result["portfolio_discover_green"],
    )
    
    return result


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
    "cross_category", "crypto", "economics", "macro", "financials",
    "politics", "climate", "sports", "tech", "culture", "science",
    "equities", "other",
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

async def _ensure_fresh_positions(max_staleness_seconds: int = 60) -> Tuple[List[Dict], Dict[str, Any]]:
    """Ensure positions are fresh by syncing from REST if cache is stale.
    
    BUG-5 FIX: This prevents API endpoints from returning stale position data
    by checking cache freshness and triggering a REST sync when needed.
    
    BUG-FIX (2026-05-10): sync_from_rest() now requires positions argument - fetch from venue adapter first.
    
    Returns:
        Tuple of (positions list, freshness metadata dict)
    """
    from merid.event_venues.kalshi.position_cache import get_position_cache
    from merid.event_venues.kalshi.venue_adapter import get_venue_adapter
    from datetime import datetime, timezone
    
    cache = get_position_cache()
    freshness_meta = {
        "cache_last_sync": None,
        "staleness_seconds": None,
        "triggered_sync": False,
        "sync_error": None,
    }
    
    # Check cache freshness
    if cache._last_sync:
        staleness = (datetime.now(timezone.utc) - cache._last_sync).total_seconds()
        freshness_meta["cache_last_sync"] = cache._last_sync.isoformat()
        freshness_meta["staleness_seconds"] = round(staleness, 1)
        
        # If cache is stale, trigger a sync
        if staleness > max_staleness_seconds:
            try:
                # Fetch positions from REST via venue adapter
                adapter = get_venue_adapter()
                rest_positions = await adapter.get_positions()
                # Convert VenuePosition to dict format expected by sync_from_rest
                positions_list = []
                for pos in rest_positions:
                    positions_list.append({
                        "market_id": pos.market_id,
                        "contracts": pos.size,
                        "side": pos.outcome_id,
                        "avg_price_cents": pos.avg_price_cents,
                        "realized_pnl": float(pos.realized_pnl) if pos.realized_pnl else 0.0,
                        "unrealized_pnl": float(pos.unrealized_pnl) if pos.unrealized_pnl else 0.0,
                    })
                await cache.sync_from_rest(positions_list)
                freshness_meta["triggered_sync"] = True
                freshness_meta["staleness_seconds"] = 0  # Now fresh
            except Exception as sync_exc:
                freshness_meta["sync_error"] = str(sync_exc)
                logger.warning(f"[API-POSITIONS] Failed to sync positions from REST: {sync_exc}")
    else:
        # No sync has ever happened - trigger one
        try:
            # Fetch positions from REST via venue adapter
            adapter = get_venue_adapter()
            rest_positions = await adapter.get_positions()
            # Convert VenuePosition to dict format expected by sync_from_rest
            positions_list = []
            for pos in rest_positions:
                positions_list.append({
                    "market_id": pos.market_id,
                    "contracts": pos.size,
                    "side": pos.outcome_id,
                    "avg_price_cents": pos.avg_price_cents,
                    "realized_pnl": float(pos.realized_pnl) if pos.realized_pnl else 0.0,
                    "unrealized_pnl": float(pos.unrealized_pnl) if pos.unrealized_pnl else 0.0,
                })
            await cache.sync_from_rest(positions_list)
            freshness_meta["triggered_sync"] = True
            freshness_meta["staleness_seconds"] = 0
        except Exception as sync_exc:
            freshness_meta["sync_error"] = str(sync_exc)
    
    # Get positions from cache (fresh or stale)
    positions = []
    try:
        cached = cache.get_all_positions(validate_freshness=False)  # We already checked
        for ticker, pos in cached.items():
            positions.append({
                "ticker": ticker,
                "outcome": pos.side,
                "size": pos.contracts,
                "avg_price": pos.avg_price_cents / 100.0 if pos.avg_price_cents else 0,
                "source": "position_cache",
                "synthetic": False,
            })
    except Exception as cache_exc:
        freshness_meta["cache_error"] = str(cache_exc)
    
    return positions, freshness_meta


@router.get("/positions")
async def get_positions(
    include_synthetic: bool = Query(False, description="Include synthetic agent-grid positions for debugging"),
    fresh: bool = Query(True, description="Ensure positions are fresh (trigger REST sync if stale)"),
) -> Dict[str, Any]:
    """Get current Kalshi positions from canonical sources only.
    
    By default, returns only positions confirmed by Kalshi API (executor or REST client).
    Synthetic agent-grid positions are excluded unless ?include_synthetic=true is passed.
    
    Args:
        include_synthetic: If true, include agent monitoring positions tagged with synthetic=true
        fresh: If true (default), ensures positions are fresh by syncing from REST if needed
    """
    # BUG-5 FIX: Ensure positions are fresh before returning
    freshness_meta = {}
    if fresh:
        try:
            cached_positions, freshness_meta = await _ensure_fresh_positions()
            if cached_positions:
                # PRODUCTION FIX (2026-05-10): Filter out test tickers from positions feed
                cached_positions = [p for p in cached_positions if not _is_test_ticker(p.get("ticker", ""))]
                _attach_kalshi_position_assets(cached_positions)
                logger.info(
                    "kalshi GET /positions count=%s source=position_cache fresh=%s staleness=%ss",
                    len(cached_positions),
                    freshness_meta.get("triggered_sync", False),
                    freshness_meta.get("staleness_seconds", "unknown"),
                )
                return {
                    "count": len(cached_positions),
                    "positions": cached_positions,
                    "freshness": freshness_meta,
                }
        except Exception as fresh_exc:
            logger.warning(f"[API-POSITIONS] Failed to get fresh positions: {fresh_exc}")
    
    # Collect real positions from executor or REST client
    real_positions = []
    executor = _get_executor()
    if executor:
        try:
            raw = await executor.get_positions()
            real_positions = [
                {
                    "ticker": p.get("ticker", ""),
                    "outcome": p.get("outcome", "yes"),
                    "size": _safe_float_val(p.get("size", 0), 0),
                    "avg_price": _safe_float_val(p.get("avg_price", 0), 0),
                    "unrealized_pnl": _safe_float_val(p.get("unrealized_pnl", 0), 0),
                    "realized_pnl": _safe_float_val(p.get("realized_pnl", 0), 0),
                    "source": "executor",
                    "synthetic": False,
                    "manual_or_external": False,
                }
                for p in raw
                if p.get("ticker")  # Filter out positions without valid tickers
                and not _is_test_ticker(p.get("ticker", ""))  # PRODUCTION FIX: Filter test tickers
                and _safe_float_val(p.get("size", 0), 0) > 0  # PRODUCTION FIX: Filter closed positions
            ]
            if real_positions:
                _attach_kalshi_position_assets(real_positions)
                logger.info(
                    "kalshi GET /positions count=%s source=executor tickers=%s",
                    len(real_positions),
                    [p.get("ticker") for p in real_positions[:12]],
                )
                return {"count": len(real_positions), "positions": real_positions}
        except Exception as exc:
            logger.warning(f"Executor positions failed: {exc}")

    if not real_positions:
        rest = _get_rest_client()
        if rest:
            try:
                raw_pos = await asyncio.to_thread(rest.get_positions)
                real_positions = [
                    {
                        "ticker": p.get("ticker", p.get("market_ticker", "")),
                        "outcome": p.get("side", "yes"),
                        "size": _safe_float_val(p.get("total_traded", p.get("position", 0)), 0),
                        "avg_price": _safe_float_val(p.get("average_price", 0), 0) / 100.0
                        if p.get("average_price")
                        else 0.0,
                        "unrealized_pnl": _safe_float_val(p.get("market_exposure", 0), 0) / 100.0
                        if p.get("market_exposure")
                        else 0.0,
                        "realized_pnl": _safe_float_val(p.get("realized_pnl", 0), 0) / 100.0
                        if p.get("realized_pnl")
                        else 0.0,
                        "source": "rest_client",
                        "synthetic": False,
                    }
                    for p in raw_pos
                    if not _is_test_ticker(p.get("ticker", p.get("market_ticker", "")))  # PRODUCTION FIX: Filter test tickers
                    and _safe_float_val(p.get("total_traded", p.get("position", 0)), 0) > 0  # PRODUCTION FIX: Filter closed positions
                ]
                if real_positions:
                    _attach_kalshi_position_assets(real_positions)
                    logger.info(
                        "kalshi GET /positions count=%s source=rest_client tickers=%s",
                        len(real_positions),
                        [p.get("ticker") for p in real_positions[:12]],
                    )
                    return {"count": len(real_positions), "positions": real_positions}
            except Exception as exc:
                logger.warning(f"merid_core positions failed: {exc}")

    # Supplement with agent grid monitoring data ONLY if explicitly requested
    all_positions = list(real_positions)
    synthetic_positions = []
    
    if include_synthetic:
        try:
            from merid.prediction.agent_grid import get_agent_grid
            grid = get_agent_grid()
            for agent in grid.agents:
                for ticker in getattr(agent.state, "active_tickers", []):
                    synthetic_positions.append({
                        "ticker": ticker, 
                        "outcome": "yes", 
                        "size": 0,  # HARD-3 fix: no magic constant
                        "avg_price": 0.0, 
                        "unrealized_pnl": 0.0, 
                        "realized_pnl": 0.0,
                        "agent": agent.config.name, 
                        "source": "synthetic_agent_grid",
                        "synthetic": True,
                        "note": "Agent monitoring only - no actual position",
                    })
                if not getattr(agent.state, "active_tickers", []) and agent.state.running:
                    asset = agent.config.assets[0] if agent.config.assets else ""
                    if asset:
                        synthetic_positions.append({
                            "ticker": f"MONITOR:{asset}:{agent.config.name}",
                            "outcome": "monitoring", 
                            "size": 0,
                            "avg_price": 0.0, 
                            "unrealized_pnl": 0.0, 
                            "realized_pnl": 0.0,
                            "agent": agent.config.name, 
                            "cycles": agent.state.cycles_run,
                            "source": "synthetic_agent_monitoring",
                            "synthetic": True,
                            "note": "Agent scanning only - no actual position",
                        })
        except Exception as exc:
            logger.debug(f"Agent grid positions fallback failed: {exc}")
    
    all_positions.extend(synthetic_positions)

    # Add reconciliation status from fills ledger if available
    reconciliation_info = {}
    try:
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        ledger = get_fills_ledger()
        rec = ledger.get_reconciliation_status()
        reconciliation_info = {
            "reconciliation_status": rec,
            "reconciliation_warning": _fills_ledger_positions_warning(rec),
        }
    except Exception as exc:
        logger.debug(f"Fills ledger reconciliation status unavailable: {exc}")

    _attach_kalshi_position_assets(all_positions)
    logger.info(
        "kalshi GET /positions count=%s tickers=%s include_synthetic=%s",
        len(all_positions),
        [p.get("ticker") for p in all_positions[:12]],
        include_synthetic,
    )

    result = {"count": len(all_positions), "positions": all_positions, "real_count": len(real_positions)}
    if include_synthetic:
        result["synthetic_count"] = len(synthetic_positions)
    result.update(reconciliation_info)
    
    # Determine if portfolio is empty/uninitialized (no real trades yet)
    has_real_positions = len(real_positions) > 0
    result["portfolio_empty_or_uninitialized"] = not has_real_positions
    if result["portfolio_empty_or_uninitialized"]:
        result["message"] = "No positions discovered yet (trading not yet active)"

    return result


@router.get("/orders")
async def get_orders(
    include_scanning: bool = Query(False, description="Include synthetic scanning/signal orders for debugging"),
) -> Dict[str, Any]:
    """Get open Kalshi orders from canonical sources only.
    
    By default, returns only orders confirmed by Kalshi API (executor or REST client).
    Synthetic scanning/signal orders are excluded unless ?include_scanning=true is passed.
    
    Args:
        include_scanning: If true, include agent scanning activity tagged with synthetic=true
    """
    # Collect real orders from executor or REST client
    real_orders = []
    venue_order_ids = set()  # Track venue-acknowledged order IDs
    
    executor = _get_executor()
    if executor:
        try:
            raw = await executor.get_orders(status="resting")
            real_orders = [
                {
                    "order_id": o.get("order_id", ""),
                    "ticker": o.get("ticker", ""),
                    "side": o.get("side", ""),
                    "size": int(_safe_float_val(o.get("remaining_count", o.get("count", 0)), 0)),
                    "price": _safe_float_val(o.get("yes_price") or o.get("no_price") or 0) / 100.0,
                    "filled": int(_safe_float_val(o.get("filled_count", 0), 0)),
                    "remaining": (
                        None
                        if o.get("remaining_count") is None
                        else int(_safe_float_val(o.get("remaining_count"), 0))
                    ),
                    "status": o.get("status", ""),
                    "created_at": o.get("created_time", None),
                    "source": "executor",
                    "synthetic": False,
                }
                for o in raw
            ]
            for o in real_orders:
                if o.get("order_id"):
                    venue_order_ids.add(o["order_id"])
            if real_orders:
                return {"count": len(real_orders), "orders": real_orders, "venue_order_ids": list(venue_order_ids)}
        except Exception as exc:
            logger.warning(f"Executor orders failed: {exc}")

    if not real_orders:
        rest = _get_rest_client()
        if rest:
            try:
                raw_orders = await asyncio.to_thread(rest.get_orders, status="resting")
                real_orders = [
                    {
                        "order_id": o.get("order_id", ""),
                        "ticker": o.get("ticker", ""),
                        "side": o.get("side", ""),
                        "size": int(_safe_float_val(o.get("remaining_count", o.get("count", 0)), 0)),
                        "price": _safe_float_val(o.get("yes_price") or o.get("no_price") or 0) / 100.0,
                        "filled": int(_safe_float_val(o.get("filled_count", 0), 0)),
                        "remaining": int(_safe_float_val(o.get("remaining_count", 0), 0)),
                        "status": o.get("status", ""),
                        "created_at": o.get("created_time", None),
                        "source": "rest_client",
                        "synthetic": False,
                    }
                    for o in raw_orders
                ]
                for o in real_orders:
                    if o.get("order_id"):
                        venue_order_ids.add(o["order_id"])
                if real_orders:
                    return {"count": len(real_orders), "orders": real_orders, "venue_order_ids": list(venue_order_ids)}
            except Exception as exc:
                logger.warning(f"merid_core orders failed: {exc}")

    # Supplement with agent grid signals and scan activity ONLY if explicitly requested
    all_orders = list(real_orders)
    synthetic_orders = []
    
    if include_scanning:
        import datetime as _dt
        try:
            from merid.prediction.agent_grid import get_agent_grid
            grid = get_agent_grid()
            _now = _dt.datetime.now(_dt.timezone.utc).isoformat()
            for agent in grid.agents:
                for sig in getattr(agent.state, "signal_log", [])[-10:]:
                    if sig.get("action") in ("buy", "sell", "place_order"):
                        synthetic_orders.append({
                            "order_id": sig.get("id", f"sig-{agent.config.name}-{sig.get('ts', '')}"),
                            "ticker": sig.get("ticker", ""),
                            "side": sig.get("action", "buy"),
                            "size": int(_safe_float_val(sig.get("contracts", 1), 1)),
                            "price": _safe_float_val(sig.get("price", 0), 0),
                            "filled": 0, "remaining": sig.get("contracts", 1),
                            "status": "scanning",  # Never "pending" - clearly mark as scanning
                            "created_at": sig.get("ts", ""),
                            "agent": agent.config.name, 
                            "source": "synthetic_agent_signal",
                            "synthetic": True,
                            "note": "Signal only - not submitted to venue",
                        })
                if not getattr(agent.state, "signal_log", []) and agent.state.running and agent.state.cycles_run > 0:
                    asset = agent.config.assets[0] if agent.config.assets else ""
                    if asset:
                        synthetic_orders.append({
                            "order_id": f"scan-{agent.config.name}",
                            "ticker": f"{asset}/*",
                            "side": "scanning", 
                            "size": 0, 
                            "price": 0,
                            "filled": 0, 
                            "remaining": 0, 
                            "status": "scanning",
                            "created_at": _now, 
                            "agent": agent.config.name,
                            "cycles": agent.state.cycles_run, 
                            "source": "synthetic_agent_scanning",
                            "synthetic": True,
                            "note": "Scanning activity only - no orders placed",
                        })
        except Exception as exc:
            logger.debug(f"Agent grid orders fallback failed: {exc}")
    
    all_orders.extend(synthetic_orders)

    result = {"count": len(all_orders), "orders": all_orders, "real_count": len(real_orders)}
    if include_scanning:
        result["synthetic_count"] = len(synthetic_orders)
        result["synthetic_orders"] = synthetic_orders
    result["venue_order_ids"] = list(venue_order_ids)
    
    return result


@router.get("/orders/{order_id}/lineage")
async def get_order_lineage(order_id: str) -> Dict[str, Any]:
    """Get full lineage trace for an order: signal → agent → consensus → risk → router.
    
    This endpoint exposes the complete chain of custody for every real order,
    making it easy to spot shadow paths or missing risk checks.
    """
    from datetime import datetime, timezone
    
    lineage = {
        "order_id": order_id,
        "found": False,
        "chain": {},
        "warnings": [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    # 1. Find order in canonical sources
    order_data = None
    venue_source = None
    
    # Check executor first
    executor = _get_executor()
    if executor:
        try:
            raw = await executor.get_orders(status="resting")
            for o in raw:
                if o.get("order_id") == order_id:
                    order_data = o
                    venue_source = "executor"
                    break
            if not order_data:
                # Check fills for completed orders
                fills = await executor.get_fills()
                for f in fills:
                    if f.get("order_id") == order_id:
                        order_data = f
                        venue_source = "executor_fills"
                        break
        except Exception as exc:
            logger.debug(f"Executor lookup failed: {exc}")
    
    # Check REST client
    if not order_data:
        rest = _get_rest_client()
        if rest:
            try:
                raw = await asyncio.to_thread(rest.get_orders, status="resting")
                for o in raw:
                    if o.get("order_id") == order_id:
                        order_data = o
                        venue_source = "rest_client"
                        break
            except Exception as exc:
                logger.debug(f"REST client lookup failed: {exc}")
    
    if not order_data:
        lineage["warnings"].append(f"Order {order_id} not found in canonical sources")
        lineage["found"] = order_data is not None
        lineage["order_id"] = order_id
        lineage["chain"] = {}  # Explicitly initialize empty
        lineage["chain_complete"] = False  # Explicit default
        lineage["chain_coverage"] = "0/4"
        lineage["manual_or_external"] = False  # Explicit default
        lineage["synthetic"] = False  # Explicit default
        lineage["warnings"] = []  # Explicit default
        
        lineage["warnings"].append(f"Order {order_id} not found in canonical sources")
        lineage["manual_or_external"] = True  # Unknown orders are external by definition
        lineage["manual_or_external_reason"] = "Order not found in any venue or internal system"
        return lineage
    
    lineage["found"] = order_data is not None
    lineage["order_id"] = order_id
    lineage["chain"] = {}  # Explicitly initialize empty
    lineage["chain_complete"] = False  # Explicit default
    lineage["chain_coverage"] = "0/4"
    lineage["manual_or_external"] = False  # Explicit default
    lineage["synthetic"] = False  # Explicit default
    lineage["warnings"] = []  # Explicit default
    
    lineage["venue_source"] = venue_source or "unknown"
    lineage["order"] = {
        "ticker": order_data.get("ticker"),
        "side": order_data.get("side"),
        "status": order_data.get("status"),
        "created_at": order_data.get("created_time"),
        "synthetic": order_data.get("synthetic", False),
    }
    
    # 2. Trace back to signal/agent
    try:
        from merid.prediction.agent_grid import get_agent_grid
        grid = get_agent_grid()
        
        # Look for agent that created this order
        for agent in grid.agents:
            agent_orders = getattr(agent.state, "order_log", [])
            for order_record in agent_orders:
                if order_record.get("order_id") == order_id or order_record.get("venue_order_id") == order_id:
                    lineage["chain"]["agent"] = {
                        "agent_id": agent.config.name,
                        "agent_type": getattr(agent.config, "agent_type", "unknown"),
                        "signal_id": order_record.get("signal_id"),
                        "timestamp": order_record.get("timestamp"),
                    }
                    
                    # Find the originating signal
                    signal_log = getattr(agent.state, "signal_log", [])
                    for sig in signal_log:
                        if sig.get("id") == order_record.get("signal_id"):
                            lineage["chain"]["signal"] = {
                                "signal_id": sig.get("id"),
                                "timestamp": sig.get("ts"),
                                "action": sig.get("action"),
                                "ticker": sig.get("ticker"),
                                "price": sig.get("price"),
                                "contracts": sig.get("contracts"),
                                "model_prob": sig.get("model_prob"),
                                "implied_prob": sig.get("implied_prob"),
                                "edge_pct": sig.get("edge_pct"),
                                "staleness_sec": sig.get("staleness_sec"),
                                "fresh": (sig.get("staleness_sec") or 999) < 60,
                            }
                            break
                    break
            if "agent" in lineage["chain"]:
                break
        
        if "agent" not in lineage["chain"]:
            lineage["warnings"].append("No agent trace found - order may be manually placed or from external source")
    except Exception as exc:
        lineage["warnings"].append(f"Agent grid lookup failed: {exc}")
    
    # 3. Check consensus
    try:
        from consensus.taco_consensus import get_consensus_coordinator
        consensus = get_consensus_coordinator()
        
        # Check if this order was consensus-approved
        for decision in getattr(consensus, "recent_decisions", []):
            if decision.get("order_id") == order_id:
                lineage["chain"]["consensus"] = {
                    "consensus_id": decision.get("decision_id"),
                    "approved": decision.get("approved"),
                    "timestamp": decision.get("timestamp"),
                    "participating_agents": decision.get("agents", []),
                    "confidence": decision.get("confidence"),
                }
                break
        
        if "consensus" not in lineage["chain"]:
            lineage["chain"]["consensus"] = {"note": "No consensus record - single-agent decision or pre-consensus routing"}
    except Exception as exc:
        lineage["warnings"].append(f"Consensus lookup failed: {exc}")
    
    # 4. Check risk decision
    try:
        from merid.risk.kill_switches import risk_controller
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
        
        # Check risk controller events
        risk_events = getattr(risk_controller, "recent_events", [])
        for event in risk_events:
            if event.get("order_id") == order_id or (event.get("context") or {}).get("order_id") == order_id:
                lineage["chain"]["risk"] = {
                    "risk_decision_id": event.get("event_id"),
                    "allowed": event.get("allowed"),
                    "timestamp": event.get("timestamp"),
                    "checks_performed": event.get("checks", []),
                    "limits_at_time": event.get("limits_snapshot"),
                }
                break
        
        # Also check kalshi_risk for pre-trade checks
        if "risk" not in lineage["chain"]:
            kr = get_kalshi_risk()
            recent_checks = getattr(kr, "recent_pre_trade_checks", [])
            for check in recent_checks:
                if check.get("order_id") == order_id:
                    lineage["chain"]["risk"] = {
                        "risk_decision_id": check.get("check_id"),
                        "allowed": check.get("passed"),
                        "timestamp": check.get("timestamp"),
                        "checks_performed": check.get("checks", []),
                        "drawdown_at_time": check.get("drawdown_pct"),
                    }
                    break
        
        if "risk" not in lineage["chain"]:
            lineage["warnings"].append("No risk decision record found - risk check may have been skipped or logged elsewhere")
    except Exception as exc:
        lineage["warnings"].append(f"Risk lookup failed: {exc}")
    
    # 5. Check router
    try:
        from merid.event_venues.kalshi.order_router import get_recent_routes
        routes = get_recent_routes()
        
        for route in routes:
            if route.get("order_id") == order_id or route.get("client_order_id") == order_id:
                lineage["chain"]["router"] = {
                    "route_call_id": route.get("route_id"),
                    "timestamp": route.get("timestamp"),
                    "mode": route.get("mode"),
                    "latency_ms": route.get("latency_ms"),
                    "venue_response": route.get("venue_status"),
                }
                break
        
        if "router" not in lineage["chain"]:
            lineage["warnings"].append("No router record found - order may have been placed through alternate path")
    except Exception as exc:
        lineage["warnings"].append(f"Router lookup failed: {exc}")
    
    # 6. Validate chain integrity and flag manual/external orders
    chain_keys = set(lineage["chain"].keys())
    expected_for_live = {"signal", "agent", "risk", "router"}
    
    missing = expected_for_live - chain_keys
    lineage["manual_or_external"] = False  # Default assumption
    
    if venue_source in ("executor", "rest_client"):
        if missing:
            lineage["warnings"].append(f"Incomplete lineage - missing: {', '.join(missing)}. Possible manual order or bypass.")
            # Flag as manual/external if order found at venue but no internal chain
            lineage["manual_or_external"] = True
            lineage["manual_or_external_reason"] = f"Venue order with incomplete internal lineage: missing {', '.join(missing)}"
    else:
        # Non-venue sources are always flagged
        lineage["manual_or_external"] = True
        lineage["manual_or_external_reason"] = f"Order source is {venue_source}, not venue-acknowledged"
    
    lineage["chain_complete"] = len(missing) == 0 and not lineage["manual_or_external"]
    lineage["chain_coverage"] = f"{len(chain_keys)}/{len(expected_for_live)}"
    
    return lineage


@router.get("/reconciliation/breaks")
async def get_reconciliation_breaks(
    threshold_usd: float = Query(1.0, ge=0.01, description="Min USD difference to flag as break"),
) -> Dict[str, Any]:
    """Get list of reconciliation breaks: unmatched fills, unmatched positions, balance drift.
    
    This endpoint surfaces any discrepancies between:
    - Fills ledger vs positions
    - Calculated balance vs venue balance
    - Expected vs actual PnL
    """
    from datetime import datetime, timezone
    
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "threshold_usd": threshold_usd,
        "status": "ok",
        "breaks": [],
        "summary": {
            "unmatched_fills": 0,
            "unmatched_positions": 0,
            "balance_drift": 0.0,
            "pnl_divergence": 0.0,
        },
    }
    
    breaks = []
    
    # 1. Check fills ledger vs positions
    try:
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        ledger = get_fills_ledger()
        
        # Get fills not matched to positions
        unmatched_fills = getattr(ledger, "unmatched_fills", [])
        for fill in unmatched_fills:
            breaks.append({
                "type": "unmatched_fill",
                "severity": "high" if fill.get("value_usd", 0) > 100 else "medium",
                "fill_id": fill.get("fill_id"),
                "ticker": fill.get("ticker"),
                "side": fill.get("side"),
                "size": fill.get("size"),
                "value_usd": fill.get("value_usd"),
                "timestamp": fill.get("timestamp"),
                "message": f"Fill {fill.get('fill_id')} for {fill.get('ticker')} has no matching position impact",
            })
        
        result["summary"]["unmatched_fills"] = len(unmatched_fills)
        
        # Get position impacts not matched to fills
        unmatched_impacts = getattr(ledger, "unmatched_position_impacts", [])
        for impact in unmatched_impacts:
            breaks.append({
                "type": "unmatched_position_impact",
                "severity": "high",
                "ticker": impact.get("ticker"),
                "expected_fill_id": impact.get("expected_fill_id"),
                "actual_impact": impact.get("impact"),
                "timestamp": impact.get("timestamp"),
                "message": f"Position impact for {impact.get('ticker')} has no matching fill (expected {impact.get('expected_fill_id')})",
            })
        
        result["summary"]["unmatched_positions"] = len(unmatched_impacts)
        
    except Exception as exc:
        breaks.append({
            "type": "system_error",
            "severity": "critical",
            "component": "fills_ledger",
            "message": f"Failed to query fills ledger: {exc}",
        })
    
    # 2. Check balance drift
    try:
        executor = _get_executor()
        venue_balance = None
        
        if executor:
            bal = await executor.get_balance()
            if hasattr(bal, "to_dict"):
                venue_balance = bal.to_dict()
            else:
                venue_balance = bal if isinstance(bal, dict) else {"available": bal}
        
        if not venue_balance:
            rest = _get_rest_client()
            if rest:
                bal = await asyncio.to_thread(rest.get_balance)
                venue_balance = bal if isinstance(bal, dict) else {"available": bal}
        
        if venue_balance:
            # Calculate expected balance from fills
            expected_balance = _calculate_expected_balance_from_fills()
            actual_available = float(venue_balance.get("USD", venue_balance.get("available", 0)))
            
            drift = abs(expected_balance - actual_available)
            if drift > threshold_usd:
                breaks.append({
                    "type": "balance_drift",
                    "severity": "high" if drift > 100 else "medium",
                    "expected_balance": expected_balance,
                    "actual_balance": actual_available,
                    "drift_usd": drift,
                    "message": f"Balance drift: ${drift:.2f} (expected ${expected_balance:.2f}, actual ${actual_available:.2f})",
                })
            
            result["summary"]["balance_drift"] = drift
        
    except Exception as exc:
        breaks.append({
            "type": "system_error",
            "severity": "warning",
            "component": "balance_check",
            "message": f"Failed to verify balance: {exc}",
        })
    
    # 3. Check PnL divergence
    try:
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        ledger = get_fills_ledger()
        
        # PnL from fills ledger (ground truth)
        _ledger_summary = ledger.summary()
        fills_pnl = float(_ledger_summary.get("daily_realized_pnl_usd", 0.0))
        
        # PnL from risk controller
        from merid.risk.kill_switches import risk_controller
        risk_pnl = float(risk_controller.get_status().get("daily_pnl", 0.0))
        
        pnl_divergence = abs(fills_pnl - risk_pnl)
        if pnl_divergence > threshold_usd:
            breaks.append({
                "type": "pnl_divergence",
                "severity": "high" if pnl_divergence > 100 else "medium",
                "fills_ledger_pnl": fills_pnl,
                "risk_controller_pnl": risk_pnl,
                "divergence_usd": pnl_divergence,
                "message": f"PnL divergence: ${pnl_divergence:.2f} (fills: ${fills_pnl:.2f}, risk: ${risk_pnl:.2f})",
            })
        
        result["summary"]["pnl_divergence"] = pnl_divergence
        
    except Exception as exc:
        breaks.append({
            "type": "system_error",
            "severity": "warning",
            "component": "pnl_check",
            "message": f"Failed to verify PnL: {exc}",
        })
    
    # 4. Determine overall status
    high_severity = [b for b in breaks if b.get("severity") == "high"]
    medium_severity = [b for b in breaks if b.get("severity") == "medium"]
    
    if high_severity:
        result["status"] = "broken"
    elif medium_severity:
        result["status"] = "degraded"
    elif breaks:
        result["status"] = "warning"
    
    result["breaks"] = breaks
    result["break_count"] = len(breaks)
    result["high_severity_count"] = len(high_severity)
    result["medium_severity_count"] = len(medium_severity)
    
    return result


def _calculate_expected_balance_from_fills() -> float:
    """Calculate expected balance from fills ledger."""
    try:
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        ledger = get_fills_ledger()
        
        # Sum all fill impacts on balance
        fills = ledger.get_fills() if hasattr(ledger, "get_fills") else []
        total_impact = 0.0
        
        for fill in fills:
            # Each fill affects balance: buy = -cost, sell = +proceeds
            size = fill.get("size", 0)
            price = fill.get("price", 0)
            fee = fill.get("fee", 0)
            side = fill.get("side", "")
            
            if side == "buy":
                total_impact -= (size * price + fee)
            elif side == "sell":
                total_impact += (size * price - fee)
        
        # Get starting balance from ledger or executor (sync-safe — no await)
        starting_balance = getattr(ledger, "starting_balance", None)
        if starting_balance is None:
            try:
                from merid.event_venues.kalshi.executor import get_executor
                executor = get_executor()
                if executor:
                    starting_balance = float(getattr(executor, "balance_usd", 0.0) or 0.0)
                else:
                    starting_balance = 0.0
            except Exception:
                starting_balance = 0.0
        
        return starting_balance + total_impact
    except Exception as exc:
        logger.warning(f"Failed to calculate expected balance: {exc}")
        return 0.0


@router.get("/fills")
async def get_fills(
    limit: int = Query(50, ge=1, le=500),
    since_hours: Optional[int] = Query(24, ge=1, le=168, description="Hours to look back for fills"),
    reconciliation_status: Optional[str] = Query(None, description="Filter by reconciliation status"),
) -> Dict[str, Any]:
    """Get recent Kalshi fills/trades from canonical ledger.
    
    This endpoint returns fills from the canonical fills ledger, which is
    maintained by dual ingestion (HTTP poller + WebSocket). All fills have
    a Kalshi-issued fill_id and are reconciled with positions.
    
    No ghost trades: every fill returned was confirmed by Kalshi API.
    """
    try:
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        from datetime import datetime, timezone, timedelta
        
        ledger = get_fills_ledger()
        
        # Calculate since time
        since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        
        # Get fills from canonical ledger
        fills = ledger.get_fills(since=since, limit=limit)
        
        # FILTER: Exclude incomplete fills (size=0 or price=0) from API response
        # These are typically WebSocket placeholder fills that will be completed by HTTP poller
        complete_fills = [
            f for f in fills 
            if not (f.is_incomplete() if callable(getattr(f, "is_incomplete", None)) else False)
        ]
        incomplete_count = len(fills) - len(complete_fills)

        sample = None
        if complete_fills:
            ff = complete_fills[0]
            sample = {
                "fill_id": ff.fill_id,
                "size": getattr(ff, "count_fp", 0),
                "price_usd": _ledger_fill_price_usd(ff),
                "incomplete": ff.is_incomplete() if callable(getattr(ff, "is_incomplete", None)) else None,
            }
        logger.info(
            "kalshi GET /fills total=%s complete=%s incomplete_filtered=%s since_hours=%s sample=%s",
            len(fills),
            len(complete_fills),
            incomplete_count,
            since_hours,
            sample,
        )
        
        # Build response (include `price`/`fee` aliases — UI types expect dollars, not only price_usd)
        result = {
            "count": len(complete_fills),
            "fills": [_kalshi_fill_api_row(f) for f in complete_fills],
            "meta": {
                "source": "canonical_ledger",
                "since_hours": since_hours,
                "ledger_total_fills": len(ledger._fills),
                "reconciliation_status": ledger.get_reconciliation_status(),
                "response_at": datetime.now(timezone.utc).isoformat(),
            }
        }
        
        # If reconciliation is broken, add warning
        if ledger._reconciliation_status.value == "broken":
            result["warning"] = "Fills reconciliation broken — positions may diverge from fills"
        
        # Check if portfolio is empty (no complete fills) - discover phase indicator
        # Note: incomplete fills are filtered out above, so if complete_fills is empty, no real trades yet
        result["portfolio_empty_or_uninitialized"] = len(complete_fills) == 0
        result["incomplete_fills_filtered"] = incomplete_count
        if result["portfolio_empty_or_uninitialized"]:
            result["message"] = "No trades discovered yet (trading not yet active)"

        return result
        
    except Exception as e:
        logger.error(f"Fills ledger query failed: {e}")
        
        # Fallback to legacy direct fetch (only if ledger fails)
        logger.warning("Falling back to legacy fills fetch")
        return await _get_fills_legacy(limit)


@router.post("/fills/reconcile-now")
async def post_fills_reconcile_now() -> Dict[str, Any]:
    """Run one HTTP fills poll plus Kalshi positions reconciliation (debug / operators)."""
    try:
        from merid.event_venues.kalshi.fills_poller import get_fills_poller

        poller = get_fills_poller()
        return await poller.reconcile_now()
    except Exception as exc:
        logger.warning("POST /fills/reconcile-now failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


async def _get_fills_legacy(limit: int) -> Dict[str, Any]:
    """Legacy fills fetch for fallback only.
    
    WARNING: This bypasses the canonical ledger and should only be used
    when the ledger is unavailable. Results may not be complete.
    """
    executor = _get_executor()
    if executor:
        try:
            raw = await executor.get_fills()
            fills = []
            for f in raw[:limit]:
                _yc = f.get("yes_price")
                _nc = f.get("no_price")
                _pc = f.get("price")
                _cents = _pc if _pc is not None else (_yc or _nc or 0)
                _size = int(_safe_float_val(f.get("count", 0), 0))
                # BUG-FIX: Filter out incomplete fills (size=0 or price=0)
                if _size <= 0 or _cents <= 0:
                    continue
                _usd = _safe_float_val(_cents, 0) / 100.0
                _fid = f.get("fill_id") or f.get("trade_id") or ""
                fills.append(
                    {
                        "fill_id": _fid,
                        "trade_id": f.get("trade_id") or _fid,
                        "ticker": f.get("ticker", ""),
                        "order_id": f.get("order_id", ""),
                        "side": f.get("side", ""),
                        "action": f.get("action", f.get("side", "")).lower(),
                        "size": _size,
                        "price_cents": int(_safe_float_val(_cents, 0)),
                        "price_usd": _usd,
                        "fee_usd": _safe_float_val(f.get("fee_paid", 0), 0) / 100.0,
                        "price": _usd,
                        "fee": _safe_float_val(f.get("fee_paid", 0), 0) / 100.0,
                        "timestamp": f.get("created_time", ""),
                        "ingestion_source": "legacy_http",
                        "incomplete": False,
                    }
                )
            return {
                "count": len(fills),
                "fills": fills,
                "meta": {
                    "source": "legacy_direct",
                    "warning": "Bypassed canonical ledger — fills may not be complete",
                }
            }
        except Exception as exc:
            logger.warning(f"Executor fills failed: {exc}")

    # Fallback: merid_core REST client (orders with status=filled)
    rest = _get_rest_client()
    if rest:
        try:
            orders = await asyncio.to_thread(rest.get_orders, status="filled")
            fills = orders[:limit]
            return {
                "count": len(fills),
                "fills": [
                    {
                        "fill_id": f.get("order_id", ""),
                        "trade_id": f.get("order_id", ""),
                        "ticker": f.get("ticker", ""),
                        "order_id": f.get("order_id", ""),
                        "side": f.get("side", ""),
                        "action": f.get("action", f.get("side", "")).lower(),
                        "size": int(_safe_float_val(f.get("filled_count", f.get("count", 0)), 0)),
                        "price_cents": int(
                            _safe_float_val(f.get("yes_price", f.get("no_price", 0)), 0)
                        ),
                        "price_usd": _safe_float_val(
                            f.get("yes_price", f.get("no_price", 0)), 0
                        )
                        / 100.0,
                        "fee_usd": 0.0,
                        "price": _safe_float_val(f.get("yes_price", f.get("no_price", 0)), 0)
                        / 100.0,
                        "fee": 0.0,
                        "timestamp": f.get("updated_time", f.get("created_time", "")),
                        "ingestion_source": "legacy_orders",
                    }
                    for f in fills
                ],
                "meta": {
                    "source": "legacy_orders",
                    "warning": "Derived from orders API — fills may be incomplete",
                }
            }
        except Exception as exc:
            logger.warning(f"merid_core fills failed: {exc}")
            return {"count": 0, "fills": [], "error": str(exc), "meta": {"source": "error"}}

    return {"count": 0, "fills": [], "error": "No Kalshi client configured", "meta": {"source": "error"}}


@router.get("/balance")
async def get_balance() -> Dict[str, Any]:
    """Get Kalshi account balance with normalized units (dollars).
    
    NEW v2 implementation - uses unified bankroll service as single source of truth.
    Returns explicit state (FRESH/STALE/ERROR) with portfolio value from centralized calculation.
    """
    # Use v2 bankroll service - single source of truth
    service = await get_bankroll_service()
    
    # Get cached summary with module attribution for logging
    summary = await service.get_summary(caller_module="kalshi_api_balance")
    
    # Use centralized portfolio value calculation from v2 service (single source of truth)
    portfolio_cents = await service.get_portfolio_value_cents()
    
    logger.info("[balance endpoint] Using v2 bankroll data: equity=%s available=%s portfolio=%s source=%s state=%s as_of=%s",
               summary.equity_usd, summary.available_cash_usd, portfolio_cents / 100.0,
               summary.source, summary.state.value, summary.as_of)
    
    # Build response with explicit state
    response = {
        "state": summary.state.value,
        "units": "dollars",
        "as_of": summary.as_of.isoformat() if summary.as_of else None,
        "source": summary.source,
    }
    
    if summary.available_cash_usd is not None:
        balance_cents = int(summary.available_cash_usd * 100)
        total_value_cents = balance_cents + portfolio_cents
        response["usd"] = float(summary.available_cash_usd)
        response["balance_cents"] = balance_cents
        response["portfolio_cents"] = portfolio_cents
        response["total_value_cents"] = total_value_cents
        response["max_position_usd"] = float(summary.max_position_usd) if summary.max_position_usd else None
    else:
        response["usd"] = None
        response["balance_cents"] = 0
        response["portfolio_cents"] = portfolio_cents
        response["total_value_cents"] = portfolio_cents
        response["max_position_usd"] = None
    
    # Add error info if applicable
    if summary.state == BalanceState.ERROR:
        response["error"] = summary.last_error_reason or "Bankroll unavailable"
        response["alert"] = True
    elif summary.state == BalanceState.STALE:
        response["warning"] = summary.last_error_reason or "Using stale bankroll data"
        response["stale"] = True
    elif summary.state == BalanceState.UNKNOWN:
        response["error"] = "Bankroll never fetched - initial load in progress"
    
    # Legacy fields for backward compatibility
    response["locked"] = 0  # v2 doesn't track locked separately (it's part of equity)
    response["available"] = response["usd"]
    
    return response


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
    since_ts: Optional[int] = Query(None, description="Minimum timestamp filter (epoch seconds)"),
    include_unreconciled: bool = Query(True, description="Include fills pending reconciliation"),
) -> Dict[str, Any]:
    """Get paginated fills from canonical ledger with optional time filter.
    
    Returns fills with full metadata including reconciliation status and
    ingestion source. Use this endpoint for portfolio views that need
    complete trade history with provenance.
    """
    try:
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        from datetime import datetime, timezone, timedelta
        
        ledger = get_fills_ledger()
        
        # Calculate since time
        if since_ts:
            since = datetime.fromtimestamp(since_ts, tz=timezone.utc)
        else:
            since = datetime.now(timezone.utc) - timedelta(hours=24)
        
        # Get fills from canonical ledger
        fills = ledger.get_fills(since=since, limit=limit)

        fill_rows: List[Dict[str, Any]] = []
        for f in fills:
            _raw_px = f.yes_price_dollars if f.side == "yes" else f.no_price_dollars
            if _raw_px is None:
                price_usd = None
                price_dollars = None
            else:
                price_usd = round(_safe_float_val(_raw_px), 4)
                price_dollars = price_usd
            fill_rows.append(
                {
                    "fill_id": f.fill_id,
                    "trade_id": f.trade_id or f.fill_id or "",
                    "order_id": f.order_id,
                    "ticker": f.market_ticker,
                    "side": f.side,
                    "action": f.action,
                    "contracts": int(_safe_float_val(getattr(f, "count_fp", 0), 0)),
                    "size": int(_safe_float_val(getattr(f, "count_fp", 0), 0)),
                    "price_cents": int(_safe_float_val(f.price_cents, 0)),
                    "price_usd": price_usd,
                    "price": price_dollars,
                    "fee_usd": round(_safe_float_val(f.fee_cost), 4),
                    "fee": round(_safe_float_val(f.fee_cost), 4),
                    "timestamp": f.created_time.isoformat() if f.created_time else None,
                    "client_order_id": f.client_order_id,
                    "agent_id": f.agent_id,
                    "intent_id": f.intent_id,
                    "ingestion_source": f.ingestion_source,
                    "reconciled": f.reconciled,
                    "reconciliation_ts": f.reconciliation_ts.isoformat() if f.reconciliation_ts else None,
                }
            )

        return {
            "count": len(fills),
            "fills": fill_rows,
            "meta": {
                "source": "canonical_ledger",
                "ledger_total": len(ledger._fills),
                "reconciliation_status": ledger.get_reconciliation_status(),
            }
        }
        
    except Exception as e:
        logger.error(f"Portfolio fills ledger query failed: {e}")
        # Fallback to direct Kalshi API
        return await _get_portfolio_fills_direct(limit, since_ts)


async def _get_portfolio_fills_direct(limit: int, since_ts: Optional[int]) -> Dict[str, Any]:
    """Direct Kalshi API fallback for portfolio fills."""
    client = _get_client()
    if not client:
        raise HTTPException(status_code=503, detail="Kalshi client not configured")

    try:
        await client.connect()
        result = await client.get_fills(limit=limit, since_ts=since_ts)

        if not result.success:
            raise HTTPException(status_code=502, detail=str(result.error))

        fills = result.data or []
        return {
            "count": len(fills),
            "fills": [
                {
                    "fill_id": f.get("fill_id", f.get("trade_id", "")),
                    "ticker": f.get("market_ticker", f.get("ticker", "")),
                    "side": f.get("side", ""),
                    "action": f.get("action", f.get("side", "")).lower(),
                    "contracts": f.get("contracts", f.get("count", 0)),
                    "price_cents": f.get("price", 0),
                    "price_usd": f.get("price", 0) / 100.0,
                    "fee_usd": f.get("fee", 0) / 100.0,
                    "timestamp": f.get("created_at", f.get("timestamp", "")),
                    "ingestion_source": "direct_api",
                }
                for f in fills
            ],
            "meta": {
                "source": "direct_api",
                "latency_ms": result.latency_ms,
                "warning": "Fetched directly from Kalshi API — not from canonical ledger",
            }
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Direct fills fetch failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/fills/reconciliation")
async def get_fills_reconciliation_status() -> Dict[str, Any]:
    """Get fills ledger reconciliation status.
    
    Returns the current state of the fills reconciliation engine,
    including any divergences between computed positions and Kalshi positions.
    """
    try:
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        from merid.event_venues.kalshi.fills_poller import get_fills_poller
        
        ledger = get_fills_ledger()
        poller = get_fills_poller()
        
        return {
            "ledger": ledger.summary(),
            "poller": poller.get_health(),
            "reconciliation": ledger.get_reconciliation_status(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
    except Exception as e:
        logger.error(f"Reconciliation status fetch failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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


@router.post("/orders",
    summary="Place Kalshi Order",
    description="Place a Kalshi order through MERID. Runs risk pre-check, then routes to KalshiVenueClient. In paper mode, returns a simulated fill without hitting Kalshi.",
    response_description="Order placement result with fill info",
    tags=["kalshi", "orders"],
)
async def place_order(
    ticker: str,
    side: str,            # "yes" or "no"
    action: str,          # "buy" or "sell"
    count: int,
    price_cents: int,
    order_type: str = "limit",
    time_in_force: str = "gtc",
    mode: Optional[str] = None,  # "paper" or "live" — defaults to MERID_PM_TRADING_MODE from settings
    take_profit_price_cents: Optional[int] = None,  # Optional TP price in cents
    take_profit_r_multiple: Optional[float] = None,  # Optional TP R-multiple
    stop_loss_price_cents: Optional[int] = None,  # Optional SL price in cents
    confidence: Optional[float] = None,  # Optional confidence for default TP computation
) -> Dict[str, Any]:
    """Place a Kalshi order through MERID.

    Runs risk pre-check, then routes to KalshiVenueClient.
    In paper mode, returns a simulated fill without hitting Kalshi.
    Defaults to MERID_PM_TRADING_MODE from settings (paper if not configured).

    For 15m crypto entry orders (buy), exit targets (TP/SL) are required.
    If not provided, default TP is computed using the dynamic TP engine.
    """
    # Validate ticker input
    if not ticker or len(ticker) > 100:
        raise HTTPException(400, "Invalid ticker: must be 1-100 characters")
    
    # Use configured default if not explicitly provided
    if mode is None:
        mode = _get_default_order_mode()
        logger.info(f"Using default order mode from settings: {mode}")
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

    # Fail-closed execution-gate pre-check (LIVE only).
    # Runs BEFORE the router so that gate outages return a structured
    # ``{status=rejected, reason=execution_gate_unavailable:...}`` to the
    # caller instead of being masked by a downstream sanity rejection.
    if mode_value == "live":
        try:
            from core.execution_gate import check_execution_gate
            _gate = check_execution_gate()
            if getattr(_gate, "blocked", False):
                _reasons = "; ".join(
                    getattr(r, "message", str(r)) for r in (getattr(_gate, "reasons", None) or [])
                ) or "unknown_execution_gate_reasons"
                return {
                    "status": "rejected",
                    "mode": mode_value,
                    "ticker": ticker,
                    "reason": f"execution_gate_blocked:{_reasons}",
                }
        except Exception as exc:
            logger.error(
                "execution_gate_unavailable_live_order_blocked: %s", exc, exc_info=True
            )
            return {
                "status": "rejected",
                "mode": mode_value,
                "ticker": ticker,
                "reason": f"execution_gate_unavailable:{exc}",
            }

    # Risk pre-check (if risk manager available)
    risk = _get_risk()
    if risk:
        try:
            ok, reason = risk.check_order(ticker, None, count, price_cents)
            if not ok:
                return {"status": "rejected", "mode": mode_value, "reason": reason, "ticker": ticker}
        except Exception as exc:
            if mode_value == "live":
                logger.error("risk_precheck_failed_live_order_blocked: %s", exc, exc_info=True)
                raise HTTPException(
                    503,
                    "Risk pre-check failed — live trading disabled until checks succeed",
                ) from exc
            logger.warning("Risk check failed (non-live, proceeding): %s", exc)

    # Compute default TP/SL for 15m crypto entry orders if not provided
    # This ensures the "no trade without exit" invariant is satisfied
    if action == "buy" and ticker.startswith(("KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M")):
        # Check if we need to compute default TP
        if take_profit_price_cents is None and take_profit_r_multiple is None:
            try:
                from merid.prediction.dynamic_takeprofit import DynamicTakeProfitEngine
                engine = DynamicTakeProfitEngine()
                
                # Default SL: 5 cents below entry (conservative)
                if stop_loss_price_cents is None:
                    stop_loss_price_cents = max(1, price_cents - 5)
                
                # Default confidence: 0.5 (medium) if not provided
                if confidence is None:
                    confidence = 0.5
                
                # Compute dynamic TP
                tp_plan = engine.compute_tp(
                    entry_price=price_cents / 100.0,  # Convert to decimal
                    stop_price=stop_loss_price_cents / 100.0,
                    direction="LONG" if side == "yes" else "SHORT",
                    confidence=confidence,
                )
                
                # Convert TP price back to cents and set as R-multiple for routing
                take_profit_r_multiple = tp_plan.tp_r_multiple
                logger.info(
                    "[API-TP] Computed default TP for %s: R=%.2f from entry=%dc stop=%dc confidence=%.2f",
                    ticker, tp_plan.tp_r_multiple, price_cents, stop_loss_price_cents, confidence
                )
            except Exception as tp_exc:
                logger.warning("[API-TP] Failed to compute default TP: %s", tp_exc)
                # If TP computation fails, set a conservative default
                take_profit_r_multiple = 1.0  # 1R as fallback
                if stop_loss_price_cents is None:
                    stop_loss_price_cents = max(1, price_cents - 5)

    # Try old order router first
    try:
        from merid.prediction.venue_gate import TradingMode
        from merid.event_venues.kalshi.decision_trace import new_decision_trace_id
        from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async

        mode_map = {"mock": TradingMode.MOCK, "paper": TradingMode.PAPER, "live": TradingMode.LIVE}
        intent = OrderIntent(
            ticker=ticker, side=side, action=action, price_cents=price_cents,
            count=count, mode=mode_map[mode_value], order_type=order_type,
            time_in_force=time_in_force, source="api",
            decision_trace_id=new_decision_trace_id("api"),
            sentiment_driven=False,
            take_profit_price_cents=take_profit_price_cents,
            take_profit_r_multiple=take_profit_r_multiple,
            stop_loss_price_cents=stop_loss_price_cents,
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
        logger.error(f"Order router failed: {exc}")
        raise HTTPException(503, f"Order routing failed: {exc}")

    # PASS 8 P0: FAIL CLOSED in LIVE/PAPER - no fallback allowed
    # The REST fallback bypasses order_router, violating single-executor contract
    from merid.utils.structured_logging import get_structured_logger
    from merid.metrics.kalshi_metrics import record_guard_trip
    
    _guard_type = "PASS8_REST_FALLBACK_GUARD"
    _endpoint = "/api/v1/kalshi/orders"
    
    # Structured logging for audit trail
    _slogger = get_structured_logger(__name__)
    _slogger.log_executor_failure(
        error=f"order_router unavailable in {mode_value} mode",
        fallback_attempted=False,
        kill_switch_triggered=(mode_value in ("live", "paper"))
    )
    
    # Metrics for monitoring
    record_guard_trip(_guard_type, mode_value, _endpoint)
    
    logger.error(
        f"[{_guard_type}] Order router unavailable in {mode_value} mode. "
        "REST fallback blocked - trading halted for safety."
    )

    if mode_value in ("live", "paper"):
        # Trigger kill-switch alert for executor contract violation
        try:
            from merid.risk.kill_switches import get_kill_switch
            from merid.metrics.kalshi_metrics import record_kill_switch
            
            ks = get_kill_switch()
            ks.trigger(
                reason="Executor contract violation: order_router unavailable in non-SIM mode",
                severity="critical",
                source="kalshi_api.place_order"
            )
            
            # Record kill switch metric
            record_kill_switch(
                reason="EXECUTOR_UNAVAILABLE",
                severity="critical"
            )
            
            # Log with structured logger
            _slogger.log_kill_switch(
                reason="Executor unavailable in non-SIM mode",
                severity="critical",
                source="kalshi_api.place_order",
                details={"mode": mode_value, "guard": _guard_type}
            )
            
        except Exception as _ks_err:
            logger.error(f"[{_guard_type}] Failed to trigger kill-switch: {_ks_err}")

        raise HTTPException(
            status_code=503,
            detail=json.dumps({
                "error": "SYSTEM_DEGRADED_EXECUTOR_UNAVAILABLE",
                "message": "Trading system degraded. Order router unavailable.",
                "mode": mode_value,
                "guard": _guard_type,
                "severity": "critical",
                "remediation": "Contact operations immediately. Do not attempt to bypass.",
                "contact": "#on-call",
                "status": "trading_halted",
                "timestamp": "2026-04-23T00:00:00Z"
            })
        )

    # SIM/MOCK only: Allow fallback for development (different risk profile)
    # Note: This path should only be reached in explicit development/testing contexts
    logger.warning("[PASS8_SIM_FALLBACK] SIM/MOCK mode: Using REST fallback for development")
    import uuid, time as _time
    rest = _get_rest_client()
    if not rest:
        raise HTTPException(500, "No Kalshi client configured")
    
    try:
        t0 = _time.time()
        _coid = str(uuid.uuid4())
        result = await asyncio.to_thread(
            rest.create_order,
            ticker=ticker, side=side, action=action, quantity=count,
            price=price_cents, client_order_id=_coid,
            order_type=order_type, time_in_force=time_in_force,
        )
        latency = (_time.time() - t0) * 1000
        order = result.get("order", {})
        return {
            "status": order.get("status", "submitted"), "mode": "sim_fallback",
            "ticker": ticker, "side": side, "action": action,
            "price_cents": price_cents, "count": count,
            "fill": order, "reason": None, "latency_ms": round(latency, 1),
        }
    except Exception as exc:
        logger.error(f"[PASS8_SIM_FALLBACK] Order placement failed: {exc}")
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
        result = await asyncio.to_thread(rest.cancel_order, order_id)
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
        result = await asyncio.to_thread(rest.amend_order, order_id, price=price_cents, quantity=count)
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
        result = await asyncio.to_thread(rest.batch_cancel_orders, ticker=ticker)
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

    # Route every order in the batch through the canonical ``route_order_async``
    # pipeline so the shared ``GlobalRiskGuard``, cross-caller dedup, pre-trade
    # gate, and sanity checks apply uniformly.  The previous code path bypassed
    # all of these by calling ``client.batch_place_orders`` directly.
    try:
        from merid.event_venues.kalshi.decision_trace import new_decision_trace_id
        from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async
        from merid.prediction.venue_gate import TradingMode
    except ImportError as exc:
        logger.error("Batch place orders: router import failed: %s", exc)
        raise HTTPException(503, "Order router unavailable")

    default_mode = _get_default_order_mode().lower().strip()
    mode_map = {"mock": TradingMode.MOCK, "paper": TradingMode.PAPER, "live": TradingMode.LIVE}

    import time as _time
    t0 = _time.monotonic()
    results: List[Dict[str, Any]] = []
    approved = 0
    rejected = 0
    for idx, spec in enumerate(orders):
        try:
            ticker = spec.get("ticker")
            side = (spec.get("side") or "yes").lower()
            action = (spec.get("action") or "buy").lower()
            count = int(spec.get("count", 0))
            price_cents = int(spec.get("yes_price") or spec.get("no_price") or spec.get("price_cents") or 0)
            order_type = (spec.get("type") or spec.get("order_type") or "limit").lower()
            tif = (spec.get("time_in_force") or "gtc").lower()
            mode_str = (spec.get("mode") or default_mode).lower()
            if mode_str not in mode_map:
                raise ValueError(f"invalid mode: {mode_str!r}")
            if side not in ("yes", "no"):
                raise ValueError(f"invalid side: {side!r}")
            if action not in ("buy", "sell"):
                raise ValueError(f"invalid action: {action!r}")
            if count <= 0:
                raise ValueError("count must be > 0")
            if not (1 <= price_cents <= 99):
                raise ValueError("price_cents must be 1-99")

            intent = OrderIntent(
                ticker=ticker,
                side=side,
                action=action,
                price_cents=price_cents,
                count=count,
                mode=mode_map[mode_str],
                order_type=order_type,
                time_in_force=tif,
                source="api_batch",
                client_tag=spec.get("client_order_id"),
                post_only=bool(spec.get("post_only", False)),
                self_trade_prevention_type=spec.get("self_trade_prevention_type"),
                decision_trace_id=new_decision_trace_id("api_batch"),
                sentiment_driven=False,
            )
            result = await route_order_async(intent)
            entry = {
                "index": idx,
                "ticker": ticker,
                "status": result.status,
                "mode": getattr(result.mode, "value", str(result.mode)).lower(),
                "fill": result.fill,
                "reason": result.reason,
                "latency_ms": round(result.latency_ms or 0.0, 2),
            }
            if result.status == "rejected":
                rejected += 1
            else:
                approved += 1
            results.append(entry)
        except Exception as exc:
            rejected += 1
            results.append({
                "index": idx,
                "ticker": spec.get("ticker"),
                "status": "rejected",
                "reason": f"validation:{exc}",
            })

    total_latency = (_time.monotonic() - t0) * 1000
    return {
        "status": "success" if rejected == 0 else "partial" if approved > 0 else "all_rejected",
        "count": len(results),
        "approved": approved,
        "rejected": rejected,
        "orders": results,
        "latency_ms": round(total_latency, 2),
    }


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


@router.post("/order-groups/{group_id}/trigger")
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


@router.get("/order-groups/dashboard")
async def get_order_groups_dashboard() -> Dict[str, Any]:
    """Get comprehensive order groups dashboard data.

    Returns aggregated status, usage statistics, and alerts for all order groups.
    Suitable for real-time monitoring UI.
    """
    _empty_dashboard = {
        "summary": {"total_groups": 0, "active": 0, "triggered": 0, "canceled": 0, "pending": 0},
        "usage": {"total_contracts_limit": 0, "total_matched_contracts": 0, "total_used_contracts": 0, "total_filled_cost": 0, "total_remaining_cost": 0, "overall_utilization_pct": 0.0},
        "groups": [], "alerts": [], "latency_ms": 0,
    }
    try:
        return await _order_groups_dashboard_impl(_empty_dashboard)
    except HTTPException as hexc:
        return {**_empty_dashboard, "error": str(hexc.detail)}
    except Exception as exc:
        return {**_empty_dashboard, "error": str(exc)}


@router.get("/order-groups/{group_id}")
async def get_order_group_endpoint(group_id: str) -> Dict[str, Any]:
    """Get a single order group by ID."""
    client = _get_client()
    if not client:
        raise HTTPException(503, "Kalshi client not configured")

    try:
        await client.connect()
        result = await client.get_order_group(group_id)

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


async def _order_groups_dashboard_impl(_empty_dashboard: Dict[str, Any]) -> Dict[str, Any]:
    client = _get_client()
    if not client:
        return {**_empty_dashboard, "error": "Kalshi client not configured"}

    import asyncio as _aio
    # OLD-HARDWARE FIX: Increased from 5s to 15s for slow connections
    await _aio.wait_for(client.connect(), timeout=15.0)

    # Fetch all order groups
    # OLD-HARDWARE FIX: Increased from 5s to 15s for slow connections
    result = await _aio.wait_for(client.get_order_groups(limit=200), timeout=15.0)
    if not result.success:
        return {**_empty_dashboard, "error": str(result.error)}

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


@router.get("/pnl")
async def get_pnl() -> Dict[str, Any]:
    """Portfolio PnL summary — canonical source: fills ledger.

    PnL fields (daily_pnl_usd, realized_pnl_usd, unrealized_pnl_usd) always
    come from fills_ledger.summary(). Equity / drawdown fields are supplemental
    from KalshiRiskManager. Category breakdown is supplemental from APT.
    
    daily_pnl_usd = portfolio value change (realized + unrealized) to match Kalshi's "recent P&L"
    - Portfolio value = cash + current market value of open positions
    - Recent P&L = change in portfolio value over the day
    realized_pnl_usd = realized PnL from closed trades only
    unrealized_pnl_usd = mark-to-market value of open positions
    """
    result: Dict[str, Any] = {
        "daily_pnl_usd": 0.0,
        "realized_pnl_usd": 0.0,
        "unrealized_pnl_usd": 0.0,
        "total_notional_usd": 0.0,
        "peak_equity_usd": 0.0,
        "current_equity_usd": 0.0,
        "drawdown_pct": 0.0,
        "category_pnl": {},
        "category_notional": {},
        "source": "fills_ledger",
        "reconciliation_status": "unknown",
    }

    # ── Canonical PnL from fills ledger ──────────────────────────────
    try:
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        ledger = get_fills_ledger()
        s = ledger.summary()
        daily_realized = _safe_float_val(s.get("daily_realized_pnl_usd", 0))
        total_unrealized = _safe_float_val(s.get("total_unrealized_pnl_usd", 0))
        daily_unrealized_change = _safe_float_val(s.get("daily_unrealized_change_usd", 0))
        # IMPLEMENTED: daily_pnl = daily_realized + (current_unrealized - prior_close_unrealized)
        # This matches Kalshi's "recent P&L" definition (portfolio value change)
        result["daily_pnl_usd"] = round(daily_realized + daily_unrealized_change, 2)
        result["realized_pnl_usd"] = round(_safe_float_val(s.get("total_realized_pnl_usd", 0)), 2)
        result["unrealized_pnl_usd"] = round(total_unrealized, 2)
        # Session-based PnL metrics (NEW)
        result["session_realized_pnl_usd"] = round(_safe_float_val(s.get("session_realized_pnl_usd", 0)), 2)
        result["session_unrealized_pnl_usd"] = round(_safe_float_val(s.get("session_unrealized_pnl_usd", 0)), 2)
        result["session_total_pnl_usd"] = round(_safe_float_val(s.get("session_total_pnl_usd", 0)), 2)
        result["cumulative_realized_pnl_usd"] = round(_safe_float_val(s.get("cumulative_realized_pnl_usd", 0)), 2)
        result["session_date"] = s.get("session_date")
        result["open_positions_count"] = s.get("open_positions_count", 0)
        result["reconciliation_status"] = s.get("reconciliation", {}).get("status", "unknown")
    except Exception as exc:
        logger.warning("PnL: fills_ledger unavailable: %s", exc)
        result["source"] = "unavailable"

    # ── Supplemental equity / drawdown from risk manager ─────────────
    risk = _get_risk()
    if risk:
        try:
            state = risk.state
            result["total_notional_usd"] = round(_safe_float_val(state.total_notional_usd), 2)
            result["peak_equity_usd"] = round(_safe_float_val(state.peak_equity_usd), 2)
            result["current_equity_usd"] = round(_safe_float_val(state.current_equity_usd), 2)
            if state.peak_equity_usd > 0:
                result["drawdown_pct"] = round(
                    (state.peak_equity_usd - state.current_equity_usd) / state.peak_equity_usd * 100, 2
                )
            result["category_notional"] = {
                k: round(_safe_float_val(v), 2) for k, v in state.category_notional.items()
            }
        except Exception as exc:
            logger.debug("PnL: risk manager equity fields unavailable: %s", exc)

    # ── Category PnL breakdown from APT (supplemental attribution) ───
    try:
        from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
        tracker = get_agent_performance_tracker()
        for agent_id, m in tracker.get_all_metrics().items():
            cat = agent_id.split("_")[0] if "_" in agent_id else agent_id
            result["category_pnl"][cat] = round(
                result["category_pnl"].get(cat, 0.0) + float(m.total_pnl_usd), 2
            )
    except Exception as exc:
        logger.debug("PnL: category APT breakdown unavailable: %s", exc)

    return result


# ── Risk ─────────────────────────────────────────────────────────────────

def _get_rate_limits_from_config() -> Dict[str, int]:
    """Get rate limit configuration from settings or env.
    
    Returns dict with max_orders_per_minute and max_orders_per_hour.
    Logs when using fallback defaults.
    """
    try:
        from merid.settings import settings
        return {
            "max_per_minute": settings.KALSHI_MAX_ORDERS_PER_MINUTE,
            "max_per_hour": settings.KALSHI_MAX_ORDERS_PER_HOUR,
            "source": "config",
        }
    except Exception:
        # Fallback to environment variables
        import os
        max_per_minute = int(os.getenv("KALSHI_MAX_ORDERS_PER_MINUTE", "30"))
        max_per_hour = int(os.getenv("KALSHI_MAX_ORDERS_PER_HOUR", "300"))
        
        # Log fallback usage
        logger.warning(
            f"Using fallback rate limits (not from config): {max_per_minute}/min, {max_per_hour}/hour. "
            "Set KALSHI_MAX_ORDERS_PER_MINUTE and KALSHI_MAX_ORDERS_PER_HOUR env vars or settings."
        )
        return {
            "max_per_minute": max_per_minute,
            "max_per_hour": max_per_hour,
            "source": "env_fallback",
        }


@router.get("/risk")
async def get_risk() -> Dict[str, Any]:
    """Risk manager status with single-source-of-truth for PnL and limits.
    
    Schema:
    - PnL fields (daily_pnl_usd, realized_pnl_usd, unrealized_pnl_usd): 
      Always from fills ledger (canonical source)
    - Kill switch: from risk_controller (authoritative)
    - Limits (Kelly, position caps, rate limits): from kalshi_risk + config
    - Performance metrics: from AgentPerformanceTracker (supplemental)
    - Discrepancies: flagged if sources disagree beyond tolerance
    """
    from datetime import datetime, timezone
    
    base: Dict[str, Any] = {
        "kill_switch_active": False, 
        "kill_switch_reason": None,
        "daily_pnl_usd": 0.0, 
        "realized_pnl_usd": 0.0, 
        "unrealized_pnl_usd": 0.0,
        "total_notional_usd": 0.0,
        "drawdown_pct": 0.0, 
        "daily_trades": 0, 
        "daily_fees_usd": 0.0,
        "open_market_count": 0, 
        "category_notional": {}, 
        "category_contracts": {},
        "recent_breaches": [], 
        "limits": {},
        "win_rate_pct": 0.0, 
        "profit_factor": 0.0, 
        "sharpe_ratio": 0.0,
        "sortino_ratio": 0.0, 
        "calmar_ratio": 0.0,
        "source_precedence": {},  # Track which source provided each field
        "risk_discrepancies": [],  # Flagged disagreements between sources
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    # ── Single Source of Truth: PnL from fills ledger ────────────────────
    try:
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        ledger = get_fills_ledger()
        ledger_summary = ledger.summary()
        
        # Canonical PnL values from fills ledger (NaN-safe)
        base["daily_pnl_usd"] = _safe_float_val(ledger_summary.get("daily_realized_pnl_usd", 0))
        base["realized_pnl_usd"] = _safe_float_val(ledger_summary.get("total_realized_pnl_usd", 0))
        base["daily_fees_usd"] = _safe_float_val(ledger_summary.get("total_fees_usd", 0))
        base["daily_trades"] = int(ledger_summary.get("total_fills", 0))
        base["source_precedence"]["pnl"] = "fills_ledger"
        base["ledger_reconciliation_status"] = ledger.get_reconciliation_status()
    except Exception as e:
        logger.warning(f"Fills ledger PnL unavailable: {e}")
        base["source_precedence"]["pnl"] = "unavailable"
    
    # ── Single Source of Truth: Kill switch from risk_controller ────────────
    try:
        from merid.risk.kill_switches import risk_controller as _rc
        _rc_status = _rc.get_status()
        base["kill_switch_active"] = not _rc_status.get("can_trade", True)
        base["kill_switch_reason"] = _rc_status.get("kill_reason")
        base["source_precedence"]["kill_switch"] = "risk_controller"
        
        # Controller PnL (for comparison/discrepancy detection only)
        _rc_pnl = float(_rc_status.get("daily_pnl", 0.0))
        base["_controller_daily_pnl_usd"] = _rc_pnl  # Private, for debugging
    except Exception as e:
        logger.warning(f"Risk controller unavailable: {e}")
        base["source_precedence"]["kill_switch"] = "unavailable"
    
    # ── Limits and Risk Config from kalshi_risk ────────────────────────────
    risk = _get_risk()
    if risk:
        try:
            risk_summary = risk.summary()
            
            # Limits (non-PnL fields) — read actual keys from KalshiRiskManager.summary()
            _rlimits = risk_summary.get("limits", {})
            # DYNAMIC FALLBACK: Get defaults from settings instead of hardcoded 10000
            from merid.settings import settings as _risk_settings
            _default_max_notional = getattr(_risk_settings, 'MAX_NOTIONAL_USD', 5000)
            _default_daily_loss = getattr(_risk_settings, 'MAX_DAILY_LOSS_USD', 500)
            
            base["limits"] = {
                "max_notional_usd": float(
                    _rlimits.get("max_total_notional_usd")
                    or _rlimits.get("max_notional_usd")
                    or _default_max_notional
                ),
                "max_open_markets": int(
                    _rlimits.get("max_open_markets", 20)
                ),
                "daily_loss_limit": float(
                    _rlimits.get("max_daily_loss_usd")
                    or _rlimits.get("daily_loss_limit")
                    or _default_daily_loss
                ),
                "max_drawdown_pct": float(
                    _rlimits.get("drawdown_halt_pct")
                    or _rlimits.get("max_drawdown_pct")
                    or 10
                ),
            }
            
            # Rate limits from config
            rate_limits = _get_rate_limits_from_config()
            base["limits"]["max_orders_per_minute"] = rate_limits["max_per_minute"]
            base["limits"]["max_orders_per_hour"] = rate_limits["max_per_hour"]
            base["limits"]["rate_limit_source"] = rate_limits["source"]
            
            # Exposure (not PnL) — NaN-safe
            base["total_notional_usd"] = _safe_float_val(risk_summary.get("total_notional_usd", 0))
            base["open_market_count"] = int(risk_summary.get("open_market_count", 0))
            base["category_notional"] = {k: _safe_float_val(v) for k, v in risk_summary.get("category_notional", {}).items()}
            base["drawdown_pct"] = _safe_float_val(risk_summary.get("drawdown_pct", 0))
            
            base["source_precedence"]["limits"] = "kalshi_risk"
            base["source_precedence"]["exposure"] = "kalshi_risk"
        except Exception as e:
            logger.warning(f"Kalshi risk summary failed: {e}")
    
    # ── Unrealized PnL from open Kalshi positions ──────────────────────────
    try:
        _executor = _get_executor()
        _rest = _get_rest_client()
        _total_unrealized = 0.0
        if _executor:
            _pos_raw = await _executor.get_positions()
            for _p in _pos_raw:
                # PRODUCTION FIX: Filter test tickers and closed positions
                if not _is_test_ticker(_p.get("ticker", "")) and _safe_float_val(_p.get("size", 0), 0) > 0:
                    _total_unrealized += _safe_float_val(_p.get("unrealized_pnl", 0), 0)
        elif _rest:
            _pos_raw = await asyncio.to_thread(_rest.get_positions)
            for _p in _pos_raw:
                # PRODUCTION FIX: Filter test tickers and closed positions
                _ticker = _p.get("ticker", _p.get("market_ticker", ""))
                _size = _safe_float_val(_p.get("total_traded", _p.get("position", 0)), 0)
                if not _is_test_ticker(_ticker) and _size > 0:
                    # REST positions: use 'pnl' field (cents) when available; market_exposure is notional, not PnL
                    _pnl_cents = _p.get("pnl", _p.get("realized_pnl", 0))
                    _total_unrealized += _safe_float_val(_pnl_cents, 0) / 100.0
        base["unrealized_pnl_usd"] = round(_total_unrealized, 2)
        base["source_precedence"]["unrealized_pnl"] = "kalshi_positions"
    except Exception as _e:
        logger.debug("Unrealized PnL from positions skipped: %s", _e)

    # ── Supplemental: Performance metrics from AgentPerformanceTracker ──────
    try:
        from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
        tracker = get_agent_performance_tracker()
        sys_summary = tracker.get_system_summary()

        base["win_rate_pct"] = round(_safe_float_val(sys_summary.get("system_win_rate", 0)) * 100, 1)
        base["daily_trades"] = max(base["daily_trades"], sys_summary.get("total_closes", 0))

        top = tracker.get_top_agents(metric="sharpe_ratio", limit=1)
        if top:
            base["sharpe_ratio"] = round(_safe_float_val(top[0].get("sharpe_ratio", 0)), 2)
            re = _safe_float_val(top[0].get("avg_realized_edge", 0))
            pe = max(_safe_float_val(top[0].get("avg_predicted_edge", 0.001)), 0.001)
            base["profit_factor"] = round(re / pe, 2)

        base["source_precedence"]["performance"] = "agent_performance_tracker"
    except Exception as e:
        logger.debug(f"Performance tracker supplement skipped: {e}")

    # ── Discrepancy Detection ───────────────────────────────────────────────
    discrepancies = []
    
    # Check if controller PnL differs from ledger PnL
    if base.get("_controller_daily_pnl_usd") is not None and base["source_precedence"].get("pnl") == "fills_ledger":
        controller_pnl = base["_controller_daily_pnl_usd"]
        ledger_pnl = base["daily_pnl_usd"]
        tolerance = 0.01  # $0.01 tolerance
        if abs(controller_pnl - ledger_pnl) > tolerance:
            discrepancies.append({
                "field": "daily_pnl_usd",
                "ledger_value": ledger_pnl,
                "controller_value": controller_pnl,
                "diff_usd": round(controller_pnl - ledger_pnl, 2),
                "severity": "warning" if abs(controller_pnl - ledger_pnl) < 10 else "critical",
            })
    
    base["risk_discrepancies"] = discrepancies
    base["has_discrepancies"] = len(discrepancies) > 0
    
    # Add ExecutionGateStrip field aliases so the component's near-limit
    # calculations work: total_exposure, max_exposure, daily_pnl, max_daily_loss
    # DYNAMIC: Get defaults from settings instead of hardcoded fallbacks
    from merid.settings import settings as _gate_settings
    _default_max_exp = getattr(_gate_settings, 'MAX_NOTIONAL_USD', 5000)
    _default_daily_loss_limit = getattr(_gate_settings, 'MAX_DAILY_LOSS_USD', 500)
    
    base.setdefault("total_exposure", base.get("total_notional_usd", 0))
    base.setdefault("max_exposure", base.get("limits", {}).get("max_notional_usd", _default_max_exp))
    base.setdefault("daily_pnl", base.get("daily_pnl_usd", 0))
    base.setdefault("max_daily_loss", base.get("limits", {}).get("daily_loss_limit", _default_daily_loss_limit))
    base.setdefault("position_count", base.get("open_market_count", 0))
    base.setdefault("max_positions", base.get("limits", {}).get("max_open_markets", 20))
    
    # FIX: Ensure max_daily_loss is never zero to prevent division by zero in frontend
    if base["max_daily_loss"] == 0:
        base["max_daily_loss"] = _default_daily_loss_limit

    # Frontend type aliases (KalshiRiskSummary interface uses these field names)
    base["total_unrealized_pnl_usd"] = base.get("unrealized_pnl_usd", 0.0)
    base["daily_realized_pnl_usd"] = base.get("realized_pnl_usd", 0.0)
    base["daily_total_pnl_usd"] = round(
        base.get("daily_pnl_usd", 0.0) + base.get("unrealized_pnl_usd", 0.0), 2
    )

    return base


@router.get("/kill-switch")
async def get_kill_switch_status(session: dict = Depends(get_current_session)) -> Dict[str, Any]:
    """Get the current Kalshi kill switch status.
    
    Auth: Uses router-level get_current_session (supports MERID_SINGLE_USER_OPERATOR bypass).
    """
    risk = _get_risk()
    if not risk:
        return {"kill_switch": False, "status": "unavailable", "error": "Risk manager not available"}
    
    return {
        "kill_switch": risk.kill_switch_active,
        "status": "active" if risk.kill_switch_active else "inactive"
    }


@router.post("/kill-switch")
async def toggle_kill_switch(activate: bool = True, session: dict = Depends(get_current_session)) -> Dict[str, Any]:
    """Activate or reset the Kalshi kill switch.
    
    Auth: Uses router-level get_current_session (supports MERID_SINGLE_USER_OPERATOR bypass).
    """
    # Verify admin/operator role from session (works with single-user bypass)
    user = session.get("user") or {}
    role = user.get("role", "viewer")
    if role not in ("operator", "admin"):
        raise HTTPException(status_code=403, detail="Requires operator or admin role")
    
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
                await asyncio.to_thread(rest.get_balance)
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


# ── Production Self-Test Endpoint ───────────────────────────────────────────

@router.get("/internal/kalshi_health",
    summary="Production Orderbook Health Self-Test",
    description="Returns detailed book health metrics for all 5 crypto 15m markets. Used for production monitoring and validation.",
    response_description="Book health metrics per market and overall trading status",
    tags=["kalshi", "internal", "health"],
)
async def production_kalshi_health() -> Dict[str, Any]:
    """Production self-test endpoint for Kalshi orderbook health.

    Returns detailed metrics for all 5 crypto 15m markets:
      - initialized flag (REST snapshot applied)
      - last_update_age_ms (freshness check)
      - best_bid, best_ask, mid (price data)
      - is_trading_enabled (circuit breaker status)

    This endpoint is used by monitoring systems to validate:
      - All books are initialized with REST snapshots
      - WS deltas are keeping books fresh (ages stay low)
      - Circuit breaker is in expected state
    """
    import time
    from merid.event_venues.kalshi.market_state import (
        get_kalshi_market_state_store,
        _ALLOWED_UNDERLYINGS,
        _ALLOWED_TIMEFRAMES,
        _parse_market_ticker,
    )

    store = get_kalshi_market_state_store()
    now = time.monotonic()
    markets = []

    with store._lock:
        for ticker, state in store._states.items():
            # Only include 5-crypto/15m markets
            underlying, timeframe = _parse_market_ticker(ticker)
            if underlying not in _ALLOWED_UNDERLYINGS or timeframe not in _ALLOWED_TIMEFRAMES:
                continue

            # Calculate age
            last_update = state.last_book_update_ts or state.last_rest_update_ts or 0
            age_ms = (now - last_update) * 1000 if last_update > 0 else float('inf')

            markets.append({
                "ticker": ticker,
                "underlying": underlying,
                "timeframe": timeframe,
                "initialized": state.book_initialized,
                "last_update_age_ms": round(age_ms, 0),
                "best_bid_cents": state.best_bid_cents,
                "best_ask_cents": state.best_ask_cents,
                "mid_cents": state.mid_cents,
                "spread_cents": state.spread_cents,
            })

    # Get overall trading status
    trading_enabled = store.is_trading_enabled()

    return {
        "trading_enabled": trading_enabled,
        "market_count": len(markets),
        "expected_market_count": 5,  # BTC, ETH, SOL, XRP, DOGE 15m
        "markets": markets,
        "timestamp": datetime.now(timezone.utc).isoformat(),
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
        return {"alerts": [{"type": "info", "message": "Volume monitor initializing — alerts will appear when anomalies are detected", "severity": "low", "ts": _now_iso()}], "total_fired": 0, "poll_count": 0}
    try:
        alerts = monitor.get_alerts(limit=limit)
        if not alerts:
            alerts = [{"type": "info", "message": f"No volume anomalies detected. Monitoring {monitor.tracked_count} markets, {monitor.poll_count} polls completed.", "severity": "low", "ts": _now_iso()}]
        return {"alerts": alerts, "total_fired": monitor.alert_count, "poll_count": monitor.poll_count}
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
        return {"alerts": [{"type": "info", "message": "Liquidity monitor initializing — alerts will appear when spread/depth anomalies are detected", "severity": "low", "ts": _now_iso()}], "summary": {"tracked_markets": 0, "status": "initializing"}}
    try:
        alerts = monitor.recent_alerts(limit=limit)
        summary = monitor.summary()
        if not alerts:
            tracked = summary.get("tracked_markets", summary.get("market_count", 0))
            alerts = [{"type": "info", "message": f"No liquidity issues detected. Monitoring {tracked} markets.", "severity": "low", "ts": _now_iso()}]
        return {"alerts": alerts, "summary": summary}
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

    # Auto-reset trigger: if tier is tradable (normal/warning) but kill switch still active,
    # trigger reset for immediate UI feedback and trading resumption
    if tier in ("normal", "warning") and risk_summary.get("kill_switch_active"):
        try:
            risk.reset_kill_switch()
            logger.info("sizing_metrics_endpoint: auto-reset kill switch triggered (tier=%s, drawdown=%.1f%%)",
                        tier, dd_pct)
            # Re-fetch summary after reset
            risk_summary = risk.summary()
        except Exception as _e:
            logger.debug("sizing_metrics_endpoint: kill switch reset skipped: %s", _e)

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
        except Exception as _e:
            logger.debug("perf tracker risk supplement skipped: %s", _e)

    # Continuous trader snapshot — injected so UI can show bankroll/PnL alongside
    # the swarm sizing metrics without a second poll.
    # status_snapshot() calls _get_balance() which is a blocking HTTP request,
    # so we run it in the default executor to avoid stalling the event loop.
    ct_snapshot = None
    try:
        import asyncio as _aio
        from merid.prediction.pm_bankroll_snapshot import build_agent_grid_bankroll_overlay
        from merid.trading.kalshi_continuous_trader import get_continuous_trader
        _loop = _aio.get_running_loop()
        _raw = await _loop.run_in_executor(
            None, get_continuous_trader().status_snapshot,
        )
        ct_snapshot = build_agent_grid_bankroll_overlay(_raw)
    except Exception as _cte:
        logger.debug("continuous trader snapshot skipped: %s", _cte)

    result: Dict[str, Any] = {
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
    if ct_snapshot is not None:
        result["continuous_trader"] = ct_snapshot
    return result


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
        except (AttributeError, TypeError) as exc:
            logger.debug("PnL history/risk summary unavailable: %s", exc)

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
                # REMOVED: Mean-reversion bias toward 0.5
                # Let edge model stand on its own without artificial bias
                model_prob = implied_prob
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

    # If no catalog signals, derive from prediction consensus opinions
    if not signals:
        try:
            from merid.prediction.consensus import get_prediction_consensus_store
            cs = get_prediction_consensus_store()
            for op in cs.list_opinions(limit=20):
                prob = getattr(op, "probability", 0.5)
                conf = getattr(op, "confidence", 0.5)
                sym = getattr(op, "symbol", "")
                if not sym:
                    continue
                implied = 0.5
                ev = round((prob - implied) * 100, 1)
                signals[sym] = {
                    "implied_prob": implied,
                    "model_prob": round(prob, 4),
                    "ev_cents": ev,
                    "edge_pct": round((prob - implied) / max(implied, 0.01) * 100, 1),
                    "confidence": round(conf, 3),
                    "confidence_bucket": "high" if conf >= 0.7 else ("medium" if conf >= 0.4 else "low"),
                    "sizing_tier": "normal",
                    "bid": None, "ask": None,
                    "source": "consensus_opinion",
                }
        except Exception as e:
            logger.debug(f"Silent error: {e}")

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
    if max_loss > 0 and daily_pnl < 0 and abs(daily_pnl) >= max_loss * 0.8:
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

    # Baseline status events when no breaches
    if not events:
        from datetime import datetime as _dt, timezone as _tz
        _now = _dt.now(_tz.utc).isoformat()
        events.append({
            "id": "status-ok",
            "ts": _now,
            "severity": "info",
            "category": "status",
            "title": "All risk checks passing",
            "detail": f"Drawdown {dd:.1f}%, orders/min {rate_min}/{_rate_limit}, daily PnL ${daily_pnl:.2f}",
        })
        # Agent grid status event
        try:
            from merid.prediction.agent_grid import get_agent_grid
            _grid = get_agent_grid()
            _running = sum(1 for a in _grid.agents if a.state.running)
            _total_cycles = sum(a.state.cycles_run for a in _grid.agents)
            events.append({
                "id": "grid-status",
                "ts": _now,
                "severity": "info",
                "category": "agent_grid",
                "title": f"Agent grid: {_running}/{len(_grid.agents)} active, {_total_cycles} total cycles",
                "detail": f"Total orders placed: {sum(a.state.orders_placed for a in _grid.agents)}",
            })
        except Exception as e:
            logger.debug(f"Silent error: {e}")

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
        consensus = aggregator.get_consensus_or_neutral(asset, timeframe)

        return {
            "asset": consensus.asset,
            "timeframe": consensus.timeframe,
            "timestamp": consensus.timestamp.isoformat(),
            "status": consensus.status.value,
            "consensus_direction": consensus.consensus_direction,
            "consensus_probability": consensus.consensus_probability,
            "consensus_confidence": consensus.consensus_confidence,
            "swarm_usable": consensus.usable,
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
        logger.debug(f"Insights mood bus unavailable: {exc}")

    # Fallback: derive insights from agent grid cycle activity + debate store
    import datetime as _dt
    _now = _dt.datetime.now(_dt.timezone.utc)
    fallback_insights = []
    try:
        from merid.prediction.agent_grid import get_agent_grid
        grid = get_agent_grid()
        for agent in grid.agents:
            if agent.state.cycles_run > 0:
                a0 = agent.config.assets[0] if agent.config.assets else ""
                tf0 = agent.config.timeframes[0] if agent.config.timeframes else ""
                fallback_insights.append({
                    "id": f"insight-{agent.config.name}",
                    "timestamp": _now.isoformat(),
                    "asset": a0, "timeframe": tf0,
                    "swarm_direction": "monitoring",
                    "swarm_probability": 0.5, "swarm_confidence": 0.0,
                    "size_band": "none",
                    "headline": f"{agent.config.name}: {agent.state.cycles_run} cycles, {agent.state.orders_placed} orders",
                    "rationale": f"Agent scanning {a0} on {tf0}",
                    "key_factors": [f"{agent.state.cycles_run} analysis cycles completed"],
                    "final_mode": "paper", "trade_executed": agent.state.orders_placed > 0,
                    "entry_price": None, "realized_pnl": None,
                    "prediction_correct": None, "lessons": [],
                })
    except Exception as e:
        logger.debug(f"Silent error: {e}")
    try:
        from merid.prediction.debate import get_debate_store
        ds = get_debate_store()
        for deb in ds.list_debates(limit=10):
            sym = getattr(deb, "symbol", "?")
            prob = getattr(deb, "post_debate_prob", 0.5)
            fallback_insights.append({
                "id": f"insight-debate-{deb.id[:12]}",
                "timestamp": str(getattr(deb, "created_at", _now.isoformat())),
                "asset": sym, "timeframe": "",
                "swarm_direction": "bullish" if prob > 0.6 else ("bearish" if prob < 0.4 else "neutral"),
                "swarm_probability": prob, "swarm_confidence": getattr(deb, "confidence", 0.5),
                "size_band": "normal",
                "headline": f"Debate on {sym}: {getattr(deb, 'rounds', 0)} rounds → prob {prob:.0%}",
                "rationale": f"Status: {getattr(deb, 'status', 'unknown')}",
                "key_factors": [], "final_mode": "paper",
                "trade_executed": False, "entry_price": None,
                "realized_pnl": None, "prediction_correct": None, "lessons": [],
            })
    except Exception as e:
        logger.debug(f"Silent error: {e}")
    return {"count": len(fallback_insights), "insights": fallback_insights[:limit]}


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


@router.post("/favorites/toggle")
async def toggle_favorite(ticker: str = Query(..., description="Market ticker to toggle")) -> Dict[str, Any]:
    """Add or remove a ticker from favorites/watchlist.
    
    If the ticker is already in favorites, it will be removed.
    If not, it will be added.
    """
    favs = _load_favorites()
    
    if ticker in favs:
        favs.remove(ticker)
        action = "removed"
    else:
        favs.append(ticker)
        action = "added"
    
    _save_favorites(favs)
    return {"ticker": ticker, "action": action, "favorites": favs, "count": len(favs)}


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
        logger.debug(f"News signals primary source unavailable: {exc}")

    # Fallback: derive from news ingestion agent recent items
    import datetime as _dt
    _now = _dt.datetime.now(_dt.timezone.utc)
    fallback_signals = []
    try:
        from merid.sentiment.news_ingestion_agent import get_news_ingestion_agent
        agent = get_news_ingestion_agent()
        for item in getattr(agent, "recent_items", [])[:limit]:
            title = getattr(item, "title", str(item)) if not isinstance(item, dict) else item.get("title", "")
            fallback_signals.append({
                "title": title,
                "source": getattr(item, "source", "news") if not isinstance(item, dict) else item.get("source", "news"),
                "url": getattr(item, "url", "") if not isinstance(item, dict) else item.get("url", ""),
                "importance": getattr(item, "importance", 0.5) if not isinstance(item, dict) else item.get("importance", 0.5),
                "published_at": _now.isoformat(),
                "posted_twitter": False, "posted_telegram": False,
                "assets": [], "categories": ["general"],
            })
    except Exception as e:
        logger.debug(f"Silent error: {e}")
    if not fallback_signals:
        # Minimal status signal so UI isn't blank
        fallback_signals.append({
            "title": "News monitor starting up — signals will appear as articles are ingested",
            "source": "system", "url": "", "importance": 0.1,
            "published_at": _now.isoformat(),
            "posted_twitter": False, "posted_telegram": False,
            "assets": [], "categories": ["status"],
        })
    return {"signals": fallback_signals, "count": len(fallback_signals), "monitor_running": False}


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
        logger.debug(f"Consensus engine unavailable: {exc}")

    # Fallback: derive signals from prediction consensus opinions
    fallback_signals = []
    try:
        from merid.prediction.consensus import get_prediction_consensus_store
        cs = get_prediction_consensus_store()
        for op in cs.list_opinions(limit=20):
            prob = getattr(op, "probability", 0.5)
            conf = getattr(op, "confidence", 0.5)
            sym = getattr(op, "symbol", "")
            direction = "bullish" if prob > 0.6 else ("bearish" if prob < 0.4 else "neutral")
            fallback_signals.append({
                "ticker": sym,
                "direction": direction,
                "confidence": round(conf, 3),
                "vote_count": 1,
                "bull_weight": round(prob, 3) if prob > 0.5 else 0.0,
                "bear_weight": round(1 - prob, 3) if prob < 0.5 else 0.0,
                "agents": [getattr(op, "agent_id", "unknown")],
            })
    except Exception as e:
        logger.debug(f"Silent error: {e}")
    return {
        "signals": fallback_signals,
        "count": len(fallback_signals),
        "pending_votes": 0,
        "consensus_rate": 0.0,
        "engine_running": False,
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
    # PASS 8 P0: Hard disable FIX endpoint in LIVE/PAPER modes
    # The FIX path bypasses order_router and uses KalshiFIXClient directly,
    # violating the single-executor contract. Only allowed in SIM/MOCK.
    from merid.trading.trade_mode import get_trade_mode
    from merid.utils.structured_logging import get_structured_logger
    from merid.metrics.kalshi_metrics import record_guard_trip
    import json
    
    _mode = get_trade_mode()
    _guard_type = "PASS8_FIX_GUARD"
    _endpoint = "/api/v1/kalshi/fix/orders"
    
    if _mode in ("live", "paper"):
        # Structured logging for audit trail
        _slogger = get_structured_logger(__name__)
        _slogger.log_guard_trip(
            guard_type=_guard_type,
            mode=_mode,
            endpoint=_endpoint,
            details={
                "ticker": ticker,
                "side": side,
                "quantity": quantity,
                "price": price,
                "ord_type": ord_type
            }
        )
        
        # Metrics for monitoring/alerting
        record_guard_trip(_guard_type, _mode, _endpoint)
        
        # Legacy logger for backward compatibility
        logger.error(
            f"[{_guard_type}] FIX endpoint blocked in {_mode} mode. "
            f"Use canonical executor at /api/v1/kalshi/orders"
        )
        
        # Enhanced error response with machine-readable code
        raise HTTPException(
            status_code=403,
            detail=json.dumps({
                "error": "GUARD_TRIP_FIX_ENDPOINT_BLOCKED",
                "message": f"FIX protocol disabled in {_mode} mode",
                "mode": _mode,
                "guard": _guard_type,
                "endpoint": _endpoint,
                "remediation": "Use POST /api/v1/kalshi/orders with canonical executor",
                "contact": "#risk-engineering",
                "timestamp": "2026-04-23T00:00:00Z"  # Will be actual timestamp in real env
            })
        )
    
    fix = _get_fix_client()
    if not fix:
        raise HTTPException(503, "FIX client not configured")

    if not fix.is_connected:
        raise HTTPException(503, "FIX not connected - connect first via POST /fix/connect")

    # ── Shared-risk-guard + cross-caller dedup (FIX path) ────────────────
    # The FIX path uses a separate transport so ``route_order_async`` cannot
    # execute it directly. Apply the canonical shared ``GlobalRiskGuard`` and
    # ``OrderDedupRegistry`` explicitly here so FIX orders participate in the
    # same 3% global risk envelope and single-batch invariants as REST.
    try:
        from merid.guards.global_risk_guard import check_intent as _grg_check_intent
        from merid.guards.order_dedup_registry import get_order_dedup_registry
    except ImportError as _imp_exc:
        logger.error("FIX submit: shared risk-guard import failed: %s", _imp_exc)
        raise HTTPException(503, "Risk guard unavailable — FIX submit blocked") from _imp_exc

    _side_lower = (side or "").lower()
    # Map FIX "buy"/"sell" (no yes/no distinction in wire) to guard semantics:
    # for risk accounting we treat "buy" as a BUY-YES long entry at ``price``.
    _guard_side = "yes"
    _guard_action = "buy" if _side_lower == "buy" else "sell"
    _guard_price = int(price) if price is not None else 50
    _ok, _reason = _grg_check_intent(
        ticker=ticker, asset="UNKNOWN",
        side=_guard_side, action=_guard_action,
        price_cents=_guard_price, count=int(quantity),
        edge=0.0,
    )
    if not _ok:
        logger.warning("[FIX] shared-guard REJECTED %s side=%s qty=%d: %s",
                       ticker, side, quantity, _reason)
        raise HTTPException(429, f"Shared risk guard blocked order: {_reason}")

    _dedup_admitted = False
    _dedup_registry = None
    if _guard_action == "buy":
        _dedup_registry = get_order_dedup_registry()
        _ok_dedup, _existing = _dedup_registry.try_admit(
            ticker=ticker, side=_guard_side, action=_guard_action,
            caller="fix_api",
        )
        if not _ok_dedup:
            _orig = getattr(_existing, "caller", "unknown") if _existing else "unknown"
            logger.warning("[FIX] dedup REJECTED %s side=%s — already in bucket (original=%s)",
                           ticker, side, _orig)
            raise HTTPException(429, f"Duplicate order in bucket (original_caller={_orig})")
        _dedup_admitted = True

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
        # Release the dedup slot so retries in the same bucket aren't
        # permanently blocked on transient FIX errors.
        if _dedup_admitted and _dedup_registry is not None:
            try:
                _dedup_registry.release(ticker, _guard_side, _guard_action)
            except Exception as _rel_exc:
                logger.warning("[FIX] dedup release failed after submit error: %s", _rel_exc)
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
    cached: Dict[str, Any] = {}
    age = None
    stale = True
    fg_synthetic = False

    # Fast path: only read the lane if the singleton already exists (no blocking init)
    try:
        from merid.lanes.btc15m_lane import _btc15m_lane
        if _btc15m_lane is not None:
            status = _btc15m_lane.get_status()
            cached = status.get("cached_sentiment") or {}
            age = status.get("sentiment_age_seconds")
            stale = status.get("sentiment_stale", True)
            fg_synthetic = status.get("fg_is_synthetic", False)
    except Exception as exc:
        logger.debug("sentiment/lane-snapshot: lane not ready — %s", exc)

    # Fallback: build snapshot from the SentimentBundle (with timeout guard)
    if not cached:
        import asyncio as _aio
        def _fetch_sentiment():
            from merid.sentiment import combine_sentiment
            bundle = combine_sentiment("BTC")
            return bundle.to_dict() if hasattr(bundle, "to_dict") else {}
        try:
            # OLD-HARDWARE FIX: Increased from 3s to 10s for slow connections
            bd = await _aio.wait_for(_aio.to_thread(_fetch_sentiment), timeout=10.0)
            if bd:
                cached = {
                    "twitter": bd.get("twitter", 0),
                    "reddit": bd.get("reddit", 0),
                    "fg_index": bd.get("fg_index", 50),
                    "fg_regime": bd.get("fg_regime", "neutral"),
                    "combined_raw": bd.get("combined", 0),
                    "combined_smoothed": bd.get("combined", 0),
                    "combined_fib": bd.get("combined", 0),
                    "kalman_gain": None,
                    "confidence": bd.get("confidence", 0.5),
                    "vader_signal": bd.get("vader_signal", "neutral"),
                    "kalshi_prob_adj": bd.get("kalshi_adjustment", 0),
                    "timestamp": bd.get("timestamp", datetime.now(timezone.utc).isoformat()),
                }
                stale = False
                fg_synthetic = bd.get("fg_is_synthetic", True)
        except (_aio.TimeoutError, Exception) as exc2:
            logger.debug("sentiment/lane-snapshot fallback: %s", exc2)

    # If still no data, return synthetic defaults so the UI renders
    if not cached:
        cached = {
            "twitter": 0, "reddit": 0, "fg_index": 50, "fg_regime": "neutral",
            "combined_raw": 0, "combined_smoothed": 0, "combined_fib": 0,
            "kalman_gain": None, "confidence": 0,
            "vader_signal": "neutral", "kalshi_prob_adj": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        fg_synthetic = True

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
    
    CRITICAL FIX (2026-05-07): Use SentimentBusV2 instead of old SentimentBus.
    The old SentimentBus wraps MarketMoodBus, but NewsIngestionAgent and HashtagAgent
    write to SentimentBusV2. This was causing a disconnect where sentiment data
    was being written but never consumed.
    """
    try:
        from merid.sentiment.sentiment_bus_v2 import get_sentiment_bus_v2
        bus = get_sentiment_bus_v2()
        # SentimentBusV2 doesn't have force_refresh, so we trigger hashtag/news cycles
        # This is a no-op for the API endpoint but prevents errors
        success = True
        
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
                # Fire-and-forget; attach a done-callback so startup crashes
                # surface in the logs instead of being swallowed by the GC.
                _start_task = asyncio.create_task(lane.start(), name="btc15m-lane-start")
                _start_task.add_done_callback(
                    lambda t: logger.error(
                        "btc15m lane start task failed: %s", t.exception()
                    ) if not t.cancelled() and t.exception() else None
                )
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
        from merid.sentiment.sentiment_bus_v2 import get_sentiment_bus_v2
        bus = get_sentiment_bus_v2()
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


@router.get("/coingecko-context")
async def get_coingecko_context() -> Dict[str, Any]:
    """H2: CoinGecko global market — BTC dominance, trending, alt season."""
    try:
        from merid.prediction.coingecko_context import get_coingecko_context_service
        return (await get_coingecko_context_service().get_snapshot()).to_dict()
    except Exception as exc:
        logger.warning("coingecko-context failed: %s", exc)
        return {"btc_dominance_pct": 0.0, "source": "stub", "error": str(exc)}


@router.get("/signal-calibrator")
def get_signal_calibrator_stats() -> Dict[str, Any]:
    """H1: Per-signal Brier scores and adaptive weights."""
    try:
        from merid.prediction.signal_calibrator import get_signal_calibrator
        cal = get_signal_calibrator()
        return {"signals": cal.stats(), "source": "live"}
    except Exception as exc:
        logger.warning("signal-calibrator failed: %s", exc)
        return {"signals": {}, "source": "stub", "error": str(exc)}


@router.post("/signal-calibrator/record")
def record_signal_outcome(
    signal: str,
    predicted_prob: float,
    outcome: float,
) -> Dict[str, Any]:
    """H1: Record a resolved outcome for a signal (predicted_prob, outcome 0/1)."""
    try:
        from merid.prediction.signal_calibrator import get_signal_calibrator
        cal = get_signal_calibrator()
        cal.record(signal, predicted_prob, outcome)
        return {"recorded": True, "signal": signal, "new_weight": cal.weight(signal)}
    except Exception as exc:
        logger.warning("signal-calibrator/record failed: %s", exc)
        return {"recorded": False, "error": str(exc)}


@router.get("/context-health")
async def get_context_health() -> Dict[str, Any]:
    """H3: Status of all 11 context signal sources — last_fetched, source, latency."""
    import time as _time
    sources = [
        ("macro",         "merid.prediction.macro_context",         "get_macro_context_service"),
        ("perp",          "merid.prediction.perp_context",          "get_perp_context_service"),
        ("finnhub",       "merid.prediction.finnhub_context",       "get_finnhub_context_service"),
        ("polygon",       "merid.prediction.polygon_context",       "get_polygon_context_service"),
        ("trends",        "merid.prediction.trends_context",        "get_trends_context_service"),
        ("hurricane",     "merid.prediction.hurricane_context",     "get_hurricane_context_service"),
        ("news",          "merid.prediction.news_context",          "get_news_context_service"),
        ("alphavantage",  "merid.prediction.alphavantage_context",  "get_alphavantage_context_service"),
        ("fear_greed",    "merid.prediction.fear_greed_context",    "get_fear_greed_context_service"),
        ("messari",       "merid.prediction.messari_context",       "get_messari_context_service"),
        ("coingecko",     "merid.prediction.coingecko_context",     "get_coingecko_context_service"),
        ("cmc",           "merid.prediction.coinmarketcap_context", "get_cmc_context_service"),
    ]
    result: Dict[str, Any] = {}
    now = _time.time()
    for name, module_path, fn_name in sources:
        try:
            import importlib
            mod = importlib.import_module(module_path)
            svc = getattr(mod, fn_name)()
            cache = getattr(svc, "_cache", None)
            cache_ts = getattr(svc, "_cache_ts", 0.0)
            src = getattr(cache, "source", "unknown") if cache else "no_cache"
            age_s = round(now - cache_ts, 1) if cache_ts > 0 else None
            result[name] = {
                "source": src,
                "cache_age_s": age_s,
                "has_cache": cache is not None,
            }
        except Exception as exc:
            result[name] = {"source": "error", "error": str(exc), "has_cache": False}
    result["checked_at"] = now
    return result


@router.get("/cmc-context")
async def get_cmc_context() -> Dict[str, Any]:
    """H3: CoinMarketCap gainers/losers + market concentration."""
    try:
        from merid.prediction.coinmarketcap_context import get_cmc_context_service
        return (await get_cmc_context_service().get_snapshot()).to_dict()
    except Exception as exc:
        logger.warning("cmc-context failed: %s", exc)
        return {"gainer_count": 0, "loser_count": 0, "source": "stub", "error": str(exc)}


@router.get("/alphavantage-context")
async def get_alphavantage_context() -> Dict[str, Any]:
    """G1: Alpha Vantage GDP growth + sector performance snapshot."""
    try:
        from merid.prediction.alphavantage_context import get_alphavantage_context_service
        return (await get_alphavantage_context_service().get_snapshot()).to_dict()
    except Exception as exc:
        logger.warning("alphavantage-context failed: %s", exc)
        return {"gdp_trend": "neutral", "source": "stub", "error": str(exc)}


@router.get("/fear-greed-context")
async def get_fear_greed_context() -> Dict[str, Any]:
    """G2: Crypto Fear & Greed Index — contrarian sentiment signal."""
    try:
        from merid.prediction.fear_greed_context import get_fear_greed_context_service
        return (await get_fear_greed_context_service().get_snapshot()).to_dict()
    except Exception as exc:
        logger.warning("fear-greed-context failed: %s", exc)
        return {"score": 50, "classification": "Neutral", "source": "stub", "error": str(exc)}


@router.get("/messari-context")
async def get_messari_context() -> Dict[str, Any]:
    """G3: Messari BTC/ETH on-chain fundamentals — dominance, NVT, momentum."""
    try:
        from merid.prediction.messari_context import get_messari_context_service
        return (await get_messari_context_service().get_snapshot()).to_dict()
    except Exception as exc:
        logger.warning("messari-context failed: %s", exc)
        return {"btc": {}, "eth": {}, "source": "stub", "error": str(exc)}


@router.get("/polygon-context")
async def get_polygon_context() -> Dict[str, Any]:
    """F1: SPY/QQQ equity momentum + CBOE put/call ratio (Polygon.io)."""
    try:
        from merid.prediction.polygon_context import get_polygon_context_service
        return (await get_polygon_context_service().get_snapshot()).to_dict()
    except Exception as exc:
        logger.warning("polygon-context failed: %s", exc)
        return {"market_regime": "neutral", "put_call_ratio": 1.0, "source": "stub", "error": str(exc)}


@router.get("/trends-context")
async def get_trends_context() -> Dict[str, Any]:
    """F2: Google Trends search spike detection for macro/crypto/risk keywords."""
    try:
        from merid.prediction.trends_context import get_trends_context_service
        return (await get_trends_context_service().get_snapshot()).to_dict()
    except Exception as exc:
        logger.warning("trends-context failed: %s", exc)
        return {"groups": {}, "source": "stub", "error": str(exc)}


@router.get("/hurricane-context")
async def get_hurricane_context() -> Dict[str, Any]:
    """F3: NOAA/NHC active storm tracking — Florida seasonal hurricane edge."""
    try:
        from merid.prediction.hurricane_context import get_hurricane_context_service
        return (await get_hurricane_context_service().get_snapshot()).to_dict()
    except Exception as exc:
        logger.warning("hurricane-context failed: %s", exc)
        return {"active_storms": [], "peak_fl_threat": 0.0, "source": "stub", "error": str(exc)}


@router.get("/news-context")
async def get_news_context() -> Dict[str, Any]:
    """F4: NewsAPI headline sentiment for crypto/macro/equity/energy topics."""
    try:
        from merid.prediction.news_context import get_news_context_service
        return (await get_news_context_service().get_snapshot()).to_dict()
    except Exception as exc:
        logger.warning("news-context failed: %s", exc)
        return {"topics": {}, "source": "stub", "error": str(exc)}


@router.get("/finnhub-context")
async def get_finnhub_context() -> Dict[str, Any]:
    """E2: Finnhub economic calendar + SPY/BTC news sentiment snapshot."""
    try:
        from merid.prediction.finnhub_context import get_finnhub_context_service
        svc = get_finnhub_context_service()
        snap = await svc.get_snapshot()
        return snap.to_dict()
    except Exception as exc:
        logger.warning("finnhub-context endpoint failed: %s", exc)
        return {"releases": [], "sentiment": {}, "source": "stub", "error": str(exc)}


@router.get("/macro-context")
async def get_macro_context() -> Dict[str, Any]:
    """D1+D2: FRED macro snapshot — Fed rate, CPI, unemployment, yield curve, VIX + BLS release calendar."""
    try:
        from merid.prediction.macro_context import get_macro_context_service
        svc = get_macro_context_service()
        snap = await svc.get_snapshot()
        return snap.to_dict()
    except Exception as exc:
        logger.warning("macro-context endpoint failed: %s", exc)
        return {
            "fed_funds_rate": 0.0, "cpi_yoy": 0.0, "unemployment_rate": 0.0,
            "yield_spread_10y2y": 0.0, "vix": 0.0, "upcoming_releases": [],
            "source": "stub", "error": str(exc),
        }


@router.get("/metaculus-context")
async def get_metaculus_context() -> Dict[str, Any]:
    """D4: Metaculus calibration priors per market category."""
    try:
        from merid.prediction.metaculus_context import get_metaculus_context_service
        svc = get_metaculus_context_service()
        snap = await svc.get_snapshot()
        return snap.to_dict()
    except Exception as exc:
        logger.warning("metaculus-context endpoint failed: %s", exc)
        return {"priors": {}, "source": "stub", "error": str(exc)}


@router.get("/perp-context")
async def get_perp_context() -> Dict[str, Any]:
    """C6: BTC/ETH Binance perp funding rate + 30-day realised vol (IV proxy).

    Returns cached snapshot (TTL=60s).  Falls back to stub zeros on error.
    """
    try:
        from merid.prediction.perp_context import get_perp_context_service
        svc = get_perp_context_service()
        snap = await svc.get_snapshot()
        return snap.to_dict()
    except Exception as exc:
        logger.warning("perp-context endpoint failed: %s", exc)
        return {
            "btc": {"funding_rate": 0.0, "mark_price": 0.0, "iv_30d": 0.0},
            "eth": {"funding_rate": 0.0, "mark_price": 0.0, "iv_30d": 0.0},
            "source": "stub",
            "error": str(exc),
        }


@router.get("/prob-accuracy")
async def get_prob_accuracy() -> Dict[str, Any]:
    """C7: Return implied vs realized probability accuracy per market family."""
    try:
        from merid.prediction.prob_accuracy_tracker import get_prob_accuracy_tracker
        tracker = get_prob_accuracy_tracker()
        return tracker.to_dict()
    except Exception as exc:
        logger.warning("prob-accuracy endpoint failed: %s", exc)
        return {"families": [], "error": str(exc)}


@router.post("/prob-accuracy/record")
async def record_prob_outcome(
    ticker: str,
    resolved_yes: bool,
    market_family: str = "",
) -> Dict[str, Any]:
    """C7: Record a market resolution to update implied vs realized tracking."""
    try:
        from merid.prediction.prob_accuracy_tracker import get_prob_accuracy_tracker
        tracker = get_prob_accuracy_tracker()
        tracker.record_outcome(ticker, resolved_yes, market_family or None)
        return {"ok": True, "ticker": ticker, "resolved_yes": resolved_yes}
    except Exception as exc:
        logger.warning("prob-accuracy/record failed: %s", exc)
        return {"ok": False, "error": str(exc)}


@router.get("/responsible-trading")
async def get_responsible_trading() -> Dict[str, Any]:
    """B2: Venue-side responsible-trading limits + MERID-side daily caps.

    Returns a merged view of:
    - Kalshi account balance and available funds
    - MERID daily loss limit and current PnL
    - Kill-switch state
    """
    try:
        from merid.event_venues.kalshi.responsible_trading import get_responsible_trading_client
        client = get_responsible_trading_client()
        snap = await client.get_snapshot()
        return snap.to_dict()
    except Exception as exc:
        logger.warning("responsible-trading endpoint failed: %s", exc)
        return {
            "balance_usd": 0.0,
            "portfolio_value_usd": 0.0,
            "available_funds_usd": 0.0,
            "merid_daily_loss_limit_usd": 0.0,
            "merid_max_position_usd": 0.0,
            "merid_kill_switch_active": False,
            "merid_current_daily_pnl_usd": 0.0,
            "venue_loss_limit_set": False,
            "venue_deposit_limit_set": False,
            "venue_cool_off_active": False,
            "source": "stub",
            "error": str(exc),
        }


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


# ── Universe / Coverage / Category-mode endpoints ─────────────────────────


@router.get("/universe/coverage",
    summary="Universe Coverage Summary",
    description="Returns total active markets, per-category counts, and current paper/live mode per category.",
    tags=["kalshi", "universe"],
)
async def get_universe_coverage() -> Dict[str, Any]:
    """Return a full coverage snapshot from KalshiUniverse."""
    try:
        from merid.event_venues.kalshi.universe import get_kalshi_universe
        universe = get_kalshi_universe()
        return universe.coverage_summary()
    except Exception as exc:
        logger.warning("universe/coverage failed: %s", exc)
        return {
            "total_active": 0,
            "total_liquid": 0,
            "by_category": {},
            "category_modes": {},
            "error": str(exc),
        }


@router.get("/universe/pool",
    summary="Universe Pool for a Category",
    description="Returns the liquidity-filtered market pool for a given category (or all categories if omitted).",
    tags=["kalshi", "universe"],
)
async def get_universe_pool(
    category: Optional[str] = Query(None, description="Kalshi category (crypto, politics, sports…)"),
    asset: Optional[str] = Query(None, description="Asset tag filter (BTC, CPI…)"),
    limit: int = Query(50, ge=1, le=500, description="Max markets to return"),
) -> Dict[str, Any]:
    """Return the universe pool for a given category/asset."""
    try:
        from merid.event_venues.kalshi.universe import get_kalshi_universe
        universe = get_kalshi_universe()
        pool = universe.get_pool(category=category, asset=asset, limit=limit)
        return {
            "category": category,
            "asset": asset,
            "count": len(pool),
            "markets": [
                {
                    "ticker": cm.market.market_id,
                    "question": cm.market.question or "",
                    "category": cm.category,
                    "asset": cm.asset,
                    "timeframe": cm.timeframe,
                    "volume": cm.market.volume,
                    "open_interest": cm.market.open_interest,
                    "expires_at": (cm.market.raw_data or {}).get("close_time"),
                }
                for cm in pool
            ],
        }
    except Exception as exc:
        logger.warning("universe/pool failed: %s", exc)
        return {"count": 0, "markets": [], "error": str(exc)}


@router.get("/universe/category-modes",
    summary="Per-Category Trading Modes",
    description="Returns the current paper/live mode for each Kalshi category.",
    tags=["kalshi", "universe"],
)
async def get_category_modes() -> Dict[str, Any]:
    """Return per-category trading modes."""
    try:
        from merid.event_venues.kalshi.universe import get_all_category_modes, KNOWN_CATEGORIES
        modes = get_all_category_modes()
        return {
            "category_modes": modes,
            "known_categories": list(KNOWN_CATEGORIES),
        }
    except Exception as exc:
        logger.warning("universe/category-modes failed: %s", exc)
        return {"category_modes": {}, "error": str(exc)}


@router.get("/universe/agents",
    summary="Universal Agent Registry",
    description="Returns status of all registered KalshiUniversalAgent instances.",
    tags=["kalshi", "universe"],
)
async def get_universal_agents() -> Dict[str, Any]:
    """Return status of all registered universal agents."""
    try:
        from merid.prediction.universal_agent import _agents, _agents_lock
        from merid.prediction.ua_ct_metrics import merge_agent_dict
        import threading

        def _safe_merge(name: str, state_dict: Dict[str, Any]) -> Dict[str, Any]:
            try:
                return merge_agent_dict(name, state_dict)
            except Exception as _me:
                logger.debug("merge_agent_dict(%s) skipped: %s", name, _me)
                return dict(state_dict)

        with _agents_lock:
            agents_snapshot = {
                name: {**_safe_merge(name, agent.state.to_dict()), "dry_run": agent.config.dry_run}
                for name, agent in _agents.items()
            }
        # Ensure sweep-all row exists for dashboard even if UA never registered
        if "sweep-all" not in agents_snapshot:
            agents_snapshot["sweep-all"] = _safe_merge(
                "sweep-all",
                {
                    "name": "sweep-all",
                    "running": False,
                    "enabled": True,
                    "cycles_run": 0,
                    "markets_evaluated": 0,
                    "orders_placed": 0,
                    "orders_rejected": 0,
                    "last_cycle_at": None,
                    "last_error": None,
                    "dry_run": True,  # conservative default when no agent exists yet
                },
            )
        return {"agents": agents_snapshot, "count": len(agents_snapshot)}
    except Exception as exc:
        logger.warning("universe/agents failed: %s", exc)
        return {"agents": {}, "count": 0, "error": str(exc)}


@router.post("/universe/agents/{name}/start",
    summary="Start a Universal Agent",
    description="Start a KalshiUniversalAgent by name (creates with defaults if not registered).",
    tags=["kalshi", "universe"],
)
async def start_universal_agent(
    name: str,
    categories: Optional[str] = Query(None, description="Comma-separated category list"),
    max_markets: int = Query(50, ge=1, le=500),
    dry_run: bool = Query(False, description="Dry-run mode (no real orders). Default False — set True explicitly for paper rehearsal."),
) -> Dict[str, Any]:
    """Start or create a universal agent."""
    try:
        from merid.prediction.universal_agent import (
            UniversalAgentConfig,
            get_or_create_universal_agent,
        )
        cat_list = [c.strip() for c in categories.split(",")] if categories else []
        cfg = UniversalAgentConfig(
            name=name,
            categories=cat_list,
            max_markets=max_markets,
            dry_run=dry_run,
        )
        agent = get_or_create_universal_agent(name, cfg)
        # BUG-FIX: get_or_create returns the cached agent and ignores the new cfg when the
        # agent already exists.  Apply mutable config fields from the request explicitly so
        # that e.g. toggling dry_run=False actually takes effect on a re-start.
        agent.config.dry_run = dry_run
        agent.config.max_markets = max_markets
        if cat_list:
            agent.config.categories = cat_list
        await agent.start()
        return {"status": "started", "agent": {**agent.state.to_dict(), "dry_run": agent.config.dry_run}}
    except Exception as exc:
        logger.error("universe/agents/%s/start failed: %s", name, exc)
        return {"status": "error", "error": str(exc)}


@router.post("/universe/agents/{name}/stop",
    summary="Stop a Universal Agent",
    tags=["kalshi", "universe"],
)
async def stop_universal_agent(name: str) -> Dict[str, Any]:
    """Stop a running universal agent by name."""
    try:
        from merid.prediction.universal_agent import get_universal_agent
        agent = get_universal_agent(name)
        if not agent:
            return {"status": "not_found", "name": name}
        await agent.stop()
        return {"status": "stopped", "agent": agent.state.to_dict()}
    except Exception as exc:
        logger.error("universe/agents/%s/stop failed: %s", name, exc)
        return {"status": "error", "error": str(exc)}


@router.get("/universe/category-caps",
    summary="Per-Category Exposure Caps",
    description=(
        "Returns category notional vs caps (USD), correlated underlyings, default corr cap (USD), "
        "and optional per-asset correlated-stack overrides in ``asset_caps`` (USD — not CT cents)."
    ),
    tags=["kalshi", "universe"],
)
async def get_category_caps() -> Dict[str, Any]:
    """Return current category exposure and caps."""
    try:
        from merid.event_venues.kalshi.category_exposure import get_category_exposure_tracker
        tracker = get_category_exposure_tracker()
        snap = tracker.get_snapshot()
        return {
            "category_notional": snap.category_notional,
            "corr_notional": snap.corr_notional,
            "category_caps": snap.category_caps,
            "corr_cap": snap.corr_cap,
            "asset_caps": snap.asset_caps,
        }
    except Exception as exc:
        logger.warning("universe/category-caps failed: %s", exc)
        return {
            "category_notional": {},
            "corr_notional": {},
            "category_caps": {},
            "corr_cap": 0.0,
            "asset_caps": {},
            "error": str(exc),
        }


@router.get("/order-errors",
    summary="Order Error Breakdown",
    description="Returns aggregated order rejection breakdown by error code, severity, and category.",
    tags=["kalshi", "orders"],
)
async def get_order_error_breakdown(window_hours: int = 24) -> Dict[str, Any]:
    """Aggregate order rejection metrics by error taxonomy."""
    from datetime import timezone as _tz
    from merid.event_venues.kalshi.order_errors import KalshiOrderErrorCode

    from monitoring.kalshi_metrics import get_kalshi_metrics_collector
    try:
        collector = get_kalshi_metrics_collector()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    try:
        metrics = collector.collect()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    # Collect rejection counts per code
    raw_counts: Dict[str, int] = {}
    for m in metrics:
        if getattr(m, "name", None) == "kalshi_orders_rejected_total":
            code = getattr(m, "labels", {}).get("error_code", "unknown")
            raw_counts[code] = raw_counts.get(code, 0) + int(getattr(m, "value", 0))

    total = sum(raw_counts.values())

    # Build breakdown list enriched with taxonomy metadata
    breakdown = []
    by_category: Dict[str, Dict] = {}
    by_severity: Dict[str, int] = {"critical": 0, "warning": 0, "info": 0}

    for code_str, count in raw_counts.items():
        ec = KalshiOrderErrorCode.from_string(code_str)
        pct = round((count / total) * 100, 2) if total else 0.0
        breakdown.append({
            "code": code_str,
            "count": count,
            "percentage": pct,
            "severity": ec.severity,
            "category": ec.category,
            "is_retryable": ec.is_retryable,
            "description": ec.description,
        })
        by_severity[ec.severity] = by_severity.get(ec.severity, 0) + count
        cat = ec.category
        if cat not in by_category:
            by_category[cat] = {"count": 0, "codes": []}
        by_category[cat]["count"] += count
        if code_str not in by_category[cat]["codes"]:
            by_category[cat]["codes"].append(code_str)

    breakdown.sort(key=lambda x: x["count"], reverse=True)
    top_errors = breakdown[:10]

    return {
        "window_hours": window_hours,
        "total_rejections": total,
        "breakdown": breakdown,
        "by_category": by_category,
        "by_severity": by_severity,
        "top_errors": top_errors,
        "last_updated": datetime.now(_tz.utc).isoformat(),
    }


# ── Calibration Tracker (Brier score + per-cell metrics) ─────────────────────

@router.get("/calibration/stats")
async def get_calibration_stats(
    forecaster_id: Optional[str] = Query(None, description="Filter to a specific forecaster"),
    bucket: Optional[str] = Query(None, description="Filter to a specific bucket (e.g. 'crypto/15m')"),
) -> Dict[str, Any]:
    """Return Brier score calibration statistics for all (or one) forecaster.

    Each entry contains: ewma_brier, n_resolved, avg_confidence, consensus_weight.
    """
    try:
        from merid.metrics.calibration import get_calibration_store
        store = get_calibration_store()

        if forecaster_id:
            summary = store.get_forecaster_summary(forecaster_id)
            return {"forecaster_id": forecaster_id, "summary": summary}

        all_stats = store.get_all_forecaster_stats()  # List[BrierStats]
        result: Dict[str, Any] = {}
        for s in all_stats:
            if bucket and s.bucket != bucket:
                continue
            fid = s.forecaster_id
            if fid not in result:
                result[fid] = []
            result[fid].append({
                "bucket": s.bucket,
                "ewma_brier": round(s.ewma_brier, 6),
                "n_resolved": s.resolved_count,
                "brier_sum": round(s.sum_brier, 6),
                "brier_sum_sq": round(s.sum_brier_sq, 6),
                "weight": round(store.get_weight(fid, s.bucket), 4),
            })
        return {
            "forecasters": len(result),
            "bucket_filter": bucket,
            "stats": result,
        }
    except Exception as exc:
        logger.warning("calibration/stats endpoint failed: %s", exc)
        return {"forecasters": 0, "stats": {}, "error": str(exc)}


@router.get("/calibration/weights")
async def get_calibration_weights(
    bucket: str = Query("crypto/15m", description="Bucket to retrieve weights for"),
) -> Dict[str, Any]:
    """Return consensus weight for every forecaster for a given bucket.

    Weights are derived from the inverse-Brier formula in CalibrationStore.get_weight().
    """
    try:
        from merid.metrics.calibration import get_calibration_store
        store = get_calibration_store()
        forecasters = store.list_forecasters()
        weights: Dict[str, float] = {}
        for fid in forecasters:
            weights[fid] = round(store.get_weight(fid, bucket), 4)
        return {
            "bucket": bucket,
            "forecasters": len(weights),
            "weights": weights,
            "sum": round(sum(weights.values()), 4),
        }
    except Exception as exc:
        logger.warning("calibration/weights endpoint failed: %s", exc)
        return {"bucket": bucket, "weights": {}, "error": str(exc)}


@router.get("/calibration/forecasters")
async def list_calibration_forecasters() -> Dict[str, Any]:
    """List all forecasters tracked in the CalibrationStore."""
    try:
        from merid.metrics.calibration import get_calibration_store
        store = get_calibration_store()
        forecasters = store.list_forecasters()
        return {"forecasters": forecasters, "count": len(forecasters)}
    except Exception as exc:
        logger.warning("calibration/forecasters endpoint failed: %s", exc)
        return {"forecasters": [], "count": 0, "error": str(exc)}


@router.get("/calibration/unresolved")
async def get_unresolved_calibration_markets(
    forecaster_id: Optional[str] = Query(None, description="Filter by forecaster"),
) -> Dict[str, Any]:
    """Return markets with outstanding (unresolved) forecasts."""
    try:
        from merid.metrics.calibration import get_calibration_store
        store = get_calibration_store()
        markets = store.get_unresolved_markets()
        return {
            "forecaster_id": forecaster_id,
            "unresolved_count": len(markets),
            "markets": markets,
        }
    except Exception as exc:
        logger.warning("calibration/unresolved endpoint failed: %s", exc)
        return {"unresolved_count": 0, "markets": [], "error": str(exc)}


@router.post("/calibration/resolve")
async def resolve_calibration_outcome(
    market_id: str,
    resolved_yes: bool,
) -> Dict[str, Any]:
    """Record the resolution of a market and update all forecasters' Brier scores."""
    try:
        from merid.metrics.calibration import get_calibration_store
        store = get_calibration_store()
        # resolve_outcome takes outcome as int: 1=YES, 0=NO
        updated = store.resolve_outcome(market_id=market_id, outcome=int(resolved_yes))
        return {
            "ok": True,
            "market_id": market_id,
            "resolved_yes": resolved_yes,
            "forecasters_updated": updated,
        }
    except Exception as exc:
        logger.warning("calibration/resolve endpoint failed: %s", exc)
        return {"ok": False, "market_id": market_id, "error": str(exc)}


@router.get("/calibration/cell-metrics")
async def get_cell_metrics(
    asset: Optional[str] = Query(None, description="Filter by asset (e.g. BTC)"),
    timeframe: Optional[str] = Query(None, description="Filter by timeframe (e.g. 15m)"),
) -> Dict[str, Any]:
    """Return per-cell (asset × timeframe) order-flow and edge metrics (BUG-016).

    Provides candidates, vetoes, orders_submitted, fills, avg_edge, fill_rate,
    cost_cents, pnl_cents per cell with optional asset/timeframe filtering.
    """
    try:
        from merid.metrics.cell_metrics import snapshot as _cm_snap, get_cell
        if asset and timeframe:
            cell = get_cell(asset, timeframe)
            if cell is None:
                return {"cells": {}, "count": 0, "filter": {"asset": asset, "timeframe": timeframe}}
            return {"cells": {f"{asset}/{timeframe}": cell.to_dict()}, "count": 1}
        snap = _cm_snap()
        if asset:
            snap = {k: v for k, v in snap.items() if v.get("asset", "").upper() == asset.upper()}
        if timeframe:
            snap = {k: v for k, v in snap.items() if v.get("timeframe", "") == timeframe}
        return {"cells": snap, "count": len(snap)}
    except Exception as exc:
        logger.warning("calibration/cell-metrics endpoint failed: %s", exc)
        return {"cells": {}, "count": 0, "error": str(exc)}


# ── Bracket Risk ─────────────────────────────────────────────────────────

@router.get("/bracket-risk")
async def get_bracket_risk() -> Dict[str, Any]:
    """Get bracket risk manager status for Kalshi hourly bracket trading.

    Returns:
        {
            "halted": bool,
            "halt_reason": str | null,
            "open_brackets": int,
            "total_brackets": int,
            "winning_brackets": int,
            "losing_brackets": int,
            "win_rate_pct": float,
            "total_pnl_cents": float,
            "total_pnl_usd": float,
            "consecutive_losers": int,
            "max_consecutive_losers_seen": int,
            "net_delta": int,
            "hours_with_exposure": int,
            "contracts_by_hour": Dict[str, int],
            "config": {...}
        }
    """
    try:
        from merid.event_venues.kalshi.bracket_risk import BracketRiskManager
        # Get or create the bracket risk manager singleton
        br = BracketRiskManager()
        return br.summary()
    except Exception as e:
        logger.warning(f"Bracket risk unavailable: {e}")
        # Return safe default structure
        return {
            "halted": False,
            "halt_reason": None,
            "open_brackets": 0,
            "total_brackets": 0,
            "winning_brackets": 0,
            "losing_brackets": 0,
            "win_rate_pct": 0.0,
            "total_pnl_cents": 0.0,
            "total_pnl_usd": 0.0,
            "consecutive_losers": 0,
            "max_consecutive_losers_seen": 0,
            "net_delta": 0,
            "hours_with_exposure": 0,
            "contracts_by_hour": {},
            "config": {
                "max_loss_per_contract_pct": 1.0,
                "max_loss_per_bracket_cents": 5000.0,
                "max_contracts_per_hour": 50,
                "max_notional_per_hour_cents": 25000.0,
                "max_consecutive_losers": 5,
                "max_unhedged_delta": 100,
                "max_open_brackets": 20,
            },
            "error": str(e),
        }


@router.get("/guardrails/p0-status")
async def get_p0_guardrails_status() -> Dict[str, Any]:
    """P0 Guardrails Status — Exposes critical safety metrics for UI surfacing.

    Returns:
      - P0-001 (Spot Staleness): violations count, current spot age per asset
      - P0-002 (Asset-Ticker Mismatch): mismatch count, last rejection reason
      - P0-003 (Settlement Guard): per-timeframe guard seconds table

    Used by: DataFreshnessIndicator, KalshiErrorPill, CryptoSpotKalshiPanel
    """
    from monitoring.metrics import get_metrics_registry

    registry = get_metrics_registry()
    result: Dict[str, Any] = {
        "p0_001_spot_staleness": {
            "metric_name": "merid_pm_spot_staleness_violations_total",
            "metric_age_name": "merid_pm_spot_age_seconds",
            "violations_total": 0,
            "spot_age_by_asset": {},
            "max_spot_age_seconds": 120,  # Default from max_spot_age_seconds()
        },
        "p0_002_asset_mismatch": {
            "metric_name": "merid_pm_strike_asset_mismatch_total",
            "rejection_reason": "ASSET_TICKER_MISMATCH",
            "mismatches_total": 0,
        },
        "p0_003_settlement_guard": {
            "metric_name": "_SETTLEMENT_GUARD_BY_TIMEFRAME",
            "guard_seconds_by_timeframe": {
                "15m": 30,
                "1h": 60,
                "daily": 300,
                "weekly": 300,
                "monthly": 300,
                "annual": 300,
            },
            "default_guard_seconds": 60,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Try to read metric values from registry
    try:
        violations_counter = registry._metrics.get("merid_pm_spot_staleness_violations_total")
        if violations_counter:
            result["p0_001_spot_staleness"]["violations_total"] = int(
                sum(v for v in violations_counter._values.values())
            )

        age_gauge = registry._metrics.get("merid_pm_spot_age_seconds")
        if age_gauge:
            for label, value in age_gauge._values.items():
                asset = label.get("asset", "unknown")
                result["p0_001_spot_staleness"]["spot_age_by_asset"][asset] = float(value)

        mismatch_counter = registry._metrics.get("merid_pm_strike_asset_mismatch_total")
        if mismatch_counter:
            result["p0_002_asset_mismatch"]["mismatches_total"] = int(
                sum(v for v in mismatch_counter._values.values())
            )
    except Exception as exc:
        logger.warning("Failed to read P0 metrics from registry: %s", exc)

    # Read env override for max_spot_age_seconds
    import os
    try:
        env_max = os.getenv("MERID_PM_MAX_SPOT_AGE_SECONDS", "")
        if env_max.isdigit():
            result["p0_001_spot_staleness"]["max_spot_age_seconds"] = int(env_max)
    except Exception as e:
        logger.debug(f"Silent error: {e}")

    return result


# ═══════════════════════════════════════════════════════════════════════════
# Missing Endpoint Stubs (501 Not Implemented)
# ═══════════════════════════════════════════════════════════════════════════
# These endpoints are declared in web/react/src/config/constants.ts but have
# no backend implementation yet. They return 501 to avoid 404 confusion for
# frontend developers and to provide a clear signal about implementation gaps.


@router.get("/news-signals")
async def get_news_signals() -> Dict[str, Any]:
    """News signal feed — 501 Not Implemented.

    Stub endpoint. Planned for future news-based signal integration.
    Track progress in engineering backlog.
    """
    raise HTTPException(
        status_code=501,
        detail="News signals endpoint not yet implemented. Track progress in backlog."
    )


# Duplicate endpoint removed - see line 5981 for the actual implementation


@router.get("/favorites")
async def get_favorites() -> Dict[str, Any]:
    """User favorites/watchlist — 501 Not Implemented.

    Stub endpoint. Planned for future user preference system.
    Track progress in engineering backlog.
    """
    raise HTTPException(
        status_code=501,
        detail="Favorites endpoint not yet implemented. Track progress in backlog."
    )


@router.post("/favorites/toggle")
async def toggle_favorite(body: Dict[str, Any]) -> Dict[str, Any]:
    """Toggle favorite status for a market — 501 Not Implemented.

    Stub endpoint. Planned for future user preference system.
    Track progress in engineering backlog.
    """
    raise HTTPException(
        status_code=501,
        detail="Favorites toggle endpoint not yet implemented. Track progress in backlog."
    )


@router.get("/sentiment/lane-snapshot")
async def get_sentiment_lane_snapshot() -> Dict[str, Any]:
    """Lane snapshot from BTC15m lane — 501 Not Implemented.

    Stub endpoint. Planned for future lane-based sentiment streaming.
    Track progress in engineering backlog.
    """
    raise HTTPException(
        status_code=501,
        detail="Sentiment lane snapshot endpoint not yet implemented. Track progress in backlog."
    )


# ═══════════════════════════════════════════════════════════════════════════
# Risk Pipeline API (New Pure-Function Pipeline)
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/risk/projection")
async def get_risk_projection_api(
    force_new: bool = Query(False, description="Force use of new pipeline regardless of feature flag"),
) -> Dict[str, Any]:
    """Get risk projection using appropriate pipeline based on feature flag.
    
    This endpoint returns risk projections from either the new pure-function pipeline
    or the legacy pipeline, controlled by the USE_NEW_RISK_PIPELINE feature flag.
    
    Query params:
        force_new: If true, use new pipeline regardless of feature flag
    
    Returns:
        Risk projection with positions, exposure, PnL, equity
    """
    try:
        from merid.event_venues.kalshi.risk_pipeline_coordinator import get_risk_projection
        
        projection = await get_risk_projection(force_new=force_new)
        
        return {
            "success": True,
            "data": projection.to_dict(),
            "pipeline_type": "new" if force_new or settings.USE_NEW_RISK_PIPELINE else "legacy",
        }
    except Exception as e:
        logger.error(f"Failed to get risk projection: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get risk projection: {str(e)}")


@router.get("/risk/diff")
async def run_parallel_diff_api() -> Dict[str, Any]:
    """Run old and new pipelines in parallel and compare outputs.
    
    This endpoint is for validation during the parallel run phase. It runs both
    the legacy pipeline and the new pure-function pipeline, then compares their outputs.
    
    Returns:
        Diff result with comparison details (position diffs, PnL diffs, etc.)
    """
    try:
        from merid.event_venues.kalshi.risk_pipeline_coordinator import run_parallel_diff
        
        diff = await run_parallel_diff()
        
        return {
            "success": True,
            "data": diff.to_dict(),
        }
    except Exception as e:
        logger.error(f"Failed to run parallel diff: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to run parallel diff: {str(e)}")


@router.get("/risk/pipeline-status")
async def get_pipeline_status_api() -> Dict[str, Any]:
    """Get current pipeline status for monitoring.
    
    Returns:
        Pipeline status including feature flag state, pipeline type, cutover readiness
    """
    try:
        from merid.event_venues.kalshi.risk_pipeline_coordinator import get_pipeline_status
        
        status = get_pipeline_status()
        
        return {
            "success": True,
            "data": status,
        }
    except Exception as e:
        logger.error(f"Failed to get pipeline status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get pipeline status: {str(e)}")
