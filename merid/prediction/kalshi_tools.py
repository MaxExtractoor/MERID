
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

import asyncio
import json
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
# LEGACY REMOVAL: session_guard moved to archive/legacy/ during 15m stack cleanup
from merid.prediction.venue_gate import get_venue_gate
from utils.logger import get_logger

logger = get_logger("merid.prediction.kalshi_tools")

# Trade trace integration for calibration
try:
    from merid.prediction.trade_trace import update_trace
    _TRACE_AVAILABLE = True
except ImportError:
    _TRACE_AVAILABLE = False
    logger.debug("[TRACE-INTEGRATION] Trade trace module not available, skipping trace updates")

# ── Lazy client accessor ───────────────────────────────────────────────

_client = None
_trader = None
_trader_lock = None


def _get_client():
    """Lazy-init the KalshiVenueClient singleton."""
    from merid.event_venues.kalshi import get_kalshi_client
    return get_kalshi_client()


def _get_trader():
    """Lazy-init the KalshiTrader singleton."""
    global _trader
    if _trader is None:
        if _trader_lock is not None:
            with _trader_lock:
                if _trader is None:  # double-checked locking
                    from merid.event_venues.kalshi.trading import KalshiTrader
                    _trader = KalshiTrader(_get_client())
        else:
            # Lock disabled - direct initialization (startup workaround)
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
    # LEGACY REMOVAL: session_guard moved to archive/legacy/ during 15m stack cleanup
    # guard = get_session_guard()
    # if not guard.is_trading_allowed():
    #     return ToolResult.fail(
    #         ToolErrorCode.VENUE_DOWN,
    #         guard.block_reason() or "Kalshi maintenance",
    #         tool_name="kalshi_list_markets",
    #     )

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
        
        # BUG-FIX (2026-05-06): Filter out markets that are not yet open or are in the future
        # The catalog may include scheduled markets that haven't opened yet on Kalshi's live API.
        # These markets will return 404 when submitting orders. Filter by:
        # 1. Market must be active (Kalshi status=open)
        # 2. Market must have a valid end_date in the future
        # 3. Market must have minutes_to_expiry > 0 (not already expired)
        # 4. For 15m crypto markets, exclude markets with end_date > 24 hours in the future
        #    (these are future scheduled markets not yet opened by Kalshi)
        # 5. For 15m crypto markets, exclude threshold contracts (e.g., KXDOGE-26MAY0623-T0.2949999)
        #    These are not 15-minute up/down contracts and will be rejected by order_router
        from datetime import datetime, timezone
        import re
        now = datetime.now(timezone.utc)
        filtered_markets = []
        for m in markets:
            # Must be active
            if not m.market.active:
                continue
            
            # Must have a valid end_date in the future
            if not m.market.end_date:
                continue
            if m.market.end_date <= now:
                continue
            
            # Must have positive minutes_to_expiry
            if m.minutes_to_expiry is None or m.minutes_to_expiry <= 0:
                continue
            
            # For 15m crypto markets, exclude markets > 24 hours in the future
            # These are scheduled markets that Kalshi hasn't opened yet
            if m.timeframe == "15m" and m.minutes_to_expiry > 24 * 60:
                continue
            
            # BUG-FIX (2026-05-06): For 15m crypto markets, exclude threshold contracts
            # Threshold contracts have ticker pattern like KXDOGE-26MAY0623-T0.2949999
            # These are not 15-minute up/down contracts and will be rejected by order_router
            if m.timeframe == "15m":
                ticker = m.market.market_id.upper()
                # Reject if ticker contains -T (threshold) pattern
                if "-T" in ticker and re.search(r"-T\d+(?:\.\d+)?$", ticker):
                    continue
            
            filtered_markets.append(m)
        
        markets = filtered_markets
        
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
    stop_loss_price_cents: Optional[int] = None,
    take_profit_r_multiple: Optional[float] = None,
) -> ToolResult:
    """Place a YES/NO order on Kalshi."""
    t0 = time.time()

    if not ticker:
        return ToolResult.fail(
            ToolErrorCode.INVALID_INPUT, "ticker is required",
            tool_name="kalshi_place_order",
        )

    # PRODUCTION DATA GUARDS (2026-05-14): Validate market_id against live catalog before order execution
    try:
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        from merid.settings import settings as _settings
        env = _settings.MERID_ENV if hasattr(_settings, 'MERID_ENV') else "development"
        pm_profile = _settings.MERID_PM_PROFILE if hasattr(_settings, 'MERID_PM_PROFILE') else "baseline"
        is_production = env == "production" or pm_profile == "production"
        
        if is_production:
            catalog = get_market_catalog()
            # Check if ticker exists in catalog
            catalog_markets = catalog.get_all_markets() if hasattr(catalog, 'get_all_markets') else []
            # CRITICAL FIX: CatalogMarket wraps EventMarket, so market_id is on nested market.market
            catalog_tickers = set()
            for m in catalog_markets:
                if hasattr(m, "market") and hasattr(m.market, "market_id"):
                    catalog_tickers.add(m.market.market_id)
                elif hasattr(m, "market_id"):
                    catalog_tickers.add(m.market_id)
            
            if ticker not in catalog_tickers:
                logger.error(
                    "[PRODUCTION_DATA_GUARD] ILLEGAL_MARKET_ID: ticker=%s not found in live catalog. "
                    "Order rejected - market does not exist in production catalog. "
                    "This prevents orders against fake/hardcoded/non-existent markets.",
                    ticker
                )
                return ToolResult.fail(
                    ToolErrorCode.INVALID_INPUT,
                    f"ILLEGAL_MARKET_ID: ticker {ticker} not found in live Kalshi catalog. "
                    "Orders only allowed for markets in production catalog.",
                    tool_name="kalshi_place_order",
                )
            logger.debug("[PRODUCTION_DATA_GUARD] Market ID validated: %s exists in live catalog", ticker)
    except Exception as e:
        # If catalog validation fails, log warning but don't block (may be dev/test mode)
        logger.warning("[PRODUCTION_DATA_GUARD] Could not validate market_id against catalog: %s", e)

    # PRODUCTION DATA GUARDS (2026-05-14): DRY_RUN mode - log but do not execute
    from merid.settings import settings as _settings
    dry_run = _settings.MERID_LOOP_DRY_RUN if hasattr(_settings, 'MERID_LOOP_DRY_RUN') else False
    
    if dry_run:
        # Extract asset from ticker for structured logging
        _asset = None
        try:
            from merid.event_venues.kalshi.market_catalog import get_market_catalog
            catalog = get_market_catalog()
            universe = catalog.get_market_universe()
            if universe is not None:
                for asset in universe.get_assets():
                    if asset in ticker.upper():
                        _asset = asset
                        break
        except Exception:
            pass
        
        logger.info(
            "WOULD_EXECUTE_ORDER: %s",
            json.dumps({
                "env": env,
                "dry_run": dry_run,
                "ticker": ticker,
                "asset": _asset,
                "side": side,
                "action": action,
                "price_cents": price_cents,
                "count": count,
                "agent_name": agent_name,
            })
        )
        # Return success without actually placing the order
        return ToolResult(
            success=True,
            payload={
                "dry_run": True,
                "would_execute": {
                    "ticker": ticker,
                    "side": side,
                    "action": action,
                    "price_cents": price_cents,
                    "count": count,
                    "agent_name": agent_name,
                },
                "message": "DRY_RUN mode - order logged but not executed"
            },
            source="kalshi_dry_run",
            validity=ToolValidity.FRESH,
            tool_name="kalshi_place_order",
            latency_ms=round((time.time() - t0) * 1000, 2),
        )
    
    # FAT-FINGER LIMIT: Reject orders exceeding max order size
    # This prevents accidental large orders that could cause significant losses
    try:
        from merid.settings import settings as _settings
        max_order_size_usd = getattr(_settings, 'MERID_MAX_ORDER_SIZE_USD', None)
        
        if max_order_size_usd is not None and max_order_size_usd > 0:
            # Calculate order notional: price_cents * count / 100
            order_notional_usd = (price_cents * count) / 100.0
            
            if order_notional_usd > max_order_size_usd:
                logger.error(
                    "[FAT-FINGER-GUARD] Order rejected: notional $%.2f exceeds max_order_size $%.2f. "
                    "ticker=%s price_cents=%d count=%d agent=%s",
                    order_notional_usd, max_order_size_usd, ticker, price_cents, count, agent_name
                )
                return ToolResult.fail(
                    ToolErrorCode.INVALID_INPUT,
                    f"Order notional ${order_notional_usd:.2f} exceeds maximum allowed ${max_order_size_usd:.2f}",
                    tool_name="kalshi_place_order",
                )
            logger.debug(
                "[FAT-FINGER-GUARD] Order notional $%.2f within max_order_size $%.2f",
                order_notional_usd, max_order_size_usd
            )
    except Exception as _ff_exc:
        logger.warning("[FAT-FINGER-GUARD] Failed to validate order size: %s", _ff_exc)

    # MARKET UNIVERSE GUARD: Reject orders for non-allowed markets
    # FIX: Use allowed_market_policy.is_market_allowed instead of universe.is_market_allowed
    # universe.is_market_allowed only checks if ticker is in the static universe.tickers set
    # which doesn't include new tickers until catalog refresh. The policy check uses
    # asset/series prefix matching which works for all tickers including new ones.
    _orders_rejected_disallowed_market = 0
    try:
        from merid.event_venues.kalshi.allowed_market_policy import is_market_allowed
        
        if not is_market_allowed(ticker):
            _orders_rejected_disallowed_market = 1
            logger.warning(
                "[MARKET-UNIVERSE-GUARD] Order rejected for disallowed market: ticker=%s agent=%s",
                ticker, agent_name
            )
            return ToolResult.fail(
                ToolErrorCode.POLICY_BLOCKED,
                f"Market {ticker} is not in the allowed universe (BTC/ETH/SOL/XRP/DOGE 15m only)",
                tool_name="kalshi_place_order",
            )
    except Exception as _universe_exc:
        logger.debug("[MARKET-UNIVERSE-GUARD] Failed to validate market: %s", _universe_exc)
    
    # Log metrics for successful orders (passed universe guard)
    if _orders_rejected_disallowed_market == 0:
        try:
            from merid.event_venues.kalshi.market_catalog import get_market_catalog
            catalog = get_market_catalog()
            universe = catalog.get_market_universe()
            if universe is not None:
                # Extract asset from ticker for metrics
                _asset = None
                for asset in universe.get_assets():
                    if asset in ticker.upper():
                        _asset = asset
                        break
                
                if _asset:
                    logger.info(
                        "[MARKET-UNIVERSE-METRICS] order_allowed ticker=%s asset=%s agent=%s",
                        ticker, _asset, agent_name
                    )
        except Exception as _metrics_exc:
            logger.debug("[MARKET-UNIVERSE-METRICS] Failed to log order metrics: %s", _metrics_exc)

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
    # LEGACY REMOVAL: session_guard moved to archive/legacy/ during 15m stack cleanup
    # session = get_session_guard()
    # if not session.is_trading_allowed():
    #     return ToolResult.fail(
    #         ToolErrorCode.VENUE_DOWN,
    #         session.block_reason() or "Kalshi maintenance",
    #         tool_name="kalshi_place_order",
    #     )

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

        # CRITICAL FIX: Direct routing to route_order_async for proper risk checks
        # SignalRouter has no subscribers in 15m production stack (no trading_agent)
        # Bypassing SignalRouter to ensure global rate limit and cooldown are enforced
        try:
            from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async

            # CRITICAL FIX: Clamp to 50-70 cents to prevent extreme purchases
            # This aligns with kalshi_crypto_15m_v2.yaml price_range [50, 70]
            # Optimized for scaling: mid-range prices have better liquidity depth for child orders
            # MID-SPREAD ENTRY OPTIMIZATION (2026-07-04): Respect calculated entry price from agent_grid
            # The agent_grid_15m.py now calculates optimal entry prices using mid-spread strategy
            # This clamp is a safety rail to ensure we never submit orders outside valid range
            original_price = int(price_cents or 50)
            _pc = max(50, min(70, original_price))
            
            # Log if price was clamped (indicates mid-spread optimization may need adjustment)
            if _pc != original_price:
                logger.warning(
                    "[KALSHI-TOOLS-PRICE-CLAMP] ticker=%s original_price=%d clamped_to=%d (safety rail 50-70c)",
                    ticker, original_price, _pc
                )
            else:
                logger.debug(
                    "[KALSHI-TOOLS-PRICE-OK] ticker=%s price=%d within range (mid-spread optimization respected)",
                    ticker, _pc
                )

            # Map side/action to Kalshi format
            side_lower = side.lower() if side else ""
            action_lower = action.lower() if action else ""
            kalshi_side = "BUY_YES" if side_lower == "yes" and action_lower == "buy" else \
                          "SELL_YES" if side_lower == "yes" and action_lower == "sell" else \
                          "BUY_NO" if side_lower == "no" and action_lower == "buy" else \
                          "SELL_NO" if side_lower == "no" and action_lower == "sell" else "BUY_YES"

            # CRITICAL FIX: Clamp count to asset-specific max_contracts limit to prevent overspending
            # Read from kalshi_crypto_15m_v2.yaml assets.{asset}.max_contracts (default 2)
            # Extract asset from ticker
            asset = None
            ticker_upper = ticker.upper()
            if "BTC" in ticker_upper:
                asset = "BTC"
            elif "ETH" in ticker_upper:
                asset = "ETH"
            elif "SOL" in ticker_upper:
                asset = "SOL"
            elif "XRP" in ticker_upper:
                asset = "XRP"
            elif "DOGE" in ticker_upper:
                asset = "DOGE"
            
            max_contracts_limit = 2  # Default fallback (per-asset limit)
            if asset:
                try:
                    from merid.risk.profiles.crypto_15m_profile import get_active_profile
                    profile_adapter = get_active_profile()
                    if profile_adapter and hasattr(profile_adapter.profile, 'assets'):
                        assets_config = profile_adapter.profile.assets
                        if assets_config and asset in assets_config:
                            asset_config = assets_config[asset]
                            if hasattr(asset_config, 'max_contracts'):
                                max_contracts_limit = asset_config.max_contracts
                except Exception as e:
                    logger.debug("[kalshi_tools] Failed to load max_contracts from profile: %s, using default 2", e)
            
            # Resolve risk contract fields for crypto 15m markets
            window_resolution_id = "15m"  # Default window resolution for 15m markets
            exit_policy_id = "tp_sl_15m"  # Default exit policy with TP/SL
            risk_tier = "conservative"  # Default risk tier
            max_hold_seconds = 900  # 15 minutes max hold time
            
            # Try to resolve policies using order_router functions if available
            try:
                from merid.event_venues.kalshi.order_router import resolve_window_policy, resolve_exit_policy
                
                # Resolve window policy
                window_resolution = resolve_window_policy(asset=asset if asset else "BTC", regime="neutral")
                window_resolution_id = window_resolution.window_id  # Fixed: was window_resolution_id
                
                # Resolve exit policy with edge result
                edge_result = {"edge_pct": 2.0}  # Default edge
                exit_policy_resolution = resolve_exit_policy(
                    edge_result=edge_result,
                    asset=asset if asset else "BTC",
                    side=side_lower,
                    price_cents=_pc,
                    minutes_to_expiry=15.0
                )
                exit_policy_id = exit_policy_resolution.exit_policy_id
                risk_tier = exit_policy_resolution.regime
                max_hold_seconds = exit_policy_resolution.max_hold_seconds
                
                logger.debug(
                    "[kalshi_tools] Resolved policies: window=%s exit=%s tier=%s max_hold=%d",
                    window_resolution_id, exit_policy_id, risk_tier, max_hold_seconds
                )
            except Exception as e:
                logger.warning("[kalshi_tools] Failed to resolve policies, using defaults: %s", e)
            
            intent = OrderIntent(
                ticker=ticker,
                side=kalshi_side,
                action=action,
                price_cents=_pc,
                count=max(1, min(max_contracts_limit, int(count))),
                source="kalshi_tools",
                agent_id=_agent_name if _agent_name else "kalshi_tools",
                stop_loss_price_cents=stop_loss_price_cents,
                take_profit_r_multiple=take_profit_r_multiple,
                window_resolution_id=window_resolution_id,
                exit_policy_id=exit_policy_id,
                risk_tier=risk_tier,
                max_hold_seconds=max_hold_seconds,
            )

            logger.info(
                "[kalshi_tools] Routing to order_router: %s | %s %s on %s count=%d price=%d¢",
                intent.intent_id, action, side, ticker, count, _pc
            )

            # Route through order_router which enforces global rate limit and cooldown
            result = await route_order_async(intent)

            if result.status == "rejected":
                logger.warning(
                    "[kalshi_tools] Order rejected by router: %s reason=%s",
                    ticker, result.reason
                )
                return ToolResult.fail(
                    ToolErrorCode.POLICY_BLOCKED,
                    f"Order rejected: {result.reason}",
                    tool_name="kalshi_place_order",
                )

            payload = {
                "order_id": result.order_id if hasattr(result, 'order_id') else intent.intent_id,
                "ticker": ticker,
                "side": side,
                "action": action,
                "price_cents": price_cents or _pc,
                "count": count,
                "status": result.status,
                "simulated": result.mode == "paper",
                "shadow": _is_shadow,
                "reason": result.reason,
                "message": f"Order {result.status} via route_order_async",
            }

            if _is_shadow and _agent_name:
                try:
                    from merid.event_venues.kalshi.deployment import get_deployment_controller
                    get_deployment_controller().record_shadow_trade(_agent_name)
                    from merid.prediction.paper_session import get_paper_session
                    _ps = get_paper_session()
                    if _ps.is_active:
                        _ps.record_fill(
                            agent_name=_agent_name,
                            pnl_cents=0.0,
                            fees_cents=0.0,
                            won=None,
                        )
                except Exception as _she:
                    logger.warning("shadow parallel paper record failed: %s", _she)
            elif _agent_name and result.mode == "live":
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

        except ImportError as _imp:
            logger.error(f"[kalshi_tools] Order router import failed: {_imp}")
            return ToolResult.fail(
                ToolErrorCode.INTERNAL,
                "Order router unavailable — order rejected for safety",
                tool_name="kalshi_place_order",
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
        
        # LOOP LAG FIX: Add timeout to prevent blocking event loop on slow API calls
        # OLD-HARDWARE FIX (2026-04-29): Increased to 8s for very spotty internet
        # Positions fetch can be slower than balance due to pagination
        # BUG-FIX: Removed asset= parameter - get_positions_result() doesn't accept it.
        # Asset filtering is done client-side after fetching all positions.
        result = await asyncio.wait_for(client.get_positions_result(), timeout=15.0)

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

        # LOOP LAG FIX: Add timeout to prevent blocking event loop on slow API calls
        # OLD-HARDWARE FIX (2026-04-29): Increased to 5s for spotty internet
        # BUG-FIX (2026-05-07): Increased to 10s to tolerate event-loop lag spikes
        # BUG-FIX (2026-05-11): Increased to 30s to tolerate network congestion + event-loop lag
        # Typical balance call should complete in <500ms; 30s is generous for slow networks + lag
        result = await asyncio.wait_for(client.get_balance_result(), timeout=30.0)

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

    except asyncio.TimeoutError:
        logger.warning("kalshi_get_balance timed out after 30s — using cached/stale balance")
        return ToolResult.fail(
            ToolErrorCode.VENUE_TIMEOUT,
            "Balance fetch timeout — consider using cached value",
            tool_name="kalshi_get_balance",
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
    take_profit_price_cents: Optional[int] = None,
    take_profit_r_multiple: Optional[float] = None,
    stop_loss_price_cents: Optional[int] = None,
):
    """Build a canonical ``OrderIntent`` for live-route / ``VenueOrder`` mapping tests.
    
    For 15m crypto entry orders (buy), exit targets (TP/SL) are required.
    If not provided, default TP is computed using the dynamic TP engine.
    """
    from merid.event_venues.kalshi.order_router import OrderIntent

    is_market = int(price_cents) == 0
    if is_market:
        pc = 0
        otype = "market"
    else:
        # CRITICAL FIX: Clamp to 50-70 cents to prevent extreme purchases
        # This aligns with kalshi_crypto_15m_v2.yaml price_range [50, 70]
        # Optimized for scaling: mid-range prices have better liquidity depth for child orders
        pc = max(50, min(70, int(price_cents)))
        otype = "limit"

    # Compute default TP/SL for 15m crypto entry orders if not provided
    if action == "buy" and ticker.startswith(("KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M")):
        if take_profit_price_cents is None and take_profit_r_multiple is None:
            try:
                from merid.prediction.dynamic_takeprofit import DynamicTakeProfitEngine
                engine = DynamicTakeProfitEngine()
                
                # Default SL: 5 cents below entry (conservative)
                if stop_loss_price_cents is None:
                    stop_loss_price_cents = max(1, pc - 5)
                
                # Compute dynamic TP with default confidence
                tp_plan = engine.compute_tp(
                    entry_price=pc / 100.0,
                    stop_price=stop_loss_price_cents / 100.0,
                    direction="LONG" if side == "yes" else "SHORT",
                    confidence=0.5,  # Default medium confidence
                )
                
                take_profit_r_multiple = tp_plan.tp_r_multiple
            except Exception:
                # Fallback to 1R if TP computation fails
                take_profit_r_multiple = 1.0
                if stop_loss_price_cents is None:
                    stop_loss_price_cents = max(1, pc - 5)

    # CRITICAL FIX: Clamp count to asset-specific max_contracts limit to prevent overspending
    # Read from kalshi_crypto_15m_v2.yaml assets.{asset}.max_contracts (default 2)
    # Extract asset from ticker
    asset = None
    ticker_upper = ticker.upper()
    if "BTC" in ticker_upper:
        asset = "BTC"
    elif "ETH" in ticker_upper:
        asset = "ETH"
    elif "SOL" in ticker_upper:
        asset = "SOL"
    elif "XRP" in ticker_upper:
        asset = "XRP"
    elif "DOGE" in ticker_upper:
        asset = "DOGE"
    
    max_contracts_limit = 2  # Default fallback (per-asset limit)
    if asset:
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            profile_adapter = get_active_profile()
            if profile_adapter and hasattr(profile_adapter.profile, 'assets'):
                assets_config = profile_adapter.profile.assets
                if assets_config and asset in assets_config:
                    asset_config = assets_config[asset]
                    if hasattr(asset_config, 'max_contracts'):
                        max_contracts_limit = asset_config.max_contracts
        except Exception as e:
            logger.debug("[kalshi_tools] Failed to load max_contracts from profile: %s, using default 2", e)

    intent = OrderIntent(
        ticker=ticker,
        side=side,
        action=action,
        price_cents=pc,
        count=max(1, min(max_contracts_limit, int(count))),
        mode=None,
        order_type=otype,
        source=source,
        take_profit_price_cents=take_profit_price_cents,
        take_profit_r_multiple=take_profit_r_multiple,
        stop_loss_price_cents=stop_loss_price_cents,
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
