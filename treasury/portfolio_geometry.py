"""
MERID-TREASURY Portfolio Geometry

Phase 3.1 of Master Build Directive

Implements:
- Fractional Kelly criterion
- Hierarchical Risk Parity (HRP)
- Copula-based tail dependency

This module answers: "How do we size positions to survive?"

Position sizing is not about maximizing returns.
Position sizing is about maximizing the probability of survival.
"""

from __future__ import annotations

import time
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
from collections import deque

from utils.logger import get_logger

logger = get_logger("treasury.portfolio_geometry")


class RiskRegime(Enum):
    """Risk regime for position sizing."""
    CONSERVATIVE = "conservative"    # 0.25x Kelly
    MODERATE = "moderate"            # 0.5x Kelly
    AGGRESSIVE = "aggressive"        # 0.75x Kelly
    SURVIVAL = "survival"            # 0.1x Kelly (crisis mode)


@dataclass
class PositionSizeResult:
    """Result of position sizing calculation."""
    asset: str
    raw_kelly: float
    fractional_kelly: float
    hrp_weight: float
    final_weight: float
    
    # Constraints applied
    max_position_cap: float
    correlation_penalty: float
    tail_risk_adjustment: float
    
    # Risk metrics
    expected_return: float
    expected_volatility: float
    var_95: float
    cvar_95: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset": self.asset,
            "raw_kelly": round(self.raw_kelly, 6),
            "fractional_kelly": round(self.fractional_kelly, 6),
            "hrp_weight": round(self.hrp_weight, 6),
            "final_weight": round(self.final_weight, 6),
            "max_position_cap": round(self.max_position_cap, 4),
            "correlation_penalty": round(self.correlation_penalty, 4),
            "tail_risk_adjustment": round(self.tail_risk_adjustment, 4),
            "expected_return": round(self.expected_return, 6),
            "expected_volatility": round(self.expected_volatility, 6),
            "var_95": round(self.var_95, 6),
            "cvar_95": round(self.cvar_95, 6),
        }


@dataclass
class PortfolioState:
    """Current portfolio state."""
    timestamp: float
    total_capital: float
    
    # Positions
    positions: Dict[str, float] = field(default_factory=dict)  # asset -> weight
    
    # Risk metrics
    portfolio_volatility: float = 0.0
    portfolio_var_95: float = 0.0
    portfolio_cvar_95: float = 0.0
    max_drawdown: float = 0.0
    
    # Diversification
    effective_n: float = 0.0  # Effective number of bets
    concentration_ratio: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "total_capital": round(self.total_capital, 2),
            "positions": {k: round(v, 6) for k, v in self.positions.items()},
            "portfolio_volatility": round(self.portfolio_volatility, 6),
            "portfolio_var_95": round(self.portfolio_var_95, 6),
            "portfolio_cvar_95": round(self.portfolio_cvar_95, 6),
            "max_drawdown": round(self.max_drawdown, 6),
            "effective_n": round(self.effective_n, 2),
            "concentration_ratio": round(self.concentration_ratio, 4),
        }


