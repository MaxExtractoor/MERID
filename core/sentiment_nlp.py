"""MERID NLP Sentiment Analysis Pipeline.

Sentiment analysis for financial text using VADER, FinBERT, and transformers.
Supports multi-source sentiment aggregation for trading signals.
"""

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
import structlog
import re

logger = structlog.get_logger(__name__)


class SentimentSource(str, Enum):
    """Source of sentiment data."""
    REDDIT = "reddit"
    TWITTER = "twitter"
    NEWS = "news"
    TELEGRAM = "telegram"
    STOCKTWITS = "stocktwits"


class SentimentPolarity(str, Enum):
    """Sentiment polarity classification."""
    VERY_NEGATIVE = "very_negative"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    POSITIVE = "positive"
    VERY_POSITIVE = "very_positive"


@dataclass
class SentimentResult:
    """Sentiment analysis result."""
    text: str
    source: SentimentSource
    compound_score: float  # -1 to 1
    polarity: SentimentPolarity
    confidence: float  # 0 to 1
    tickers: List[str]
    timestamp: float
    metadata: Dict[str, Any]
    
    def to_signal_strength(self) -> Decimal:
        """Convert sentiment to trading signal strength."""
        # Map compound score to signal strength (-1 to 1)
        return Decimal(str(self.compound_score)) * Decimal(str(self.confidence))


@dataclass
class AggregatedSentiment:
    """Aggregated sentiment across multiple sources."""
    ticker: str
    overall_score: float
    overall_polarity: SentimentPolarity
    source_breakdown: Dict[SentimentSource, float]
    confidence: float
    mention_count: int
    volume_score: float
    timestamp: float


class VaderSentimentAnalyzer:
    """VADER-based sentiment analyzer for social media text."""
    
    def __init__(self):
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
            self.analyzer = SentimentIntensityAnalyzer()
            self.available = True
        except ImportError:
            logger.warning("vaderSentiment not installed, using fallback")
            self.analyzer = None
            self.available = False
        
        logger.info("vader_analyzer_initialized", available=self.available)
    
    def analyze(self, text: str) -> Tuple[float, float, float, float]:
        """
        Analyze text sentiment.
        
        Returns:
            Tuple of (negative, neutral, positive, compound) scores
        """
        if not self.available or not self.analyzer:
            # Fallback: simple keyword-based
            return self._fallback_analysis(text)
        
        scores = self.analyzer.polarity_scores(text)
        return (
            scores['neg'],
            scores['neu'],
            scores['pos'],
            scores['compound']
        )
    
    def _fallback_analysis(self, text: str) -> Tuple[float, float, float, float]:
        """Simple fallback sentiment analysis."""
        text_lower = text.lower()
        
        positive_words = ['bullish', 'moon', 'pump', 'buy', 'long', 'gain', 'profit', 'up']
        negative_words = ['bearish', 'crash', 'dump', 'sell', 'short', 'loss', 'down', 'fear']
        
        pos_count = sum(1 for w in positive_words if w in text_lower)
        neg_count = sum(1 for w in negative_words if w in text_lower)
        
        total = pos_count + neg_count
        if total == 0:
            return 0.0, 1.0, 0.0, 0.0
        
        pos_score = pos_count / total
        neg_score = neg_count / total
        compound = pos_score - neg_score
        
        return neg_score, 0.0, pos_score, compound
    
    def analyze_batch(self, texts: List[str]) -> List[Tuple[float, float, float, float]]:
        """Analyze batch of texts."""
        return [self.analyze(text) for text in texts]


