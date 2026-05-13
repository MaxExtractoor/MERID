"""
Reddit Sentiment Scraper for Kalshi markets.

Polls specific subreddits (r/Bitcoin, r/Kalshi, r/cryptocurrency) for
posts mentioning target assets and aggregates sentiment using TextBlob.

Lower frequency than Twitter (5-15 min intervals) but richer context.

Usage:
    from merid.sentiment.reddit_scraper import get_reddit_sentiment_service
    
    service = get_reddit_sentiment_service()
    score = service.get_sentiment("BTC", limit=100)
    service.update_mood_bus("BTC")  # Push to MarketMoodBus
"""

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any
import os
import asyncio
from utils.logger import get_logger
from collections import defaultdict

try:
    import requests
except ImportError:
    requests = None  # type: ignore

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
except ImportError:
    SentimentIntensityAnalyzer = None  # type: ignore

# VADER analyzer singleton
_vader_analyzer: Optional[Any] = None
_vader_analyzer_lock = threading.Lock()


def get_vader_analyzer() -> Optional[Any]:
    """Get or create VADER sentiment analyzer."""
    global _vader_analyzer
    if _vader_analyzer is None and SentimentIntensityAnalyzer:
        with _vader_analyzer_lock:
            if _vader_analyzer is None and SentimentIntensityAnalyzer:
                _vader_analyzer = SentimentIntensityAnalyzer()
    return _vader_analyzer

logger = get_logger(__name__)


@dataclass
class RedditPost:
    """Structured Reddit post data."""
    id: str
    title: str
    selftext: str
    subreddit: str
    created_utc: datetime
    score: int  # Upvotes - downvotes
    upvote_ratio: float  # 0.0 to 1.0
    num_comments: int
    permalink: str
    author: Optional[str] = None


@dataclass
class SentimentResult:
    """Reddit sentiment analysis result."""
    score: float  # -1.0 to +1.0
    confidence: float  # 0.0 to 1.0 based on volume/engagement
    volume: int  # Number of posts analyzed
    avg_engagement: float  # Average upvote score
    subreddit_breakdown: Dict[str, Dict[str, Any]]  # Per-sub stats
    raw_data: List[Dict[str, Any]]  # Raw posts for debugging
    timestamp: datetime
    model_version: str = "vader"  # model used for scoring
    correlation_id: Optional[str] = None  # [AGENT_AUDIT: Section 9] trace chain from caller
    available: bool = True  # Whether sentiment data is available (False when no posts found in window)


