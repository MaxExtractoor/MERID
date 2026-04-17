"""
Continuous Simulation Miner - PoUS Block Advancement.

Runs continuously, advancing simulation blocks and
calculating useful work rewards.
"""

from __future__ import annotations

import threading
import asyncio
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
import time
import hashlib
import json

from core.streaming_bus import get_event_bus, EventChannel, StreamEvent
from utils.logger import get_logger

logger = get_logger("simulation.miner")


@dataclass
class SimulationBlock:
    """A PoUS simulation block."""
    block_number: int
    timestamp: float
    useful_work: float
    winning_strategy: str
    reward: float
    parent_hash: str
    block_hash: str = ""
    
    def __post_init__(self):
        if not self.block_hash:
            self.block_hash = self._calculate_hash()
    
    def _calculate_hash(self) -> str:
        """Calculate deterministic block hash."""
        data = f"{self.block_number}:{self.timestamp}:{self.useful_work}:{self.winning_strategy}:{self.parent_hash}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "block": self.block_number,
            "timestamp": self.timestamp,
            "useful_work": self.useful_work,
            "winning_strategy": self.winning_strategy,
            "reward": self.reward,
            "parent_hash": self.parent_hash,
            "block_hash": self.block_hash
        }


class ContinuousMiner:
    """
    Continuous simulation miner.
    
    Advances PoUS blocks based on:
    - Consensus decisions
    - Strategy performance
    - Useful work calculation
    """
    
    def __init__(self):
        self.bus = get_event_bus()
        self.running = False
        self._task: Optional[asyncio.Task] = None
        
        # Chain state
        self.current_block = 0
        self.chain: List[SimulationBlock] = []
        self.last_hash = "genesis"
        
        # Mining parameters
        self.block_interval = 30.0  # Seconds between blocks
        self.base_reward = 1.0
        
        # Strategy tracking
        self.strategies: Dict[str, Dict] = {}
        self.pending_decisions: List[Dict] = []
        
    async def start(self):
        """Start the continuous miner."""
        if self.running:
            return
        
        self.running = True
        
        # Subscribe to consensus decisions
        await self.bus.subscribe_named(
            subscriber_id="simulation-miner",
            channels=[EventChannel.CONSENSUS],
            queue_size=50
        )
        
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Continuous simulation miner started")
        
    async def stop(self):
        """Stop the miner."""
        self.running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        await self.bus.unsubscribe("simulation-miner")
        logger.info("Continuous simulation miner stopped")
        
    async def _run_loop(self):
        """Main mining loop."""
        logger.info("Simulation miner entering block production loop")
        last_block_time = time.time()
        
        while self.running:
            try:
                # Collect consensus decisions
                try:
                    event = await asyncio.wait_for(
                        self.bus.get_event("simulation-miner"),
                        timeout=1.0
                    )
                    if event and event.event_type == "consensus_decision":
                        self._record_decision(event)
                except asyncio.TimeoutError:
                    pass
                
                # Check if it's time to mine a block
                now = time.time()
                if now - last_block_time >= self.block_interval:
                    block = await self._mine_block()
                    if block:
                        await self._publish_block(block)
                    last_block_time = now
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Mining error: {e}")
                await asyncio.sleep(1)
                
    def _record_decision(self, event: StreamEvent):
        """Record a consensus decision for block inclusion."""
        data = event.data
        self.pending_decisions.append({
            "decision": data.get("decision"),
            "signal": data.get("signal"),
            "confidence": data.get("confidence"),
            "timestamp": event.timestamp
        })
        
        # Track strategy performance
        strategy = f"{data.get('signal', 'neutral')}_strategy"
        if strategy not in self.strategies:
            self.strategies[strategy] = {
                "decisions": 0,
                "total_confidence": 0.0,
                "useful_work": 0.0
            }
        
        self.strategies[strategy]["decisions"] += 1
        self.strategies[strategy]["total_confidence"] += data.get("confidence", 0)
        
    async def _mine_block(self) -> Optional[SimulationBlock]:
        """Mine a new simulation block."""
        self.current_block += 1
        
        # Calculate useful work from pending decisions
        useful_work = self._calculate_useful_work()
        
        # Determine winning strategy
        winning_strategy = self._determine_winner()
        
        # Calculate reward
        reward = self._calculate_reward(useful_work)
        
        # Create block
        block = SimulationBlock(
            block_number=self.current_block,
            timestamp=time.time(),
            useful_work=useful_work,
            winning_strategy=winning_strategy,
            reward=reward,
            parent_hash=self.last_hash
        )
        
        # Update chain state
        self.chain.append(block)
        self.last_hash = block.block_hash
        
        # Clear pending decisions
        self.pending_decisions.clear()
        
        logger.info(f"Mined block {block.block_number}: useful_work={useful_work:.2f}, winner={winning_strategy}, reward={reward:.2f}")
        
        return block
        
    def _calculate_useful_work(self) -> float:
        """Calculate useful work from decisions."""
        if not self.pending_decisions:
            return 0.0
        
        # Useful work = sum of confidence-weighted decisions
        total_work = sum(d.get("confidence", 0) * 100 for d in self.pending_decisions)
        return round(total_work, 2)
        
    def _determine_winner(self) -> str:
        """Determine winning strategy for this block."""
        if not self.strategies:
            return "baseline_v1"
        
        # Winner is strategy with highest useful work
        best_strategy = max(
            self.strategies.items(),
            key=lambda x: x[1]["useful_work"] + x[1]["total_confidence"]
        )
        return best_strategy[0]
        
    def _calculate_reward(self, useful_work: float) -> float:
        """Calculate block reward based on useful work."""
        # Reward scales with useful work
        if useful_work <= 0:
            return 0.0
        
        reward = self.base_reward * (1 + useful_work / 100)
        return round(reward, 2)
        
    async def _publish_block(self, block: SimulationBlock):
        """Publish mined block to event bus."""
        await self.bus.publish(StreamEvent(
            channel=EventChannel.SIMULATION,
            event_type="block_mined",
            source="simulation-miner",
            data=block.to_dict(),
            timestamp=block.timestamp
        ))


# Singleton
_miner: Optional[ContinuousMiner] = None
_miner_lock = threading.Lock()


def get_continuous_miner() -> ContinuousMiner:
    """Get the singleton continuous miner."""
    global _miner
    if _miner is None:
        with _miner_lock:
            if _miner is None:
                _miner = ContinuousMiner()
    return _miner
