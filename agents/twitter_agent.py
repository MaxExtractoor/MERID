"""
Twitter/X Agent for MERID.

Handles posting updates, market insights, and breaking news to X/Twitter.
Production-grade implementation with real API integration.

Configuration:
    ENABLE_TWITTER_AGENT: Set to "false" to completely disable Twitter integration
    X_BEARER_TOKEN, X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET:
        Twitter API v2 credentials (required if agent enabled)
"""

from __future__ import annotations

import threading
import os
import time
from typing import Optional, List, Dict
from dataclasses import dataclass
from datetime import datetime

try:  # tweepy is optional for test environments
    import tweepy
except ImportError:  # pragma: no cover - exercised when dependency missing
    tweepy = None  # type: ignore[assignment]

from utils.logger import get_logger

logger = get_logger("agents.twitter_agent")

# Config knob to disable Twitter agent completely
_ENABLE_TWITTER_AGENT = os.getenv("ENABLE_TWITTER_AGENT", "true").lower() not in ("false", "0", "no", "off")


@dataclass
class Tweet:
    """Tweet data structure."""
    text: str
    tweet_id: Optional[str] = None
    created_at: Optional[datetime] = None
    likes: int = 0
    retweets: int = 0


class TwitterAgent:
    """
    Production Twitter/X Agent.
    
    Capabilities:
    - Post market updates
    - Post breaking news
    - Post consensus results
    - Post agent insights
    - Monitor engagement
    """
    
    def __init__(self):
        """Initialize Twitter agent with API credentials."""
        # Check config knob first - allow complete disable via env var
        if not _ENABLE_TWITTER_AGENT:
            logger.info("[TWITTER-AUTH] Twitter agent disabled via ENABLE_TWITTER_AGENT=false")
            self.enabled = False
            self.client = None
            self._disabled_reason = "disabled_by_config"
            return

        # API v2 credentials — URL-decode if pasted with %XX sequences
        from urllib.parse import unquote
        def _env(key: str) -> Optional[str]:
            v = os.getenv(key)
            return unquote(v) if v and "%" in v else v

        self.bearer_token = _env('X_BEARER_TOKEN')
        self.api_key = _env('X_API_KEY')
        self.api_secret = _env('X_API_SECRET')
        self.access_token = _env('X_ACCESS_TOKEN')
        self.access_token_secret = _env('X_ACCESS_TOKEN_SECRET')

        # Validate credentials
        if tweepy is None:
            logger.info("[TWITTER-AUTH] tweepy not installed - Twitter agent disabled")
            self.enabled = False
            self.client = None
            self._disabled_reason = "tweepy_missing"
        elif not all([self.api_key, self.api_secret, self.access_token, self.access_token_secret]):
            logger.info("[TWITTER-AUTH] Twitter credentials incomplete - agent disabled (set ENABLE_TWITTER_AGENT=false to suppress this message)")
            self.enabled = False
            self.client = None
            self._disabled_reason = "credentials_incomplete"
        else:
            try:
                # Initialize Twitter API v2 client
                self.client = tweepy.Client(
                    bearer_token=self.bearer_token,
                    consumer_key=self.api_key,
                    consumer_secret=self.api_secret,
                    access_token=self.access_token,
                    access_token_secret=self.access_token_secret,
                    wait_on_rate_limit=True
                )
                self.enabled = True
                self._disabled_reason = None
                logger.info("Twitter agent initialized successfully")
            except Exception as exc:
                # Log at WARNING (not ERROR) - auth misconfig is non-critical
                logger.warning(f"[TWITTER-AUTH] Failed to initialize Twitter client (will retry): {exc}")
                self.enabled = False
                self.client = None
                self._disabled_reason = "init_failed"

        # Common initialization (only reached if not disabled_by_config)
        self.recent_tweets: List[Tweet] = []
        self.last_post_time = 0
        self.min_post_interval = 5100  # ~85 min — keeps us under 17 tweets/24h Free tier cap
        self._consecutive_failures = 0
        self._max_consecutive_failures = 3

        # Free tier: 17 tweets per 24h per user AND per app
        self._daily_tweet_limit = 17
        self._daily_tweet_count = 0
        self._daily_reset_day = datetime.now().date()
    
    def post_tweet(self, text: str, force: bool = False) -> Optional[Tweet]:
        """
        Post a tweet to X/Twitter.
        
        Args:
            text: Tweet content (max 280 characters)
            force: Skip rate limiting check
            
        Returns:
            Tweet object if successful, None otherwise
        """
        if not self.enabled:
            if not self._disabled_reason:
                logger.debug(f"Twitter agent disabled - would have posted: {text[:80]}...")
            return None
        
        # Daily counter reset at midnight
        today = datetime.now().date()
        if today != self._daily_reset_day:
            self._daily_tweet_count = 0
            self._daily_reset_day = today

        # Free tier daily cap: 17 tweets / 24h
        if self._daily_tweet_count >= self._daily_tweet_limit:
            logger.debug("X Free tier daily limit reached (%d/%d) — skipping",
                         self._daily_tweet_count, self._daily_tweet_limit)
            return None

        # Rate limiting — ~85 min between posts to spread across the day
        if not force:
            time_since_last = time.time() - self.last_post_time
            if time_since_last < self.min_post_interval:
                return None
        
        # Truncate if needed
        if len(text) > 280:
            text = text[:277] + "..."
            logger.warning("Tweet truncated to 280 characters")
        
        try:
            # Post tweet
            response = self.client.create_tweet(text=text)
            
            tweet = Tweet(
                text=text,
                tweet_id=response.data['id'],
                created_at=datetime.now()
            )
            
            self.recent_tweets.append(tweet)
            self.last_post_time = time.time()
            self._consecutive_failures = 0
            self._daily_tweet_count += 1
            
            logger.info(f"Tweet posted successfully: {tweet.tweet_id} ({self._daily_tweet_count}/{self._daily_tweet_limit} today)")
            return tweet
            
        except Exception as exc:
            exc_str = str(exc)
            self.last_post_time = time.time()  # Prevent retry flood
            self._consecutive_failures += 1

            # 403 = OAuth permissions not configured for write — permanent failure
            if "403" in exc_str and ("Forbidden" in exc_str or "oauth" in exc_str.lower() or "permissions" in exc_str.lower()):
                self._disabled_reason = f"OAuth write permissions not granted: {exc_str}"
                self.enabled = False
                logger.error(
                    "Twitter agent DISABLED — OAuth1 app lacks write permissions. "
                    "Go to developer.twitter.com → App Settings → User authentication → "
                    "set App permissions to 'Read and write'. Error: %s", exc_str
                )
                return None

            # 401 = bad credentials — permanent failure, but known config issue
            # Log at WARNING not ERROR since this is expected when credentials not configured
            if "401" in exc_str and "Unauthorized" in exc_str:
                self._disabled_reason = f"Invalid credentials: {exc_str}"
                self.enabled = False
                logger.warning("Twitter agent DISABLED — invalid credentials: %s", exc_str)
                return None

            # Transient failures: back off after N consecutive failures
            if self._consecutive_failures >= self._max_consecutive_failures:
                self._disabled_reason = f"Too many consecutive failures ({self._consecutive_failures}): {exc_str}"
                self.enabled = False
                logger.error(
                    "Twitter agent DISABLED after %d consecutive failures. Last error: %s",
                    self._consecutive_failures, exc_str,
                )
                return None

            logger.warning("Tweet failed (%d/%d): %s",
                           self._consecutive_failures, self._max_consecutive_failures, exc_str)
            return None
    
    # ── Kalshi-native post methods ─────────────────────────────────────

    def post_swarm_call(
        self,
        asset: str,
        direction: str,
        prob: float,
        confidence: float,
        n_agents: int,
        mode: str = "paper",
    ) -> Optional[Tweet]:
        """Post a swarm consensus call (non-paper only, confidence ≥ 0.7)."""
        if mode.lower() == "paper" or confidence < 0.7:
            return None
        icon = {"YES": "🟢", "NO": "🔴"}.get(direction.upper(), "⚪")
        text = (
            f"{icon} MERID swarm: {direction.upper()} on {asset} @ {prob:.1%} "
            f"(conf {confidence:.0%}, {n_agents} agents)\n"
            f"#Kalshi #PredictionMarkets"
        )
        return self.post_tweet(text)

    def post_market_resolution(
        self,
        market: str,
        result: str,
        question: str,
        pnl_cents: Optional[float] = None,
    ) -> Optional[Tweet]:
        """Post when a Kalshi market resolves."""
        icon = "✅" if result.upper() == "YES" else "❌"
        q = question if len(question) <= 80 else question[:77] + "…"
        text = f"{icon} SETTLED {result.upper()}\n{q}\n#Kalshi #PredictionMarkets"
        if pnl_cents is not None:
            sign = "+" if pnl_cents >= 0 else ""
            text += f"\nPnL: {sign}{pnl_cents:.0f}¢"
        return self.post_tweet(text)

    def post_edge_alert(
        self,
        asset: str,
        edge_pct: float,
        prob: float,
        market_prob: float,
    ) -> Optional[Tweet]:
        """Post when the swarm detects a meaningful edge over market price."""
        text = (
            f"⚡ Edge detected on {asset}\n"
            f"Swarm: {prob:.1%} vs Market: {market_prob:.1%} ({edge_pct:+.2f}%)\n"
            f"#Kalshi #PredictionMarkets #MERID"
        )
        return self.post_tweet(text)

    def post_session_pnl(
        self,
        pnl_cents: float,
        fills: int,
        win_rate: float,
        mode: str = "paper",
    ) -> Optional[Tweet]:
        """Post end-of-session PnL summary."""
        if mode.lower() == "paper":
            return None  # Don't tweet simulated results
        icon = "🟢" if pnl_cents >= 0 else "🔴"
        sign = "+" if pnl_cents >= 0 else ""
        text = (
            f"{icon} MERID session: {sign}{pnl_cents:.0f}¢ "
            f"({fills} fills, {win_rate:.1%} win rate)\n"
            f"#Kalshi #PredictionMarkets"
        )
        return self.post_tweet(text)

    def post_debate_outcome(
        self,
        market: str,
        question: str,
        winner: str,
        confidence: float,
        agents: int,
    ) -> Optional[Tweet]:
        """Post the outcome of a MERID debate round."""
        q = question if len(question) <= 70 else question[:67] + "…"
        text = (
            f"🏛️ MERID debate settled: {winner.upper()}\n"
            f"{q}\n"
            f"Conf: {confidence:.0%} ({agents} agents)\n"
            f"#Kalshi #MERID"
        )
        return self.post_tweet(text)

    def post_signal_quality_alert(
        self,
        slow_domains: int,
        dead_domains: int,
    ) -> Optional[Tweet]:
        """Post a signal quality degradation alert."""
        text = (
            f"⚠️ MERID signal quality degraded\n"
            f"Slow domains: {slow_domains} | Dead: {dead_domains}\n"
            f"#MERID #Kalshi"
        )
        return self.post_tweet(text)
    
    def post_consensus_result(
        self,
        block_index: int,
        approved: bool,
        confidence: float,
        agents_voted: int,
    ) -> Optional[Tweet]:
        """Post a consensus result to X/Twitter."""
        icon = "✅" if approved else "❌"
        verdict = "APPROVED" if approved else "REJECTED"
        text = (
            f"{icon} Consensus #{block_index}: {verdict}\n"
            f"Confidence: {confidence:.1%} ({agents_voted} agents)\n"
            f"#MERID #PredictionMarkets"
        )
        return self.post_tweet(text)

    def post_system_status(
        self,
        blocks_mined: int,
        agents_active: int,
        consensus_rate: float,
    ) -> Optional[Tweet]:
        """Post a system status update tweet.

        Args:
            blocks_mined: Number of blocks mined
            agents_active: Number of active agents
            consensus_rate: Consensus rate (0-1)

        Returns:
            Tweet object if posted successfully, None otherwise
        """
        text = (
            f"🤖 MERID System Status\n"
            f"⛏️ Blocks: {blocks_mined}\n"
            f"🔄 Agents: {agents_active}\n"
            f"📊 Consensus: {consensus_rate:.1%}"
        )
        return self.post_tweet(text)

    def post_tweet_reply(self, text: str, reply_to_id: str) -> Optional[Tweet]:
        """Post a reply tweet to thread a follow-up on the same market."""
        if not self.enabled:
            return None
        if len(text) > 280:
            text = text[:277] + "..."
        try:
            response = self.client.create_tweet(
                text=text,
                in_reply_to_tweet_id=reply_to_id,
            )
            tweet = Tweet(
                text=text,
                tweet_id=response.data["id"],
                created_at=datetime.now(),
            )
            self.recent_tweets.append(tweet)
            self.last_post_time = time.time()
            self._consecutive_failures = 0
            logger.info("Reply tweet posted: %s → %s", tweet.tweet_id, reply_to_id)
            return tweet
        except Exception as exc:
            logger.warning("Reply tweet failed: %s", exc)
            return None

    def post_kalshi_insight(
        self,
        category: str,
        question: str,
        prob_pct: str,
        change_str: str,
        swarm_pct: str,
        market_url: str,
        tags: List[str],
        action: str = "update",
    ) -> Optional[Tweet]:
        """Post a Kalshi market insight with category-aware formatting."""
        action_emojis = {
            "new_market": "🆕", "prob_cross": "📈",
            "swing": "⚡", "resolution": "🏁", "update": "🔄",
        }
        cat_emojis = {
            "Trending": "🔥", "Politics": "🏛️", "Sports": "🏆",
            "Culture": "🎭", "Crypto": "₿", "Climate": "🌍",
            "Economics": "📊", "Mentions": "📰", "Companies": "🏢",
            "Financials": "💹", "Tech & Science": "🔬",
        }
        ce = cat_emojis.get(category, "📌")
        ae = action_emojis.get(action, "🔄")
        tag_str = " ".join(tags[:2])
        q = question if len(question) <= 80 else question[:77] + "…"
        text = (
            f"{ce} {ae} {category.upper()}\n"
            f"{q}\n"
            f"Now: {prob_pct} {change_str} | MERID: {swarm_pct}\n"
            f"{market_url}\n"
            f"{tag_str}"
        )
        return self.post_tweet(text)

    def get_recent_tweets(self, limit: int = 10) -> List[Tweet]:
        """Get recent tweets posted by this agent."""
        return self.recent_tweets[-limit:]
    
    def get_health(self) -> Dict:
        """Structured health status for dependency health model.

        Returns a dict with:
          - status: "healthy" | "degraded" | "disabled"
          - enabled: bool
          - disabled_reason: Optional[str]
          - consecutive_failures: int
          - daily_tweets_remaining: int
        """
        if not self.enabled:
            status = "disabled"
        elif self._consecutive_failures > 0:
            status = "degraded"
        else:
            status = "healthy"

        today = datetime.now().date()
        remaining = max(0, self._daily_tweet_limit - self._daily_tweet_count) if today == self._daily_reset_day else self._daily_tweet_limit

        return {
            "status": status,
            "enabled": self.enabled,
            "disabled_reason": self._disabled_reason,
            "consecutive_failures": self._consecutive_failures,
            "daily_tweets_remaining": remaining,
            "tweepy_installed": tweepy is not None,
        }

    def get_engagement_stats(self) -> Dict:
        """Get engagement statistics for recent tweets."""
        if not self.recent_tweets:
            return {
                "total_tweets": 0,
                "total_likes": 0,
                "total_retweets": 0,
                "avg_engagement": 0.0
            }
        
        total_likes = sum(t.likes for t in self.recent_tweets)
        total_retweets = sum(t.retweets for t in self.recent_tweets)
        
        return {
            "total_tweets": len(self.recent_tweets),
            "total_likes": total_likes,
            "total_retweets": total_retweets,
            "avg_engagement": (total_likes + total_retweets) / len(self.recent_tweets)
        }


# Global singleton
_twitter_agent: Optional[TwitterAgent] = None
_twitter_agent_lock = threading.Lock()


def get_twitter_agent() -> TwitterAgent:
    """Get or create Twitter agent singleton."""
    global _twitter_agent
    if _twitter_agent is None:
        with _twitter_agent_lock:
            if _twitter_agent is None:
                _twitter_agent = TwitterAgent()
    return _twitter_agent
