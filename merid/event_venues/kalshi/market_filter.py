"""Market Selection Filter — Liquidity, spread, and overlap checks.

Filters Kalshi crypto hourly markets by quality criteria before
attaching agents:

1. **Liquidity floor**: Minimum volume / open interest
2. **Spread threshold**: Max bid-ask spread in cents
3. **Overlap detection**: Groups temporally overlapping brackets on the
   same underlying into a single risk bucket
4. **Settlement recency**: Prefer markets settling soon for tighter pricing

Usage::

    filt = MarketFilter(config)
    candidates = filt.filter_markets(markets)
    groups = filt.group_overlapping(candidates)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.market_filter")


# ── Configuration ────────────────────────────────────────────────────────

@dataclass
class MarketFilterConfig:
    """Quality gates for market selection."""

    # Minimum volume (contracts traded) to consider a market
    min_volume: int = 50

    # Minimum open interest (contracts outstanding)
    min_open_interest: int = 10

    # Maximum bid-ask spread in cents (e.g. 8 = max 8c spread)
    max_spread_cents: int = 12

    # Minimum best-bid price (filter out near-zero contracts)
    min_price_cents: int = 10

    # Maximum best-bid price (filter out near-certain contracts)
    max_price_cents: int = 90

    # Only include markets for these underlyings.
    # Empty list = allow all underlyings (full Kalshi platform coverage).
    allowed_underlyings: List[str] = field(
        default_factory=lambda: []
    )

    # Only include these timeframes.
    # Empty list = allow all timeframes (daily, weekly, monthly, etc.).
    allowed_timeframes: List[str] = field(
        default_factory=lambda: []
    )

    # Overlap window: markets within this many seconds of each other
    # are considered overlapping (same risk bucket)
    overlap_window_seconds: int = 3600


DEFAULT_FILTER_CONFIG = MarketFilterConfig()


# ── Market candidate ─────────────────────────────────────────────────────

@dataclass
class MarketCandidate:
    """A market that has passed or is being evaluated by the filter."""
    ticker: str
    underlying: str         # e.g. "BTC", "ETH"
    timeframe: str          # e.g. "hourly", "15m"
    expiry_ts: float = 0.0  # epoch seconds
    volume: int = 0
    open_interest: int = 0
    best_bid_cents: int = 0
    best_ask_cents: int = 0
    spread_cents: int = 0
    mid_price_cents: int = 0
    category: str = ""

    @property
    def has_book(self) -> bool:
        return self.best_bid_cents > 0 and self.best_ask_cents > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "underlying": self.underlying,
            "timeframe": self.timeframe,
            "expiry_ts": self.expiry_ts,
            "volume": self.volume,
            "open_interest": self.open_interest,
            "best_bid_cents": self.best_bid_cents,
            "best_ask_cents": self.best_ask_cents,
            "spread_cents": self.spread_cents,
            "mid_price_cents": self.mid_price_cents,
        }


@dataclass
class FilterResult:
    """Result of filtering a set of markets."""
    total_input: int = 0
    passed: int = 0
    rejected_volume: int = 0
    rejected_oi: int = 0
    rejected_spread: int = 0
    rejected_price: int = 0
    rejected_underlying: int = 0
    rejected_timeframe: int = 0
    candidates: List[MarketCandidate] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_input": self.total_input,
            "passed": self.passed,
            "rejected_volume": self.rejected_volume,
            "rejected_oi": self.rejected_oi,
            "rejected_spread": self.rejected_spread,
            "rejected_price": self.rejected_price,
            "rejected_underlying": self.rejected_underlying,
            "rejected_timeframe": self.rejected_timeframe,
            "candidates": [c.to_dict() for c in self.candidates],
        }


# ── Overlap group ────────────────────────────────────────────────────────

@dataclass
class OverlapGroup:
    """Group of temporally overlapping markets on the same underlying."""
    underlying: str
    markets: List[MarketCandidate] = field(default_factory=list)
    combined_volume: int = 0
    combined_oi: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "underlying": self.underlying,
            "market_count": len(self.markets),
            "tickers": [m.ticker for m in self.markets],
            "combined_volume": self.combined_volume,
            "combined_oi": self.combined_oi,
        }


# ── Market filter ────────────────────────────────────────────────────────

class MarketFilter:
    """Filters and groups Kalshi crypto markets by quality criteria."""

    def __init__(self, config: Optional[MarketFilterConfig] = None) -> None:
        self._config = config or DEFAULT_FILTER_CONFIG

    @property
    def config(self) -> MarketFilterConfig:
        return self._config

    def evaluate(self, market: MarketCandidate) -> Tuple[bool, str]:
        """Evaluate a single market against all quality gates.

        Returns:
            (passed, rejection_reason) — reason is empty if passed.
        """
        cfg = self._config

        # Underlying check — empty list means allow all underlyings
        if cfg.allowed_underlyings and market.underlying.upper() not in [u.upper() for u in cfg.allowed_underlyings]:
            return False, f"underlying {market.underlying} not allowed"

        # Timeframe check — empty list means allow all timeframes
        if market.timeframe and cfg.allowed_timeframes:
            if market.timeframe.lower() not in [t.lower() for t in cfg.allowed_timeframes]:
                return False, f"timeframe {market.timeframe} not allowed"

        # Volume floor
        if market.volume < cfg.min_volume:
            return False, f"volume {market.volume} < {cfg.min_volume}"

        # Open interest floor
        if market.open_interest < cfg.min_open_interest:
            return False, f"OI {market.open_interest} < {cfg.min_open_interest}"

        # Spread check (only if book data available)
        if market.has_book:
            spread = market.best_ask_cents - market.best_bid_cents
            if spread > cfg.max_spread_cents:
                return False, f"spread {spread}c > {cfg.max_spread_cents}c"

        # Price range check
        mid = market.mid_price_cents
        if mid > 0:
            if mid < cfg.min_price_cents:
                return False, f"price {mid}c < {cfg.min_price_cents}c"
            if mid > cfg.max_price_cents:
                return False, f"price {mid}c > {cfg.max_price_cents}c"

        return True, ""

    def filter_markets(
        self, markets: List[MarketCandidate],
    ) -> FilterResult:
        """Filter a list of markets and return qualifying candidates.

        Args:
            markets: Raw market candidates to evaluate.

        Returns:
            FilterResult with passed candidates and rejection counts.
        """
        result = FilterResult(total_input=len(markets))
        cfg = self._config

        for market in markets:
            passed, reason = self.evaluate(market)
            if passed:
                result.candidates.append(market)
                result.passed += 1
            else:
                if "volume" in reason:
                    result.rejected_volume += 1
                elif "OI" in reason:
                    result.rejected_oi += 1
                elif "spread" in reason:
                    result.rejected_spread += 1
                elif "price" in reason:
                    result.rejected_price += 1
                elif "underlying" in reason:
                    result.rejected_underlying += 1
                elif "timeframe" in reason:
                    result.rejected_timeframe += 1

        return result

    def group_overlapping(
        self, markets: List[MarketCandidate],
    ) -> List[OverlapGroup]:
        """Group temporally overlapping markets by underlying.

        Markets on the same underlying with expiry times within
        `overlap_window_seconds` of each other are grouped together.
        These groups represent a single combined risk bucket.

        Args:
            markets: Filtered market candidates (should already pass quality gates).

        Returns:
            List of OverlapGroup, each containing markets that overlap.
        """
        window = self._config.overlap_window_seconds

        # Group by underlying first
        by_underlying: Dict[str, List[MarketCandidate]] = {}
        for m in markets:
            key = m.underlying.upper()
            by_underlying.setdefault(key, []).append(m)

        groups: List[OverlapGroup] = []

        for underlying, mkts in by_underlying.items():
            # Sort by expiry
            sorted_mkts = sorted(mkts, key=lambda m: m.expiry_ts)

            current_group: Optional[OverlapGroup] = None

            for m in sorted_mkts:
                if current_group is None:
                    current_group = OverlapGroup(underlying=underlying)
                    current_group.markets.append(m)
                else:
                    # Check if this market overlaps with the last in the group
                    last_expiry = current_group.markets[-1].expiry_ts
                    if m.expiry_ts > 0 and last_expiry > 0 and abs(m.expiry_ts - last_expiry) <= window:
                        current_group.markets.append(m)
                    else:
                        # Finalize current group
                        current_group.combined_volume = sum(x.volume for x in current_group.markets)
                        current_group.combined_oi = sum(x.open_interest for x in current_group.markets)
                        groups.append(current_group)
                        current_group = OverlapGroup(underlying=underlying)
                        current_group.markets.append(m)

            if current_group and current_group.markets:
                current_group.combined_volume = sum(x.volume for x in current_group.markets)
                current_group.combined_oi = sum(x.open_interest for x in current_group.markets)
                groups.append(current_group)

        return groups

    def summary(self, markets: List[MarketCandidate]) -> Dict[str, Any]:
        """Filter markets and return a full summary with overlap groups."""
        result = self.filter_markets(markets)
        groups = self.group_overlapping(result.candidates)
        return {
            "filter": result.to_dict(),
            "overlap_groups": [g.to_dict() for g in groups],
            "total_groups": len(groups),
        }
