"""
MERID Pipelines Package

Provides the 15m execution shell architecture where:
- Only 15m crypto agents (BTC/ETH/SOL/XRP/DOGE) can place trades
- All other agents are feature producers (sentiment, regime, macro, etc.)
- No non-15m behavior leaks into execution
"""

from merid.pipelines.feature_bundle import (
    FifteenMinuteFeatureBundle,
    FeatureDict,
    TradeDecision,
)

from merid.pipelines.pipeline_schema import (
    PipelineConfig,
    PipelineRegistry,
    FeatureAgentConfig,
    ExecutionAgentConfig,
    ExecutorConfig,
    AgentRole,
    FeatureNamespace,
)

from merid.pipelines.pipeline_loader import (
    load_pipeline_config,
    get_default_pipeline_config_path,
)

from merid.pipelines.kalshi_15m_orchestrator import (
    Kalshi15mOrchestrator,
    FeatureAgentInvoker,
)

from merid.pipelines.pre_trade_risk import (
    PreTradeRiskChecker,
    RiskCheckResult,
)

from merid.pipelines.observability import (
    PipelineObservability,
    DecisionTrace,
    FeatureNamespaceSummary,
)

__all__ = [
    # Feature Bundle
    "FifteenMinuteFeatureBundle",
    "FeatureDict",
    "TradeDecision",
    # Pipeline Schema
    "PipelineConfig",
    "PipelineRegistry",
    "FeatureAgentConfig",
    "ExecutionAgentConfig",
    "ExecutorConfig",
    "AgentRole",
    "FeatureNamespace",
    # Pipeline Loader
    "load_pipeline_config",
    "get_default_pipeline_config_path",
    # Orchestrator
    "Kalshi15mOrchestrator",
    "FeatureAgentInvoker",
    # Pre-Trade Risk
    "PreTradeRiskChecker",
    "RiskCheckResult",
    # Observability
    "PipelineObservability",
    "DecisionTrace",
    "FeatureNamespaceSummary",
]
