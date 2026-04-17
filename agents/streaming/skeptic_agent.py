"""
Skeptic Agent - Streaming implementation.

Adversarial agent that challenges other agents' conclusions.
Can force re-round if contradictions detected.
"""

from __future__ import annotations

from typing import Dict, Any, Optional, List
from agents.streaming_agent import StreamingAgent
from core.streaming_bus import EventChannel, StreamEvent


class SkepticAgent(StreamingAgent):
    """
    Adversarial skeptic that challenges consensus.
    
    Monitors agent outputs for:
    - Contradictions between agents
    - Overconfidence
    - Missing risk factors
    - Groupthink patterns
    """
    
    def __init__(self, agent_id: str = "skeptic-agent-01"):
        super().__init__(
            agent_id=agent_id,
            channels=[EventChannel.AGENT_OUTPUT],
            model="merid-strategist:latest"
        )
        
        # Track recent agent outputs for contradiction detection
        self.recent_outputs: List[Dict] = []
        self.max_outputs = 20
        
        # Thresholds
        self.overconfidence_threshold = 0.90
        self.groupthink_threshold = 0.85  # If all agents agree above this
        
    async def analyze(self, event: StreamEvent) -> Optional[Dict[str, Any]]:
        """
        Analyze agent outputs for contradictions and issues.
        
        Can emit:
        - contradiction_flag: Agents disagree significantly
        - overconfidence_warning: Agent too confident
        - groupthink_alert: All agents suspiciously aligned
        - force_reround: Request consensus re-evaluation
        """
        if event.channel != EventChannel.AGENT_OUTPUT:
            return None
        
        data = event.data
        
        # Store output for comparison
        self.recent_outputs.append({
            "source": event.source,
            "type": event.event_type,
            "data": data,
            "timestamp": event.timestamp
        })
        
        # Keep bounded
        if len(self.recent_outputs) > self.max_outputs:
            self.recent_outputs.pop(0)
        
        # Check for issues
        issues = []
        
        # Check overconfidence
        confidence = data.get("confidence", 0)
        if confidence > self.overconfidence_threshold:
            issues.append({
                "issue": "overconfidence",
                "agent": event.source,
                "confidence": confidence,
                "threshold": self.overconfidence_threshold
            })
        
        # Check for contradictions with recent outputs
        contradiction = self._check_contradictions(event.source, data)
        if contradiction:
            issues.append(contradiction)
        
        # Check for groupthink
        groupthink = self._check_groupthink()
        if groupthink:
            issues.append(groupthink)
        
        # Emit if issues found
        if issues:
            severity = "high" if any(i.get("issue") == "contradiction" for i in issues) else "medium"
            force_reround = severity == "high"
            
            return {
                "type": "skeptic_challenge",
                "issues": issues,
                "severity": severity,
                "force_reround": force_reround,
                "reasoning": f"Skeptic detected {len(issues)} issue(s) in agent outputs",
                "recommendation": "RE_EVALUATE" if force_reround else "REVIEW"
            }
        
        return None
    
    def _check_contradictions(self, current_source: str, current_data: Dict) -> Optional[Dict]:
        """Check if current output contradicts recent outputs."""
        current_signal = current_data.get("signal", "").lower()
        
        if not current_signal:
            return None
        
        # Look for opposite signals from other agents
        for output in self.recent_outputs[-10:]:
            if output["source"] == current_source:
                continue
            
            other_signal = output["data"].get("signal", "").lower()
            
            # Check for direct contradiction
            if (current_signal == "bullish" and other_signal == "bearish") or \
               (current_signal == "bearish" and other_signal == "bullish"):
                return {
                    "issue": "contradiction",
                    "agent_a": current_source,
                    "signal_a": current_signal,
                    "agent_b": output["source"],
                    "signal_b": other_signal,
                    "reasoning": f"{current_source} says {current_signal} but {output['source']} says {other_signal}"
                }
        
        return None
    
    def _check_groupthink(self) -> Optional[Dict]:
        """Check if all agents are suspiciously aligned."""
        if len(self.recent_outputs) < 3:
            return None
        
        # Get recent signals
        recent_signals = []
        for output in self.recent_outputs[-5:]:
            signal = output["data"].get("signal", "")
            if signal:
                recent_signals.append(signal.lower())
        
        if len(recent_signals) < 3:
            return None
        
        # Check if all same
        if len(set(recent_signals)) == 1:
            return {
                "issue": "groupthink",
                "signal": recent_signals[0],
                "agent_count": len(recent_signals),
                "reasoning": f"All {len(recent_signals)} recent agents agree on {recent_signals[0]} - possible groupthink"
            }
        
        return None
