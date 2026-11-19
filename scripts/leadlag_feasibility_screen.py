#!/usr/bin/env python3
"""Lead-lag feasibility screen — READ-ONLY offline evaluation.

Answers, with archived data only, whether BTC cross-asset RTI returns add
incremental settlement-forecast information beyond MERID's incumbent
probability chain — before any live shadow hook is written.

Design: MERID_LEAD_LAG_SHADOW_LANE_DESIGN_2026-11-12.md (amended 2026-11-12).

Stages:
  provenance  — coverage/causality tables (gates everything else)
  dataset     — checkpoint-sampled forecast dataset w/ reconstructed RTI features
  evaluate    — Experiments A (p_settle_raw ~ raw_p_yes) & B (p_final_yes ~
                calibrated_p_yes); P0 / P0-cal / P1 variants; falsification
                battery; paired-loss differences + block bootstrap
  economics   — indicative taker EV where book archive overlaps (best effort)

No writes to any production store; all DB access is mode=ro.
Outputs: analysis/leadlag_screen_2026-11-12/{provenance.json,dataset.jsonl,
         dataset_meta.json,evaluation.json,report.md}

Usage:
    .venv\\Scripts\\python.exe scripts\\leadlag_feasibility_screen.py --stage provenance
    .venv\\Scripts\\python.exe scripts\\leadlag_feasibility_screen.py --stage all
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
RTI_DB = ROOT / "data" / "cf_rti_ticks.db"
AUDIT_DB = Path(os.environ.get(
    "LEADLAG_AUDIT_DB",
    str(ROOT / "data" / "decision_audit.db")))
BOOK_DB_CANDIDATES = [
    ROOT / "data" / "kalshi_book_archive_active.db",
    ROOT / "data" / "preserved_book_archive_2026-11-06" / "kalshi_book_archive.db",
    ROOT / "data" / "preserved_book_archive_2026-11-07" / "kalshi_book_archive_live2.db",
]
# Production freshness bound: cf_rti_adapter._MAX_CFB_RTI_AGE_MS default.
RTI_MAX_AGE_MS = 5000
OUT_DIR = ROOT / "analysis" / "leadlag_screen_2026-11-12"

CHECKPOINTS_S = (600.0, 300.0, 120.0, 60.0)
RTI_HORIZONS_S = (1.0, 3.0, 10.0, 30.0, 60.0, 120.0)
MAX_EVAL_AGE_S = 90.0
ASSETS = ("BTC", "ETH", "SOL", "XRP", "DOGE")
TARGET_ASSETS = ("ETH", "SOL", "XRP", "DOGE")
EPS = 1e-6
BOOTSTRAP_N = 2000
SEED = 42


def _iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else None


def _logit(p):
    p = min(1.0 - EPS, max(EPS, float(p)))
    return math.log(p / (1.0 - p))


def _connect_ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=60)
    con.execute("pragma busy_timeout=60000")
    con.execute("pragma temp_store=MEMORY")
    return con


def ticker_asset(ticker: str):
    t = str(ticker).upper()
    for a in ASSETS:
        if t.startswith(f"KX{a}15M"):
            return a
    return None


# ---------------------------------------------------------------------------
# Stage 1: provenance
# ---------------------------------------------------------------------------

def stage_provenance(lo: float | None = None, hi: float | None = None) -> tuple[dict, tuple]:
    rep: dict = {}

    con = _connect_ro(RTI_DB)
    rti = {}
    for asset, n, mn, mx, null_recv, avg_lag, max_lag in con.execute(
        """select asset, count(*), min(src_ts_ms), max(src_ts_ms),
                  sum(recv_ts_ms is null),
                  avg(recv_ts_ms - src_ts_ms), max(recv_ts_ms - src_ts_ms)
           from rti_ticks group by asset"""
    ):
        rti[asset] = {
            "rows": n,
            "first_src_utc": _iso(mn / 1000),
            "last_src_utc": _iso(mx / 1000),
            "null_recv": int(null_recv or 0),
            "avg_recv_lag_ms": round(avg_lag, 1) if avg_lag else None,
            "max_recv_lag_ms": round(max_lag, 1) if max_lag else None,
        }
    per_day = defaultdict(int)
    for d, n in con.execute(
        "select date(src_ts_ms/1000,'unixepoch') d, count(*) from rti_ticks group by d"
    ):
        per_day[d] = n
    rti["per_day_rows"] = dict(sorted(per_day.items()))
    rep["rti_archive"] = rti
    mn, mx = con.execute("select min(src_ts_ms), max(src_ts_ms) from rti_ticks").fetchone()
    con.close()
    rti_lo, rti_hi = mn / 1000.0, mx / 1000.0
    lo = rti_lo if lo is None else lo
    hi = rti_hi if hi is None else hi
    rep["rti_window_epoch_s"] = [rti_lo, rti_hi]
    rep["decision_window_epoch_s"] = [lo, hi]
    rep["decision_window_utc"] = [_iso(lo), _iso(hi)]

    con = _connect_ro(AUDIT_DB)
    base = "from strategy_decisions where decision_ts between ? and ?"
    rep["decisions_total_in_window"] = con.execute(
        f"select count(*) {base}", (lo, hi)
    ).fetchone()[0]
    rep["decisions_by_asset"] = dict(con.execute(
        f"select asset, count(*) {base} group by asset", (lo, hi)
    ).fetchall())
    rep["decisions_by_env_eligibility"] = [
        {"record_environment": e, "is_eligible_for_research": r, "n": n}
        for e, r, n in con.execute(
            f"""select record_environment, is_eligible_for_research, count(*) {base}
                group by 1,2""", (lo, hi)
        )
    ]
    for key, col in (("model_version", "model_version"), ("config_version", "config_version")):
        rep[f"decisions_by_{key}"] = [
            {key: v, "n": n}
            for v, n in con.execute(
                f"""select coalesce({col},'<null>'), count(*) {base}
                    group by 1 order by 2 desc limit 15""", (lo, hi)
            )
        ]
    rep["decisions_by_outcome"] = [
        {"decision": v, "n": n}
        for v, n in con.execute(
            f"""select coalesce(decision,'<null>'), count(*) {base}
                group by 1 order by 2 desc""", (lo, hi)
        )
    ]
    rep["decisions_per_day"] = [
        {"day_utc": d, "n": n}
        for d, n in con.execute(
            f"""select date(decision_ts,'unixepoch') d, count(*) {base}
                group by d order by d""", (lo, hi)
        )
    ]
    rep["distinct_tickers"] = con.execute(
        f"select count(distinct ticker) {base}", (lo, hi)
    ).fetchone()[0]
    # rows per candidate_id histogram (route duplication)
    rep["rows_per_candidate_hist"] = [
        {"rows_per_candidate": r, "n_candidates": n}
        for r, n in con.execute(
            f"""select cnt, count(*) from (
                  select coalesce(candidate_id, decision_id) c, count(*) cnt
                  {base} group by c
                ) group by cnt order by cnt""", (lo, hi)
        )
    ]
    rep["with_snapshot"] = con.execute(
        f"""select count(*) from strategy_decisions d
            join strategy_decision_snapshots s using(decision_id)
            where d.decision_ts between ? and ?""", (lo, hi)
    ).fetchone()[0]
    rep["with_settled_outcome"] = con.execute(
        f"""select count(*) from strategy_decisions d
            join strategy_decision_outcomes o using(decision_id)
            where d.decision_ts between ? and ? and o.settled_yes is not null""",
        (lo, hi),
    ).fetchone()[0]
    rep["prob_field_coverage"] = [
        {"field": f, "nonnull": n}
        for f, n in con.execute(
            f"""select 'raw_p_yes', count(s.raw_p_yes) from strategy_decisions d
                join strategy_decision_snapshots s using(decision_id)
                where d.decision_ts between ? and ?
                union all
                select 'calibrated_p_yes', count(s.calibrated_p_yes)
                from strategy_decisions d
                join strategy_decision_snapshots s using(decision_id)
                where d.decision_ts between ? and ?""", (lo, hi, lo, hi)
        )
    ]
    rep["settlement_reference_values"] = [
        {"settlement_reference": v, "n": n}
        for v, n in con.execute(
            f"""select settlement_reference, count(*) {base}
                group by 1 order by 2 desc limit 10""", (lo, hi)
        )
    ]
    con.close()

    # Book-archive probing is deferred to stage_economics: the live archive
    # (kalshi_book_archive_live2.db) carries a multi-GB WAL and even
    # sqlite_master reads can stall; keep provenance fast and deterministic.

    return rep, (lo, hi)  # effective decision window used


# ---------------------------------------------------------------------------
# Stage 2: RTI series + dataset
# ---------------------------------------------------------------------------

class RtiSeries:
    __slots__ = ("src", "recv", "val")

    def __init__(self, rows):
        rows = sorted(rows, key=lambda r: r[0])
        self.src = np.array([r[0] for r in rows], dtype=np.int64)
        self.recv = np.array(
            [r[1] if r[1] is not None else r[0] for r in rows], dtype=np.int64)
        self.val = np.array([r[3] for r in rows], dtype=np.float64)

    def returns(self, t_ms: float, anchor: str = "src") -> dict:
        """Log returns at preregistered horizons.

        anchor='src'  : current = latest tick with src_ts <= t_ms  (upper bound)
        anchor='recv' : current = latest tick with recv_ts <= t_ms (deployable)
        prior         = latest tick with src_ts <= current.src_ts - h*1000,
                        also satisfying the anchor bound.
        """
        times = self.src if anchor == "src" else self.recv
        i = int(np.searchsorted(times, t_ms, side="right")) - 1
        out = {h: None for h in RTI_HORIZONS_S}
        if i < 0:
            return out
        # production freshness bound (cf_rti_adapter._MAX_CFB_RTI_AGE_MS=5000):
        # a "current" tick older than this would be rejected live, so its
        # returns are unavailable — never fabricate from a stale tick.
        if t_ms - int(times[i]) > RTI_MAX_AGE_MS:
            return out
        cur_src = int(self.src[i])
        cur_val = float(self.val[i])
        if not (cur_val > 0):
            return out
        for h in RTI_HORIZONS_S:
            cutoff_src = cur_src - int(h * 1000)
            j = int(np.searchsorted(self.src, cutoff_src, side="right")) - 1
            while j >= 0 and int(times[j]) > t_ms:
                j -= 1
            if j < 0 or j == i:
                continue
            pv = float(self.val[j])
            if pv > 0:
                out[h] = math.log(cur_val / pv)
        return out


def load_rti_series() -> dict:
    con = _connect_ro(RTI_DB)
    by_asset = defaultdict(list)
    for asset, src, recv, local, val in con.execute(
        "select asset, src_ts_ms, recv_ts_ms, local_ts_ms, value from rti_ticks"
    ):
        by_asset[asset].append((src, recv, local, val))
    con.close()
    return {a: RtiSeries(rows) for a, rows in by_asset.items()}


_DECISION_SQL = """
select d.decision_id, d.candidate_id, d.run_id, d.ticker, d.asset,
       d.decision_ts, d.close_ts, d.seconds_to_close,
       d.decision, d.selected_side, d.primary_reason_code,
       d.model_version, d.config_version,
       d.settlement_reference, d.settlement_rule_version,
       s.raw_p_yes, s.calibrated_p_yes, s.zscore,
       s.settlement_reference_price, s.settlement_reference_source,
       s.settlement_reference_age_ms, s.book_age_ms, s.book_is_executable,
       s.spot_age_ms,
       s.distance_to_strike, s.log_moneyness,
       s.yes_bid_cents, s.yes_ask_cents, s.no_bid_cents, s.no_ask_cents,
       s.yes_depth, s.no_depth,
       s.spot_price,
       s.vol_forecast, s.realized_vol_1s, s.realized_vol_5s,
       s.realized_vol_1m, s.realized_vol_5m
