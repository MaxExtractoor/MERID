"""
Twitter/X Agent for MERID.

Handles posting updates, market insights, and breaking news to X/Twitter.
Production-grade implementation with real API integration.
"""

from __future__ import annotations

import os
import time
from typing import Optional, List, Dict
from dataclasses import dataclass
from datetime import datetime

import tweepy
from utils.logger import get_logger

logger = get_logger("agents.twitter_agent")


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
        # API v2 credentials
        self.bearer_token = os.getenv('X_BEARER_TOKEN')
        self.api_key = os.getenv('X_API_KEY')
        self.api_secret = os.getenv('X_API_SECRET')
        self.access_token = os.getenv('X_ACCESS_TOKEN')
        self.access_token_secret = os.getenv('X_ACCESS_TOKEN_SECRET')
        
        # Validate credentials
        if not all([self.api_key, self.api_secret, self.access_token, self.access_token_secret]):
            logger.warning("Twitter credentials incomplete - agent will run in dry-run mode")
            self.enabled = False
            self.client = None
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
                logger.info("Twitter agent initialized successfully")
            except Exception as exc:
                logger.error(f"Failed to initialize Twitter client: {exc}")
                self.enabled = False
                self.client = None
        
        self.recent_tweets: List[Tweet] = []
        self.last_post_time = 0
        self.min_post_interval = 60  # Minimum 60 seconds between posts
    
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
            logger.warning(f"Twitter agent disabled - would have posted: {text}")
            return None
        
        # Rate limiting
        if not force:
            time_since_last = time.time() - self.last_post_time
            if time_since_last < self.min_post_interval:
                logger.warning(f"Rate limit: {self.min_post_interval - time_since_last:.0f}s until next post")
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
            
            logger.info(f"Tweet posted successfully: {tweet.tweet_id}")
            return tweet
            
        except Exception as exc:
            logger.error(f"Failed to post tweet: {exc}")
            return None
    
    def post_market_update(self, asset: str, price: float, change_pct: float, volume: float) -> Optional[Tweet]:
        """Post market update."""
        emoji = "🟢" if change_pct >= 0 else "🔴"
        sign = "+" if change_pct >= 0 else ""
        
        text = (
            f"{emoji} ${asset} Market Update\n\n"
            f"Price: ${price:,.2f}\n"
            f"24h Change: {sign}{change_pct:.2f}%\n"
            f"Volume: ${volume:,.0f}\n\n"
            f"#MERID #Crypto #{asset}"
        )
        
        return self.post_tweet(text)
    
    def post_breaking_news(self, headline: str, source: str, url: Optional[str] = None) -> Optional[Tweet]:
        """Post breaking news alert."""
        text = f"🚨 BREAKING NEWS\n\n{headline}\n\nSource: {source}"
        
        if url and len(text) + len(url) + 2 <= 280:
            text += f"\n\n{url}"
        
        text += "\n\n#MERID #CryptoNews"
        
        return self.post_tweet(text)
    
    def post_consensus_result(self, block_index: int, approved: bool, confidence: float, agents_voted: int) -> Optional[Tweet]:
        """Post consensus result."""
        status = "✅ APPROVED" if approved else "❌ REJECTED"
        
        text = (
            f"{status} Block #{block_index}\n\n"
            f"Consensus: {confidence:.1%}\n"
            f"Agents: {agents_voted}\n\n"
            f"MERID consensus engine in action.\n\n"
            f"#MERID #Blockchain #Consensus"
        )
        
        return self.post_tweet(text)
    
    def post_arbitrage_opportunity(self, asset: str, venue_a: str, venue_b: str, spread_bps: float, profit: float) -> Optional[Tweet]:
        """Post arbitrage opportunity detected."""
        text = (
            f"💰 Arbitrage Detected\n\n"
            f"Asset: ${asset}\n"
            f"{venue_a} → {venue_b}\n"
            f"Spread: {spread_bps:.1f} bps\n"
            f"Est. Profit: ${profit:.2f}\n\n"
            f"#MERID #Arbitrage #Trading"
        )
        
        return self.post_tweet(text)
    
    def post_agent_insight(self, agent_name: str, insight: str) -> Optional[Tweet]:
        """Post agent insight or decision."""
        text = (
            f"🤖 Agent Insight: {agent_name}\n\n"
            f"{insight}\n\n"
            f"#MERID #AI #Trading"
        )
        
        return self.post_tweet(text)
    
    def post_system_status(self, blocks_mined: int, agents_active: int, consensus_rate: float) -> Optional[Tweet]:
        """Post system status update."""
        text = (
            f"📊 MERID System Status\n\n"
            f"Blocks Mined: {blocks_mined}\n"
            f"Active Agents: {agents_active}\n"
            f"Consensus Rate: {consensus_rate:.1%}\n\n"
            f"System operational.\n\n"
            f"#MERID #Status"
        )
        
        return self.post_tweet(text)
    
    def get_recent_tweets(self, limit: int = 10) -> List[Tweet]:
        """Get recent tweets posted by this agent."""
        return self.recent_tweets[-limit:]
    
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


def get_twitter_agent() -> TwitterAgent:
    """Get or create Twitter agent singleton."""
    global _twitter_agent
    if _twitter_agent is None:
        _twitter_agent = TwitterAgent()
    return _twitter_agent
