"""Kalshi Venue Adapter — MERID-internal wrapper for Kalshi integration.

Bridges KalshiVenueClient to MERID's internal venue protocol:
- Translates EventMarket to InstrumentConfig
- Exposes positions, orders, fills in MERID format
- Routes orders through matching engine in paper mode
- Provides risk snapshots for reconciliation

Usage::

    adapter = get_kalshi_venue_adapter()
    instruments = await adapter.list_instruments()
    positions = await adapter.get_positions()
    await adapter.submit_order(order)
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any, Dict, List, Optional

from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.market_catalog import get_market_catalog
from merid.event_venues.base import EventMarket, VenueOrder, PlacedOrder, VenuePosition
from merid.matching_engine import Order, Fill, OrderSide, get_matching_engine
from merid.paper_config import InstrumentConfig, DomainMode
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.venue_adapter")


class KalshiVenueAdapter:
    """MERID-internal adapter for Kalshi venue.
    
    Responsibilities:
    - Discover Kalshi markets and map to InstrumentConfig
    - Translate orders between MERID and Kalshi formats
    - Route paper orders through matching engine
    - Provide unified position/order/fill views for reconciliation
    - Expose risk metrics for global risk aggregation
    """

    def __init__(
        self,
        mode: str = "paper",
        client: Optional[KalshiVenueClient] = None,
    ):
        """Initialize Kalshi venue adapter.
        
        Args:
            mode: "paper" or "live" (default: "paper")
            client: Optional KalshiVenueClient instance (lazy-loaded if None)
        """
        self.mode = DomainMode(mode) if isinstance(mode, str) else mode
        self._client = client
        self._catalog = get_market_catalog()
        self._matching_engine = None
        
        # Cache
        self._instruments_cache: List[InstrumentConfig] = []
        self._cache_ts = 0.0
        self._cache_ttl = 300.0  # 5 minutes

        logger.info(f"KalshiVenueAdapter initialized: mode={self.mode.value}")

    @property
    def venue_name(self) -> str:
        return "kalshi"

    @property
    def client(self) -> KalshiVenueClient:
        """Lazy-load Kalshi client."""
        if self._client is None:
            from merid.event_venues.kalshi.client import KalshiVenueClient
            from merid.event_venues.kalshi.models import KalshiConfig
            import os

            # Load from env (KalshiConfig will auto-load from env in __post_init__)
            config = KalshiConfig()
            self._client = KalshiVenueClient(config)
        return self._client

    # ── Instrument Discovery ──────────────────────────────────────────────

    async def list_instruments(
        self,
        category: Optional[str] = None,
        active_only: bool = True,
        force_refresh: bool = False,
    ) -> List[InstrumentConfig]:
        """List Kalshi markets as MERID InstrumentConfig objects.
        
        Args:
            category: Filter by category (e.g., "crypto")
            active_only: Only return active markets
            force_refresh: Bypass cache
            
        Returns:
            List of InstrumentConfig for Kalshi markets
        """
        now = time.time()
        if not force_refresh and (now - self._cache_ts) < self._cache_ttl:
            instruments = self._instruments_cache
        else:
            # Fetch from catalog
            markets = self._catalog.get_all_markets()
            instruments = []
            for cm in markets:
                if active_only and not cm.market.active:
                    continue
                if category and cm.category != category:
                    continue

                # Convert to InstrumentConfig
                inst = self._market_to_instrument(cm.market)
                instruments.append(inst)

            self._instruments_cache = instruments
            self._cache_ts = now

        return instruments

    def _market_to_instrument(self, market: EventMarket) -> InstrumentConfig:
        """Convert Kalshi EventMarket to MERID InstrumentConfig."""
        return InstrumentConfig(
            id=market.market_id,
            domain="prediction",
            enabled=market.active,
            venues=["kalshi"],
            min_size=1.0,           # Kalshi: minimum 1 contract
            max_size=10_000.0,      # Kalshi: typical max ~10k contracts
            tick_size=0.01,         # 1 cent tick
            quote_currency="USD",
            max_stake_usd=1000.0,   # Default per-market limit
            settlement_source="kalshi",
            odds_format="decimal",
        )

    # ── Positions ─────────────────────────────────────────────────────────

    async def get_positions(self) -> List[VenuePosition]:
        """Get current Kalshi positions.
        
        In paper mode: returns positions from matching engine.
        In live mode: fetches from Kalshi API.
        
        Returns:
            List of VenuePosition objects
        """
        if self.mode == DomainMode.PAPER:
            return await self._get_paper_positions()
        else:
            return await self._get_live_positions()

    async def _get_paper_positions(self) -> List[VenuePosition]:
        """Get positions from paper matching engine."""
        engine = self._get_matching_engine()
        if not engine:
            return []

        # Get filled orders and aggregate into positions
        orders = list(engine._orders.values())
        positions_map: Dict[str, VenuePosition] = {}

        for order in orders:
            if order.filled_quantity <= 0:
                continue

            key = order.instrument_id
            if key not in positions_map:
                positions_map[key] = VenuePosition(
                    market_id=order.instrument_id,
                    outcome_id=None,  # Kalshi: outcome is YES/NO, side determines long/short
                    size=Decimal("0"),
                    average_entry_price=Decimal("0"),
                    unrealized_pnl=Decimal("0"),
                    realized_pnl=Decimal("0"),
                    venue="kalshi",
                )

            pos = positions_map[key]
            qty = Decimal(str(order.filled_quantity))
            price = Decimal(str(order.filled_price))

            # Aggregate position (simple average for now)
            old_size = pos.size
            new_size = old_size + qty
            if new_size > 0:
                pos.average_entry_price = (
                    (pos.average_entry_price * old_size + price * qty) / new_size
                )
            pos.size = new_size

        return list(positions_map.values())

    async def _get_live_positions(self) -> List[VenuePosition]:
        """Fetch positions from Kalshi REST API."""
        try:
            await self.client.connect()
            positions = await self.client.get_positions()
            await self.client.close()
            return positions
        except Exception as exc:
            logger.error(f"Failed to fetch Kalshi positions: {exc}")
            return []

    # ── Orders ────────────────────────────────────────────────────────────

    async def get_orders(self, status: Optional[str] = None) -> List[PlacedOrder]:
        """Get current Kalshi orders.
        
        Args:
            status: Filter by status ("pending", "filled", "cancelled")
            
        Returns:
            List of PlacedOrder objects
        """
        if self.mode == DomainMode.PAPER:
            return await self._get_paper_orders(status)
        else:
            return await self._get_live_orders(status)

    async def _get_paper_orders(self, status: Optional[str] = None) -> List[PlacedOrder]:
        """Get orders from paper matching engine."""
        engine = self._get_matching_engine()
        if not engine:
            return []

        orders = []
        for order in engine._orders.values():
            if status and order.status.value != status:
                continue

            orders.append(
                PlacedOrder(
                    order_id=order.order_id,
                    market_id=order.instrument_id,
                    side=order.side.value,
                    size=Decimal(str(order.quantity)),
                    price=Decimal(str(order.price)) if order.price > 0 else None,
                    filled_size=Decimal(str(order.filled_quantity)),
                    remaining_size=Decimal(str(order.quantity - order.filled_quantity)),
                    status=order.status.value,
                    venue="kalshi",
                    raw_data=order.to_dict(),
                )
            )
        return orders

    async def _get_live_orders(self, status: Optional[str] = None) -> List[PlacedOrder]:
        """Fetch orders from Kalshi REST API."""
        try:
            await self.client.connect()
            orders = await self.client.get_orders()
            await self.client.close()
            if status:
                orders = [o for o in orders if o.status == status]
            return orders
        except Exception as exc:
            logger.error(f"Failed to fetch Kalshi orders: {exc}")
            return []

    # ── Order Submission ──────────────────────────────────────────────────

    async def submit_order(self, order: VenueOrder) -> PlacedOrder:
        """Submit an order to Kalshi.
        
        In paper mode: routes through matching engine.
        In live mode: sends to Kalshi REST API.
        
        Args:
            order: VenueOrder to place
            
        Returns:
            PlacedOrder with execution details
            
        Raises:
            ValueError: Invalid order parameters
            RuntimeError: Order submission failed
        """
        if self.mode == DomainMode.PAPER:
            return await self._submit_paper_order(order)
        else:
            return await self._submit_live_order(order)

    async def _submit_paper_order(self, order: VenueOrder) -> PlacedOrder:
        """Submit order to paper matching engine."""
        engine = self._get_matching_engine()
        if not engine:
            raise RuntimeError("Matching engine not available for paper trading")

        # Convert VenueOrder to matching engine Order
        me_order = Order(
            instrument_id=order.market_id,
            side=OrderSide.BUY if order.side.lower() == "buy" else OrderSide.SELL,
            price=float(order.price) if order.price else 0.0,
            quantity=float(order.size),
            domain="prediction",
            agent_id=order.client_order_id or "kalshi-adapter",
        )

        # Submit and get immediate fill (paper mode)
        fill = engine.submit_order(me_order)

        # Convert to PlacedOrder
        return PlacedOrder(
            order_id=me_order.order_id,
            market_id=order.market_id,
            side=order.side,
            size=order.size,
            price=order.price,
            filled_size=Decimal(str(fill.quantity)),
            remaining_size=Decimal("0") if fill.quantity > 0 else order.size,
            status="filled" if fill.quantity > 0 else "rejected",
            venue="kalshi",
            raw_data={"fill": fill.to_dict(), "order": me_order.to_dict()},
        )

    async def _submit_live_order(self, order: VenueOrder) -> PlacedOrder:
        """Submit order to Kalshi REST API."""
        # Kill switch hard gate
        try:
            from merid.risk.kill_switches import risk_controller
            if not risk_controller.can_trade():
                reason = risk_controller.get_kill_reason() or "kill_switch_active"
                raise RuntimeError(f"Trading halted: {reason}")
        except ImportError:
            pass
        try:
            await self.client.connect()
            placed = await self.client.place_order(order)
            await self.client.close()
            return placed
        except Exception as exc:
            logger.error(f"Failed to place Kalshi order: {exc}")
            raise RuntimeError(f"Order submission failed: {exc}") from exc

    # ── Risk Snapshot ─────────────────────────────────────────────────────

    async def get_risk_snapshot(self) -> Dict[str, Any]:
        """Get current risk metrics for Kalshi positions.
        
        Returns:
            Dict with risk metrics:
                - total_notional_usd: Total position notional
                - unrealized_pnl_usd: Unrealized P&L
                - realized_pnl_usd: Realized P&L
                - position_count: Number of open positions
                - order_count: Number of open orders
                - exposure_pct: % of capital exposed
                - kill_switch_active: Emergency stop status
        """
        positions = await self.get_positions()
        orders = await self.get_orders(status="pending")

        total_notional = sum(
            float(p.size) * float(p.average_entry_price) for p in positions
        )
        unrealized_pnl = sum(float(p.unrealized_pnl or 0) for p in positions)
        realized_pnl = sum(float(p.realized_pnl or 0) for p in positions)

        return {
            "venue": "kalshi",
            "mode": self.mode.value,
            "total_notional_usd": round(total_notional, 2),
            "unrealized_pnl_usd": round(unrealized_pnl, 2),
            "realized_pnl_usd": round(realized_pnl, 2),
            "position_count": len(positions),
            "order_count": len(orders),
            "exposure_pct": 0.0,  # Computed by global risk manager
            "kill_switch_active": False,  # Delegated to KalshiRiskManager
        }

    # ── Internal Helpers ──────────────────────────────────────────────────

    def _get_matching_engine(self):
        """Get or initialize matching engine for prediction domain."""
        if self._matching_engine is None:
            try:
                self._matching_engine = get_matching_engine("prediction")
            except Exception as exc:
                logger.warning(f"Matching engine not available: {exc}")
                return None
        return self._matching_engine


# ── Singleton accessor ────────────────────────────────────────────────────

_adapter: Optional[KalshiVenueAdapter] = None


def get_kalshi_venue_adapter(mode: Optional[str] = None) -> KalshiVenueAdapter:
    """Get or create the singleton KalshiVenueAdapter.
    
    Args:
        mode: "paper" or "live" (default: from settings)
        
    Returns:
        KalshiVenueAdapter instance
    """
    from merid.settings import settings
    
    global _adapter
    if _adapter is None:
        # Determine mode from settings if not explicitly provided
        if mode is None:
            # Use live mode if MERID_PM_LIVE_ENABLED is True
            if settings.MERID_PM_LIVE_ENABLED:
                mode = "live"
            else:
                mode = "paper"
        
        _adapter = KalshiVenueAdapter(mode=mode)
        logger.info(f"Created KalshiVenueAdapter singleton: mode={mode}")
    return _adapter


def reset_kalshi_venue_adapter() -> None:
    """Reset the singleton (for testing)."""
    global _adapter
    _adapter = None
