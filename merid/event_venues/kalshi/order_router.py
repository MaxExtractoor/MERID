"""Kalshi Order Router — Mode-aware order dispatch (mock/paper/live).

Routes ``OrderIntent`` through risk checks and dispatches to the
appropriate execution path based on ``TradingMode``.

Usage::

    from merid.event_venues.kalshi.order_router import (
        OrderIntent, OrderResult, route_order,
    )

    intent = OrderIntent(
        ticker="KXBTCD-25JUN-T100000",
        side="yes",
        action="buy",
        price_cents=55,
        count=10,
    )
    result = route_order(intent)
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from merid.prediction.venue_gate import TradingMode, get_venue_gate
from trading.trade_mode import get_trade_mode
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.order_router")


PAPER_SLIPPAGE_BPS = float(os.getenv("MERID_KALSHI_PAPER_SLIPPAGE_BPS", "8.0"))
PAPER_PARTIAL_FILL_PROB = float(os.getenv("MERID_KALSHI_PAPER_PARTIAL_FILL_PROB", "0.35"))
PAPER_MIN_FILL_RATIO = float(os.getenv("MERID_KALSHI_PAPER_MIN_FILL_RATIO", "0.4"))

# ── WS / event bus channel constants ──────────────────────────────────────

KALSHI_CHANNEL_PRICE = "kalshi:price_update"
KALSHI_CHANNEL_TRADE = "kalshi:trade"
KALSHI_CHANNEL_ORDERBOOK = "kalshi:orderbook_delta"
KALSHI_CHANNEL_ORDER_FILL = "kalshi:order_fill"
KALSHI_CHANNEL_ORDER_REJECT = "kalshi:order_reject"
KALSHI_CHANNEL_ORDER_GROUP_TRIGGERED = "kalshi:order_group_triggered"


# ── Order Group Auto-Cancel Handler ─────────────────────────────────────

async def handle_order_group_triggered(group_id: str, group_data: Dict[str, Any]) -> Dict[str, Any]:
    """Handle order group triggered event - cancel all orders in the group.

    Called when WebSocket receives a triggered status for an order group.
    Fetches all open orders in the group and cancels them.

    Args:
        group_id: The order group ID that was triggered
        group_data: Full group data from the WebSocket message

    Returns:
        Dict with canceled order IDs and status
    """
    from merid.event_venues.kalshi.client import get_kalshi_client

    logger.warning(f"[order-router] Order group {group_id} triggered - initiating auto-cancel")

    client = get_kalshi_client()
    if not client:
        return {"error": "Kalshi client not available", "canceled": []}

    try:
        await client.connect()

        # Get all open orders
        result = await client.get_open_orders_result()
        if not result.success:
            return {"error": str(result.error), "canceled": []}

        all_orders = result.data or []

        # Filter orders by group_id
        group_orders = [
            o for o in all_orders
            if o.get("order_group_id") == group_id or o.get("group_id") == group_id
        ]

        if not group_orders:
            logger.info(f"[order-router] No open orders found for triggered group {group_id}")
            return {"group_id": group_id, "canceled": [], "message": "No orders to cancel"}

        # Cancel each order
        canceled = []
        failed = []

        for order in group_orders:
            order_id = order.get("order_id")
            if not order_id:
                continue

            try:
                cancel_result = await client.cancel_order_result(order_id)
                if cancel_result.success:
                    canceled.append(order_id)
                    logger.info(f"[order-router] Auto-canceled order {order_id} from triggered group {group_id}")
                else:
                    failed.append({"order_id": order_id, "error": str(cancel_result.error)})
            except Exception as e:
                failed.append({"order_id": order_id, "error": str(e)})

        await client.close()

        # Publish event for other components
        try:
            from core.events import publish_event
            publish_event(KALSHI_CHANNEL_ORDER_GROUP_TRIGGERED, {
                "group_id": group_id,
                "canceled_orders": canceled,
                "failed_cancels": failed,
                "group_data": group_data,
                "ts": datetime.now(timezone.utc).isoformat(),
            })
        except ImportError:
            pass

        return {
            "group_id": group_id,
            "canceled": canceled,
            "failed": failed,
            "total_orders": len(group_orders),
        }

    except Exception as exc:
        logger.error(f"[order-router] Auto-cancel failed for triggered group {group_id}: {exc}")
        return {"error": str(exc), "group_id": group_id, "canceled": []}


# ── OrderIntent ───────────────────────────────────────────────────────────

@dataclass
class OrderIntent:
    """Typed order intent for Kalshi markets.

    Attributes:
        ticker: Kalshi market ticker
        side: ``"yes"`` or ``"no"``
        action: ``"buy"`` or ``"sell"``
        price_cents: Limit price in cents (1-99)
        count: Number of contracts
        mode: Override trading mode (None = use VenueGate default)
        order_type: ``"limit"`` or ``"market"``
        time_in_force: ``"fill_or_kill"`` | ``"gtc"`` | ``"ioc"``
        edge_pct: Optional edge estimate for risk checks
        source: Originating agent/strategy name
        order_group_id: Optional order group ID for aggregate limits
        self_trade_prevention_type: Optional STP mode (e.g., "taker_at_cross")
    """
    ticker: str
    side: str
    action: str
    price_cents: int
    count: int
    mode: Optional[TradingMode] = None
    order_type: str = "limit"
    time_in_force: str = "fill_or_kill"
    edge_pct: Optional[float] = None
    source: str = "manual"
    order_group_id: Optional[str] = None
    self_trade_prevention_type: Optional[str] = None
    post_only: bool = False
    # Live orderbook params (E1) — populated from the current orderbook snapshot
    spread_cents: Optional[int] = None
    depth_at_price: Optional[int] = None


@dataclass
class OrderResult:
    """Result of order routing.

    Attributes:
        status: ``"filled_mock"`` | ``"filled_paper"`` | ``"filled_live"`` | ``"rejected"``
        mode: Resolved trading mode
        fill: Fill details (if filled)
        reason: Rejection reason (if rejected)
        latency_ms: Routing latency
    """
    status: str
    mode: TradingMode
    fill: Optional[Dict[str, Any]] = None
    reason: Optional[str] = None
    latency_ms: float = 0.0


# ── Paper fill simulation ─────────────────────────────────────────────────

def _resolve_mode(override: Optional[TradingMode]) -> TradingMode:
    """Resolve mode from explicit override or canonical process-wide mode."""
    if override is not None:
        return override
    try:
        return TradingMode(get_trade_mode().value)
    except Exception as _e:
        logger.debug("_resolve_mode: get_trade_mode failed, falling back to venue_gate: %s", _e)
        return get_venue_gate().mode


def _mode_value(mode: TradingMode) -> str:
    return getattr(mode, "value", str(mode)).lower()


def _is_mock_mode(mode: TradingMode) -> bool:
    # Keep legacy "sim" compatibility while canonical mode is "mock"
    return _mode_value(mode) in {"mock", "sim"}


def _is_paper_mode(mode: TradingMode) -> bool:
    return _mode_value(mode) == "paper"


def _is_live_mode(mode: TradingMode) -> bool:
    return _mode_value(mode) == "live"


def _kalshi_fee_cents(price_cents: int, contracts: int) -> int:
    """Kalshi fee schedule mirrored for simulation/live-normalized reporting."""
    if contracts <= 0 or price_cents <= 0 or price_cents >= 100:
        return 0
    payout = 100 - price_cents
    if contracts < 100:
        rate = 0.07
    elif contracts < 1000:
        rate = 0.05
    else:
        rate = 0.03
    per_contract = max(2, int((payout * rate) + 0.9999))
    return per_contract * contracts


def simulate_paper_fill(intent: OrderIntent) -> Dict[str, Any]:
    """Simulate a paper/mock fill with slippage, partial-fill probability, and fees."""
    requested_count = max(0, int(intent.count))
    requested_price = max(1, min(99, int(intent.price_cents)))

    # Basic side-aware slippage in cents from configured basis points.
    slippage_cents = max(0, int(round(requested_price * PAPER_SLIPPAGE_BPS / 10_000)))
    if intent.order_type == "market":
        slippage_cents = max(slippage_cents, 1)

    # Buy pays up; sell receives down.
    side_sign = 1 if intent.action == "buy" else -1
    fill_price = max(1, min(99, requested_price + (side_sign * slippage_cents)))

    # Partial fill simulation when size > 1 contract.
    partial_fill = False
    fill_count = requested_count
    if requested_count > 1 and random.random() < PAPER_PARTIAL_FILL_PROB:
        partial_fill = True
        min_fill = max(1, int(round(requested_count * PAPER_MIN_FILL_RATIO)))
        fill_count = random.randint(min_fill, requested_count)

    remaining_count = max(0, requested_count - fill_count)
    fee_cents = _kalshi_fee_cents(fill_price, fill_count)

    return {
        "ticker": intent.ticker,
        "side": intent.side,
        "action": intent.action,
        "price_cents": fill_price,
        "requested_price_cents": requested_price,
        "count": fill_count,
        "requested_count": requested_count,
        "remaining_count": remaining_count,
        "partial_fill": partial_fill,
        "fee_cents": fee_cents,
        "ts": datetime.now(timezone.utc).isoformat(),
        "simulated": True,
    }


# ── Risk check ────────────────────────────────────────────────────────────

def _check_intent_risk(intent: OrderIntent) -> Optional[str]:
    """Basic pre-flight risk checks on an OrderIntent.

    Returns rejection reason string, or None if OK.
    """
    if intent.count <= 0:
        return "non_positive_size"
    if intent.price_cents <= 0 or intent.price_cents >= 100:
        return "invalid_price"
    if intent.side not in ("yes", "no"):
        return "invalid_side"
    if intent.action not in ("buy", "sell"):
        return "invalid_action"
    return None


# ── Router ────────────────────────────────────────────────────────────────

def _route_sync_non_live(intent: OrderIntent, mode: TradingMode, t0: float) -> OrderResult:
    """Route MOCK/PAPER intents synchronously."""
    if _is_mock_mode(mode):
        fill = simulate_paper_fill(intent)
        latency = (time.monotonic() - t0) * 1000
        logger.info(
            f"[order-router] MOCK fill {intent.ticker} {intent.action} "
            f"{intent.count}x @ {intent.price_cents}c"
        )
        return OrderResult(
            status="filled_mock",
            mode=mode,
            fill=fill,
            latency_ms=round(latency, 2),
        )

    if _is_paper_mode(mode):
        fill = simulate_paper_fill(intent)
        latency = (time.monotonic() - t0) * 1000
        logger.info(
            f"[order-router] PAPER fill {intent.ticker} {intent.action} "
            f"{intent.count}x @ {intent.price_cents}c"
        )
        return OrderResult(
            status="filled_paper",
            mode=mode,
            fill=fill,
            latency_ms=round(latency, 2),
        )

    latency = (time.monotonic() - t0) * 1000
    return OrderResult(
        status="rejected",
        mode=mode,
        reason=f"sync_route_unsupported_mode_{_mode_value(mode)}",
        latency_ms=round(latency, 2),
    )


async def _route_live(intent: OrderIntent, mode: TradingMode, t0: float) -> OrderResult:
    """Route LIVE intents through the canonical KalshiVenueClient."""
    # Kill switch hard gate — must be checked before any live execution
    try:
        from merid.risk.kill_switches import risk_controller
        if not risk_controller.can_trade():
            latency = (time.monotonic() - t0) * 1000
            reason = risk_controller.get_kill_reason() or "kill_switch_active"
            logger.warning(f"[order-router] Live order blocked by kill switch: {reason}")
            return OrderResult(
                status="rejected",
                mode=mode,
                reason=f"kill_switch:{reason}",
                latency_ms=round(latency, 2),
            )
    except ImportError as exc:
        # Fail-closed: if risk_controller unavailable, block live orders for safety
        latency = (time.monotonic() - t0) * 1000
        logger.error(f"[order-router] Risk controller unavailable - blocking live order: {exc}")
        return OrderResult(
            status="rejected",
            mode=mode,
            reason="risk_controller_unavailable",
            latency_ms=round(latency, 2),
        )
    except Exception as exc:
        # Fail-closed: any unexpected error in risk check should block order
        latency = (time.monotonic() - t0) * 1000
        logger.error(f"[order-router] Risk check failed - blocking live order: {exc}")
        return OrderResult(
            status="rejected",
            mode=mode,
            reason=f"risk_check_error:{str(exc)}",
            latency_ms=round(latency, 2),
        )

    gate = get_venue_gate()
    if not gate.live_enabled:
        latency = (time.monotonic() - t0) * 1000
        return OrderResult(
            status="rejected",
            mode=mode,
            reason="live_not_enabled",
            latency_ms=round(latency, 2),
        )

    # KalshiRiskManager — position limits, category caps, drawdown, rate limiting
    try:
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
        risk = get_kalshi_risk()
        allowed, reason = risk.check_order(
            ticker=intent.ticker,
            category=None,  # category inferred downstream if needed
            contracts=intent.count,
            price_cents=intent.price_cents,
            edge=intent.edge_pct or 0.0,
            spread_cents=intent.spread_cents,
            depth_at_price=intent.depth_at_price,
        )
        if not allowed:
            latency = (time.monotonic() - t0) * 1000
            logger.warning(f"[order-router] Live order blocked by KalshiRiskManager: {reason}")
            return OrderResult(
                status="rejected",
                mode=mode,
                reason=f"risk_check:{reason}",
                latency_ms=round(latency, 2),
            )
    except Exception as exc:
        latency = (time.monotonic() - t0) * 1000
        logger.error(f"[order-router] KalshiRiskManager unavailable — blocking live order: {exc}")
        return OrderResult(
            status="rejected",
            mode=mode,
            reason=f"risk_manager_unavailable:{exc}",
            latency_ms=round(latency, 2),
        )

    try:
        from merid.event_venues.base import VenueOrder
        from merid.event_venues.kalshi.client import get_kalshi_client
        from merid.event_venues.kalshi.order_group_manager import OrderGroupRiskManager

        client = get_kalshi_client()
        await client.connect()

        # ── Order Group Risk Check ─────────────────────────────────────────
        if intent.order_group_id:
            og_manager = OrderGroupRiskManager(client)
            group = og_manager.get_group(intent.order_group_id)
            
            if not group:
                latency = (time.monotonic() - t0) * 1000
                return OrderResult(
                    status="rejected",
                    mode=mode,
                    reason=f"order_group_not_found:{intent.order_group_id}",
                    latency_ms=round(latency, 2),
                )
            
            if not group.is_active():
                latency = (time.monotonic() - t0) * 1000
                return OrderResult(
                    status="rejected",
                    mode=mode,
                    reason=f"order_group_not_active:{intent.order_group_id}:status={group.status}",
                    latency_ms=round(latency, 2),
                )
            
            if not group.can_add_contracts(intent.count):
                latency = (time.monotonic() - t0) * 1000
                return OrderResult(
                    status="rejected",
                    mode=mode,
                    reason=f"order_group_limit_exceeded:{intent.order_group_id}:used={group.used_contracts}:limit={group.contracts_limit}:requested={intent.count}",
                    latency_ms=round(latency, 2),
                )
            
            # Record optimistic usage
            og_manager.record_new_order(intent.order_group_id, intent.count)

        tif = intent.time_in_force.upper()
        if tif not in {"GTC", "IOC", "FOK"}:
            tif = "GTC"

        order = VenueOrder(
            market_id=intent.ticker,
            side=intent.action,
            size=Decimal(intent.count),
            price=(Decimal(intent.price_cents) / Decimal("100")) if intent.order_type == "limit" else None,
            order_type="limit" if intent.order_type == "limit" else "market",
            outcome_id=intent.side,
            time_in_force=tif,
            client_order_id=f"merid_{intent.source}_{int(time.time() * 1000)}",
        )

        placed_res = await client.place_order_result(
            order,
            order_group_id=intent.order_group_id,
            self_trade_prevention_type=intent.self_trade_prevention_type,
        )
        latency = (time.monotonic() - t0) * 1000
        if not placed_res.success or placed_res.data is None:
            reason = getattr(placed_res, "error_message", None) or str(placed_res.error) if placed_res.error else "live_order_failed"
            return OrderResult(
                status="rejected",
                mode=mode,
                reason=reason,
                latency_ms=round(latency, 2),
            )

        placed = placed_res.data
        requested_count = int(placed.size)
        filled_count = int(placed.filled_size)
        remaining_count = int(placed.remaining_size) if placed.remaining_size is not None else max(0, requested_count - filled_count)
        fill_price_cents = int((placed.price or Decimal(intent.price_cents) / Decimal("100")) * 100)
        fee_cents = _kalshi_fee_cents(fill_price_cents, filled_count)

        if filled_count >= requested_count and requested_count > 0:
            status = "filled_live"
        elif filled_count > 0:
            status = "partial_live"
        else:
            status = "accepted_live"

        # Record fill in KalshiRiskManager for exposure/rate tracking
        if filled_count > 0:
            try:
                from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
                get_kalshi_risk().record_order(None, filled_count, fill_price_cents)
            except Exception as _rr:
                logger.debug("record_order after live fill failed (non-fatal): %s", _rr)

        return OrderResult(
            status=status,
            mode=mode,
            fill={
                "ticker": intent.ticker,
                "side": intent.side,
                "action": intent.action,
                "price_cents": fill_price_cents,
                "count": filled_count,
                "requested_count": requested_count,
                "remaining_count": remaining_count,
                "fee_cents": fee_cents,
                "order_id": placed.order_id,
                "status": placed.status,
                "ts": datetime.now(timezone.utc).isoformat(),
                "simulated": False,
            },
            latency_ms=round(latency, 2),
        )
    except Exception as exc:
        latency = (time.monotonic() - t0) * 1000
        logger.error(f"[order-router] LIVE execution failed: {exc}")
        return OrderResult(
            status="rejected",
            mode=mode,
            reason=f"live_execution_error:{exc}",
            latency_ms=round(latency, 2),
        )


def route_order(intent: OrderIntent) -> OrderResult:
    """Sync order routing (MOCK/PAPER only).

    LIVE mode requires ``route_order_async`` so the real Kalshi client can be
    called without blocking hacks.
    """
    t0 = time.monotonic()
    mode = _resolve_mode(intent.mode)

    # Risk check
    reject_reason = _check_intent_risk(intent)
    if reject_reason:
        latency = (time.monotonic() - t0) * 1000
        logger.warning(
            f"[order-router] REJECTED {intent.ticker} {intent.action} "
            f"{intent.count}x @ {intent.price_cents}c: {reject_reason}"
        )
        return OrderResult(
            status="rejected",
            mode=mode,
            reason=reject_reason,
            latency_ms=round(latency, 2),
        )

    if _is_live_mode(mode):
        latency = (time.monotonic() - t0) * 1000
        return OrderResult(
            status="rejected",
            mode=mode,
            reason="live_requires_async_route_order",
            latency_ms=round(latency, 2),
        )

    return _route_sync_non_live(intent, mode, t0)


async def route_order_async(intent: OrderIntent) -> OrderResult:
    """Async order routing that supports true LIVE execution."""
    t0 = time.monotonic()
    mode = _resolve_mode(intent.mode)

    reject_reason = _check_intent_risk(intent)
    if reject_reason:
        latency = (time.monotonic() - t0) * 1000
        logger.warning(
            f"[order-router] REJECTED {intent.ticker} {intent.action} "
            f"{intent.count}x @ {intent.price_cents}c: {reject_reason}"
        )
        return OrderResult(
            status="rejected",
            mode=mode,
            reason=reject_reason,
            latency_ms=round(latency, 2),
        )

    # ── E-3: Venue availability check ──────────────────────────────────────
    try:
        from merid.event_venues.kalshi.exchange_availability import (
            get_exchange_availability,
        )
        avail = get_exchange_availability()
        if not avail.trading_open_now():
            latency = (time.monotonic() - t0) * 1000
            logger.warning(
                "[order-router] Order blocked — Kalshi venue not available: %s",
                intent.ticker,
            )
            return OrderResult(
                status="rejected",
                mode=mode,
                reason="venue_unavailable:kalshi_maintenance",
                latency_ms=round(latency, 2),
            )
    except Exception as _avail_exc:
        logger.debug("[order-router] Exchange availability check skipped: %s", _avail_exc)

    # ── E-2: RTI settlement-window buy-block ────────────────────────────────
    try:
        from merid.event_venues.kalshi.settlement_execution_guard import (
            evaluate_settlement_order,
        )
        guard_result = evaluate_settlement_order(intent)
        if not guard_result.allowed:
            latency = (time.monotonic() - t0) * 1000
            logger.warning(
                "[order-router] Order blocked by settlement guard: %s — %s",
                intent.ticker,
                guard_result.reason,
            )
            return OrderResult(
                status="rejected",
                mode=mode,
                reason=guard_result.reason or "settlement_window_block",
                latency_ms=round(latency, 2),
            )
    except Exception as _sg_exc:
        logger.debug("[order-router] Settlement guard check skipped: %s", _sg_exc)

    if _is_live_mode(mode):
        return await _route_live(intent, mode, t0)

    return _route_sync_non_live(intent, mode, t0)


# ═══════════════════════════════════════════════════════════════════════════
# Batch Order Placement with Order Group Assignment
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class BatchOrderIntent:
    """Batch of orders with shared order group."""
    orders: List[OrderIntent]
    order_group_id: Optional[str] = None
    self_trade_prevention_type: Optional[str] = None
    mode: Optional[TradingMode] = None


@dataclass
class BatchOrderResult:
    """Result of batch order placement."""
    total: int
    successful: int
    failed: int
    results: List[OrderResult]
    latency_ms: float
    order_group_id: Optional[str] = None


async def route_batch_orders_async(
    batch: BatchOrderIntent,
    max_concurrent: int = 5,
) -> BatchOrderResult:
    """Route multiple orders with optional shared order group.

    All orders in the batch share the same order_group_id and STP type
    if specified at the batch level. Individual order settings override
    batch-level defaults.

    Args:
        batch: Batch of orders to place
        max_concurrent: Max concurrent order placements

    Returns:
        BatchOrderResult with aggregated results
    """
    t0 = time.monotonic()

    # Apply batch-level defaults to each order
    orders: List[OrderIntent] = []
    for intent in batch.orders:
        # Merge batch-level settings
        order_group_id = intent.order_group_id or batch.order_group_id
        stp_type = intent.self_trade_prevention_type or batch.self_trade_prevention_type
        mode = intent.mode or batch.mode

        orders.append(OrderIntent(
            ticker=intent.ticker,
            side=intent.side,
            action=intent.action,
            price_cents=intent.price_cents,
            count=intent.count,
            mode=mode,
            order_type=intent.order_type,
            time_in_force=intent.time_in_force,
            edge_pct=intent.edge_pct,
            source=intent.source,
            order_group_id=order_group_id,
            self_trade_prevention_type=stp_type,
            post_only=intent.post_only,
        ))

    # Validate all orders first
    valid_orders: List[OrderIntent] = []
    pre_validated_results: List[OrderResult] = []

    for intent in orders:
        reject_reason = _check_intent_risk(intent)
        if reject_reason:
            pre_validated_results.append(OrderResult(
                status="rejected",
                mode=_resolve_mode(intent.mode),
                reason=f"pre_validation_failed:{reject_reason}",
                latency_ms=0.0,
            ))
        else:
            valid_orders.append(intent)

    # Route valid orders with concurrency limit
    semaphore = asyncio.Semaphore(max_concurrent)

    async def route_with_limit(intent: OrderIntent) -> OrderResult:
        async with semaphore:
            return await route_order_async(intent)

    # Execute all valid orders concurrently
    route_tasks = [route_with_limit(intent) for intent in valid_orders]
    route_results = await asyncio.gather(*route_tasks, return_exceptions=True)

    # Combine pre-validation failures with routing results
    all_results = pre_validated_results + [
        r if isinstance(r, OrderResult) else OrderResult(
            status="rejected",
            mode=TradingMode.MOCK,
            reason=f"routing_exception:{str(r)}",
            latency_ms=0.0,
        )
        for r in route_results
    ]

    latency = (time.monotonic() - t0) * 1000

    successful = sum(1 for r in all_results if "filled" in r.status or "accepted" in r.status)
    failed = len(all_results) - successful

    return BatchOrderResult(
        total=len(batch.orders),
        successful=successful,
        failed=failed,
        results=all_results,
        latency_ms=round(latency, 2),
        order_group_id=batch.order_group_id,
    )
