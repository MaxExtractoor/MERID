"""
Built-in typed tools that wrap MERID's existing subsystems.

Each tool returns a ToolResult with structured payloads and validity flags.
Tools are auto-registered into the ToolRegistry on import.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from merid.guardrails.tools import ToolResult, ToolValidity, ToolErrorCode, ToolDefinition, get_tool_registry
from utils.logger import get_logger

logger = get_logger("merid.guardrails.builtin_tools")


def _register_all() -> None:
    """Register all built-in tools into the global ToolRegistry."""
    registry = get_tool_registry()

    # ── Market Data Tools (read-only, low risk) ──────────────────────

    registry.register(ToolDefinition(
        name="get_order_book",
        description="Get order book snapshot for a symbol from the live price feed",
        input_schema={"symbol": "str"},
        output_schema={"symbol": "str", "best_bid": "float", "best_ask": "float",
                       "spread": "float", "ts": "float", "source": "str", "validity": "str"},
        risk_level="low",
        idempotent=True,
        max_calls_per_minute=120,
        scopes=["research", "paper", "live"],
        handler=_get_order_book,
    ))

    registry.register(ToolDefinition(
        name="get_ticker",
        description="Get latest ticker (price, change, volume) for a symbol",
        input_schema={"symbol": "str"},
        output_schema={"symbol": "str", "price": "float", "change_pct": "float",
                       "volume_24h": "float", "source": "str"},
        risk_level="low",
        idempotent=True,
        max_calls_per_minute=120,
        scopes=["research", "paper", "live"],
        handler=_get_ticker,
    ))

    registry.register(ToolDefinition(
        name="get_position_state",
        description="Get current position state from the paper trading engine",
        input_schema={"portfolio_id": "str"},
        output_schema={"positions": "list", "equity": "float", "pnl": "float"},
        risk_level="low",
        idempotent=True,
        max_calls_per_minute=60,
        scopes=["research", "paper", "live"],
        handler=_get_position_state,
    ))

    registry.register(ToolDefinition(
        name="get_portfolio_summary",
        description="Get portfolio summary from the paper trading engine",
        input_schema={"portfolio_id": "str"},
        output_schema={"equity": "float", "total_pnl": "float", "open_positions": "int"},
        risk_level="low",
        idempotent=True,
        max_calls_per_minute=60,
        scopes=["research", "paper", "live"],
        handler=_get_portfolio_summary,
    ))

    registry.register(ToolDefinition(
        name="get_config_flag",
        description="Read a runtime configuration flag",
        input_schema={"key": "str"},
        output_schema={"key": "str", "value": "any"},
        risk_level="low",
        idempotent=True,
        max_calls_per_minute=60,
        scopes=["research", "paper", "live"],
        handler=_get_config_flag,
    ))

    registry.register(ToolDefinition(
        name="get_risk_metrics",
        description="Get current risk metrics from the runtime config and paper engine",
        input_schema={},
        output_schema={"mode": "str", "spectator": "bool", "daily_pnl": "float"},
        risk_level="low",
        idempotent=True,
        max_calls_per_minute=30,
        scopes=["research", "paper", "live"],
        handler=_get_risk_metrics,
    ))

    registry.register(ToolDefinition(
        name="get_prediction_markets",
        description="Get prediction market summary from the aggregator",
        input_schema={"limit": "int"},
        output_schema={"markets": "list", "total": "int"},
        risk_level="low",
        idempotent=True,
        max_calls_per_minute=30,
        scopes=["research", "paper", "live"],
        handler=_get_prediction_markets,
    ))

    # ── Trading Tools (write, medium/high risk) ──────────────────────

    registry.register(ToolDefinition(
        name="place_order",
        description="Place a paper/live order through the execution router",
        input_schema={"symbol": "str", "side": "str", "quantity": "float",
                      "price": "float", "order_type": "str"},
        output_schema={"order_id": "str", "status": "str"},
        risk_level="high",
        idempotent=False,
        max_calls_per_minute=10,
        scopes=["paper", "live"],
        handler=_place_order,
    ))

    registry.register(ToolDefinition(
        name="cancel_order",
        description="Cancel an open order",
        input_schema={"order_id": "str"},
        output_schema={"order_id": "str", "cancelled": "bool"},
        risk_level="medium",
        idempotent=True,
        max_calls_per_minute=20,
        scopes=["paper", "live"],
        handler=_cancel_order,
    ))

    registry.register(ToolDefinition(
        name="get_open_orders",
        description="List open orders for a portfolio",
        input_schema={"portfolio_id": "str"},
        output_schema={"orders": "list", "count": "int"},
        risk_level="low",
        idempotent=True,
        max_calls_per_minute=30,
        scopes=["research", "paper", "live"],
        handler=_get_open_orders,
    ))

    # ── Control Tools (critical risk) ────────────────────────────────

    registry.register(ToolDefinition(
        name="trigger_halt",
        description="Trigger a trading halt / kill switch",
        input_schema={"reason": "str"},
        output_schema={"halted": "bool", "reason": "str"},
        risk_level="critical",
        idempotent=True,
        max_calls_per_minute=5,
        scopes=["paper", "live"],
        handler=_trigger_halt,
    ))

    logger.info("Registered %d built-in tools", len(registry.list_names()))


# ── Handler implementations ──────────────────────────────────────────

async def _get_order_book(symbol: str = "BTC/USD") -> ToolResult:
    """Get order book snapshot from live price feed."""
    try:
        from data.live_price_feed import get_live_price_feed
        feed = get_live_price_feed()
        prices = feed.get_all_prices()
        if symbol in prices:
            pd = prices[symbol]
            age = time.time() - pd.timestamp if hasattr(pd, 'timestamp') else 0
            validity = ToolValidity.FRESH if age < 30 else ToolValidity.STALE
            return ToolResult.ok({
                "symbol": symbol,
                "best_bid": pd.bid,
                "best_ask": pd.ask,
                "spread": round((pd.ask - pd.bid) / pd.bid * 10000, 2) if pd.bid > 0 else 0,
                "price": pd.price,
                "volume_24h": pd.volume_24h,
                "ts": pd.timestamp if hasattr(pd, 'timestamp') else time.time(),
                "source": pd.exchange if hasattr(pd, 'exchange') else "unknown",
                "age_seconds": round(age, 1),
            }, source=getattr(pd, 'exchange', 'ccxt'), validity=validity)
        # Check price_cache fallback
        cached = feed.price_cache.get(symbol)
        if cached:
            return ToolResult.ok({
                "symbol": symbol,
                "price": cached.get("price", 0),
                "source": cached.get("source", "cache"),
            }, source="cache", validity=ToolValidity.STALE)
        return ToolResult.fail(ToolErrorCode.NOT_FOUND, f"No data for {symbol}")
    except Exception as exc:
        return ToolResult.fail(ToolErrorCode.INTERNAL, str(exc))


async def _get_ticker(symbol: str = "BTC/USD") -> ToolResult:
    """Get latest ticker from live price feed."""
    try:
        from data.live_price_feed import get_live_price_feed
        feed = get_live_price_feed()
        cached = feed.price_cache.get(symbol)
        if cached:
            return ToolResult.ok({
                "symbol": symbol,
                "price": cached.get("price", 0),
                "change_pct": cached.get("change", 0),
                "volume_24h": cached.get("volume", 0),
                "source": cached.get("source", "unknown"),
                "ts": cached.get("timestamp", time.time()),
            }, source=cached.get("source", "ccxt"), validity=ToolValidity.FRESH)
        return ToolResult.fail(ToolErrorCode.NOT_FOUND, f"No ticker for {symbol}")
    except Exception as exc:
        return ToolResult.fail(ToolErrorCode.INTERNAL, str(exc))


async def _get_position_state(portfolio_id: str = "default") -> ToolResult:
    """Get position state from paper trading engine."""
    try:
        from trading.paper_trading import get_paper_engine
        engine = get_paper_engine()
        port = engine.get_portfolio_summary(portfolio_id)
        return ToolResult.ok({
            "portfolio_id": portfolio_id,
            "positions": port.get("positions", []),
            "equity": port.get("equity", 0),
            "total_pnl": port.get("total_pnl", 0),
            "open_positions": port.get("open_positions", 0),
        }, source="paper_engine", validity=ToolValidity.FRESH)
    except Exception as exc:
        return ToolResult.fail(ToolErrorCode.INTERNAL, str(exc))


async def _get_portfolio_summary(portfolio_id: str = "default") -> ToolResult:
    """Get portfolio summary from paper trading engine."""
    return await _get_position_state(portfolio_id)


async def _get_config_flag(key: str = "") -> ToolResult:
    """Read a runtime configuration flag."""
    try:
        from trading.config.runtime import get_trading_runtime_config
        cfg = get_trading_runtime_config()
        state = cfg.get_state()
        known = {
            "mode": state.mode.value,
            "spectator_mode": state.spectator_mode,
            "allow_live_trades": state.allow_live_trades,
        }
        if key in known:
            return ToolResult.ok({"key": key, "value": known[key]}, source="runtime_config")
        return ToolResult.ok({"key": key, "value": None, "known_keys": list(known.keys())},
                             source="runtime_config")
    except Exception as exc:
        return ToolResult.fail(ToolErrorCode.INTERNAL, str(exc))


async def _get_risk_metrics() -> ToolResult:
    """Get current risk metrics."""
    try:
        from trading.config.runtime import get_trading_runtime_config
        cfg = get_trading_runtime_config()
        state = cfg.get_state()
        return ToolResult.ok({
            "mode": state.mode.value,
            "spectator_mode": state.spectator_mode,
            "allow_live_trades": state.allow_live_trades,
        }, source="runtime_config")
    except Exception as exc:
        return ToolResult.fail(ToolErrorCode.INTERNAL, str(exc))


async def _get_prediction_markets(limit: int = 20) -> ToolResult:
    """Get prediction market summary."""
    try:
        from monitoring.prediction_markets import get_prediction_aggregator
        agg = get_prediction_aggregator()
        markets = agg.get_all_markets()
        items = []
        for m in markets[:limit]:
            items.append({
                "market_id": m.market_id,
                "question": m.question,
                "yes_price": m.yes_price,
                "volume_24h": m.volume_24h,
                "platform": m.platform.value,
            })
        return ToolResult.ok({
            "markets": items,
            "total": len(markets),
            "returned": len(items),
        }, source="kalshi", validity=ToolValidity.FRESH)
    except Exception as exc:
        return ToolResult.fail(ToolErrorCode.INTERNAL, str(exc))


async def _place_order(
    symbol: str = "",
    side: str = "buy",
    quantity: float = 0,
    price: float = 0,
    order_type: str = "limit",
) -> ToolResult:
    """Place an order through the paper trading engine."""
    try:
        from trading.paper_trading import get_paper_engine
        engine = get_paper_engine()
        result = engine.place_order(
            portfolio_id="default",
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            order_type=order_type,
        )
        return ToolResult.ok({
            "order_id": result.get("order_id", ""),
            "status": result.get("status", "submitted"),
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": price,
        }, source="paper_engine")
    except Exception as exc:
        return ToolResult.fail(ToolErrorCode.INTERNAL, str(exc))


async def _cancel_order(order_id: str = "") -> ToolResult:
    """Cancel an open order."""
    try:
        from trading.paper_trading import get_paper_engine
        engine = get_paper_engine()
        result = engine.cancel_order("default", order_id)
        return ToolResult.ok({
            "order_id": order_id,
            "cancelled": result.get("cancelled", False),
        }, source="paper_engine")
    except Exception as exc:
        return ToolResult.fail(ToolErrorCode.INTERNAL, str(exc))


async def _get_open_orders(portfolio_id: str = "default") -> ToolResult:
    """List open orders."""
    try:
        from trading.paper_trading import get_paper_engine
        engine = get_paper_engine()
        orders = engine.get_open_orders(portfolio_id)
        return ToolResult.ok({
            "orders": orders if isinstance(orders, list) else [],
            "count": len(orders) if isinstance(orders, list) else 0,
        }, source="paper_engine")
    except Exception as exc:
        return ToolResult.fail(ToolErrorCode.INTERNAL, str(exc))


async def _trigger_halt(reason: str = "manual") -> ToolResult:
    """Trigger a trading halt."""
    try:
        from trading.config.runtime import get_trading_runtime_config
        cfg = get_trading_runtime_config()
        cfg.update_config(spectator_mode=True)
        logger.warning("Trading HALTED by guardrail tool: %s", reason)
        return ToolResult.ok({
            "halted": True,
            "reason": reason,
            "spectator_mode": True,
        }, source="runtime_config")
    except Exception as exc:
        return ToolResult.fail(ToolErrorCode.INTERNAL, str(exc))


# Auto-register on import
_register_all()
