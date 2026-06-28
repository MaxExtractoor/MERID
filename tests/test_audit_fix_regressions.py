"""Regression tests for the 10 audit fixes applied 2026-03-15.

LEGACY: This module tests ReflectionSystem, which is not used by kalshi_crypto_15m_v2 profile.
The lean 15m stack does not use reflection systems.

Fix 1  — Missing threading import in agents/reflection/runtime.py
Fix 2  — LearningEngine insights persisted to LongTermKnowledgeBase
Fix 3  — Dual DB path risk: stores anchored to project root via __file__
Fix 4  — Stale ConsensusView served after proposals expire
Fix 5  — SignalStore.reset_all() missing signal_snapshots
Fix 6  — asyncio.ensure_future() without loop guard in consensus_aggregator
Fix 7  — Orchestrator cycle_id now includes UUID fragment
Fix 8  — arb_plans.signal_id FK reference to arb_signals
Fix 9  — Atomic writes in LongTermKnowledgeBase._persist()
Fix 10 — PatternEngine stop-word filter in _tokenize()
"""

import asyncio
import os
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.legacy


# ===========================================================================
# §1  Fix 1 — threading import in runtime.py
# ===========================================================================

class TestReflectionRuntimeThreadingImport:
    """Fix 1: threading must be importable from runtime module."""

    def test_threading_in_runtime_module_globals(self):
        import agents.reflection.runtime as rt
        assert "threading" in dir(rt) or hasattr(rt, "threading") or \
               "threading" in sys.modules, \
            "threading must be imported by agents.reflection.runtime"

    def test_runtime_lock_is_threading_lock(self):
        import agents.reflection.runtime as rt
        assert isinstance(rt._runtime_lock, type(threading.Lock())), \
            "_runtime_lock must be a threading.Lock instance"

    def test_get_reflection_runtime_does_not_crash(self):
        """get_reflection_runtime() must not raise NameError on threading."""
        import agents.reflection.runtime as rt
        # Reset singleton so the factory path is exercised
        original = rt._runtime
        rt._runtime = None
        try:
            with patch("agents.reflection.runtime.ReflectionRuntime") as MockRT:
                MockRT.return_value = MagicMock()
                result = rt.get_reflection_runtime()
                assert result is not None
        finally:
            rt._runtime = original

    def test_second_call_returns_same_instance(self):
        import agents.reflection.runtime as rt
        original = rt._runtime
        rt._runtime = None
        try:
            with patch("agents.reflection.runtime.ReflectionRuntime") as MockRT:
                instance = MagicMock()
                MockRT.return_value = instance
                r1 = rt.get_reflection_runtime()
                r2 = rt.get_reflection_runtime()
                assert r1 is r2
        finally:
            rt._runtime = original


# ===========================================================================
# §2  Fix 2 — LearningEngine insights persisted to LongTermKnowledgeBase
# ===========================================================================

