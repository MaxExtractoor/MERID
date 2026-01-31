"""Tests for the HSM key management system."""

from __future__ import annotations

from datetime import datetime as real_datetime, timedelta as real_timedelta

import pytest

from swarm import hsm_key_management as hkm


@pytest.fixture(autouse=True)
def deterministic_datetime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make timestamp-based IDs deterministic and unique."""

    class _DeterministicDatetime(real_datetime):
        _tick = 0

        @classmethod
        def utcnow(cls):
            cls._tick += 1
            return real_datetime(2024, 1, 1) + real_timedelta(seconds=cls._tick)

    monkeypatch.setattr(hkm, "datetime", _DeterministicDatetime)


@pytest.fixture()
def hsm(monkeypatch: pytest.MonkeyPatch) -> hkm.HSMKeyManagementSystem:
    monkeypatch.setattr(hkm, "_hsm_key_management_system", None)
    return hkm.HSMKeyManagementSystem()


def test_generate_wrap_and_rotate_key(hsm: hkm.HSMKeyManagementSystem) -> None:
    hsm_config = next(iter(hsm._hsm_configs.values()))

    key = hsm.generate_key(hkm.KeyType.SIGNING, hsm_config.hsm_id)
    assert key.key_id in hsm._keys
    assert key.status == hkm.KeyStatus.ACTIVE

    wrapped = hsm.wrap_key(key.key_id, "wrapping-key")
    assert wrapped.wrapped is True
    assert wrapped.wrapping_key_id == "wrapping-key"

    new_key = hsm.rotate_key(key.key_id)
    assert new_key.key_id != key.key_id
    assert hsm._keys[new_key.key_id].key_type == hkm.KeyType.SIGNING

    new_key.next_rotation_at = hkm.datetime.utcnow() - real_timedelta(days=1)
    due_for_rotation = hsm.get_key_rotation_schedule()
    assert new_key in due_for_rotation


def test_signing_request_flow_and_rejection(hsm: hkm.HSMKeyManagementSystem) -> None:
    request = hsm.create_signing_request(
        intent_type="deploy",
        intent_data={"contract": "alpha"},
        requester_id="agent-1",
        requester_type="agent",
        policy=hkm.SigningPolicy.DUAL_CONTROL,
    )

    hsm.approve_signing_request(request.request_id, "admin-a", hkm.HSMRole.KEY_ADMIN)
    assert request.approved is False
    assert len(request.approvals) == 1

    hsm.approve_signing_request(request.request_id, "admin-b", hkm.HSMRole.KEY_ADMIN)
    assert request.approved is True
    assert request.signed is True

    reject_request = hsm.create_signing_request(
        intent_type="rotate",
        intent_data={},
        requester_id="agent-2",
        requester_type="agent",
    )

    hsm.reject_signing_request(
        reject_request.request_id,
        rejector_id="auditor",
        rejector_role=hkm.HSMRole.AUDITOR,
        reason="Policy violation",
    )
    assert reject_request.rejected is True
    assert "Policy" in reject_request.rejection_reason


def test_disaster_recovery_plan_and_status(hsm: hkm.HSMKeyManagementSystem) -> None:
    primary_hsm_id = next(iter(hsm._hsm_configs.keys()))
    plan = hsm.create_disaster_recovery_plan([primary_hsm_id], backup_frequency_hours=12)
    assert plan.plan_id in hsm._dr_plans

    assert hsm.test_disaster_recovery(plan.plan_id) is True

    status = hsm.get_hsm_status()
    assert status["hsms"]["total"] >= 1
    assert status["audit"]["total_logs"] >= 1
    assert status["disaster_recovery"]["plans"] >= 1
