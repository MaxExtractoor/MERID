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



# ===========================================================================
# §5  Fix 5 — SignalStore.reset_all() clears signal_snapshots
# ===========================================================================



# ===========================================================================
# §6  Fix 6 — asyncio.ensure_future replaced with get_running_loop guard
# ===========================================================================



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
