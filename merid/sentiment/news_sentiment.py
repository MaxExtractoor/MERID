"""
Kalshi News Sentiment Integration

Uses FinBERT (ProsusAI/finbert) to score financial news headlines
for sentiment analysis on crypto/BTC markets.

Slower-moving context than Twitter/Reddit, useful for macro/ETF events.
"""

import logging
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta, timezone
import os

logger = logging.getLogger(__name__)

# Lazy loading of FinBERT - only import when needed
_finbert_tokenizer = None
_finbert_model = None


def _get_finbert():
    """Lazy load FinBERT model."""
    global _finbert_tokenizer, _finbert_model
    
    if _finbert_tokenizer is None or _finbert_model is None:
        try:
            from transformers import AutoTokenizer, AutoModelForSequenceClassification
            import torch
            
            logger.info("Loading FinBERT model...")
            _finbert_tokenizer = AutoTokenizer.from_pretrained("ProsusAI/finbert")
            _finbert_model = AutoModelForSequenceClassification.from_pretrained("ProsusAI/finbert")
            
            if torch.cuda.is_available():
                _finbert_model = _finbert_model.cuda()
                logger.info("FinBERT loaded on GPU")
            else:
                logger.info("FinBERT loaded on CPU")
                
        except ImportError:
            logger.error("transformers/torch not installed, FinBERT unavailable")
            return None, None
        except Exception as exc:
            logger.error(f"Failed to load FinBERT: {exc}")
            return None, None
    
    return _finbert_tokenizer, _finbert_model


@dataclass
class NewsSentimentResult:
    """Result of news sentiment analysis."""
    headline: str
    source: str
    timestamp: datetime
    sentiment_score: float  # -1 to 1
    confidence: float       # 0 to 1
    label: str              # 'positive', 'negative', 'neutral'
    raw_probs: Dict[str, float]  # raw probabilities from model


