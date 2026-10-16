"""FIX 14: streaming settlement-driven calibration overlay."""
import json
import os

import pytest

from merid.prediction import streaming_calibration as sc


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("MERID_STREAM_CAL_PATH", str(tmp_path / "sc.json"))
    monkeypatch.setenv("MERID_STREAM_CAL_ENABLED", "1")
    monkeypatch.delenv("MERID_STREAM_CAL_HALFLIFE_DAYS", raising=False)
    monkeypatch.delenv("MERID_STREAM_CAL_PRIOR_K", raising=False)
    monkeypatch.delenv("MERID_STREAM_CAL_MIN_NEFF", raising=False)
    monkeypatch.delenv("MERID_STREAM_CAL_BUFFER", raising=False)
    sc.reset_cache()
    yield
    sc.reset_cache()


def _row(asset="ETH", side="yes", price=30.0, p=0.55, won=False,
         tte=400.0, sat=1_000_000.0, ts=999_900.0, ticker="KXETH-T1"):
    return {
        "asset": asset, "side": side, "ticker": ticker,
        "entry_cents": price, "seconds_to_close": tte,
        "calibrated_probability": p, "settled_yes": won if side == "yes" else not won,
        "settled_at": sat, "decision_ts": ts,
        "src": "veto", "mkey": f"{ticker}|{side}",
    }


def test_overlay_tightens_inflated_claim():
    """A cell where reality wins far less than claimed bounds p down."""
    # 12 observations of claimed 0.55, only 25% actually won.
    rows = [
        _row(ticker=f"KXETH-T{i}", won=(i < 3), sat=1_000_000.0 + i)
        for i in range(12)
    ]
    n = sc.update_from_rows(rows, now=1_000_100.0)
    assert n == 12
    b = sc.streaming_bound("ETH", "yes", 30.0, 400.0, now=1_000_100.0)
    assert b is not None
    # posterior: ~(3 + 20*0.55)/(12+20) = 0.4375; this cohort also trips the
    # CUSUM overconfidence alarm, which strips the +0.05 honesty buffer.
    assert b == pytest.approx(0.4375, abs=2e-3)
    assert sc.drift_alarm("ETH", "yes", 30.0, 400.0, now=1_000_100.0)[
        "direction"
    ] == "over"
    # The bound tightens an inflated 0.55 claim but never lifts a lower one.
    assert sc.corrected_probability(
        "ETH", "yes", 30.0, 400.0, 0.55, now=1_000_100.0
    ) < 0.55
    assert sc.corrected_probability(
        "ETH", "yes", 30.0, 400.0, 0.40, now=1_000_100.0
    ) == 0.40


def test_watermark_idempotency():
    """Re-scanning the same window must not re-apply observations."""
    rows = [_row(ticker=f"KXETH-T{i}", sat=1_000_000.0) for i in range(10)]
    assert sc.update_from_rows(rows, now=1_000_100.0) == 10
    assert sc.update_from_rows(rows, now=1_000_200.0) == 0
    st = sc.load_state(force=True)
    cell = next(iter(st["cells"].values()))
    assert cell["n"] == pytest.approx(10.0)


def test_fill_and_veto_same_market_side_dedup():
    """A fill row and veto rows for one (ticker, side) = one observation."""
    rows = [
        _row(side="no", ticker="KXSOL-T1", sat=1_000_000.0, ts=999_800.0,
             p=0.50, won=True),
        _row(side="no", ticker="KXSOL-T1", sat=1_000_000.0, ts=999_700.0,
             p=0.45, won=True),
        _row(side="no", ticker="KXSOL-T1", sat=1_000_000.0, ts=999_900.0,
             p=0.60, won=True),
    ]
    assert sc.update_from_rows(rows, now=1_000_100.0) == 1
    st = sc.load_state(force=True)
    cell = next(iter(st["cells"].values()))
    assert cell["n"] == pytest.approx(1.0)
    # The newest eval's claim (0.60) is the one retained.
    assert cell["wp"] == pytest.approx(0.60)


def test_pav_monotonicity_across_price():
    """A non-monotone measured pattern is isotonized over the price axis."""
    rows = []
    # 25-49 bucket: claimed 0.40 won 60% (underconfident); 50-74: claimed
    # 0.60 won 20% (overconfident) -> raw means invert; PAV must flatten.
    for i in range(12):
        rows.append(_row(price=30.0, p=0.40, won=True,
                         ticker=f"KXA-{i}", sat=1_000_000.0 + i))
    for i in range(12):
        rows.append(_row(price=60.0, p=0.60, won=(i < 2),
                         ticker=f"KXB-{i}", sat=1_000_050.0 + i))
    sc.update_from_rows(rows, now=1_000_200.0)
    b_lo = sc.streaming_bound("ETH", "yes", 30.0, 400.0, now=1_000_200.0)
    b_hi = sc.streaming_bound("ETH", "yes", 60.0, 400.0, now=1_000_200.0)
    assert b_lo is not None and b_hi is not None
    assert b_lo <= b_hi + 1e-9


