"""late_window_trend_favorite — probability-trace + coverage diagnostic (offline).

Decomposes raw_p -> cal_p into (tail-cap, streaming-bound, lane-cap) stages on
the stored cohort, verifies the Phi(z) baseline under each unit convention,
reconciles cushion coverage, and re-slices the 86-89c candidate with
asset x side and predicted-vs-observed calibration.

No merid imports: tail calibrator JSON + streaming state are replicated here
exactly from merid/risk/probability/tail_calibrator.py and
merid/prediction/streaming_calibration.py semantics.
"""
import json, math, os, sqlite3, collections

ROOT = r"C:\Dev\MERID"
EXTRACT = os.path.join(ROOT, "data", "_lwf_extract.jsonl")
TAIL_JSON = os.path.join(ROOT, "data", "probability_tail_calibration.json")
STREAM_JSON = os.path.join(ROOT, "data", "streaming_calibration.json")
SETTLE = os.path.join(ROOT, "logs", "settlement_outcomes.jsonl")
SHADOW = os.path.join(ROOT, "logs", "late_taker_shadow.jsonl")
DB = os.path.join(ROOT, "data", "decision_audit.db")
SECS_PER_YEAR = 365.0 * 86400.0
PHI = lambda z: 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))

# ---------- artifact: tail calibration (replicated lookup, PAVA step knots) ---
tj = json.load(open(TAIL_JSON))
BUFFER = float(tj.get("buffer", 0.05))
def _lookup(price, xs, ys):
    if not xs:
        return price
    price = max(0.0, min(1.0, price))
    if price <= xs[0]:
        return ys[0]
    for x, y in zip(xs, ys):
        if price <= x:
            return y
    return ys[-1]
def _asset_curves(asset):
    pa = (tj.get("per_asset") or {}).get(str(asset).upper())
    if pa and int(pa.get("n") or 0) >= 500:
        return (pa["yes_held_prices"], pa["yes_actual_probs"],
                pa["no_held_prices"], pa["no_actual_probs"])
    return (tj["yes_held_prices"], tj["yes_actual_probs"],
            tj["no_held_prices"], tj["no_actual_probs"])
def curve_p(side, entry_frac, asset):
    yx, yy, nx, ny = _asset_curves(asset)
    return _lookup(entry_frac, yx, yy) if side == "yes" else _lookup(entry_frac, nx, ny)
def cap_p(side, raw_p, entry_frac, asset):
    return min(raw_p, curve_p(side, entry_frac, asset) + BUFFER)

# ---------- streaming bound (replicated; decayed to eval ts) -----------------
sj = json.load(open(STREAM_JSON))
CELLS = sj.get("cells") or {}
HL = 10.0          # MERID_STREAM_CAL_HALFLIFE_DAYS default
PRIOR_K = 20.0     # MERID_STREAM_CAL_PRIOR_K
MIN_NEFF = 8.0     # MERID_STREAM_CAL_MIN_NEFF
SBUF = 0.05        # MERID_STREAM_CAL_BUFFER
CUSUM_H = 0.5      # MERID_DRIFT_CUSUM_H
P_ORDER = ("01-09", "10-24", "25-49", "50-74", "75-89", "90-100")
def price_bucket(pc):
    p = int(round(pc))
    return ("01-09" if p <= 9 else "10-24" if p <= 24 else "25-49" if p <= 49
            else "50-74" if p <= 74 else "75-89" if p <= 89 else "90-100")
def tte_bucket(t):
    return "early" if t > 600 else "mid" if t > 300 else "late" if t > 120 else "final"
def _pav(xs, ws):
    blocks = [[x, w, 1] for x, w in zip(xs, ws)]
    out, i, n = [], 0, len(blocks)
    while i < n - 1:
        if blocks[i][0] > blocks[i + 1][0] + 1e-12:
            w = blocks[i][1] + blocks[i + 1][1]
            m = (blocks[i][0] * blocks[i][1] + blocks[i + 1][0] * blocks[i + 1][1]) / w
            blocks[i] = [m, w, blocks[i][2] + blocks[i + 1][2]]
            del blocks[i + 1]; n -= 1; i = max(0, i - 1)
        else:
            i += 1
    for m, _w, c in blocks:
        out.extend([m] * int(c))
    return out
