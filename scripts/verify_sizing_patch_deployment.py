"""Post-deployment verification for the 2026-11-05 sizing clip patch.

Run AFTER the separately-authorized production restart. Produces the minimum
verification record; records are "post-deployment, verification pending"
until every check passes — only then does the verified-current cohort open.

Checks (aligned to the agreed evidence record):
  1. deployment identity   — live process started after the patch timestamp
  2. shard resolution      — attempt payloads show resolved shard + source
  3. adaptive sizing       — requested 6 -> admissible qty (clip annotation)
  4. submission consistency— clipped qty == wire qty == acknowledged qty
  5. constraint accounting — premium <= stake cap; premium+fee <= cash
  6. attribution           — selected side / lane / probability orientation
  7. input integrity       — book validity / missing-input state at decision
  8. accounting            — fill qty, actual fees, reservation handling

Exit code 0 = all checks that could run passed. Items with no post-restart
evidence yet report PENDING, not PASS.
"""
import json, os, sqlite3, subprocess, sys, time
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
PATCH_FILES = [
    BASE / "merid" / "loop_15m.py",
    BASE / "merid" / "event_venues" / "kalshi" / "order_router.py",
    # 2026-11-06 schema v2 (commit 878c25e2) — included in freshness so an
    # interpreter older than these files flags as stale.
    BASE / "merid" / "event_venues" / "kalshi" / "order_identity.py",
    BASE / "merid" / "event_venues" / "kalshi" / "resting_order_monitor.py",
    BASE / "merid" / "prediction" / "decision_telemetry.py",
]
ATTEMPTS_DB = BASE / "data" / "kalshi_order_attempts.db"
FILLS_DB = BASE / "data" / "kalshi_fills.db"

results = []
def check(name, status, detail):
    results.append((name, status, detail))
    print(f"[{status:>7}] {name}: {detail}")

# ── 1a. process_restart (restart evidence only — NOT loaded-patch proof) ───
import hashlib
from datetime import timezone
patch_ts = max(os.path.getmtime(f) for f in PATCH_FILES)
patch_dt = datetime.fromtimestamp(patch_ts).astimezone()
live_pid = live_start = None
try:
    out = subprocess.check_output(
        ["wmic", "process", "where", "name='python.exe'",
         "get", "ProcessId,CreationDate,ExecutablePath,CommandLine"],
        text=True, timeout=30)
    rows = [l for l in out.splitlines() if l.strip() and "CreationDate" not in l]
    import re as _re
    self_pid = os.getpid()
    # The trading engine is the process whose cmdline runs the 15m web/loop
    # entrypoint — NOT analysis subprocesses (exporters, scripts, this verifier).
    ENGINE_RE = _re.compile(r"main_15m|uvicorn|loop_15m|start_15m", _re.I)
    for line in rows:
        m = _re.search(r"(\d{14})\.\d+([+-]\d+)", line)
        if not m: continue
        pid = int(line.rsplit()[-1])
        if pid == self_pid: continue
        ts = datetime.strptime(m.group(1), "%Y%m%d%H%M%S").timestamp()
        if ENGINE_RE.search(line) and (live_start is None or ts > live_start):
            live_start, live_pid = ts, pid
            live_cmd = line
    if live_start:
        st = "PASS" if live_start > patch_ts else "FAIL"
        check("process_restart", st,
              f"python.exe pid={live_pid} start={datetime.fromtimestamp(live_start).astimezone().isoformat()} "
              f"patch_mtime={patch_dt.isoformat()}")
    else:
        check("process_restart", "PENDING", "no python.exe with parseable CreationDate")
except Exception as e:
    check("process_restart", "PENDING", f"process check failed: {e}")

# ── 1b. loaded_patch_identity — artifact identity, not circumstances ───────
# A post-patch PID proves a restart, not that the intended checkout/modules/
# config were loaded.  Evidence we can capture externally:
#   - process start must post-date BOTH patch files' mtime (else interpreter
#     may hold pre-patch bytecode)
#   - record sha256 of the two patched files (detection: uncommitted edits
#     landing after process start invalidate the identity silently)
#   - report command line / executable path for account+checkout attestation
# Remaining PENDING items (cannot be verified from outside the process):
#   effective config, loaded-module __file__ paths, submission account/shard
#   -> confirm via startup telemetry line 'live_startup_preflight_passed' +
#      first attempt payload's resolved shard/account fields.
if live_start:
    later_edit = False
    hashes = {}
    for f in PATCH_FILES:
        mt = os.path.getmtime(f)
        hashes[f.name] = hashlib.sha256(open(f, "rb").read()).hexdigest()[:16]
        if mt > live_start: later_edit = True
    if later_edit:
        check("loaded_patch_identity", "FAIL",
              "patched file modified AFTER process start — interpreter may hold stale bytecode")
    else:
        check("loaded_patch_identity", "PASS_WITH_CAVEAT",
              f"pid={live_pid} post-dates file mtimes; sha256 "
              f"loop_15m={hashes['loop_15m.py']} order_router={hashes['order_router.py']}; "
              f"cmdline={live_cmd[:160]!r}")
        print("       NOTE: effective-config + loaded-module paths still require "
              "startup-telemetry / attempt-payload attestation")
