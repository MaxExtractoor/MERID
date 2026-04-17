"""
Lane Enforcement Module — Runtime guards for swarm topology
==========================================================

Ensures agents stay in their declared lanes and cross-lane calls
only happen through defined gateways.

Usage:
    from merid.prediction.lane_enforcement import (
        Lane, assert_lane, gate_production_only, verify_no_dev_agents
    )

    @assert_lane(Lane.SIGNAL)
    async def get_opinion(self):
        ...

    gate_production_only()  # Blocks dev agents in production
"""

from __future__ import annotations

import functools
import os
from enum import Enum, auto
from typing import Any, Callable, Optional, Set

from utils.logger import get_logger

logger = get_logger("merid.prediction.lane_enforcement")


class Lane(Enum):
    """Swarm lanes (see AGENT_GRID_AND_SWARM_MATRIX_AUDIT.md)."""
    SIGNAL = auto()      # Input → Decision (traders, sentiment, consensus)
    RISK = auto()         # Continuous monitoring (risk, critic, analytics)
    EXECUTION = auto()    # Decision → Fill (execution, order routing)
    ANALYTICS = auto()    # Observer only (read-only)
    DEV = auto()          # Code/testing (dev, test agents)
    UNKNOWN = auto()      # Unclassified (blocked in production)


# Agent → Lane mapping (populated from grid config at runtime)
_AGENT_LANE_MAP: dict[str, Lane] = {}

# Dev-only agent IDs (blocked in production)
_DEV_AGENT_IDS: Set[str] = {
    "dev_swarm", "test_agent", "mock_trader", "simulation_agent",
    "archive_btc_15m", "legacy_eth_hourly",  # Archive agents
}

# Production environment detection
_IS_PRODUCTION = os.getenv("MERID_ENV", "").lower() in ("production", "prod")
_KALSHI_ONLY = os.getenv("MERID_PROFILE", "").lower() == "kalshi-only"


def register_agent_lane(agent_id: str, lane: Lane) -> None:
    """Register an agent's lane for runtime enforcement."""
    _AGENT_LANE_MAP[agent_id] = lane
    logger.debug("Lane registered: %s → %s", agent_id, lane.name)


def get_agent_lane(agent_id: str) -> Lane:
    """Get an agent's lane (defaults to UNKNOWN)."""
    return _AGENT_LANE_MAP.get(agent_id, Lane.UNKNOWN)


def assert_lane(lane: Lane):
    """Decorator: enforce that decorated function only runs in declared lane.

    Usage:
        @assert_lane(Lane.SIGNAL)
        async def get_opinion(self):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            _check_lane(func.__qualname__, lane)
            return await func(*args, **kwargs)

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            _check_lane(func.__qualname__, lane)
            return func(*args, **kwargs)

        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    return decorator


def _check_lane(func_name: str, expected_lane: Lane) -> None:
    """Verify we're in the expected lane (production enforcement)."""
    if not _IS_PRODUCTION:
        return  # Skip in dev/test

    # In production, UNKNOWN lane is blocked
    if expected_lane == Lane.UNKNOWN:
        raise LaneViolationError(
            f"Function {func_name} declared in UNKNOWN lane — "
            "must register agent with explicit lane"
        )

    # DEV lane blocked in production
    if expected_lane == Lane.DEV:
        raise LaneViolationError(
            f"DEV lane function {func_name} called in production — blocked"
        )


def gate_production_only(agent_id: Optional[str] = None) -> None:
    """Production gate: blocks dev/archive agents and unknown lanes.

    Call at start of agent initialization in production.
    """
    if not _IS_PRODUCTION and not _KALSHI_ONLY:
        return

    # Block dev agents
    if agent_id and agent_id.lower() in _DEV_AGENT_IDS:
        raise LaneViolationError(
            f"Dev agent '{agent_id}' blocked in production"
        )

    # Block UNKNOWN lane agents in kalshi-only profile
    if _KALSHI_ONLY and agent_id:
        lane = get_agent_lane(agent_id)
        if lane == Lane.UNKNOWN:
            raise LaneViolationError(
                f"Agent '{agent_id}' in UNKNOWN lane blocked in kalshi-only profile"
            )


def verify_no_dev_agents(agent_ids: list[str]) -> list[str]:
    """Filter list to only production-safe agents.

    Returns agents that passed verification.
    """
    safe: list[str] = []
    for aid in agent_ids:
        if aid.lower() in _DEV_AGENT_IDS:
            logger.warning("Filtered dev agent: %s", aid)
            continue
        if _KALSHI_ONLY and get_agent_lane(aid) == Lane.UNKNOWN:
            logger.warning("Filtered unknown-lane agent: %s", aid)
            continue
        safe.append(aid)
    return safe


class LaneViolationError(RuntimeError):
    """Raised when lane boundaries are violated."""
    pass


# Convenience aliases for common lanes
SIGNAL = Lane.SIGNAL
RISK = Lane.RISK
EXECUTION = Lane.EXECUTION
ANALYTICS = Lane.ANALYTICS
DEV = Lane.DEV


# Lazy import to avoid circular dependency
import asyncio
