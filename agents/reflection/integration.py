"""
ReflectionSystem Integration - Unified Interface

Provides a unified interface to all reflection layers with:
- Automatic layer coordination
- Event-driven updates
- Performance monitoring
- Error handling
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from pathlib import Path

from agents.reflection.core import ReflectionCore, Reflection, DecisionOutcome
from agents.reflection.validator import OutcomeValidator, ValidationResult, ValidationMethod
from agents.reflection.analytics import PerformanceAnalytics, AgentMetrics
from agents.reflection.learning import LearningEngine, LearningInsight
from agents.reflection.context import ContextProvider
from agents.reflection.persistence import PersistenceLayer
from agents.reflection.orchestrator import ReflectionOrchestrator
from utils.logger import get_logger

logger = get_logger("reflection.system")


class ReflectionSystem:
    """
    Unified reflection system integrating all layers.
    
    This is the main interface for the reflection system.
    All other components should use this class.
    """
    
    def __init__(
        self,
        storage_path: Optional[Path] = None,
        auto_persist: bool = True
    ):
        # Initialize layers
        self.core = ReflectionCore(max_reflections=50000)
        self.validator = OutcomeValidator()
        self.analytics = PerformanceAnalytics()
        self.learning = LearningEngine(min_evidence=5)
        self.context = ContextProvider(max_context_items=10)
        
        # Persistence
        storage = storage_path or Path("logs/agent_reflections_v2.json")
        self.persistence = PersistenceLayer(
            storage_path=storage,
            batch_size=100,
            flush_interval=30.0
        )
        
        self.auto_persist = auto_persist
        self.orchestrator = ReflectionOrchestrator(reflection_system=self)
        
        # Load existing reflections
        self._load_from_storage()
        
        # Start background tasks
        if auto_persist:
            self.persistence.start()
        
        logger.info("ReflectionSystem initialized with all layers")
    
    def _load_from_storage(self):
        """Load reflections from storage into core."""
        reflections = self.persistence.load_all()
        
        for reflection in reflections:
            # Restore to core (bypass persistence)
            self.core._reflections[reflection.reflection_id] = reflection
            
            # Update indexes
            if reflection.agent_id not in self.core._agent_index:
                self.core._agent_index[reflection.agent_id] = []
            self.core._agent_index[reflection.agent_id].append(reflection.reflection_id)
            
            if reflection.energy_id not in self.core._energy_index:
                self.core._energy_index[reflection.energy_id] = []
            self.core._energy_index[reflection.energy_id].append(reflection.reflection_id)
        
        logger.info("Loaded %d reflections from storage", len(reflections))
    
    def record_decision(
        self,
        agent_id: str,
        energy_id: str,
        decision: str,
        confidence: float,
        reasoning: str,
        market_context: Optional[Dict[str, Any]] = None,
        agent_state: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Record an agent decision.
        
        Args:
            agent_id: Agent identifier
            energy_id: Energy packet identifier
            decision: Decision (accept/reject/abstain)
            confidence: Confidence score (0.0-1.0)
            reasoning: Decision reasoning
            market_context: Optional market context
            agent_state: Optional agent state
        
        Returns:
            reflection_id: Unique reflection identifier
        """
        # Record in core
        reflection_id = self.core.record_decision(
            agent_id=agent_id,
            energy_id=energy_id,
            decision=decision,
            confidence=confidence,
            reasoning=reasoning,
            market_context=market_context,
            agent_state=agent_state
        )
        
        # Persist if enabled
        if self.auto_persist:
            reflection = self.core.get_reflection(reflection_id)
            if reflection:
                self.persistence.save_reflection(reflection)
        
        return reflection_id
    
    def validate_consensus_outcome(
        self,
        reflection_id: str,
        actual_consensus: str,
        consensus_confidence: float,
        vote_distribution: Dict[str, int]
    ) -> bool:
        """
        Validate a reflection against consensus outcome.
        
        Args:
            reflection_id: Reflection to validate
            actual_consensus: Actual consensus decision
            consensus_confidence: Consensus confidence
            vote_distribution: Vote distribution
        
        Returns:
            bool: True if updated successfully
        """
        reflection = self.core.get_reflection(reflection_id)
        if not reflection:
            logger.warning("Reflection not found: %s", reflection_id)
            return False
        
        # Validate
        result = self.validator.validate_consensus_outcome(
            prediction=reflection.decision,
            actual_consensus=actual_consensus,
            consensus_confidence=consensus_confidence,
            vote_distribution=vote_distribution
        )
        
        # Update outcome
        outcome = DecisionOutcome.VALIDATED if result.validated else DecisionOutcome.INVALIDATED
        
        # Generate learning insight
        learning = self._generate_learning_from_validation(reflection, result)
        
        # Update core
        success = self.core.update_outcome(
            reflection_id=reflection_id,
            outcome=outcome,
            reality_gap=result.reality_gap,
            validation_score=result.validation_score,
            learning_insight=learning
        )
        
        # Persist if enabled
        if success and self.auto_persist:
            updated_reflection = self.core.get_reflection(reflection_id)
            if updated_reflection:
                self.persistence.save_reflection(updated_reflection)
        
        return success
    
    def validate_market_outcome(
        self,
        reflection_id: str,
        actual_price_change: float,
        timeframe_hours: float = 24.0
    ) -> bool:
        """
        Validate a reflection against market outcome.
        
        Args:
            reflection_id: Reflection to validate
            actual_price_change: Actual price change percentage
            timeframe_hours: Timeframe for validation
        
        Returns:
            bool: True if updated successfully
        """
        reflection = self.core.get_reflection(reflection_id)
        if not reflection:
            return False
        
        # Map decision to direction
        direction_map = {
            "accept": "bullish",
            "reject": "bearish",
            "abstain": "neutral"
        }
        predicted_direction = direction_map.get(reflection.decision, "neutral")
        
        # Validate
        result = self.validator.validate_market_outcome(
            predicted_direction=predicted_direction,
            actual_price_change=actual_price_change,
            confidence=reflection.confidence,
            timeframe_hours=timeframe_hours
        )
        
        # Update outcome
        outcome = DecisionOutcome.VALIDATED if result.validated else DecisionOutcome.INVALIDATED
        learning = self._generate_learning_from_validation(reflection, result)
        
        success = self.core.update_outcome(
            reflection_id=reflection_id,
            outcome=outcome,
            reality_gap=result.reality_gap,
            validation_score=result.validation_score,
            learning_insight=learning
        )
        
        if success and self.auto_persist:
            updated_reflection = self.core.get_reflection(reflection_id)
            if updated_reflection:
                self.persistence.save_reflection(updated_reflection)
        
        return success
    
    def get_agent_context(
        self,
        agent_id: str,
        include_metrics: bool = True,
        include_insights: bool = True
    ) -> str:
        """
        Get reflection context for an agent.
        
        Args:
            agent_id: Agent identifier
            include_metrics: Include performance metrics
            include_insights: Include learning insights
        
        Returns:
            Formatted context string
        """
        # Get reflections
        reflections = self.core.get_agent_reflections(agent_id, limit=100)
        
        if not reflections:
            return f"No reflection history for {agent_id}"
        
        # Calculate metrics if requested
        metrics = None
        if include_metrics:
            metrics = self.analytics.calculate_agent_metrics(agent_id, reflections)
        
        # Generate insights if requested
        insights = None
        if include_insights:
            insights = self.learning.generate_insights(agent_id, reflections)
        
        # Generate context
        return self.context.get_agent_context(
            agent_id=agent_id,
            reflections=reflections,
            metrics=metrics,
            insights=insights,
            include_recent=True,
            include_patterns=True,
            include_metrics=include_metrics
        )
    
    def get_agent_metrics(self, agent_id: str) -> Optional[AgentMetrics]:
        """Get performance metrics for an agent."""
        reflections = self.core.get_agent_reflections(agent_id)
        if not reflections:
            return None
        
        return self.analytics.calculate_agent_metrics(agent_id, reflections)
    
    def get_agent_insights(self, agent_id: str) -> List[LearningInsight]:
        """Get learning insights for an agent."""
        reflections = self.core.get_agent_reflections(agent_id)
        if not reflections:
            return []
        
        return self.learning.generate_insights(agent_id, reflections)
    
    def get_all_agent_metrics(self) -> Dict[str, AgentMetrics]:
        """Get metrics for all agents."""
        metrics = {}
        
        for agent_id in self.core._agent_index.keys():
            agent_metrics = self.get_agent_metrics(agent_id)
            if agent_metrics:
                metrics[agent_id] = agent_metrics
        
        return metrics
    
    def get_system_stats(self) -> Dict[str, Any]:
        """Get comprehensive system statistics."""
        return {
            "core": self.core.get_stats(),
            "validator": self.validator.get_stats(),
            "analytics": self.analytics.get_stats(),
            "learning": self.learning.get_stats(),
            "context": self.context.get_stats(),
            "persistence": self.persistence.get_stats()
        }
    
    def _generate_learning_from_validation(
        self,
        reflection: Reflection,
        result: ValidationResult
    ) -> str:
        """Generate learning insight from validation result."""
        if result.validated:
            if result.reality_gap < 0.2:
                return f"Excellent prediction (gap: {result.reality_gap:.3f}) - maintain this reasoning approach"
            else:
                return f"Correct but imprecise (gap: {result.reality_gap:.3f}) - refine confidence calibration"
        else:
            if reflection.confidence > 0.7:
                return f"High confidence failure (gap: {result.reality_gap:.3f}) - review overconfidence patterns"
            else:
                return f"Prediction invalidated (gap: {result.reality_gap:.3f}) - analyze reasoning errors"
    
    def shutdown(self):
        """Shutdown the reflection system."""
        logger.info("Shutting down reflection system...")
        
        # Stop persistence
        if self.auto_persist:
            self.persistence.stop()
        
        logger.info("Reflection system shutdown complete")


# Global singleton
_reflection_system: Optional[ReflectionSystem] = None


def get_reflection_system() -> ReflectionSystem:
    """Get the global reflection system instance."""
    global _reflection_system
    if _reflection_system is None:
        _reflection_system = ReflectionSystem()
    return _reflection_system
