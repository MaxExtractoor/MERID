"""
Coarse Filter Module for Kalshi 15m Crypto Trading System

Implements hierarchical sequential gates for universe reduction:
1. τ-gate (time to expiry)
2. Asset whitelist
3. Price range gate (dynamic)
4. Spread gate (dynamic)
5. Volume/depth gate
6. Edge gate

Each gate is a binary veto—no compensation between gates.
Order matters: cheap gates first, expensive gates later.

Reference: DYNAMIC_THRESHOLD_RESEARCH_AND_RECOMMENDATIONS.md
"""

from dataclasses import dataclass
from typing import List, Callable, Optional
from merid.event_venues.kalshi.dynamic_thresholds import (
    DynamicThresholdManager,
    get_dynamic_threshold_manager
)
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.coarse_filter")


@dataclass
class MarketCandidate:
    """Market candidate for filtering."""
    ticker: str
    price_cents: int
    spread_cents: int
    volume_24h: int
    depth_bid: int
    depth_ask: int
    time_to_expiry_minutes: int
    asset: str
    
    def to_dict(self) -> dict:
        """Convert to dictionary for logging."""
        return {
            "ticker": self.ticker,
            "price_cents": self.price_cents,
            "spread_cents": self.spread_cents,
            "volume_24h": self.volume_24h,
            "depth_bid": self.depth_bid,
            "depth_ask": self.depth_ask,
            "time_to_expiry_minutes": self.time_to_expiry_minutes,
            "asset": self.asset
        }


