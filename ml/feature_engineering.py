"""
Feature Engineering for MERID ML Models

Provides comprehensive feature extraction, selection, and transformation
for cryptocurrency trading and market analysis.

Features:
- Technical indicators calculation
- Market microstructure features
- Sentiment analysis features
- Time series feature extraction
- Feature selection and importance
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

logger = get_logger("ml.feature_engineering")

@dataclass
class FeatureConfig:
    """Feature engineering configuration."""
    technical_indicators: bool = True
    market_microstructure: bool = True
    sentiment_features: bool = True
    time_series_features: bool = True
    volume_features: bool = True
    volatility_features: bool = True
    price_features: bool = True
    
    # Feature selection
    feature_selection: bool = True
    importance_threshold: float = 0.01
    max_features: int = 50
    
    # Time windows
    short_window: int = 5
    medium_window: int = 20
    long_window: int = 50
    
    # Sentiment weights
    news_weight: float = 0.4
    social_weight: float = 0.3
    onchain_weight: float = 0.3

@dataclass
class FeatureSet:
    """Set of engineered features."""
    features: pd.DataFrame
    feature_names: List[str]
    feature_types: Dict[str, str]
    importance_scores: Dict[str, float] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_time: float = field(default_factory=time.time)

class TechnicalIndicators:
    """Technical indicators calculation."""
    
    @staticmethod
    def rsi(prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculate Relative Strength Index."""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    @staticmethod
    def macd(prices: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, pd.Series]:
        """Calculate MACD indicator."""
        exp_fast = prices.ewm(span=fast).mean()
        exp_slow = prices.ewm(span=slow).mean()
        macd_line = exp_fast - exp_slow
        signal_line = macd_line.ewm(span=signal).mean()
        histogram = macd_line - signal_line
        
        return {
            'macd': macd_line,
            'signal': signal_line,
            'histogram': histogram
        }
    
    @staticmethod
    def bollinger_bands(prices: pd.Series, period: int = 20, std_dev: float = 2) -> Dict[str, pd.Series]:
        """Calculate Bollinger Bands."""
        sma = prices.rolling(window=period).mean()
        std = prices.rolling(window=period).std()
        upper_band = sma + (std * std_dev)
        lower_band = sma - (std * std_dev)
        
        return {
            'upper': upper_band,
            'middle': sma,
            'lower': lower_band,
            'bandwidth': (upper_band - lower_band) / sma,
            'position': (prices - lower_band) / (upper_band - lower_band)
        }
    
    @staticmethod
    def stochastic_oscillator(high: pd.Series, low: pd.Series, close: pd.Series, 
                             k_period: int = 14, d_period: int = 3) -> Dict[str, pd.Series]:
        """Calculate Stochastic Oscillator."""
        lowest_low = low.rolling(window=k_period).min()
        highest_high = high.rolling(window=k_period).max()
        k_percent = 100 * (close - lowest_low) / (highest_high - lowest_low)
        d_percent = k_percent.rolling(window=d_period).mean()
        
        return {
            'k': k_percent,
            'd': d_percent
        }
    
    @staticmethod
    def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        """Calculate Average True Range."""
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        return atr
    
    @staticmethod
    def williams_r(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        """Calculate Williams %R."""
        highest_high = high.rolling(window=period).max()
        lowest_low = low.rolling(window=period).min()
        williams_r = -100 * (highest_high - close) / (highest_high - lowest_low)
        return williams_r

class MarketMicrostructureFeatures:
    """Market microstructure feature extraction."""
    
    @staticmethod
    def order_book_imbalance(bids: pd.Series, asks: pd.Series, depth: int = 10) -> pd.Series:
        """Calculate order book imbalance."""
        bid_volume = bids.iloc[:depth].sum()
        ask_volume = asks.iloc[:depth].sum()
        imbalance = (bid_volume - ask_volume) / (bid_volume + ask_volume)
        return imbalance
    
    @staticmethod
    def price_impact(trades: pd.DataFrame, window: int = 100) -> pd.Series:
        """Calculate price impact of trades."""
        if len(trades) < window:
            return pd.Series([0.0] * len(trades))
        
        price_changes = trades['price'].pct_change()
        volumes = trades['volume']
        
        # Calculate correlation between price changes and volumes
        impact = price_changes.rolling(window=window).corr(volumes)
        return impact
    
    @staticmethod
    def bid_ask_spread(bids: pd.Series, asks: pd.Series) -> pd.Series:
        """Calculate bid-ask spread."""
        spread = (asks - bids) / ((bids + asks) / 2)
        return spread
    
    @staticmethod
    def market_depth(bids: pd.Series, asks: pd.Series, levels: int = 5) -> Dict[str, pd.Series]:
        """Calculate market depth at different levels."""
        depth_features = {}
        
        for level in range(1, levels + 1):
            bid_depth = bids.iloc[:level].sum()
            ask_depth = asks.iloc[:level].sum()
            total_depth = bid_depth + ask_depth
            
            depth_features[f'bid_depth_{level}'] = bid_depth
            depth_features[f'ask_depth_{level}'] = ask_depth
            depth_features[f'total_depth_{level}'] = total_depth
            depth_features[f'depth_imbalance_{level}'] = (bid_depth - ask_depth) / total_depth
        
        return depth_features
    
    @staticmethod
    def trade_intensity(trades: pd.DataFrame, window: int = 60) -> pd.Series:
        """Calculate trade intensity (trades per second)."""
        if 'timestamp' not in trades.columns:
            return pd.Series([0.0] * len(trades))
        
        trades['time_diff'] = trades['timestamp'].diff()
        intensity = 1 / trades['time_diff'].rolling(window=window).mean()
        return intensity

class SentimentFeatures:
    """Sentiment analysis feature extraction."""
    
    @staticmethod
    def aggregate_sentiment(news_sentiment: pd.Series, social_sentiment: pd.Series, 
                           onchain_sentiment: pd.Series, weights: Dict[str, float]) -> pd.Series:
        """Aggregate multiple sentiment sources."""
        weighted_news = news_sentiment * weights.get('news', 0.4)
        weighted_social = social_sentiment * weights.get('social', 0.3)
        weighted_onchain = onchain_sentiment * weights.get('onchain', 0.3)
        
        return weighted_news + weighted_social + weighted_onchain
    
    @staticmethod
    def sentiment_momentum(sentiment: pd.Series, periods: List[int] = [5, 10, 20]) -> Dict[str, pd.Series]:
        """Calculate sentiment momentum over different periods."""
        momentum_features = {}
        
        for period in periods:
            momentum = sentiment.rolling(window=period).mean()
            momentum_features[f'sentiment_momentum_{period}'] = momentum
        
        return momentum_features
    
    @staticmethod
    def sentiment_volatility(sentiment: pd.Series, window: int = 20) -> pd.Series:
        """Calculate sentiment volatility."""
        return sentiment.rolling(window=window).std()
    
    @staticmethod
    def sentiment_trend_strength(sentiment: pd.Series, window: int = 14) -> pd.Series:
        """Calculate sentiment trend strength using linear regression slope."""
        def linear_regression_slope(series):
            if len(series) < 2:
                return 0.0
            x = np.arange(len(series))
            slope = np.polyfit(x, series, 1)[0]
            return slope
        
        return sentiment.rolling(window=window).apply(linear_regression_slope)

class TimeSeriesFeatures:
    """Time series feature extraction."""
    
    @staticmethod
    def lag_features(series: pd.Series, lags: List[int] = [1, 2, 3, 5, 10]) -> Dict[str, pd.Series]:
        """Create lagged features."""
        lag_features = {}
        
        for lag in lags:
            lag_features[f'lag_{lag}'] = series.shift(lag)
        
        return lag_features
    
    @staticmethod
    def rolling_features(series: pd.Series, windows: List[int] = [5, 10, 20, 50]) -> Dict[str, pd.Series]:
        """Create rolling statistical features."""
        rolling_features = {}
        
        for window in windows:
            rolling_features[f'rolling_mean_{window}'] = series.rolling(window=window).mean()
            rolling_features[f'rolling_std_{window}'] = series.rolling(window=window).std()
            rolling_features[f'rolling_min_{window}'] = series.rolling(window=window).min()
            rolling_features[f'rolling_max_{window}'] = series.rolling(window=window).max()
            rolling_features[f'rolling_median_{window}'] = series.rolling(window=window).median()
        
        return rolling_features
    
    @staticmethod
    def difference_features(series: pd.Series, periods: List[int] = [1, 5, 10]) -> Dict[str, pd.Series]:
        """Create difference features."""
        diff_features = {}
        
        for period in periods:
            diff_features[f'diff_{period}'] = series.diff(periods=period)
            diff_features[f'pct_change_{period}'] = series.pct_change(periods=period)
        
        return diff_features
    
    @staticmethod
    def seasonal_features(timestamps: pd.Series) -> Dict[str, pd.Series]:
        """Create seasonal/time-based features."""
        timestamps = pd.to_datetime(timestamps)
        
        return {
            'hour': timestamps.dt.hour,
            'day_of_week': timestamps.dt.dayofweek,
            'day_of_month': timestamps.dt.day,
            'month': timestamps.dt.month,
            'quarter': timestamps.dt.quarter,
            'is_weekend': (timestamps.dt.dayofweek >= 5).astype(int),
            'is_trading_hours': ((timestamps.dt.hour >= 9) & (timestamps.dt.hour <= 16)).astype(int)
        }

class FeatureEngineering:
    """
    Comprehensive feature engineering system for MERID.
    
    Provides automated feature extraction, selection, and transformation
    for machine learning models.
    """
    
    def __init__(self, config: FeatureConfig):
        self.config = config
        
        # Feature extractors
        self.technical_indicators = TechnicalIndicators()
        self.market_microstructure = MarketMicrostructureFeatures()
        self.sentiment_features = SentimentFeatures()
        self.time_series_features = TimeSeriesFeatures()
        
        # Feature storage
        self.feature_history: deque = deque(maxlen=100)
        self.importance_scores: Dict[str, float] = {}
        
        logger.info("FeatureEngineering initialized")
    
    async def extract_features(self, market_data: pd.DataFrame, 
                              sentiment_data: Optional[Dict[str, pd.Series]] = None) -> FeatureSet:
        """Extract comprehensive features from market data."""
        try:
            all_features = {}
            feature_types = {}
            
            # Price features
            if self.config.price_features and 'price' in market_data.columns:
                price_features = self._extract_price_features(market_data)
                all_features.update(price_features)
                feature_types.update({k: 'price' for k in price_features.keys()})
            
            # Volume features
            if self.config.volume_features and 'volume' in market_data.columns:
                volume_features = self._extract_volume_features(market_data)
                all_features.update(volume_features)
                feature_types.update({k: 'volume' for k in volume_features.keys()})
            
            # Technical indicators
            if self.config.technical_indicators:
                technical_features = self._extract_technical_features(market_data)
                all_features.update(technical_features)
                feature_types.update({k: 'technical' for k in technical_features.keys()})
            
            # Market microstructure features
            if self.config.market_microstructure:
                microstructure_features = self._extract_microstructure_features(market_data)
                all_features.update(microstructure_features)
                feature_types.update({k: 'microstructure' for k in microstructure_features.keys()})
            
            # Sentiment features
            if self.config.sentiment_features and sentiment_data:
                sentiment_features = self._extract_sentiment_features(sentiment_data)
                all_features.update(sentiment_features)
                feature_types.update({k: 'sentiment' for k in sentiment_features.keys()})
            
            # Time series features
            if self.config.time_series_features:
                ts_features = self._extract_time_series_features(market_data)
                all_features.update(ts_features)
                feature_types.update({k: 'timeseries' for k in ts_features.keys()})
            
            # Volatility features
            if self.config.volatility_features:
                volatility_features = self._extract_volatility_features(market_data)
                all_features.update(volatility_features)
                feature_types.update({k: 'volatility' for k in volatility_features.keys()})
            
            # Create feature DataFrame
            features_df = pd.DataFrame(all_features)
            
            # Handle missing values
            features_df = self._handle_missing_values(features_df)
            
            # Feature selection
            if self.config.feature_selection:
                features_df = self._select_features(features_df)
            
            # Create feature set
            feature_set = FeatureSet(
                features=features_df,
                feature_names=list(features_df.columns),
                feature_types=feature_types,
                importance_scores=self.importance_scores,
                metadata={
                    'total_features': len(features_df.columns),
                    'missing_values': features_df.isnull().sum().sum(),
                    'extraction_time': time.time()
                }
            )
            
            # Store feature set
            self.feature_history.append(feature_set)
            
            logger.info(f"Extracted {len(features_df.columns)} features")
            return feature_set
            
        except Exception as e:
            logger.error(f"Failed to extract features: {e}")
            raise
    
    def _extract_price_features(self, data: pd.DataFrame) -> Dict[str, pd.Series]:
        """Extract price-related features."""
        features = {}
        price = data['price']
        
        # Price changes
        features['price_change_1h'] = price.pct_change(periods=1)
        features['price_change_4h'] = price.pct_change(periods=4)
        features['price_change_24h'] = price.pct_change(periods=24)
        
        # Moving averages
        features['price_ma_5'] = price.rolling(window=self.config.short_window).mean()
        features['price_ma_20'] = price.rolling(window=self.config.medium_window).mean()
        features['price_ma_50'] = price.rolling(window=self.config.long_window).mean()
        
        # Price relative to moving averages
        features['price_vs_ma5'] = price / features['price_ma_5']
        features['price_vs_ma20'] = price / features['price_ma_20']
        features['price_vs_ma50'] = price / features['price_ma_50']
        
        # Price momentum
        features['price_momentum_5'] = price - price.shift(self.config.short_window)
        features['price_momentum_20'] = price - price.shift(self.config.medium_window)
        
        return features
    
    def _extract_volume_features(self, data: pd.DataFrame) -> Dict[str, pd.Series]:
        """Extract volume-related features."""
        features = {}
        volume = data['volume']
        
        # Volume changes
        features['volume_change_1h'] = volume.pct_change(periods=1)
        features['volume_change_4h'] = volume.pct_change(periods=4)
        features['volume_change_24h'] = volume.pct_change(periods=24)
        
        # Volume moving averages
        features['volume_ma_5'] = volume.rolling(window=self.config.short_window).mean()
        features['volume_ma_20'] = volume.rolling(window=self.config.medium_window).mean()
        
        # Volume relative to moving averages
        features['volume_vs_ma5'] = volume / features['volume_ma_5']
        features['volume_vs_ma20'] = volume / features['volume_ma_20']
        
        # Volume price trend (VPT)
        price_change = data['price'].pct_change()
        features['volume_price_trend'] = (volume * price_change).cumsum()
        
        return features
    
    def _extract_technical_features(self, data: pd.DataFrame) -> Dict[str, pd.Series]:
        """Extract technical indicator features."""
        features = {}
        price = data['price']
        
        # RSI
        rsi_14 = self.technical_indicators.rsi(price, 14)
        rsi_30 = self.technical_indicators.rsi(price, 30)
        features['rsi_14'] = rsi_14
        features['rsi_30'] = rsi_30
        features['rsi_trend'] = rsi_14 - rsi_30
        
        # MACD
        macd_data = self.technical_indicators.macd(price)
        features['macd'] = macd_data['macd']
        features['macd_signal'] = macd_data['signal']
        features['macd_histogram'] = macd_data['histogram']
        features['macd_trend'] = (macd_data['macd'] > macd_data['signal']).astype(int)
        
        # Bollinger Bands
        bb_data = self.technical_indicators.bollinger_bands(price)
        features['bb_position'] = bb_data['position']
        features['bb_bandwidth'] = bb_data['bandwidth']
        features['bb_squeeze'] = (bb_data['bandwidth'] < bb_data['bandwidth'].rolling(50).mean()).astype(int)
        
        # Stochastic Oscillator
        if 'high' in data.columns and 'low' in data.columns:
            stoch_data = self.technical_indicators.stochastic_oscillator(
                data['high'], data['low'], price
            )
            features['stoch_k'] = stoch_data['k']
            features['stoch_d'] = stoch_data['d']
            features['stoch_signal'] = (stoch_data['k'] > stoch_data['d']).astype(int)
        
        # ATR (volatility measure)
        if 'high' in data.columns and 'low' in data.columns:
            atr = self.technical_indicators.atr(data['high'], data['low'], price)
            features['atr'] = atr
            features['atr_ratio'] = atr / price
        
        return features
    
    def _extract_microstructure_features(self, data: pd.DataFrame) -> Dict[str, pd.Series]:
        """Extract market microstructure features."""
        features = {}
        
        # Mock order book data (in production, use real order book)
        if 'bid_price' in data.columns and 'ask_price' in data.columns:
            # Bid-ask spread
            spread = self.market_microstructure.bid_ask_spread(
                data['bid_price'], data['ask_price']
            )
            features['bid_ask_spread'] = spread
            features['spread_ratio'] = spread / data['price']
        
        # Mock trade data
        if 'trade_volume' in data.columns:
            # Trade intensity
            trade_data = pd.DataFrame({
                'volume': data['trade_volume'],
                'price': data['price']
            })
            intensity = self.market_microstructure.trade_intensity(trade_data)
            features['trade_intensity'] = intensity
        
        # Price impact
        if 'trade_volume' in data.columns:
            trade_data = pd.DataFrame({
                'volume': data['trade_volume'],
                'price': data['price']
            })
            impact = self.market_microstructure.price_impact(trade_data)
            features['price_impact'] = impact
        
        return features
    
    def _extract_sentiment_features(self, sentiment_data: Dict[str, pd.Series]) -> Dict[str, pd.Series]:
        """Extract sentiment-related features."""
        features = {}
        
        # Aggregate sentiment
        if 'news' in sentiment_data and 'social' in sentiment_data and 'onchain' in sentiment_data:
            weights = {
                'news': self.config.news_weight,
                'social': self.config.social_weight,
                'onchain': self.config.onchain_weight
            }
            
            aggregated = self.sentiment_features.aggregate_sentiment(
                sentiment_data['news'],
                sentiment_data['social'],
                sentiment_data['onchain'],
                weights
            )
            features['market_sentiment'] = aggregated
        
        # Individual sentiment sources
        for source, series in sentiment_data.items():
            features[f'{source}_sentiment'] = series
            
            # Sentiment momentum
            momentum = self.sentiment_features.sentiment_momentum(series)
            features.update({f'{source}_{k}': v for k, v in momentum.items()})
            
            # Sentiment volatility
            volatility = self.sentiment_features.sentiment_volatility(series)
            features[f'{source}_sentiment_volatility'] = volatility
        
        return features
    
    def _extract_time_series_features(self, data: pd.DataFrame) -> Dict[str, pd.Series]:
        """Extract time series features."""
        features = {}
        
        # Seasonal features
        if 'timestamp' in data.columns:
            seasonal = self.time_series_features.seasonal_features(data['timestamp'])
            features.update(seasonal)
        
        # Price time series features
        if 'price' in data.columns:
            price = data['price']
            
            # Lag features
            lags = self.time_series_features.lag_features(price, [1, 2, 3, 5, 10])
            features.update(lags)
            
            # Rolling features
            rolling = self.time_series_features.rolling_features(price, [5, 10, 20])
            features.update(rolling)
            
            # Difference features
            diffs = self.time_series_features.difference_features(price, [1, 5, 10])
            features.update(diffs)
        
        return features
    
    def _extract_volatility_features(self, data: pd.DataFrame) -> Dict[str, pd.Series]:
        """Extract volatility-related features."""
        features = {}
        
        if 'price' in data.columns:
            price = data['price']
            
            # Price volatility (rolling standard deviation of returns)
            returns = price.pct_change()
            features['volatility_1h'] = returns.rolling(window=1).std()
            features['volatility_4h'] = returns.rolling(window=4).std()
            features['volatility_24h'] = returns.rolling(window=24).std()
            
            # Volatility trend
            features['volatility_trend'] = features['volatility_4h'] - features['volatility_24h']
            
            # Volatility ratio
            features['volatility_ratio'] = features['volatility_1h'] / features['volatility_24h']
            
            # Realized volatility
            features['realized_volatility'] = np.sqrt(returns.rolling(window=24).var())
        
        return features
    
    def _handle_missing_values(self, features_df: pd.DataFrame) -> pd.DataFrame:
        """Handle missing values in features."""
        # Forward fill for time series data
        features_df = features_df.fillna(method='ffill')
        
        # Backward fill for remaining missing values
        features_df = features_df.fillna(method='bfill')
        
        # Fill any remaining NaN with 0
        features_df = features_df.fillna(0)
        
        return features_df
    
    def _select_features(self, features_df: pd.DataFrame) -> pd.DataFrame:
        """Select important features based on importance scores."""
        if not self.importance_scores:
            return features_df
        
        # Filter features by importance threshold
        important_features = [
            feature for feature, score in self.importance_scores.items()
            if score >= self.config.importance_threshold and feature in features_df.columns
        ]
        
        # Limit to max features
        if len(important_features) > self.config.max_features:
            # Sort by importance and take top features
            sorted_features = sorted(
                important_features,
                key=lambda f: self.importance_scores.get(f, 0),
                reverse=True
            )
            important_features = sorted_features[:self.config.max_features]
        
        return features_df[important_features]
    
    def update_importance_scores(self, importance_scores: Dict[str, float]):
        """Update feature importance scores."""
        self.importance_scores.update(importance_scores)
    
    def get_feature_summary(self) -> Dict[str, Any]:
        """Get summary of engineered features."""
        if not self.feature_history:
            return {"total_feature_sets": 0}
        
        latest_set = self.feature_history[-1]
        
        return {
            "total_feature_sets": len(self.feature_history),
            "latest_features": len(latest_set.feature_names),
            "feature_types": {
                ftype: sum(1 for ft in latest_set.feature_types.values() if ft == ftype)
                for ftype in set(latest_set.feature_types.values())
            },
            "importance_scores": len(self.importance_scores),
            "last_extraction": latest_set.created_time
        }
    
    def get_feature_importance(self, top_n: int = 20) -> List[Tuple[str, float]]:
        """Get top feature importance scores."""
        sorted_features = sorted(
            self.importance_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        return sorted_features[:top_n]
