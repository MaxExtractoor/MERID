"""Typed Kalshi tools — registered into the guardrails ToolRegistry.

Each tool wraps the existing KalshiVenueClient / KalshiTrader and returns
a structured ToolResult.  Agents call these through the GuardedToolRouter
which enforces budgets, capabilities, and policies.

Tools:
  kalshi_list_crypto_markets  — Discovery: filter by timeframe + asset
  kalshi_get_market_state     — Single market snapshot
  kalshi_place_order          — Execute: YES/NO order with price + size
  kalshi_cancel_order         — Cancel an open order
  kalshi_get_positions        — Account: current positions (optionally per-asset)
  kalshi_get_balance          — Account: available + locked balance
"""

from __future__ import annotations

import os
import time
from decimal import Decimal
from typing import Any, Dict, List, Optional

import threading

from merid.guardrails.tools import (
    ToolDefinition,
    ToolErrorCode,
    ToolResult,
    ToolValidity,
    get_tool_registry,
)
from merid.prediction.session_guard import get_session_guard
from merid.prediction.venue_gate import get_venue_gate
from utils.logger import get_logger

logger = get_logger("merid.prediction.kalshi_tools")

# ── Lazy client accessor ───────────────────────────────────────────────

_client = None
_trader = None
_trader_lock = threading.Lock()  # FPA-02: protect singleton init


def _get_client():
    """Lazy-init the KalshiVenueClient singleton."""
    from merid.event_venues.kalshi import get_kalshi_client
    return get_kalshi_client()


def _get_trader():
    """Lazy-init the KalshiTrader singleton."""
    global _trader
    if _trader is None:
        with _trader_lock:
            if _trader is None:  # double-checked locking
                from merid.event_venues.kalshi.trading import KalshiTrader
                _trader = KalshiTrader(_get_client())
    return _trader


# ── Tool handlers ──────────────────────────────────────────────────────

async def _kalshi_list_markets(
    category: str = "all",
    timeframe: str = "",
    asset: str = "",
    limit: int = 50,
) -> ToolResult:
    """List Kalshi markets filtered by category, timeframe and asset."""
    t0 = time.time()

    # Session guard
    guard = get_session_guard()
    if not guard.is_trading_allowed():
        return ToolResult.fail(
            ToolErrorCode.VENUE_DOWN,
            guard.block_reason() or "Kalshi maintenance",
            tool_name="kalshi_list_markets",
        )

    try:
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        catalog = get_market_catalog()
        
        # If catalog is empty or stale, trigger a refresh (non-blocking if already running)
        if not catalog.get_all_markets():
            await catalog.refresh()

        if category == "all":
            markets = catalog.get_all_markets()
            if timeframe:
                markets = [m for m in markets if m.timeframe == timeframe]
            if asset:
                markets = [m for m in markets if m.asset == asset]
        else:
            markets = catalog.get_markets_by_category(category, timeframe=timeframe, asset=asset)
        
        # Limit the results
        markets = markets[:limit]

        payload = {
            "markets": [
                {
                    "ticker": m.market.market_id,
                    "question": m.market.question,
                    "category": m.category,
                    "tags": m.market.tags,
                    "end_date": m.market.end_date.isoformat() if m.market.end_date else None,
                    "volume": str(m.market.volume) if m.market.volume else "0",
                    "open_interest": str(m.market.open_interest) if m.market.open_interest else "0",
                    "active": m.market.active,
                    "outcomes": [
                        {
                            "id": o.outcome_id,
                            "name": o.outcome_name,
                            "price": str(o.price),
                            "probability": str(o.probability) if o.probability else None,
                        }
                        for o in m.market.outcomes
                    ],
                }
                for m in markets
            ],
            "count": len(markets),
            "filters": {"category": category, "timeframe": timeframe, "asset": asset},
        }

        gate = get_venue_gate()
        validity = ToolValidity.SIMULATED if gate.should_simulate_fill() else ToolValidity.FRESH

        return ToolResult(
            success=True,
            payload=payload,
            source="kalshi",
            validity=validity,
            tool_name="kalshi_list_markets",
            latency_ms=round((time.time() - t0) * 1000, 2),
        )

    except Exception as exc:
        logger.error(f"kalshi_list_markets failed: {exc}")
        return ToolResult.fail(
            ToolErrorCode.INTERNAL, str(exc),
            tool_name="kalshi_list_markets",
        )


