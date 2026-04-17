"""Canonical ``kalshi:order_filled`` emissions tied to ledger fills.

Prevents duplicate social/UI notifications when the same fill arrives via
HTTP poller and private WebSocket ``fill`` channel.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Set

from utils.logger import get_logger

if TYPE_CHECKING:
    from merid.event_venues.kalshi.fills_ledger import KalshiFill

logger = get_logger("merid.event_venues.kalshi.fill_bus")

# Recent fill_ids already announced (dedupe HTTP + WS ingestion)
_recent_order_filled_ids: Set[str] = set()
_MAX_DEDUPE: int = 2000


def _remember(fill_id: str) -> bool:
    """Return True if this is the first announcement for fill_id in-process."""
    if fill_id in _recent_order_filled_ids:
        return False
    _recent_order_filled_ids.add(fill_id)
    if len(_recent_order_filled_ids) > _MAX_DEDUPE:
        # Evict oldest half by dropping an arbitrary subset (set has no ordering)
        evict_count = len(_recent_order_filled_ids) // 2
        it = iter(_recent_order_filled_ids)
        to_remove = [next(it) for _ in range(evict_count)]
        for fid in to_remove:
            _recent_order_filled_ids.discard(fid)
    return True


async def publish_order_filled_for_ledger_fill(fill: "KalshiFill") -> None:
    """Publish one bus event for a verified ledger fill (user-owned trade).

    Skips zero-size fills, incomplete price rows, and duplicate fill_ids.
    """
    if not fill.fill_id or fill.count_fp <= 0:
        return
    if fill.is_incomplete():
        logger.debug(
            "fill_bus skip_incomplete fill_id=%s ticker=%s price_cents=%s",
            fill.fill_id,
            fill.market_ticker,
            fill.price_cents,
        )
        return
    if not _remember(fill.fill_id):
        return

    try:
        from core.event_bus import event_stream

        price_cents = fill.price_cents
        asset = fill.resolved_asset() or ""
        payload = {
            "fill_id": fill.fill_id,
            "venue_fill_id": fill.trade_id or fill.fill_id,
            "order_id": fill.order_id or "",
            "market_id": fill.market_ticker,
            "asset": asset,
            "side": fill.side,
            "action": (fill.action or "buy").lower(),
            "contracts": int(fill.count_fp),
            "price_cents": int(price_cents),
            "fee_cents": int(float(fill.fee_cost) * 100),
            "simulated": False,
            "agent": fill.agent_id or "",
            "timestamp": fill.created_time.isoformat() if fill.created_time else "",
            "source": "fills_ledger",
            "ingestion_source": fill.ingestion_source,
        }
        await event_stream.publish("kalshi:order_filled", payload)
        logger.debug(
            "fill_bus order_filled fill_id=%s order_id=%s ticker=%s asset=%s action=%s size=%s",
            fill.fill_id,
            fill.order_id,
            fill.market_ticker,
            asset,
            payload["action"],
            fill.count_fp,
        )
        # BUG-016: record per-cell fill metric (asset × timeframe)
        try:
            from merid.metrics.cell_metrics import record_fill as _cm_fill
            # Infer timeframe from ticker suffix (e.g. "BTC-1H-..." → "1h", "BTC-15M-..." → "15m")
            _ticker_upper = (fill.market_ticker or "").upper()
            _tf = "unknown"
            for _candidate in ("1H", "15M", "1D", "4H", "30M", "5M"):
                if _candidate in _ticker_upper:
                    _tf = _candidate.lower()
                    break
            _fill_cents = int(float(fill.price_cents) * int(fill.count_fp))
            _cm_fill(asset or "unknown", _tf, _fill_cents, 0)
        except Exception as e:
            logger.debug(f"CM fill recording failed: {e}")
    except Exception as exc:
        logger.warning("fill_bus publish failed: %s", exc)
