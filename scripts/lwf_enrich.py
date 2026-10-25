"""lwf_shadow offline enrichment — recover contemporaneously-available inputs
for pre-engine-rejected candidates WITHOUT changing production or the log.

For each lwf_shadow record:
  strike  <- unique strike for the ticker in strategy_decisions (contract-
             immutable; populated at market open, so any same-ticker decision
             row is contemporaneously valid).
  vol     <- latest vol_forecast from a same-ticker snapshot with
             decision_ts <= record event_ts (strictly prior only).
  ref     <- already in the record (cfb_rti_live at eval time).
  trend   <- recomputed from the pre-eval settlement_reference_price series
             of same-ticker snapshots (30s lookback +/-15s, flat band
             0.10*sigma_price, crossings over 60s) — same frozen spec.

What is NOT enriched: the engine forecast.  probability_status stays
INPUTS_MISSING when production never ran the model; w7/w8 stay
not_evaluable.  q_phi_enriched is a clearly-labelled endpoint diagnostic.

Outputs logs/lwf_shadow_enriched.jsonl (derived file; original untouched)
and prints the separated counts:
  above_85_price_candidates / research_86_89_price_candidates /
  complete_input_candidates / position_and_trend_qualified /
  valid_forecast_candidates / shadow_economic_admissions /
  production_divergences
"""
import json, math, os, sqlite3, sys, collections
from datetime import datetime

ROOT = r"C:\Dev\MERID"
LOG = os.environ.get("MERID_LWF_SHADOW_LOG", os.path.join(ROOT, "logs", "lwf_shadow.jsonl"))
OUT = os.path.join(ROOT, "logs", "lwf_shadow_enriched.jsonl")
DB = os.path.join(ROOT, "data", "decision_audit.db")
SECS_PER_YEAR = 365.0 * 86400.0
TREND_LOOKBACK_S, TREND_TOL_S, TREND_FLAT_FRAC, CROSS_LOOKBACK_S = 30.0, 15.0, 0.10, 60.0

