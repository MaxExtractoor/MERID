"""
Sentiment Integration for Signal Generation

Integrates news, X (Twitter), and Reddit sentiment data into the unified
signal pipeline for cross-domain signal generation.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

from merid.sentiment.news_sentiment import KalshiNewsSentiment
from merid.sentiment.sentiment_bus import get_sentiment_bus
from merid.signals.unified_manager import get_unified_signal_manager
from utils.logger import get_logger

logger = get_logger("signals.sentiment_integration")


@dataclass
class SentimentMetrics:
    """Sentiment analysis metrics for a symbol"""
    symbol: str
    news_sentiment: float  # -1 to +1
    news_intensity: float  # 0 to 1 (article count normalized)
    social_sentiment: float  # -1 to +1
    social_intensity: float  # 0 to 1 (mention count normalized)
    combined_sentiment: float  # -1 to +1 (weighted combination)
    confidence: float  # 0 to 1
    intensity_score: float  # 0 to 1 overall intensity
    timestamp: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        return {
            "symbol": self.symbol,
            "news_sentiment": self.news_sentiment,
            "news_intensity": self.news_intensity,
            "social_sentiment": self.social_sentiment,
            "social_intensity": self.social_intensity,
            "combined_sentiment": self.combined_sentiment,
            "confidence": self.confidence,
            "intensity_score": self.intensity_score,
            "timestamp": self.timestamp,
        }


class SentimentSignalIntegrator:
    """Integrates sentiment data from multiple sources into unified signals"""
    
    def __init__(self):
        self._unified_manager = get_unified_signal_manager()
        self._sentiment_bus = get_sentiment_bus()
        self._news_analyzer: Optional[KalshiNewsSentiment] = None  # Lazy init to avoid FinBERT blocking
        self._symbol_mapping = self._create_symbol_mapping()
        self._cache: Dict[str, SentimentMetrics] = {}
        self._cache_ttl = 600  # 10 minutes cache
    
    def _get_news_analyzer(self) -> KalshiNewsSentiment:
        """Lazy initialization of news analyzer to prevent FinBERT blocking on startup."""
        if self._news_analyzer is None:
            self._news_analyzer = KalshiNewsSentiment()
        return self._news_analyzer
    
    def process_all_sentiment_signals(self) -> int:
        """Process sentiment signals for all tracked symbols"""
        processed_count = 0
        
        try:
            # Get symbols from various sources
            symbols = self._get_tracked_symbols()
            
            for symbol in symbols:
                try:
                    metrics = self._calculate_sentiment_metrics(symbol)
                    if metrics:
                        # Store as feature snapshot
                        success = self._unified_manager.store_feature_snapshot(
                            symbol=symbol,
                            domain="prediction",
                            features=metrics.to_dict(),
                            source="news_reddit_x"
                        )
                        
                        # Create sentiment signal if significant
                        if abs(metrics.combined_sentiment) > 0.3 and metrics.intensity_score > 0.2:
                            self._create_sentiment_signal(metrics)
                        
                        if success:
                            processed_count += 1
                            
                except Exception as e:
                    logger.warning(f"Failed to process sentiment for {symbol}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Failed to process sentiment signals: {e}")
            
        return processed_count
    
    def get_sentiment_metrics(self, symbol: str) -> Optional[SentimentMetrics]:
        """Get cached sentiment metrics for a symbol"""
        cached = self._cache.get(symbol)
        if cached and (time.time() - cached.timestamp) < self._cache_ttl:
            return cached
        
        # Calculate fresh metrics
        metrics = self._calculate_sentiment_metrics(symbol)
        if metrics:
            self._cache[symbol] = metrics
            
        return metrics
    
    def _get_tracked_symbols(self) -> List[str]:
        """Get list of symbols to track for sentiment"""
        # Get symbols from Kalshi markets, crypto assets, etc.
        symbols = set()
        
        try:
            # Add major crypto symbols
            symbols.update(["BTC", "ETH", "SOL", "ADA", "DOT", "MATIC", "AVAX", "LINK"])
            
            # Add Kalshi-related symbols (would need to query Kalshi universe)
            # For now, add common prediction market symbols
            symbols.update(["BTC-USD", "ETH-USD", "SPY", "QQQ", "IWM"])
            
        except Exception as e:
            logger.warning(f"Failed to get tracked symbols: {e}")
            
        return list(symbols)
    
    def _calculate_sentiment_metrics(self, symbol: str) -> Optional[SentimentMetrics]:
        """Calculate comprehensive sentiment metrics for a symbol"""
        try:
            # Get news sentiment
            news_sentiment, news_intensity = self._get_news_sentiment(symbol)
            
            # Get social sentiment (X/Reddit)
            social_sentiment, social_intensity = self._get_social_sentiment(symbol)
            
            # Calculate combined sentiment
            combined_sentiment = self._combine_sentiment(
                news_sentiment, news_intensity,
                social_sentiment, social_intensity
            )
            
            # Calculate confidence
            confidence = self._calculate_confidence(
                news_intensity, social_intensity
            )
            
            # Calculate overall intensity score
            intensity_score = (news_intensity + social_intensity) / 2.0
            
            return SentimentMetrics(
                symbol=symbol,
                news_sentiment=news_sentiment,
                news_intensity=news_intensity,
                social_sentiment=social_sentiment,
                social_intensity=social_intensity,
                combined_sentiment=combined_sentiment,
                confidence=confidence,
                intensity_score=intensity_score,
                timestamp=time.time()
            )
            
        except Exception as e:
            logger.warning(f"Failed to calculate sentiment metrics for {symbol}: {e}")
            return None
    
    def _get_news_sentiment(self, symbol: str) -> Tuple[float, float]:
        """Get news sentiment and intensity for a symbol"""
        try:
            # Map symbol to news search terms
            search_terms = self._symbol_mapping.get(symbol, [symbol])
            
            # Get recent news using the KalshiNewsSentiment analyzer
            sentiment_scores = []
            article_count = 0
            
            for term in search_terms:
                try:
                    # Use the fetch_crypto_sentiment method
                    news_result = self._get_news_analyzer().fetch_crypto_sentiment(
                        symbol=term, lookback_minutes=1440  # 24 hours
                    )

                    if not news_result:
                        continue

                    # Skip synthetic placeholders — they carry no real signal
                    if news_result.get("is_synthetic", False):
                        logger.debug("Skipping synthetic news result for term %s", term)
                        continue

                    articles_scored = news_result.get("articles_scored", 0)
                    if articles_scored > 0:
                        article_count += articles_scored
                        # Use the pre-computed aggregate sentiment directly
                        agg_sentiment = news_result.get("sentiment", 0.0)
                        if agg_sentiment is not None:
                            # Weight by article count so larger batches contribute more
                            sentiment_scores.extend([agg_sentiment] * articles_scored)

                except Exception as e:
                    logger.debug(f"Failed to get news for term {term}: {e}")
                    continue

            # Calculate average sentiment and intensity
            if sentiment_scores:
                avg_sentiment = sum(sentiment_scores) / len(sentiment_scores)
                # Normalize intensity (0-1 scale, where 1 = high activity)
                intensity = min(1.0, article_count / 50.0)  # 50 articles = max intensity
            else:
                avg_sentiment = 0.0
                intensity = 0.0
            
            return avg_sentiment, intensity
            
        except Exception as e:
            logger.warning(f"Failed to get news sentiment for {symbol}: {e}")
            return 0.0, 0.0
    
    def _get_social_sentiment(self, symbol: str) -> Tuple[float, float]:
        """Get social sentiment (X/Reddit) for a symbol"""
        try:
            # Map symbol to base asset (strip -USD suffix if present)
            asset = symbol.split("-")[0]

            # get_sentiment() returns UnifiedSentiment dataclass (or None)
            unified = self._sentiment_bus.get_sentiment(asset)

            if unified is not None:
                sentiment = unified.combined_social_sentiment
                # Use twitter_volume as intensity proxy (capped at 1000 tweets)
                intensity = min(1.0, unified.twitter_volume / 1000.0)
                return sentiment, intensity
            else:
                return 0.0, 0.0

        except Exception as e:
            logger.warning(f"Failed to get social sentiment for {symbol}: {e}")
            return 0.0, 0.0
    
    def _combine_sentiment(
        self,
        news_sentiment: float, news_intensity: float,
        social_sentiment: float, social_intensity: float
    ) -> float:
        """Combine news and social sentiment with intensity weighting"""
        # Weight by intensity (higher intensity = more influence)
        total_intensity = news_intensity + social_intensity
        if total_intensity == 0:
            return 0.0
        
        news_weight = news_intensity / total_intensity
        social_weight = social_intensity / total_intensity
        
        combined = news_weight * news_sentiment + social_weight * social_sentiment
        
        # Clamp to -1 to 1 range
        return max(-1.0, min(1.0, combined))
    
    def _calculate_confidence(self, news_intensity: float, social_intensity: float) -> float:
        """Calculate confidence in sentiment based on data availability"""
        # Return exactly 0.0 when there is no data at all — a zero-intensity
        # signal with non-zero confidence would incorrectly enter the signal store.
        if news_intensity == 0.0 and social_intensity == 0.0:
            return 0.0

        # Higher intensity = more data = higher confidence
        avg_intensity = (news_intensity + social_intensity) / 2.0

        # Apply confidence curve (diminishing returns)
        confidence = 1.0 - (2.718 ** (-2 * avg_intensity))  # Exponential approach to 1

        return max(0.0, min(1.0, confidence))
    
    def _create_sentiment_signal(self, metrics: SentimentMetrics):
        """Create a sentiment signal when significant"""
        try:
            success = self._unified_manager.create_news_sentiment_signal(
                symbol=metrics.symbol,
                sentiment_score=metrics.combined_sentiment,
                intensity=(metrics.news_intensity + metrics.social_intensity) / 2.0,
                features={
                    "news_sentiment": metrics.news_sentiment,
                    "news_intensity": metrics.news_intensity,
                    "social_sentiment": metrics.social_sentiment,
                    "social_intensity": metrics.social_intensity,
                    "confidence": metrics.confidence,
                },
                source="news_reddit_x"
            )
            
            if success:
                sentiment_label = "positive" if metrics.combined_sentiment > 0.2 else "negative" if metrics.combined_sentiment < -0.2 else "neutral"
                logger.info(f"Created {sentiment_label} sentiment signal for {metrics.symbol}: {metrics.combined_sentiment:.2f}")
                
        except Exception as e:
            logger.warning(f"Failed to create sentiment signal for {metrics.symbol}: {e}")
    
    def _create_symbol_mapping(self) -> Dict[str, List[str]]:
        """Create mapping from symbols to search terms for sentiment analysis"""
        return {
            "BTC": ["Bitcoin", "BTC", "bitcoin", "BTCUSD"],
            "ETH": ["Ethereum", "ETH", "ethereum", "ETHUSD"],
            "SOL": ["Solana", "SOL", "solana", "SOLUSD"],
            "ADA": ["Cardano", "ADA", "cardano", "ADAUSD"],
            "DOT": ["Polkadot", "DOT", "polkadot", "DOTUSD"],
            "MATIC": ["Polygon", "MATIC", "polygon", "MATICUSD"],
            "AVAX": ["Avalanche", "AVAX", "avalanche", "AVAXUSD"],
            "LINK": ["Chainlink", "LINK", "chainlink", "LINKUSD"],
            "SPY": ["S&P 500", "SPY", "SP500", "stock market"],
            "QQQ": ["NASDAQ", "QQQ", "tech stocks", "technology"],
            "IWM": ["Russell 2000", "IWM", "small caps", "small cap stocks"],
            "BTC-USD": ["Bitcoin", "BTC", "bitcoin", "BTCUSD"],
            "ETH-USD": ["Ethereum", "ETH", "ethereum", "ETHUSD"],
        }


# Singleton instance
_integrator: Optional[SentimentSignalIntegrator] = None


def get_sentiment_signal_integrator() -> SentimentSignalIntegrator:
    """Get the singleton sentiment signal integrator"""
    global _integrator
    if _integrator is None:
        _integrator = SentimentSignalIntegrator()
    return _integrator


def run_sentiment_signal_processing() -> int:
    """Run sentiment signal processing and return count of processed symbols"""
    integrator = get_sentiment_signal_integrator()
    return integrator.process_all_sentiment_signals()