class FinBERTAnalyzer:
    """FinBERT-based sentiment analyzer for financial text."""
    
    def __init__(self, model_name: str = "ProsusAI/finbert"):
        self.model_name = model_name
        self.pipeline = None
        self.available = False
        
        try:
            from transformers import pipeline
            self.pipeline = pipeline(
                "sentiment-analysis",
                model=model_name,
                tokenizer=model_name,
                device=-1  # CPU
            )
            self.available = True
            logger.info("finbert_analyzer_initialized", model=model_name)
        except ImportError:
            logger.warning("transformers not installed, FinBERT unavailable")
        except Exception as e:
            logger.error("finbert_init_error", error=str(e))
    
    def analyze(self, text: str) -> Dict[str, Any]:
        """Analyze text with FinBERT."""
        if not self.available or not self.pipeline:
            return {"label": "neutral", "score": 0.5}
        
        # FinBERT expects shorter texts, truncate if needed
        truncated = text[:512]
        
        try:
            result = self.pipeline(truncated)[0]
            return result
        except Exception as e:
            logger.error("finbert_analysis_error", error=str(e))
            return {"label": "neutral", "score": 0.5}
    
    def to_compound_score(self, result: Dict[str, Any]) -> float:
        """Convert FinBERT result to compound score."""
        label_map = {
            "positive": 1.0,
            "neutral": 0.0,
            "negative": -1.0
        }
        
        label = result.get("label", "neutral").lower()
        score = result.get("score", 0.5)
        
        return label_map.get(label, 0.0) * score


class TickerExtractor:
    """Extract stock/crypto tickers from text."""
    
    def __init__(self):
        # Common crypto tickers
        self.crypto_tickers = {
            'BTC', 'ETH', 'SOL', 'ADA', 'DOT', 'LINK', 'UNI', 'AAVE',
            'CRV', 'SUSHI', '1INCH', 'COMP', 'MKR', 'YFI', 'SNX'
        }
        
        # Common stock patterns
        self.ticker_pattern = re.compile(r'\$([A-Z]{1,5})\b')
        self.cashtag_pattern = re.compile(r'\$([A-Z]{1,5})')
        
        logger.info("ticker_extractor_initialized")
    
    def extract(self, text: str) -> List[str]:
        """Extract tickers from text."""
        tickers = set()
        
        # Find cashtags ($AAPL)
        cashtags = self.cashtag_pattern.findall(text.upper())
        tickers.update(cashtags)
        
        # Find standalone uppercase words that look like tickers
        words = text.upper().split()
        for word in words:
            clean = re.sub(r'[^A-Z]', '', word)
            if 1 <= len(clean) <= 5 and clean.isalpha():
                tickers.add(clean)
        
        return list(tickers)
    
    def extract_with_context(self, text: str) -> List[Tuple[str, str]]:
        """Extract tickers with surrounding context."""
        tickers_with_context = []
        tickers = self.extract(text)
        
        for ticker in tickers:
            # Find context around ticker
            pattern = re.compile(rf'.{{0,50}}\${ticker}.{{0,50}}', re.IGNORECASE)
            matches = pattern.findall(text)
            context = ' '.join(matches) if matches else text[:100]
            tickers_with_context.append((ticker, context))
        
        return tickers_with_context


