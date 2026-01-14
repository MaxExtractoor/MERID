"""
ContextProvider - Layer 5: Reflection Context for Agent Decision-Making

Responsibilities:
- Provide relevant reflection context to agents
- Format learning insights for agent consumption
- Filter and prioritize context based on relevance
- Track context usage and effectiveness
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from collections import defaultdict

from agents.reflection.core import Reflection, DecisionOutcome
from agents.reflection.analytics import AgentMetrics
from agents.reflection.learning import LearningInsight
from utils.logger import get_logger

logger = get_logger("reflection.context")


class ContextProvider:
    """
    Provides reflection context to agents for improved decision-making.
    
    Features:
    - Relevant reflection history
    - Learning insights
    - Performance metrics
    - Success/failure patterns
    - Formatted for agent consumption
    """
    
    def __init__(self, max_context_items: int = 10):
        self.max_context_items = max_context_items
        self._context_requests = 0
        self._start_time = time.time()
        
        logger.info("ContextProvider initialized (max_items=%d)", max_context_items)
    
    def get_agent_context(
        self,
        agent_id: str,
        reflections: List[Reflection],
        metrics: Optional[AgentMetrics] = None,
        insights: Optional[List[LearningInsight]] = None,
        include_recent: bool = True,
        include_patterns: bool = True,
        include_metrics: bool = True
    ) -> str:
        """
        Get formatted reflection context for an agent.
        
        Args:
            agent_id: Agent identifier
            reflections: Agent's reflections
            metrics: Agent performance metrics
            insights: Learning insights
            include_recent: Include recent decisions
            include_patterns: Include pattern insights
            include_metrics: Include performance metrics
        
        Returns:
            Formatted context string for agent prompt
        """
        start = time.time()
        
        context_parts = []
        
        # Header
        context_parts.append(f"=== Reflection Context for {agent_id} ===")
        
        # Performance metrics
        if include_metrics and metrics:
            context_parts.append(self._format_metrics(metrics))
        
        # Recent decisions
        if include_recent and reflections:
            context_parts.append(self._format_recent_decisions(reflections))
        
        # Learning insights
        if include_patterns and insights:
            context_parts.append(self._format_insights(insights))
        
        # Success patterns
        if reflections:
            context_parts.append(self._format_success_patterns(reflections))
        
        # Failure warnings
        if reflections:
            context_parts.append(self._format_failure_warnings(reflections))
        
        context = "\n\n".join(filter(None, context_parts))
        
        self._context_requests += 1
        duration_ms = (time.time() - start) * 1000
        
        logger.debug(
            "Generated context for %s: %d chars (%.2fms)",
            agent_id, len(context), duration_ms
        )
        
        return context
    
    def _format_metrics(self, metrics: AgentMetrics) -> str:
        """Format performance metrics."""
        lines = [
            "## Performance Metrics",
            f"- Accuracy: {metrics.accuracy*100:.1f}% ({metrics.validated_count}/{metrics.validated_count + metrics.invalidated_count} correct)",
            f"- Confidence: {metrics.avg_confidence:.2f} (calibration: {metrics.confidence_calibration:.2f})",
            f"- Reality Gap: {metrics.avg_reality_gap:.3f} (lower is better)",
        ]
        
        if metrics.accuracy_trend != "stable":
            lines.append(f"- Trend: {metrics.accuracy_trend.upper()}")
        
        if metrics.overconfidence_rate > 0.3:
            lines.append(f"- ⚠️ Overconfidence detected: {metrics.overconfidence_rate*100:.1f}%")
        
        return "\n".join(lines)
    
    def _format_recent_decisions(self, reflections: List[Reflection]) -> str:
        """Format recent decisions."""
        recent = sorted(reflections, key=lambda r: r.decision_timestamp, reverse=True)[:5]
        
        if not recent:
            return ""
        
        lines = ["## Recent Decisions"]
        
        for r in recent:
            outcome_emoji = {
                DecisionOutcome.VALIDATED: "✓",
                DecisionOutcome.INVALIDATED: "✗",
                DecisionOutcome.PENDING: "⏳"
            }.get(r.outcome, "?")
            
            gap_str = f" (gap: {r.reality_gap:.2f})" if r.reality_gap is not None else ""
            
            lines.append(
                f"- {outcome_emoji} {r.decision.upper()} @ {r.confidence:.2f} confidence{gap_str}"
            )
        
        return "\n".join(lines)
    
    def _format_insights(self, insights: List[LearningInsight]) -> str:
        """Format learning insights."""
        if not insights:
            return ""
        
        # Prioritize actionable insights
        actionable = [i for i in insights if i.actionable]
        top_insights = sorted(actionable, key=lambda i: i.confidence, reverse=True)[:3]
        
        if not top_insights:
            return ""
        
        lines = ["## Key Learning Insights"]
        
        for insight in top_insights:
            lines.append(f"- **{insight.title}**")
            if insight.recommendations:
                lines.append(f"  → {insight.recommendations[0]}")
        
        return "\n".join(lines)
    
    def _format_success_patterns(self, reflections: List[Reflection]) -> str:
        """Format success patterns."""
        successful = [
            r for r in reflections
            if r.outcome == DecisionOutcome.VALIDATED and r.reality_gap is not None
        ]
        
        if len(successful) < 3:
            return ""
        
        # Find best predictions
        best = sorted(successful, key=lambda r: r.reality_gap)[:3]
        
        lines = ["## Success Patterns"]
        
        for r in best:
            lines.append(
                f"- {r.decision.upper()} @ {r.confidence:.2f} → gap: {r.reality_gap:.3f}"
            )
        
        # Common factors
        decision_counts = defaultdict(int)
        for r in successful:
            decision_counts[r.decision] += 1
        
        if decision_counts:
            best_decision = max(decision_counts.items(), key=lambda x: x[1])
            lines.append(f"- Best performing decision type: {best_decision[0].upper()} ({best_decision[1]} successes)")
        
        return "\n".join(lines)
    
    def _format_failure_warnings(self, reflections: List[Reflection]) -> str:
        """Format failure warnings."""
        failed = [
            r for r in reflections
            if r.outcome == DecisionOutcome.INVALIDATED
        ]
        
        if len(failed) < 3:
            return ""
        
        lines = ["## Failure Warnings"]
        
        # High confidence failures
        high_conf_failures = [r for r in failed if r.confidence > 0.7]
        if len(high_conf_failures) >= 2:
            lines.append(
                f"- ⚠️ {len(high_conf_failures)} high-confidence failures detected"
            )
            lines.append("  → Reduce confidence in uncertain contexts")
        
        # Decision type failures
        decision_counts = defaultdict(int)
        for r in failed:
            decision_counts[r.decision] += 1
        
        if decision_counts:
            worst_decision = max(decision_counts.items(), key=lambda x: x[1])
            if worst_decision[1] >= 3:
                lines.append(
                    f"- ⚠️ {worst_decision[1]} failures on {worst_decision[0].upper()} decisions"
                )
                lines.append(f"  → Review reasoning for {worst_decision[0]} votes")
        
        # High reality gap
        high_gap = [r for r in failed if r.reality_gap and r.reality_gap > 0.7]
        if len(high_gap) >= 2:
            lines.append(
                f"- ⚠️ {len(high_gap)} predictions with severe reality gap (>0.7)"
            )
            lines.append("  → Predictions far from actual outcomes")
        
        return "\n".join(lines) if len(lines) > 1 else ""
    
    def get_context_for_energy(
        self,
        agent_id: str,
        energy_id: str,
        all_reflections: List[Reflection],
        metrics: Optional[AgentMetrics] = None
    ) -> str:
        """
        Get context specific to an energy packet.
        
        Useful for showing how this agent has performed on similar energies.
        
        Args:
            agent_id: Agent identifier
            energy_id: Energy packet identifier
            all_reflections: All agent reflections
            metrics: Agent metrics
        
        Returns:
            Formatted context string
        """
        # Filter to this agent's reflections
        agent_reflections = [r for r in all_reflections if r.agent_id == agent_id]
        
        # Get similar reflections (same energy or similar context)
        similar = [r for r in agent_reflections if r.energy_id == energy_id]
        
        if not similar:
            # Fall back to general context
            return self.get_agent_context(
                agent_id, agent_reflections, metrics,
                include_recent=True, include_patterns=True, include_metrics=True
            )
        
        context_parts = [
            f"=== Context for Energy {energy_id[:8]} ===",
            f"Previous decisions on this energy: {len(similar)}"
        ]
        
        for r in similar:
            outcome_str = r.outcome.value
            gap_str = f" (gap: {r.reality_gap:.2f})" if r.reality_gap else ""
            context_parts.append(
                f"- {r.decision.upper()} @ {r.confidence:.2f} → {outcome_str}{gap_str}"
            )
        
        return "\n".join(context_parts)
    
    def get_comparative_context(
        self,
        agent_id: str,
        all_metrics: Dict[str, AgentMetrics]
    ) -> str:
        """
        Get comparative context showing how agent ranks vs others.
        
        Args:
            agent_id: Agent identifier
            all_metrics: Metrics for all agents
        
        Returns:
            Formatted comparative context
        """
        if agent_id not in all_metrics:
            return ""
        
        agent_metrics = all_metrics[agent_id]
        
        # Rank by accuracy
        ranked = sorted(
            all_metrics.items(),
            key=lambda x: x[1].accuracy,
            reverse=True
        )
        
        rank = next((i+1 for i, (aid, _) in enumerate(ranked) if aid == agent_id), 0)
        
        lines = [
            "## Comparative Performance",
            f"- Rank: {rank}/{len(all_metrics)} agents",
            f"- Your accuracy: {agent_metrics.accuracy*100:.1f}%",
        ]
        
        if rank == 1:
            lines.append("- 🏆 Top performing agent!")
        elif rank <= len(all_metrics) * 0.25:
            lines.append("- ⭐ Above average performance")
        elif rank >= len(all_metrics) * 0.75:
            lines.append("- ⚠️ Below average - improvement needed")
        
        # Show best agent for reference
        if rank > 1:
            best_agent_id, best_metrics = ranked[0]
            lines.append(
                f"- Top agent ({best_agent_id}): {best_metrics.accuracy*100:.1f}% accuracy"
            )
        
        return "\n".join(lines)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get context provider statistics."""
        uptime = time.time() - self._start_time
        
        return {
            "max_context_items": self.max_context_items,
            "total_requests": self._context_requests,
            "performance": {
                "uptime_seconds": round(uptime, 2),
                "requests_per_second": round(self._context_requests / uptime, 2) if uptime > 0 else 0
            }
        }
