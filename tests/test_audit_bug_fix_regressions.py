"""test_audit_bug_fix_regressions.py

Regression tests for all 14 bugs fixed in the agent lifecycle / promotion audit.

BUG-1   SwarmSpawner bypasses lifecycle gates — quarantine spawned children
BUG-2   AutoPromoter promotes to LIVE without gauntlet or PromotionEngine check
BUG-3   Gauntlet verdict not persisted and not version-stamped (config_hash)
BUG-4   Gauntlet PnL model nonsensical — Sharpe always passes
BUG-5   is_agent_promoted() never called in pre_trade_check()
BUG-6   DeploymentController state lost on process restart
BUG-7   validate_before_lift() not enforced before LIVE promotion
BUG-8   promote_to_live() skips SHADOW stage when called from PAPER state
BUG-9   ExecutionGuard fail-open in paper mode allows ungated paper trading
MED-m1  PromotionEngine singleton shared across all agents
MED-m2  AutoRollback silently disabled when metrics dict is empty
MED-m3  Minimum time in SHADOW mode not enforced
MED-m4  bootstrap_canonical_agents auto-runs on import
MED-m5  AutoPromoter re-promotes immediately after rollback (no cooldown)

Run with:
    pytest tests/test_audit_bug_fix_regressions.py -v
"""
from __future__ import annotations

import json
import logging
import sys
import time
import types
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import os

import pytest

# ---------------------------------------------------------------------------
# Minimal utils.logger stub — keeps imports clean for modules that use it
# ---------------------------------------------------------------------------
if "utils.logger" not in sys.modules:
    import contextvars as _cv
    _ul = types.ModuleType("utils.logger")
    _ul.get_logger = logging.getLogger  # type: ignore[attr-defined]
    _ul.correlation_id_var = _cv.ContextVar("correlation_id", default=None)
    _ul.get_correlation_id = lambda: None
    _ul.set_correlation_id = lambda cid: None
    sys.modules["utils.logger"] = _ul


# ===========================================================================
# BUG-1: SwarmSpawner quarantines newly spawned children
# ===========================================================================
class TestBug1SwarmSpawnerQuarantine:
    """Spawned children must go to quarantine, not _active_agents."""

    def _make_spawner(self):
        from swarm.spawner import SwarmSpawner
        from swarm.performance import SwarmPerformanceLedger
        ledger = MagicMock(spec=SwarmPerformanceLedger)
        ledger.leaderboard.return_value = []
        ledger.best_parent.return_value = None
        return SwarmSpawner(ledger)

    def _make_agent(self, agent_id: str):
        agent = MagicMock()
        agent.agent_id = agent_id
        agent.model_name = "test"
        agent.trust = 1.0
        agent.__class__ = type(agent_id, (), {})
        return agent

    def test_refresh_population_spawned_child_not_in_active(self):
        """After refresh_population(), spawned children must be in quarantine not _active."""
        from swarm.spawner import SwarmSpawner
        from swarm.performance import SwarmPerformanceLedger

        ledger = MagicMock(spec=SwarmPerformanceLedger)
        ledger.leaderboard.return_value = []
        # best_parent returns the parent so a child gets spawned
        ledger.best_parent.return_value = {"agent_id": "parent-001", "score": 0.9}

        spawner = SwarmSpawner(ledger, max_population=10)
        parent = self._make_agent("parent-001")
        spawner.bootstrap([parent])

        initial_active = len(spawner._active_agents)

        with patch("core.time_authority.current_time", return_value={"utc_iso": "2026-01-01T00:00:00Z"}):
            spawner.refresh_population()

        # No new agent in _active_agents (spawned child is quarantined)
        assert len(spawner._active_agents) == initial_active, (
            f"Spawned child must NOT be in _active_agents; active count changed "
            f"from {initial_active} to {len(spawner._active_agents)}. BUG-1 may have regressed."
        )
        # But it must be in quarantine
        assert len(spawner._quarantine) == 1, (
            f"Spawned child must be in _quarantine; found {len(spawner._quarantine)}. "
            "BUG-1 may have regressed."
        )

    def test_spawned_child_trust_reset_to_zero(self):
        """_spawn_child must set child.trust = 0.0 (not inheriting parent trust)."""
        spawner = self._make_spawner()
        parent = self._make_agent("parent-trust")
        parent.trust = 0.99  # high parent trust

        with patch("core.time_authority.current_time", return_value={"utc_iso": "2026-01-01T00:00:00Z"}):
            child = spawner._spawn_child(parent)

        assert child.trust == 0.0, (
            f"Spawned child trust must be reset to 0.0, got {child.trust}. BUG-1 regressed."
        )

    def test_clear_gauntlet_pass_marks_child_for_release(self):
        """clear_gauntlet_pass() must set gauntlet_passed=True on the record."""
        from swarm.spawner import QuarantineRecord
        spawner = self._make_spawner()
        spawner._quarantine["child-q"] = QuarantineRecord(
            agent_id="child-q",
            parent_id="parent-p",
            quarantined_at="2026-01-01T00:00:00Z",
        )

        result = spawner.clear_gauntlet_pass("child-q", "verdict-001")

        assert result is True
        assert spawner._quarantine["child-q"].gauntlet_passed is True, (
            "clear_gauntlet_pass must set gauntlet_passed=True. BUG-1 regressed."
        )

    def test_release_quarantined_requires_gauntlet_pass(self):
        """_release_quarantined must NOT release a child whose gauntlet hasn't passed."""
        from swarm.spawner import QuarantineRecord
        spawner = self._make_spawner()
        agent = self._make_agent("child-notpassed")
        spawner._quarantine["child-notpassed"] = QuarantineRecord(
            agent_id="child-notpassed",
            parent_id="parent-p",
            quarantined_at="2026-01-01T00:00:00Z",
            gauntlet_passed=False,   # not yet cleared
        )
        spawner._quarantine_agents["child-notpassed"] = agent

        released = spawner._release_quarantined()

        assert len(released) == 0, (
            "_release_quarantined must not release agents without gauntlet PASS. BUG-1 regressed."
        )
        assert "child-notpassed" in spawner._quarantine, "Non-cleared agent must stay in quarantine"

    def test_bootstrap_is_idempotent(self):
        """Calling bootstrap() twice must not duplicate agents."""
        spawner = self._make_spawner()
        agents = [self._make_agent(f"boot-{i}") for i in range(3)]

        with patch("core.time_authority.current_time", return_value={"utc_iso": "2026-01-01T00:00:00Z"}):
            spawner.bootstrap(agents)
            count_after_first = len(spawner._active_agents)
            spawner.bootstrap(agents)  # second call — should be no-op

        assert len(spawner._active_agents) == count_after_first, (
            "bootstrap() must be idempotent — second call must not duplicate agents."
        )


