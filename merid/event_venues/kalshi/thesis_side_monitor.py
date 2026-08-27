"""
Thesis Side Inversion Monitor

This module provides monitoring and metrics for side inversion detection.
It tracks side inversion incidents and provides metrics for production dashboards.
"""

import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from collections import defaultdict
from utils.logger import get_logger

logger = get_logger("merid.thesis_side_monitor")


class ThesisSideMonitor:
    """Monitor for tracking side inversion incidents."""
    
    def __init__(self):
        """Initialize the thesis side monitor."""
        self._inversion_count = 0
        self._inversion_by_market: Dict[str, int] = defaultdict(int)
        self._inversion_by_asset: Dict[str, int] = defaultdict(int)
        self._inversion_history: List[Dict] = []
        self._max_history_size = 1000
        self._sync_error_count = 0
        self._sync_error_by_market: Dict[str, int] = defaultdict(int)
        self._last_inversion_time: Optional[datetime] = None
        self._last_sync_error_time: Optional[datetime] = None
        self._legacy_mapping_count = 0
        self._legacy_mapping_by_market: Dict[str, int] = defaultdict(int)
        self._legacy_mapping_by_reason: Dict[str, int] = defaultdict(int)
    
    def record_inversion(
        self,
        market_id: str,
        thesis_side: str,
        inverted_side: str,
        fill_id: Optional[str] = None,
        context: str = "unknown"
    ) -> None:
        """
        Record a side inversion incident.
        
        Args:
            market_id: Market ticker where inversion occurred
            thesis_side: The expected thesis side (yes/no)
            inverted_side: The actual inverted side (no/yes)
            fill_id: Optional fill ID for traceability
            context: Context where inversion was detected (entry/exit/sync)
        """
        self._inversion_count += 1
        self._inversion_by_market[market_id] += 1
        self._last_inversion_time = datetime.now(timezone.utc)
        
        # Extract asset from market_id (e.g., KXBTC15M -> BTC)
        asset = self._extract_asset(market_id)
        if asset:
            self._inversion_by_asset[asset] += 1
        
        # Record in history
        incident = {
            "timestamp": self._last_inversion_time.isoformat(),
            "market_id": market_id,
            "asset": asset,
            "thesis_side": thesis_side,
            "inverted_side": inverted_side,
            "fill_id": fill_id,
            "context": context
        }
        
        self._inversion_history.append(incident)
        
        # Trim history if needed
        if len(self._inversion_history) > self._max_history_size:
            self._inversion_history = self._inversion_history[-self._max_history_size:]
        
        # Log critical alert
        logger.critical(
            "[THESIS-SIDE-INVERSION] market=%s asset=%s thesis=%s inverted=%s fill_id=%s context=%s "
            "total_inversions=%d market_inversions=%d",
            market_id, asset, thesis_side, inverted_side, fill_id, context,
            self._inversion_count, self._inversion_by_market[market_id]
        )
    
    def record_sync_error(
        self,
        market_id: str,
        thesis_side: str,
        rest_side: str,
        context: str = "rest_sync"
    ) -> None:
        """
        Record a REST sync error where REST disagrees with thesis.
        
        Args:
            market_id: Market ticker where sync error occurred
            thesis_side: The thesis side from position cache
            rest_side: The side reported by REST API
            context: Context where sync error was detected
        """
        self._sync_error_count += 1
        self._sync_error_by_market[market_id] += 1
        self._last_sync_error_time = datetime.now(timezone.utc)
        
        # Extract asset from market_id
        asset = self._extract_asset(market_id)
        if asset:
            self._sync_error_by_asset = self._sync_error_by_asset  # Initialize if needed
            if asset not in self._sync_error_by_asset:
                self._sync_error_by_asset[asset] = 0
            self._sync_error_by_asset[asset] += 1
        
        # Log critical alert
        logger.critical(
            "[THESIS-SIDE-SYNC-ERROR] market=%s asset=%s thesis=%s rest=%s context=%s "
            "total_sync_errors=%d market_sync_errors=%d",
            market_id, asset, thesis_side, rest_side, context,
            self._sync_error_count, self._sync_error_by_market[market_id]
        )
    
    def record_legacy_mapping_usage(
        self,
        market_id: str,
        reason: str = "unknown"
    ) -> None:
        """
        Record usage of legacy direction mapping (should be rare).
        
        Args:
            market_id: Market ticker where legacy mapping was used
            reason: Reason for using legacy mapping (feature_flag_enabled, missing_thesis_side, etc.)
        """
        self._legacy_mapping_count += 1
        self._legacy_mapping_by_market[market_id] += 1
        self._legacy_mapping_by_reason[reason] += 1
        
        # Log warning (legacy mapping should be rare)
        logger.warning(
            "[THESIS-SIDE-LEGACY-MAPPING] market=%s reason=%s total_legacy_usage=%d market_legacy_usage=%d",
            market_id, reason, self._legacy_mapping_count, self._legacy_mapping_by_market[market_id]
        )
    
    def record_external_trade(
        self,
        market_id: str,
        fill_agent_id: str,
        position_agent_id: Optional[str] = None,
        fill_id: Optional[str] = None
    ) -> None:
        """
        Record an external trade (fill from non-15m agent on a 15m market).
        
        Args:
            market_id: Market ticker where external trade occurred
            fill_agent_id: Agent ID from the fill (non-15m agent)
            position_agent_id: Agent ID of the cached position (if any)
            fill_id: Optional fill ID for traceability
        """
        # Track external trades by market
        self._external_trade_count = getattr(self, '_external_trade_count', 0) + 1
        external_by_market = getattr(self, '_external_trade_by_market', {})
        external_by_market[market_id] = external_by_market.get(market_id, 0) + 1
        self._external_trade_by_market = external_by_market
        
        # Log warning for external trade on 15m market
        logger.warning(
            "[THESIS-SIDE-EXTERNAL-TRADE] market=%s fill_agent_id=%s position_agent_id=%s fill_id=%s "
            "total_external_trades=%d market_external_trades=%d - "
            "External agent trading on 15m market detected",
            market_id, fill_agent_id, position_agent_id, fill_id,
            self._external_trade_count, external_by_market[market_id]
        )
    
    def _extract_asset(self, market_id: str) -> Optional[str]:
        """Extract asset from market_id (e.g., KXBTC15M -> BTC)."""
        if "KXBTC" in market_id:
            return "BTC"
        elif "KXETH" in market_id:
            return "ETH"
        elif "KXSOL" in market_id:
            return "SOL"
        elif "KXXRP" in market_id:
            return "XRP"
        elif "KXDOGE" in market_id:
            return "DOGE"
        return None
    
    def get_metrics(self) -> Dict:
        """
        Get current metrics for monitoring dashboards.
        
        Returns:
            Dict with current metrics including:
            - total_inversions: Total number of inversions detected
            - total_sync_errors: Total number of sync errors detected
            - total_legacy_mapping_usage: Total number of legacy mapping uses
            - inversion_by_market: Inversions per market
            - inversion_by_asset: Inversions per asset
            - sync_error_by_market: Sync errors per market
            - sync_error_by_asset: Sync errors per asset
            - legacy_mapping_by_market: Legacy mapping usage per market
            - legacy_mapping_by_reason: Legacy mapping usage by reason
            - last_inversion_time: Timestamp of last inversion
            - last_sync_error_time: Timestamp of last sync error
            - recent_inversions: List of recent inversion incidents
        """
        return {
            "total_inversions": self._inversion_count,
            "total_sync_errors": self._sync_error_count,
            "total_legacy_mapping_usage": self._legacy_mapping_count,
            "total_external_trades": getattr(self, '_external_trade_count', 0),
            "inversion_by_market": dict(self._inversion_by_market),
            "inversion_by_asset": dict(self._inversion_by_asset),
            "sync_error_by_market": dict(self._sync_error_by_market),
            "sync_error_by_asset": dict(getattr(self, '_sync_error_by_asset', {})),
            "legacy_mapping_by_market": dict(self._legacy_mapping_by_market),
            "legacy_mapping_by_reason": dict(self._legacy_mapping_by_reason),
            "external_trade_by_market": dict(getattr(self, '_external_trade_by_market', {})),
            "last_inversion_time": self._last_inversion_time.isoformat() if self._last_inversion_time else None,
            "last_sync_error_time": self._last_sync_error_time.isoformat() if self._last_sync_error_time else None,
            "recent_inversions": self._inversion_history[-10:] if self._inversion_history else []
        }
    
    def get_inversion_rate(self, window_minutes: int = 60) -> float:
        """
        Calculate inversion rate over a time window.
        
        Args:
            window_minutes: Time window in minutes
            
        Returns:
            Inversions per minute over the window
        """
        if not self._inversion_history:
            return 0.0
        
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
        recent_inversions = [
            inc for inc in self._inversion_history
            if datetime.fromisoformat(inc["timestamp"]) >= cutoff_time
        ]
        
        return len(recent_inversions) / window_minutes if window_minutes > 0 else 0.0
    
    def check_thresholds(self, inversion_threshold: int = 5, sync_error_threshold: int = 5) -> Dict:
        """
        Check if metrics exceed alert thresholds.
        
        Args:
            inversion_threshold: Alert threshold for inversions per market
            sync_error_threshold: Alert threshold for sync errors per market
            
        Returns:
            Dict with threshold check results and any alerts
        """
        alerts = []
        
        # Check per-market inversion thresholds
        for market, count in self._inversion_by_market.items():
            if count >= inversion_threshold:
                alerts.append({
                    "type": "inversion_threshold",
                    "market": market,
                    "count": count,
                    "threshold": inversion_threshold,
                    "severity": "critical" if count >= inversion_threshold * 2 else "warning"
                })
        
        # Check per-market sync error thresholds
        for market, count in self._sync_error_by_market.items():
            if count >= sync_error_threshold:
                alerts.append({
                    "type": "sync_error_threshold",
                    "market": market,
                    "count": count,
                    "threshold": sync_error_threshold,
                    "severity": "critical" if count >= sync_error_threshold * 2 else "warning"
                })
        
        return {
            "alerts": alerts,
            "alert_count": len(alerts),
            "has_critical_alerts": any(a["severity"] == "critical" for a in alerts)
        }
    
    def reset_metrics(self) -> None:
        """Reset all metrics (use with caution, typically only after manual intervention)."""
        logger.warning("[THESIS-SIDE-MONITOR] Resetting all metrics - manual intervention required")
        self._inversion_count = 0
        self._inversion_by_market.clear()
        self._inversion_by_asset.clear()
        self._inversion_history.clear()
        self._sync_error_count = 0
        self._sync_error_by_market.clear()
        self._last_inversion_time = None
        self._last_sync_error_time = None


# Global singleton instance
_monitor: Optional[ThesisSideMonitor] = None


def get_thesis_side_monitor() -> ThesisSideMonitor:
    """Get the global thesis side monitor instance."""
    global _monitor
    if _monitor is None:
        _monitor = ThesisSideMonitor()
    return _monitor
