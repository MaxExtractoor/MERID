"""Late-window trend-favorite alignment audit — offline/shadow, read-only.

Answers, for the proposed ``late_window_trend_favorite`` lane (purchased-side
price >85c, evaluated at <=150s to expiry, underlying position + trend
supporting the purchased side):

  1. Does the current system let this exact cohort reach execution at all,
     and when it declines, which exact gate rejects it?
  2. What does the strike-distance / reversal-risk picture look like for the
     cohort (signed cushion, normalized z vs remaining-vol estimate, cushion
     trend, recent target crossings)?
  3. What were the settled outcomes — realized for the few admitted, and
     counterfactual (hold-to-settlement at decision-time quotes) for the
     rejected, under ONE predefined entry rule per market-side?

Data sources (all read-only):
  - data/decision_audit.db: strategy_decisions + _snapshots + _side_ev +
    _outcomes + _events.  The snapshots carry the settlement-reference
    price, strike distance, vol forecast and executable quotes at decision
    time; side_ev carries per-side calibrated probabilities and executable
    prices; outcomes carry settled_yes + counterfactual PnL.
  - logs/settlement_outcomes.jsonl: authoritative ticker -> outcome fallback.
  - logs/late_window_shadow.jsonl: TTE-floor shadow records (30-90s band).

Fee model: merid.event_venues.kalshi.parabolic_fees.kalshi_fee_cents_exact
(taker 0.07 / maker 0.0175 rate*C*P*(1-P), ceil to 0.01c) — same helper the
live gates use.

Usage:
  .\\.venv\\Scripts\\python.exe scripts\\late_window_favorite_audit.py --extract
  .\\.venv\\Scripts\\python.exe scripts\\late_window_favorite_audit.py
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import os
import sqlite3
import sys
import time
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DB = os.path.join(ROOT, "data", "decision_audit.db")
EXTRACT = os.path.join(ROOT, "data", "_lwf_extract.jsonl")
SETTLE_LOG = os.path.join(ROOT, "logs", "settlement_outcomes.jsonl")

ASSETS = ("BTC", "ETH", "SOL", "XRP", "DOGE")
SIDES = ("yes", "no")
SECS_PER_YEAR = 365.25 * 86400.0

PRICE_LO_C = 85.0           # "strictly above 85c" -> >=86 whole-cent
TTE_HI_S = 150.0            # lane activation
TTE_SCAN_HI_S = 200.0       # scan a bit wider for context bands
PRICE_BANDS = ((86, 89), (90, 91), (92, 95), (96, 99))
TTE_BANDS = ((121, 150), (61, 120), (0, 60))
Z_BANDS = ((0, 0.5), (0.5, 1.0), (1.0, 2.0), (2.0, 4.0), (4.0, 1e9))


def _fee_exact_cents(price_dollars: float, contracts: float, role: str) -> float:
    try:
        from merid.event_venues.kalshi.parabolic_fees import (
            kalshi_fee_cents_exact,
        )
        return float(kalshi_fee_cents_exact(price_dollars, contracts, role))
    except Exception:
        rate = 0.0175 if role == "maker" else 0.07
        return max(0.0, math.ceil(rate * contracts * price_dollars
                                  * (1 - price_dollars) * 100 * 1e4) / 1e4)


def _ro(path: str) -> sqlite3.Connection:
    p = os.path.abspath(path).replace("\\", "/")
    if not p.startswith("/"):
        p = "/" + p
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    c.execute("PRAGMA busy_timeout=60000")
    return c


def _chunks(seq, n=400):
    buf = []
    for x in seq:
        buf.append(x)
        if len(buf) >= n:
            yield buf
            buf = []
    if buf:
        yield buf


# --------------------------------------------------------------------------
# Extract: one pass over strategy_decisions + indexed joins -> compact JSONL
# --------------------------------------------------------------------------

def extract(snap_path: Optional[str] = None, days: Optional[float] = None) -> None:
    # Crash-consistent copy of the live WAL DB first — a direct scan of the
    # 8GB table starves against the live writer (same trick as
    # window_funnel_report._snapshot).  Pass --snap to reuse an existing copy.
    if snap_path and os.path.exists(snap_path):
        snap = snap_path
        owns_snap = False
    else:
        from scripts.window_funnel_report import _snapshot  # noqa
        snap = _snapshot(DB)
        owns_snap = True
    conn = _ro(snap)
    t0 = time.time()
    lo_ts = None
    if days:
        hi = conn.execute(
            "SELECT MAX(decision_ts) FROM strategy_decisions").fetchone()[0]
        if hi:
            lo_ts = hi - days * 86400.0
    q = (
        "SELECT decision_id, candidate_id, decision_ts, ticker, asset, "
        "strike, close_ts, seconds_to_close, selected_side, decision, "
        "primary_reason_code, reason_codes, strategy_version, admission_lane, "
        "exclusion_reason, dir_regime, run_id, gate_results_json "
        "FROM strategy_decisions "
        "WHERE seconds_to_close IS NOT NULL AND seconds_to_close > 0 "
        "AND seconds_to_close <= ?"
    )
    params: list = [TTE_SCAN_HI_S]
    if lo_ts is not None:
        q += " AND decision_ts > ?"
        params.append(lo_ts)
    rows: List[Dict[str, Any]] = []
    dids: List[str] = []
    n = 0
    for r in conn.execute(q, params):
        n += 1
        (did, cid, ts, tick, asset, strike, close_ts, tte, sel, dec,
         prc, rcs, sver, lane, excl, dreg, run, gj) = r
        raw_reason = None
        first_failed = None
        if gj:
            try:
                g = json.loads(gj)
                for name, gv in g.items():
                    if isinstance(gv, dict) and gv.get("passed") is False:
                        first_failed = name
                        if name == "pre_decision_pipeline":
                            raw_reason = (gv.get("observed") or {}).get("raw_reason")
                        break
            except Exception:
                pass
        rows.append({
            "did": did, "cid": cid, "ts": ts, "ticker": tick, "asset": asset,
            "strike": strike, "close_ts": close_ts, "tte": tte,
            "sel": sel, "decision": dec, "reason": prc,
            "reasons": rcs, "sver": sver, "lane": lane, "excl": excl,
            "dir_regime": dreg, "run": run,
            "raw_reason": raw_reason, "first_failed": first_failed,
        })
        dids.append(did)
    print(f"[extract] {n} decision rows TTE<= {TTE_SCAN_HI_S:.0f}s "
          f"in {time.time()-t0:.0f}s", file=sys.stderr)

    idx = {r["did"]: r for r in rows}

    # --- snapshots ---
    t0 = time.time()
    for ch in _chunks(dids):
        ph = ",".join("?" * len(ch))
        for (did, spot, ref, ref_src, ref_age, yb, ya, nb, na, bexec,
             rawp, calp, vol, volsrc, zs, dist, vel, book_age, qowner) in conn.execute(
            "SELECT decision_id, spot_price, settlement_reference_price, "
            "settlement_reference_source, settlement_reference_age_ms, "
            "yes_bid_cents, yes_ask_cents, no_bid_cents, no_ask_cents, "
            "book_is_executable, raw_p_yes, calibrated_p_yes, vol_forecast, "
            "vol_source, zscore, distance_to_strike, velocity, book_age_ms, "
            "quote_owner "
            f"FROM strategy_decision_snapshots WHERE decision_id IN ({ph})", ch):
            r = idx.get(did)
            if r is None:
                continue
            r.update({
                "spot": spot, "ref": ref, "ref_src": ref_src,
                "ref_age_ms": ref_age, "yb": yb, "ya": ya, "nb": nb, "na": na,
                "bexec": bexec, "raw_p": rawp, "cal_p": calp,
                "vol": vol, "vol_src": volsrc, "zs": zs, "dist": dist,
                "vel": vel, "book_age_ms": book_age, "qowner": qowner,
            })
    print(f"[extract] snapshots joined in {time.time()-t0:.0f}s", file=sys.stderr)

    # --- side_ev ---
    t0 = time.time()
    for ch in _chunks(dids):
        ph = ",".join("?" * len(ch))
        for (did, side, px, calp, gev, neve, peg, dlane, cfstat) in conn.execute(
            "SELECT decision_id, side, executable_entry_price_cents, "
            "calibrated_probability, gross_edge_cents, expected_net_ev_cents, "
            "passed_edge_gate, decision_lane, counterfactual_execution_status "
            f"FROM strategy_decision_side_ev WHERE decision_id IN ({ph})", ch):
            r = idx.get(did)
            if r is None:
                continue
            r.setdefault("sev", {})[side] = {
                "px": px, "cal_p": calp, "gev": gev, "nev": neve,
                "peg": peg, "lane": dlane, "cfstat": cfstat,
            }
    print(f"[extract] side_ev joined in {time.time()-t0:.0f}s", file=sys.stderr)

    # --- outcomes ---
    t0 = time.time()
    n_out = 0
    for ch in _chunks(dids):
        ph = ",".join("?" * len(ch))
        for (did, sy, cfy, cfn, rpnl, st, afp) in conn.execute(
            "SELECT decision_id, settled_yes, counterfactual_yes_pnl_cents, "
            "counterfactual_no_pnl_cents, realized_net_pnl_cents, "
            "outcome_status, actual_fill_price_cents "
            f"FROM strategy_decision_outcomes WHERE decision_id IN ({ph})", ch):
            r = idx.get(did)
            if r is None:
                continue
            n_out += 1
            r.update({"settled_yes": sy, "cf_yes": cfy, "cf_no": cfn,
                      "rpnl": rpnl, "ostatus": st, "fill_px": afp})
    print(f"[extract] outcomes joined ({n_out}) in {time.time()-t0:.0f}s",
          file=sys.stderr)

    # --- events for emitted rows ---
    t0 = time.time()
    emit_dids = [r["did"] for r in rows if r["decision"] == "ENTER"]
    for ch in _chunks(emit_dids):
        ph = ",".join("?" * len(ch))
        for did, et, rcode in conn.execute(
            "SELECT decision_id, event_type, reason_code "
            f"FROM strategy_decision_events WHERE decision_id IN ({ph})", ch):
            r = idx.get(did)
            if r is None:
                continue
            r.setdefault("events", []).append([et, rcode])
    print(f"[extract] events joined ({len(emit_dids)} emitted) in "
          f"{time.time()-t0:.0f}s", file=sys.stderr)
    conn.close()
    if owns_snap:
        for sfx in ("", "-wal", "-shm"):
            try:
                os.unlink(snap + sfx)
            except OSError:
                pass

    with open(EXTRACT, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, default=str) + "\n")
    print(f"[extract] wrote {len(rows)} rows -> {EXTRACT}", file=sys.stderr)


# --------------------------------------------------------------------------
# Settlement truth fallback (ticker -> resolved_yes)
# --------------------------------------------------------------------------

def load_settlements() -> Dict[str, int]:
    out = {}
    if not os.path.exists(SETTLE_LOG):
        return out
    with open(SETTLE_LOG, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            tick = r.get("ticker")
            if not tick:
                continue
            if r.get("resolved_yes") is not None:
                out[tick] = int(r["resolved_yes"])
            elif (r.get("outcome") or "") in ("yes", "no"):
                out[tick] = 1 if r["outcome"] == "yes" else 0
    return out


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------

def px_band(px):
    if px is None:
        return None
    for lo, hi in PRICE_BANDS:
        if lo <= px <= hi:
            return f"{lo}-{hi}c"
    if px < 86:
        return "<86c"
    return ">99c"


def tte_band(t):
    if t is None:
        return "?"
    if t > 150:
        return "150-200s"
    if t > 120:
        return "121-150s"
    if t > 60:
        return "61-120s"
    return "<=60s"


def z_band(z):
    if z is None:
        return "no_z"
    if z < 0:
        return "wrong_side"
    for lo, hi in Z_BANDS:
        if lo <= z < hi:
            return f"z{lo}-{hi if hi < 1e8 else 'inf'}"
    return "z4+"


def trend_label(d_side_now, d_side_prev):
    """Cushion trajectory vs the nearest earlier eval."""
    if d_side_now is None or d_side_prev is None:
        return "no_prior"
    dd = d_side_now - d_side_prev
    if dd > 0:
        return "expanding"
    if dd < 0:
        return "shrinking"
    return "flat"


def analyze() -> int:
    recs = []
    with open(EXTRACT, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                recs.append(json.loads(line))
            except Exception:
                pass
    settle = load_settlements()
    print(f"[analyze] {len(recs)} decision rows; {len(settle)} settled tickers",
          file=sys.stderr)

    # group by ticker for cushion trajectory (chronological)
    by_tick: Dict[str, List[dict]] = collections.defaultdict(list)
    for r in recs:
        by_tick[r.get("ticker") or "?"].append(r)
    for v in by_tick.values():
        v.sort(key=lambda r: r.get("ts") or 0)

    # ------------------------------------------------------------------
    # Per-eval "cohort" record: for each side, did the *market* present a
    # late-window favorite candidate (own-side price > 85c)?
    # ------------------------------------------------------------------
    cohort = []           # one entry per (eval, side) with price condition met
    funnel = collections.Counter()
    reject_reasons = collections.Counter()
    first_fail_ctr = collections.Counter()
    lane_ctr = collections.Counter()
    emit_events = collections.Counter()

    for r in recs:
        tte = r.get("tte")
        if tte is None or tte > TTE_HI_S:
            # context only — count the 150-200s band separately
            funnel["ctx_150_200_evals"] += 1
            continue
        funnel["evals_tte<=150"] += 1
        ya, yb, na, nb = r.get("ya"), r.get("yb"), r.get("na"), r.get("nb")
        ref, K = r.get("ref"), r.get("strike")
        vol = r.get("vol")
        bexec = r.get("bexec")

        sides_px = {}
        if ya is not None:
            sides_px["yes"] = {"ask": ya, "bid": yb}
        if na is not None:
            sides_px["no"] = {"ask": na, "bid": nb}
        # executable-price condition: own-side ASK > 85 (taker basis);
        # record bid>85 too for the maker interpretation.
        for side, q in sides_px.items():
            ask, bid = q["ask"], q["bid"]
            if ask is None or ask <= PRICE_LO_C:
                continue
            funnel[f"px>85_{side}"] += 1
            s_dir = 1.0 if side == "yes" else -1.0
            d_side = None
            z = None
            sig_rem = None
            if ref is not None and K:
                d_side = s_dir * (float(ref) - float(K))
                d_bps = 1e4 * d_side / float(K)
                if vol:
                    sig_rem = float(ref) * float(vol) * math.sqrt(
                        float(tte) / SECS_PER_YEAR)
                    if sig_rem and sig_rem > 0:
                        z = d_side / sig_rem
            else:
                d_bps = None
            cohort.append({
                "r": r, "side": side, "ask": ask, "bid": bid,
                "d_side": d_side, "d_bps": d_bps, "z": z,
                "sig_rem": sig_rem, "bexec": bexec,
            })

    print(f"[analyze] cohort eval-sides (TTE<=150, own-side ask>85c): "
          f"{len(cohort)}", file=sys.stderr)

    # ------------------------------------------------------------------
    # Per-eval cushion trend: same ticker, nearest earlier eval >= 8s older
    # ------------------------------------------------------------------
    pos_hist: Dict[str, List] = collections.defaultdict(list)
    for r in recs:
        ref, K = r.get("ref"), r.get("strike")
        if ref is None or not K:
            continue
        pos_hist[r.get("ticker") or "?"].append(
            (r.get("ts") or 0, float(ref) - float(K), r.get("tte")))
    for v in pos_hist.values():
        v.sort()

    for c in cohort:
        r = c["r"]
        tick = r.get("ticker") or "?"
        ts = r.get("ts") or 0
        hist = pos_hist.get(tick) or []
        prev = None
        crosses = 0
        last_sign = 0
        for (pts, pd, _ptte) in hist:
            if pts >= ts:
                break
            sg = 1 if pd > 0 else (-1 if pd < 0 else 0)
            if last_sign and sg and sg != last_sign:
                crosses += 1
            if sg:
                last_sign = sg
            if ts - pts >= 8.0:
                prev = pd
        s_dir = 1.0 if c["side"] == "yes" else -1.0
        d_prev = s_dir * prev if prev is not None else None
        c["d_prev"] = d_prev
        c["crosses"] = crosses
        c["trend"] = trend_label(c["d_side"], d_prev)

    # ------------------------------------------------------------------
    # Aggregate the funnel for the cohort
    # ------------------------------------------------------------------
    # stage counters per (asset, side)
    st = collections.Counter()
    band_px = collections.Counter()
    band_tte = collections.Counter()
    zc = collections.Counter()
    tr = collections.Counter()
    gate = collections.Counter()
    econ_rows = []

    for c in cohort:
        r = c["r"]
        a, s = r.get("asset") or "?", c["side"]
        st[("eval", a, s)] += 1
        band_px[px_band(c["ask"])] += 1
        band_tte[tte_band(r.get("tte"))] += 1
        if c["bexec"]:
            st[("executable_book", a, s)] += 1
        if c["d_side"] is not None:
            st[("ref_available", a, s)] += 1
            if c["d_side"] > 0:
                st[("correct_side_of_target", a, s)] += 1
        zc[z_band(c["z"])] += 1
        tr[c["trend"]] += 1

        # system disposition for this eval
        dec = r.get("decision")
        sver = r.get("sver")
        reason = r.get("reason")
        raw = r.get("raw_reason")
        lane = r.get("lane")
        if dec == "ENTER":
            st[("emitted", a, s)] += 1
            lane_ctr[lane or "?"] += 1
            for et, rc in (r.get("events") or []):
                emit_events[et] += 1
                if et == "ORDER_FILLED":
                    st[("filled", a, s)] += 1
            if r.get("settled_yes") is not None:
                st[("settled", a, s)] += 1
        else:
            gkey = raw or r.get("first_failed") or reason or "?"
            gate[gkey] += 1
            # did this eval even evaluate our side? (side_ev row exists?)
            sev = (r.get("sev") or {}).get(s)
            if sev:
                st[("side_evaluated", a, s)] += 1

        # economics at decision-time quotes (taker basis, 1 contract)
        sev = (r.get("sev") or {}).get(s)
        p_cal = None
        if sev and sev.get("cal_p") is not None:
            p_cal = float(sev["cal_p"])
        elif r.get("cal_p") is not None:
            p_cal = float(r["cal_p"]) if s == "yes" else 1.0 - float(r["cal_p"])
        fee = _fee_exact_cents(c["ask"] / 100.0, 1.0, "taker")
        mk_fee = _fee_exact_cents((c["bid"] or c["ask"]) / 100.0, 1.0, "maker")
        econ_rows.append({
            "asset": a, "side": s, "tte": r.get("tte"),
            "ask": c["ask"], "bid": c["bid"], "p_cal": p_cal,
            "z": c["z"], "d_bps": c["d_bps"], "trend": c["trend"],
            "crosses": c["crosses"], "decision": dec, "lane": lane,
            "settled_yes": r.get("settled_yes"),
            "ticker": r.get("ticker"), "ts": r.get("ts"),
            "taker_fee": fee, "maker_fee": mk_fee,
            "sev_nev": (sev or {}).get("nev"),
        })

    # ------------------------------------------------------------------
    # One-entry-rule-per-market counterfactual: first eval per (ticker, side)
    # meeting the full lane condition: TTE<=150, ask>85, correct side of
    # target, cushion expanding-or-stable (trend != shrinking), |crosses|<=1
    # ------------------------------------------------------------------
    entry_rule = collections.defaultdict(list)
    for e in econ_rows:
        if e["d_bps"] is None or e["z"] is None:
            continue
        if e["d_bps"] <= 0:
            continue  # wrong side of target
        entry_rule[(e["ticker"], e["side"])].append(e)
    cf = collections.defaultdict(lambda: [0, 0, 0.0, 0.0])  # n, wins, pnl_t, pnl_m
    cf_detail = collections.defaultdict(lambda: [0, 0, 0.0])
    chosen = 0
    for (tick, side), rows_ in entry_rule.items():
        rows_.sort(key=lambda e: e["ts"] or 0)
        # first qualifying eval with trend not collapsing
        pick = None
        for e in rows_:
            if e["trend"] == "shrinking":
                continue
            pick = e
            break
        if pick is None:
            pick = rows_[0]
        sy = pick["settled_yes"]
        if sy is None:
            sy = settle.get(tick)
        if sy is None:
            continue
        won = (int(sy) == 1) == (side == "yes")
        chosen += 1
        # hold-to-settlement PnL at ask (taker) and at bid (maker)
        pnl_t = (100.0 - pick["ask"] - pick["taker_fee"]) if won else (
            -pick["ask"] - pick["taker_fee"])
        mpx = pick["bid"] if pick["bid"] is not None else pick["ask"]
        pnl_m = (100.0 - mpx - pick["maker_fee"]) if won else (
            -mpx - pick["maker_fee"])
        key = (pick["asset"], side)
        v = cf[key]; v[0] += 1; v[1] += won; v[2] += pnl_t; v[3] += pnl_m
        for kb, vv in (
            (("ALL", "all"), cf_detail[("ALL", "all")]),
            ((px_band(pick["ask"]), "px"), cf_detail[(px_band(pick["ask"]), "px")]),
            ((tte_band(pick["tte"]), "tte"), cf_detail[(tte_band(pick["tte"]), "tte")]),
            ((z_band(pick["z"]), "z"), cf_detail[(z_band(pick["z"]), "z")]),
            ((pick["trend"], "trend"), cf_detail[(pick["trend"], "trend")]),
        ):
            vv[0] += 1; vv[1] += won; vv[2] += pnl_t

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------
    P = print
    P("\n" + "=" * 78)
    P("LATE-WINDOW TREND-FAVORITE ALIGNMENT REPORT")
    P("lane: late_window_trend_favorite | own-side ASK >85c | TTE<=150s | "
      "trend+position must support purchased side")
    P("=" * 78)

    P("\n--- FUNNEL (decision-eval rows) ---")
    P(f"  eval rows TTE<=150s:              {funnel['evals_tte<=150']:>8,}")
    P(f"  (context) eval rows 150-200s:     {funnel['ctx_150_200_evals']:>8,}")
    P(f"  eval-sides with own-side ask>85c: {len(cohort):>8,}")
    for s in SIDES:
        P(f"    {s}: {funnel[f'px>85_{s}']:>8,}")

    P("\n--- COHORT BY PRICE BAND (own-side ask) ---")
    for b in ("<86c", "86-89c", "90-91c", "92-95c", "96-99c", ">99c"):
        if band_px.get(b):
            P(f"  {b:8s} {band_px[b]:>8,}")
    P("--- COHORT BY TTE BAND ---")
    for b in ("121-150s", "61-120s", "<=60s"):
        P(f"  {b:8s} {band_tte.get(b,0):>8,}")

    P("\n--- COHORT BY ASSET x SIDE ---")
    P(f"  {'asset-side':10s} {'evals':>7s} {'exec_book':>9s} {'ref_ok':>7s} "
      f"{'right_side':>10s} {'side_ev':>7s} {'emit':>5s} {'fill':>5s} {'setl':>5s}")
    for a in ASSETS:
        for s in SIDES:
            n = st[("eval", a, s)]
            if not n:
                continue
            P(f"  {a+'-'+s:10s} {n:>7d} {st[('executable_book',a,s)]:>9d} "
              f"{st[('ref_available',a,s)]:>7d} "
              f"{st[('correct_side_of_target',a,s)]:>10d} "
              f"{st[('side_evaluated',a,s)]:>7d} {st[('emitted',a,s)]:>5d} "
              f"{st[('filled',a,s)]:>5d} {st[('settled',a,s)]:>5d}")

    P("\n--- WHICH GATE REJECTED THE COHORT (eval-sides, non-ENTER) ---")
    for g, n in gate.most_common(20):
        P(f"  {n:>8,}  {g}")
    P("\n--- EMITTED lane mix + downstream events ---")
    for l, n in lane_ctr.most_common():
        P(f"  {n:>6,}  emitted lane={l}")
    for e, n in emit_events.most_common():
        P(f"  {n:>6,}  event={e}")

    P("\n--- CUSHION: normalized z = signed_dist/(ref*vol*sqrt(tte/yr)) ---")
    for b in ("wrong_side", "z0-0.5", "z0.5-1.0", "z1.0-2.0",
              "z2.0-4.0", "z4.0-inf", "z4+", "no_z"):
        if zc.get(b):
            P(f"  {b:12s} {zc[b]:>8,}")
    P("--- CUSHION TREND (vs nearest eval >=8s earlier, same ticker) ---")
    for t_, n in tr.most_common():
        P(f"  {t_:12s} {n:>8,}")

    P("\n--- COUNTERFACTUAL: one entry per (ticker,side), first eval meeting")
    P("    TTE<=150 + ask>85 + ref on purchased side + cushion not shrinking ---")
    P("    (hold-to-settlement; taker=own-side ask, maker=own-side bid;")
    P("     exact parabolic fee; n=%d market-sides)" % chosen)
    P(f"  {'asset-side':10s} {'n':>5s} {'win%':>6s} {'pnl_taker':>10s} "
      f"{'pnl_maker':>10s} {'taker/tr':>8s}")
    tot = [0, 0, 0.0, 0.0]
    for (a, s), (n, w, pt, pm) in sorted(cf.items()):
        if not n:
            continue
        P(f"  {a+'-'+s:10s} {n:>5d} {w/n*100:>5.1f}% {pt:>+10.1f} "
          f"{pm:>+10.1f} {pt/n:>+8.2f}c")
        for i in range(4):
            tot[i] += (n, w, pt, pm)[i]
    if tot[0]:
        P(f"  {'TOTAL':10s} {tot[0]:>5d} {tot[1]/tot[0]*100:>5.1f}% "
          f"{tot[2]:>+10.1f} {tot[3]:>+10.1f} {tot[2]/tot[0]:>+8.2f}c")

    P("\n--- COUNTERFACTUAL SPLITS (taker basis) ---")
    groups = collections.defaultdict(list)
    for (k, kind), v in cf_detail.items():
        if kind != "all":
            groups[kind].append((k, v))
    for kind in ("px", "tte", "z", "trend"):
        P(f"  by {kind}:")
        for k, (n, w, p) in sorted(groups[kind]):
            P(f"    {k:12s} n={n:>4d} win={w/n*100:>5.1f}% pnl={p:>+9.1f} "
              f"({p/n:>+6.2f}/tr)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--extract", action="store_true",
                    help="rebuild the extract from decision_audit.db")
    ap.add_argument("--snap", help="reuse an existing snapshot DB copy")
    ap.add_argument("--days", type=float,
                    help="bound the scan to the last N days of decision_ts")
    args = ap.parse_args()
    if args.extract or not os.path.exists(EXTRACT):
        extract(snap_path=args.snap, days=args.days)
    return analyze()


if __name__ == "__main__":
    sys.exit(main())