# ===========================================================================
# BUG-2: AutoPromoter must gate LIVE promotion through gauntlet + PromotionEngine
# ===========================================================================
class TestBug2AutoPromoterGates:
    """AutoPromoter.evaluate() must consult gauntlet verdict and PromotionEngine."""

    def _make_promoter(self):
        from merid.event_venues.kalshi.auto_promoter import AutoPromoter
        ap = AutoPromoter.__new__(AutoPromoter)
        ap._interval = 60.0
        ap._on_transition = None
        ap._running = False
        ap._task = None
        ap._eval_history = []
        ap._max_history = 500
        ap._last_eval_ts = 0.0
        ap._eval_count = 0
        ap._last_rollback_ts = {}
        return ap

    def test_check_gauntlet_verdict_fails_when_no_grid(self):
        """_check_gauntlet_verdict must return (False, ...) when grid is unavailable."""
        ap = self._make_promoter()
        with patch("merid.prediction.agent_grid.get_agent_grid", side_effect=RuntimeError("no grid")):
            ok, reason = ap._check_gauntlet_verdict("test-agent")
        assert ok is False
        assert reason  # must have a reason string

    def test_check_promotion_engine_live_fails_closed_on_error(self):
        """_check_promotion_engine_live must return (False, ...) when engine unavailable."""
        ap = self._make_promoter()
        with patch(
            "merid.risk.promotion_engine.get_promotion_engine",
            side_effect=ImportError("no engine"),
        ):
            ok, reason = ap._check_promotion_engine_live("test-agent")
        assert ok is False, (
            "_check_promotion_engine_live must fail CLOSED when engine unavailable. "
            "BUG-2 may have regressed."
        )

    def test_check_promotion_engine_live_passes_when_can_go_live(self):
        """_check_promotion_engine_live must return (True, ...) when engine allows live."""
        ap = self._make_promoter()
        mock_engine = MagicMock()
        mock_engine.can_go_live.return_value = True
        with patch(
            "merid.risk.promotion_engine.get_promotion_engine",
            return_value=mock_engine,
        ):
            ok, reason = ap._check_promotion_engine_live("test-agent")
        assert ok is True
        assert "ok" in reason

    def test_check_promotion_engine_live_blocked_when_phase_disallows(self):
        """_check_promotion_engine_live must return (False, ...) when phase blocks live."""
        ap = self._make_promoter()
        mock_engine = MagicMock()
        mock_engine.can_go_live.return_value = False
        mock_engine.current_phase.name = "PHASE_0"
        with patch(
            "merid.risk.promotion_engine.get_promotion_engine",
            return_value=mock_engine,
        ):
            ok, reason = ap._check_promotion_engine_live("test-agent")
        assert ok is False
        assert "PHASE_0" in reason or "does_not_allow" in reason

    def test_evaluate_shadow_to_live_gates_include_gauntlet_and_engine(self):
        """_evaluate_shadow_to_live must include gauntlet_verdict and promotion_engine_live gates."""
        from merid.event_venues.kalshi.auto_promoter import AutoPromoter
        from merid.event_venues.kalshi.deployment import AgentDeployment, AgentMode, DeploymentConfig

        ap = self._make_promoter()

        dep = AgentDeployment(agent_name="test-agent", mode=AgentMode.SHADOW)
        dep.shadow_trades = 200

        ctrl = MagicMock()
        ctrl.config = DeploymentConfig(
            min_shadow_trades_before_full_live=100,
            min_profit_factor=1.2,
            max_drawdown_pct=15.0,
        )
        ctrl.promote_to_live.return_value = (False, "blocked_by_test")

        metrics = {"profit_factor": 2.0, "max_drawdown_pct": 5.0}

        # Patch both gates to return False so we can verify they are called
        with patch.object(ap, "_check_gauntlet_verdict", return_value=(False, "no_verdict")) as mock_g, \
             patch.object(ap, "_check_promotion_engine_live", return_value=(False, "phase_blocked")) as mock_e:
            eval_ = ap._evaluate_shadow_to_live("test-agent", metrics, dep, ctrl)

        mock_g.assert_called_once_with("test-agent")
        mock_e.assert_called_once_with("test-agent")

        gate_names = [g.gate for g in eval_.gates]
        assert "gauntlet_verdict" in gate_names, (
            "gauntlet_verdict gate missing from _evaluate_shadow_to_live. BUG-2 regressed."
        )
        assert "promotion_engine_live" in gate_names, (
            "promotion_engine_live gate missing from _evaluate_shadow_to_live. BUG-2 regressed."
        )


