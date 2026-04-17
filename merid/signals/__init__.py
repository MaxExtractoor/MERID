"""MERID Signals — Unified ingestion, processing, and feature extraction.

§1 Domain objects: InfoEvent, SentimentFeature, SentimentSpike
§2 Ingestion: XWorker, TelegramWorker, NewsWorker
§3 Processing: SentimentProcessor, spike detection
§4 Agents: SentimentAgent, NewsThesisAgent, TelegramOpsAgent
§5 Operator I/O: AlertRouter for Telegram + X outbound

Signal Layer (decay-aware opportunity discovery):
§D1 Decay: DecayConfig, decay_weight(), DecayEnvelope, SignalSnapshot
§D2 Features: NewsFeatures, MacroFeatures, OnChainFeatures, SocialFeatures
§D3 Arbitrage: DislocationScanner, DislocationSignal, ArbPlan with TTL
§D4 Store: SignalStore (SQLite persistence)
§D5 Drift: DriftDetector, DomainDriftMetric, ConsensusQualityIndex

TA Decision Stack (canonical technical analysis):
§T1 Models: OHLCVSnapshot, IndicatorBundle, MarketStructure, SignalScore
§T2 Engine: TAEngine with RSI/MACD divergence detection
§T3 Fusion: TimeframeFusionEngine for multi-TF signal clustering
§T4 Regime: RegimeEngine for dynamic threshold adjustment
§T5 Logging: DecisionLogger for structured audit trail
"""

# TA Stack exports
from .ta_models import (
    OHLCVSnapshot,
    IndicatorBundle,
    MarketStructure,
    SignalScore,
    FusedClusterSignal,
    Divergence,
    FibPivots,
    GlobalRegime,
)

from .ta_engine import TAEngine, IndicatorConfig

from .timeframe_fusion import TimeframeFusionEngine, FusionConfig

from .regime_engine import RegimeEngine, RegimeConfig, get_regime_engine

from .decision_logger import DecisionLogger, TradeDecisionLog, get_decision_logger

__all__ = [
    # Models
    "OHLCVSnapshot",
    "IndicatorBundle",
    "MarketStructure",
    "SignalScore",
    "FusedClusterSignal",
    "Divergence",
    "FibPivots",
    "GlobalRegime",
    # Engine
    "TAEngine",
    "IndicatorConfig",
    # Fusion
    "TimeframeFusionEngine",
    "FusionConfig",
    # Regime
    "RegimeEngine",
    "RegimeConfig",
    "get_regime_engine",
    # Logging
    "DecisionLogger",
    "TradeDecisionLog",
    "get_decision_logger",
]
