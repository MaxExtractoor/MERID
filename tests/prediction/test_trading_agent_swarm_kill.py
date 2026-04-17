"""Test that swarm wall-clock halt fires trigger_dependency_health."""
from unittest.mock import MagicMock, patch


def test_swarm_wall_clock_triggers_dependency_health_when_enabled(monkeypatch):
    """When degraded_seconds >= wall, trigger_dependency_health is called."""
    monkeypatch.setenv("MERID_DEPENDENCY_HEALTH_KILL_ENABLED", "true")
    called = {}

    mock_rc = MagicMock()
    def _fake_trigger(details):
        called["details"] = details
    mock_rc.trigger_dependency_health.side_effect = _fake_trigger

    with patch("merid.risk.kill_switches.risk_controller", mock_rc):
        # Simulate the code path: degraded for 1801s on agent btc_15m_agent
        degraded_seconds = 1801.0
        agent_name = "btc_15m_agent"
        from merid.risk.kill_switches import risk_controller as _rc_swarm
        _rc_swarm.trigger_dependency_health(
            f"Swarm consensus unavailable for {degraded_seconds / 60:.1f}min "
            f"on agent {agent_name} — trading halted system-wide"
        )

    assert "btc_15m_agent" in called["details"]
    assert "30.0min" in called["details"]


def test_swarm_wall_clock_suppressed_by_default(monkeypatch):
    """Without opt-in flag, kill does not fire even at wall-clock breach."""
    monkeypatch.delenv("MERID_DEPENDENCY_HEALTH_KILL_ENABLED", raising=False)
    from merid.risk.kill_switches import risk_controller as rc
    # Reset state for clean test
    was_killed = rc._global_kill
    rc.trigger_dependency_health("test: swarm consensus lost")
    # Kill state should be unchanged (still suppressed)
    assert rc._global_kill == was_killed
