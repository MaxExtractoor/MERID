"""
MERID Canonical JSON Schemas - Phase 14 Contract Freeze

Version: 1.0.0
Date: 2026-01-11

These schemas define the immutable "physics" of MERID.
All data structures must validate against these schemas.
"""

SCHEMA_VERSION = "1.0.0"
SCHEMA_DATE = "2026-01-11"

SCHEMAS = [
    "IntentEnvelope",
    "ConsensusBlock", 
    "SimulationReport",
    "RiskPreview",
    "ExecutionResult",
    "ArbitrageOpportunity",
]