def stream_bound(asset, side, pc, tte, now_ts):
    a, s, tb, pb = str(asset).upper(), side, tte_bucket(tte), price_bucket(pc)
    eff = {}
    for k, c in CELLS.items():
        d = 0.5 ** (max(0.0, (now_ts - float(c.get("ts") or 0)) / 86400.0) / HL)
        n = float(c.get("n") or 0) * d
        if n > 0:
            eff[k] = {"wy": float(c["wy"]) * d, "wp": float(c["wp"]) * d,
                      "n": n, "cusum_hi": float(c.get("cusum_hi") or 0) * d}
    sl = {b: eff[f"{a}|{s}|{b}|{tb}"] for b in P_ORDER if f"{a}|{s}|{b}|{tb}" in eff}
    pooled = False
    if not sl or sl.get(pb) is None or sl[pb]["n"] < MIN_NEFF:
        pooled_map = {}
        for k, c in eff.items():
            ka, ks, kb, _kt = k.split("|", 3)
            if ka == a and ks == s:
                r = pooled_map.setdefault(kb, {"wy": 0, "wp": 0, "n": 0})
                for f in ("wy", "wp", "n"):
                    r[f] += c[f]
        if not pooled_map:
            return None
        sl = pooled_map; pooled = True
    xs, ws, present = [], [], []
    for b in P_ORDER:
        c = sl.get(b)
        if not c or c["n"] <= 0:
            continue
        claimed = c["wp"] / c["n"]
        m = (c["wy"] + PRIOR_K * claimed) / (c["n"] + PRIOR_K)
        xs.append(m + (0.0 if float(c.get("cusum_hi") or 0) >= CUSUM_H else SBUF))
        ws.append(c["n"] + PRIOR_K); present.append(b)
    if not present:
        return None
    bmap = dict(zip(present, _pav(xs, ws)))
    exact = sl.get(pb)
    if exact is not None and exact["n"] >= MIN_NEFF and pb in bmap:
        return max(0.01, min(0.99, bmap[pb]))
    tw = sum(c["wy"] for c in sl.values()); tp = sum(c["wp"] for c in sl.values())
    tn = sum(c["n"] for c in sl.values())
    if tn <= 0:
        return None
    b = (tw + PRIOR_K * (tp / tn)) / (tn + PRIOR_K) + SBUF
    return max(0.01, min(0.99, b))

def fee_cents(frac, role="taker"):
    r = 0.0175 if role == "maker" else 0.07
    p = min(0.99, max(0.01, frac))
    return max(0.0, math.ceil(r * 1.0 * p * (1 - p) * 1e4) * 100.0 / 1e4)

# ---------- load extract + settlements ---------------------------------------
rows = []
with open(EXTRACT, encoding="utf-8", errors="replace") as f:
    for line in f:
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
settle = {}
with open(SETTLE, encoding="utf-8", errors="replace") as f:
    for line in f:
        try:
            r = json.loads(line)
        except Exception:
            continue
        t = r.get("ticker")
        if not t:
            continue
        if r.get("resolved_yes") is not None:
            settle[t] = int(r["resolved_yes"])
        elif (r.get("outcome") or "") in ("yes", "no"):
            settle[t] = 1 if r["outcome"] == "yes" else 0

# ---------- trajectory from the extract itself (TTE<=200 series) -------------
traj = collections.defaultdict(list)
K_of = {}
for r in rows:
    ref = r.get("ref") if r.get("ref") is not None else r.get("spot")
    K = r.get("strike")
    if K and r["ticker"] not in K_of:
        K_of[r["ticker"]] = float(K)
    if ref is not None and K:
        traj[r["ticker"]].append((float(r["ts"]), float(ref) - float(K)))
for v in traj.values():
    v.sort()

# frozen trend spec: lookback L=30s (+/-15s window), flat tol = 0.10*sigma_rem_price
TREND_L, TREND_W, FLAT_FRAC = 30.0, 15.0, 0.10

# ---------- cohort = engine eval-sides with own-side ask>85, tte<=150 --------
cohort = []
for r in rows:
    t = r.get("tte")
    if t is None or t > 150 or (r.get("sver") != "trade_decision_v2"):
        continue
    for side, sev in (r.get("sev") or {}).items():
        ask = sev.get("px")
        if ask is None or ask <= 85:
            continue
        cohort.append((r, side, sev))
print(f"engine eval-sides ask>85c tte<=150: {len(cohort)}")

