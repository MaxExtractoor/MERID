"""Execution-stage latency instrumentation test.

Drives the real ``_emit_execution_stage_latency`` with a synthetic mark
set and asserts the required stage metrics are computed, UTC correlation
fields present (never subtracted into durations), and the rolling
distribution reports p50/p90/p99/max.
"""
import json
import logging
import sys
import time as _time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from merid.event_venues.kalshi.order_router import (            # noqa: E402
    OrderIntent, _emit_execution_stage_latency, _exec_delta_ms,
)
from merid.observability.latency_distribution import (          # noqa: E402
    latency_snapshot, record_metric, _reset_for_tests,
)

PASS = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name} {detail}")
    PASS.append((name, cond))


print("== stage-latency emitter fields ==")
captured = []


class _H(logging.Handler):
    def emit(self, rec):
        captured.append(rec.getMessage())


logging.getLogger("merid.event_venues.kalshi.order_router").addHandler(_H())
logging.getLogger("merid.event_venues.kalshi.order_router").setLevel(
    logging.INFO)

now = _time.monotonic_ns()
ms = 1_000_000
intent = OrderIntent(ticker="KXBTC15M-LAT-30", price_cents=45,
                     count=2.0, side="yes", action="buy",
                     intent_id="lat_i", client_order_id="lat_c")
intent.exec_stage_marks_ns.update({
    "eval_end": now,
    "router_entry": now + 100 * ms,
    "router_dequeue": now + 350 * ms,
    "submit_revalidation_start": now + 400 * ms,
    "submit_revalidation_end": now + 415 * ms,
    "exit_intent_created": now - 500 * ms,
    "api_send": now + 700 * ms,
    "api_ack": now + 950 * ms,
})
intent._submit_prob_age_ms = 1800
intent._submit_book_age_ms = 250
intent._api_send_utc = 1760000000.0
intent._api_ack_utc = 1760000000.25


class _R:
    status = "submitted"
    reason = "ok"


_emit_execution_stage_latency(intent, _R())
row = None
for m in captured:
    if "EXECUTION-STAGE-LATENCY" in m:
        row = json.loads(m.split("EXECUTION-STAGE-LATENCY ", 1)[1])
check("emitted", row is not None)
if row:
    check("eval_to_submit_ms=700", row.get("eval_to_submit_ms") == 700,
          str(row.get("eval_to_submit_ms")))
    check("queue_wait_ms=250", row.get("queue_wait_ms") == 250,
          str(row.get("queue_wait_ms")))
    check("submit_revalidation_ms=15",
          row.get("submit_revalidation_ms") == 15,
          str(row.get("submit_revalidation_ms")))
    check("prob_age_at_submit_ms=1800",
          row.get("prob_age_at_submit_ms") == 1800)
    check("book_age_at_submit_ms=250",
          row.get("book_age_at_submit_ms") == 250)
    check("exit_intent_to_send_ms=1200",
          row.get("exit_intent_to_send_ms") == 1200,
          str(row.get("exit_intent_to_send_ms")))
    check("send_to_ack_ms=250", row.get("send_to_ack_ms") == 250)
    check("utc correlation fields present",
          row.get("send_utc") == 1760000000.0
          and row.get("ack_utc") == 1760000000.25)

print("== rolling distribution ==")
_reset_for_tests()
for v in [10, 20, 30, 40, 50, 60, 70, 80, 90, 1000]:
    record_metric("test.metric", v)
record_metric("test.metric", None)
record_metric("test.metric", -5)
snap = latency_snapshot()
m = snap.get("test.metric")
check("distribution exists", m is not None)
check("count excludes invalid", m["count"] == 10, str(m["count"]))
check("p50 sane", 45 <= m["p50_ms"] <= 60, str(m["p50_ms"]))
check("p90 > p50", m["p90_ms"] > m["p50_ms"], str(m["p90_ms"]))
check("p99 >= p90", m["p99_ms"] >= m["p90_ms"])
check("max=1000", m["max_ms"] == 1000)

fails = [n for n, ok in PASS if not ok]
print(f"\nEXEC-LATENCY: {len(PASS) - len(fails)}/{len(PASS)} passed")
if fails:
    print("FAILURES:", fails)
sys.exit(0 if not fails else 1)

