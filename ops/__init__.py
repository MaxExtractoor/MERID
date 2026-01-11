"""
MERID-OPS Module

Operations & Intelligence Fabric - "What is happening in the world right now?"

Phase 1 of Master Build Directive - PERCEPTION (BLOCKING)

Components:
- Regime Detection: HMM + Bayesian Change Point Detection
- Anomaly Detection: Isolation Forest, CUSUM, Page-Hinkley
- Epistemic Confidence: Ensemble disagreement, OOD detection, confidence decay
- Information Latency: Oracle/exchange latency, alpha decay modeling
- Data Provenance: Source trust tracking and decay
- Signal Entropy: Echo chamber and noise detection
- Conflict Detector: Cross-domain disagreement analysis
- Causal Attribution: Strategy-outcome causality, counterfactual analysis
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
from ops.regime_detection import (
    RegimeDetector,
    MarketRegime,
    RegimeConstraints,
    RegimeState,
    RegimeObservation,
    REGIME_CONSTRAINTS,
    get_regime_detector,
)
from ops.anomaly_detection import (
    AnomalyDetectionStack,
    AnomalyType,
    AnomalySeverity,
    AnomalyEvent,
    IsolationForest,
    CUSUM,
    PageHinkley,
    get_anomaly_detection,
)
from ops.epistemic_confidence import (
    EpistemicConfidenceEngine,
    EpistemicState,
    EpistemicSnapshot,
    ConfidenceSource,
    get_epistemic_engine,
)
from ops.information_latency import (
    InformationLatencyTracker,
    InformationSource,
    LatencyClass,
    SourceLatencyProfile,
    get_latency_tracker,
)
from ops.causal_attribution import (
    CausalAttributionEngine,
    CausalFactor,
    CausalLink,
    Counterfactual,
    CausalAnalysis,
    get_causal_engine,
)
from ops.signal_generator import (
    SignalGenerator,
    TradingSignal,
    SignalType,
    SignalStrength,
    SignalGeneratorConfig,
    get_signal_generator,
)

__all__ = [
    # Data Provenance
    "DataProvenanceTracker",
    "DataSource",
    "DataPoint",
    "SourceType",
    "get_provenance_tracker",
    # Signal Entropy
    "SignalEntropyTracker",
    "Signal",
    "EntropyWindow",
    "get_entropy_tracker",
    # Conflict Detector
    "CrossDomainConflictDetector",
    "Domain",
    "DomainSignal",
    "Conflict",
    "ConflictSeverity",
    "get_conflict_detector",
    # Regime Detection
    "RegimeDetector",
    "MarketRegime",
    "RegimeConstraints",
    "RegimeState",
    "RegimeObservation",
    "REGIME_CONSTRAINTS",
    "get_regime_detector",
    # Anomaly Detection
    "AnomalyDetectionStack",
    "AnomalyType",
    "AnomalySeverity",
    "AnomalyEvent",
    "IsolationForest",
    "CUSUM",
    "PageHinkley",
    "get_anomaly_detection",
    # Epistemic Confidence
    "EpistemicConfidenceEngine",
    "EpistemicState",
    "EpistemicSnapshot",
    "ConfidenceSource",
    "get_epistemic_engine",
    # Information Latency
    "InformationLatencyTracker",
    "InformationSource",
    "LatencyClass",
    "SourceLatencyProfile",
    "get_latency_tracker",
    # Causal Attribution
    "CausalAttributionEngine",
    "CausalFactor",
    "CausalLink",
    "Counterfactual",
    "CausalAnalysis",
    "get_causal_engine",
    # Signal Generator
    "SignalGenerator",
    "TradingSignal",
    "SignalType",
    "SignalStrength",
    "SignalGeneratorConfig",
    "get_signal_generator",
]