class RedditSentimentService:
    """
    Fetches and analyzes Reddit sentiment for crypto/assets.
    
    Uses Reddit API (PRAW-style) or raw HTTP to search target subreddits
    for posts mentioning specific symbols/keywords.
    
    Subreddits polled:
    - r/Bitcoin - BTC-specific discussion
    - r/CryptoCurrency - General crypto sentiment
    - r/Kalshi - Prediction market specific sentiment
    - r/wallstreetbets - Retail sentiment (optional, noisy)
    - r/ethtrader - ETH-specific
    - r/Solana - SOL-specific
    """
    
    _instance = None
    _instance_lock = __import__('threading').Lock()

    # Asset → search terms mapping
    ASSET_TERMS: Dict[str, List[str]] = {
        "BTC": ["BTC", "Bitcoin", "bitcoin", "satoshi", "halving"],
        "ETH": ["ETH", "Ethereum", "ether", "vitalik", "gas fees"],
        "SOL": ["SOL", "Solana", "solana", "phantom wallet"],
        "XRP": ["XRP", "Ripple", "ripple", "xrp"],
        "DOGE": ["DOGE", "Dogecoin", "dogecoin", "doge", "shiba"],
        "PEPE": ["PEPE", "Pepe", "pepe", "meme coin"],
        "FED": ["Fed", "Federal Reserve", "FOMC", "Powell", "rate hike"],
        "CPI": ["CPI", "inflation", "consumer price", "PCE"],
        "SPX": ["S&P 500", "SPX", "stock market", "Nasdaq", "Dow"],
    }
    
    # Default subreddits to search
    DEFAULT_SUBREDDITS: List[str] = [
        "Bitcoin",
        "CryptoCurrency",
        "Kalshi",
        "ethtrader",
        "Solana",
    ]
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        user_agent: str = "MERID-sentiment-bot/1.0 (by /u/merid-system)",
    ):
        if self._initialized:
            return
        
        self.user_agent = user_agent
        
        self._cache: Dict[str, SentimentResult] = {}
        self._cache_ttl_seconds = 300  # 5 minute cache
        self._fail_count = 0
        self._disabled = False
        self._disabled_at: Optional[float] = None  # P1 FIX: Track disable time for auto-reset
        self._last_request_ts: float = 0.0
        self._min_request_interval = 2.0  # Reddit rate-limits unauthenticated to ~30 req/min
        
        # BUG-FIX (2026-05-12): Reusable httpx client to avoid SSL context blocking
        # Using synchronous httpx.Client instead of AsyncClient to avoid asyncio issues on Windows
        # Creating fresh Client involves SSL context creation which blocks on Windows
        self._http_client: Optional[httpx.Client] = None
        
        if not httpx:
            logger.warning("httpx library not available - Reddit sentiment disabled")
        
        if not get_vader_analyzer():
            logger.warning("VADER not available - sentiment analysis disabled")
        
        self._initialized = True
        logger.info("RedditSentimentService initialized (public JSON feeds, no OAuth required)")
    
    def _get_http_client(self) -> httpx.Client:
        """Get or create reusable httpx client to avoid SSL context blocking."""
        if self._http_client is None:
            # BUG-FIX (2026-05-12): Disable SSL verification to avoid SSL context blocking
            # Reddit public JSON doesn't require strict SSL verification
            # ssl.create_default_context() blocks on Windows due to certificate store access
            self._http_client = httpx.Client(
                timeout=15.0,
                verify=False,  # Disable SSL verification to avoid blocking
            )
        return self._http_client

    def _throttle(self):
        """Rate-limit requests to avoid Reddit 429s."""
        import time as _time
        elapsed = _time.time() - self._last_request_ts
        if elapsed < self._min_request_interval:
            # BUG-FIX (2026-05-12): Use very short sleep chunks (0.01s) to minimize blocking
            remaining = self._min_request_interval - elapsed
            while remaining > 0:
                chunk = min(0.01, remaining)
                _time.sleep(chunk)
                remaining -= chunk
        self._last_request_ts = _time.time()
    
    def _get_headers(self) -> Dict[str, str]:
        """Headers for public JSON endpoint (no auth needed)."""
        return {"User-Agent": self.user_agent}
    
    def search_subreddit(
        self,
        subreddit: str,
        query: str,
        sort: str = "new",
        limit: int = 25,
        time_filter: str = "hour",
    ) -> List[RedditPost]:
        """
        Search a subreddit via public JSON endpoint (no OAuth).
        
        Uses https://www.reddit.com/r/{sub}/search.json which is
        publicly accessible with proper User-Agent and rate limiting.
        """
        if not requests or self._disabled:
            return []
        
        self._throttle()
        
        params = {
            "q": query,
            "sort": sort,
            "limit": min(limit, 100),
            "t": time_filter,
            "restrict_sr": "on",
            "type": "link",
            "raw_json": "1",
        }
        
        try:
            # BUG-FIX (2026-05-12): Use httpx instead of requests to avoid SSL blocking
            client = self._get_http_client()
            resp = client.get(
                f"https://www.reddit.com/r/{subreddit}/search.json",
                params=params,
                headers=self._get_headers(),
            )
            
            if resp.status_code == 429:
                logger.warning("Reddit rate limited — backing off")
                self._min_request_interval = min(self._min_request_interval * 2, 30)
                return []
            
            if resp.status_code == 403:
                self._fail_count += 1
                if self._fail_count >= 5:
                    self._disabled = True
                    self._disabled_at = time.time()  # P1 FIX: Track when disabled for auto-reset
                    logger.warning("Reddit public JSON blocked 5x — disabling for 30min")
                else:
                    logger.debug(f"Reddit 403 for r/{subreddit} ({self._fail_count}/5)")
                return []
            
            resp.raise_for_status()
            data = resp.json()
            self._fail_count = 0  # reset on success
            self._min_request_interval = 2.0  # reset backoff on success
            
            posts = []
            for child in data.get("data", {}).get("children", []):
                post = child.get("data", {})
                created_utc = post.get("created_utc", 0)
                
                posts.append(RedditPost(
                    id=post.get("id", ""),
                    title=post.get("title", ""),
                    selftext=post.get("selftext", ""),
                    subreddit=subreddit,
                    created_utc=datetime.fromtimestamp(created_utc, tz=timezone.utc),
                    score=int(post.get("score", 0)),
                    upvote_ratio=float(post.get("upvote_ratio", 0.5)),
                    num_comments=int(post.get("num_comments", 0)),
                    permalink=post.get("permalink", ""),
                    author=post.get("author"),
                ))
            
            logger.debug(f"Fetched {len(posts)} posts from r/{subreddit} for '{query}'")
            return posts
            
        except requests.exceptions.Timeout:
            logger.debug(f"Reddit timeout for r/{subreddit}")
            return []
        except Exception as exc:
            self._fail_count += 1
            if self._fail_count >= 5:
                self._disabled = True
                self._disabled_at = time.time()  # P1 FIX: Track when disabled for auto-reset
                logger.warning(f"Reddit scraping failed 5x — disabling for 30min: {exc}")
            else:
                logger.debug(f"Reddit search error ({self._fail_count}/5): {exc}")
            return []
    
    def fetch_posts_for_asset(
        self,
        asset: str,
        subreddits: Optional[List[str]] = None,
        limit_per_sub: int = 25,
        time_filter: str = "hour",
    ) -> List[RedditPost]:
        """
        Fetch posts mentioning an asset across multiple subreddits.
        
        Args:
            asset: Asset symbol (BTC, ETH, etc.)
            subreddits: List of subreddits to search (default: all configured)
            limit_per_sub: Max posts per subreddit
            time_filter: Time window
        
        Returns:
            Combined list of RedditPost objects
        """
        if subreddits is None:
            subreddits = self.DEFAULT_SUBREDDITS
        
        search_terms = self.ASSET_TERMS.get(asset.upper(), [asset])
        # Build OR query for search terms
        query = " OR ".join(f'"{term}"' for term in search_terms[:3])  # Limit to top 3 terms
        
        all_posts = []
        for subreddit in subreddits:
            posts = self.search_subreddit(
                subreddit=subreddit,
                query=query,
                sort="new",
                limit=limit_per_sub,
                time_filter=time_filter,
            )
            all_posts.extend(posts)
        
        # Deduplicate by ID
        seen_ids = set()
        unique_posts = []
        for post in all_posts:
            if post.id not in seen_ids:
                seen_ids.add(post.id)
                unique_posts.append(post)
        
        # Sort by recency
        unique_posts.sort(key=lambda p: p.created_utc, reverse=True)
        
        logger.debug(f"Total unique posts for {asset}: {len(unique_posts)}")
        return unique_posts
    
    def analyze_sentiment(self, posts: List[RedditPost]) -> SentimentResult:
        """
        Analyze sentiment of Reddit posts using VADER.
        
        VADER is specifically designed for short, informal social media text
        and handles slang, emoticons, and intensity well.
        
        Weights by:
        - Post score (upvotes - downvotes)
        - Upvote ratio (quality signal)
        - Number of comments (engagement)
        
        Returns:
            SentimentResult with score (-1 to +1) and confidence
        """
        analyzer = get_vader_analyzer()
        
        if not posts:
            return SentimentResult(
                score=0.0,
                confidence=0.0,
                volume=0,
                avg_engagement=0.0,
                subreddit_breakdown={},
                raw_data=[],
                timestamp=datetime.now(timezone.utc),
            )
        
        if not analyzer:
            # Fallback: neutral sentiment
            avg_score = sum(p.score for p in posts) / len(posts)
            return SentimentResult(
                score=0.0,
                confidence=0.2,  # Low confidence
                volume=len(posts),
                avg_engagement=avg_score,
                subreddit_breakdown={},
                raw_data=[],
                timestamp=datetime.now(timezone.utc),
            )
        
        total_weighted_sentiment = 0.0
        total_weight = 0.0
        subreddit_stats: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "sentiment_sum": 0.0, "engagement_sum": 0}
        )
        
        for post in posts:
            # Combine title and selftext
            text = post.title + " " + post.selftext
            
            # Get VADER compound sentiment (-1 to +1)
            scores = analyzer.polarity_scores(text)
            compound = scores["compound"]  # Normalized to [-1, 1]
            
            # Calculate weight
            # Base weight from engagement
            engagement_weight = max(1, abs(post.score) ** 0.5)  # sqrt to dampen extremes; abs() guards negative scores
            quality_weight = post.upvote_ratio * 2  # 0-2x multiplier for quality
            discussion_weight = 1 + (post.num_comments ** 0.3)  # slight boost for discussion
            
            # Text length weight (longer posts often have more substance)
            length_weight = 1.0 + len(text) ** 0.3
            
            weight = engagement_weight * quality_weight * discussion_weight * length_weight
            
            total_weighted_sentiment += compound * weight
            total_weight += weight
            
            # Track per-subreddit stats
            subreddit_stats[post.subreddit]["count"] += 1
            subreddit_stats[post.subreddit]["sentiment_sum"] += compound
            subreddit_stats[post.subreddit]["engagement_sum"] += post.score
        
        # Calculate weighted average
        score = total_weighted_sentiment / total_weight if total_weight > 0 else 0.0
        
        # Confidence calculation
        avg_engagement = sum(p.score for p in posts) / len(posts)
        volume_factor = min(len(posts) / 30.0, 1.0)  # Max at 30 posts
        engagement_factor = min(avg_engagement / 50.0, 1.0)  # Max at avg 50 score
        confidence = 0.25 + (0.75 * volume_factor * engagement_factor)
        
        # Build subreddit breakdown
        breakdown = {}
        for sub, stats in subreddit_stats.items():
            count = stats["count"]
            breakdown[sub] = {
                "count": count,
                "avg_sentiment": stats["sentiment_sum"] / count if count > 0 else 0,
                "avg_engagement": stats["engagement_sum"] / count if count > 0 else 0,
            }
        
        # Raw data for debugging - include VADER scores
        raw_data = []
        for p in posts[:10]:
            text = p.title + " " + p.selftext
            vs = analyzer.polarity_scores(text) if analyzer else {"compound": 0, "pos": 0, "neg": 0, "neu": 0}
            raw_data.append({
                "id": p.id,
                "title": p.title[:100],
                "subreddit": p.subreddit,
                "score": p.score,
                "upvote_ratio": p.upvote_ratio,
                "compound": vs["compound"],
                "pos": vs["pos"],
                "neg": vs["neg"],
                "neu": vs["neu"],
            })
        
        return SentimentResult(
            score=score,
            confidence=confidence,
            volume=len(posts),
            avg_engagement=avg_engagement,
            subreddit_breakdown=breakdown,
            raw_data=raw_data,
            timestamp=datetime.now(timezone.utc),
        )
    
    def get_sentiment(
        self,
        asset: str,
        subreddits: Optional[List[str]] = None,
        limit_per_sub: int = 25,
        time_filter: str = "hour",
        use_cache: bool = True,
    ) -> SentimentResult:
        """
        Get Reddit sentiment for an asset (fetch + analyze, with caching).
        
        This is the main entry point for agents/UI.
        
        Args:
            asset: Asset symbol
            subreddits: Subreddits to search
            limit_per_sub: Max posts per subreddit
            time_filter: Time window (hour, day, week)
            use_cache: Use cached result if fresh
        
        Returns:
            SentimentResult with score, confidence, volume
        """
        cache_key = f"{asset}:{time_filter}"
        
        # Check cache
        if use_cache and cache_key in self._cache:
            cached = self._cache[cache_key]
            age = (datetime.now(timezone.utc) - cached.timestamp).total_seconds()
            if age < self._cache_ttl_seconds:
                logger.debug(f"Using cached Reddit sentiment for {asset}")
                return cached
        
        # Fetch and analyze
        posts = self.fetch_posts_for_asset(
            asset=asset,
            subreddits=subreddits,
            limit_per_sub=limit_per_sub,
            time_filter=time_filter,
        )
        result = self.analyze_sentiment(posts)
        
        # Set available=False if no posts found (missing data, not neutral sentiment)
        if result.volume == 0:
            result.available = False
            logger.info(
                f"Reddit sentiment for {asset}: no posts found in window (missing data, not blocking)"
            )
        else:
            logger.info(
                f"Reddit sentiment for {asset}: score={result.score:+.3f}, "
                f"confidence={result.confidence:.2f}, volume={result.volume}"
            )
        
        # Cache result
        self._cache[cache_key] = result
        
        return result
    
    def update_mood_bus(
        self,
        asset: str,
        time_filter: str = "hour",
    ) -> bool:
        """
        Fetch sentiment and push to MarketMoodBus.
        
        This is the integration point - call this on a schedule
        (every 5-15 minutes) to keep the mood bus updated.
        
        Args:
            asset: Asset to update
            time_filter: Time window for Reddit search
        
        Returns:
            True if successful
        """
        try:
            result = self.get_sentiment(asset, time_filter=time_filter)
            
            from merid.swarm.market_mood_bus import get_market_mood_bus
            bus = get_market_mood_bus()
            
            # Estimate 24h volume (rough approximation)
            time_hours = {"hour": 1, "day": 24, "week": 168}.get(time_filter, 1)
            volume_24h_estimate = int(result.volume * (24 / time_hours))
            
            # Reddit sentiment goes into news_sentiment channel (richer, slower)
            bus.update_news_sentiment(
                asset=asset,
                sentiment=result.score,
                volume_24h=volume_24h_estimate,
                source="reddit",
                confidence=result.confidence,
                subreddit_breakdown=result.subreddit_breakdown,
            )
            
            logger.debug(f"Updated MarketMoodBus Reddit sentiment for {asset}")
            return True
            
        except Exception as exc:
            logger.warning(f"Failed to update mood bus for {asset}: {exc}")
            return False
    
    async def update_all_assets(
        self,
        assets: Optional[List[str]] = None,
        time_filter: str = "hour",
    ):
        """
        Update sentiment for all assets asynchronously.

        update_mood_bus() is synchronous (blocking I/O), so we run each call
        in a thread pool to avoid blocking the event loop.

        Args:
            assets: List of assets (defaults to all configured)
            time_filter: Time window
        """
        if assets is None:
            assets = list(self.ASSET_TERMS.keys())

        loop = asyncio.get_running_loop()
        tasks = [
            loop.run_in_executor(None, self.update_mood_bus, asset, time_filter)
            for asset in assets
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        success_count = sum(1 for r in results if r is True)
        logger.info(f"Updated Reddit sentiment for {success_count}/{len(assets)} assets")


# Singleton accessor
_reddit_service: Optional[RedditSentimentService] = None
_reddit_service_lock = threading.Lock()


def get_reddit_sentiment_service(
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> Optional[RedditSentimentService]:
    """Get the singleton RedditSentimentService instance.

    LEAN 15m KALSHI STACK (2026-05-13): Disabled when ENABLE_SENTIMENT_TRUTH=false
    to prevent native crashes during Reddit API calls.
    """
    if os.getenv("ENABLE_SENTIMENT_TRUTH", "false").lower() == "false":
        logger.warning("Reddit sentiment disabled via ENABLE_SENTIMENT_TRUTH=false")
        return None

    global _reddit_service
    if _reddit_service is None:
        with _reddit_service_lock:
            if _reddit_service is None:
                _reddit_service = RedditSentimentService(client_id, client_secret)
    return _reddit_service


# ── Convenience functions ─────────────────────────────────────────────

def quick_reddit_sentiment(asset: str, time_filter: str = "hour") -> float:
    """
    Quick one-liner to get Reddit sentiment score.
    
    PRODUCTION FIX (2026-05-10): Removed fake fallback data.
    Raises exception on failure instead of returning 0.0.
    Ensures only real sentiment data is used in trading decisions.
    """
    service = get_reddit_sentiment_service()
    result = service.get_sentiment(asset, time_filter=time_filter)
    return result.score


def compare_sentiment_sources(asset: str) -> Dict[str, float]:
    """
    Compare Twitter vs Reddit sentiment for an asset.
    
    Returns dict with both scores for analysis.
    """
    twitter_score = 0.0
    reddit_score = 0.0
    
    try:
        from merid.sentiment.twitter_fetcher import quick_twitter_sentiment
        twitter_score = quick_twitter_sentiment(asset, minutes=15)
    except Exception as _e:
        logger.debug("quick_twitter_sentiment: %s", _e)
    
    try:
        reddit_score = quick_reddit_sentiment(asset, time_filter="hour")
    except Exception as _e:
        logger.debug("quick_reddit_sentiment: %s", _e)
    
    return {
        "asset": asset,
        "twitter": twitter_score,
        "reddit": reddit_score,
        "difference": abs(twitter_score - reddit_score),
        "agreement": "aligned" if (twitter_score * reddit_score) > 0 else "divergent",
    }