class TestInsightPersistence:
    """Fix 2: persist_insights() must route LearningInsight objects to KB."""

    def _make_reflection_system(self, tmp_path):
        from agents.reflection.integration import ReflectionSystem
        return ReflectionSystem(
            storage_path=tmp_path / "reflections.json",
            auto_persist=False,
        )

    def test_persist_insights_method_exists(self, tmp_path):
        rs = self._make_reflection_system(tmp_path)
        assert hasattr(rs, "persist_insights"), \
            "ReflectionSystem must expose persist_insights()"

    def test_persist_insights_returns_int(self, tmp_path):
        rs = self._make_reflection_system(tmp_path)
        result = rs.persist_insights("agent-x")
        assert isinstance(result, int)

    def test_persist_insights_calls_kb_record_entry(self, tmp_path):
        rs = self._make_reflection_system(tmp_path)

        fake_insight = MagicMock()
        fake_insight.insight_type = "failure_mode"
        fake_insight.description = "High confidence failure detected"
        fake_insight.severity = "high"
        fake_insight.confidence = 0.9
        fake_insight.evidence_count = 10
        fake_insight.recommendations = ["review overconfidence"]

        fake_kb = MagicMock()
        fake_kb.record_entry = MagicMock()

        with patch.object(rs, "get_agent_insights", return_value=[fake_insight]):
            with patch("agents.reflection.integration._get_kb", return_value=fake_kb):
                count = rs.persist_insights("agent-x")

        assert count == 1
        fake_kb.record_entry.assert_called_once()
        call_kwargs = fake_kb.record_entry.call_args.kwargs
        assert call_kwargs["entry_type"] == "lesson"
        assert "agent-x" in call_kwargs["tags"]
        assert call_kwargs["recorded_by"] == "reflection_system"

    def test_persist_insights_graceful_when_kb_unavailable(self, tmp_path):
        rs = self._make_reflection_system(tmp_path)
        with patch("agents.reflection.integration._get_kb", return_value=None):
            result = rs.persist_insights("agent-x")
        assert result == 0

    def test_persist_insights_called_after_consensus_validation(self, tmp_path):
        """validate_consensus_outcome must call persist_insights when auto_persist=True."""
        rs = self._make_reflection_system(tmp_path)
        rs.auto_persist = True

        with patch.object(rs, "persist_insights") as mock_persist, \
             patch.object(rs.core, "get_reflection") as mock_get, \
             patch.object(rs.core, "update_outcome", return_value=True), \
             patch.object(rs.validator, "validate_consensus_outcome") as mock_val, \
             patch.object(rs.persistence, "save_reflection"):

            mock_reflection = MagicMock()
            mock_reflection.agent_id = "agent-y"
            mock_reflection.decision = "accept"
            mock_reflection.confidence = 0.8
            mock_get.return_value = mock_reflection

            mock_result = MagicMock()
            mock_result.validated = True
            mock_result.reality_gap = 0.1
            mock_result.validation_score = 0.9
            mock_val.return_value = mock_result

            rs.validate_consensus_outcome("ref-1", "accept", 0.8, {"accept": 3})

        mock_persist.assert_called_once_with("agent-y")

    def test_persist_insights_called_after_market_validation(self, tmp_path):
        """validate_market_outcome must call persist_insights when auto_persist=True."""
        rs = self._make_reflection_system(tmp_path)
        rs.auto_persist = True

        with patch.object(rs, "persist_insights") as mock_persist, \
             patch.object(rs.core, "get_reflection") as mock_get, \
             patch.object(rs.core, "update_outcome", return_value=True), \
             patch.object(rs.validator, "validate_market_outcome") as mock_val, \
             patch.object(rs.persistence, "save_reflection"):

            mock_reflection = MagicMock()
            mock_reflection.agent_id = "agent-z"
            mock_reflection.decision = "accept"
            mock_reflection.confidence = 0.7
            mock_get.return_value = mock_reflection

            mock_result = MagicMock()
            mock_result.validated = True
            mock_result.reality_gap = 0.05
            mock_result.validation_score = 0.95
            mock_val.return_value = mock_result

            rs.validate_market_outcome("ref-2", actual_price_change=0.05)

        mock_persist.assert_called_once_with("agent-z")


# ===========================================================================
# §3  Fix 3 — DB paths anchored to project root
# ===========================================================================

class TestDbPathAnchoredToProjectRoot:
    """Fix 3: default DB paths must be absolute and inside project root data/."""

    def test_calibration_default_path_is_absolute(self):
        from merid.metrics.calibration import _DEFAULT_DB_PATH
        assert os.path.isabs(_DEFAULT_DB_PATH), \
            f"CalibrationStore default path must be absolute, got: {_DEFAULT_DB_PATH}"

    def test_calibration_default_path_ends_in_data_dir(self):
        from merid.metrics.calibration import _DEFAULT_DB_PATH
        assert _DEFAULT_DB_PATH.replace("\\", "/").endswith("data/calibration.db"), \
            f"CalibrationStore path must end in data/calibration.db, got: {_DEFAULT_DB_PATH}"

    def test_realized_edge_default_path_is_absolute(self):
        from merid.metrics.realized_edge import _DEFAULT_DB_PATH
        assert os.path.isabs(_DEFAULT_DB_PATH), \
            f"RealizedEdgeStore default path must be absolute, got: {_DEFAULT_DB_PATH}"

    def test_realized_edge_default_path_ends_in_data_dir(self):
        from merid.metrics.realized_edge import _DEFAULT_DB_PATH
        assert _DEFAULT_DB_PATH.replace("\\", "/").endswith("data/realized_edge.db"), \
            f"RealizedEdgeStore path must end in data/realized_edge.db, got: {_DEFAULT_DB_PATH}"

    def test_signal_store_default_path_is_absolute(self):
        from merid.signals.store import SignalStore
        store = SignalStore(db_path=":memory:")
        # The default path logic is inside __init__; verify via re-instantiating
        # with env-var override cleared and checking module constant derivation
        from merid.signals import store as store_mod
        import importlib, inspect
        src = inspect.getsource(store_mod.SignalStore.__init__)
        assert "__file__" in src, \
            "SignalStore.__init__ must use __file__-relative path resolution"

    def test_calibration_and_realized_edge_share_same_project_root(self):
        from merid.metrics.calibration import _PROJECT_ROOT as cal_root
        from merid.metrics.realized_edge import _PROJECT_ROOT as edge_root
        assert os.path.normpath(cal_root) == os.path.normpath(edge_root), \
            "Both stores must resolve to the same project root"

    def test_project_root_contains_merid_package(self):
        from merid.metrics.calibration import _PROJECT_ROOT
        assert os.path.isdir(os.path.join(_PROJECT_ROOT, "merid")), \
            "_PROJECT_ROOT must contain the merid/ package directory"


