"""Golden-file regression test for the replay state-diff harness.

This test proves that the replay+checksum path is deterministic: with the same
tape and the same logical events, the checksum sequence is byte-for-byte stable.
"""

import json
import os
from decimal import Decimal
from pathlib import Path

import pytest

from merid.data.ingress_recorder import SOURCE_KALSHI_REST, SOURCE_KALSHI_WS
from merid.data.ingress_replay import (
    get_replay_dispatcher,
    reset_replay_dispatcher_for_tests,
)
from merid.audit.replay_state_diff import (
    record_state_checksum,
    reset_replay_state_diff,
)
from merid.utils.state_checksum import state_checksum


_GOLDEN_DIR = Path(__file__).parent / "golden"
_TAPE_DIR = _GOLDEN_DIR / "replay_tape"
_GOLDEN_FILE = _GOLDEN_DIR / "replay_state_diff_golden.jsonl"
_DIFF_FILE = Path("data/replay_state_diff/state_diff_replay.jsonl")


def _load_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _write_jsonl(path: Path, records: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, sort_keys=True) + "\n")


@pytest.fixture(autouse=True)
def _isolate():
    reset_replay_dispatcher_for_tests(None)
    reset_replay_state_diff()
    old_env = os.environ.get("MERID_REPLAY_TAPE")
    old_dir = os.environ.get("MERID_REPLAY_STATE_DIFF_DIR")
    os.environ["MERID_REPLAY_TAPE"] = str(_TAPE_DIR)
    os.environ["MERID_REPLAY_STATE_DIFF_DIR"] = str(_DIFF_FILE.parent)
    yield
    reset_replay_dispatcher_for_tests(None)
    reset_replay_state_diff()
    if old_env is not None:
        os.environ["MERID_REPLAY_TAPE"] = old_env
    else:
        os.environ.pop("MERID_REPLAY_TAPE", None)
    if old_dir is not None:
        os.environ["MERID_REPLAY_STATE_DIFF_DIR"] = old_dir
    else:
        os.environ.pop("MERID_REPLAY_STATE_DIFF_DIR", None)


def test_state_checksum_is_deterministic() -> None:
    """Same canonical state must always produce the same checksum."""
    state = {
        "ticker": "KXBTC",
        "price": 0.1234567890123,
        "size": Decimal("1.55"),
        "nested": {"b": 2, "a": 1},
        "list": [3.0, 1.0, 2.0],
    }
    c1 = state_checksum(state)
    c2 = state_checksum(state)
    assert c1 == c2
    # Canonical JSON sorts dict keys and rounds floats to 8 places.
    assert c1 == state_checksum(
        {
            "ticker": "KXBTC",
            "price": 0.12345679,
            "size": Decimal("1.55"),
            "nested": {"a": 1, "b": 2},
            "list": [3.0, 1.0, 2.0],
        }
    )


def test_replay_state_diff_matches_golden() -> None:
    """State checksum sequence for a fixed tape must match the stored golden."""
    dispatcher = get_replay_dispatcher()
    assert dispatcher is not None

    # Consume records in capture order; each record advances the replay clock
    # and the global capture_seq index.
    dispatcher.get(SOURCE_KALSHI_WS)
    record_state_checksum(
        "after_ws",
        {"ticker": "KXBTC", "bid": 0.12345678, "ask": 0.23456789},
        kind="book",
    )

    dispatcher.get(SOURCE_KALSHI_REST)
    record_state_checksum(
        "after_rest",
        {"ticker": "KXBTC", "position": Decimal("1.55"), "pnl": -0.001},
        kind="risk",
    )

    actual = _load_jsonl(_DIFF_FILE)

    if os.environ.get("MERID_REGENERATE_GOLDEN") == "1" or not _GOLDEN_FILE.exists():
        _write_jsonl(_GOLDEN_FILE, actual)
        pytest.skip(f"Regenerated golden file: {_GOLDEN_FILE}")

    golden = _load_jsonl(_GOLDEN_FILE)
    assert actual == golden, (
        f"Replay state diff does not match golden.\n"
        f"Actual:   {actual}\n"
        f"Expected: {golden}\n"
        f"Run with MERID_REGENERATE_GOLDEN=1 to update the golden file."
    )
