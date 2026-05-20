"""
NewsAnalyst Agent - Sentiment analysis per MASTER_SPEC v1.0

Agent ID: news-analyst-01
Role: News and social sentiment analysis
Expertise: 0.88
Risk Factor: 0.3

This agent:
- Observes news stream events (articles, social signals)
- Analyzes sentiment and impact potential
- Votes on proposals based on news sentiment
- Reflects on prediction accuracy to improve

Reference: MASTER_SPEC.md Section 4.1
"""

from __future__ import annotations

import threading
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from agents.interface import (
    AgentInterface,
    AgentVote,
    VoteDecision,
    MarketState,
    Proposal,
    Outcome,
    AgentState,
)
from utils.logger import get_logger

logger = get_logger("agents.news_analyst")


@dataclass
class NewsSignal:
    """Processed news signal with sentiment."""
    signal_id: str
    source: str
    title: str
    timestamp: float
    sentiment_score: float
    impact_score: float
    keywords: List[str]
    category: str


@dataclass
class SentimentSnapshot:
    """Aggregated sentiment at a point in time."""
    timestamp: float
    overall_sentiment: float
    signal_count: int
    bullish_count: int
    bearish_count: int
    neutral_count: int
    high_impact_count: int


class NewsAnalystAgent(AgentInterface):
    """
    News Analyst Agent - Specializes in sentiment analysis.
    
    Capabilities:
    - News headline sentiment scoring
    - Impact assessment (regulatory, adoption, technical)
    - Keyword extraction and categorization
    - Trend detection in news flow
    - Social signal aggregation
    
    This agent consumes news events and generates
    sentiment signals for consensus voting.
    """
    
    AGENT_ID = "news-analyst-01"
    EXPERTISE_SCORE = 0.88
    RISK_FACTOR = 0.3
    
    SIGNAL_HISTORY_LIMIT = 500
    SENTIMENT_WINDOW_HOURS = 24
    
    BULLISH_KEYWORDS = frozenset([
        "bullish", "surge", "rally", "breakout", "adoption", "partnership",
        "approval", "etf", "institutional", "upgrade", "milestone", "record",
        "growth", "profit", "gain", "soar", "jump", "spike", "moon",
        "accumulation", "buy", "long", "support", "breakthrough"
    ])
    
    BEARISH_KEYWORDS = frozenset([
        "bearish", "crash", "dump", "plunge", "ban", "regulation", "hack",
        "exploit", "scam", "fraud", "lawsuit", "sec", "warning", "risk",
        "loss", "decline", "fall", "drop", "sell", "short", "resistance",
        "liquidation", "bankruptcy", "collapse", "fear"
    ])
    
    HIGH_IMPACT_KEYWORDS = frozenset([
        "sec", "regulation", "ban", "etf", "approval", "hack", "exploit",
        "fed", "interest", "inflation", "halving", "fork", "upgrade",
        "partnership", "adoption", "institutional", "government"
    ])
    
    def __init__(self) -> None:
        """Initialize news analyst agent."""
        super().__init__(
            agent_id=self.AGENT_ID,
            expertise_score=self.EXPERTISE_SCORE,
            risk_factor=self.RISK_FACTOR,
        )
        
        self._signal_history: List[NewsSignal] = []
        self._sentiment_snapshots: List[SentimentSnapshot] = []
        self._keyword_counts: Dict[str, int] = defaultdict(int)
        self._source_sentiment: Dict[str, List[float]] = defaultdict(list)
        self._last_analysis: Optional[Dict[str, object]] = None
        self._prediction_history: List[Dict[str, object]] = []
    
    async def observe(self, market_state: MarketState) -> None:
        """
        Ingest market state (primarily for news sentiment in metadata).
        
        Args:
            market_state: Current market snapshot
        """
        self._state = AgentState.PROCESSING
        self.heartbeat()
        
        self.set_working_memory("news_sentiment", market_state.news_sentiment)
        self.set_working_memory("last_observation", time.time())
        
        self._logger.debug(
            "Observed market state: news_sentiment=%.2f",
            market_state.news_sentiment
        )
    
    def process_news_event(self, event_payload: Dict[str, object]) -> Optional[NewsSignal]:
        """
        Process a news event and extract sentiment signal.
        
        Args:
            event_payload: News event payload from stream
            
        Returns:
            Processed NewsSignal or None if invalid
        """
        title = str(event_payload.get("title", ""))
        if not title:
            return None
        
        source = str(event_payload.get("source", "unknown"))
        item_id = str(event_payload.get("item_id", ""))
        published_at = float(event_payload.get("published_at", time.time()))
        keywords = list(event_payload.get("keywords", []))
        
        sentiment_score = self._calculate_sentiment(title, keywords)
        impact_score = self._calculate_impact(title, keywords)
        category = self._categorize_news(title, keywords)
        
        signal = NewsSignal(
            signal_id=item_id,
            source=source,
            title=title,
            timestamp=published_at,
            sentiment_score=sentiment_score,
            impact_score=impact_score,
            keywords=keywords,
            category=category,
        )
        
        self._signal_history.append(signal)
        if len(self._signal_history) > self.SIGNAL_HISTORY_LIMIT:
            self._signal_history = self._signal_history[-self.SIGNAL_HISTORY_LIMIT:]
        
        for kw in keywords:
            self._keyword_counts[kw.lower()] += 1
        
        self._source_sentiment[source].append(sentiment_score)
        if len(self._source_sentiment[source]) > 100:
            self._source_sentiment[source] = self._source_sentiment[source][-100:]
        
        return signal
    
    async def analyze(self) -> Dict[str, object]:
        """
        Generate sentiment analysis from observed signals.
        
        Returns:
            Analysis results with sentiment assessment
        """
        self._state = AgentState.PROCESSING
        start_time = time.time()
        
        cutoff = time.time() - (self.SENTIMENT_WINDOW_HOURS * 3600)
        recent_signals = [s for s in self._signal_history if s.timestamp > cutoff]
        
        if not recent_signals:
            self._last_analysis = {
                "timestamp": time.time(),
                "signal_count": 0,
                "overall_sentiment": 0.0,
                "confidence": 0.3,
                "assessment": "insufficient_data",
            }
            return self._last_analysis
        
        sentiment_scores = [s.sentiment_score for s in recent_signals]
        impact_scores = [s.impact_score for s in recent_signals]
        
        overall_sentiment = sum(sentiment_scores) / len(sentiment_scores)
        avg_impact = sum(impact_scores) / len(impact_scores)
        
        bullish_count = sum(1 for s in sentiment_scores if s > 0.2)
        bearish_count = sum(1 for s in sentiment_scores if s < -0.2)
        neutral_count = len(sentiment_scores) - bullish_count - bearish_count
        high_impact_count = sum(1 for s in impact_scores if s > 0.7)
        
        snapshot = SentimentSnapshot(
            timestamp=time.time(),
            overall_sentiment=overall_sentiment,
            signal_count=len(recent_signals),
            bullish_count=bullish_count,
            bearish_count=bearish_count,
            neutral_count=neutral_count,
            high_impact_count=high_impact_count,
        )
        self._sentiment_snapshots.append(snapshot)
        if len(self._sentiment_snapshots) > 100:
            self._sentiment_snapshots = self._sentiment_snapshots[-100:]
        
        sentiment_trend = self._calculate_sentiment_trend()
        top_keywords = self._get_top_keywords(10)
        source_reliability = self._calculate_source_reliability()
        
        if overall_sentiment > 0.3:
            assessment = "bullish"
        elif overall_sentiment < -0.3:
            assessment = "bearish"
        else:
            assessment = "neutral"
        
        confidence = self._calculate_confidence(
            len(recent_signals), avg_impact, sentiment_trend
        )
        
        self._last_analysis = {
            "timestamp": time.time(),
            "signal_count": len(recent_signals),
            "overall_sentiment": overall_sentiment,
            "avg_impact": avg_impact,
            "bullish_count": bullish_count,
            "bearish_count": bearish_count,
            "neutral_count": neutral_count,
            "high_impact_count": high_impact_count,
            "sentiment_trend": sentiment_trend,
            "top_keywords": top_keywords,
            "source_reliability": source_reliability,
            "assessment": assessment,
            "confidence": confidence,
        }
        
        latency_ms = (time.time() - start_time) * 1000
        self._record_processing(latency_ms, True)
        
        self._logger.info(
            "Analysis complete: %d signals, sentiment=%.2f, assessment=%s, confidence=%.2f",
            len(recent_signals), overall_sentiment, assessment, confidence
        )
        
        return self._last_analysis
    
    async def vote(self, proposal: Proposal) -> AgentVote:
        """
        Cast vote on proposal based on sentiment analysis.
        
        Args:
            proposal: Proposal to vote on
            
        Returns:
            Agent's vote with reasoning
        """
        self._state = AgentState.VOTING
        self.heartbeat()
        
        if proposal.is_expired():
            return AgentVote(
                agent_id=self._agent_id,
                decision=VoteDecision.ABSTAIN,
                confidence=0.0,
                reasoning="Proposal expired before vote could be cast",
            )
        
        if self._last_analysis is None or self._last_analysis.get("signal_count", 0) == 0:
            return AgentVote(
                agent_id=self._agent_id,
                decision=VoteDecision.ABSTAIN,
                confidence=0.3,
                reasoning="Insufficient news data for informed vote",
            )
        
        decision, confidence, reasoning = self._evaluate_proposal(
            proposal.proposal_type, proposal.payload
        )
        
        self._prediction_history.append({
            "proposal_id": proposal.proposal_id,
            "decision": decision.value,
            "confidence": confidence,
            "timestamp": time.time(),
            "sentiment": self._last_analysis.get("overall_sentiment", 0),
        })
        
        if len(self._prediction_history) > 100:
            self._prediction_history = self._prediction_history[-100:]
        
        self._state = AgentState.READY
        
        return AgentVote(
            agent_id=self._agent_id,
            decision=decision,
            confidence=confidence,
            reasoning=reasoning,
        )
    
    async def reflect(self, outcome: Outcome) -> None:
        """
        Update internal state based on outcome.
        
        Args:
            outcome: Outcome of the proposal
        """
        self._state = AgentState.REFLECTING
        self.heartbeat()
        
        matching_prediction = None
        for pred in self._prediction_history:
            if pred.get("proposal_id") == outcome.proposal_id:
                matching_prediction = pred
                break
        
        if matching_prediction is None:
            return
        
        was_correct = self._evaluate_prediction_accuracy(matching_prediction, outcome)
        
        self.set_working_memory(f"outcome:{outcome.proposal_id}", {
            "prediction": matching_prediction["decision"],
            "actual": outcome.result,
            "correct": was_correct,
            "sentiment_at_vote": matching_prediction.get("sentiment", 0),
        })
        
        self._state = AgentState.READY
    
    def _calculate_sentiment(self, title: str, keywords: List[str]) -> float:
        """
        Calculate sentiment score from title and keywords.
        
        Args:
            title: News headline
            keywords: Extracted keywords
            
        Returns:
            Sentiment score [-1.0, 1.0]
        """
        text = f"{title} {' '.join(keywords)}".lower()
        words = set(re.findall(r'\w+', text))
        
        bullish_matches = len(words & self.BULLISH_KEYWORDS)
        bearish_matches = len(words & self.BEARISH_KEYWORDS)
        
        total_matches = bullish_matches + bearish_matches
        if total_matches == 0:
            return 0.0
        
        sentiment = (bullish_matches - bearish_matches) / total_matches
        return max(-1.0, min(1.0, sentiment))
    
    def _calculate_impact(self, title: str, keywords: List[str]) -> float:
        """
        Calculate impact score from title and keywords.
        
        Args:
            title: News headline
            keywords: Extracted keywords
            
        Returns:
            Impact score [0.0, 1.0]
        """
        text = f"{title} {' '.join(keywords)}".lower()
        words = set(re.findall(r'\w+', text))
        
        high_impact_matches = len(words & self.HIGH_IMPACT_KEYWORDS)
        
        base_impact = min(high_impact_matches / 3, 1.0)
        
        if any(word in text for word in ["breaking", "urgent", "alert"]):
            base_impact = min(base_impact + 0.3, 1.0)
        
        return base_impact
    
    def _categorize_news(self, title: str, keywords: List[str]) -> str:
        """
        Categorize news by topic.
        
        Args:
            title: News headline
            keywords: Extracted keywords
            
        Returns:
            Category string
        """
        text = f"{title} {' '.join(keywords)}".lower()
        
        if any(word in text for word in ["sec", "regulation", "ban", "lawsuit", "government"]):
            return "regulatory"
        if any(word in text for word in ["hack", "exploit", "scam", "fraud", "security"]):
            return "security"
        if any(word in text for word in ["partnership", "adoption", "institutional"]):
            return "adoption"
        if any(word in text for word in ["upgrade", "fork", "protocol", "development"]):
            return "technical"
        if any(word in text for word in ["etf", "fund", "investment", "trading"]):
            return "market"
        
        return "general"
    
    def _calculate_sentiment_trend(self) -> str:
        """Calculate trend in sentiment over recent snapshots."""
        if len(self._sentiment_snapshots) < 3:
            return "stable"
        
        recent = self._sentiment_snapshots[-5:]
        sentiments = [s.overall_sentiment for s in recent]
        
        first_half = sum(sentiments[:len(sentiments)//2]) / max(len(sentiments)//2, 1)
        second_half = sum(sentiments[len(sentiments)//2:]) / max(len(sentiments) - len(sentiments)//2, 1)
        
        diff = second_half - first_half
        
        if diff > 0.1:
            return "improving"
        elif diff < -0.1:
            return "deteriorating"
        else:
            return "stable"
    
    def _get_top_keywords(self, n: int) -> List[Dict[str, object]]:
        """Get top N keywords by frequency."""
        sorted_keywords = sorted(
            self._keyword_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )
        return [{"keyword": k, "count": c} for k, c in sorted_keywords[:n]]
    
    def _calculate_source_reliability(self) -> Dict[str, float]:
        """Calculate reliability score per source."""
        reliability = {}
        for source, sentiments in self._source_sentiment.items():
            if len(sentiments) < 5:
                reliability[source] = 0.5
            else:
                variance = sum((s - sum(sentiments)/len(sentiments))**2 for s in sentiments) / len(sentiments)
                reliability[source] = max(0.3, 1.0 - variance)
        return reliability
    
    def _calculate_confidence(
        self,
        signal_count: int,
        avg_impact: float,
        trend: str,
    ) -> float:
        """Calculate confidence in analysis."""
        data_confidence = min(signal_count / 50, 1.0)
        impact_confidence = avg_impact
        trend_confidence = 0.7 if trend != "stable" else 0.5
        
        base_confidence = (
            data_confidence * 0.4 +
            impact_confidence * 0.3 +
            trend_confidence * 0.3
        )
        
        return base_confidence * self._expertise_score
    
    def _evaluate_proposal(
        self,
        proposal_type: str,
        payload: Dict[str, object],
    ) -> tuple[VoteDecision, float, str]:
        """Evaluate proposal and determine vote."""
        if self._last_analysis is None:
            return (VoteDecision.ABSTAIN, 0.3, "No analysis available")
        
        sentiment = self._last_analysis.get("overall_sentiment", 0)
        assessment = self._last_analysis.get("assessment", "neutral")
        confidence = self._last_analysis.get("confidence", 0.5)
        trend = self._last_analysis.get("sentiment_trend", "stable")
        
        if proposal_type in ("buy", "long", "bullish_bet"):
            if assessment == "bullish" and sentiment > 0.3:
                return (
                    VoteDecision.APPROVE,
                    min(confidence + 0.1, 0.95),
                    f"News sentiment is {assessment} ({sentiment:.2f}), trend is {trend}. "
                    f"Sentiment supports bullish position.",
                )
            elif assessment == "bearish" and sentiment < -0.3:
                return (
                    VoteDecision.REJECT,
                    min(confidence + 0.1, 0.95),
                    f"News sentiment is {assessment} ({sentiment:.2f}), trend is {trend}. "
                    f"Sentiment contradicts bullish position.",
                )
            else:
                return (
                    VoteDecision.ABSTAIN,
                    0.4,
                    f"News sentiment is {assessment} ({sentiment:.2f}). "
                    f"Insufficient conviction to support or reject.",
                )
        
        elif proposal_type in ("sell", "short", "bearish_bet"):
            if assessment == "bearish" and sentiment < -0.3:
                return (
                    VoteDecision.APPROVE,
                    min(confidence + 0.1, 0.95),
                    f"News sentiment is {assessment} ({sentiment:.2f}), trend is {trend}. "
                    f"Sentiment supports bearish position.",
                )
            elif assessment == "bullish" and sentiment > 0.3:
                return (
                    VoteDecision.REJECT,
                    min(confidence + 0.1, 0.95),
                    f"News sentiment is {assessment} ({sentiment:.2f}), trend is {trend}. "
                    f"Sentiment contradicts bearish position.",
                )
            else:
                return (
                    VoteDecision.ABSTAIN,
                    0.4,
                    f"News sentiment is {assessment} ({sentiment:.2f}). "
                    f"Insufficient conviction to support or reject.",
                )
        
        return (
            VoteDecision.ABSTAIN,
            0.3,
            f"Proposal type '{proposal_type}' not in news analyst domain.",
        )
    
    def _evaluate_prediction_accuracy(
        self,
        prediction: Dict[str, object],
        outcome: Outcome,
    ) -> bool:
        """Evaluate if prediction was correct."""
        pred_decision = prediction.get("decision", "abstain")
        actual_result = outcome.result
        
        if pred_decision == "approve" and actual_result in ("success", "profit", "correct"):
            return True
        if pred_decision == "reject" and actual_result in ("failure", "loss", "incorrect"):
            return True
        
        return False


_news_analyst: Optional[NewsAnalystAgent] = None
_news_analyst_lock = threading.Lock()


def get_news_analyst() -> NewsAnalystAgent:
    """Get or create news analyst agent singleton."""
    global _news_analyst
    if _news_analyst is None:
        with _news_analyst_lock:
            if _news_analyst is None:
                _news_analyst = NewsAnalystAgent()
    return _news_analyst
