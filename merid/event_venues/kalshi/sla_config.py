"""
Kalshi SLA Configuration

Centralized SLA thresholds for spot data, market data, and trading gates.
Used by both readiness endpoint and trading agents to ensure consistent
data quality enforcement across the stack.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Literal
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.sla_config")


@dataclass
class SpotSLA:
    """Spot data SLA thresholds for a specific asset."""
    asset: str
    ok_threshold_ms: int  # Below this = OK
    warn_threshold_ms: int  # Between OK and WARN = stale (warn)
    block_threshold_ms: int  # Above WARN = block trading
    
    def get_status(self, age_ms: int) -> Literal["ok", "stale", "bad"]:
        """Get status based on age."""
        if age_ms < 0:
            return "bad"  # No data
        if age_ms <= self.ok_threshold_ms:
            return "ok"
        if age_ms <= self.warn_threshold_ms:
            return "stale"
        return "bad"


@dataclass
class MDSLA:
    """Market data SLA thresholds."""
    ok_threshold_ms: int  # Below this = OK
    warn_threshold_ms: int  # Between OK and WARN = stale (warn)
    block_threshold_ms: int  # Above WARN = block trading
    
    def get_status(self, age_ms: int) -> Literal["ok", "stale", "bad"]:
        """Get status based on age."""
        if age_ms < 0:
            return "bad"  # No data
        if age_ms <= self.ok_threshold_ms:
            return "ok"
        if age_ms <= self.warn_threshold_ms:
            return "stale"
        return "bad"


# Per-asset spot SLAs based on market efficiency
# Higher thresholds for smaller coins due to less efficient markets
SPOT_SLAS: Dict[str, SpotSLA] = {
    "BTC": SpotSLA(asset="BTC", ok_threshold_ms=5000, warn_threshold_ms=30000, block_threshold_ms=60000),
    "ETH": SpotSLA(asset="ETH", ok_threshold_ms=5000, warn_threshold_ms=30000, block_threshold_ms=60000),
    "SOL": SpotSLA(asset="SOL", ok_threshold_ms=5000, warn_threshold_ms=45000, block_threshold_ms=90000),
    "XRP": SpotSLA(asset="XRP", ok_threshold_ms=5000, warn_threshold_ms=45000, block_threshold_ms=90000),
    "DOGE": SpotSLA(asset="DOGE", ok_threshold_ms=5000, warn_threshold_ms=60000, block_threshold_ms=120000),
}

# Market data SLA (same for all tickers)
MD_SLA = MDSLA(
    ok_threshold_ms=2000,   # 2 seconds for OK
    warn_threshold_ms=10000,  # 10 seconds for stale
    block_threshold_ms=120000,  # 120 seconds for block
)


def get_spot_sla(asset: str) -> SpotSLA:
    """Get spot SLA for an asset, defaulting to BTC if not found."""
    return SPOT_SLAS.get(asset.upper(), SPOT_SLAS["BTC"])


def get_md_sla() -> MDSLA:
    """Get market data SLA."""
    return MD_SLA


def get_spot_status(asset: str, age_ms: int) -> Literal["ok", "stale", "bad"]:
    """Get spot status for an asset based on age."""
    sla = get_spot_sla(asset)
    return sla.get_status(age_ms)


def get_md_status(age_ms: int) -> Literal["ok", "stale", "bad"]:
    """Get MD status based on age."""
    return MD_SLA.get_status(age_ms)


def get_md_status_timing_aware(age_ms: int, minutes_to_expiry: Optional[float] = None) -> Literal["ok", "stale", "bad"]:
    """
    Get MD status based on age and time to expiry.
    Uses timing-aware thresholds for contracts near expiry.
    """
    if minutes_to_expiry is not None:
        # For timing-aware status, we need to check against dynamic thresholds
        max_age_seconds = get_md_max_age_seconds(minutes_to_expiry)
        max_age_ms = max_age_seconds * 1000
        
        if age_ms < 0:
            return "bad"
        if age_ms <= max_age_ms:
            return "ok"
        else:
            return "bad"
    else:
        # Fall back to static SLA
        return MD_SLA.get_status(age_ms)


def get_spot_max_age_seconds(asset: str, minutes_to_expiry: Optional[float] = None) -> float:
    """
    Get maximum spot age in seconds for agent gating.
    This is the threshold used by LeanAgent15m to reject stale spot data.

    This function now reads from data.spot_sla_config as the canonical SLA source,
    ensuring all layers use the same freshness thresholds.

    Design Philosophy:
    - Spot is a reference anchor, not a primary trading venue
    - Single hard threshold for all assets (60s)
    - Only hard-block on spot in truly pathological cases
    - Allow MD-only trading when spot is unavailable

    Args:
        asset: Asset ticker (e.g., "BTC", "ETH") - unused in new design
        minutes_to_expiry: Optional time to expiry in minutes - unused in new design

    Returns:
        Maximum age in seconds (60s for all assets).
    """
    # Import from canonical SLA source
    try:
        from data.spot_sla_config import get_spot_max_age
        return get_spot_max_age()
    except ImportError:
        # Fallback to local SLA if canonical source unavailable
        logger.warning("[SLA-CONFIG] Canonical spot_sla_config not available, using local SLA")
        sla = get_spot_sla(asset)
        return sla.block_threshold_ms / 1000.0


def get_md_max_age_seconds(minutes_to_expiry: Optional[float] = None) -> float:
    """
    Get maximum MD age in seconds for agent gating.
    This is the threshold used by LeanAgent15m to reject stale MD data.

    Args:
        minutes_to_expiry: Optional time to expiry in minutes for timing-aware SLAs

    Returns:
        Maximum age in seconds. If minutes_to_expiry is provided, returns
        stricter threshold for contracts near expiry.
    
    Timing-aware thresholds for 15m markets:
    - Far from expiry (>10 min): 120s (base threshold)
    - Near expiry (2-10 min): 60s (stricter)
    - Very near expiry (<2 min): 10s (very strict - ensures fresh data for exits)
    """
    base_threshold = MD_SLA.block_threshold_ms / 1000.0  # 120s

    # Timing-aware SLA: stricter threshold near expiry
    # MD needs to be fresher than spot since it's directly used for pricing
    # CRITICAL FIX (2026-07-11): Enable timing-aware thresholds for exit safety
    if minutes_to_expiry is not None:
        if minutes_to_expiry < 2.0:
            # Very near expiry: require very fresh data (10s)
            return 10.0
        elif minutes_to_expiry < 10.0:
            # Near expiry: stricter threshold (60s)
            return 60.0
        else:
            # Far from expiry: use base threshold (120s)
            return base_threshold
    else:
        # No expiry info: use base threshold
        return base_threshold
