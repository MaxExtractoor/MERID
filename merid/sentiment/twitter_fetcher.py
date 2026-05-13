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

import re
import threading
import time
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Any
import os
import asyncio
from utils.logger import get_logger
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
class TweetData:
    """Structured tweet data."""
    id: str
    text: str
    created_at: datetime
    like_count: int
    retweet_count: int
    reply_count: int
    author_id: Optional[str] = None
    source: str = "api"  # "api" | "nitter_scrape" — used to gate confidence


@dataclass
class SentimentResult:
    """Sentiment analysis result."""
    score: float  # -1.0 to +1.0
    confidence: float  # 0.0 to 1.0 based on volume/engagement
    volume: int  # Number of tweets/posts analyzed
    avg_engagement: float  # Average engagement score
    raw_data: List[Dict[str, Any]]  # Raw tweets/posts for debugging
    timestamp: datetime
    model_version: str = "vader"  # model used for scoring; "vader" or "vader/nitter_scrape"
    available: bool = True  # Whether sentiment data is available (False when no posts found in window)


class TwitterSentimentService:
    """
    Fetches and analyzes Twitter/X sentiment for crypto assets.
    
    Uses Twitter API v2 recent search endpoint with keyword queries
    tailored to Kalshi market assets (BTC, ETH, SOL, etc.).
    """
    
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
    }
    
    def __new__(cls, *args, **kwargs):
        global _twitter_service
        if _twitter_service is None:
            with _twitter_service_lock:
                if _twitter_service is None:
                    _twitter_service = super().__new__(cls)
                    _twitter_service._initialized = False
        return _twitter_service

    def __init__(self, bearer_token: Optional[str] = None):
        if self._initialized:
            return
        
        raw_token = bearer_token or os.getenv("X_BEARER_TOKEN") or os.getenv("TWITTER_BEARER_TOKEN")
        # URL-decode if the token was pasted with %XX sequences (e.g. %3D → =)
        if raw_token and "%" in raw_token:
            from urllib.parse import unquote
            raw_token = unquote(raw_token)
        self.bearer_token = raw_token
        self.base_url = "https://api.twitter.com/2"
        self._cache: Dict[str, SentimentResult] = {}
        self._cache_ttl_seconds = 900  # 15 min cache — matches Free tier 1 req/15min limit

        # Free tier: GET /2/tweets/search/recent = 1 request per 15 min
        self._last_api_call = 0.0
        self._api_min_interval = 900  # 15 minutes between API calls
        self._asset_round_robin_idx = 0  # rotate which asset gets the API call
        
        if not self.bearer_token:
            logger.warning("X bearer token not configured (set X_BEARER_TOKEN in .env) — sentiment will return 0")
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
        
        # Free tier: 1 request per 15 min — enforce globally
        now = time.time()
        elapsed = now - self._last_api_call
        if elapsed < self._api_min_interval:
            remaining = int(self._api_min_interval - elapsed)
            logger.debug("X Free tier rate limit: %ds until next search/recent call", remaining)
            return []
        
        # Buffer end_time 30s behind now (X API rejects times too close to present)
        end_time = datetime.now(timezone.utc) - timedelta(seconds=30)
        start_time = end_time - timedelta(minutes=minutes)
        
        query = self._build_query(asset, additional_terms)
        
        # Free tier: max_results 10-100, 512 char query limit, core operators only
        params = {
            "query": query[:512],
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
            
            self._last_api_call = time.time()  # record BEFORE checking status

            if resp.status_code == 429:
                logger.debug("X API rate limited (429) — will retry after 15 min cooldown")
                return []
            
            if resp.status_code == 401:
                logger.warning("X API unauthorized - check X_BEARER_TOKEN in .env")
                return []

            if resp.status_code == 403:
                logger.debug(
                    "X API 403 Forbidden for %s — Free tier may not include "
                    "search/recent or app lacks proper access level. "
                    "Falling back to scrape.",
                    asset,
                )
                return []

            if resp.status_code == 400:
                body = resp.text[:200] if resp.text else "(empty)"
                logger.warning("X API 400 Bad Request for %s: %s", asset, body)
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
        
        # If all tweets came from the Nitter scrape path they have no real
        # engagement metadata (like_count=0, retweet_count=0), so the
        # engagement_factor collapses to near-zero and confidence is already
        # low.  Enforce a hard ceiling of 0.3 to make the quality boundary
        # explicit and tag the model_version so consumers can filter.
        is_scrape_only = all(getattr(t, "source", "api") == "nitter_scrape" for t in tweets)
        if is_scrape_only:
            confidence = min(confidence, 0.3)
        mv = "vader/nitter_scrape" if is_scrape_only else "vader"

        return SentimentResult(
            score=score,
            confidence=confidence,
            volume=len(tweets),
            avg_engagement=avg_engagement,
            raw_data=raw_data,
            timestamp=datetime.now(timezone.utc),
            model_version=mv,
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
            
        NOTE: If Twitter API fails, returns neutral sentiment (score=0.0, confidence=0.0)
        with default multiplier behavior. This is a graceful fallback - not a hard failure.
        """
        import os
        # Skip Twitter sentiment if disabled via env var
        if os.getenv("DISABLE_TWITTER_SENTIMENT", "").lower() in ("1", "true", "yes"):
            logger.debug(f"[twitter_disabled] Twitter sentiment disabled via env var for {asset} - skipping")
            # Return unavailable sentiment immediately (no delay)
            return SentimentResult(
                score=0.0,
                confidence=0.0,
                volume=0,
                avg_engagement=0.0,
                raw_data=[],
                timestamp=datetime.now(timezone.utc),
                model_version="disabled",
                available=False,
            )
        
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
        
        # Fallback: if Twitter API failed (no tweets), use Reddit sentiment as real data source
        if result.volume == 0 and result.score == 0.0:
            # Rate limit warning to once per minute per asset to prevent log spam
            _last_warning_key = f"_twitter_fallback_warn_{asset}"
            _last_warning_time = getattr(self, _last_warning_key, 0)
            if time.time() - _last_warning_time > 60:
                setattr(self, _last_warning_key, time.time())
                logger.warning(
                    f"[twitter_fallback] Twitter API failed for {asset}, "
                    f"falling back to Reddit sentiment for real data"
                )
            # Fall back to Reddit sentiment (real data, not fake neutral)
            try:
                from merid.sentiment.reddit_scraper import RedditSentimentService, get_reddit_sentiment_service
                import os
                if os.getenv("ENABLE_SENTIMENT_TRUTH", "false").lower() == "false":
                    logger.warning("Reddit sentiment disabled via ENABLE_SENTIMENT_TRUTH=false, skipping fallback")
                    return 0.0
                reddit_service = get_reddit_sentiment_service()
                if reddit_service is None:
                    logger.warning("Reddit sentiment service unavailable, skipping fallback")
                    return 0.0
                # Map minutes to time_filter: 15m -> hour, 60m -> day
                time_filter = "hour" if minutes <= 60 else "day"
                # Clean asset symbol: strip # prefix and map hashtag variants to clean symbols
                clean_asset = asset.lstrip('#')
                # Map common hashtag variants to clean asset symbols
                hashtag_to_asset = {
                    "BTCUSD": "BTC", "BitcoinPrice": "BTC", "Bitcoin": "BTC",
                    "ETHUSD": "ETH", "EthereumPrice": "ETH", "Ethereum": "ETH",
                    "SOLUSD": "SOL", "SolanaPrice": "SOL", "Solana": "SOL",
                    "XRPUSD": "XRP", "RipplePrice": "XRP", "Ripple": "XRP",
                    "DOGEUSD": "DOGE", "DogecoinPrice": "DOGE", "Dogecoin": "DOGE", "DogecoinToTheMoon": "DOGE",
                }
                clean_asset = hashtag_to_asset.get(clean_asset, clean_asset)
                reddit_result = reddit_service.get_sentiment(clean_asset, time_filter=time_filter)
                
                # If Reddit has no posts, return result with available=False (non-fatal)
                if reddit_result.volume == 0:
                    logger.info(
                        f"[twitter_fallback] No Reddit posts for {asset} (missing data, not blocking)"
                    )
                    result = SentimentResult(
                        score=0.0,
                        confidence=0.0,
                        volume=0,
                        avg_engagement=0.0,
                        raw_data=[],
                        timestamp=datetime.now(timezone.utc),
                        model_version="no_data",
                        available=False,
                    )
                else:
                    # Use Reddit sentiment as fallback
                    logger.info(
                        f"[twitter_fallback] Using Reddit sentiment for {asset}: "
                        f"score={reddit_result.score:+.3f}, confidence={reddit_result.confidence:.2f}, "
                        f"volume={reddit_result.volume}"
                    )
                    result = SentimentResult(
                        score=reddit_result.score,
                        confidence=reddit_result.confidence * 0.8,  # Slightly lower confidence for cross-source
                        volume=reddit_result.volume,
                        avg_engagement=reddit_result.avg_engagement,
                        raw_data=reddit_result.raw_data,
                        timestamp=reddit_result.timestamp,
                        model_version="reddit_fallback",
                        available=reddit_result.available,
                    )
            except Exception as e:
                logger.info(
                    f"[twitter_fallback] Reddit fallback failed for {asset}: {e} (missing data, not blocking)"
                )
                # If Reddit fallback fails, return no data with available=False (non-fatal)
                result = SentimentResult(
                    score=0.0,
                    confidence=0.0,
                    volume=0,
                    avg_engagement=0.0,
                    raw_data=[],
                    timestamp=datetime.now(timezone.utc),
                    model_version="no_data",
                    available=False,
                )
        
        # Cache result
        self._cache[cache_key] = result
        
        logger.debug(
            f"Twitter sentiment for {asset}: score={result.score:+.3f}, "
            f"confidence={result.confidence:.2f}, volume={result.volume}"
        )
        
        return result
    
    def update_mood_bus(self, asset: str, minutes: int = 15) -> bool:
        """
        Fetch sentiment and push to MarketMoodBus.
        
        Uses get_sentiment_with_fallback so API credits are preserved:
        API first → scrape fallback → neutral if both fail.
        
        Args:
            asset: Asset to update
            minutes: Tweet lookback window
        
        Returns:
            True if successful
        """
        try:
            result = self.get_sentiment_with_fallback(asset, minutes=minutes)
            
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
        Update sentiment for ONE asset per call (round-robin).

        Free tier allows only 1 search/recent request per 15 minutes,
        so we rotate through assets one at a time. Each call updates
        the next asset in the rotation. Full cycle takes ~150 min for
        10 assets.

        Args:
            assets: List of assets (defaults to all configured)
            minutes: Tweet lookback window
        """
        if assets is None:
            assets = list(self.ASSET_QUERIES.keys())

        if not assets:
            return

        # Pick the next asset in rotation
        idx = self._asset_round_robin_idx % len(assets)
        asset = assets[idx]
        self._asset_round_robin_idx = idx + 1

        # BUG-FIX (2026-05-12): update_mood_bus is now synchronous with httpx.Client
        # Offload to executor to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        ok = await loop.run_in_executor(None, self.update_mood_bus, asset, minutes)
        if ok:
            logger.info(f"X sentiment updated for {asset} (round-robin {idx + 1}/{len(assets)})")
        else:
            logger.debug(f"X sentiment skipped for {asset} (rate-limited or no data)")
    
    def get_multi_asset_sentiment(
        self,
        assets: List[str],
        minutes: int = 15,
    ) -> Dict[str, SentimentResult]:
        """Get sentiment for multiple assets."""
        results = {}
        for asset in assets:
            results[asset] = self.get_sentiment(asset, minutes=minutes)
        return results

    def fetch_tweets_scrape(
        self,
        asset: str,
        max_results: int = 30,
    ) -> List[TweetData]:
        """
        Scrape-based fallback for X sentiment when API credits are exhausted.

        Uses Nitter public instances or syndication endpoints to grab recent
        tweets without consuming API credits.  Falls back silently to empty
        list on failure so the caller never blocks.

        This is intentionally best-effort:
        - No authentication required
        - No rate limit impact on X API quota
        - Lower fidelity than API (no engagement metrics)
        - Rotate through multiple Nitter mirrors for resilience
        """
        if not requests:
            return []

        NITTER_MIRRORS = [
            "https://nitter.privacydev.net",
            "https://nitter.poast.org",
            "https://nitter.cz",
            "https://nitter.net",
            "https://nitter.fdn.fr",
            "https://nitter.1d4.us",
        ]

        query_terms = self.ASSET_QUERIES.get(asset.upper())
        if not query_terms:
            return []

        # Extract the primary search term from the query (e.g., "SOL" from "(SOL OR Solana OR #Solana OR #SOL OR solana price)")
        # Use the first simple term for Nitter search
        import re
        primary_term_match = re.search(r'\b([A-Z]{2,})\b', query_terms.split()[0])
        search_term = primary_term_match.group(1) if primary_term_match else asset.upper()

        tweets: List[TweetData] = []
        for mirror in NITTER_MIRRORS:
            try:
                resp = requests.get(
                    f"{mirror}/search",
                    params={"f": "tweets", "q": search_term},
                    headers={"User-Agent": "MERID-sentiment/1.0"},
                    timeout=10,
                )
                if resp.status_code != 200:
                    continue

                # Simple HTML extraction — Nitter renders tweets in
                # <div class="timeline-item"> blocks with .tweet-content
                text_chunks = []
                for line in resp.text.split("tweet-content"):
                    if len(text_chunks) >= max_results:
                        break
                    if "<p" not in line:
                        continue
                    # Extract text between <p ...> and </p>
                    start = line.find(">") + 1
                    end = line.find("</p>")
                    if start > 0 and end > start:
                        raw = line[start:end]
                        # Strip HTML tags and unescape HTML entities
                        import html as _html
                        clean = _html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()
                        # Require at least 4 whitespace-separated words to
                        # filter out fragments, error pages, and entity refs
                        if clean and len(clean.split()) >= 4:
                            text_chunks.append(clean)

                for idx, text in enumerate(text_chunks):
                    tweets.append(TweetData(
                        id=f"scrape_{asset}_{idx}_{int(time.time())}",
                        text=text,
                        created_at=datetime.now(timezone.utc),
                        like_count=0,
                        retweet_count=0,
                        reply_count=0,
                        author_id=None,
                        source="nitter_scrape",
                    ))

                if tweets:
                    logger.debug("Scraped %d tweets for %s via %s", len(tweets), asset, mirror)
                    break  # Got data from this mirror, stop trying others

            except Exception as exc:
                logger.debug("Nitter scrape failed (%s): %s", mirror, exc)
                continue

        return tweets

    def get_sentiment_with_fallback(
        self,
        asset: str,
        minutes: int = 15,
        use_cache: bool = True,
        max_results: int = 100,
    ) -> SentimentResult:
        """
        Get sentiment using API first, falling back to scraping.

        Order:
        1. Check cache → return if fresh
        2. Try X API (search/recent) → if rate-limited, skip
        3. Fallback: scrape via Nitter mirrors → analyze with VADER
        4. If all fail → return neutral with zero confidence

        This ensures we never waste API credits on low-value calls
        while still maintaining continuous sentiment coverage.
        """
        import os
        if os.getenv("DISABLE_TWITTER_SENTIMENT", "").lower() in ("1", "true", "yes"):
            return SentimentResult(
                score=0.0,
                confidence=0.0,
                volume=0,
                avg_engagement=0.0,
                raw_data=[],
                timestamp=datetime.now(timezone.utc),
                model_version="disabled",
                available=False,
            )

        cache_key = f"{asset}:{minutes}"

        # 1. Check cache
        if use_cache and cache_key in self._cache:
            cached = self._cache[cache_key]
            age = (datetime.now(timezone.utc) - cached.timestamp).total_seconds()
            if age < self._cache_ttl_seconds:
                return cached
            # Staleness ceiling: if cache is older than 30 min return
            # zero-confidence neutral rather than dangerously stale scores.
            if age > 1800:
                logger.warning(
                    "Twitter cache for %s is %.0fs old (>30 min) — "
                    "returning zero-confidence neutral to avoid stale signal.",
                    asset, age,
                )
                return SentimentResult(
                    score=0.0,
                    confidence=0.0,
                    volume=0,
                    avg_engagement=0.0,
                    raw_data=[],
                    timestamp=cached.timestamp,
                )

        # 2. Try API first
        tweets = self.fetch_tweets(asset, minutes, max_results)

        # 3. If API returned nothing (rate-limited or no data), try scraping
        if not tweets:
            tweets = self.fetch_tweets_scrape(asset, max_results=30)
            if tweets:
                logger.info("X sentiment for %s via scrape fallback (%d tweets)", asset, len(tweets))

        # 4. Analyze whatever we got
        result = self.analyze_sentiment(tweets)
        self._cache[cache_key] = result
        return result


# Singleton accessor
_twitter_service: Optional[TwitterSentimentService] = None
_twitter_service_lock = threading.Lock()


def get_twitter_sentiment_service(bearer_token: Optional[str] = None) -> TwitterSentimentService:
    """Get the singleton TwitterSentimentService instance."""
    return TwitterSentimentService(bearer_token)


# ── Convenience functions for quick usage ─────────────────────────────

def quick_twitter_sentiment(asset: str, minutes: int = 15) -> float:
    """
    Quick one-liner to get Twitter sentiment score.
    
    PRODUCTION FIX (2026-05-10): Removed fake fallback data.
    Raises exception on failure instead of returning 0.0.
    Ensures only real sentiment data is used in trading decisions.
    """
    service = get_twitter_sentiment_service()
    result = service.get_sentiment(asset, minutes=minutes)
    return result.score


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
        raw_token = bearer_token or os.getenv("X_BEARER_TOKEN") or os.getenv("TWITTER_BEARER_TOKEN")
        if raw_token and "%" in raw_token:
            from urllib.parse import unquote
            raw_token = unquote(raw_token)
        self.bearer_token = raw_token
        self.base_url = "https://api.twitter.com/2"
        self._running = False
        self._stream_thread: Optional[threading.Thread] = None
        self._sentiment_windows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._window_size = 100  # Keep last 100 tweets per asset
        self._callbacks: List[Callable[[str, float, Dict], None]] = []
        # Guards _sentiment_windows and _callbacks from concurrent access
        # between the background stream thread and external callers.
        self._stream_lock = threading.Lock()
        
        # Asset detection patterns
        self.ASSET_PATTERNS: Dict[str, List[str]] = {
            "BTC": ["btc", "bitcoin", "#bitcoin", "#btc"],
            "ETH": ["eth", "ethereum", "#ethereum", "#eth"],
            "SOL": ["sol", "solana", "#solana", "#sol"],
        }
    
    def _get_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.bearer_token}"}
    
    def setup_stream_rules(self, assets: List[str]) -> bool:
        """Set up filtered stream rules for tracking assets.

        NOTE: search/stream and stream/rules are Pro-only endpoints.
        On Free tier this is a no-op that returns False.
        """
        # Free tier does not support search/stream or stream/rules.
        # Attempting to call them results in 403 Forbidden.
        logger.info("Stream rules skipped — search/stream requires Pro tier or higher")
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
            
            with self._stream_lock:
                window = self._sentiment_windows[asset]
                window.append(entry)
                if len(window) > self._window_size:
                    window.pop(0)
                callbacks = list(self._callbacks)
            
            # Notify callbacks outside lock
            for callback in callbacks:
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
        
        _backoff = 5
        _max_backoff = 300  # 5 min cap
        _auth_failures = 0

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
                    _backoff = 5  # reset on success
                    _auth_failures = 0
                    
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
                            
            except requests.exceptions.HTTPError as exc:
                if exc.response is not None and exc.response.status_code in (401, 403):
                    _auth_failures += 1
                    if _auth_failures >= 3:
                        logger.warning("Twitter stream auth failed %dx — stopping reconnect loop", _auth_failures)
                        self._running = False
                        break
                    logger.warning(f"Twitter stream auth error ({exc.response.status_code}), retry {_auth_failures}/3 in {_backoff}s")
                else:
                    logger.warning(f"Stream HTTP error: {exc}")
                time.sleep(_backoff)
                _backoff = min(_backoff * 2, _max_backoff)
            except requests.exceptions.RequestException as exc:
                logger.warning(f"Stream connection error: {exc}")
                time.sleep(_backoff)
                _backoff = min(_backoff * 2, _max_backoff)
            except Exception as exc:
                logger.warning(f"Stream error: {exc}")
                time.sleep(_backoff)
                _backoff = min(_backoff * 2, _max_backoff)
    
    def start(self, assets: List[str] = None):
        """Start the streaming handler.

        NOTE: On X Free tier, search/stream is not available (Pro-only).
        This method logs a notice and returns without starting.
        Sentiment is instead provided via periodic search/recent polling
        in TwitterSentimentService.
        """
        # Free tier: search/stream and stream/rules require Pro or higher.
        # Polling via search/recent (1 req / 15 min) is used instead.
        logger.info(
            "X streaming disabled (Free tier). "
            "Sentiment provided via search/recent polling (1 req/15 min)."
        )
        return
    
    def stop(self):
        """Stop the streaming handler."""
        self._running = False
        if self._stream_thread:
            self._stream_thread.join(timeout=2)
        logger.info("Twitter stream stopped")
    
    def get_rolling_sentiment(self, asset: str, window: int = 50) -> Dict[str, Any]:
        """Get rolling average sentiment from stream."""
        with self._stream_lock:
            data = list(self._sentiment_windows.get(asset, []))
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
        with self._stream_lock:
            self._callbacks.append(callback)
    
    def unregister_callback(self, callback: Callable[[str, float, Dict], None]):
        """Unregister a callback."""
        with self._stream_lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)


# Streaming singleton accessor
_stream_handler: Optional[TwitterStreamHandler] = None
_stream_handler_lock = threading.Lock()

def get_twitter_stream_handler() -> TwitterStreamHandler:
    """Get the singleton TwitterStreamHandler instance."""
    global _stream_handler
    if _stream_handler is None:
        with _stream_handler_lock:
            if _stream_handler is None:
                _stream_handler = TwitterStreamHandler()
    return _stream_handler

