"""Scan frontend for all API calls."""
import re
import os

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
    print(f"{url} | {', '.join(sources)}")
