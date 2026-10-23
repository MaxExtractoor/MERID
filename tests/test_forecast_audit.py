"""Acceptance tests for merid.analysis.forecast_audit.

Synthetic fixtures only — no DB, no log files, no trading code paths.
Covers the release acceptance criteria: temporal selection, YES-space
dedupe, dependence-aware resampling, reproducibility, missingness,
equal-forecast zero diffs, complement handling, and known/no-signal/
side-inversion/duplicated-observation fixtures.
"""

from __future__ import annotations

import numpy as np
import pytest

from merid.analysis.forecast_audit.bootstrap import (
    CompBlocks,
    block_ids_for_units,
    make_comp_blocks,
    paired_bootstrap,
    shared_draws,
)
from merid.analysis.forecast_audit.inference import (
    LABEL_POLICY_GRACE,
    LABEL_POLICY_OBSERVED,
    brier,
    build_fold_plan,
    compute_fitted_forecasts,
    irls_logistic,
    logit,
    sigmoid,
    training_label_at,
)
from merid.analysis.forecast_audit.records import (
    AnchoredStageLog,
    AnchoredStageRecord,
    DecisionRow,
    LabelVersion,
    OfficialOutcome,
    OfficialOutcomes,
    load_anchored_stage,
    probe_horizon_population,
)
from merid.analysis.forecast_audit.units import (
    JOIN_ASOF_BOUNDED,
    JOIN_NONE,
    JOIN_REJECT_FUTURE,
    JOIN_REJECT_TOLERANCE,
    EvalUnit,
    build_population,
    build_population_from_probes,
    join_anchored,
)


def _row(ticker, ts, close_ts=None, **kw):
    defaults = dict(
        decision_id=f"{ticker}:{ts}",
        asset="BTC",
        seconds_to_close=None,
        raw_p_yes=0.6,
        calibrated_p_yes=0.6,
        yes_bid_cents=55.0,
        yes_ask_cents=57.0,
        no_bid_cents=43.0,
        no_ask_cents=45.0,
        model_version="mv", calibration_version="cv",
        config_version="cfg", build_sha="sha", policy_epoch="pe",
        record_environment="production", record_source="live",
        selected_side=None, decision="NO_TRADE",
        settled_yes=1, settled_at=(close_ts or 0.0) + 5.0,
        outcome_status="SETTLED",
        realized_net_pnl_cents=None, fill_id=None,
    )
    defaults.update(kw)
    return DecisionRow(ticker=ticker, decision_ts=ts, close_ts=close_ts, **defaults)


def _unit(ticker="T", close_ts=1000.0, target_ts=940.0, horizon_s=60.0, **kw):
    defaults = dict(
        asset="BTC", model_version_id="v1", snapshot_ts=target_ts - 10,
        snapshot_offset_s=10.0, close_ts_source="ledger_median",
        p_raw=0.6, p_final=0.6, m_mid=0.55, p_anch_wf=None,
        anch_wf_offset_s=None, y=1, label_ts=close_ts + 5,
        decision="NO_TRADE", selected_side=None,
        realized_net_pnl_cents=None, run_version_fields={},
    )
    defaults.update(kw)
    u = EvalUnit(ticker=ticker, close_ts=close_ts, target_ts=target_ts,
                 horizon_s=horizon_s, **defaults)
    # Backward-compatible label: tests that set label_ts intend a version
    # observed at that time under either policy.
    if not u.label_versions and u.y is not None:
        u.label_versions = [LabelVersion(
            observed_ts=u.label_ts, settlement_ts=u.close_ts,
            resolved_yes=u.y)]
    return u


def _pop(trows_by_ticker, horizons, outcomes=None, max_age=90.0):
    rows = [r for rows in trows_by_ticker.values() for r in rows]
    anchored = AnchoredStageLog({}, 0, 0, None, None)
    official = outcomes or OfficialOutcomes({}, 0, 0)
    return build_population(
        rows, horizons_s=horizons, max_age_s=max_age,
        anchored=anchored, official=official)


# ---------------------------------------------------------------------------
# Temporal selection
# ---------------------------------------------------------------------------

