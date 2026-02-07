"""
Oracle Stack - Triple-redundant price oracles per MASTER_SPEC v1.0

This module exports the oracle stack components:
- Chainlink (Primary - highest reliability)
- Pyth (Secondary - lowest latency)
- Switchboard (Tertiary - backup)
- OracleCoordinator (2-of-3 consensus)

Reference: MASTER_SPEC.md Section 3 (Layer 5: Oracle Stack)
"""

from oracles.base_oracle import BaseOracle, OraclePrice, OracleStatus, OracleHealth
from oracles.chainlink import ChainlinkOracle, get_chainlink_oracle
from oracles.pyth import PythOracle, get_pyth_oracle
from oracles.switchboard import SwitchboardOracle, get_switchboard_oracle
from oracles.coordinator import (
    OracleCoordinator,
    OracleConsensusResult,
    CoordinatorConfig,
    get_oracle_coordinator,
    initialize_oracles,
    shutdown_oracles,
)

__all__ = [
    "BaseOracle",
    "OraclePrice",
    "OracleStatus",
    "OracleHealth",
    "ChainlinkOracle",
    "PythOracle",
    "SwitchboardOracle",
    "OracleCoordinator",
    "OracleConsensusResult",
    "CoordinatorConfig",
    "get_chainlink_oracle",
    "get_pyth_oracle",
    "get_switchboard_oracle",
    "get_oracle_coordinator",
    "initialize_oracles",
    "shutdown_oracles",
]
