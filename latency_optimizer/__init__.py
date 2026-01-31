"""Latency-aware orchestration utilities for MERID."""
from .config import DOMAIN_SLOS, LatencyBudget, SLODefinition, FallbackStrategy
from .tracer import LatencyTracer, LatencySpan, get_latency_tracer
from .policies import LatencyOptimizerPolicy, get_latency_policy
from .orchestrator_hooks import (
    record_trading_tick,
    record_dev_swarm_command,
    record_llm_request,
)

__all__ = [
    "DOMAIN_SLOS",
    "LatencyBudget",
    "SLODefinition",
    "FallbackStrategy",
    "LatencyTracer",
    "LatencySpan",
    "get_latency_tracer",
    "LatencyOptimizerPolicy",
    "get_latency_policy",
    "record_trading_tick",
    "record_dev_swarm_command",
    "record_llm_request",
]
