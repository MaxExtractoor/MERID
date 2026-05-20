"""Spot alignment monitor for MERID_SPOT vs CF Benchmarks RTI.

Periodic task that:
- Fetches MERID_SPOT (composite) and CF Benchmarks RTI price per asset
- Computes absolute and percentage basis (MERID_SPOT - RTI)
- Maintains rolling stats (mean, std, max, P95) of that basis per asset
- Emits metrics/logs and triggers alerts if misalignment exceeds thresholds

Runs in background as an async task, typically started at application startup.
"""
from __future__ import annotations

import asyncio
import os
import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from data.cfb_rti_client import get_cfb_rti_client
from data.spot_composite import get_spot_composite
from data.spot_models import Asset, AlignmentHealth, SpotAlignment
from utils.logger import get_logger

logger = get_logger("data.spot_alignment_monitor")

# Assets to monitor
MONITORED_ASSETS = [Asset.BTC, Asset.ETH, Asset.SOL, Asset.XRP, Asset.DOGE]

# Monitoring interval (seconds)
MONITOR_INTERVAL_SECONDS = float(os.getenv("MERID_SPOT_ALIGNMENT_INTERVAL", "30.0"))

# Rolling stats window (seconds)
ROLLING_WINDOW_SECONDS = float(os.getenv("MERID_SPOT_ALIGNMENT_WINDOW", "3600.0"))

# Alignment thresholds (basis points)
THRESHOLD1_BPS = float(os.getenv("MERID_SPOT_ALIGNMENT_THRESHOLD1_BPS", "5.0"))  # ALIGNED -> MILD_DRIFT
THRESHOLD2_BPS = float(os.getenv("MERID_SPOT_ALIGNMENT_THRESHOLD2_BPS", "20.0"))  # MILD_DRIFT -> SEVERE_DRIFT

# Maximum samples in rolling buffer (cap memory)
MAX_SAMPLES = int(ROLLING_WINDOW_SECONDS / MONITOR_INTERVAL_SECONDS) + 100


@dataclass
class AlignmentStats:
    """Rolling statistics for spot vs RTI alignment."""
    asset: Asset
    basis_abs_mean: Optional[float] = None
    basis_abs_std: Optional[float] = None
    basis_abs_max: Optional[float] = None
    basis_abs_p95: Optional[float] = None
    basis_bps_mean: Optional[float] = None
    basis_bps_std: Optional[float] = None
    aligned_pct: Optional[float] = None  # % of samples in ALIGNED state
    mild_drift_pct: Optional[float] = None  # % of samples in MILD_DRIFT state
    severe_drift_pct: Optional[float] = None  # % of samples in SEVERE_DRIFT state
    sample_count: int = 0
    last_computed_at: float = field(default_factory=time.monotonic)


