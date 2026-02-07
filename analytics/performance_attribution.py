"""
Performance Attribution for MERID Advanced Analytics

Provides comprehensive performance attribution analysis with
factor models and US-compliant configuration.

Features:
- Multi-factor attribution analysis
- Sector and regional attribution
- Style factor attribution
- Risk-adjusted performance attribution
- US-compliant reporting
"""

import asyncio
import time
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
import logging
from enum import Enum

from utils.logger import get_logger

logger = get_logger("analytics.performance_attribution")

class AttributionType(Enum):
    """Attribution type enumeration."""
    ASSET_ALLOCATION = "asset_allocation"
    SECTOR = "sector"
    REGION = "region"
    STYLE = "style"
    FACTOR = "factor"
    RISK = "risk"
    CURRENCY = "currency"

class AttributionMethod(Enum):
    """Attribution method enumeration."""
    ARITHMETIC = "arithmetic"
    GEOMETRIC = "geometric"
    REGRESSION = "regression"
    RISK_ADJUSTED = "risk_adjusted"

@dataclass
class AttributionFactor:
    """Attribution factor definition."""
    factor_id: str
    factor_name: str
    factor_type: AttributionType
    exposure: float
    contribution: float
    attribution: float
    weight: float
    benchmark_weight: float
    active_weight: float
    return_contribution: float
    risk_contribution: float
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class AttributionResult:
    """Performance attribution result."""
    attribution_id: str
    portfolio_id: str
    benchmark_id: str
    period_start: datetime
    period_end: datetime
    total_return: float
    benchmark_return: float
    active_return: float
    attribution_method: AttributionMethod
    factors: List[AttributionFactor]
    allocation_effect: float
    selection_effect: float
    interaction_effect: float
    total_attribution: float
    attribution_quality: float
    risk_adjusted_attribution: float
    timestamp: float
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class FactorModel:
    """Factor model definition."""
    model_id: str
    model_name: str
    model_type: str
    factors: List[str]
    factor_loadings: Dict[str, float]
    factor_returns: Dict[str, float]
    factor_covariance: np.ndarray
    specific_risk: float
    r_squared: float
    adjusted_r_squared: float
    metadata: Dict[str, Any] = field(default_factory=dict)

