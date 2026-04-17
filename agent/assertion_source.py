"""
Agent Assertion Source

Provides agent domain assertions to reduce blind spots in the reality system.
"""

import threading
import time
import uuid
from typing import Dict, List, Optional
from dataclasses import dataclass

from core.reality_registry import (
    get_reality_registry,
    AssertionDomain,
    AssertionProvenance,
    RealityAssertion,
    AssertionStatus
)
from utils.logger import get_logger

logger = get_logger("agent.assertion_source")


@dataclass
class AgentAssertion:
    """Agent data assertion for reality system."""
    agent_name: str
    status: str
    health_score: float
    last_heartbeat: float
    timestamp: float
    source: str
    confidence: float = 0.9


class AgentAssertionSource:
    """
    Agent data assertion source for reality system.
    
    Periodically registers agent state assertions to reduce blind spots
    in the agent domain.
    """
    
    def __init__(self):
        self.registry = get_reality_registry()
        self.last_assertion_time = 0.0
        self.assertion_interval = 240.0  # 4 minutes
        self.agent_state_cache: Dict[str, AgentAssertion] = {}
    
    def update_agent_state(self, agent_name: str, status: str, health_score: float, 
                         last_heartbeat: float, source: str = "swarm_registry"):
        """Update agent state and register assertion if needed."""
        current_time = time.time()
        
        # Cache the agent state
        self.agent_state_cache[agent_name] = AgentAssertion(
            agent_name=agent_name,
            status=status,
            health_score=health_score,
            last_heartbeat=last_heartbeat,
            timestamp=current_time,
            source=source,
            confidence=0.9
        )
        
        # Register assertion if interval has passed
        if current_time - self.last_assertion_time >= self.assertion_interval:
            self._register_agent_assertion(agent_name)
            self.last_assertion_time = current_time
    
    def _register_agent_assertion(self, agent_name: str):
        """Register an agent state assertion."""
        try:
            agent_data = self.agent_state_cache.get(agent_name)
            if not agent_data:
                logger.warning(f"No agent data available for {agent_name}")
                return
            
            # Create assertion
            assertion_id = self.registry.register_assertion(
                domain=AssertionDomain.AGENT,
                description=f"Agent {agent_name}: {agent_data.status}, health {agent_data.health_score:.2f}, heartbeat {agent_data.last_heartbeat}",
                confidence=agent_data.confidence,
                provenance_score=0.8,
                regime_compatibility=1.0,
                decay_rate=0.02,  # Agent data decays slowly
                validity_window=1200.0,  # 20 minutes
                sources=[
                    AssertionProvenance(
                        source_id="agent_feed",
                        module_id="agent_assertion_source",
                        evidence_hash=f"agent_{agent_name}_{agent_data.timestamp}",
                        weight=1.0,
                        timestamp=agent_data.timestamp
                    )
                ]
            )
            
            logger.info(f"Registered agent assertion: {agent_name} - {assertion_id}")
            
        except Exception as e:
            logger.error(f"Error registering agent assertion for {agent_name}: {e}")
    
    def register_batch_agent_data(self, agent_data_list: List[Dict]):
        """Register multiple agent data assertions at once."""
        for agent_data in agent_data_list:
            agent_name = agent_data.get("agent_name")
            status = agent_data.get("status")
            health_score = agent_data.get("health_score")
            last_heartbeat = agent_data.get("last_heartbeat")
            source = agent_data.get("source", "batch")
            
            if agent_name and status and health_score is not None and last_heartbeat is not None:
                # Cache the agent data
                current_time = time.time()
                self.agent_state_cache[agent_name] = AgentAssertion(
                    agent_name=agent_name,
                    status=status,
                    health_score=health_score,
                    last_heartbeat=last_heartbeat,
                    timestamp=current_time,
                    source=source,
                    confidence=0.9
                )
                
                # Register assertion immediately for demo data (bypass interval check)
                if source == "demo":
                    self._register_agent_assertion(agent_name)
                else:
                    self.update_agent_state(agent_name, status, health_score, last_heartbeat, source)
    
    def get_agent_assertions(self) -> List[Dict]:
        """Get all agent assertions from the registry."""
        try:
            assertions = self.registry.get_assertions_by_domain(AssertionDomain.AGENT)
            return [
                {
                    "assertion_id": a.assertion_id,
                    "agent_name": a.description.split(":")[0].replace("Agent ", ""),
                    "description": a.description,
                    "confidence_score": a.confidence_score,
                    "provenance_score": a.provenance_score,
                    "status": a.status.value,
                    "created_at": a.created_at,
                    "effective_confidence": a.effective_confidence(time.time(), self.registry.regime_entropy),
                    "is_usable": a.is_usable(time.time(), self.registry.regime_entropy)
                }
                for a in assertions
            ]
        except Exception as e:
            logger.error(f"Error getting agent assertions: {e}")
            return []


# Singleton instance
_agent_source: Optional[AgentAssertionSource] = None
_agent_source_lock = threading.Lock()


def get_agent_assertion_source() -> AgentAssertionSource:
    """Get the global agent assertion source."""
    global _agent_source
    if _agent_source is None:
        with _agent_source_lock:
            if _agent_source is None:
                _agent_source = AgentAssertionSource()
    return _agent_source


# Example usage
if __name__ == "__main__":
    # Create agent assertion source
    source = get_agent_assertion_source()
    
    # Update some agent data
    source.update_agent_state("governance_agent", "ACTIVE", 0.95, time.time(), "swarm_registry")
    source.update_agent_state("risk_agent", "ACTIVE", 0.92, time.time(), "swarm_registry")
    source.update_agent_state("execution_agent", "ACTIVE", 0.88, time.time(), "bootstrap")
    
    # Get agent assertions
    assertions = source.get_agent_assertions()
    print(f"Agent assertions: {len(assertions)}")
    for assertion in assertions[:3]:  # Show first 3
        print(f"  - {assertion['agent_name']}: {assertion['status']} (confidence: {assertion['confidence_score']:.2f})")
    
    print("Agent assertion source is ready!")