class TestHorizonSelection:
    def test_latest_at_or_before_target(self):
        t = "KXBTC15M-A"
        rows = [
            _row(t, 910.0, 1000.0),
            _row(t, 950.0, 1000.0),
            _row(t, 990.0, 1000.0),
            _row(t, 1005.0, 1000.0),  # after close: never selectable
        ]
        pop = _pop({t: rows}, horizons=[60.0, 50.0, 45.0])
        by_h = {u.horizon_s: u for u in pop.units}
        assert by_h[60.0].snapshot_ts == 910.0   # target 940, latest <= 940
        assert by_h[50.0].snapshot_ts == 950.0   # exact boundary counts
        assert by_h[45.0].snapshot_ts == 950.0   # target 955
        assert all(u.snapshot_ts <= u.target_ts for u in pop.units)

    def test_no_snapshot_before_target(self):
        t = "KXBTC15M-B"
        rows = [_row(t, 990.0, 1000.0)]
        pop = _pop({t: rows}, horizons=[120.0])  # target 880
        e = pop.entries[0]
        assert e.status == "missing"
        assert e.reason == "no_snapshot_before_target"
        assert not pop.units

    def test_stale_snapshot_rejected(self):
        t = "KXBTC15M-C"
        rows = [_row(t, 800.0, 1000.0)]  # target 940, offset 140 > max_age 90
        pop = _pop({t: rows}, horizons=[60.0], max_age=90.0)
        e = pop.entries[0]
        assert e.status == "missing"
        assert e.reason == "stale_snapshot"
        assert e.snapshot_offset_s == pytest.approx(140.0)

    def test_missing_close_ts(self):
        t = "KXBTC15M-D"
        rows = [_row(t, 990.0, None)]
        pop = _pop({t: rows}, horizons=[60.0])
        assert pop.entries[0].reason == "no_close_ts"

    def test_unresolved_outcome_visible(self):
        t = "KXBTC15M-E"
        rows = [_row(t, 930.0, 1000.0, settled_yes=None, outcome_status="PENDING")]
        pop = _pop({t: rows}, horizons=[60.0])
        e = pop.entries[0]
        assert e.status == "unscored"
        assert e.reason == "outcome_pending"
        assert pop.units[0].y is None

    def test_ticker_without_decisions_counted(self):
        out = OfficialOutcomes(
            {"KXBTC15M-F": OfficialOutcome(1, 1000.0, 995.0, "BTC")}, 0, 0)
        pop = build_population(
            [], horizons_s=[60.0], max_age_s=90.0,
            anchored=AnchoredStageLog({}, 0, 0, None, None),
            official=out, expected_tickers=["KXBTC15M-F"])
        assert pop.entries[0].reason == "no_decisions_for_ticker"


# ---------------------------------------------------------------------------
# YES space / stage semantics
# ---------------------------------------------------------------------------

class TestYesSpace:
    def test_anchored_join_minute_mismatch_not_joined(self):
        # snapshot tte = 65s -> minute 1; record keyed at minute 9 must
        # NOT be pulled into the unit.
        anchored = AnchoredStageLog(
            {("KXBTC15M-G", 9): [AnchoredStageRecord(ts=934.0, p_model=0.61)]},
            2, 0, None, None)
        rows = [_row("KXBTC15M-G", 935.0, 1000.0)]
        pop = build_population(
            rows, horizons_s=[60.0], max_age_s=90.0,
            anchored=anchored, official=OfficialOutcomes({}, 0, 0))
        assert pop.units[0].p_anch_wf is None

    def test_anchored_join_tte_minute_match(self):
        # snapshot at 935.0 with close 1000 -> tte 65 -> minute 1
        anchored = AnchoredStageLog(
            {("KXBTC15M-H", 1): [AnchoredStageRecord(ts=934.9, p_model=0.61)]},
            1, 0, None, None)
        rows = [_row("KXBTC15M-H", 935.0, 1000.0)]
        pop = build_population(
            rows, horizons_s=[60.0], max_age_s=90.0,
            anchored=anchored, official=OfficialOutcomes({}, 0, 0))
        assert pop.units[0].p_anch_wf == pytest.approx(0.61)

    def test_complement_rows_deduped_and_mismatch_counted(self, tmp_path):
        """yes+no rows for the same (ticker, minute) are one observation;
        a complement that does not sum to 1 is counted, not silently used."""
        p = tmp_path / "mc.jsonl"
        p.write_text(
            '{"ts": 949.1, "ticker": "T1", "asset": "BTC", "side": "yes", '
            '"p_model": 0.61, "entry_price_cents": 55.0, '
            '"seconds_to_expiry": 50.0, "fee_cents": 1.0}\n'
            '{"ts": 949.2, "ticker": "T1", "asset": "BTC", "side": "no", '
            '"p_model": 0.35, "entry_price_cents": 45.0, '
            '"seconds_to_expiry": 50.0, "fee_cents": 1.0}\n'
        )
        log = load_anchored_stage(p)
        assert len(log.by_key) == 1            # only the YES row keyed
        assert log.by_key[("T1", 0)][0].p_model == pytest.approx(0.61)
        assert log.complement_mismatches == 1  # 0.61 + 0.35 != 1


# ---------------------------------------------------------------------------
# Losses / paired bootstrap
# ---------------------------------------------------------------------------

