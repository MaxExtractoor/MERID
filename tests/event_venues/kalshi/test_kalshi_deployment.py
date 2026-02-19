"""Tests for Kalshi Live Deployment Controller."""

import pytest

from merid.event_venues.kalshi.deployment import (
    AgentDeployment,
    AgentMode,
    DeploymentConfig,
    DeploymentController,
    TransitionLog,
)


# ── Helpers ────────────────────────────────────────────────────────────

def _ready_verdict():
    return {"ready": True, "checks": {}, "details": {}}


def _not_ready_verdict():
    return {"ready": False, "checks": {"min_trades": False}, "details": {"min_trades": "10 < 200"}}


def _relaxed_config(**overrides):
    defaults = dict(
        require_readiness_check=False,
        max_live_agents=5,
        min_shadow_trades_before_full_live=0,
    )
    defaults.update(overrides)
    return DeploymentConfig(**defaults)


# ── Registration ─────────────────────────────────────────────────────

class TestRegistration:
    def test_register_agent(self):
        ctrl = DeploymentController()
        dep = ctrl.register_agent("BTC_HOURLY")
        assert dep.agent_name == "BTC_HOURLY"
        assert dep.mode == AgentMode.PAPER

    def test_get_mode_unregistered(self):
        ctrl = DeploymentController()
        assert ctrl.get_mode("UNKNOWN") == AgentMode.PAPER

    def test_is_live_false_by_default(self):
        ctrl = DeploymentController()
        assert ctrl.is_live("BTC_HOURLY") is False


# ── Promotion to shadow ─────────────────────────────────────────────

class TestPromoteToShadow:
    def test_promote_paper_to_shadow(self):
        ctrl = DeploymentController(_relaxed_config())
        ctrl.register_agent("BTC_HOURLY")
        ok, reason = ctrl.promote_to_shadow("BTC_HOURLY")
        assert ok is True
        assert ctrl.get_mode("BTC_HOURLY") == AgentMode.SHADOW

    def test_already_shadow_rejected(self):
        ctrl = DeploymentController(_relaxed_config())
        ctrl.register_agent("BTC_HOURLY")
        ctrl.promote_to_shadow("BTC_HOURLY")
        ok, reason = ctrl.promote_to_shadow("BTC_HOURLY")
        assert ok is False

    def test_readiness_required(self):
        ctrl = DeploymentController(DeploymentConfig(require_readiness_check=True))
        ctrl.register_agent("BTC_HOURLY")
        ok, reason = ctrl.promote_to_shadow("BTC_HOURLY", readiness=None)
        assert ok is False

    def test_readiness_not_ready_rejected(self):
        ctrl = DeploymentController(DeploymentConfig(require_readiness_check=True))
        ctrl.register_agent("BTC_HOURLY")
        ok, reason = ctrl.promote_to_shadow("BTC_HOURLY", readiness=_not_ready_verdict())
        assert ok is False

    def test_readiness_ready_accepted(self):
        ctrl = DeploymentController(DeploymentConfig(
            require_readiness_check=True, max_live_agents=5,
        ))
        ctrl.register_agent("BTC_HOURLY")
        ok, reason = ctrl.promote_to_shadow("BTC_HOURLY", readiness=_ready_verdict())
        assert ok is True

    def test_max_live_agents_blocks(self):
        cfg = _relaxed_config(max_live_agents=1)
        ctrl = DeploymentController(cfg)
        ctrl.register_agent("BTC_HOURLY")
        ctrl.register_agent("ETH_HOURLY")
        ctrl.promote_to_shadow("BTC_HOURLY")
        ok, reason = ctrl.promote_to_shadow("ETH_HOURLY")
        assert ok is False
        assert "Max live agents" in reason


# ── Promotion to live ────────────────────────────────────────────────