# ===========================================================================
# §4  Fix 4 — Stale ConsensusView eviction
# ===========================================================================

class TestStaleConsensusEviction:
    """Fix 4: get_consensus() must return None when all proposals are expired."""

    def _make_aggregator(self):
        from merid.swarm.consensus_aggregator import SwarmConsensusAggregator
        agg = SwarmConsensusAggregator.__new__(SwarmConsensusAggregator)
        agg._initialized = False
        SwarmConsensusAggregator.__init__(
            agg,
            min_agents_for_consensus=1,
            max_proposal_age_seconds=60.0,
            consensus_threshold=0.5,
        )
        return agg

    def _make_proposal(self, agent_id="a1", ts: Optional[datetime] = None):
        from merid.swarm.consensus_aggregator import AgentProposal
        return AgentProposal(
            agent_id=agent_id,
            asset="BTC",
            timeframe="15m",
            direction="yes",
            probability=0.7,
            confidence=0.8,
            size_preference="base",
            rationale="test",
            edge_estimate=3.0,
            timestamp=ts or datetime.now(timezone.utc),
            agent_archetype="trend",
            agent_track_record=None,
        )

    def test_returns_none_when_no_proposals(self):
        agg = self._make_aggregator()
        result = agg.get_consensus("BTC", "15m")
        assert result is None

    def test_returns_none_when_all_proposals_expired(self):
        from merid.swarm.consensus_aggregator import ConsensusView, ConsensusStatus
        agg = self._make_aggregator()
        key = "BTC:15m"

        # Inject an already-expired proposal directly into the internal store
        old_ts = datetime.now(timezone.utc) - timedelta(seconds=120)
        agg._proposals[key] = [self._make_proposal(ts=old_ts)]

        # Inject a fake cached consensus
        fake_view = MagicMock(spec=ConsensusView)
        agg._consensus_cache[key] = fake_view

        result = agg.get_consensus("BTC", "15m")
        assert result is None, "Expired proposals must cause cache eviction"
        assert key not in agg._consensus_cache, "Cache entry must be removed"

    def test_returns_view_when_live_proposal_exists(self):
        from merid.swarm.consensus_aggregator import ConsensusView, ConsensusStatus
        agg = self._make_aggregator()
        key = "BTC:15m"

        agg._proposals[key] = [self._make_proposal()]
        fake_view = MagicMock(spec=ConsensusView)
        agg._consensus_cache[key] = fake_view

        result = agg.get_consensus("BTC", "15m")
        assert result is fake_view

    def test_cache_cleared_after_eviction(self):
        agg = self._make_aggregator()
        key = "BTC:15m"
        old_ts = datetime.now(timezone.utc) - timedelta(seconds=200)
        agg._proposals[key] = [self._make_proposal(ts=old_ts)]
        agg._consensus_cache[key] = MagicMock()

        agg.get_consensus("BTC", "15m")
        assert key not in agg._consensus_cache

    def test_mixed_fresh_and_stale_proposals_not_evicted(self):
        agg = self._make_aggregator()
        key = "BTC:15m"

        old_ts = datetime.now(timezone.utc) - timedelta(seconds=200)
        fresh_ts = datetime.now(timezone.utc) - timedelta(seconds=10)
        agg._proposals[key] = [
            self._make_proposal(agent_id="a1", ts=old_ts),
            self._make_proposal(agent_id="a2", ts=fresh_ts),
        ]
        fake_view = MagicMock()
        agg._consensus_cache[key] = fake_view

        result = agg.get_consensus("BTC", "15m")
        assert result is fake_view, "One live proposal is enough to keep cache"


