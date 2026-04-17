"""End-to-end wiring audit: probe every endpoint used by the frontend."""
import requests, json, re, sys, time

BASE = "http://localhost:8011"
TIMEOUT = 15

# Extract all endpoint paths from constants.ts
constants_file = r"c:\Dev\MERID\web\react\src\config\constants.ts"
with open(constants_file, "r") as f:
    text = f.read()

# Find all string values that look like API paths
paths = re.findall(r'"(/api/[^"]+)"', text)
# Also find function-style endpoints like KALSHI_SENTIMENT_BUNDLE: (asset) => `/api/.../${asset}`
func_paths = re.findall(r'`(/api/[^`]+)`', text)
for fp in func_paths:
    # Replace ${...} with a test value
    resolved = re.sub(r'\$\{[^}]+\}', 'BTC', fp)
    paths.append(resolved)

# Deduplicate and sort
paths = sorted(set(paths))

ok = 0
empty = 0
fail = 0
errors = []

for path in paths:
    try:
        r = requests.get(f"{BASE}{path}", timeout=TIMEOUT)
        if r.status_code == 200:
            try:
                data = r.json()
                # Check if data is meaningfully populated
                is_empty = False
                if isinstance(data, dict):
                    # Check for empty lists/dicts as values
                    vals = list(data.values())
                    if all(v in ([], {}, 0, 0.0, None, "", False) for v in vals):
                        is_empty = True
                elif isinstance(data, list) and len(data) == 0:
                    is_empty = True
                
                if is_empty:
                    print(f"  [EMPTY   ] {r.status_code}  {path}")
                    empty += 1
                else:
                    print(f"  [OK      ] {r.status_code}  {path}")
                    ok += 1
            except:
                print(f"  [OK      ] {r.status_code}  {path}")
                ok += 1
        elif r.status_code == 405:
            # POST-only endpoint, skip
            print(f"  [POST    ] {r.status_code}  {path}")
        elif r.status_code == 404:
            print(f"  [404     ] {r.status_code}  {path}")
            errors.append((path, 404, "Not Found"))
            fail += 1
        elif r.status_code == 422:
            print(f"  [422     ] {r.status_code}  {path}  (missing required params)")
        else:
            print(f"  [ERR     ] {r.status_code}  {path}")
            errors.append((path, r.status_code, r.text[:100]))
            fail += 1
    except requests.exceptions.Timeout:
        print(f"  [TIMEOUT ] ---  {path}")
        errors.append((path, 0, "Timeout"))
        fail += 1
    except requests.exceptions.ConnectionError:
        print(f"  [CONNFAIL] ---  {path}")
        errors.append((path, 0, "Connection refused"))
        fail += 1

print(f"\n{'='*60}")
print(f"Total: {len(paths)} endpoints")
print(f"  OK: {ok} | EMPTY: {empty} | FAIL: {fail}")
if errors:
    print(f"\nFailed endpoints:")
    for path, code, msg in errors:
        print(f"  {code:>3d}  {path}  — {msg}")
