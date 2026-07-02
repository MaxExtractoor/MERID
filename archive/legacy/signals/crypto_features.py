"""
Crypto Feature Processor

Computes fear & greed scores, volume anomalies, and other crypto-specific features
from live price feed data and stores them in the unified signal system.
"""

from __future__ import annotations

import statistics
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from utils.logger import get_logger

logger = get_logger("crypto.feature_processor")


# Lazy import to avoid circular dependency
def _get_live_price_feed():
    from data.live_price_feed import get_live_price_feed, PriceData
    return get_live_price_feed(), PriceData


def _get_swarm_eligible():
    from data.asset_universe import get_swarm_eligible
    return get_swarm_eligible()


def _get_unified_signal_manager():
    from merid.signals.unified_manager import get_unified_signal_manager
    return get_unified_signal_manager()


@dataclass
class VolumeMetrics:
    """Volume analysis metrics"""
    current_volume: float
    volume_z_score: float
    volume_percentile: float
    volume_trend: str  # "increasing", "decreasing", "stable"
    avg_volume_7d: float
    avg_volume_30d: float


@dataclass
class FearGreedMetrics:
    """Fear & Greed analysis metrics"""
    fg_score: float  # 0-1, where 0=extreme fear, 0.5=neutral, 1=extreme greed
    fg_category: str  # "extreme_fear", "fear", "neutral", "greed", "extreme_greed"
    volume_weight: float  # How much volume influences the score
    price_momentum: float  # Price change contribution
    volatility_component: float  # Volatility contribution


