"""
MERID-ARCHIVE Module

Memory & Truth - "What actually happened, and what did we learn?"

Layer 7 of Master Build Directive - MEMORY & FORENSICS

Components:
- Audit Ledger: Immutable history with hash chain
- Hash Chains: Tamper proofing and Merkle proofs
- Decision Logs: Intent → outcome mapping
- Replay Engine: Simulation rewind and counterfactual analysis
- Outcome Scoring: Agent performance tracking based on actual results
- Strategy Autopsy: Post-mortem analysis of failed strategies

Authority:
- Cannot influence live systems
- Immutable truth only
"""

from archive.outcome_scoring import (
    OutcomeScoringEngine,
    AgentOutcome,
    AgentScorecard,
    OutcomeType,
    OutcomeResult,
    get_outcome_scoring,
)
from archive.strategy_autopsy import (
    StrategyAutopsyEngine,
    StrategyAutopsy,
    StrategyPerformance,
    StrategyOutcome,
    FailureCategory,
    get_strategy_autopsy,
)
from archive.ledger import (
    AuditLedger,
    LedgerEntry,
    EventType,
    get_audit_ledger,
)
from archive.hashchain import (
    HashChain,
    Block,
    get_hash_chain,
)
from archive.decisions import (
    DecisionLogger,
    DecisionRecord,
    DecisionEvent,
    DecisionStatus,
    DecisionOutcome,
    get_decision_logger,
)
from archive.replay import (
    ReplayEngine,
    ReplaySession,
    ReplayEvent,
    ReplayMode,
    ReplayState,
    get_replay_engine,
)
from archive.system_recorder import (
    SystemRecorder,
    SystemRecord,
    RecordCategory,
    RecordPriority,
    get_system_recorder,
)

__all__ = [
    # Outcome Scoring
    "OutcomeScoringEngine",
    "AgentOutcome",
    "AgentScorecard",
    "OutcomeType",
    "OutcomeResult",
    "get_outcome_scoring",
    # Strategy Autopsy
    "StrategyAutopsyEngine",
    "StrategyAutopsy",
    "StrategyPerformance",
    "StrategyOutcome",
    "FailureCategory",
    "get_strategy_autopsy",
    # Audit Ledger
    "AuditLedger",
    "LedgerEntry",
    "EventType",
    "get_audit_ledger",
    # Hash Chain
    "HashChain",
    "Block",
    "get_hash_chain",
    # Decision Logs
    "DecisionLogger",
    "DecisionRecord",
    "DecisionEvent",
    "DecisionStatus",
    "DecisionOutcome",
    "get_decision_logger",
    # Replay Engine
    "ReplayEngine",
    "ReplaySession",
    "ReplayEvent",
    "ReplayMode",
    "ReplayState",
    "get_replay_engine",
    # System Recorder
    "SystemRecorder",
    "SystemRecord",
    "RecordCategory",
    "RecordPriority",
    "get_system_recorder",
]
