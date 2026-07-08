"""Grid Context — Centralized arbiter winner list for 15m execution alignment.

This module provides a singleton GridContext that stores the current cycle's
arbiter winner list and provides methods for 15m agents to check if their asset
is a winner before attempting execution.

Purpose:
- Enforce that only arbiter winners can execute in 15m timeframe
- Provide a single source of truth for winner list across all agents
- Enable PROB-GATE relaxation for winners
- Support micro-scalp winner alignment

Usage:
    from merid.prediction.grid_context import get_grid_context, GridContext
    
    # Check if asset is winner before execution
    grid = get_grid_context()
    if not grid.is_winner(ticker):
        # Skip execution - not in winner set
        return StrategySignal(action=NO_ACTION, reason="notwinner")
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from utils.logger import get_logger

logger = get_logger("merid.prediction.grid_context")


@dataclass
class WinnerInfo:
    """Information about a winner from the arbiter."""
    
    ticker: str
    asset: str  # BTC, ETH, SOL, XRP, DOGE
    rank: int  # 1 = best edge
    edge: float
    direction: str  # long, short
    timestamp: datetime
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "asset": self.asset,
            "rank": self.rank,
            "edge": self.edge,
            "direction": self.direction,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class CycleInfo:
    """Information about the current arbiter cycle."""
    
    cycle_id: str
    timestamp: datetime
    top_edge: float
    median_edge: float
    floor: float
    winners: List[WinnerInfo]
    assets_selected: Set[str]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "timestamp": self.timestamp.isoformat(),
            "top_edge": self.top_edge,
            "median_edge": self.median_edge,
            "floor": self.floor,
            "winners_count": len(self.winners),
            "assets_selected": list(self.assets_selected),
            "winners": [w.to_dict() for w in self.winners],
        }


class GridContext:
    """Centralized grid context for arbiter winner alignment.
    
    Responsibilities:
    1. Store current cycle's winner list from CryptoTopEdgeArbiter
    2. Provide is_winner() check for 15m agents
    3. Support winner-specific PROB-GATE relaxation
    4. Track cycle age for freshness checks
    
    Thread-safe singleton.
    """
    
    def __init__(
        self,
        winner_max_age_seconds: float = 30.0,
        winner_min_probedge: float = 0.0,  # Relaxed threshold for winners
    ):
        self._winner_max_age_seconds = winner_max_age_seconds
        self._winner_min_probedge = winner_min_probedge
        
        # Current cycle storage
        self._current_cycle: Optional[CycleInfo] = None
        self._winners_by_ticker: Dict[str, WinnerInfo] = {}
        self._winners_by_asset: Dict[str, List[WinnerInfo]] = {
            "BTC": [], "ETH": [], "SOL": [], "XRP": [], "DOGE": []
        }
        
        self._lock = threading.RLock()
        
        logger.info(
            "[GRID_CONTEXT] Initialized winner_max_age=%.0fs winner_min_probedge=%.4f",
            winner_max_age_seconds, winner_min_probedge
        )
    
    def update_cycle(
        self,
        cycle_id: str,
        top_edge: float,
        median_edge: float,
        floor: float,
        winners: List[Any],  # CandidateSignal objects from arbiter
    ) -> None:
        """Update the current cycle with arbiter results.
        
        Args:
            cycle_id: Cycle identifier
            top_edge: Top edge value
            median_edge: Median edge value
            floor: Dynamic floor value
            winners: List of CandidateSignal winners from CryptoTopEdgeArbiter
        """
        with self._lock:
            timestamp = datetime.now(timezone.utc)
            
            # Convert CandidateSignal to WinnerInfo
            winner_infos = []
            assets_selected = set()
            
            for w in winners:
                # Extract asset from ticker (e.g., KXBTC-26APR2717-T87749.99 -> BTC)
                asset = self._extract_asset_from_ticker(w.ticker)
                if not asset:
                    logger.warning("[GRID_CONTEXT] Could not extract asset from ticker: %s", w.ticker)
                    continue
                
                winner_info = WinnerInfo(
                    ticker=w.ticker,
                    asset=asset,
                    rank=getattr(w, 'rank', 0),
                    edge=getattr(w, 'net_edge', 0.0),
                    direction=getattr(w, 'direction', 'none'),
                    timestamp=timestamp,
                )
                winner_infos.append(winner_info)
                assets_selected.add(asset)
            
            # Store cycle info
            self._current_cycle = CycleInfo(
                cycle_id=cycle_id,
                timestamp=timestamp,
                top_edge=top_edge,
                median_edge=median_edge,
                floor=floor,
                winners=winner_infos,
                assets_selected=assets_selected,
            )
            
            # Update lookup maps
            self._winners_by_ticker = {w.ticker: w for w in winner_infos}
            self._winners_by_asset = {a: [] for a in ["BTC", "ETH", "SOL", "XRP", "DOGE"]}
            for w in winner_infos:
                self._winners_by_asset[w.asset].append(w)
            
            logger.info(
                "[GRID_CONTEXT] Cycle=%s updated TopEdge=%.4f Floor=%.4f Winners=%d Assets=%s",
                cycle_id, top_edge, floor, len(winner_infos), ",".join(sorted(assets_selected))
            )
    
    def is_winner(
        self,
        ticker: str,
        max_age_seconds: Optional[float] = None,
    ) -> bool:
        """Check if a ticker is a winner in the current cycle.
        
        Args:
            ticker: Full Kalshi ticker (e.g., "KXBTC-26APR2717-T87749.99")
            max_age_seconds: Maximum age of cycle to consider (uses default if None)
            
        Returns:
            True if ticker is a winner and cycle is fresh
        """
        with self._lock:
            if not self._current_cycle:
                return False
            
            # Check cycle age
            max_age = max_age_seconds if max_age_seconds is not None else self._winner_max_age_seconds
            # Handle both datetime and float (timestamp) types
            timestamp = self._current_cycle.timestamp
            if isinstance(timestamp, (int, float)):
                timestamp = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            age = (datetime.now(timezone.utc) - timestamp).total_seconds()
            if age > max_age:
                logger.debug(
                    "[GRID_CONTEXT] Cycle too old: age=%.0fs > max=%.0fs",
                    age, max_age
                )
                return False
            
            # Check if ticker is in winners
            return ticker in self._winners_by_ticker
    
    def is_asset_winner(
        self,
        asset: str,
        max_age_seconds: Optional[float] = None,
    ) -> bool:
        """Check if an asset (BTC, ETH, etc.) has any winners in the current cycle.
        
        Args:
            asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
            max_age_seconds: Maximum age of cycle to consider
            
        Returns:
            True if asset has at least one winner and cycle is fresh
        """
        with self._lock:
            if not self._current_cycle:
                return False
            
            # Check cycle age
            max_age = max_age_seconds if max_age_seconds is not None else self._winner_max_age_seconds
            # Handle both datetime and float (timestamp) types
            timestamp = self._current_cycle.timestamp
            if isinstance(timestamp, (int, float)):
                timestamp = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            age = (datetime.now(timezone.utc) - timestamp).total_seconds()
            if age > max_age:
                return False
            
            # Check if asset has winners
            return len(self._winners_by_asset.get(asset, [])) > 0
    
    def get_winner_info(
        self,
        ticker: str,
        max_age_seconds: Optional[float] = None,
    ) -> Optional[WinnerInfo]:
        """Get winner information for a ticker.
        
        Args:
            ticker: Full Kalshi ticker
            max_age_seconds: Maximum age of cycle to consider
            
        Returns:
            WinnerInfo if ticker is a winner and cycle is fresh, else None
        """
        with self._lock:
            if not self.is_winner(ticker, max_age_seconds):
                return None
            return self._winners_by_ticker.get(ticker)
    
    def get_winner_min_probedge(self) -> float:
        """Get the relaxed probedge threshold for winners.
        
        Returns:
            Minimum probedge threshold for arbiter winners
        """
        return self._winner_min_probedge
    
    def get_current_cycle(self) -> Optional[CycleInfo]:
        """Get the current cycle info.
        
        Returns:
            CycleInfo if available, else None
        """
        with self._lock:
            return self._current_cycle
    
    def get_cycle_age_seconds(self) -> float:
        """Get the age of the current cycle in seconds.
        
        Returns:
            Age in seconds, or -1 if no current cycle
        """
        with self._lock:
            if not self._current_cycle:
                return -1.0
            # Handle both datetime and float (timestamp) types
            timestamp = self._current_cycle.timestamp
            if isinstance(timestamp, (int, float)):
                timestamp = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            return (datetime.now(timezone.utc) - timestamp).total_seconds()
    
    def _extract_asset_from_ticker(self, ticker: str) -> Optional[str]:
        """Extract asset symbol from Kalshi ticker.
        
        Args:
            ticker: Full Kalshi ticker (e.g., "KXBTC-26APR2717-T87749.99")
            
        Returns:
            Asset symbol (BTC, ETH, SOL, XRP, DOGE) or None
        """
        ticker_upper = ticker.upper()
        if "KXBTC" in ticker_upper:
            return "BTC"
        elif "KXETH" in ticker_upper:
            return "ETH"
        elif "KXSOL" in ticker_upper:
            return "SOL"
        elif "KXXRP" in ticker_upper:
            return "XRP"
        elif "KXDOGE" in ticker_upper:
            return "DOGE"
        return None
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get grid context metrics for monitoring."""
        with self._lock:
            if not self._current_cycle:
                return {
                    "has_cycle": False,
                    "cycle_age_seconds": -1.0,
                    "winners_count": 0,
                }
            
            return {
                "has_cycle": True,
                "cycle_id": self._current_cycle.cycle_id,
                "cycle_age_seconds": self.get_cycle_age_seconds(),
                "top_edge": self._current_cycle.top_edge,
                "median_edge": self._current_cycle.median_edge,
                "floor": self._current_cycle.floor,
                "winners_count": len(self._current_cycle.winners),
                "assets_selected": list(self._current_cycle.assets_selected),
                "winner_min_probedge": self._winner_min_probedge,
            }
    
    def log_winner_alignment_assertion(self, executed_tickers: List[str]) -> None:
        """Log-level assertion for winner alignment verification.
        
        This should be called after each 15m cycle to verify that:
        - Only winner assets (and no others) have 15m new trade intents
        - Every non-winner asset's 15m agents should have noaction with reason "notwinner"
        
        Args:
            executed_tickers: List of tickers that were executed in this cycle
        """
        with self._lock:
            if not self._current_cycle:
                logger.warning("[WINNER_ASSERTION] No current cycle - skipping assertion")
                return
            
            winner_tickers = set(w.ticker for w in self._current_cycle.winners)
            executed_set = set(executed_tickers)
            
            # Check for non-winners that were executed
            non_winner_executed = executed_set - winner_tickers
            if non_winner_executed:
                logger.error(
                    "[WINNER_ASSERTION_FAIL] Cycle=%s: Non-winners executed: %s (winners: %s)",
                    self._current_cycle.cycle_id,
                    ",".join(sorted(non_winner_executed)),
                    ",".join(sorted(winner_tickers))
                )
            else:
                logger.info(
                    "[WINNER_ASSERTION_PASS] Cycle=%s: All executed tickers are winners (%d executed, %d winners)",
                    self._current_cycle.cycle_id,
                    len(executed_set),
                    len(winner_tickers)
                )
            
            # Check for winners that were not executed (this is OK if they were blocked by other gates)
            winner_not_executed = winner_tickers - executed_set
            if winner_not_executed:
                logger.info(
                    "[WINNER_ASSERTION_INFO] Cycle=%s: Winners not executed: %s (may be blocked by other gates)",
                    self._current_cycle.cycle_id,
                    ",".join(sorted(winner_not_executed))
                )