class TestPromoteToLive:
    def test_promote_paper_to_live(self):
        ctrl = DeploymentController(_relaxed_config())
        ctrl.register_agent("BTC_HOURLY")
        ok, reason = ctrl.promote_to_live("BTC_HOURLY")
        assert ok is True
        assert ctrl.get_mode("BTC_HOURLY") == AgentMode.LIVE

    def test_already_live_rejected(self):
        ctrl = DeploymentController(_relaxed_config())
        ctrl.register_agent("BTC_HOURLY")
        ctrl.promote_to_live("BTC_HOURLY")
        ok, reason = ctrl.promote_to_live("BTC_HOURLY")
        assert ok is False

    def test_shadow_to_live_needs_trades(self):
        cfg = _relaxed_config(min_shadow_trades_before_full_live=50)
        ctrl = DeploymentController(cfg)
        ctrl.register_agent("BTC_HOURLY")
        ctrl.promote_to_shadow("BTC_HOURLY")
        ok, reason = ctrl.promote_to_live("BTC_HOURLY")
        assert ok is False
        assert "shadow trades" in reason.lower()

    def test_shadow_to_live_with_enough_trades(self):
        cfg = _relaxed_config(min_shadow_trades_before_full_live=10)
        ctrl = DeploymentController(cfg)
        ctrl.register_agent("BTC_HOURLY")
        ctrl.promote_to_shadow("BTC_HOURLY")
        for _ in range(15):
            ctrl.record_shadow_trade("BTC_HOURLY")
        ok, reason = ctrl.promote_to_live("BTC_HOURLY")
        assert ok is True

    def test_is_live_true_after_promotion(self):
        ctrl = DeploymentController(_relaxed_config())
        ctrl.register_agent("BTC_HOURLY")
        ctrl.promote_to_live("BTC_HOURLY")
        assert ctrl.is_live("BTC_HOURLY") is True

    def test_shadow_counts_as_live(self):
        ctrl = DeploymentController(_relaxed_config())
        ctrl.register_agent("BTC_HOURLY")
        ctrl.promote_to_shadow("BTC_HOURLY")
        assert ctrl.is_live("BTC_HOURLY") is True


# ── Rollback ─────────────────────────────────────────────────────────

class TestRollback:
    def test_rollback_live_to_paper(self):
        ctrl = DeploymentController(_relaxed_config())
        ctrl.register_agent("BTC_HOURLY")
        ctrl.promote_to_live("BTC_HOURLY")
        ok, msg = ctrl.rollback("BTC_HOURLY", reason="PF collapsed")
        assert ok is True
        assert ctrl.get_mode("BTC_HOURLY") == AgentMode.PAPER

    def test_rollback_increments_counter(self):
        ctrl = DeploymentController(_relaxed_config())
        ctrl.register_agent("BTC_HOURLY")
        ctrl.promote_to_live("BTC_HOURLY")
        ctrl.rollback("BTC_HOURLY", "test1")
        ctrl.promote_to_live("BTC_HOURLY")
        ctrl.rollback("BTC_HOURLY", "test2")
        dep = ctrl._agents["BTC_HOURLY"]
        assert dep.rollback_count == 2
        assert dep.last_rollback_reason == "test2"

    def test_rollback_paper_rejected(self):
        ctrl = DeploymentController(_relaxed_config())
        ctrl.register_agent("BTC_HOURLY")
        ok, msg = ctrl.rollback("BTC_HOURLY")
        assert ok is False

    def test_rollback_unregistered(self):
        ctrl = DeploymentController()
        ok, msg = ctrl.rollback("UNKNOWN")
        assert ok is False

    def test_halt(self):
        ctrl = DeploymentController(_relaxed_config())
        ctrl.register_agent("BTC_HOURLY")
        ctrl.promote_to_live("BTC_HOURLY")
        ok, msg = ctrl.halt("BTC_HOURLY", "emergency")
        assert ok is True
        assert ctrl.get_mode("BTC_HOURLY") == AgentMode.HALTED


# ── Auto-rollback ────────────────────────────────────────────────────

