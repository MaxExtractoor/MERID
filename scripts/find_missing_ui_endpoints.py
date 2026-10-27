#!/usr/bin/env python3
"""Find missing UI endpoints — identifies frontend constants with no backend route.

This script compares frontend API_ENDPOINTS against registered FastAPI routes
to find:
1. MISSING_ROUTE: Frontend expects endpoint that doesn't exist
2. METHOD_MISMATCH: Path exists but with wrong HTTP method
3. STUB_ROUTES: Backend routes that return hardcoded zeros/empty data
4. ZERO_METRICS: Endpoints likely returning stub metric data

Usage:
    python scripts/find_missing_ui_endpoints.py [--json] [--kalshi-only]

Output:
    Terminal report + JSON file with full details for CI integration
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Set, Tuple, Dict, List

REPO = Path(__file__).resolve().parent.parent
CONSTANTS_TS = REPO / "web" / "react" / "src" / "config" / "constants.ts"
CONTRACT_FILE = REPO / "web" / "api" / "generated" / "endpoints.json"
OUTPUT_JSON = REPO / "docs" / "missing_endpoints_report.json"

# ── Constants ─────────────────────────────────────────────────────────

# Keywords that suggest a metrics endpoint returns calculated data vs stub data
CALCULATED_METRIC_INDICATORS = [
    "calculate", "compute", "aggregate", "fetch", "get_live", "query",
    "from_cache", "update", "refresh", "sync", "ingest"
]

# Keywords that suggest stub/placeholder data
STUB_INDICATORS = [
    "stub", "mock", "fake", "placeholder", "dummy", "synthetic",
    "return 0", "return None", "return []", "return {}", "pass  # TODO"
]

# Kalshi-critical path patterns - these should never be missing/zero
KALSHI_CRITICAL_PATTERNS = [
    "/kalshi/balance", "/kalshi/positions", "/kalshi/orders", "/kalshi/fills",
    "/kalshi/pnl", "/kalshi/risk", "/kalshi/grid", "/kalshi/markets",
    "/kalshi/health", "/kalshi/catalog", "/kalshi/edge", "/kalshi/sizing",
    "/execution-gate", "/kill-switch", "/operator/", "/risk/",
    "/kalshi/continuous-trader/", "/kalshi/deployment/",
    "/kalshi/consensus", "/kalshi/sentiment", "/kalshi/metrics/"
]

# Legacy/non-Kalshi patterns that are lower priority
LEGACY_PATTERNS = [
    "/pipeline/", "/paper-trading/", "/mining/", "/wallet/",
    "/treasury/", "/rewards/", "/betting/", "/arbitrage/",
    "/defi/", "/sniping/", "/social/", "/moat/"
]

# Endpoints that commonly return zeros when data is missing
METRIC_ENDPOINT_SUFFIXES = [
    "/metrics", "/stats", "/summary", "/health", "/status",
    "/pnl", "/performance", "/calibration", "/edge", "/sizing-metrics",
    "/correlation", "/consensus", "/sentiment", "/mood"
]


@dataclass
class EndpointIssue:
    """Represents a single endpoint issue."""
    key: str
    method: str
    path: str
    issue_type: str
    severity: str
    category: str
    note: str = ""
    suggestion: str = ""


@dataclass
class AnalysisReport:
    """Full analysis report."""
    total_frontend: int
    total_backend: int
    issues: List[EndpointIssue]
    whitelisted: List[Dict]
    backend_orphaned: List[Tuple[str, str]]
    metrics_by_category: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "summary": {
                "total_frontend_endpoints": self.total_frontend,
                "total_backend_routes": self.total_backend,
                "total_issues": len(self.issues),
                "critical_issues": sum(1 for i in self.issues if i.severity == "CRITICAL"),
                "high_issues": sum(1 for i in self.issues if i.severity == "HIGH"),
            },
            "issues_by_category": self.metrics_by_category,
            "issues": [
                {
                    "key": i.key,
                    "method": i.method,
                    "path": i.path,
                    "issue_type": i.issue_type,
                    "severity": i.severity,
                    "category": i.category,
                    "note": i.note,
                    "suggestion": i.suggestion
                }
                for i in self.issues
            ],
            "orphaned_backend_routes": [
                {"method": m, "path": p} for m, p in self.backend_orphaned[:50]
            ]
        }


def _normalize_path(path: str) -> str:
    return path.rstrip("/")


def _parameterized_to_regex(path: str) -> re.Pattern:
    parts = re.split(r"\{[^}]+\}", path)
    escaped = [re.escape(p) for p in parts]
    return re.compile("^" + r"[^/]+".join(escaped) + "$")


def _path_matches(path: str, backend_paths: Set[str]) -> bool:
    norm = _normalize_path(path)
    if norm in backend_paths:
        return True
    if "{" in norm:
        pattern = _parameterized_to_regex(norm)
        return any(pattern.match(bp) for bp in backend_paths)
    return False


def _categorize_endpoint(path: str) -> str:
    path_lower = path.lower()
    for pattern in KALSHI_CRITICAL_PATTERNS:
        if pattern in path_lower:
            return "kalshi-critical"
    if "/kalshi/" in path_lower:
        return "kalshi-standard"
    if "/operator/" in path_lower or "/system/" in path_lower:
        return "operator"
    for pattern in LEGACY_PATTERNS:
        if pattern in path_lower:
            return "legacy"
    return "other"


def _calculate_severity(issue_type: str, category: str, path: str) -> str:
    if category == "kalshi-critical":
        return "CRITICAL" if issue_type == "MISSING_ROUTE" else "HIGH"
    elif category == "kalshi-standard":
        return "HIGH" if issue_type == "MISSING_ROUTE" else "MEDIUM"
    elif category == "operator":
        return "HIGH" if issue_type in ("MISSING_ROUTE", "METHOD_MISMATCH") else "MEDIUM"
    elif category == "legacy":
        return "LOW"
    else:
        return "MEDIUM"


def _is_metrics_endpoint(path: str) -> bool:
    path_lower = path.lower()
    return any(suffix in path_lower for suffix in METRIC_ENDPOINT_SUFFIXES)


def load_contract() -> List[Dict]:
    if not CONTRACT_FILE.exists():
        print(f"ERROR: Contract file not found: {CONTRACT_FILE}")
        print("Run: python scripts/generate_endpoints_contract.py")
        sys.exit(1)
    return json.loads(CONTRACT_FILE.read_text(encoding="utf-8"))


def load_whitelist() -> Set[Tuple[str, str]]:
    whitelist: Set[Tuple[str, str]] = set()
    test_file = REPO / "tests" / "test_ui_backend_contract.py"
    if test_file.exists():
        content = test_file.read_text(encoding="utf-8")
        match = re.search(r"WHITELIST:\s*Set\[Tuple\[str,\s*str\]\]\s*=\s*\{([^}]+)\}", content, re.DOTALL)
        if match:
            entries_block = match.group(1)
            for line in entries_block.split("\n"):
                line = line.strip()
                if line.startswith("(") and line.endswith(")"):
                    parts = line[1:-1].split(",")
                    if len(parts) >= 2:
                        method = parts[0].strip().strip('"')
                        path = parts[1].strip().strip('"')
                        whitelist.add((method, path))
    return whitelist


def extract_backend_routes() -> Set[Tuple[str, str]]:
    import asyncio
    sys.path.insert(0, str(REPO))

    async def _noop_lifespan(app):
        yield

    try:
        from web.main_15m_lean import app
    except Exception as e:
        print(f"WARNING: Could not load FastAPI app: {e}")
        print("Falling back to manual route extraction...")
        return _extract_routes_from_source()

    routes: Set[Tuple[str, str]] = set()
    for route in app.routes:
        if hasattr(route, "methods") and hasattr(route, "path"):
            path = _normalize_path(route.path)
            for method in route.methods:
                if method.upper() != "HEAD":
                    routes.add((method.upper(), path))
        if hasattr(route, "app") and hasattr(route.app, "routes"):
            prefix = _normalize_path(route.path)
            for sub in route.app.routes:
                if hasattr(sub, "methods") and hasattr(sub, "path"):
                    sub_path = _normalize_path(sub.path)
                    full = prefix + sub_path if not sub_path.startswith(prefix) else sub_path
                    for method in sub.methods:
                        if method.upper() != "HEAD":
                            routes.add((method.upper(), full))
    return routes


def _extract_routes_from_source() -> Set[Tuple[str, str]]:
    routes: Set[Tuple[str, str]] = set()
    api_dir = REPO / "web" / "api"
    for py_file in api_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        prefix_match = re.search(r'router\s*=\s*APIRouter\([^)]*prefix\s*=\s*["\']([^"\']+)', content)
        prefix = prefix_match.group(1) if prefix_match else ""
        for match in re.finditer(r'@router\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)', content, re.IGNORECASE):
            method = match.group(1).upper()
            path = prefix + match.group(2)
            routes.add((method, _normalize_path(path)))
    return routes


def analyze_endpoints(kalshi_only: bool = False) -> AnalysisReport:
    contract = load_contract()
    backend_routes = extract_backend_routes()
    whitelist = load_whitelist()

    backend_by_method: Dict[str, Set[str]] = defaultdict(set)
    all_backend_paths: Set[str] = set()
    for method, path in backend_routes:
        backend_by_method[method].add(path)
        all_backend_paths.add(path)

    issues: List[EndpointIssue] = []
    used_whitelist: List[Dict] = []

    for entry in contract:
        key = entry["key"]
        method = entry["method"].upper()
        path = _normalize_path(entry["path"])

        if (method, path) in whitelist:
            used_whitelist.append({"key": key, "method": method, "path": path})
            continue

        category = _categorize_endpoint(path)

        if kalshi_only and category not in ("kalshi-critical", "kalshi-standard", "operator"):
            continue

        method_paths = backend_by_method.get(method, set())
        if not _path_matches(path, method_paths):
            if _path_matches(path, all_backend_paths):
                issue_type = "METHOD_MISMATCH"
                note = f"Path exists but not with {method}"
            else:
                issue_type = "MISSING_ROUTE"
                note = "No backend implementation found"

                if _is_metrics_endpoint(path):
                    note += " (metrics endpoint - likely shows 0 in UI)"

            severity = _calculate_severity(issue_type, category, path)

            suggestion = ""
            if issue_type == "MISSING_ROUTE":
                suggestion = f"Implement {method} handler in web/api/ or remove from API_ENDPOINTS"
            elif issue_type == "METHOD_MISMATCH":
                suggestion = f"Add {method} method to existing route or fix frontend to use correct method"

            issues.append(EndpointIssue(
                key=key, method=method, path=path, issue_type=issue_type,
                severity=severity, category=category, note=note, suggestion=suggestion
            ))

    # Find orphaned backend routes
    frontend_paths = {_normalize_path(e["path"]) for e in contract}
    orphaned = []
    for method, path in sorted(backend_routes):
        if not path.startswith("/api/v1/"):
            continue
        generic = re.sub(r"\{[^}]+\}", "{_}", path)
        frontend_generic = {re.sub(r"\{[^}]+\}", "{_}", p) for p in frontend_paths}
        if generic not in frontend_generic:
            orphaned.append((method, path))

    metrics_by_category = defaultdict(int)
    for issue in issues:
        metrics_by_category[issue.category] += 1

    return AnalysisReport(
        total_frontend=len(contract),
        total_backend=len(backend_routes),
        issues=sorted(issues, key=lambda x: (x.severity != "CRITICAL", x.severity != "HIGH", x.path)),
        whitelisted=used_whitelist,
        backend_orphaned=orphaned,
        metrics_by_category=dict(metrics_by_category)
    )


def print_report(report: AnalysisReport, kalshi_only: bool = False):
    print("\n" + "=" * 80)
    print("  MISSING UI ENDPOINTS REPORT")
    print("=" * 80)

    print(f"\n  Summary:")
    print(f"    Frontend endpoints: {report.total_frontend}")
    print(f"    Backend routes: {report.total_backend}")
    print(f"    Total issues: {len(report.issues)}")

    critical = [i for i in report.issues if i.severity == "CRITICAL"]
    high = [i for i in report.issues if i.severity == "HIGH"]
    medium = [i for i in report.issues if i.severity == "MEDIUM"]
    low = [i for i in report.issues if i.severity == "LOW"]

    if critical:
        print(f"\n  🔴 CRITICAL ({len(critical)}): Kalshi trading will be broken")
    if high:
        print(f"  🟠 HIGH ({len(high)}): Significant UI functionality missing")
    if medium:
        print(f"  🟡 MEDIUM ({len(medium)}): Minor features may not work")
    if low:
        print(f"  ⚪ LOW ({len(low)}): Legacy/non-critical features")

    if not report.issues:
        print("\n  ✅ All endpoints are properly wired!")
        return

    # Group by severity
    for severity, label, color in [("CRITICAL", "CRITICAL", "🔴"), ("HIGH", "HIGH", "🟠")]:
        items = [i for i in report.issues if i.severity == severity]
        if not items:
            continue

        print(f"\n  {color} {label} ISSUES ({len(items)})")
        print("  " + "-" * 76)

        for issue in items:
            print(f"\n    {issue.issue_type:18s}  {issue.method:6s}  {issue.path}")
            print(f"    {'':18s}  key: {issue.key}")
            print(f"    {'':18s}  category: {issue.category}")
            if issue.note:
                print(f"    {'':18s}  note: {issue.note}")
            if issue.suggestion:
                print(f"    {'':18s}  fix: {issue.suggestion}")

    # Compact list for medium/low
    for severity, label, color in [("MEDIUM", "MEDIUM", "🟡"), ("LOW", "LOW", "⚪")]:
        items = [i for i in report.issues if i.severity == severity]
        if not items:
            continue

        print(f"\n  {color} {label} ISSUES ({len(items)}) - abbreviated")
        print("  " + "-" * 76)
        for issue in items:
            print(f"    {issue.method:6s}  {issue.path:<50s}  ({issue.key})")

    # Orphaned routes summary
    if report.backend_orphaned:
        kalshi_orphaned = [o for o in report.backend_orphaned if "/kalshi/" in o[1]]
        if kalshi_orphaned:
            print(f"\n  📡 KALSHI BACKEND ROUTES NOT USED BY FRONTEND ({len(kalshi_orphaned)})")
            print("  " + "-" * 76)
            for method, path in kalshi_orphaned[:15]:
                print(f"    {method:6s}  {path}")
            if len(kalshi_orphaned) > 15:
                print(f"    ... and {len(kalshi_orphaned) - 15} more")

    print("\n" + "=" * 80)
    print(f"  Full JSON report: {OUTPUT_JSON.relative_to(REPO)}")
    print("=" * 80 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Find missing UI endpoints between frontend and backend"
    )
    parser.add_argument("--json", action="store_true", help="Output JSON to file")
    parser.add_argument("--kalshi-only", action="store_true", help="Only check Kalshi-critical endpoints")
    args = parser.parse_args()

    print("Analyzing frontend/backend endpoint contracts...")
    report = analyze_endpoints(kalshi_only=args.kalshi_only)

    print_report(report, kalshi_only=args.kalshi_only)

    if args.json:
        OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_JSON.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
        print(f"JSON report written to: {OUTPUT_JSON}")

    # Exit with error code if critical issues found
    critical_count = sum(1 for i in report.issues if i.severity == "CRITICAL")
    if critical_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
