"""UnifiedVenueAdapter ABC and AdapterRegistry.

Every venue (Kalshi, Binance, Coinbase, Kraken, OKX, Alpaca, IBKR)
implements this interface.  The TradeRouter looks up adapters by venue
name and dispatches proposals.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Dict, List, Optional

from merid.pipeline.proposal import ExecutionResult, TradeProposal

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

class AdapterRegistry:
    """Central registry of all venue adapters."""

    def __init__(self) -> None:
        self._adapters: Dict[str, UnifiedVenueAdapter] = {}

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
