"""Dynamic Allocation Calculator — Risk-parity based position limits.

Replaces static per-asset caps with dynamic calculations based on:
- Total portfolio value (bankroll)
- Asset volatility (risk parity weighting)
- Correlation between assets
- Kelly-optimal allocation

Usage::

    from merid.prediction.dynamic_allocation_calculator import get_dynamic_allocation_calculator
    
    calculator = get_dynamic_allocation_calculator()
    
    # Get dynamic cap for BTC based on current portfolio and market conditions
    btc_cap = calculator.get_asset_cap("BTC", total_portfolio_value_usd=50000)
    # Returns dynamically computed cap based on volatility, correlation, Kelly
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import math

from utils.logger import get_logger

logger = get_logger("merid.prediction.dynamic_allocation_calculator")


@dataclass
class AssetRiskMetrics:
    """Risk metrics for a single asset."""
    asset: str
    volatility: float  # Annualized volatility
    avg_return: float  # Expected return (from edge estimates)
    correlation_matrix: Dict[str, float]  # Correlations with other assets
    liquidity_score: float  # 0-1 scale, higher = more liquid
    last_update: float


@dataclass
class DynamicAllocationConfig:
    """Configuration for dynamic allocation calculation."""
    
    # Base allocation strategy
    strategy: str = "risk_parity"  # risk_parity, kelly, equal_weight, volatility_target
    
    # Maximum concentration in any single asset
    max_single_asset_pct: Decimal = Decimal("0.40")  # 40% max
    
    # Minimum allocation for any active asset
    min_asset_pct: Decimal = Decimal("0.05")  # 5% min
    
    # Risk target for volatility-target strategy
    target_portfolio_vol: float = 0.30  # 30% annualized
    
    # Kelly fraction to use (quarter-Kelly default)
    kelly_fraction: Decimal = Decimal("0.25")
    
    # Volatility lookback period in days
    vol_lookback_days: int = 30
    
    # Correlation lookback period in days  
    corr_lookback_days: int = 90
    
    # Rebalance threshold (trigger rebalance when weights drift by this much)
    rebalance_threshold_pct: Decimal = Decimal("0.10")  # 10%
    
    # Asset universe (if empty, use all 5 crypto assets)
    asset_universe: List[str] = field(default_factory=lambda: ["BTC", "ETH", "SOL", "XRP", "DOGE"])
    
    # Static override caps (for emergency use)
    static_caps_usd: Optional[Dict[str, float]] = None


class DynamicAllocationCalculator:
    """Computes dynamic asset allocations based on risk parity and Kelly criteria.
    
    This replaces the hardcoded per-asset caps in settings.py with dynamically
    computed allocations that respond to market conditions and portfolio size.
    """
    
    def __init__(self, config: Optional[DynamicAllocationConfig] = None):
        self.config = config or DynamicAllocationConfig()
        self._risk_metrics: Dict[str, AssetRiskMetrics] = {}
        self._last_recompute = 0.0
        self._cached_allocations: Dict[str, Decimal] = {}
        # LEGACY REMOVAL: Threading lock removed - causing deadlock during startup
        # Single-threaded FastAPI startup doesn't need lock protection
        self._cache_ttl_seconds = 600  # 10 minute TTL
        
    def _fetch_risk_metrics(self, asset: str) -> AssetRiskMetrics:
        """Fetch risk metrics for an asset.
        
        In production, fetches from risk data store.
        Falls back to sensible defaults.
        """
        # Default correlations (BTC-centric)
        default_correlations = {
            "BTC": {"ETH": 0.75, "SOL": 0.65, "XRP": 0.55, "DOGE": 0.60},
            "ETH": {"BTC": 0.75, "SOL": 0.70, "XRP": 0.50, "DOGE": 0.55},
            "SOL": {"BTC": 0.65, "ETH": 0.70, "XRP": 0.45, "DOGE": 0.50},
            "XRP": {"BTC": 0.55, "ETH": 0.50, "SOL": 0.45, "DOGE": 0.40},
            "DOGE": {"BTC": 0.60, "ETH": 0.55, "SOL": 0.50, "XRP": 0.40},
        }
        
        # Default volatilities and expected returns
        defaults = {
            "BTC": (0.45, 0.08, 0.95),   # vol=45%, exp_return=8%, liquidity=0.95
            "ETH": (0.55, 0.10, 0.90),
            "SOL": (0.75, 0.12, 0.80),
            "XRP": (0.70, 0.09, 0.75),
            "DOGE": (0.90, 0.15, 0.70),
        }
        
        vol, exp_ret, liq = defaults.get(asset, (0.60, 0.08, 0.80))
        
        try:
            # Try to fetch from actual data sources
            from merid.prediction.crypto_vol_indicators import get_crypto_vol_indicator_stack
            stack = get_crypto_vol_indicator_stack()
            vol_data = stack.get_latest_volatility(asset)
            if vol_data:
                vol = vol_data.get("rv_30d", vol)
        except Exception:
            pass
        
        return AssetRiskMetrics(
            asset=asset,
            volatility=vol,
            avg_return=exp_ret,
            correlation_matrix=default_correlations.get(asset, {}),
            liquidity_score=liq,
            last_update=time.time(),
        )
    
    def _compute_risk_parity_weights(
        self,
        assets: List[str],
        total_value: float,
    ) -> Dict[str, Decimal]:
        """Compute risk-parity weights based on volatility and correlation.
        
        Risk parity: equal risk contribution from each asset.
        Weight is inversely proportional to volatility, adjusted for correlation.
        """
        # Fetch metrics
        metrics = {a: self._fetch_risk_metrics(a) for a in assets}
        
        # Compute risk budgets (inverse volatility)
        risk_budgets = {}
        for asset in assets:
            m = metrics[asset]
            # Higher liquidity = higher capacity = higher budget
            liq_adj = m.liquidity_score
            risk_budgets[asset] = (1.0 / m.volatility) * liq_adj
        
        # Normalize to sum to 1
        total_budget = sum(risk_budgets.values())
        
        weights = {}
        for asset in assets:
            raw_weight = risk_budgets[asset] / total_budget
            
            # Apply correlation penalty (diversification benefit)
            corr_penalty = 0.0
            for other_asset in assets:
                if other_asset != asset:
                    corr = metrics[asset].correlation_matrix.get(other_asset, 0.5)
                    corr_penalty += corr * float(weights.get(other_asset, Decimal("0")))
            
            # Adjust weight for correlation
            adj_weight = raw_weight * (1 - corr_penalty * 0.5)
            
            # Clamp to min/max
            adj_weight = max(
                float(self.config.min_asset_pct),
                min(float(self.config.max_single_asset_pct), adj_weight)
            )
            
            weights[asset] = Decimal(str(adj_weight))
        
        # Renormalize
        total_weight = sum(weights.values())
        for asset in weights:
            weights[asset] = (weights[asset] / total_weight).quantize(Decimal("0.0001"))
        
        return weights
    
    def _compute_kelly_weights(
        self,
        assets: List[str],
        total_value: float,
    ) -> Dict[str, Decimal]:
        """Compute Kelly-optimal weights based on expected returns and variance."""
        metrics = {a: self._fetch_risk_metrics(a) for a in assets}
        
        kelly_fractions = {}
        for asset in assets:
            m = metrics[asset]
            # Simplified Kelly: f* = (mu - r) / sigma^2
            # Assuming risk-free rate = 0 for simplicity
            mu = m.avg_return
            sigma_sq = m.volatility ** 2
            
            if sigma_sq > 0:
                kelly_f = mu / sigma_sq
                # Apply fractional Kelly and liquidity adjustment
                adj_kelly = kelly_f * float(self.config.kelly_fraction) * m.liquidity_score
                kelly_fractions[asset] = adj_kelly
            else:
                kelly_fractions[asset] = 0.0
        
        # Normalize
        total_kelly = sum(kelly_fractions.values())
        if total_kelly == 0:
            # Fallback to equal weight
            return {a: Decimal("0.20") for a in assets}
        
        weights = {}
        for asset in assets:
            w = kelly_fractions[asset] / total_kelly
            # Clamp
            w = max(float(self.config.min_asset_pct), min(float(self.config.max_single_asset_pct), w))
            weights[asset] = w
        
        # Renormalize
        total_w = sum(weights.values())
        for asset in weights:
            weights[asset] = Decimal(str(weights[asset] / total_w)).quantize(Decimal("0.0001"))
        
        return weights
    
    def compute_allocations(
        self,
        total_portfolio_value_usd: float,
        strategy: Optional[str] = None,
    ) -> Dict[str, Decimal]:
        """Compute dynamic allocations for all assets.
        
        Args:
            total_portfolio_value_usd: Total portfolio value
            strategy: Override strategy (risk_parity, kelly, equal_weight)
            
        Returns:
            Dict mapping asset to allocation percentage (0-1)
        """
        assets = self.config.asset_universe
        strat = strategy or self.config.strategy
        
        if strat == "risk_parity":
            weights = self._compute_risk_parity_weights(assets, total_portfolio_value_usd)
        elif strat == "kelly":
            weights = self._compute_kelly_weights(assets, total_portfolio_value_usd)
        elif strat == "equal_weight":
            equal = Decimal("1.0") / len(assets)
            weights = {a: equal for a in assets}
        else:
            weights = self._compute_risk_parity_weights(assets, total_portfolio_value_usd)
        
        if self._cache_lock is not None:
            with self._cache_lock:
                self._cached_allocations = weights
                self._last_recompute = time.time()
        else:
            # Lock disabled - direct access (startup workaround)
            self._cached_allocations = weights
            self._last_recompute = time.time()
        
        return weights
    
    def get_asset_cap(
        self,
        asset: str,
        total_portfolio_value_usd: float,
        strategy: Optional[str] = None,
    ) -> float:
        """Get dynamic notional cap for an asset.
        
        Args:
            asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
            total_portfolio_value_usd: Total portfolio value
            strategy: Allocation strategy override
            
        Returns:
            Maximum notional USD for this asset
        """
        # Check for static override
        if self.config.static_caps_usd and asset in self.config.static_caps_usd:
            return self.config.static_caps_usd[asset]
        
        # Check cache freshness
        if self._cache_lock is not None:
            with self._cache_lock:
                cache_age = time.time() - self._last_recompute
                if cache_age < self._cache_ttl_seconds and self._cached_allocations:
                    cached = self._cached_allocations.get(asset)
                    if cached is not None:
                        return cached
        else:
            # Lock disabled - direct access (startup workaround)
            cache_age = time.time() - self._last_recompute
            if cache_age < self._cache_ttl_seconds and self._cached_allocations:
                cached = self._cached_allocations.get(asset)
                if cached is not None:
                    return cached
        
        # Compute fresh allocations
        allocations = self.compute_allocations(total_portfolio_value_usd, strategy)
        
        # Add correlation stack cap (single underlying across timeframes)
        # This ensures we don't over-allocate to one asset across multiple timeframes
        corr_stack_factor = 1.2  # Allow 20% extra for timeframe diversification
        
        asset_alloc = allocations.get(asset, Decimal("0.20"))
        cap_usd = float(asset_alloc) * total_portfolio_value_usd * corr_stack_factor
        
        logger.debug(
            f"Dynamic cap for {asset}: ${cap_usd:.2f} "
            f"(allocation={asset_alloc:.2%}, portfolio=${total_portfolio_value_usd:.2f})"
        )
        
        return cap_usd
    
    def get_all_caps(
        self,
        total_portfolio_value_usd: float,
        strategy: Optional[str] = None,
    ) -> Dict[str, float]:
        """Get all asset caps for a portfolio value."""
        allocations = self.compute_allocations(total_portfolio_value_usd, strategy)
        
        caps = {}
        corr_stack_factor = 1.2
        for asset, alloc in allocations.items():
            caps[asset] = float(alloc) * total_portfolio_value_usd * corr_stack_factor
        
        return caps
    
    def get_timeframe_distribution(
        self,
        asset: str,
        total_asset_allocation: float,
    ) -> Dict[str, float]:
        """Distribute allocation across timeframes for an asset.
        
        Based on volume and opportunity distribution:
        - Higher frequency = more opportunities but lower expected edge per trade
        """
        # Default distribution: more weight to shorter timeframes (more opportunities)
        # But adjust for expected edge decay at higher frequency
        base_dist = {
            "15m": 0.35,    # 35% to highest frequency
            "1h": 0.25,
            "daily": 0.20,
            "weekly": 0.12,
            "monthly": 0.05,
            "annual": 0.03,
        }
        
        # Adjust based on asset volatility (higher vol = more 15m opportunities)
        try:
            metrics = self._fetch_risk_metrics(asset)
            if metrics.volatility > 0.70:  # High vol assets (SOL, DOGE)
                base_dist["15m"] += 0.10
                base_dist["1h"] += 0.05
                base_dist["daily"] -= 0.10
                base_dist["weekly"] -= 0.05
            elif metrics.volatility < 0.50:  # Low vol (BTC)
                base_dist["15m"] -= 0.10
                base_dist["daily"] += 0.05
                base_dist["weekly"] += 0.05
        except Exception:
            pass
        
        # Renormalize
        total = sum(base_dist.values())
        return {tf: (pct / total) * total_asset_allocation for tf, pct in base_dist.items()}


# Singleton instance
_calculator_instance: Optional[DynamicAllocationCalculator] = None
# LEGACY REMOVAL: Threading lock removed - causing deadlock during startup
# Single-threaded FastAPI startup doesn't need lock protection


def get_dynamic_allocation_calculator() -> DynamicAllocationCalculator:
    """Get the singleton DynamicAllocationCalculator instance."""
    global _calculator_instance
    if _calculator_instance is None:
        _calculator_instance = DynamicAllocationCalculator()
    return _calculator_instance


def compute_dynamic_allocation(asset: str, total_portfolio_value: float) -> float:
    """Convenience function to get cap for an asset."""
    return get_dynamic_allocation_calculator().get_asset_cap(asset, total_portfolio_value)
