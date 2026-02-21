"""
Dashboard API Endpoints
Provides real-time data for the React dashboard — wired to live sources.
"""
from fastapi import APIRouter, HTTPException
from typing import Dict, Any, List, Optional
from datetime import datetime
import time

from utils.logger import get_logger

logger = get_logger("api.dashboard")

router = APIRouter(prefix="/api", tags=["Dashboard"])


def _format_volume(vol: float) -> str:
    """Format volume as human-readable string."""
    if not vol or vol == 0:
        return "N/A"
    if vol >= 1_000_000_000:
        return f"{vol / 1_000_000_000:.1f}B"
    if vol >= 1_000_000:
        return f"{vol / 1_000_000:.1f}M"
    if vol >= 1_000:
        return f"{vol / 1_000:.1f}K"
    return f"{vol:.0f}"


def _get_paper_stats() -> Dict[str, Any]:
    """Pull real stats from the paper trading engine."""
    from trading.paper_trading import get_paper_engine
    engine = get_paper_engine()
    # Use first portfolio or default
    user_id = next(iter(engine.portfolios), "default")
    return engine.get_portfolio_stats(user_id)


def _normalize_label(value: Any, default: str) -> str:
    """Normalize enum/string values into uppercase labels."""
    if value is None:
        return default

    raw_value = value
    if hasattr(raw_value, "value"):
        raw_value = raw_value.value
    elif hasattr(raw_value, "name"):
        raw_value = raw_value.name

    text = str(raw_value).strip()
    return text.upper() if text else default


@router.get("/portfolio/summary")
async def get_portfolio_summary() -> Dict[str, Any]:
    """
    Get portfolio summary from the live paper trading engine.
    """
    try:
        stats = _get_paper_stats()
        equity = stats.get("equity", stats.get("current_balance", 10000))
        starting = stats.get("starting_balance", 10000)
        total_pnl = stats.get("total_pnl", 0)
        unrealized = stats.get("total_unrealized_pnl", 0)
        daily_pnl = total_pnl + unrealized
        daily_pnl_pct = (daily_pnl / starting * 100) if starting else 0
        return {
            "equity": round(equity, 2),
            "dailyPnl": round(daily_pnl, 2),
            "dailyPnlPct": round(daily_pnl_pct, 2),
            "availableMargin": round(stats.get("current_balance", equity), 2),
            "activeBots": stats.get("open_positions", 0),
            "totalValue": round(equity, 2),
            "unrealizedPnl": round(unrealized, 2),
            "activePositions": stats.get("open_positions", 0),
            "totalTrades": stats.get("total_trades", 0),
            "winRate": round(stats.get("win_rate_pct", 0), 1),
            "roi": round(stats.get("roi_pct", 0), 2),
            "startingBalance": round(starting, 2),
        }
    except Exception as e:
        logger.error(f"Failed to get portfolio summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prices/live")
async def get_live_prices(symbols: str) -> Dict[str, Any]:
    """
    Get live prices for multiple symbols.
    Tries CCXT LivePriceFeed first, falls back to CoinGecko live_data cache.
    Query param: symbols (comma-separated, e.g., "BTC,ETH,SOL")
    """
    try:
        # --- Source 1: CCXT LivePriceFeed ---
        all_prices: Dict[str, Dict[str, Any]] = {}
        try:
            from data.live_price_feed import get_live_price_feed
            feed = get_live_price_feed()
            all_prices = feed.get_latest_prices()
        except Exception as exc:
            logger.debug(f"Live price feed error (ignored): {exc}")

        # --- Source 2: CoinGecko live_data cache (fallback) ---
        if not all_prices:
            try:
                from web.api.live_data import _price_cache as cg_cache, fetch_live_prices as _fetch_cg
                if not cg_cache:
                    await _fetch_cg()
                for sym, data in cg_cache.items():
                    short = sym.replace("/USDT", "").replace("/USD", "")
                    all_prices[short] = {
                        "price": data.get("price", 0),
                        "change_24h": data.get("change_24h", 0),
                        "volume_24h": data.get("volume_24h", 0),
                        "source": "coingecko",
                        "timestamp": data.get("timestamp"),
                    }
            except Exception as cg_err:
                logger.warning(f"CoinGecko fallback failed: {cg_err}")

        symbol_list = [s.strip().upper() for s in symbols.split(",")]
        prices = []

        for symbol in symbol_list:
            key = symbol
            if key not in all_prices:
                key = symbol.replace("-USD", "").replace("/USD", "")
            if key not in all_prices:
                for k in all_prices:
                    if k.upper().startswith(symbol.replace("-USD", "")):
                        key = k
                        break

            if key in all_prices:
                pd = all_prices[key]
                prices.append({
                    "symbol": symbol,
                    "price": round(pd["price"], 2),
                    "change": round(pd.get("change_24h", 0), 2),
                    "volume": _format_volume(pd.get("volume_24h", 0)),
                    "source": pd.get("source", "unknown"),
                    "timestamp": pd.get("timestamp"),
                })
            else:
                prices.append({
                    "symbol": symbol,
                    "price": 0,
                    "change": 0,
                    "volume": "N/A",
                    "source": "unavailable",
                })

        return {"prices": prices}
    except Exception as e:
        logger.error(f"Failed to get live prices: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orders/recent")
