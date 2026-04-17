"""Aggregate PnL for fills tagged with ``decision_trace_id`` (sentiment/swarm audit)."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any, Dict, List, Tuple

from utils.logger import get_logger

logger = get_logger("merid.sentiment.sentiment_pnl_attribution")


def _fill_pnl_contribution(f: Any) -> Tuple[Decimal, Decimal]:
    """Same sign convention as :meth:`KalshiFillsLedger.summary` (simplified per-fill)."""
    sign = Decimal("1") if getattr(f, "action", "") == "sell" else Decimal("-1")
    notional = getattr(f, "notional_usd", None)
    if notional is None:
        notional = Decimal("0")
    fee = getattr(f, "fee_cost", None) or Decimal("0")
    return sign * notional - fee, fee


def aggregate_sentiment_pnl(
    *,
    fills: List[Any] | None = None,
) -> Dict[str, Any]:
    """Summarize fills that carry a non-null ``decision_trace_id``.

    If *fills* is None, reads from :func:`merid.event_venues.kalshi.fills_ledger.get_fills_ledger`.
    """
    detailed = aggregate_sentiment_pnl_detailed(fills=fills)
    legacy_by_asset: Dict[str, Dict[str, float]] = {}
    for a, b in detailed["by_asset"].items():
        legacy_by_asset[a] = {
            "trades": float(b["trade_count_tagged"]),
            "contracts": 0.0,
            "fee_usd": float(b["fees_tagged"]),
        }
    return {
        "sentiment_tagged_fills": detailed["totals"]["trade_count_tagged"],
        "untagged_fills": detailed["totals"]["trade_count_untagged"],
        "by_asset": legacy_by_asset,
        "by_asset_detail": detailed["by_asset"],
        "totals": detailed["totals"],
    }


def aggregate_sentiment_pnl_detailed(
    *,
    fills: List[Any] | None = None,
) -> Dict[str, Any]:
    """Per-asset and global tagged vs untagged: counts, fees, realized PnL, hit-rate."""
    if fills is None:
        try:
            from merid.event_venues.kalshi.fills_ledger import get_fills_ledger

            ledger = get_fills_ledger()
            fills = ledger.get_fills()
        except Exception as exc:
            logger.debug("sentiment PnL: ledger unavailable: %s", exc)
            fills = []

    by_asset: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "trade_count_tagged": 0,
            "trade_count_untagged": 0,
            "realized_pnl_tagged": 0.0,
            "realized_pnl_untagged": 0.0,
            "fees_tagged": 0.0,
            "fees_untagged": 0.0,
            "wins_tagged": 0,
            "wins_untagged": 0,
        }
    )

    totals = {
        "trade_count_tagged": 0,
        "trade_count_untagged": 0,
        "realized_pnl_tagged": 0.0,
        "realized_pnl_untagged": 0.0,
        "fees_tagged": 0.0,
        "fees_untagged": 0.0,
        "hit_rate_tagged": 0.0,
        "hit_rate_untagged": 0.0,
    }

    for f in fills:
        tid = getattr(f, "decision_trace_id", None) or (
            (f.raw_payload or {}).get("decision_trace_id") if getattr(f, "raw_payload", None) else None
        )
        asset = f.resolved_asset() or "UNKNOWN"
        pnl_c, fee = _fill_pnl_contribution(f)
        pnl_f = float(pnl_c)
        fee_f = float(fee)
        win = pnl_f > 0
        bucket = by_asset[asset]
        if tid:
            bucket["trade_count_tagged"] += 1
            bucket["realized_pnl_tagged"] += pnl_f
            bucket["fees_tagged"] += fee_f
            if win:
                bucket["wins_tagged"] += 1
            totals["trade_count_tagged"] += 1
            totals["realized_pnl_tagged"] += pnl_f
            totals["fees_tagged"] += fee_f
        else:
            bucket["trade_count_untagged"] += 1
            bucket["realized_pnl_untagged"] += pnl_f
            bucket["fees_untagged"] += fee_f
            if win:
                bucket["wins_untagged"] += 1
            totals["trade_count_untagged"] += 1
            totals["realized_pnl_untagged"] += pnl_f
            totals["fees_untagged"] += fee_f

    for _a, b in by_asset.items():
        tc = b["trade_count_tagged"]
        b["hit_rate_tagged"] = (b["wins_tagged"] / tc) if tc else 0.0
        uc = b["trade_count_untagged"]
        b["hit_rate_untagged"] = (b["wins_untagged"] / uc) if uc else 0.0
        b["net_pnl_tagged"] = b["realized_pnl_tagged"]
        b["net_pnl_untagged"] = b["realized_pnl_untagged"]

    tt = totals["trade_count_tagged"]
    tu = totals["trade_count_untagged"]
    totals["hit_rate_tagged"] = (
        sum(b["wins_tagged"] for b in by_asset.values()) / tt if tt else 0.0
    )
    totals["hit_rate_untagged"] = (
        sum(b["wins_untagged"] for b in by_asset.values()) / tu if tu else 0.0
    )
    totals["net_pnl_tagged"] = totals["realized_pnl_tagged"]
    totals["net_pnl_untagged"] = totals["realized_pnl_untagged"]

    return {"by_asset": dict(by_asset), "totals": totals}