async def _kalshi_get_market_state(ticker: str = "") -> ToolResult:
    """Get detailed state for a single Kalshi market."""
    t0 = time.time()
    if not ticker:
        return ToolResult.fail(
            ToolErrorCode.INVALID_INPUT, "ticker is required",
            tool_name="kalshi_get_market_state",
        )

    try:
        client = _get_client()

        # Fast-path: skip API call if circuit breaker is open
        if client.is_circuit_open:
            return ToolResult.fail(
                ToolErrorCode.VENUE_DOWN,
                "Kalshi circuit breaker is open — skipping get_market_state",
                tool_name="kalshi_get_market_state",
            )

        result = await client.get_market_result(ticker)

        if not result.success:
            error_code = ToolErrorCode.VENUE_DOWN if result.circuit_open else ToolErrorCode.INTERNAL
            return ToolResult.fail(
                error_code,
                f"Kalshi API error: {result.error}",
                tool_name="kalshi_get_market_state",
            )

        market = result.data
        if not market:
            return ToolResult.fail(
                ToolErrorCode.NOT_FOUND, f"Market {ticker} returned empty",
                tool_name="kalshi_get_market_state",
            )

        # Also fetch orderbook
        ob = await client.get_orderbook(ticker)

        payload = {
            "ticker": market.market_id,
            "question": market.question,
            "category": market.category,
            "tags": market.tags,
            "end_date": market.end_date.isoformat() if market.end_date else None,
            "active": market.active,
            "volume": str(market.volume) if market.volume else "0",
            "liquidity": str(market.liquidity) if market.liquidity else "0",
            "outcomes": [
                {
                    "id": o.outcome_id,
                    "name": o.outcome_name,
                    "price": str(o.price),
                    "probability": str(o.probability) if o.probability else None,
                }
                for o in market.outcomes
            ],
            "orderbook": {
                "bids": [(str(p), str(s)) for p, s in ob.bids] if ob else [],
                "asks": [(str(p), str(s)) for p, s in ob.asks] if ob else [],
            },
        }

        return ToolResult(
            success=True,
            payload=payload,
            source="kalshi",
            validity=ToolValidity.FRESH,
            tool_name="kalshi_get_market_state",
            latency_ms=round((time.time() - t0) * 1000, 2),
        )

    except Exception as exc:
        logger.error(f"kalshi_get_market_state failed: {exc}")
        return ToolResult.fail(
            ToolErrorCode.INTERNAL, str(exc),
            tool_name="kalshi_get_market_state",
        )