# ---------- per-record trace -------------------------------------------------
recs = []
missing = collections.Counter()
for r, side, sev in cohort:
    s_dir = 1.0 if side == "yes" else -1.0
    K = r.get("strike")
    ref = r.get("ref") if r.get("ref") is not None else r.get("spot")
    spot = r.get("spot")
    vol = r.get("vol")
    tte = float(r["tte"])
    ask_c = float(sev["px"])
    cal = sev.get("cal_p")
    raw_side = (r.get("raw_p") if side == "yes"
                else (1.0 - r["raw_p"] if r.get("raw_p") is not None else None))
    lm = math.log(float(ref) / float(K)) if (ref and K and float(K) > 0) else None
    lm_spot = math.log(float(spot) / float(K)) if (spot and K and float(K) > 0) else None
    t_y = tte / SECS_PER_YEAR
    sig = float(vol) * math.sqrt(t_y) if vol else None  # return-space sigma_rem
    d_side = s_dir * (float(ref) - float(K)) if (ref is not None and K) else None
    z_base = (lm / sig) if (lm is not None and sig and sig > 0) else None
    z_base_spot = (lm_spot / sig) if (lm_spot is not None and sig and sig > 0) else None
    q_base = PHI(s_dir * z_base) if z_base is not None else None
    z_cush = (d_side / (float(ref) * sig)) if (d_side is not None and sig) else None
    zs_st = r.get("zs")
    # stage decomposition
    p_tail = cap_p(side, raw_side, ask_c / 100.0, r["asset"]) if raw_side is not None else None
    ts_eval = float(r["ts"])
    bnd = stream_bound(r["asset"], side, ask_c, tte, ts_eval)
    lane_hi = 0.999 if (sev.get("lane") == "settlement_convergence") else (
        0.99 if sev.get("lane") in ("pinned_fav",) else 0.95)
    p_pred = None
    if p_tail is not None:
        p_pred = min(p_tail, lane_hi)
        if bnd is not None:
            p_pred = min(p_pred, bnd)
    fee = fee_cents(ask_c / 100.0)
    # frozen trend: signed cushion now vs 30s ago, flat band = +/-0.10*sigma_rem_price
    tr = "no_prior"
    sig_price = float(ref) * sig if (ref and sig) else None
    pts = [(t_, d_) for (t_, d_) in traj.get(r["ticker"], [])
           if TREND_L - TREND_W <= ts_eval - t_ <= TREND_L + TREND_W]
    if pts and d_side is not None:
        _tp, prev_d = min(pts, key=lambda pd: abs(ts_eval - pd[0] - TREND_L))
        tol = (FLAT_FRAC * sig_price) if sig_price else 0.0
        chg = (s_dir * (float(ref) - float(K))) - (s_dir * prev_d)
        tr = ("expanding" if chg > tol else "shrinking" if chg < -tol else "flat")
    crosses = 0; last = 0
    for (t_, d_) in traj.get(r["ticker"], []):
        if t_ >= ts_eval or ts_eval - t_ > 60:
            continue
        sg = 1 if d_ > 0 else (-1 if d_ < 0 else 0)
        if last and sg and sg != last:
            crosses += 1
        if sg:
            last = sg
    if ref is None:
        missing["no_ref_or_spot"] += 1
    if not K:
        missing["no_K"] += 1
    if not vol:
        missing["no_vol"] += 1
    if raw_side is None:
        missing["no_raw_p"] += 1
    if cal is None:
        missing["no_cal_p"] += 1
    sy = settle.get(r["ticker"])
    won = None if sy is None else (bool(sy) == (side == "yes"))
    recs.append(dict(r=r, side=side, sev=sev, asset=r["asset"], tick=r["ticker"],
        tte=tte, ask_c=ask_c, raw=raw_side, cal=cal, p_tail=p_tail, bnd=bnd,
        p_pred=p_pred, q_base=q_base, z_base=z_base, z_spot=z_base_spot,
        zs_st=zs_st, lm=lm, sig=sig, vol=vol, d_side=d_side, z_cush=z_cush,
        trend=tr, crosses=crosses, fee=fee, won=won, ts=ts_eval,
        lane=sev.get("lane"), gev=sev.get("gev"), nev=sev.get("nev")))

print("missing inputs:", dict(missing))

# ---------- 1. baseline verification -----------------------------------------
print("\n=== BASELINE VERIFICATION ===")
cmp_ = [(abs(e["raw"] - PHI(e["zs_st"] * 1.0)) if e["side"] == "yes" else
        abs(e["raw"] - (1 - PHI(e["zs_st"]))) )
       for e in recs if e["raw"] is not None and e["zs_st"] is not None]