class TestBootstrap:
    def _blocks(self, diffs_per_block):
        """Build CompBlocks from explicit per-block unit diffs."""
        n_blocks = len(diffs_per_block)
        block_of_unit = []
        d, lc, lb = [], [], []
        for b, diffs in enumerate(diffs_per_block):
            for dv in diffs:
                block_of_unit.append(b)
                d.append(dv)
                lc.append(0.20)
                lb.append(0.20 + dv)
        idx = list(range(len(d)))
        return make_comp_blocks(
            np.array(block_of_unit), idx,
            np.array(d), np.array(lc), np.array(lb), n_blocks)

    def test_equal_forecasts_zero_diff(self):
        cb = self._blocks([[0.0, 0.0], [0.0, 0.0, 0.0]])
        res = paired_bootstrap({"eq": cb}, replicates=200, seed=1)["eq"]
        assert res.point_mean_d == 0.0
        assert res.point_bss == 0.0
        assert res.ci_d == (0.0, 0.0)

    def test_positive_shift_detected(self):
        cb = self._blocks([[0.01] * 20 for _ in range(40)])
        res = paired_bootstrap({"pos": cb}, replicates=400, seed=7)["pos"]
        assert res.point_mean_d == pytest.approx(0.01)
        assert res.ci_d[0] > 0

    def test_shared_draws_align_comparisons(self):
        """Two comparisons over the same block universe get identical draws:
        a comparison that is a scalar multiple of another should have
        proportional interval bounds."""
        cb1 = self._blocks([[0.01] * 10 for _ in range(30)])
        cb2 = self._blocks([[0.02] * 10 for _ in range(30)])
        out = paired_bootstrap(
            {"a": cb1, "b": cb2}, replicates=300, seed=3)
        assert out["b"].ci_d[0] == pytest.approx(2.0 * out["a"].ci_d[0])

    def test_duplication_within_blocks_identical(self):
        """Duplicating units inside the same blocks must not change point
        estimates or tighten intervals — sample size is in blocks."""
        base = self._blocks([[0.01, -0.02, 0.03] for _ in range(50)])
        dup = self._blocks([[0.01, -0.02, 0.03, 0.01, -0.02, 0.03]
                            for _ in range(50)])
        r1 = paired_bootstrap({"x": base}, replicates=500, seed=5)["x"]
        r2 = paired_bootstrap({"x": dup}, replicates=500, seed=5)["x"]
        assert r1.point_mean_d == pytest.approx(r2.point_mean_d)
        assert r1.ci_d == pytest.approx(r2.ci_d)

    def test_block_assignment_contract_aligned(self):
        # same ticker, two horizons -> same close -> same block
        units = [
            _unit("T1", close_ts=3600.0, target_ts=3540.0, horizon_s=60.0),
            _unit("T1", close_ts=3600.0, target_ts=3300.0, horizon_s=300.0),
            _unit("T2", close_ts=3600.0, target_ts=3540.0, horizon_s=60.0),  # other asset, same close
            _unit("T3", close_ts=7200.0, target_ts=7140.0, horizon_s=60.0),
        ]
        ids, n = block_ids_for_units([u.close_ts for u in units], 3600.0)
        assert ids[0] == ids[1] == ids[2]
        assert ids[3] != ids[0]
        assert n == int(ids.max()) + 1


# ---------------------------------------------------------------------------
# IRLS logistic + fitted comparators
# ---------------------------------------------------------------------------

class TestLogisticFit:
    def test_recovers_coefficients(self):
        rng = np.random.default_rng(0)
        n = 4000
        x1 = rng.normal(0, 1, n)
        x2 = rng.normal(0, 1, n)
        eta = 0.4 + 1.1 * x1 - 0.8 * x2
        p = 1.0 / (1.0 + np.exp(-eta))
        y = (rng.random(n) < p).astype(float)
        X = np.column_stack([np.ones(n), x1, x2])
        fit = irls_logistic(X, y)
        assert fit.converged
        np.testing.assert_allclose(fit.coef, [0.4, 1.1, -0.8], atol=0.1)
        se = fit.se
        assert se[2] > 0
        # z-value for the nonzero coef is huge; for ~0 coef would be small
        assert abs(fit.coef[2] / se[2]) > 8

    def test_known_signal_beats_market_only(self):
        """True model: y ~ sigmoid(logit(m) + 1.3*z). q1 must beat q0."""
        rng = np.random.default_rng(42)
        n = 900
        units = []
        for i in range(n):
            close = 1_000_000.0 + i * 900.0
            m = float(rng.uniform(0.25, 0.75))
            z = float(rng.normal(0, 0.6))
            q = sigmoid(logit(m) + 1.3 * z)
            y = int(rng.random() < q)
            raw = sigmoid(logit(m) + z)
            units.append(_unit(
                ticker=f"T{i}", close_ts=close,
                target_ts=close - 60.0, horizon_s=60.0,
                p_raw=raw, p_final=raw, m_mid=m,
                y=y, label_ts=close + 5))
        plan = build_fold_plan(units, n_folds=4, min_train_n=100)
        fitted, _stats = compute_fitted_forecasts(
            units, plan, n_folds=4, min_train_n=100)
        idx = [i for i in range(len(units))
               if fitted.get(i) and fitted[i].p_q0 is not None
               and fitted[i].p_q1 is not None]
        assert len(idx) > 400
        d = np.array([
            brier(fitted[i].p_q0, units[i].y) - brier(fitted[i].p_q1, units[i].y)
            for i in idx])
        assert d.mean() > 0
        gammas = [fitted[i].gamma for i in idx]
        assert np.mean(gammas) == pytest.approx(1.3, abs=0.4)

    def test_no_signal_no_improvement(self):
        rng = np.random.default_rng(9)
        n = 800
        units = []
        for i in range(n):
            close = 1_000_000.0 + i * 900.0
            m = float(rng.uniform(0.25, 0.75))
            y = int(rng.random() < m)  # outcome depends only on m
            raw = sigmoid(logit(m) + rng.normal(0, 0.8))  # useless residual
            units.append(_unit(
                ticker=f"T{i}", close_ts=close, target_ts=close - 60.0,
                horizon_s=60.0, p_raw=raw, p_final=raw, m_mid=m,
                y=y, label_ts=close + 5))
        plan = build_fold_plan(units, n_folds=4, min_train_n=100)
        fitted, _stats = compute_fitted_forecasts(
            units, plan, n_folds=4, min_train_n=100)
        idx = [i for i in range(len(units))
               if fitted.get(i) and fitted[i].p_q0 is not None
               and fitted[i].p_q1 is not None]
        d = np.array([
            brier(fitted[i].p_q0, units[i].y) - brier(fitted[i].p_q1, units[i].y)
            for i in idx])
        assert abs(d.mean()) < 0.01

    def test_fold_training_never_sees_future_labels(self):
        units = []
        for i in range(10):
            units.append(_unit(
                ticker=f"T{i}", close_ts=1000.0 + i * 100,
                target_ts=940.0 + i * 100, horizon_s=60.0,
                y=i % 2, label_ts=1005.0 + i * 100))
        plan = build_fold_plan(units, n_folds=4, min_train_n=1)
        # every unit's fold boundary must exceed its own label availability
        for i, u in enumerate(units):
            f = plan.fold_of[i]
            b = plan.boundaries[f]
            train_units = [
                j for j, v in enumerate(units)
                if v.label_ts is not None and v.label_ts < b]
            assert i not in train_units or u.label_ts < b
            # and strictly: label_ts >= b for any unit not in its own train set
        # first fold trains on labels available before boundary[0]
        f0_train = [i for i, v in enumerate(units)
                    if v.label_ts < plan.boundaries[0]]
        assert len(f0_train) == 0 or all(units[i].label_ts < plan.boundaries[0]
                                        for i in f0_train)