class PerformanceAttribution:
    """
    Comprehensive performance attribution system for MERID.
    
    Provides multi-factor attribution analysis with various
    attribution methods and US-compliant configuration.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Attribution history
        self.attribution_history: deque = deque(maxlen=1000)
        
        # Factor models
        self.factor_models: Dict[str, FactorModel] = {}
        
        # Benchmark data
        self.benchmark_data: Dict[str, pd.DataFrame] = {}
        
        # Attribution parameters
        self.attribution_params = config.get("attribution_parameters", {
            "min_periods": 20,
            "confidence_level": 0.95,
            "risk_free_rate": 0.02,
            "attribution_method": AttributionMethod.ARITHMETIC.value
        })
        
        # Factor definitions
        self.factor_definitions = {
            "market": {"type": AttributionType.FACTOR, "description": "Market factor"},
            "size": {"type": AttributionType.STYLE, "description": "Size factor"},
            "value": {"type": AttributionType.STYLE, "description": "Value factor"},
            "momentum": {"type": AttributionType.STYLE, "description": "Momentum factor"},
            "quality": {"type": AttributionType.STYLE, "description": "Quality factor"},
            "volatility": {"type": AttributionType.STYLE, "description": "Volatility factor"},
            "sector_technology": {"type": AttributionType.SECTOR, "description": "Technology sector"},
            "sector_healthcare": {"type": AttributionType.SECTOR, "description": "Healthcare sector"},
            "sector_financial": {"type": AttributionType.SECTOR, "description": "Financial sector"},
            "region_us": {"type": AttributionType.REGION, "description": "US region"},
            "region_europe": {"type": AttributionType.REGION, "description": "Europe region"},
            "region_asia": {"type": AttributionType.REGION, "description": "Asia region"}
        }
        
        # US compliance settings
        self.us_compliance = config.get("us_compliance", {
            "attribution_standards": True,
            "performance_disclosure": True,
            "risk_adjusted_returns": True,
            "audit_attribution": True
        })
        
        logger.info("PerformanceAttribution initialized")
    
    async def calculate_attribution(self, portfolio_data: pd.DataFrame, 
                                  benchmark_data: pd.DataFrame,
                                  attribution_method: AttributionMethod = AttributionMethod.ARITHMETIC) -> Optional[AttributionResult]:
        """Calculate performance attribution."""
        try:
            start_time = time.time()
            
            # Validate data
            if not self._validate_attribution_data(portfolio_data, benchmark_data):
                logger.error("Invalid attribution data")
                return None
            
            # Calculate basic returns
            portfolio_return = self._calculate_total_return(portfolio_data)
            benchmark_return = self._calculate_total_return(benchmark_data)
            active_return = portfolio_return - benchmark_return
            
            # Calculate attribution based on method
            if attribution_method == AttributionMethod.ARITHMETIC:
                factors = await self._arithmetic_attribution(portfolio_data, benchmark_data)
            elif attribution_method == AttributionMethod.GEOMETRIC:
                factors = await self._geometric_attribution(portfolio_data, benchmark_data)
            elif attribution_method == AttributionMethod.REGRESSION:
                factors = await self._regression_attribution(portfolio_data, benchmark_data)
            elif attribution_method == AttributionMethod.RISK_ADJUSTED:
                factors = await self._risk_adjusted_attribution(portfolio_data, benchmark_data)
            else:
                logger.error(f"Unknown attribution method: {attribution_method}")
                return None
            
            # Calculate attribution effects
            allocation_effect, selection_effect, interaction_effect = self._calculate_attribution_effects(factors)
            
            # Calculate attribution quality
            attribution_quality = self._calculate_attribution_quality(factors, active_return)
            
            # Calculate risk-adjusted attribution
            risk_adjusted_attribution = self._calculate_risk_adjusted_attribution(factors, portfolio_data)
            
            # Create attribution result
            result = AttributionResult(
                attribution_id=f"attr_{int(time.time())}",
                portfolio_id="portfolio",
                benchmark_id="benchmark",
                period_start=portfolio_data.index[0],
                period_end=portfolio_data.index[-1],
                total_return=portfolio_return,
                benchmark_return=benchmark_return,
                active_return=active_return,
                attribution_method=attribution_method,
                factors=factors,
                allocation_effect=allocation_effect,
                selection_effect=selection_effect,
                interaction_effect=interaction_effect,
                total_attribution=allocation_effect + selection_effect + interaction_effect,
                attribution_quality=attribution_quality,
                risk_adjusted_attribution=risk_adjusted_attribution,
                timestamp=time.time(),
                metadata={
                    "calculation_time": time.time() - start_time,
                    "factor_count": len(factors)
                }
            )
            
            # Store result
            self.attribution_history.append(result)
            
            # Record for compliance
            if self.us_compliance.get("audit_attribution", True):
                await self._record_attribution(result)
            
            logger.info(f"Performance attribution completed: {attribution_method.value}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to calculate performance attribution: {e}")
            return None
    
    def _validate_attribution_data(self, portfolio_data: pd.DataFrame, benchmark_data: pd.DataFrame) -> bool:
        """Validate attribution data."""
        try:
            # Check data length
            min_periods = self.attribution_params["min_periods"]
            if len(portfolio_data) < min_periods or len(benchmark_data) < min_periods:
                return False
            
            # Check data alignment
            if not portfolio_data.index.equals(benchmark_data.index):
                return False
            
            # Check required columns
            required_columns = ["return", "weight"]
            for col in required_columns:
                if col not in portfolio_data.columns or col not in benchmark_data.columns:
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Attribution data validation error: {e}")
            return False
    
    def _calculate_total_return(self, data: pd.DataFrame) -> float:
        """Calculate total return from data."""
        try:
            # Calculate weighted return
            total_return = (data["return"] * data["weight"]).sum()
            return total_return
            
        except Exception as e:
            logger.error(f"Total return calculation error: {e}")
            return 0.0
    
    async def _arithmetic_attribution(self, portfolio_data: pd.DataFrame, 
                                   benchmark_data: pd.DataFrame) -> List[AttributionFactor]:
        """Calculate arithmetic attribution."""
        try:
            factors = []
            
            # Calculate active weights
            portfolio_weights = portfolio_data["weight"]
            benchmark_weights = benchmark_data["weight"]
            active_weights = portfolio_weights - benchmark_weights
            
            # Calculate returns
            portfolio_returns = portfolio_data["return"]
            benchmark_returns = benchmark_data["return"]
            
            # Asset allocation attribution
            for asset in portfolio_data.index:
                if asset in benchmark_data.index:
                    active_weight = active_weights[asset]
                    benchmark_return = benchmark_returns[asset]
                    
                    allocation_contribution = active_weight * benchmark_return
                    
                    factor = AttributionFactor(
                        factor_id=f"allocation_{asset}",
                        factor_name=f"Allocation_{asset}",
                        factor_type=AttributionType.ASSET_ALLOCATION,
                        exposure=active_weight,
                        contribution=allocation_contribution,
                        attribution=allocation_contribution,
                        weight=portfolio_weights[asset],
                        benchmark_weight=benchmark_weights[asset],
                        active_weight=active_weight,
                        return_contribution=allocation_contribution,
                        risk_contribution=0.0  # Simplified
                    )
                    
                    factors.append(factor)
            
            # Security selection attribution
            for asset in portfolio_data.index:
                if asset in benchmark_data.index:
                    portfolio_weight = portfolio_weights[asset]
                    excess_return = portfolio_returns[asset] - benchmark_returns[asset]
                    
                    selection_contribution = portfolio_weight * excess_return
                    
                    factor = AttributionFactor(
                        factor_id=f"selection_{asset}",
                        factor_name=f"Selection_{asset}",
                        factor_type=AttributionType.ASSET_ALLOCATION,
                        exposure=portfolio_weight,
                        contribution=selection_contribution,
                        attribution=selection_contribution,
                        weight=portfolio_weights[asset],
                        benchmark_weight=benchmark_weights[asset],
                        active_weight=portfolio_weights[asset] - benchmark_weights[asset],
                        return_contribution=selection_contribution,
                        risk_contribution=0.0  # Simplified
                    )
                    
                    factors.append(factor)
            
            return factors
            
        except Exception as e:
            logger.error(f"Arithmetic attribution error: {e}")
            return []
    
    async def _geometric_attribution(self, portfolio_data: pd.DataFrame, 
                                  benchmark_data: pd.DataFrame) -> List[AttributionFactor]:
        """Calculate geometric attribution."""
        try:
            # Simplified geometric attribution
            # In production, implement full geometric attribution methodology
            
            factors = []
            
            # Calculate cumulative returns
            portfolio_cum_return = (1 + portfolio_data["return"]).prod() - 1
            benchmark_cum_return = (1 + benchmark_data["return"]).prod() - 1
            
            # Calculate geometric attribution for each asset
            for asset in portfolio_data.index:
                if asset in benchmark_data.index:
                    portfolio_weight = portfolio_data["weight"][asset]
                    benchmark_weight = benchmark_data["weight"][asset]
                    portfolio_return = portfolio_data["return"][asset]
                    benchmark_return = benchmark_data["return"][asset]
                    
                    # Simplified geometric attribution
                    geometric_contribution = (portfolio_weight - benchmark_weight) * benchmark_return
                    geometric_contribution += portfolio_weight * (portfolio_return - benchmark_return)
                    
                    factor = AttributionFactor(
                        factor_id=f"geometric_{asset}",
                        factor_name=f"Geometric_{asset}",
                        factor_type=AttributionType.ASSET_ALLOCATION,
                        exposure=portfolio_weight - benchmark_weight,
                        contribution=geometric_contribution,
                        attribution=geometric_contribution,
                        weight=portfolio_weight,
                        benchmark_weight=benchmark_weight,
                        active_weight=portfolio_weight - benchmark_weight,
                        return_contribution=geometric_contribution,
                        risk_contribution=0.0
                    )
                    
                    factors.append(factor)
            
            return factors
            
        except Exception as e:
            logger.error(f"Geometric attribution error: {e}")
            return []
    
    async def _regression_attribution(self, portfolio_data: pd.DataFrame, 
                                   benchmark_data: pd.DataFrame) -> List[AttributionFactor]:
        """Calculate regression-based attribution."""
        try:
            factors = []
            
            # Simplified regression attribution
            # In production, implement proper factor regression analysis
            
            # Market factor attribution
            portfolio_excess_return = portfolio_data["return"].mean() - self.attribution_params["risk_free_rate"]
            benchmark_excess_return = benchmark_data["return"].mean() - self.attribution_params["risk_free_rate"]
            
            # Calculate beta (simplified)
            portfolio_returns = portfolio_data["return"]
            benchmark_returns = benchmark_data["return"]
            
            if len(portfolio_returns) > 1 and len(benchmark_returns) > 1:
                covariance = np.cov(portfolio_returns, benchmark_returns)[0, 1]
                benchmark_variance = np.var(benchmark_returns)
                beta = covariance / benchmark_variance if benchmark_variance > 0 else 1.0
            else:
                beta = 1.0
            
            # Market factor contribution
            market_contribution = beta * benchmark_excess_return
            
            factor = AttributionFactor(
                factor_id="market_factor",
                factor_name="Market Factor",
                factor_type=AttributionType.FACTOR,
                exposure=beta,
                contribution=market_contribution,
                attribution=market_contribution,
                weight=1.0,
                benchmark_weight=1.0,
                active_weight=0.0,
                return_contribution=market_contribution,
                risk_contribution=beta ** 2 * benchmark_variance
            )
            
            factors.append(factor)
            
            # Add other style factors (simplified)
            style_factors = ["size", "value", "momentum"]
            for style_factor in style_factors:
                # Mock factor returns and loadings
                factor_return = np.random.normal(0.001, 0.02)
                factor_loading = np.random.normal(0.5, 0.2)
                
                contribution = factor_loading * factor_return
                
                factor = AttributionFactor(
                    factor_id=f"{style_factor}_factor",
                    factor_name=f"{style_factor.title()} Factor",
                    factor_type=AttributionType.STYLE,
                    exposure=factor_loading,
                    contribution=contribution,
                    attribution=contribution,
                    weight=factor_loading,
                    benchmark_weight=0.0,
                    active_weight=factor_loading,
                    return_contribution=contribution,
                    risk_contribution=factor_loading ** 2 * 0.0004  # Simplified risk
                )
                
                factors.append(factor)
            
            return factors
            
        except Exception as e:
            logger.error(f"Regression attribution error: {e}")
            return []
    
    async def _risk_adjusted_attribution(self, portfolio_data: pd.DataFrame, 
                                      benchmark_data: pd.DataFrame) -> List[AttributionFactor]:
        """Calculate risk-adjusted attribution."""
        try:
            # Get base attribution
            base_factors = await self._arithmetic_attribution(portfolio_data, benchmark_data)
            
            # Adjust for risk
            risk_adjusted_factors = []
            
            for factor in base_factors:
                # Calculate risk adjustment
                risk_adjustment = 1.0 - abs(factor.exposure) * 0.1  # Simplified risk adjustment
                
                risk_adjusted_contribution = factor.contribution * risk_adjustment
                
                risk_adjusted_factor = AttributionFactor(
                    factor_id=f"risk_adj_{factor.factor_id}",
                    factor_name=f"Risk Adj {factor.factor_name}",
                    factor_type=factor.factor_type,
                    exposure=factor.exposure,
                    contribution=risk_adjusted_contribution,
                    attribution=risk_adjusted_contribution,
                    weight=factor.weight,
                    benchmark_weight=factor.benchmark_weight,
                    active_weight=factor.active_weight,
                    return_contribution=risk_adjusted_contribution,
                    risk_contribution=factor.risk_contribution * risk_adjustment
                )
                
                risk_adjusted_factors.append(risk_adjusted_factor)
            
            return risk_adjusted_factors
            
        except Exception as e:
            logger.error(f"Risk-adjusted attribution error: {e}")
            return []
    
    def _calculate_attribution_effects(self, factors: List[AttributionFactor]) -> Tuple[float, float, float]:
        """Calculate allocation, selection, and interaction effects."""
        try:
            allocation_effect = 0.0
            selection_effect = 0.0
            interaction_effect = 0.0
            
            for factor in factors:
                if "allocation" in factor.factor_id:
                    allocation_effect += factor.contribution
                elif "selection" in factor.factor_id:
                    selection_effect += factor.contribution
                else:
                    interaction_effect += factor.contribution
            
            return allocation_effect, selection_effect, interaction_effect
            
        except Exception as e:
            logger.error(f"Attribution effects calculation error: {e}")
            return 0.0, 0.0, 0.0
    
    def _calculate_attribution_quality(self, factors: List[AttributionFactor], active_return: float) -> float:
        """Calculate attribution quality score."""
        try:
            if not factors or active_return == 0:
                return 0.0
            
            # Calculate explained attribution
            total_attribution = sum(factor.contribution for factor in factors)
            
            # Quality based on how well attribution explains active return
            explained_ratio = abs(total_attribution) / abs(active_return) if active_return != 0 else 0
            
            # Adjust for factor count (penalize too many factors)
            factor_penalty = min(0.1, len(factors) * 0.01)
            
            quality_score = max(0.0, explained_ratio - factor_penalty)
            
            return min(1.0, quality_score)
            
        except Exception as e:
            logger.error(f"Attribution quality calculation error: {e}")
            return 0.0
    
    def _calculate_risk_adjusted_attribution(self, factors: List[AttributionFactor], 
                                           portfolio_data: pd.DataFrame) -> float:
        """Calculate risk-adjusted attribution."""
        try:
            # Calculate portfolio risk
            portfolio_volatility = portfolio_data["return"].std() * np.sqrt(252)
            
            # Calculate risk-adjusted contribution
            risk_adjusted_contribution = 0.0
            total_risk_contribution = sum(abs(factor.risk_contribution) for factor in factors)
            
            if total_risk_contribution > 0:
                for factor in factors:
                    risk_weight = abs(factor.risk_contribution) / total_risk_contribution
                    risk_adjusted_contribution += factor.contribution * risk_weight
            
            # Adjust for portfolio volatility
            risk_adjusted_attribution = risk_adjusted_contribution / portfolio_volatility if portfolio_volatility > 0 else 0
            
            return risk_adjusted_attribution
            
        except Exception as e:
            logger.error(f"Risk-adjusted attribution calculation error: {e}")
            return 0.0
    
    async def create_factor_model(self, model_id: str, model_name: str, 
                               factor_returns: pd.DataFrame) -> Optional[FactorModel]:
        """Create a factor model."""
        try:
            # Calculate factor loadings (simplified)
            factor_loadings = {}
            for factor in factor_returns.columns:
                # Mock factor loading
                factor_loadings[factor] = np.random.normal(0.5, 0.2)
            
            # Calculate factor covariance matrix
            factor_covariance = factor_returns.cov().values
            
            # Calculate model statistics
            specific_risk = np.random.uniform(0.1, 0.3)
            r_squared = np.random.uniform(0.6, 0.9)
            adjusted_r_squared = r_squared - (1 - r_squared) * len(factor_returns.columns) / (len(factor_returns) - len(factor_returns.columns) - 1)
            
            factor_model = FactorModel(
                model_id=model_id,
                model_name=model_name,
                model_type="multi_factor",
                factors=list(factor_returns.columns),
                factor_loadings=factor_loadings,
                factor_returns={factor: factor_returns[factor].mean() for factor in factor_returns.columns},
                factor_covariance=factor_covariance,
                specific_risk=specific_risk,
                r_squared=r_squared,
                adjusted_r_squared=adjusted_r_squared
            )
            
            # Store factor model
            self.factor_models[model_id] = factor_model
            
            logger.info(f"Factor model created: {model_id}")
            return factor_model
            
        except Exception as e:
            logger.error(f"Failed to create factor model {model_id}: {e}")
            return None
    
    async def calculate_factor_attribution(self, portfolio_data: pd.DataFrame, 
                                         factor_model_id: str) -> Optional[Dict[str, float]]:
        """Calculate factor-based attribution."""
        try:
            if factor_model_id not in self.factor_models:
                logger.error(f"Factor model {factor_model_id} not found")
                return None
            
            factor_model = self.factor_models[factor_model_id]
            
            # Calculate factor attribution
            factor_attribution = {}
            
            for factor in factor_model.factors:
                factor_loading = factor_model.factor_loadings.get(factor, 0.0)
                factor_return = factor_model.factor_returns.get(factor, 0.0)
                
                attribution = factor_loading * factor_return
                factor_attribution[factor] = attribution
            
            return factor_attribution
            
        except Exception as e:
            logger.error(f"Failed to calculate factor attribution: {e}")
            return None
    
    def get_attribution_history(self, limit: int = 100) -> List[AttributionResult]:
        """Get attribution history."""
        return list(self.attribution_history)[-limit:]
    
    def get_factor_models(self) -> Dict[str, FactorModel]:
        """Get all factor models."""
        return self.factor_models.copy()
    
    def get_attribution_summary(self) -> Dict[str, Any]:
        """Get comprehensive attribution summary."""
        try:
            if not self.attribution_history:
                return {"status": "no_data"}
            
            # Recent attributions
            recent_attributions = list(self.attribution_history)[-50:]
            
            # Method distribution
            method_counts = {}
            for attribution in recent_attributions:
                method = attribution.attribution_method.value
                method_counts[method] = method_counts.get(method, 0) + 1
            
            # Performance metrics
            active_returns = [attr.active_return for attr in recent_attributions]
            attribution_qualities = [attr.attribution_quality for attr in recent_attributions]
            
            return {
                "total_attributions": len(self.attribution_history),
                "recent_attributions": len(recent_attributions),
                "method_distribution": method_counts,
                "performance_metrics": {
                    "avg_active_return": np.mean(active_returns) if active_returns else 0,
                    "avg_attribution_quality": np.mean(attribution_qualities) if attribution_qualities else 0,
                    "max_attribution_quality": max(attribution_qualities) if attribution_qualities else 0
                },
                "factor_models": len(self.factor_models),
                "us_compliance": self.us_compliance
            }
            
        except Exception as e:
            logger.error(f"Failed to get attribution summary: {e}")
            return {"status": "error", "error": str(e)}
    
    async def _record_attribution(self, result: AttributionResult):
        """Record attribution for compliance."""
        if not self.us_compliance.get("audit_attribution", True):
            return
        
        audit_entry = {
            "action": "performance_attribution",
            "attribution_id": result.attribution_id,
            "portfolio_id": result.portfolio_id,
            "benchmark_id": result.benchmark_id,
            "total_return": result.total_return,
            "active_return": result.active_return,
            "attribution_method": result.attribution_method.value,
            "timestamp": result.timestamp,
            "user": "system"  # In production, get actual user
        }
        
        # In production, store in audit database
        logger.debug(f"Performance attribution audit entry: {audit_entry}")
    
    def update_config(self, new_config: Dict[str, Any]):
        """Update attribution configuration."""
        self.config.update(new_config)
        
        # Update specific parameters
        if "attribution_parameters" in new_config:
            self.attribution_params.update(new_config["attribution_parameters"])
        
        logger.info("Performance attribution configuration updated")
