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
    except Exception:
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
    except ImportError:
        pass  # risk_controller not available — proceed cautiously

    gate = get_venue_gate()
    if not gate.live_enabled:
        latency = (time.monotonic() - t0) * 1000
        return OrderResult(
            status="rejected",
            mode=mode,
            reason="live_not_enabled",
            latency_ms=round(latency, 2),
        )

    try:
        from merid.event_venues.base import VenueOrder
        from merid.event_venues.kalshi.client import get_kalshi_client

        client = get_kalshi_client()
        await client.connect()

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

        placed_res = await client.place_order_result(order)
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

    if _is_live_mode(mode):
        return await _route_live(intent, mode, t0)

    return _route_sync_non_live(intent, mode, t0)

    # Fallback
    latency = (time.monotonic() - t0) * 1000
    return OrderResult(
        status="rejected",
        mode=mode,
        reason=f"unknown_mode_{mode}",
        latency_ms=round(latency, 2),
    )
