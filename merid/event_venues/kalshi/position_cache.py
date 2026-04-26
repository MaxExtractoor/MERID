"""Real-time position cache updated from WebSocket fill events.

Reduces latency from 5-30s (REST polling) to <1s (WS event-driven).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.position_cache")


@dataclass
class CachedPosition:
    """Cached position state."""
    market_id: str
    contracts: int
    side: str  # "yes" or "no"
    avg_price_cents: int
    realized_pnl_usd: Decimal = Decimal("0")
    unrealized_pnl_usd: Decimal = Decimal("0")
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def apply_fill(self, contracts: int, price_cents: int, fee_cents: int, side: str) -> None:
        """Update position with a new fill."""
        if side == self.side:
            # Adding to position
            total_cost_old = self.contracts * self.avg_price_cents
            total_cost_new = contracts * price_cents
            self.contracts += contracts
            # P0-2 FIX: Use proper rounding instead of integer division to prevent PnL drift
            self.avg_price_cents = round((total_cost_old + total_cost_new) / self.contracts) if self.contracts > 0 else price_cents
        else:
            # Closing/reducing position
            # YES positions profit when close price > entry price;
            # NO positions profit when close price < entry price.
            if self.side == "yes":
                pnl_per = price_cents - self.avg_price_cents
            else:
                pnl_per = self.avg_price_cents - price_cents
            if contracts >= self.contracts:
                # Full close
                pnl_cents = self.contracts * pnl_per
                self.realized_pnl_usd += Decimal(pnl_cents) / Decimal("100") - Decimal(fee_cents) / Decimal("100")
                self.contracts = 0
            else:
                # Partial close
                pnl_cents = contracts * pnl_per
                self.realized_pnl_usd += Decimal(pnl_cents) / Decimal("100") - Decimal(fee_cents) / Decimal("100")
                self.contracts -= contracts

        self.last_updated = datetime.now(timezone.utc)

    def update_unrealized_pnl(self, current_price_cents: int) -> None:
        """Recalculate unrealized PnL based on current market price."""
        if self.contracts > 0:
            if self.side == "yes":
                pnl_cents = self.contracts * (current_price_cents - self.avg_price_cents)
            else:
                pnl_cents = self.contracts * (self.avg_price_cents - current_price_cents)
            self.unrealized_pnl_usd = Decimal(pnl_cents) / Decimal("100")
        else:
            self.unrealized_pnl_usd = Decimal("0")


class KalshiPositionCache:
    """Real-time position cache updated from WebSocket events.

    Usage:
        cache = get_position_cache()
        cache.on_fill(market_id, contracts, price_cents, fee_cents, side)
        position = cache.get_position(market_id)
    """

    _instance: Optional[KalshiPositionCache] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._positions: Dict[str, CachedPosition] = {}
        self._last_sync: Optional[datetime] = None
        self._initialized = True
        logger.info("KalshiPositionCache initialized")

    def on_fill(self, market_id: str, contracts: int, price_cents: int, fee_cents: int, side: str) -> None:
        """Handle a fill event from WebSocket."""
        position = self._positions.get(market_id)

        if position is None:
            # New position
            self._positions[market_id] = CachedPosition(
                market_id=market_id,
                contracts=contracts,
                side=side,
                avg_price_cents=price_cents,
            )
            logger.debug(f"Position cache: opened {side} position on {market_id}: {contracts} @ {price_cents}¢")
        else:
            # Update existing
            position.apply_fill(contracts, price_cents, fee_cents, side)
            logger.debug(f"Position cache: updated {market_id}: {position.contracts} contracts")

            # Remove if fully closed
            if position.contracts == 0:
                del self._positions[market_id]
                logger.debug(f"Position cache: closed position on {market_id}")

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

    def sync_from_rest(self, positions: list) -> None:
        """Sync cache with REST API positions (fallback/reconciliation)."""
        try:
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
                    realized_pnl_usd=Decimal(str(pos.get("realized_pnl", 0))),
                    unrealized_pnl_usd=Decimal(str(pos.get("unrealized_pnl", 0))),
                )

            self._last_sync = datetime.now(timezone.utc)
            logger.info(f"Position cache synced from REST: {len(self._positions)} positions")
        except Exception as e:
            logger.error(f"Position cache sync from REST failed: {e}")

    def clear(self) -> None:
        """Clear all cached positions."""
        self._positions.clear()
        logger.info("Position cache cleared")


# Singleton accessor
import threading as _threading
_position_cache_instance: "KalshiPositionCache | None" = None
_position_cache_lock = _threading.Lock()


def get_position_cache() -> "KalshiPositionCache":
    """Get the global position cache singleton."""
    global _position_cache_instance
    if _position_cache_instance is None:
        with _position_cache_lock:
            if _position_cache_instance is None:
                _position_cache_instance = KalshiPositionCache()
    return _position_cache_instance