from strategy_decisions d
join strategy_decision_snapshots s using(decision_id)
where d.decision_ts between ? and ?
  and d.record_environment='production'
  and d.is_eligible_for_research=1
  and s.raw_p_yes is not null
  and s.calibrated_p_yes is not null
"""

_DECISION_KEYS = [
    "decision_id", "candidate_id", "run_id", "ticker", "asset",
    "decision_ts", "close_ts", "seconds_to_close",
    "decision", "selected_side", "primary_reason_code",
    "model_version", "config_version",
    "settlement_reference", "settlement_rule_version",
    "raw_p_yes", "calibrated_p_yes", "zscore",
    "settlement_reference_price", "settlement_reference_source",
    "settlement_reference_age_ms", "book_age_ms", "book_is_executable",
    "spot_age_ms",
    "distance_to_strike", "log_moneyness",
    "yes_bid_cents", "yes_ask_cents", "no_bid_cents", "no_ask_cents",
    "yes_depth", "no_depth",
    "spot_price",
    "vol_forecast", "realized_vol_1s", "realized_vol_5s",
    "realized_vol_1m", "realized_vol_5m",
]


def ticker_outcomes(con: sqlite3.Connection, lo: float, hi: float) -> dict:
    """ticker -> settled_yes, from any decision row of that ticker with a
    settled outcome (market-level label, backfilled per decision)."""
    out = {}
    # SQLite bare-column-with-max: settled_yes comes from the row with the
    # latest settled_at per ticker (market-level label).
    for ticker, sy, sat in con.execute(
        """select d.ticker, o.settled_yes, max(o.settled_at)
           from strategy_decisions d
           join strategy_decision_outcomes o using(decision_id)
           where d.decision_ts between ? and ? and o.settled_yes is not null
           group by d.ticker""",
        (lo, hi),
    ):
        out[ticker] = int(sy)
    # The group-by above can emit both yes/no rows per ticker if data is
    # inconsistent; last-write would clobber — detect conflicts.
    conflicts = con.execute(
        """select d.ticker, count(distinct o.settled_yes)
           from strategy_decisions d
           join strategy_decision_outcomes o using(decision_id)
           where d.decision_ts between ? and ? and o.settled_yes is not null
           group by d.ticker having count(distinct o.settled_yes) > 1""",
        (lo, hi),
    ).fetchall()
    return out, [t for t, _ in conflicts]


def build_forecast_dataset(rti: dict, con: sqlite3.Connection,
                           lo: float, hi: float):
    cur = con.execute(_DECISION_SQL, (lo, hi))
    decisions = [dict(zip(_DECISION_KEYS, r)) for r in cur.fetchall()]
    outcomes, outcome_conflicts = ticker_outcomes(con, lo, hi)

    # route dedup: one row per candidate_id; prefer ':taker' suffix
    by_cand = defaultdict(list)
    for d in decisions:
        by_cand[d.get("candidate_id") or d["decision_id"]].append(d)
    route_prob_mismatch = 0
    cand_rows = []
    for cid, ds in by_cand.items():
        if len({round(float(x["raw_p_yes"]), 9) for x in ds}) > 1 or \
           len({round(float(x["calibrated_p_yes"]), 9) for x in ds}) > 1:
            route_prob_mismatch += 1
        ds.sort(key=lambda x: (not str(x["decision_id"]).endswith(":taker"),
                               x["decision_ts"]))
        cand_rows.append(ds[0])

    close_by_ticker = {}
    for d in cand_rows:
        if d.get("close_ts"):
            close_by_ticker[d["ticker"]] = max(
                close_by_ticker.get(d["ticker"], 0.0), float(d["close_ts"]))

    by_ticker = defaultdict(list)
    for d in cand_rows:
        by_ticker[d["ticker"]].append(d)
    for t in by_ticker:
        by_ticker[t].sort(key=lambda x: x["decision_ts"])

    dataset, coverage = [], defaultdict(int)
    for ticker, close_ts in close_by_ticker.items():
        asset = ticker_asset(ticker)
        if asset not in TARGET_ASSETS or ticker not in outcomes:
            continue
        y = outcomes[ticker]
        ds = by_ticker[ticker]
        ts_arr = [d["decision_ts"] for d in ds]
        for h in CHECKPOINTS_S:
            target = close_ts - h
            # latest decision at-or-before target within staleness bound;
            # if the newest lacks a usable eval, walk back within the bound.
            i = bisect.bisect_right(ts_arr, target) - 1
            chosen = None
            while i >= 0 and target - ds[i]["decision_ts"] <= MAX_EVAL_AGE_S:
                chosen = ds[i]
                break
            if chosen is None:
                coverage[f"miss_{'stale_or_none' if i >= 0 else 'no_prior'}|h{int(h)}"] += 1
                continue
            age = target - chosen["decision_ts"]
            t_ms = chosen["decision_ts"] * 1000.0
            own, btc = rti.get(asset), rti.get("BTC")
            if own is None or btc is None:
                coverage[f"miss_no_rti|h{int(h)}"] += 1
                continue
            row = {
                "ticker": ticker, "asset": asset, "close_ts": close_ts,
                "checkpoint_s": h, "eval_age_s": round(age, 3),
                "decision_ts": chosen["decision_ts"],
                "decision_id": chosen["decision_id"],
                "candidate_id": chosen.get("candidate_id"),
                "y": y,
                "p_raw": float(chosen["raw_p_yes"]),
                "p_cal": float(chosen["calibrated_p_yes"]),
                "zscore": chosen.get("zscore"),
                "distance_to_strike": chosen.get("distance_to_strike"),
                "log_moneyness": chosen.get("log_moneyness"),
                "seconds_to_close": chosen.get("seconds_to_close"),
                "yes_bid_cents": chosen.get("yes_bid_cents"),
                "yes_ask_cents": chosen.get("yes_ask_cents"),
                "no_bid_cents": chosen.get("no_bid_cents"),
                "no_ask_cents": chosen.get("no_ask_cents"),
                "yes_depth": chosen.get("yes_depth"),
                "no_depth": chosen.get("no_depth"),
                "spot_price": chosen.get("spot_price"),
                "settlement_reference_price": chosen.get("settlement_reference_price"),
                "model_version": chosen.get("model_version"),
                "config_version": chosen.get("config_version"),
                "settlement_reference": chosen.get("settlement_reference"),
                "settlement_rule_version": chosen.get("settlement_rule_version"),
                "settlement_reference_source": chosen.get("settlement_reference_source"),
                "settlement_reference_age_ms": chosen.get("settlement_reference_age_ms"),
                "book_age_ms": chosen.get("book_age_ms"),
                "book_is_executable": chosen.get("book_is_executable"),
                "spot_age_ms": chosen.get("spot_age_ms"),
                # Experiment A purity flag: p_raw is the settlement-distribution
                # probability only when the settlement path was active.
                "settlement_active": bool(
                    chosen.get("settlement_reference_source")
                    and "rti" in str(chosen.get("settlement_reference_source")).lower()
                ),
                "day_utc": datetime.fromtimestamp(
                    chosen["decision_ts"], tz=timezone.utc).strftime("%Y-%m-%d"),
            }
            for arm, anchor, shift_ms in (
                ("src", "src", 0.0), ("recv", "recv", 0.0),
                ("recv_p500", "recv", 500.0), ("recv_p1000", "recv", 1000.0),
            ):
                eff = t_ms - shift_ms
                row[f"own_ret_{arm}"] = own.returns(eff, anchor=anchor)
                row[f"btc_ret_{arm}"] = btc.returns(eff, anchor=anchor)
            if row["yes_bid_cents"] is not None and row["yes_ask_cents"] is not None:
                row["yes_mid_prob"] = (
                    float(row["yes_bid_cents"]) + float(row["yes_ask_cents"])) / 200.0
            else:
                row["yes_mid_prob"] = None
            dataset.append(row)
            coverage[f"emitted|h{int(h)}"] += 1

    meta = {
        "decision_window_epoch_s": [lo, hi],
        "decisions_loaded": len(decisions),
        "candidates_after_route_dedup": len(cand_rows),
        "route_prob_mismatch_candidates": route_prob_mismatch,
        "tickers_with_close": len(close_by_ticker),
        "tickers_with_outcome": len(outcomes),
        "outcome_conflict_tickers": outcome_conflicts[:20],
        "n_outcome_conflicts": len(outcome_conflicts),
        "coverage": dict(sorted(coverage.items())),
    }
    return dataset, meta


# ---------------------------------------------------------------------------
# Stage 3: evaluation
# ---------------------------------------------------------------------------

def _feat_vector(row, anchor, include_btc, include_own, include_market):
    """Return feature list or None if a required return is missing."""
    p0 = row.get("_p0")
    if p0 is None:
        return None
    btc_ret = row.get(f"btc_ret_{anchor}") or {}
    own_ret = row.get(f"own_ret_{anchor}") or {}
    x = [_logit(p0)]
    for h in RTI_HORIZONS_S:
        if include_btc:
            v = btc_ret.get(h)
            if v is None:
                return None
            x.append(float(v) * 1e4)
        else:
            x.append(0.0)
    for h in RTI_HORIZONS_S:
        if include_own:
            v = own_ret.get(h)
            if v is None:
                return None
            x.append(float(v) * 1e4)
        else:
            x.append(0.0)
    x.append(float(row.get("zscore") or 0.0))
    x.append(float(row.get("seconds_to_close") or 0.0) / 900.0)
    x.append(1.0 if (row.get("seconds_to_close") or 999.0) <= 60.0 else 0.0)
    x.append(float(row.get("eval_age_s") or 0.0) / MAX_EVAL_AGE_S)
    if include_market:
        mp = row.get("yes_mid_prob")
        if mp is not None and 0.0 < mp < 1.0:
            x.append(_logit(mp))
            x.append(0.0)
        else:
            x.append(0.0)
            x.append(1.0)
    x.extend(1.0 if row["asset"] == a else 0.0 for a in TARGET_ASSETS)
    return x


def _log_loss(y, p):
    p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
    y = np.asarray(y, dtype=float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def _brier(y, p):
    return float(np.mean((np.asarray(y, dtype=float) - np.asarray(p, dtype=float)) ** 2))


def stage_evaluate(dataset):
    from sklearn.linear_model import LogisticRegression

    # variants: name -> (include_btc, include_own, include_market, is_future_diag)
    VARIANTS = {
        "P1":           (True,  True,  True,  False),
        "P1_noBTC":     (False, True,  True,  False),
        "P1_noMkt":     (True,  True,  False, False),
        "P1_min":       (True,  False, False, False),   # BTC returns + settlement state only
        "P1_future":    (True,  True,  True,  True),    # leakage diagnostic
    }

    all_preds = []   # pooled out-of-fold predictions for paired diffs
    fold_summaries = []
    coverage = {}

    # anchor arms: src = source-time upper bound; recv = deployable receipt
    # time; recv_p500/p1000 = additional-latency stress (info 0.5s/1.0s older)
    for anchor in ("src", "recv", "recv_p500", "recv_p1000"):
        for exp_name, p0_key in (("A_mechanistic_raw", "p_raw"),
                                 ("B_production_cal", "p_cal")):
            rows = []
            for r in dataset:
                rr = dict(r)
                rr["_p0"] = r.get(p0_key)
                rows.append(rr)
            # Experiment A purity: p_raw is the settlement-distribution
            # probability only when settlement_reference_source was RTI-live.
            if exp_name.startswith("A_"):
                n_settle = sum(1 for r in rows if r.get("settlement_active"))
                rows_eval = [r for r in rows if r.get("settlement_active")]
            else:
                n_settle = None
                rows_eval = rows
            # Common support: every variant is scored on rows where the full
            # preregistered P1 feature set is complete under this anchor —
            # keeps P0/P0_cal/P1 fold metrics and paired diffs comparable.
            def _feat_complete(r):
                b = r.get(f"btc_ret_{anchor}") or {}
                o = r.get(f"own_ret_{anchor}") or {}
                return (r.get("_p0") is not None
                        and all(b.get(h) is not None for h in RTI_HORIZONS_S)
                        and all(o.get(h) is not None for h in RTI_HORIZONS_S))
            n_p0 = sum(1 for r in rows_eval if r.get("_p0") is not None)
            usable = [r for r in rows_eval if _feat_complete(r)]
            coverage[f"{anchor}|{exp_name}"] = {
                "n_rows": len(rows_eval),
                "n_settlement_active": n_settle,
                "n_with_p0": n_p0,
                "n_feature_complete": len(usable),
                "n_days": len({r["day_utc"] for r in usable}),
                "n_tickers": len({r["ticker"] for r in usable}),
            }
            if len(usable) < 40:
                fold_summaries.append({
                    "anchor": anchor, "experiment": exp_name,
                    "status": "insufficient_support", "n": len(usable)})
                continue

            usable.sort(key=lambda r: (r["close_ts"], r["ticker"], r["checkpoint_s"]))
            days = sorted({r["day_utc"] for r in usable})
            # expanding-day folds: train on earlier days, test on each later day
            splits = []
            min_train = max(30, int(0.4 * len(usable)))
            for k in range(1, len(days)):
                tr = [r for r in usable if r["day_utc"] < days[k]]
                te = [r for r in usable if r["day_utc"] >= days[k]]
                if len(tr) >= min_train and len(te) >= 8:
                    splits.append((tr, te, f"pre_{days[k]}__post"))
            if not splits:
                cut = int(len(usable) * 0.6)
                splits = [(usable[:cut], usable[cut:], "first60pct_train")]

            for tr, te, tag in splits:
                ytr = np.array([r["y"] for r in tr], dtype=float)
                yte = np.array([r["y"] for r in te], dtype=float)
                fold_rec = {"anchor": anchor, "experiment": exp_name,
                            "fold": tag, "n_train": len(tr), "n_test": len(te),
                            "test_days": sorted({r["day_utc"] for r in te}),
                            "variants": {}}

                # P0: raw baseline passthrough
                p0_te = np.array([min(1 - EPS, max(EPS, r["_p0"])) for r in te])
                fold_rec["variants"]["P0"] = {
                    "log_loss": _log_loss(yte, p0_te), "brier": _brier(yte, p0_te)}
                for r, p in zip(te, p0_te):
                    all_preds.append({"anchor": anchor, "experiment": exp_name,
                                      "variant": "P0", "fold": tag,
                                      "day": r["day_utc"], "ticker": r["ticker"],
                                      "checkpoint_s": r["checkpoint_s"],
                                      "decision_id": r.get("decision_id"),
                                      "candidate_id": r.get("candidate_id"),
                                      "seconds_to_close": r.get("seconds_to_close"),
                                      "y": r["y"], "p": float(p)})

                # P0_cal: recalibration control sigmoid(a + b*logit(p0))
                Xtr0 = np.array([_logit(r["_p0"]) for r in tr]).reshape(-1, 1)
                Xte0 = np.array([_logit(r["_p0"]) for r in te]).reshape(-1, 1)
                from sklearn.linear_model import LogisticRegression as _LR
                clf0 = _LR(C=1.0, max_iter=1000).fit(Xtr0, ytr)
                pcal_te = clf0.predict_proba(Xte0)[:, 1]
                fold_rec["variants"]["P0_cal"] = {
                    "log_loss": _log_loss(yte, pcal_te), "brier": _brier(yte, pcal_te)}
                for r, p in zip(te, pcal_te):
                    all_preds.append({"anchor": anchor, "experiment": exp_name,
                                      "variant": "P0_cal", "fold": tag,
                                      "day": r["day_utc"], "ticker": r["ticker"],
                                      "checkpoint_s": r["checkpoint_s"],
                                      "decision_id": r.get("decision_id"),
                                      "candidate_id": r.get("candidate_id"),
                                      "seconds_to_close": r.get("seconds_to_close"),
                                      "y": r["y"], "p": float(p)})

                # P1 family
                for vname, (ib, io, im, fut) in VARIANTS.items():
                    def fv(rr):
                        if fut:
                            # leakage diagnostic: substitute features from the
                            # same ticker's NEXT checkpoint (later eval = future)
                            cands = [x for x in usable
                                     if x["ticker"] == rr["ticker"]
                                     and x["decision_ts"] > rr["decision_ts"]
                                     and x["checkpoint_s"] < rr["checkpoint_s"]]
                            if not cands:
                                return None
                            src = min(cands, key=lambda x: x["decision_ts"])
                            rr = dict(rr)
                            rr[f"btc_ret_{anchor}"] = src.get(f"btc_ret_{anchor}")
                            rr[f"own_ret_{anchor}"] = src.get(f"own_ret_{anchor}")
                        return _feat_vector(rr, anchor, ib, io, im)
                    Xtr_l = [fv(r) for r in tr]
                    Xte_l = [fv(r) for r in te]
                    tr_idx = [i for i, f in enumerate(Xtr_l) if f is not None]
                    te_idx = [i for i, f in enumerate(Xte_l) if f is not None]
                    if len(tr_idx) < 20 or len(te_idx) < 5:
                        fold_rec["variants"][vname] = {"status": "insufficient_features",
                                                       "n_test": len(te_idx)}
                        continue
                    Xtr_a = np.array([Xtr_l[i] for i in tr_idx])
                    ytr_a = ytr[tr_idx]
                    Xte_a = np.array([Xte_l[i] for i in te_idx])
                    yte_a = yte[te_idx]
                    clf = _LR(C=0.5, max_iter=2000).fit(Xtr_a, ytr_a)
                    p_te = clf.predict_proba(Xte_a)[:, 1]
                    m = {"log_loss": _log_loss(yte_a, p_te),
                         "brier": _brier(yte_a, p_te),
                         "n_test": int(len(yte_a)),
                         "mean_p": round(float(np.mean(p_te)), 4),
                         "base_rate": round(float(np.mean(yte_a)), 4)}
                    fold_rec["variants"][vname] = m
                    for i, p in zip(te_idx, p_te):
                        r = te[i]
                        all_preds.append({"anchor": anchor, "experiment": exp_name,
                                          "variant": vname, "fold": tag,
                                          "day": r["day_utc"], "ticker": r["ticker"],
                                          "checkpoint_s": r["checkpoint_s"],
                                          "decision_id": r.get("decision_id"),
                                          "candidate_id": r.get("candidate_id"),
                                          "seconds_to_close": r.get("seconds_to_close"),
                                          "y": int(yte_a[list(te_idx).index(i)]),
                                          "p": float(p)})
                fold_summaries.append(fold_rec)

    # ---- paired differences + block bootstrap ----
    paired = _paired_analysis(all_preds)
    return {"coverage": coverage, "folds": fold_summaries,
            "paired": paired, "n_pred_records": len(all_preds),
            # per-row out-of-fold predictions for every arm — enables the
            # forecast->economics join that the first screen lacked
            "preds": all_preds}


def _paired_analysis(preds):
    """Paired out-of-fold loss differences, block-bootstrapped by day."""
    from collections import defaultdict as dd

    # per (experiment, anchor, fold): obs keyed by (day, ticker, checkpoint)
    groups = dd(lambda: dd(list))
    for p in preds:
        gkey = (p["experiment"], p["anchor"], p["fold"])
        okey = (p["day"], p["ticker"], p["checkpoint_s"])
        groups[gkey][okey].append((p["variant"], p["y"], p["p"]))

    rng = np.random.default_rng(SEED)
    out = {}
    for (exp, anchor, fold), obs_map in groups.items():
        # pivot: each obs -> {variant: p}; require P0_cal & at least one P1
        rows = []
        for (day, ticker, cp), items in obs_map.items():
            pv = {}
            y = None
            for v, yy, pp in items:
                pv[v] = pp
                y = yy
            if y is None:
                continue
            rows.append({"day": day, "ticker": ticker, "cp": cp, "y": y, "pv": pv})
        if len(rows) < 10:
            continue
        comparisons = []
        # (challenger, baseline): vs P0_cal isolates total added value;
        # P1-vs-P1_noBTC isolates the BTC block; P1-vs-P1_noMkt the market block.
        for challenger, base in (
            ("P1", "P0_cal"), ("P1_noBTC", "P0_cal"), ("P1_noMkt", "P0_cal"),
            ("P1_min", "P0_cal"), ("P1", "P1_noBTC"), ("P1", "P1_noMkt"),
        ):
            pairs = [(r["y"], r["pv"].get(base), r["pv"].get(challenger))
                     for r in rows
                     if base in r["pv"] and challenger in r["pv"]]
            if len(pairs) < 10:
                continue
            d_ll = np.array([_log_loss([y], [pb]) - _log_loss([y], [pc])
                             for y, pb, pc in pairs])
            d_br = np.array([_brier([y], [pb]) - _brier([y], [pc])
                             for y, pb, pc in pairs])
            # block bootstrap over days
            pair_rows = [r for r in rows if base in r["pv"] and challenger in r["pv"]]
            pday = defaultdict(list)
            for i, r in enumerate(pair_rows):
                pday[r["day"]].append(i)
            uniq_days = sorted(pday)
            if len(uniq_days) < 2:
                continue
            boots_ll, boots_br = [], []
            for _ in range(BOOTSTRAP_N):
                sample_days = rng.choice(uniq_days, size=len(uniq_days), replace=True)
                idx = [i for d in sample_days for i in pday[d]]
                ys = np.array([pair_rows[i]["y"] for i in idx])
                pb = np.array([pair_rows[i]["pv"][base] for i in idx])
                pc = np.array([pair_rows[i]["pv"][challenger] for i in idx])
                boots_ll.append(_log_loss(ys, pb) - _log_loss(ys, pc))
                boots_br.append(_brier(ys, pb) - _brier(ys, pc))
            comparisons.append({
                "challenger": challenger, "baseline": base,
                "n_pairs": len(pairs),
                "mean_d_logloss": round(float(np.mean(d_ll)), 5),
                "mean_d_brier": round(float(np.mean(d_br)), 5),
                "ll_lcb95": round(float(np.percentile(boots_ll, 5)), 5),
                "ll_ucb95": round(float(np.percentile(boots_ll, 95)), 5),
                "br_lcb95": round(float(np.percentile(boots_br, 5)), 5),
                "br_ucb95": round(float(np.percentile(boots_br, 95)), 5),
                "n_days": len(uniq_days),
            })
        key = f"{exp}|{anchor}|{fold}"
        out[key] = {"n_obs": len(rows), "comparisons": comparisons}
    return out


# ---------------------------------------------------------------------------
# Stage 4: indicative economics (book archive overlap)
# ---------------------------------------------------------------------------

def _probe_book_coverage() -> dict:
    """Book-archive coverage WITHOUT opening the multi-GB WAL databases.

    The live archiver writes a heartbeat JSON with per-ticker coverage state;
    that plus file mtimes establishes overlap cheaply. Direct DB reads on
    kalshi_book_archive_live2.db (71GB WAL) are prohibitive for a screen.
    """
    rep = {"method": "heartbeat+filesystem (no book_events reads)", "archives": []}
    hb_path = ROOT / "data" / "kalshi_book_archiver.heartbeat.json"
    if hb_path.exists():
        try:
            hb = json.loads(hb_path.read_text(encoding="utf-8"))
            rep["heartbeat"] = {
                "ts_utc": hb.get("ts_utc"),
                "collector_instance_id": hb.get("collector_instance_id"),
                "db_path": hb.get("db_path"),
                "queue_depth": hb.get("queue_depth"),
                "overflow_total": hb.get("overflow_total"),
                "dropped_total": hb.get("dropped_total"),
                "n_tickers_covered": len(hb.get("coverage", {})),
                "ticker_range": (
                    min(hb["coverage"]), max(hb["coverage"])
                ) if hb.get("coverage") else None,
            }
        except Exception as exc:
            rep["heartbeat_error"] = str(exc)[:200]
    for name in ("kalshi_book_archive_live2.db", "kalshi_book_archive_active.db",
                 "kalshi_book_archive.db"):
        p = ROOT / "data" / name
        if p.exists():
            rep["archives"].append({
                "path": f"data/{name}",
                "size_mb": round(p.stat().st_size / 1e6, 1),
                "mtime_utc": _iso(p.stat().st_mtime),
                "wal_size_mb": round(
                    (p.parent / (p.name + "-wal")).stat().st_size / 1e6, 1)
                if (p.parent / (p.name + "-wal")).exists() else 0,
            })
    # preserved snapshots
    for d in ("preserved_book_archive_2026-11-06", "preserved_book_archive_2026-11-07"):
        dp = ROOT / "data" / d
        if dp.is_dir():
            for p in dp.glob("*.db"):
                rep["archives"].append({
                    "path": f"data/{d}/{p.name}",
                    "size_mb": round(p.stat().st_size / 1e6, 1),
                    "mtime_utc": _iso(p.stat().st_mtime),
                })
    return rep


def stage_economics(dataset, hi):
    """Indicative taker economics at recorded decision-time quotes.

    For each checkpoint row and each side, compute taker EV =
    p_side - ask - exact_taker_fee - reserves(0 here) in cents, for both
    probability bases (p_raw ~ settlement dist, p_cal ~ p_final_yes).
    Top-of-book, 1-contract indicative only — NOT a fill model.
    """
    rep = {"book_coverage": _probe_book_coverage()}
    try:
        from merid.event_venues.kalshi.parabolic_fees import kalshi_fee_cents_exact
    except Exception as exc:
        rep["fee_import_error"] = str(exc)[:200]
        kalshi_fee_cents_exact = None

    ev_rows = []
    for r in dataset:
        y = r["y"]
        for side in ("yes", "no"):
            ask = r.get(f"{side}_ask_cents")
            if ask is None:
                continue
            ask = float(ask)
            depth = r.get(f"{side}_depth")
            for pk in ("p_raw", "p_cal"):
                p = r.get(pk)
                if p is None:
                    continue
                p_side = p if side == "yes" else 1.0 - p
                fee_c = 0.0
                if kalshi_fee_cents_exact is not None:
                    try:
                        fee_c = float(kalshi_fee_cents_exact(
                            ask / 100.0, 1, "taker"))
                    except Exception:
                        # fallback: taker parabolic fee in cents,
                        # 0.07 * p * (1-p) * 100 (p in dollars)
                        fee_c = (0.07 * (ask / 100.0)
                                 * (1.0 - ask / 100.0) * 100.0)
                gross_c = (p_side - ask / 100.0) * 100.0
                ev_rows.append({
                    "ticker": r["ticker"], "asset": r["asset"],
                    "checkpoint_s": r["checkpoint_s"], "day": r["day_utc"],
                    "side": side, "baseline": pk,
                    "ask_cents": ask, "fee_cents": round(fee_c, 3),
                    "gross_edge_cents": round(gross_c, 3),
                    "net_ev_cents": round(gross_c - fee_c, 3),
                    "settled": int(y if side == "yes" else 1 - y),
                    "book_is_executable": r.get("book_is_executable"),
                    "book_age_ms": r.get("book_age_ms"),
                })
    rep["n_ev_rows"] = len(ev_rows)
    rep["depth_field_present"] = sum(
        1 for r in dataset if r.get("yes_depth") or r.get("no_depth"))

    for pk in ("p_raw", "p_cal"):
        for side in ("yes", "no"):
            sub = [e for e in ev_rows
                   if e["baseline"] == pk and e["side"] == side]
            if not sub:
                continue
            net = np.array([e["net_ev_cents"] for e in sub])
            key = f"{pk}|{side}"
            rep[key] = {
                "n": len(sub),
                "mean_net_ev_cents": round(float(np.mean(net)), 3),
                "median_net_ev_cents": round(float(np.median(net)), 3),
                "pct_net_ev_gt_0": round(float(np.mean(net > 0)), 3),
                "pct_net_ev_gt_1c": round(float(np.mean(net > 1.0)), 3),
                "pct_net_ev_gt_2c": round(float(np.mean(net > 2.0)), 3),
                "sum_net_ev_cents_if_all_taken": round(float(np.sum(net)), 1),
            }
    # per-checkpoint for the production baseline
    rep["by_checkpoint_p_cal"] = {}
    for cp in CHECKPOINTS_S:
        sub = [e for e in ev_rows if e["baseline"] == "p_cal"
               and e["checkpoint_s"] == cp]
        if sub:
            net = np.array([e["net_ev_cents"] for e in sub])
            rep["by_checkpoint_p_cal"][f"h{int(cp)}"] = {
                "n": len(sub),
                "mean_net_ev_cents": round(float(np.mean(net)), 3),
                "pct_gt_1c": round(float(np.mean(net > 1.0)), 3),
            }
    rep["caveats"] = [
        "Top-of-book 1-contract indicative EV; no depth walk, no fill model, "
        "no reserves/slippage beyond the exact entry fee.",
        "Settlement pays $1/$0 with no exit fee assumed (verify contract terms).",
        "Snapshot asks are decision-time quotes; staleness = book_age_ms.",
        "Shadow-model EV comparison requires per-row shadow probabilities — "
        "the offline screen did not persist them; the prospective lane must "
        "emit p_shadow per eval to enable this join.",
    ]
    return rep


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def write_report(out_dir, prov, meta, ev, econ):
    lines = ["# Lead–Lag Feasibility Screen — 2026-11-12", ""]
    lines.append("Read-only offline screen per MERID_LEAD_LAG_SHADOW_LANE_DESIGN_2026-11-12.md.\n")

    lines.append("## 1. Data provenance\n")
    ra = prov.get("rti_archive", {})
    lines.append(f"- RTI archive span: {ra.get('per_day_rows')}")
    lines.append(f"- Decision screen window (UTC): {prov.get('decision_window_utc')}")
    lines.append(f"- Decisions in window: {prov.get('decisions_total_in_window')} "
                 f"across {prov.get('distinct_tickers')} tickers")
    lines.append(f"- Research-eligible production rows: see provenance.json")
    lines.append(f"- Rows with snapshot probs: {prov.get('with_snapshot')}; "
                 f"with settled outcome: {prov.get('with_settled_outcome')}")
    lines.append(f"- Route-dedup probability mismatches: "
                 f"{meta.get('route_prob_mismatch_candidates')}")
    lines.append(f"- Outcome conflict tickers: {meta.get('n_outcome_conflicts')}")
    lines.append("")
    lines.append("### RTI per-day coverage\n")
    lines.append("| day | ticks |")
    lines.append("|---|---|")
    for d, n in (ra.get("per_day_rows") or {}).items():
        lines.append(f"| {d} | {n} |")
    lines.append("")
    lines.append("### Decisions per day\n")
    lines.append("| day | decisions |")
    lines.append("|---|---|")
    for r in prov.get("decisions_per_day", []):
        lines.append(f"| {r['day_utc']} | {r['n']} |")
    lines.append("")

    lines.append("## 2. Dataset\n")
    lines.append(f"- Candidate rows after route dedup: {meta.get('candidates_after_route_dedup')}")
    lines.append(f"- Forecast dataset rows: see dataset.jsonl")
    lines.append(f"- Coverage: `{json.dumps(meta.get('coverage', {}))}`")
    lines.append("")

    lines.append("## 3. Evaluation coverage\n")
    for k, v in (ev.get("coverage") or {}).items():
        lines.append(f"- `{k}`: {v}")
    lines.append("")

    lines.append("## 4. Fold metrics (test-fold log-loss / Brier)\n")
    for f in ev.get("folds", []):
        lines.append(f"### {f.get('experiment')} / {f.get('anchor')} / {f.get('fold')} "
                     f"(n_test={f.get('n_test', f.get('n'))})")
        for vn, m in (f.get("variants") or {}).items():
            if "log_loss" in m:
                lines.append(f"- {vn}: ll={m['log_loss']} brier={m['brier']} "
                             f"n={m.get('n_test')} base={m.get('base_rate')}")
            else:
                lines.append(f"- {vn}: {m.get('status', m)}")
        lines.append("")

    lines.append("## 5. Paired differences (challenger − P0_cal; >0 favors challenger)\n")
    for k, v in (ev.get("paired") or {}).items():
        lines.append(f"### {k} (n_obs={v.get('n_obs')})")
        for c in v.get("comparisons", []):
            lines.append(f"- {c['challenger']} vs {c['baseline']}: "
                         f"dLL={c['mean_d_logloss']} (90% CI [{c['ll_lcb95']}, {c['ll_ucb95']}]) "
                         f"dBrier={c['mean_d_brier']} n={c['n_pairs']} days={c['n_days']}")
        lines.append("")

    lines.append("## 6. Indicative economics (taker EV at snapshot asks, exact fee)\n")
    hb = (econ.get("book_coverage") or {}).get("heartbeat") or {}
    if hb:
        lines.append(f"- Book archiver last heartbeat: {hb.get('ts_utc')} "
                     f"(instance {hb.get('collector_instance_id')}); "
                     f"tickers {hb.get('ticker_range')}; "
                     f"dropped_total={hb.get('dropped_total')} "
                     f"(lossy under load)")
    for k in ("p_raw|yes", "p_raw|no", "p_cal|yes", "p_cal|no"):
        v = econ.get(k)
        if v:
            lines.append(f"- {k}: n={v['n']} mean_net={v['mean_net_ev_cents']}c "
                         f"median={v['median_net_ev_cents']}c "
                         f"%>0={v['pct_net_ev_gt_0']} %>1c={v['pct_net_ev_gt_1c']} "
                         f"%>2c={v['pct_net_ev_gt_2c']}")
    lines.append("- By checkpoint (p_cal): "
                 + json.dumps(econ.get("by_checkpoint_p_cal", {})))
    for c in econ.get("caveats", []):
        lines.append(f"- caveat: {c}")
    lines.append("")

    lines.append("## 7. Interpretation notes (review corrections 2026-11-13)\n")
    lines.append(
        "- A failed future-information diagnostic does not identify the cause. "
        "Neither the deployable variants nor the future-shifted diagnostic "
        "improved the incumbent on this small test block. The screen cannot "
        "distinguish absence of incremental information, estimation error, "
        "model misspecification, distribution shift, or insufficient power. "
        "Future BTC returns are not an oracle for another asset's settlement "
        "outcome; they can remain unhelpful when the target's own price, "
        "banked samples, and baseline probability already explain most of "
        "the outcome. The diagnostic is retained as a pipeline check, not a "
        "required positive control.")
    lines.append(
        "- Negative average EV does not imply no tradable subset. The window "
        "provided no demonstrated incremental taker opportunity from "
        "lead-lag; it does not establish that a properly selected, "
        "deduplicated subset lacks opportunity, nor that value must be "
        "expressed through maker or settlement lanes. Because per-row "
        "shadow probabilities were not persisted, the key comparison — "
        "incremental opportunities under p_shadow vs p_incumbent — was not "
        "completed. (Repaired: the runner now persists per-row predictions.)")
    lines.append(
        "- Receipt-time reconstruction supports latency robustness, not full "
        "production deployability. Archiver receipt time establishes "
        "availability to the archiver, not to the production adapter; small "
        "average lag does not characterize all operational failure modes. "
        "Prospective capture must measure the production path directly.")
    lines.append(
        "- Bootstrap limitation is specific to this screen: with a single "
        "test day, day-block resampling is not meaningful. Shorter blocks "
        "could technically be resampled but would not create evidence about "
        "performance across days or regimes; descriptive paired losses are "
        "more useful than a fragile significance calculation here.")
    lines.append("")
    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all",
                    choices=["provenance", "dataset", "evaluate", "economics",
                             "report", "all"])
    ap.add_argument("--out", default=str(OUT_DIR))
    ap.add_argument("--lo", type=float, default=None,
                    help="decision_ts window start (epoch s); default = RTI min")
    ap.add_argument("--hi", type=float, default=None,
                    help="decision_ts window end (epoch s); default = RTI max")
    ap.add_argument("--reuse-dataset", action="store_true",
                    help="load dataset.jsonl from --out instead of rebuilding")
    args = ap.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    prov = meta = ev = econ = None
    lo = hi = None

    # Effective decision window: explicit args win; else RTI archive bounds.
    if args.lo is None or args.hi is None:
        con = _connect_ro(RTI_DB)
        mn, mx = con.execute(
            "select min(src_ts_ms), max(src_ts_ms) from rti_ticks").fetchone()
        con.close()
        rti_lo, rti_hi = mn / 1000.0, mx / 1000.0
    else:
        rti_lo = rti_hi = None
    eff_lo = args.lo if args.lo is not None else rti_lo
    eff_hi = args.hi if args.hi is not None else rti_hi

    if args.stage in ("provenance", "all"):
        print("[stage] provenance ...", flush=True)
        prov, (lo, hi) = stage_provenance(eff_lo, eff_hi)
        (out_dir / "provenance.json").write_text(
            json.dumps(prov, indent=2, default=str), encoding="utf-8")
        print(f"window epoch s: {lo:.0f} -> {hi:.0f}", flush=True)
        print(f"decisions in window: {prov['decisions_total_in_window']}", flush=True)
        if args.stage == "provenance":
            return 0
    else:
        lo, hi = eff_lo, eff_hi
        pfile = out_dir / "provenance.json"
        if pfile.exists():
            prov = json.loads(pfile.read_text(encoding="utf-8"))

    print(f"[window] decision_ts {lo:.0f} -> {hi:.0f}", flush=True)

    dataset = None
    if args.stage in ("dataset", "evaluate", "economics", "all"):
        ds_file = out_dir / "dataset.jsonl"
        if args.reuse_dataset and ds_file.exists():
            print("[stage] loading cached dataset ...", flush=True)
            dataset = []
            for line in ds_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                r = json.loads(line)
                # JSON turns float horizon keys into strings; restore floats
                for k in list(r.keys()):
                    if k.endswith("_ret_src") or k.endswith("_ret_recv") \
                            or "_ret_recv_p" in k:
                        r[k] = {float(h): v for h, v in (r[k] or {}).items()}
                dataset.append(r)
            meta = json.loads(
                (out_dir / "dataset_meta.json").read_text(encoding="utf-8"))
            print(f"loaded {len(dataset)} cached rows", flush=True)
        else:
            print("[stage] loading RTI ...", flush=True)
            rti = load_rti_series()
            print({a: int(len(s.src)) for a, s in rti.items()}, flush=True)
            print("[stage] building dataset ...", flush=True)
            con = _connect_ro(AUDIT_DB)
            dataset, meta = build_forecast_dataset(rti, con, lo, hi)
            con.close()
            (out_dir / "dataset_meta.json").write_text(
                json.dumps(meta, indent=2, default=str), encoding="utf-8")
            with open(ds_file, "w", encoding="utf-8") as f:
                for r in dataset:
                    f.write(json.dumps(r, default=str) + "\n")
            print(f"dataset rows: {len(dataset)}", flush=True)
            print("coverage:", json.dumps(meta["coverage"]), flush=True)

    if args.stage in ("evaluate", "all"):
        print("[stage] evaluating ...", flush=True)
        ev = stage_evaluate(dataset)
        preds = ev.pop("preds", [])
        (out_dir / "evaluation.json").write_text(
            json.dumps(ev, indent=2, default=str), encoding="utf-8")
        with open(out_dir / "predictions.jsonl", "w", encoding="utf-8") as f:
            for p in preds:
                f.write(json.dumps(p, default=str) + "\n")
        print(f"eval done ({len(preds)} pred records)", flush=True)

    if args.stage in ("economics", "all"):
        econ = stage_economics(dataset, hi)
        (out_dir / "economics.json").write_text(
            json.dumps(econ, indent=2, default=str), encoding="utf-8")

    if prov is not None and meta is not None:
        write_report(out_dir, prov, meta, ev or {}, econ or {})
    elif args.stage == "report":
        # regenerate report.md from persisted artifacts
        def _lj(name):
            p = out_dir / name
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        prov = _lj("provenance.json")
        meta = _lj("dataset_meta.json")
        ev = _lj("evaluation.json")
        econ = _lj("economics.json")
        if prov and meta:
            write_report(out_dir, prov, meta, ev, econ)
    print(f"[done] outputs in {out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