async def _kalshi_place_order(
    ticker: str = "",
    side: str = "yes",
    action: str = "buy",
    price_cents: int = 0,
    count: int = 1,
    agent_name: str = "",
) -> ToolResult:
    """Place a YES/NO order on Kalshi."""
    t0 = time.time()

    if not ticker:
        return ToolResult.fail(
            ToolErrorCode.INVALID_INPUT, "ticker is required",
            tool_name="kalshi_place_order",
        )

    # Venue gate check
    gate = get_venue_gate()
    try:
        gate.check_order("kalshi")
    except (gate.VenueBlockedError, gate.ModeBlockedError) as exc:
        return ToolResult.fail(
            ToolErrorCode.POLICY_BLOCKED, str(exc),
            tool_name="kalshi_place_order",
        )

    # Per-agent deployment mode check (PAPER/SHADOW/LIVE/HALTED)
    _agent_name = agent_name
    _agent_mode = None
    if _agent_name:
        try:
            from merid.event_venues.kalshi.deployment import get_deployment_controller, AgentMode
            _dc = get_deployment_controller()
            _agent_mode = _dc.get_mode(_agent_name)
            if _agent_mode == AgentMode.HALTED:
                return ToolResult.fail(
                    ToolErrorCode.POLICY_BLOCKED,
                    f"Agent {_agent_name} is HALTED — no orders allowed",
                    tool_name="kalshi_place_order",
                )
        except Exception as _dce:
            logger.debug("deployment_controller check skipped: %s", _dce)

    # Unified execution gate — block live orders when safety checks fail
    if not gate.should_simulate_fill():
        try:
            from core.execution_gate import check_execution_gate, live_execution_blocked
            exec_gate = check_execution_gate()
            if live_execution_blocked(exec_gate):
                reasons = "; ".join(r.message for r in exec_gate.reasons)
                return ToolResult.fail(
                    ToolErrorCode.POLICY_BLOCKED,
                    f"Execution gate blocked: {reasons}",
                    tool_name="kalshi_place_order",
                )
        except ImportError:
            pass  # execution gate module not available — fall through

    # Session guard
    session = get_session_guard()
    if not session.is_trading_allowed():
        return ToolResult.fail(
            ToolErrorCode.VENUE_DOWN,
            session.block_reason() or "Kalshi maintenance",
            tool_name="kalshi_place_order",
        )

    # Simulate only when VenueGate says so. DeploymentController PAPER must not
    # override a LIVE VenueGate — otherwise every AgentGrid agent (registered PAPER
    # in the deployment ledger) would never reach Kalshi despite PM live mode.
    _force_paper_deploy = (
        _agent_mode is not None
        and _agent_mode.value == "PAPER"
        and gate.should_simulate_fill()
    )
    if gate.should_simulate_fill() or _force_paper_deploy:
        # Realistic fill simulation using orderbook
        try:
            client = _get_client()
            ob = await client.get_orderbook(ticker)
            
            fillable = False
            reason = "No liquidity at price"
            
            if ob:
                # If buying YES, we need YES asks
                # Kalshi orderbook: bids are buys, asks are sells
                # buy yes -> check yes_ask
                # sell yes -> check yes_bid
                if action == "buy":
                    # For simplicity, check if price_cents >= best ask
                    best_ask = int(ob.asks[0][0] * 100) if ob.asks else None
                    if best_ask is not None and (price_cents == 0 or price_cents >= best_ask):
                        fillable = True
                else:
                    best_bid = int(ob.bids[0][0] * 100) if ob.bids else None
                    if best_bid is not None and (price_cents == 0 or price_cents <= best_bid):
                        fillable = True
            
            # If no orderbook data, fallback to immediate fill at price (legacy behavior)
            else:
                fillable = True
                reason = "No orderbook data, assumed fill"

            if fillable:
                payload = {
                    "order_id": f"sim_{ticker}_{int(time.time()*1000)}",
                    "ticker": ticker,
                    "side": side,
                    "action": action,
                    "price_cents": price_cents,
                    "count": count,
                    "status": "simulated",
                    "simulated": True,
                    "fill_reason": reason if not ob else "orderbook_match",
                }
                return ToolResult(
                    success=True,
                    payload=payload,
                    source="kalshi_sim",
                    validity=ToolValidity.SIMULATED,
                    tool_name="kalshi_place_order",
                    latency_ms=round((time.time() - t0) * 1000, 2),
                )
            else:
                return ToolResult.fail(
                    ToolErrorCode.INTERNAL,
                    f"Paper fill failed: {reason}",
                    tool_name="kalshi_place_order",
                )
        except Exception as e:
            logger.warning(f"Paper fill simulation error — orderbook unavailable, rejecting fill: {e}")
            # Do NOT silently fill when the orderbook is unavailable: that would
            # overstate paper performance under exactly the adverse-venue conditions
            # where real orders would also fail.
            return ToolResult.fail(
                ToolErrorCode.VENUE_DOWN,
                f"Paper fill rejected: orderbook unavailable ({e})",
                tool_name="kalshi_place_order",
            )

    # SHADOW mode: place real order AND record a parallel paper fill
    _is_shadow = (_agent_mode is not None and _agent_mode.value == "SHADOW")

    # FINAL SAFETY NET: Block real orders if KALSHI_USE_DEMO is True
    # This catches any case where mode gating above was bypassed
    try:
        _demo_flag = os.getenv("KALSHI_USE_DEMO", "true").lower()
        if _demo_flag in ("1", "true", "yes", "on"):
            logger.warning("kalshi_place_order: KALSHI_USE_DEMO=true — blocking real order, simulating instead")
            payload = {
                "order_id": f"demo_blocked_{ticker}_{int(time.time() * 1000)}",
                "ticker": ticker, "side": side, "action": action,
                "price_cents": price_cents, "count": count,
                "status": "simulated", "simulated": True,
                "source": "demo_safety_net",
            }
            return ToolResult(
                success=True, payload=payload, source="kalshi_demo_block",
                validity=ToolValidity.SIMULATED, tool_name="kalshi_place_order",
                latency_ms=round((time.time() - t0) * 1000, 2),
            )
    except Exception:
        pass  # If env check fails, proceed with normal flow

    try:
        from merid.event_venues.base import VenueOrder
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk

        # ── Fills integrity check ────────────────────────────────────────────
        # This is a safety net: even when called directly from tools, we verify
        # data integrity before submitting live orders.
        risk_mgr = get_kalshi_risk()
        fills_ok, fills_reason = risk_mgr._check_fills_integrity()
        if not fills_ok:
            return ToolResult.fail(
                ToolErrorCode.POLICY_BLOCKED,
                f"Fills integrity check failed: {fills_reason}",
                tool_name="kalshi_place_order",
            )

        # Route through canonical order router (ensures fills ledger, risk checks, lineage)
        try:
            from merid.event_venues.kalshi.decision_trace import new_decision_trace_id
            from merid.event_venues.kalshi.order_router import route_order_async, OrderIntent
            from merid.prediction.venue_gate import TradingMode

            _pc = max(1, min(99, int(price_cents or 50)))
            _mode = TradingMode.PAPER if _is_shadow else TradingMode.LIVE
            intent = OrderIntent(
                ticker=ticker,
                side=side,
                action=action,
                price_cents=_pc,
                count=max(1, int(count)),
                mode=_mode,
                order_type="limit" if price_cents else "market",
                time_in_force="gtc",
                source="kalshi_tools",
                decision_trace_id=new_decision_trace_id("tool"),
                sentiment_driven=False,
                agent_id=_agent_name if _agent_name else None,
            )

            result = await route_order_async(intent)

            if result.status in ("rejected",):
                return ToolResult.fail(
                    ToolErrorCode.INTERNAL,
                    f"Order rejected: {result.reason or ''}",
                    tool_name="kalshi_place_order",
                )

            placed = result.fill or {}
            payload = {
                "order_id": placed.get("order_id") or placed.get("fill_id") or "",
                "ticker": ticker,
                "side": side,
                "action": action,
                "price_cents": price_cents or _pc,
                "count": count,
                "status": result.status,
                "simulated": False,
                "shadow": _is_shadow,
            }
            
        except ImportError as _imp:
            # FAIL-CLOSED: order_router is required for idempotency safety.
            # Direct client calls bypass: deterministic client_order_id, pre-trade gate,
            # jittered backoff, duplicate error handling, and sanity checking.
            logger.error("order_router unavailable — rejecting order for safety: %s", _imp)
            return ToolResult.fail(
                ToolErrorCode.INTERNAL,
                "Order router unavailable — order rejected for idempotency safety",
                tool_name="kalshi_place_order",
            )

        # L4: Shadow mode — record parallel paper fill and increment counters
        if _is_shadow and _agent_name:
            try:
                from merid.event_venues.kalshi.deployment import get_deployment_controller
                get_deployment_controller().record_shadow_trade(_agent_name)
                from merid.prediction.paper_session import get_paper_session
                _ps = get_paper_session()
                if _ps.is_active:
                    _ps.record_fill(
                        agent_name=_agent_name,
                        pnl_cents=0.0,  # PnL unknown at fill time; updated on settlement
                        fees_cents=0.0,
                        won=None,
                    )
            except Exception as _she:
                logger.warning("shadow parallel paper record failed: %s", _she)
        elif _agent_name:
            try:
                from merid.event_venues.kalshi.deployment import get_deployment_controller
                get_deployment_controller().record_live_trade(_agent_name)
            except Exception as _lte:
                logger.warning("live trade record failed: %s", _lte)

        return ToolResult(
            success=True,
            payload=payload,
            source="kalshi",
            validity=ToolValidity.FRESH,
            tool_name="kalshi_place_order",
            latency_ms=round((time.time() - t0) * 1000, 2),
        )

    except Exception as exc:
        logger.error(f"kalshi_place_order failed: {exc}")
        return ToolResult.fail(
            ToolErrorCode.INTERNAL, str(exc),
            tool_name="kalshi_place_order",
        )