class SpotAlignmentMonitor:
    """Background task that monitors MERID_SPOT vs CF Benchmarks RTI alignment.
    
    Lifecycle:
        monitor = SpotAlignmentMonitor()
        await monitor.start()  # Starts background task
        ...
        await monitor.stop()   # Stops background task
    
    Access latest alignment:
        alignment = monitor.get_latest_alignment(Asset.BTC)
        stats = monitor.get_stats(Asset.BTC)
    """
    
    def __init__(
        self,
        interval_seconds: float = MONITOR_INTERVAL_SECONDS,
        rolling_window_seconds: float = ROLLING_WINDOW_SECONDS,
        threshold1_bps: float = THRESHOLD1_BPS,
        threshold2_bps: float = THRESHOLD2_BPS,
    ):
        """
        Initialize SpotAlignmentMonitor.
        
        Args:
            interval_seconds: Monitoring interval in seconds
            rolling_window_seconds: Rolling stats window in seconds
            threshold1_bps: Basis threshold for ALIGNED -> MILD_DRIFT (bps)
            threshold2_bps: Basis threshold for MILD_DRIFT -> SEVERE_DRIFT (bps)
        """
        self.interval_seconds = interval_seconds
        self.rolling_window_seconds = rolling_window_seconds
        self.threshold1_bps = threshold1_bps
        self.threshold2_bps = threshold2_bps
        
        # Latest alignment per asset
        self._latest_alignment: Dict[Asset, SpotAlignment] = {}
        
        # Rolling basis samples: asset -> deque of (timestamp, basis_abs, basis_bps, health)
        self._rolling_samples: Dict[Asset, deque] = {
            asset: deque(maxlen=MAX_SAMPLES) for asset in MONITORED_ASSETS
        }
        
        # Rolling stats per asset
        self._stats: Dict[Asset, AlignmentStats] = {
            asset: AlignmentStats(asset=asset) for asset in MONITORED_ASSETS
        }
        
        # Background task
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        
        logger.info(
            f"SpotAlignmentMonitor initialized: interval={interval_seconds}s, "
            f"window={rolling_window_seconds}s, thresholds={threshold1_bps}/{threshold2_bps} bps"
        )
    
    async def start(self):
        """Start the background monitoring task."""
        if self._running:
            logger.warning("SpotAlignmentMonitor already running")
            return
        
        self._running = True
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(), name="spot-alignment-monitor")
        logger.info("SpotAlignmentMonitor started")
    
    async def stop(self):
        """Stop the background monitoring task."""
        if not self._running:
            return
        
        self._running = False
        self._stop_event.set()
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        
        logger.info("SpotAlignmentMonitor stopped")
    
    def get_latest_alignment(self, asset: Asset) -> Optional[SpotAlignment]:
        """Get the latest alignment snapshot for an asset."""
        return self._latest_alignment.get(asset)
    
    def get_all_latest_alignments(self) -> Dict[Asset, SpotAlignment]:
        """Get all latest alignment snapshots."""
        return self._latest_alignment.copy()
    
    def get_stats(self, asset: Asset) -> AlignmentStats:
        """Get rolling statistics for an asset."""
        return self._stats.get(asset, AlignmentStats(asset=asset))
    
    def get_all_stats(self) -> Dict[Asset, AlignmentStats]:
        """Get all rolling statistics."""
        return self._stats.copy()
    
    async def _run(self):
        """Background monitoring loop."""
        logger.info("[SPOT-ALIGNMENT-MONITOR] Background task started")
        
        while self._running and not self._stop_event.is_set():
            try:
                await self._tick()
                await asyncio.sleep(self.interval_seconds)
            except asyncio.CancelledError:
                logger.info("[SPOT-ALIGNMENT-MONITOR] Task cancelled")
                break
            except Exception as exc:
                logger.error(f"[SPOT-ALIGNMENT-MONITOR] Tick error: {exc}")
                await asyncio.sleep(self.interval_seconds)
        
        logger.info("[SPOT-ALIGNMENT-MONITOR] Background task stopped")
    
    async def _tick(self):
        """Compute alignment for all assets."""
        composite = get_spot_composite()
        cfb_client = await get_cfb_rti_client()
        
        for asset in MONITORED_ASSETS:
            try:
                # Get composite spot
                composite_spot = composite.get_composite_spot(asset)
                
                # Get CF Benchmarks RTI
                rti = await cfb_client.get_latest_rti(asset)
                
                # Compute alignment
                alignment = SpotAlignment.from_composite_and_rti(
                    asset=asset,
                    composite=composite_spot,
                    rti=rti,
                    threshold1_bps=self.threshold1_bps,
                    threshold2_bps=self.threshold2_bps,
                )
                
                # Store latest
                self._latest_alignment[asset] = alignment
                
                # Add to rolling samples
                if alignment.basis_abs is not None and alignment.basis_bps is not None:
                    self._rolling_samples[asset].append(
                        (time.monotonic(), alignment.basis_abs, alignment.basis_bps, alignment.health)
                    )
                
                # Update rolling stats
                self._update_stats(asset)
                
                # Log alignment
                self._log_alignment(alignment, composite_spot, rti)
                
            except Exception as exc:
                logger.warning(f"[SPOT-ALIGNMENT-MONITOR] Error processing {asset}: {exc}")
    
    def _update_stats(self, asset: Asset):
        """Update rolling statistics for an asset."""
        samples = self._rolling_samples[asset]
        cutoff = time.monotonic() - self.rolling_window_seconds
        
        # Filter to window
        window_samples = [(ts, abs_val, bps, health) for ts, abs_val, bps, health in samples if ts >= cutoff]
        
        if not window_samples:
            return
        
        # Extract values
        basis_abs_values = [abs_val for _, abs_val, _, _ in window_samples]
        basis_bps_values = [bps for _, _, bps, _ in window_samples]
        health_values = [health for _, _, _, health in window_samples]
        
        # Compute stats
        stats = self._stats[asset]
        stats.sample_count = len(window_samples)
        
        if basis_abs_values:
            stats.basis_abs_mean = statistics.mean(basis_abs_values)
            stats.basis_abs_std = statistics.stdev(basis_abs_values) if len(basis_abs_values) > 1 else 0.0
            stats.basis_abs_max = max(basis_abs_values)
            stats.basis_abs_p95 = self._percentile(basis_abs_values, 0.95)
        
        if basis_bps_values:
            stats.basis_bps_mean = statistics.mean(basis_bps_values)
            stats.basis_bps_std = statistics.stdev(basis_bps_values) if len(basis_bps_values) > 1 else 0.0
        
        # Compute health percentages
        total = len(health_values)
        if total > 0:
            aligned_count = sum(1 for h in health_values if h == AlignmentHealth.ALIGNED)
            mild_count = sum(1 for h in health_values if h == AlignmentHealth.MILD_DRIFT)
            severe_count = sum(1 for h in health_values if h == AlignmentHealth.SEVERE_DRIFT)
            
            stats.aligned_pct = (aligned_count / total) * 100.0
            stats.mild_drift_pct = (mild_count / total) * 100.0
            stats.severe_drift_pct = (severe_count / total) * 100.0
        
        stats.last_computed_at = time.monotonic()
    
    def _percentile(self, values: List[float], p: float) -> float:
        """Compute percentile of values."""
        if not values:
            return 0.0
        sorted_values = sorted(values)
        k = (len(sorted_values) - 1) * p
        f = int(k)
        c = f + 1 if f + 1 < len(sorted_values) else f
        if f == c:
            return sorted_values[f]
        d = k - f
        return sorted_values[f] * (1 - d) + sorted_values[c] * d
    
    def _log_alignment(
        self,
        alignment: SpotAlignment,
        composite_spot,
        rti,
    ):
        """Log alignment snapshot with structured details."""
        contributing = getattr(composite_spot, "contributing_exchanges", [])
        exchanges_str = ",".join(contributing) if contributing else "none"
        
        logger.info(
            f"[SPOT-ALIGNMENT] asset={alignment.asset.value} "
            f"merid_spot={alignment.merid_spot:.2f if alignment.merid_spot else 'N/A'} "
            f"cfb_rti={alignment.cfb_rti:.2f if alignment.cfb_rti else 'N/A'} "
            f"basis_abs={alignment.basis_abs:.2f if alignment.basis_abs else 'N/A'} "
            f"basis_bps={alignment.basis_bps:.1f if alignment.basis_bps else 'N/A'} "
            f"health={alignment.health.value} "
            f"exchanges=[{exchanges_str}]"
        )
        
        # Alert on severe drift
        if alignment.health == AlignmentHealth.SEVERE_DRIFT:
            logger.warning(
                f"[SPOT-ALIGNMENT-ALERT] Severe drift detected for {alignment.asset.value}: "
                f"basis_bps={alignment.basis_bps:.1f} > {self.threshold2_bps} bps threshold"
            )


# Singleton instance
_monitor: Optional[SpotAlignmentMonitor] = None
_monitor_lock = asyncio.Lock()


async def get_spot_alignment_monitor() -> SpotAlignmentMonitor:
    """Get or create the singleton SpotAlignmentMonitor instance."""
    global _monitor
    
    if _monitor is None:
        async with _monitor_lock:
            if _monitor is None:
                _monitor = SpotAlignmentMonitor()
                await _monitor.start()
    
    return _monitor


async def close_spot_alignment_monitor():
    """Close the singleton SpotAlignmentMonitor instance."""
    global _monitor
    
    async with _monitor_lock:
        if _monitor:
            await _monitor.stop()
            _monitor = None
