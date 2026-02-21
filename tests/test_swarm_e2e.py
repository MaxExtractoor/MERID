"""
End-to-End Swarm Integration Test

Tests the complete opinion → consensus → trade flow:
1. Multiple strategy agents emit StrategyOpinion events
2. ConsensusCoordinator consumes opinions and forms consensus
3. ConsensusDecision is emitted with opinion IDs
4. Full ancestry is traceable

Usage:
    pytest tests/test_swarm_e2e.py -v
    # Or run directly:
    python tests/test_swarm_e2e.py
"""

import asyncio
import time
from typing import List

from agents.strategy_agent import StrategyAgent
from consensus.consensus_coordinator import get_consensus_coordinator, ConsensusConfig
from schemas.swarm_events import TradingMode, StrategyOpinion, ConsensusDecision
from observability.event_stream import get_event_stream
from utils.logger import get_logger

logger = get_logger("tests.swarm_e2e")


class SwarmE2ETest:
    """End-to-end test for swarm integration."""
    
    def __init__(self):
        self.opinions_received: List[StrategyOpinion] = []
        self.consensus_received: List[ConsensusDecision] = []
        self.event_stream = get_event_stream()
        
    async def setup(self):
        """Setup test environment."""
        # Start consensus coordinator
        config = ConsensusConfig(
            min_agents_for_quorum=3,
            round_timeout_seconds=10.0,
        )
        self.coordinator = get_consensus_coordinator(config)
        await self.coordinator.start_opinion_subscriber()
        
        # Subscribe to events
        self.event_queue = await self.event_stream.subscribe()
        
        logger.info("Test environment setup complete")
    
    async def teardown(self):
        """Cleanup test environment."""
        await self.coordinator.stop_opinion_subscriber()
        await self.event_stream.unsubscribe(self.event_queue)
        logger.info("Test environment cleaned up")
    
    async def collect_events(self, duration: float = 5.0):
        """Collect events for specified duration."""
        end_time = time.time() + duration
        
        while time.time() < end_time:
            try:
                event = await asyncio.wait_for(
                    self.event_queue.get(),
                    timeout=0.5
                )
                
                if event.event_type == "strategy_opinion":
                    opinion = StrategyOpinion(**event.payload)
                    self.opinions_received.append(opinion)
                    logger.info(f"Collected opinion: {opinion.agent_id} → {opinion.symbol} {opinion.direction.value}")
                
                elif event.event_type == "consensus_decision":
                    decision = ConsensusDecision(**event.payload)
                    self.consensus_received.append(decision)
                    logger.info(f"Collected consensus: {decision.symbol} → {decision.decision.value} ({len(decision.opinion_ids)} opinions)")
            
            except asyncio.TimeoutError:
                continue
    
    async def test_opinion_to_consensus_flow(self):
        """
        Test Case 1: Opinion → Consensus Flow
        
        Verify that:
        - Multiple agents emit opinions
        - Consensus forms when quorum reached
        - Consensus includes opinion IDs for ancestry
        """
        logger.info("\n" + "="*80)
        logger.info("TEST: Opinion → Consensus Flow")
        logger.info("="*80)
        
        # Create 3 strategy agents
        agents = [
            StrategyAgent(agent_id=f"test-strategy-{i:02d}")
            for i in range(1, 4)
        ]
        
        for agent in agents:
            agent.set_trading_mode(TradingMode.SIMULATION)
        
        # Start event collector
        collector_task = asyncio.create_task(self.collect_events(duration=10.0))
        
        # Give consensus subscriber time to start
        await asyncio.sleep(0.5)
        
        # Each agent processes same signal and emits opinion
        symbol = "BTC/USDT"
        price = 50000.0
        
        for i, agent in enumerate(agents):
            energy = {
                "energy_id": f"test-{i:03d}",
                "symbol": symbol,
                "price": price,
                "payload": {
                    "symbol": symbol,
                    "price": price,
                    "signal": f"bullish momentum from agent {i}",
                }
            }
            
            result = await agent.process(energy)
            logger.info(f"Agent {agent.agent_id}: vote={result['vote']}, conf={result['confidence']:.2f}")
            
            # Small delay between opinions
            await asyncio.sleep(0.5)
        
        # Wait for events to be collected
        await collector_task
        
        # Stop heartbeats
        for agent in agents:
            await agent.stop_heartbeat_loop()
        
        # Verify results
        logger.info("\n" + "-"*80)
        logger.info("VERIFICATION")
        logger.info("-"*80)
        
        print(f"\n✓ Opinions received: {len(self.opinions_received)}")
        print(f"✓ Consensus formed: {len(self.consensus_received)}")
        
        # Check we got opinions from all agents
        assert len(self.opinions_received) >= 3, f"Expected ≥3 opinions, got {len(self.opinions_received)}"
        
        # Check opinions are for correct symbol
        for opinion in self.opinions_received:
            assert opinion.symbol == symbol, f"Opinion symbol mismatch: {opinion.symbol} != {symbol}"
        
        # Check consensus was formed
        assert len(self.consensus_received) > 0, "No consensus formed"
        
        # Check consensus has opinion IDs
        consensus = self.consensus_received[0]
        print(f"\nConsensus Details:")
        print(f"  Symbol: {consensus.symbol}")
        print(f"  Decision: {consensus.decision.value}")
        print(f"  Confidence: {consensus.confidence:.2f}")
        print(f"  Opinion IDs: {consensus.opinion_ids}")
        print(f"  Participating agents: {len(consensus.participating_agents)}")
        print(f"  Supporting: {len(consensus.supporting_agents)}")
        print(f"  Opposing: {len(consensus.opposing_agents)}")
        print(f"  Dissent ratio: {consensus.dissent_ratio:.2%}")
        
        assert len(consensus.opinion_ids) >= 3, f"Expected ≥3 opinion IDs, got {len(consensus.opinion_ids)}"
        assert len(consensus.participating_agents) >= 3, f"Expected ≥3 participating agents, got {len(consensus.participating_agents)}"
        
        # Verify ancestry: all opinion IDs in consensus are from actual opinions
        opinion_id_set = {op.opinion_id for op in self.opinions_received}
        for opinion_id in consensus.opinion_ids:
            assert opinion_id in opinion_id_set, f"Opinion ID {opinion_id} not found in received opinions"
        
        print(f"\n✓ Full ancestry verified: {len(consensus.opinion_ids)} opinions → 1 consensus")
        
        logger.info("\n" + "="*80)
        logger.info("✓ TEST PASSED: Opinion → Consensus Flow")
        logger.info("="*80 + "\n")
        
        return True


async def run_tests():
    """Run all swarm E2E tests."""
    test = SwarmE2ETest()
    
    try:
        await test.setup()
        
        # Run test
        result = await test.test_opinion_to_consensus_flow()
        
        if result:
            print("\n" + "="*80)
            print("✓ ALL TESTS PASSED")
            print("="*80)
            return 0
        else:
            print("\n" + "="*80)
            print("✗ TESTS FAILED")
            print("="*80)
            return 1
    
    except Exception as e:
        logger.error(f"Test failed with exception: {e}", exc_info=True)
        print(f"\n✗ TEST FAILED: {e}")
        return 1
    
    finally:
        await test.teardown()


if __name__ == "__main__":
    """Run tests when executed directly."""
    import sys
    
    print("\n" + "="*80)
    print("MERID Swarm E2E Integration Test")
    print("="*80)
    print("\nTesting: Opinion → Consensus flow with full ancestry tracking")
    print()
    
    exit_code = asyncio.run(run_tests())
    sys.exit(exit_code)