# ===========================================================================
# BUG-3: Gauntlet verdict persisted with config_hash and verdict_id
# ===========================================================================
class TestBug3GauntletVerdictPersistence:

    def test_verdict_has_config_hash_field(self):
        from merid.agent_gauntlet import AgentGauntletVerdict
        v = AgentGauntletVerdict.__new__(AgentGauntletVerdict)
        assert hasattr(v, "config_hash"), "AgentGauntletVerdict must have config_hash field"

    def test_verdict_has_verdict_id_field(self):
        from merid.agent_gauntlet import AgentGauntletVerdict
        v = AgentGauntletVerdict.__new__(AgentGauntletVerdict)
        assert hasattr(v, "verdict_id"), "AgentGauntletVerdict must have verdict_id field"

    def test_verdict_has_timestamp_field(self):
        from merid.agent_gauntlet import AgentGauntletVerdict
        v = AgentGauntletVerdict.__new__(AgentGauntletVerdict)
        assert hasattr(v, "timestamp"), "AgentGauntletVerdict must have timestamp field"

    def test_persist_verdict_writes_jsonl(self, tmp_path):
        from merid.agent_gauntlet import AgentGauntletVerdict, GauntletResult, persist_verdict
        import merid.agent_gauntlet as gmod

        verdict_file = tmp_path / "verdicts.jsonl"
        old_path = gmod._VERDICT_LOG
        gmod._VERDICT_LOG = verdict_file
        try:
            v = AgentGauntletVerdict(
                agent_id="test-reg-agent",
                category="test",
                result=GauntletResult.PASS,
                config_hash="abc123",
                verdict_id="v-001",
                timestamp=time.time(),
            )

            persist_verdict(v)

            assert verdict_file.exists(), "persist_verdict must create the JSONL file"
            lines = verdict_file.read_text().strip().splitlines()
            assert len(lines) == 1
            record = json.loads(lines[0])
            assert record["agent_id"] == "test-reg-agent"
            assert record["config_hash"] == "abc123"
            assert record["verdict_id"] == "v-001"
        finally:
            gmod._VERDICT_LOG = old_path

    def test_load_latest_verdict_returns_matching_hash(self, tmp_path):
        from merid.agent_gauntlet import AgentGauntletVerdict, GauntletResult, persist_verdict, load_latest_verdict
        import merid.agent_gauntlet as gmod

        verdict_file = tmp_path / "verdicts.jsonl"
        old_path = gmod._VERDICT_LOG
        gmod._VERDICT_LOG = verdict_file
        try:
            v = AgentGauntletVerdict(
                agent_id="load-test-agent",
                category="test",
                result=GauntletResult.PASS,
                config_hash="hash99",
                verdict_id="v-load-001",
                timestamp=time.time(),
                promoted=True,
            )
            persist_verdict(v)

            loaded = load_latest_verdict("load-test-agent", "hash99")
            assert loaded is not None, "load_latest_verdict must return the persisted verdict"
            # load_latest_verdict returns AgentGauntletVerdict, not a dict
            assert loaded.config_hash == "hash99"
            assert loaded.result == GauntletResult.PASS
        finally:
            gmod._VERDICT_LOG = old_path

    def test_load_latest_verdict_wrong_hash_returns_none(self, tmp_path):
        from merid.agent_gauntlet import AgentGauntletVerdict, GauntletResult, persist_verdict, load_latest_verdict
        import merid.agent_gauntlet as gmod

        verdict_file = tmp_path / "verdicts.jsonl"
        old_path = gmod._VERDICT_LOG
        gmod._VERDICT_LOG = verdict_file
        try:
            v = AgentGauntletVerdict(
                agent_id="hash-mismatch-agent",
                category="test",
                result=GauntletResult.PASS,
                config_hash="correct-hash",
                verdict_id="v-002",
                timestamp=time.time(),
            )
            persist_verdict(v)

            loaded = load_latest_verdict("hash-mismatch-agent", "WRONG-hash")
            assert loaded is None, (
                "load_latest_verdict must return None when config_hash does not match"
            )
        finally:
            gmod._VERDICT_LOG = old_path

    def test_has_valid_gauntlet_pass_false_when_no_verdict(self, tmp_path):
        from merid.agent_gauntlet import has_valid_gauntlet_pass
        import merid.agent_gauntlet as gmod

        old_path = gmod._VERDICT_LOG
        gmod._VERDICT_LOG = tmp_path / "empty.jsonl"
        try:
            valid, reason = has_valid_gauntlet_pass("nonexistent-agent", "anyhash")
            assert valid is False
        finally:
            gmod._VERDICT_LOG = old_path

    def test_compute_agent_config_hash_is_deterministic(self):
        from merid.agent_gauntlet import _compute_agent_config_hash
        agent = MagicMock()
        agent.__class__ = type("TestAgent", (), {})
        h1 = _compute_agent_config_hash(agent)
        h2 = _compute_agent_config_hash(agent)
        assert h1 == h2, "Config hash must be deterministic for the same agent class"
        assert len(h1) == 16, "Config hash must be 16 hex chars (SHA256[:16])"


# ===========================================================================
# BUG-4: Gauntlet PnL model — Sharpe floor is 0.0, not -1.0
# ===========================================================================
class TestBug4GauntletPnLModel:

    def test_sharpe_threshold_floor_is_zero(self):
        """GauntletSLO default min_sharpe_ratio must be 0.0 (not negative)."""
        from merid.agent_gauntlet import GauntletSLO
        slo = GauntletSLO()
        assert slo.min_sharpe_ratio >= 0.0, (
            f"GauntletSLO.min_sharpe_ratio={slo.min_sharpe_ratio} must be ≥ 0.0. "
            "BUG-4 (Sharpe always passes) may have regressed."
        )

    def test_negative_sharpe_fails_gauntlet(self):
        """An agent with consistently negative returns must fail the Sharpe SLO."""
        from merid.agent_gauntlet import GauntletSLO, GauntletRunner, SLOCheck

        slo = GauntletSLO()  # min_sharpe_ratio=0.0
        runner = GauntletRunner.__new__(GauntletRunner)
        runner.slo = slo

        # Build fill mocks with alternating buy/sell to realize negative PnL
        def make_fill(side, price, notional=10.0, instr="BTC"):
            f = MagicMock()
            f.instrument_id = instr
            f.side = MagicMock(value=side)
            f.notional_usd = notional
            f.price = price
            return f

        # Use varying loss amounts so stdev > 0 → sharpe is well-defined and negative
        fills = []
        losses = [5.0, 10.0, 15.0, 8.0, 12.0, 7.0, 14.0, 9.0, 11.0, 6.0]
        for i, loss in enumerate(losses):
            buy_price = 100.0
            sell_price = buy_price - loss
            fills.append(make_fill("buy",  price=buy_price, notional=buy_price, instr=f"X{i}"))
            fills.append(make_fill("sell", price=sell_price, notional=sell_price, instr=f"X{i}"))

        metrics = runner._compute_pnl_metrics(fills)
        assert metrics["sharpe_ratio"] < 0.0, (
            f"Negative returns must produce negative sharpe_ratio (got {metrics['sharpe_ratio']:.4f}). "
            "BUG-4 may have regressed."
        )

        # Verify SLO check fails
        checks = runner._evaluate_slos(
            slo=slo,
            total_cycles=len(fills),
            successful=len(fills),
            errored=0,
            latencies=[50.0] * len(fills),
            confidences=[0.5] * len(fills),
            fills=fills,
            rejections=0,
            pnl_metrics=metrics,
        )
        sharpe_check = next((c for c in checks if "sharpe" in c.name.lower()), None)
        assert sharpe_check is not None, "sharpe SLO check must exist"
        assert sharpe_check.passed is False, (
            "Negative Sharpe must FAIL the Sharpe SLO. BUG-4 regressed."
        )

    def test_positive_pnl_stream_produces_positive_sharpe(self):
        """Consistent positive returns must produce positive sharpe_ratio."""
        from merid.agent_gauntlet import GauntletRunner

        runner = GauntletRunner.__new__(GauntletRunner)

        def make_fill(side, price, notional=10.0, instr="ETH"):
            f = MagicMock()
            f.instrument_id = instr
            f.side = MagicMock(value=side)
            f.notional_usd = notional
            f.price = price
            return f

        # buy low, sell high × 10
        fills = []
        for _ in range(10):
            fills.append(make_fill("buy",  price=100.0, notional=100.0))
            fills.append(make_fill("sell", price=115.0, notional=115.0))

        metrics = runner._compute_pnl_metrics(fills)
        assert metrics["sharpe_ratio"] > 0.0, (
            "Consistently profitable trades must produce positive sharpe_ratio"
        )

    def test_empty_pnl_does_not_crash(self):
        """_compute_pnl_metrics must handle empty fills list gracefully."""
        from merid.agent_gauntlet import GauntletRunner

        runner = GauntletRunner.__new__(GauntletRunner)
        metrics = runner._compute_pnl_metrics([])
        assert "sharpe_ratio" in metrics, "sharpe_ratio key must be present in empty metrics"
        assert "max_drawdown_pct" in metrics, "max_drawdown_pct key must be present in empty metrics"


