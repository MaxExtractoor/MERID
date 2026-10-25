"""late_window_trend_favorite — waterfall grader for logs/lwf_shadow.jsonl (v2).

First-live-report requirements:
  scheduled evaluations by asset | logger invocation count | records written
  complete-input forecasts | fallback/unknown forecasts | missing-input reasons
  valid model-margin positives | lane admissions | production floor conflicts

Funnel (three-state): scheduled(120<tte<=150) -> trusted inputs -> ask>85c
-> research band -> correct side -> non-shrinking -> depth -> bookflow ->
model margin (COMPUTED_VALID only) -> lane econ admission -> hypothetical
taker execution -> settlement.

Outcomes graded ONLY on named valid populations: one entry per
(ticker, side) where every stage == "pass".
"""
import json, os, collections, sys

ROOT = r"C:\Dev\MERID"
LOG = os.environ.get("MERID_LWF_SHADOW_LOG", os.path.join(ROOT, "logs", "lwf_shadow.jsonl"))
SETTLE = os.path.join(ROOT, "logs", "settlement_outcomes.jsonl")

STAGE_ORDER = ["w1_inputs_trusted", "w2_price_above_85", "w2b_research_band_86_89",
               "w3_correct_side", "w4_trend_non_shrinking", "w5_depth_ok",
               "w6_bookflow_clear", "w7_model_margin_positive",
               "w8_econ_admission_lane"]

recs, metas = [], []
if not os.path.exists(LOG):
    print(f"no records yet at {LOG}")
    sys.exit(0)
with open(LOG, encoding="utf-8", errors="replace") as f:
    for line in f:
        try:
            r = json.loads(line)
        except Exception:
            continue
        (metas if r.get("type") == "lwf_shadow_meta" else recs).append(r) \
            if r.get("type") in ("lwf_shadow", "lwf_shadow_meta") else None

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

last_meta = metas[-1] if metas else {}

print("=== PROCESS / REVISION ===")
print(f"meta heartbeats: {len(metas)}  records: {len(recs)}")
print(f"schema_version: {last_meta.get('schema_version','?')}  "
      f"lane_revision: {last_meta.get('lane_revision','?')}")
print(f"process_id: {last_meta.get('process_id','?')}  "
      f"counters_reset_utc: {last_meta.get('counters_reset_utc','?')}")
procs = collections.Counter(r.get("process_id") for r in recs)
if len(procs) > 1:
    print("  NOTE: records span multiple process_ids:", dict(procs))

print("\n=== HOOK COVERAGE (unit-explicit counters) ===")
print({k: last_meta.get(k) for k in (
    "hook_invocations", "invocations_skipped_tte", "side_evaluations",
    "records_written", "side_evaluations_deduplicated",
    "evaluation_errors", "write_errors")})
hi = last_meta.get("hook_invocations") or 0
sk = last_meta.get("invocations_skipped_tte") or 0
se = last_meta.get("side_evaluations") or 0
rw = last_meta.get("records_written") or 0
dd = last_meta.get("side_evaluations_deduplicated") or 0
we = last_meta.get("write_errors") or 0
print(f"reconcile: invocations {hi} = in-window {hi-sk} + skipped {sk}  |  "
      f"written {rw} = side_evals {se} - dedup {dd}  |  write_errors {we}")
if rw != se - dd:
    print("  !! counters do not reconcile — check write_errors/process restarts")
print("per-asset hook coverage:", json.dumps(last_meta.get("by_asset"), default=str))
print(f"records written (file): {len(recs)}  in-window eval-sides by asset:",
      dict(collections.Counter(r['asset'] for r in recs)))
print("eval_path:", dict(collections.Counter(r.get('eval_path') for r in recs)))
if rw == 0 and hi > 0:
    print("  nonzero invocations, zero records -> reconcile skips/dedup/errors "
          "above; do NOT read this as an input constraint")

print("\n=== FORECAST PROVENANCE ===")
print("probability_status:", dict(collections.Counter(r.get("probability_status") for r in recs)))
print("probability_source:", dict(collections.Counter(r.get("probability_source") for r in recs)))
mi = collections.Counter()
for r in recs:
    for f_ in (r.get("missing_input_fields") or []):
        mi[f_] += 1