async def _kalshi_place_paper_order(
    ticker: str = "",
    side: str = "yes",
    action: str = "buy",
    price_cents: int = 0,
    count: int = 1,
) -> ToolResult:
    """Force-paper order — always simulated, bypasses venue gate.

    Called by trading_agent._execute_signal when the BTC 15m risk layer
    returns TradeMode.PAPER regardless of the global venue gate setting.
    """
    t0 = time.time()
    if not ticker:
        return ToolResult.fail(
            ToolErrorCode.INVALID_INPUT, "ticker is required",
            tool_name="kalshi_place_paper_order",
        )
    payload = {
        "order_id": f"paper_{ticker}_{int(time.time() * 1000)}",
        "ticker": ticker,
        "side": side,
        "action": action,
        "price_cents": price_cents,
        "count": count,
        "status": "simulated",
        "simulated": True,
        "source": "force_paper",
    }
    return ToolResult(
        success=True,
        payload=payload,
        source="kalshi_paper",
        validity=ToolValidity.SIMULATED,
        tool_name="kalshi_place_paper_order",
        latency_ms=round((time.time() - t0) * 1000, 2),
    )


async def _kalshi_cancel_order(order_id: str = "", agent_name: str = "") -> ToolResult:
    """Cancel an open Kalshi order."""
    t0 = time.time()
    if not order_id:
        return ToolResult.fail(
            ToolErrorCode.INVALID_INPUT, "order_id is required",
            tool_name="kalshi_cancel_order",
        )

    # Simulated orders — always succeed without hitting the real API
    if order_id.startswith("sim_"):
        return ToolResult(
            success=True,
            payload={"order_id": order_id, "cancelled": True, "simulated": True},
            source="kalshi_sim",
            validity=ToolValidity.SIMULATED,
            tool_name="kalshi_cancel_order",
            latency_ms=round((time.time() - t0) * 1000, 2),
        )

    # G7: VenueGate — block real cancel in SIM/PAPER/MOCK mode
    _gate = get_venue_gate()
    if _gate.should_simulate_fill():
        return ToolResult(
            success=True,
            payload={"order_id": order_id, "cancelled": True, "simulated": True},
            source="kalshi_sim",
            validity=ToolValidity.SIMULATED,
            tool_name="kalshi_cancel_order",
            latency_ms=round((time.time() - t0) * 1000, 2),
        )

    # G7: DeploymentController — block cancel for HALTED/PAPER agents
    if agent_name:
        try:
            from merid.event_venues.kalshi.deployment import get_deployment_controller, AgentMode
            _mode = get_deployment_controller().get_mode(agent_name)
            if _mode in (AgentMode.HALTED, AgentMode.PAPER):
                return ToolResult(
                    success=True,
                    payload={"order_id": order_id, "cancelled": True, "simulated": True},
                    source="kalshi_sim",
                    validity=ToolValidity.SIMULATED,
                    tool_name="kalshi_cancel_order",
                    latency_ms=round((time.time() - t0) * 1000, 2),
                )
        except Exception as _dce:
            logger.debug("cancel deployment check skipped: %s", _dce)

    try:
        client = _get_client()
        result = await client.cancel_order_result(order_id)

        return ToolResult(
            success=result.success,
            payload={"order_id": order_id, "cancelled": result.success, "simulated": False},
            source="kalshi",
            validity=ToolValidity.FRESH,
            tool_name="kalshi_cancel_order",
            latency_ms=round((time.time() - t0) * 1000, 2),
            error_code=ToolErrorCode.OK if result.success else ToolErrorCode.INTERNAL,
            error_message="" if result.success else str(result.error),
        )

    except Exception as exc:
        logger.error(f"kalshi_cancel_order failed: {exc}")
        return ToolResult.fail(
            ToolErrorCode.INTERNAL, str(exc),
            tool_name="kalshi_cancel_order",
        )


