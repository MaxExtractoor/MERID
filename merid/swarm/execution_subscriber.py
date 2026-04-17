"""Execution Subscriber — Sprint M.

Subscribes to Decision messages on the StreamingBus and routes approved
decisions to the execution path. This closes the last architectural gap:
the execution agent now consumes from the bus instead of being called
directly by the sequential loop.

The subscriber:
1. Listens on CONSENSUS + EXECUTION channels
2. Filters for Decision messages with ``risk_approved=True``
3. Routes to the appropriate TradingAgent's ``_execute_signal`` path
4. Publishes execution confirmations back to the bus

Usage::

    subscriber = get_execution_subscriber()
    await subscriber.start()
    # Decisions published to bus are now auto-routed to execution
"""

from __future__ import annotations

import threading
import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.swarm.execution_subscriber")

_MAX_DECISION_AGE_S: float = 25.0  # Warn when routing decisions older than this


@dataclass
class ExecutionRecord:
    """Record of a decision→execution routing."""
    decision_id: str
    market_id: str
    action: str
    side: str
    size_contracts: int
    timestamp: float = field(default_factory=time.time)
    routed: bool = False
    route_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "decision_id": self.decision_id,
            "market_id": self.market_id,
            "action": self.action,
            "side": self.side,
            "size_contracts": self.size_contracts,
            "timestamp": self.timestamp,
            "routed": self.routed,
            "route_reason": self.route_reason,
        }


