"""Tests for the invariants enforcement system."""

from __future__ import annotations

from datetime import datetime as real_datetime, timedelta as real_timedelta

import pytest

from swarm import invariants_enforcement as ie


@pytest.fixture(autouse=True)
def deterministic_datetime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force deterministic timestamps so violation IDs are stable."""

    class _DeterministicDatetime(real_datetime):
        _tick = 0

        @classmethod
        def utcnow(cls):
            cls._tick += 1
            return real_datetime(2024, 1, 1) + real_timedelta(seconds=cls._tick)

    monkeypatch.setattr(ie, "datetime", _DeterministicDatetime)


@pytest.fixture()
def enforcement_system(monkeypatch: pytest.MonkeyPatch) -> ie.InvariantsEnforcementSystem:
    monkeypatch.setattr(ie, "_invariants_enforcement_system", None)
    return ie.InvariantsEnforcementSystem()


def test_initialization_populates_invariants_and_variants(enforcement_system: ie.InvariantsEnforcementSystem) -> None:
    status = enforcement_system.get_invariant_status()

    assert status["invariants"]["total"] > 0
    assert status["variants"]["total"] > 0
    assert sum(status["violations"]["by_severity"].values()) == 0


def test_validate_change_creates_violation_and_tracks_counts(enforcement_system: ie.InvariantsEnforcementSystem) -> None:
    violations = enforcement_system.validate_change(
        change_type="deployment",
        change_description="Custodial upgrade",
        component="custody_engine",
        change_data={"custodial": True},
    )

    assert violations
    assert violations[0].blocked is True

    status = enforcement_system.get_invariant_status()
    assert status["violations"]["total"] == 1
    assert status["violations"]["blocked"] == 1


def test_check_evolution_meta_invariants_records_failures(enforcement_system: ie.InvariantsEnforcementSystem) -> None:
    check = enforcement_system.check_evolution_meta_invariants(
        change_type="risk_model",
        change_description="Tighten limits",
        has_tests=False,
        has_governance=False,
        has_telemetry=True,
        has_rollback=False,
    )

    assert check.passed is False
    assert "governance approval" in " ".join(check.failures)
    assert enforcement_system.get_invariant_status()["evolution_checks"]["failed"] >= 1


def test_get_domain_queries_only_enabled_items(enforcement_system: ie.InvariantsEnforcementSystem) -> None:
    custody_invariants = enforcement_system.get_invariants_by_domain(ie.InvariantDomain.CUSTODY)
    assert custody_invariants

    infra_variants = enforcement_system.get_variants_by_domain(ie.VariantDomain.INFRASTRUCTURE)
    assert infra_variants