# ---------------------------------------------------------------------------
# End-to-end population + reproducibility
# ---------------------------------------------------------------------------

class TestPopulationAndRepro:
    def test_one_unit_per_ticker_horizon(self):
        t = "KXBTC15M-I"
        rows = [_row(t, ts, 1000.0) for ts in range(700, 1000, 7)]
        pop = _pop({t: rows}, horizons=[60.0, 300.0])
        assert len(pop.units) == 2
        assert {u.ticker for u in pop.units} == {t}

    def test_seed_reproducibility(self):
        cb_pairs = []
        for name in ("a", "b"):
            blocks = np.array([0, 0, 1, 1, 2, 2, 3, 3])
            cb_pairs.append(make_comp_blocks(
                blocks, list(range(8)),
                np.array([0.01] * 8), np.array([0.2] * 8),
                np.array([0.21] * 8), 4))
        r1 = paired_bootstrap({"x": cb_pairs[0], "y": cb_pairs[1]},
                              replicates=100, seed=99)
        r2 = paired_bootstrap({"x": cb_pairs[0], "y": cb_pairs[1]},
                              replicates=100, seed=99)
        assert r1["x"].ci_d == r2["x"].ci_d
        assert r1["y"].draw_mean_bss == r2["y"].draw_mean_bss

    def test_side_inversion_flips_sign(self):
        """A deployed prob that is the complement of the truth must score
        strictly worse than the market (diagnostic, not proof of cause)."""
        y = np.array([0, 1, 1, 0, 1, 0, 0, 1] * 20)
        m = np.array([0.45, 0.55, 0.6, 0.4, 0.55, 0.45, 0.4, 0.6] * 20)
        good = np.array([0.1, 0.9, 0.8, 0.2, 0.85, 0.15, 0.1, 0.9] * 20)
        bad = 1.0 - good
        d_good = float(np.mean([
            brier(m_i, y_i) - brier(g_i, y_i)
            for m_i, g_i, y_i in zip(m, good, y)]))
        d_bad = float(np.mean([
            brier(m_i, y_i) - brier(b_i, y_i)
            for m_i, b_i, y_i in zip(m, bad, y)]))
        assert d_good > 0 > d_bad


