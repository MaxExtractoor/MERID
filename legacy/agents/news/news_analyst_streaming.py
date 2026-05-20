"""
News Analyst Agent - Streaming implementation.

Subscribes to NEWS channel, analyzes sentiment and impact,
emits market impact assessments autonomously.
"""

from __future__ import annotations

from typing import Dict, Any, Optional
from agents.streaming_agent import StreamingAgent
from core.streaming_bus import EventChannel, StreamEvent


class NewsAnalystAgent(StreamingAgent):
    """
    Autonomous news analyst.
    
    Monitors news streams, assesses market impact, emits alerts.
    """
    
    def __init__(self, agent_id: str = "news-analyst-01"):
        super().__init__(
            agent_id=agent_id,
            channels=[EventChannel.NEWS],
            model="merid-strategist:latest"
        )
        
        # High-impact keywords
        self.high_impact_keywords = [
            'sec', 'regulation', 'ban', 'hack', 'exploit', 'etf',
            'approval', 'adoption', 'partnership', 'lawsuit', 'crash',
            'rally', 'breakthrough', 'record', 'milestone'
        ]
        
    async def analyze(self, event: StreamEvent) -> Optional[Dict[str, Any]]:
        """
        Analyze news event.
        
        Assesses:
        - Sentiment (positive/negative/neutral)
        - Market impact (high/medium/low)
        - Urgency
        """
        if event.event_type != "article":
            return None
        
        data = event.data
        title = data.get("title", "").lower()
        summary = data.get("summary", "").lower()
        sentiment = data.get("sentiment", 0.0)
        
        # Calculate impact score
        impact_score = self._calculate_impact(title, summary, sentiment)
        
        # Only emit for medium/high impact news
        if impact_score < 0.3:
            return None
        
        # Determine impact level
        if impact_score >= 0.7:
            impact_level = "high"
        elif impact_score >= 0.5:
            impact_level = "medium"
        else:
            impact_level = "low"
        
        # Determine direction
        if sentiment > 0.3:
            direction = "bullish"
        elif sentiment < -0.3:
            direction = "bearish"
        else:
            direction = "neutral"
        
        return {
            "type": "news_impact",
            "title": data.get("title"),
            "source": data.get("source_name"),
            "sentiment": sentiment,
            "impact_level": impact_level,
            "impact_score": impact_score,
            "direction": direction,
            "confidence": min(impact_score, 0.9),
            "reasoning": f"{impact_level.upper()} impact {direction} news from {data.get('source_name')}"
        }
    
    def _calculate_impact(self, title: str, summary: str, sentiment: float) -> float:
        """Calculate market impact score (0-1)."""
        text = f"{title} {summary}"
        
        # Count high-impact keywords
        keyword_count = sum(1 for kw in self.high_impact_keywords if kw in text)
        
        # Base score from keywords
        keyword_score = min(keyword_count * 0.2, 0.6)
        
        # Sentiment contribution
        sentiment_score = abs(sentiment) * 0.4
        
        return min(keyword_score + sentiment_score, 1.0)
