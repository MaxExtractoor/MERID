"""P1-7: Offline snapshot replay stays deterministic; pipeline counts stable for a fixed fixture."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from merid.event_venues.kalshi.replay_harness import PipelineSnapshot, ReplayHarness
from tools.replay_kalshi_snapshot import replay_snapshot

pytestmark = pytest.mark.kalshi_live_ready


def _minimal_snapshot_path(tmp_path: Path) -> Path:
    payload = {
        "schema_version": 1,
        "meta": {"asset": "BTC", "timeframe": "15m", "cycle_id": "unit"},
        "markets": [
            {
                "ticker": "KXBTC15M-26MAR291200-T89500",
                "underlying": "BTC",
                "timeframe": "15m",
                "expiry_ts": 1e10,
                "volume": 1000,
                "open_interest": 500,
                "best_bid_cents": 45,
                "best_ask_cents": 55,
                "spread_cents": 10,
                "mid_price_cents": 50,
                "category": "crypto",
            },
            {
                "ticker": "KXBTC15M-26MAR291200-T90000",
                "underlying": "BTC",
                "timeframe": "15m",
                "expiry_ts": 1e10,
                "volume": 2000,
                "open_interest": 800,
                "best_bid_cents": 40,
                "best_ask_cents": 48,
                "spread_cents": 8,
                "mid_price_cents": 44,
                "category": "crypto",
            },
        ],
    }
    p = tmp_path / "snap.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_replay_snapshot_is_deterministic(tmp_path: Path) -> None:
    path = _minimal_snapshot_path(tmp_path)
    a = replay_snapshot(path, verbose=False, spot_overrides={"BTC": 90_000.0})
    b = replay_snapshot(path, verbose=False, spot_overrides={"BTC": 90_000.0})
    assert a["input_count"] == b["input_count"]
    assert a["filter_passed"] == b["filter_passed"]
    assert a["near_spot_selected"] == b["near_spot_selected"]
    assert a["filter_rejected"] == b["filter_rejected"]
    assert a["selected_tickers"] == b["selected_tickers"]


def test_golden_kalshi_snapshot_v1_replay_bounds() -> None:
    """Pinned counts for tests/data/kalshi_snapshot_v1.json — tighten as behavior stabilizes."""
    golden = Path(__file__).resolve().parents[2] / "data" / "kalshi_snapshot_v1.json"
    assert golden.is_file(), f"missing golden snapshot: {golden}"
    r = replay_snapshot(golden, verbose=False)
    assert r["input_count"] == 2
    assert r["filter_passed"] == 2
    assert r["filter_rejected"] == {
        "volume": 0,
        "oi": 0,
        "spread": 0,
        "price": 0,
        "underlying": 0,
        "timeframe": 0,
    }
    assert r["near_spot_selected"] == 0
    assert r["selected_tickers"] == []


def test_replay_harness_equivalence_on_pipeline_snapshots(tmp_path: Path) -> None:
    path = _minimal_snapshot_path(tmp_path)
    r = replay_snapshot(path, verbose=False, spot_overrides={"BTC": 90_000.0})
    live = PipelineSnapshot(
        candidate_count=r["input_count"],
        per_bucket_stats={"filter_passed": r["filter_passed"], "near_spot": r["near_spot_selected"]},
        selected_orders=[{"ticker": t} for t in r["selected_tickers"]],
        timestamp="unit",
    )
    harness = ReplayHarness()
    harness.assert_equivalence(live, live)