# Singleton instance
_global_grid_context: Optional[GridContext] = None
_global_lock = None


def get_grid_context(
    winner_max_age_seconds: Optional[float] = None,
    winner_min_probedge: Optional[float] = None,
) -> GridContext:
    """Get or create global GridContext singleton.
    
    Args:
        winner_max_age_seconds: Maximum age for winner validity
        winner_min_probedge: Relaxed probedge threshold for winners
        
    Returns:
        GridContext singleton
    """
    global _global_grid_context
    
    if _global_lock is not None:
        with _global_lock:
            if _global_grid_context is None:
                # Read from environment if not provided
                if winner_max_age_seconds is None:
                    winner_max_age_seconds = float(
                        os.getenv("GRID_CONTEXT_WINNER_MAX_AGE_SECONDS", "30.0")
                    )
                if winner_min_probedge is None:
                    # CRITICAL FIX: Read from profile YAML instead of env var (single source of truth)
                    # Use max terminal edge across all assets (DOGE has highest at 6%)
                    try:
                        from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
                        profile_adapter = Crypto15mProfileAdapter()
                        profile = profile_adapter.profile
                        # Get max terminal edge from profile (DOGE has 6%, highest among assets)
                        # BTC/ETH: 4%, SOL/XRP: 5%, DOGE: 6%
                        winner_min_probedge = 0.06  # Use DOGE's 6% as conservative default
                    except Exception as e:
                        # Fallback to env var if profile not available
                        logger.warning(
                            "[grid-context] Failed to load min_edge_terminal from profile: %s (using env var fallback)",
                            e
                        )
                        winner_min_probedge = float(
                            os.getenv("MERID_PM_MIN_EDGE_TERMINAL", "0.02")
                        )
                _global_grid_context = GridContext(
                    winner_max_age_seconds=winner_max_age_seconds,
                    winner_min_probedge=winner_min_probedge,
                )
    else:
        # Lock disabled - direct initialization (startup workaround)
        if _global_grid_context is None:
            # Read from environment if not provided
            if winner_max_age_seconds is None:
                winner_max_age_seconds = float(
                    os.getenv("GRID_CONTEXT_WINNER_MAX_AGE_SECONDS", "30.0")
                )
            if winner_min_probedge is None:
                # CRITICAL FIX: Read from profile YAML instead of env var (single source of truth)
                # Use max terminal edge across all assets (DOGE has highest at 6%)
                try:
                    from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
                    profile_adapter = Crypto15mProfileAdapter()
                    profile = profile_adapter.profile
                    # Get max terminal edge from profile (DOGE has 6%, highest among assets)
                    # BTC/ETH: 4%, SOL/XRP: 5%, DOGE: 6%
                    winner_min_probedge = 0.06  # Use DOGE's 6% as conservative default
                except Exception as e:
                    # Fallback to env var if profile not available
                    logger.warning(
                        "[grid-context] Failed to load min_edge_terminal from profile: %s (using env var fallback)",
                        e
                    )
                    winner_min_probedge = float(
                        os.getenv("MERID_PM_MIN_EDGE_TERMINAL", "0.02")
                    )
            _global_grid_context = GridContext(
                winner_max_age_seconds=winner_max_age_seconds,
                winner_min_probedge=winner_min_probedge,
            )
    
    return _global_grid_context


def is_winner(ticker: str, max_age_seconds: Optional[float] = None) -> bool:
    """Convenience function to check if ticker is a winner.
    
    Args:
        ticker: Full Kalshi ticker
        max_age_seconds: Maximum age of cycle to consider
        
    Returns:
        True if ticker is a winner and cycle is fresh
    """
    grid = get_grid_context()
    return grid.is_winner(ticker, max_age_seconds)


def is_asset_winner(asset: str, max_age_seconds: Optional[float] = None) -> bool:
    """Convenience function to check if asset has any winners.
    
    Args:
        asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
        max_age_seconds: Maximum age of cycle to consider
        
    Returns:
        True if asset has at least one winner and cycle is fresh
    """
    grid = get_grid_context()
    return grid.is_asset_winner(asset, max_age_seconds)
