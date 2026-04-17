#!/usr/bin/env python3
"""Generate endpoints.json contract from the frontend API_ENDPOINTS constants.

Parses web/react/src/config/constants.ts and emits a JSON list of
{method, path} pairs that the frontend expects the backend to serve.

Usage:
    python scripts/generate_endpoints_contract.py

Output:
    web/api/generated/endpoints.json
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CONSTANTS_TS = REPO / "web" / "react" / "src" / "config" / "constants.ts"
OUTPUT = REPO / "web" / "api" / "generated" / "endpoints.json"

# ── Method inference heuristics ─────────────────────────────────────────
# Keys whose name implies a non-GET method.
_POST_HINTS = {
    "REFRESH", "START", "STOP", "PAUSE", "RESUME", "RESET", "TRIGGER",
    "TOGGLE", "SEED", "SYNC", "EXPORT", "SEND", "POST", "PROMOTE",
    "ROLLBACK", "HALT", "DOWNSIZE", "PLACE", "CANARY", "REPORT",
    "RELOAD", "EMERGENCY", "STOP", "KILL", "UNKILL", "SHUTDOWN",
    "RUN", "CLEAR", "READ_ALL",
}
_DELETE_HINTS = {"CANCEL", "DELETE"}
_PUT_HINTS = {"AMEND", "SETTINGS", "UPDATE", "LIMIT"}


def _infer_method(key: str) -> str:
    """Best-effort HTTP method from the constant name."""
    parts = set(key.upper().split("_"))
    if parts & _DELETE_HINTS:
        return "DELETE"
    if parts & _PUT_HINTS:
        return "PUT"
    if parts & _POST_HINTS:
        return "POST"
    # Special cases
    if key.endswith("_TOGGLE"):
        return "POST"
    if key.endswith("_CREATE"):
        return "POST"
    if "BATCH_CANCEL" in key:
        return "DELETE"
    return "GET"


# ── Overrides for keys where the heuristic is wrong ────────────────────
_METHOD_OVERRIDES: dict[str, str] = {
    # /categories is both GET and PUT — the GET is the default, PUT uses
    # a separate call in the UI; we record the GET here, the PUT is
    # covered by the constant being used with PUT in KillSwitchView.
    "KALSHI_GRID_MODE": "GET",       # Also POST, but GET is the primary read
    "KALSHI_ORDERS_BATCH_CANCEL": "DELETE",
    "KALSHI_ORDER_CANCEL": "DELETE",
    "KALSHI_ORDER_AMEND": "PATCH",
    "RISK_KILL_SWITCH_DELETE": "DELETE",
    # SSE streams treated as GET
    "KALSHI_ORDERBOOK_STREAM": "GET",
    "KALSHI_ORDER_GROUP_STREAM": "GET",
    # Method corrections from CI contract test run
    "KALSHI_EXPORT": "GET",                    # GET endpoint, not POST
    "KALSHI_METRICS_RESOLVE_ALL": "POST",       # POST action, not GET
    "KALSHI_ORDER_GROUP_RESET": "PUT",          # PUT, not POST
    "KALSHI_ORDER_GROUP_TRIGGER": "PUT",        # PUT, not POST
    "KALSHI_BATCH_ORDERS": "POST",              # POST to submit batch
    "LOOP_EXECUTION_TOGGLE": "GET",             # GET with query param
    "NOTIFICATIONS_READ_ALL": "POST",           # POST action
    "NOTIFICATION_READ": "POST",                # POST action
    "OPERATOR_KILL_SWITCH_STATUS": "GET",       # GET status, not POST
    "TRADING_MODE_SET": "POST",                 # POST to set mode
    "PM_ALERT_ACKNOWLEDGE": "POST",             # POST action
    "REPLAY_COMPARE": "POST",                   # POST with body
    "REPLAY_QUICK_COMPARE": "POST",             # POST with body
    "AUTH_REFRESH": "POST",                     # POST to refresh token
    # Second-pass corrections
    "RISK_ALERTS_ACKNOWLEDGE_ALL": "POST",      # POST action
    "RISK_ALERT_ACKNOWLEDGE": "POST",           # POST action
    "RISK_HALT_STATUS": "GET",                  # GET status, not POST
    "SYSTEM_FRESH_START": "GET",                # GET, not POST
    "TELEMETRY": "POST",                        # POST telemetry data
    "RISK_DOWNSIZE_ALL": "POST",                # POST action
    "RISK_KILL_SWITCH_DELETE": "DELETE",         # DELETE
}

# ── Paths that are dual-method (both GET and mutation) ─────────────────
# We emit a second entry for these.
_DUAL_METHOD: dict[str, list[str]] = {
    "KALSHI_GRID_MODE": ["GET", "POST"],
    "KALSHI_CATEGORIES": ["GET", "PUT"],
}

# ── Whitelist of known "UI-only" or alias entries to skip ──────────────
_SKIP_KEYS: set[str] = {
    # Aliases that resolve to the same {method, path} as another key
    "OPERATOR_ORDERS",           # alias of KALSHI_ORDERS
    "RISK_PROTECTIONS",          # alias of OPERATOR_RISK_STATE
    "RISK_CIRCUIT_BREAKER_RESET",  # alias of OPERATOR_RESET_KILL_SWITCH
    "KALSHI_GRID_CRYPTO_PAPER_VS_SHADOW",  # stub — same path as CRYPTO_EDGE
    # RISK_KILL_SWITCH is a function, not a static path — dual paths
    # handled by GUARD_KILL and GUARD_UNKILL constants
    "RISK_KILL_SWITCH",
}


def _normalize_path(raw: str) -> str:
    """Convert TS template-literal paths to OpenAPI-style {param} paths.

    Examples:
        /api/v1/kalshi/markets/${ticker}  →  /api/v1/kalshi/markets/{ticker}
        /api/v1/kalshi/orders/${orderId}  →  /api/v1/kalshi/orders/{orderId}
    """
    return re.sub(r"\$\{(\w+)\}", r"{\1}", raw)


def parse_constants() -> list[dict[str, str]]:
    """Parse API_ENDPOINTS from constants.ts → [{method, path, key}]."""
    src = CONSTANTS_TS.read_text(encoding="utf-8")

    # Extract the block between `export const API_ENDPOINTS = {` and `} as const;`
    m = re.search(
        r"export\s+const\s+API_ENDPOINTS\s*=\s*\{(.*?)\}\s*as\s+const",
        src,
        re.DOTALL,
    )
    if not m:
        raise RuntimeError("Could not find API_ENDPOINTS block in constants.ts")

    block = m.group(1)
    entries: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    # Pattern 1: static string — `KEY: "/path/here",`
    for km in re.finditer(r'(\w+)\s*:\s*"(/[^"]+)"', block):
        key, path = km.group(1), km.group(2)
        if key in _SKIP_KEYS:
            continue
        path = _normalize_path(path)
        methods = _DUAL_METHOD.get(key, [_METHOD_OVERRIDES.get(key, _infer_method(key))])
        for method in methods:
            pair = (method, path)
            if pair not in seen:
                seen.add(pair)
                entries.append({"method": method, "path": path, "key": key})

    # Pattern 2: arrow-function — `KEY: (param) => `/path/${param}``
    for km in re.finditer(r"(\w+)\s*:\s*\([^)]*\)\s*=>\s*`(/[^`]+)`", block):
        key, path_tmpl = km.group(1), km.group(2)
        if key in _SKIP_KEYS:
            continue
        path = _normalize_path(path_tmpl)
        methods = _DUAL_METHOD.get(key, [_METHOD_OVERRIDES.get(key, _infer_method(key))])
        for method in methods:
            pair = (method, path)
            if pair not in seen:
                seen.add(pair)
                entries.append({"method": method, "path": path, "key": key})

    entries.sort(key=lambda e: (e["path"], e["method"]))
    return entries


def main() -> None:
    entries = parse_constants()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    print(f"OK  Wrote {len(entries)} endpoint entries -> {OUTPUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
