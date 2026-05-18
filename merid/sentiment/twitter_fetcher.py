"""
Twitter/X Sentiment Fetcher for Kalshi markets.

Fetches recent tweets for asset keywords, aggregates sentiment using
TextBlob polarity scores weighted by engagement metrics.

Usage:
    from merid.sentiment.twitter_fetcher import get_twitter_sentiment_service
    
    service = get_twitter_sentiment_service()
    score = service.get_sentiment("BTC", minutes=15)
    service.update_mood_bus("BTC")  # Push to MarketMoodBus
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Any
import os
import asyncio
import logging
from collections import defaultdict

try:
    import requests
except ImportError:
    requests = None  # type: ignore

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
except ImportError:
    SentimentIntensityAnalyzer = None  # type: ignore

# VADER analyzer singleton
_vader_analyzer: Optional[Any] = None

def get_vader_analyzer() -> Optional[Any]:
    """Get or create VADER sentiment analyzer."""
    global _vader_analyzer
    if _vader_analyzer is None and SentimentIntensityAnalyzer:
        _vader_analyzer = SentimentIntensityAnalyzer()
    return _vader_analyzer

logger = logging.getLogger(__name__)


@dataclass
class TweetData:
    """Structured tweet data."""
    id: str
    text: str
    created_at: datetime
    like_count: int
    retweet_count: int
    reply_count: int
    author_id: Optional[str] = None


@dataclass
class SentimentResult:
    """Sentiment analysis result."""
    score: float  # -1.0 to +1.0
    confidence: float  # 0.0 to 1.0 based on volume/engagement
    volume: int  # Number of tweets analyzed
    avg_engagement: float  # Average engagement score
    raw_data: List[Dict[str, Any]]  # Raw tweets for debugging
    timestamp: datetime


class TwitterSentimentService:
    """
    Fetches and analyzes Twitter/X sentiment for crypto assets.
    
    Uses Twitter API v2 recent search endpoint with keyword queries
    tailored to Kalshi market assets (BTC, ETH, SOL, etc.).
    """
    
    _instance = None
    
    # Asset → keyword mappings for Kalshi-relevant search
    ASSET_QUERIES: Dict[str, str] = {
        "BTC": "(BTC OR Bitcoin OR #Bitcoin OR #BTC OR bitcoin price)",
        "ETH": "(ETH OR Ethereum OR #Ethereum OR #ETH OR ethereum price)",
        "SOL": "(SOL OR Solana OR #Solana OR #SOL OR solana price)",
        "XRP": "(XRP OR Ripple OR #XRP OR ripple price)",
        "DOGE": "(DOGE OR Dogecoin OR #Dogecoin OR dogecoin price)",
        "PEPE": "(PEPE OR Pepe OR #PEPE OR pepe coin)",
        "WIF": "(WIF OR dogwifhat OR #WIF OR dogwifhat price)",
        "FED": "(Federal Reserve OR Fed OR FOMC OR Powell OR interest rate)",
        "CPI": "(CPI OR inflation OR consumer price OR PCE)",
        "SPX": "(S&P 500 OR SPX OR stock market OR Nasdaq)",
        # Energy assets (NEW)
        "ERCOT": "(ERCOT OR Texas grid OR electricity price OR power outage OR grid failure)",
        "OIL": "(oil price OR crude oil OR WTI OR Brent OR OPEC OR petroleum OR barrel)",
        "GAS": "(natural gas OR LNG OR gas price OR natgas OR gas storage)",
        "CARBON": "(carbon credit OR emission trading OR carbon price OR carbon market)",
        "RENEWABLE": "(renewable energy OR solar power OR wind power OR green energy)",
    }
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, bearer_token: Optional[str] = None):
        if self._initialized:
            return
        
        self.bearer_token = bearer_token or os.getenv("TWITTER_BEARER_TOKEN")
        self.base_url = "https://api.twitter.com/2"
        self._cache: Dict[str, SentimentResult] = {}
        self._cache_ttl_seconds = 120  # 2 minute cache
        
        if not self.bearer_token:
            logger.warning("Twitter bearer token not configured - sentiment will return 0")
        if not self.bearer_token or not requests:
            logger.debug("Twitter API not configured - returning empty tweets")
            return []
        if not SentimentIntensityAnalyzer:
            logger.warning("VADER not available - sentiment analysis disabled")
        
        self._initialized = True
        logger.info("TwitterSentimentService initialized (VADER-enabled)")
    
    def _get_headers(self) -> Dict[str, str]:
        """Get auth headers for Twitter API."""
        return {"Authorization": f"Bearer {self.bearer_token}"}
    
    def _build_query(self, asset: str, additional_terms: Optional[str] = None) -> str:
        """Build search query for an asset."""
        base_query = self.ASSET_QUERIES.get(asset.upper(), f"({asset})")
        
        # Add filters to reduce noise
        filters = "lang:en -is:retweet -is:reply"
        
        query = f"{base_query} {filters}"
        if additional_terms:
            query = f"{base_query} ({additional_terms}) {filters}"
        
        return query
    
    def fetch_tweets(
        self,
        asset: str,
        minutes: int = 15,
        max_results: int = 100,
        additional_terms: Optional[str] = None,
    ) -> List[TweetData]:
        """
        Fetch recent tweets for an asset.
        
        Args:
            asset: Asset symbol (BTC, ETH, etc.)
            minutes: How far back to search
            max_results: Max tweets to fetch (10-100)
            additional_terms: Additional search terms
        
        Returns:
            List of TweetData objects
        """
        if not self.bearer_token or not requests:
            logger.debug("Twitter API not configured - returning empty tweets")
            return []
        
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(minutes=minutes)
        
        query = self._build_query(asset, additional_terms)
        
        params = {
            "query": query,
            "max_results": min(max(max_results, 10), 100),
            "start_time": start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_time": end_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tweet.fields": "created_at,public_metrics,author_id",
        }
        
        try:
            resp = requests.get(
                f"{self.base_url}/tweets/search/recent",
                params=params,
                headers=self._get_headers(),
                timeout=15,
            )
            
            if resp.status_code == 429:
                logger.warning("Twitter API rate limited")
                return []
            
            if resp.status_code == 401:
                logger.error("Twitter API unauthorized - check bearer token")
                return []
            
            resp.raise_for_status()
            data = resp.json()
            
            tweets = []
            for t in data.get("data", []):
                metrics = t.get("public_metrics", {})
                tweets.append(TweetData(
                    id=t["id"],
                    text=t["text"],
                    created_at=datetime.fromisoformat(t["created_at"].replace("Z", "+00:00")),
                    like_count=metrics.get("like_count", 0),
                    retweet_count=metrics.get("retweet_count", 0),
                    reply_count=metrics.get("reply_count", 0),
                    author_id=t.get("author_id"),
                ))
            
            logger.debug(f"Fetched {len(tweets)} tweets for {asset}")
            return tweets
            
        except requests.exceptions.Timeout:
            logger.warning(f"Twitter API timeout for {asset}")
            return []
        except Exception as exc:
            logger.warning(f"Twitter fetch error: {exc}")
            return []
    
    def analyze_sentiment(self, tweets: List[TweetData]) -> SentimentResult:
        """
        Analyze sentiment of tweets using VADER.
        
        VADER is specifically designed for short, informal social media text
        like tweets, handling slang, emoticons, and intensity well.
        
        Weights tweets by engagement (likes^0.5) to give more
        weight to viral/engaging content.
        
        Returns:
            SentimentResult with score (-1 to +1) and confidence
        """
        analyzer = get_vader_analyzer()
        
        if not tweets:
            return SentimentResult(
                score=0.0,
                confidence=0.0,
                volume=0,
                avg_engagement=0.0,
                raw_data=[],
                timestamp=datetime.now(timezone.utc),
            )
        
        if not analyzer:
            # Fallback: neutral sentiment if VADER unavailable
            return SentimentResult(
                score=0.0,
                confidence=0.3,  # Low confidence due to no analysis
                volume=len(tweets),
                avg_engagement=sum(t.like_count for t in tweets) / len(tweets),
                raw_data=[{"id": t.id, "text": t.text[:100]} for t in tweets[:5]],
                timestamp=datetime.now(timezone.utc),
            )
        
        total_weighted_sentiment = 0.0
        total_weight = 0.0
        engagement_scores = []
        
        for tweet in tweets:
            # Get VADER compound sentiment (-1 to +1)
            scores = analyzer.polarity_scores(tweet.text)
            compound = scores["compound"]  # Normalized to [-1, 1]
            
            # Weight by engagement (sqrt of likes to dampen extreme values)
            engagement = 1.0 + (tweet.like_count ** 0.5) + (tweet.retweet_count ** 0.5)
            engagement_scores.append(engagement)
            
            total_weighted_sentiment += compound * engagement
            total_weight += engagement
        
        # Calculate weighted average
        score = total_weighted_sentiment / total_weight if total_weight > 0 else 0.0
        
        # Confidence based on volume and engagement
        avg_engagement = sum(engagement_scores) / len(engagement_scores)
        volume_factor = min(len(tweets) / 50.0, 1.0)  # Max at 50 tweets
        engagement_factor = min(avg_engagement / 10.0, 1.0)  # Max at avg 10 engagement
        confidence = 0.3 + (0.7 * volume_factor * engagement_factor)
        
        # Raw data includes VADER breakdown
        raw_data = []
        for t in tweets[:10]:
            vs = analyzer.polarity_scores(t.text)
            raw_data.append({
                "id": t.id,
                "text": t.text[:150],
                "likes": t.like_count,
                "retweets": t.retweet_count,
                "compound": vs["compound"],
                "pos": vs["pos"],
                "neg": vs["neg"],
                "neu": vs["neu"],
            })
        
        return SentimentResult(
            score=score,
            confidence=confidence,
            volume=len(tweets),
            avg_engagement=avg_engagement,
            raw_data=raw_data,
            timestamp=datetime.now(timezone.utc),
        )
    
    def get_sentiment(
        self,
        asset: str,
        minutes: int = 15,
        max_results: int = 100,
        use_cache: bool = True,
    ) -> SentimentResult:
        """
        Get sentiment for an asset (fetch + analyze, with caching).
        
        This is the main entry point for agents/UI to get Twitter sentiment.
        
        Args:
            asset: Asset symbol (BTC, ETH, etc.)
            minutes: Lookback window for tweets
            max_results: Max tweets to analyze
            use_cache: Use cached result if fresh
        
        Returns:
            SentimentResult with score, confidence, volume
        """
        cache_key = f"{asset}:{minutes}"
        
        # Check cache
        if use_cache and cache_key in self._cache:
            cached = self._cache[cache_key]
            age = (datetime.now(timezone.utc) - cached.timestamp).total_seconds()
            if age < self._cache_ttl_seconds:
                logger.debug(f"Using cached Twitter sentiment for {asset}")
                return cached
        
        # Fetch and analyze
        tweets = self.fetch_tweets(asset, minutes, max_results)
        result = self.analyze_sentiment(tweets)
        
        # Cache result
        self._cache[cache_key] = result
        
        logger.info(
            f"Twitter sentiment for {asset}: score={result.score:+.3f}, "
            f"confidence={result.confidence:.2f}, volume={result.volume}"
        )
        
        return result
    
    def update_mood_bus(self, asset: str, minutes: int = 15) -> bool:
        """
        Fetch sentiment and push to MarketMoodBus.
        
        This is the integration point - call this on a schedule
        to keep the mood bus updated with fresh Twitter sentiment.
        
        Args:
            asset: Asset to update
            minutes: Tweet lookback window
        
        Returns:
            True if successful
        """
        try:
            result = self.get_sentiment(asset, minutes=minutes)
            
            from merid.swarm.market_mood_bus import get_market_mood_bus
            bus = get_market_mood_bus()
            
            # Convert volume to 24h estimate (approximate)
            volume_24h_estimate = int(result.volume * (1440 / minutes))
            
            bus.update_social_sentiment(
                asset=asset,
                sentiment=result.score,
                volume_24h=volume_24h_estimate,
                is_trending=result.volume > 50 and result.confidence > 0.6,
                source="twitter",
                confidence=result.confidence,
            )
            
            logger.debug(f"Updated MarketMoodBus Twitter sentiment for {asset}")
            return True
            
        except Exception as exc:
            logger.warning(f"Failed to update mood bus for {asset}: {exc}")
            return False
    
    async def update_all_assets(self, assets: Optional[List[str]] = None, minutes: int = 15):
        """
        Update sentiment for all assets asynchronously.
        
        Args:
            assets: List of assets (defaults to all configured)
            minutes: Tweet lookback window
        """
        if assets is None:
            assets = list(self.ASSET_QUERIES.keys())
        
        # Run updates concurrently
        tasks = [self.update_mood_bus(asset, minutes) for asset in assets]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        success_count = sum(1 for r in results if r is True)
        logger.info(f"Updated Twitter sentiment for {success_count}/{len(assets)} assets")
    
    def get_multi_asset_sentiment(
        self,
        assets: List[str],
        minutes: int = 15,
    ) -> Dict[str, SentimentResult]:
        """Get sentiment for multiple assets."""
        return {
            asset: self.get_sentiment(asset, minutes=minutes)
            for asset in assets
        }


# Singleton accessor
def get_twitter_sentiment_service(bearer_token: Optional[str] = None) -> TwitterSentimentService:
    """Get the singleton TwitterSentimentService instance."""
    return TwitterSentimentService(bearer_token)


# ── Convenience functions for quick usage ─────────────────────────────

def quick_twitter_sentiment(asset: str, minutes: int = 15) -> float:
    """
    Quick one-liner to get Twitter sentiment score.
    
    Returns sentiment score (-1 to +1) or 0.0 if unavailable.
    """
    try:
        service = get_twitter_sentiment_service()
        result = service.get_sentiment(asset, minutes=minutes)
        return result.score
    except Exception:
        return 0.0


def get_btc_kalshi_sentiment() -> float:
    """
    Get Twitter sentiment specifically for BTC Kalshi markets.
    
    Convenience function matching the user's skeleton pattern.
    """
    return quick_twitter_sentiment("BTC", minutes=15)


# ── Streaming Support ──────────────────────────────────────────────────

class TwitterStreamHandler:
    """
    Real-time Twitter stream handler for continuous sentiment.
    
    Uses Twitter API v2 filtered stream to track assets continuously.
    Maintains a rolling window of sentiment scores for each tracked asset.
    """
    
    def __init__(self, bearer_token: Optional[str] = None):
        self.bearer_token = bearer_token or os.getenv("TWITTER_BEARER_TOKEN")
        self.base_url = "https://api.twitter.com/2"
        self._running = False
        self._stream_thread: Optional[threading.Thread] = None
        self._sentiment_windows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._window_size = 100  # Keep last 100 tweets per asset
        self._callbacks: List[Callable[[str, float, Dict], None]] = []
        
        # Asset detection patterns
        self.ASSET_PATTERNS: Dict[str, List[str]] = {
            "BTC": ["btc", "bitcoin", "#bitcoin", "#btc"],
            "ETH": ["eth", "ethereum", "#ethereum", "#eth"],
            "SOL": ["sol", "solana", "#solana", "#sol"],
        }
    
    def _get_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.bearer_token}"}
    
    def setup_stream_rules(self, assets: List[str]) -> bool:
        """Set up filtered stream rules for tracking assets."""
        if not self.bearer_token or not requests:
            return False
        
        url = f"{self.base_url}/tweets/search/stream/rules"
        headers = self._get_headers()
        
        # Build rules for each asset
        rules = []
        for asset in assets:
            if asset.upper() in ["BTC", "BITCOIN"]:
                rules.append({
                    "value": "(BTC OR Bitcoin OR #Bitcoin OR #BTC) lang:en -is:retweet",
                    "tag": "BTC"
                })
            elif asset.upper() in ["ETH", "ETHEREUM"]:
                rules.append({
                    "value": "(ETH OR Ethereum OR #Ethereum OR #ETH) lang:en -is:retweet",
                    "tag": "ETH"
                })
            elif asset.upper() in ["SOL", "SOLANA"]:
                rules.append({
                    "value": "(SOL OR Solana OR #Solana OR #SOL) lang:en -is:retweet",
                    "tag": "SOL"
                })
        
        try:
            # Delete existing rules first
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                existing = resp.json()
                if existing.get("data"):
                    delete_ids = [r["id"] for r in existing["data"]]
                    requests.post(
                        url,
                        headers=headers,
                        json={"delete": {"ids": delete_ids}},
                        timeout=10
                    )
            
            # Add new rules
            resp = requests.post(
                url,
                headers=headers,
                json={"add": rules},
                timeout=10
            )
            resp.raise_for_status()
            logger.info(f"Stream rules set: {[r['tag'] for r in rules]}")
            return True
            
        except Exception as exc:
            logger.error(f"Failed to set stream rules: {exc}")
            return False
    
    def _detect_asset(self, text: str) -> Optional[str]:
        """Detect which asset a tweet is about."""
        text_lower = text.lower()
        for asset, patterns in self.ASSET_PATTERNS.items():
            if any(p in text_lower for p in patterns):
                return asset
        return None
    
    def _process_tweet(self, tweet_data: Dict[str, Any]):
        """Process a streamed tweet for sentiment."""
        try:
            text = tweet_data.get("data", {}).get("text", "")
            matching_rules = tweet_data.get("matching_rules", [{}])
            
            # Detect asset
            asset = None
            for rule in matching_rules:
                tag = rule.get("tag")
                if tag:
                    asset = tag
                    break
            
            if not asset:
                asset = self._detect_asset(text)
            
            if not asset:
                return
            
            # Analyze with VADER
            analyzer = get_vader_analyzer()
            if not analyzer:
                return
            
            scores = analyzer.polarity_scores(text)
            compound = scores["compound"]
            
            # Store in rolling window
            entry = {
                "timestamp": datetime.now(timezone.utc),
                "compound": compound,
                "pos": scores["pos"],
                "neg": scores["neg"],
                "neu": scores["neu"],
                "text": text[:200],
            }
            
            window = self._sentiment_windows[asset]
            window.append(entry)
            if len(window) > self._window_size:
                window.pop(0)
            
            # Notify callbacks
            for callback in self._callbacks:
                try:
                    callback(asset, compound, entry)
                except Exception as _e:
                    logger.debug("stream_callback error: %s", _e)
            
            logger.debug(f"Streamed {asset}: compound={compound:+.3f}")
            
        except Exception as exc:
            logger.debug(f"Tweet processing error: {exc}")
    
    def _stream_loop(self):
        """Main streaming loop."""
        if not self.bearer_token or not requests:
            return
        
        url = f"{self.base_url}/tweets/search/stream"
        headers = self._get_headers()
        params = {
            "tweet.fields": "created_at,public_metrics",
            "expansions": "author_id",
        }
        
        logger.info("Starting Twitter stream...")
        
        while self._running:
            try:
                with requests.get(
                    url,
                    headers=headers,
                    params=params,
                    stream=True,
                    timeout=30
                ) as resp:
                    resp.raise_for_status()
                    
                    for line in resp.iter_lines():
                        if not self._running:
                            break
                        if not line:
                            continue
                        
                        try:
                            data = json.loads(line.decode("utf-8"))
                            self._process_tweet(data)
                        except json.JSONDecodeError:
                            continue
                        except Exception as exc:
                            logger.debug(f"Stream parse error: {exc}")
                            
            except requests.exceptions.RequestException as exc:
                logger.warning(f"Stream connection error: {exc}")
                time.sleep(5)  # Backoff before retry
            except Exception as exc:
                logger.error(f"Stream error: {exc}")
                time.sleep(5)
    
    def start(self, assets: List[str] = None):
        """Start the streaming handler."""
        if self._running:
            return
        
        if not self.bearer_token:
            logger.warning("Twitter bearer token not configured - streaming disabled")
            return
        
        if assets:
            self.setup_stream_rules(assets)
        
        self._running = True
        import threading
        self._stream_thread = threading.Thread(target=self._stream_loop, daemon=True)
        self._stream_thread.start()
        logger.info(f"Twitter stream started for assets: {assets or 'all'}")
    
    def stop(self):
        """Stop the streaming handler."""
        self._running = False
        if self._stream_thread:
            self._stream_thread.join(timeout=2)
        logger.info("Twitter stream stopped")
    
    def get_rolling_sentiment(self, asset: str, window: int = 50) -> Dict[str, Any]:
        """Get rolling average sentiment from stream."""
        data = self._sentiment_windows.get(asset, [])
        if not data:
            return {"score": 0.0, "volume": 0, "trend": "neutral"}
        
        recent = data[-window:] if len(data) > window else data
        scores = [d["compound"] for d in recent]
        avg_score = sum(scores) / len(scores)
        
        # Determine trend
        if len(scores) >= 10:
            first_half = sum(scores[:len(scores)//2]) / (len(scores)//2)
            second_half = sum(scores[len(scores)//2:]) / (len(scores) - len(scores)//2)
            trend = "improving" if second_half > first_half else "declining" if second_half < first_half else "stable"
        else:
            trend = "neutral"
        
        return {
            "score": round(avg_score, 4),
            "volume": len(data),
            "recent_volume": len(recent),
            "trend": trend,
            "last_update": data[-1]["timestamp"] if data else None,
        }
    
    def register_callback(self, callback: Callable[[str, float, Dict], None]):
        """Register a callback for new tweets.
        
        Callback receives: (asset, compound_score, full_entry)
        """
        self._callbacks.append(callback)
    
    def unregister_callback(self, callback: Callable[[str, float, Dict], None]):
        """Unregister a callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)


# Streaming singleton accessor
_stream_handler: Optional[TwitterStreamHandler] = None

def get_twitter_stream_handler() -> TwitterStreamHandler:
    """Get the singleton TwitterStreamHandler instance."""
    global _stream_handler
    if _stream_handler is None:
        _stream_handler = TwitterStreamHandler()
    return _stream_handler


# Import needed for streaming
import threading
import time
import json
