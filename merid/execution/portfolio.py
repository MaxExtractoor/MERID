"""Portfolio aggregation and PnL tracking across all venues."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from merid.execution.base import Position


@dataclass(slots=True)
class AggregatedPosition:
    symbol: str
    total_size: float
    avg_entry_price: float
    unrealized_pnl: float
    venue_breakdown: Dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class PortfolioSnapshot:
    positions: List[AggregatedPosition]
    total_unrealized_pnl: float
    total_notional: float
    metadata: Dict[str, Any] = field(default_factory=dict)


class PortfolioAggregator:
    """Aggregates positions and PnL across all venue executors."""

    def __init__(self) -> None:
        self._price_cache: Dict[str, float] = {}

    async def aggregate(self, venue_positions: Dict[str, List[Position]]) -> PortfolioSnapshot:
        """Merge positions from multiple venues into a portfolio snapshot."""
        aggregated: Dict[str, AggregatedPosition] = {}
        for venue, positions in venue_positions.items():
            for pos in positions:
                if pos.symbol not in aggregated:
                    aggregated[pos.symbol] = AggregatedPosition(
                        symbol=pos.symbol,
                        total_size=0.0,
                        avg_entry_price=0.0,
                        unrealized_pnl=0.0,
                        venue_breakdown={},
                    )
                agg = aggregated[pos.symbol]
                agg.total_size += pos.size
                agg.unrealized_pnl += pos.pnl
                agg.venue_breakdown[venue] = agg.venue_breakdown.get(venue, 0.0) + pos.size

                # Weighted average entry price
                if agg.total_size != 0:
                    agg.avg_entry_price = (agg.avg_entry_price * (agg.total_size - pos.size) + pos.entry_price * pos.size) / agg.total_size

        total_unrealized_pnl = sum(p.unrealized_pnl for p in aggregated.values())
        total_notional = sum(abs(p.total_size) * self._price_cache.get(p.symbol, 0) for p in aggregated.values())

        return PortfolioSnapshot(
            positions=list(aggregated.values()),
            total_unrealized_pnl=total_unrealized_pnl,
            total_notional=total_notional,
            metadata={"venues": list(venue_positions.keys())},
        )

    def update_price_cache(self, symbol: str, price: float) -> None:
        """Cache the latest price for a symbol (used for notional calculations)."""
        self._price_cache[symbol] = price
