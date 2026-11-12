"""2026-11-12: logs/rejected_candidates.jsonl reached 12.3 GB with no
rotation — disk pressure on the production spindle.  The counterfactual
writer now size-rotates before each append burst, keeping timestamped
siblings bounded by MERID_REJECTED_CANDIDATES_BACKUPS.
"""

import os

from merid.prediction import rejection_counterfactual as rc


def test_rotation_triggered_over_cap(tmp_path, monkeypatch):
    target = tmp_path / "rejected_candidates.jsonl"
    target.write_bytes(b"x" * 2048)
    monkeypatch.setattr(rc, "_REJECTED_MAX_BYTES", 1024)
    monkeypatch.setattr(rc, "_REJECTED_BACKUPS", 2)

    rc._rotate_rejected_candidates_if_needed(str(target))

    assert not target.exists()
    siblings = list(tmp_path.glob("rejected_candidates.jsonl.*"))
    assert len(siblings) == 1
    assert siblings[0].read_bytes() == b"x" * 2048


def test_rotation_prunes_oldest_beyond_backups(tmp_path, monkeypatch):
    target = tmp_path / "rejected_candidates.jsonl"
    monkeypatch.setattr(rc, "_REJECTED_MAX_BYTES", 10)
    monkeypatch.setattr(rc, "_REJECTED_BACKUPS", 2)

    # Pre-seed two old siblings plus the live file over the cap.
    for i, name in enumerate(("20260101-000000", "20260102-000000")):
        (tmp_path / f"rejected_candidates.jsonl.{name}").write_bytes(b"old" + str(i).encode())
    target.write_bytes(b"y" * 100)

    rc._rotate_rejected_candidates_if_needed(str(target))

    remaining = sorted(p.name for p in tmp_path.glob("rejected_candidates.jsonl.*"))
    # 2 pre-seeded + 1 new rotation = 3 siblings; cap=2 -> oldest pruned.
    assert len(remaining) == 2
    assert "20260101-000000" not in remaining[0]
    assert target.exists() is False


def test_rotation_skipped_under_cap_and_disabled(tmp_path, monkeypatch):
    target = tmp_path / "rejected_candidates.jsonl"
    target.write_bytes(b"small")
    monkeypatch.setattr(rc, "_REJECTED_MAX_BYTES", 1 << 20)
    rc._rotate_rejected_candidates_if_needed(str(target))
    assert target.exists()

    monkeypatch.setattr(rc, "_REJECTED_MAX_BYTES", 0)  # disabled
    target.write_bytes(b"z" * 4096)
    rc._rotate_rejected_candidates_if_needed(str(target))
    assert target.exists()


def test_rotation_never_raises_on_bad_path(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "_REJECTED_MAX_BYTES", 1)
    # Directory-as-file edge and missing parent must not propagate.
    rc._rotate_rejected_candidates_if_needed(str(tmp_path / "no" / "such" / "dir" / "f.jsonl"))
    rc._rotate_rejected_candidates_if_needed("")