print("missing_input_fields:", dict(mi))
print("model_evaluation_completed:", dict(collections.Counter(bool(r.get("model_evaluation_completed")) for r in recs)))
ref_ok = sum(1 for r in recs if r.get("ref_price_ts_utc") and
             (r.get("rti_age_ms") is None or float(r["rti_age_ms"]) <= 2000.0))
print(f"records with valid ref timestamp: {ref_ok}/{len(recs)}")

print("\n=== CANDIDATE WATERFALL (eval-side view, three-state) ===")
stage_ct = collections.defaultdict(collections.Counter); first_fail = collections.Counter()
for r in recs:
    st = r.get("stages") or {}
    for s in STAGE_ORDER:
        stage_ct[s][st.get(s, "?")] += 1
    ff = r.get("first_failed_stage")
    if ff:
        first_fail[(ff, st.get(ff, "?"))] += 1
for s in STAGE_ORDER:
    c = stage_ct[s]
    print(f"  {s:28s} pass={c.get('pass',0):4d} fail={c.get('fail',0):4d} not_evaluable={c.get('not_evaluable',0):4d}")
print(f"lane_would_admit: {sum(1 for r in recs if r.get('lane_would_admit'))}  "
      f"verdicts:", dict(collections.Counter(r.get("lane_verdict") for r in recs)))
print("first non-pass stage:", {f"{k[0]}:{k[1]}": v for k, v in first_fail.most_common()})

print("\n=== PRODUCTION FLOOR CONFLICTS ===")
xt = collections.Counter((r.get("engine_would_reject_tte"), r.get("eval_path"),
                          r.get("engine_decision_reason") or "?") for r in recs)
for k, c in xt.most_common(12):
    print(f"  {c:5d}  floor_reject={k[0]} path={k[1]} reason={k[2]}")

valid = [r for r in recs if r.get("probability_status") == "COMPUTED_VALID"]
print(f"\n=== VALID FORECAST ECONOMICS (COMPUTED_VALID only, n={len(valid)}) ===")
mg = sorted(r["margin_fee_only_cents"] for r in valid if r.get("margin_fee_only_cents") is not None)
ml = sorted(r["margin_lane_cents"] for r in valid if r.get("margin_lane_cents") is not None)
if mg:
    print(f"model margin: med={mg[len(mg)//2]:+.2f}c p10={mg[len(mg)//10]:+.2f} "
          f"p90={mg[9*len(mg)//10]:+.2f} >0: {sum(1 for m in mg if m>0)}")
    print(f"lane margin : med={ml[len(ml)//2]:+.2f}c >0: {sum(1 for m in ml if m>0)}")

def band(p):
    for lo, hi in ((86, 89), (90, 91), (92, 95), (96, 99)):
        if lo <= p <= hi:
            return f"{lo}-{hi}"
    return "?"
print("\nprice band x side:", dict(collections.Counter((band(r["ask_cents"]), r["side"]) for r in recs)))
print("trend:", dict(collections.Counter(r.get("trend") for r in recs)))
print("crossings_60s:", dict(collections.Counter(min(r.get("crossings_60s") or 0, 3) for r in recs)))

print("\n=== ONE-ENTRY-PER-(TICKER,SIDE): lane-admitted only ===")
best = {}
for r in recs:
    if not r.get("lane_would_admit"):
        continue
    k = (r["ticker"], r["side"])
    if k not in best or r["event_ts_utc"] < best[k]["event_ts_utc"]:
        best[k] = r
print(f"admitted markets: {len(best)}")
agg = collections.defaultdict(lambda: [0, 0, 0.0]); pend = 0
for (tick, side), r in best.items():
    sy = settle.get(tick)
    if sy is None:
        pend += 1
        continue
    won = bool(sy) == (side == "yes")
    pnl = (100 - r["ask_cents"] - r["taker_fee_cents"]) if won else (-r["ask_cents"] - r["taker_fee_cents"])
    for k in (("ALL",), (r["asset"],), (r["asset"], side), (band(r["ask_cents"]),), (r["trend"],)):
        v = agg[k]; v[0] += 1; v[1] += won; v[2] += pnl
print(f"pending settlement: {pend}")
for k, (n, w, p) in sorted(agg.items()):
    print(f"  {str(k):16s} n={n:4d} win={w/n*100:5.1f}% pnl_t={p:+8.1f} ({p/n:+6.2f}/tr)")
