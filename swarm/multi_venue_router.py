"""
Multi-venue order routing optimization.

Evaluates venue liquidity, fees, and latency to derive an optimal split for
large HFT orders across CEX/DEX venues.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List


@dataclass
class VenueQuote:
    venue_id: str
    available_liquidity: Decimal
    fee_bps: Decimal
    latency_ms: float
    price: Decimal


@dataclass
class RouteAllocation:
    venue_id: str
    size_usd: Decimal
    expected_price: Decimal


class MultiVenueRouter:
    def __init__(self) -> None:
        self._quotes: Dict[str, VenueQuote] = {}

    def update_quote(self, quote: VenueQuote) -> None:
        self._quotes[quote.venue_id] = quote

    def optimize(self, total_size_usd: Decimal) -> List[RouteAllocation]:
        venues = sorted(self._quotes.values(), key=lambda v: (v.price + v.fee_bps / Decimal("10000"), v.latency_ms))
        allocations: List[RouteAllocation] = []
        remaining = total_size_usd
        for venue in venues:
            if remaining <= 0:
                break
            size = min(venue.available_liquidity, remaining)
            expected_price = venue.price * (1 + venue.fee_bps / Decimal("10000"))
            allocations.append(RouteAllocation(venue_id=venue.venue_id, size_usd=size, expected_price=expected_price))
            remaining -= size
        return allocations
