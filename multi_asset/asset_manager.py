"""
Multi-Asset Manager for MERID Multi-Asset Expansion

Provides comprehensive multi-asset management with cross-asset
strategies and US-compliant configuration.

Features:
- Multi-asset data integration
- Asset class management
- Cross-asset correlation analysis
- Asset-specific risk models
- US-compliant asset management
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

logger = get_logger("multi_asset.asset_manager")

class AssetClass(Enum):
    """Asset class enumeration."""
    EQUITY = "equity"
    FIXED_INCOME = "fixed_income"
    COMMODITY = "commodity"
    CURRENCY = "currency"
    CRYPTO = "crypto"
    REAL_ESTATE = "real_estate"
    ALTERNATIVE = "alternative"

class AssetStatus(Enum):
    """Asset status enumeration."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    DELISTED = "delisted"

@dataclass
class AssetDefinition:
    """Asset definition for multi-asset management."""
    symbol: str
    name: str
    asset_class: AssetClass
    exchange: str
    currency: str
    sector: Optional[str] = None
    region: Optional[str] = None
    market_cap: Optional[float] = None
    trading_hours: Optional[Dict[str, str]] = None
    min_order_size: float = 1.0
    max_order_size: float = 1000000.0
    tick_size: float = 0.01
    multiplier: float = 1.0
    status: AssetStatus = AssetStatus.ACTIVE
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class AssetData:
    """Asset market data."""
    symbol: str
    timestamp: float
    price: float
    volume: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volatility: Optional[float] = None
    beta: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class AssetMetrics:
    """Asset performance metrics."""
    symbol: str
    asset_class: AssetClass
    return_1d: float
    return_1w: float
    return_1m: float
    return_ytd: float
    volatility_1m: float
    sharpe_ratio: float
    max_drawdown: float
    beta: float
    correlation_to_market: float
    liquidity_score: float
    risk_score: float
    timestamp: float
    metadata: Dict[str, Any] = field(default_factory=dict)

