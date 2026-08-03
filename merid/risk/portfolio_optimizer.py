"""
Portfolio Optimizer for MERID Advanced Risk Management

CRITICAL: The 15m Kalshi crypto system uses a fixed $1 global exposure cap
(MERID_FIXED_EXPOSURE_CAP_USD). This optimizer is DEPRECATED for the production
15m crypto stack and should NOT be used. The production system uses slot-based
allocation via GlobalSlotAllocator with a hard $1 cap across all assets.

Legacy Features (NOT USED IN PRODUCTION):
- Mean-variance optimization
- Risk parity allocation
- Maximum diversification
- Dynamic rebalancing
- US-compliant risk management
"""

import asyncio
import time
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque

# Portfolio optimization libraries (with fallbacks)
try:
    import cvxpy as cp
    CVXPY_AVAILABLE = True
except ImportError:
    CVXPY_AVAILABLE = False

try:
    from scipy.optimize import minimize
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

from utils.logger import get_logger

logger = get_logger("risk.portfolio_optimizer")

@dataclass
class Asset:
    """Asset definition for portfolio optimization."""
    symbol: str
    expected_return: float
    volatility: float
    weight: float = 0.0
    min_weight: float = 0.0
    max_weight: float = 1.0
    asset_class: str = "equity"
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class PortfolioMetrics:
    """Portfolio performance metrics."""
    expected_return: float
    volatility: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    var_95: float
    var_99: float
    expected_shortfall_95: float
    diversification_ratio: float
    concentration_risk: float
    turnover: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class OptimizationResult:
    """Portfolio optimization result."""
    optimization_id: str
    optimization_method: str
    assets: List[Asset]
    weights: Dict[str, float]
    portfolio_metrics: PortfolioMetrics
    optimization_time: float
    convergence: bool
    objective_value: float
    constraints: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)

