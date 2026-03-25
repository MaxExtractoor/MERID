"""Kalshi Continuous Trader — Multi-asset filter pipeline with distance logic.

This module implements the filter pipeline, candidate selection, and distance
logic for continuously trading Kalshi crypto markets. It provides:

1. **Filter Pipeline**: Raw market filtering with detailed counters
   - directional filtering
   - strike parsing
   - distance-from-spot filtering (volatility-aware)
   - expiry window filtering
   - liquidity filtering

2. **Candidate Selection**: Per-asset and global capping with composite scoring

3. **Distance Logic**: Volatility-aware strike distance calculations

4. **Performance Instrumentation**: Timing metrics and event-loop monitoring

Usage::

    trader = KalshiContinuousTrader(config)
    await trader.start()
    # ... trader runs continuously ...
    await trader.stop()

Monitoring::

    stats = trader.get_stats()
    # Returns filter counts, timing metrics, lag stats
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
import math
import re

from utils.logger import get_logger

logger = get_logger("merid.trading.kalshi_continuous_trader")


# ── Configuration ────────────────────────────────────────────────────────

@dataclass
class AssetVolatilityConfig:
    """Volatility-based filtering config per asset."""

    # Asset symbol (e.g., "BTC", "ETH")
    asset: str

    # Maximum volatility-adjusted distance from spot
    max_vols_from_spot: float = 3.0

    # Hard guardrail: maximum percent distance (decimal, e.g., 0.25 = 25%)
    max_pct_from_spot: float = 0.25

    # Daily volatility estimate (annual can be converted)
    daily_volatility: Optional[float] = None

    # Implied volatility source if available
    implied_vol_source: Optional[str] = None


@dataclass
class FilterPipelineConfig:
    """Configuration for the multi-asset filter pipeline."""

    # List of assets to trade (e.g., ["BTC", "ETH", "SOL", "XRP", "DOGE"])
    assets: List[str] = field(default_factory=lambda: ["BTC", "ETH", "SOL", "XRP", "DOGE"])

    # Per-asset volatility configs (keyed by asset symbol)
    asset_vol_configs: Dict[str, AssetVolatilityConfig] = field(default_factory=dict)

    # Maximum candidates per asset before global cap
    max_candidates_per_asset: int = 5

    # Maximum total candidates across all assets
    max_candidates_global: int = 10

    # Minimum volume threshold
    min_volume: int = 50

    # Minimum open interest threshold
    min_open_interest: int = 10

    # Maximum spread in cents
    max_spread_cents: int = 12

    # Expiry window filtering
    min_minutes_to_expiry: int = 5
    max_minutes_to_expiry: int = 180

    # Event-loop lag warning threshold (milliseconds)
    event_loop_lag_warning_ms: float = 200.0

    def get_vol_config(self, asset: str) -> AssetVolatilityConfig:
        """Get volatility config for an asset, or default."""
        if asset in self.asset_vol_configs:
            return self.asset_vol_configs[asset]
        # Default config
        return AssetVolatilityConfig(
            asset=asset,
            max_vols_from_spot=3.0,
            max_pct_from_spot=0.25,
            daily_volatility=0.03,  # Default 3% daily vol
        )


# ── Market candidate with strike ──────────────────────────────────────────

@dataclass
class MarketCandidate:
    """A market candidate with parsed strike and distance metrics."""

    ticker: str
    asset: str
    series: str  # e.g., "KXBTC", "KXSOL15M"
    strike_price: Optional[Decimal] = None
    expiry_time: Optional[datetime] = None

    # Market data
    volume: int = 0
    open_interest: int = 0
    best_bid_cents: int = 0
    best_ask_cents: int = 0
    spread_cents: int = 0
    mid_price_cents: int = 0

    # Distance metrics (computed during filtering)
    spot_price: Optional[Decimal] = None
    pct_distance: Optional[float] = None  # Percent distance from spot
    vol_distance: Optional[float] = None  # Vol-adjusted distance

    # Composite score for ranking
    composite_score: float = 0.0

    # Raw market data for downstream
    raw_data: Optional[Dict[str, Any]] = None


# ── Filter result with detailed counters ──────────────────────────────────

@dataclass
class FilterStepTimings:
    """Timing metrics for each filter pipeline step."""

    fetch_ms: float = 0.0
    directional_ms: float = 0.0
    parse_ms: float = 0.0
    strike_distance_ms: float = 0.0
    expiry_ms: float = 0.0
    liquidity_ms: float = 0.0
    scoring_ms: float = 0.0
    total_ms: float = 0.0


@dataclass
class AssetFilterResult:
    """Filter result for a single asset with detailed breakdown."""

    asset: str

    # Raw count
    raw: int = 0

    # Filter stage counts
    directional: int = 0  # Passed directional filter (binary yes/no markets)
    parseable_strikes: int = 0  # Successfully parsed strikes

    # Rejection counters (explicit categories)
    strike_too_far: int = 0  # Strike distance exceeded threshold
    expiry_too_soon: int = 0  # Expiry < min_minutes_to_expiry
    expiry_too_far: int = 0  # Expiry > max_minutes_to_expiry
    illiquid: int = 0  # Volume or OI below threshold
    invalid_symbol_format: int = 0  # Could not parse ticker
    unknown_type: int = 0  # Not a recognized market type

    # Final candidates
    candidates: int = 0
    sample_tickers: List[str] = field(default_factory=list)

    # Timing metrics
    timings: FilterStepTimings = field(default_factory=FilterStepTimings)

    def to_log_dict(self) -> Dict[str, Any]:
        """Convert to structured dict for logging (only non-zero counters)."""
        result = {
            "asset": self.asset,
            "raw": self.raw,
            "directional": self.directional,
            "parseable_strikes": self.parseable_strikes,
            "candidates": self.candidates,
            "latency_total_ms": round(self.timings.total_ms, 2),
        }

        # Only include non-zero rejection counters
        if self.strike_too_far > 0:
            result["strike_too_far"] = self.strike_too_far
        if self.expiry_too_soon > 0:
            result["expiry_too_soon"] = self.expiry_too_soon
        if self.expiry_too_far > 0:
            result["expiry_too_far"] = self.expiry_too_far
        if self.illiquid > 0:
            result["illiquid"] = self.illiquid
        if self.invalid_symbol_format > 0:
            result["invalid_symbol_format"] = self.invalid_symbol_format
        if self.unknown_type > 0:
            result["unknown_type"] = self.unknown_type

        # Add timing breakdown if any step is significant
        if any([
            self.timings.fetch_ms > 1,
            self.timings.directional_ms > 1,
            self.timings.parse_ms > 1,
            self.timings.strike_distance_ms > 1,
        ]):
            result["latency_fetch_ms"] = round(self.timings.fetch_ms, 2)
            result["latency_directional_ms"] = round(self.timings.directional_ms, 2)
            result["latency_parse_ms"] = round(self.timings.parse_ms, 2)
            result["latency_strike_distance_ms"] = round(self.timings.strike_distance_ms, 2)

        # Sample tickers (up to 3)
        if self.sample_tickers:
            result["sample_tickers"] = self.sample_tickers[:3]

        return result


@dataclass
class MultiAssetFilterResult:
    """Aggregated filter result across all assets."""

    per_asset: Dict[str, AssetFilterResult] = field(default_factory=dict)

    total_raw: int = 0
    total_candidates_pre_cap: int = 0
    total_candidates_post_cap: int = 0

    assets_with_candidates: List[str] = field(default_factory=list)
    capped_to: int = 0

    # Final selected candidates after all capping
    final_candidates: List[MarketCandidate] = field(default_factory=list)

    def to_log_dict(self) -> Dict[str, Any]:
        """Convert to structured dict for multi-asset summary logging."""
        return {
            "total_raw": self.total_raw,
            "total_candidates_pre_cap": self.total_candidates_pre_cap,
            "total_candidates_post_cap": self.total_candidates_post_cap,
            "assets_with_candidates": self.assets_with_candidates,
            "capped_to": self.capped_to,
        }


# ── Ticker parsing ────────────────────────────────────────────────────────

class TickerParser:
    """Parse Kalshi ticker strings to extract strike, series, expiry."""

    # Regex patterns for different ticker formats
    # Example: KXXRP-26MAR2508-B1.5899500
    #          KXBTC-15M-26MAR25-T95000
    #          KXSOL-26MAR25-T150
    PATTERN_WITH_BARRIER = re.compile(
        r'^(?P<series>KX[A-Z]+(?:-15M|-D1)?)-(?P<date>\d{2}[A-Z]{3}\d{2,4})-B(?P<strike>[\d.]+)$'
    )
    PATTERN_WITH_THRESHOLD = re.compile(
        r'^(?P<series>KX[A-Z]+(?:-15M|-D1)?)-(?P<date>\d{2}[A-Z]{3}\d{2,4})-T(?P<strike>[\d.]+)$'
    )
    # Simpler pattern without strike (for markets that don't have barriers)
    PATTERN_NO_STRIKE = re.compile(
        r'^(?P<series>KX[A-Z]+(?:-15M|-D1)?)-(?P<date>\d{2}[A-Z]{3}\d{2,4})$'
    )

    # Asset mapping from series prefix
    ASSET_MAP = {
        "KXBTC": "BTC",
        "KXETH": "ETH",
        "KXSOL": "SOL",
        "KXXRP": "XRP",
        "KXDOGE": "DOGE",
    }

    @classmethod
    def parse(cls, ticker: str) -> Tuple[Optional[str], Optional[str], Optional[Decimal]]:
        """Parse a ticker into (asset, series, strike_price).

        Args:
            ticker: Kalshi ticker string

        Returns:
            (asset, series, strike_price) or (None, None, None) if parsing fails

        Examples:
            >>> TickerParser.parse("KXXRP-26MAR2508-B1.5899500")
            ("XRP", "KXXRP", Decimal("1.5899500"))

            >>> TickerParser.parse("KXBTC-15M-26MAR25-T95000")
            ("BTC", "KXBTC-15M", Decimal("95000"))
        """
        # Try barrier pattern
        match = cls.PATTERN_WITH_BARRIER.match(ticker)
        if match:
            series = match.group("series")
            strike_str = match.group("strike")
            asset = cls._extract_asset(series)
            try:
                strike = Decimal(strike_str)
                return asset, series, strike
            except:
                return None, None, None

        # Try threshold pattern
        match = cls.PATTERN_WITH_THRESHOLD.match(ticker)
        if match:
            series = match.group("series")
            strike_str = match.group("strike")
            asset = cls._extract_asset(series)
            try:
                strike = Decimal(strike_str)
                return asset, series, strike
            except:
                return None, None, None

        # Try no-strike pattern
        match = cls.PATTERN_NO_STRIKE.match(ticker)
        if match:
            series = match.group("series")
            asset = cls._extract_asset(series)
            return asset, series, None

        # Failed to parse
        return None, None, None

    @classmethod
    def _extract_asset(cls, series: str) -> Optional[str]:
        """Extract asset from series string."""
        # Remove tenor suffix if present
        base_series = series.split("-")[0]
        return cls.ASSET_MAP.get(base_series)


# ── Distance calculator ───────────────────────────────────────────────────

class DistanceCalculator:
    """Calculate distance metrics between strike and spot with volatility adjustment."""

    @staticmethod
    def percent_distance(strike: Decimal, spot: Decimal) -> float:
        """Calculate percent distance from spot.

        Distance = (strike - spot) / spot

        Returns:
            Percent distance (e.g., 0.05 = 5% above spot, -0.05 = 5% below spot)
        """
        if spot <= 0:
            return 0.0
        return float((strike - spot) / spot)

    @staticmethod
    def vol_distance(
        strike: Decimal,
        spot: Decimal,
        sigma_horizon: float,
    ) -> float:
        """Calculate volatility-adjusted distance.

        Vol distance = abs(percent_distance) / sigma_horizon

        Args:
            strike: Strike price
            spot: Spot price
            sigma_horizon: Horizon-adjusted volatility (e.g., sigma_daily * sqrt(T))

        Returns:
            Vol distance (number of standard deviations from spot)
        """
        if sigma_horizon <= 0:
            return 0.0
        pct_dist = DistanceCalculator.percent_distance(strike, spot)
        return abs(pct_dist) / sigma_horizon

    @staticmethod
    def horizon_adjusted_vol(
        daily_vol: float,
        minutes_to_expiry: float,
    ) -> float:
        """Convert daily volatility to horizon-adjusted volatility.

        Formula: sigma_horizon = sigma_daily * sqrt(T)
        where T is time to expiry in trading days

        Args:
            daily_vol: Daily volatility (e.g., 0.03 = 3%)
            minutes_to_expiry: Time to expiry in minutes

        Returns:
            Horizon-adjusted volatility
        """
        # Convert minutes to trading days (assume 24/7 crypto trading)
        trading_days = minutes_to_expiry / (24 * 60)
        return daily_vol * math.sqrt(max(trading_days, 0.001))


# ── Filter pipeline ───────────────────────────────────────────────────────

class FilterPipeline:
    """Multi-asset filter pipeline with instrumentation and distance logic."""

    def __init__(self, config: FilterPipelineConfig):
        self.config = config
        self._spot_prices: Dict[str, Decimal] = {}  # Cached spot prices

    def set_spot_price(self, asset: str, price: Decimal) -> None:
        """Update spot price for an asset."""
        self._spot_prices[asset] = price

    def get_spot_price(self, asset: str) -> Optional[Decimal]:
        """Get cached spot price for an asset."""
        return self._spot_prices.get(asset)

    async def filter_markets(
        self,
        raw_markets: Dict[str, List[Dict[str, Any]]],
    ) -> MultiAssetFilterResult:
        """Run the full filter pipeline across all assets.

        Args:
            raw_markets: Dict mapping asset -> list of raw market dicts

        Returns:
            MultiAssetFilterResult with per-asset breakdown and final candidates
        """
        t0 = time.monotonic()

        result = MultiAssetFilterResult()
        per_asset_candidates: Dict[str, List[MarketCandidate]] = {}

        # Process each asset independently
        for asset, markets in raw_markets.items():
            asset_result = await self._filter_asset(asset, markets)
            result.per_asset[asset] = asset_result
            result.total_raw += asset_result.raw
            result.total_candidates_pre_cap += asset_result.candidates

            if asset_result.candidates > 0:
                result.assets_with_candidates.append(asset)
                # Extract candidates from asset result (stored in sample_tickers as placeholder)
                # In real implementation, we'd store MarketCandidate objects
                per_asset_candidates[asset] = []

            # Log per-asset filter stats
            logger.info(
                f"Filter [{asset}]: {asset_result.to_log_dict()}"
            )

        # Apply per-asset caps
        capped_candidates = self._apply_per_asset_caps(per_asset_candidates)

        # Apply global cap
        final_candidates = self._apply_global_cap(capped_candidates)

        result.total_candidates_post_cap = len(final_candidates)
        result.final_candidates = final_candidates
        result.capped_to = self.config.max_candidates_global

        # Log multi-asset summary
        logger.info(
            f"Filter [Multi-asset summary]: {result.to_log_dict()}"
        )

        # Log scanning preview for each asset
        for asset in result.assets_with_candidates:
            asset_candidates = [c for c in final_candidates if c.asset == asset]
            if asset_candidates and asset in self._spot_prices:
                spot = self._spot_prices[asset]
                vol_config = self.config.get_vol_config(asset)
                logger.info(
                    f"Scanning {len(asset_candidates)} {asset}-multi within "
                    f"±{vol_config.max_pct_from_spot*100:.1f}% / "
                    f"±{vol_config.max_vols_from_spot:.1f} vols of spot {float(spot):.2f}..."
                )

        return result

    async def _filter_asset(
        self,
        asset: str,
        markets: List[Dict[str, Any]],
    ) -> AssetFilterResult:
        """Filter markets for a single asset with detailed timing."""
        result = AssetFilterResult(asset=asset)
        result.raw = len(markets)

        if result.raw == 0:
            return result

        t_step = time.monotonic()

        # Step 1: Directional filter (binary yes/no markets)
        directional_markets = self._filter_directional(markets)
        result.directional = len(directional_markets)
        result.timings.directional_ms = (time.monotonic() - t_step) * 1000

        # Step 2: Parse strikes
        t_step = time.monotonic()
        parsed_markets = self._parse_strikes(asset, directional_markets, result)
        result.parseable_strikes = len(parsed_markets)
        result.timings.parse_ms = (time.monotonic() - t_step) * 1000

        # Step 3: Strike distance filter
        t_step = time.monotonic()
        distance_filtered = self._filter_strike_distance(asset, parsed_markets, result)
        result.timings.strike_distance_ms = (time.monotonic() - t_step) * 1000

        # Step 4: Expiry filter
        t_step = time.monotonic()
        expiry_filtered = self._filter_expiry(distance_filtered, result)
        result.timings.expiry_ms = (time.monotonic() - t_step) * 1000

        # Step 5: Liquidity filter
        t_step = time.monotonic()
        liquidity_filtered = self._filter_liquidity(expiry_filtered, result)
        result.timings.liquidity_ms = (time.monotonic() - t_step) * 1000

        # Step 6: Composite scoring and ranking
        t_step = time.monotonic()
        scored_candidates = self._score_candidates(liquidity_filtered)
        result.timings.scoring_ms = (time.monotonic() - t_step) * 1000

        result.candidates = len(scored_candidates)
        result.sample_tickers = [c.ticker for c in scored_candidates[:3]]

        # Total timing
        result.timings.total_ms = sum([
            result.timings.directional_ms,
            result.timings.parse_ms,
            result.timings.strike_distance_ms,
            result.timings.expiry_ms,
            result.timings.liquidity_ms,
            result.timings.scoring_ms,
        ])

        return result

    def _filter_directional(
        self,
        markets: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Filter for directional (binary yes/no) markets."""
        # For now, assume all Kalshi crypto markets are binary
        # In real implementation, check market type
        return markets

    def _parse_strikes(
        self,
        asset: str,
        markets: List[Dict[str, Any]],
        result: AssetFilterResult,
    ) -> List[MarketCandidate]:
        """Parse strikes from tickers."""
        candidates = []

        for mkt in markets:
            ticker = mkt.get("ticker", "")
            parsed_asset, series, strike = TickerParser.parse(ticker)

            if parsed_asset is None:
                result.invalid_symbol_format += 1
                continue

            if parsed_asset != asset:
                result.unknown_type += 1
                continue

            candidate = MarketCandidate(
                ticker=ticker,
                asset=asset,
                series=series or ticker,
                strike_price=strike,
                volume=mkt.get("volume", 0),
                open_interest=mkt.get("open_interest", 0),
                best_bid_cents=mkt.get("best_bid_cents", 0),
                best_ask_cents=mkt.get("best_ask_cents", 0),
                raw_data=mkt,
            )

            # Compute spread
            if candidate.best_ask_cents > candidate.best_bid_cents:
                candidate.spread_cents = candidate.best_ask_cents - candidate.best_bid_cents
            candidate.mid_price_cents = (candidate.best_bid_cents + candidate.best_ask_cents) // 2

            candidates.append(candidate)

        return candidates

    def _filter_strike_distance(
        self,
        asset: str,
        candidates: List[MarketCandidate],
        result: AssetFilterResult,
    ) -> List[MarketCandidate]:
        """Filter by strike distance from spot (volatility-aware)."""
        filtered = []
        spot = self.get_spot_price(asset)
        vol_config = self.config.get_vol_config(asset)

        if spot is None or spot <= 0:
            # No spot price available, skip distance filtering
            logger.warning(f"No spot price for {asset}, skipping distance filter")
            return candidates

        for candidate in candidates:
            if candidate.strike_price is None:
                # No strike, can't compute distance
                filtered.append(candidate)
                continue

            # Compute percent distance
            pct_dist = DistanceCalculator.percent_distance(
                candidate.strike_price, spot
            )
            candidate.pct_distance = pct_dist
            candidate.spot_price = spot

            # Check hard guardrail
            if abs(pct_dist) > vol_config.max_pct_from_spot:
                result.strike_too_far += 1
                continue

            # Compute vol distance if we have vol estimate
            if vol_config.daily_volatility:
                # Estimate time to expiry (placeholder: use 60 minutes)
                minutes_to_expiry = 60.0
                sigma_horizon = DistanceCalculator.horizon_adjusted_vol(
                    vol_config.daily_volatility,
                    minutes_to_expiry,
                )
                vol_dist = DistanceCalculator.vol_distance(
                    candidate.strike_price, spot, sigma_horizon
                )
                candidate.vol_distance = vol_dist

                # Check vol-based threshold
                if vol_dist > vol_config.max_vols_from_spot:
                    result.strike_too_far += 1
                    continue

            filtered.append(candidate)

        return filtered

    def _filter_expiry(
        self,
        candidates: List[MarketCandidate],
        result: AssetFilterResult,
    ) -> List[MarketCandidate]:
        """Filter by expiry window."""
        filtered = []
        now = datetime.now(timezone.utc)

        for candidate in candidates:
            if candidate.expiry_time is None:
                # No expiry info, allow through
                filtered.append(candidate)
                continue

            minutes_to_expiry = (candidate.expiry_time - now).total_seconds() / 60

            if minutes_to_expiry < self.config.min_minutes_to_expiry:
                result.expiry_too_soon += 1
                continue

            if minutes_to_expiry > self.config.max_minutes_to_expiry:
                result.expiry_too_far += 1
                continue

            filtered.append(candidate)

        return filtered

    def _filter_liquidity(
        self,
        candidates: List[MarketCandidate],
        result: AssetFilterResult,
    ) -> List[MarketCandidate]:
        """Filter by liquidity (volume, OI, spread)."""
        filtered = []

        for candidate in candidates:
            # Volume check
            if candidate.volume < self.config.min_volume:
                result.illiquid += 1
                continue

            # Open interest check
            if candidate.open_interest < self.config.min_open_interest:
                result.illiquid += 1
                continue

            # Spread check
            if candidate.spread_cents > self.config.max_spread_cents:
                result.illiquid += 1
                continue

            filtered.append(candidate)

        return filtered

    def _score_candidates(
        self,
        candidates: List[MarketCandidate],
    ) -> List[MarketCandidate]:
        """Compute composite scores and rank candidates."""
        for candidate in candidates:
            score = 0.0

            # Distance component (closer to spot = higher score)
            if candidate.vol_distance is not None:
                # Invert vol distance (closer = better)
                score += max(0, 10 - candidate.vol_distance)
            elif candidate.pct_distance is not None:
                # Invert pct distance
                score += max(0, 10 - abs(candidate.pct_distance) * 100)

            # Liquidity component
            score += min(candidate.volume / 100, 10)  # Cap at 10
            score += min(candidate.open_interest / 50, 10)  # Cap at 10

            # Spread component (tighter = better)
            score += max(0, 10 - candidate.spread_cents)

            candidate.composite_score = score

        # Sort by score descending
        candidates.sort(key=lambda c: c.composite_score, reverse=True)

        return candidates

    def _apply_per_asset_caps(
        self,
        per_asset: Dict[str, List[MarketCandidate]],
    ) -> Dict[str, List[MarketCandidate]]:
        """Apply per-asset candidate caps."""
        capped = {}

        for asset, candidates in per_asset.items():
            # Already sorted by composite score
            capped[asset] = candidates[:self.config.max_candidates_per_asset]

        return capped

    def _apply_global_cap(
        self,
        per_asset: Dict[str, List[MarketCandidate]],
    ) -> List[MarketCandidate]:
        """Apply global cap by merging and re-ranking."""
        # Merge all candidates
        all_candidates = []
        for candidates in per_asset.values():
            all_candidates.extend(candidates)

        # Sort by composite score
        all_candidates.sort(key=lambda c: c.composite_score, reverse=True)

        # Take top N
        return all_candidates[:self.config.max_candidates_global]


