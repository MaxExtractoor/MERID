"""Kalshi Order Manager — Partial fill handling and order lifecycle.

Tracks orders through their full lifecycle (open → partially_filled →
filled / canceled), processes incremental fills into PnL/risk accounting,
and provides timeout-based cancel logic.

Usage::

    mgr = OrderManager(client)
    tracked = await mgr.submit_order(order)
    result = await mgr.wait_for_fill(tracked.order_id, timeout_s=10)
    mgr.summary()

Integration with PaperSession / KalshiRiskManager::

    mgr = OrderManager(client, on_fill=my_fill_callback)
    # on_fill is called for each incremental fill with (order_id, fill_event)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.order_manager")


# ── Data models ──────────────────────────────────────────────────────────

TERMINAL_STATUSES = frozenset({"filled", "canceled", "cancelled", "expired", "rejected"})


@dataclass
class FillEvent:
    """An incremental fill on a tracked order."""
    order_id: str
    ts: float
    fill_size: int          # contracts filled in this increment
    cumulative_filled: int  # total filled so far
    remaining: int          # contracts still open
    avg_fill_price: Optional[float] = None
    fee_cents: float = 0.0
    ticker: str = ""
    side: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "order_id": self.order_id,
            "ts": self.ts,
            "fill_size": self.fill_size,
            "cumulative_filled": self.cumulative_filled,
            "remaining": self.remaining,
            "avg_fill_price": self.avg_fill_price,
            "fee_cents": self.fee_cents,
            "ticker": self.ticker,
            "side": self.side,
        }


@dataclass
class TrackedOrder:
    """An order being tracked through its lifecycle."""
    order_id: str
    client_order_id: str
    ticker: str
    side: str               # "buy" or "sell"
    outcome: str            # "yes" or "no"
    requested_size: int
    price_cents: int
    status: str = "pending"
    filled_size: int = 0
    remaining_size: int = 0
    avg_fill_price: Optional[float] = None
    created_at: float = 0.0
    last_polled_at: float = 0.0
    fill_events: List[FillEvent] = field(default_factory=list)
    terminal: bool = False
    cancel_requested: bool = False

    def __post_init__(self):
        if self.remaining_size == 0:
            self.remaining_size = self.requested_size

    @property
    def fill_pct(self) -> float:
        if self.requested_size <= 0:
            return 0.0
        return self.filled_size / self.requested_size * 100

    @property
    def is_partial(self) -> bool:
        return 0 < self.filled_size < self.requested_size

    def to_dict(self) -> Dict[str, Any]:
        return {
            "order_id": self.order_id,
            "client_order_id": self.client_order_id,
            "ticker": self.ticker,
            "side": self.side,
            "outcome": self.outcome,
            "requested_size": self.requested_size,
            "price_cents": self.price_cents,
            "status": self.status,
            "filled_size": self.filled_size,
            "remaining_size": self.remaining_size,
            "fill_pct": round(self.fill_pct, 1),
            "avg_fill_price": self.avg_fill_price,
            "terminal": self.terminal,
            "fill_events": [e.to_dict() for e in self.fill_events],
        }


@dataclass
class WaitResult:
    """Result of waiting for an order to fill."""
    order_id: str
    final_status: str
    filled_size: int
    remaining_size: int
    timed_out: bool = False
    canceled_on_timeout: bool = False
    fill_events: List[FillEvent] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "order_id": self.order_id,
            "final_status": self.final_status,
            "filled_size": self.filled_size,
            "remaining_size": self.remaining_size,
            "timed_out": self.timed_out,
            "canceled_on_timeout": self.canceled_on_timeout,
            "fill_count": len(self.fill_events),
        }


@dataclass
class FlattenResult:
    """Result of a cancel-and-flatten operation."""
    order_id: str
    success: bool = False
    cancel_success: bool = False
    filled_size: int = 0
    remaining_canceled: int = 0
    ticker: str = ""
    side: str = ""
    outcome: str = ""
    flatten_order_id: Optional[str] = None
    flatten_placed: bool = False
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "order_id": self.order_id,
            "success": self.success,
            "cancel_success": self.cancel_success,
            "filled_size": self.filled_size,
            "remaining_canceled": self.remaining_canceled,
            "flatten_order_id": self.flatten_order_id,
            "flatten_placed": self.flatten_placed,
            "error": self.error,
        }


# ── Fill callback type ───────────────────────────────────────────────────

FillCallback = Callable[[str, FillEvent], None]


# ── Order Manager ────────────────────────────────────────────────────────

class OrderManager:
    """Manages order lifecycle with incremental fill tracking.

    Wraps a KalshiVenueClient (or any client with get_order / cancel_order
    / place_order methods) and adds:

    - Incremental fill detection (compares filled_size between polls)
    - Fill event callbacks for PnL/risk integration
    - Timeout-based cancel logic
    - Order tracking and summary
    """

    def __init__(
        self,
        client: Any = None,
        on_fill: Optional[FillCallback] = None,
        poll_interval: float = 0.25,
    ) -> None:
        """
        Args:
            client: KalshiVenueClient or compatible async client.
            on_fill: Callback invoked on each incremental fill.
            poll_interval: Default seconds between status polls.
        """
        self._client = client
        self._on_fill = on_fill
        self._poll_interval = poll_interval
        self._orders: Dict[str, TrackedOrder] = {}
        self._total_fills = 0
        self._total_partial_fills = 0

    # ── Submit ───────────────────────────────────────────────────────

    async def submit_order(self, order: Any) -> Optional[TrackedOrder]:
        """Submit an order via the client and start tracking it.

        Args:
            order: A VenueOrder instance.

        Returns:
            TrackedOrder if submission succeeded, None otherwise.
        """
        if self._client is None:
            return None

        # Kill switch hard gate
        try:
            from merid.risk.kill_switches import risk_controller
            if not risk_controller.can_trade():
                reason = risk_controller.get_kill_reason() or "kill_switch_active"
                logger.warning(f"[order-manager] Order blocked by kill switch: {reason}")
                return None
        except ImportError:
            logger.warning("[order-manager] kill_switches module not available — proceeding without kill switch check")
        
        # CRITICAL: Price guard - prevent deep OTM longshots (15¢ minimum)
        if order and hasattr(order, 'price') and order.price is not None:
            _price_cents = int(order.price * 100)
            min_price_cents = 15  # 15 cents / $0.15 minimum
            try:
                from merid.risk.profiles.crypto_15m_profile import get_active_profile
                profile_adapter = get_active_profile()
                if profile_adapter and hasattr(profile_adapter.profile, 'guardrails_min_contract_price_cents'):
                    min_price_cents = profile_adapter.profile.guardrails_min_contract_price_cents
            except Exception as e:
                logger.debug("[order-manager] Failed to load min_contract_price_cents from profile: %s, using default 15c", e)
            
            if _price_cents < min_price_cents:
                logger.critical(
                    "[order-manager] Deep OTM longshot rejected: price=%dc < %dc threshold | ticker=%s",
                    _price_cents, min_price_cents, getattr(order, 'market_id', 'unknown')
                )
                return None

        # G6: VenueGate — block real orders in SIM/PAPER/MOCK mode
        try:
            from merid.prediction.venue_gate import get_venue_gate
            _gate = get_venue_gate()
            if _gate.should_simulate_fill():
                logger.warning(
                    "[order-manager] Order blocked: VenueGate mode=%s (simulated fill mode)",
                    _gate.mode.value,
                )
                return None
        except Exception as _vge:
            logger.debug("[order-manager] VenueGate check skipped: %s", _vge)

        # G6: DeploymentController — block real orders for HALTED or PAPER agents
        _agent_name = getattr(order, "agent_name", "") or ""
        if _agent_name:
            try:
                from merid.event_venues.kalshi.deployment import get_deployment_controller, AgentMode
                _dep = get_deployment_controller()._agents.get(_agent_name)
                if _dep and _dep.mode in (AgentMode.HALTED, AgentMode.PAPER):
                    logger.warning(
                        "[order-manager] Order blocked: agent %s is in %s mode",
                        _agent_name, _dep.mode.value,
                    )
                    return None
            except Exception as _dce:
                logger.debug("[order-manager] DeploymentController check skipped: %s", _dce)

        placed = await self._client.place_order(order)
        if placed is None:
            return None

        tracked = TrackedOrder(
            order_id=placed.order_id,
            client_order_id=getattr(order, "client_order_id", "") or "",
            ticker=placed.market_id,
            side=placed.side,
            outcome=getattr(order, "outcome_id", "yes") or "yes",
            requested_size=int(placed.size),
            price_cents=int(placed.price * 100) if placed.price else 0,
            status=placed.status,
            filled_size=int(placed.filled_size),
            remaining_size=int(placed.remaining_size) if placed.remaining_size else int(placed.size),
            created_at=time.time(),
        )
        self._orders[tracked.order_id] = tracked

        # Publish to streaming_bus.EXECUTION so AuditTrail receives order placements
        try:
            import asyncio as _asyncio
            from core.streaming_bus import streaming_bus, StreamEvent, EventChannel
            _place_event = StreamEvent(
                channel=EventChannel.EXECUTION,
                event_type="order_placed",
                data={
                    "order_id": tracked.order_id,
                    "ticker": tracked.ticker,
                    "side": tracked.side,
                    "outcome": tracked.outcome,
                    "size": tracked.requested_size,
                    "price_cents": tracked.price_cents,
                    "status": tracked.status,
                    "ts": tracked.created_at,
                },
                source="kalshi_order_manager",
            )
            try:
                _loop = _asyncio.get_running_loop()
                _loop.create_task(streaming_bus.publish(_place_event))
            except RuntimeError:
                pass  # No running loop — skip publish (sync context)
        except Exception as _exc:
            logger.debug(f"streaming_bus EXECUTION order_placed publish error (non-fatal): {_exc}")

        return tracked

    # ── Poll and update ──────────────────────────────────────────────

    async def poll_order(self, order_id: str) -> Optional[TrackedOrder]:
        """Poll order status and process any incremental fills.

        Returns updated TrackedOrder, or None if order not found.
        """
        tracked = self._orders.get(order_id)
        if tracked is None or tracked.terminal:
            return tracked

        if self._client is None:
            return tracked

        placed = await self._client.get_order(order_id)
        if placed is None:
            return tracked

        self._update_from_placed(tracked, placed)
        return tracked

    def update_from_status(
        self,
        order_id: str,
        status: str,
        filled_size: int,
        remaining_size: int,
        avg_fill_price: Optional[float] = None,
    ) -> Optional[TrackedOrder]:
        """Manually update order status (for testing or WS-driven updates).

        Returns updated TrackedOrder.
        """
        tracked = self._orders.get(order_id)
        if tracked is None:
            return None

        old_filled = tracked.filled_size
        tracked.status = status
        tracked.filled_size = filled_size
        tracked.remaining_size = remaining_size
        tracked.avg_fill_price = avg_fill_price
        tracked.last_polled_at = time.time()
        tracked.terminal = status in TERMINAL_STATUSES

        # Detect incremental fill
        increment = filled_size - old_filled
        if increment > 0:
            self._emit_fill(tracked, increment)

        return tracked

    def _update_from_placed(self, tracked: TrackedOrder, placed: Any) -> None:
        """Update tracked order from a PlacedOrder response."""
        old_filled = tracked.filled_size
        tracked.status = placed.status
        tracked.filled_size = int(placed.filled_size)
        if placed.remaining_size is not None:
            tracked.remaining_size = int(placed.remaining_size)
        else:
            tracked.remaining_size = tracked.requested_size - tracked.filled_size
        tracked.last_polled_at = time.time()
        tracked.terminal = placed.status in TERMINAL_STATUSES

        # Detect incremental fill
        increment = tracked.filled_size - old_filled
        if increment > 0:
            self._emit_fill(tracked, increment)

    def _emit_fill(self, tracked: TrackedOrder, increment: int) -> None:
        """Create a FillEvent and invoke the callback."""
        event = FillEvent(
            order_id=tracked.order_id,
            ts=time.time(),
            fill_size=increment,
            cumulative_filled=tracked.filled_size,
            remaining=tracked.remaining_size,
            avg_fill_price=tracked.avg_fill_price,
            ticker=tracked.ticker,
            side=tracked.side,
        )
        tracked.fill_events.append(event)
        self._total_fills += 1
        if tracked.is_partial:
            self._total_partial_fills += 1

        if self._on_fill:
            try:
                self._on_fill(tracked.order_id, event)
            except Exception as exc:
                logger.warning(f"Fill callback error for {tracked.order_id}: {exc}")

        # Publish to streaming_bus.EXECUTION so AuditTrail + any EXECUTION subscribers receive fills
        try:
            import asyncio as _asyncio
            from core.streaming_bus import streaming_bus, StreamEvent, EventChannel
            _exec_event = StreamEvent(
                channel=EventChannel.EXECUTION,
                event_type="order_fill",
                data=event.to_dict(),
                source="kalshi_order_manager",
            )
            try:
                _loop = _asyncio.get_running_loop()
                _loop.create_task(streaming_bus.publish(_exec_event))
            except RuntimeError:
                pass  # No running loop — skip publish (sync context)
        except Exception as _exc:
            logger.debug(f"streaming_bus EXECUTION publish error (non-fatal): {_exc}")

    # ── Wait for fill ────────────────────────────────────────────────

    async def wait_for_fill(
        self,
        order_id: str,
        timeout_s: float = 10.0,
        poll_interval: Optional[float] = None,
        cancel_on_timeout: bool = True,
    ) -> WaitResult:
        """Poll until order reaches a terminal state or times out.

        Args:
            order_id: Order to wait for.
            timeout_s: Max seconds to wait.
            poll_interval: Override default poll interval.
            cancel_on_timeout: If True, cancel remaining size on timeout.

        Returns:
            WaitResult with final status and fill events.
        """
        interval = poll_interval or self._poll_interval
        start = time.time()
        tracked = self._orders.get(order_id)

        if tracked is None:
            return WaitResult(
                order_id=order_id, final_status="unknown",
                filled_size=0, remaining_size=0, timed_out=True,
            )

        while time.time() - start < timeout_s:
            if tracked.terminal:
                break
            await asyncio.sleep(interval)
            await self.poll_order(order_id)

        timed_out = not tracked.terminal
        canceled = False

        if timed_out and cancel_on_timeout and tracked.remaining_size > 0:
            if self._client is not None:
                success = await self._client.cancel_order(order_id)
                canceled = success
                if success:
                    tracked.cancel_requested = True
                    tracked.status = "canceled"
                    tracked.terminal = True

        return WaitResult(
            order_id=order_id,
            final_status=tracked.status,
            filled_size=tracked.filled_size,
            remaining_size=tracked.remaining_size,
            timed_out=timed_out,
            canceled_on_timeout=canceled,
            fill_events=list(tracked.fill_events),
        )

    # ── Cancel ───────────────────────────────────────────────────────

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an order and update tracking."""
        tracked = self._orders.get(order_id)
        if tracked is None or tracked.terminal:
            return False

        if self._client is not None:
            success = await self._client.cancel_order(order_id)
            if not success:
                return False

        tracked.cancel_requested = True
        tracked.status = "canceled"
        tracked.terminal = True
        return True

    # ── Cancel and flatten ──────────────────────────────────────────

    async def cancel_and_flatten(
        self,
        order_id: str,
        place_flatten_order: bool = True,
    ) -> "FlattenResult":
        """Atomic cancel → reconcile → flatten sequence for mental stops.

        1. Cancel the resting order
        2. Poll the order to get final filled_count (post-cancel reconciliation)
        3. If any contracts were filled, optionally place an opposite-side
           taker order sized to the *actual* filled position (not the
           original intended size)

        Args:
            order_id: The order to cancel and flatten.
            place_flatten_order: If True, place an opposite-side market
                order to close the filled position.

        Returns:
            FlattenResult with reconciliation details.
        """
        tracked = self._orders.get(order_id)
        if tracked is None:
            return FlattenResult(
                order_id=order_id, success=False,
                error="Order not found",
            )

        # Step 1: Cancel resting order via client directly
        # (Don't use self.cancel_order which sets terminal and blocks polling)
        cancel_success = False
        if self._client is not None and not tracked.terminal:
            cancel_success = await self._client.cancel_order(order_id)
            tracked.cancel_requested = True
        elif tracked.terminal:
            cancel_success = True  # Already terminal

        # Step 2: Reconcile — poll to get final filled_count BEFORE setting terminal
        # This captures any fills that happened before/during cancel
        if self._client is not None:
            # Temporarily allow polling by unsetting terminal
            was_terminal = tracked.terminal
            tracked.terminal = False
            await self.poll_order(order_id)
            # Now set terminal
            tracked.terminal = True
            tracked.status = tracked.status if tracked.status in TERMINAL_STATUSES else "canceled"
        else:
            tracked.terminal = True
            tracked.status = "canceled"

        filled_before_cancel = tracked.filled_size
        remaining_after_cancel = tracked.remaining_size

        result = FlattenResult(
            order_id=order_id,
            success=True,
            cancel_success=cancel_success,
            filled_size=filled_before_cancel,
            remaining_canceled=remaining_after_cancel if cancel_success else 0,
            ticker=tracked.ticker,
            side=tracked.side,
            outcome=tracked.outcome,
        )

        # Step 3: If position exists and flatten requested, place opposite order
        if place_flatten_order and filled_before_cancel > 0 and self._client is not None:
            opposite_side = "sell" if tracked.side == "buy" else "buy"
            try:
                # G14: VenueGate — skip real flatten order in paper/sim mode
                _allow_flatten = True
                try:
                    from merid.prediction.venue_gate import get_venue_gate as _gvg
                    if _gvg().should_simulate_fill():
                        _allow_flatten = False
                        logger.debug(
                            "[order-manager] flatten skipped: VenueGate in paper/sim mode for %s",
                            tracked.ticker,
                        )
                except Exception as _vg_exc:
                    logger.debug("[order-manager] VenueGate check failed during flatten: %s", _vg_exc)
                flatten_placed = None
                if _allow_flatten:
                    from merid.event_venues.base import VenueOrder
                    # BUG-FIX: Pass price for ALL orders (including market) to avoid 50c fallback in Kalshi client
                    # PRODUCTION-FIX: Use actual market price from KalshiMarketStateStore instead of hardcoded 50c
                    price_est = 50  # Fallback if market state unavailable
                    try:
                        from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                        state = get_kalshi_market_state_store().get_unified(tracked.ticker)
                        if state and state.mid_cents > 0:
                            price_est = state.mid_cents
                    except Exception as _exc:
                        logger.debug("flatten_order: failed to fetch market state for %s, using 50c fallback: %s", tracked.ticker, _exc)
                    
                    # Kalshi API accepts price for market orders (it's used for validation but not as a limit)
                    flatten_order = VenueOrder(
                        market_id=tracked.ticker,
                        side=opposite_side,
                        size=filled_before_cancel,
                        price=Decimal(price_est) / 100,
                        order_type="market",
                        outcome_id=tracked.outcome,
                    )
                    flatten_placed = await self._client.place_order(flatten_order)
                if flatten_placed is not None:
                    result.flatten_order_id = flatten_placed.order_id
                    result.flatten_placed = True
                    # Track the flatten order too
                    flatten_tracked = TrackedOrder(
                        order_id=flatten_placed.order_id,
                        client_order_id="",
                        ticker=tracked.ticker,
                        side=opposite_side,
                        outcome=tracked.outcome,
                        requested_size=filled_before_cancel,
                        price_cents=0,
                        status=flatten_placed.status,
                        filled_size=int(flatten_placed.filled_size),
                        created_at=time.time(),
                    )
                    self._orders[flatten_placed.order_id] = flatten_tracked
                else:
                    result.error = "Flatten order placement failed"
            except Exception as exc:
                result.error = f"Flatten order error: {exc}"
                logger.warning(f"[order-mgr] Flatten failed for {order_id}: {exc}")

        return result

    # ── Tracking ─────────────────────────────────────────────────────

    def track_order(
        self,
        order_id: str,
        ticker: str = "",
        side: str = "",
        outcome: str = "yes",
        requested_size: int = 0,
        price_cents: int = 0,
    ) -> TrackedOrder:
        """Manually register an order for tracking (e.g. placed externally)."""
        tracked = TrackedOrder(
            order_id=order_id,
            client_order_id="",
            ticker=ticker,
            side=side,
            outcome=outcome,
            requested_size=requested_size,
            price_cents=price_cents,
            created_at=time.time(),
        )
        self._orders[order_id] = tracked
        return tracked

    def get_tracked(self, order_id: str) -> Optional[TrackedOrder]:
        return self._orders.get(order_id)

    @property
    def open_orders(self) -> List[TrackedOrder]:
        return [o for o in self._orders.values() if not o.terminal]

    @property
    def all_orders(self) -> List[TrackedOrder]:
        return list(self._orders.values())

    # ── Summary ──────────────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """JSON-serializable order manager summary."""
        orders = list(self._orders.values())
        open_orders = [o for o in orders if not o.terminal]
        filled = [o for o in orders if o.status == "filled"]
        partial = [o for o in orders if o.is_partial]
        canceled = [o for o in orders if o.status in ("canceled", "cancelled")]

        return {
            "total_orders": len(orders),
            "open_orders": len(open_orders),
            "filled_orders": len(filled),
            "partial_fills": len(partial),
            "canceled_orders": len(canceled),
            "total_fill_events": self._total_fills,
            "total_partial_fill_events": self._total_partial_fills,
            "orders": {oid: o.to_dict() for oid, o in self._orders.items()},
        }
