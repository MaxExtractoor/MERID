"""
MERID Reflection System - Multi-Layer Architecture

Layers:
1. ReflectionCore - Decision recording and storage
2. OutcomeValidator - Reality gap calculation and validation
3. PerformanceAnalytics - Agent performance metrics
4. LearningEngine - Pattern recognition and insights
5. ContextProvider - Reflection context for agents
6. PersistenceLayer - Optimized storage with caching

Each layer has:
- Individual logging
- Validation
- Error handling
- Performance metrics
- Unit tests
"""

from agents.reflection.core import ReflectionCore, Reflection
from agents.reflection.validator import OutcomeValidator, ValidationResult
from agents.reflection.analytics import PerformanceAnalytics, AgentMetrics
from agents.reflection.learning import LearningEngine, LearningInsight
from agents.reflection.context import ContextProvider
from agents.reflection.persistence import PersistenceLayer
from agents.reflection.orchestrator import ReflectionOrchestrator

__all__ = [
    "ReflectionCore",
    "Reflection",
    "OutcomeValidator",
    "ValidationResult",
    "PerformanceAnalytics",
    "AgentMetrics",
    "LearningEngine",
    "LearningInsight",
    "ContextProvider",
    "PersistenceLayer",
    "ReflectionOrchestrator",
    "get_reflection_system",
]


# Singleton reflection system
_reflection_system = None


def get_reflection_system():
    """Get the global reflection system instance."""
    global _reflection_system
    if _reflection_system is None:
        _reflection_system = ReflectionCore()
    return _reflection_system
