"""Scan frontend for all API calls and backend for all registered routes."""
import re
import os

print("FRONTEND API CALLS")
print("-" * 60)

api_calls = {}
for root, dirs, files in os.walk('web/react/src'):
    for f in files:
        if f.endswith(('.ts', '.tsx')):
            path = os.path.join(root, f)
            with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
                content = fh.read()
                for m in re.finditer(r"fetch\(['\"`](/[^'\"`\s]+)", content):
                    url = m.group(1)
                    api_calls.setdefault(url, []).append(f)
                for m in re.finditer(r"fetchJSON[^(]*\(['\"`](/[^'\"`\s]+)", content):
                    url = m.group(1)
                    api_calls.setdefault(url, []).append(f)

for url in sorted(api_calls.keys()):
    sources = sorted(set(api_calls[url]))
    print(f"  {url}  <-- {', '.join(sources)}")

print()
print("BACKEND ROUTES")
print("-" * 60)

for root, dirs, files in os.walk('web/api'):
    for f in sorted(files):
        if not f.endswith('.py') or f.startswith('__'):
            continue
        path = os.path.join(root, f)
        with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
            content = fh.read()
        prefix_match = re.search(r"APIRouter\(prefix=['\"]([^'\"]+)", content)
        prefix = prefix_match.group(1) if prefix_match else ''
        routes = re.findall(r"@\w+\.(get|post|put|delete|patch|websocket)\(['\"]([^'\"]*)", content)
        if routes:
            for method, route in routes:
                full = prefix + route
                print(f"  {method.upper():8s} {full}  ({f})")
