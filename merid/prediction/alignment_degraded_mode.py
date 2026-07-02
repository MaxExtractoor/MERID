"""
Alignment degraded mode for spot vs contract invariant.

This module implements degraded mode behavior when spot-contract alignment
fails (gap exceeds threshold).
"""

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Optional, Set

logger = logging.getLogger(__name__)


class AlignmentDegradedMode:
    """
    Manages degraded mode for assets with poor spot-contract alignment.
    
    When an asset has consecutive alignment failures:
    - Block new entries
    - Continue managing exits and TP/SL for open positions
    - Log [ALIGNMENT-DEGRADED] and [ALIGNMENT-RESTORED]
    """
    
    def __init__(self, gap_threshold_cents: int = 50, consecutive_failures_threshold: int = 3):
        self.gap_threshold_cents = gap_threshold_cents
        self.consecutive_failures_threshold = consecutive_failures_threshold
        
        # Track consecutive failures per asset
        self.consecutive_failures: Dict[str, int] = defaultdict(int)
        
        # Track degraded assets
        self.degraded_assets: Set[str] = set()
        
        # Track last check time per asset
        self.last_check_time: Dict[str, datetime] = {}
    
    def check_alignment(
        self,
        asset: str,
        gap_cents: float,
        timestamp: datetime = None
    ) -> bool:
        """
        Check alignment and update degraded mode status.
        
        Args:
            asset: Asset symbol
            gap_cents: Alignment gap in cents
            timestamp: Check timestamp (defaults to now)
        
        Returns:
            True if asset is in good alignment, False if degraded
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        
        is_aligned = gap_cents < self.gap_threshold_cents
        
        if is_aligned:
            # Reset consecutive failures
            if self.consecutive_failures[asset] > 0:
                logger.info(
                    "[ALIGNMENT-RESET] %s gap=%.2fc < threshold=%dc - resetting failures",
                    asset, gap_cents, self.gap_threshold_cents
                )
            self.consecutive_failures[asset] = 0
            
            # If asset was degraded, restore it
            if asset in self.degraded_assets:
                self.degraded_assets.remove(asset)
                logger.warning(
                    "[ALIGNMENT-RESTORED] %s gap=%.2fc - exiting degraded mode, allowing new entries",
                    asset, gap_cents
                )
        else:
            # Increment consecutive failures
            self.consecutive_failures[asset] += 1
            logger.warning(
                "[ALIGNMENT-FAIL] %s gap=%.2fc >= threshold=%dc - consecutive failures=%d",
                asset, gap_cents, self.gap_threshold_cents, self.consecutive_failures[asset]
            )
            
            # Check if threshold exceeded
            if self.consecutive_failures[asset] >= self.consecutive_failures_threshold:
                if asset not in self.degraded_assets:
                    self.degraded_assets.add(asset)
                    logger.error(
                        "[ALIGNMENT-DEGRADED] %s consecutive failures=%d >= threshold=%d - entering degraded mode, blocking new entries",
                        asset, self.consecutive_failures[asset], self.consecutive_failures_threshold
                    )
        
        self.last_check_time[asset] = timestamp
        
        return is_aligned
    
    def is_degraded(self, asset: str) -> bool:
        """
        Check if an asset is in degraded mode.
        
        Args:
            asset: Asset symbol
        
        Returns:
            True if asset is degraded (new entries blocked)
        """
        return asset in self.degraded_assets
    
    def can_enter_new_position(self, asset: str) -> bool:
        """
        Check if new entries are allowed for an asset.
        
        Args:
            asset: Asset symbol
        
        Returns:
            True if new entries allowed, False if blocked
        """
        if self.is_degraded(asset):
            logger.warning(
                "[ALIGNMENT-BLOCK-ENTRY] %s is in degraded mode - blocking new entry",
                asset
            )
            return False
        return True
    
    def get_status(self) -> Dict:
        """
        Get current status of all assets.
        
        Returns:
            Dict with status per asset
        """
        status = {}
        for asset in self.consecutive_failures.keys():
            status[asset] = {
                "consecutive_failures": self.consecutive_failures[asset],
                "is_degraded": self.is_degraded(asset),
                "last_check_time": self.last_check_time.get(asset),
            }
        return status
    
    def log_status(self):
        """Log current status of all assets."""
        status = self.get_status()
        
        logger.info(
            "[ALIGNMENT-STATUS] Tracking %d assets, %d degraded",
            len(status), len(self.degraded_assets)
        )
        
        for asset, info in status.items():
            degraded_str = "DEGRADED" if info["is_degraded"] else "OK"
            logger.info(
                "  %s: failures=%d %s last_check=%s",
                asset, info["consecutive_failures"], degraded_str, info["last_check_time"]
            )


# Singleton instance
_alignment_degraded_mode: Optional[AlignmentDegradedMode] = None


def get_alignment_degraded_mode() -> AlignmentDegradedMode:
    """Get the singleton alignment degraded mode instance."""
    global _alignment_degraded_mode
    if _alignment_degraded_mode is None:
        _alignment_degraded_mode = AlignmentDegradedMode()
    return _alignment_degraded_mode
