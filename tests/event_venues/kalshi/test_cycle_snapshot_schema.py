"""Version gate for Kalshi cycle snapshot JSON."""

from __future__ import annotations

import pytest

from merid.event_venues.kalshi.cycle_snapshot_schema import assert_replayable_cycle_snapshot

pytestmark = pytest.mark.kalshi_live_ready


def test_rejects_missing_schema_version() -> None:
    with pytest.raises(ValueError, match="schema_version"):
        assert_replayable_cycle_snapshot({"meta": {}, "markets": []})


def test_rejects_schema_too_new() -> None:
    with pytest.raises(ValueError, match="newer than harness"):
        assert_replayable_cycle_snapshot(
            {"schema_version": 9999, "meta": {}, "markets": []}
        )
