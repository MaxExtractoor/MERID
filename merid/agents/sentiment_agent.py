from typing import Any, Dict
from merid.agents.base import CanonicalAgent, AgentCategory
from merid.agents.coordination import AgentVote
from merid.pipeline.proposal import TradeProposal, OrderSide
from merid.sentiment.sentiment_bus import get_sentiment_bus

class SentimentVotingAgent(CanonicalAgent):
    """
    Subscribes to SentimentBus and votes on TradeProposals based on social/news sentiment.
    """
    def __init__(self, agent_id: str = "sentiment-voter-01"):
        super().__init__(agent_id, AgentCategory.RESEARCH)
        self.bus = get_sentiment_bus()

    async def _execute(self, context: Dict[str, Any]) -> Any:
        pass

    async def vote(self, proposal: TradeProposal) -> AgentVote:
        # Limit to crypto domain
        if proposal.domain.value != "crypto":
            return AgentVote(
                agent_id=self.agent_id, decision="abstain", confidence=0.0,
                reasoning=f"Unsupported domain: {proposal.domain.value}"
            )

        # Infer asset from instrument_id (e.g. KXBTCD-25JUN-T100000 -> BTC)
        asset = "BTC"
        if "ETH" in proposal.instrument_id:
            asset = "ETH"
        elif "SOL" in proposal.instrument_id:
            asset = "SOL"
            
        sentiment = self.bus.get_sentiment(asset)
        
        if not sentiment:
            return AgentVote(
                agent_id=self.agent_id,
                decision="abstain",
                confidence=0.0,
                reasoning=f"No sentiment data available for {asset}"
            )
            
        score = sentiment.combined_social_sentiment
        
        # Map sentiment score to approval/rejection.
        # Assuming BUY means betting YES on the outcome (price going up or hitting target).
        is_yes = proposal.side == OrderSide.BUY
        
        decision = "abstain"
        reasoning = f"Sentiment is neutral ({score:.2f})"
        
        if score > 0.15:
            if is_yes:
                decision = "approve"
                reasoning = f"Positive sentiment ({score:.2f}) supports YES"
            else:
                decision = "reject"
                reasoning = f"Positive sentiment ({score:.2f}) opposes NO"
        elif score < -0.15:
            if is_yes:
                decision = "reject"
                reasoning = f"Negative sentiment ({score:.2f}) opposes YES"
            else:
                decision = "approve"
                reasoning = f"Negative sentiment ({score:.2f}) supports NO"
                
        # Boost confidence if we have high volume and strong sentiment
        confidence = sentiment.social_confidence
        if abs(score) > 0.4:
            confidence = min(1.0, confidence + 0.2)
            
        return AgentVote(
            agent_id=self.agent_id,
            decision=decision,
            confidence=confidence,
            reasoning=reasoning,
            weight=1.0
        )
