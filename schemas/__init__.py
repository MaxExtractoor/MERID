"""
MERID Canonical Data Schemas.

This module defines the authoritative data structures for the entire system.
All modules MUST use these schemas to prevent drift.

Version: 1.0.0
"""

from schemas.intent import IntentEnvelope, IntentType, IntentStatus
# from schemas.consensus import ConsensusBlock, ConsensusVote, ConsensusOutcome  # File doesn't exist - removed
from schemas.arbitrage import ArbitrageOpportunity, ArbitrageType, ArbitrageLeg
from schemas.execution import ExecutionResult, ExecutionStatus, OrderFill
from schemas.simulation import SimulationReport, SimulationScenario
from schemas.risk_schemas import RiskPreview, RiskLevel, RiskFactor

__all__ = [
    # Intent
    "IntentEnvelope",
    "IntentType",
    "IntentStatus",
    # Consensus - REMOVED: file doesn't exist
    # "ConsensusBlock",
    # "ConsensusVote",
    # "ConsensusOutcome",
    # Arbitrage
    "ArbitrageOpportunity",
    "ArbitrageType",
    "ArbitrageLeg",
    # Execution
    "ExecutionResult",
    "ExecutionStatus",
    "OrderFill",
    # Simulation
    "SimulationReport",
    "SimulationScenario",
    # Risk
    "RiskPreview",
    "RiskLevel",
    "RiskFactor",
]

SCHEMA_VERSION = "1.0.0"
