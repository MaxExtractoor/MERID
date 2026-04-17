"""Latency optimizer configuration and SLO definitions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class LatencyBudget:
    p50_ms: float
    p95_ms: float
    hard_deadline_ms: float


@dataclass(frozen=True)
class FallbackStrategy:
    strategy_id: str
    description: str
    action: str  # e.g., "use_cached_result", "route_light_model", "skip_optional_stage"


@dataclass(frozen=True)
class SLODefinition:
    domain: str
    workflow: str
    budget: LatencyBudget
    fallback_chain: Tuple[FallbackStrategy, ...]


DOMAIN_SLOS: Dict[str, Dict[str, SLODefinition]] = {
    "trading": {
        "tick_to_order": SLODefinition(
            domain="trading",
            workflow="tick_to_order",
            budget=LatencyBudget(p50_ms=8.0, p95_ms=12.0, hard_deadline_ms=20.0),
            fallback_chain=(
                FallbackStrategy(
                    strategy_id="fast_risk_path",
                    description="Bypass non-critical analytics and use cached risk envelope",
                    action="use_cached_result",
                ),
                FallbackStrategy(
                    strategy_id="edge_execution",
                    description="Route order to edge gateway with co-located market data",
                    action="reroute_edge_path",
                ),
            ),
        ),
        "social_signal_gate": SLODefinition(
            domain="trading",
            workflow="social_signal_gate",
            budget=LatencyBudget(p50_ms=25.0, p95_ms=60.0, hard_deadline_ms=120.0),
            fallback_chain=(
                FallbackStrategy(
                    strategy_id="summary_only",
                    description="Use summarized sentiment snapshot instead of full recompute",
                    action="use_cached_result",
                ),
            ),
        ),
    },
    "dev_swarm": {
        "command_execution": SLODefinition(
            domain="dev_swarm",
            workflow="command_execution",
            budget=LatencyBudget(p50_ms=250.0, p95_ms=750.0, hard_deadline_ms=2000.0),
            fallback_chain=(
                FallbackStrategy(
                    strategy_id="local_runner",
                    description="Prefer local lightweight runner over remote executor",
                    action="reroute_edge_path",
                ),
                FallbackStrategy(
                    strategy_id="llm_light_mode",
                    description="Switch to cached plan + minimal diff validation to unblock review",
                    action="use_cached_result",
                ),
            ),
        ),
    },
    "llm": {
        "default_request": SLODefinition(
            domain="llm",
            workflow="default_request",
            budget=LatencyBudget(p50_ms=1500.0, p95_ms=3500.0, hard_deadline_ms=6000.0),
            fallback_chain=(
                FallbackStrategy(
                    strategy_id="route_small_model",
                    description="Fallback to distilled model with prompt compression",
                    action="route_light_model",
                ),
                FallbackStrategy(
                    strategy_id="serve_cached_completion",
                    description="Return cached completion when prompt hash matches",
                    action="use_cached_result",
                ),
            ),
        ),
    },
    "social": {
        "signal_gate": SLODefinition(
            domain="social",
            workflow="signal_gate",
            budget=LatencyBudget(p50_ms=30.0, p95_ms=80.0, hard_deadline_ms=150.0),
            fallback_chain=(
                FallbackStrategy(
                    strategy_id="use_cached_signal",
                    description="Use cached social sentiment snapshot when full recompute breaches SLO",
                    action="use_cached_result",
                ),
                FallbackStrategy(
                    strategy_id="defer_low_priority_signals",
                    description="Drop low-priority channels to favor critical feeds",
                    action="skip_optional_stage",
                ),
            ),
        ),
    },
}


def get_slo(domain: str, workflow: str) -> SLODefinition | None:
    return DOMAIN_SLOS.get(domain, {}).get(workflow)