def test_sparse_cells_pool_and_missing_returns_none():
    """Under min_neff the exact cell falls back to the pooled curve; a
    wholly unmeasured cohort returns None (pass-through)."""
    rows = [_row(price=30.0, p=0.50, won=False,
                 ticker=f"KXC-{i}", sat=1_000_000.0 + i) for i in range(5)]
    sc.update_from_rows(rows, now=1_000_100.0)
    # 5 < min_neff(8) exact -> pooled asset mean still gives a bound.
    b = sc.streaming_bound("ETH", "yes", 30.0, 400.0, now=1_000_100.0)
    assert b is not None
    # Unmeasured asset -> pass-through.
    assert sc.streaming_bound("BTC", "yes", 30.0, 400.0, now=1_000_100.0) is None
    assert sc.corrected_probability(
        "BTC", "yes", 30.0, 400.0, 0.6, now=1_000_100.0
    ) == 0.6


def test_cusum_drift_alarm_and_bound_tightening():
    """FIX 15: sustained overconfidence trips the drift alarm; the alarm
    strips the honesty buffer and exposes an 'over' alarm for the reserve."""
    # residual = claim - outcome = 0.55 - 0 = 0.55 per obs; slack 0.05 ->
    # cusum grows +0.5/obs; h=0.5 trips after 2 observations.
    rows = [_row(ticker=f"KXD-{i}", p=0.55, won=False,
                 sat=1_000_000.0 + i) for i in range(10)]
    sc.update_from_rows(rows, now=1_000_100.0)
    al = sc.drift_alarm("ETH", "yes", 30.0, 400.0, now=1_000_100.0)
    assert al is not None and al["direction"] == "over"
    # While alarmed the bound loses the +0.05 buffer.
    b = sc.streaming_bound("ETH", "yes", 30.0, 400.0, now=1_000_100.0)
    assert b == pytest.approx(
        (0.0 + 20 * 0.55) / (10 + 20), abs=2e-3
    )
    # A different side/cell with no drift -> no alarm.
    assert sc.drift_alarm("ETH", "no", 30.0, 400.0, now=1_000_100.0) is None


def test_cusum_no_alarm_when_model_matches():
    """Residuals inside the slack never accumulate."""
    rows = [_row(ticker=f"KXE-{i}", p=0.52, won=(i % 2 == 0),
                 sat=1_000_000.0 + i) for i in range(20)]
    sc.update_from_rows(rows, now=1_000_100.0)
    assert sc.drift_alarm("ETH", "yes", 30.0, 400.0, now=1_000_100.0) is None


def test_bound_detail_provenance():
    """``streaming_bound_detail`` names whether the bound came from the
    candidate's own slice (alarm-aware) or a pooled/alarm-blind fallback."""
    # Dense exact cell (n>=8) -> "exact".
    rows = [
        _row(ticker=f"KXP-{i}", p=0.55, won=(i < 4), sat=1_000_000.0 + i)
        for i in range(10)
    ]
    sc.update_from_rows(rows, now=1_000_100.0)
    d = sc.streaming_bound_detail("ETH", "yes", 30.0, 400.0, now=1_000_100.0)
    assert d == {"bound": d["bound"], "source": "exact"}
    assert d["bound"] is not None
    # Sparse exact cell -> pooled fallback -> "pooled".
    d2 = sc.streaming_bound_detail("ETH", "yes", 70.0, 400.0, now=1_000_100.0)
    assert d2["source"] == "pooled" and d2["bound"] is not None
    # Unmeasured cohort -> pass-through, no source.
    d3 = sc.streaming_bound_detail("BTC", "yes", 30.0, 400.0, now=1_000_100.0)
    assert d3 == {"bound": None, "source": None}


def test_decay_shrinks_stale_evidence():
    """A stale cell's influence decays with the configured halflife."""
    rows = [_row(ticker=f"KXD-{i}", p=0.55, won=False,
                 sat=1_000_000.0 + i) for i in range(16)]
    sc.update_from_rows(rows, now=1_000_050.0)
    fresh = sc.streaming_bound("ETH", "yes", 30.0, 400.0, now=1_000_050.0)
    # 20 days later (2 halflives): n_eff ~4 < 8 -> pooled fallback path.
    stale = sc.streaming_bound("ETH", "yes", 30.0, 400.0,
                               now=1_000_050.0 + 20 * 86400.0)
    assert fresh is not None and stale is not None
    # Decayed bound relaxes toward the cell's claimed mean (0.55) + buffer.
    assert stale > fresh
