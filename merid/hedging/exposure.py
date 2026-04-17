"""ExposureSnapshot — aggregates per-asset × per-timeframe directional exposure.

Reads from:
  - ``KalshiPositionCache`` (real-time fill events)
  - Pending orders in ``IdempotentOrderStore``
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.hedging.exposure")


@dataclass
class CellExposure:
    """Directional exposure for one (asset, timeframe) cell.

    All values in **cents** (1 contract @ 50¢ = 50 cents notional).
    ``net_delta`` is signed: positive = net YES / long, negative = net NO / short.
    """

    asset: str
    timeframe: str
    yes_notional_cents: int = 0
    no_notional_cents: int = 0
    yes_contracts: int = 0
    no_contracts: int = 0
    pending_yes_cents: int = 0
    pending_no_cents: int = 0

    @property
    def net_delta_cents(self) -> int:
        """Signed net directional exposure including pending orders."""
        return (
            (self.yes_notional_cents + self.pending_yes_cents)
            - (self.no_notional_cents + self.pending_no_cents)
        )

    @property
    def gross_cents(self) -> int:
        return (
            self.yes_notional_cents
            + self.no_notional_cents
            + self.pending_yes_cents
            + self.pending_no_cents
        )


@dataclass
class ExposureSnapshot:
    """Point-in-time exposure across all assets and timeframes."""

    cells: Dict[Tuple[str, str], CellExposure] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def get_cell(self, asset: str, tf: str) -> CellExposure:
        key = (asset.upper(), tf)
        if key not in self.cells:
            self.cells[key] = CellExposure(asset=asset.upper(), timeframe=tf)
        return self.cells[key]

    def net_delta_cents(self, asset: str, tf: str) -> int:
        cell = self.cells.get((asset.upper(), tf))
        return cell.net_delta_cents if cell else 0

    def all_asset_timeframes(self) -> List[Tuple[str, str]]:
        """Return all (asset, timeframe) pairs with non-zero exposure."""
        return [k for k, v in self.cells.items() if v.gross_cents > 0]


def build_exposure_snapshot() -> ExposureSnapshot:
    """Build snapshot from live position cache and pending order store.

    Graceful-degrade: returns empty snapshot if infrastructure is unavailable.
    """
    snap = ExposureSnapshot()

    # ── 1. Position cache ─────────────────────────────────────────────
    try:
        from merid.event_venues.kalshi.position_cache import get_position_cache
        from merid.event_venues.kalshi.market_filter import (
            extract_asset_from_ticker,
            get_series_timeframe_bucket,
        )

        for ticker, pos in get_position_cache().get_all_positions().items():
            asset = extract_asset_from_ticker(ticker)
            if not asset:
                continue
            tf = get_series_timeframe_bucket(ticker)
            cell = snap.get_cell(asset, tf)
            notional = pos.contracts * pos.avg_price_cents
            if pos.side == "yes":
                cell.yes_notional_cents += notional
                cell.yes_contracts += pos.contracts
            else:
                cell.no_notional_cents += notional
                cell.no_contracts += pos.contracts
    except Exception as exc:
        logger.debug("[exposure] position cache read failed: %s", exc)

    # ── 2. Pending orders (from IdempotentOrderStore) ─────────────────
    try:
        from merid.event_venues.kalshi.order_gate import get_pre_trade_gate, OrderStatus
        from merid.event_venues.kalshi.market_filter import (
            extract_asset_from_ticker as _eat,
            get_series_timeframe_bucket as _gstb,
        )

        gate = get_pre_trade_gate()
        for rec in gate._store.snapshot():
            if rec.status not in (OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.LIVE):
                continue
            asset = _eat(rec.contract_id)
            if not asset:
                continue
            tf = _gstb(rec.contract_id)
            cell = snap.get_cell(asset, tf)
            notional = rec.target_count * rec.price_cents
            if rec.side == "yes":
                cell.pending_yes_cents += notional
            else:
                cell.pending_no_cents += notional
    except Exception as exc:
        logger.debug("[exposure] pending orders read failed: %s", exc)

    return snap