# raw_side for 'no' = 1 - raw_p_yes = 1 - Phi(zs) = Phi(-zs)
if cmp_:
    cmp_.sort()
    print(f"stored raw_p_side vs Phi(stored zscore): n={len(cmp_)} "
          f"median|diff|={cmp_[len(cmp_)//2]:.5f} p90={cmp_[9*len(cmp_)//10]:.5f} "
          f"max={cmp_[-1]:.5f}")
cmpz = [(abs(e["z_spot"] - e["zs_st"])) for e in recs
        if e["z_spot"] is not None and e["zs_st"] is not None]
if cmpz:
    cmpz.sort()
    print(f"recomputed z(spot,lm/sig) vs stored zscore: n={len(cmpz)} "
          f"median|diff|={cmpz[len(cmpz)//2]:.4f} p90={cmpz[9*len(cmpz)//10]:.4f}")
qb = [e["q_base"] for e in recs if e["q_base"] is not None]
rawv = [e["raw"] for e in recs if e["raw"] is not None]
calv = [e["cal"] for e in recs if e["cal"] is not None]
def _med(x): return sorted(x)[len(x)//2] if x else float("nan")
print(f"median raw_p_side={_med(rawv):.3f}  cal_p_side={_med(calv):.3f}  "
      f"Phi-baseline={_med(qb):.3f}")
sign_bad = sum(1 for e in recs if e["d_side"] is not None and e["d_side"] > 0
               and e["raw"] is not None and e["raw"] < 0.5)
print(f"raw_p<0.5 while correct-side-of-target: {sign_bad} "
      f"(expect 0 under correct sign/units)")

# ---------- 2. stage decomposition -------------------------------------------
print("\n=== STAGE DECOMPOSITION (margin = p*100 - ask - taker_fee) ===")
stg = collections.Counter(); marg = collections.defaultdict(list)
for e in recs:
    if e["raw"] is None or e["cal"] is None:
        continue
    m = e["cal"] * 100 - e["ask_c"] - e["fee"]
    marg["final"].append(m)
    if e["p_tail"] is not None:
        marg["post_tail"].append(e["p_tail"] * 100 - e["ask_c"] - e["fee"])
    if e["raw"] is not None:
        marg["raw"].append(e["raw"] * 100 - e["ask_c"] - e["fee"])
    drop_tail = (e["p_tail"] - e["raw"]) if e["p_tail"] is not None else 0.0
    drop_rest = (e["cal"] - e["p_tail"]) if e["p_tail"] is not None else 0.0
    if abs(e["cal"] - (e["p_pred"] or -9)) < 0.02:
        stg["pred_matches_cal"] += 1
    if drop_tail < -0.02:
        stg["tail_cap_binds"] += 1
    if drop_rest < -0.02:
        stg["stream_bound_binds_further"] += 1
    if e["bnd"] is not None:
        stg["stream_bound_present"] += 1
    if e["cal"] > e["raw"] + 0.02:
        stg["cal_above_raw"] += 1
for k, v in marg.items():
    v.sort()
    print(f"  {k:10s} n={len(v):4d} median={v[len(v)//2]:+7.2f}c "
          f"p10={v[len(v)//10]:+7.2f} p90={v[9*len(v)//10]:+7.2f}")
print("stage flags:", dict(stg))

# median drop attribution
dt = sorted((e["p_tail"] - e["raw"]) * 100 for e in recs
            if e["raw"] is not None and e["p_tail"] is not None)
dr = sorted((e["cal"] - e["p_tail"]) * 100 for e in recs
            if e["cal"] is not None and e["p_tail"] is not None)
print(f"median tail-cap delta: {_med(dt):+.2f}c | median post-tail->cal delta: {_med(dr):+.2f}c")

# ---------- 3. coverage reconciliation ---------------------------------------
print("\n=== CUSHION COVERAGE (engine cohort) ===")
cov = collections.Counter()
for e in recs:
    has = (e["d_side"] is not None, e["sig"] is not None, e["z_cush"] is not None)
    cov[f"d_side={has[0]},sig={has[1]},z={has[2]}"] += 1
for k, n in cov.most_common():
    print(f"  {n:5d}  {k}")
tp = collections.Counter(e["trend"] for e in recs)
print("trend (frozen L=30s, tol=0.10*sigma_rem):", dict(tp))
print("crossings<=60s:", dict(collections.Counter(min(e["crosses"],3) for e in recs)))

# ---------- 4. one-entry-per-market outcomes ----------------------------------
print("\n=== ONE-ENTRY-PER-(TICKER,SIDE) — lane def: ask>85, tte<=150, d_side>0, trend!=shrinking ===")
rule = collections.defaultdict(list)
for e in recs:
    if e["d_side"] is not None and e["d_side"] > 0 and e["won"] is not None:
        rule[(e["tick"], e["side"])].append(e)
picks = []
for k, rs in rule.items():
    rs.sort(key=lambda e: e["ts"])
    picks.append(next((e for e in rs if e["trend"] != "shrinking"), rs[0]))
def band(p):
    for lo, hi in ((86,89),(90,91),(92,95),(96,99)):
        if lo <= p <= hi: return f"{lo}-{hi}"
    return "?"
def tteb(t): return "121-150" if t > 120 else "61-120" if t > 60 else "<=60"
def zband(z):
    if z is None: return "no_z"
    if z < 0: return "wrong_side"
    for lo,hi in ((0,.5),(.5,1),(1,2),(2,4),(4,1e9)):
        if lo <= z < hi: return f"z{lo}-{hi if hi<1e8 else 'inf'}"
    return "z4+"
agg = collections.defaultdict(lambda: [0,0,0.0,0.0])
for e in picks:
    pt = (100 - e["ask_c"] - e["fee"]) if e["won"] else (-e["ask_c"] - e["fee"])
    for k in (("ALL",), (e["asset"],), (e["asset"],e["side"]), (band(e["ask_c"]),),
              (tteb(e["tte"]),), (zband(e["z_cush"]),), (e["trend"],),
              (e["asset"], band(e["ask_c"])), (e["side"], band(e["ask_c"]))):
        v = agg[k]; v[0]+=1; v[1]+=e["won"]; v[2]+=pt; v[3]+= (e["cal"] or 0)
for k in sorted(agg):
    n,w,p,cp = agg[k]
    print(f"  {str(k):22s} n={n:4d} win={w/n*100:5.1f}% pnl_t={p:+8.1f} ({p/n:+6.2f}/tr) mean_cal={cp/n:.3f}")

print("\n=== 86-89c candidate slice: asset x side ===")
for k in sorted(agg):
    if len(k)==2 and k[1]=="86-89":
        n,w,p,cp = agg[k]
        print(f"  {str(k):22s} n={n:4d} win={w/n*100:5.1f}% pnl_t={p:+8.1f} ({p/n:+6.2f}/tr) mean_cal={cp/n:.3f}")

# ---------- 5. predicted vs observed on the defined population ----------------
print("\n=== PREDICTED-vs-OBSERVED (one-entry picks, cal_p buckets) ===")
rel = collections.defaultdict(lambda: [0,0,0.0])
for e in picks:
    if e["cal"] is None: continue
    b = "p<.5" if e["cal"]<.5 else ".5-.7" if e["cal"]<.7 else ".7-.85" if e["cal"]<.85 else ">=.85"
    v = rel[b]; v[0]+=1; v[1]+=e["won"]; v[2]+=e["cal"]
for b in ("p<.5",".5-.7",".7-.85",">=.85"):
    if rel[b][0]:
        n,w,s = rel[b]
        print(f"  {b:7s} n={n:4d} predicted={s/n:.3f} observed={w/n*100:.1f}%")

# ============================================================================
# 6. SHADOW COHORT (20d, floor-rejected engine evals) — the -42c decomposition
# ============================================================================
print("\n" + "=" * 70)
print("=== SHADOW COHORT (late_taker_shadow, ask>85c tte<=150) ===")
scoh = []
with open(SHADOW, encoding="utf-8", errors="replace") as f:
    for line in f:
        try:
            r = json.loads(line)
        except Exception:
            continue
        t = r.get("tte_seconds"); ask = r.get("ask_cents")
        if t is None or ask is None or t > 150 or ask <= 85:
            continue
        scoh.append(r)
print(f"shadow eval-sides: {len(scoh)}")

def ro(path):
    p = os.path.abspath(path).replace("\\", "/")
    if not p.startswith("/"):
        p = "/" + p
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    c.execute("PRAGMA busy_timeout=60000")
    return c

conn = ro(DB)
sfield = {}
dids = [r["decision_id"] for r in scoh if r.get("decision_id")]
for i in range(0, len(dids), 400):
    ch = dids[i:i+400]
    ph = ",".join("?" * len(ch))
    for row in conn.execute(
        "SELECT s.decision_id, s.raw_p_yes, s.calibrated_p_yes, s.zscore, "
        "s.spot_price, s.settlement_reference_price, s.vol_forecast, "
        "d.strike, s.settlement_reference_source, s.log_moneyness "
        "FROM strategy_decision_snapshots s "
        "JOIN strategy_decisions d ON d.decision_id = s.decision_id "
        f"WHERE s.decision_id IN ({ph})", ch):
        sfield[row[0]] = dict(raw_y=row[1], cal_y=row[2], zs=row[3], spot=row[4],
                              ref=row[5], vol=row[6], K=row[7], ref_src=row[8],
                              lm=row[9])
print(f"snapshots joined: {len(sfield)}/{len(scoh)}")

cov = collections.Counter(); srecs = []
for r in scoh:
    side = r["side"]; s_dir = 1.0 if side == "yes" else -1.0
    sf = sfield.get(r.get("decision_id")) or {}
    ref = sf.get("ref") if sf.get("ref") is not None else sf.get("spot")
    K = sf.get("K"); vol = sf.get("vol")
    tte = float(r["tte_seconds"]); ask_c = float(r["ask_cents"])
    raw = (sf.get("raw_y") if side == "yes"
           else (1 - sf["raw_y"] if sf.get("raw_y") is not None else None))
    cal = r.get("p_calibrated")
    d_side = s_dir * (float(ref) - float(K)) if (ref is not None and K) else None
    t_y = tte / SECS_PER_YEAR
    sig = float(vol) * math.sqrt(t_y) if vol else None
    z_cush = (d_side / (float(ref) * sig)) if (d_side is not None and sig) else None
    q_base = PHI(s_dir * math.log(float(ref)/float(K)) / sig) if (ref and K and sig) else None
    p_tail = cap_p(side, raw, ask_c/100.0, r["asset"]) if raw is not None else None
    try:
        from datetime import datetime
        ts_eval = datetime.fromisoformat(
            r["event_ts_utc"].replace("Z", "+00:00")).timestamp()
    except Exception:
        ts_eval = None
    bnd = (stream_bound(r["asset"], side, ask_c, tte, ts_eval)
           if ts_eval else None)
    fee = fee_cents(ask_c / 100.0)
    cov[("has_snap=%s" % bool(sf), "ref=%s" % (ref is not None),
         "K=%s" % bool(K), "vol=%s" % bool(vol), "z=%s" % (z_cush is not None))] += 1
    sy = settle.get(r["ticker"])
    won = None if sy is None else (bool(sy) == (side == "yes"))
    srecs.append(dict(r=r, side=side, asset=r["asset"], tick=r["ticker"], tte=tte,
        ask_c=ask_c, raw=raw, cal=cal, p_tail=p_tail, bnd=bnd, q_base=q_base,
        z_cush=z_cush, d_side=d_side, sig=sig, zs=sf.get("zs"), fee=fee, won=won))

print("\ncoverage cross-tab (has_snap,ref,K,vol,z):")
for k, n in cov.most_common():
    print(f"  {n:5d}  {k}")

print("\n--- stage decomposition (margin cents) ---")
mg = collections.defaultdict(list); fl = collections.Counter()
for e in srecs:
    if e["raw"] is None or e["cal"] is None:
        fl["missing_raw_or_cal"] += 1
        continue
    mg["raw"].append(e["raw"] * 100 - e["ask_c"] - e["fee"])
    if e["p_tail"] is not None:
        mg["post_tail"].append(e["p_tail"] * 100 - e["ask_c"] - e["fee"])
    mg["final"].append(e["cal"] * 100 - e["ask_c"] - e["fee"])
    if e["q_base"] is not None:
        mg["phi_baseline"].append(e["q_base"] * 100 - e["ask_c"] - e["fee"])
    if e["p_tail"] is not None and e["p_tail"] < e["raw"] - 0.02:
        fl["tail_cap_binds"] += 1
    if e["bnd"] is not None:
        fl["stream_bound_present"] += 1
        if e["p_tail"] is not None and e["bnd"] < e["p_tail"] - 0.02:
            fl["stream_binds_below_tail"] += 1
    if e["cal"] is not None and e["raw"] is not None and e["cal"] < e["raw"] - 0.02:
        fl["cal_below_raw"] += 1
for k, v in sorted(mg.items()):
    v.sort()
    print(f"  {k:13s} n={len(v):4d} med={v[len(v)//2]:+7.2f}c "
          f"p10={v[len(v)//10]:+7.2f} p90={v[9*len(v)//10]:+7.2f}")
print("flags:", dict(fl))
dt = sorted((e["p_tail"]-e["raw"])*100 for e in srecs if e["raw"] is not None and e["p_tail"] is not None)
dr = sorted((e["cal"]-e["p_tail"])*100 for e in srecs if e["cal"] is not None and e["p_tail"] is not None)
print(f"median tail-cap delta={_med(dt):+.2f}c | median tail->cal delta={_med(dr):+.2f}c")

# enriched-subset: production raw vs independent Phi-baseline on same cushion
en = [e for e in srecs if e["q_base"] is not None and e["raw"] is not None]
if en:
    a = sorted(e["raw"]*100 - e["ask_c"] - e["fee"] for e in en)
    b = sorted(e["q_base"]*100 - e["ask_c"] - e["fee"] for e in en)
    dz = sorted(abs((e["zs"] or 0) - (e["q_base"] and 0 or 0)) for e in en)
    zcmp = [(e["zs"], None) for e in en[:0]]
    print(f"\nenriched subset n={len(en)}: raw_margin={a[len(a)//2]:+.2f}c "
          f"phi_margin={b[len(b)//2]:+.2f}c")
    zw = [(e["zs"], (e["d_side"]/(e["ref0"]*e["sig"])) if False else e["z_cush"])
          for e in en]
    pair = sorted(abs((e["zs"] or 0) - (e["z_cush"] or 0)) for e in en
                  if e["zs"] is not None and e["z_cush"] is not None)
    if pair:
        print(f"stored zscore vs z_cushion |diff|: med={pair[len(pair)//2]:.2f} "
              f"p90={pair[9*len(pair)//10]:.2f}")
    sb = sum(1 for e in en if e["d_side"] > 0 and e["raw"] < 0.5)
    print(f"correct-side & raw<0.5 on enriched: {sb}/{len(en)}")

# per-band decomposition
print("\n--- per price band: raw -> tail -> cal margins ---")
pb = collections.defaultdict(lambda: collections.defaultdict(list))
for e in srecs:
    if e["raw"] is None or e["cal"] is None:
        continue
    b = band(e["ask_c"])
    pb[b]["raw"].append(e["raw"]*100 - e["ask_c"] - e["fee"])
    if e["p_tail"] is not None:
        pb[b]["tail"].append(e["p_tail"]*100 - e["ask_c"] - e["fee"])
    pb[b]["cal"].append(e["cal"]*100 - e["ask_c"] - e["fee"])
for b in ("86-89","90-91","92-95","96-99"):
    if b in pb:
        out = f"  {b}: n={len(pb[b]['cal'])}"
        for s in ("raw","tail","cal"):
            v = sorted(pb[b][s])
            if v: out += f"  {s}={v[len(v)//2]:+.1f}c"
        print(out)

# annotated traces: one per band
print("\n--- annotated example traces ---")
seen = set()
for e in srecs:
    b = band(e["ask_c"])
    if b in seen or e["raw"] is None or e["cal"] is None or e["d_side"] is None:
        continue
    seen.add(b)
    print(f"  [{b}] {e['tick']} {e['side']} ask={e['ask_c']:.0f}c tte={e['tte']:.0f}s "
          f"asset={e['asset']}")
    print(f"     K={e['r'].get('strike') or 'n/a'} d_side={e['d_side']:+.4g} "
          f"z_cush={e['z_cush'] if e['z_cush'] is None else round(e['z_cush'],2)} "
          f"q_phi={e['q_base'] if e['q_base'] is None else round(e['q_base'],3)}")
    print(f"     raw={e['raw']:.3f} -> tail={e['p_tail']:.3f} -> "
          f"stream_bnd={e['bnd'] if e['bnd'] is None else round(e['bnd'],3)} "
          f"-> cal={e['cal']:.3f} | margin={e['cal']*100-e['ask_c']-e['fee']:+.1f}c "
          f"reason={e['r'].get('decision_reason')} won={e['won']}")
