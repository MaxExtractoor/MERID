"""
Correlation Analysis for MERID Predictive Analytics

Provides comprehensive correlation analysis and asset relationship modeling
with US-compliant configuration.

Features:
- Cross-asset correlation analysis
- Dynamic correlation tracking
- Portfolio diversification metrics
- Risk factor analysis
- US-compliant data handling
"""

import asyncio
import time
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque

from utils.logger import get_logger

logger = get_logger("analytics.correlation_analysis")

@dataclass
class CorrelationMetrics:
    """Correlation metrics snapshot."""
    timestamp: float
    asset_pairs: List[Tuple[str, str]]
    correlation_matrix: Dict[str, Dict[str, float]]
    average_correlation: float
    max_correlation: float
    min_correlation: float
    correlation_trend: float
    diversification_ratio: float
    concentration_risk: float
    systemic_risk: float
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class CorrelationForecast:
    """Correlation forecast result."""
    forecast_id: str
    asset_pairs: List[Tuple[str, str]]
    correlation_forecasts: Dict[str, float]
    confidence_intervals: Dict[str, Tuple[float, float]]
    forecast_horizon: int
    timestamps: List[datetime]
    model_metrics: Dict[str, float]
    prediction_time: float
    metadata: Dict[str, Any] = field(default_factory=dict)

