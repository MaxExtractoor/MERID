"""
X/Twitter Bot Client for Debate Alert Notifications
"""

import os
import threading
import httpx
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class XClient:
    """Simple X/Twitter bot client for sending debate alerts."""
    
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None, 
                 access_token: Optional[str] = None, access_token_secret: Optional[str] = None):
        """
        Initialize X client.
        
        Args:
            api_key: X API key (defaults to X_API_KEY env var)
            api_secret: X API secret (defaults to X_API_SECRET env var)
            access_token: X access token (defaults to X_ACCESS_TOKEN env var)
            access_token_secret: X access token secret (defaults to X_ACCESS_TOKEN_SECRET env var)
        """
        self.api_key = api_key or os.getenv("X_API_KEY")
        self.api_secret = api_secret or os.getenv("X_API_SECRET")
        self.access_token = access_token or os.getenv("X_ACCESS_TOKEN")
        self.access_token_secret = access_token_secret or os.getenv("X_ACCESS_TOKEN_SECRET")
        
        # For X API v2, we need bearer token for app-only auth
        self.bearer_token = os.getenv("X_BEARER_TOKEN")
        
        missing_configs = []
        if not self.bearer_token and not (self.api_key and self.api_secret):
            missing_configs.append("API credentials")
        if not self.access_token:
            missing_configs.append("access token")
            
        if missing_configs:
            logger.warning(f"X client missing configurations: {', '.join(missing_configs)}")
    
    async def send_tweet(self, text: str) -> bool:
        """
        Send a tweet/status update via the TwitterAgent singleton (tweepy OAuth 1.0a).

        Bearer tokens cannot post tweets (read-only app auth).  All posting must go
        through user-context OAuth 1.0a, which TwitterAgent handles via tweepy.

        Args:
            text: Tweet text (must be ≤ 280 characters)

        Returns:
            True if tweet sent successfully, False otherwise
        """
        if len(text) > 280:
            logger.error(f"Tweet text too long: {len(text)} characters (max 280)")
            return False

        try:
            import asyncio
            from agents.twitter_agent import get_twitter_agent
            agent = get_twitter_agent()
            if not agent.enabled:
                reason = agent._disabled_reason or "credentials missing or tweepy not installed"
                logger.warning("XClient.send_tweet: TwitterAgent disabled — %s", reason)
                return False
            # post_tweet is synchronous (tweepy) — run in thread pool
            result = await asyncio.to_thread(agent.post_tweet, text)
            if result:
                logger.info("XClient.send_tweet OK (tweet_id=%s): %s", result.tweet_id, text[:50])
                return True
            logger.debug("XClient.send_tweet: skipped (rate-limit / daily cap)")
            return False
        except Exception as exc:
            logger.error("XClient.send_tweet error: %s", exc)
            return False
    
    async def send_alert(self, alert_text: str) -> bool:
        """
        Send a debate alert to X.
        
        Args:
            alert_text: Formatted alert message (≤ 280 chars)
            
        Returns:
            True if sent successfully
        """
        return await self.send_tweet(alert_text)
    
    async def send_daily_summary(self, summary_text: str) -> bool:
        """
        Send a daily summary to X.
        
        Args:
            summary_text: Formatted daily summary (≤ 280 chars)
            
        Returns:
            True if sent successfully
        """
        return await self.send_tweet(summary_text)
    
    def is_configured(self) -> bool:
        """Check if X client is properly configured."""
        return bool(self.bearer_token or (self.api_key and self.access_token))

# Global instance for reuse
_x_client: Optional[XClient] = None
_x_client_lock = threading.Lock()

def get_x_client() -> XClient:
    """Get or create the global X client instance."""
    global _x_client
    if _x_client is None:  # E2a: double-checked locking
        with _x_client_lock:
            if _x_client is None:
                _x_client = XClient()
    return _x_client
