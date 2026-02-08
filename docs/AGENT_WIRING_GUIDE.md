# Agent Wiring Guide - SwarmAgentMixin Integration

**Step-by-step guide for integrating agents with the swarm system.**

---

## Overview

This guide shows how to wire any strategy agent to emit `StrategyOpinion` events and participate in swarm consensus. The POC agent (`agents/strategy_agent.py`) is already wired and serves as the reference implementation.

---

## Prerequisites

- Agent inherits from `BaseAgent`
- Agent has a `process()` method that returns vote decisions
- Python 3.9+

---

## Step 1: Import SwarmAgentMixin

Add the mixin import to your agent file:

```python
# At top of file
from agents.swarm_mixin import SwarmAgentMixin
from schemas.swarm_events import TradingMode
```

---

## Step 2: Add Mixin Inheritance

Update your agent class to inherit from both `SwarmAgentMixin` and `BaseAgent`:

```python
# Before:
class MyStrategyAgent(BaseAgent):
    def __init__(self, agent_id: str = "my-agent"):
        super().__init__(agent_id=agent_id)

# After:
class MyStrategyAgent(SwarmAgentMixin, BaseAgent):
    def __init__(self, agent_id: str = "my-agent"):
        super().__init__(agent_id=agent_id)
        # Start heartbeat loop
        asyncio.create_task(self.start_heartbeat_loop())
```

**Key Points**:
- `SwarmAgentMixin` must come FIRST in inheritance (Python MRO)
- Start heartbeat loop in `__init__` after `super().__init__()`
- Heartbeat runs in background, emitting health status every 30s

---

## Step 3: Set Trading Mode

In your agent's initialization or before processing:

```python
async def initialize(self):
    """Initialize agent for swarm operation."""
    # Set mode from environment or configuration
    mode = TradingMode.SIMULATION  # or PAPER, LIVE
    self.set_trading_mode(mode)
```

---

## Step 4: Emit Opinions in process()

Update your `process()` method to emit opinions when making decisions:

### **Pattern A: After Vote Decision**

```python
async def process(self, energy: Dict[str, Any], phase: str = "reasoning") -> Dict[str, Any]:
    """Process signal and emit opinion."""
    
    # Your existing logic
    result = await self._analyze_and_vote(energy)
    
    # Extract decision details
    vote = result.get("vote", "abstain")
    confidence = result.get("confidence", 0.0)
    reasoning = result.get("reasoning", "")
    
    # Emit opinion if not abstaining
    if vote != "abstain":
        # Map vote to direction
        direction_map = {
            "approve": OpinionDirection.LONG,
            "reject": OpinionDirection.SHORT,
        }
        direction = direction_map.get(vote, OpinionDirection.FLAT)
        
        # Emit opinion
        await self.emit_strategy_opinion(
            symbol=energy.get("symbol", "BTC/USDT"),
            direction=direction,
            confidence=confidence,
            rationale_summary=reasoning,
            price_at_opinion=energy.get("price", 0.0),
            signal_strength=confidence,  # Or calculate separately
        )
    
    return result
```

### **Pattern B: With Error Handling**

```python
async def process(self, energy: Dict[str, Any], phase: str = "reasoning") -> Dict[str, Any]:
    """Process signal with error tracking."""
    start_time = time.time()
    
    try:
        # Your logic
        result = await self._analyze(energy)
        
        # Emit opinion
        if result["vote"] != "abstain":
            await self.emit_strategy_opinion(
                symbol=energy["symbol"],
                direction=self._map_vote_to_direction(result["vote"]),
                confidence=result["confidence"],
                rationale_summary=result["reasoning"],
                price_at_opinion=energy["price"],
                signal_strength=result["signal_strength"],
            )
        
        # Track success
        latency_ms = (time.time() - start_time) * 1000
        self.record_processing_success(latency_ms)
        
        return result
    
    except Exception as e:
        # Track error
        self.record_processing_error(str(e))
        logger.error(f"Processing error: {e}", exc_info=True)
        raise
```

---

## Step 5: Add Cleanup

Ensure heartbeat stops when agent is destroyed:

```python
async def shutdown(self):
    """Clean shutdown."""
    await self.stop_heartbeat_loop()
    # Your other cleanup
```

---

## Complete Example

Here's a complete minimal agent with swarm integration:

