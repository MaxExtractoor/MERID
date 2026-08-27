"""State diff / checksum recorder for live vs replay verification.

This is Task 4 of the determinism work: at each decision point (e.g.
``compute_trade_decision``) we emit a stable checksum of the canonical decision
inputs and outputs.  The live run writes a "golden" file; the replay run writes a
second file; a regression test diffs the two.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Optional

from merid.data.ingress_replay import get_replay_dispatcher, replay_time
from merid.utils.state_checksum import state_checksum
from utils.logger import get_logger

logger = get_logger("merid.audit.replay_state_diff")

_LOCK = threading.Lock()


def reset_replay_state_diff() -> None:
    """Remove live/replay diff files; intended for tests only."""
    for suffix in ("live", "replay"):
        path = _output_dir() / f"state_diff_{suffix}.jsonl"
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _output_dir() -> Path:
    base = os.environ.get("MERID_REPLAY_STATE_DIFF_DIR", "data/replay_state_diff")
    path = Path(base)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _is_replay() -> bool:
    return get_replay_dispatcher() is not None


def record_state_checksum(
    decision_id: str,
    state: Any,
    capture_seq: Optional[int] = None,
    kind: str = "decision",
) -> str:
    """Record a canonical checksum of a state snapshot.

    In live mode the output goes to ``state_diff_live.jsonl``; in replay mode to
    ``state_diff_replay.jsonl``.  The caller is responsible for collecting the
    state to be hashed (book, position, risk, and the decision itself).
    """
    checksum = state_checksum(state)
    dispatcher = get_replay_dispatcher()
    if capture_seq is None and dispatcher is not None:
        capture_seq = dispatcher._next_index

    entry = {
        "ts": replay_time(),
        "decision_id": decision_id,
        "kind": kind,
        "capture_seq": capture_seq,
        "checksum": checksum,
    }

    suffix = "replay" if _is_replay() else "live"
    path = _output_dir() / f"state_diff_{suffix}.jsonl"

    with _LOCK:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    return checksum


def read_state_diff_file(path: Path) -> list:
    """Read a state-diff JSON-line file."""
    if not path.exists():
        return []
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def diff_state_diff_files(live_path: Path, replay_path: Path) -> dict:
    """Return a structured diff between a live and a replay state-diff file."""
    live = [r["checksum"] for r in read_state_diff_file(live_path)]
    replay = [r["checksum"] for r in read_state_diff_file(replay_path)]

    from merid.utils.state_checksum import checksum_list_diff

    diffs = checksum_list_diff(live, replay)
    return {
        "live_count": len(live),
        "replay_count": len(replay),
        "mismatches": len(diffs),
        "first_mismatch_index": diffs[0] if diffs else None,
        "mismatch_indices": diffs,
        "equal": live == replay,
    }
