"""Social Ingestion Agents.

Wraps the underlying sentiment fetchers (HashtagAgent, NewsIngestionAgent, Reddit)
into the CanonicalAgent framework so they run on the orchestrator tick.

After each cycle the agents push SocialSignal objects into the
EnhancedConsensusCoordinator so that sentiment nudges consensus scores.
"""

import asyncio
import logging
import time
from typing import Any, Dict, List
from merid.agents.base import CanonicalAgent, AgentCategory

logger = logging.getLogger(__name__)
from merid.sentiment.hashtag_agent import HashtagAgent
from merid.sentiment.news_ingestion_agent import NewsIngestionAgent
from consensus.consensus_coordinator import SocialSignal, get_consensus_coordinator

class TwitterIngestionAgent(CanonicalAgent):
    """
    Runs the HashtagAgent to scrape X/Twitter for crypto sentiment.
    """
    def __init__(self, agent_id: str = "twitter-ingestion-01"):
        super().__init__(agent_id, AgentCategory.RESEARCH)
        self.hashtag_agent = HashtagAgent()

    async def _execute(self, context: Dict[str, Any]) -> Any:
        self.logger.info("Running Twitter sentiment cycle")
        sentiments = await self.hashtag_agent.run_asset_cycle()
        self._push_signals(sentiments, "twitter")
        return {
            "sentiments_gathered": len(sentiments),
            "provider": "twitter"
        }

    @staticmethod
    def _push_signals(sentiments: List, source: str) -> None:
        """Convert HashtagSentiment objects to SocialSignals and push to coordinator."""
        try:
            coord = get_consensus_coordinator()
            for s in sentiments:
                symbol = getattr(s, "asset", None) or getattr(s, "tag", "UNKNOWN")
                coord.submit_social_signal(SocialSignal(
                    source=source,
                    agent_id=f"{source}-ingestion-01",
                    symbol=symbol,
                    score=getattr(s, "score", 0.0),
                    confidence=getattr(s, "confidence", 0.5),
                    volume=getattr(s, "volume", 0),
                ))
        except Exception:
            pass  # coordinator may not be initialised yet

class RedditIngestionAgent(CanonicalAgent):
    """
    Runs Reddit sentiment scraping.
    """
    def __init__(self, agent_id: str = "reddit-ingestion-01"):
        super().__init__(agent_id, AgentCategory.RESEARCH)
        from merid.sentiment.reddit_scraper import get_reddit_sentiment_service
        self.reddit_svc = get_reddit_sentiment_service()

    async def _execute(self, context: Dict[str, Any]) -> Any:
        self.logger.info("Running Reddit sentiment cycle")
        if self.reddit_svc:
            # BUG-EL6 FIX: Offload sync Reddit scraping to thread pool
            # so it cannot block the event loop for 3-4s per asset call.
            score = await asyncio.to_thread(self.reddit_svc.get_sentiment, "BTC", limit=50)
            await asyncio.to_thread(self.reddit_svc.update_mood_bus, "BTC")
            self._push_reddit_signal("BTC", score)
            return {
                "btc_score": score,
                "provider": "reddit"
            }
        return {"error": "Reddit service unavailable"}

    @staticmethod
    def _push_reddit_signal(asset: str, score_obj: Any) -> None:
        """Push a single Reddit sentiment score into the coordinator."""
        try:
            raw_score = float(getattr(score_obj, "compound_score", None) or getattr(score_obj, "score", 0.0))
            coord = get_consensus_coordinator()
            coord.submit_social_signal(SocialSignal(
                source="reddit",
                agent_id="reddit-ingestion-01",
                symbol=asset,
                score=raw_score,
                confidence=0.5,
                volume=0,
            ))
        except Exception as e:
            logger.debug(f"Failed to push Reddit signal for {asset}: {e}")

class NewsIngestionAgentWrapper(CanonicalAgent):
    """
    Runs the NewsIngestionAgent.
    """
    def __init__(self, agent_id: str = "news-ingestion-01"):
        super().__init__(agent_id, AgentCategory.RESEARCH)
        self.news_agent = NewsIngestionAgent()

    async def _execute(self, context: Dict[str, Any]) -> Any:
        self.logger.info("Running News sentiment cycle")
        sentiments = await self.news_agent.run_cycle()
        TwitterIngestionAgent._push_signals(sentiments, "newsapi")
        return {
            "news_gathered": len(sentiments),
            "provider": "newsapi"
        }