class ExecutionSubscriber:
    """Subscribes to Decision messages and routes to execution.

    Bridges the message bus architecture with the existing execution
    path, so agents can publish Decisions and have them auto-routed
    without the sequential loop needing to call execution directly.
    """

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._shutdown = asyncio.Event()
        self._queue: Optional[asyncio.Queue] = None
        self._history: Deque[ExecutionRecord] = deque(maxlen=500)
        self._decisions_received = 0
        self._decisions_routed = 0
        self._decisions_skipped = 0
        self._consecutive_failures = 0
        self._CB_FAILURE_THRESHOLD = 5

    async def start(self) -> None:
        """Subscribe to the bus and start processing decisions and orderbook events."""
        self._shutdown.clear()
        try:
            from core.streaming_bus import get_streaming_bus, EventChannel
            bus = get_streaming_bus()
            self._queue = await bus.subscribe(
                channels=[EventChannel.CONSENSUS, EventChannel.EXECUTION, EventChannel.MARKET_DATA]
            )
            self._task = asyncio.create_task(
                self._process_loop(), name="execution-subscriber"
            )
            logger.info("Execution subscriber started (listening on CONSENSUS, EXECUTION, MARKET_DATA)")
        except Exception as exc:
            logger.warning(f"Execution subscriber start failed: {exc}")

    async def stop(self) -> None:
        """Stop the subscriber."""
        self._shutdown.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._queue:
            try:
                from core.streaming_bus import get_streaming_bus
                bus = get_streaming_bus()
                await bus.unsubscribe(self._queue)
            except Exception as _unsub_exc:
                logger.debug("streaming bus unsubscribe failed: %s", _unsub_exc)
        logger.info(
            f"Execution subscriber stopped "
            f"(received={self._decisions_received}, "
            f"routed={self._decisions_routed}, "
            f"skipped={self._decisions_skipped})"
        )

    async def _process_loop(self) -> None:
        """Main event processing loop."""
        self._pending_decisions: Dict[str, Dict[str, Any]] = {}
        
        while not self._shutdown.is_set():
            try:
                if self._queue is None:
                    await asyncio.sleep(1)
                    continue

                try:
                    event = await asyncio.wait_for(
                        self._queue.get(), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    # Periodically check for stale pending decisions and execute them anyway
                    now = time.time()
                    expired = []
                    for mid, decision_data in self._pending_decisions.items():
                        if now > decision_data.get("_expiry", 0):
                            expired.append(mid)
                            
                    for mid in expired:
                        decision_data = self._pending_decisions.pop(mid)
                        logger.info(f"Execution timing window expired for {mid}, executing immediately")
                        await self._handle_decision(decision_data)
                    continue

                if event.event_type == "decision":
                    # Buffer the decision until we see a favorable orderbook state
                    data = event.data
                    market_id = data.get("market_id", "")
                    
                    # If already pending, just update it
                    if market_id not in self._pending_decisions:
                        # Set a timeout for how long we're willing to wait for a favorable book (e.g., 30s)
                        data["_expiry"] = time.time() + 30.0
                        data["_created_at"] = (
                            data.get("signal_timestamp") or time.time()
                        )
                        self._pending_decisions[market_id] = data
                        logger.info(f"Buffered decision for {market_id}, waiting for favorable execution timing...")
                    else:
                        data["_expiry"] = self._pending_decisions[market_id].get("_expiry", time.time() + 30.0)
                        if data.get("signal_timestamp") is not None:
                            data["_created_at"] = data["signal_timestamp"]
                        self._pending_decisions[market_id] = data
                    
                elif event.event_type == "ticker":
                    # An orderbook update came in via MARKET_DATA
                    data = event.data
                    market_id = data.get("symbol", "")
                    
                    if market_id in self._pending_decisions:
                        decision_data = self._pending_decisions[market_id]
                        
                        # Extract liquidity metrics
                        bid = data.get("bid", 0)
                        ask = data.get("ask", 0)
                        
                        # Calculate spread
                        if bid and ask:
                            spread = ask - bid
                            
                            # Execute if spread is tight (<= 3 cents) or if we've waited enough
                            if spread <= 3:
                                logger.info(f"Favorable execution timing found for {market_id} (spread {spread}c)")
                                await self._handle_decision(decision_data)
                                del self._pending_decisions[market_id]
                                
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Execution subscriber error: {exc}")
                await asyncio.sleep(1)

    async def _handle_decision(self, data: Dict[str, Any]) -> None:
        """Process a Decision message from the bus."""
        self._decisions_received += 1
        decision_id = data.get("decision_id", "unknown")
        market_id = data.get("market_id", "")
        action = data.get("action", "skip")
        side = data.get("side", "")
        size = data.get("size_contracts", 0)
        risk_approved = data.get("risk_approved", False)

        record = ExecutionRecord(
            decision_id=decision_id,
            market_id=market_id,
            action=action,
            side=side,
            size_contracts=size,
        )

        # Skip if action is skip/hold
        if action in ("skip", "hold", "no_action"):
            record.route_reason = f"Action is {action}"
            self._decisions_skipped += 1
            self._history.append(record)
            return

        # Skip if not risk-approved
        if not risk_approved:
            record.route_reason = "Not risk-approved"
            self._decisions_skipped += 1
            self._history.append(record)
            logger.debug(f"Decision {decision_id} skipped: not risk-approved")
            return

        # Skip if no size
        if size <= 0:
            record.route_reason = "Zero size"
            self._decisions_skipped += 1
            self._history.append(record)
            return

        # Staleness guard — discard decisions whose price signal is too old
        _ref_ts = data.get("signal_timestamp")
        if _ref_ts is None:
            _ref_ts = data.get("_created_at")
        if _ref_ts and (time.time() - _ref_ts) > _MAX_DECISION_AGE_S:
            age_s = time.time() - _ref_ts
            logger.warning(
                f"Decision {decision_id} discarded: stale by {age_s:.1f}s "
                f"(threshold={_MAX_DECISION_AGE_S}s) — agent will re-evaluate next cycle"
            )
            record.route_reason = f"stale_decision:{age_s:.1f}s"
            self._decisions_skipped += 1
            self._history.append(record)
            return

        # Circuit breaker guard — skip if consecutive failures have tripped the breaker
        try:
            from merid.circuit_breaker import get_circuit_breaker, CircuitState
            _cb = get_circuit_breaker(
                "kalshi:execution_subscriber",
                failure_threshold=self._CB_FAILURE_THRESHOLD,
                recovery_timeout=120.0,
            )
            if _cb.state == CircuitState.OPEN:
                record.route_reason = "circuit_breaker_open:kalshi:execution_subscriber"
                self._decisions_skipped += 1
                logger.warning(
                    f"Decision {decision_id} blocked — execution subscriber CB is OPEN "
                    f"(consecutive_failures={self._consecutive_failures})"
                )
                self._history.append(record)
                return
        except Exception:
            pass  # CB check failure is non-fatal — proceed to routing

        # Route to execution
        try:
            await self._route_to_execution(data)
            record.routed = True
            record.route_reason = "Routed to execution"
            self._decisions_routed += 1
            self._consecutive_failures = 0
            try:
                from merid.circuit_breaker import get_circuit_breaker
                get_circuit_breaker(
                    "kalshi:execution_subscriber",
                    failure_threshold=self._CB_FAILURE_THRESHOLD,
                    recovery_timeout=120.0,
                )._on_success()
            except Exception:
                pass
            logger.info(
                f"Decision {decision_id} routed: {action} {side} "
                f"{size} contracts on {market_id}"
            )
        except Exception as exc:
            self._consecutive_failures += 1
            record.route_reason = f"Routing failed: {exc}"
            self._decisions_skipped += 1
            logger.warning(
                f"Decision {decision_id} routing failed "
                f"(consecutive={self._consecutive_failures}): {exc}"
            )
            try:
                from merid.circuit_breaker import get_circuit_breaker
                get_circuit_breaker(
                    "kalshi:execution_subscriber",
                    failure_threshold=self._CB_FAILURE_THRESHOLD,
                    recovery_timeout=120.0,
                )._on_failure()
            except Exception:
                pass

        self._history.append(record)

    async def _route_to_execution(self, data: Dict[str, Any]) -> None:
        """Route an approved Decision to the execution path.

        Finds the appropriate agent from AgentGrid and triggers execution.
        Falls back to direct order placement if no matching agent found.
        """
        market_id = data.get("market_id", "")
        action = data.get("action", "")
        side = data.get("side", "yes")
        size = data.get("size_contracts", 0)
        limit_price = data.get("limit_price_cents", 0)

        # D1: VenueGate check — enforce allow-list and trading mode
        try:
            from merid.prediction.venue_gate import get_venue_gate
            gate = get_venue_gate()
            gate.check_venue("kalshi")
            gate.check_can_trade()
        except Exception as _vge:
            logger.warning(
                "ExecutionSubscriber: VenueGate blocked routing for %s: %s",
                market_id, _vge,
            )
            raise RuntimeError(f"VenueGate blocked: {_vge}") from _vge

        # D1: ExecutionGuard pre-trade check — kill switch, CQI, caps, promotion
        try:
            from merid.execution_guard import get_execution_guard
            guard = get_execution_guard()
            size_usd = float(size) * float(limit_price) / 100.0 if limit_price else float(size)
            verdict = guard.pre_trade_check(
                plan_id=data.get("decision_id", "sub_direct"),
                symbol=market_id,
                domain="prediction",
                size_usd=size_usd,
                direction="long" if "buy" in action else "short",
                venue="kalshi",
            )
            if not verdict.allowed:
                logger.warning(
                    "ExecutionSubscriber: ExecutionGuard blocked %s: %s",
                    market_id, verdict.reason,
                )
                raise RuntimeError(f"ExecutionGuard blocked: {verdict.reason}")
        except RuntimeError:
            raise
        except Exception as _ege:
            logger.warning(
                "ExecutionSubscriber: ExecutionGuard check failed for %s: %s — blocking",
                market_id, _ege,
            )
            raise RuntimeError(f"ExecutionGuard check failed: {_ege}") from _ege

        # Try to route through AgentGrid — match on the agent that owns this market_id
        try:
            from merid.prediction.agent_grid import get_agent_grid
            grid = get_agent_grid()
            if grid and grid.is_running:
                from merid.prediction.kalshi_tools import _kalshi_place_order
                kalshi_action = "buy" if "buy" in action else "sell"

                # First pass: find the agent whose active_tickers includes market_id
                owning_agent = None
                for agent in grid.agents:
                    if agent.state.enabled and market_id in agent.state.active_tickers:
                        owning_agent = agent
                        break

                # Second pass: fall back to the agent whose assets appear in market_id
                if owning_agent is None:
                    for agent in grid.agents:
                        if agent.state.enabled and any(
                            a.upper() in market_id.upper() for a in agent.config.assets
                        ):
                            owning_agent = agent
                            break

                if owning_agent is not None:
                    await _kalshi_place_order(
                        ticker=market_id,
                        side=side,
                        action=kalshi_action,
                        price_cents=limit_price,
                        count=size,
                        agent_name=owning_agent.agent_id,
                    )
                    return
                logger.warning(
                    "ExecutionSubscriber: no owning agent found for %s — falling back to direct placement",
                    market_id,
                )
        except Exception as exc:
            logger.warning("ExecutionSubscriber: AgentGrid routing failed for %s: %s — falling back to direct placement", market_id, exc)

        # Fallback: direct order placement
        try:
            from merid.prediction.kalshi_tools import _kalshi_place_order
            kalshi_action = "buy" if "buy" in action else "sell"
            await _kalshi_place_order(
                ticker=market_id,
                side=side,
                action=kalshi_action,
                price_cents=limit_price,
                count=size,
                agent_name="execution_subscriber",
            )
        except Exception as exc:
            raise RuntimeError(f"Direct order placement failed: {exc}") from exc

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "received": self._decisions_received,
            "routed": self._decisions_routed,
            "skipped": self._decisions_skipped,
            "history_size": len(self._history),
        }

    @property
    def history(self) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self._history]


# ── Singleton ────────────────────────────────────────────────────────────

_subscriber: Optional[ExecutionSubscriber] = None
_subscriber_lock = threading.Lock()


def get_execution_subscriber() -> ExecutionSubscriber:
    """Get or create the singleton ExecutionSubscriber."""
    global _subscriber
    if _subscriber is None:
        with _subscriber_lock:
            if _subscriber is None:
                _subscriber = ExecutionSubscriber()
    return _subscriber


async def reset_execution_subscriber() -> None:
    """F1: Stop and discard the singleton so a fresh instance is created next call.

    Must be awaited to ensure the old subscriber's asyncio.Task is cancelled
    before the reference is dropped — prevents ghost subscribers accumulating
    in the StreamingBus channel sets across test runs or hot-reloads.
    """
    global _subscriber
    with _subscriber_lock:
        old = _subscriber
        _subscriber = None
    if old is not None:
        try:
            await old.stop()
        except Exception as _exc:
            logger.debug("reset_execution_subscriber: stop error (ignored): %s", _exc)
