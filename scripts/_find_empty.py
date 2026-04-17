"""Find all empty endpoints from the frontend constants."""
import requests, re, json

BASE = "http://localhost:8011"
constants_file = r"c:\Dev\MERID\web\react\src\config\constants.ts"
with open(constants_file) as f:
    text = f.read()

paths = re.findall(r'"(/api/[^"]+)"', text)
func_paths = re.findall(r'`(/api/[^`]+)`', text)
for fp in func_paths:
    resolved = re.sub(r'\$\{[^}]+\}', 'BTC', fp)
    paths.append(resolved)
paths = sorted(set(paths))

empty = []
for path in paths:
    try:
        r = requests.get(f"{BASE}{path}", timeout=15)
        if r.status_code == 200:
            data = r.json()
            is_empty = False
            if isinstance(data, dict):
                vals = list(data.values())
                if all(v in ([], {}, 0, 0.0, None, "", False) for v in vals):
                    is_empty = True
            elif isinstance(data, list) and len(data) == 0:
                is_empty = True
            if is_empty:
                empty.append((path, data))
    except:
        pass

print(f"Found {len(empty)} empty endpoints:\n")
for path, data in empty:
    print(f"  {path}")
    print(f"    -> {json.dumps(data)[:300]}")
    print()
