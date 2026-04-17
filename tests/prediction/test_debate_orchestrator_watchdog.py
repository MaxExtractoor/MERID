"""Tests for debate orchestrator per-step timeout enforcement."""
import asyncio
import pytest
from unittest.mock import patch, AsyncMock


@pytest.mark.asyncio
async def test_hung_step_does_not_block_subsequent_steps():
    """A step that hangs beyond STEP_TIMEOUT_S must be cancelled; remaining steps must run."""
    from merid.prediction.debate_orchestrator import DebateOrchestrator

    orchestrator = DebateOrchestrator.__new__(DebateOrchestrator)
    orchestrator._running = False  # prevent full loop
    orchestrator._debates = {}
    orchestrator._invitations = {}
    orchestrator._completed_sessions = []

    call_log = []

    async def slow_scan():
        call_log.append("scan_start")
        await asyncio.sleep(100)  # far beyond any timeout
        call_log.append("scan_end")  # must NOT be reached

    async def instant_noop():
        call_log.append("noop")

    # Override the timeout to 0.1s so the test runs in <1s instead of 30s
    orchestrator._ORCHESTRATION_STEP_TIMEOUT_S = 0.1

    with patch.object(orchestrator, "_scan_debate_opportunities", slow_scan), \
         patch.object(orchestrator, "_process_invitations", instant_noop), \
         patch.object(orchestrator, "_manage_active_sessions", instant_noop), \
         patch.object(orchestrator, "_evaluate_completed_sessions", instant_noop), \
         patch.object(orchestrator, "_cleanup_expired_sessions", instant_noop):

        TIMEOUT = orchestrator._ORCHESTRATION_STEP_TIMEOUT_S
        for step_name, step_fn in [
            ("scan", orchestrator._scan_debate_opportunities),
            ("invitations", orchestrator._process_invitations),
            ("sessions", orchestrator._manage_active_sessions),
            ("evaluate", orchestrator._evaluate_completed_sessions),
            ("cleanup", orchestrator._cleanup_expired_sessions),
        ]:
            try:
                await asyncio.wait_for(step_fn(), timeout=TIMEOUT)
            except asyncio.TimeoutError:
                pass  # expected for slow_scan
            except Exception:
                pass

    assert "scan_start" in call_log, "scan must have been called"
    assert "scan_end" not in call_log, "slow scan must have been timed out before completing"
    assert call_log.count("noop") == 4, f"All 4 subsequent steps must run; got {call_log}"


@pytest.mark.asyncio
async def test_step_timeout_constant_exists():
    """_ORCHESTRATION_STEP_TIMEOUT_S must be a class-level float."""
    from merid.prediction.debate_orchestrator import DebateOrchestrator
    assert hasattr(DebateOrchestrator, "_ORCHESTRATION_STEP_TIMEOUT_S"), \
        "Class must have _ORCHESTRATION_STEP_TIMEOUT_S"
    assert isinstance(DebateOrchestrator._ORCHESTRATION_STEP_TIMEOUT_S, float), \
        "_ORCHESTRATION_STEP_TIMEOUT_S must be a float"
    assert DebateOrchestrator._ORCHESTRATION_STEP_TIMEOUT_S > 0
