"""Real-time position cache updated from WebSocket fill events.

Reduces latency from 5-30s (REST polling) to <1s (WS event-driven).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Optional

from trading.trade_mode import TradeMode
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.position_cache")


@dataclass
class CachedPosition:
    """Cached position state with mode tagging to prevent live/paper confusion."""
    market_id: str
    contracts: int
    side: str  # "yes" or "no"
    avg_price_cents: int
    mode: TradeMode  # live, paper, or mock - prevents mode confusion
    realized_pnl_usd: Decimal = Decimal("0")
    unrealized_pnl_usd: Decimal = Decimal("0")
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def apply_fill(self, contracts: int, price_cents: int, fee_cents: int, side: str, fill_mode: TradeMode) -> None:
        """Update position with a new fill.

        Args:
            contracts: Number of contracts filled
            price_cents: Fill price in cents
            fee_cents: Fee paid in cents
            side: "yes" or "no"
            fill_mode: Mode of the fill (must match position mode)

        Raises:
            ValueError: If fill_mode doesn't match position mode
        """
        if fill_mode != self.mode:
            raise ValueError(
                f"Mode mismatch: position is {self.mode.value}, fill is {fill_mode.value}. "
                f"Cannot apply fill from different mode to prevent live/paper confusion."
            )
        if side == self.side:
            # Adding to position
            total_cost_old = self.contracts * self.avg_price_cents
            total_cost_new = contracts * price_cents
            self.contracts += contracts
            self.avg_price_cents = (total_cost_old + total_cost_new) // self.contracts if self.contracts > 0 else price_cents
        else:
            # Closing/reducing position
            if contracts >= self.contracts:
                # Full close
                pnl_cents = self.contracts * (price_cents - self.avg_price_cents)
                self.realized_pnl_usd += Decimal(str(pnl_cents / 100.0)) - Decimal(str(fee_cents / 100.0))
                self.contracts = 0
            else:
                # Partial close
                pnl_cents = contracts * (price_cents - self.avg_price_cents)
                self.realized_pnl_usd += Decimal(str(pnl_cents / 100.0)) - Decimal(str(fee_cents / 100.0))
                self.contracts -= contracts

        self.last_updated = datetime.now(timezone.utc)

    def update_unrealized_pnl(self, current_price_cents: int) -> None:
        """Recalculate unrealized PnL based on current market price."""
        if self.contracts > 0:
            pnl_cents = self.contracts * (current_price_cents - self.avg_price_cents)
            self.unrealized_pnl_usd = Decimal(str(pnl_cents / 100.0))
        else:
            self.unrealized_pnl_usd = Decimal("0")


class KalshiPositionCache:
    """Real-time position cache updated from WebSocket events with mode isolation.

    Each cache instance is bound to a specific trading mode (LIVE or PAPER)
    to prevent live/paper confusion. Fills from the wrong mode are rejected.

    Usage:
        cache = get_position_cache(TradeMode.LIVE)
        cache.on_fill(market_id, contracts, price_cents, fee_cents, side, mode=TradeMode.LIVE)
        position = cache.get_position(market_id)
    """

    def __init__(self, mode: TradeMode):
        """Initialize cache for a specific trading mode.

        Args:
            mode: Trading mode this cache is bound to (LIVE, PAPER, or MOCK)
        """
        self.mode = mode
        self._positions: Dict[str, CachedPosition] = {}
        self._last_sync: Optional[datetime] = None
        logger.info(f"KalshiPositionCache initialized for mode={mode.value}")

    def on_fill(
        self,
        market_id: str,
        contracts: int,
        price_cents: int,
        fee_cents: int,
        side: str,
        mode: TradeMode
    ) -> None:
        """Handle a fill event from WebSocket.

        Args:
            market_id: Market identifier
            contracts: Number of contracts filled
            price_cents: Fill price in cents
            fee_cents: Fee paid in cents
            side: "yes" or "no"
            mode: Mode of the fill source

        Raises:
            ValueError: If fill mode doesn't match cache mode
        """
        if mode != self.mode:
            logger.error(
                f"Mode violation: cache is {self.mode.value}, fill is {mode.value}. "
                f"Rejecting fill for {market_id} to prevent live/paper confusion."
            )
            raise ValueError(
                f"Cannot apply {mode.value} fill to {self.mode.value} cache. "
                f"Use get_position_cache({mode.value}) instead."
            )
        position = self._positions.get(market_id)

        if position is None:
            # New position
            self._positions[market_id] = CachedPosition(
                market_id=market_id,
                contracts=contracts,
                side=side,
                avg_price_cents=price_cents,
                mode=mode,
            )
            logger.debug(f"Position cache ({self.mode.value}): opened {side} position on {market_id}: {contracts} @ {price_cents}¢")
        else:
            # Update existing
            position.apply_fill(contracts, price_cents, fee_cents, side, fill_mode=mode)
            logger.debug(f"Position cache ({self.mode.value}): updated {market_id}: {position.contracts} contracts")

            # Remove if fully closed
            if position.contracts == 0:
                del self._positions[market_id]
                logger.debug(f"Position cache ({self.mode.value}): closed position on {market_id}")

    def on_price_update(self, market_id: str, price_cents: int) -> None:
        """Update unrealized PnL when market price changes."""
        position = self._positions.get(market_id)
        if position:
            position.update_unrealized_pnl(price_cents)

    def get_position(self, market_id: str) -> Optional[CachedPosition]:
        """Get cached position for a market."""
        return self._positions.get(market_id)

    def get_all_positions(self) -> Dict[str, CachedPosition]:
        """Get all cached positions."""
        return dict(self._positions)

    def sync_from_rest(self, positions: list, mode: TradeMode) -> None:
        """Sync cache with REST API positions (fallback/reconciliation).

        Args:
            positions: List of position dicts from REST API
            mode: Mode of the positions source (must match cache mode)

        Raises:
            ValueError: If mode doesn't match cache mode
        """
        if mode != self.mode:
            logger.error(
                f"Mode violation: cache is {self.mode.value}, REST positions are {mode.value}"
            )
            raise ValueError(
                f"Cannot sync {mode.value} positions to {self.mode.value} cache"
            )

        self._positions.clear()
        for pos in positions:
            market_id = pos.get("market_id") or pos.get("ticker")
            if not market_id:
                continue

            self._positions[market_id] = CachedPosition(
                market_id=market_id,
                contracts=int(pos.get("contracts", 0)),
                side=pos.get("side", "yes"),
                avg_price_cents=int(pos.get("avg_price_cents", 50)),
                mode=mode,
                realized_pnl_usd=Decimal(str(pos.get("realized_pnl", 0))),
                unrealized_pnl_usd=Decimal(str(pos.get("unrealized_pnl", 0))),
            )

        self._last_sync = datetime.now(timezone.utc)
        logger.info(f"Position cache ({self.mode.value}) synced from REST: {len(self._positions)} positions")

    def clear(self) -> None:
        """Clear all cached positions."""
        self._positions.clear()
        logger.info(f"Position cache ({self.mode.value}) cleared")


# ══════════════════════════════════════════════════════════════════════════════
# Mode-isolated singleton accessors
# ══════════════════════════════════════════════════════════════════════════════

_live_cache: Optional[KalshiPositionCache] = None
_paper_cache: Optional[KalshiPositionCache] = None
_mock_cache: Optional[KalshiPositionCache] = None


def get_position_cache(mode: TradeMode) -> KalshiPositionCache:
    """Get the position cache singleton for a specific trading mode.

    Each mode has its own cache instance to prevent live/paper confusion.

    Args:
        mode: Trading mode (LIVE, PAPER, or MOCK)

    Returns:
        KalshiPositionCache instance for the specified mode

    Example:
        >>> live_cache = get_position_cache(TradeMode.LIVE)
        >>> paper_cache = get_position_cache(TradeMode.PAPER)
        >>> # These are separate instances with independent state
    """
    global _live_cache, _paper_cache, _mock_cache

    if mode == TradeMode.LIVE:
        if _live_cache is None:
            _live_cache = KalshiPositionCache(TradeMode.LIVE)
        return _live_cache
    elif mode == TradeMode.PAPER:
        if _paper_cache is None:
            _paper_cache = KalshiPositionCache(TradeMode.PAPER)
        return _paper_cache
    else:  # MOCK
        if _mock_cache is None:
            _mock_cache = KalshiPositionCache(TradeMode.MOCK)
        return _mock_cache


def clear_all_caches() -> None:
    """Clear all position caches across all modes.

    Useful when switching modes or resetting system state.
    """
    global _live_cache, _paper_cache, _mock_cache

    if _live_cache:
        _live_cache.clear()
    if _paper_cache:
        _paper_cache.clear()
    if _mock_cache:
        _mock_cache.clear()

    logger.info("All position caches cleared across all modes")