async def _kalshi_get_positions(asset: str = "") -> ToolResult:
    """Get current Kalshi positions, optionally filtered by asset."""
    t0 = time.time()
    try:
        client = _get_client()

        # Fast-path: skip API call if circuit breaker is open
        if client.is_circuit_open:
            return ToolResult.fail(
                ToolErrorCode.VENUE_DOWN,
                "Kalshi circuit breaker is open — skipping get_positions",
                tool_name="kalshi_get_positions",
            )

        result = await client.get_positions_result()

        if not result.success:
            return ToolResult.fail(
                ToolErrorCode.INTERNAL,
                f"Failed to fetch positions: {result.error}",
                tool_name="kalshi_get_positions",
            )

        positions = result.data or []

        # Filter by asset if provided
        if asset:
            asset_upper = asset.upper()
            positions = [
                p for p in positions
                if asset_upper in p.market_id.upper()
            ]

        payload = {
            "positions": [
                {
                    "ticker": p.market_id,
                    "outcome": p.outcome_id,
                    "size": str(p.size),
                    "avg_entry_price": str(p.average_entry_price),
                    "unrealized_pnl": str(p.unrealized_pnl) if p.unrealized_pnl else "0",
                    "realized_pnl": str(p.realized_pnl) if p.realized_pnl else "0",
                }
                for p in positions
            ],
            "count": len(positions),
            "filter_asset": asset,
        }

        return ToolResult(
            success=True,
            payload=payload,
            source="kalshi",
            validity=ToolValidity.FRESH,
            tool_name="kalshi_get_positions",
            latency_ms=round((time.time() - t0) * 1000, 2),
        )

    except Exception as exc:
        logger.warning(f"kalshi_get_positions failed: {exc}")
        return ToolResult.fail(
            ToolErrorCode.INTERNAL, str(exc),
            tool_name="kalshi_get_positions",
        )


