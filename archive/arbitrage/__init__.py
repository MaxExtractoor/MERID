"""
MERID Arbitrage Engine.

Read-only scanners for detecting arbitrage opportunities.
Execution is DISABLED by default until scanners are proven.

Version: 1.0.0
"""

from arbitrage.scanner_base import ArbitrageScanner, ScannerConfig, ScannerState
from arbitrage.cross_cex_scanner import CrossCEXScanner, get_cross_cex_scanner
from arbitrage.dex_cex_scanner import DEXCEXScanner, get_dex_cex_scanner
from arbitrage.perp_spot_scanner import PerpSpotScanner, get_perp_spot_scanner
from arbitrage.funding_rate_scanner import FundingRateScanner, get_funding_rate_scanner
from arbitrage.cost_model import CostModelEngine, get_cost_model_engine
from arbitrage.execution_gate import ExecutionGate, get_execution_gate

__all__ = [
    "ArbitrageScanner",
    "ScannerConfig",
    "ScannerState",
    "CrossCEXScanner",
    "get_cross_cex_scanner",
    "DEXCEXScanner",
    "get_dex_cex_scanner",
    "PerpSpotScanner",
    "get_perp_spot_scanner",
    "FundingRateScanner",
    "get_funding_rate_scanner",
    "CostModelEngine",
    "get_cost_model_engine",
    "ExecutionGate",
    "get_execution_gate",
]

# CRITICAL: Execution is disabled by default
EXECUTION_ENABLED = False
