"""Deep audit: probe ALL API endpoints for stubs, hardcoded data, NaN, empty, missing attrs."""
import requests, json, sys, re, math

BASE = "http://localhost:8011"

# Get all registered routes from the frontend constants
ENDPOINTS = []
try:
    with open(r"c:\Dev\MERID\web\react\src\config\constants.ts", encoding="utf-8") as f:
        for line in f:
            m = re.search(r"['\"](/api/[^'\"]+)['\"]", line)
            if m:
                path = m.group(1)
                if "${" not in path and "{" not in path:
                    ENDPOINTS.append(path)
except Exception:
    pass

# Add known non-prefixed routes
ENDPOINTS.extend([
    "/debates/alerts", "/debates/correlation", "/debates/historical",
    "/debates/rollups",
])
ENDPOINTS = sorted(set(ENDPOINTS))

ISSUES = []

def check_value(path, key, val, depth=0):
    """Recursively check a value for problems."""
    prefix = f"{path} -> {key}" if key else path
    
    # NaN / Infinity
    if isinstance(val, float):
        if math.isnan(val):
            ISSUES.append(("NaN", prefix, f"NaN float value"))
        elif math.isinf(val):
            ISSUES.append(("Infinity", prefix, f"Infinite float value"))
    
    # None where data expected
    if val is None and key and key not in ("error", "detail", "message", "_stub_message"):
        # Only flag if key suggests it should have data
        if any(k in str(key).lower() for k in ("price", "score", "count", "total", "pnl", "rate", "value")):
            ISSUES.append(("None", prefix, f"None value for data field"))
    
    # Stub markers
    if isinstance(val, bool) and val and key in ("_stub", "stub"):
        ISSUES.append(("STUB", prefix, "Stub marker is True"))
    if isinstance(val, str) and val == "NOT_IMPLEMENTED":
        ISSUES.append(("NOT_IMPL", prefix, "NOT_IMPLEMENTED status"))
    if isinstance(val, str) and key == "data_mode" and val == "offline":
        ISSUES.append(("OFFLINE", prefix, "data_mode is offline"))
    
    # Hardcoded crypto names in Kalshi-only mode
    if isinstance(val, str) and key in ("symbol", "venue") and val in ("Kraken", "Coinbase", "Binance"):
        ISSUES.append(("HARDCODED", prefix, f"Hardcoded crypto venue: {val}"))
    if isinstance(val, str) and key == "symbol" and val in ("BTC-USD", "ETH-USD", "SOL-USD"):
        ISSUES.append(("HARDCODED", prefix, f"Hardcoded crypto pair: {val}"))
    
    # Empty strings where data expected
    if isinstance(val, str) and val == "" and key and key not in ("error", "detail", "message", "charter", "reasoning", "_stub_message"):
        if any(k in str(key).lower() for k in ("name", "id", "symbol", "ticker", "agent")):
            ISSUES.append(("EMPTY_STR", prefix, f"Empty string for '{key}'"))
    
    # Recurse
    if isinstance(val, dict) and depth < 3:
        for k, v in val.items():
            check_value(path, f"{key}.{k}" if key else k, v, depth+1)
    elif isinstance(val, list) and depth < 3 and len(val) > 0:
        check_value(path, f"{key}[0]" if key else "[0]", val[0], depth+1)


empty_count = 0
stub_count = 0
error_count = 0
ok_count = 0

for path in ENDPOINTS:
    try:
        idx = ENDPOINTS.index(path)+1
        print(f"  [{idx}/{len(ENDPOINTS)}] {path}", end="", flush=True)
        r = requests.get(f"{BASE}{path}", timeout=10)
        if r.status_code != 200:
            error_count += 1
            ISSUES.append(("HTTP_ERR", path, f"HTTP {r.status_code}"))
            print(f" -> HTTP {r.status_code}")
            continue
        
        try:
            data = r.json()
        except Exception:
            ISSUES.append(("BAD_JSON", path, f"Non-JSON response"))
            continue
        
        # Check for empty
        is_empty = False
        if isinstance(data, list) and len(data) == 0:
            is_empty = True
        elif isinstance(data, dict):
            for key in ("items", "data", "results", "agents", "rows", "debates", "opinions", "events", "alerts", "verdicts", "decisions", "orders", "positions", "fills", "critiques", "signals", "symbols", "teams", "messages", "feeds"):
                val = data.get(key)
                if val is not None and (val == [] or val == {}):
                    is_empty = True
                    ISSUES.append(("EMPTY", path, f"'{key}' is empty"))
                    break
            # All-zero dict
            if not is_empty:
                non_meta = {k: v for k, v in data.items() if not k.startswith("_")}
                if non_meta and all(v in (0, 0.0, None, "", False, [], {}) for v in non_meta.values()):
                    is_empty = True
                    ISSUES.append(("ALL_ZERO", path, f"All values are zero/empty/false"))
        
        if is_empty:
            empty_count += 1
        
        # Deep check
        check_value(path, "", data)
        
        # Check for stub
        if isinstance(data, dict) and data.get("_stub"):
            stub_count += 1
            print(" STUB")
        elif isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict) and data[0].get("_stub"):
            stub_count += 1
            print(" STUB")
        else:
            ok_count += 1
            tag = "EMPTY" if is_empty else "OK"
            print(f" {tag}")
        
    except requests.exceptions.Timeout:
        ISSUES.append(("TIMEOUT", path, "Request timed out (10s)"))
        error_count += 1
        print(" TIMEOUT")
    except Exception as exc:
        ISSUES.append(("EXCEPTION", path, str(exc)))
        error_count += 1
        print(f" ERR: {exc}")

# Print results
print(f"\n{'='*80}")
print(f"DEEP AUDIT RESULTS: {len(ENDPOINTS)} endpoints probed")
print(f"  OK: {ok_count}  |  EMPTY: {empty_count}  |  STUB: {stub_count}  |  ERROR: {error_count}")
print(f"  Total issues found: {len(ISSUES)}")
print(f"{'='*80}\n")

# Group by type
from collections import defaultdict
by_type = defaultdict(list)
for typ, path, msg in ISSUES:
    by_type[typ].append((path, msg))

for typ in sorted(by_type.keys()):
    items = by_type[typ]
    print(f"\n[{typ}] ({len(items)} issues)")
    for path, msg in items[:30]:
        print(f"  {path}: {msg}")
    if len(items) > 30:
        print(f"  ... and {len(items)-30} more")
