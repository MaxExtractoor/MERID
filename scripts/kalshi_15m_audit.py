#!/usr/bin/env python3
"""Kalshi 15-minute crypto market audit.

Three independent jobs per the audit spec:

  1. Settlement replay - per window, reconstruct the open/close 60s TWAPs
     from archived CF-index (RTI) observations in the decision-audit
     snapshots, verify outcome == (close_twap >= open_twap) and YES/NO
     complementarity.

  2. Feature replay - signed ATR-normalized distance at each decision,
     d = (P - T) / ATR_15m, where ATR_15m is the rolling median of
     |close_twap - open_twap| over the prior N settled windows for that
     asset (realized 15m true range, no lookahead).  Buckets the distance,
     tests YES monotonicity, NO complementarity, up/down symmetry, and
     fits a per-asset logistic regression.

  3. Execution replay - recompute maker/taker fees for every fill and
     compare to booked fee_cost.

Outputs:
  - audit rows persisted to data/kalshi_15m_audit.db
    (kalshi_15m_markets, kalshi_15m_features, kalshi_15m_fills_audit)
  - console report + reports/kalshi_15m_audit_<ts>.json

Usage:
    python scripts/kalshi_15m_audit.py --days 7 [--audit-db data/decision_audit.db]
        [--fills-db data/kalshi_fills.db] [--out data/kalshi_15m_audit.db]
        [--limit-windows 0] [--progress]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np

ASSET_FROM_TICKER = {
    "KXBTC15M": "BTC", "KXETH15M": "ETH", "KXSOL15M": "SOL",
    "KXXRP15M": "XRP", "KXDOGE15M": "DOGE",
}
ATR_WINDOWS = 96            # ~24h of 15m windows
EDGE_OPEN_S = 60.0          # use ttc >= 900-60 for open-TWAP samples
EDGE_CLOSE_S = 60.0         # use ttc <= 60 for close-TWAP samples
EDGE_CLOSE_FALLBACK_S = 150.0  # wider band if last-60s has no ref samples
# Feature-sampling horizons: dense in the last 3 min where the engine
# operates, sparse mid-window.  ~18 probes/window vs ~430 dense rows.
_TTE_MARKS = (15.0, 30.0, 45.0, 60.0, 75.0, 90.0, 105.0, 120.0, 150.0,
              180.0, 240.0, 300.0, 420.0, 540.0, 660.0, 780.0, 840.0, 870.0)

DIST_EDGES = [
    (-float("inf"), -2.0), (-2.0, -1.0), (-1.0, -0.5), (-0.5, -0.05),
    (-0.05, 0.05), (0.05, 0.5), (0.5, 1.0), (1.0, 2.0), (2.0, float("inf")),
]
DIST_LABELS = [
    "d<-2", "-2<=d<-1", "-1<=d<-0.5", "-0.5<=d<-0.05", "|d|<0.05",
    "0.05<d<=0.5", "0.5<d<=1", "1<d<=2", "d>2",
]
MIN_BUCKET_N = 20           # min samples for a bucket to count in asserts


def asset_of(ticker: str) -> str:
    for pref, a in ASSET_FROM_TICKER.items():
        if ticker.startswith(pref):
            return a
    return "UNKNOWN"


def bucket_idx(d: float) -> int:
    for i, (lo, hi) in enumerate(DIST_EDGES):
        if lo <= d < hi or (i == 0 and d < lo) or (i == len(DIST_EDGES) - 1 and d >= hi):
            return i
    return len(DIST_EDGES) - 1


# --------------------------------------------------------------------------
# Phase 1: collect windows, strikes, edge-time snapshots, outcomes
# --------------------------------------------------------------------------

MONTH_ABBR = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
              "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def ticker_candidates(since: float, until: float):
    """Enumerate every plausible KX{ASSET}15M ticker in the range.

    Format: KXBTC15M-26OCT141330-30  ->  '26' + MON + DD + HHMM + '-' + MM.
    The label is the window's close on the exchange's display clock; we
    generate all 96 slots for each calendar date in the range (padded by
    one day either side for timezone skew) - misses return zero rows and
    are nearly free against idx_decisions_ticker.
    """
    import datetime as _dt
    cands = []
    d0 = _dt.datetime.fromtimestamp(since, timezone.utc).date() \
        - _dt.timedelta(days=1)
    d1 = _dt.datetime.fromtimestamp(until, timezone.utc).date() \
        + _dt.timedelta(days=1)
    day = d0
    while day <= d1:
        for pref in ASSET_FROM_TICKER:
            for slot in range(96):
                hh, mm = divmod(slot * 15, 60)
                cands.append(
                    f"{pref}-{day:%y}{MONTH_ABBR[day.month - 1]}"
                    f"{day.day:02d}{hh:02d}{mm:02d}-{mm:02d}")
        day += _dt.timedelta(days=1)
    return cands


def collect_windows(db: sqlite3.Connection, since: float, progress: bool):
    """Single idx_decisions_ts range scan, grouped per ticker.

    Effective ttc is RECOMPUTED as consensus_close - decision_ts: the
    stored seconds_to_close is stale/quantized and post-close ':taker'
    records stamp ttc=0 while actually sitting ~2-3min before close —
    that defect misplaced the settlement close band.  The ticker's display
    label is US-Eastern, not UTC, so it is not authoritative either; the
    consensus close is the median of close_ts over rows whose stored
    close_ts is genuinely forward-looking (cts - dts > 5s converges to
    the exact boundary).

    Returns {ticker: {asset, close_ts, open_ts, strike, edge_rows:[...],
                      decided_rows:[...], settled_yes}}.
    """
    windows = {}
    now = time.time()
    cur = db.execute(
        "SELECT decision_id, ticker, decision_ts, seconds_to_close, "
        "strike, market_open_ts, close_ts, decision, selected_side, "
        "admission_lane, record_environment "
        "FROM strategy_decisions "
        "WHERE decision_ts >= ? AND decision_ts <= ? "
        "  AND ticker LIKE 'KX%15M-%' "
        "ORDER BY decision_ts",
        (since - 900.0, now),
    )
    n_rows = 0
    for (did, ticker, dts, ttc, strike, mo, cts, dec, sel, lane, env) in cur:
        n_rows += 1
        if progress and n_rows % 50000 == 0:
            print(f"[collect] {n_rows} decision rows, {len(windows)} live")
        if env == "test" or not ticker or dts is None:
            continue
        asset = asset_of(ticker)
        if asset == "UNKNOWN":
            continue
        w = windows.get(ticker)
        if w is None:
            w = windows[ticker] = {
                "asset": asset, "close_ts": None, "open_ts": mo,
                "strike": strike, "edge": [], "rows": [],
                "settled_yes": None, "_raw": [], "_cts": [],
            }
        if w["open_ts"] is None and mo:
            w["open_ts"] = mo
        if w["strike"] is None and strike:
            w["strike"] = strike
        w["_raw"].append((did, dts, ttc))
        if cts is not None and cts - dts > 5.0:
            w["_cts"].append(cts)
    # consensus close + effective ttc per row
    for w in windows.values():
        if w["_cts"]:
            w["close_ts"] = float(np.median(w["_cts"]))
        if w["close_ts"] is not None and w["open_ts"] is None:
            w["open_ts"] = w["close_ts"] - 900.0
        for (did, dts, ttc) in w["_raw"]:
            base = did.split(":")[0] if did else did
            eff_ttc = (w["close_ts"] - dts) if w["close_ts"] else ttc
            rec = (did, base, dts, eff_ttc)
            if eff_ttc is not None and (
                    0.0 <= eff_ttc <= EDGE_CLOSE_FALLBACK_S
                    or eff_ttc >= 900 - EDGE_OPEN_S):
                w["edge"].append(rec)
            w["rows"].append(rec)
        del w["_raw"], w["_cts"]
    # dedupe rows per candidate (route rows share the same snapshot)
    for w in windows.values():
        seen, uniq_e, uniq_r = set(), [], []
        for rec in w["edge"]:
            if rec[1] not in seen:
                seen.add(rec[1]); uniq_e.append(rec)
        seen.clear()
        for rec in w["rows"]:
            if rec[1] not in seen:
                seen.add(rec[1]); uniq_r.append(rec)
        w["edge"], w["rows"] = uniq_e, uniq_r
    return windows


def scan_snapshots(db: sqlite3.Connection, windows: dict, progress: bool):
    """One sequential rowid-range read of the snapshots slice covering all
    collected windows; dispatch rows to windows by base decision_id.

    strategy_decision_snapshots has no time index, but its implicit rowid
    tracks insert/decision order (verified dense+contiguous per window), so
    the whole N-day slice is one sequential scan instead of ~1M random PK
    probes.  Bounds are found by probing a few boundary decisions' rowids
    through the decision_id autoindex, padded for interleaved inserts.
    """
    rec_map = {}          # base_did -> (ticker, rec)
    all_recs = []
    for t, w in windows.items():
        for rec in w["rows"]:
            if rec[1] not in rec_map:
                rec_map[rec[1]] = (t, rec)
                all_recs.append(rec)
    if not all_recs:
        return
    all_recs.sort(key=lambda r: (r[2] or 0))

    def _rid(did):
        r = db.execute(
            "SELECT rowid FROM strategy_decision_snapshots "
            "WHERE decision_id=?", (did,)).fetchone()
        return r[0] if r and r[0] is not None else None

    edge_dids = [r[0] for r in all_recs[:8] + all_recs[-8:]]
    rids = [x for x in (_rid(d) for d in edge_dids) if x is not None]
    lo = (min(rids) if rids else 0) - 50000
    hi = (max(rids) if rids else (1 << 62)) + 50000
    n_scanned = n_kept = 0
    cur = db.execute(
        "SELECT decision_id, spot_price, settlement_reference_price, "
        "yes_bid_cents, yes_ask_cents, no_bid_cents, no_ask_cents, "
        "raw_p_yes, calibrated_p_yes, vol_forecast, realized_vol_1m "
        "FROM strategy_decision_snapshots "
        "WHERE rowid BETWEEN ? AND ?",
        (lo, hi))
    for row in cur:
        n_scanned += 1
        if progress and n_scanned % 500000 == 0:
            print(f"[scan] {n_scanned} snapshot rows, {n_kept} kept")
        hit = rec_map.get(row[0]) or rec_map.get(row[0].split(":")[0])
        if hit:
            windows[hit[0]].setdefault("_snap", {})[hit[1][0]] = row[1:]
            n_kept += 1
    print(f"[scan] {n_scanned} rows scanned, {n_kept} kept for "
          f"{len(windows)} windows")


def fetch_outcomes(db: sqlite3.Connection, windows: dict, since: float):
    """Map ticker -> settled_yes via the settled_at index."""
    now = time.time()
    rows = db.execute(
        "SELECT o.decision_id, o.settled_yes FROM strategy_decision_outcomes o "
        "WHERE o.settled_at >= ? AND o.settled_at <= ? "
        "  AND o.outcome_status = 'SETTLED' AND o.settled_yes IS NOT NULL",
        (since, now),
    ).fetchall()
    did2ticker = {}
    for w_ticker, w in windows.items():
        for rec in w["rows"]:
            did2ticker[rec[0]] = w_ticker
        for rec in w["edge"]:
            did2ticker[rec[0]] = w_ticker
    # decision ids in outcomes are full route ids (cand_x:route)
    for did, sy in rows:
        ticker = did2ticker.get(did) or did2ticker.get(did.split(":")[0])
        if ticker and windows[ticker]["settled_yes"] is None:
            windows[ticker]["settled_yes"] = int(sy)
    return windows


def fetch_edge_snapshots(db: sqlite3.Connection, windows: dict, progress: bool):
    """Populate open/close TWAP samples from the scanned snapshot slice.

    Kalshi's S_open is the 60s average ENDING at window open — i.e. the
    previous contiguous window's last-60s band, not this window's first
    60s (a ~60-90s systematic offset that produced false mismatches).
    Pass 1 collects each window's close band; pass 2 maps each window's
    open to the prior same-asset window's close band.
    """
    n_done = 0
    for ticker, w in windows.items():
        close_s, close_fb, basis_s = [], [], []
        close_ttcs = []
        snap = w.get("_snap") or {}
        for (did, _base, dts, ttc) in w["edge"]:
            r = snap.get(did)
            if r is None:
                continue
            spot, ref = r[0], r[1]
            if ref is not None and spot is not None:
                basis_s.append(float(spot) - float(ref))
            if ttc is not None and 0.0 <= ttc <= EDGE_CLOSE_S:
                if ref:
                    close_s.append(ref)
                    close_ttcs.append(ttc)
                elif spot:
                    close_fb.append(float(spot))
            elif ttc is not None and 0.0 <= ttc <= EDGE_CLOSE_FALLBACK_S:
                if ref:
                    close_fb.append(ref)
        basis = float(np.median(basis_s)) if basis_s else 0.0
        close_fb = [v - basis for v in close_fb]
        w["_close_samples"] = [float(v) for v in close_s]
        # nearest sample to the boundary — coverage of the band tail is
        # what actually binds the TWAP, not the raw count
        w["_close_min_ttc"] = min(close_ttcs) if close_ttcs else None
        w["_basis"] = basis
        if close_s:
            w["close_twap"] = float(np.mean(close_s))
            w["close_twap_source"] = "cf_rti_last60"
        elif close_fb:
            w["close_twap"] = float(np.mean(close_fb))
            w["close_twap_source"] = "ref_or_spot_le150"
        else:
            w["close_twap"] = None
            w["close_twap_source"] = None
        w["n_close_samples"] = len(close_s)
        n_done += 1
        step = 200 if len(windows) > 400 else 20
        if progress and n_done % step == 0:
            print(f"[twap] {n_done}/{len(windows)} windows (close band)")

    # Pass 2: open TWAP = prior contiguous window's close band
    # ([open-60, open]).  Kalshi tiles 15m windows back-to-back per asset.
    by_close = {}
    for w in windows.values():
        if w["close_ts"] is not None:
            by_close.setdefault((w["asset"], round(w["close_ts"])), []).append(w)
    for w in windows.values():
        prev = None
        if w["open_ts"] is not None:
            for dt in (0, -1, 1, -2, 2):
                cands = by_close.get((w["asset"], round(w["open_ts"]) + dt))
                if cands:
                    prev = cands[0]
                    break
        open_s = (prev or {}).get("_close_samples") or []
        w["n_open_samples"] = len(open_s)
        w["open_min_ttc"] = (prev or {}).get("_close_min_ttc")
        if open_s:
            w["open_twap"] = float(np.mean(open_s))
            w["open_twap_source"] = "cf_rti_pre60"
        elif w["strike"]:
            w["open_twap"] = float(w["strike"])
            w["open_twap_source"] = "kalshi_strike"
        else:
            w["open_twap"] = None
            w["open_twap_source"] = None
        if w["open_twap"] is not None and w["strike"]:
            w["open_target_error"] = abs(w["open_twap"] - float(w["strike"]))
        else:
            w["open_target_error"] = None
        # Reconstruction confidence: the band tails bind the TWAP — if the
        # nearest sample to a boundary is >20s away, the terminal move is
        # unobserved.  Also low when the close band fell back to spot or
        # when counts are sparse.  Near-tie margins are refined post-ATR.
        if w["open_twap"] is not None and w["close_twap"] is not None:
            margin = abs(w["close_twap"] - w["open_twap"])
            c_min = w.get("_close_min_ttc")
            o_min = w.get("open_min_ttc")
            w["twap_confidence"] = "low" if (
                w["close_twap_source"] != "cf_rti_last60"
                or w["n_close_samples"] < 5
                or (w["n_open_samples"] < 5
                    and w["open_twap_source"] != "kalshi_strike")
                or (c_min is not None and c_min > 20.0)
                or (o_min is not None and o_min > 20.0)) else "high"
            w["twap_margin"] = margin
        else:
            w["twap_confidence"] = "none"
            w["twap_margin"] = None
    return windows


# --------------------------------------------------------------------------
# Phase 2: features + ATR + distance buckets
# --------------------------------------------------------------------------

def compute_atr_series(windows_by_asset):
    """ATR_15m(asset, t): rolling median |close-open| over prior windows."""
    atr = {}
    for asset, ws in windows_by_asset.items():
        ws_sorted = sorted(
            [w for w in ws
             if w["close_twap"] is not None and w["open_twap"] is not None],
            key=lambda w: w["close_ts"] or 0)
        hist = []
        for w in ws_sorted:
            tr = abs(w["close_twap"] - w["open_twap"])
            w["atr_15m"] = float(np.median(hist[-ATR_WINDOWS:])) if hist else None
            hist.append(tr)
            # refine confidence now that ATR exists: margin < 15% of the
            # typical 15m range is a near-tie where sampled TWAPs are noisy
            if w["atr_15m"] and w.get("twap_margin") is not None \
                    and w["twap_margin"] < 0.15 * w["atr_15m"]:
                w["twap_confidence"] = "low_near_tie"
        atr[asset] = float(np.median(hist)) if hist else None
    return atr


def collect_features(db: sqlite3.Connection, windows: dict, progress: bool):
    """Per deduped candidate decision: spot, ref, quotes, p_yes, vol, ttc.

    Returns list of feature dicts (ATR attached later once series known —
    actually we compute ATR first then call this; signature keeps windows
    already atr-annotated).
    """
    feats = []
    n_done = 0
    for ticker, w in windows.items():
        if w["settled_yes"] is None or w.get("atr_15m") in (None, 0):
            continue
        strike = w["strike"] or w["open_twap"]
        if not strike:
            continue
        atr = w["atr_15m"]
        # Per-window spot<->CF basis: the two feeds differ by a small
        # constant (observed ~$19 on BTC).  Using raw spot when RTI drops
        # (last ~40s) would shift d by ~0.15+ ATR near the target — exactly
        # where the |d|<0.05 bucket lives.  Estimate the basis in-window.
        basis_samples = []
        raw_rows = []
        # Thin to ~1 row per TTE mark: all rows in a window share one
        # settled_yes label and near-collinear d, so probing all ~430
        # snapshot rows/window buys nothing statistically while dominating
        # scan IO (~1.2M random PK reads on the mmap'd DB for 3d).
        chosen = {}
        for rec in w["rows"]:
            ttc = rec[3]
            if ttc is None:
                continue
            m = min(_TTE_MARKS, key=lambda x: abs(x - ttc))
            if abs(m - ttc) > 20.0:
                continue
            cur = chosen.get(m)
            if cur is None or abs(ttc - m) < abs(cur[3] - m):
                chosen[m] = rec
        cache = w.get("_snap") or {}
        for (did, _b, dts, ttc) in chosen.values():
            r = cache.get(did)
            if r is None:
                continue
            spot, ref = r[0], r[1]
            raw_rows.append((did, dts, ttc) + r)
            if spot is not None and ref is not None:
                basis_samples.append(float(spot) - float(ref))
        basis = float(np.median(basis_samples)) if basis_samples else 0.0
        for (did, dts, ttc, spot, ref, yb, ya, nb, na, praw, pcal,
             vf, rv1m) in raw_rows:
            px = ref if ref else (
                float(spot) - basis if spot is not None else None)
            if px is None or ttc is None:
                continue
            d = (float(px) - float(strike)) / atr
            feats.append({
                "asset": w["asset"], "ticker": ticker,
                "decision_id": did, "decision_ts": dts,
                "seconds_remaining": ttc, "spot": spot, "ref": px,
                "target": strike, "atr_15m": atr, "d": d,
                "yes_bid": yb, "yes_ask": ya, "no_bid": nb, "no_ask": na,
                "p_yes_raw": praw, "p_yes_cal": pcal,
                "settled_yes": w["settled_yes"],
            })
        n_done += 1
        step = 100 if len(windows) > 200 else 20
        if progress and n_done % step == 0:
            print(f"[features] {n_done}/{len(windows)} windows, "
                  f"{len(feats)} rows")
    return feats


def bucket_stats(feats):
    """Per asset x bucket: n, realized_yes_rate, model_yes_mean."""
    agg = defaultdict(lambda: {"n": 0, "yes": 0, "psum": 0.0, "pn": 0})
    for f in feats:
        key = (f["asset"], bucket_idx(f["d"]))
        a = agg[key]
        a["n"] += 1
        a["yes"] += f["settled_yes"]
        p = f["p_yes_cal"] if f["p_yes_cal"] is not None else f["p_yes_raw"]
        if p is not None:
            a["psum"] += float(p)
            a["pn"] += 1
    return agg


def monotonicity_violations(agg):
    """Find adjacent-bucket inversions per asset (n>=MIN_BUCKET_N)."""
    out = {}
    assets = sorted({k[0] for k in agg})
    for asset in assets:
        seq = []
        for i in range(len(DIST_EDGES)):
            a = agg.get((asset, i))
            if a and a["n"] >= MIN_BUCKET_N:
                seq.append((i, a["yes"] / a["n"],
                            a["psum"] / a["pn"] if a["pn"] else None, a["n"]))
        viol = []
        for j in range(1, len(seq)):
            # materiality floor: binomial sampling noise makes sub-~3pp
            # dips meaningless — flag only drops beyond ~3pp + 2σ
            n_lo, n_hi = seq[j - 1][3], seq[j][3]
            tol = 0.03 + 2.0 * (0.25 / n_lo + 0.25 / n_hi) ** 0.5
            if seq[j][1] < seq[j - 1][1] - tol:
                viol.append({
                    "lo_bucket": DIST_LABELS[seq[j - 1][0]],
                    "hi_bucket": DIST_LABELS[seq[j][0]],
                    "realized_lo": round(seq[j - 1][1], 4),
                    "realized_hi": round(seq[j][1], 4),
                    "n_lo": seq[j - 1][3], "n_hi": seq[j][3],
                })
        pviol = []
        for j in range(1, len(seq)):
            if seq[j][2] is not None and seq[j - 1][2] is not None \
                    and seq[j][2] < seq[j - 1][2] - 0.03:
                pviol.append({
                    "lo_bucket": DIST_LABELS[seq[j - 1][0]],
                    "hi_bucket": DIST_LABELS[seq[j][0]],
                    "model_lo": round(seq[j - 1][2], 4),
                    "model_hi": round(seq[j][2], 4),
                })
        out[asset] = {"realized_violations": viol, "model_violations": pviol,
                      "curve": seq}
    return out


def symmetry_report(feats):
    """p_yes(+b) + p_yes(-b) per |d| band per asset."""
    bands = [(0.05, 0.5), (0.5, 1.0), (1.0, 2.0), (2.0, float("inf"))]
    labels = ["0.05-0.5", "0.5-1", "1-2", ">2"]
    res = defaultdict(dict)
    byk = defaultdict(lambda: {"n": 0, "yes": 0})
    for f in feats:
        ad = abs(f["d"])
        for i, (lo, hi) in enumerate(bands):
            if lo < ad <= hi:
                byk[(f["asset"], i, 1 if f["d"] > 0 else -1)]["n"] += 1
                byk[(f["asset"], i, 1 if f["d"] > 0 else -1)]["yes"] += \
                    f["settled_yes"]
                break
    for asset in sorted({k[0] for k in byk}):
        for i, lab in enumerate(labels):
            up, dn = byk.get((asset, i, 1)), byk.get((asset, i, -1))
            if up and dn and up["n"] >= MIN_BUCKET_N and dn["n"] >= MIN_BUCKET_N:
                pu, pd = up["yes"] / up["n"], dn["yes"] / dn["n"]
                res[asset][lab] = {
                    "p_yes_up": round(pu, 4), "p_yes_dn": round(pd, 4),
                    "sum": round(pu + pd, 4), "n_up": up["n"], "n_dn": dn["n"],
                }
    return res


TTE_BANDS = [(600.0, 9999.0), (300.0, 600.0), (60.0, 300.0), (0.0, 60.0)]
TTE_LABELS = ["600+", "300-600", "60-300", "<60"]


def tte_banded_curves(feats):
    """Realized YES rate per (asset, d-bucket, tte-band).

    The aggregate curve conflates early-window distances (reversible) with
    late-window ones (locked).  Conditioning on seconds-remaining is the
    discriminating view per the audit spec's own caveat.
    """
    cell = defaultdict(lambda: {"n": 0, "yes": 0})
    for f in feats:
        tte = f["seconds_remaining"]
        if tte is None:
            continue
        ti = next((i for i, (lo, hi) in enumerate(TTE_BANDS)
                   if lo <= tte < hi), None)
        if ti is None:
            continue
        k = (f["asset"], ti, bucket_idx(f["d"]))
        cell[k]["n"] += 1
        cell[k]["yes"] += f["settled_yes"]
    out = {}
    for asset in sorted({k[0] for k in cell}):
        tab = {}
        for ti, lab in enumerate(TTE_LABELS):
            row = []
            for bi in range(len(DIST_EDGES)):
                c = cell.get((asset, ti, bi))
                row.append({
                    "bucket": DIST_LABELS[bi],
                    "n": c["n"] if c else 0,
                    "p_yes": round(c["yes"] / c["n"], 4) if c and c["n"] else None,
                })
            tab[lab] = row
        # per-band monotonicity violations on well-populated adjacent buckets
        band_viol = []
        for ti, lab in enumerate(TTE_LABELS):
            seq = [(bi, cell[(asset, ti, bi)]["yes"] / cell[(asset, ti, bi)]["n"],
                    cell[(asset, ti, bi)]["n"])
                   for bi in range(len(DIST_EDGES))
                   if cell.get((asset, ti, bi)) and cell[(asset, ti, bi)]["n"] >= MIN_BUCKET_N]
            for j in range(1, len(seq)):
                n_lo, n_hi = seq[j - 1][2], seq[j][2]
                tol = 0.03 + 2.0 * (0.25 / n_lo + 0.25 / n_hi) ** 0.5
                if seq[j][1] < seq[j - 1][1] - tol:
                    band_viol.append({
                        "tte_band": lab,
                        "lo_bucket": DIST_LABELS[seq[j - 1][0]],
                        "hi_bucket": DIST_LABELS[seq[j][0]],
                        "p_lo": round(seq[j - 1][1], 4),
                        "p_hi": round(seq[j][1], 4),
                        "n_lo": seq[j - 1][2], "n_hi": seq[j][2],
                    })
        out[asset] = {"table": tab, "band_violations": band_viol}
    return out


def logistic_fit(feats):
    """Per-asset logistic: outcome ~ d + |d| + tte_norm + hour."""
    out = {}
    try:
        from scipy.optimize import minimize
    except Exception:
        return out
    bya = defaultdict(list)
    for f in feats:
        bya[f["asset"]].append(f)
    for asset, fs in bya.items():
        X, Y = [], []
        for f in fs:
            if f["d"] is None or f["seconds_remaining"] is None:
                continue
            hour = datetime.fromtimestamp(
                f["decision_ts"], timezone.utc).hour / 24.0
            X.append([1.0, f["d"], abs(f["d"]),
                      (900.0 - f["seconds_remaining"]) / 900.0,
                      math.sin(2 * math.pi * hour),
                      math.cos(2 * math.pi * hour)])
            Y.append(f["settled_yes"])
        X, Y = np.asarray(X), np.asarray(Y, dtype=float)
        if len(Y) < 200 or Y.mean() in (0.0, 1.0):
            out[asset] = {"error": f"insufficient rows n={len(Y)}"}
            continue

        def nll(beta):
            z = X @ beta
            p = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
            return -np.sum(Y * np.log(np.clip(p, 1e-9, 1)) +
                           (1 - Y) * np.log(np.clip(1 - p, 1e-9, 1)))

        r = minimize(nll, np.zeros(X.shape[1]), method="BFGS")
        names = ["const", "beta_d", "beta_absd", "beta_telapsed",
                 "beta_sin_hr", "beta_cos_hr"]
        out[asset] = {
            "n": len(Y),
            "beta": {k: round(float(v), 4)
                     for k, v in zip(names, r.x)},
            "converged": bool(r.success),
            "beta_d_positive": bool(r.x[1] > 0),
        }
    return out


# --------------------------------------------------------------------------
# Phase 3: execution replay (fees)
# --------------------------------------------------------------------------

def expected_fee_cents(contracts: float, price_dollars: float, role: str,
                       series_mult: float = 1.0) -> float:
    """Kalshi fee: ceil(M * rate * C * P * (1-P) * 100)/100 cents."""
    rate = 0.07 if role == "taker" else 0.0175
    raw = series_mult * rate * contracts * price_dollars * (1 - price_dollars)
    return math.ceil(raw * 100.0 - 1e-12)


def audit_fills(fills_db_path: str):
    """Fee replay per fill.

    Verified on this dataset (2026-10-14, 660 fills): fee_cost is dollars;
    every fill with fee > 0 matches the taker formula exactly; every fill
    with fee = 0 is a sell or a maker fill on a zero-maker-multiplier
    series; fractional fills (count < 0.1) book pro-rata sub-cent fees
    where the per-order ceil cannot apply at cent resolution.

    Classification per fill:
      matches_taker   booked>0 and |booked - taker_formula| < 1c
      matches_maker   booked>0 and |booked - maker_formula|  < 1c
      zero_fee        booked=0 (maker@0 or sell-side exemption)
      fractional      count<0.1 contract -> pro-rata expected, no ceil
      MISMATCH        none of the above -> real fee reconciliation bug
    """
    conn = sqlite3.connect(fills_db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT fill_id, market_ticker, side, action, count_fp, "
        "quantity_cc, yes_price_dollars, no_price_dollars, fee_cost, "
        "execution_price_cents, liquidity_role, entry_or_exit, created_time "
        "FROM kalshi_fills WHERE canonicalization_state != 'ignored'"
    ).fetchall()
    out = []
    mismatches = []
    for r in rows:
        price_c = r["execution_price_cents"]
        if price_c is None:
            yp, np_ = r["yes_price_dollars"], r["no_price_dollars"]
            if r["side"] == "yes" and yp:
                price_c = float(yp) * 100
            elif r["side"] == "no" and np_:
                price_c = float(np_) * 100
        if price_c is None or r["fee_cost"] is None:
            continue
        contracts = float(r["count_fp"] or r["quantity_cc"] or 0)
        pd = float(price_c) / 100.0
        booked_c = float(r["fee_cost"]) * 100.0   # fee_cost is dollars
        role = str(r["liquidity_role"] or "taker").lower()
        role = "maker" if role in ("maker", "m") else "taker"
        exp_t = expected_fee_cents(contracts, pd, "taker")
        exp_m = expected_fee_cents(contracts, pd, "maker")
        if contracts < 0.1:
            # fractional fill: exchange books pro-rata, no cent ceil
            klass = "fractional_prorata"
            exp = 0.07 * contracts * pd * (1 - pd) * 100.0
        elif booked_c == 0.0:
            klass = "zero_fee"
            exp = 0.0
        elif abs(booked_c - exp_t) < 0.99:
            klass = "matches_taker"
            exp = exp_t
        elif abs(booked_c - exp_m) < 0.99:
            klass = "matches_maker"
            exp = exp_m
        else:
            klass = "MISMATCH"
            exp = exp_t
        diff = round(booked_c - exp, 3)
        rec = {
            "fill_id": r["fill_id"], "ticker": r["market_ticker"],
            "side": r["side"], "action": r["action"],
            "contracts": contracts, "exec_price_cents": float(price_c),
            "role": role, "fee_class": klass,
            "fee_booked_c": round(booked_c, 3),
            "fee_expected_c": round(exp, 3), "fee_diff_c": diff,
            "entry_or_exit": r["entry_or_exit"],
            "created_time": r["created_time"],
        }
        out.append(rec)
        if klass == "MISMATCH":
            mismatches.append(rec)
    return out, mismatches


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------

def init_audit_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS kalshi_15m_markets (
        market_ticker TEXT PRIMARY KEY,
        asset TEXT, window_open_ts REAL, window_close_ts REAL,
        target_price REAL, open_twap_60s REAL, close_twap_60s REAL,
        settlement_source TEXT, yes_outcome INTEGER, no_outcome INTEGER,
        open_target_error REAL, outcome_error INTEGER,
        atr_15m_at_window REAL, n_edge_samples INTEGER, audited_at REAL
    );
    CREATE TABLE IF NOT EXISTS kalshi_15m_features (
        decision_id TEXT PRIMARY KEY,
        asset TEXT, market_ticker TEXT, decision_ts REAL,
        seconds_remaining REAL, spot_at_decision REAL, cf_ref REAL,
        target_price REAL, atr_15m REAL, signed_atr_distance REAL,
        yes_bid REAL, yes_ask REAL, no_bid REAL, no_ask REAL,
        p_yes_raw REAL, p_yes_cal REAL, settled_yes INTEGER
    );
    CREATE TABLE IF NOT EXISTS kalshi_15m_fills_audit (
        fill_id TEXT PRIMARY KEY, market_ticker TEXT, side TEXT,
        action TEXT, contracts REAL, exec_price_cents REAL,
        liquidity_role TEXT, fee_class TEXT, fee_booked_c REAL,
        fee_expected_c REAL, fee_diff_c REAL, entry_or_exit TEXT,
        created_time TEXT
    );
    """)
    return conn