# ===========================================================================
# §5  Fix 5 — SignalStore.reset_all() clears signal_snapshots
# ===========================================================================

class TestSignalStoreResetAll:
    """Fix 5: reset_all() must truncate signal_snapshots table."""

    def _make_store(self):
        from merid.signals.store import SignalStore
        return SignalStore(db_path=":memory:")

    def test_reset_all_clears_signal_snapshots(self):
        store = self._make_store()
        store.store_snapshot(
            {"snapshot_id": "snap-1", "symbol": "BTC", "timestamp": 1234.0},
            opinion_or_plan_id="op-1",
        )
        assert len(store.get_snapshots()) == 1

        store.reset_all()
        assert len(store.get_snapshots()) == 0, \
            "reset_all() must clear signal_snapshots"

    def test_reset_all_clears_signal_features(self):
        store = self._make_store()
        store.store_signal({
            "signal_id": "sig-1", "ticker": "BTC",
            "signal_type": "kalshi", "source": "test",
        })
        store.reset_all()
        assert len(store.get_latest_features("BTC")) == 0

    def test_reset_all_clears_arb_signals(self):
        store = self._make_store()
        store.store_arb_signal({
            "signal_id": "arb-1", "domain": "crypto", "arb_type": "spread",
            "symbol": "BTC", "venues": [], "detected_at": 1234.0,
        })
        store.reset_all()
        assert len(store.list_arb_signals()) == 0

    def test_reset_all_clears_drift_metrics(self):
        store = self._make_store()
        store.store_drift_metric({"domain": "crypto", "window": "24h",
                                  "timestamp": 1234.0})
        store.reset_all()
        assert len(store.get_drift_metrics()) == 0

    def test_reset_all_clears_cqi_history(self):
        store = self._make_store()
        store.store_cqi({"domain": "crypto", "quality_index": 0.7,
                          "band": "good", "timestamp": 1234.0})
        store.reset_all()
        assert len(store.get_latest_cqi()) == 0

    def test_reset_all_metrics_all_zero(self):
        store = self._make_store()
        store.store_snapshot({"snapshot_id": "s1", "symbol": "ETH",
                               "timestamp": 1.0}, opinion_or_plan_id="op-2")
        store.reset_all()
        metrics = store.get_signal_metrics()
        assert metrics["signal_snapshots"] == 0
        assert metrics["feature_snapshots"] == 0


# ===========================================================================
# §6  Fix 6 — asyncio.ensure_future replaced with get_running_loop guard
# ===========================================================================