async def get_recent_orders(limit: int = 10) -> Dict[str, Any]:
    """
    Get recent trades from the paper trading engine.
    """
    try:
        from trading.paper_trading import get_paper_engine
        engine = get_paper_engine()
        user_id = next(iter(engine.portfolios), "default")
        portfolio = engine.get_portfolio(user_id)

        orders = []
        # trade_history stores filled PaperOrder objects
        for order in reversed(portfolio.trade_history[-limit:]):
            ts = getattr(order, "filled_at", None) or getattr(order, "created_at", time.time())
            time_str = datetime.fromtimestamp(ts).strftime("%H:%M:%S") if isinstance(ts, (int, float)) else str(ts)
            side = _normalize_label(getattr(order, "side", None), "BUY")
            asset = getattr(order, "asset", "?")
            size = getattr(order, "size_usd", getattr(order, "quantity", 0))
            price = getattr(order, "fill_price", getattr(order, "price", 0))
            status = _normalize_label(getattr(order, "status", None), "FILLED")
            orders.append({
                "time": time_str,
                "action": f"{side} {asset}",
                "size": f"{size}",
                "price": f"{price}",
                "status": status,
            })

        return {"orders": orders[:limit]}
    except Exception as e:
        logger.error(f"Failed to get recent orders: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agents/activity")
async def get_agent_activity() -> Dict[str, Any]:
    """
    Get real agent activity from the agent framework registry.
    """
    try:
        from agents.agent_framework import AgentStatus
        from agents.registry import get_registry
        registry = get_registry()
        all_agents = registry.get_all_agents()

        agents = []
        for agent in all_agents:
            m = agent.get_metrics()
            status_str = agent.status.value if hasattr(agent.status, "value") else str(agent.status)
            # Format uptime
            uptime_s = m.uptime_seconds if hasattr(m, "uptime_seconds") else 0
            if uptime_s > 3600:
                uptime_label = f"{int(uptime_s // 3600)}h ago"
            elif uptime_s > 60:
                uptime_label = f"{int(uptime_s // 60)}m ago"
            else:
                uptime_label = f"{int(uptime_s)}s ago"

            agents.append({
                "agent_id": agent.agent_id,
                "agent_name": getattr(agent, "name", agent.agent_id),
                "status": status_str,
                "last_action": getattr(m, "last_action", "") if hasattr(m, "last_action") else "",
                "last_action_time": uptime_label,
                "tasks_completed": getattr(m, "tasks_completed", 0) if hasattr(m, "tasks_completed") else 0,
                "current_task": getattr(agent, "current_task", None),
            })

        return {
            "agents": agents,
            "summary": {
                "total": len(agents),
                "active": sum(1 for a in agents if a["status"] in ("active", "running", "idle")),
                "idle": sum(1 for a in agents if a["status"] == "idle"),
                "error": sum(1 for a in agents if a["status"] in ("error", "failed")),
            },
        }
    except Exception as e:
        logger.error(f"Failed to get agent activity: {e}")
        raise HTTPException(status_code=500, detail=str(e))