class KellyCriterion:
    """
    Kelly Criterion for optimal position sizing.
    
    Kelly fraction = (p * b - q) / b
    where:
        p = probability of win
        q = probability of loss (1 - p)
        b = win/loss ratio
    
    MERID uses fractional Kelly (typically 0.25-0.5x) for:
    - Parameter uncertainty
    - Non-normal distributions
    - Correlation effects
    - Survival priority
    """
    
    # Kelly fraction by risk regime
    KELLY_FRACTIONS = {
        RiskRegime.CONSERVATIVE: 0.25,
        RiskRegime.MODERATE: 0.50,
        RiskRegime.AGGRESSIVE: 0.75,
        RiskRegime.SURVIVAL: 0.10,
    }
    
    def __init__(self, default_regime: RiskRegime = RiskRegime.MODERATE):
        self.regime = default_regime
        self._history: deque = deque(maxlen=1000)
        
        logger.info("Kelly criterion initialized (regime=%s)", default_regime.value)
    
    def calculate_kelly(
        self,
        win_probability: float,
        win_loss_ratio: float,
        confidence: float = 1.0,
    ) -> float:
        """
        Calculate raw Kelly fraction.
        
        Returns optimal fraction of capital to bet.
        """
        p = max(0.0, min(1.0, win_probability))
        q = 1 - p
        b = max(0.01, win_loss_ratio)
        
        # Kelly formula
        kelly = (p * b - q) / b
        
        # Adjust for confidence
        kelly *= confidence
        
        # Never bet more than 100%
        kelly = max(0.0, min(1.0, kelly))
        
        return kelly
    
    def calculate_fractional_kelly(
        self,
        win_probability: float,
        win_loss_ratio: float,
        confidence: float = 1.0,
        regime: Optional[RiskRegime] = None,
    ) -> float:
        """
        Calculate fractional Kelly for survival-first sizing.
        """
        raw_kelly = self.calculate_kelly(win_probability, win_loss_ratio, confidence)
        
        regime = regime or self.regime
        fraction = self.KELLY_FRACTIONS[regime]
        
        fractional = raw_kelly * fraction
        
        self._history.append({
            "raw_kelly": raw_kelly,
            "fractional": fractional,
            "regime": regime.value,
            "timestamp": time.time(),
        })
        
        return fractional
    
    def calculate_from_returns(
        self,
        returns: np.ndarray,
        regime: Optional[RiskRegime] = None,
    ) -> float:
        """
        Calculate Kelly from historical returns.
        """
        if len(returns) < 10:
            return 0.0
        
        # Estimate parameters
        wins = returns[returns > 0]
        losses = returns[returns < 0]
        
        if len(wins) == 0 or len(losses) == 0:
            return 0.0
        
        win_prob = len(wins) / len(returns)
        avg_win = np.mean(wins)
        avg_loss = abs(np.mean(losses))
        
        if avg_loss == 0:
            return 0.0
        
        win_loss_ratio = avg_win / avg_loss
        
        # Confidence based on sample size
        confidence = min(1.0, len(returns) / 100)
        
        return self.calculate_fractional_kelly(
            win_prob, win_loss_ratio, confidence, regime
        )
    
    def set_regime(self, regime: RiskRegime) -> None:
        """Set risk regime."""
        self.regime = regime
        logger.info("Kelly regime changed to: %s", regime.value)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get calculator statistics."""
        history = list(self._history)
        
        return {
            "current_regime": self.regime.value,
            "kelly_fraction": self.KELLY_FRACTIONS[self.regime],
            "calculations": len(history),
            "avg_raw_kelly": round(np.mean([h["raw_kelly"] for h in history]), 4) if history else 0,
            "avg_fractional": round(np.mean([h["fractional"] for h in history]), 4) if history else 0,
        }


class HierarchicalRiskParity:
    """
    Hierarchical Risk Parity (HRP) for portfolio construction.
    
    HRP uses hierarchical clustering to build a diversified portfolio
    that accounts for the correlation structure of assets.
    
    Steps:
    1. Compute correlation matrix
    2. Hierarchical clustering
    3. Quasi-diagonalization
    4. Recursive bisection for weights
    """
    
    def __init__(self):
        self._correlation_matrix: Optional[np.ndarray] = None
        self._assets: List[str] = []
        self._weights: Dict[str, float] = {}
        
        logger.info("HRP initialized")
    
    def _compute_distance_matrix(self, correlation: np.ndarray) -> np.ndarray:
        """Convert correlation to distance matrix."""
        # Distance = sqrt(0.5 * (1 - correlation))
        return np.sqrt(0.5 * (1 - correlation))
    
    def _hierarchical_cluster(self, distance: np.ndarray) -> List[Tuple[int, int, float, int]]:
        """
        Perform hierarchical clustering using single linkage.
        
        Returns list of (cluster1, cluster2, distance, size) tuples.
        """
        n = distance.shape[0]
        
        # Initialize clusters
        clusters = {i: [i] for i in range(n)}
        active = set(range(n))
        linkage = []
        next_cluster = n
        
        while len(active) > 1:
            # Find minimum distance
            min_dist = float('inf')
            min_pair = (0, 0)
            
            active_list = list(active)
            for i, c1 in enumerate(active_list):
                for c2 in active_list[i+1:]:
                    # Single linkage: minimum distance between clusters
                    d = float('inf')
                    for a in clusters[c1]:
                        for b in clusters[c2]:
                            if a < n and b < n:
                                d = min(d, distance[a, b])
                    
                    if d < min_dist:
                        min_dist = d
                        min_pair = (c1, c2)
            
            c1, c2 = min_pair
            
            # Merge clusters
            new_cluster = clusters[c1] + clusters[c2]
            clusters[next_cluster] = new_cluster
            
            linkage.append((c1, c2, min_dist, len(new_cluster)))
            
            active.remove(c1)
            active.remove(c2)
            active.add(next_cluster)
            next_cluster += 1
        
        return linkage
    
    def _get_quasi_diagonal_order(
        self,
        linkage: List[Tuple[int, int, float, int]],
        n_assets: int,
    ) -> List[int]:
        """Get quasi-diagonal ordering from linkage."""
        # Build tree structure
        if not linkage:
            return list(range(n_assets))
        
        # Start from root (last merge)
        def get_leaves(node: int) -> List[int]:
            if node < n_assets:
                return [node]
            
            # Find the merge that created this node
            idx = node - n_assets
            if idx >= len(linkage):
                return []
            
            c1, c2, _, _ = linkage[idx]
            return get_leaves(c1) + get_leaves(c2)
        
        root = n_assets + len(linkage) - 1
        return get_leaves(root)
    
    def _recursive_bisection(
        self,
        covariance: np.ndarray,
        order: List[int],
    ) -> np.ndarray:
        """
        Recursive bisection to compute HRP weights.
        """
        n = len(order)
        weights = np.ones(n)
        
        # Recursive bisection
        clusters = [order]
        
        while clusters:
            new_clusters = []
            
            for cluster in clusters:
                if len(cluster) <= 1:
                    continue
                
                # Split cluster
                mid = len(cluster) // 2
                left = cluster[:mid]
                right = cluster[mid:]
                
                # Compute cluster variances
                left_var = self._cluster_variance(covariance, left)
                right_var = self._cluster_variance(covariance, right)
                
                # Allocate inversely proportional to variance
                total_var = left_var + right_var
                if total_var > 0:
                    left_weight = 1 - left_var / total_var
                    right_weight = 1 - right_var / total_var
                else:
                    left_weight = right_weight = 0.5
                
                # Update weights
                for i in left:
                    weights[order.index(i)] *= left_weight
                for i in right:
                    weights[order.index(i)] *= right_weight
                
                if len(left) > 1:
                    new_clusters.append(left)
                if len(right) > 1:
                    new_clusters.append(right)
            
            clusters = new_clusters
        
        # Normalize
        weights = weights / weights.sum()
        
        return weights
    
    def _cluster_variance(
        self,
        covariance: np.ndarray,
        cluster: List[int],
    ) -> float:
        """Compute variance of a cluster using inverse-variance weights."""
        if len(cluster) == 1:
            return covariance[cluster[0], cluster[0]]
        
        # Extract sub-covariance matrix
        sub_cov = covariance[np.ix_(cluster, cluster)]
        
        # Inverse variance weights
        ivp = 1 / np.diag(sub_cov)
        ivp = ivp / ivp.sum()
        
        # Cluster variance
        return float(ivp @ sub_cov @ ivp)
    
    def compute_weights(
        self,
        returns: np.ndarray,
        assets: List[str],
    ) -> Dict[str, float]:
        """
        Compute HRP weights from returns matrix.
        
        returns: (n_periods, n_assets) array
        assets: list of asset names
        """
        if returns.shape[1] != len(assets):
            raise ValueError("Returns columns must match assets")
        
        n_assets = len(assets)
        self._assets = assets
        
        # Compute correlation and covariance
        correlation = np.corrcoef(returns.T)
        covariance = np.cov(returns.T)
        
        # Handle NaN
        correlation = np.nan_to_num(correlation, nan=0.0)
        covariance = np.nan_to_num(covariance, nan=0.0)
        
        self._correlation_matrix = correlation
        
        # Distance matrix
        distance = self._compute_distance_matrix(correlation)
        
        # Hierarchical clustering
        linkage = self._hierarchical_cluster(distance)
        
        # Quasi-diagonal order
        order = self._get_quasi_diagonal_order(linkage, n_assets)
        
        # Recursive bisection
        weights = self._recursive_bisection(covariance, order)
        
        # Map to assets
        self._weights = {
            assets[order[i]]: float(weights[i])
            for i in range(n_assets)
        }
        
        logger.info("HRP weights computed for %d assets", n_assets)
        
        return self._weights
    
    def get_weights(self) -> Dict[str, float]:
        """Get current HRP weights."""
        return self._weights.copy()
    
    def get_correlation_matrix(self) -> Optional[np.ndarray]:
        """Get correlation matrix."""
        return self._correlation_matrix


class CopulaTailDependency:
    """
    Copula-based tail dependency estimation.
    
    Measures how assets behave together in extreme scenarios.
    High tail dependency = assets crash together.
    """
    
    def __init__(self):
        self._tail_dependencies: Dict[Tuple[str, str], float] = {}
        
        logger.info("Copula tail dependency estimator initialized")
    
    def estimate_lower_tail_dependency(
        self,
        returns_x: np.ndarray,
        returns_y: np.ndarray,
        threshold: float = 0.05,
    ) -> float:
        """
        Estimate lower tail dependency coefficient.
        
        Lambda_L = P(Y < F_Y^{-1}(u) | X < F_X^{-1}(u)) as u -> 0
        
        Uses empirical estimation with threshold.
        """
        n = len(returns_x)
        if n < 50:
            return 0.0
        
        # Convert to uniform using empirical CDF
        u_x = np.argsort(np.argsort(returns_x)) / n
        u_y = np.argsort(np.argsort(returns_y)) / n
        
        # Count joint exceedances
        below_threshold = (u_x < threshold) & (u_y < threshold)
        x_below = u_x < threshold
        
        if x_below.sum() == 0:
            return 0.0
        
        lambda_l = below_threshold.sum() / x_below.sum()
        
        return float(lambda_l)
    
    def estimate_upper_tail_dependency(
        self,
        returns_x: np.ndarray,
        returns_y: np.ndarray,
        threshold: float = 0.95,
    ) -> float:
        """
        Estimate upper tail dependency coefficient.
        """
        n = len(returns_x)
        if n < 50:
            return 0.0
        
        # Convert to uniform
        u_x = np.argsort(np.argsort(returns_x)) / n
        u_y = np.argsort(np.argsort(returns_y)) / n
        
        # Count joint exceedances
        above_threshold = (u_x > threshold) & (u_y > threshold)
        x_above = u_x > threshold
        
        if x_above.sum() == 0:
            return 0.0
        
        lambda_u = above_threshold.sum() / x_above.sum()
        
        return float(lambda_u)
    
    def compute_tail_dependency_matrix(
        self,
        returns: np.ndarray,
        assets: List[str],
    ) -> Dict[Tuple[str, str], Dict[str, float]]:
        """
        Compute tail dependency for all asset pairs.
        """
        n_assets = len(assets)
        result = {}
        
        for i in range(n_assets):
            for j in range(i + 1, n_assets):
                lower = self.estimate_lower_tail_dependency(
                    returns[:, i], returns[:, j]
                )
                upper = self.estimate_upper_tail_dependency(
                    returns[:, i], returns[:, j]
                )
                
                pair = (assets[i], assets[j])
                result[pair] = {
                    "lower_tail": lower,
                    "upper_tail": upper,
                    "avg_tail": (lower + upper) / 2,
                }
                
                self._tail_dependencies[pair] = (lower + upper) / 2
        
        return result
    
    def get_tail_risk_adjustment(
        self,
        asset: str,
        portfolio_assets: List[str],
    ) -> float:
        """
        Get tail risk adjustment factor for an asset.
        
        High tail dependency with portfolio = reduce weight.
        """
        if not self._tail_dependencies:
            return 1.0
        
        # Average tail dependency with other assets
        total_dep = 0.0
        count = 0
        
        for other in portfolio_assets:
            if other == asset:
                continue
            
            pair = tuple(sorted([asset, other]))
            if pair in self._tail_dependencies:
                total_dep += self._tail_dependencies[pair]
                count += 1
        
        if count == 0:
            return 1.0
        
        avg_dep = total_dep / count
        
        # Adjustment: reduce weight if high tail dependency
        # 0 dependency -> 1.0 multiplier
        # 1 dependency -> 0.5 multiplier
        adjustment = 1.0 - 0.5 * avg_dep
        
        return max(0.1, adjustment)


class PortfolioGeometryEngine:
    """
    Main portfolio geometry engine.
    
    Combines Kelly, HRP, and copula analysis for
    survival-first position sizing.
    """
    
    # Position limits
    MAX_SINGLE_POSITION = 0.20  # 20% max in any single asset
    MIN_POSITION = 0.01         # 1% minimum meaningful position
    MAX_CONCENTRATION = 0.50    # Top 3 positions max 50%
    
    def __init__(self):
        self.kelly = KellyCriterion()
        self.hrp = HierarchicalRiskParity()
        self.copula = CopulaTailDependency()
        
        # Current state
        self._current_state: Optional[PortfolioState] = None
        self._state_history: List[PortfolioState] = []
        
        # Returns data
        self._returns_buffer: Dict[str, deque] = {}
        
        logger.info("Portfolio geometry engine initialized")
    
    def update_returns(self, asset: str, returns: float) -> None:
        """Update returns buffer for an asset."""
        if asset not in self._returns_buffer:
            self._returns_buffer[asset] = deque(maxlen=500)
        self._returns_buffer[asset].append(returns)
    
    def compute_optimal_weights(
        self,
        assets: List[str],
        expected_returns: Dict[str, float],
        win_probabilities: Dict[str, float],
        regime: Optional[RiskRegime] = None,
    ) -> Dict[str, PositionSizeResult]:
        """
        Compute optimal portfolio weights.
        
        Combines Kelly, HRP, and tail risk adjustments.
        """
        results = {}
        
        # Build returns matrix
        returns_matrix = self._build_returns_matrix(assets)
        
        # Compute HRP weights if we have enough data
        if returns_matrix is not None and returns_matrix.shape[0] >= 50:
            hrp_weights = self.hrp.compute_weights(returns_matrix, assets)
            
            # Compute tail dependencies
            self.copula.compute_tail_dependency_matrix(returns_matrix, assets)
        else:
            # Equal weight fallback
            hrp_weights = {a: 1.0 / len(assets) for a in assets}
        
        # Compute Kelly for each asset
        kelly_weights = {}
        for asset in assets:
            win_prob = win_probabilities.get(asset, 0.5)
            exp_ret = expected_returns.get(asset, 0.0)
            
            # Estimate win/loss ratio from expected return
            if exp_ret > 0:
                win_loss_ratio = 1.0 + exp_ret * 10  # Scale factor
            else:
                win_loss_ratio = 0.5
            
            kelly_weights[asset] = self.kelly.calculate_fractional_kelly(
                win_prob, win_loss_ratio, regime=regime
            )
        
        # Combine weights
        for asset in assets:
            raw_kelly = kelly_weights.get(asset, 0.0)
            hrp_weight = hrp_weights.get(asset, 1.0 / len(assets))
            
            # Tail risk adjustment
            tail_adj = self.copula.get_tail_risk_adjustment(asset, assets)
            
            # Combined weight: geometric mean of Kelly and HRP, adjusted for tail risk
            if raw_kelly > 0 and hrp_weight > 0:
                combined = math.sqrt(raw_kelly * hrp_weight) * tail_adj
            else:
                combined = hrp_weight * tail_adj * 0.5
            
            # Apply position cap
            capped = min(combined, self.MAX_SINGLE_POSITION)
            
            # Calculate risk metrics
            asset_returns = list(self._returns_buffer.get(asset, []))
            if len(asset_returns) >= 20:
                vol = np.std(asset_returns) * math.sqrt(252)
                var_95 = np.percentile(asset_returns, 5)
                cvar_95 = np.mean([r for r in asset_returns if r <= var_95])
            else:
                vol = 0.2  # Default 20% vol
                var_95 = -0.02
                cvar_95 = -0.03
            
            results[asset] = PositionSizeResult(
                asset=asset,
                raw_kelly=raw_kelly,
                fractional_kelly=raw_kelly * self.kelly.KELLY_FRACTIONS[regime or self.kelly.regime],
                hrp_weight=hrp_weight,
                final_weight=capped,
                max_position_cap=self.MAX_SINGLE_POSITION,
                correlation_penalty=1.0 - hrp_weight / (1.0 / len(assets)),
                tail_risk_adjustment=tail_adj,
                expected_return=expected_returns.get(asset, 0.0),
                expected_volatility=vol,
                var_95=var_95,
                cvar_95=cvar_95,
            )
        
        # Normalize weights
        total_weight = sum(r.final_weight for r in results.values())
        if total_weight > 0:
            for asset in results:
                results[asset].final_weight /= total_weight
        
        # Apply concentration limit
        results = self._apply_concentration_limit(results)
        
        return results
    
    def _build_returns_matrix(self, assets: List[str]) -> Optional[np.ndarray]:
        """Build returns matrix from buffer."""
        if not all(asset in self._returns_buffer for asset in assets):
            return None
        
        min_len = min(len(self._returns_buffer[a]) for a in assets)
        if min_len < 50:
            return None
        
        matrix = np.column_stack([
            list(self._returns_buffer[a])[-min_len:]
            for a in assets
        ])
        
        return matrix
    
    def _apply_concentration_limit(
        self,
        results: Dict[str, PositionSizeResult],
    ) -> Dict[str, PositionSizeResult]:
        """Apply concentration limit to top positions."""
        # Sort by weight
        sorted_assets = sorted(
            results.keys(),
            key=lambda a: results[a].final_weight,
            reverse=True
        )
        
        # Check top 3 concentration
        top_3_weight = sum(results[a].final_weight for a in sorted_assets[:3])
        
        if top_3_weight > self.MAX_CONCENTRATION:
            # Scale down top 3
            scale = self.MAX_CONCENTRATION / top_3_weight
            for asset in sorted_assets[:3]:
                results[asset].final_weight *= scale
            
            # Redistribute to others
            redistributed = top_3_weight - self.MAX_CONCENTRATION
            other_assets = sorted_assets[3:]
            if other_assets:
                per_asset = redistributed / len(other_assets)
                for asset in other_assets:
                    results[asset].final_weight += per_asset
        
        return results
    
    def compute_portfolio_risk(
        self,
        weights: Dict[str, float],
    ) -> Dict[str, float]:
        """Compute portfolio-level risk metrics."""
        assets = list(weights.keys())
        
        # Build returns matrix
        returns_matrix = self._build_returns_matrix(assets)
        
        if returns_matrix is None:
            return {
                "volatility": 0.0,
                "var_95": 0.0,
                "cvar_95": 0.0,
                "effective_n": len(assets),
            }
        
        # Weight vector
        w = np.array([weights[a] for a in assets])
        
        # Portfolio returns
        portfolio_returns = returns_matrix @ w
        
        # Metrics
        vol = np.std(portfolio_returns) * math.sqrt(252)
        var_95 = np.percentile(portfolio_returns, 5)
        cvar_95 = np.mean(portfolio_returns[portfolio_returns <= var_95])
        
        # Effective N (diversification measure)
        effective_n = 1.0 / np.sum(w ** 2)
        
        return {
            "volatility": float(vol),
            "var_95": float(var_95),
            "cvar_95": float(cvar_95),
            "effective_n": float(effective_n),
        }
    
    def update_state(
        self,
        total_capital: float,
        positions: Dict[str, float],
    ) -> PortfolioState:
        """Update portfolio state."""
        risk_metrics = self.compute_portfolio_risk(positions)
        
        # Concentration ratio
        sorted_weights = sorted(positions.values(), reverse=True)
        concentration = sum(sorted_weights[:3]) if len(sorted_weights) >= 3 else sum(sorted_weights)
        
        state = PortfolioState(
            timestamp=time.time(),
            total_capital=total_capital,
            positions=positions,
            portfolio_volatility=risk_metrics["volatility"],
            portfolio_var_95=risk_metrics["var_95"],
            portfolio_cvar_95=risk_metrics["cvar_95"],
            effective_n=risk_metrics["effective_n"],
            concentration_ratio=concentration,
        )
        
        self._current_state = state
        self._state_history.append(state)
        
        return state
    
    def should_rebalance(
        self,
        current_weights: Dict[str, float],
        target_weights: Dict[str, float],
        threshold: float = 0.05,
    ) -> Tuple[bool, Dict[str, float]]:
        """
        Check if rebalancing is needed.
        
        Returns (should_rebalance, weight_differences).
        """
        diffs = {}
        max_diff = 0.0
        
        all_assets = set(current_weights.keys()) | set(target_weights.keys())
        
        for asset in all_assets:
            current = current_weights.get(asset, 0.0)
            target = target_weights.get(asset, 0.0)
            diff = target - current
            diffs[asset] = diff
            max_diff = max(max_diff, abs(diff))
        
        should_rebalance = max_diff > threshold
        
        return should_rebalance, diffs
    
    def get_status(self) -> Dict[str, Any]:
        """Get engine status."""
        state = self._current_state
        
        return {
            "current_state": state.to_dict() if state else None,
            "kelly": self.kelly.get_stats(),
            "hrp_weights": self.hrp.get_weights(),
            "assets_tracked": len(self._returns_buffer),
            "history_length": len(self._state_history),
        }


# Singleton instance
_portfolio_engine: Optional[PortfolioGeometryEngine] = None


def get_portfolio_geometry() -> PortfolioGeometryEngine:
    """Get the singleton portfolio geometry engine."""
    global _portfolio_engine
    if _portfolio_engine is None:
        _portfolio_engine = PortfolioGeometryEngine()
    return _portfolio_engine
