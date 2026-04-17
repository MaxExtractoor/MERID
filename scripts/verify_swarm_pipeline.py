"""
Swarm Pipeline Verification Script

Quick verification that the full Opinion→Consensus→Execution pipeline is working.

Usage:
    python scripts/verify_swarm_pipeline.py
    
Requirements:
    - Backend must be running (uvicorn web.main:app)
"""

import asyncio
import sys
import time
from typing import List

from agents.strategy_agent import StrategyAgent
from schemas.swarm_events import TradingMode
from observability.event_stream import get_event_stream
from utils.logger import get_logger

logger = get_logger("scripts.verify_pipeline")

# ANSI colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
BOLD = "\033[1m"
RESET = "\033[0m"


class PipelineVerifier:
    """Verifies the complete swarm pipeline."""
    
    def __init__(self):
        self.event_stream = get_event_stream()
        self.opinions_received = 0
        self.consensus_received = 0
        self.trades_received = 0
        self.orders_received = 0
        self.test_symbol = "BTC/USDT"
        
    async def run_verification(self) -> bool:
        """Run full pipeline verification."""
        print(f"\n{BOLD}{BLUE}{'='*80}{RESET}")
        print(f"{BOLD}{BLUE}MERID SWARM PIPELINE VERIFICATION{RESET}")
        print(f"{BOLD}{BLUE}{'='*80}{RESET}\n")
        
        print(f"Testing: {self.test_symbol}")
        print(f"Mode: SIMULATION\n")
        
        # Step 1: Setup
        print(f"{BOLD}[1/5] Setting up components...{RESET}")
        agents = await self._setup_agents()
        event_queue = await self.event_stream.subscribe()
        print(f"  {GREEN}✓{RESET} 3 strategy agents created")
        print(f"  {GREEN}✓{RESET} Event stream subscriber ready\n")
        
        # Step 2: Start event collector
        print(f"{BOLD}[2/5] Starting event collector...{RESET}")
        collector_task = asyncio.create_task(
            self._collect_events(event_queue, duration=15.0)
        )
        await asyncio.sleep(1)
        print(f"  {GREEN}✓{RESET} Collector running\n")
        
        # Step 3: Trigger agents
        print(f"{BOLD}[3/5] Triggering agent opinions...{RESET}")
        await self._trigger_agents(agents)
        print(f"  {GREEN}✓{RESET} All agents processed signal\n")
        
        # Step 4: Wait for pipeline
        print(f"{BOLD}[4/5] Waiting for pipeline execution...{RESET}")
        print(f"  {YELLOW}→{RESET} Waiting for consensus formation...")
        await collector_task
        print(f"  {GREEN}✓{RESET} Event collection complete\n")
        
        # Step 5: Verify results
        print(f"{BOLD}[5/5] Verifying pipeline results...{RESET}")
        success = self._verify_results()
        
        # Cleanup
        await self._cleanup(agents, event_queue)
        
        return success
    
    async def _setup_agents(self) -> List[StrategyAgent]:
        """Create and configure test agents."""
        agents = [
            StrategyAgent(agent_id=f"verify-agent-{i:02d}")
            for i in range(1, 4)
        ]
        
        for agent in agents:
            agent.set_trading_mode(TradingMode.MOCK)
        
        return agents
    
    async def _trigger_agents(self, agents: List[StrategyAgent]) -> None:
        """Trigger all agents to emit opinions."""
        energy = {
            "energy_id": "verify-pipeline-001",
            "symbol": self.test_symbol,
            "price": 50000.0,
            "payload": {
                "symbol": self.test_symbol,
                "price": 50000.0,
                "signal": "verification test signal - bullish momentum",
            }
        }
        
        for i, agent in enumerate(agents, 1):
            result = await agent.process(energy)
            vote = result.get("vote", "abstain")
            conf = result.get("confidence", 0.0)
            print(f"  Agent {i}: {vote} (confidence={conf:.2f})")
            await asyncio.sleep(0.5)
    
    async def _collect_events(self, queue: asyncio.Queue, duration: float) -> None:
        """Collect events for specified duration."""
        end_time = time.time() + duration
        
        while time.time() < end_time:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=0.5)
                
                if event.event_type == "strategy_opinion":
                    self.opinions_received += 1
                    logger.info(f"Opinion received (total: {self.opinions_received})")
                
                elif event.event_type == "consensus_decision":
                    self.consensus_received += 1
                    logger.info(f"Consensus received (total: {self.consensus_received})")
                
                elif event.event_type == "trade_intent":
                    self.trades_received += 1
                    logger.info(f"Trade intent received (total: {self.trades_received})")
                
                elif event.event_type == "order_event":
                    self.orders_received += 1
                    logger.info(f"Order event received (total: {self.orders_received})")
            
            except asyncio.TimeoutError:
                continue
    
    def _verify_results(self) -> bool:
        """Verify pipeline executed correctly."""
        checks = []
        
        # Check 1: Opinions received
        opinions_ok = self.opinions_received >= 3
        status = f"{GREEN}✓{RESET}" if opinions_ok else f"{RED}✗{RESET}"
        print(f"  {status} Opinions received: {self.opinions_received}/3")
        checks.append(opinions_ok)
        
        # Check 2: Consensus formed
        consensus_ok = self.consensus_received >= 1
        status = f"{GREEN}✓{RESET}" if consensus_ok else f"{RED}✗{RESET}"
        print(f"  {status} Consensus formed: {self.consensus_received}/1")
        checks.append(consensus_ok)
        
        # Check 3: Trade intent created
        trade_ok = self.trades_received >= 1
        status = f"{GREEN}✓{RESET}" if trade_ok else f"{RED}✗{RESET}"
        print(f"  {status} Trade intent created: {self.trades_received}/1")
        checks.append(trade_ok)
        
        # Check 4: Order executed
        order_ok = self.orders_received >= 1
        status = f"{GREEN}✓{RESET}" if order_ok else f"{RED}✗{RESET}"
        print(f"  {status} Order executed: {self.orders_received}/1")
        checks.append(order_ok)
        
        print()
        
        # Overall result
        all_passed = all(checks)
        
        if all_passed:
            print(f"{BOLD}{GREEN}{'='*80}{RESET}")
            print(f"{BOLD}{GREEN}✓ PIPELINE VERIFICATION PASSED{RESET}")
            print(f"{BOLD}{GREEN}{'='*80}{RESET}\n")
            print(f"Full chain verified: Opinion → Consensus → Trade Intent → Order\n")
        else:
            print(f"{BOLD}{RED}{'='*80}{RESET}")
            print(f"{BOLD}{RED}✗ PIPELINE VERIFICATION FAILED{RESET}")
            print(f"{BOLD}{RED}{'='*80}{RESET}\n")
            
            print(f"{YELLOW}Troubleshooting:{RESET}")
            if not opinions_ok:
                print("  - Agents may not be emitting opinions correctly")
                print("  - Check that SwarmAgentMixin is integrated")
            if not consensus_ok:
                print("  - ConsensusCoordinator may not be subscribed to opinions")
                print("  - Check backend startup logs for consensus subscriber")
            if not trade_ok:
                print("  - ExecutionCoordinator may not be running")
                print("  - Check backend startup logs for execution coordinator")
            if not order_ok:
                print("  - OrderRouter may not be configured correctly")
                print("  - Check mode configuration and routing logic")
            print()
        
        return all_passed
    
    async def _cleanup(self, agents: List[StrategyAgent], queue: asyncio.Queue) -> None:
        """Cleanup resources."""
        for agent in agents:
            await agent.stop_heartbeat_loop()
        
        await self.event_stream.unsubscribe(queue)


async def main():
    """Main entry point."""
    print(f"\n{BOLD}Prerequisites:{RESET}")
    print("  - Backend must be running: python -m uvicorn web.main:app --reload")
    print("  - Wait for all startup messages before running this script")
    print()
    
    input("Press ENTER when backend is ready... ")
    
    verifier = PipelineVerifier()
    
    try:
        success = await verifier.run_verification()
        return 0 if success else 1
    
    except Exception as e:
        print(f"\n{RED}✗ Verification failed with error:{RESET}")
        print(f"  {e}")
        logger.error(f"Verification error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