# ── Continuous trader ─────────────────────────────────────────────────────

class KalshiContinuousTrader:
    """Continuous trader with instrumented filter pipeline."""

    def __init__(self, config: FilterPipelineConfig):
        self.config = config
        self.pipeline = FilterPipeline(config)
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Event-loop lag monitoring
        self._loop_lag_samples: List[float] = []
        self._lag_check_handle: Optional[asyncio.TimerHandle] = None
        self._expected_lag_ts: float = 0.0
        self._current_task_type: str = "idle"

    async def start(self) -> None:
        """Start the continuous trader."""
        if self._running:
            return

        self._running = True
        logger.info(
            f"Starting KalshiContinuousTrader with config: "
            f"assets={self.config.assets}, "
            f"max_per_asset={self.config.max_candidates_per_asset}, "
            f"max_global={self.config.max_candidates_global}, "
            f"lag_threshold={self.config.event_loop_lag_warning_ms}ms"
        )

        # Start lag monitoring
        self._start_lag_monitor()

        # Start main loop
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Stop the continuous trader."""
        self._running = False

        if self._lag_check_handle:
            self._lag_check_handle.cancel()

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info("Stopped KalshiContinuousTrader")

    async def _run_loop(self) -> None:
        """Main trading loop."""
        while self._running:
            try:
                self._current_task_type = "filter_pipeline_batch"

                # Mock: fetch markets for each asset
                # In real implementation, this would call Kalshi API
                raw_markets = await self._fetch_raw_markets()

                # Run filter pipeline
                result = await self.pipeline.filter_markets(raw_markets)

                # TODO: Execute orders for final candidates

                self._current_task_type = "idle"

                # Sleep between cycles
                await asyncio.sleep(5.0)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Error in continuous trader loop: {exc}")
                await asyncio.sleep(1.0)

    async def _fetch_raw_markets(self) -> Dict[str, List[Dict[str, Any]]]:
        """Fetch raw markets for all assets.

        In real implementation, this would call Kalshi API.
        For now, return mock data.
        """
        raw_markets = {}

        for asset in self.config.assets:
            # Mock market data
            markets = []
            # TODO: Fetch from Kalshi API
            raw_markets[asset] = markets

        return raw_markets

    def _start_lag_monitor(self) -> None:
        """Start periodic event-loop lag monitoring."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._expected_lag_ts = time.monotonic()
        self._schedule_lag_check(loop)

    def _schedule_lag_check(self, loop: asyncio.AbstractEventLoop) -> None:
        """Schedule next lag measurement."""
        if not self._running:
            return
        self._expected_lag_ts = time.monotonic() + 1.0
        self._lag_check_handle = loop.call_later(
            1.0, self._measure_lag, loop
        )

    def _measure_lag(self, loop: asyncio.AbstractEventLoop) -> None:
        """Measure event-loop lag."""
        now = time.monotonic()
        lag = now - self._expected_lag_ts
        self._loop_lag_samples.append(lag)

        # Keep last 60 samples
        if len(self._loop_lag_samples) > 60:
            self._loop_lag_samples = self._loop_lag_samples[-60:]

        # Warn if lag exceeds threshold
        lag_ms = lag * 1000
        if lag_ms > self.config.event_loop_lag_warning_ms:
            logger.warning(
                f"Event-loop lag: {lag_ms:.0f}ms | task={self._current_task_type}"
            )

        # Reschedule
        self._schedule_lag_check(loop)

    def get_stats(self) -> Dict[str, Any]:
        """Get trader statistics."""
        lag_samples = self._loop_lag_samples
        avg_lag_ms = (
            sum(lag_samples) / len(lag_samples) * 1000
            if lag_samples else 0
        )
        max_lag_ms = max(lag_samples) * 1000 if lag_samples else 0

        return {
            "running": self._running,
            "avg_loop_lag_ms": round(avg_lag_ms, 1),
            "max_loop_lag_ms": round(max_lag_ms, 1),
            "lag_samples": len(lag_samples),
        }