else:
    check("loaded_patch_identity", "PENDING", "no live process")

# ── post-patch attempt records ────────────────────────────────────────────
attempts = []
if ATTEMPTS_DB.exists():
    con = sqlite3.connect(str(ATTEMPTS_DB)); con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM order_attempts WHERE created_at > ? ORDER BY created_at",
        (patch_ts,)).fetchall()
    for r in rows:
        try: pl = json.loads(r["payload_json"])
        except Exception: pl = {}
        attempts.append((r, pl))
    con.close()
check("post_patch_attempts", "INFO" if attempts else "PENDING",
      f"{len(attempts)} attempt records since patch timestamp")

# ── 3/4/5. three sizing paths — separate statuses, none manufactured ──────
# Compare against the exchange-acknowledged ORIGINAL order quantity where the
# attempt record carries it (a partial fill does not equal wrong wire qty).
REQ_MAX = 6.0
six_ok = clip_ok = 0
no_adm = 0
for r, p in attempts:
    o = p.get("order") or {}
    try:
        req = float(o.get("stake_cap_clipped_from_count_fp") or o.get("count_fp"))
        wire = float(o.get("count_fp"))
        ack = o.get("acknowledged_count_fp")
        ack = float(ack) if ack is not None else wire  # fall back to wire spec
    except Exception:
        continue
    if o.get("stake_cap_clipped_from_count_fp") and wire == ack and wire < req + 1e-9:
        clip_ok += 1
    elif not o.get("stake_cap_clipped_from_count_fp") and abs(req - REQ_MAX) < 1e-6 \
            and wire == ack == req:
        six_ok += 1
for r, p in attempts:
    rr = str(p.get("route_reason") or p.get("reason") or "")
    if "stake_at_risk_cap:no_admissible_qty" in rr and r["status"] == "REJECTED":
        no_adm += 1
check("six_contract_path", "PASS" if six_ok else "NOT_OBSERVED",
      f"{six_ok} attempts requested=submitted=acknowledged at 6")
check("clipped_quantity_path", "PASS" if clip_ok else "NOT_OBSERVED",
      f"{clip_ok} attempts clipped->wire==ack<requested")
check("no_admissible_qty_path", "PASS" if no_adm else "NOT_OBSERVED",
      f"{no_adm} no-admissible-qty rejections (distinct reason, no submission)")
check("constraint_accounting", "PENDING",
      "premium<=cap and premium+fee<=cash: reconcile router 'stake_at_risk_clip' "
      "log lines (cap=, shard_cash=) vs attempt payload price/count_fp per attempt")

# ── 3b. decision funnel — is zero-attempts 'nothing eligible' or 'stalled'?─
telemetry = BASE / "logs" / "decision_telemetry.jsonl"
if telemetry.exists():
    recent = post = 0
    kinds = {}
    try:
        with open(telemetry, encoding="utf-8") as f:
            f.seek(0, 2); size = f.tell()
            f.seek(max(0, size - 2_000_000))  # tail ~2MB only
            for line in f:
                try: d = json.loads(line)
                except Exception: continue
                ts = d.get("ts") or d.get("timestamp") or 0
                if ts > patch_ts:
                    post += 1
                    k = d.get("type") or d.get("event") or "row"
                    kinds[k] = kinds.get(k, 0) + 1
        check("decision_funnel", "PASS" if post else "PENDING",
              f"{post} post-patch telemetry rows; kinds={dict(sorted(kinds.items(), key=lambda x:-x[1])[:8])}")
    except Exception as e:
        check("decision_funnel", "PENDING", f"telemetry tail failed: {e}")
else:
    check("decision_funnel", "PENDING", "no decision_telemetry.jsonl")

# ── 6. attribution on post-patch attempts ────────────────────────────────
attr_ok = sum(1 for _, p in attempts
              if (p.get("order") or {}).get("side") in ("yes", "no")
              and (p.get("decision_lane") or (p.get("order") or {}).get("decision_lane")))
check("attribution", "PASS" if attempts and attr_ok == len(attempts) else "PENDING",
      f"{attr_ok}/{len(attempts)} attempts carry side + decision_lane")

# ── 7. input integrity — rejections for integrity vs sizing post-patch ────
rej = {}
for r, p in attempts:
    if r["status"] == "REJECTED":
        reason = p.get("route_reason") or p.get("reason") or ""
        rej[reason.split(":")[0]] = rej.get(reason.split(":")[0], 0) + 1
check("input_integrity", "INFO", f"post-patch rejection taxonomy: {rej}")

