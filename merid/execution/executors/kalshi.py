"""Kalshi prediction market executor for MERID.

Delegates all HTTP, auth (RSA-PSS), retry, and circuit-breaker logic to
KalshiVenueClient — the single canonical Kalshi client implementation.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from merid.execution.base import Quote, Position, TradeResult, TradeSideLiteral
from utils.logger import get_logger

logger = get_logger("merid.execution.executors.kalshi")


def _get_venue_client():
    """Lazy-load KalshiVenueClient with settings-based config."""
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
    return KalshiVenueClient(config)


class KalshiExecutor:
    """Kalshi prediction market executor.

    Thin adapter that bridges MERID's TradeExecutor interface to the
    canonical KalshiVenueClient (RSA-PSS auth, circuit breaker, retry).
    """

    venue = "kalshi"

    def __init__(self) -> None:
        self._client = None

    def _get_client(self):
        """Return shared venue client, creating on first call."""
        if self._client is None:
            self._client = _get_venue_client()
        return self._client

    # ------------------------------------------------------------------
    # TradeExecutor interface
    # ------------------------------------------------------------------

    async def get_quote(self, symbol: str, side: TradeSideLiteral, amount: float) -> Quote:
        """Get best bid/ask for a Kalshi market outcome."""
        client = self._get_client()
        result = await client._request_with_resilience(
            "GET",
            f"/markets/{symbol}/orderbook",
            operation_name="get_quote",
        )
        if not result.success:
            raise RuntimeError(f"Kalshi quote failed: {result.error}")
        data = result.data
        yes_bids = data.get("orderbook", {}).get("yes", [])
        price = float(yes_bids[0][0]) / 100.0 if yes_bids else 0.5
        return Quote(
            symbol=symbol,
            side=side,
            price=price,
            venue=self.venue,
            size=amount,
            latency_ms=result.latency_ms,
            metadata={"raw": data},
        )

    async def execute_trade(
        self,
        symbol: str,
        side: TradeSideLiteral,
        amount: float,
        *,
        order_type: str = "market",
        price: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TradeResult:
        """Submit an order to Kalshi via the canonical venue client."""
        meta = metadata or {}

        # Kill switch hard gate — fail-CLOSED on any error
        try:
            from merid.risk.kill_switches import risk_controller
            if not risk_controller.can_trade():
                reason = risk_controller.get_kill_reason() or "kill_switch_active"
                return TradeResult(
                    success=False, venue=self.venue, symbol=symbol,
                    side=side, size=amount, price=price or 0.0,
                    error=f"Trading halted: {reason}", metadata={},
                )
        except Exception as exc:
            logger.error("Kill-switch unavailable — blocking order (fail-closed): %s", exc)
            return TradeResult(
                success=False, venue=self.venue, symbol=symbol,
                side=side, size=amount, price=price or 0.0,
                error=f"Risk controller unavailable: {exc}", metadata={},
            )

        # VenueGate — block real orders in SIM/PAPER/MOCK mode (fail-CLOSED)
        try:
            from merid.prediction.venue_gate import get_venue_gate
            _gate = get_venue_gate()
            if _gate.should_simulate_fill():
                return TradeResult(
                    success=False, venue=self.venue, symbol=symbol,
                    side=side, size=amount, price=price or 0.0,
                    error=f"VenueGate blocked: mode={_gate.mode.value} (paper/sim)",
                    metadata={"simulated": True},
                )
        except Exception as _vge:
            logger.error("VenueGate unavailable — blocking order (fail-closed): %s", _vge)
            return TradeResult(
                success=False, venue=self.venue, symbol=symbol,
                side=side, size=amount, price=price or 0.0,
                error=f"VenueGate unavailable: {_vge}", metadata={},
            )

        # KalshiRiskManager — position limits, category caps, drawdown, rate limiting (fail-CLOSED)
        try:
            from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
            _risk = get_kalshi_risk()
            price_cents = int(round(price * 100)) if price and price <= 1.0 else int(price or 50)
            _allowed, _reason = _risk.check_order(
                ticker=symbol, category=None,
                contracts=int(amount), price_cents=price_cents,
            )
            if not _allowed:
                return TradeResult(
                    success=False, venue=self.venue, symbol=symbol,
                    side=side, size=amount, price=price or 0.0,
                    error=f"Risk check blocked: {_reason}", metadata={},
                )
        except Exception as _rke:
            logger.error("KalshiRiskManager unavailable — blocking order (fail-closed): %s", _rke)
            return TradeResult(
                success=False, venue=self.venue, symbol=symbol,
                side=side, size=amount, price=price or 0.0,
                error=f"KalshiRiskManager unavailable: {_rke}", metadata={},
            )

        # DeploymentController — block HALTED/PAPER agents
        _agent_name = meta.get("agent_name", "")
        if _agent_name:
            try:
                from merid.event_venues.kalshi.deployment import get_deployment_controller, AgentMode
                _dep = get_deployment_controller()._agents.get(_agent_name)
                if _dep and _dep.mode in (AgentMode.HALTED, AgentMode.PAPER):
                    return TradeResult(
                        success=False, venue=self.venue, symbol=symbol,
                        side=side, size=amount, price=price or 0.0,
                        error=f"Agent {_agent_name} is {_dep.mode.value} — no live orders",
                        metadata={},
                    )
            except Exception as _dce:
                logger.error("DeploymentController unavailable — blocking order (fail-closed): %s", _dce)
                return TradeResult(
                    success=False, venue=self.venue, symbol=symbol,
                    side=side, size=amount, price=price or 0.0,
                    error=f"DeploymentController unavailable: {_dce}", metadata={},
                )

        client = self._get_client()

        # Kalshi v2 order payload
        # side here is "buy"/"sell" from MERID; Kalshi uses action + side(yes/no)
        action = side  # "buy" or "sell"
        outcome_side = meta.get("outcome", "yes")  # "yes" or "no"
        client_order_id = meta.get("client_order_id") or f"merid-{uuid.uuid4().hex[:12]}"

        payload: Dict[str, Any] = {
            "ticker": symbol,
            "action": action,
            "side": outcome_side,
            "type": order_type,
            "count": int(amount),
            "client_order_id": client_order_id,
        }
        if order_type == "limit" and price is not None:
            # Kalshi prices are integers 1-99 (cents per dollar)
            payload["yes_price"] = int(round(price * 100)) if price <= 1.0 else int(price)

        result = await client._request_with_resilience(
            "POST",
            "/portfolio/orders",
            json_data=payload,
            operation_name="execute_trade",
        )

        if not result.success:
            return TradeResult(
                success=False,
                venue=self.venue,
                symbol=symbol,
                side=side,
                size=amount,
                price=price or 0.0,
                error=f"Kalshi order failed: {result.error}",
                metadata={"latency_ms": result.latency_ms},
            )

        order_data = result.data.get("order", result.data)
        executed_price_raw = order_data.get("yes_price") or order_data.get("no_price") or 0
        executed_price = float(executed_price_raw) / 100.0

        return TradeResult(
            success=True,
            venue=self.venue,
            symbol=symbol,
            side=side,
            size=amount,
            price=executed_price,
            tx_id=order_data.get("order_id"),
            metadata={
                "order_id": order_data.get("order_id"),
                "status": order_data.get("status"),
                "client_order_id": client_order_id,
                "latency_ms": result.latency_ms,
            },
        )

    async def get_positions(self) -> List[Position]:
        """Fetch open positions from Kalshi."""
        client = self._get_client()
        result = await client._request_with_resilience(
            "GET",
            "/portfolio/positions",
            operation_name="get_positions",
        )
        if not result.success:
            logger.warning(f"[kalshi] get_positions failed: {result.error}")
            return []

        positions = []
        for pos in result.data.get("market_positions", []):
            raw_count = pos.get("position", 0)
            if raw_count == 0:
                continue
            total_cost = float(pos.get("total_traded", 0)) / 100.0
            entry_price = total_cost / abs(raw_count) if raw_count else 0.0
            positions.append(
                Position(
                    symbol=pos["ticker"],
                    size=float(raw_count),
                    entry_price=entry_price,
                    pnl=float(pos.get("realized_pnl", 0)) / 100.0,
                    venue=self.venue,
                    metadata={
                        "ticker": pos["ticker"],
                        "resting_orders_count": pos.get("resting_orders_count", 0),
                    },
                )
            )
        return positions

    # ------------------------------------------------------------------
    # Extended Kalshi-specific methods
    # ------------------------------------------------------------------

    async def authenticate(self) -> bool:
        """Test authentication with Kalshi API."""
        try:
            client = self._get_client()
            result = await client._request_with_resilience(
                "GET",
                "/exchange/status",
                operation_name="authenticate",
            )
            return result.success
        except Exception as exc:
            logger.warning(f"[kalshi] authenticate check failed: {exc}")
            return False

    async def get_balance(self) -> Dict[str, Any]:
        """Fetch account balance from Kalshi.

        Returns:
            Balance dict with all values in USD dollars (not cents).
            Fields: usd_dollars, locked_dollars, available_dollars
        """
        client = self._get_client()
        result = await client._request_with_resilience(
            "GET",
            "/portfolio/balance",
            operation_name="get_balance",
        )
        if not result.success:
            raise RuntimeError(f"Kalshi balance fetch failed: {result.error}")
        data = result.data
        balance_cents = data.get("balance", 0)
        locked_cents = data.get("payout", 0)
        # Return all values in dollars for consistency
        return {
            "usd_dollars": balance_cents / 100.0,
            "locked_dollars": locked_cents / 100.0,
            "available_dollars": (balance_cents - locked_cents) / 100.0,
        }

    async def get_orders(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch orders from Kalshi."""
        client = self._get_client()
        params: Dict[str, Any] = {}
        if status:
            params["status"] = status
        result = await client._request_with_resilience(
            "GET",
            "/portfolio/orders",
            params=params,
            operation_name="get_orders",
        )
        if not result.success:
            logger.warning(f"[kalshi] get_orders failed: {result.error}")
            return []
        return result.data.get("orders", [])

    async def get_fills(self) -> List[Dict[str, Any]]:
        """Fetch recent fills/trades from Kalshi."""
        client = self._get_client()
        result = await client._request_with_resilience(
            "GET",
            "/portfolio/fills",
            operation_name="get_fills",
        )
        if not result.success:
            logger.warning(f"[kalshi] get_fills failed: {result.error}")
            return []
        return result.data.get("fills", [])

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        client = self._get_client()
        result = await client._request_with_resilience(
            "DELETE",
            f"/portfolio/orders/{order_id}",
            operation_name="cancel_order",
        )
        if not result.success:
            logger.warning(f"[kalshi] cancel_order {order_id} failed: {result.error}")
            return False
        return True
