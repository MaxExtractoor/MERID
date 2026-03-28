"""KalshiFillsLedger — canonical source of truth for all Kalshi fills.

Responsibilities:
  1. Accept fills from two source paths (REST portfolio/fills poll and WS fill events).
  2. Key every fill by Kalshi ``fill_id`` so duplicate deliveries from either
     path are idempotently merged — never double-counted.
  3. Expose query methods for:
     - UI fills table
     - Position reconstruction (net YES/NO contracts per market)
     - PnL calculation

Design invariants:
  - A fill MUST carry a non-empty ``fill_id``; entries without one are rejected.
  - All public write methods are thread-safe via an asyncio lock.
  - ``upsert()`` returns True on a new fill and False on a duplicate.

Usage::

    ledger = get_fills_ledger()
    ledger.upsert(fill_id="f-123", ticker="KXBTC-15M-T95000", ...)
    positions = ledger.positions()
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.fills_ledger")


@dataclass
class Fill:
    """Single canonical fill record.

    Fields are intentionally minimal; raw_data holds anything extra from
    either the REST or WS delivery.
    """

    fill_id: str           # Kalshi fill_id — primary key
    ticker: str            # market ticker (e.g. "KXBTC-15M-T95000")
    side: str              # "yes" or "no"
    action: str            # "buy" or "sell"
    count: int             # number of contracts
    price_cents: int       # fill price in cents (0-100)
    is_taker: bool = False
    ts: float = field(default_factory=time.time)
    order_id: Optional[str] = None
    source: str = "unknown"  # "rest" | "ws" | "unknown"
    raw_data: Optional[dict] = None

    def pnl_contribution(self) -> float:
        """Net dollar value of this fill (positive = proceeds, negative = cost)."""
        value = self.count * self.price_cents / 100.0
        return -value if self.action == "buy" else value


class KalshiFillsLedger:
    """Canonical, idempotent fill store keyed by Kalshi fill_id.

    Thread-safe for use with asyncio coroutines.
    """

    def __init__(self) -> None:
        self._fills: Dict[str, Fill] = {}
        self._lock = asyncio.Lock()

    # ── Write ─────────────────────────────────────────────────────────────

    async def upsert(
        self,
        fill_id: str,
        ticker: str,
        side: str,
        action: str,
        count: int,
        price_cents: int,
        *,
        is_taker: bool = False,
        ts: Optional[float] = None,
        order_id: Optional[str] = None,
        source: str = "unknown",
        raw_data: Optional[dict] = None,
    ) -> bool:
        """Insert or ignore a fill.

        Returns:
            True  — fill was new and stored.
            False — fill_id already present; record unchanged.

        Raises:
            ValueError — if fill_id is empty (fills without a Kalshi id are
                         rejected to prevent ghost-trade corruption).
        """
        if not fill_id:
            raise ValueError("fill_id must be non-empty; Kalshi fills always carry one.")

        async with self._lock:
            if fill_id in self._fills:
                logger.debug("fills_ledger: duplicate fill_id=%s (ignored)", fill_id)
                return False

            self._fills[fill_id] = Fill(
                fill_id=fill_id,
                ticker=ticker,
                side=side,
                action=action,
                count=count,
                price_cents=price_cents,
                is_taker=is_taker,
                ts=ts if ts is not None else time.time(),
                order_id=order_id,
                source=source,
                raw_data=raw_data,
            )
            logger.info(
                "fills_ledger: +fill fill_id=%s ticker=%s %s %s %d@%dc src=%s",
                fill_id, ticker, action, side, count, price_cents, source,
            )
            return True

    async def clear(self) -> None:
        """Remove all fills — for testing only."""
        async with self._lock:
            self._fills.clear()

    # ── Read ──────────────────────────────────────────────────────────────

    def all_fills(self) -> List[Fill]:
        """Return all fills sorted by timestamp (oldest first)."""
        return sorted(self._fills.values(), key=lambda f: f.ts)

    def fills_for_ticker(self, ticker: str) -> List[Fill]:
        """All fills for a specific market ticker."""
        return sorted(
            (f for f in self._fills.values() if f.ticker == ticker),
            key=lambda f: f.ts,
        )

    def has_fill(self, fill_id: str) -> bool:
        """Check whether a fill_id is already present."""
        return fill_id in self._fills

    def positions(self) -> Dict[str, int]:
        """Net position per ticker (positive = net YES, negative = net NO).

        Computed from fills each time; use a cache if hot-path performance matters.
        """
        pos: Dict[str, int] = {}
        for fill in self._fills.values():
            delta = fill.count if fill.action == "buy" else -fill.count
            if fill.side == "no":
                delta = -delta  # buying "no" is short the yes side
            pos[fill.ticker] = pos.get(fill.ticker, 0) + delta
        return pos

    def realized_pnl(self) -> float:
        """Sum of PnL contributions across all fills."""
        return sum(f.pnl_contribution() for f in self._fills.values())

    def size(self) -> int:
        """Total number of unique fills stored."""
        return len(self._fills)

    # ── Status ────────────────────────────────────────────────────────────

    def summary(self) -> dict:
        """JSON-serializable ledger status."""
        return {
            "fill_count": len(self._fills),
            "realized_pnl": self.realized_pnl(),
            "positions": self.positions(),
        }


# ── Singleton ─────────────────────────────────────────────────────────────

_ledger: Optional[KalshiFillsLedger] = None


def get_fills_ledger() -> KalshiFillsLedger:
    """Return the process-singleton fills ledger."""
    global _ledger
    if _ledger is None:
        _ledger = KalshiFillsLedger()
    return _ledger

