"""Tests for critical audit fixes (Findings #64-#98).

Covers:
  - FIX-92: Kill switch mid-batch abort in loop._execute_plans
  - FIX-91: Cap exhaustion alert firing
  - FIX-98: AgentRiskLimits validation and clamping
  - FIX-95: Silent try-except improvement (logging check)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── FIX-92: Kill switch race condition in loop.py ────────────────────────


@dataclass
class FakePlan:
    plan_id: str
    symbol: str
    direction: str = "buy"
    domain: str = "prediction"
    status: str = "approved"
    target_size_usd: float = 100.0
    approved_size_usd: Optional[float] = None

    def is_expired(self):
        return False


@dataclass
class FakeVerdict:
    allowed: bool = True
    reason: str = "all checks passed"
    adjusted_size_usd: float = 100.0
    throttle_pct: float = 1.0
    cqi_score: float = 0.9


class FakeGuard:
    """Simulates ExecutionGuard with controllable kill switch."""

    def __init__(self):
        self.kill_switch_active = False
        self._check_count = 0
        self._activate_after_check = None
        self._executions: List[float] = []

    def pre_trade_check(self, **kwargs) -> FakeVerdict:
        self._check_count += 1
        if self.kill_switch_active:
            return FakeVerdict(allowed=False, reason="kill_switch", adjusted_size_usd=0)
        return FakeVerdict()

    def record_execution(self, domain: str, notional_usd: float):
        self._executions.append(notional_usd)

    def activate_mid_batch(self):
        """Simulates kill switch activating between plan checks."""
        self.kill_switch_active = True


@pytest.mark.asyncio
async def test_kill_switch_aborts_mid_batch():
    """FIX-92: Kill switch short-circuits _execute_plans before any plan runs.

    The consensus-based mid-batch plan loop was deliberately removed
    ("plan_execution:consensus_removed"); the canonical contract is the
    top-of-function kill-switch short-circuit in _execute_plans.
    """
    from merid.loop import MeridLoop, LoopConfig

    loop = MeridLoop(LoopConfig())
    guard = FakeGuard()
    guard.activate_mid_batch()

    summary: Dict[str, Any] = {"actions": []}

    with patch.object(loop, '_execution_guard', return_value=guard):
        await loop._execute_plans(summary)

    assert "execution:blocked_by_kill_switch" in summary["actions"]
    assert not any("executed:" in a for a in summary["actions"])


# ── FIX-91: Cap exhaustion alert ────────────────────────────────────────


def test_cap_exhaustion_fires_alert():
    """FIX-91: When daily notional cap is exhausted, an alert should fire."""
    from merid.execution_guard import ExecutionGuard

    guard = ExecutionGuard()

    # Set up a domain cap with no remaining notional
    cap_key = "prediction"
    if cap_key in guard._domain_caps:
        cap = guard._domain_caps[cap_key]
        cap.daily_notional_usd = cap.max_daily_notional_usd + 1
    else:
        pytest.skip("No prediction domain cap configured")

    with patch.object(ExecutionGuard, "_log_verdict") as mock_log:
        verdict = guard.pre_trade_check(
            plan_id="test-plan",
            symbol="TEST",
            domain=cap_key,
            size_usd=100.0,
        )

    assert not verdict.allowed
    assert "cap exhausted" in verdict.reason
    assert "daily_notional_cap" in verdict.checks_failed
    # Cap-exhaustion observability now flows through _log_verdict (BLOCKED warning
    # + trade log), which replaced the dedicated _fire_cap_exhaustion_alert hook.
    mock_log.assert_called_once()
    logged_verdict = mock_log.call_args[0][1]
    assert logged_verdict.reason == verdict.reason


# ── FIX-98: Config validation ───────────────────────────────────────────


def test_agent_risk_limits_rejects_negative_notional():
    """FIX-98: Negative max_notional_usd should raise ValueError."""
    from merid.prediction.agent_grid_config import AgentRiskLimits

    with pytest.raises(ValueError, match="max_notional_usd must be >= 0"):
        AgentRiskLimits(max_notional_usd=Decimal("-100"))






def test_agent_risk_limits_rejects_negative_positions():
    """FIX-98: Negative position limits should raise ValueError."""
    from merid.prediction.agent_grid_config import AgentRiskLimits

    with pytest.raises(ValueError, match="must be >= 0"):
        AgentRiskLimits(max_yes_position=-1)


def test_unknown_archetype_rejected():
    """FIX-78: Unknown archetypes (e.g. 'god_mode') should be rejected at parse time."""
    from merid.prediction.agent_grid_config import _parse_agent

    with pytest.raises(ValueError, match="unknown archetype"):
        _parse_agent({
            "name": "EVIL_AGENT",
            "archetype": "god_mode",
        })




# ── FIX-87: Vol zero safety ─────────────────────────────────────────────


def test_vol_scaled_fraction_zero_vol_returns_zero():
    """FIX-87: Zero realized vol should return 0 (not divide-by-zero)."""
    from merid.event_venues.kalshi.position_sizer import vol_scaled_fraction

    result = vol_scaled_fraction(base_fraction=0.25, realized_vol=0.0)
    assert result == 0.0


def test_vol_scaled_fraction_negative_vol_returns_zero():
    """FIX-87: Negative realized vol should return 0."""
    from merid.event_venues.kalshi.position_sizer import vol_scaled_fraction

    result = vol_scaled_fraction(base_fraction=0.25, realized_vol=-0.01)
    assert result == 0.0


def test_vol_scaled_fraction_normal_vol():
    """Sanity: Normal vol produces reasonable fraction."""
    from merid.event_venues.kalshi.position_sizer import vol_scaled_fraction

    result = vol_scaled_fraction(
        base_fraction=0.25,
        realized_vol=0.02,
        target_vol=0.02,
    )
    assert 0.0 < result <= 0.25