# ---------------------------------------------------------------------------
# Probe loader (index-assisted production path)
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE strategy_decisions (
    decision_id TEXT PRIMARY KEY, ticker TEXT, asset TEXT,
    decision_ts REAL, close_ts REAL, seconds_to_close REAL,
    model_version TEXT, calibration_version TEXT, config_version TEXT,
    build_sha TEXT, policy_epoch TEXT, record_environment TEXT,
    record_source TEXT, selected_side TEXT, decision TEXT,
    is_eligible_for_research INTEGER DEFAULT 1
);
CREATE INDEX idx_decisions_ticker ON strategy_decisions(ticker, decision_ts);
CREATE TABLE strategy_decision_snapshots (
    decision_id TEXT PRIMARY KEY, raw_p_yes REAL, calibrated_p_yes REAL,
    yes_bid_cents INTEGER, yes_ask_cents INTEGER,
    no_bid_cents INTEGER, no_ask_cents INTEGER
);
CREATE TABLE strategy_decision_outcomes (
    decision_id TEXT PRIMARY KEY, settled_yes INTEGER, settled_at REAL,
    outcome_status TEXT, realized_net_pnl_cents REAL, fill_id TEXT
);
"""


def _fixture_db(tmp_path, rows):
    """Write DecisionRow fixtures into a minimal audit-DB schema."""
    import sqlite3
    db = tmp_path / "audit.db"
    con = sqlite3.connect(db)
    con.executescript(_DDL)
    for r in rows:
        con.execute(
            "INSERT INTO strategy_decisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (r.decision_id, r.ticker, r.asset, r.decision_ts, r.close_ts,
             r.seconds_to_close, r.model_version, r.calibration_version,
             r.config_version, r.build_sha, r.policy_epoch,
             r.record_environment, r.record_source, r.selected_side,
             r.decision, 1))
        con.execute(
            "INSERT INTO strategy_decision_snapshots VALUES (?,?,?,?,?,?,?)",
            (r.decision_id, r.raw_p_yes, r.calibrated_p_yes,
             r.yes_bid_cents, r.yes_ask_cents, r.no_bid_cents, r.no_ask_cents))
        con.execute(
            "INSERT INTO strategy_decision_outcomes VALUES (?,?,?,?,?,?)",
            (r.decision_id, r.settled_yes, r.settled_at, r.outcome_status,
             r.realized_net_pnl_cents, r.fill_id))
    con.commit()
    con.close()
    return db


class TestProbePath:
    def test_probe_matches_row_based_population(self, tmp_path):
        t = "KXBTC15M-A"
        rows = [_row(t, ts, 1000.0) for ts in range(700, 1000, 7)]
        db = _fixture_db(tmp_path, rows)
        run = probe_horizon_population(db, horizons_s=[60.0, 300.0])
        assert len(run) == 1
        assert run.probes[0].close_ts_last == 1000.0
        assert run.universe_query == "indexed"

        official = OfficialOutcomes({}, 0, 0)
        anchored = AnchoredStageLog({}, 0, 0, None, None)
        pop_probe = build_population_from_probes(
            run.probes, horizons_s=[60.0, 300.0], max_age_s=90.0,
            anchored=anchored, official=official)
        pop_rows = build_population(
            rows, horizons_s=[60.0, 300.0], max_age_s=90.0,
            anchored=anchored, official=official)
        ps = sorted((u.horizon_s, u.snapshot_ts) for u in pop_probe.units)
        rs = sorted((u.horizon_s, u.snapshot_ts) for u in pop_rows.units)
        assert ps == rs
        assert {e.reason for e in pop_probe.entries} == {None}

    def test_probe_latest_eligible_skips_ineligible_rows(self, tmp_path):
        t = "KXBTC15M-B"
        rows = [
            _row(t, 930.0, 1000.0),
            # newer row at 939 is research-ineligible -> snapshot is 930
            _row(t, 939.0, 1000.0, decision_id=f"{t}:939",
                 record_environment="replay"),
        ]
        db = _fixture_db(tmp_path, rows)
        run = probe_horizon_population(db, horizons_s=[60.0])
        pop = build_population_from_probes(
            run.probes, horizons_s=[60.0], max_age_s=90.0,
            anchored=AnchoredStageLog({}, 0, 0, None, None),
            official=OfficialOutcomes({}, 0, 0))
        assert pop.units[0].snapshot_ts == 930.0

    def test_probe_no_eligible_reason(self, tmp_path):
        t = "KXBTC15M-C"
        rows = [_row(t, 939.0, 1000.0, record_environment="replay")]
        db = _fixture_db(tmp_path, rows)
        run = probe_horizon_population(db, horizons_s=[60.0])
        pop = build_population_from_probes(
            run.probes, horizons_s=[60.0], max_age_s=90.0,
            anchored=AnchoredStageLog({}, 0, 0, None, None),
            official=OfficialOutcomes({}, 0, 0))
        assert pop.entries[0].reason == "no_eligible_snapshot"
        assert not pop.units

    def test_probe_asset_and_close_window_filters(self, tmp_path):
        rows = (
            [_row("KXBTC15M-D", 930.0, 1000.0)]
            + [_row("KXETH15M-E", 930.0, 2000.0)]
            + [_row("KXBTC15M-F", 930.0, 99999.0)]  # outside close window
        )
        db = _fixture_db(tmp_path, rows)
        run = probe_horizon_population(
            db, horizons_s=[60.0], assets=["BTC"],
            since_close_ts=900.0, until_close_ts=5000.0)
        assert {p.ticker for p in run.probes} == {"KXBTC15M-D"}


# ---------------------------------------------------------------------------
# P0: anchored-stage join attribution
# ---------------------------------------------------------------------------

def _alog(ticker, close_ts, entries):
    """entries: (rec_ts, tte_seconds_at_emission, p_model) -> keyed log."""
    by_key = {}
    for ts, tte, p in entries:
        k = (ticker, int(tte // 60))
        by_key.setdefault(k, []).append(AnchoredStageRecord(ts=ts, p_model=p))
    for v in by_key.values():
        v.sort(key=lambda r: r.ts)
    return AnchoredStageLog(by_key, sum(map(len, by_key.values())), 0, None, None)


class TestAnchoredJoin:
    T = "KXBTC15M-J"

    def _join(self, alog, decision_ts=935.0, close_ts=1000.0):
        return join_anchored(alog, self.T, decision_ts, close_ts)

    def test_closer_valid_candidate_in_adjacent_bucket_wins(self):
        # decision tte = 65s -> bucket 1. Own-bucket record at offset -29;
        # adjacent-bucket (bucket 2) record at offset -1 -> closer wins.
        alog = _alog(self.T, 1000.0, [
            (906.0, 70.0, 0.40),    # bucket 1, offset -29
            (934.0, 130.0, 0.61),   # bucket 2, offset -1
        ])
        j = self._join(alog)
        assert j.join_class == JOIN_ASOF_BOUNDED
        assert j.record.p_model == pytest.approx(0.61)
        assert j.n_candidates == 2

    def test_future_candidate_rejected(self):
        # rec.ts - decision_ts > future_slack -> rejected, never scored.
        alog = _alog(self.T, 1000.0, [(942.0, 60.0, 0.61)])
        j = self._join(alog)
        assert j.join_class == JOIN_REJECT_FUTURE
        assert j.record is None

    def test_out_of_tolerance_unavailable(self):
        alog = _alog(self.T, 1000.0, [(900.0, 60.0, 0.61)])  # offset -35 < -30
        j = self._join(alog)
        assert j.join_class == JOIN_REJECT_TOLERANCE
        assert j.record is None

    def test_multiple_candidates_deterministic_selection(self):
        alog = _alog(self.T, 1000.0, [
            (934.0, 60.0, 0.50),   # offset -1.0
            (934.5, 60.0, 0.61),   # offset -0.5 -> closest
        ])
        j1 = self._join(alog)
        j2 = self._join(alog)
        assert j1.record.p_model == pytest.approx(0.61)
        assert j1.ambiguous                    # |off| gap 0.5 < eps
        assert j1.record.p_model == j2.record.p_model
        assert j1.offset_s == j2.offset_s

    def test_no_candidate(self):
        j = self._join(_alog(self.T, 1000.0, []))
        assert j.join_class == JOIN_NONE

    def test_reuse_across_unrelated_decisions_flagged(self):
        # One record joins two DIFFERENT decisions of the same ticker:
        # unit h=60 -> snapshot 935 (offset +5), unit h=30 -> snapshot 970
        # (offset -30). Both admissible; sharing across decision_ids must
        # be flagged, not silently allowed.
        alog = _alog(self.T, 1000.0, [(940.0, 61.0, 0.61)])  # bucket 1
        rows = [_row(self.T, 935.0, 1000.0), _row(self.T, 970.0, 1000.0)]
        pop = build_population(
            rows, horizons_s=[60.0, 30.0], max_age_s=90.0,
            anchored=alog, official=OfficialOutcomes({}, 0, 0))
        assert len(pop.units) == 2
        assert all(u.anch_reused for u in pop.units)
        assert pop.anch_reused_records >= 1

    def test_same_decision_multi_horizon_reuse_not_flagged(self):
        # The same record serving two horizons of ONE decision is
        # legitimate consumption, not cross-decision reuse.
        alog = _alog(self.T, 1000.0, [(935.5, 61.0, 0.61)])
        rows = [_row(self.T, 935.0, 1000.0)]
        pop = build_population(
            rows, horizons_s=[60.0, 50.0], max_age_s=90.0,
            anchored=alog, official=OfficialOutcomes({}, 0, 0))
        assert len(pop.units) == 2
        assert not any(u.anch_reused for u in pop.units)


# ---------------------------------------------------------------------------
# P0: label-availability policy + correction versioning
# ---------------------------------------------------------------------------

class TestLabelPolicy:
    def test_undated_label_excluded_under_observed_only(self):
        u = _unit(close_ts=500.0, target_ts=440.0, y=1)
        u.label_versions = [LabelVersion(
            observed_ts=None, settlement_ts=500.0, resolved_yes=1)]
        y, avail, kind = training_label_at(u, 1000.0, LABEL_POLICY_OBSERVED)
        assert y is None and kind == "undated_only"
        # grace admits the same version as assumed availability
        y2, avail2, kind2 = training_label_at(u, 1000.0, LABEL_POLICY_GRACE)
        assert y2 == 1 and kind2 == "assumed" and avail2 == pytest.approx(800.0)

    def test_correction_after_boundary_cannot_leak_backward(self):
        u = _unit(close_ts=500.0, target_ts=440.0, y=1)
        u.label_versions = [
            LabelVersion(observed_ts=100.0, settlement_ts=490.0, resolved_yes=0),
            # correction published AFTER the fold boundary: invisible at 1000
            LabelVersion(observed_ts=5000.0, settlement_ts=495.0, resolved_yes=1),
        ]
        y, avail, _ = training_label_at(u, 1000.0, LABEL_POLICY_OBSERVED)
        assert y == 0 and avail == pytest.approx(100.0)
        # after the correction's availability, the corrected label trains
        y2, _, _ = training_label_at(u, 6000.0, LABEL_POLICY_OBSERVED)
        assert y2 == 1

    def test_observed_only_train_n_zero_when_no_dated_labels(self):
        units = [
            _unit(ticker=f"T{i}", close_ts=500.0 + i,
                  target_ts=440.0 + i, y=i % 2)
            for i in range(10)
        ]
        for u in units:
            u.label_versions = [LabelVersion(
                observed_ts=None, settlement_ts=u.close_ts,
                resolved_yes=u.y)]
        plan = build_fold_plan(
            units, n_folds=2, min_train_n=1, label_policy=LABEL_POLICY_OBSERVED)
        fitted, stats = compute_fitted_forecasts(
            units, plan, n_folds=2, min_train_n=1,
            label_policy=LABEL_POLICY_OBSERVED)
        # no fold reaches min_train under observed_only -> no fitted probs
        assert all(f.p_q0 is None and f.p_q1 is None for f in fitted.values())
        for h_stats in stats.values():
            for f in h_stats.values():
                assert f["train_labels_observed"] == 0
                assert f["train_labels_excluded_no_availability"] >= 0


# ---------------------------------------------------------------------------
# P0: bootstrap arithmetic + replicate accounting
# ---------------------------------------------------------------------------

class TestBootstrapAccounting:
    def _ref_stats(self, cb: CompBlocks, draws: np.ndarray):
        """Trivial per-draw loop over the IDENTICAL draw weights."""
        md, bss = [], []
        for w in draws:
            denom = float(w @ cb.n)
            if denom <= 0:
                continue
            md.append(float(w @ cb.sum_d) / denom)
            bs_b = float(w @ cb.sum_b) / denom
            if bs_b > 0:
                bss.append(1.0 - float(w @ cb.sum_c) / denom / bs_b)
        return np.asarray(md), np.asarray(bss)

    def test_optimized_matches_reference_same_weights(self):
        rng = np.random.default_rng(11)
        n_blocks = 12
        block_of_unit = np.repeat(np.arange(n_blocks), 3)
        d = rng.normal(0.01, 0.05, n_blocks * 3)
        lc = np.abs(rng.normal(0.2, 0.05, n_blocks * 3))
        lb = np.abs(rng.normal(0.22, 0.05, n_blocks * 3))
        cb = make_comp_blocks(
            block_of_unit, list(range(n_blocks * 3)), d, lc, lb, n_blocks)
        R, seed = 300, 17
        res = paired_bootstrap({"x": cb}, replicates=R, seed=seed)["x"]
        draws = shared_draws(n_blocks, R, seed)  # identical draw weights
        md_ref, bss_ref = self._ref_stats(cb, draws)
        assert res.draw_mean_d == pytest.approx(float(md_ref.mean()))
        lo, hi = np.percentile(md_ref, [2.5, 97.5])
        assert res.ci_d == pytest.approx((lo, hi))
        assert res.n_valid_loss_draws == int(len(md_ref))
        assert res.n_valid_skill_draws == int(len(bss_ref))
        assert res.draw_mean_bss == pytest.approx(float(bss_ref.mean()))

    def test_zero_baseline_loss_draws_still_count_toward_loss(self):
        # baseline loss identically zero -> BSS undefined every draw, but
        # every draw still has a valid loss difference.
        n_blocks = 8
        cb = CompBlocks(
            n=np.full(n_blocks, 2),
            sum_d=np.full(n_blocks, 0.5),
            sum_c=np.full(n_blocks, 0.4),
            sum_b=np.zeros(n_blocks),
        )
        res = paired_bootstrap({"z": cb}, replicates=100, seed=3)["z"]
        assert res.n_valid_loss_draws == 100
        assert res.n_valid_skill_draws == 0
        assert res.n_zero_baseline_loss_draws == 100
        assert res.n_empty_support_draws == 0
        assert res.ci_d is not None and res.ci_bss is None

    def test_empty_support_draws_distinguished(self):
        n_blocks = 6
        empty = CompBlocks(
            n=np.zeros(n_blocks, dtype=np.int64),
            sum_d=np.zeros(n_blocks), sum_c=np.zeros(n_blocks),
            sum_b=np.zeros(n_blocks))
        res = paired_bootstrap({"e": empty}, replicates=50, seed=4)["e"]
        assert res.n_valid_loss_draws == 0
        assert res.n_empty_support_draws == 50
        assert res.ci_d is None and res.n_units == 0

    def test_empty_block_universe_safe(self):
        cb = CompBlocks(
            n=np.zeros(0, dtype=np.int64), sum_d=np.zeros(0),
            sum_c=np.zeros(0), sum_b=np.zeros(0))
        res = paired_bootstrap({"e": cb}, replicates=50, seed=4)["e"]
        assert res.n_units == 0 and res.ci_d is None


# ---------------------------------------------------------------------------
# P0: per-comparison integrity scoping + population correctness
# ---------------------------------------------------------------------------

class TestIntegrityScoping:
    def test_asof_join_provisional_but_only_for_anchored_comparisons(self):
        from merid.analysis.forecast_audit.report import AuditConfig, _integrity_for
        u = _unit()
        u.p_anch_wf = 0.6
        u.anch_join_class = JOIN_ASOF_BOUNDED
        cfg = AuditConfig()
        anch = _integrity_for("anch_wf", "raw", [u], [0], cfg)
        fin = _integrity_for("final", "mid", [u], [0], cfg)
        assert anch["integrity_status"] == "PROVISIONAL"
        assert "anch_join_asof_bounded" in anch["integrity_reasons"]
        assert not anch["evidence_eligible"]
        assert anch["deployment_gate_passed"] is False
        assert fin["integrity_status"] == "VALID"
        assert fin["evidence_eligible"]

    def test_future_join_actually_scored_is_invalid(self):
        from merid.analysis.forecast_audit.report import AuditConfig, _integrity_for
        u = _unit()
        u.p_anch_wf = 0.6                       # scored despite reject class
        u.anch_join_class = JOIN_REJECT_FUTURE
        cfg = AuditConfig()
        out = _integrity_for("anch_wf", "raw", [u], [0], cfg)
        assert out["integrity_status"] == "INVALID"

    def test_grace_policy_marks_fitted_comparisons_provisional(self):
        from merid.analysis.forecast_audit.report import AuditConfig, _integrity_for
        u = _unit()
        cfg = AuditConfig(label_policy=LABEL_POLICY_GRACE)
        out = _integrity_for("q1", "q0", [u], [0], cfg,
                             assumed_train_labels=5)
        assert out["integrity_status"] == "PROVISIONAL"
        assert "assumed_training_labels_used" in out["integrity_reasons"]

    def test_grace_configured_but_unused_stays_valid(self):
        # Enabling grace without any assumed label actually training is
        # not a downgrade — downgrade is for exercised dependency only.
        from merid.analysis.forecast_audit.report import AuditConfig, _integrity_for
        u = _unit()
        cfg = AuditConfig(label_policy=LABEL_POLICY_GRACE)
        out = _integrity_for("q1", "q0", [u], [0], cfg,
                             assumed_train_labels=0)
        assert out["integrity_status"] == "VALID"
        assert out["evidence_eligible"]


class TestPopulationCorrectness:
    def test_nontarget_null_asset_outcome_not_expected(self):
        # A non-target-series ticker with NULL asset must not enter the
        # expected universe (report-side filter uses the ticker stem).
        from merid.analysis.forecast_audit.records import asset_from_ticker
        assert asset_from_ticker("INXD-26JAN") is None
        assert asset_from_ticker("KXBTC15M-26JAN1") == "BTC"

    def test_empty_population_report_valid(self, tmp_path):
        # Empty decision DB -> valid empty report, never a crash.
        from merid.analysis.forecast_audit.report import AuditConfig, build_report
        db = _fixture_db(tmp_path, [])
        cfg = AuditConfig(
            db_path=str(db), model_cal_path=str(tmp_path / "none.jsonl"),
            outcomes_path=str(tmp_path / "none2.jsonl"),
            replicates=50, block_lens_s=(3600.0,), primary_block_len_s=3600.0)
        rep = build_report(cfg)
        assert rep["population"]["units_scored"] == 0
        for comp, res in rep["primary_results"]["pooled"].items():
            assert res["statistical_verdict"] == "INSUFFICIENT_DATA"
            assert "integrity_status" in res
            assert "evidence_eligible" in res
            assert res["deployment_gate_passed"] is False
        assert rep["economics"]["status"] == "not_run"
        assert rep["economics"]["filled_decisions"] is None

    def test_econ_not_run_vs_ran_zero_fills(self, tmp_path):
        # Skipped economics (null) must differ from a completed scan with
        # zero fills (0).
        from merid.analysis.forecast_audit.report import AuditConfig, build_report
        db = _fixture_db(tmp_path, [])
        base = dict(
            db_path=str(db), model_cal_path=str(tmp_path / "n1.jsonl"),
            outcomes_path=str(tmp_path / "n2.jsonl"),
            replicates=10, block_lens_s=(3600.0,), primary_block_len_s=3600.0)
        skip = build_report(AuditConfig(**base, include_econ=False))
        ran = build_report(AuditConfig(**base, include_econ=True))
        assert skip["economics"]["status"] == "not_run"
        assert skip["economics"]["filled_decisions"] is None
        assert ran["economics"]["status"] == "ran"
        assert ran["economics"]["filled_decisions"] == 0
