"""Market Selection Filter — Liquidity, spread, overlap, and edge checks.

Filters Kalshi crypto hourly markets by quality criteria before
attaching agents:

1. **Liquidity floor**: Minimum volume / open interest
2. **Spread threshold**: Max bid-ask spread in cents
3. **Overlap detection**: Groups temporally overlapping brackets on the
   same underlying into a single risk bucket
4. **Settlement recency**: Prefer markets settling soon for tighter pricing
5. **Strike distance**: Keep only strikes within `spot_band_pct` of spot
6. **Edge dead-zone**: Skip markets where win probability is too close to 50%
   (within `min_edge_dead_zone_pct`) to avoid coin-flip bleed
7. **Candidate limit**: Return at most `max_candidates_per_asset` per asset
8. **Relative-volume band**: Reject markets whose volume, expressed as a
   fraction of the *batch maximum*, falls outside
   [``volume_band_min``, ``volume_band_max``].  This keeps the "middle
   regime" of liquidity: avoiding both the illiquid tail (too thin) and
   anomalous spike/auction events (unreliably high).

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


# ── Per-asset, per-timeframe spot band configuration ─────────────────────
#
# Spot band percentage: maximum distance from spot price (as a percentage of
# spot) for strikes to be considered. Tighter bands focus on near-the-money
# contracts with higher liquidity; wider bands capture more candidates but may
# include illiquid far-OTM/ITM strikes.
#
# This configuration mirrors the EDGE_THRESHOLDS pattern in kalshi_continuous_trader.py.
# Each entry is keyed by (asset, timeframe) and specifies the band percentage
# as a decimal (e.g., 0.25 = ±25% from spot).
#
# Values are initially set to the legacy default (12.5%) and should be updated
# based on optimization analysis via scripts/optimize_spot_bands.py.
#
SPOT_BANDS: Dict[Tuple[str, str], float] = {
    # BTC — Liquid, tight spreads → tighter bands for quality focus
    ("BTC", "15m"): 0.20,    # 20% - tight focus on near-the-money
    ("BTC", "1h"): 0.25,     # 25% - balance quality and quantity
    ("BTC", "daily"): 0.30,  # 30% - wider for daily strikes
    ("BTC", "weekly"): 0.35, # 35% - capture weekly candidates
    ("BTC", "monthly"): 0.40, # 40% - sufficient long-dated strikes
    # ETH — Moderately liquid → balanced bands
    ("ETH", "15m"): 0.25,    # 25% - moderate focus
    ("ETH", "1h"): 0.30,     # 30% - good candidate pool
    ("ETH", "daily"): 0.35,  # 35% - daily coverage
    ("ETH", "weekly"): 0.40, # 40% - weekly strikes
    ("ETH", "monthly"): 0.45, # 45% - long-dated coverage
    # SOL — Less liquid → wider bands for throughput
    ("SOL", "15m"): 0.30,    # 30% - ensure candidates
    ("SOL", "1h"): 0.35,     # 35% - adequate pool
    ("SOL", "daily"): 0.40,  # 40% - daily coverage
    ("SOL", "weekly"): 0.45, # 45% - weekly strikes
    ("SOL", "monthly"): 0.50, # 50% - max coverage
    # XRP — Similar to SOL, wider for liquidity
    ("XRP", "15m"): 0.30,    # 30% - sufficient candidates
    ("XRP", "1h"): 0.35,     # 35% - good pool
    ("XRP", "daily"): 0.40,  # 40% - daily strikes
    ("XRP", "weekly"): 0.45, # 45% - weekly coverage
    ("XRP", "monthly"): 0.50, # 50% - long-dated strikes
    # DOGE — Least liquid → widest bands for candidate availability
    ("DOGE", "15m"): 0.35,   # 35% - wide search needed
    ("DOGE", "1h"): 0.40,    # 40% - ensure pool
    ("DOGE", "daily"): 0.45, # 45% - daily coverage
    ("DOGE", "weekly"): 0.50, # 50% - weekly strikes
    ("DOGE", "monthly"): 0.50, # 50% - max coverage
}


def get_spot_band(asset: str, timeframe: str, default: float = 12.5) -> float:
    """Get the spot band percentage for a given (asset, timeframe) pair.

    Args:
        asset: Asset symbol (e.g., "BTC", "ETH")
        timeframe: Timeframe (e.g., "15m", "1h", "daily")
        default: Fallback value if no specific band is configured (default: 12.5%)
                 Can be provided as percentage (12.5) or decimal (0.125)

    Returns:
        Spot band percentage (e.g., 12.5 for ±12.5%, NOT 0.125)
    """
    key = (asset.upper(), timeframe.lower())
    band = SPOT_BANDS.get(key)

    if band is not None:
        # SPOT_BANDS stores decimals (0.125), convert to percentage for evaluate()
        return band * 100.0 if band < 1.0 else band

    # Use default, no conversion needed (already in percentage form)
    return default


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

    # ── Tighter-market settings ────────────────────────────────────────

    # Maximum distance from spot price as a percentage of spot.
    # 0.0 = disabled.  Recommended: 12.5 for intraday (15M/1H).
    spot_band_pct: float = 12.5

    # "Dead zone" around 50% win-probability: markets whose mid-price is
    # within this many percentage points of 50¢ are skipped (coin-flip bleed).
    # 0.0 = disabled.  E.g. 3.0 skips markets with mid in [47¢, 53¢].
    min_edge_dead_zone_pct: float = 3.0

    # Maximum candidates to return per underlying asset after all other
    # filters.  The candidates closest to spot are preferred.  0 = no limit.
    max_candidates_per_asset: int = 5

    # ── Relative-volume band ───────────────────────────────────────────────
    #
    # "Relative volume" for a candidate is defined as:
    #
    #   volume_fraction = market.volume / max(m.volume for m in batch)
    #
    # where the denominator is the maximum raw volume across ALL markets
    # submitted to filter_markets() in a single call — computed before any
    # other gate removes markets from the batch.  This gives each market a
    # normalised score in [0, 1] reflecting where it sits in the current
    # liquidity distribution.
    #
    # The band [volume_band_min, volume_band_max] retains only markets that
    # fall within that relative-volume range.  The design intent is:
    #   - Reject the illiquid tail (volume_fraction < min): very thin markets
    #     where spreads are wide and fills are uncertain.
    #   - Reject anomalous spikes (volume_fraction > max): markets showing
    #     unusually high activity relative to peers, which may indicate
    #     news events, auctions, or data artifacts that distort edge estimates.
    #   - Live in the middle regime: established, liquid, well-behaved markets.
    #
    # Setting volume_band_min=0.0 and volume_band_max=1.0 disables the filter
    # entirely (every market passes regardless of relative volume).
    # Recommended production values: volume_band_min=0.4, volume_band_max=0.8
    volume_band_min: float = 0.0  # 0.0 = no lower bound (disabled)
    volume_band_max: float = 1.0  # 1.0 = no upper bound (disabled)


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
    # Strike price of the contract (underlying units, e.g. USD for BTC)
    strike_price: Optional[float] = None
    # Current spot price of the underlying (same units as strike_price)
    spot_price: Optional[float] = None
    # Per-side best prices from the Kalshi order book (decimal, 0.0–1.0).
    # In a binary YES/NO market: best_yes_ask ≈ 1 - best_no_bid and vice versa.
    # These fields are populated by enrichment steps; None means no data yet.
    best_yes_bid: Optional[float] = None
    best_yes_ask: Optional[float] = None
    best_no_bid: Optional[float] = None
    best_no_ask: Optional[float] = None
    # Edge/model enrichment fields (populated by signal layer or enrichment step).
    # ``edge_pct`` is the signed edge as a percentage of implied probability;
    # ``model_prob`` is the model-estimated probability (0–1).
    edge_pct: Optional[float] = None
    model_prob: Optional[float] = None

    @property
    def has_book(self) -> bool:
        return self.best_bid_cents > 0 and self.best_ask_cents > 0

    @property
    def distance_from_spot_pct(self) -> Optional[float]:
        """Absolute percentage distance of strike from spot.

        Returns None if strike_price or spot_price is not available or spot is zero.
        """
        if self.strike_price is None or self.spot_price is None or self.spot_price == 0:
            return None
        return abs(self.strike_price - self.spot_price) / self.spot_price * 100.0

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
            "strike_price": self.strike_price,
            "spot_price": self.spot_price,
            "best_yes_bid": self.best_yes_bid,
            "best_yes_ask": self.best_yes_ask,
            "best_no_bid": self.best_no_bid,
            "best_no_ask": self.best_no_ask,
            "edge_pct": self.edge_pct,
            "model_prob": self.model_prob,
        }

    def __getattr__(self, name: str) -> Any:
        """
        Gracefully handle missing best_* fields for legacy instances.

        Older pickled/constructed objects might not carry the best_yes/no fields;
        return None for those attributes instead of raising AttributeError so
        downstream edge calculations remain safe.
        """
        if name in ("best_yes_bid", "best_yes_ask", "best_no_bid", "best_no_ask",
                    "edge_pct", "model_prob"):
            return None
        raise AttributeError(f"{type(self).__name__!s} has no attribute {name!r}")


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
    rejected_distance: int = 0       # struck too far from spot
    rejected_edge_deadzone: int = 0  # mid-price too close to 50¢
    rejected_volume_band: int = 0    # outside relative-volume band
    rejected_missing_spot: int = 0   # spot_price required but missing
    capped_per_asset: int = 0        # dropped by max_candidates_per_asset limit
    candidates: List[MarketCandidate] = field(default_factory=list)

    @property
    def volume_band_block_rate(self) -> float:
        """Fraction of input markets blocked purely by the relative-volume band.

        Useful for auditing whether the band is hitting a meaningful fraction
        of otherwise-eligible candidates (typically 15–40% is healthy;
        < 10% suggests the band is too loose; > 60% may be too restrictive).
        """
        if self.total_input == 0:
            return 0.0
        return self.rejected_volume_band / self.total_input

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
            "rejected_distance": self.rejected_distance,
            "rejected_edge_deadzone": self.rejected_edge_deadzone,
            "rejected_volume_band": self.rejected_volume_band,
            "rejected_missing_spot": self.rejected_missing_spot,
            "volume_band_block_rate": round(self.volume_band_block_rate, 4),
            "capped_per_asset": self.capped_per_asset,
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

        # Strike distance check — skip if strike too far from spot
        # Use dynamic per-(asset, timeframe) band if available, otherwise fall back to config default
        spot_band = get_spot_band(market.underlying, market.timeframe, default=cfg.spot_band_pct)
        if spot_band > 0:
            dist = market.distance_from_spot_pct
            # dist is None when strike_price or spot_price is missing.
            # If strike_price is missing we cannot compute distance, so pass the
            # candidate through (the Kelly/edge layer will handle it later).
            # Only hard-reject when we have a strike but no spot price, because
            # that means our spot feed is broken and we shouldn't trade.
            if dist is None:
                if market.strike_price is not None and (
                    market.spot_price is None or market.spot_price <= 0
                ):
                    return False, (
                        f"spot_price missing but distance check enabled (±{spot_band:.1f}% band)"
                    )
                # strike_price is None — skip distance check, let candidate through
            elif dist > spot_band:
                return False, (
                    f"distance {dist:.1f}% from spot exceeds band ±{spot_band:.1f}%"
                )

        # Edge dead-zone check — skip near-50% coin-flips
        if cfg.min_edge_dead_zone_pct > 0 and mid > 0:
            dist_from_50 = abs(mid - 50)
            if dist_from_50 < cfg.min_edge_dead_zone_pct:
                return False, (
                    f"mid {mid}c within dead zone ±{cfg.min_edge_dead_zone_pct}c of 50c"
                )

        return True, ""

    def filter_markets(
        self, markets: List[MarketCandidate],
    ) -> FilterResult:
        """Filter a list of markets and return qualifying candidates.

        Applies quality gates via :meth:`evaluate`, then limits candidates
        to ``max_candidates_per_asset`` per underlying (preferring those
        closest to spot when ``spot_price`` is available).

        The relative-volume band (if configured) is applied first, before
        any per-market quality gate.  The denominator for the band is the
        maximum volume across ALL input markets in this call, so the score
        is stable regardless of which other filters are active.

        Args:
            markets: Raw market candidates to evaluate.

        Returns:
            FilterResult with passed candidates and rejection counts.
        """
        result = FilterResult(total_input=len(markets))
        cfg = self._config

        # Pre-compute the relative-volume denominator for the entire batch.
        # The band is only applied when at least one bound is non-trivial.
        check_vol_band = cfg.volume_band_min > 0.0 or cfg.volume_band_max < 1.0
        max_volume: int = max((m.volume for m in markets), default=0) if markets else 0

        for market in markets:
            # ── Relative-volume band (batch-level check) ──────────────────
            # Applied before per-market gates so that the rejection bucket is
            # exclusive (a market that fails the band is not also counted as a
            # volume-floor or spread rejection).
            if check_vol_band and max_volume > 0:
                rel_vol = market.volume / max_volume
                if rel_vol < cfg.volume_band_min or rel_vol > cfg.volume_band_max:
                    result.rejected_volume_band += 1
                    continue

            passed, reason = self.evaluate(market)
            if passed:
                result.candidates.append(market)
                result.passed += 1
            else:
                if "spot_price missing" in reason:
                    result.rejected_missing_spot += 1
                elif "volume" in reason:
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
                elif "distance" in reason:
                    result.rejected_distance += 1
                elif "dead zone" in reason:
                    result.rejected_edge_deadzone += 1

        # Per-asset candidate cap: keep the top N closest to spot
        if cfg.max_candidates_per_asset > 0:
            result.candidates, capped = self._cap_candidates_per_asset(
                result.candidates, cfg.max_candidates_per_asset
            )
            result.capped_per_asset += capped
            result.passed = len(result.candidates)

        return result

    @staticmethod
    def _cap_candidates_per_asset(
        candidates: List[MarketCandidate], max_per_asset: int
    ) -> Tuple[List[MarketCandidate], int]:
        """Keep at most *max_per_asset* candidates per underlying.

        Candidates with ``distance_from_spot_pct`` available are sorted
        nearest-first; those without distance data retain their original order.

        Returns:
            (kept, dropped_count)
        """
        by_asset: Dict[str, List[MarketCandidate]] = {}
        for m in candidates:
            by_asset.setdefault(m.underlying.upper(), []).append(m)

        kept: List[MarketCandidate] = []
        dropped = 0
        for asset_candidates in by_asset.values():
            # Sort nearest-to-spot first; candidates without distance data go last.
            # Tuple key: (True if distance is None, distance or 0) — None sorts after real values.
            asset_candidates.sort(
                key=lambda m: (m.distance_from_spot_pct is None, m.distance_from_spot_pct or 0.0)
            )
            kept.extend(asset_candidates[:max_per_asset])
            dropped += max(0, len(asset_candidates) - max_per_asset)
        return kept, dropped

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