async def _kalshi_get_balance() -> ToolResult:
    """Get Kalshi account balance."""
    t0 = time.time()
    try:
        client = _get_client()

        # Fast-path: skip API call if circuit breaker is open
        if client.is_circuit_open:
            return ToolResult.fail(
                ToolErrorCode.VENUE_DOWN,
                "Kalshi circuit breaker is open — skipping get_balance",
                tool_name="kalshi_get_balance",
            )

        result = await client.get_balance_result()

        if not result.success:
            return ToolResult.fail(
                ToolErrorCode.INTERNAL,
                f"Failed to fetch balance: {result.error}",
                tool_name="kalshi_get_balance",
            )

        balance = result.data or {}
        payload = {
            "available_usd": str(balance.get("USD", 0)),
            "locked_usd": str(balance.get("locked", 0)),
        }

        return ToolResult(
            success=True,
            payload=payload,
            source="kalshi",
            validity=ToolValidity.FRESH,
            tool_name="kalshi_get_balance",
            latency_ms=round((time.time() - t0) * 1000, 2),
        )

    except Exception as exc:
        logger.error(f"kalshi_get_balance failed: {exc}")
        return ToolResult.fail(
            ToolErrorCode.INTERNAL, str(exc),
            tool_name="kalshi_get_balance",
        )


