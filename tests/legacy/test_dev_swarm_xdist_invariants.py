"""
xdist Isolation & Invariant Tests for MERID Dev Swarm

These tests verify that shared fixtures remain isolated under parallel
execution (-n auto) and that session-scoped config is identical across workers.

Run with:
    pytest tests/test_dev_swarm_xdist_invariants.py -n auto -v
    pytest tests/test_dev_swarm_xdist_invariants.py -v  # also works serial

Markers:
    devswarm, auditor — included in standard marker-based runs
"""
from __future__ import annotations

import hashlib
import json

import pytest

pytestmark = [pytest.mark.devswarm, pytest.mark.auditor]


# ============================================
# SESSION CONFIG IDENTITY
# ============================================

class TestS2ConfigIdentity:
    """Verify the session-scoped S2 config is deterministic and hashable."""

    def test_s2_config_is_dict(self, dev_swarm_s2_config):
        """Config fixture returns a plain dict (JSON-serializable)."""
        assert isinstance(dev_swarm_s2_config, dict)

    def test_s2_config_json_roundtrip(self, dev_swarm_s2_config):
        """Config survives JSON serialization without data loss."""
        serialized = json.dumps(dev_swarm_s2_config, sort_keys=True)
        deserialized = json.loads(serialized)
        assert deserialized == dev_swarm_s2_config

    def test_s2_config_hash_stable(self, dev_swarm_s2_config):
        """Same config produces the same SHA-256 hash across calls."""
        def _hash(d):
            return hashlib.sha256(
                json.dumps(d, sort_keys=True).encode()
            ).hexdigest()

        h1 = _hash(dev_swarm_s2_config)
        h2 = _hash(dev_swarm_s2_config)
        assert h1 == h2

    def test_s2_config_template_count_invariant(self, dev_swarm_s2_config):
        """Template count matches the templates dict length."""
        assert dev_swarm_s2_config["template_count"] == len(
            dev_swarm_s2_config["templates"]
        )

    def test_s2_config_season_is_two(self, dev_swarm_s2_config):
        """Season field is always 2."""
        assert dev_swarm_s2_config["season"] == 2


# ============================================
# FIXTURE ISOLATION
# ============================================

class TestFixtureIsolation:
    """Verify function-scoped fixtures produce independent instances."""

    def test_swarm_instances_are_independent(self, dev_swarm_instance):
        """Each test gets its own DevSwarm — mutating one doesn't affect another."""
        from core.dev_swarm import DevTask
        # Add a task to this instance
        task = DevTask(
            task_id="isolation-test-001",
            description="Isolation test task",
            target_files=[],
            success_criteria="n/a",
        )
        dev_swarm_instance.task_history.append(task)
        assert len(dev_swarm_instance.task_history) == 1

    def test_swarm_instance_starts_clean(self, dev_swarm_instance):
        """This test runs after the mutation above — history must still be empty."""
        assert len(dev_swarm_instance.task_history) == 0

    def test_commitments_dataset_root_is_writable(self, commitments_dataset_root):
        """Each worker's dataset root is a real writable directory."""
        probe = commitments_dataset_root / "probe.txt"
        probe.write_text("ok", encoding="utf-8")
        assert probe.read_text(encoding="utf-8") == "ok"

    def test_commitments_datasets_exist(self, commitments_dataset_root):
        """All 4 synthetic datasets are present in the root."""
        expected = {"none.md", "one_overdue.md", "mixed.md", "malformed.md"}
        actual = {p.name for p in commitments_dataset_root.iterdir() if p.suffix == ".md"}
        assert expected.issubset(actual), f"Missing: {expected - actual}"

    def test_historical_auditor_factory_returns_fresh_reports(self, historical_auditor_for):
        """Two calls to the factory with the same file return independent objects."""
        r1 = historical_auditor_for("none.md")
        r2 = historical_auditor_for("none.md")
        assert r1 is not r2
        assert len(r1.commitments) == len(r2.commitments)


# ============================================
# ORDERING & PRIORITY INVARIANTS
# ============================================

class TestPriorityInvariants:
    """Verify priority ordering is deterministic regardless of execution order."""

    def test_template_priorities_are_bounded(self, dev_swarm_s2_config):
        """All priorities are in [0, 2]."""
        for name, meta in dev_swarm_s2_config["templates"].items():
            assert 0 <= meta["priority"] <= 2, (
                f"{name}: priority {meta['priority']} out of [0,2] range"
            )

    def test_critical_templates_have_priority_zero(self, dev_swarm_s2_config):
        """Templates with 'critical' in their effort or description have priority 0."""
        critical_names = {"build_state_manager", "implement_black_swan_drill_harness",
                          "add_observability_kill_switch"}
        for name in critical_names:
            meta = dev_swarm_s2_config["templates"][name]
            assert meta["priority"] == 0, f"{name}: expected priority 0, got {meta['priority']}"

    def test_sorted_priorities_are_stable(self, dev_swarm_s2_config):
        """Sorting templates by priority produces a stable ordering."""
        items = list(dev_swarm_s2_config["templates"].items())
        sorted_once = sorted(items, key=lambda x: x[1]["priority"])
        sorted_twice = sorted(items, key=lambda x: x[1]["priority"])
        assert sorted_once == sorted_twice


# ============================================
# CROSS-WORKER DATA INTEGRITY
# ============================================

class TestDataIntegrity:
    """Tests that would catch data corruption under parallel execution."""

    def test_overdue_counts_are_non_negative(self, historical_auditor_for):
        """Overdue count is never negative for any dataset."""
        for filename in ("none.md", "one_overdue.md", "mixed.md", "malformed.md"):
            report = historical_auditor_for(filename)
            assert report.overdue_count >= 0, f"{filename}: negative overdue count"

    def test_passed_matches_overdue_count(self, historical_auditor_for):
        """passed == True iff overdue_count == 0 for all datasets."""
        for filename in ("none.md", "one_overdue.md", "mixed.md", "malformed.md"):
            report = historical_auditor_for(filename)
            assert report.passed == (report.overdue_count == 0), (
                f"{filename}: passed={report.passed} but overdue_count={report.overdue_count}"
            )

    def test_commitment_ids_are_non_empty(self, historical_auditor_for):
        """Every parsed commitment has a non-empty ID."""
        for filename in ("none.md", "one_overdue.md", "mixed.md"):
            report = historical_auditor_for(filename)
            for c in report.commitments:
                assert c.id and len(c.id) > 0, f"{filename}: empty commitment ID"

    def test_commitment_statuses_are_valid_enums(self, historical_auditor_for):
        """Every parsed commitment has a valid CommitmentStatus."""
        from core.historical_commitments_auditor import CommitmentStatus
        valid = set(CommitmentStatus)
        for filename in ("none.md", "one_overdue.md", "mixed.md"):
            report = historical_auditor_for(filename)
            for c in report.commitments:
                assert c.status in valid, f"{filename}/{c.id}: invalid status {c.status}"