class CorrelationAnalyzer:
    """
    Comprehensive correlation analysis system for MERID.
    
    Provides cross-asset correlation analysis, dynamic tracking,
    and portfolio diversification metrics with US-compliant configuration.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Analysis parameters
        self.lookback_period = config.get("lookback_period", 252)  # 1 year
        self.min_samples = config.get("min_samples", 100)
        self.correlation_threshold = config.get("correlation_threshold", 0.7)
        
        # Analysis history
        self.correlation_history: deque = deque(maxlen=1000)
        self.forecast_history: deque = deque(maxlen=500)
        
        # Asset universe
        self.asset_universe: Dict[str, Dict[str, Any]] = {}
        
        # Correlation matrices
        self.correlation_matrices: deque = deque(maxlen=100)
        
        # Risk metrics
        self.risk_metrics: Dict[str, float] = {}
        
        # US compliance settings
        self.us_compliance = config.get("us_compliance", {
            "data_privacy": True,
            "correlation_logging": True,
            "risk_assessment": True
        })
        
        logger.info("CorrelationAnalyzer initialized")
    
    async def add_asset(self, asset_id: str, asset_data: pd.Series, 
                        asset_metadata: Dict[str, Any]) -> bool:
        """Add asset to correlation analysis."""
        try:
            # Validate data
            if len(asset_data) < self.min_samples:
                logger.warning(f"Insufficient data for asset {asset_id}")
                return False
            
            # Store asset data
            self.asset_universe[asset_id] = {
                "data": asset_data,
                "metadata": asset_metadata,
                "added_timestamp": time.time()
            }
            
            logger.info(f"Added asset {asset_id} to correlation analysis")
            return True
            
        except Exception as e:
            logger.error(f"Failed to add asset {asset_id}: {e}")
            return False
    
    async def calculate_correlations(self, window: Optional[int] = None) -> Optional[CorrelationMetrics]:
        """Calculate correlation matrix for all assets."""
        try:
            if len(self.asset_universe) < 2:
                logger.warning("Insufficient assets for correlation analysis")
                return None
            
            # Use default window if not specified
            if window is None:
                window = self.lookback_period
            
            # Collect asset returns
            returns_data = {}
            asset_ids = list(self.asset_universe.keys())
            
            for asset_id in asset_ids:
                asset_data = self.asset_universe[asset_id]["data"]
                
                # Calculate log returns
                returns = np.log(asset_data / asset_data.shift(1)).dropna()
                
                # Use recent window
                if len(returns) > window:
                    returns = returns.tail(window)
                
                returns_data[asset_id] = returns
            
            # Create returns DataFrame
            returns_df = pd.DataFrame(returns_data)
            returns_df = returns_df.dropna()
            
            if len(returns_df) < self.min_samples:
                logger.warning("Insufficient overlapping data for correlation analysis")
                return None
            
            # Calculate correlation matrix
            correlation_matrix = returns_df.corr()
            
            # Convert to nested dict
            corr_dict = correlation_matrix.to_dict()
            
            # Calculate metrics
            asset_pairs = []
            correlations = []
            
            for i, asset1 in enumerate(asset_ids):
                for j, asset2 in enumerate(asset_ids):
                    if i < j:  # Avoid duplicates
                        pair = (asset1, asset2)
                        asset_pairs.append(pair)
                        correlations.append(corr_dict[asset1][asset2])
            
            # Calculate statistics
            avg_correlation = np.mean(correlations)
            max_correlation = np.max(correlations)
            min_correlation = np.min(correlations)
            
            # Calculate correlation trend (compare with previous)
            correlation_trend = 0.0
            if self.correlation_history:
                prev_avg = self.correlation_history[-1].average_correlation
                correlation_trend = (avg_correlation - prev_avg) / prev_avg if prev_avg != 0 else 0.0
            
            # Calculate diversification ratio
            n_assets = len(asset_ids)
            perfect_diversification = 1 / n_assets
            diversification_ratio = perfect_diversification / avg_correlation if avg_correlation > 0 else 1.0
            
            # Calculate concentration risk
            high_correlations = [c for c in correlations if abs(c) > self.correlation_threshold]
            concentration_risk = len(high_correlations) / len(correlations)
            
            # Calculate systemic risk (simplified)
            systemic_risk = avg_correlation * concentration_risk
            
            # Create metrics object
            metrics = CorrelationMetrics(
                timestamp=time.time(),
                asset_pairs=asset_pairs,
                correlation_matrix=corr_dict,
                average_correlation=avg_correlation,
                max_correlation=max_correlation,
                min_correlation=min_correlation,
                correlation_trend=correlation_trend,
                diversification_ratio=diversification_ratio,
                concentration_risk=concentration_risk,
                systemic_risk=systemic_risk,
                metadata={
                    "window": window,
                    "asset_count": n_assets,
                    "sample_count": len(returns_df)
                }
            )
            
            # Store results
            self.correlation_history.append(metrics)
            self.correlation_matrices.append(corr_dict)
            
            logger.info(f"Correlation analysis completed: {n_assets} assets, avg corr: {avg_correlation:.3f}")
            return metrics
            
        except Exception as e:
            logger.error(f"Failed to calculate correlations: {e}")
            return None
    
    async def calculate_rolling_correlations(self, window: int = 60, step: int = 1) -> List[CorrelationMetrics]:
        """Calculate rolling correlations over time."""
        try:
            if len(self.asset_universe) < 2:
                return []
            
            # Get the longest asset data
            max_length = max(len(asset["data"]) for asset in self.asset_universe.values())
            
            rolling_metrics = []
            
            # Calculate correlations for each window
            for start_idx in range(0, max_length - window + 1, step):
                end_idx = start_idx + window
                
                # Create temporary asset data for this window
                temp_assets = {}
                for asset_id, asset_info in self.asset_universe.items():
                    asset_data = asset_info["data"]
                    if len(asset_data) >= end_idx:
                        temp_assets[asset_id] = asset_data.iloc[start_idx:end_idx]
                
                if len(temp_assets) >= 2:
                    # Calculate correlations for this window
                    window_metrics = await self._calculate_window_correlations(temp_assets)
                    if window_metrics:
                        rolling_metrics.append(window_metrics)
            
            logger.info(f"Rolling correlation analysis completed: {len(rolling_metrics)} windows")
            return rolling_metrics
            
        except Exception as e:
            logger.error(f"Failed to calculate rolling correlations: {e}")
            return []
    
    async def _calculate_window_correlations(self, asset_data: Dict[str, pd.Series]) -> Optional[CorrelationMetrics]:
        """Calculate correlations for a specific window."""
        try:
            # Calculate returns
            returns_data = {}
            for asset_id, data in asset_data.items():
                returns = np.log(data / data.shift(1)).dropna()
                returns_data[asset_id] = returns
            
            # Create DataFrame
            returns_df = pd.DataFrame(returns_data)
            returns_df = returns_df.dropna()
            
            if len(returns_df) < 10:  # Minimum for meaningful correlation
                return None
            
            # Calculate correlation matrix
            correlation_matrix = returns_df.corr()
            corr_dict = correlation_matrix.to_dict()
            
            # Calculate metrics
            asset_ids = list(asset_data.keys())
            correlations = []
            
            for i, asset1 in enumerate(asset_ids):
                for j, asset2 in enumerate(asset_ids):
                    if i < j:
                        correlations.append(corr_dict[asset1][asset2])
            
            avg_correlation = np.mean(correlations)
            max_correlation = np.max(correlations)
            min_correlation = np.min(correlations)
            
            # Asset pairs
            asset_pairs = []
            for i, asset1 in enumerate(asset_ids):
                for j, asset2 in enumerate(asset_ids):
                    if i < j:
                        asset_pairs.append((asset1, asset2))
            
            metrics = CorrelationMetrics(
                timestamp=time.time(),
                asset_pairs=asset_pairs,
                correlation_matrix=corr_dict,
                average_correlation=avg_correlation,
                max_correlation=max_correlation,
                min_correlation=min_correlation,
                correlation_trend=0.0,
                diversification_ratio=0.0,
                concentration_risk=0.0,
                systemic_risk=0.0,
                metadata={"window_analysis": True}
            )
            
            return metrics
            
        except Exception as e:
            logger.error(f"Failed to calculate window correlations: {e}")
            return None
    
    async def detect_correlation_breakdown(self, threshold: float = 0.3) -> List[Tuple[str, str, float]]:
        """Detect correlation breakdown events."""
        try:
            if len(self.correlation_history) < 2:
                return []
            
            # Get recent correlations
            recent_corr = self.correlation_history[-1]
            previous_corr = self.correlation_history[-2]
            
            breakdowns = []
            
            for asset1, asset2 in recent_corr.asset_pairs:
                if asset1 in recent_corr.correlation_matrix and asset2 in recent_corr.correlation_matrix[asset1]:
                    current_corr = recent_corr.correlation_matrix[asset1][asset2]
                    
                    if asset1 in previous_corr.correlation_matrix and asset2 in previous_corr.correlation_matrix[asset1]:
                        previous_corr_val = previous_corr.correlation_matrix[asset1][asset2]
                        
                        # Check for breakdown
                        correlation_change = abs(current_corr - previous_corr_val)
                        if correlation_change > threshold:
                            breakdowns.append((asset1, asset2, correlation_change))
            
            # Sort by magnitude
            breakdowns.sort(key=lambda x: x[2], reverse=True)
            
            logger.info(f"Detected {len(breakdowns)} correlation breakdowns")
            return breakdowns
            
        except Exception as e:
            logger.error(f"Failed to detect correlation breakdown: {e}")
            return []
    
    async def calculate_portfolio_risk(self, weights: Dict[str, float]) -> Dict[str, float]:
        """Calculate portfolio risk metrics based on correlations."""
        try:
            if not self.correlation_history:
                return {"error": "No correlation data available"}
            
            # Get latest correlation matrix
            latest_corr = self.correlation_history[-1]
            corr_matrix = latest_corr.correlation_matrix
            
            # Convert weights to array
            asset_ids = list(weights.keys())
            weight_array = np.array([weights[asset_id] for asset_id in asset_ids])
            
            # Create correlation matrix as numpy array
            corr_array = np.zeros((len(asset_ids), len(asset_ids)))
            for i, asset1 in enumerate(asset_ids):
                for j, asset2 in enumerate(asset_ids):
                    if asset1 in corr_matrix and asset2 in corr_matrix[asset1]:
                        corr_array[i, j] = corr_matrix[asset1][asset2]
            
            # Calculate portfolio variance
            portfolio_variance = np.dot(weight_array, np.dot(corr_array, weight_array))
            portfolio_volatility = np.sqrt(portfolio_variance)
            
            # Calculate diversification benefit
            uncorrelated_volatility = np.sqrt(np.sum(weight_array ** 2))
            diversification_benefit = uncorrelated_volatility - portfolio_volatility
            
            # Calculate concentration risk
            concentration_risk = np.sum(weight_array ** 2)
            
            return {
                "portfolio_volatility": portfolio_volatility,
                "portfolio_variance": portfolio_variance,
                "diversification_benefit": diversification_benefit,
                "concentration_risk": concentration_risk,
                "asset_count": len(asset_ids),
                "average_correlation": latest_corr.average_correlation
            }
            
        except Exception as e:
            logger.error(f"Failed to calculate portfolio risk: {e}")
            return {"error": str(e)}
    
    async def find_diversification_opportunities(self) -> List[Tuple[str, str, float]]:
        """Find assets with low correlation for diversification."""
        try:
            if not self.correlation_history:
                return []
            
            # Get latest correlation matrix
            latest_corr = self.correlation_history[-1]
            corr_matrix = latest_corr.correlation_matrix
            
            # Find low correlation pairs
            opportunities = []
            
            for asset1, asset2 in latest_corr.asset_pairs:
                if asset1 in corr_matrix and asset2 in corr_matrix[asset1]:
                    correlation = corr_matrix[asset1][asset2]
                    
                    # Low correlation opportunity
                    if abs(correlation) < 0.2:
                        opportunities.append((asset1, asset2, abs(correlation)))
            
            # Sort by correlation (ascending)
            opportunities.sort(key=lambda x: x[2])
            
            logger.info(f"Found {len(opportunities)} diversification opportunities")
            return opportunities
            
        except Exception as e:
            logger.error(f"Failed to find diversification opportunities: {e}")
            return []
    
    def get_correlation_summary(self) -> Dict[str, Any]:
        """Get comprehensive correlation analysis summary."""
        if not self.correlation_history:
            return {"status": "no_data"}
        
        # Recent correlations
        recent_correlations = list(self.correlation_history)[-100:]
        
        # Asset universe
        asset_count = len(self.asset_universe)
        
        # Average statistics
        avg_correlations = [c.average_correlation for c in recent_correlations]
        avg_correlation = np.mean(avg_correlations)
        
        # Correlation trend
        if len(recent_correlations) > 1:
            latest_avg = recent_correlations[-1].average_correlation
            previous_avg = recent_correlations[-2].average_correlation
            correlation_trend = (latest_avg - previous_avg) / previous_avg if previous_avg != 0 else 0
        else:
            correlation_trend = 0.0
        
        # Risk metrics
        avg_systemic_risk = np.mean([c.systemic_risk for c in recent_correlations])
        avg_concentration_risk = np.mean([c.concentration_risk for c in recent_correlations])
        
        return {
            "total_analyses": len(self.correlation_history),
            "recent_analyses": len(recent_correlations),
            "asset_count": asset_count,
            "average_correlation": avg_correlation,
            "correlation_trend": correlation_trend,
            "risk_metrics": {
                "systemic_risk": avg_systemic_risk,
                "concentration_risk": avg_concentration_risk
            },
            "correlation_matrices": len(self.correlation_matrices),
            "us_compliance": self.us_compliance
        }
    
    def get_correlation_history(self, limit: int = 100) -> List[CorrelationMetrics]:
        """Get correlation analysis history."""
        return list(self.correlation_history)[-limit:]
    
    def get_asset_universe(self) -> Dict[str, Dict[str, Any]]:
        """Get current asset universe."""
        return {
            asset_id: {
                "metadata": info["metadata"],
                "added_timestamp": info["added_timestamp"],
                "data_length": len(info["data"])
            }
            for asset_id, info in self.asset_universe.items()
        }
    
    def update_config(self, new_config: Dict[str, Any]):
        """Update correlation analysis configuration."""
        self.config.update(new_config)
        
        # Update specific parameters
        if "lookback_period" in new_config:
            self.lookback_period = new_config["lookback_period"]
        if "min_samples" in new_config:
            self.min_samples = new_config["min_samples"]
        if "correlation_threshold" in new_config:
            self.correlation_threshold = new_config["correlation_threshold"]
        
        logger.info("Correlation analysis configuration updated")
