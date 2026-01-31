from __future__ import annotations

from pathlib import Path

import pytest

from tests.snapshots.builders import build_swarm_performance_snapshot
from tests.snapshots.utils import assert_matches_snapshot


@pytest.mark.snapshot
def test_swarm_performance_snapshot(tmp_path: Path) -> None:
    log_path = tmp_path / "swarm_performance.json"
    payload = build_swarm_performance_snapshot(log_path=log_path)
    assert_matches_snapshot("swarm_performance", payload)