def _phi(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def _ts(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()

recs = []
for line in open(LOG, encoding="utf-8", errors="replace"):
    try:
        r = json.loads(line)
    except Exception:
        continue
    if r.get("type") == "lwf_shadow":
        recs.append(r)
if not recs:
    print("no lwf_shadow records"); sys.exit(0)

con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
tickers = sorted({r["ticker"] for r in recs if r.get("ticker")})
strikes, ref_series, vol_series = {}, {}, {}
for t in tickers:
    row = con.execute(
        "SELECT strike FROM strategy_decisions WHERE ticker=? AND strike IS NOT NULL LIMIT 1",
        (t,)).fetchone()
    if row:
        strikes[t] = float(row["strike"])
    # reference series for the 30s lookback: settlement_reference_price where
    # resolved, else contemporaneous spot_price (flagged; ~0.03% typical gap).
    rows = con.execute(
        """SELECT d.decision_ts_iso ts, s.settlement_reference_price ref,
                  s.spot_price spot, s.vol_forecast vol
           FROM strategy_decisions d JOIN strategy_decision_snapshots s
             ON s.decision_id = d.decision_id
           WHERE d.ticker=? AND (s.settlement_reference_price IS NOT NULL
                                 OR s.spot_price IS NOT NULL)
           ORDER BY d.decision_ts""", (t,)).fetchall()
    ref_series[t] = [
        (_ts(r["ts"]), float(r["ref"]) if r["ref"] is not None else float(r["spot"]),
         "settlement_ref" if r["ref"] is not None else "spot")
        for r in rows]
    vol_series[t] = [(_ts(r["ts"]), float(r["vol"])) for r in rows if r["vol"] is not None]
con.close()

def prior_val(series, ts, max_age=None):
    best = None
    for t, v in series:
        if t <= ts and (best is None or t > best[0]):
            best = (t, v)
    if best is None or (max_age and ts - best[0] > max_age):
        return None
    return best

def dist_at(series, ts, target_age, tol):
    """Nearest observation to ts-target_age within +/-tol.  Series entries are
    (ts, price, source); prefers settlement_ref on ties."""
    best, best_err = None, tol
    for t, px, src in series:
        err = abs(ts - t - target_age)
        if err < best_err or (
            err == best_err and best is not None and src == "settlement_ref"
            and best[1] != "settlement_ref"):
            best_err, best = err, (px, src)
    return best

def crossings(series, ts, lookback, K):
    prev = None; n = 0
    for t, px, _src in series:
        if ts - lookback <= t <= ts:
            s = 1 if px > K else (-1 if px < K else 0)
            if prev is not None and s != 0 and prev != 0 and s != prev:
                n += 1
            if s != 0:
                prev = s
    return n

out = []
stats = collections.Counter()
for r in recs:
    e = dict(r)
    ts = _ts(r["event_ts_utc"]); t = r["ticker"]; side = r["side"]
    s_dir = 1.0 if side == "yes" else -1.0
    en = {"enrichment_ts_utc": datetime.now().isoformat() + "Z", "inputs": {}, "status": "not_needed"}
    K = r.get("strike")
    if K is None and t in strikes:
        K = strikes[t]
        en["inputs"]["strike"] = {"value": K, "source": "decision_metadata_same_ticker"}
        stats["strike_enriched"] += 1
    vol, vol_prov = r.get("annualized_vol"), None
    if vol is None:
        pv = prior_val(vol_series.get(t, []), ts, max_age=600.0)
        if pv is not None:
            vol, vol_prov = pv[1], {"value": pv[1], "source": f"vol_forecast_prior@{pv[0]:.3f}", "age_s": round(ts - pv[0], 1)}
            en["inputs"]["annualized_vol"] = vol_prov
            stats["vol_enriched"] += 1
    ref = r.get("ref_price")
    complete = (ref is not None and K is not None and vol is not None)
    if not complete:
        en["status"] = "unresolved"
        stats["unresolved"] += 1
    else:
        en["status"] = "enriched"
        stats["enriched"] += 1
    if complete:
        sig_price = ref * vol * math.sqrt(r["tte_seconds"] / SECS_PER_YEAR)
        d_side = s_dir * (ref - K)
        dp = dist_at(ref_series.get(t, []), ts, TREND_LOOKBACK_S, TREND_TOL_S)
        d_prev_side = (s_dir * (dp[0] - K)) if dp is not None else None
        tol = TREND_FLAT_FRAC * sig_price
        if d_prev_side is None:
            trend = "no_prior"
        else:
            chg = d_side - d_prev_side
            trend = "expanding" if chg > tol else ("shrinking" if chg < -tol else "flat")
        n_cross = crossings(ref_series.get(t, []), ts, CROSS_LOOKBACK_S, K)
        lm = math.log(ref / K) if K > 0 else 0.0
        sig_frac = vol * math.sqrt(r["tte_seconds"] / SECS_PER_YEAR)
        q_phi = _phi(s_dir * (lm / sig_frac)) if sig_frac > 0 else None
        z_cush = d_side / sig_price if sig_price > 0 else None
        en.update({"strike": K, "annualized_vol": vol,
                   "signed_distance_price": d_side, "sigma_rem_price": sig_price,
                   "z_cushion": z_cush, "trend_enriched": trend,
                   "trend_prior_source": dp[1] if dp else None,
                   "crossings_60s_enriched": n_cross,
                   "q_phi_enriched_diagnostic": q_phi})
        e["strike"] = K; e["annualized_vol"] = vol
        # re-grade the input-dependent stages with enriched inputs
        st = dict(e.get("stages") or {})
        st["w1_inputs_trusted"] = "pass" if vol_prov or r.get("annualized_vol") else st.get("w1_inputs_trusted", "fail")
        st["w3_correct_side"] = "pass" if d_side > 0 else "fail"
        st["w4_trend_non_shrinking"] = ("pass" if trend in ("expanding", "flat")
                                        else "fail" if trend == "shrinking"
                                        else "not_evaluable")
        e["stages_enriched"] = st
        e["position_and_trend_qualified"] = (st["w3_correct_side"] == "pass"
                                           and st["w4_trend_non_shrinking"] == "pass")
    e["enrichment"] = en
    out.append(e)

with open(OUT, "w", encoding="utf-8") as f:
    for e in out:
        f.write(json.dumps(e, default=str) + "\n")

ev = [_ts(r["event_ts_utc"]) for r in recs]
print(f"records: {len(recs)}  window: {min(ev):.0f}-{max(ev):.0f} epoch "
      f"(span {max(ev)-min(ev):.1f}s of the 120<tte<=150 entry interval)")
print("enrichment:", dict(stats))
print()
ask = lambda r: float(r["ask_cents"])
n = len(recs)
above = [r for r in recs if 85 < ask(r) <= 99]
res = [r for r in recs if 86 <= ask(r) <= 89]
comp = [e for e in out if e["enrichment"]["status"] == "enriched" or
        (e.get("strike") and e.get("annualized_vol"))]
qual = [e for e in out if e.get("position_and_trend_qualified")]
valid = [r for r in recs if r.get("probability_status") == "COMPUTED_VALID"]
adm = [r for r in recs if r.get("lane_would_admit")]
print("=== SEPARATED COUNTS (eval-sides) ===")
print(f"above_85_price_candidates:        {len(above)}")
print(f"research_86_89_price_candidates:  {len(res)}")
print(f"complete_input_candidates:        {len(comp)}  (after contemporaneous enrichment)")
print(f"position_and_trend_qualified:     {len(qual)}")
print(f"valid_forecast_candidates:        {len(valid)}  (engine COMPUTED_VALID)")
print(f"shadow_economic_admissions:       {len(adm)}")
print("production_divergences:",
      dict(collections.Counter(r.get("engine_decision_reason") for r in recs)))
print()
for e in comp:
    print(f"  {e['asset']:4s} {e['side']:3s} ask={e['ask_cents']:5.1f} "
          f"d={e['enrichment'].get('signed_distance_price')} "
          f"z={e['enrichment'].get('z_cushion')} "
          f"trend={e['enrichment'].get('trend_enriched')} "
          f"q_phi={e['enrichment'].get('q_phi_enriched_diagnostic')}")