```python
"""
Example Strategy Agent with Swarm Integration
"""

import asyncio
import time
from typing import Dict, Any

from agents.base_agent import BaseAgent
from agents.swarm_mixin import SwarmAgentMixin
from schemas.swarm_events import TradingMode, OpinionDirection
from utils.logger import get_logger

logger = get_logger("agents.example")


class ExampleStrategyAgent(SwarmAgentMixin, BaseAgent):
    """Example agent with full swarm integration."""
    
    def __init__(self, agent_id: str = "example-agent-01"):
        super().__init__(agent_id=agent_id)
        
        # Set trading mode
        self.set_trading_mode(TradingMode.SIMULATION)
        
        # Start heartbeat
        asyncio.create_task(self.start_heartbeat_loop())
        
        logger.info(f"ExampleStrategyAgent initialized: {agent_id}")
    
    async def process(self, energy: Dict[str, Any], phase: str = "reasoning") -> Dict[str, Any]:
        """
        Process signal and emit opinion.
        
        Args:
            energy: Signal data with symbol, price, payload
            phase: Processing phase
        
        Returns:
            Vote result with decision and confidence
        """
        start_time = time.time()
        
        try:
            # Extract signal data
            symbol = energy.get("symbol", "BTC/USDT")
            price = energy.get("price", 0.0)
            signal_data = energy.get("payload", {})
            
            # Your analysis logic here
            vote, confidence, reasoning = await self._analyze_signal(signal_data)
            
            # Emit opinion if actionable
            if vote != "abstain":
                direction = self._map_vote_to_direction(vote)
                
                await self.emit_strategy_opinion(
                    symbol=symbol,
                    direction=direction,
                    confidence=confidence,
                    rationale_summary=reasoning,
                    price_at_opinion=price,
                    signal_strength=confidence,  # Could be separate metric
                )
            
            # Track success
            latency_ms = (time.time() - start_time) * 1000
            self.record_processing_success(latency_ms)
            
            return {
                "vote": vote,
                "confidence": confidence,
                "reasoning": reasoning,
                "agent_id": self.agent_id,
            }
        
        except Exception as e:
            self.record_processing_error(str(e))
            logger.error(f"Processing error: {e}", exc_info=True)
            raise
    
    async def _analyze_signal(self, signal_data: Dict[str, Any]) -> tuple[str, float, str]:
        """
        Analyze signal and determine vote.
        
        Returns:
            (vote, confidence, reasoning)
        """
        # Your analysis logic
        # This is a placeholder - implement your actual strategy
        
        sentiment = signal_data.get("sentiment", 0.0)
        
        if sentiment > 0.5:
            return "approve", 0.75, "Strong bullish sentiment detected"
        elif sentiment < -0.5:
            return "reject", 0.70, "Strong bearish sentiment detected"
        else:
            return "abstain", 0.3, "Neutral sentiment, no clear signal"
    
    def _map_vote_to_direction(self, vote: str) -> OpinionDirection:
        """Map vote string to OpinionDirection enum."""
        mapping = {
            "approve": OpinionDirection.LONG,
            "reject": OpinionDirection.SHORT,
            "abstain": OpinionDirection.FLAT,
        }
        return mapping.get(vote, OpinionDirection.FLAT)
    
    async def shutdown(self):
        """Clean shutdown."""
        await self.stop_heartbeat_loop()
        logger.info(f"ExampleStrategyAgent shutdown: {self.agent_id}")


# Singleton getter
_example_agent = None

def get_example_agent() -> ExampleStrategyAgent:
    """Get or create singleton instance."""
    global _example_agent
    if _example_agent is None:
        _example_agent = ExampleStrategyAgent()
    return _example_agent
```

---

## Testing Your Agent

### **Unit Test**

```python
# tests/test_example_agent.py
import asyncio
import pytest
from agents.example_agent import ExampleStrategyAgent
from schemas.swarm_events import TradingMode

@pytest.mark.asyncio
async def test_agent_emits_opinion():
    """Test that agent emits opinion on signal."""
    agent = ExampleStrategyAgent("test-agent")
    
    energy = {
        "energy_id": "test-001",
        "symbol": "BTC/USDT",
        "price": 50000.0,
        "payload": {"sentiment": 0.8}  # Bullish
    }
    
    result = await agent.process(energy)
    
    assert result["vote"] == "approve"
    assert result["confidence"] > 0.5
    
    await agent.shutdown()
```

### **Integration Test**