class KalshiNewsSentiment:
    """
    News sentiment analyzer for Kalshi markets using FinBERT.
    
    Fetches and scores financial news headlines for crypto/BTC sentiment.
    Slower-moving than Twitter/Reddit, useful for macro context.
    
    Usage:
        news = KalshiNewsSentiment()
        
        # Score single headline
        result = news.score_headline("Bitcoin surges to new all-time high")
        
        # Fetch and score recent BTC news
        sentiment = news.fetch_crypto_sentiment("BTC", lookback_minutes=30)
    """
    
    def __init__(
        self,
        news_api_key: Optional[str] = None,
        min_confidence: float = 0.6,
    ):
        self.api_key = news_api_key or os.getenv("NEWS_API_KEY")
        self.min_confidence = min_confidence
        self._cache: Dict[str, Any] = {}
        self._cache_ttl = 300  # 5 minute cache
    
    def score_headline(self, text: str) -> Optional[NewsSentimentResult]:
        """
        Score a single headline using FinBERT.
        
        Args:
            text: Headline text
        
        Returns:
            NewsSentimentResult or None if scoring fails
        """
        tokenizer, model = _get_finbert()
        
        if tokenizer is None or model is None:
            logger.warning("FinBERT not available, using fallback sentiment")
            return self._fallback_score(text)
        
        try:
            import torch
            
            # Tokenize
            inputs = tokenizer(
                text,
                return_tensors="pt",
                truncation=True,
                max_length=512,
                padding=True,
            )
            
            # Move to GPU if available
            if torch.cuda.is_available():
                inputs = {k: v.cuda() for k, v in inputs.items()}
            
            # Score
            with torch.no_grad():
                outputs = model(**inputs)
                logits = outputs.logits[0]
                probs = torch.softmax(logits, dim=-1)
            
            # FinBERT labels: [negative, neutral, positive]
            probs = probs.cpu().numpy()
            
            neg_prob = float(probs[0])
            neu_prob = float(probs[1])
            pos_prob = float(probs[2])
            
            # Compute sentiment score: pos - neg, range [-1, 1]
            sentiment = pos_prob - neg_prob
            
            # Confidence: max prob
            confidence = max(pos_prob, neg_prob, neu_prob)
            
            # Label
            if pos_prob > neg_prob and pos_prob > neu_prob:
                label = "positive"
            elif neg_prob > pos_prob and neg_prob > neu_prob:
                label = "negative"
            else:
                label = "neutral"
            
            return NewsSentimentResult(
                headline=text,
                source="finbert",
                timestamp=datetime.now(timezone.utc),
                sentiment_score=sentiment,
                confidence=confidence,
                label=label,
                raw_probs={
                    "negative": neg_prob,
                    "neutral": neu_prob,
                    "positive": pos_prob,
                },
            )
            
        except Exception as exc:
            logger.warning(f"FinBERT scoring failed: {exc}")
            return self._fallback_score(text)
    
    def _fallback_score(self, text: str) -> NewsSentimentResult:
        """Fallback sentiment scoring using VADER if FinBERT unavailable."""
        try:
            from merid.sentiment.vader_utils import vader_signal
            
            # Simple VADER-based fallback
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
            analyzer = SentimentIntensityAnalyzer()
            
            scores = analyzer.polarity_scores(text)
            compound = scores["compound"]
            
            label = vader_signal(compound)
            
            return NewsSentimentResult(
                headline=text,
                source="vader_fallback",
                timestamp=datetime.now(timezone.utc),
                sentiment_score=compound,
                confidence=0.5,
                label=label.replace("_", " "),
                raw_probs={
                    "compound": compound,
                    "pos": scores["pos"],
                    "neu": scores["neu"],
                    "neg": scores["neg"],
                },
            )
        except Exception as _ve:
            logger.debug("VADER analysis failed, returning neutral: %s", _ve)
            # Ultimate fallback - neutral
            return NewsSentimentResult(
                headline=text,
                source="neutral_fallback",
                timestamp=datetime.now(timezone.utc),
                sentiment_score=0.0,
                confidence=0.0,
                label="neutral",
                raw_probs={},
            )
    
    def fetch_crypto_news(
        self,
        symbol: str = "BTC",
        lookback_minutes: int = 30,
    ) -> List[Dict[str, Any]]:
        """
        Fetch recent crypto news from API.
        
        Args:
            symbol: Crypto symbol (BTC, ETH, etc.)
            lookback_minutes: How far back to look
        
        Returns:
            List of article dicts with title, source, timestamp
        """
        if not self.api_key:
            logger.warning("No NEWS_API_KEY configured, returning synthetic data")
            return self._synthetic_news(symbol)
        
        try:
            import requests
            
            params = {
                "q": symbol,
                "category": "crypto",
                "apiKey": self.api_key,
                "pageSize": 50,
                "language": "en",
            }
            
            resp = requests.get(
                "https://newsapi.org/v2/everything",
                params=params,
                timeout=10,
            )
            resp.raise_for_status()
            
            data = resp.json()
            articles = data.get("articles", [])
            
            # Filter by timestamp
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)
            
            filtered = []
            for a in articles:
                pub_time = datetime.fromisoformat(a.get("publishedAt", "").replace("Z", "+00:00"))
                if pub_time >= cutoff:
                    filtered.append({
                        "title": a.get("title", ""),
                        "source": a.get("source", {}).get("name", "unknown"),
                        "timestamp": pub_time,
                        "url": a.get("url", ""),
                    })
            
            return filtered
            
        except Exception as exc:
            logger.warning(f"News fetch failed: {exc}, using synthetic")
            return self._synthetic_news(symbol)
    
    def _synthetic_news(self, symbol: str) -> List[Dict[str, Any]]:
        """Generate synthetic news for testing."""
        now = datetime.now(timezone.utc)
        
        templates = {
            "BTC": [
                "Bitcoin price analysis: Technical indicators show mixed signals",
                "Bitcoin ETF sees record inflows amid institutional demand",
                "Crypto market volatility rises as traders await Fed decision",
                "Bitcoin mining difficulty adjusts to network hash rate changes",
            ],
            "ETH": [
                "Ethereum network upgrades drive gas fee optimization",
                "ETH staking rewards remain attractive for long-term holders",
                "DeFi activity on Ethereum shows signs of renewed growth",
            ],
        }
        
        headlines = templates.get(symbol, [f"{symbol} market analysis shows mixed sentiment"])
        
        return [
            {
                "title": h,
                "source": "synthetic",
                "timestamp": now - timedelta(minutes=i*5),
                "url": "",
            }
            for i, h in enumerate(headlines)
        ]
    
    def fetch_crypto_sentiment(
        self,
        symbol: str = "BTC",
        lookback_minutes: int = 30,
    ) -> Dict[str, Any]:
        """
        Fetch and score news sentiment for a crypto symbol.
        
        Args:
            symbol: Crypto symbol
            lookback_minutes: Lookback window
        
        Returns:
            Dict with sentiment summary
        """
        articles = self.fetch_crypto_news(symbol, lookback_minutes)
        
        if not articles:
            return {
                "symbol": symbol,
                "sentiment": 0.0,
                "confidence": 0.0,
                "articles_scored": 0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        
        results = []
        for article in articles:
            result = self.score_headline(article["title"])
            if result and result.confidence >= self.min_confidence:
                results.append(result)
        
        if not results:
            return {
                "symbol": symbol,
                "sentiment": 0.0,
                "confidence": 0.0,
                "articles_scored": len(articles),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        
        # Weight by confidence
        total_weight = sum(r.confidence for r in results)
        weighted_sentiment = sum(r.sentiment_score * r.confidence for r in results) / total_weight
        avg_confidence = sum(r.confidence for r in results) / len(results)
        
        # Count labels
        label_counts = {}
        for r in results:
            label_counts[r.label] = label_counts.get(r.label, 0) + 1
        
        return {
            "symbol": symbol,
            "sentiment": round(weighted_sentiment, 3),
            "confidence": round(avg_confidence, 3),
            "articles_scored": len(results),
            "total_articles": len(articles),
            "label_distribution": label_counts,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "details": [
                {
                    "headline": r.headline,
                    "sentiment": r.sentiment_score,
                    "label": r.label,
                }
                for r in results[:5]  # Top 5
            ],
        }
    
    def get_combined_sentiment(
        self,
        symbol: str = "BTC",
        lookback_minutes: int = 30,
    ) -> Dict[str, Any]:
        """
        Get combined sentiment from news + social (Twitter/Reddit).
        
        Returns:
            Combined sentiment dict
        """
        # Get news sentiment
        news_sent = self.fetch_crypto_sentiment(symbol, lookback_minutes)
        
        # Get social sentiment (from existing modules)
        try:
            from merid.sentiment import combine_sentiment
            social_bundle = combine_sentiment(symbol)
            social_sent = social_bundle.combined
            social_conf = social_bundle.confidence
        except Exception as exc:
            logger.warning(f"Failed to fetch social sentiment: {exc}")
            social_sent = 0.0
            social_conf = 0.0
        
        # Combine (news is slower, social is faster)
        # Weight: 30% news, 70% social
        combined = 0.3 * news_sent["sentiment"] + 0.7 * social_sent
        conf_combined = 0.3 * news_sent["confidence"] + 0.7 * social_conf
        
        return {
            "symbol": symbol,
            "combined_sentiment": round(combined, 3),
            "confidence": round(conf_combined, 3),
            "news": {
                "sentiment": news_sent["sentiment"],
                "confidence": news_sent["confidence"],
                "articles": news_sent["articles_scored"],
            },
            "social": {
                "sentiment": social_sent,
                "confidence": social_conf,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ── Convenience functions ──────────────────────────────────────────

def quick_news_sentiment(headline: str) -> float:
    """Quick one-liner to score a headline."""
    news = KalshiNewsSentiment()
    result = news.score_headline(headline)
    return result.sentiment_score if result else 0.0


def quick_crypto_news_sentiment(symbol: str = "BTC") -> Dict[str, Any]:
    """Quick one-liner to get news sentiment for a crypto symbol."""
    news = KalshiNewsSentiment()
    return news.fetch_crypto_sentiment(symbol)
