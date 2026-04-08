"""UnifiedVenueAdapter ABC and AdapterRegistry.

Every venue (Kalshi, Binance, Coinbase, Kraken, OKX, Alpaca, IBKR)
implements this interface.  The TradeRouter looks up adapters by venue
name and dispatches proposals.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Dict, List, Optional, Any
import os

from merid.pipeline.proposal import ExecutionResult, TradeProposal, OrderSide
from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.models import KalshiConfig
from merid.event_venues.base import VenueOrder, MarketFilter

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
        try:
            from merid.settings import settings as _s
            _api_key = _s.KALSHI_API_KEY_ID
            _key_path = _s.KALSHI_PRIVATE_KEY_PATH
            _key_pem = _s.KALSHI_PRIVATE_KEY_PEM
            _use_demo = _s.KALSHI_USE_DEMO
            _rate_tier = os.getenv("KALSHI_RATE_TIER", "basic")
        except Exception as _se:
            logger.warning(
                "KalshiPipelineAdapter: merid.settings unavailable, falling back to raw env vars — "
                "verify KALSHI_API_KEY_ID and KALSHI_USE_DEMO are set correctly. Error: %s", _se
            )
            _api_key = os.getenv("KALSHI_API_KEY_ID")
            _key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH")
            _key_pem = None
            _use_demo = os.getenv("KALSHI_USE_DEMO", "false").lower() == "true"
            _rate_tier = os.getenv("KALSHI_RATE_TIER", "basic")
        config = KalshiConfig(
            api_key=_api_key,
            private_key_path=_key_path,
            private_key_pem=_key_pem,
            use_demo=_use_demo,
        )
        self._client = KalshiVenueClient(config, rate_tier=_rate_tier)
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

        # Convert TradeProposal to VenueOrder
        v_order = VenueOrder(
            market_id=proposal.native_symbol or proposal.instrument_id,
            side="buy" if proposal.side == OrderSide.BUY else "sell",
            size=proposal.qty,
            price=proposal.price,
            order_type=proposal.order_type.value.lower() if hasattr(proposal.order_type, 'value') else str(proposal.order_type).lower(),
            outcome_id=proposal.metadata.get("outcome_id", "yes"),
        )

        res = await self._client.place_order_result(v_order)
        if not res.success or not res.data:
            return ExecutionResult(
                proposal_id=proposal.proposal_id,
                venue=self.venue_name,
                status="error",
                error=str(res.error),
            )

        o = res.data
        return ExecutionResult(
            proposal_id=proposal.proposal_id,
            venue=self.venue_name,
            venue_order_id=o.order_id,
            status="filled" if o.status == "executed" else "submitted",
            filled_qty=o.filled_size,
            avg_price=o.price or Decimal("0"),
            fee=Decimal("0"),
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


def get_adapter_registry() -> AdapterRegistry:
    global _registry
    if _registry is None:
        _registry = AdapterRegistry()
    return _registry