class PortfolioOptimizer:
    """
    Advanced portfolio optimization system for MERID.
    
    DEPRECATED: This class is NOT used in the 15m Kalshi crypto production stack.
    The production system uses fixed $1 slot allocation (GlobalSlotAllocator)
    instead of percentage-based portfolio optimization.
    
    Provides multiple optimization methods with risk management
    and US-compliant configuration.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Assets universe
        self.assets: Dict[str, Asset] = {}
        
        # Correlation matrix
        self.correlation_matrix: Optional[np.ndarray] = None
        self.covariance_matrix: Optional[np.ndarray] = None
        
        # Optimization history
        self.optimization_history: deque = deque(maxlen=100)
        
        # Optimization parameters
        self.risk_free_rate = config.get("risk_free_rate", 0.02)
        self.optimization_methods = config.get("optimization_methods", [
            "mean_variance", "risk_parity", "max_diversification", "min_variance"
        ])
        
        # Constraints
        # DEPRECATED: These percentage-based constraints are not used in production
        # The 15m crypto stack uses fixed $1 slot allocation instead
        self.default_constraints = {
            "weight_sum": 1.0,
            "min_weight": 0.0,
            "max_weight": 1.0,
            "max_turnover": 0.5
        }
        
        # US compliance settings
        self.us_compliance = config.get("us_compliance", {
            "position_limits": True,
            "concentration_limits": True,
            "risk_limits": True,
            "audit_optimization": True
        })
        
        logger.info("PortfolioOptimizer initialized")
    
    def add_asset(self, asset: Asset) -> bool:
        """Add asset to optimization universe."""
        try:
            self.assets[asset.symbol] = asset
            logger.info(f"Added asset {asset.symbol} to optimization universe")
            return True
            
        except Exception as e:
            logger.error(f"Failed to add asset {asset.symbol}: {e}")
            return False
    
    def update_correlation_matrix(self, correlation_matrix: np.ndarray) -> bool:
        """Update correlation matrix for optimization."""
        try:
            asset_symbols = list(self.assets.keys())
            
            if correlation_matrix.shape != (len(asset_symbols), len(asset_symbols)):
                logger.error("Correlation matrix dimensions don't match asset count")
                return False
            
            self.correlation_matrix = correlation_matrix
            
            # Calculate covariance matrix
            volatilities = np.array([self.assets[symbol].volatility for symbol in asset_symbols])
            vol_matrix = np.outer(volatilities, volatilities)
            self.covariance_matrix = correlation_matrix * vol_matrix
            
            logger.info(f"Updated correlation matrix for {len(asset_symbols)} assets")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update correlation matrix: {e}")
            return False
    
    async def optimize_portfolio(self, method: str = "mean_variance", 
                               constraints: Optional[Dict[str, Any]] = None) -> Optional[OptimizationResult]:
        """Optimize portfolio using specified method."""
        try:
            start_time = time.time()
            
            if not self.assets or len(self.assets) < 2:
                logger.error("Insufficient assets for optimization")
                return None
            
            if self.covariance_matrix is None:
                logger.error("Covariance matrix not available")
                return None
            
            # Merge constraints
            opt_constraints = {**self.default_constraints}
            if constraints:
                opt_constraints.update(constraints)
            
            # Select optimization method
            if method == "mean_variance":
                result = await self._optimize_mean_variance(opt_constraints)
            elif method == "risk_parity":
                result = await self._optimize_risk_parity(opt_constraints)
            elif method == "max_diversification":
                result = await self._optimize_max_diversification(opt_constraints)
            elif method == "min_variance":
                result = await self._optimize_min_variance(opt_constraints)
            else:
                logger.error(f"Unknown optimization method: {method}")
                return None
            
            if result:
                result.optimization_time = time.time() - start_time
                
                # Store result
                self.optimization_history.append(result)
                
                # Record for compliance
                if self.us_compliance.get("audit_optimization", True):
                    await self._record_compliance(result)
                
                logger.info(f"Portfolio optimization completed: {method}")
                return result
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to optimize portfolio: {e}")
            return None
    
    async def _optimize_mean_variance(self, constraints: Dict[str, Any]) -> Optional[OptimizationResult]:
        """Mean-variance optimization (Markowitz)."""
        try:
            asset_symbols = list(self.assets.keys())
            n_assets = len(asset_symbols)
            
            # Expected returns and covariance matrix
            expected_returns = np.array([self.assets[symbol].expected_return for symbol in asset_symbols])
            cov_matrix = self.covariance_matrix
            
            if not SCIPY_AVAILABLE:
                logger.warning("Scipy not available, using simplified optimization")
                return await self._simplified_mean_variance(expected_returns, cov_matrix, constraints)
            
            # Optimization variables
            def objective(weights):
                portfolio_return = np.sum(expected_returns * weights)
                portfolio_variance = np.dot(weights, np.dot(cov_matrix, weights))
                return -(portfolio_return - self.risk_free_rate) / np.sqrt(portfolio_variance)  # Negative Sharpe
            
            # Constraints
            constraint_list = [
                {'type': 'eq', 'fun': lambda w: np.sum(w) - constraints['weight_sum']}
            ]
            
            # Bounds
            bounds = [(constraints.get('min_weight', 0), constraints.get('max_weight', 1)) for _ in range(n_assets)]
            
            # Initial guess (equal weight)
            x0 = np.array([1.0 / n_assets] * n_assets)
            
            # Optimize
            result = minimize(
                objective,
                x0,
                method='SLSQP',
                bounds=bounds,
                constraints=constraint_list,
                options={'ftol': 1e-9, 'disp': False}
            )
            
            if result.success:
                weights = dict(zip(asset_symbols, result.x))
                portfolio_metrics = self._calculate_portfolio_metrics(weights)
                
                return OptimizationResult(
                    optimization_id=f"mv_{int(time.time())}",
                    optimization_method="mean_variance",
                    assets=list(self.assets.values()),
                    weights=weights,
                    portfolio_metrics=portfolio_metrics,
                    optimization_time=0.0,
                    convergence=result.success,
                    objective_value=-result.fun,
                    constraints=list(constraints.keys()),
                    metadata={"scipy_success": result.success}
                )
            else:
                logger.warning("Mean-variance optimization failed to converge")
                return None
                
        except Exception as e:
            logger.error(f"Mean-variance optimization failed: {e}")
            return None
    
    async def _optimize_risk_parity(self, constraints: Dict[str, Any]) -> Optional[OptimizationResult]:
        """Risk parity optimization."""
        try:
            asset_symbols = list(self.assets.keys())
            n_assets = len(asset_symbols)
            
            cov_matrix = self.covariance_matrix
            
            if not SCIPY_AVAILABLE:
                logger.warning("Scipy not available, using simplified risk parity")
                return await self._simplified_risk_parity(cov_matrix, constraints)
            
            # Risk parity objective: minimize variance of risk contributions
            def objective(weights):
                portfolio_variance = np.dot(weights, np.dot(cov_matrix, weights))
                marginal_contrib = np.dot(cov_matrix, weights)
                risk_contrib = weights * marginal_contrib
                risk_contrib_pct = risk_contrib / portfolio_variance
                
                # Minimize squared deviations from equal risk contribution
                equal_contrib = 1.0 / n_assets
                return np.sum((risk_contrib_pct - equal_contrib) ** 2)
            
            # Constraints
            constraint_list = [
                {'type': 'eq', 'fun': lambda w: np.sum(w) - constraints['weight_sum']}
            ]
            
            # Bounds
            bounds = [(constraints.get('min_weight', 0), constraints.get('max_weight', 1)) for _ in range(n_assets)]
            
            # Initial guess (equal weight)
            x0 = np.array([1.0 / n_assets] * n_assets)
            
            # Optimize
            result = minimize(
                objective,
                x0,
                method='SLSQP',
                bounds=bounds,
                constraints=constraint_list,
                options={'ftol': 1e-9, 'disp': False}
            )
            
            if result.success:
                weights = dict(zip(asset_symbols, result.x))
                portfolio_metrics = self._calculate_portfolio_metrics(weights)
                
                return OptimizationResult(
                    optimization_id=f"rp_{int(time.time())}",
                    optimization_method="risk_parity",
                    assets=list(self.assets.values()),
                    weights=weights,
                    portfolio_metrics=portfolio_metrics,
                    optimization_time=0.0,
                    convergence=result.success,
                    objective_value=result.fun,
                    constraints=list(constraints.keys()),
                    metadata={"scipy_success": result.success}
                )
            else:
                logger.warning("Risk parity optimization failed to converge")
                return None
                
        except Exception as e:
            logger.error(f"Risk parity optimization failed: {e}")
            return None
    
    async def _optimize_max_diversification(self, constraints: Dict[str, Any]) -> Optional[OptimizationResult]:
        """Maximum diversification optimization."""
        try:
            asset_symbols = list(self.assets.keys())
            n_assets = len(asset_symbols)
            
            expected_returns = np.array([self.assets[symbol].expected_return for symbol in asset_symbols])
            volatilities = np.array([self.assets[symbol].volatility for symbol in asset_symbols])
            cov_matrix = self.covariance_matrix
            
            if not SCIPY_AVAILABLE:
                logger.warning("Scipy not available, using simplified max diversification")
                return await self._simplified_max_diversification(expected_returns, volatilities, cov_matrix, constraints)
            
            # Max diversification objective: maximize diversification ratio
            def objective(weights):
                portfolio_volatility = np.sqrt(np.dot(weights, np.dot(cov_matrix, weights)))
                weighted_avg_volatility = np.sum(weights * volatilities)
                
                # Negative because we want to maximize
                return -weighted_avg_volatility / portfolio_volatility
            
            # Constraints
            constraint_list = [
                {'type': 'eq', 'fun': lambda w: np.sum(w) - constraints['weight_sum']}
            ]
            
            # Bounds
            bounds = [(constraints.get('min_weight', 0), constraints.get('max_weight', 1)) for _ in range(n_assets)]
            
            # Initial guess (equal weight)
            x0 = np.array([1.0 / n_assets] * n_assets)
            
            # Optimize
            result = minimize(
                objective,
                x0,
                method='SLSQP',
                bounds=bounds,
                constraints=constraint_list,
                options={'ftol': 1e-9, 'disp': False}
            )
            
            if result.success:
                weights = dict(zip(asset_symbols, result.x))
                portfolio_metrics = self._calculate_portfolio_metrics(weights)
                
                return OptimizationResult(
                    optimization_id=f"md_{int(time.time())}",
                    optimization_method="max_diversification",
                    assets=list(self.assets.values()),
                    weights=weights,
                    portfolio_metrics=portfolio_metrics,
                    optimization_time=0.0,
                    convergence=result.success,
                    objective_value=-result.fun,
                    constraints=list(constraints.keys()),
                    metadata={"scipy_success": result.success}
                )
            else:
                logger.warning("Max diversification optimization failed to converge")
                return None
                
        except Exception as e:
            logger.error(f"Max diversification optimization failed: {e}")
            return None
    
    async def _optimize_min_variance(self, constraints: Dict[str, Any]) -> Optional[OptimizationResult]:
        """Minimum variance optimization."""
        try:
            asset_symbols = list(self.assets.keys())
            n_assets = len(asset_symbols)
            
            cov_matrix = self.covariance_matrix
            
            if not SCIPY_AVAILABLE:
                logger.warning("Scipy not available, using simplified min variance")
                return await self._simplified_min_variance(cov_matrix, constraints)
            
            # Min variance objective: minimize portfolio variance
            def objective(weights):
                return np.dot(weights, np.dot(cov_matrix, weights))
            
            # Constraints
            constraint_list = [
                {'type': 'eq', 'fun': lambda w: np.sum(w) - constraints['weight_sum']}
            ]
            
            # Bounds
            bounds = [(constraints.get('min_weight', 0), constraints.get('max_weight', 1)) for _ in range(n_assets)]
            
            # Initial guess (equal weight)
            x0 = np.array([1.0 / n_assets] * n_assets)
            
            # Optimize
            result = minimize(
                objective,
                x0,
                method='SLSQP',
                bounds=bounds,
                constraints=constraint_list,
                options={'ftol': 1e-9, 'disp': False}
            )
            
            if result.success:
                weights = dict(zip(asset_symbols, result.x))
                portfolio_metrics = self._calculate_portfolio_metrics(weights)
                
                return OptimizationResult(
                    optimization_id=f"mv_{int(time.time())}",
                    optimization_method="min_variance",
                    assets=list(self.assets.values()),
                    weights=weights,
                    portfolio_metrics=portfolio_metrics,
                    optimization_time=0.0,
                    convergence=result.success,
                    objective_value=result.fun,
                    constraints=list(constraints.keys()),
                    metadata={"scipy_success": result.success}
                )
            else:
                logger.warning("Min variance optimization failed to converge")
                return None
                
        except Exception as e:
            logger.error(f"Min variance optimization failed: {e}")
            return None
    
    async def _simplified_mean_variance(self, expected_returns: np.ndarray, 
                                      cov_matrix: np.ndarray, 
                                      constraints: Dict[str, Any]) -> OptimizationResult:
        """Simplified mean-variance optimization (fallback)."""
        try:
            n_assets = len(expected_returns)
            asset_symbols = list(self.assets.keys())
            
            # Equal weight portfolio (simplified)
            weights = np.array([1.0 / n_assets] * n_assets)
            
            # Apply basic constraints
            weights = np.clip(weights, constraints.get('min_weight', 0), constraints.get('max_weight', 1))
            weights = weights / np.sum(weights)  # Re-normalize
            
            weight_dict = dict(zip(asset_symbols, weights))
            portfolio_metrics = self._calculate_portfolio_metrics(weight_dict)
            
            return OptimizationResult(
                optimization_id=f"mv_simple_{int(time.time())}",
                optimization_method="mean_variance_simplified",
                assets=list(self.assets.values()),
                weights=weight_dict,
                portfolio_metrics=portfolio_metrics,
                optimization_time=0.0,
                convergence=True,
                objective_value=0.0,
                constraints=list(constraints.keys()),
                metadata={"simplified": True}
            )
            
        except Exception as e:
            logger.error(f"Simplified mean-variance optimization failed: {e}")
            return None
    
    async def _simplified_risk_parity(self, cov_matrix: np.ndarray, 
                                    constraints: Dict[str, Any]) -> OptimizationResult:
        """Simplified risk parity optimization (fallback)."""
        try:
            n_assets = len(self.assets)
            asset_symbols = list(self.assets.keys())
            
            # Inverse volatility weighting (simplified risk parity)
            volatilities = np.array([self.assets[symbol].volatility for symbol in asset_symbols])
            inv_vol_weights = 1.0 / volatilities
            weights = inv_vol_weights / np.sum(inv_vol_weights)
            
            # Apply constraints
            weights = np.clip(weights, constraints.get('min_weight', 0), constraints.get('max_weight', 1))
            weights = weights / np.sum(weights)  # Re-normalize
            
            weight_dict = dict(zip(asset_symbols, weights))
            portfolio_metrics = self._calculate_portfolio_metrics(weight_dict)
            
            return OptimizationResult(
                optimization_id=f"rp_simple_{int(time.time())}",
                optimization_method="risk_parity_simplified",
                assets=list(self.assets.values()),
                weights=weight_dict,
                portfolio_metrics=portfolio_metrics,
                optimization_time=0.0,
                convergence=True,
                objective_value=0.0,
                constraints=list(constraints.keys()),
                metadata={"simplified": True}
            )
            
        except Exception as e:
            logger.error(f"Simplified risk parity optimization failed: {e}")
            return None
    
    async def _simplified_max_diversification(self, expected_returns: np.ndarray, 
                                            volatilities: np.ndarray,
                                            cov_matrix: np.ndarray, 
                                            constraints: Dict[str, Any]) -> OptimizationResult:
        """Simplified max diversification optimization (fallback)."""
        try:
            n_assets = len(expected_returns)
            asset_symbols = list(self.assets.keys())
            
            # Equal weight portfolio (simplified)
            weights = np.array([1.0 / n_assets] * n_assets)
            
            # Apply constraints
            weights = np.clip(weights, constraints.get('min_weight', 0), constraints.get('max_weight', 1))
            weights = weights / np.sum(weights)  # Re-normalize
            
            weight_dict = dict(zip(asset_symbols, weights))
            portfolio_metrics = self._calculate_portfolio_metrics(weight_dict)
            
            return OptimizationResult(
                optimization_id=f"md_simple_{int(time.time())}",
                optimization_method="max_diversification_simplified",
                assets=list(self.assets.values()),
                weights=weight_dict,
                portfolio_metrics=portfolio_metrics,
                optimization_time=0.0,
                convergence=True,
                objective_value=0.0,
                constraints=list(constraints.keys()),
                metadata={"simplified": True}
            )
            
        except Exception as e:
            logger.error(f"Simplified max diversification optimization failed: {e}")
            return None
    
    async def _simplified_min_variance(self, cov_matrix: np.ndarray, 
                                     constraints: Dict[str, Any]) -> OptimizationResult:
        """Simplified min variance optimization (fallback)."""
        try:
            n_assets = len(self.assets)
            asset_symbols = list(self.assets.keys())
            
            # Equal weight portfolio (simplified)
            weights = np.array([1.0 / n_assets] * n_assets)
            
            # Apply constraints
            weights = np.clip(weights, constraints.get('min_weight', 0), constraints.get('max_weight', 1))
            weights = weights / np.sum(weights)  # Re-normalize
            
            weight_dict = dict(zip(asset_symbols, weights))
            portfolio_metrics = self._calculate_portfolio_metrics(weight_dict)
            
            return OptimizationResult(
                optimization_id=f"minv_simple_{int(time.time())}",
                optimization_method="min_variance_simplified",
                assets=list(self.assets.values()),
                weights=weight_dict,
                portfolio_metrics=portfolio_metrics,
                optimization_time=0.0,
                convergence=True,
                objective_value=0.0,
                constraints=list(constraints.keys()),
                metadata={"simplified": True}
            )
            
        except Exception as e:
            logger.error(f"Simplified min variance optimization failed: {e}")
            return None
    
    def _calculate_portfolio_metrics(self, weights: Dict[str, float]) -> PortfolioMetrics:
        """Calculate portfolio performance metrics."""
        try:
            asset_symbols = list(self.assets.keys())
            
            # Expected return and volatility
            expected_return = sum(self.assets[symbol].expected_return * weights[symbol] for symbol in asset_symbols)
            
            # Portfolio variance
            weights_array = np.array([weights[symbol] for symbol in asset_symbols])
            portfolio_variance = np.dot(weights_array, np.dot(self.covariance_matrix, weights_array))
            portfolio_volatility = np.sqrt(portfolio_variance)
            
            # Sharpe ratio
            sharpe_ratio = (expected_return - self.risk_free_rate) / portfolio_volatility if portfolio_volatility > 0 else 0
            
            # Sortino ratio (simplified - using downside deviation)
            downside_returns = [self.assets[symbol].expected_return - self.risk_free_rate 
                              for symbol in asset_symbols if self.assets[symbol].expected_return < self.risk_free_rate]
            downside_deviation = np.std(downside_returns) if downside_returns else 0.01
            sortino_ratio = (expected_return - self.risk_free_rate) / downside_deviation if downside_deviation > 0 else 0
            
            # Max drawdown (simplified)
            max_drawdown = 0.15  # Mock value
            
            # VaR and Expected Shortfall (simplified)
            var_95 = expected_return - 1.645 * portfolio_volatility
            var_99 = expected_return - 2.326 * portfolio_volatility
            expected_shortfall_95 = expected_return - 2.06 * portfolio_volatility  # Mock
            
            # Diversification ratio
            weighted_avg_volatility = sum(self.assets[symbol].volatility * weights[symbol] for symbol in asset_symbols)
            diversification_ratio = weighted_avg_volatility / portfolio_volatility if portfolio_volatility > 0 else 1
            
            # Concentration risk (Herfindahl index)
            concentration_risk = sum(weights[symbol] ** 2 for symbol in asset_symbols)
            
            return PortfolioMetrics(
                expected_return=expected_return,
                volatility=portfolio_volatility,
                sharpe_ratio=sharpe_ratio,
                sortino_ratio=sortino_ratio,
                max_drawdown=max_drawdown,
                var_95=var_95,
                var_99=var_99,
                expected_shortfall_95=expected_shortfall_95,
                diversification_ratio=diversification_ratio,
                concentration_risk=concentration_risk
            )
            
        except Exception as e:
            logger.error(f"Failed to calculate portfolio metrics: {e}")
            return PortfolioMetrics(
                expected_return=0.0, volatility=0.0, sharpe_ratio=0.0, sortino_ratio=0.0,
                max_drawdown=0.0, var_95=0.0, var_99=0.0, expected_shortfall_95=0.0,
                diversification_ratio=0.0, concentration_risk=0.0
            )
    
    async def compare_optimizations(self, constraints: Optional[Dict[str, Any]] = None) -> Dict[str, OptimizationResult]:
        """Compare multiple optimization methods."""
        try:
            results = {}
            
            for method in self.optimization_methods:
                result = await self.optimize_portfolio(method, constraints)
                if result:
                    results[method] = result
            
            # Find best result by Sharpe ratio
            best_method = None
            best_sharpe = -float('inf')
            
            for method, result in results.items():
                if result.portfolio_metrics.sharpe_ratio > best_sharpe:
                    best_sharpe = result.portfolio_metrics.sharpe_ratio
                    best_method = method
            
            results["best_method"] = best_method
            results["best_sharpe"] = best_sharpe
            
            logger.info(f"Optimization comparison completed: best method = {best_method}")
            return results
            
        except Exception as e:
            logger.error(f"Failed to compare optimizations: {e}")
            return {}
    
    async def _record_compliance(self, result: OptimizationResult):
        """Record compliance audit entry."""
        if not self.us_compliance.get("audit_optimization", True):
            return
        
        audit_entry = {
            "optimization_id": result.optimization_id,
            "method": result.optimization_method,
            "timestamp": time.time(),
            "portfolio_return": result.portfolio_metrics.expected_return,
            "portfolio_volatility": result.portfolio_metrics.volatility,
            "sharpe_ratio": result.portfolio_metrics.sharpe_ratio,
            "concentration_risk": result.portfolio_metrics.concentration_risk,
            "user": "system"  # In production, get actual user
        }
        
        # In production, store in audit database
        logger.debug(f"Portfolio optimization audit entry: {audit_entry}")
    
    def get_optimization_history(self, limit: int = 50) -> List[OptimizationResult]:
        """Get optimization history."""
        return list(self.optimization_history)[-limit:]
    
    def get_asset_universe(self) -> Dict[str, Asset]:
        """Get current asset universe."""
        return self.assets.copy()
    
    def update_config(self, new_config: Dict[str, Any]):
        """Update optimizer configuration."""
        self.config.update(new_config)
        
        # Update specific parameters
        if "risk_free_rate" in new_config:
            self.risk_free_rate = new_config["risk_free_rate"]
        if "optimization_methods" in new_config:
            self.optimization_methods = new_config["optimization_methods"]
        
        logger.info("Portfolio optimizer configuration updated")
    
    def get_optimization_summary(self) -> Dict[str, Any]:
        """Get comprehensive optimization summary."""
        if not self.optimization_history:
            return {"status": "no_data"}
        
        # Recent optimizations
        recent_optimizations = list(self.optimization_history)[-20:]
        
        # Method distribution
        method_counts = {}
        for opt in recent_optimizations:
            method = opt.optimization_method
            method_counts[method] = method_counts.get(method, 0) + 1
        
        # Performance metrics
        sharpe_ratios = [opt.portfolio_metrics.sharpe_ratio for opt in recent_optimizations]
        volatilities = [opt.portfolio_metrics.volatility for opt in recent_optimizations]
        
        return {
            "total_optimizations": len(self.optimization_history),
            "recent_optimizations": len(recent_optimizations),
            "method_distribution": method_counts,
            "performance_metrics": {
                "avg_sharpe_ratio": np.mean(sharpe_ratios) if sharpe_ratios else 0,
                "max_sharpe_ratio": max(sharpe_ratios) if sharpe_ratios else 0,
                "avg_volatility": np.mean(volatilities) if volatilities else 0,
                "min_volatility": min(volatilities) if volatilities else 0
            },
            "asset_count": len(self.assets),
            "available_methods": self.optimization_methods,
            "us_compliance": self.us_compliance
        }