class CoarseFilter:
    """
    Hierarchical sequential coarse filter for universe reduction.
    
    Applies gates in sequence to efficiently filter markets.
    Each gate is a binary veto—no compensation between gates.
    """
    
    def __init__(self):
        self.threshold_manager = get_dynamic_threshold_manager()
        self.gates = [
            self._tau_gate,
            self._asset_whitelist_gate,
            self._price_range_gate,
            self._spread_gate,
            self._volume_depth_gate,
            self._edge_gate,
        ]
        
        # Gate configuration from profile
        self.min_tau_minutes = 5
        self.max_tau_minutes = 1440  # 24 hours
        self.allowed_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        self.min_implied_yield_pct = 50
        self.min_edge_vs_model_pct = 5
        
        # Load configuration from profile
        self._load_profile_config()
    
    def _load_profile_config(self):
        """Load gate configuration from profile YAML."""
        try:
            from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
            adapter = Crypto15mProfileAdapter()
            profile = adapter.profile
            
            if hasattr(profile, 'coarse_filters') and hasattr(profile.coarse_filters, 'gates'):
                for gate_config in profile.coarse_filters.gates:
                    if gate_config.name == "tau_gate" and gate_config.enabled:
                        self.min_tau_minutes = gate_config.min_minutes
                        self.max_tau_minutes = gate_config.max_minutes
                    elif gate_config.name == "asset_whitelist" and gate_config.enabled:
                        self.allowed_assets = gate_config.assets
                    elif gate_config.name == "edge_gate" and gate_config.enabled:
                        self.min_implied_yield_pct = gate_config.min_implied_yield_pct
                        self.min_edge_vs_model_pct = gate_config.min_edge_vs_model_pct
                
                logger.info(
                    "[COARSE-FILTER] Loaded gate configuration from profile: "
                    "tau=%d-%dmin, assets=%s",
                    self.min_tau_minutes, self.max_tau_minutes, self.allowed_assets
                )
        except Exception as e:
            logger.warning(
                "[COARSE-FILTER] Failed to load gate config from profile: %s",
                e
            )
    
    def filter(self, markets: List[MarketCandidate]) -> List[MarketCandidate]:
        """
        Apply hierarchical sequential gates to filter markets.
        
        Args:
            markets: List of market candidates
            
        Returns:
            Filtered list of market candidates
        """
        candidates = markets
        initial_count = len(candidates)
        
        for i, gate in enumerate(self.gates):
            before_count = len(candidates)
            candidates = [m for m in candidates if gate(m)]
            after_count = len(candidates)
            
            if after_count < before_count:
                logger.debug(
                    "[COARSE-FILTER] Gate %d: %d -> %d candidates",
                    i + 1, before_count, after_count
                )
            
            if not candidates:
                logger.debug(
                    "[COARSE-FILTER] No candidates remaining after gate %d",
                    i + 1
                )
                break
        
        logger.info(
            "[COARSE-FILTER] Filtered %d -> %d candidates (%.1f%% reduction)",
            initial_count, len(candidates),
            (1 - len(candidates) / initial_count) * 100 if initial_count > 0 else 0
        )
        
        return candidates
    
    def _tau_gate(self, market: MarketCandidate) -> bool:
        """
        Gate 1: Time to expiry check.
        
        Args:
            market: Market candidate
            
        Returns:
            True if market passes gate, False otherwise
        """
        thresholds = self.threshold_manager.get_current_thresholds()
        return self.min_tau_minutes <= market.time_to_expiry_minutes <= self.max_tau_minutes
    
    def _asset_whitelist_gate(self, market: MarketCandidate) -> bool:
        """
        Gate 2: Asset whitelist check.
        
        Args:
            market: Market candidate
            
        Returns:
            True if market passes gate, False otherwise
        """
        return market.asset in self.allowed_assets
    
    def _price_range_gate(self, market: MarketCandidate) -> bool:
        """
        Gate 3: Dynamic price range check.
        
        Args:
            market: Market candidate
            
        Returns:
            True if market passes gate, False otherwise
        """
        thresholds = self.threshold_manager.get_current_thresholds()
        return (thresholds.min_price_cents <= market.price_cents <= 
                thresholds.max_price_cents)
    
    def _spread_gate(self, market: MarketCandidate) -> bool:
        """
        Gate 4: Dynamic spread check.
        
        Args:
            market: Market candidate
            
        Returns:
            True if market passes gate, False otherwise
        """
        thresholds = self.threshold_manager.get_current_thresholds()
        return market.spread_cents <= thresholds.max_spread_cents
    
    def _volume_depth_gate(self, market: MarketCandidate) -> bool:
        """
        Gate 5: Volume and depth check.
        
        Args:
            market: Market candidate
            
        Returns:
            True if market passes gate, False otherwise
        """
        thresholds = self.threshold_manager.get_current_thresholds()
        return (market.volume_24h >= thresholds.min_volume and
                market.depth_bid >= thresholds.min_depth and
                market.depth_ask >= thresholds.min_depth)
    
    def _edge_gate(self, market: MarketCandidate) -> bool:
        """
        Gate 6: Edge check (requires model prediction).
        
        This gate is deferred to agent grid for actual edge calculation.
        For now, return True (deferred evaluation).
        
        Args:
            market: Market candidate
            
        Returns:
            True (deferred to agent grid)
        """
        # Edge calculation requires signal generation
        # This gate is applied later in the pipeline
        return True
    
    def get_gate_stats(self, markets: List[MarketCandidate]) -> dict:
        """
        Get statistics for each gate.
        
        Args:
            markets: List of market candidates
            
        Returns:
            Dict of gate statistics
        """
        stats = {}
        candidates = markets
        
        for i, gate in enumerate(self.gates):
            gate_name = gate.__name__.replace("_gate", "")
            before_count = len(candidates)
            candidates = [m for m in candidates if gate(m)]
            after_count = len(candidates)
            
            stats[gate_name] = {
                "before": before_count,
                "after": after_count,
                "filtered": before_count - after_count,
                "pass_rate": after_count / before_count if before_count > 0 else 0
            }
        
        return stats


# Global singleton instance
_coarse_filter: Optional[CoarseFilter] = None


def get_coarse_filter() -> CoarseFilter:
    """Get global coarse filter singleton instance."""
    global _coarse_filter
    if _coarse_filter is None:
        _coarse_filter = CoarseFilter()
    return _coarse_filter


def reset_coarse_filter():
    """Reset global coarse filter singleton (for testing)."""
    global _coarse_filter
    _coarse_filter = None
