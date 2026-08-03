"""
Dynamic Threshold Manager for Kalshi 15m Crypto Trading System

Manages dynamic thresholds based on regime detection:
- Price range (10-75c canonical, 5-95c crisis)
- Spread threshold (30c canonical, 100c crisis)
- Liquidity thresholds (static)
- Position size adjustments

Integrates with profile YAML for canonical/crisis configuration.
Uses regime detector for runtime adjustment.

Reference: DYNAMIC_THRESHOLD_RESEARCH_AND_RECOMMENDATIONS.md
"""

from dataclasses import dataclass
from typing import Optional, Dict
from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
from merid.event_venues.kalshi.regime_detector import (
    RegimeDetector, 
    Regime, 
    get_regime_detector,
    reset_regime_detector
)
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.dynamic_thresholds")


@dataclass
class DynamicThresholds:
    """Dynamic thresholds for current regime."""
    min_price_cents: int
    max_price_cents: int
    max_spread_cents: int
    min_spread_gate_cents: int
    max_spread_to_edge_ratio: float  # Maximum spread/edge ratio (dynamic by regime)
    min_volume: int
    min_depth: int
    regime: str
    adjustment_factors: Dict[str, float]
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for logging/serialization."""
        return {
            "min_price_cents": self.min_price_cents,
            "max_price_cents": self.max_price_cents,
            "max_spread_cents": self.max_spread_cents,
            "min_spread_gate_cents": self.min_spread_gate_cents,
            "max_spread_to_edge_ratio": self.max_spread_to_edge_ratio,
            "min_volume": self.min_volume,
            "min_depth": self.min_depth,
            "regime": self.regime,
            "adjustment_factors": self.adjustment_factors
        }


class DynamicThresholdManager:
    """
    Manages dynamic thresholds based on regime detection.
    
    Loads canonical/crisis configuration from profile YAML.
    Applies regime-based adjustment factors at runtime.
    """
    
    def __init__(self):
        self.profile_adapter = Crypto15mProfileAdapter()
        self.regime_detector = get_regime_detector()
        self.current_thresholds: Optional[DynamicThresholds] = None
        
        # Load regime detection configuration from profile
        self._load_regime_config()
    
    def _load_regime_config(self):
        """Load regime detection configuration from profile."""
        try:
            profile = self.profile_adapter.profile
            if hasattr(profile, 'regime_detection'):
                regime_config = profile.regime_detection
                if hasattr(regime_config, 'thresholds') and hasattr(regime_config.thresholds, 'atr_pct'):
                    atr_thresholds = regime_config.thresholds.atr_pct
                    self.regime_detector.set_atr_thresholds(atr_thresholds)
                    logger.info(
                        "[DYNAMIC-THRESHOLDS] Loaded ATR thresholds from profile: %s",
                        atr_thresholds
                    )
        except Exception as e:
            logger.warning(
                "[DYNAMIC-THRESHOLDS] Failed to load regime config from profile: %s",
                e
            )
    
    def update(self, price_series: Dict, volume_series: Dict, 
               order_book_depth: Dict) -> DynamicThresholds:
        """
        Update dynamic thresholds based on current regime.
        
        Args:
            price_series: Dict of price series by asset
            volume_series: Dict of volume series by asset
            order_book_depth: Dict of order book depth by asset
            
        Returns:
            Current dynamic thresholds
        """
        # Update regime detection
        regime_state = self.regime_detector.update(
            price_series,
            volume_series,
            order_book_depth
        )
        
        # Get profile configuration
        profile = self.profile_adapter.profile
        canonical = self._get_canonical_config(profile)
        crisis = self._get_crisis_config(profile)
        
        # Get adjustment factors
        adjustment = self.regime_detector.get_adjustment_factor()
        
        # Apply adjustments based on regime
        if regime_state.current == Regime.CRISIS:
            base = crisis
        else:
            base = canonical
        
        thresholds = DynamicThresholds(
            min_price_cents = int(base["price_range"]["min_cents"] * adjustment["price_range_multiplier"]),
            max_price_cents = int(base["price_range"]["max_cents"] * adjustment["price_range_multiplier"]),
            max_spread_cents = int(base["spread"]["max_cents"] * adjustment["spread_multiplier"]),
            min_spread_gate_cents = base["spread"]["min_gate_cents"],
            max_spread_to_edge_ratio = base["spread"]["max_spread_to_edge_ratio"] * adjustment.get("spread_to_edge_ratio_multiplier", 1.0),
            min_volume = base["liquidity"]["min_volume_24h"],
            min_depth = base["liquidity"]["min_depth_top_of_book"],
            regime = regime_state.current.value,
            adjustment_factors = adjustment
        )
        
        self.current_thresholds = thresholds
        logger.debug(
            "[DYNAMIC-THRESHOLDS] Updated thresholds: regime=%s, price_range=%d-%dc, spread=%dc",
            thresholds.regime, thresholds.min_price_cents, thresholds.max_price_cents,
            thresholds.max_spread_cents
        )
        
        return thresholds
    
    def _get_canonical_config(self, profile) -> Dict:
        """
        Get canonical configuration from profile.
        
        Args:
            profile: Profile adapter instance
            
        Returns:
            Dict of canonical configuration
        """
        if hasattr(profile, 'canonical'):
            return {
                "price_range": {
                    "min_cents": profile.canonical.price_range.min_cents,
                    "max_cents": profile.canonical.price_range.max_cents
                },
                "spread": {
                    "max_cents": profile.canonical.spread.max_cents,
                    "min_gate_cents": profile.canonical.spread.min_gate_cents,
                    "max_spread_to_edge_ratio": profile.canonical.spread.max_spread_to_edge_ratio
                },
                "liquidity": {
                    "min_volume_24h": profile.canonical.liquidity.min_volume_24h,
                    "min_depth_top_of_book": profile.canonical.liquidity.min_depth_top_of_book
                }
            }
        else:
            # Fallback to guardrails if canonical not defined
            return self._get_fallback_canonical()
    
    def _get_crisis_config(self, profile) -> Dict:
        """
        Get crisis configuration from profile.
        
        Args:
            profile: Profile adapter instance
            
        Returns:
            Dict of crisis configuration
        """
        if hasattr(profile, 'crisis'):
            return {
                "price_range": {
                    "min_cents": profile.crisis.price_range.min_cents,
                    "max_cents": profile.crisis.price_range.max_cents
                },
                "spread": {
                    "max_cents": profile.crisis.spread.max_cents,
                    "min_gate_cents": profile.crisis.spread.min_gate_cents,
                    "max_spread_to_edge_ratio": profile.crisis.spread.max_spread_to_edge_ratio
                },
                "liquidity": {
                    "min_volume_24h": profile.crisis.liquidity.min_volume_24h,
                    "min_depth_top_of_book": profile.crisis.liquidity.min_depth_top_of_book
                }
            }
        else:
            # Fallback to guardrails if crisis not defined
            return self._get_fallback_crisis()
    
    def _get_fallback_canonical(self) -> Dict:
        """Fallback canonical thresholds if profile not updated."""
        return {
            "price_range": {"min_cents": 10, "max_cents": 75},  # 2026-07-12: Expanded to 75c for market conditions
            # CRITICAL FIX (2026-07-27): Increased max_spread_to_edge_ratio from 0.4 to 0.8
            # Previous 0.4 threshold was too strict for current market conditions where spread/edge ratios
            # are frequently 0.8-1.1 due to wider spreads and moderate edges. Relaxing to 0.8 allows
            # more orders to pass while still protecting against extremely wide spreads (>80% of edge).
            "spread": {"max_cents": 30, "min_gate_cents": 30, "max_spread_to_edge_ratio": 0.8},
            "liquidity": {"min_volume_24h": 500, "min_depth_top_of_book": 100}
        }
    
    def _get_fallback_crisis(self) -> Dict:
        """Fallback crisis thresholds if profile not updated."""
        return {
            "price_range": {"min_cents": 5, "max_cents": 95},
            "spread": {"max_cents": 100, "min_gate_cents": 30, "max_spread_to_edge_ratio": 1.5},
            "liquidity": {"min_volume_24h": 500, "min_depth_top_of_book": 100}
        }
    
    def get_current_thresholds(self) -> DynamicThresholds:
        """
        Get current dynamic thresholds.
        
        Returns:
            Current dynamic thresholds (initializes with canonical if not set)
        """
        if self.current_thresholds is None:
            # Initialize with canonical thresholds
            return self._initialize_with_canonical()
        return self.current_thresholds
    
    def _initialize_with_canonical(self) -> DynamicThresholds:
        """Initialize thresholds with canonical configuration."""
        profile = self.profile_adapter.profile
        canonical = self._get_canonical_config(profile)
        
        thresholds = DynamicThresholds(
            min_price_cents = canonical["price_range"]["min_cents"],
            max_price_cents = canonical["price_range"]["max_cents"],
            max_spread_cents = canonical["spread"]["max_cents"],
            min_spread_gate_cents = canonical["spread"]["min_gate_cents"],
            max_spread_to_edge_ratio = canonical["spread"]["max_spread_to_edge_ratio"],
            min_volume = canonical["liquidity"]["min_volume_24h"],
            min_depth = canonical["liquidity"]["min_depth_top_of_book"],
            regime = "MEAN_REVERSION",  # Default regime
            adjustment_factors = {
                "price_range_multiplier": 1.0,
                "spread_multiplier": 1.0,
                "spread_to_edge_ratio_multiplier": 1.0,
                "position_size_multiplier": 1.0
            }
        )
        
        self.current_thresholds = thresholds
        return thresholds
    
    def get_price_range(self) -> tuple[int, int]:
        """Get current price range (min, max)."""
        thresholds = self.get_current_thresholds()
        return thresholds.min_price_cents, thresholds.max_price_cents
    
    def get_max_spread_cents(self) -> int:
        """Get current max spread threshold."""
        thresholds = self.get_current_thresholds()
        return thresholds.max_spread_cents
    
    def get_min_spread_gate_cents(self) -> int:
        """Get current min spread gate threshold."""
        thresholds = self.get_current_thresholds()
        return thresholds.min_spread_gate_cents
    
    def get_max_spread_to_edge_ratio(self) -> float:
        """Get current max spread/edge ratio threshold."""
        thresholds = self.get_current_thresholds()
        return thresholds.max_spread_to_edge_ratio
    
    def get_liquidity_thresholds(self) -> tuple[int, int]:
        """Get current liquidity thresholds (min_volume, min_depth)."""
        thresholds = self.get_current_thresholds()
        return thresholds.min_volume, thresholds.min_depth
    
    def get_regime(self) -> str:
        """Get current regime."""
        thresholds = self.get_current_thresholds()
        return thresholds.regime
    
    def get_position_size_multiplier(self) -> float:
        """Get current position size multiplier."""
        thresholds = self.get_current_thresholds()
        return thresholds.adjustment_factors.get("position_size_multiplier", 1.0)


# Global singleton instance
_threshold_manager: Optional[DynamicThresholdManager] = None


def get_dynamic_threshold_manager() -> DynamicThresholdManager:
    """Get global dynamic threshold manager singleton instance."""
    global _threshold_manager
    if _threshold_manager is None:
        _threshold_manager = DynamicThresholdManager()
    return _threshold_manager


def reset_dynamic_threshold_manager():
    """Reset global dynamic threshold manager singleton (for testing)."""
    global _threshold_manager
    _threshold_manager = None
    reset_regime_detector()