# ===========================================================================
# BUG-5: is_agent_promoted() called in pre_trade_check()
# ===========================================================================
class TestBug5AgentPromotionCheck:

    def test_pre_trade_check_blocks_unpromoted_live_agent(self):
        """pre_trade_check must block an agent not in the promotion report."""
        from merid.execution_guard import ExecutionGuard

        guard = ExecutionGuard()
        guard._init_ts = 0.0  # expire grace window
        guard._promotion_report_grace_s = 0.0
        guard._promotion_eligible_domains = {"crypto"}
        guard._promotion_blocked_agents = {"blocked-agent-01"}
        guard.enforce_promotion = True

        with patch(
            "merid.execution_guard.get_trading_mode_controller",
            return_value=MagicMock(is_live=True),
            create=True,
        ):
            verdict = guard.pre_trade_check(
                plan_id="p1",
                symbol="KXBTC-X",
                domain="crypto",
                size_usd=100.0,
                agent_id="blocked-agent-01",
            )

        assert not verdict.allowed, (
            "pre_trade_check must reject an unpromoted agent in live mode. "
            "BUG-5 may have regressed."
        )
        assert any("agent" in c.lower() or "promot" in c.lower()
                   for c in (verdict.checks_failed or [])), (
            "Rejection reason must reference agent promotion."
        )

    def test_pre_trade_check_allows_promoted_agent(self):
        """pre_trade_check must not reject a promoted agent on promotion grounds."""
        from merid.execution_guard import ExecutionGuard

        guard = ExecutionGuard()
        guard._init_ts = 0.0
        guard._promotion_report_grace_s = 0.0
        guard._promotion_eligible_domains = {"crypto"}
        guard._promotion_blocked_agents = set()  # no blocked agents
        guard.enforce_promotion = True
        guard._global_kill_switch = False

        verdict = guard.pre_trade_check(
            plan_id="p2",
            symbol="KXBTC-X",
            domain="crypto",
            size_usd=100.0,
            agent_id="good-agent-01",
        )

        # Should not be blocked by promotion check specifically
        assert not any(
            "agent" in c.lower() and "promot" in c.lower()
            for c in (verdict.checks_failed or [])
        )

    def test_pre_trade_check_accepts_agent_id_param(self):
        """pre_trade_check signature must accept agent_id parameter."""
        import inspect
        from merid.execution_guard import ExecutionGuard
        sig = inspect.signature(ExecutionGuard.pre_trade_check)
        assert "agent_id" in sig.parameters, (
            "pre_trade_check must have an agent_id parameter. BUG-5 regressed."
        )