class TestAutoRollback:
    def test_pf_below_threshold(self):
        ctrl = DeploymentController(_relaxed_config(auto_rollback_on_pf_below=1.0))
        ctrl.register_agent("BTC_HOURLY")
        ctrl.promote_to_live("BTC_HOURLY")
        reason = ctrl.check_auto_rollback("BTC_HOURLY", profit_factor=0.8)
        assert reason is not None
        assert ctrl.get_mode("BTC_HOURLY") == AgentMode.PAPER

    def test_drawdown_above_threshold(self):
        ctrl = DeploymentController(_relaxed_config(auto_rollback_on_drawdown_above_pct=10.0))
        ctrl.register_agent("BTC_HOURLY")
        ctrl.promote_to_live("BTC_HOURLY")
        reason = ctrl.check_auto_rollback("BTC_HOURLY", drawdown_pct=12.0)
        assert reason is not None

    def test_consecutive_losses(self):
        ctrl = DeploymentController(_relaxed_config(auto_rollback_on_consecutive_losses=5))
        ctrl.register_agent("BTC_HOURLY")
        ctrl.promote_to_live("BTC_HOURLY")
        reason = ctrl.check_auto_rollback("BTC_HOURLY", consecutive_losses=6)
        assert reason is not None

    def test_no_rollback_when_ok(self):
        ctrl = DeploymentController(_relaxed_config())
        ctrl.register_agent("BTC_HOURLY")
        ctrl.promote_to_live("BTC_HOURLY")
        reason = ctrl.check_auto_rollback("BTC_HOURLY", profit_factor=1.5, drawdown_pct=3.0)
        assert reason is None
        assert ctrl.get_mode("BTC_HOURLY") == AgentMode.LIVE

    def test_no_rollback_for_paper_agent(self):
        ctrl = DeploymentController(_relaxed_config())
        ctrl.register_agent("BTC_HOURLY")
        reason = ctrl.check_auto_rollback("BTC_HOURLY", profit_factor=0.5)
        assert reason is None


# ── Trade recording ──────────────────────────────────────────────────

class TestTradeRecording:
    def test_record_live_trade(self):
        ctrl = DeploymentController(_relaxed_config())
        ctrl.register_agent("BTC_HOURLY")
        ctrl.record_live_trade("BTC_HOURLY")
        ctrl.record_live_trade("BTC_HOURLY")
        assert ctrl._agents["BTC_HOURLY"].live_trades == 2

    def test_record_shadow_trade(self):
        ctrl = DeploymentController(_relaxed_config())
        ctrl.register_agent("BTC_HOURLY")
        ctrl.record_shadow_trade("BTC_HOURLY")
        assert ctrl._agents["BTC_HOURLY"].shadow_trades == 1


# ── Status ───────────────────────────────────────────────────────────

class TestStatus:
    def test_status_structure(self):
        ctrl = DeploymentController(_relaxed_config())
        ctrl.register_agent("BTC_HOURLY")
        ctrl.register_agent("ETH_HOURLY")
        ctrl.promote_to_live("BTC_HOURLY")
        status = ctrl.status()
        assert status["live_count"] == 1
        assert "BTC_HOURLY" in status["live"]
        assert "ETH_HOURLY" in status["paper"]
        assert status["total_agents"] == 2

    def test_transition_log(self):
        ctrl = DeploymentController(_relaxed_config())
        ctrl.register_agent("BTC_HOURLY")
        ctrl.promote_to_shadow("BTC_HOURLY")
        ctrl.promote_to_live("BTC_HOURLY")
        log = ctrl.transition_log
        assert len(log) == 2
        assert log[0]["to"] == "SHADOW"
        assert log[1]["to"] == "LIVE"


# ── AgentDeployment ──────────────────────────────────────────────────

class TestAgentDeployment:
    def test_to_dict(self):
        dep = AgentDeployment(agent_name="BTC_HOURLY", mode=AgentMode.LIVE)
        d = dep.to_dict()
        assert d["agent_name"] == "BTC_HOURLY"
        assert d["mode"] == "LIVE"


# ── TransitionLog ────────────────────────────────────────────────────

class TestTransitionLog:
    def test_to_dict(self):
        entry = TransitionLog(
            ts="2026-02-16T00:00:00Z",
            agent_name="BTC_HOURLY",
            from_mode="PAPER",
            to_mode="LIVE",
            reason="test",
        )
        d = entry.to_dict()
        assert d["agent"] == "BTC_HOURLY"
        assert d["from"] == "PAPER"
        assert d["to"] == "LIVE"
