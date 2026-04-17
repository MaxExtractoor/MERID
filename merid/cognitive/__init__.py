"""Cognitive Layer — structured hypotheses, mental models, and reality debugging.

Provides:
  - CognitiveSnapshot: point-in-time set of hypotheses about a market/domain
  - Hypothesis: tagged belief with confidence and evidence links
  - EvidenceLink: reference to supporting/contradicting data
  - RegimeTag: structured label for macro/micro narrative classification
  - CognitiveStore: SQLite persistence + history tracking
  - RealityDebugger: stuck models, conceptual disagreement, hypothesis dynamics
"""

from merid.cognitive.models import (
    CognitiveSnapshot,
    EvidenceLink,
    EvidenceType,
    Hypothesis,
    HypothesisAction,
    HypothesisStatus,
    RegimeTag,
    SnapshotDomain,
)
from merid.cognitive.store import CognitiveStore, get_cognitive_store
from merid.cognitive.reality_debugger import (
    ConceptualDisagreement,
    HypothesisDynamics,
    RealityDebugger,
    StuckModel,
    get_reality_debugger,
)

__all__ = [
    # Models
    "CognitiveSnapshot",
    "EvidenceLink",
    "EvidenceType",
    "Hypothesis",
    "HypothesisAction",
    "HypothesisStatus",
    "RegimeTag",
    "SnapshotDomain",
    # Store
    "CognitiveStore",
    "get_cognitive_store",
    # Reality debugger
    "ConceptualDisagreement",
    "HypothesisDynamics",
    "RealityDebugger",
    "StuckModel",
    "get_reality_debugger",
]