class SentimentPipeline:
    """Main sentiment analysis pipeline."""
    
    def __init__(self, use_finbert: bool = False):
        self.vader = VaderSentimentAnalyzer()
        self.finbert = FinBERTAnalyzer() if use_finbert else None
        self.ticker_extractor = TickerExtractor()
        self.use_finbert = use_finbert
        
        logger.info(
            "sentiment_pipeline_initialized",
            vader=self.vader.available,
            finbert=self.finbert.available if self.finbert else False
        )
    
    def analyze_text(
        self,
        text: str,
        source: SentimentSource,
        timestamp: Optional[float] = None
    ) -> SentimentResult:
        """Analyze single text for sentiment."""
        import time
        
        # Get VADER scores
        neg, neu, pos, compound = self.vader.analyze(text)
        confidence = 1.0 - neu  # Confidence based on non-neutral score
        
        # Get FinBERT score if available
        if self.use_finbert and self.finbert and self.finbert.available:
            finbert_result = self.finbert.analyze(text)
            finbert_compound = self.finbert.to_compound_score(finbert_result)
            # Blend scores
            compound = (compound * 0.6) + (finbert_compound * 0.4)
        
        # Determine polarity
        polarity = self._score_to_polarity(compound)
        
        # Extract tickers
        tickers = self.ticker_extractor.extract(text)
        
        return SentimentResult(
            text=text[:500],  # Truncate for storage
            source=source,
            compound_score=compound,
            polarity=polarity,
            confidence=confidence,
            tickers=tickers,
            timestamp=timestamp or time.time(),
            metadata={
                "vader_neg": neg,
                "vader_neu": neu,
                "vader_pos": pos,
                "char_count": len(text),
                "word_count": len(text.split())
            }
        )
    
    def analyze_batch(
        self,
        texts: List[str],
        source: SentimentSource,
        timestamps: Optional[List[float]] = None
    ) -> List[SentimentResult]:
        """Analyze batch of texts."""
        import time
        
        results = []
        for i, text in enumerate(texts):
            ts = timestamps[i] if timestamps else time.time()
            result = self.analyze_text(text, source, ts)
            results.append(result)
        
        return results
    
    def aggregate_by_ticker(
        self,
        results: List[SentimentResult],
        ticker: str
    ) -> AggregatedSentiment:
        """Aggregate sentiment results for a specific ticker."""
        import time
        
        # Filter results containing ticker
        ticker_results = [
            r for r in results
            if ticker.upper() in [t.upper() for t in r.tickers]
        ]
        
        if not ticker_results:
            return AggregatedSentiment(
                ticker=ticker,
                overall_score=0.0,
                overall_polarity=SentimentPolarity.NEUTRAL,
                source_breakdown={},
                confidence=0.0,
                mention_count=0,
                volume_score=0.0,
                timestamp=time.time()
            )
        
        # Calculate weighted average score
        total_confidence = sum(r.confidence for r in ticker_results)
        weighted_score = sum(
            r.compound_score * r.confidence for r in ticker_results
        ) / total_confidence if total_confidence > 0 else 0.0
        
        # Source breakdown
        source_scores: Dict[SentimentSource, List[float]] = {}
        for r in ticker_results:
            if r.source not in source_scores:
                source_scores[r.source] = []
            source_scores[r.source].append(r.compound_score)
        
        source_breakdown = {
            source: sum(scores) / len(scores)
            for source, scores in source_scores.items()
        }
        
        # Volume score based on mention count
        volume_score = min(len(ticker_results) / 100, 1.0)
        
        return AggregatedSentiment(
            ticker=ticker,
            overall_score=weighted_score,
            overall_polarity=self._score_to_polarity(weighted_score),
            source_breakdown=source_breakdown,
            confidence=total_confidence / len(ticker_results),
            mention_count=len(ticker_results),
            volume_score=volume_score,
            timestamp=time.time()
        )
    
    def _score_to_polarity(self, score: float) -> SentimentPolarity:
        """Convert compound score to polarity."""
        if score <= -0.6:
            return SentimentPolarity.VERY_NEGATIVE
        elif score <= -0.2:
            return SentimentPolarity.NEGATIVE
        elif score >= 0.6:
            return SentimentPolarity.VERY_POSITIVE
        elif score >= 0.2:
            return SentimentPolarity.POSITIVE
        else:
            return SentimentPolarity.NEUTRAL


class SentimentSignalGenerator:
    """Generate trading signals from sentiment data."""
    
    def __init__(self, pipeline: SentimentPipeline):
        self.pipeline = pipeline
        self.logger = logger.bind(component="SentimentSignalGenerator")
        
        # Thresholds for signal generation
        self.buy_threshold = Decimal("0.5")
        self.sell_threshold = Decimal("-0.5")
        self.min_confidence = Decimal("0.6")
        self.min_mentions = 5
    
    def generate_signal(
        self,
        aggregated: AggregatedSentiment
    ) -> Optional[Dict[str, Any]]:
        """Generate trading signal from aggregated sentiment."""
        
        if aggregated.mention_count < self.min_mentions:
            return None
        
        if aggregated.confidence < float(self.min_confidence):
            return None
        
        signal_strength = Decimal(str(aggregated.overall_score)) * Decimal(str(aggregated.confidence))
        
        if signal_strength >= self.buy_threshold:
            signal_type = "BUY"
        elif signal_strength <= self.sell_threshold:
            signal_type = "SELL"
        else:
            return None
        
        self.logger.info(
            "sentiment_signal_generated",
            ticker=aggregated.ticker,
            signal=signal_type,
            strength=str(signal_strength)
        )
        
        return {
            "ticker": aggregated.ticker,
            "signal": signal_type,
            "strength": float(signal_strength),
            "confidence": aggregated.confidence,
            "sentiment_score": aggregated.overall_score,
            "mention_count": aggregated.mention_count,
            "sources": list(aggregated.source_breakdown.keys()),
            "timestamp": aggregated.timestamp
        }


# Singleton pipeline instance
sentiment_pipeline = SentimentPipeline(use_finbert=False)
