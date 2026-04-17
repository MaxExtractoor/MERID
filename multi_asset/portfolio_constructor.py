"""
Multi-Asset Portfolio Constructor for MERID Multi-Asset Expansion

Provides comprehensive multi-asset portfolio construction and
rebalancing with US-compliant configuration.

Features:
- Multi-asset portfolio construction
- Asset class allocation
- Dynamic rebalancing
- Risk budgeting
- US-compliant portfolio management
"""

import asyncio
import time
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
from enum import Enum

from utils.logger import get_logger

logger = get_logger("multi_asset.portfolio_constructor")

class RebalanceFrequency(Enum):
    """Rebalancing frequency enumeration."""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMI_ANNUALLY = "semi_annually"
    ANNUALLY = "annually"
    THRESHOLD = "threshold"

class PortfolioType(Enum):
    """Portfolio type enumeration."""
    BALANCED = "balanced"
    GROWTH = "growth"
    INCOME = "income"
    CONSERVATIVE = "conservative"
    AGGRESSIVE = "aggressive"
    TARGET_DATE = "target_date"
    RISK_PARITY = "risk_parity"

@dataclass
class AssetAllocation:
    """Asset allocation definition."""
    asset_class: str
    target_weight: float
    current_weight: float
    min_weight: float
    max_weight: float
    drift_threshold: float
    rebalance_band: float
    assets: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class PortfolioConstruction:
    """Portfolio construction result."""
    portfolio_id: str
    portfolio_type: PortfolioType
    allocations: Dict[str, AssetAllocation]
    total_value: float
    expected_return: float
    expected_volatility: float
    sharpe_ratio: float
    diversification_score: float
    rebalance_frequency: RebalanceFrequency
    construction_time: float
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class RebalanceRecommendation:
    """Portfolio rebalancing recommendation."""
    rebalance_id: str
    portfolio_id: str
    rebalance_type: str  # scheduled, threshold, tactical
    current_allocations: Dict[str, float]
    target_allocations: Dict[str, float]
    trades: List[Dict[str, Any]]
    estimated_cost: float
    tax_impact: float
    urgency: str  # low, medium, high
    reasoning: str
    timestamp: float
    metadata: Dict[str, Any] = field(default_factory=dict)

