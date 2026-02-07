"""
MERID Prediction Market Time-Exploit Engine.

Detects and exploits timing inefficiencies in prediction markets.
HIGH REGULATORY RISK - Alert-only mode by default.

Version: 1.0.0
"""

from prediction.oracle_latency import OracleLatencyDetector, get_oracle_latency_detector
from prediction.resolution_tracker import ResolutionTracker, get_resolution_tracker
from prediction.probability_decay import ProbabilityDecayAnalyzer, get_probability_decay_analyzer
from prediction.time_exploit_scanner import TimeExploitScanner, get_time_exploit_scanner
from prediction.cross_hedge import CrossHedgeEngine, get_cross_hedge_engine

__all__ = [
    "OracleLatencyDetector",
    "get_oracle_latency_detector",
    "ResolutionTracker",
    "get_resolution_tracker",
    "ProbabilityDecayAnalyzer",
    "get_probability_decay_analyzer",
    "TimeExploitScanner",
    "get_time_exploit_scanner",
    "CrossHedgeEngine",
    "get_cross_hedge_engine",
]

# CRITICAL: Alert-only mode by default - no execution
EXECUTION_ENABLED = False
ALERT_ONLY = True
