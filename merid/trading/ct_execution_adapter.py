"""CT Execution Adapter — Shadow Mode Router Integration.

Converts KalshiContinuousTrader order dicts to OrderIntent and routes through
the canonical order_router for parity validation.

Phase 1 (Shadow Mode): CT executes via direct HTTP, adapter calls router in
paper/mock mode for comparison logging.

Phase 2 (Canary): Gradually flip CT to use adapter for live execution.

Phase 3 (Removal): Delete direct HTTP path, CT becomes pure strategy driver.
"""

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set, Tuple

from utils.logger import get_logger

logger = get_logger("merid.trading.ct_execution_adapter")

# Shadow mode parity logging threshold (percent difference to warn)
_SHADOW_PARITY_THRESHOLD_PCT = float(os.getenv("CT_SHADOW_PARITY_THRESHOLD_PCT", "5.0"))


@dataclass
class ParityLogEntry:
    """Record of HTTP vs router execution comparison."""
    ticker: str
    side: str
    count: int
    price_cents: int
    http_status: str
    router_status: str
    http_latency_ms: float
    router_latency_ms: float
    fill_count_http: int
    fill_count_router: int
    parity_match: bool
    ts: float


class CTExecutionAdapter:
    """Adapter that bridges CT's order dicts to the canonical router.

    Usage (Shadow Mode):
        adapter = CTExecutionAdapter()
        # CT executes via direct HTTP as usual
        http_result = self._post("/portfolio/orders", order_data)
        # Shadow: also call adapter
        router_result = await adapter.execute_shadow(order_data)
        # Parity is logged automatically

    Usage (Live Mode — Phase 2+):
        result = await adapter.execute_live(order_data)
        # Returns OrderResult from router, CT uses this instead of HTTP
    """

    def __init__(self):
        self._shadow_mode = os.getenv("CT_ADAPTER_MODE", "shadow").lower() == "shadow"
        self._parity_logs: list = []
        self._shadow_calls = 0
        self._parity_matches = 0
        self._parity_mismatches = 0
        
        # BUG-3 FIX: Pending orders tracking to prevent race conditions
        # Track tickers with in-flight orders to prevent duplicate submissions
        self._pending_orders: Dict[str, Dict[str, Any]] = {}  # ticker -> order_info
        self._pending_lock = threading.Lock()

    def _order_dict_to_intent(
        self,
        order_data: Dict[str, Any],
        effective_equity_usd: Optional[float] = None,
    ) -> "OrderIntent":
        """Convert CT order dict to canonical OrderIntent.

        Args:
            order_data: CT order dict with ticker, side, count, price, etc.
            effective_equity_usd: Optional capped equity for portfolio risk limits
        """
        from merid.event_venues.kalshi.order_router import OrderIntent
        from merid.event_venues.kalshi.decision_trace import new_decision_trace_id

        # Extract fields from CT order_data
        ticker = order_data.get("ticker", "")
        side = order_data.get("side", "yes")
        action = order_data.get("action", "buy")
        count = int(order_data.get("count", 1))
        price_cents = int(order_data.get("yes_price", order_data.get("no_price", 50)))
        client_order_id = order_data.get("client_order_id")
        group_id = order_data.get("group_id")

        # CT always uses limit orders
        order_type = "limit"
        time_in_force = "gtc"

        # Compute default TP/SL for 15m crypto entry orders if not provided
        take_profit_price_cents = None
        take_profit_r_multiple = None
        stop_loss_price_cents = None
        
        if action == "buy" and ticker.startswith(("KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M")):
            try:
                from merid.prediction.dynamic_takeprofit import DynamicTakeProfitEngine
                engine = DynamicTakeProfitEngine()
                
                # Default SL: 5 cents below entry (conservative)
                stop_loss_price_cents = max(1, price_cents - 5)
                
                # Compute dynamic TP with default confidence
                tp_plan = engine.compute_tp(
                    entry_price=price_cents / 100.0,
                    stop_price=stop_loss_price_cents / 100.0,
                    direction="LONG" if side == "yes" else "SHORT",
                    confidence=0.5,  # Default medium confidence
                )
                
                take_profit_r_multiple = tp_plan.tp_r_multiple
                logger.info(
                    "[CT-ADAPTER-TP] Computed default TP for %s: R=%.2f",
                    ticker, tp_plan.tp_r_multiple
                )
            except Exception as tp_exc:
                logger.warning("[CT-ADAPTER-TP] Failed to compute default TP: %s", tp_exc)
                # Fallback to 1R
                take_profit_r_multiple = 1.0
                stop_loss_price_cents = max(1, price_cents - 5)

        # Build canonical OrderIntent
        intent = OrderIntent(
            ticker=ticker,
            side=side,
            action=action,
            price_cents=price_cents,
            count=count,
            mode=None,  # Use process-wide mode (paper/live via venue_gate)
            order_type=order_type,
            time_in_force=time_in_force,
            source="ct_execution_adapter",
            client_tag=client_order_id,
            group_id=group_id,
            decision_trace_id=new_decision_trace_id("ct_adapter"),
            sentiment_driven=False,
            agent_id="kalshi_ct",
            snapshot_ts=time.time(),  # Current snapshot
            effective_equity_usd=effective_equity_usd,
            take_profit_price_cents=take_profit_price_cents,
            take_profit_r_multiple=take_profit_r_multiple,
            stop_loss_price_cents=stop_loss_price_cents,
        )
        return intent

    async def execute_shadow(
        self,
        order_data: Dict[str, Any],
        http_result: Optional[Dict[str, Any]] = None,
    ) -> Optional["OrderResult"]:
        """Execute in shadow mode: call router for comparison, don't affect live state.

        Args:
            order_data: CT's order dict (as sent to HTTP)
            http_result: Optional result from the HTTP call for parity comparison

        Returns:
            OrderResult from router (for logging), or None if router unavailable
        """
        from merid.event_venues.kalshi.order_router import route_order_async

        t0 = time.monotonic()

        try:
            intent = self._order_dict_to_intent(order_data)
        except Exception as exc:
            logger.warning("[CT-ADAPTER] Failed to build OrderIntent: %s", exc)
            return None

        try:
            # Call router in paper/mock mode (shadow only)
            result = await route_order_async(intent)
            latency_ms = (time.monotonic() - t0) * 1000

            self._shadow_calls += 1

            # Log parity comparison if HTTP result provided
            if http_result is not None:
                self._log_parity(order_data, http_result, result, latency_ms)

            logger.info(
                "[CT-ADAPTER] shadow_call | ticker=%s | status=%s | latency=%.2fms | calls=%d",
                intent.ticker,
                result.status,
                latency_ms,
                self._shadow_calls,
            )
            return result

        except Exception as exc:
            logger.warning("[CT-ADAPTER] Shadow router call failed: %s", exc)
            return None

    def _log_parity(
        self,
        order_data: Dict[str, Any],
        http_result: Dict[str, Any],
        router_result: "OrderResult",
        router_latency_ms: float,
    ) -> None:
        """Log parity comparison between HTTP and router execution."""
        ticker = order_data.get("ticker", "")
        side = order_data.get("side", "")
        count = int(order_data.get("count", 0))
        price_cents = int(order_data.get("yes_price", order_data.get("no_price", 0)))

        # Extract HTTP status
        http_status = "unknown"
        http_latency_ms = 0.0
        http_filled = 0
        if isinstance(http_result, dict):
            http_status = http_result.get("status", http_result.get("order_status", "unknown"))
            http_filled = int(http_result.get("filled_count", 0))

        # Router status
        router_status = router_result.status
        router_filled = 0
        if router_result.fill:
            router_filled = int(router_result.fill.get("count", 0))

        # Parity check: statuses should match (both filled or both rejected)
        # Note: In shadow mode, router is in paper/mock so exact fills may differ
        parity_match = ("filled" in http_status.lower()) == ("filled" in router_status.lower())

        if parity_match:
            self._parity_matches += 1
        else:
            self._parity_mismatches += 1
            logger.warning(
                "[CT-ADAPTER] PARITY_MISMATCH | ticker=%s | http=%s | router=%s | "
                "http_filled=%d | router_filled=%d",
                ticker, http_status, router_status, http_filled, router_filled,
            )

        # Build parity entry
        entry = ParityLogEntry(
            ticker=ticker,
            side=side,
            count=count,
            price_cents=price_cents,
            http_status=http_status,
            router_status=router_status,
            http_latency_ms=http_latency_ms,
            router_latency_ms=router_latency_ms,
            fill_count_http=http_filled,
            fill_count_router=router_filled,
            parity_match=parity_match,
            ts=time.time(),
        )
        self._parity_logs.append(entry)

        # Emit structured parity log
        logger.info(
            "[CT-ADAPTER] parity | ticker=%s | match=%s | http_status=%s | "
            "router_status=%s | http_filled=%d | router_filled=%d | "
            "matches=%d | mismatches=%d",
            ticker,
            parity_match,
            http_status,
            router_status,
            http_filled,
            router_filled,
            self._parity_matches,
            self._parity_mismatches,
        )

    async def execute_live(
        self,
        order_data: Dict[str, Any],
        effective_equity_usd: Optional[float] = None,
    ) -> "OrderResult":
        """Submit signal to trading_agent for execution (Single Executor Principle).

        SIGNAL-ONLY AGENT: CT adapter submits signals via SignalRouter.
        trading_agent is the SOLE EXECUTOR that calls route_order_async.
        This ensures risk guards, caller whitelist, and audit trail are enforced.

        Args:
            order_data: CT order dict with ticker, side, count, price, etc.
            effective_equity_usd: Optional capped equity for portfolio risk limits
        """
        from merid.event_venues.kalshi import submit_signal
        from merid.event_venues.kalshi.order_router import OrderResult

        ticker = order_data.get("ticker", "")
        
        # BUG-3 FIX: Check for pending orders on the same ticker
        # to prevent race conditions and duplicate submissions
        with self._pending_lock:
            if ticker in self._pending_orders:
                pending = self._pending_orders[ticker]
                logger.warning(
                    "[CT-ADAPTER] Rejecting order for %s: Pending order already in flight "
                    "(submitted %s ago)",
                    ticker, pending.get("time_ago", "unknown")
                )
                return OrderResult(
                    status="rejected",
                    reason=f"pending_order_conflict:ticker={ticker}",
                    latency_ms=0.0,
                )
            # Track this order as pending
            self._pending_orders[ticker] = {
                "action": order_data.get("action", "buy"),
                "side": order_data.get("side", "yes"),
                "count": int(order_data.get("count", 1)),
                "submitted_at": time.time(),
            }
        
        try:
            side = order_data.get("side", "yes")
            action = order_data.get("action", "buy")
            count = int(order_data.get("count", 1))
            price_cents = int(order_data.get("yes_price", order_data.get("no_price", 50)))

            signal = submit_signal(
            agent_id="kalshi_continuous_trader",
            agent_type="ct_execution_adapter",
            market_id=ticker,
            action=action,
            side=side,
            size=count,
            price_cents=price_cents,
            confidence=0.7,
            reasoning=f"Continuous Trader signal: {action} {side} on {ticker}",
            metadata={
                "effective_equity_usd": effective_equity_usd,
                "client_order_id": order_data.get("client_order_id"),
                "group_id": order_data.get("group_id"),
            },
            origin_agent="kalshi_continuous_trader",
            risk_bucket="ct_automated",
        )

            logger.info(
                "[CT-ADAPTER] signal_submitted | ticker=%s | signal_id=%s | side=%s | count=%d",
                ticker, signal.signal_id, side, count,
            )

            # Return a synthetic OrderResult indicating signal submission
            # trading_agent will receive the signal and execute via route_order_async
            return OrderResult(
                status="submitted_signal",
                fill={
                    "signal_id": signal.signal_id,
                    "ticker": ticker,
                    "side": side,
                    "count": count,
                    "price_cents": price_cents,
                    "action": action,
                },
                latency_ms=0.0,
                reason="Signal submitted to trading_agent for execution",
            )
        finally:
            # BUG-3 FIX: Clean up pending order tracking
            with self._pending_lock:
                if ticker in self._pending_orders:
                    del self._pending_orders[ticker]

    def get_stats(self) -> Dict[str, Any]:
        """Return adapter statistics for monitoring."""
        total = self._parity_matches + self._parity_mismatches
        parity_rate = self._parity_matches / total if total > 0 else 0.0

        return {
            "shadow_calls": self._shadow_calls,
            "parity_matches": self._parity_matches,
            "parity_mismatches": self._parity_mismatches,
            "parity_rate": parity_rate,
            "mode": "shadow" if self._shadow_mode else "live",
        }


# Singleton accessor
_ct_adapter: Optional[CTExecutionAdapter] = None


def get_ct_execution_adapter() -> CTExecutionAdapter:
    """Get singleton CTExecutionAdapter instance."""
    global _ct_adapter
    if _ct_adapter is None:
        _ct_adapter = CTExecutionAdapter()
    return _ct_adapter