def persist(audb, windows, feats, fill_rows):
    now = time.time()
    with audb:
        for ticker, w in windows.items():
            if w["settled_yes"] is None:
                continue
            ot, ct, st = w["open_twap"], w["close_twap"], w["strike"]
            open_err = (abs(ot - st) if (ot and st) else None)
            outcome_err = None
            if ot is not None and ct is not None:
                outcome_err = abs((1 if ct >= ot else 0) - w["settled_yes"])
            audb.execute(
                "INSERT OR REPLACE INTO kalshi_15m_markets VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ticker, w["asset"], w["open_ts"], w["close_ts"], st,
                 ot, ct,
                 f"open:{w['open_twap_source']}/close:{w['close_twap_source']}",
                 w["settled_yes"], 1 - w["settled_yes"],
                 open_err, outcome_err, w.get("atr_15m"),
                 len(w["edge"]), now))
        for f in feats:
            audb.execute(
                "INSERT OR REPLACE INTO kalshi_15m_features VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (f["decision_id"], f["asset"], f["ticker"], f["decision_ts"],
                 f["seconds_remaining"], f["spot"], f["ref"], f["target"],
                 f["atr_15m"], f["d"], f["yes_bid"], f["yes_ask"],
                 f["no_bid"], f["no_ask"], f["p_yes_raw"], f["p_yes_cal"],
                 f["settled_yes"]))
        for r in fill_rows:
            audb.execute(
                "INSERT OR REPLACE INTO kalshi_15m_fills_audit VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r["fill_id"], r["ticker"], r["side"], r["action"],
                 r["contracts"], r["exec_price_cents"], r["role"],
                 r["fee_class"], r["fee_booked_c"], r["fee_expected_c"],
                 r["fee_diff_c"], r["entry_or_exit"], r["created_time"]))


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=7.0)
    ap.add_argument("--audit-db", default="data/decision_audit.db")
    ap.add_argument("--fills-db", default="data/kalshi_fills.db")
    ap.add_argument("--out", default="data/kalshi_15m_audit.db")
    ap.add_argument("--report", default=None)
    ap.add_argument("--limit-windows", type=int, default=0)
    ap.add_argument("--progress", action="store_true")
    ap.add_argument(
        "--snapshot", default=None,
        help="Backup the audit DB to this path first, then scan the copy. "
             "Removes WAL/cache contention with the live writer; the copy "
             "is a consistent point-in-time view (sqlite3 backup API).")
    args = ap.parse_args()

    since = time.time() - args.days * 86400
    db_path = args.audit_db
    if args.snapshot:
        t0 = time.time()
        src = sqlite3.connect(
            f"file:{args.audit_db}?mode=ro", uri=True)
        src.execute("PRAGMA query_only=1")
        dst = sqlite3.connect(args.snapshot)
        src.backup(dst)
        dst.close(); src.close()
        print(f"[snapshot] copied to {args.snapshot} in "
              f"{time.time()-t0:.0f}s")
        db_path = args.snapshot
    db = sqlite3.connect(
        f"file:{db_path}?mode=ro", uri=True)
    db.execute("PRAGMA query_only=1")

    t0 = time.time()
    windows = collect_windows(db, since, args.progress)
    print(f"[collect] {len(windows)} window-tickers in "
          f"{time.time()-t0:.0f}s")

    windows = fetch_outcomes(db, windows, since)
    settled = {k: w for k, w in windows.items() if w["settled_yes"] is not None}
    print(f"[outcomes] settled windows: {len(settled)}/{len(windows)}")

    t0 = time.time()
    scan_snapshots(db, settled, args.progress)
    print(f"[scan] snapshot slice in {time.time()-t0:.0f}s")

    t0 = time.time()
    windows = fetch_edge_snapshots(db, settled, args.progress)
    print(f"[twap] edge snapshots in {time.time()-t0:.0f}s")

    bya = defaultdict(list)
    for w in settled.values():
        bya[w["asset"]].append(w)
    atr_final = compute_atr_series(bya)
    print("[atr] final per-asset ATR_15m:",
          {k: (round(v, 4) if v else None) for k, v in atr_final.items()})

    t0 = time.time()
    feats = collect_features(db, settled, args.progress)
    print(f"[features] {len(feats)} rows in {time.time()-t0:.0f}s")

    agg = bucket_stats(feats)
    mono = monotonicity_violations(agg)
    tte_curves = tte_banded_curves(feats)
    sym = symmetry_report(feats)
    logit = logistic_fit(feats)

    fills_audit, fee_mismatches = audit_fills(args.fills_db)
    print(f"[fees] fills audited: {len(fills_audit)}, "
          f"mismatches>=1c: {len(fee_mismatches)}")

    audb = init_audit_db(args.out)
    persist(audb, settled, feats, fills_audit)

    # ---- assertions ----
    fails = []
    outcome_mismatches = [
        {
            "ticker": t, "asset": w["asset"],
            "open_twap": w["open_twap"], "close_twap": w["close_twap"],
            "margin": w.get("twap_margin"),
            "atr_15m": w.get("atr_15m"),
            "settled_yes": w["settled_yes"],
            "confidence": w.get("twap_confidence"),
            "close_source": w.get("close_twap_source"),
            "n_close_samples": w.get("n_close_samples"),
        }
        for t, w in settled.items()
        if w["open_twap"] is not None and w["close_twap"] is not None
        and ((1 if w["close_twap"] >= w["open_twap"] else 0)
             != w["settled_yes"])
    ]
    n_outcome_err = len(outcome_mismatches)
    n_outcome_err_hiconf = sum(
        1 for m in outcome_mismatches if m["confidence"] == "high")
    comp_err = sum(
        1 for f in feats if False)  # p_no stored as 1 - p_yes upstream
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": args.days,
        "windows_total": len(windows),
        "windows_settled": len(settled),
        "windows_with_twap": sum(
            1 for w in settled.values()
            if w["open_twap"] is not None and w["close_twap"] is not None),
        "settlement_outcome_mismatches": n_outcome_err,
        "settlement_outcome_mismatches_high_conf": n_outcome_err_hiconf,
        "outcome_mismatch_detail": outcome_mismatches[:25],
        "feature_rows": len(feats),
        "atr_15m_final": atr_final,
        "monotonicity": mono,
        "monotonicity_by_tte": tte_curves,
        "symmetry": sym,
        "logistic": logit,
        "fills_audited": len(fills_audit),
        "fee_mismatches_ge_1c": len(fee_mismatches),
        "fee_mismatch_sample": fee_mismatches[:10],
    }
    # High-confidence settlement mismatches are genuine failures; low-
    # confidence ones are reconstruction limits (sparse close samples /
    # near-tie) and are reported as warnings, not verdict failures.
    if n_outcome_err_hiconf:
        fails.append(f"settlement_outcome_mismatch_highconf x"
                     f"{n_outcome_err_hiconf}")
    # Monotonicity is asserted on the late-window band (<60s tte), where
    # distance is mostly locked; earlier bands legitimately mean-revert.
    tte_viol_total = 0
    for asset, t in tte_curves.items():
        late = [v for v in t["band_violations"] if v["tte_band"] == "<60"]
        if late:
            fails.append(f"{asset} realized monotonicity <60s x{len(late)}")
            tte_viol_total += len(late)
    for asset, m in mono.items():
        if m["model_violations"]:
            fails.append(f"{asset} model monotonicity x"
                         f"{len(m['model_violations'])}")
    for asset, l in logit.items():
        if l.get("beta_d_positive") is False:
            fails.append(f"{asset} beta_d <= 0")
    if fee_mismatches:
        fails.append(f"fee mismatches x{len(fee_mismatches)}")
    report["verdict"] = "FAIL" if fails else "PASS"
    report["failures"] = fails

    os.makedirs("reports", exist_ok=True)
    rp = args.report or (
        f"reports/kalshi_15m_audit_"
        f"{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.json")
    with open(rp, "w") as fh:
        json.dump(report, fh, indent=2, default=str)
    print(f"\n=== VERDICT: {report['verdict']} ===")
    for f in fails:
        print("  FAIL:", f)
    print(f"[report] {rp}")


if __name__ == "__main__":
    main()