def build_live_route_order_intent(
    ticker: str,
    side: str,
    action: str,
    price_cents: int,
    count: int,
    *,
    correlation_id: Optional[str] = None,
    source: str = "kalshi_tools",
):
    """Build a canonical ``OrderIntent`` for live-route / ``VenueOrder`` mapping tests."""
    from merid.event_venues.kalshi.order_router import OrderIntent

    is_market = int(price_cents) == 0
    if is_market:
        pc = 0
        otype = "market"
    else:
        pc = max(1, min(99, int(price_cents)))
        otype = "limit"

    intent = OrderIntent(
        ticker=ticker,
        side=side,
        action=action,
        price_cents=pc,
        count=max(1, int(count)),
        mode=None,
        order_type=otype,
        source=source,
    )
    if correlation_id:
        intent.client_tag = correlation_id
        intent.decision_trace_id = correlation_id
    return intent


# ── Registration ───────────────────────────────────────────────────────

def register_kalshi_tools() -> None:
    """Register all Kalshi tools into the global ToolRegistry."""
    registry = get_tool_registry()

    registry.register(ToolDefinition(
        name="kalshi_list_markets",
        description="List Kalshi prediction markets filtered by category, timeframe and asset",
        input_schema={"category": "str", "timeframe": "str", "asset": "str", "limit": "int"},
        output_schema={"markets": "list", "count": "int", "filters": "dict"},
        risk_level="low",
        idempotent=True,
        max_calls_per_minute=30,
        scopes=["research", "paper", "live"],
        handler=_kalshi_list_markets,
    ))

    registry.register(ToolDefinition(
        name="kalshi_get_market_state",
        description="Get detailed state for a single Kalshi market including orderbook",
        input_schema={"ticker": "str"},
        output_schema={"ticker": "str", "question": "str", "outcomes": "list", "orderbook": "dict"},
        risk_level="low",
        idempotent=True,
        max_calls_per_minute=60,
        scopes=["research", "paper", "live"],
        handler=_kalshi_get_market_state,
    ))

    registry.register(ToolDefinition(
        name="kalshi_place_order",
        description="Place a YES/NO order on a Kalshi market",
        input_schema={"ticker": "str", "side": "str", "action": "str", "price_cents": "int", "count": "int"},
        output_schema={"order_id": "str", "status": "str", "simulated": "bool"},
        risk_level="high",
        idempotent=False,
        max_calls_per_minute=20,
        scopes=["paper", "live"],
        handler=_kalshi_place_order,
    ))

    registry.register(ToolDefinition(
        name="kalshi_cancel_order",
        description="Cancel an open Kalshi order",
        input_schema={"order_id": "str"},
        output_schema={"order_id": "str", "cancelled": "bool"},
        risk_level="medium",
        idempotent=True,
        max_calls_per_minute=30,
        scopes=["paper", "live"],
        handler=_kalshi_cancel_order,
    ))

    registry.register(ToolDefinition(
        name="kalshi_get_positions",
        description="Get current Kalshi positions, optionally filtered by asset",
        input_schema={"asset": "str"},
        output_schema={"positions": "list", "count": "int"},
        risk_level="low",
        idempotent=True,
        max_calls_per_minute=30,
        scopes=["research", "paper", "live"],
        handler=_kalshi_get_positions,
    ))

    registry.register(ToolDefinition(
        name="kalshi_get_balance",
        description="Get Kalshi account balance (available + locked)",
        input_schema={},
        output_schema={"available_usd": "str", "locked_usd": "str"},
        risk_level="low",
        idempotent=True,
        max_calls_per_minute=30,
        scopes=["research", "paper", "live"],
        handler=_kalshi_get_balance,
    ))

    logger.info("Registered 6 Kalshi tools into ToolRegistry")
