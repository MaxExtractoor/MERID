"""
MERID-ARCHIVE Module

Memory & Truth - "What actually happened, and what did we learn?"

⚠️  SECURITY GUARD (Pass 8): This module is BLOCKED in live trading processes.
Archive modules contain historical analytics code that must not influence live execution.

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

# ═══════════════════════════════════════════════════════════════════════════════
# PASS 8 P0: Archive Import Guard
# Blocks import of archive modules into live trading processes
# ═══════════════════════════════════════════════════════════════════════════════

import os
import sys

def _enforce_archive_import_guard():
    """Prevent archive imports in live trading contexts."""
    _env = os.getenv("KALSHI_ENV", os.getenv("MERID_TRADE_MODE", "unknown"))
    _process = os.getenv("MERID_PROCESS_TYPE", "")
    
    # Block in live/paper modes
    if _env in ("live", "paper", "LIVE", "PAPER"):
        # Additional check: is this a trading process?
        _is_trading = any(x in _process.lower() for x in [
            "trading", "execution", "agent", "trader", "order"
        ])
        
        if _is_trading or not _process:  # If no process type, be conservative
            # Try to log and record metric before raising (may fail, that's ok)
            try:
                from merid.utils.structured_logging import get_structured_logger
                from merid.metrics.kalshi_metrics import record_guard_trip
                
                slogger = get_structured_logger(__name__)
                slogger.log_guard_trip(
                    guard_type="PASS8_ARCHIVE_GUARD",
                    mode=_env.lower(),
                    endpoint="archive_import",
                    details={"process_type": _process or "unknown"}
                )
                record_guard_trip("PASS8_ARCHIVE_GUARD", _env.lower(), "archive_import")
            except Exception:
                pass  # Guard must work even if logging/metrics fail
            
            raise ImportError(
                f"\n"
                f"╔════════════════════════════════════════════════════════════════╗\n"
                f"║  FATAL: Archive Import Blocked in {_env.upper()} Mode                  ║\n"
                f"╠════════════════════════════════════════════════════════════════╣\n"
                f"║  Attempted to import 'archive' module in a trading process.    ║\n"
                f"║  Archive modules are for post-trade analytics ONLY.            ║\n"
                f"║                                                                ║\n"
                f"║  Process type: {_process or 'UNKNOWN (trading suspected)'}      ║\n"
                f"║                                                                ║\n"
                f"║  If you need this functionality in production:                 ║\n"
                f"║  1. Move the module to merid/analytics/ (for post-trade)       ║\n"
                f"║  2. Or port the logic to the canonical executor path           ║\n"
                f"║  3. Or set MERID_PROCESS_TYPE=analytics for reporting          ║\n"
                f"╚════════════════════════════════════════════════════════════════╝\n"
            )

# Apply guard at module import time
_enforce_archive_import_guard()

"""
MERID-ARCHIVE Module (continued)

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