class PortfolioConstructor:
    """
    Comprehensive multi-asset portfolio constructor for MERID.
    
    Provides portfolio construction, rebalancing, and optimization
    with US-compliant configuration.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Portfolio registry
        self.portfolios: Dict[str, PortfolioConstruction] = {}
        
        # Asset class templates
        self.portfolio_templates = {
            PortfolioType.CONSERVATIVE: {
                "equity": 0.20,
                "fixed_income": 0.50,
                "commodity": 0.05,
                "real_estate": 0.10,
                "alternative": 0.15
            },
            PortfolioType.BALANCED: {
                "equity": 0.40,
                "fixed_income": 0.35,
                "commodity": 0.10,
                "real_estate": 0.10,
                "alternative": 0.05
            },
            PortfolioType.GROWTH: {
                "equity": 0.60,
                "fixed_income": 0.20,
                "commodity": 0.10,
                "real_estate": 0.05,
                "alternative": 0.05
            },
            PortfolioType.AGGRESSIVE: {
                "equity": 0.80,
                "fixed_income": 0.10,
                "commodity": 0.05,
                "real_estate": 0.03,
                "alternative": 0.02
            },
            PortfolioType.INCOME: {
                "equity": 0.15,
                "fixed_income": 0.60,
                "commodity": 0.05,
                "real_estate": 0.15,
                "alternative": 0.05
            },
            PortfolioType.RISK_PARITY: {
                "equity": 0.25,
                "fixed_income": 0.40,
                "commodity": 0.15,
                "real_estate": 0.10,
                "alternative": 0.10
            }
        }
        
        # Asset class parameters
        self.asset_class_params = {
            "equity": {
                "expected_return": 0.08,
                "volatility": 0.16,
                "min_weight": 0.0,
                "max_weight": 0.8,
                "drift_threshold": 0.05,
                "rebalance_band": 0.10
            },
            "fixed_income": {
                "expected_return": 0.04,
                "volatility": 0.08,
                "min_weight": 0.0,
                "max_weight": 0.7,
                "drift_threshold": 0.03,
                "rebalance_band": 0.08
            },
            "commodity": {
                "expected_return": 0.06,
                "volatility": 0.20,
                "min_weight": 0.0,
                "max_weight": 0.3,
                "drift_threshold": 0.05,
                "rebalance_band": 0.10
            },
            "real_estate": {
                "expected_return": 0.07,
                "volatility": 0.15,
                "min_weight": 0.0,
                "max_weight": 0.4,
                "drift_threshold": 0.04,
                "rebalance_band": 0.08
            },
            "alternative": {
                "expected_return": 0.09,
                "volatility": 0.18,
                "min_weight": 0.0,
                "max_weight": 0.3,
                "drift_threshold": 0.05,
                "rebalance_band": 0.10
            }
        }
        
        # Rebalancing parameters
        self.rebalance_params = config.get("rebalancing", {
            "min_trade_size": 1000.0,
            "max_trade_size": 100000.0,
            "transaction_cost": 0.001,  # 0.1%
            "tax_rate": 0.20,  # 20% capital gains
            "rebalance_threshold": 0.05  # 5% drift threshold
        })
        
        # Risk budgeting
        self.risk_budget = config.get("risk_budget", {
            "max_portfolio_volatility": 0.12,
            "max_asset_class_volatility": 0.20,
            "correlation_limit": 0.7
        })
        
        # US compliance settings
        self.us_compliance = config.get("us_compliance", {
            "concentration_limits": True,
            "suitability_checks": True,
            "disclosure_requirements": True,
            "audit_portfolios": True
        })
        
        logger.info("PortfolioConstructor initialized")
    
    async def construct_portfolio(self, portfolio_id: str, portfolio_type: PortfolioType,
                                total_value: float, asset_data: Dict[str, Any],
                                custom_allocations: Optional[Dict[str, float]] = None) -> Optional[PortfolioConstruction]:
        """Construct a multi-asset portfolio."""
        try:
            start_time = time.time()
            
            # Get target allocations
            if custom_allocations:
                target_allocations = custom_allocations
            else:
                target_allocations = self.portfolio_templates.get(portfolio_type, {})
            
            # Validate allocations
            if not self._validate_allocations(target_allocations):
                logger.error(f"Invalid allocations for portfolio {portfolio_id}")
                return None
            
            # Create asset allocations
            allocations = {}
            total_expected_return = 0
            total_variance = 0
            
            for asset_class, target_weight in target_allocations.items():
                # Get asset class parameters
                class_params = self.asset_class_params.get(asset_class, {})
                
                # Get assets in this class
                assets = asset_data.get(asset_class, {}).get("assets", [])
                
                # Create allocation
                allocation = AssetAllocation(
                    asset_class=asset_class,
                    target_weight=target_weight,
                    current_weight=0.0,  # Will be updated after construction
                    min_weight=class_params.get("min_weight", 0.0),
                    max_weight=class_params.get("max_weight", 1.0),
                    drift_threshold=class_params.get("drift_threshold", 0.05),
                    rebalance_band=class_params.get("rebalance_band", 0.10),
                    assets=assets
                )
                
                allocations[asset_class] = allocation
                
                # Calculate contribution to portfolio metrics
                expected_return = class_params.get("expected_return", 0.05)
                volatility = class_params.get("volatility", 0.15)
                
                total_expected_return += target_weight * expected_return
                total_variance += (target_weight ** 2) * (volatility ** 2)
            
            # Calculate portfolio metrics
            expected_volatility = np.sqrt(total_variance)
            sharpe_ratio = (total_expected_return - 0.02) / expected_volatility if expected_volatility > 0 else 0
            
            # Calculate diversification score
            diversification_score = self._calculate_diversification_score(allocations)
            
            # Determine rebalance frequency
            rebalance_frequency = self._determine_rebalance_frequency(portfolio_type)
            
            # Create portfolio construction
            portfolio = PortfolioConstruction(
                portfolio_id=portfolio_id,
                portfolio_type=portfolio_type,
                allocations=allocations,
                total_value=total_value,
                expected_return=total_expected_return,
                expected_volatility=expected_volatility,
                sharpe_ratio=sharpe_ratio,
                diversification_score=diversification_score,
                rebalance_frequency=rebalance_frequency,
                construction_time=time.time() - start_time,
                metadata={
                    "target_allocations": target_allocations,
                    "asset_data_sources": list(asset_data.keys())
                }
            )
            
            # Store portfolio
            self.portfolios[portfolio_id] = portfolio
            
            # Record for compliance
            if self.us_compliance.get("audit_portfolios", True):
                await self._record_portfolio_construction(portfolio)
            
            logger.info(f"Portfolio constructed: {portfolio_id} ({portfolio_type.value})")
            return portfolio
            
        except Exception as e:
            logger.error(f"Failed to construct portfolio {portfolio_id}: {e}")
            return None
    
    def _validate_allocations(self, allocations: Dict[str, float]) -> bool:
        """Validate portfolio allocations."""
        try:
            # Check if allocations sum to 1 (or close to it)
            total_weight = sum(allocations.values())
            if abs(total_weight - 1.0) > 0.01:  # 1% tolerance
                return False
            
            # Check individual allocations
            for asset_class, weight in allocations.items():
                if weight < 0 or weight > 1:
                    return False
                
                # Check against asset class limits
                class_params = self.asset_class_params.get(asset_class, {})
                min_weight = class_params.get("min_weight", 0.0)
                max_weight = class_params.get("max_weight", 1.0)
                
                if weight < min_weight or weight > max_weight:
                    return False
            
            # US compliance checks
            if self.us_compliance.get("concentration_limits", True):
                if not self._check_concentration_limits(allocations):
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Allocation validation error: {e}")
            return False
    
    def _check_concentration_limits(self, allocations: Dict[str, float]) -> bool:
        """Check concentration limits for US compliance."""
        try:
            # Check for excessive concentration in any single asset class
            max_concentration = 0.6  # 60% max in any single class
            
            for asset_class, weight in allocations.items():
                if weight > max_concentration:
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Concentration limit check error: {e}")
            return False
    
    def _calculate_diversification_score(self, allocations: Dict[str, AssetAllocation]) -> float:
        """Calculate portfolio diversification score."""
        try:
            # Simple diversification score based on number of asset classes and weight distribution
            n_classes = len(allocations)
            weights = [alloc.target_weight for alloc in allocations.values()]
            
            # Herfindahl index (lower = more diversified)
            herfindahl = sum(w ** 2 for w in weights)
            
            # Normalize to 0-1 scale (higher = more diversified)
            max_herfindahl = 1.0  # Single asset class
            min_herfindahl = 1.0 / n_classes  # Equal weights
            
            if max_herfindahl > min_herfindahl:
                diversification_score = 1 - (herfindahl - min_herfindahl) / (max_herfindahl - min_herfindahl)
            else:
                diversification_score = 1.0
            
            return max(0.0, min(1.0, diversification_score))
            
        except Exception as e:
            logger.error(f"Diversification score calculation error: {e}")
            return 0.5  # Default moderate diversification
    
    def _determine_rebalance_frequency(self, portfolio_type: PortfolioType) -> RebalanceFrequency:
        """Determine optimal rebalancing frequency."""
        try:
            # Different portfolio types have different optimal frequencies
            frequency_map = {
                PortfolioType.CONSERVATIVE: RebalanceFrequency.QUARTERLY,
                PortfolioType.BALANCED: RebalanceFrequency.MONTHLY,
                PortfolioType.GROWTH: RebalanceFrequency.MONTHLY,
                PortfolioType.AGGRESSIVE: RebalanceFrequency.WEEKLY,
                PortfolioType.INCOME: RebalanceFrequency.MONTHLY,
                PortfolioType.RISK_PARITY: RebalanceFrequency.THRESHOLD
            }
            
            return frequency_map.get(portfolio_type, RebalanceFrequency.MONTHLY)
            
        except Exception as e:
            logger.error(f"Rebalance frequency determination error: {e}")
            return RebalanceFrequency.MONTHLY
    
    async def generate_rebalance_recommendation(self, portfolio_id: str, 
                                              current_values: Dict[str, float]) -> Optional[RebalanceRecommendation]:
        """Generate portfolio rebalancing recommendation."""
        try:
            if portfolio_id not in self.portfolios:
                logger.error(f"Portfolio {portfolio_id} not found")
                return None
            
            portfolio = self.portfolios[portfolio_id]
            
            # Calculate current allocations
            total_value = sum(current_values.values())
            current_allocations = {}
            
            for asset_class, value in current_values.items():
                current_allocations[asset_class] = value / total_value if total_value > 0 else 0
            
            # Update current weights in portfolio
            for asset_class, allocation in portfolio.allocations.items():
                allocation.current_weight = current_allocations.get(asset_class, 0.0)
            
            # Check if rebalancing is needed
            rebalance_needed = False
            rebalance_type = "scheduled"
            max_drift = 0
            
            for asset_class, allocation in portfolio.allocations.items():
                current_weight = allocation.current_weight
                target_weight = allocation.target_weight
                drift = abs(current_weight - target_weight)
                
                if drift > allocation.drift_threshold:
                    rebalance_needed = True
                    max_drift = max(max_drift, drift)
                    rebalance_type = "threshold"
            
            if not rebalance_needed:
                return None
            
            # Calculate target trades
            trades = []
            total_trade_value = 0
            
            for asset_class, allocation in portfolio.allocations.items():
                current_weight = allocation.current_weight
                target_weight = allocation.target_weight
                
                if abs(current_weight - target_weight) > 0.01:  # 1% minimum trade
                    current_value = current_values.get(asset_class, 0)
                    target_value = total_value * target_weight
                    
                    trade_value = target_value - current_value
                    
                    if abs(trade_value) > self.rebalance_params["min_trade_size"]:
                        trades.append({
                            "asset_class": asset_class,
                            "trade_type": "buy" if trade_value > 0 else "sell",
                            "trade_value": trade_value,
                            "current_weight": current_weight,
                            "target_weight": target_weight,
                            "assets": allocation.assets
                        })
                        
                        total_trade_value += abs(trade_value)
            
            if not trades:
                return None
            
            # Calculate estimated costs
            transaction_cost = total_trade_value * self.rebalance_params["transaction_cost"]
            tax_impact = self._estimate_tax_impact(trades)
            total_cost = transaction_cost + tax_impact
            
            # Determine urgency
            if max_drift > 0.10:
                urgency = "high"
            elif max_drift > 0.05:
                urgency = "medium"
            else:
                urgency = "low"
            
            # Generate reasoning
            reasoning = f"Rebalancing needed due to {max_drift:.1%} maximum drift from target allocations"
            
            # Create recommendation
            recommendation = RebalanceRecommendation(
                rebalance_id=f"rebalance_{int(time.time())}",
                portfolio_id=portfolio_id,
                rebalance_type=rebalance_type,
                current_allocations=current_allocations,
                target_allocations={ac: alloc.target_weight for ac, alloc in portfolio.allocations.items()},
                trades=trades,
                estimated_cost=total_cost,
                tax_impact=tax_impact,
                urgency=urgency,
                reasoning=reasoning,
                timestamp=time.time(),
                metadata={
                    "max_drift": max_drift,
                    "total_trade_value": total_trade_value,
                    "transaction_cost": transaction_cost
                }
            )
            
            logger.info(f"Rebalance recommendation generated: {portfolio_id}")
            return recommendation
            
        except Exception as e:
            logger.error(f"Failed to generate rebalance recommendation: {e}")
            return None
    
    def _estimate_tax_impact(self, trades: List[Dict[str, Any]]) -> float:
        """Estimate tax impact of trades."""
        try:
            # Simplified tax estimation
            # In production, use actual cost basis, holding periods, etc.
            
            total_tax = 0
            tax_rate = self.rebalance_params["tax_rate"]
            
            for trade in trades:
                trade_value = abs(trade["trade_value"])
                
                # Assume 50% of trades are taxable gains (simplified)
                taxable_gain = trade_value * 0.5
                total_tax += taxable_gain * tax_rate
            
            return total_tax
            
        except Exception as e:
            logger.error(f"Tax impact estimation error: {e}")
            return 0.0
    
    async def optimize_portfolio_allocation(self, portfolio_id: str, 
                                          asset_returns: Dict[str, pd.DataFrame]) -> Optional[Dict[str, float]]:
        """Optimize portfolio allocation based on historical returns."""
        try:
            if portfolio_id not in self.portfolios:
                logger.error(f"Portfolio {portfolio_id} not found")
                return None
            
            portfolio = self.portfolios[portfolio_id]
            
            # Collect return data for all asset classes
            return_data = {}
            
            for asset_class in portfolio.allocations.keys():
                if asset_class in asset_returns:
                    returns = asset_returns[asset_class]["returns"].dropna()
                    if len(returns) > 50:  # Minimum data requirement
                        return_data[asset_class] = returns
            
            if len(return_data) < 2:
                logger.warning("Insufficient return data for optimization")
                return None
            
            # Calculate expected returns and covariance matrix
            expected_returns = {}
            for asset_class, returns in return_data.items():
                expected_returns[asset_class] = returns.mean()
            
            # Create covariance matrix
            asset_classes = list(return_data.keys())
            n_assets = len(asset_classes)
            
            # Align data
            min_length = min(len(returns) for returns in return_data.values())
            aligned_returns = {}
            
            for asset_class, returns in return_data.items():
                aligned_returns[asset_class] = returns.tail(min_length)
            
            # Create return matrix
            return_matrix = np.column_stack([aligned_returns[ac] for ac in asset_classes])
            cov_matrix = np.cov(return_matrix.T)
            
            # Mean-variance optimization (simplified)
            # Use equal risk contribution as starting point
            n_assets = len(asset_classes)
            
            # Simple optimization: inverse volatility weighting
            volatilities = np.sqrt(np.diag(cov_matrix))
            inv_vol_weights = 1.0 / volatilities
            weights = inv_vol_weights / np.sum(inv_vol_weights)
            
            # Apply constraints
            optimized_weights = {}
            for i, asset_class in enumerate(asset_classes):
                weight = weights[i]
                
                # Apply min/max constraints
                allocation = portfolio.allocations[asset_class]
                weight = max(allocation.min_weight, min(allocation.max_weight, weight))
                
                optimized_weights[asset_class] = weight
            
            # Normalize weights
            total_weight = sum(optimized_weights.values())
            if total_weight > 0:
                for asset_class in optimized_weights:
                    optimized_weights[asset_class] /= total_weight
            
            logger.info(f"Portfolio optimization completed: {portfolio_id}")
            return optimized_weights
            
        except Exception as e:
            logger.error(f"Failed to optimize portfolio allocation: {e}")
            return None
    
    def get_portfolio(self, portfolio_id: str) -> Optional[PortfolioConstruction]:
        """Get portfolio construction."""
        return self.portfolios.get(portfolio_id)
    
    def get_all_portfolios(self) -> Dict[str, PortfolioConstruction]:
        """Get all portfolios."""
        return self.portfolios.copy()
    
    def update_portfolio_value(self, portfolio_id: str, new_value: float) -> bool:
        """Update portfolio total value."""
        try:
            if portfolio_id not in self.portfolios:
                return False
            
            self.portfolios[portfolio_id].total_value = new_value
            logger.info(f"Updated portfolio {portfolio_id} value: ${new_value:,.2f}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update portfolio value: {e}")
            return False
    
    def remove_portfolio(self, portfolio_id: str) -> bool:
        """Remove a portfolio."""
        try:
            if portfolio_id in self.portfolios:
                del self.portfolios[portfolio_id]
                logger.info(f"Portfolio {portfolio_id} removed")
                return True
            return False
            
        except Exception as e:
            logger.error(f"Failed to remove portfolio: {e}")
            return False
    
    async def _record_portfolio_construction(self, portfolio: PortfolioConstruction):
        """Record portfolio construction for compliance."""
        if not self.us_compliance.get("audit_portfolios", True):
            return
        
        audit_entry = {
            "action": "portfolio_construction",
            "portfolio_id": portfolio.portfolio_id,
            "portfolio_type": portfolio.portfolio_type.value,
            "total_value": portfolio.total_value,
            "expected_return": portfolio.expected_return,
            "expected_volatility": portfolio.expected_volatility,
            "timestamp": time.time(),
            "user": "system"  # In production, get actual user
        }
        
        # In production, store in audit database
        logger.debug(f"Portfolio construction audit entry: {audit_entry}")
    
    def get_portfolio_summary(self) -> Dict[str, Any]:
        """Get comprehensive portfolio summary."""
        try:
            if not self.portfolios:
                return {"status": "no_portfolios"}
            
            # Portfolio type distribution
            type_counts = {}
            total_value = 0
            
            for portfolio in self.portfolios.values():
                portfolio_type = portfolio.portfolio_type.value
                type_counts[portfolio_type] = type_counts.get(portfolio_type, 0) + 1
                total_value += portfolio.total_value
            
            # Performance metrics
            expected_returns = [p.expected_return for p in self.portfolios.values()]
            volatilities = [p.expected_volatility for p in self.portfolios.values()]
            sharpe_ratios = [p.sharpe_ratio for p in self.portfolios.values()]
            diversification_scores = [p.diversification_score for p in self.portfolios.values()]
            
            return {
                "total_portfolios": len(self.portfolios),
                "total_value": total_value,
                "portfolio_types": type_counts,
                "performance_metrics": {
                    "avg_expected_return": np.mean(expected_returns) if expected_returns else 0,
                    "avg_volatility": np.mean(volatilities) if volatilities else 0,
                    "avg_sharpe_ratio": np.mean(sharpe_ratios) if sharpe_ratios else 0,
                    "avg_diversification_score": np.mean(diversification_scores) if diversification_scores else 0
                },
                "rebalance_frequencies": {
                    freq.value: sum(1 for p in self.portfolios.values() if p.rebalance_frequency == freq)
                    for freq in RebalanceFrequency
                },
                "us_compliance": self.us_compliance
            }
            
        except Exception as e:
            logger.error(f"Failed to get portfolio summary: {e}")
            return {"status": "error", "error": str(e)}
    
    def update_config(self, new_config: Dict[str, Any]):
        """Update portfolio constructor configuration."""
        self.config.update(new_config)
        
        # Update specific parameters
        if "rebalancing" in new_config:
            self.rebalance_params.update(new_config["rebalancing"])
        if "risk_budget" in new_config:
            self.risk_budget.update(new_config["risk_budget"])
        
        logger.info("Portfolio constructor configuration updated")
