import os
import sys
import time
import re
import threading
import datetime

FILES = [
    ("full", r"C:\Dev\MERID\logs\full.log"),
    ("server_output", r"C:\Dev\MERID\server_output.log"),
    ("order_decisions", r"C:\Dev\MERID\logs\order_decisions.jsonl"),
    ("decision_telemetry", r"C:\Dev\MERID\logs\decision_telemetry.jsonl"),
    ("rejections", r"C:\Dev\MERID\data\rejections\rejections_2026-08-27.jsonl"),
    ("hybrid_model", r"C:\Dev\MERID\data\logs\hybrid_model_decomposition.jsonl"),
    ("shadow_telemetry", r"C:\Dev\MERID\data\logs\shadow_side_telemetry.jsonl"),
    ("settlement", r"C:\Dev\MERID\logs\settlement_outcomes.jsonl"),
]

OUT = r"C:\Dev\MERID\logs\live_tail_30min.log"
DURATION = 30 * 60
LINE_MAX = 2000

PATTERNS = [
    r"ERROR", r"WARNING", r"CRITICAL", r"FATAL", r"EXCEPTION",
    r"reconcil", r"reconciliation_halted",
    r"firewall",
    r"\bloss\b", r"pnl", r"realized_pnl", r"unrealized_pnl", r"net_pnl",
    r"reject", r"rejected", r"reject_reason",
    r"fail", r"failed", r"failure", r"timeout",
    r"halt", r"halted",
    r"bracket",
    r"stop.?loss", r"STOP.?LOSS",
    r"exit_guard", r"EXIT_EVAL",
    r"PRICE-FILTER-REJECT", r"SIGNAL-GENERATION-REJECT", r"both_sides_out_of_canonical_range",
    r"NO_TRIGGER", r"EXIT_TARGET_NOT_REACHED", r"profit_exit_not_profitable", r"stale_quote",
    r"submission_unknown", r"duplicate_fill", r"UNMATCHED_FILL",
    r"cfb_rti_unavailable", r"cfb_rti_stale", r"final_minute",
    r"INSUFFICIENT_BALANCE", r"RATE_LIMIT", r"HTTPError",
    r"BANKROLL", r"BALANCE-CALIBRATOR", r"Bankroll is None",
    r"ENTRY_DISABLED", r"ENTRY-READINESS", r"global_allow", r"allow_new_entries", r"infra_ready",
    r"position_qty", r"trade_decision",
    r"settlement_guard", r"expiry_liquidation", r"time_exit",
]

compiled = re.compile("|".join(PATTERNS), re.IGNORECASE)


def tail_file(path, label, out, stop):
    f = open(path, "r", encoding="utf-8", errors="replace")
    f.seek(0, 2)
    while not stop.is_set():
        line = f.readline()
        if line:
            if compiled.search(line):
                now = datetime.datetime.utcnow().isoformat()
                payload = line.rstrip()
                if len(payload) > LINE_MAX:
                    payload = payload[:LINE_MAX] + " ...[truncated]"
                out.write(f"{now}Z [{label}] {payload}\n")
                out.flush()
        else:
            time.sleep(0.3)
    f.close()


def main():
    out = open(OUT, "a", encoding="utf-8", errors="replace")
    stop = threading.Event()
    start = time.time()
    out.write(f"# TAIL START {datetime.datetime.utcnow().isoformat()}Z\n")
    out.flush()

    threads = []
    for label, path in FILES:
        if not os.path.exists(path):
            out.write(f"# SKIP missing {path}\n")
            continue
        t = threading.Thread(target=tail_file, args=(path, label, out, stop), daemon=True)
        t.start()
        threads.append(t)

    try:
        while time.time() - start < DURATION and any(t.is_alive() for t in threads):
            time.sleep(1)
    except KeyboardInterrupt:
        pass

    stop.set()
    for t in threads:
        t.join(timeout=5)

    out.write(f"# TAIL END {datetime.datetime.utcnow().isoformat()}Z\n")
    out.flush()
    out.close()


if __name__ == "__main__":
    main()
