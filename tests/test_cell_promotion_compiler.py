"""Promotion-compiler stage tests — identical gate for all five assets.

Uses a synthetic discovery payload; never touches data/decision_audit.db or
the live registry file.
"""

import importlib.util
import os

import pytest


def _load_compiler():
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "scripts", "cell_promotion_compiler.py",
    )
    spec = importlib.util.spec_from_file_location(
        "cell_promotion_compiler", path
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_compiler = _load_compiler()

ASSETS = ("BTC", "ETH", "SOL", "XRP", "DOGE")


def _bucket(asset, side, plo, phi, tlo, thi, *, n=80, lcb=4.0,
            folds=(5.0, 5.0, 5.0), n21=40.0, m21=8.0, day_share=0.2,
            n_markets=None, mkt_share=None, in_domain=None):
    if in_domain is None:
        in_domain = (20 <= plo and phi <= 90 and 120 <= tlo and thi <= 600)
    if n_markets is None:
        n_markets = n
    return {
        "bucket": f"{asset}|{side}|{plo:02d}-{phi:02d}|t{tlo}_{thi}|cf_taker_ask",
        "n": n, "n_markets": n_markets, "max_day_share": day_share,
        "max_market_share": mkt_share,
        "mean": lcb + 4.0, "median": lcb + 4.0,
        "lcb10": lcb, "lcb10_plus1c": lcb - 1.0,
        "mean_plus2c": lcb + 2.0,
        "folds": list(folds),
        "n_eff_7d": n21 / 2, "n_eff_21d": n21,
        "mean_7d": m21, "mean_21d": m21,
        "in_domain": in_domain,
        "verdict": "PROMOTES",
    }


def _touch(verdict="TOUCHABILITY_PASS", rate=0.5, informative=30, lcb=3.0):
    return {
        "verdict": verdict,
        "touchable_rate": rate,
        "informative_n": informative,
        "touchable_lcb10_cents": lcb,
        "label_counts": {"TOUCHABLE": int(informative * rate)},
    }


def _discovery(rows_by_asset):
    return {
        "per_asset": {
            a: {"buckets": rows_by_asset.get(a, []), "status": "x"}
            for a in ASSETS
        }
    }


@pytest.mark.parametrize("asset", ASSETS)
def test_strong_in_domain_bucket_is_pending_feasibility(asset):
    """A statistically clean in-domain bucket can never auto-promote —
    execution feasibility is UNKNOWN, so it caps at CANDIDATE_PENDING_*."""
    disc = _discovery({asset: [_bucket(asset, "no", 40, 50, 120, 300)]})
    cand, rej = _compiler.compile_candidates(disc, {})
    assert len(cand) == 1 and not rej
    row = cand[0]
    assert row["asset"] == asset
    assert row["promotion_status"] == "CANDIDATE_PENDING_EXECUTION_FEASIBILITY"
    assert row["failed_stage"] == "S3_execution_feasibility"
    assert row["fill_feasibility"] == "FILL_FEASIBILITY_UNKNOWN"


@pytest.mark.parametrize("asset", ASSETS)
def test_late_tail_buckets_are_rejected_at_domain_gate(asset):
    """The 0-10c / <120s 'huge counterfactual' cells must never promote."""
    disc = _discovery({
        asset: [
            _bucket(asset, "no", 0, 10, 0, 120, lcb=40.0, in_domain=False),
            _bucket(asset, "yes", 90, 100, 300, 600, lcb=20.0, in_domain=False),
        ]
    })
    cand, rej = _compiler.compile_candidates(disc, {})
    assert not cand and len(rej) == 2
    assert all(r["failed_stage"] == "S2_domain" for r in rej)
    assert all(r["promotion_status"] == "REJECTED" for r in rej)


@pytest.mark.parametrize("asset", ASSETS)
def test_weak_lcb_bucket_rejected_at_statistics(asset):
    disc = _discovery({
        asset: [_bucket(asset, "no", 40, 50, 120, 300, lcb=-1.0)]
    })
    cand, rej = _compiler.compile_candidates(disc, {})
    assert not cand and rej[0]["failed_stage"] == "S1_statistical"


@pytest.mark.parametrize("asset", ASSETS)
def test_thin_recent_evidence_marks_pending_recency(asset):
    """S1/S2/S3 pass but weak 21d decayed evidence -> PENDING_RECENCY_*."""
    disc = _discovery({
        asset: [_bucket(asset, "no", 40, 50, 120, 300, n21=2.0, m21=-1.0)]
    })
    bkey = f"{asset}|no|40-50|t120_300|cf_taker_ask"
    cand, rej = _compiler.compile_candidates(
        disc, {}, touch_map={bkey: _touch()}
    )
    assert len(cand) == 1
    assert cand[0]["promotion_status"] == "CANDIDATE_PENDING_RECENCY_AND_CALIBRATION"
    assert cand[0]["failed_stage"] == "S4_recency_calibration"


@pytest.mark.parametrize("asset", ASSETS)
def test_s3_unknown_caps_before_recency(asset):
    """Without touchability evidence the row can never reach S4 — thin
    recency is irrelevant because feasibility is the first open blocker."""
    disc = _discovery({
        asset: [_bucket(asset, "no", 40, 50, 120, 300, n21=2.0, m21=-1.0)]
    })
    cand, rej = _compiler.compile_candidates(disc, {})
    assert len(cand) == 1
    assert cand[0]["promotion_status"] == "CANDIDATE_PENDING_EXECUTION_FEASIBILITY"
    assert cand[0]["failed_stage"] == "S3_execution_feasibility"


@pytest.mark.parametrize("asset", ASSETS)
def test_touchability_pass_with_good_recency_is_ready_for_approval(asset):
    """S3 pass + S4 pass -> CANDIDATE_READY_FOR_APPROVAL, never APPROVED —
    only a human copying the row into the live yaml completes deployment."""
    disc = _discovery({asset: [_bucket(asset, "no", 40, 50, 120, 300)]})
    bkey = f"{asset}|no|40-50|t120_300|cf_taker_ask"
    cand, rej = _compiler.compile_candidates(
        disc, {}, touch_map={bkey: _touch()}
    )
    assert len(cand) == 1 and not rej
    row = cand[0]
    assert row["promotion_status"] == "CANDIDATE_READY_FOR_APPROVAL"
    assert row["fill_feasibility"] == "TOUCHABILITY_PASS"
    assert row["maker_touchable_rate"] == 0.5
    assert row["failed_stage"] is None


@pytest.mark.parametrize("asset", ASSETS)
def test_touchability_fail_rejects(asset):
    """A cell that is only profitable at taker prices but never touchable
    passively must be rejected at S3, not promoted."""
    disc = _discovery({asset: [_bucket(asset, "no", 40, 50, 120, 300)]})
    bkey = f"{asset}|no|40-50|t120_300|cf_taker_ask"
    cand, rej = _compiler.compile_candidates(
        disc, {},
        touch_map={bkey: _touch(verdict="TOUCHABILITY_FAIL", rate=0.05)},
    )
    assert not cand and len(rej) == 1
    assert rej[0]["failed_stage"] == "S3_execution_feasibility"
    assert rej[0]["promotion_status"] == "REJECTED"


@pytest.mark.parametrize("asset", ASSETS)
def test_few_distinct_markets_rejected(asset):
    """80 observations concentrated in 30 markets is not independent
    evidence — the S1b concentration gate rejects it."""
    disc = _discovery({
        asset: [_bucket(asset, "no", 40, 50, 120, 300, n_markets=30)]
    })
    cand, rej = _compiler.compile_candidates(disc, {})
    assert not cand and rej[0]["failed_stage"] == "S1b_market_concentration"
    assert "distinct markets" in rej[0]["exclusion_reason"]


@pytest.mark.parametrize("asset", ASSETS)
def test_single_market_dominance_rejected(asset):
    """One market contributing >5% of observations fails independence."""
    disc = _discovery({
        asset: [_bucket(asset, "no", 40, 50, 120, 300, n_markets=80,
                        mkt_share=0.12)]
    })
    cand, rej = _compiler.compile_candidates(disc, {})
    assert not cand and rej[0]["failed_stage"] == "S1b_market_concentration"
    assert "max_market_share" in rej[0]["exclusion_reason"]


@pytest.mark.parametrize("asset", ASSETS)
def test_already_live_cell_flagged(asset):
    """A bucket matching a live-registry cell reports LIVE_PROVISIONAL — it
    is measuring, not pending promotion."""
    disc = _discovery({asset: [_bucket(asset, "no", 40, 50, 120, 300)]})
    live = {asset: [f"{asset.lower()}_no_40_50_t120_300"]}
    cand, _rej = _compiler.compile_candidates(disc, live)
    assert cand[0]["already_live"] is True
    assert cand[0]["promotion_status"] == "LIVE_PROVISIONAL"


@pytest.mark.parametrize("asset", ASSETS)
def test_small_sample_never_promotes(asset):
    disc = _discovery({
        asset: [_bucket(asset, "no", 40, 50, 120, 300, n=20, lcb=9.0)]
    })
    cand, rej = _compiler.compile_candidates(disc, {})
    assert not cand and rej[0]["failed_stage"] == "S1_statistical"


# ---------------------------------------------------------------------------
# Touchability labeler — honest UNKNOWN, never fabricated fill probability
# ---------------------------------------------------------------------------

def _load_touch():
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "scripts", "touchability_labels.py",
    )
    spec = importlib.util.spec_from_file_location("touchability_labels", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_tl = _load_touch()


def _snap(ts, no_bid, no_ask, age_ms=100.0, crossed=0):
    return {
        "ts": ts, "yes_bid": 100 - no_ask, "yes_ask": 100 - no_bid,
        "no_bid": no_bid, "no_ask": no_ask, "age_ms": age_ms,
        "crossed": crossed, "exec": 1, "seq": None,
    }


def _row(px=45.0, ts=1000.0, close_ts=1900.0):
    return {
        "asset": "BTC", "side": "no", "ticker": "KXBTC15M-T",
        "ts": ts, "cf": 10.0, "px": px, "tte": 120,
        "close_ts": close_ts,
        "bucket": "BTC|no|40-50|t120_300|cf_taker_ask",
    }


def test_touchable_when_forward_ask_reaches_limit():
    """Resting bid at px-1=44 fills plausibly when no_ask descends to 44."""
    book = [
        _snap(1000.0, 40, 45),
        _snap(1010.0, 41, 44),   # ask descended to our limit
        _snap(1040.0, 41, 44),
    ]
    label, limit = _tl.classify_row(_row(), book)
    assert label == "TOUCHABLE" and limit == 44.0


def test_not_touchable_when_window_fully_covered():
    """Ask stays at 46 through a covered window -> NOT_TOUCHABLE."""
    book = [
        _snap(1000.0, 40, 45),
        _snap(1005.0, 40, 46),
        _snap(1040.0, 41, 46),   # span 35s >= 50% of the 60s window
    ]
    label, _ = _tl.classify_row(_row(), book)
    assert label == "NOT_TOUCHABLE"


def test_unknown_when_forward_coverage_insufficient():
    """One sliver forward snapshot cannot prove a 60s window — UNKNOWN."""
    book = [
        _snap(1000.0, 40, 45),
        _snap(1003.0, 40, 46),   # span 3s — the gap could hide a touch
    ]
    label, _ = _tl.classify_row(_row(), book)
    assert label == "UNKNOWN_BOOK_HISTORY"


def test_expired_before_touch_when_market_closes():
    book = [_snap(1000.0, 40, 45)]
    label, _ = _tl.classify_row(_row(close_ts=1020.0), book)
    assert label == "EXPIRED_BEFORE_TOUCH"


def test_stale_book_at_decision():
    book = [_snap(1000.0, 40, 45, age_ms=9000.0)]
    label, _ = _tl.classify_row(_row(), book)
    assert label == "STALE_BOOK"


def test_crossing_only_when_book_inverted():
    book = [_snap(1000.0, 46, 45)]   # bid > ask — no passive price exists
    label, _ = _tl.classify_row(_row(), book)
    assert label == "CROSSING_ONLY"


def test_cell_verdict_unknown_below_informative_minimum():
    """19 informative rows, even at 100% touchable, cannot prove the cell —
    the verdict is UNKNOWN, not pass/fail."""
    labels = ["TOUCHABLE"] * 19
    v = _tl.cell_verdict(labels, [10.0] * 19)
    assert v["verdict"] == "FILL_FEASIBILITY_UNKNOWN"
    assert v["informative_n"] == 19
    assert v["touchable_rate"] == 1.0


def test_cell_verdict_unknown_rows_excluded_from_rate():
    """UNKNOWN/STALE rows do not dilute or inflate the touchable rate."""
    labels = ["TOUCHABLE"] * 10 + ["NOT_TOUCHABLE"] * 10 \
        + ["UNKNOWN_BOOK_HISTORY"] * 50 + ["STALE_BOOK"] * 5
    v = _tl.cell_verdict(labels, [10.0] * 10 + [5.0] * 65)
    assert v["informative_n"] == 20
    assert v["touchable_rate"] == 0.5


def test_cell_verdict_pass_and_fail():
    pnls = [12.0] * 12
    ok = _tl.cell_verdict(["TOUCHABLE"] * 12 + ["NOT_TOUCHABLE"] * 18,
                          pnls + [0.0] * 18)
    assert ok["verdict"] == "TOUCHABILITY_PASS"
    bad = _tl.cell_verdict(["TOUCHABLE"] * 2 + ["NOT_TOUCHABLE"] * 28,
                           [12.0] * 2 + [0.0] * 28)
    assert bad["verdict"] == "TOUCHABILITY_FAIL"
