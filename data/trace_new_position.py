import re

log_path = "C:/Dev/MERID/server_output.log"
out_path = "C:/Dev/MERID/data/trace_new_position_output.txt"

ticker = "KXBTC15M-26AUG112330-30"
patterns = [
    re.compile(re.escape(ticker)),
    re.compile(r"WS_ORDERBOOK_SNAPSHOT_BOOTSTRAP"),
    re.compile(r"POSITION-MONITOR-AUDIT"),
    re.compile(r"data_source"),
    re.compile(r"add_position|on_fill|sync_from_rest"),
]

with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
    lines = f.readlines()

matches = []
for i, line in enumerate(lines, 1):
    if any(p.search(line) for p in patterns):
        matches.append((i, line))

with open(out_path, "w", encoding="utf-8") as out:
    out.write(f"=== Tracing {ticker} and WS_ORDERBOOK_SNAPSHOT_BOOTSTRAP ===\n")
    for i, line in matches:
        out.write(f"{i}: {line}")

print(f"Wrote {len(matches)} lines to {out_path}")
