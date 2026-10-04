"""Stop-to-settlement counterfactual.

For every protective exit that executed (fills with entry_or_exit='exit'
from stop_candidate) and every residual decision recorded after a
non-executable stop, compare the realized/simulated exit value against the
binary settlement value of holding.

    saved_cents = exit_proceeds - hold_value      (per contract, held side)

Positive = the exit beat holding.  Ex-post scoring of an ex-ante decision:
aggregate over many events, segment by trigger / asset / TTE before acting.

Usage:
    .\\.venv\\Scripts\\python.exe scripts\\stop_settlement_counterfactual.py [since_iso]
"""
import collections
import json
import sqlite3
import sys

since = sys.argv[1] if len(sys.argv) > 1 else "2026-09-01T00:00:00"

outcomes = {}
for line in open("logs/settlement_outcomes.jsonl", "r", errors="replace"):
    try:
        d = json.loads(line)
    except Exception:
        continue
    if d.get("event_type") == "settlement_outcome" and d.get("ticker") and d.get("outcome"):
        outcomes[d["ticker"]] = str(d["outcome"]).lower()

print("== Executed protective exits ==")
c = sqlite3.connect("file:data/kalshi_fills.db?mode=ro", uri=True, timeout=5)
cols = [r[1] for r in c.execute("pragma table_info(kalshi_fills)")]
rows = [dict(zip(cols, r)) for r in c.execute(
    "select * from kalshi_fills where created_time >= ? order by created_time", (since,))]
by_agg = collections.defaultdict(lambda: [0, 0.0])
for d in rows:
    if d.get("entry_or_exit") != "exit":
        continue
    tk = d["market_ticker"]
    side, act = str(d["side"]).lower(), str(d["action"]).lower()
    yp = round(float(d["yes_price_dollars"]) * 100)
    # An exit SELL of side X closes a long X position.
    held = side if act == "sell" else ("no" if side == "yes" else "yes")
    proceeds = yp if held == "yes" else 100 - yp
    out = outcomes.get(tk)
    if out is None:
        print(f"{d['created_time'][:19]} {tk} held={held} exit@{proceeds}c  (unsettled)")
        continue
    hold = 100 if out == held else 0
    saved = proceeds - hold
    agent = d.get("agent_id") or "?"
    by_agg[agent][0] += 1
    by_agg[agent][1] += saved
    print(f"{d['created_time'][:19]} {tk} held={held} exit@{proceeds}c hold_value={hold}c "
          f"settled={out} saved={saved:+d}c agent={agent}")
for agent, (n, s) in by_agg.items():
    print(f"  {agent}: n={n} total_saved={s:+.0f}c avg={s / n:+.1f}c")

print("\n== Residual decisions (post non-executable stop) ==")
agg = collections.defaultdict(lambda: [0, 0.0, 0])
for line in open("logs/stop_candidates.jsonl", "r", errors="replace"):
    try:
        d = json.loads(line)
    except Exception:
        continue
    if d.get("record_type") != "residual_decision":
        continue
    tk = d.get("ticker")
    out = outcomes.get(tk)
    vwap = d.get("degraded_limit_cents") or d.get("degraded_vwap_cents")
    held = "yes" if "yes" in str(d.get("residual_id", "")).split(":")[1:2] else "no"
    dec = d.get("decision")
    if out is None or vwap is None:
        agg[(dec, "unsettled")][0] += 1
        continue
    hold = 100 if out == held else 0
    # Value of the exit the policy approved (or would have) vs holding.
    exit_minus_hold = vwap - hold
    key = (dec, d.get("basis"))
    a = agg[key]
    a[0] += 1
    a[1] += exit_minus_hold
    a[2] += exit_minus_hold > 0
for (dec, basis), (n, s, good) in sorted(agg.items(), key=lambda kv: -kv[1][0]):
    if basis == "unsettled":
        print(f"  {dec:<38} unsettled n={n}")
        continue
    print(f"  {dec:<38} {str(basis):<44} n={n:3d} exit-hold avg={s / n:+6.1f}c exit_better={good}/{n}")
print(
    "\nRead: for DEGRADED_EXIT_APPROVED, positive exit-hold supports enabling "
    "live degraded exits; for HOLD_TO_SETTLEMENT_APPROVED, negative exit-hold "
    "means holding was right.  DATA_UNAVAILABLE rows measure how often the "
    "policy could not decide at all."
)