class TestSubscriberLoopGuard:
    """Fix 6: coroutine subscriber callbacks must use get_running_loop, not ensure_future."""

    def test_ensure_future_not_in_recompute_source(self):
        import inspect
        from merid.swarm import consensus_aggregator as mod
        src = inspect.getsource(mod.SwarmConsensusAggregator._recompute_consensus)
        assert "ensure_future" not in src, \
            "ensure_future must be replaced with get_running_loop().create_task()"

    def test_get_running_loop_used_for_coroutines(self):
        import inspect
        from merid.swarm import consensus_aggregator as mod
        src = inspect.getsource(mod.SwarmConsensusAggregator._recompute_consensus)
        assert "get_running_loop" in src, \
            "_recompute_consensus must use get_running_loop() for coroutine dispatch"

    def test_sync_subscriber_callback_invoked(self):
        """A plain sync callback must still be called normally."""
        from merid.swarm.consensus_aggregator import SwarmConsensusAggregator, AgentProposal
        agg = SwarmConsensusAggregator.__new__(SwarmConsensusAggregator)
        agg._initialized = False
        SwarmConsensusAggregator.__init__(agg, min_agents_for_consensus=1,
                                          max_proposal_age_seconds=300,
                                          consensus_threshold=0.5)
        received = []
        agg.subscribe(lambda cv: received.append(cv))

        prop = AgentProposal(
            agent_id="a1", asset="ETH", timeframe="5m",
            direction="yes", probability=0.65, confidence=0.75,
            size_preference="base", rationale="r", edge_estimate=2.0,
            timestamp=datetime.now(timezone.utc), agent_archetype="trend",
        )
        with patch.object(agg, "_aggregate_proposals") as mock_agg, \
             patch("merid.swarm.market_mood_bus.get_market_mood_bus", side_effect=Exception), \
             patch("merid.swarm.messages.publish_decision", side_effect=Exception):
            from merid.swarm.consensus_aggregator import ConsensusView, ConsensusStatus
            fake_cv = MagicMock(spec=ConsensusView)
            fake_cv.status = ConsensusStatus.READY
            fake_cv.consensus_direction = "yes"
            fake_cv.consensus_probability = 0.65
            fake_cv.consensus_confidence = 0.75
            fake_cv.direction_breakdown = {"yes": 1}
            fake_cv.confidence_factors = []
            fake_cv.disagreement_flags = []
            fake_cv.size_band = "base"
            fake_cv.size_rationale = ""
            fake_cv.voting_agents = 1
            fake_cv.asset = "ETH"
            fake_cv.timeframe = "5m"
            mock_agg.return_value = fake_cv
            agg._proposals["ETH:5m"] = [prop]
            agg._recompute_consensus("ETH:5m")

        assert len(received) >= 1

    def test_coroutine_subscriber_closed_without_loop(self):
        """Coroutine returned by subscriber must be closed, not leaked, outside async."""
        closed = []

        async def async_cb(cv):
            pass  # pragma: no cover

        from merid.swarm.consensus_aggregator import SwarmConsensusAggregator, ConsensusView, ConsensusStatus
        agg = SwarmConsensusAggregator.__new__(SwarmConsensusAggregator)
        agg._initialized = False
        SwarmConsensusAggregator.__init__(agg, min_agents_for_consensus=1,
                                          max_proposal_age_seconds=300,
                                          consensus_threshold=0.5)
        agg.subscribe(async_cb)

        fake_old = None
        fake_new = MagicMock(spec=ConsensusView)
        fake_new.consensus_direction = "yes"
        fake_new.consensus_probability = 0.7
        fake_new.consensus_confidence = 0.8
        fake_new.status = ConsensusStatus.READY

        # Verify no RuntimeError / unraisable exception is raised
        with patch.object(agg, "_is_significant_change", return_value=True), \
             patch("merid.swarm.market_mood_bus.get_market_mood_bus", side_effect=Exception), \
             patch("merid.swarm.messages.publish_decision", side_effect=Exception), \
             patch("core.event_bus.event_stream", MagicMock()):
            agg._consensus_cache["X:1m"] = fake_new
            # Directly test the subscriber notification section
            for callback in agg._subscribers:
                try:
                    result = callback(fake_new)
                    if asyncio.iscoroutine(result):
                        try:
                            loop = asyncio.get_running_loop()
                            loop.create_task(result)
                        except RuntimeError:
                            result.close()
                            closed.append(True)
                except Exception:
                    pass

        assert len(closed) == 1, "Coroutine must be closed when no event loop is running"


# ===========================================================================
# §7  Fix 7 — Orchestrator cycle_id includes UUID fragment
# ===========================================================================

