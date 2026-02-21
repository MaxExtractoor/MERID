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

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any
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
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        user_agent: str = "MERID-sentiment-bot/1.0",
    ):
        if self._initialized:
            return
        
        self.client_id = client_id or os.getenv("REDDIT_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("REDDIT_CLIENT_SECRET")
        self.user_agent = user_agent
        self.access_token: Optional[str] = None
        self.token_expires: Optional[datetime] = None
        
        self._cache: Dict[str, SentimentResult] = {}
        self._cache_ttl_seconds = 300  # 5 minute cache (slower than Twitter)
        
        # Try to get access token on init
        if self.client_id and self.client_secret and requests:
            self._refresh_token()
        else:
            logger.warning("Reddit API credentials not configured - sentiment will return 0")
        
        if not TextBlob:
            logger.warning("TextBlob not available - sentiment analysis disabled")
        
        self._initialized = True
        logger.info("RedditSentimentService initialized")
    
    def _refresh_token(self) -> bool:
        """Refresh Reddit OAuth token."""
        if not requests:
            return False
        
        try:
            auth = requests.auth.HTTPBasicAuth(self.client_id, self.client_secret)
            headers = {"User-Agent": self.user_agent}
            data = {
                "grant_type": "client_credentials",
            }
            
            resp = requests.post(
                "https://www.reddit.com/api/v1/access_token",
                auth=auth,
                headers=headers,
                data=data,
                timeout=10,
            )
            resp.raise_for_status()
            
            token_data = resp.json()
            self.access_token = token_data.get("access_token")
            expires_in = token_data.get("expires_in", 3600)
            self.token_expires = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)
            
            logger.debug("Reddit OAuth token refreshed")
            return True
            
        except Exception as exc:
            logger.warning(f"Reddit token refresh failed: {exc}")
            return False
    
    def _get_headers(self) -> Dict[str, str]:
        """Get headers for Reddit API."""
        # Check if token needs refresh
        if not self.access_token or (self.token_expires and datetime.now(timezone.utc) > self.token_expires):
            self._refresh_token()
        
        return {
            "User-Agent": self.user_agent,
            "Authorization": f"bearer {self.access_token}" if self.access_token else "",
        }
    
    def search_subreddit(
        self,
        subreddit: str,
        query: str,
        sort: str = "new",
        limit: int = 25,
        time_filter: str = "hour",  # hour, day, week, month, year, all
    ) -> List[RedditPost]:
        """
        Search a subreddit for posts matching query.
        
        Args:
            subreddit: Subreddit name (without r/)
            query: Search query
            sort: Sort order (relevance, hot, top, new, comments)
            limit: Max results (max 100)
            time_filter: Time window for search
        
        Returns:
            List of RedditPost objects
        """
        if not requests:
            return []
        
        # Ensure we have a valid token
        if not self.access_token:
            if not self._refresh_token():
                return []
        
        params = {
            "q": query,
            "sort": sort,
            "limit": min(limit, 100),
            "t": time_filter,
            "restrict_sr": "true",  # Restrict to this subreddit
        }
        
        try:
            resp = requests.get(
                f"https://oauth.reddit.com/r/{subreddit}/search",
                params=params,
                headers=self._get_headers(),
                timeout=15,
            )
            
            if resp.status_code == 401:
                # Token expired, try refreshing
                if self._refresh_token():
                    resp = requests.get(
                        f"https://oauth.reddit.com/r/{subreddit}/search",
                        params=params,
                        headers=self._get_headers(),
                        timeout=15,
                    )
            
            if resp.status_code == 429:
                logger.warning("Reddit API rate limited")
                return []
            
            resp.raise_for_status()
            data = resp.json()
            
            posts = []
            for child in data.get("data", {}).get("children", []):
                post = child.get("data", {})
                
                created_utc = post.get("created_utc", 0)
                
                posts.append(RedditPost(
                    id=post.get("id", ""),
                    title=post.get("title", ""),
                    selftext=post.get("selftext", ""),
                    subreddit=subreddit,
                    created_utc=datetime.utcfromtimestamp(created_utc),
                    score=post.get("score", 0),
                    upvote_ratio=post.get("upvote_ratio", 0.5),
                    num_comments=post.get("num_comments", 0),
                    permalink=post.get("permalink", ""),
                    author=post.get("author"),
                ))
            
            logger.debug(f"Fetched {len(posts)} posts from r/{subreddit} for '{query}'")
            return posts
            
        except requests.exceptions.Timeout:
            logger.warning(f"Reddit API timeout for r/{subreddit}")
            return []
        except Exception as exc:
            logger.warning(f"Reddit search error: {exc}")
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
            engagement_weight = max(1, post.score ** 0.5)  # sqrt to dampen extremes
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
        
        # Cache result
        self._cache[cache_key] = result
        
        logger.info(
            f"Reddit sentiment for {asset}: score={result.score:+.3f}, "
            f"confidence={result.confidence:.2f}, volume={result.volume}"
        )
        
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
        
        Args:
            assets: List of assets (defaults to all configured)
            time_filter: Time window
        """
        if assets is None:
            assets = list(self.ASSET_TERMS.keys())
        
        # Run updates concurrently
        tasks = [self.update_mood_bus(asset, time_filter) for asset in assets]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        success_count = sum(1 for r in results if r is True)
        logger.info(f"Updated Reddit sentiment for {success_count}/{len(assets)} assets")


# Singleton accessor
def get_reddit_sentiment_service(
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> RedditSentimentService:
    """Get the singleton RedditSentimentService instance."""
    return RedditSentimentService(client_id, client_secret)


# ── Convenience functions ─────────────────────────────────────────────

def quick_reddit_sentiment(asset: str, time_filter: str = "hour") -> float:
    """
    Quick one-liner to get Reddit sentiment score.
    
    Returns sentiment score (-1 to +1) or 0.0 if unavailable.
    """
    try:
        service = get_reddit_sentiment_service()
        result = service.get_sentiment(asset, time_filter=time_filter)
        return result.score
    except Exception as _e:
        logger.debug("get_reddit_sentiment_score(%s) failed: %s", asset, _e)
        return 0.0


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
