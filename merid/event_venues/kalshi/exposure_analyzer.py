"""Exposure Analyzer — Track and log realized exposure by asset/timeframe.

This module provides utilities to analyze actual portfolio exposure against
spend caps, helping tune the cap ranges based on live trading results.

The analyzer tracks:
- Per-(asset, timeframe) exposure as a percentage of bankroll
- Per-asset total exposure across all timeframes
- Global portfolio exposure

Results are logged periodically to help operators:
1. Identify if caps are too loose (positions rarely hitting limits)
2. Identify if caps are too tight (positions frequently capped)
3. Adjust the (min, max) ranges in SPEND_CAPS based on observed patterns
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from utils.logger import get_logger
from merid.event_venues.kalshi.crypto_kalshi_risk import (
    get_spend_cap,
    get_per_asset_total_cap,
    PORTFOLIO_GLOBAL_CAP,
    OpenPositions,
)

logger = get_logger("merid.event_venues.kalshi.exposure_analyzer")


@dataclass
class ExposureSnapshot:
    """Single snapshot of portfolio exposure at a point in time."""

    timestamp: float
    bankroll: float

    # Per-(asset, timeframe) exposure in USD and as % of bankroll
    position_exposures: Dict[Tuple[str, str], float] = field(default_factory=dict)
    position_pcts: Dict[Tuple[str, str], float] = field(default_factory=dict)

    # Per-asset total exposure (all timeframes combined)
    asset_total_exposures: Dict[str, float] = field(default_factory=dict)
    asset_total_pcts: Dict[str, float] = field(default_factory=dict)

    # Global portfolio exposure (all positions)
    global_exposure: float = 0.0
    global_pct: float = 0.0


@dataclass
class ExposureStats:
    """Aggregated exposure statistics over a collection of snapshots."""

    asset: str
    timeframe: Optional[str] = None  # None means asset-total stats

    # Exposure statistics (as % of bankroll)
    avg_exposure_pct: float = 0.0
    max_exposure_pct: float = 0.0
    min_exposure_pct: float = 0.0

    # Spend cap reference (for comparison)
    cap_min_pct: Optional[float] = None
    cap_max_pct: Optional[float] = None
    cap_midpoint_pct: Optional[float] = None

    # Usage metrics
    times_at_cap: int = 0  # How many snapshots hit or exceeded the cap
    total_snapshots: int = 0

    @property
    def cap_utilization_pct(self) -> Optional[float]:
        """Percentage of the cap midpoint being used on average."""
        if self.cap_midpoint_pct is None or self.cap_midpoint_pct == 0:
            return None
        return (self.avg_exposure_pct / self.cap_midpoint_pct) * 100.0

    @property
    def cap_hit_rate(self) -> float:
        """Fraction of snapshots where exposure hit or exceeded the cap."""
        if self.total_snapshots == 0:
            return 0.0
        return self.times_at_cap / self.total_snapshots


class ExposureAnalyzer:
    """Tracks and analyzes portfolio exposure against spend caps."""

    def __init__(self, max_snapshots: int = 1000) -> None:
        """Initialize the exposure analyzer.

        Args:
            max_snapshots: Maximum number of snapshots to retain in memory.
                           Older snapshots are dropped when this limit is reached.
        """
        self._max_snapshots = max_snapshots
        self._snapshots: List[ExposureSnapshot] = []

    def capture_snapshot(
        self,
        timestamp: float,
        bankroll: float,
        open_positions: OpenPositions,
    ) -> ExposureSnapshot:
        """Capture a snapshot of current portfolio exposure.

        Args:
            timestamp: Unix timestamp of the snapshot.
            bankroll: Current total bankroll.
            open_positions: Dict of ticker -> position info.
                            Expected keys: "asset", "timeframe", "contracts", "entry_price"

        Returns:
            ExposureSnapshot with all exposure metrics computed.
        """
        snapshot = ExposureSnapshot(timestamp=timestamp, bankroll=bankroll)

        # Aggregate exposure by (asset, timeframe)
        exposure_by_key: Dict[Tuple[str, str], float] = defaultdict(float)
        exposure_by_asset: Dict[str, float] = defaultdict(float)

        for ticker, info in open_positions.items():
            asset = info.get("asset", "").upper()
            timeframe = info.get("timeframe", "").lower()
            contracts = info.get("contracts", 0)
            entry_price = info.get("entry_price", 0.0)

            if not asset or not timeframe:
                continue

            exposure_usd = abs(contracts) * entry_price

            # Track by (asset, timeframe)
            key = (asset, timeframe)
            exposure_by_key[key] += exposure_usd

            # Track by asset (all timeframes)
            exposure_by_asset[asset] += exposure_usd

            # Track global
            snapshot.global_exposure += exposure_usd

        # Convert to percentages
        if bankroll > 0:
            for key, exp_usd in exposure_by_key.items():
                snapshot.position_exposures[key] = exp_usd
                snapshot.position_pcts[key] = exp_usd / bankroll

            for asset, exp_usd in exposure_by_asset.items():
                snapshot.asset_total_exposures[asset] = exp_usd
                snapshot.asset_total_pcts[asset] = exp_usd / bankroll

            snapshot.global_pct = snapshot.global_exposure / bankroll

        # Store snapshot
        self._snapshots.append(snapshot)

        # Trim to max_snapshots
        if len(self._snapshots) > self._max_snapshots:
            self._snapshots = self._snapshots[-self._max_snapshots :]

        return snapshot

    def compute_stats(
        self,
        asset: str,
        timeframe: Optional[str] = None,
    ) -> Optional[ExposureStats]:
        """Compute exposure statistics for a given asset/timeframe combination.

        Args:
            asset: Asset symbol (e.g., "BTC")
            timeframe: Timeframe (e.g., "15m"). If None, computes asset-total stats.

        Returns:
            ExposureStats object, or None if no data is available.
        """
        if not self._snapshots:
            return None

        exposures: List[float] = []

        if timeframe is None:
            # Asset-total stats (all timeframes combined)
            for snapshot in self._snapshots:
                pct = snapshot.asset_total_pcts.get(asset.upper(), 0.0)
                exposures.append(pct)

            # Get per-asset total cap
            cap_min, cap_max = get_per_asset_total_cap(asset)
            cap_midpoint = (cap_min + cap_max) / 2.0
        else:
            # Per-(asset, timeframe) stats
            key = (asset.upper(), timeframe.lower())
            for snapshot in self._snapshots:
                pct = snapshot.position_pcts.get(key, 0.0)
                exposures.append(pct)

            # Get spend cap for this (asset, timeframe)
            cap_min, cap_max = get_spend_cap(asset, timeframe)
            cap_midpoint = (cap_min + cap_max) / 2.0

        if not exposures:
            return None

        # Compute statistics
        avg_exp = sum(exposures) / len(exposures)
        max_exp = max(exposures)
        min_exp = min(exposures)

        # Count times at or above cap
        times_at_cap = sum(1 for exp in exposures if exp >= cap_midpoint)

        stats = ExposureStats(
            asset=asset.upper(),
            timeframe=timeframe.lower() if timeframe else None,
            avg_exposure_pct=avg_exp,
            max_exposure_pct=max_exp,
            min_exposure_pct=min_exp,
            cap_min_pct=cap_min,
            cap_max_pct=cap_max,
            cap_midpoint_pct=cap_midpoint,
            times_at_cap=times_at_cap,
            total_snapshots=len(exposures),
        )

        return stats

    def log_exposure_summary(self, assets: List[str], timeframes: List[str]) -> None:
        """Log a summary of exposure statistics for all asset/timeframe combinations.

        Args:
            assets: List of asset symbols to analyze.
            timeframes: List of timeframes to analyze.
        """
        if not self._snapshots:
            logger.info("ExposureAnalyzer: No snapshots available for summary")
            return

        logger.info(
            "ExposureAnalyzer: Summary based on %d snapshots", len(self._snapshots)
        )

        # Global portfolio stats
        global_exposures = [s.global_pct for s in self._snapshots]
        if global_exposures:
            avg_global = sum(global_exposures) / len(global_exposures)
            max_global = max(global_exposures)
            logger.info(
                "GLOBAL PORTFOLIO: avg=%.1f%% max=%.1f%% (cap=%.1f%%)",
                avg_global * 100,
                max_global * 100,
                PORTFOLIO_GLOBAL_CAP * 100,
            )

        # Per-asset total exposure
        logger.info("PER-ASSET TOTAL EXPOSURE:")
        for asset in assets:
            stats = self.compute_stats(asset, timeframe=None)
            if stats:
                logger.info(
                    "  %s: avg=%.1f%% max=%.1f%% cap=[%.1f%%-%.1f%%] "
                    "utilization=%.0f%% hit_rate=%.1f%%",
                    asset,
                    stats.avg_exposure_pct * 100,
                    stats.max_exposure_pct * 100,
                    stats.cap_min_pct * 100,
                    stats.cap_max_pct * 100,
                    stats.cap_utilization_pct or 0.0,
                    stats.cap_hit_rate * 100,
                )

        # Per-(asset, timeframe) exposure
        logger.info("PER-POSITION EXPOSURE:")
        for asset in assets:
            for timeframe in timeframes:
                stats = self.compute_stats(asset, timeframe)
                if stats and stats.avg_exposure_pct > 0:
                    logger.info(
                        "  %s/%s: avg=%.1f%% max=%.1f%% cap=[%.1f%%-%.1f%%] "
                        "utilization=%.0f%% hit_rate=%.1f%%",
                        asset,
                        timeframe,
                        stats.avg_exposure_pct * 100,
                        stats.max_exposure_pct * 100,
                        stats.cap_min_pct * 100,
                        stats.cap_max_pct * 100,
                        stats.cap_utilization_pct or 0.0,
                        stats.cap_hit_rate * 100,
                    )

    def get_snapshot_count(self) -> int:
        """Return the number of snapshots currently stored."""
        return len(self._snapshots)

    def clear_snapshots(self) -> None:
        """Clear all stored snapshots."""
        self._snapshots.clear()
        logger.info("ExposureAnalyzer: All snapshots cleared")