@dataclass
class CryptoFeatures:
    """Complete crypto feature set for a symbol"""
    symbol: str
    price_data: PriceData
    volume_metrics: VolumeMetrics
    fear_greed_metrics: FearGreedMetrics
    timestamp: float
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for storage"""
        return {
            "symbol": self.symbol,
            "underlying": self._map_to_underlying(self.symbol),  # Add underlying mapping
            "price": self.price_data.price,
            "volume_24h": self.price_data.volume_24h,
            "change_24h_pct": self.price_data.change_24h_pct,
            "volume_z_score": self.volume_metrics.volume_z_score,
            "volume_percentile": self.volume_metrics.volume_percentile,
            "volume_trend": self.volume_metrics.volume_trend,
            "fear_greed_score": self.fear_greed_metrics.fg_score,
            "fear_greed_category": self.fear_greed_metrics.fg_category,
            "price_momentum": self.fear_greed_metrics.price_momentum,
            "volatility_component": self.fear_greed_metrics.volatility_component,
            "timestamp": self.timestamp,
        }
    
    def _map_to_underlying(self, symbol: str) -> str:
        """Map crypto symbol to underlying asset for Kalshi joins"""
        # Standardize symbol names for cross-domain joins
        symbol_map = {
            "BTC": "BTC",
            "ETH": "ETH", 
            "SOL": "SOL",
            "ADA": "ADA",
            "DOT": "DOT",
            "MATIC": "MATIC",
            "AVAX": "AVAX",
            "LINK": "LINK",
            # Handle common variations
            "BTC-USD": "BTC",
            "ETH-USD": "ETH",
            "WBTC": "BTC",
            "WETH": "ETH",
        }
        return symbol_map.get(symbol, symbol)


class CryptoFeatureProcessor:
    """Processes crypto data to generate fear & greed and volume features"""
    
    def __init__(self):
        # Defer imports until actually needed to avoid circular dependencies
        self._unified_manager = None
        self._price_feed = None
        self._volume_history: Dict[str, List[float]] = {}
        self._price_history: Dict[str, List[float]] = {}
        self._max_history = 30  # Keep up to 30 samples (not strictly daily - depends on processing frequency)
        # Note: volume_z and fg_score are "last N samples" metrics, not strictly daily bars
    
    def _ensure_initialized(self):
        """Ensure lazy imports are loaded"""
        if self._unified_manager is None:
            self._unified_manager = _get_unified_signal_manager()
            self._price_feed = _get_live_price_feed()[0]
        
    def process_all_crypto_features(self) -> int:
        """Process features for all crypto assets"""
        self._ensure_initialized()  # Ensure lazy imports are loaded
        processed_count = 0
        
        try:
            # Get all eligible crypto assets
            assets = _get_swarm_eligible()
            crypto_assets = [a for a in assets if a.category == "crypto"]
            
            # Get current price data
            price_data = self._price_feed.get_all_prices()
            
            for asset in crypto_assets:
                symbol = asset.symbol
                if symbol in price_data:
                    try:
                        features = self.process_symbol_features(symbol, price_data[symbol])
                        if features:
                            # Store as feature snapshot
                            success = self._unified_manager.store_feature_snapshot(
                                symbol=symbol,
                                domain="crypto",
                                features=features.to_dict(),
                                source="coingecko_live"
                            )
                            
                            # Also create fear & greed signal if significant
                            if abs(features.fear_greed_metrics.fg_score - 0.5) > 0.2:
                                self._create_fear_greed_signal(features)
                            
                            if success:
                                processed_count += 1
                                
                    except Exception as e:
                        logger.warning(f"Failed to process features for {symbol}: {e}")
                        continue
                        
        except Exception as e:
            logger.error(f"Failed to process crypto features: {e}")
            
        return processed_count
    
    def process_symbol_features(self, symbol: str, price_data: PriceData) -> Optional[CryptoFeatures]:
        """Process features for a single symbol"""
        try:
            # Update history
            self._update_history(symbol, price_data)
            
            # Calculate volume metrics
            volume_metrics = self._calculate_volume_metrics(symbol, price_data.volume_24h)
            
            # Calculate fear & greed metrics
            fg_metrics = self._calculate_fear_greed_metrics(symbol, price_data, volume_metrics)
            
            features = CryptoFeatures(
                symbol=symbol,
                price_data=price_data,
                volume_metrics=volume_metrics,
                fear_greed_metrics=fg_metrics,
                timestamp=time.time()
            )
            
            return features
            
        except Exception as e:
            logger.warning(f"Failed to process features for {symbol}: {e}")
            return None
    
    def _update_history(self, symbol: str, price_data: PriceData):
        """Update historical data for a symbol"""
        current_time = time.time()
        
        # Update volume history
        if symbol not in self._volume_history:
            self._volume_history[symbol] = []
        self._volume_history[symbol].append((current_time, price_data.volume_24h))
        
        # Update price history
        if symbol not in self._price_history:
            self._price_history[symbol] = []
        self._price_history[symbol].append((current_time, price_data.price))
        
        # Trim old data (keep last N samples based on processing frequency)
        cutoff_time = current_time - (30 * 24 * 3600)  # Approximate 30-day window for cleanup
        self._volume_history[symbol] = [
            (t, v) for t, v in self._volume_history[symbol] if t > cutoff_time
        ]
        self._price_history[symbol] = [
            (t, p) for t, p in self._price_history[symbol] if t > cutoff_time
        ]
    
    def _calculate_volume_metrics(self, symbol: str, current_volume: float) -> VolumeMetrics:
        """Calculate volume analysis metrics"""
        volumes = [v for _, v in self._volume_history.get(symbol, [])]
        
        if len(volumes) < 7:
            # Not enough history, use defaults
            return VolumeMetrics(
                current_volume=current_volume,
                volume_z_score=0.0,
                volume_percentile=0.5,
                volume_trend="stable",
                avg_volume_7d=current_volume,
                avg_volume_30d=current_volume
            )
        
        # Calculate averages
        avg_7d = statistics.mean(volumes[-7:]) if len(volumes) >= 7 else current_volume
        avg_30d = statistics.mean(volumes) if len(volumes) >= 30 else avg_7d
        
        # Calculate z-score
        if len(volumes) >= 10:
            mean_vol = statistics.mean(volumes)
            std_vol = statistics.stdev(volumes) if len(volumes) > 1 else 1.0
            z_score = (current_volume - mean_vol) / std_vol if std_vol > 0 else 0.0
        else:
            z_score = 0.0
        
        # Calculate percentile using rank-based approach
        if volumes:
            sorted_volumes = sorted(volumes)
            pos = sum(1 for v in sorted_volumes if v <= current_volume)
            percentile = pos / len(sorted_volumes)
        else:
            percentile = 0.5
        
        # Determine trend
        if len(volumes) >= 3:
            recent_avg = statistics.mean(volumes[-3:])
            older_avg = statistics.mean(volumes[-6:-3]) if len(volumes) >= 6 else recent_avg
            if recent_avg > older_avg * 1.1:
                trend = "increasing"
            elif recent_avg < older_avg * 0.9:
                trend = "decreasing"
            else:
                trend = "stable"
        else:
            trend = "stable"
        
        return VolumeMetrics(
            current_volume=current_volume,
            volume_z_score=z_score,
            volume_percentile=percentile,
            volume_trend=trend,
            avg_volume_7d=avg_7d,
            avg_volume_30d=avg_30d
        )
    
    def _calculate_fear_greed_metrics(
        self, 
        symbol: str, 
        price_data: PriceData, 
        volume_metrics: VolumeMetrics
    ) -> FearGreedMetrics:
        """Calculate fear & greed metrics"""
        
        # Base score from price momentum (24h change)
        price_change = price_data.change_24h_pct / 100.0  # Convert to decimal
        price_momentum = max(0, min(1, 0.5 + price_change))  # Normalize to 0-1
        
        # Volume influence
        volume_influence = max(0, min(1, volume_metrics.volume_z_score / 3.0 + 0.5))
        
        # Combine price and volume (40% price, 30% volume, 30% volatility)
        volatility_component = self._calculate_volatility_component(symbol)
        
        fg_score = (
            0.4 * price_momentum +
            0.3 * volume_influence +
            0.3 * volatility_component
        )
        
        # Clamp to 0-1
        fg_score = max(0, min(1, fg_score))
        
        # Determine category
        if fg_score < 0.2:
            category = "extreme_fear"
        elif fg_score < 0.4:
            category = "fear"
        elif fg_score < 0.6:
            category = "neutral"
        elif fg_score < 0.8:
            category = "greed"
        else:
            category = "extreme_greed"
        
        return FearGreedMetrics(
            fg_score=fg_score,
            fg_category=category,
            volume_weight=volume_influence,
            price_momentum=price_momentum,
            volatility_component=volatility_component
        )
    
    def _calculate_volatility_component(self, symbol: str) -> float:
        """Calculate volatility component for fear & greed"""
        prices = [p for _, p in self._price_history.get(symbol, [])]
        
        if len(prices) < 10:
            return 0.5  # Default to neutral
        
        # Calculate recent volatility (last 7 prices vs previous 7)
        if len(prices) >= 14:
            recent_prices = prices[-7:]
            older_prices = prices[-14:-7]
            
            recent_vol = statistics.stdev(recent_prices) / statistics.mean(recent_prices) if len(recent_prices) > 1 else 0
            older_vol = statistics.stdev(older_prices) / statistics.mean(older_prices) if len(older_prices) > 1 else 0
            
            # Higher recent volatility = more fear (lower score)
            vol_ratio = recent_vol / (older_vol + 0.001)  # Avoid division by zero
            volatility_score = 1.0 / (1.0 + vol_ratio)  # Invert so high vol = low score
        else:
            volatility_score = 0.5
        
        return max(0, min(1, volatility_score))
    
    def _create_fear_greed_signal(self, features: CryptoFeatures):
        """Create a fear & greed signal when significant"""
        try:
            underlying = features._map_to_underlying(features.symbol)
            
            success = self._unified_manager.create_fear_greed_signal(
                symbol=features.symbol,
                fg_score=features.fear_greed_metrics.fg_score,
                volume_z=features.volume_metrics.volume_z_score,
                features={
                    "underlying": underlying,  # Add underlying for cross-domain joins
                    "price": features.price_data.price,
                    "change_24h_pct": features.price_data.change_24h_pct,
                    "volume_24h": features.price_data.volume_24h,
                    "volume_trend": features.volume_metrics.volume_trend,
                    "fg_category": features.fear_greed_metrics.fg_category,
                    "volume_percentile": features.volume_metrics.volume_percentile,
                },
                source="coingecko_live"
            )
            
            if success:
                logger.info(f"Created fear/greed signal for {features.symbol} ({underlying}): {features.fear_greed_metrics.fg_category}")
                
        except Exception as e:
            logger.warning(f"Failed to create fear/greed signal for {features.symbol}: {e}")


# Singleton instance
_processor: Optional[CryptoFeatureProcessor] = None


def get_crypto_feature_processor() -> CryptoFeatureProcessor:
    """Get the singleton crypto feature processor"""
    global _processor
    if _processor is None:
        _processor = CryptoFeatureProcessor()
    return _processor


def run_crypto_feature_processing() -> int:
    """Run crypto feature processing and return count of processed symbols"""
    processor = get_crypto_feature_processor()
    return processor.process_all_crypto_features()
