"""
Spot SLA Configuration - Single Source of Truth for Spot Freshness Thresholds

This module provides centralized SLA thresholds for spot data freshness across
the entire MERID stack. All components (UnifiedSpotService, watchdog, health
snapshot, trading agents) MUST use these thresholds to ensure consistency.

Design Philosophy:
- Spot is a reference anchor for Kalshi 15m contracts, not a primary trading venue
- Spot should only hard-block trades in truly pathological cases (minutes of outage)
- As long as Kalshi MD is live and books are liquid, the engine should run
- Spot is optional support data - not a single point of failure

SLA Thresholds:
- MAX_SPOT_AGE_HARD: Single hard threshold for all assets (60s)
  - If spot_age <= MAX_SPOT_AGE_HARD: Use spot normally for alignment, filters
  - If spot_age > MAX_SPOT_AGE_HARD: Treat spot as unavailable, allow MD-only trading

No per-asset differences, no degraded mode - spot is either available or unavailable.

Usage:
    from data.spot_sla_config import get_spot_sla, SPOT_SLA, MAX_SPOT_AGE_HARD
    
    if age_s > MAX_SPOT_AGE_HARD:
        # Spot is unavailable - allow MD-only trading
"""

from __future__ import annotations

from typing import Literal


# =============================================================================
# Single Hard Threshold for All Assets
# =============================================================================

# Spot is a reference anchor, not a primary trading venue.
# Only hard-block on spot in truly pathological cases (minutes of outage).
MAX_SPOT_AGE_HARD = 60.0  # seconds - single threshold for all assets


def get_spot_max_age() -> float:
    """Get the single hard spot age threshold for all assets.
    
    This is the only threshold used for spot freshness gating.
    If spot_age > MAX_SPOT_AGE_HARD, treat spot as unavailable and allow MD-only trading.
    """
    return MAX_SPOT_AGE_HARD


def is_spot_available(age_s: float) -> Literal["available", "unavailable"]:
    """Check if spot data is available based on age.
    
    Returns:
        - "available": age_s <= MAX_SPOT_AGE_HARD - use spot normally
        - "unavailable": age_s > MAX_SPOT_AGE_HARD - treat as missing, allow MD-only trading
    """
    if age_s < 0:
        return "unavailable"  # No data
    if age_s <= MAX_SPOT_AGE_HARD:
        return "available"
    return "unavailable"


# =============================================================================
# Legacy Compatibility (deprecated)
# =============================================================================

from dataclasses import dataclass
from typing import Dict


@dataclass
class SpotSLA:
    """Deprecated: Spot data SLA thresholds for a specific asset.
    
    This is kept for backward compatibility only.
    New code should use MAX_SPOT_AGE_HARD directly.
    """
    asset: str
    fresh_s: float  # OK threshold - data within this age is fresh
    stale_s: float  # Warn threshold - data within this age is stale but usable
    degrade_s: float  # Trading gate threshold - data older than this triggers degradation
    
    def get_status(self, age_s: float) -> Literal["fresh", "stale", "degraded"]:
        """Get status based on age in seconds.
        
        Status logic:
        - fresh: age < fresh_s (data is fresh)
        - stale: fresh_s <= age < stale_s (data is stale but still usable, warn threshold)
        - degraded: age >= degrade_s (data is too stale, trading gate)
        """
        if age_s < 0:
            return "degraded"  # No data
        if age_s < self.fresh_s:
            return "fresh"
        if age_s < self.stale_s:
            return "stale"
        return "degraded"


# Per-asset SLAs based on API characteristics and timeout tuning
# SOL has higher thresholds to match its 2s timeout (vs 0.5s for others)
# degrade_s = stale_s for simplicity: stale data degrades trading
# DEPRECATED: New code should use MAX_SPOT_AGE_HARD directly
SPOT_SLA: Dict[str, SpotSLA] = {
    "BTC": SpotSLA(asset="BTC", fresh_s=5.0, stale_s=10.0, degrade_s=10.0),
    "ETH": SpotSLA(asset="ETH", fresh_s=5.0, stale_s=10.0, degrade_s=10.0),
    "SOL": SpotSLA(asset="SOL", fresh_s=10.0, stale_s=20.0, degrade_s=20.0),
    "XRP": SpotSLA(asset="XRP", fresh_s=5.0, stale_s=10.0, degrade_s=10.0),
    "DOGE": SpotSLA(asset="DOGE", fresh_s=5.0, stale_s=10.0, degrade_s=10.0),
}


def get_spot_sla(asset: str) -> SpotSLA:
    """Deprecated: Get spot SLA for an asset, defaulting to BTC if not found.
    
    New code should use get_spot_max_age() and is_spot_available() instead.
    """
    return SPOT_SLA.get(asset.upper(), SPOT_SLA["BTC"])


def get_spot_status(asset: str, age_s: float) -> Literal["fresh", "stale", "degraded"]:
    """Deprecated: Get spot status for an asset based on age in seconds.
    
    New code should use is_spot_available() instead.
    """
    sla = get_spot_sla(asset)
    return sla.get_status(age_s)