```python
# Test with consensus
async def test_agent_with_consensus():
    """Test agent integrates with consensus."""
    from consensus.consensus_coordinator import get_consensus_coordinator
    
    # Start consensus
    consensus = get_consensus_coordinator()
    await consensus.start_opinion_subscriber()
    
    # Create agent
    agent = ExampleStrategyAgent("integration-test")
    
    # Process signal
    energy = {
        "symbol": "BTC/USDT",
        "price": 50000.0,
        "payload": {"sentiment": 0.8}
    }
    
    await agent.process(energy)
    
    # Wait for consensus processing
    await asyncio.sleep(2)
    
    # Cleanup
    await agent.shutdown()
    await consensus.stop_opinion_subscriber()
```

---

## Common Patterns

### **Multiple Opinions Per Process**

If your agent wants to emit multiple opinions (e.g., for different symbols):

```python
async def process(self, energy: Dict[str, Any]) -> Dict[str, Any]:
    """Process multi-symbol signal."""
    
    symbols = energy.get("symbols", ["BTC/USDT"])
    
    for symbol in symbols:
        # Analyze each symbol
        direction, confidence = await self._analyze_symbol(symbol)
        
        if confidence > 0.5:
            await self.emit_strategy_opinion(
                symbol=symbol,
                direction=direction,
                confidence=confidence,
                rationale_summary=f"Analysis for {symbol}",
                price_at_opinion=energy.get(f"{symbol}_price", 0.0),
                signal_strength=confidence,
            )
    
    return {"processed": len(symbols)}
```

### **Conditional Opinions**

Only emit opinions when confidence exceeds threshold:

```python
MIN_CONFIDENCE_FOR_OPINION = 0.6

async def process(self, energy: Dict[str, Any]) -> Dict[str, Any]:
    """Only emit high-confidence opinions."""
    
    result = await self._analyze(energy)
    
    # Only emit if confident enough
    if result["confidence"] >= MIN_CONFIDENCE_FOR_OPINION:
        await self.emit_strategy_opinion(...)
    
    return result
```

### **State Version Tracking**

Include state version for staleness detection:

```python
async def emit_strategy_opinion(...):
    """Emit opinion with state version."""
    
    # Get current state version (implement your own tracking)
    state_version = self._get_current_state_version()
    
    await self.emit_strategy_opinion(
        symbol=symbol,
        direction=direction,
        confidence=confidence,
        rationale_summary=reasoning,
        price_at_opinion=price,
        signal_strength=signal_strength,
        state_version=state_version,  # For staleness detection
    )
```

---

## Verification Checklist

After wiring your agent, verify:

- [ ] Agent inherits from `SwarmAgentMixin` and `BaseAgent` (in that order)
- [ ] Heartbeat loop starts in `__init__`
- [ ] Trading mode is set
- [ ] Opinions emitted on non-abstain votes
- [ ] Opinions include all required fields (symbol, direction, confidence)
- [ ] Error handling tracks failures
- [ ] Shutdown stops heartbeat loop
- [ ] Unit tests pass
- [ ] Integration test with consensus passes
- [ ] Agent appears in swarm telemetry
- [ ] Agent heartbeats visible in logs

---

## Troubleshooting

### **Opinions Not Appearing**

Check:
1. Is heartbeat loop running? Look for heartbeat logs
2. Is `emit_strategy_opinion()` being called? Add debug logging
3. Is EventStream operational? Check `observability/event_stream.py`
4. Is ConsensusCoordinator subscribed? Check backend startup logs

### **Heartbeat Not Emitting**

Check:
1. Did you call `start_heartbeat_loop()` in `__init__`?
2. Is asyncio event loop running?
3. Check for exceptions in agent logs

### **Consensus Not Forming**

Check:
1. Are ≥3 agents emitting opinions?
2. Is ConsensusCoordinator opinion subscriber running?
3. Check consensus logs for opinion receipt

---

## Next Steps

After wiring your agent:

1. **Test Locally**: `python -c "import asyncio; from agents.my_agent import MyAgent; asyncio.run(MyAgent().process({...}))"`
2. **Run E2E Test**: `python tests/test_swarm_e2e.py`
3. **Run Rehearsal**: `python scripts/paper_rehearsal.py --mode simulation`
4. **Monitor Telemetry**: `curl http://localhost:8000/api/v1/swarm/stats`
5. **Check UI**: View agent in SwarmActivityPanel

---

## Reference Implementation

See `agents/strategy_agent.py` for the complete POC implementation.

---

**Questions?** Check `TESTING_GUIDE.md` for testing procedures or `TROUBLESHOOTING.md` for common issues.