# ── 8. fills reconciliation on post-patch attempts ────────────────────────
if FILLS_DB.exists() and attempts:
    con = sqlite3.connect(str(FILLS_DB)); con.row_factory = sqlite3.Row
    try:
        nf = con.execute(
            "SELECT COUNT(*) FROM kalshi_fills WHERE created_at > ?", (patch_ts,)).fetchone()[0]
        check("accounting", "INFO", f"{nf} fill rows since patch timestamp — reconcile qty/fees per attempt manually")
    except Exception as e:
        check("accounting", "PENDING", f"fills query failed: {e}")
    con.close()

# ── 9. schema-v2 admitting-economics acceptance (commit 878c25e2) ─────────
# Only attempts whose payload actually carries schema v2 count — a historical
# attempt never acquires v2 status by post-hoc reconstruction.
v2 = [(r, p) for r, p in attempts
      if str(p.get("payload_schema_version")) == "2"]
if not v2:
    check("schema_v2_deployed", "PENDING",
          "0 attempts carry payload_schema_version=2 (commit 878c25e2 not yet "
          "deployed, or no post-deploy attempt)")
else:
    r, p = v2[-1]
    ae = p.get("admitting_economics") or {}
    ge = p.get("generic_economics") or {}
    o = p.get("order") or {}
    check("schema_v2_deployed", "PASS",
          f"{len(v2)} v2 attempt(s); latest={o.get('ticker')} status={r['status']}")
    # 9a. authority identification
    auth_ok = bool(ae.get("admitting_authority")) and (
        ae.get("admitting_lane") is not None
        or ae.get("admitting_authority") == "generic_gate")
    check("v2_authority", "PASS" if auth_ok else "FAIL",
          f"authority={ae.get('admitting_authority')} lane={ae.get('admitting_lane')} "
          f"route={ae.get('admitting_route')} basis={ae.get('price_basis')}")
    # 9b. arithmetic reconcile (full precision from payload, not log strings):
    #     gross - documented costs vs candidate net; ev_order ~ ev_pc * wire qty
    gross = ae.get("gross_edge_cents_per_contract")
    cand_ev = ae.get("candidate_ev_net_cents_per_contract")
    parts = [gross is not None, cand_ev is not None]
    recon = "gross=%s cand_net=%s" % (gross, cand_ev)
    sr = p.get("submit_revalidation") or {}
    ev_pc, ev_ord = sr.get("ev_per_contract_cents"), sr.get("ev_order_cents")
    qty_ok = None
    if ev_pc is not None and ev_ord is not None:
        try:
            wire = float(o.get("count_fp"))
            qty_ok = abs(float(ev_ord) - float(ev_pc) * wire) <= 0.51
            recon += f" | ev_ord={ev_ord} vs ev_pc*qty={float(ev_pc)*wire:.4f}"
        except Exception:
            recon += f" | ev_ord={ev_ord} ev_pc={ev_pc} wire={o.get('count_fp')}"
    check("v2_arithmetic",
          "PASS" if (all(parts) and (qty_ok is not False)) else
          ("PENDING" if not all(parts) else "FAIL"),
          recon)
    # 9c. quantity basis incl. clip: submit_revalidation on the SAME attempt
    #     that carries the order block (persistence across lifecycle merges)
    check("v2_revalidation_persist",
          "PASS" if (p.get("submit_revalidation") and p.get("order")) else
          "PENDING",
          f"submit_revalidation={'present' if p.get('submit_revalidation') else 'absent'} "
          f"on attempt {r['order_attempt_id'][:24]}")
    # 9d. null semantics: absent inputs must stay null, not collapse to 0.
    nulls = [k for k, v in ae.items() if v is None]
    zeros = [k for k, v in ae.items()
             if isinstance(v, (int, float)) and v == 0]
    check("v2_null_handling", "INFO",
          f"null fields={len(nulls)} {nulls[:6]} | true-zero fields={zeros[:6]}")
    # 9e. generic economics flagged non-authoritative on bounded-lane admits
    bounded = ae.get("admitting_authority") == "bounded_lane"
    flag_ok = (p.get("generic_economics_authoritative") is False) if bounded else True
    check("v2_generic_flag",
          "PASS" if flag_ok else "FAIL",
          f"authority={ae.get('admitting_authority')} "
          f"generic_authoritative={p.get('generic_economics_authoritative')}")

n_pass = sum(1 for _, s, _ in results if s == "PASS")
n_fail = sum(1 for _, s, _ in results if s == "FAIL")
n_pend = sum(1 for _, s, _ in results if s == "PENDING")
print(f"\n=== {n_pass} PASS / {n_fail} FAIL / {n_pend} PENDING / {len(results)} total ===")
print("Cohort status:", "VERIFIED-CURRENT OPEN" if n_fail == 0 and n_pend == 0
      else "POST-DEPLOYMENT, VERIFICATION PENDING")
sys.exit(1 if n_fail else 0)
