"""Regression tests for the survivorship-bias repair in the live entry
evidence artifact (2026-10-15).

``_refresh_live_entry_evidence`` previously aggregated only ``ENTER``
fills, so cells measured "cohorts yesterday's gates already admitted" —
a bad gate could never accumulate the evidence that would clear it.  The
refresh now also joins settled ``NO_TRADE`` decisions' per-side vetoed
candidates (``strategy_decision_side_ev``) at their executable prices.

These tests pin the aggregation semantics in ``build_cells``:

- ``mkey``-keyed normalization: repeated evals of one (ticker, side)
  collapse to ~1 effective observation, so eval-density cannot inflate
  a cell's n_eff.
- ``src`` provenance counters: n_fill / n_veto recorded per cell.
- Fill rows keep per-ticker normalization (unchanged legacy behavior).
"""

import time

from merid.prediction import evidence_policy as ep


def _row(**kw):
    base = {
        "asset": "BTC",
        "side": "no",
        "ticker": "KXBTC15M-T",
        "decision_id": "d",
        "entry_cents": 40,
        "settled_yes": 1,
        "settled_at": time.time() - 3600.0,
        "seconds_to_close": 400.0,
        "src": "veto",
    }
    base.update(kw)
    return base


def test_veto_mkey_normalizes_repeated_evals_to_one_market_side():
    """200 vetoed evals of the same (ticker, side) ~= 1 effective sample."""
    now = time.time()
    rows = [
        _row(decision_id=f"d{i}", mkey="KXBTC15M-T|no", settled_at=now - 3600)
        for i in range(200)
    ]
    cells = ep.build_cells(rows, half_life_days=7, now=now)
    c = cells["BTC|no|25-49|mid"]
    # Per-(ticker,side) normalization: the market contributes ~mweight,
    # not 200 samples.
    assert c["n_eff"] <= 1.01
    assert c["n_raw"] == 200
    assert c["n_veto"] == 200
    assert c["n_fill"] == 0
    assert c["n_markets"] == 1


def test_veto_mkey_splits_sides_of_same_ticker():
    """A market's yes-side and no-side veto cohorts normalize separately."""
    now = time.time()
    rows = []
    for i in range(50):
        rows.append(
            _row(decision_id=f"y{i}", side="yes", mkey="T1|yes",
                 settled_at=now - 3600)
        )
        rows.append(
            _row(decision_id=f"n{i}", side="no", mkey="T1|no",
                 settled_at=now - 3600)
        )
    cells = ep.build_cells(rows, half_life_days=7, now=now)
    assert cells["BTC|yes|25-49|mid"]["n_eff"] <= 1.01
    assert cells["BTC|no|25-49|mid"]["n_eff"] <= 1.01
    assert cells["BTC|yes|25-49|mid"]["n_markets"] == 1
    assert cells["BTC|no|25-49|mid"]["n_markets"] == 1


def test_fill_and_veto_rows_share_cell_with_provenance():
    """A fill row (mkey=ticker) and veto rows (ticker|side) both aggregate
    into the same cell with distinct n_fill / n_veto provenance."""
    now = time.time()
    rows = [
        _row(src="fill", mkey="KXFILL", ticker="KXFILL",
             settled_at=now - 3600),
    ] + [
        _row(decision_id=f"v{i}", mkey="KXFILL|no",
             settled_at=now - 3600)
        for i in range(10)
    ]
    cells = ep.build_cells(rows, half_life_days=7, now=now)
    c = cells["BTC|no|25-49|mid"]
    assert c["n_fill"] == 1
    assert c["n_veto"] == 10
    assert c["n_markets"] == 2  # fill market + veto market-side
    # ~2 effective samples: one from the filled market, one from the
    # normalized veto cohort.
    assert 1.9 <= c["n_eff"] <= 2.1


def test_rows_without_mkey_fall_back_to_ticker():
    """Legacy callers (no mkey/src) keep per-ticker normalization."""
    now = time.time()
    rows = [
        _row(decision_id=f"d{i}", settled_at=now - 3600)
        for _ in range(3)
        for i in range(1)
    ]
    for i, r in enumerate(rows):
        r.pop("src", None)
        r["decision_id"] = f"d{i}"
    cells = ep.build_cells(rows, half_life_days=7, now=now)
    c = cells["BTC|no|25-49|mid"]
    assert c["n_markets"] == 1
    assert c["n_fill"] == 0 and c["n_veto"] == 0


def test_won_flag_scores_vetoed_side_against_settlement():
    """A vetoed NO-side candidate 'wins' iff the market settled NO."""
    now = time.time()
    win = ep.build_cells(
        [_row(mkey="M1|no", settled_yes=0, settled_at=now - 3600)],
        half_life_days=7, now=now,
    )["BTC|no|25-49|mid"]
    assert win["w"] > 0.0 and win["l"] == 0.0
    lose = ep.build_cells(
        [_row(mkey="M2|no", settled_yes=1, settled_at=now - 3600)],
        half_life_days=7, now=now,
    )["BTC|no|25-49|mid"]
    assert lose["l"] > 0.0 and lose["w"] == 0.0