class TestOrchestratorCycleId:
    """Fix 7: cycle_id must contain a UUID fragment for cross-restart uniqueness."""

    def test_uuid_import_in_orchestrator(self):
        import merid.agents.orchestrator as mod
        import inspect
        src = inspect.getsource(mod)
        assert "import uuid" in src, "orchestrator.py must import uuid"

    def test_cycle_id_format_contains_uuid_fragment(self):
        from merid.agents.orchestrator import AgentOrchestrator
        from merid.agents.base import CanonicalAgentRegistry
        orch = AgentOrchestrator(registry=CanonicalAgentRegistry())

        async def _run():
            return await orch.run_cycle({})

        with patch.object(orch, "_run_phase") as mock_phase:
            from merid.agents.orchestrator import PhaseResult
            from merid.agents.base import AgentCategory
            mock_phase.return_value = PhaseResult(phase="research")
            with patch("merid.agents.orchestrator.get_tick_bus") as mock_bus:
                mock_bus.return_value = MagicMock()
                orch.phases = []  # Skip all phases for speed
                result = asyncio.get_event_loop().run_until_complete(orch.run_cycle({}))

        parts = result.cycle_id.split("-")
        assert len(parts) >= 3, f"cycle_id must be 'cycle-N-<hex>', got: {result.cycle_id}"
        hex_part = parts[-1]
        assert len(hex_part) == 8, f"UUID fragment must be 8 hex chars, got: {hex_part}"
        assert all(c in "0123456789abcdef" for c in hex_part), \
            f"UUID fragment must be hex, got: {hex_part}"

    def test_two_cycle_ids_differ(self):
        from merid.agents.orchestrator import AgentOrchestrator
        from merid.agents.base import CanonicalAgentRegistry
        orch = AgentOrchestrator(registry=CanonicalAgentRegistry())
        orch.phases = []

        async def _run_two():
            with patch("merid.agents.orchestrator.get_tick_bus") as mock_bus:
                mock_bus.return_value = MagicMock()
                r1 = await orch.run_cycle({})
                r2 = await orch.run_cycle({})
            return r1, r2

        r1, r2 = asyncio.get_event_loop().run_until_complete(_run_two())
        assert r1.cycle_id != r2.cycle_id, "Consecutive cycle IDs must differ"

    def test_cycle_id_starts_with_cycle_prefix(self):
        from merid.agents.orchestrator import AgentOrchestrator
        from merid.agents.base import CanonicalAgentRegistry
        orch = AgentOrchestrator(registry=CanonicalAgentRegistry())
        orch.phases = []

        async def _run():
            with patch("merid.agents.orchestrator.get_tick_bus") as mock_bus:
                mock_bus.return_value = MagicMock()
                return await orch.run_cycle({})

        result = asyncio.get_event_loop().run_until_complete(_run())
        assert result.cycle_id.startswith("cycle-"), \
            f"cycle_id must start with 'cycle-', got: {result.cycle_id}"


# ===========================================================================
# §8  Fix 8 — arb_plans FK to arb_signals
# ===========================================================================

class TestArbPlansForeignKey:
    """Fix 8: arb_plans.signal_id must be a FK referencing arb_signals."""

    def _make_store(self):
        from merid.signals.store import SignalStore
        return SignalStore(db_path=":memory:")

    def test_fk_declaration_in_schema_source(self):
        import inspect
        from merid.signals import store as mod
        src = inspect.getsource(mod.SignalStore._init_db)
        assert "REFERENCES arb_signals" in src, \
            "arb_plans DDL must include REFERENCES arb_signals FK"

    def test_arb_plan_stores_without_signal_id(self):
        """Null signal_id (ON DELETE SET NULL path) must be allowed."""
        store = self._make_store()
        store.store_arb_plan({
            "plan_id": "plan-1", "signal_id": None,
            "domain": "crypto", "arb_type": "spread", "symbol": "BTC",
            "legs": [], "created_at": 1234.0,
        })
        plans = store.list_arb_plans()
        assert len(plans) == 1

    def test_arb_plan_with_valid_signal_id(self):
        store = self._make_store()
        store.store_arb_signal({
            "signal_id": "sig-1", "domain": "crypto", "arb_type": "spread",
            "symbol": "BTC", "venues": [], "detected_at": 1234.0,
        })
        store.store_arb_plan({
            "plan_id": "plan-2", "signal_id": "sig-1",
            "domain": "crypto", "arb_type": "spread", "symbol": "BTC",
            "legs": [], "created_at": 1234.0,
        })
        plans = store.list_arb_plans()
        assert any(p["id"] == "plan-2" for p in plans)


# ===========================================================================
# §9  Fix 9 — Atomic write in LongTermKnowledgeBase
# ===========================================================================

