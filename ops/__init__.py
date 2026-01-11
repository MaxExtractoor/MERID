"""
MERID-OPS Module

Operations & Intelligence Fabric - "What is happening in the world right now?"

Components:
- Data Provenance: Source trust tracking and decay
- Signal Entropy: Echo chamber and noise detection
- Conflict Detector: Cross-domain disagreement analysis
"""

from ops.data_provenance import (
    DataProvenanceTracker,
    DataSource,
    DataPoint,
    SourceType,
    get_provenance_tracker,
)
from ops.signal_entropy import (
    SignalEntropyTracker,
    Signal,
    EntropyWindow,
    get_entropy_tracker,
)
from ops.conflict_detector import (
    CrossDomainConflictDetector,
    Domain,
    DomainSignal,
    Conflict,
    ConflictSeverity,
    get_conflict_detector,
)

__all__ = [
    "DataProvenanceTracker",
    "DataSource",
    "DataPoint",
    "SourceType",
    "get_provenance_tracker",
    "SignalEntropyTracker",
    "Signal",
    "EntropyWindow",
    "get_entropy_tracker",
    "CrossDomainConflictDetector",
    "Domain",
    "DomainSignal",
    "Conflict",
    "ConflictSeverity",
    "get_conflict_detector",
]