# ── Upstream data validation ──────────────────────────────────────────────

class DataValidator:
    """Validates upstream data (spot prices, volatility, market data)."""

    @staticmethod
    def validate_spot_price(asset: str, spot: Optional[Decimal]) -> Tuple[bool, str]:
        """Validate spot price data.

        Args:
            asset: Asset symbol
            spot: Spot price

        Returns:
            (is_valid, error_message)
        """
        if spot is None:
            return False, f"Spot price for {asset} is None"

        if spot <= 0:
            return False, f"Spot price for {asset} is non-positive: {spot}"

        # Sanity check: spot prices should be within reasonable ranges
        # These are very loose bounds to catch obviously bogus data
        bounds = {
            "BTC": (1000, 1000000),
            "ETH": (100, 100000),
            "SOL": (1, 10000),
            "XRP": (0.01, 100),
            "DOGE": (0.001, 10),
        }

        if asset in bounds:
            min_price, max_price = bounds[asset]
            if not (min_price <= float(spot) <= max_price):
                return False, (
                    f"Spot price for {asset} is outside expected range "
                    f"[{min_price}, {max_price}]: {spot}"
                )

        return True, ""

    @staticmethod
    def validate_volatility(
        asset: str,
        vol: Optional[float],
    ) -> Tuple[bool, str]:
        """Validate volatility estimate.

        Args:
            asset: Asset symbol
            vol: Daily volatility estimate

        Returns:
            (is_valid, error_message)
        """
        if vol is None:
            return False, f"Volatility for {asset} is None"

        if vol <= 0:
            return False, f"Volatility for {asset} is non-positive: {vol}"

        # Sanity check: daily crypto vol should be between 0.1% and 50%
        if not (0.001 <= vol <= 0.50):
            return False, (
                f"Volatility for {asset} is outside reasonable range "
                f"[0.1%, 50%]: {vol*100:.2f}%"
            )

        return True, ""

    @staticmethod
    def validate_market_data(market: Dict[str, Any]) -> Tuple[bool, str]:
        """Validate raw market data structure.

        Args:
            market: Raw market dict from API

        Returns:
            (is_valid, error_message)
        """
        # Check required fields
        required_fields = ["ticker"]
        for field in required_fields:
            if field not in market:
                return False, f"Missing required field: {field}"

        # Validate ticker format
        ticker = market.get("ticker", "")
        if not ticker or not isinstance(ticker, str):
            return False, f"Invalid ticker format: {ticker}"

        # Validate numeric fields if present
        numeric_fields = ["volume", "open_interest", "best_bid_cents", "best_ask_cents"]
        for field in numeric_fields:
            if field in market:
                value = market[field]
                if not isinstance(value, (int, float)) or value < 0:
                    return False, f"Invalid {field}: {value}"

        return True, ""

    @staticmethod
    def sanitize_spot_prices(
        spot_prices: Dict[str, Decimal],
    ) -> Dict[str, Decimal]:
        """Sanitize spot prices, removing invalid entries.

        Args:
            spot_prices: Dict of asset -> spot price

        Returns:
            Sanitized dict with only valid spot prices
        """
        sanitized = {}

        for asset, spot in spot_prices.items():
            is_valid, error = DataValidator.validate_spot_price(asset, spot)
            if is_valid:
                sanitized[asset] = spot
            else:
                logger.warning(f"Dropping invalid spot price: {error}")

        return sanitized

    @staticmethod
    def sanitize_market_data(
        markets: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Sanitize market data, removing invalid entries.

        Args:
            markets: List of raw market dicts

        Returns:
            Sanitized list with only valid markets
        """
        sanitized = []

        for market in markets:
            is_valid, error = DataValidator.validate_market_data(market)
            if is_valid:
                sanitized.append(market)
            else:
                logger.warning(f"Dropping invalid market data: {error}")

        return sanitized


# ── Configuration helpers ─────────────────────────────────────────────────

def log_config_at_startup(config: FilterPipelineConfig) -> None:
    """Log all configuration parameters at startup for auditability.

    Args:
        config: Filter pipeline configuration
    """
    logger.info("=" * 60)
    logger.info("Kalshi Continuous Trader Configuration")
    logger.info("=" * 60)

    logger.info(f"Assets: {config.assets}")
    logger.info(f"Max candidates per asset: {config.max_candidates_per_asset}")
    logger.info(f"Max candidates global: {config.max_candidates_global}")

    logger.info("")
    logger.info("Liquidity filters:")
    logger.info(f"  min_volume: {config.min_volume}")
    logger.info(f"  min_open_interest: {config.min_open_interest}")
    logger.info(f"  max_spread_cents: {config.max_spread_cents}")

    logger.info("")
    logger.info("Expiry filters:")
    logger.info(f"  min_minutes_to_expiry: {config.min_minutes_to_expiry}")
    logger.info(f"  max_minutes_to_expiry: {config.max_minutes_to_expiry}")

    logger.info("")
    logger.info("Event-loop monitoring:")
    logger.info(f"  lag_warning_threshold_ms: {config.event_loop_lag_warning_ms}")

    logger.info("")
    logger.info("Per-asset volatility configs:")
    for asset in config.assets:
        vol_config = config.get_vol_config(asset)
        logger.info(f"  {asset}:")
        logger.info(f"    max_pct_from_spot: {vol_config.max_pct_from_spot*100:.1f}%")
        logger.info(f"    max_vols_from_spot: {vol_config.max_vols_from_spot:.1f}")
        if vol_config.daily_volatility:
            logger.info(f"    daily_volatility: {vol_config.daily_volatility*100:.2f}%")

    logger.info("=" * 60)
