from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Union

from merid.metrics.canonical_buckets import (
    get_basis_bucket,
    get_distance_bucket,
    get_price_bucket,
    get_tte_bucket,
)


@dataclass
class PostTradeBucket:
    """Aggregated statistics for one post-trade bucket."""
    bucket_name: str
    count: int = 0
    wins: int = 0
    total_pnl: Decimal = Decimal("0")
    total_proceeds: Decimal = Decimal("0")
    total_edge: Decimal = Decimal("0")
    total_ev: Decimal = Decimal("0")
    total_all_in_cost: Decimal = Decimal("0")
    total_model_prob: Decimal = Decimal("0")
    total_count: Decimal = Decimal("0")

    @property
    def win_rate(self) -> float:
        return (self.wins / self.count * 100.0) if self.count else 0.0

    @property
    def avg_pnl(self) -> Decimal:
        return self.total_pnl / self.count if self.count else Decimal("0")

    @property
    def avg_edge(self) -> Decimal:
        return self.total_edge / self.count if self.count else Decimal("0")

    @property
    def avg_ev_cents(self) -> Decimal:
        return self.total_ev / self.count if self.count else Decimal("0")

    @property
    def avg_all_in_cost_cents(self) -> Decimal:
        return self.total_all_in_cost / self.count if self.count else Decimal("0")

    @property
    def avg_model_prob(self) -> Decimal:
        return self.total_model_prob / self.count if self.count else Decimal("0")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bucket_name": self.bucket_name,
            "count": self.count,
            "wins": self.wins,
            "win_rate": round(self.win_rate, 2),
            "avg_pnl": float(self.avg_pnl),
            "avg_edge_pct": float(self.avg_edge),
            "avg_ev_cents": float(self.avg_ev_cents),
            "avg_all_in_cost_cents": float(self.avg_all_in_cost_cents),
            "avg_model_prob": float(self.avg_model_prob),
        }


def _as_dict(fill: Any) -> Dict[str, Any]:
    if isinstance(fill, dict):
        return fill
    if hasattr(fill, "to_dict"):
        return fill.to_dict()
    return dict(fill)


def _price_cents(fill: Dict[str, Any]) -> int:
    if "price_cents" in fill and fill["price_cents"] is not None:
        return int(fill["price_cents"])
    if fill.get("side") == "yes" and fill.get("yes_price_dollars") is not None:
        return int(Decimal(str(fill["yes_price_dollars"])) * 100)
    if fill.get("side") == "no" and fill.get("no_price_dollars") is not None:
        return int(Decimal(str(fill["no_price_dollars"])) * 100)
    return 0


def _proceeds(fill: Dict[str, Any]) -> Optional[Decimal]:
    if "proceeds_dollars" in fill and fill["proceeds_dollars"] is not None:
        return Decimal(str(fill["proceeds_dollars"]))
    if "proceeds" in fill and fill["proceeds"] is not None:
        return Decimal(str(fill["proceeds"]))
    return None


def _to_bool(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes", "buy")
    return bool(value)


class PostTradeReport:
    """Bucketed post-trade analysis from a list of fills."""

    def __init__(self, fills: Sequence[Any]) -> None:
        self.fills: List[Dict[str, Any]] = [_as_dict(f) for f in fills]
        self._buckets: Dict[str, Dict[str, PostTradeBucket]] = defaultdict(dict)

    def build(self) -> None:
        """Aggregate fills into all bucket dimensions."""
        self._buckets.clear()
        for fill in self.fills:
            pnl = _proceeds(fill)
            if pnl is None:
                continue

            price_cents = _price_cents(fill)
            side = str(fill.get("side") or "unknown")
            thesis_side = str(fill.get("thesis_side") or "unknown")
            asset = str(fill.get("asset") or "unknown")
            regime = str(fill.get("regime") or "unknown")
            is_counter_trend = _to_bool(fill.get("is_counter_trend"))
            thesis_aligned = (side == thesis_side) if side in ("yes", "no") and thesis_side in ("yes", "no") else None

            tte = fill.get("time_to_expiry_seconds")
            if tte is None and "tte_seconds" in fill:
                tte = fill["tte_seconds"]
            if tte is not None:
                try:
                    tte = float(tte)
                except (TypeError, ValueError):
                    tte = None

            basis = fill.get("cf_rti_basis")
            if basis is not None:
                try:
                    basis = float(basis)
                except (TypeError, ValueError):
                    basis = None

            edge = Decimal(str(fill.get("edge_pct") or 0))
            ev = Decimal(str(fill.get("ev_net_cents") or fill.get("ev_cents") or 0))
            all_in_cost = Decimal(str(fill.get("all_in_cost_cents") or 0))
            model_prob = Decimal(str(fill.get("entry_model_probability") or fill.get("model_prob") or 0))
            count = Decimal(str(fill.get("count_fp") or fill.get("count") or 1))

            is_win = pnl > 0

            bucket_values = {
                "price": get_price_bucket(price_cents),
                "tte": get_tte_bucket(tte),
                "side": f"side_{side}",
                "thesis_alignment": f"thesis_aligned_{thesis_aligned}" if thesis_aligned is not None else "thesis_unknown",
                "counter_trend": f"counter_trend_{is_counter_trend}",
                "asset": f"asset_{asset}",
                "regime": f"regime_{regime}",
                "basis": get_basis_bucket(basis),
            }

            for dimension, bucket_name in bucket_values.items():
                bucket = self._buckets[dimension].setdefault(bucket_name, PostTradeBucket(bucket_name))
                bucket.count += 1
                if is_win:
                    bucket.wins += 1
                bucket.total_pnl += pnl
                bucket.total_proceeds += pnl
                bucket.total_edge += edge
                bucket.total_ev += ev
                bucket.total_all_in_cost += all_in_cost
                bucket.total_model_prob += model_prob
                bucket.total_count += count

    def by_dimension(self, dimension: str) -> List[PostTradeBucket]:
        return [bucket for bucket in self._buckets.get(dimension, {}).values()]

    def summary(self) -> Dict[str, Any]:
        total_count = len(self.fills)
        total_wins = sum(1 for f in self.fills if _proceeds(f) is not None and _proceeds(f) > 0)
        total_pnl = sum((_proceeds(f) or Decimal("0")) for f in self.fills)
        return {
            "total_fills": total_count,
            "winning_fills": total_wins,
            "win_rate_pct": round(total_wins / total_count * 100, 2) if total_count else 0.0,
            "total_pnl": float(total_pnl),
            "dimensions": sorted(self._buckets.keys()),
        }

    def report(self) -> str:
        self.build()
        lines = ["=" * 80, "BUCKETED POST-TRADE REPORT", "=" * 80]
        for dimension in sorted(self._buckets.keys()):
            lines.append(f"\n--- {dimension.upper()} BUCKETS ---")
            for bucket in sorted(self.by_dimension(dimension), key=lambda b: b.count, reverse=True):
                d = bucket.to_dict()
                lines.append(
                    f"  {d['bucket_name']}: n={d['count']} win={d['win_rate']:.1f}% "
                    f"avg_pnl=${d['avg_pnl']:.4f} avg_edge={d['avg_edge_pct']:.4f} "
                    f"avg_ev={d['avg_ev_cents']:.2f}c"
                )
        lines.append("\n" + "=" * 80)
        summary = self.summary()
        lines.append(f"TOTAL FILLS: {summary['total_fills']}")
        lines.append(f"WIN RATE:    {summary['win_rate_pct']:.2f}%")
        lines.append(f"TOTAL PnL:   ${summary['total_pnl']:.4f}")
        return "\n".join(lines)