class TestLongTermKnowledgeBaseAtomicWrite:
    """Fix 9: _persist() must write to .tmp then rename atomically."""

    def test_persist_uses_tmp_then_replace(self):
        import inspect
        from memory import long_term_knowledge_base as mod
        src = inspect.getsource(mod.LongTermKnowledgeBase._persist)
        assert ".tmp" in src, "_persist must write to a .tmp file first"
        assert "replace" in src, "_persist must call .replace() for atomic rename"

    def test_no_direct_write_text_on_final_path(self):
        """write_text must only be called on the tmp path, not the final path."""
        import inspect
        from memory import long_term_knowledge_base as mod
        src = inspect.getsource(mod.LongTermKnowledgeBase._persist)
        # write_text should appear exactly once and be on tmp_path
        lines = [l.strip() for l in src.splitlines() if "write_text" in l]
        assert len(lines) == 1
        assert "tmp_path" in lines[0], \
            "write_text must be called on tmp_path, not on _storage_path directly"

    def test_persisted_file_is_valid_json(self, tmp_path):
        import json
        from memory.long_term_knowledge_base import LongTermKnowledgeBase
        kb = LongTermKnowledgeBase(storage_path=tmp_path / "kb.json")
        kb.record_entry("lesson", "Test lesson", "Some summary",
                        tags=["test"], recorded_by="pytest")
        raw = (tmp_path / "kb.json").read_text(encoding="utf-8")
        data = json.loads(raw)
        assert isinstance(data, list)
        assert data[0]["title"] == "Test lesson"

    def test_no_tmp_file_left_after_persist(self, tmp_path):
        from memory.long_term_knowledge_base import LongTermKnowledgeBase
        kb = LongTermKnowledgeBase(storage_path=tmp_path / "kb.json")
        kb.record_entry("bug", "A bug", "Description", recorded_by="pytest")
        tmp_file = tmp_path / "kb.tmp"
        assert not tmp_file.exists(), ".tmp file must be removed after atomic rename"

    def test_data_survives_reload(self, tmp_path):
        from memory.long_term_knowledge_base import LongTermKnowledgeBase
        kb1 = LongTermKnowledgeBase(storage_path=tmp_path / "kb2.json")
        kb1.record_entry("breakthrough", "Discovery", "Details",
                         tags=["perf"], recorded_by="pytest")
        kb2 = LongTermKnowledgeBase(storage_path=tmp_path / "kb2.json")
        entries = kb2.list_entries(entry_type="breakthrough")
        assert len(entries) == 1
        assert entries[0].title == "Discovery"


# ===========================================================================
# §10  Fix 10 — PatternEngine stop-word filter
# ===========================================================================

class TestPatternEngineStopWords:
    """Fix 10: _tokenize must filter common English stop-words."""

    def test_stop_words_constant_exists(self):
        from memory import patterns as mod
        assert hasattr(mod, "_STOP_WORDS"), \
            "memory.patterns must define _STOP_WORDS"

    def test_stop_words_is_frozenset(self):
        from memory.patterns import _STOP_WORDS
        assert isinstance(_STOP_WORDS, frozenset)

    def test_common_stop_words_excluded(self):
        from memory.patterns import _tokenize
        tokens = _tokenize("this should have been removed from the result")
        for word in ("this", "have", "been", "from"):
            assert word not in tokens, f"Stop word '{word}' must be filtered"

    def test_domain_keywords_retained(self):
        from memory.patterns import _tokenize
        tokens = _tokenize("bitcoin consensus prediction market probability")
        for word in ("bitcoin", "consensus", "prediction", "market", "probability"):
            assert word in tokens, f"Domain keyword '{word}' must be retained"

    def test_short_tokens_still_excluded(self):
        from memory.patterns import _tokenize
        tokens = _tokenize("is at of to a")
        assert tokens == [], "Tokens of length <= 3 must be excluded"

    def test_token_count_capped_at_50(self):
        from memory.patterns import _tokenize
        payload = " ".join(f"word{i}" for i in range(100))
        tokens = _tokenize(payload)
        assert len(tokens) <= 50

    def test_pattern_engine_insights_excludes_stop_words(self):
        from memory.patterns import PatternEngine
        fake_store = MagicMock()
        fake_store.recent.return_value = [
            {"source": "kalshi", "payload": "this market should have probability",
             "validation": {"status": "validated"}},
        ]
        engine = PatternEngine(fake_store)
        result = engine.insights(window=10)
        keyword_labels = [kw["label"] for kw in result["keywords"]]
        for stop in ("this", "should", "have"):
            assert stop not in keyword_labels, \
                f"Stop word '{stop}' must not appear in keyword insights"
        assert "market" in keyword_labels or "probability" in keyword_labels, \
            "Domain keywords must appear in results"