# ===========================================================================
# BUG-6: DeploymentController state persists across restarts
# ===========================================================================
class TestBug6DeploymentStatePersistence:

    def _make_ctrl(self, state_file: Path):
        from merid.event_venues.kalshi.deployment import DeploymentController, DeploymentConfig
        cfg = DeploymentConfig(require_operator_ack_after_restart=False)
        ctrl = DeploymentController.__new__(DeploymentController)
        ctrl._config = cfg
        ctrl._agents = {}
        ctrl._log = []
        ctrl._state_file = state_file
        ctrl._restart_pending_ack = set()
        return ctrl

    def test_persist_and_reload_state(self, tmp_path):
        from merid.event_venues.kalshi.deployment import DeploymentController, DeploymentConfig, AgentMode
        import merid.event_venues.kalshi.deployment as dmod

        state_file = tmp_path / "deployment_state.json"
        old_state_file = dmod._STATE_FILE
        dmod._STATE_FILE = state_file
        try:
            cfg = DeploymentConfig(require_operator_ack_after_restart=False)
            ctrl = DeploymentController(config=cfg)

            dep = ctrl.register_agent("persist-agent")
            dep.mode = AgentMode.SHADOW
            dep.shadow_trades = 42
            ctrl._persist_state()

            assert state_file.exists(), "_persist_state must create the state file"

            # Reload in a fresh instance using same patched _STATE_FILE
            ctrl2 = DeploymentController(config=cfg)
            dep2 = ctrl2._agents.get("persist-agent")
            assert dep2 is not None, "Agent must be restored from persisted state"
            assert dep2.shadow_trades == 42, (
                f"shadow_trades must survive restart, got {dep2.shadow_trades}"
            )
        finally:
            dmod._STATE_FILE = old_state_file

    def test_live_agents_downgraded_to_paper_on_restart(self, tmp_path):
        """Agents persisted in LIVE mode must restart as PAPER (safe default)."""
        from merid.event_venues.kalshi.deployment import DeploymentController, DeploymentConfig, AgentMode
        import merid.event_venues.kalshi.deployment as dmod

        state_file = tmp_path / "deployment_state.json"
        # Write a state file with a LIVE agent directly
        state_data = {
            "agents": {"live-restart-agent": {
                "agent_name": "live-restart-agent",
                "mode": "LIVE",
                "promoted_at": None,
                "rollback_count": 0,
                "last_rollback_reason": None,
                "last_rollback_at": None,
                "live_trades": 500,
                "shadow_trades": 200,
            }},
            "log": [],
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        state_file.write_text(json.dumps(state_data))

        old_state_file = dmod._STATE_FILE
        dmod._STATE_FILE = state_file
        try:
            cfg = DeploymentConfig(require_operator_ack_after_restart=True)
            ctrl = DeploymentController(config=cfg)
            dep = ctrl._agents.get("live-restart-agent")
            assert dep is not None
            assert dep.mode == AgentMode.PAPER, (
                f"LIVE agent must restart as PAPER for safety; got {dep.mode}. "
                "BUG-6 may have regressed."
            )
        finally:
            dmod._STATE_FILE = old_state_file


# ===========================================================================
# BUG-7: validate_before_lift() enforced before LIVE promotion
# ===========================================================================
class TestBug7ValidateBeforeLift:

    def _make_ctrl(self, tmp_path: Path):
        from merid.event_venues.kalshi.deployment import DeploymentController, DeploymentConfig
        import merid.event_venues.kalshi.deployment as dmod

        cfg = DeploymentConfig(
            require_operator_ack_after_restart=False,
            min_shadow_trades_before_full_live=0,
            min_shadow_hours_before_full_live=0.0,
        )
        dmod._STATE_FILE = tmp_path / "state.json"
        ctrl = DeploymentController(config=cfg)
        return ctrl

    def test_promote_to_live_blocked_when_no_backtest_report(self, tmp_path):
        """promote_to_live must fail when get_latest_backtest_report returns None."""
        from merid.event_venues.kalshi.deployment import AgentMode

        ctrl = self._make_ctrl(tmp_path)
        dep = ctrl.register_agent("no-backtest-agent")
        dep.mode = AgentMode.SHADOW
        dep.shadow_trades = 500

        with patch(
            "merid.backtesting.kalshi_backtest.get_latest_backtest_report",
            return_value=None,
        ):
            ok, reason = ctrl.promote_to_live("no-backtest-agent")

        assert ok is False, (
            "promote_to_live must fail when no backtest report exists. "
            "BUG-7 may have regressed."
        )
        assert "backtest" in reason.lower() or "lift" in reason.lower(), (
            f"Rejection reason must mention backtest/lift gate, got: {reason}"
        )

    def test_promote_to_live_blocked_when_backtest_fails_validation(self, tmp_path):
        """promote_to_live must fail when validate_before_lift returns ok=False."""
        from merid.event_venues.kalshi.deployment import AgentMode
        from merid.risk.btc_promotion_config import BacktestReport

        ctrl = self._make_ctrl(tmp_path)
        dep = ctrl.register_agent("bad-backtest-agent")
        dep.mode = AgentMode.SHADOW
        dep.shadow_trades = 500

        bad_report = BacktestReport(
            equity_curve=[1.0, 0.5],
            returns=[-0.5],
            max_drawdown=0.5,   # > 30% threshold
            sharpe=-1.0,        # < 0.7 threshold
            trades=5,           # < 100 trades
            years=0.5,          # < 1 year
        )
        with patch(
            "merid.backtesting.kalshi_backtest.get_latest_backtest_report",
            return_value=bad_report,
        ):
            ok, reason = ctrl.promote_to_live("bad-backtest-agent")

        assert ok is False, (
            "promote_to_live must fail when backtest validation fails. BUG-7 regressed."
        )

    def test_promote_to_live_succeeds_with_valid_backtest(self, tmp_path):
        """promote_to_live must succeed when all gates pass."""
        from merid.event_venues.kalshi.deployment import AgentMode
        from merid.risk.btc_promotion_config import BacktestReport

        ctrl = self._make_ctrl(tmp_path)
        ctrl._config.max_live_agents = 10
        dep = ctrl.register_agent("good-backtest-agent")
        dep.mode = AgentMode.SHADOW
        dep.shadow_trades = 500

        good_report = BacktestReport(
            equity_curve=[1.0] + [1.0 + 0.01 * i for i in range(100)],
            returns=[0.01] * 100,
            max_drawdown=0.05,
            sharpe=1.5,
            trades=150,
            years=2.0,
        )
        with patch(
            "merid.backtesting.kalshi_backtest.get_latest_backtest_report",
            return_value=good_report,
        ):
            ok, reason = ctrl.promote_to_live(
                "good-backtest-agent",
                readiness={"ready": True},
            )

        assert ok is True, (
            f"promote_to_live must succeed with valid backtest; got reason={reason}"
        )


# ===========================================================================
# BUG-8: PAPER → LIVE direct path blocked; SHADOW stage required
# ===========================================================================
class TestBug8NoPaperToLiveDirectPromotion:

    def _make_ctrl(self, tmp_path: Path):
        from merid.event_venues.kalshi.deployment import DeploymentController, DeploymentConfig
        import merid.event_venues.kalshi.deployment as dmod
        cfg = DeploymentConfig(require_operator_ack_after_restart=False)
        dmod._STATE_FILE = tmp_path / "state.json"
        ctrl = DeploymentController(config=cfg)
        return ctrl

    def test_promote_paper_agent_to_live_is_rejected(self, tmp_path):
        """Agents in PAPER mode must not be promotable to LIVE directly."""
        from merid.event_venues.kalshi.deployment import AgentMode

        ctrl = self._make_ctrl(tmp_path)
        dep = ctrl.register_agent("paper-agent")
        assert dep.mode == AgentMode.PAPER

        ok, reason = ctrl.promote_to_live("paper-agent")

        assert ok is False, (
            "promote_to_live must reject a PAPER agent — SHADOW stage required. "
            "BUG-8 may have regressed."
        )
        assert "shadow" in reason.lower() or "paper" in reason.lower(), (
            f"Rejection reason must mention SHADOW requirement, got: {reason}"
        )

    def test_promote_halted_agent_to_live_is_rejected(self, tmp_path):
        """Agents in HALTED mode must not be promotable to LIVE directly."""
        from merid.event_venues.kalshi.deployment import AgentMode

        ctrl = self._make_ctrl(tmp_path)
        dep = ctrl.register_agent("halted-agent")
        dep.mode = AgentMode.HALTED

        ok, reason = ctrl.promote_to_live("halted-agent")

        assert ok is False, (
            "promote_to_live must reject a HALTED agent — SHADOW stage required."
        )

    def test_promote_to_shadow_succeeds_from_paper(self, tmp_path):
        """promote_to_shadow from PAPER must succeed (the correct path)."""
        from merid.event_venues.kalshi.deployment import AgentMode

        ctrl = self._make_ctrl(tmp_path)
        dep = ctrl.register_agent("shadow-candidate")

        ok, reason = ctrl.promote_to_shadow("shadow-candidate", readiness={"ready": True})

        assert ok is True, f"promote_to_shadow from PAPER must succeed, got: {reason}"
        assert dep.mode == AgentMode.SHADOW

    def test_full_paper_shadow_live_sequence(self, tmp_path):
        """PAPER → SHADOW → LIVE must be the only valid promotion sequence."""
        from merid.event_venues.kalshi.deployment import AgentMode
        from merid.risk.btc_promotion_config import BacktestReport

        ctrl = self._make_ctrl(tmp_path)
        ctrl._config.min_shadow_trades_before_full_live = 0
        ctrl._config.min_shadow_hours_before_full_live = 0.0
        ctrl._config.max_live_agents = 10
        dep = ctrl.register_agent("seq-agent")

        # Step 1: PAPER → SHADOW
        ok, _ = ctrl.promote_to_shadow("seq-agent", readiness={"ready": True})
        assert ok and dep.mode == AgentMode.SHADOW

        # Step 2: SHADOW → LIVE (with valid backtest)
        good_report = BacktestReport(
            equity_curve=[1.0 + 0.01 * i for i in range(150)],
            returns=[0.01] * 150,
            max_drawdown=0.05,
            sharpe=1.8,
            trades=150,
            years=2.0,
        )
        with patch(
            "merid.backtesting.kalshi_backtest.get_latest_backtest_report",
            return_value=good_report,
        ):
            ok2, reason2 = ctrl.promote_to_live("seq-agent", readiness={"ready": True})

        assert ok2 is True, f"SHADOW → LIVE must succeed with valid backtest, got: {reason2}"
        assert dep.mode == AgentMode.LIVE


# ===========================================================================
# BUG-9: ExecutionGuard fail-open in paper mode has a grace window
# ===========================================================================
class TestBug9ExecutionGuardGraceWindow:

    def test_guard_has_init_ts_attribute(self):
        """ExecutionGuard must have _init_ts set at construction time."""
        from merid.execution_guard import ExecutionGuard
        guard = ExecutionGuard()
        assert hasattr(guard, "_init_ts"), "ExecutionGuard must have _init_ts. BUG-9 regressed."
        assert hasattr(guard, "_promotion_report_grace_s"), (
            "ExecutionGuard must have _promotion_report_grace_s"
        )

    def test_guard_allows_paper_within_grace_window(self):
        """Paper-mode domain check must be allowed within the grace window."""
        from merid.execution_guard import ExecutionGuard
        guard = ExecutionGuard()
        # Manually reset to simulate 'no report loaded yet' state
        # (sync_promotion_report in __init__ may have set an empty set; force None)
        guard._promotion_eligible_domains = None
        guard._promotion_blocked_agents = None
        guard._promotion_report_ts = 0.0
        guard._init_ts = time.time()  # just started — within grace
        guard._promotion_report_grace_s = 300.0  # 5 min grace

        # Patch sync so it does nothing (simulates no report file available)
        def _noop_sync(self_inner=None):
            pass  # do NOT update _promotion_eligible_domains

        _live_false = MagicMock()
        _live_false.is_live = False
        with patch.object(guard, "sync_promotion_report", side_effect=_noop_sync), \
             patch("merid.execution_guard.get_trading_mode_controller", return_value=_live_false, create=True), \
             patch("trading.mode_controller.get_trading_mode_controller", return_value=_live_false, create=True):
            result = guard.is_domain_promoted("crypto")

        assert result is True, (
            "Paper trading within grace window must be allowed. BUG-9 regressed."
        )

    def test_guard_blocks_paper_after_grace_window_expires(self):
        """Paper-mode domain check must be blocked after grace window + no report."""
        from merid.execution_guard import ExecutionGuard
        guard = ExecutionGuard()
        guard._promotion_eligible_domains = None
        guard._promotion_blocked_agents = None
        guard._init_ts = time.time() - 600.0  # started 10 min ago
        guard._promotion_report_grace_s = 300.0  # only 5 min grace
        guard._promotion_report_ts = 0.0

        # Patch sync so it does nothing (simulates persistent no-report condition)
        def _noop_sync(self_inner=None):
            pass

        with patch.object(guard, "sync_promotion_report", side_effect=_noop_sync):
            result = guard.is_domain_promoted("crypto")

        assert result is False, (
            "Paper trading must be blocked after grace window expires with no report. "
            "BUG-9 (permanent fail-open) may have regressed."
        )

    def test_is_agent_promoted_blocks_post_grace_no_report(self):
        """is_agent_promoted must return False post-grace when no report exists."""
        from merid.execution_guard import ExecutionGuard
        guard = ExecutionGuard()
        guard._promotion_blocked_agents = None
        guard._init_ts = time.time() - 600.0
        guard._promotion_report_grace_s = 300.0

        result = guard.is_agent_promoted("some-agent")
        assert result is False, (
            "is_agent_promoted must be False post-grace with no report. BUG-9 regressed."
        )

    def test_is_agent_promoted_allows_within_grace(self):
        """is_agent_promoted must return True within grace window."""
        from merid.execution_guard import ExecutionGuard
        guard = ExecutionGuard()
        guard._promotion_blocked_agents = None
        guard._init_ts = time.time()
        guard._promotion_report_grace_s = 300.0

        result = guard.is_agent_promoted("some-agent")
        assert result is True, (
            "is_agent_promoted must be True within grace window."
        )

    def test_grace_window_configurable_via_env(self, monkeypatch):
        """MERID_PROMOTION_GRACE_S env var must set the grace window."""
        monkeypatch.setenv("MERID_PROMOTION_GRACE_S", "60")
        from merid.execution_guard import ExecutionGuard
        guard = ExecutionGuard()
        assert guard._promotion_report_grace_s == 60.0, (
            f"Grace window must respect MERID_PROMOTION_GRACE_S, got {guard._promotion_report_grace_s}"
        )


# ===========================================================================
# MED-m1: PromotionEngine per-agent registry (not a global singleton)
# ===========================================================================
class TestMedM1PerAgentPromotionEngine:

    def test_different_agent_ids_get_different_engines(self):
        from merid.risk.promotion_engine import get_promotion_engine, reset_promotion_engine

        reset_promotion_engine("reg-agent-A")
        reset_promotion_engine("reg-agent-B")

        engine_a = get_promotion_engine("reg-agent-A")
        engine_b = get_promotion_engine("reg-agent-B")

        assert engine_a is not engine_b, (
            "Different agent IDs must return different PromotionEngine instances. "
            "MED-m1 may have regressed."
        )

    def test_same_agent_id_returns_same_engine(self):
        from merid.risk.promotion_engine import get_promotion_engine, reset_promotion_engine

        reset_promotion_engine("stable-agent-X")
        e1 = get_promotion_engine("stable-agent-X")
        e2 = get_promotion_engine("stable-agent-X")

        assert e1 is e2, "Same agent ID must always return the same engine instance"

    def test_no_arg_call_uses_global_key(self):
        from merid.risk.promotion_engine import get_promotion_engine, _GLOBAL_AGENT_KEY

        engine = get_promotion_engine()
        engine2 = get_promotion_engine(_GLOBAL_AGENT_KEY)
        assert engine is engine2, "No-arg call must use __global__ sentinel key"

    def test_reset_removes_engine(self):
        from merid.risk.promotion_engine import get_promotion_engine, reset_promotion_engine

        e1 = get_promotion_engine("reset-test-agent")
        reset_promotion_engine("reset-test-agent")
        e2 = get_promotion_engine("reset-test-agent")

        assert e1 is not e2, "reset_promotion_engine must cause a new engine to be created"

    def test_phase_state_independent_between_agents(self):
        """Promoting engine-A to PHASE_1 must not affect engine-B."""
        from merid.risk.promotion_engine import (
            get_promotion_engine, reset_promotion_engine, PerformanceSnapshot,
        )
        import datetime

        reset_promotion_engine("ind-agent-A")
        reset_promotion_engine("ind-agent-B")

        ea = get_promotion_engine("ind-agent-A")
        eb = get_promotion_engine("ind-agent-B")

        # Aggressively promote agent-A
        perf = PerformanceSnapshot(
            equity=100_000, max_drawdown=0.01, sharpe=3.0,
            total_trades=1000,
            first_live_date=datetime.date.today() - datetime.timedelta(days=365),
        )
        for _ in range(5):
            ea.maybe_promote(perf)

        # Agent-B should still be at PHASE_0
        assert eb.current_phase.name == "PHASE_0", (
            f"Promoting engine-A must not change engine-B phase. "
            f"Got {eb.current_phase.name}. MED-m1 regressed."
        )


# ===========================================================================
# MED-m2: AutoRollback fail-safe for empty metrics
# ===========================================================================
class TestMedM2AutoRollbackFailSafe:

    def _make_promoter(self):
        from merid.event_venues.kalshi.auto_promoter import AutoPromoter
        ap = AutoPromoter.__new__(AutoPromoter)
        ap._interval = 60.0
        ap._on_transition = None
        ap._running = False
        ap._task = None
        ap._eval_history = []
        ap._max_history = 500
        ap._last_eval_ts = 0.0
        ap._eval_count = 0
        ap._last_rollback_ts = {}
        return ap

    def test_empty_metrics_for_live_agent_triggers_rollback(self):
        """Empty metrics for a LIVE agent must trigger fail-safe rollback, not silent skip."""
        from merid.event_venues.kalshi.deployment import (
            DeploymentController, DeploymentConfig, AgentDeployment, AgentMode
        )

        ap = self._make_promoter()

        dep = AgentDeployment(agent_name="live-no-metrics", mode=AgentMode.LIVE)
        ctrl = MagicMock(spec=DeploymentController)
        ctrl.config = DeploymentConfig()
        ctrl.register_agent.return_value = dep

        fired = []

        def on_transition(agent, from_, to, reason):
            fired.append((agent, from_, to, reason))

        ap._on_transition = on_transition

        with patch.object(ap, "_collect_agent_metrics", return_value={"live-no-metrics": {}}), \
             patch("merid.event_venues.kalshi.deployment.get_deployment_controller", return_value=ctrl), \
             patch("merid.event_venues.kalshi.auto_promoter.get_deployment_controller", return_value=ctrl, create=True):
            import asyncio
            asyncio.run(ap._evaluate_all())

        ctrl.rollback.assert_called_once()
        assert any("live-no-metrics" in str(t) for t in fired), (
            "Empty metrics for LIVE agent must trigger rollback and fire transition. "
            "MED-m2 may have regressed."
        )

    def test_empty_metrics_for_shadow_agent_triggers_rollback(self):
        """Empty metrics for a SHADOW agent must also trigger fail-safe rollback."""
        from merid.event_venues.kalshi.deployment import (
            DeploymentController, DeploymentConfig, AgentDeployment, AgentMode
        )

        ap = self._make_promoter()

        dep = AgentDeployment(agent_name="shadow-no-metrics", mode=AgentMode.SHADOW)
        ctrl = MagicMock(spec=DeploymentController)
        ctrl.config = DeploymentConfig()
        ctrl.register_agent.return_value = dep

        with patch.object(ap, "_collect_agent_metrics", return_value={"shadow-no-metrics": {}}), \
             patch("merid.event_venues.kalshi.deployment.get_deployment_controller", return_value=ctrl), \
             patch("merid.event_venues.kalshi.auto_promoter.get_deployment_controller", return_value=ctrl, create=True):
            import asyncio
            asyncio.run(ap._evaluate_all())

        ctrl.rollback.assert_called_once()


# ===========================================================================
# MED-m3: Minimum time in SHADOW mode enforced
# ===========================================================================
class TestMedM3MinShadowTime:

    def _make_ctrl(self, tmp_path: Path, min_hours: float = 48.0):
        from merid.event_venues.kalshi.deployment import DeploymentController, DeploymentConfig
        import merid.event_venues.kalshi.deployment as dmod
        cfg = DeploymentConfig(
            require_operator_ack_after_restart=False,
            min_shadow_trades_before_full_live=0,
            min_shadow_hours_before_full_live=min_hours,
            max_live_agents=10,
        )
        dmod._STATE_FILE = tmp_path / "state.json"
        ctrl = DeploymentController(config=cfg)
        return ctrl

    def test_promote_blocked_if_shadow_time_insufficient(self, tmp_path):
        """SHADOW → LIVE must be blocked if minimum shadow wall-clock hours not met."""
        from merid.event_venues.kalshi.deployment import AgentMode
        from merid.risk.btc_promotion_config import BacktestReport

        ctrl = self._make_ctrl(tmp_path, min_hours=48.0)
        dep = ctrl.register_agent("young-shadow-agent")
        dep.mode = AgentMode.SHADOW
        dep.shadow_trades = 1000
        # promoted_at is right now → 0 hours in shadow
        dep.promoted_at = datetime.now(timezone.utc).isoformat()

        good_report = BacktestReport(
            equity_curve=[1.0 + 0.01 * i for i in range(150)],
            returns=[0.01] * 150,
            max_drawdown=0.05,
            sharpe=1.5,
            trades=150,
            years=2.0,
        )
        with patch(
            "merid.backtesting.kalshi_backtest.get_latest_backtest_report",
            return_value=good_report,
        ):
            ok, reason = ctrl.promote_to_live("young-shadow-agent", readiness={"ready": True})

        assert ok is False, (
            "SHADOW → LIVE must fail when minimum shadow time has not elapsed. "
            "MED-m3 may have regressed."
        )
        assert "shadow" in reason.lower() or "hour" in reason.lower() or "time" in reason.lower(), (
            f"Rejection must mention shadow time requirement, got: {reason}"
        )

    def test_promote_succeeds_after_sufficient_shadow_time(self, tmp_path):
        """SHADOW → LIVE must succeed when min hours have elapsed."""
        from merid.event_venues.kalshi.deployment import AgentMode
        from merid.risk.btc_promotion_config import BacktestReport

        ctrl = self._make_ctrl(tmp_path, min_hours=0.001)  # tiny threshold
        dep = ctrl.register_agent("mature-shadow-agent")
        dep.mode = AgentMode.SHADOW
        dep.shadow_trades = 1000
        dep.promoted_at = (
            datetime.now(timezone.utc) - timedelta(hours=1)
        ).isoformat()

        good_report = BacktestReport(
            equity_curve=[1.0 + 0.01 * i for i in range(150)],
            returns=[0.01] * 150,
            max_drawdown=0.05,
            sharpe=1.5,
            trades=150,
            years=2.0,
        )
        with patch(
            "merid.backtesting.kalshi_backtest.get_latest_backtest_report",
            return_value=good_report,
        ):
            ok, reason = ctrl.promote_to_live("mature-shadow-agent", readiness={"ready": True})

        assert ok is True, (
            f"SHADOW → LIVE must succeed when time threshold is met, got: {reason}"
        )


# ===========================================================================
# MED-m4: bootstrap_canonical_agents does NOT auto-run on import
# ===========================================================================
class TestMedM4BootstrapNotOnImport:

    def test_import_does_not_call_bootstrap(self):
        """Importing bootstrap module must not call bootstrap_canonical_agents()."""
        import importlib
        import merid.agents.bootstrap as mod

        with patch.object(mod, "bootstrap_canonical_agents") as mock_bootstrap:
            importlib.reload(mod)
            mock_bootstrap.assert_not_called(), (
                "bootstrap_canonical_agents must not be called on import. "
                "MED-m4 may have regressed."
            )

    def test_ensure_bootstrapped_is_idempotent(self):
        """ensure_bootstrapped() called twice must register agents only once."""
        import merid.agents.bootstrap as mod

        mod._bootstrapped = False
        call_count = []

        original = mod.bootstrap_canonical_agents

        def counting_bootstrap():
            call_count.append(1)
            return original()

        with patch.object(mod, "bootstrap_canonical_agents", side_effect=counting_bootstrap):
            mod.ensure_bootstrapped()
            mod.ensure_bootstrapped()  # second call

        assert len(call_count) == 1, (
            f"bootstrap_canonical_agents must be called exactly once; called {len(call_count)} times. "
            "MED-m4 idempotency regressed."
        )

    def test_new_agents_start_inactive(self):
        """Agents registered via bootstrap_canonical_agents must start with is_active=False."""
        import inspect
        import merid.agents.bootstrap as mod
        source = inspect.getsource(mod.bootstrap_canonical_agents)
        assert "is_active" in source and "False" in source, (
            "bootstrap_canonical_agents must set is_active=False on new agents. "
            "MED-m4 regressed."
        )


# ===========================================================================
# MED-m5: AutoPromoter rollback cooldown prevents immediate re-promotion
# ===========================================================================
class TestMedM5RollbackCooldown:

    def _make_promoter(self):
        from merid.event_venues.kalshi.auto_promoter import AutoPromoter
        ap = AutoPromoter.__new__(AutoPromoter)
        ap._interval = 60.0
        ap._on_transition = None
        ap._running = False
        ap._task = None
        ap._eval_history = []
        ap._max_history = 500
        ap._last_eval_ts = 0.0
        ap._eval_count = 0
        ap._last_rollback_ts = {}
        return ap

    def test_in_rollback_cooldown_true_immediately_after_rollback(self):
        ap = self._make_promoter()
        ap._record_rollback_ts("agent-cool")
        assert ap._in_rollback_cooldown("agent-cool") is True, (
            "_in_rollback_cooldown must be True immediately after rollback. "
            "MED-m5 may have regressed."
        )

    def test_in_rollback_cooldown_false_before_first_rollback(self):
        ap = self._make_promoter()
        assert ap._in_rollback_cooldown("agent-new") is False, (
            "_in_rollback_cooldown must be False for an agent with no rollback history."
        )

    def test_in_rollback_cooldown_false_after_window_expires(self):
        ap = self._make_promoter()
        # Simulate a rollback that happened far in the past
        ap._last_rollback_ts["agent-expired"] = time.time() - (ap._ROLLBACK_COOLDOWN_S + 1)
        assert ap._in_rollback_cooldown("agent-expired") is False, (
            "_in_rollback_cooldown must expire after ROLLBACK_COOLDOWN_S seconds."
        )

    def test_rollback_cooldown_blocks_paper_to_shadow_promotion(self):
        """AutoPromoter must skip PAPER→SHADOW if agent is in rollback cooldown."""
        from merid.event_venues.kalshi.deployment import AgentDeployment, AgentMode, DeploymentConfig

        ap = self._make_promoter()
        ap._record_rollback_ts("cooldown-agent")  # just rolled back

        dep = AgentDeployment(agent_name="cooldown-agent", mode=AgentMode.PAPER)
        ctrl = MagicMock()
        ctrl.config = DeploymentConfig()
        ctrl.register_agent.return_value = dep
        ctrl.get_all_deployments.return_value = {"cooldown-agent": dep}

        metrics = {"profit_factor": 9.9, "max_drawdown_pct": 0.1, "consecutive_losses": 0}

        evaluate_called = []
        original_eval = ap._evaluate_paper_to_shadow

        def spy_eval(*args, **kwargs):
            evaluate_called.append(True)
            return original_eval(*args, **kwargs)

        with patch.object(ap, "_collect_agent_metrics", return_value={"cooldown-agent": metrics}), \
             patch("merid.event_venues.kalshi.auto_promoter.get_deployment_controller", return_value=ctrl, create=True), \
             patch.object(ap, "_evaluate_paper_to_shadow", side_effect=spy_eval):
            import asyncio
            asyncio.run(ap._evaluate_all())

        assert len(evaluate_called) == 0, (
            "_evaluate_paper_to_shadow must not be called during rollback cooldown. "
            "MED-m5 regressed."
        )

    def test_rollback_cooldown_constant_is_at_least_1_hour(self):
        """Rollback cooldown must be at least 1 hour to prevent thrashing."""
        from merid.event_venues.kalshi.auto_promoter import AutoPromoter
        assert AutoPromoter._ROLLBACK_COOLDOWN_S >= 3600.0, (
            f"ROLLBACK_COOLDOWN_S={AutoPromoter._ROLLBACK_COOLDOWN_S} must be ≥3600s. "
            "MED-m5 protection is insufficient."
        )


# ===========================================================================
# Integration: BacktestReport persistence helpers
# ===========================================================================
class TestBacktestReportPersistence:
    """Tests for save_backtest_report() / get_latest_backtest_report() (BUG-7 support)."""

    def test_save_and_load_backtest_report(self, tmp_path):
        from merid.backtesting.kalshi_backtest import save_backtest_report, get_latest_backtest_report
        from merid.risk.btc_promotion_config import BacktestReport
        import merid.backtesting.kalshi_backtest as kmod

        old_store = kmod._REPORT_STORE
        kmod._REPORT_STORE = tmp_path / "reports.json"
        try:
            report = BacktestReport(
                equity_curve=[1.0, 1.05, 1.1],
                returns=[0.05, 0.05],
                max_drawdown=0.03,
                sharpe=1.2,
                trades=200,
                years=2.0,
            )
            save_backtest_report("persistence-agent", report)

            loaded = get_latest_backtest_report("persistence-agent")
            assert loaded is not None
            assert loaded.trades == 200
            assert loaded.years == 2.0
            assert abs(loaded.sharpe - 1.2) < 1e-6
        finally:
            kmod._REPORT_STORE = old_store

    def test_get_latest_backtest_report_returns_none_when_missing(self, tmp_path):
        from merid.backtesting.kalshi_backtest import get_latest_backtest_report
        import merid.backtesting.kalshi_backtest as kmod

        old_store = kmod._REPORT_STORE
        kmod._REPORT_STORE = tmp_path / "empty.json"
        try:
            result = get_latest_backtest_report("nonexistent-agent")
            assert result is None
        finally:
            kmod._REPORT_STORE = old_store

    def test_save_overwrites_previous_report(self, tmp_path):
        from merid.backtesting.kalshi_backtest import save_backtest_report, get_latest_backtest_report
        from merid.risk.btc_promotion_config import BacktestReport
        import merid.backtesting.kalshi_backtest as kmod

        old_store = kmod._REPORT_STORE
        kmod._REPORT_STORE = tmp_path / "overwrite.json"
        try:
            r1 = BacktestReport(
                equity_curve=[1.0], returns=[], max_drawdown=0.1,
                sharpe=0.5, trades=50, years=1.0,
            )
            r2 = BacktestReport(
                equity_curve=[1.0, 1.5], returns=[0.5], max_drawdown=0.05,
                sharpe=1.8, trades=300, years=2.0,
            )
            save_backtest_report("overwrite-agent", r1)
            save_backtest_report("overwrite-agent", r2)

            loaded = get_latest_backtest_report("overwrite-agent")
            assert loaded.trades == 300, "Second save must overwrite the first"
        finally:
            kmod._REPORT_STORE = old_store
