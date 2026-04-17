"""Triage silent except:pass blocks into SAFE vs DANGEROUS categories."""
import json
import os
import re

with open(os.path.join("data", "audit_sweep_results.json")) as f:
    data = json.load(f)

safe_patterns = [
    "CancelledError",
    "QueueEmpty",
    "QueueFull",
    "ImportError",
    "ModuleNotFoundError",
    "ConnectionError",
    "RuntimeError",   # ws.close() cleanup
    "AttributeError",  # optional attr
]

dangerous = []
safe = []

for item in data.get("SILENT_EXCEPT_PASS", []):
    detail = item.get("detail", "")
    fp = item["file"]
    line = item["line"]
    
    # Check if the except clause catches a safe pattern
    is_safe = any(pat in detail for pat in safe_patterns)
    
    # Also check: Exception classes that act as sentinels (empty exception subclass)
    if "class " in detail and "(Exception)" in detail:
        is_safe = True
    if "(ExecutionError)" in detail or "(Exception):" in detail:
        is_safe = True
    
    if is_safe:
        safe.append(item)
    else:
        dangerous.append(item)

print(f"=== SAFE (acceptable patterns): {len(safe)} ===")
print(f"=== DANGEROUS (needs logging): {len(dangerous)} ===\n")

for item in dangerous:
    fp = item["file"]
    line = item["line"]
    detail = item.get("detail", "")
    print(f"  {fp}:{line}  {detail[:100]}")