class AssetManager:
    """
    Comprehensive multi-asset management system for MERID.
    
    Provides multi-asset data integration, asset class management,
    and cross-asset analysis with US-compliant configuration.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Asset registry
        self.asset_registry: Dict[str, AssetDefinition] = {}
        
        # Asset data storage
        self.asset_data: Dict[str, deque] = {}  # symbol -> data deque
        self.asset_metrics: Dict[str, AssetMetrics] = {}
        
        # Asset class organization
        self.asset_classes: Dict[AssetClass, List[str]] = {
            asset_class: [] for asset_class in AssetClass
        }
        
        # Cross-asset correlations
        self.correlation_matrices: Dict[str, np.ndarray] = {}  # timeframe -> matrix
        self.correlation_cache: Dict[str, Dict[str, float]] = {}
        
        # Data management
        self.data_retention_period = config.get("data_retention_period", 252 * 24 * 60 * 60)  # 1 year in seconds
        self.max_data_points = config.get("max_data_points", 10000)
        
        # Asset class configurations
        self.asset_class_configs = {
            AssetClass.EQUITY: {
                "default_currency": "USD",
                "trading_hours": {"market_open": "09:30", "market_close": "16:00"},
                "settlement_days": 2
            },
            AssetClass.FIXED_INCOME: {
                "default_currency": "USD",
                "trading_hours": {"market_open": "08:00", "market_close": "17:00"},
                "settlement_days": 1
            },
            AssetClass.COMMODITY: {
                "default_currency": "USD",
                "trading_hours": {"market_open": "00:00", "market_close": "23:59"},
                "settlement_days": 2
            },
            AssetClass.CURRENCY: {
                "default_currency": "USD",
                "trading_hours": {"market_open": "00:00", "market_close": "23:59"},
                "settlement_days": 2
            },
            AssetClass.CRYPTO: {
                "default_currency": "USD",
                "trading_hours": {"market_open": "00:00", "market_close": "23:59"},
                "settlement_days": 0
            },
            AssetClass.REAL_ESTATE: {
                "default_currency": "USD",
                "trading_hours": {"market_open": "09:00", "market_close": "16:00"},
                "settlement_days": 3
            },
            AssetClass.ALTERNATIVE: {
                "default_currency": "USD",
                "trading_hours": {"market_open": "09:00", "market_close": "16:00"},
                "settlement_days": 2
            }
        }
        
        # US compliance settings
        self.us_compliance = config.get("us_compliance", {
            "asset_screening": True,
            "data_privacy": True,
            "trading_restrictions": True,
            "audit_logging": True
        })
        
        logger.info("AssetManager initialized")
    
    async def register_asset(self, asset: AssetDefinition) -> bool:
        """Register a new asset in the system."""
        try:
            # Validate asset definition
            if not self._validate_asset(asset):
                logger.error(f"Invalid asset definition: {asset.symbol}")
                return False
            
            # Check for existing asset
            if asset.symbol in self.asset_registry:
                logger.warning(f"Asset {asset.symbol} already registered, updating")
            
            # Register asset
            self.asset_registry[asset.symbol] = asset
            
            # Add to asset class
            if asset.symbol not in self.asset_classes[asset.asset_class]:
                self.asset_classes[asset.asset_class].append(asset.symbol)
            
            # Initialize data storage
            if asset.symbol not in self.asset_data:
                self.asset_data[asset.symbol] = deque(maxlen=self.max_data_points)
            
            # Apply asset class defaults if not specified
            self._apply_asset_class_defaults(asset)
            
            # Record for compliance
            if self.us_compliance.get("audit_logging", True):
                await self._record_asset_registration(asset)
            
            logger.info(f"Asset registered: {asset.symbol} ({asset.asset_class.value})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to register asset {asset.symbol}: {e}")
            return False
    
    def _validate_asset(self, asset: AssetDefinition) -> bool:
        """Validate asset definition."""
        try:
            # Basic validation
            if not asset.symbol or not asset.name:
                return False
            
            if not isinstance(asset.asset_class, AssetClass):
                return False
            
            if not asset.exchange or not asset.currency:
                return False
            
            # US compliance checks
            if self.us_compliance.get("asset_screening", True):
                if not self._screen_asset(asset):
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Asset validation error: {e}")
            return False
    
    def _screen_asset(self, asset: AssetDefinition) -> bool:
        """Screen asset for US compliance."""
        try:
            # In production, implement actual screening logic
            # For now, basic checks
            
            # Check for restricted exchanges
            restricted_exchanges = []
            if asset.exchange in restricted_exchanges:
                return False
            
            # Check for restricted regions
            restricted_regions = []
            if asset.region and asset.region in restricted_regions:
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Asset screening error: {e}")
            return False
    
    def _apply_asset_class_defaults(self, asset: AssetDefinition):
        """Apply asset class defaults to asset."""
        try:
            class_config = self.asset_class_configs.get(asset.asset_class, {})
            
            # Apply trading hours if not specified
            if not asset.trading_hours and "trading_hours" in class_config:
                asset.trading_hours = class_config["trading_hours"]
            
            # Apply other defaults as needed
            # In production, apply more comprehensive defaults
            
        except Exception as e:
            logger.error(f"Failed to apply asset class defaults: {e}")
    
    async def update_asset_data(self, data: AssetData) -> bool:
        """Update asset market data."""
        try:
            # Validate asset exists
            if data.symbol not in self.asset_registry:
                logger.error(f"Asset {data.symbol} not registered")
                return False
            
            # Validate data
            if not self._validate_asset_data(data):
                logger.error(f"Invalid asset data for {data.symbol}")
                return False
            
            # Store data
            self.asset_data[data.symbol].append(data)
            
            # Clean old data
            self._clean_old_data(data.symbol)
            
            # Update metrics if enough data
            if len(self.asset_data[data.symbol]) >= 50:  # Minimum for metrics
                await self._update_asset_metrics(data.symbol)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to update asset data {data.symbol}: {e}")
            return False
    
    def _validate_asset_data(self, data: AssetData) -> bool:
        """Validate asset market data."""
        try:
            # Basic validation
            if not data.symbol or data.price <= 0:
                return False
            
            if data.timestamp <= 0:
                return False
            
            if data.volume < 0:
                return False
            
            # Validate bid/ask spread if available
            if data.bid and data.ask:
                if data.bid >= data.ask or data.bid <= 0 or data.ask <= 0:
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Asset data validation error: {e}")
            return False
    
    def _clean_old_data(self, symbol: str):
        """Clean old data beyond retention period."""
        try:
            if symbol not in self.asset_data:
                return
            
            data_queue = self.asset_data[symbol]
            current_time = time.time()
            
            # Remove old data
            while data_queue and (current_time - data_queue[0].timestamp) > self.data_retention_period:
                data_queue.popleft()
            
        except Exception as e:
            logger.error(f"Failed to clean old data for {symbol}: {e}")
    
    async def _update_asset_metrics(self, symbol: str):
        """Update asset performance metrics."""
        try:
            if symbol not in self.asset_data or len(self.asset_data[symbol]) < 50:
                return
            
            data_points = list(self.asset_data[symbol])
            asset_def = self.asset_registry[symbol]
            
            # Calculate returns
            prices = [dp.price for dp in data_points]
            returns = np.diff(np.log(prices))
            
            # Calculate different period returns
            current_price = prices[-1]
            
            # 1-day return
            return_1d = (prices[-1] - prices[-2]) / prices[-2] if len(prices) >= 2 else 0
            
            # 1-week return (assuming daily data)
            return_1w = (prices[-1] - prices[-7]) / prices[-7] if len(prices) >= 7 else 0
            
            # 1-month return (assuming daily data)
            return_1m = (prices[-1] - prices[-30]) / prices[-30] if len(prices) >= 30 else 0
            
            # YTD return (simplified)
            return_ytd = return_1m  # Simplified
            
            # Calculate volatility (1-month)
            volatility_1m = np.std(returns[-30:]) * np.sqrt(252) if len(returns) >= 30 else 0
            
            # Calculate Sharpe ratio (simplified)
            risk_free_rate = 0.02
            sharpe_ratio = (return_1m - risk_free_rate) / volatility_1m if volatility_1m > 0 else 0
            
            # Calculate max drawdown (simplified)
            peak = np.maximum.accumulate(prices)
            drawdown = (peak - prices) / peak
            max_drawdown = np.max(drawdown)
            
            # Calculate beta (simplified - would need market data)
            beta = 1.0  # Default
            
            # Calculate correlation to market (simplified)
            correlation_to_market = 0.5  # Default
            
            # Calculate liquidity score
            avg_volume = np.mean([dp.volume for dp in data_points[-30:]]) if len(data_points) >= 30 else 0
            liquidity_score = min(1.0, avg_volume / 1000000)  # Normalized by 1M volume
            
            # Calculate risk score
            risk_score = min(1.0, volatility_1m / 0.5)  # Normalized by 50% vol
            
            # Create metrics
            metrics = AssetMetrics(
                symbol=symbol,
                asset_class=asset_def.asset_class,
                return_1d=return_1d,
                return_1w=return_1w,
                return_1m=return_1m,
                return_ytd=return_ytd,
                volatility_1m=volatility_1m,
                sharpe_ratio=sharpe_ratio,
                max_drawdown=max_drawdown,
                beta=beta,
                correlation_to_market=correlation_to_market,
                liquidity_score=liquidity_score,
                risk_score=risk_score,
                timestamp=time.time()
            )
            
            self.asset_metrics[symbol] = metrics
            
        except Exception as e:
            logger.error(f"Failed to update asset metrics for {symbol}: {e}")
    
    async def calculate_cross_asset_correlations(self, timeframe: str = "daily") -> Dict[str, Dict[str, float]]:
        """Calculate cross-asset correlations."""
        try:
            # Get active assets with sufficient data
            active_assets = [
                symbol for symbol in self.asset_registry.keys()
                if (self.asset_registry[symbol].status == AssetStatus.ACTIVE and
                    len(self.asset_data.get(symbol, [])) >= 50)
            ]
            
            if len(active_assets) < 2:
                logger.warning("Insufficient assets for correlation calculation")
                return {}
            
            # Collect price data
            price_data = {}
            min_length = float('inf')
            
            for symbol in active_assets:
                data_points = list(self.asset_data[symbol])
                prices = [dp.price for dp in data_points]
                price_data[symbol] = prices
                min_length = min(min_length, len(prices))
            
            # Align data lengths
            aligned_prices = {}
            for symbol, prices in price_data.items():
                aligned_prices[symbol] = prices[-min_length:]
            
            # Calculate correlation matrix
            symbols = list(aligned_prices.keys())
            n_assets = len(symbols)
            
            # Create price matrix
            price_matrix = np.column_stack([aligned_prices[symbol] for symbol in symbols])
            
            # Calculate returns
            returns = np.diff(np.log(price_matrix), axis=0)
            
            # Calculate correlation matrix
            correlation_matrix = np.corrcoef(returns.T)
            
            # Convert to dictionary
            correlation_dict = {}
            for i, symbol1 in enumerate(symbols):
                correlation_dict[symbol1] = {}
                for j, symbol2 in enumerate(symbols):
                    correlation_dict[symbol1][symbol2] = correlation_matrix[i, j]
            
            # Store correlation matrix
            self.correlation_matrices[timeframe] = correlation_matrix
            self.correlation_cache[timeframe] = correlation_dict
            
            logger.info(f"Calculated cross-asset correlations: {n_assets} assets")
            return correlation_dict
            
        except Exception as e:
            logger.error(f"Failed to calculate cross-asset correlations: {e}")
            return {}
    
    async def get_asset_class_performance(self, asset_class: AssetClass) -> Dict[str, Any]:
        """Get asset class performance summary."""
        try:
            assets_in_class = self.asset_classes.get(asset_class, [])
            
            if not assets_in_class:
                return {"status": "no_assets"}
            
            # Collect metrics for assets in class
            class_metrics = []
            for symbol in assets_in_class:
                if symbol in self.asset_metrics:
                    class_metrics.append(self.asset_metrics[symbol])
            
            if not class_metrics:
                return {"status": "no_metrics"}
            
            # Calculate class-level metrics
            returns_1d = [m.return_1d for m in class_metrics]
            returns_1m = [m.return_1m for m in class_metrics]
            volatilities = [m.volatility_1m for m in class_metrics]
            sharpe_ratios = [m.sharpe_ratio for m in class_metrics]
            
            return {
                "asset_class": asset_class.value,
                "asset_count": len(assets_in_class),
                "metrics_count": len(class_metrics),
                "performance": {
                    "avg_return_1d": np.mean(returns_1d),
                    "avg_return_1m": np.mean(returns_1m),
                    "avg_volatility": np.mean(volatilities),
                    "avg_sharpe_ratio": np.mean(sharpe_ratios),
                    "best_performer": max(class_metrics, key=lambda m: m.return_1m).symbol,
                    "worst_performer": min(class_metrics, key=lambda m: m.return_1m).symbol
                },
                "risk_metrics": {
                    "avg_risk_score": np.mean([m.risk_score for m in class_metrics]),
                    "avg_liquidity_score": np.mean([m.liquidity_score for m in class_metrics]),
                    "avg_max_drawdown": np.mean([m.max_drawdown for m in class_metrics])
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to get asset class performance: {e}")
            return {"status": "error", "error": str(e)}
    
    async def get_multi_asset_summary(self) -> Dict[str, Any]:
        """Get comprehensive multi-asset summary."""
        try:
            # Asset class distribution
            asset_class_counts = {}
            total_assets = 0
            
            for asset_class, symbols in self.asset_classes.items():
                active_symbols = [
                    s for s in symbols 
                    if self.asset_registry.get(s, AssetStatus.INACTIVE).status == AssetStatus.ACTIVE
                ]
                asset_class_counts[asset_class.value] = len(active_symbols)
                total_assets += len(active_symbols)
            
            # Performance by asset class
            class_performance = {}
            for asset_class in AssetClass:
                performance = await self.get_asset_class_performance(asset_class)
                if "status" not in performance:
                    class_performance[asset_class.value] = performance
            
            # Correlation summary
            correlation_summary = {}
            if self.correlation_cache:
                for timeframe, correlations in self.correlation_cache.items():
                    all_correlations = []
                    for symbol1, corr_dict in correlations.items():
                        for symbol2, corr in corr_dict.items():
                            if symbol1 != symbol2:
                                all_correlations.append(abs(corr))
                    
                    correlation_summary[timeframe] = {
                        "avg_correlation": np.mean(all_correlations) if all_correlations else 0,
                        "max_correlation": np.max(all_correlations) if all_correlations else 0,
                        "min_correlation": np.min(all_correlations) if all_correlations else 0
                    }
            
            return {
                "total_assets": total_assets,
                "asset_class_distribution": asset_class_counts,
                "class_performance": class_performance,
                "correlation_summary": correlation_summary,
                "data_points": {
                    symbol: len(data) for symbol, data in self.asset_data.items()
                },
                "us_compliance": self.us_compliance
            }
            
        except Exception as e:
            logger.error(f"Failed to get multi-asset summary: {e}")
            return {"status": "error", "error": str(e)}
    
    def get_assets_by_class(self, asset_class: AssetClass) -> List[str]:
        """Get assets by asset class."""
        return self.asset_classes.get(asset_class, []).copy()
    
    def get_asset_definition(self, symbol: str) -> Optional[AssetDefinition]:
        """Get asset definition."""
        return self.asset_registry.get(symbol)
    
    def get_asset_metrics(self, symbol: str) -> Optional[AssetMetrics]:
        """Get asset metrics."""
        return self.asset_metrics.get(symbol)
    
    def get_asset_data(self, symbol: str, limit: int = 100) -> List[AssetData]:
        """Get recent asset data."""
        if symbol not in self.asset_data:
            return []
        
        return list(self.asset_data[symbol])[-limit:]
    
    def get_correlation_matrix(self, timeframe: str = "daily") -> Optional[np.ndarray]:
        """Get correlation matrix."""
        return self.correlation_matrices.get(timeframe)
    
    def get_correlations(self, symbol: str, timeframe: str = "daily") -> Dict[str, float]:
        """Get correlations for a specific symbol."""
        if timeframe not in self.correlation_cache:
            return {}
        
        return self.correlation_cache[timeframe].get(symbol, {})
    
    async def _record_asset_registration(self, asset: AssetDefinition):
        """Record asset registration for compliance."""
        if not self.us_compliance.get("audit_logging", True):
            return
        
        audit_entry = {
            "action": "asset_registration",
            "symbol": asset.symbol,
            "name": asset.name,
            "asset_class": asset.asset_class.value,
            "exchange": asset.exchange,
            "timestamp": time.time(),
            "user": "system"  # In production, get actual user
        }
        
        # In production, store in audit database
        logger.debug(f"Asset registration audit entry: {audit_entry}")
    
    def update_asset_status(self, symbol: str, status: AssetStatus) -> bool:
        """Update asset status."""
        try:
            if symbol not in self.asset_registry:
                logger.error(f"Asset {symbol} not found")
                return False
            
            self.asset_registry[symbol].status = status
            logger.info(f"Updated {symbol} status to {status.value}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update asset status: {e}")
            return False
    
    def remove_asset(self, symbol: str) -> bool:
        """Remove asset from system."""
        try:
            if symbol not in self.asset_registry:
                logger.error(f"Asset {symbol} not found")
                return False
            
            # Remove from registry
            asset = self.asset_registry[symbol]
            del self.asset_registry[symbol]
            
            # Remove from asset class
            if symbol in self.asset_classes[asset.asset_class]:
                self.asset_classes[asset.asset_class].remove(symbol)
            
            # Remove data
            if symbol in self.asset_data:
                del self.asset_data[symbol]
            
            # Remove metrics
            if symbol in self.asset_metrics:
                del self.asset_metrics[symbol]
            
            logger.info(f"Removed asset {symbol} from system")
            return True
            
        except Exception as e:
            logger.error(f"Failed to remove asset {symbol}: {e}")
            return False
    
    def update_config(self, new_config: Dict[str, Any]):
        """Update asset manager configuration."""
        self.config.update(new_config)
        
        # Update specific parameters
        if "data_retention_period" in new_config:
            self.data_retention_period = new_config["data_retention_period"]
        if "max_data_points" in new_config:
            self.max_data_points = new_config["max_data_points"]
        
        logger.info("Asset manager configuration updated")
