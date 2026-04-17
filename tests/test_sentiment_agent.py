import pytest
import asyncio
from decimal import Decimal
from merid.pipeline.proposal import TradeProposal, OrderSide, OrderType, TradeDomain
from merid.agents.sentiment_agent import SentimentVotingAgent
from merid.sentiment.sentiment_bus import get_sentiment_bus, UnifiedSentiment
from datetime import datetime, timezone

class MockSentimentBus:
    def __init__(self):
        self.sentiments = {}
        
    def get_sentiment(self, asset: str):
        return self.sentiments.get(asset)

@pytest.mark.asyncio
async def test_sentiment_voting_agent():
    # Mock bus
    bus = MockSentimentBus()
    bus.sentiments["BTC"] = UnifiedSentiment(
        asset="BTC",
        timestamp=datetime.now(timezone.utc),
        twitter_score=0.5,
        twitter_confidence=0.8,
        twitter_volume=100,
        reddit_score=0.6,
        reddit_confidence=0.7,
        reddit_volume=50,
        combined_social_sentiment=0.55,
        social_confidence=0.75,
        vader_signal="bullish",
        fear_greed_index=70,
        trend_regime="greed"
    )
    
    agent = SentimentVotingAgent()
    agent.bus = bus  # Override with mock
    
    # Test positive sentiment + YES side
    prop_yes = TradeProposal(
        proposal_id="test_1",
        domain=TradeDomain.CRYPTO,
        instrument_id="KXBTCD-25JUN-T100000",
        side=OrderSide.BUY,  # YES
        qty=Decimal("10")
    )
    
    vote_yes = await agent.vote(prop_yes)
    assert vote_yes.decision == "approve"
    assert vote_yes.confidence > 0.7  # boosted by high score
    
    # Test positive sentiment + NO side
    prop_no = TradeProposal(
        proposal_id="test_2",
        domain=TradeDomain.CRYPTO,
        instrument_id="KXBTCD-25JUN-T100000",
        side=OrderSide.SELL,  # NO
        qty=Decimal("10")
    )
    
    vote_no = await agent.vote(prop_no)
    assert vote_no.decision == "reject"

    # Test neutral sentiment
    bus.sentiments["ETH"] = UnifiedSentiment(
        asset="ETH",
        timestamp=datetime.now(timezone.utc),
        twitter_score=0.0,
        twitter_confidence=0.5,
        twitter_volume=10,
        reddit_score=0.0,
        reddit_confidence=0.5,
        reddit_volume=5,
        combined_social_sentiment=0.05,
        social_confidence=0.5,
        vader_signal="neutral",
        fear_greed_index=50,
        trend_regime="neutral"
    )
    
    prop_neutral = TradeProposal(
        proposal_id="test_3",
        domain=TradeDomain.CRYPTO,
        instrument_id="KXETHD-25JUN-T5000",
        side=OrderSide.BUY,
        qty=Decimal("10")
    )
    
    vote_neutral = await agent.vote(prop_neutral)
    assert vote_neutral.decision == "abstain"
