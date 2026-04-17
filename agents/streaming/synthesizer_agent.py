"""
Synthesizer Agent - Streaming implementation.

Cross-agent analysis - merges outputs from multiple agents
into unified proposals for consensus.
"""

from __future__ import annotations

from typing import Dict, Any, Optional, List
from agents.streaming_agent import StreamingAgent
from core.streaming_bus import EventChannel, StreamEvent


class SynthesizerAgent(StreamingAgent):
    """
    Cross-agent synthesizer.
    
    Collects outputs from multiple agents and produces
    unified proposals for the consensus engine.
    """
    
    def __init__(self, agent_id: str = "synthesizer-agent-01"):
        super().__init__(
            agent_id=agent_id,
            channels=[EventChannel.AGENT_OUTPUT],
            model="merid-strategist:latest"
        )
        
        # Collect agent outputs
        self.agent_outputs: Dict[str, Dict] = {}
        self.synthesis_threshold = 3  # Need at least 3 agent outputs to synthesize
        
    async def analyze(self, event: StreamEvent) -> Optional[Dict[str, Any]]:
        """
        Collect agent outputs and synthesize when threshold reached.
        
        Emits:
        - synthesis_proposal: Unified proposal from multiple agents
        """
        if event.channel != EventChannel.AGENT_OUTPUT:
            return None
        
        # Skip our own outputs and skeptic challenges
        if event.source == self.agent_id:
            return None
        if event.event_type == "skeptic_challenge":
            return None
        
        # Store agent output
        self.agent_outputs[event.source] = {
            "type": event.event_type,
            "data": event.data,
            "timestamp": event.timestamp
        }
        
        # Check if we have enough outputs to synthesize
        if len(self.agent_outputs) >= self.synthesis_threshold:
            synthesis = self._synthesize()
            
            # Clear outputs after synthesis
            self.agent_outputs.clear()
            
            return synthesis
        
        return None
    
    def _synthesize(self) -> Dict[str, Any]:
        """Synthesize outputs from multiple agents."""
        # Collect signals and confidences
        signals = []
        confidences = []
        reasonings = []
        
        for source, output in self.agent_outputs.items():
            data = output["data"]
            
            signal = data.get("signal", data.get("direction", ""))
            if signal:
                signals.append(signal.lower())
            
            confidence = data.get("confidence", 0.5)
            confidences.append(confidence)
            
            reasoning = data.get("reasoning", "")
            if reasoning:
                reasonings.append(f"{source}: {reasoning}")
        
        # Calculate consensus signal
        bullish_count = signals.count("bullish")
        bearish_count = signals.count("bearish")
        
        if bullish_count > bearish_count:
            consensus_signal = "bullish"
            signal_strength = bullish_count / len(signals) if signals else 0
        elif bearish_count > bullish_count:
            consensus_signal = "bearish"
            signal_strength = bearish_count / len(signals) if signals else 0
        else:
            consensus_signal = "neutral"
            signal_strength = 0.5
        
        # Calculate average confidence
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.5
        
        # Adjust confidence by signal strength
        final_confidence = avg_confidence * signal_strength
        
        return {
            "type": "synthesis_proposal",
            "signal": consensus_signal,
            "confidence": final_confidence,
            "signal_strength": signal_strength,
            "agent_count": len(self.agent_outputs),
            "bullish_votes": bullish_count,
            "bearish_votes": bearish_count,
            "avg_agent_confidence": avg_confidence,
            "reasoning": f"Synthesized {len(self.agent_outputs)} agents: {bullish_count} bullish, {bearish_count} bearish",
            "agent_reasonings": reasonings
        }
