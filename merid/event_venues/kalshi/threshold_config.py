"""
Threshold Configuration Accessor for Kalshi 15m Trading.

This module provides a single interface to read threshold values from
kalshi_15m_thresholds.yaml. All hardcoded literals in market_state/orderbook
should be replaced with calls to this accessor.

This ensures spread/price/liquidity logic is fully driven by config,
not sprinkled numbers.
"""

import os
import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class SpreadThresholds:
    """Spread thresholds for an asset."""
    max_spread_cents: int


@dataclass
class ExtremePriceThresholds:
    """Extreme price thresholds for an asset."""
    extreme_yes_price_min: int
    extreme_yes_price_max: int


@dataclass
class LiquidityThresholds:
    """Liquidity thresholds for an asset."""
    min_depth_contracts: int
    max_one_sidedness_ratio: float


@dataclass
class StalenessThresholds:
    """Staleness thresholds."""
    max_book_staleness_s: int
    max_quote_staleness_s: int


@dataclass
class DualityThresholds:
    """Duality validation thresholds."""
    duality_tolerance_cents: int


@dataclass
class ExpiryThresholds:
    """Market expiry thresholds."""
    min_seconds_to_expiry: int
    cutoff_seconds_to_expiry: int


@dataclass
class VolumeThresholds:
    """Volume and open interest thresholds."""
    min_volume_24h: int
    min_open_interest: int


class ThresholdConfig:
    """
    Threshold configuration accessor.
    
    This is the SINGLE SOURCE OF TRUTH for all threshold values.
    All modules should read from this instead of using hardcoded literals.
    """
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize threshold config.
        
        Args:
            config_path: Path to thresholds YAML file. If None, uses default.
        """
        if config_path is None:
            # Default path - try both relative to module and relative to repo root
            module_path = Path(__file__).parent.parent.parent / "config" / "kalshi_15m_thresholds.yaml"
            repo_path = Path(__file__).parent.parent.parent.parent / "config" / "kalshi_15m_thresholds.yaml"
            
            # Use whichever path exists
            if module_path.exists():
                config_path = module_path
            elif repo_path.exists():
                config_path = repo_path
            else:
                # Default to module path (will raise error if not found)
                config_path = module_path
        
        self.config_path = Path(config_path)
        self._config: Dict[str, Any] = {}
        self._load_config()
    
    def _load_config(self) -> None:
        """Load configuration from YAML file."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Threshold config not found: {self.config_path}")
        
        with open(self.config_path, 'r') as f:
            self._config = yaml.safe_load(f)
    
    def get_spread_threshold(self, asset: str) -> SpreadThresholds:
        """Get spread thresholds for an asset.
        
        2026-07-11: Use dynamic threshold manager for regime-aware spread thresholds.
        Fallback to config file if dynamic threshold manager unavailable.
        """
        # Try dynamic threshold manager first
        try:
            from merid.event_venues.kalshi.dynamic_thresholds import get_dynamic_threshold_manager
            threshold_manager = get_dynamic_threshold_manager()
            max_spread = threshold_manager.get_max_spread_cents()
            return SpreadThresholds(max_spread_cents=max_spread)
        except Exception:
            # Fallback to config file
            spread_config = self._config.get("spread_thresholds", {})
            asset_config = spread_config.get(asset, spread_config.get("default", {}))
            
            return SpreadThresholds(
                max_spread_cents=asset_config.get("max_spread_cents", 30)  # Canonical default
            )
    
    def get_extreme_price_threshold(self, asset: str) -> ExtremePriceThresholds:
        """Get extreme price thresholds for an asset."""
        price_config = self._config.get("extreme_price_thresholds", {})
        asset_config = price_config.get(asset, price_config.get("default", {}))
        
        return ExtremePriceThresholds(
            extreme_yes_price_min=asset_config.get("extreme_yes_price_min", 5),
            extreme_yes_price_max=asset_config.get("extreme_yes_price_max", 95)
        )
    
    def get_liquidity_threshold(self, asset: str) -> LiquidityThresholds:
        """Get liquidity thresholds for an asset."""
        liquidity_config = self._config.get("liquidity_thresholds", {})
        asset_config = liquidity_config.get(asset, liquidity_config.get("default", {}))
        
        return LiquidityThresholds(
            min_depth_contracts=asset_config.get("min_depth_contracts", 20),
            max_one_sidedness_ratio=asset_config.get("max_one_sidedness_ratio", 0.8)
        )
    
    def get_depth_window_cents(self) -> int:
        """Get depth window for depth_10c calculation."""
        depth_config = self._config.get("depth_thresholds", {})
        return depth_config.get("depth_window_cents", 10)
    
    def get_staleness_thresholds(self) -> StalenessThresholds:
        """Get staleness thresholds."""
        staleness_config = self._config.get("staleness_thresholds", {})
        # CRITICAL FIX: Increase default from 15s to 120s to match SLA config base threshold
        # 15s was too strict and causing false positives blocking trading
        return StalenessThresholds(
            max_book_staleness_s=staleness_config.get("max_book_staleness_s", 120),
            max_quote_staleness_s=staleness_config.get("max_quote_staleness_s", 30)
        )
    
    def get_duality_thresholds(self) -> DualityThresholds:
        """Get duality validation thresholds."""
        duality_config = self._config.get("duality_thresholds", {})
        return DualityThresholds(
            duality_tolerance_cents=duality_config.get("duality_tolerance_cents", 15)
        )
    
    def get_expiry_thresholds(self) -> ExpiryThresholds:
        """Get market expiry thresholds."""
        expiry_config = self._config.get("expiry_thresholds", {})
        return ExpiryThresholds(
            min_seconds_to_expiry=expiry_config.get("min_seconds_to_expiry", 150),
            cutoff_seconds_to_expiry=expiry_config.get("cutoff_seconds_to_expiry", 60)
        )
    
    def get_volume_thresholds(self) -> VolumeThresholds:
        """Get volume and open interest thresholds."""
        volume_config = self._config.get("volume_thresholds", {})
        return VolumeThresholds(
            min_volume_24h=volume_config.get("min_volume_24h", 1000),
            min_open_interest=volume_config.get("min_open_interest", 10)
        )
    
    def reload(self) -> None:
        """Reload configuration from file (useful for runtime updates)."""
        self._load_config()


# Global config instance
_threshold_config: Optional[ThresholdConfig] = None


def get_threshold_config() -> ThresholdConfig:
    """Get the global threshold config instance."""
    global _threshold_config
    if _threshold_config is None:
        _threshold_config = ThresholdConfig()
    return _threshold_config


def reload_threshold_config() -> None:
    """Reload threshold configuration from file."""
    global _threshold_config
    if _threshold_config is not None:
        _threshold_config.reload()
