from __future__ import annotations

from pathlib import Path

from merid.safeguards.swarm_integrity_guard import (
    UNVERIFIED_DATA_MESSAGE,
    evaluate_swarm_integrity,
    load_safeguard_policy,
    load_swarm_snapshot,
    run_swarm_integrity_gate,
)


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "swarm"


def test_guard_passes_for_healthy_snapshot() -> None:
    snapshot = load_swarm_snapshot(FIXTURE_DIR / "healthy_snapshot.json")
    report = evaluate_swarm_integrity(snapshot)

    assert report.ok is True
    assert report.warning is None
    assert report.health_summary["all_online"] is True
    assert report.health_summary["all_synced"] is True
    assert report.health_summary["all_healthy"] is True
    assert report.data_summary["all_verified"] is True
    assert set(report.mode_tags) == {"live", "paper"}


def test_guard_fails_for_degraded_snapshot() -> None:
    snapshot = load_swarm_snapshot(FIXTURE_DIR / "degraded_snapshot.json")
    report = evaluate_swarm_integrity(snapshot)

    assert report.ok is False
    assert report.warning == UNVERIFIED_DATA_MESSAGE
    assert any("offline" in issue for issue in report.issues)
    assert any("not synced" in issue for issue in report.issues)
    assert any("source_type" in issue for issue in report.issues)


def test_policy_loader_reads_repo_policy_file() -> None:
    policy = load_safeguard_policy(".merid_safeguard.yml")

    assert policy["enforcement"]["min_health_pct"] == 100.0
    assert policy["reporting"]["unverified_data_message"] == UNVERIFIED_DATA_MESSAGE


def test_run_gate_requires_snapshot_path_when_missing(monkeypatch) -> None:
    monkeypatch.delenv("MERID_SWARM_HEALTH_SNAPSHOT", raising=False)

    report = run_swarm_integrity_gate(snapshot_path=None, policy_path=".merid_safeguard.yml")

    assert report.ok is False
    assert any("Missing swarm snapshot path" in issue for issue in report.issues)
    assert report.warning == UNVERIFIED_DATA_MESSAGE


def test_run_gate_uses_env_snapshot_path(monkeypatch) -> None:
    monkeypatch.setenv(
        "MERID_SWARM_HEALTH_SNAPSHOT",
        str(FIXTURE_DIR / "healthy_snapshot.json"),
    )

    report = run_swarm_integrity_gate(snapshot_path=None, policy_path=".merid_safeguard.yml")

    assert report.ok is True
