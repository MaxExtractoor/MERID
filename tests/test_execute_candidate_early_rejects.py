"""Behavioral tests for _execute_candidate early-validation rejects.

Replaces source-scan assertions in test_loop_15m_bugfixes.py with outcome
checks: the method must return False and stamp _reject_detail with the
named gate/reason, so callers never track these candidates as executed.
"""

from collections import Counter
from unittest.mock import MagicMock

import pytest


def _make_loop():
    from merid.loop_15m import Kalshi15mLoop

    loop = Kalshi15mLoop(
        agent_grid=MagicMock(),
        bankroll_service=MagicMock(),
        risk_config=MagicMock(),
        cadence_seconds=5,
    )
    loop._rejection_counters = Counter()
    return loop


@pytest.mark.asyncio
async def test_missing_ticker_rejected_with_detail():
    loop = _make_loop()
    candidate = {"side": "yes", "action": "buy"}

    result = await loop._execute_candidate(candidate, tick=1)

    assert result is False
    detail = candidate["_reject_detail"]
    assert detail["stage"] == "candidate_validation"
    assert detail["reason"] == "missing_ticker"


@pytest.mark.asyncio
async def test_missing_side_rejected_with_detail():
    loop = _make_loop()
    candidate = {"ticker": "KXBTC15M-TEST", "side": "", "action": "buy"}

    result = await loop._execute_candidate(candidate, tick=1)

    assert result is False
    detail = candidate["_reject_detail"]
    assert detail["stage"] == "candidate_validation"
    assert detail["reason"] == "missing_side_or_action"
    assert loop._rejection_counters.get("other", 0) == 1


@pytest.mark.asyncio
async def test_missing_action_rejected_with_detail():
    loop = _make_loop()
    candidate = {"ticker": "KXBTC15M-TEST", "side": "yes", "action": None}

    result = await loop._execute_candidate(candidate, tick=1)

    assert result is False
    detail = candidate["_reject_detail"]
    assert detail["stage"] == "candidate_validation"
    assert detail["reason"] == "missing_side_or_action"


@pytest.mark.asyncio
async def test_dispatch_attempt_incremented_on_early_reject():
    """Every _execute_candidate entry bumps _dispatch_attempt so retry /
    duplicate-dispatch accounting stays accurate even on early rejects."""
    loop = _make_loop()
    candidate = {"side": "yes", "action": "buy"}

    await loop._execute_candidate(candidate, tick=1)

    assert candidate["_dispatch_attempt"] == 1
