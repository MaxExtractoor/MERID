"""UnifiedVenueAdapter ABC and AdapterRegistry.

Every venue (Kalshi, Binance, Coinbase, Kraken, OKX, Alpaca, IBKR)
implements this interface.  The TradeRouter looks up adapters by venue
name and dispatches proposals.

NOTE (2026-08-18): Kalshi submissions are routed through the canonical
order router (``merid.event_venues.kalshi.order_router.route_order_async``)
so that all orders pass identity, circuit-breaker, canonical-intent, and
ExecutionRiskFirewall gates before any venue client is invoked.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Dict, List, Optional, Any
import threading
import os

from merid.pipeline.proposal import ExecutionResult, TradeProposal, OrderSide, OrderType
from merid.event_venues.kalshi.client import KalshiVenueClient, get_kalshi_client
from merid.event_venues.kalshi.models import KalshiConfig
from merid.event_venues.base import VenueOrder, MarketFilter
# SEV-1 FIX: Removed deprecated GlobalExecutionGuard import
# The unified pipeline system is not used by the 15m Kalshi production stack
# which uses loop_15m.py directly with the risk envelope system

from utils.logger import get_logger

logger = get_logger("merid.pipeline.adapter")


class UnifiedVenueAdapter(ABC):
    """Abstract base for all venue adapters in the unified pipeline."""

    @property
    @abstractmethod
    def venue_name(self) -> str:
        """Canonical venue identifier (e.g. 'kalshi', 'binance')."""

    @property
    @abstractmethod
    def domain(self) -> str:
        """Market domain: 'prediction', 'crypto', 'equity'."""

    @property
    @abstractmethod
    def supports_trading(self) -> bool:
        """Whether this adapter can submit live orders."""

    # ── Market data ──────────────────────────────────────────────────
    @abstractmethod
    async def get_symbols(self) -> List[str]:
        """Return list of tradeable native symbols."""

    @abstractmethod
    async def get_quote(self, native_symbol: str) -> Optional[Dict]:
        """Return best bid/ask/last for a symbol.

        Returns dict with keys: bid, ask, last, volume (all Decimal or None).
        """

    @abstractmethod
    async def get_order_book(self, native_symbol: str, depth: int = 5) -> Optional[Dict]:
        """Return order book levels.

        Returns dict with keys: bids [(price, qty)], asks [(price, qty)].
        """

    # ── Trading ──────────────────────────────────────────────────────
    @abstractmethod
    async def submit_order(self, proposal: TradeProposal) -> ExecutionResult:
        """Submit an order to the venue.  Returns ExecutionResult."""

    @abstractmethod
    async def cancel_order(self, venue_order_id: str, native_symbol: str = "") -> bool:
        """Cancel an open order.  Returns True on success."""

    # ── Account ──────────────────────────────────────────────────────
    @abstractmethod
    async def get_balances(self) -> Dict[str, Decimal]:
        """Return balances keyed by asset (e.g. {'USD': Decimal('5000')})."""

    @abstractmethod
    async def get_positions(self) -> List[Dict]:
        """Return open positions as list of dicts.

        Each dict: symbol, qty, entry_price, unrealized_pnl, venue.
        """

    # ── Health ───────────────────────────────────────────────────────
    async def health_check(self) -> Dict:
        """Return adapter health status."""
        return {
            "venue": self.venue_name,
            "domain": self.domain,
            "supports_trading": self.supports_trading,
            "status": "ok",
        }


# ── Registry ─────────────────────────────────────────────────────────

class KalshiUnifiedAdapter(UnifiedVenueAdapter):
    """Kalshi implementation of the UnifiedVenueAdapter interface.
    
    This connects the resilient Kalshi client to the modern trade pipeline.
    """
    
    def __init__(self, paper: bool = True):
        # Use the singleton KalshiVenueClient so that the canonical order router
        # and the adapter share one connection and one identity space.
        self._client = get_kalshi_client()
        self._paper = paper
        self._connected = False

    @property
    def venue_name(self) -> str:
        return "kalshi"

    @property
    def domain(self) -> str:
        return "prediction"

    @property
    def supports_trading(self) -> bool:
        return True

    async def connect(self) -> bool:
        try:
            await self._client.connect()
            self._connected = True
            return True
        except Exception as _ce:
            logger.warning("KalshiPipelineAdapter.connect failed: %s", _ce)
            return False

    async def disconnect(self) -> bool:
        await self._client.close()
        self._connected = False
        return True

    async def get_symbols(self) -> List[str]:
        res = await self._client.list_markets_result(MarketFilter(active_only=True))
        if not res.success:
            return []
        return [m.market_id for m in res.data]

    async def get_quote(self, native_symbol: str) -> Optional[Dict]:
        res = await self._client.get_market_result(native_symbol)
        if not res.success or not res.data:
            return None
        m = res.data
        yes_outcome = next((o for o in m.outcomes if o.outcome_id == "yes"), None)
        if not yes_outcome:
            return None
        return {
            "bid": yes_outcome.best_bid,
            "ask": yes_outcome.best_ask,
            "last": yes_outcome.price,
            "volume": m.volume,
        }

    async def get_order_book(self, native_symbol: str, depth: int = 5) -> Optional[Dict]:
        res = await self._client.get_orderbook_result(native_symbol)
        if not res.success or not res.data:
            return None
        return {
            "bids": [(p, s) for p, s in res.data.bids[:depth]],
            "asks": [(p, s) for p, s in res.data.asks[:depth]],
        }

    async def submit_order(self, proposal: TradeProposal) -> ExecutionResult:
        """Submit a proposal to Kalshi through the canonical order router.

        The adapter does NOT call the venue client directly. It builds a canonical
        OrderIntent so that identity, circuit-breaker, canonical-intent, and
        ExecutionRiskFirewall gates run before any outbound API call.
        """
        from merid.event_venues.kalshi.order_router import (
            OrderIntent,
            OrderResult,
            route_order_async,
        )

        # ── HARD GATE: Kill switch (mirrors ExecutionRouter gate) ────────
        try:
            from merid.risk.kill_switches import risk_controller
            if not risk_controller.can_trade():
                reason = risk_controller.get_kill_reason()
                logger.warning(
                    f"[kalshi-adapter] Order blocked by kill switch: {reason} "
                    f"(proposal={proposal.proposal_id})"
                )
                return ExecutionResult(
                    proposal_id=proposal.proposal_id,
                    venue=self.venue_name,
                    status="error",
                    error=f"Trading halted: {reason}",
                )
        except ImportError:
            pass  # risk_controller not available in test environments

        # UNIFIED GUARD CHECK — 3% cycle / 8% total bankroll cap enforcement
        # This blocks orders that would exceed the global portfolio limit
        _guard = get_global_execution_guard()
        _price_cents = int((proposal.price or 50) * 100)  # Default to 50 cents if no price
        _allowed, _reason = _guard.check_order(
            ticker=proposal.native_symbol or proposal.instrument_id,
            contracts=int(proposal.qty),
            price_cents=_price_cents,
            source="pipeline_adapter",
            asset=proposal.metadata.get("asset"),
        )
        if not _allowed:
            logger.error(
                "[PIPELINE_ADAPTER_BLOCKED] GlobalExecutionGuard rejected order: %s | proposal=%s",
                _reason, proposal.proposal_id
            )
            return ExecutionResult(
                proposal_id=proposal.proposal_id,
                venue=self.venue_name,
                status="error",
                error=f"Global guard blocked: {_reason}",
            )

        # Canonical order-intent construction.
        count = int(proposal.qty)
        if count <= 0:
            logger.error(
                "[PIPELINE_ADAPTER_BLOCKED] Non-positive order size for proposal=%s qty=%s",
                proposal.proposal_id, proposal.qty,
            )
            return ExecutionResult(
                proposal_id=proposal.proposal_id,
                venue=self.venue_name,
                status="error",
                error=f"Non-positive order size: {proposal.qty}",
            )

        if proposal.order_type == OrderType.MARKET:
            _order_type = "market"
            _time_in_force = "ioc"
        elif proposal.order_type == OrderType.IOC:
            _order_type = "limit"
            _time_in_force = "ioc"
        elif proposal.order_type == OrderType.FOK:
            _order_type = "limit"
            _time_in_force = "fok"
        else:
            _order_type = "limit"
            _time_in_force = "gtc"

        intent = OrderIntent(
            ticker=proposal.native_symbol or proposal.instrument_id,
            side=proposal.metadata.get("outcome_id", "yes"),
            action="buy" if proposal.side == OrderSide.BUY else "sell",
            price_cents=_price_cents,
            count=count,
            count_fp=proposal.qty,
            order_type=_order_type,
            time_in_force=_time_in_force,
            source="pipeline_adapter",
            agent_id=proposal.agent_id,
            rationale=(proposal.rationale or f"pipeline proposal {proposal.proposal_id}")[:200],
            client_tag=proposal.proposal_id,
            parent_entry_fill_id=proposal.metadata.get("parent_entry_fill_id"),
            metadata=dict(proposal.metadata),
        )

        result: OrderResult = await route_order_async(intent)

        if not result:
            return ExecutionResult(
                proposal_id=proposal.proposal_id,
                venue=self.venue_name,
                status="error",
                error="route_order_async returned no result",
            )

        if result.request_completed:
            if result.has_execution:
                status = "filled"
            elif not result.is_terminal:
                status = "submitted"
            else:
                status = "rejected"
        else:
            status = "error"

        filled_qty = Decimal(result.executed_quantity_cc) / Decimal("100")
        avg_price = proposal.price or Decimal("0")
        fee = Decimal(0)
        if result.has_execution and result.fill:
            _fill_price_cents = result.fill.get("price_cents")
            if _fill_price_cents is not None:
                avg_price = Decimal(_fill_price_cents) / Decimal(100)
            _fee_cents = result.fill.get("fee_cents") or 0
            fee = Decimal(_fee_cents) / Decimal(100)

        return ExecutionResult(
            proposal_id=proposal.proposal_id,
            venue=self.venue_name,
            venue_order_id=result.order_id,
            status=status,
            error=result.reason or result.error,
            filled_qty=filled_qty,
            avg_price=avg_price,
            fee=fee,
        )

    async def cancel_order(self, venue_order_id: str, native_symbol: str = "") -> bool:
        res = await self._client.cancel_order_result(venue_order_id, native_symbol)
        return res.success

    async def get_balances(self) -> Dict[str, Decimal]:
        res = await self._client.get_balance_result()
        if not res.success:
            return {}
        return res.data

    async def get_positions(self) -> List[Dict]:
        res = await self._client.get_positions_result()
        if not res.success:
            return []
        return [
            {
                "symbol": p.market_id,
                "qty": p.size,
                "entry_price": p.average_entry_price,
                "unrealized_pnl": p.unrealized_pnl or Decimal("0"),
                "venue": "kalshi",
            }
            for p in res.data
        ]

    async def health_check(self) -> Dict:
        status = self._client.get_circuit_status()
        return {
            "venue": self.venue_name,
            "domain": self.domain,
            "supports_trading": self.supports_trading,
            "status": "ok" if status.get("state") == "closed" else "degraded",
            "connected": self._connected,
            "circuit": status,
        }


class AdapterRegistry:
    """Central registry of all venue adapters."""

    def __init__(self) -> None:
        self._adapters: Dict[str, UnifiedVenueAdapter] = {}
        # Register default adapters
        self.register(KalshiUnifiedAdapter())

    def register(self, adapter: UnifiedVenueAdapter) -> None:
        self._adapters[adapter.venue_name] = adapter
        logger.info(f"Registered adapter: {adapter.venue_name} ({adapter.domain})")

    def get(self, venue: str) -> Optional[UnifiedVenueAdapter]:
        return self._adapters.get(venue)

    def list_venues(self) -> List[str]:
        return list(self._adapters.keys())

    def by_domain(self, domain: str) -> List[UnifiedVenueAdapter]:
        return [a for a in self._adapters.values() if a.domain == domain]

    def all(self) -> Dict[str, UnifiedVenueAdapter]:
        return dict(self._adapters)

    def summary(self) -> List[Dict]:
        return [
            {
                "venue": a.venue_name,
                "domain": a.domain,
                "supports_trading": a.supports_trading,
            }
            for a in self._adapters.values()
        ]


# Module-level singleton
_registry: Optional[AdapterRegistry] = None
_registry_lock = threading.Lock()


def get_adapter_registry() -> AdapterRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = AdapterRegistry()
    return _registry


