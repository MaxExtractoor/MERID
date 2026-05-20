"""Outbound Publisher Agents.

Publishes trading decisions, consensus, and position updates to social platforms
(e.g., Twitter/X) by pulling recent activities and formatting them.
"""

from typing import Any, Dict
from merid.agents.base import CanonicalAgent, AgentCategory
from merid.prediction.social_broadcaster import KalshiSocialBroadcaster

class TwitterPublisherAgent(CanonicalAgent):
    """
    Agent that acts as a publisher to Twitter/X for the system's actions.
    Periodically checks the event bus or social broadcaster to ensure 
    events have been published.
    """
    def __init__(self, agent_id: str = "twitter-publisher-01"):
        super().__init__(agent_id, AgentCategory.OPS)
        self.broadcaster = KalshiSocialBroadcaster()
        self._started = False

    async def _execute(self, context: Dict[str, Any]) -> Any:
        self.logger.info("Running TwitterPublisher cycle")
        
        # Start the broadcaster if not already running
        if not self._started:
            await self.broadcaster.start()
            self._started = True
            
        # Normally this would fetch pending draft tweets and publish them
        # For scaffolding, we just report the broadcaster status
        
        messages_logged = getattr(self.broadcaster, "_messages_logged", 0)
        return {
            "status": "running",
            "messages_published": messages_logged,
            "provider": "twitter"
        }
        
    async def stop(self) -> None:
        """Stop the broadcaster on shutdown."""
        if self._started:
            await self.broadcaster.stop()
            self._started = False
