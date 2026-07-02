#!/usr/bin/env python
"""
time_audit.py

Static scanner to surface all time-handling sites in the MERID Kalshi 15m stack:
- naive vs aware datetime usage
- UTC vs ET usage
- multiple 15m window implementations
- ticker suffix formatters

Run:
    python tools/time_audit.py c:/Dev/MERID > time_audit_report.md
"""

import os
import re
import sys
from pathlib import Path
from typing import List, Dict, Any

# Simple patterns to search for
TIME_PATTERNS = {
    "datetime_now": re.compile(r"\bdatetime\.now\s*\("),
    "datetime_utcnow": re.compile(r"\bdatetime\.utcnow\s*\("),
    "timezone_utc": re.compile(r"\btimezone\.utc\b"),
    "zoneinfo_et": re.compile(r'ZoneInfo\(["\']America/New_York["\']\)'),
    "replace_tzinfo": re.compile(r"\.replace\s*\(\s*tzinfo\s*="),
    "strftime_suffix": re.compile(r"strftime\([^)]*%[yY].*%[bB].*%[dD].*%[Hh].*%[Mm]"),
    "kalshi_suffix_literal": re.compile(r"KX(BTC|ETH|SOL|XRP|DOGE)15M-"),
    "window_15m_names": re.compile(
        r"(compute_current_window_suffix|get_current_window|current_window|barindex|round_?to_?15m|get_kalshi_15m_window)"
    ),
    "kalshi_mentions": re.compile(r"kalshi", re.IGNORECASE),
    "minutes_to_expiry": re.compile(r"minutes_to_expiry"),
    "get_current_utc_window": re.compile(r"get_current_utc_window"),
    "get_next_utc_window": re.compile(r"get_next_utc_window"),
    "get_previous_utc_window": re.compile(r"get_previous_utc_window"),
    "compute_minutes_to_expiry": re.compile(r"compute_minutes_to_expiry"),
}

CODE_EXTS = {".py"}


def scan_file(path: Path) -> List[Dict[str, Any]]:
    findings = []
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return findings

    lines = text.splitlines()

    def add(kind: str, line_no: int, line: str):
        findings.append(
            {
                "file": str(path),
                "line": line_no,
                "kind": kind,
                "code": line.strip(),
            }
        )

    for i, line in enumerate(lines, start=1):
        for kind, pattern in TIME_PATTERNS.items():
            if pattern.search(line):
                add(kind, i, line)
    return findings


def walk_dir(root: Path) -> List[Dict[str, Any]]:
    all_findings: List[Dict[str, Any]] = []
    try:
        # Focus on Kalshi-related directories for faster scanning
        kalshi_dirs = [
            root / "merid" / "event_venues" / "kalshi",
            root / "merid" / "prediction",
            root / "merid" / "loop_15m.py",
        ]
        
        for target in kalshi_dirs:
            if target.is_file() and target.suffix == ".py":
                all_findings.extend(scan_file(target))
            elif target.is_dir():
                for path in target.rglob("*.py"):
                    # Skip certain directories
                    if any(skip in str(path) for skip in ["__pycache__"]):
                        continue
                    all_findings.extend(scan_file(path))
    except Exception as e:
        print(f"Error walking directory: {e}", file=sys.stderr)
    return all_findings


def group_by_file(findings: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for f in findings:
        grouped.setdefault(f["file"], []).append(f)
    # sort entries in each file by line
    for k in grouped:
        grouped[k].sort(key=lambda x: x["line"])
    return grouped


def main():
    if len(sys.argv) != 2:
        print("Usage: python time_audit.py /path/to/MERID", file=sys.stderr)
        sys.exit(1)

    # Set UTF-8 encoding for stdout to handle Unicode characters
    if sys.platform == "win32":
        import codecs
        sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "strict")
        sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, "strict")

    root = Path(sys.argv[1]).resolve()
    findings = walk_dir(root)
    grouped = group_by_file(findings)

    # Emit a markdown report for manual review
    print("# Time Handling Audit Report\n")
    print(f"Root: `{root}`")
    print()
    print(f"Total findings: {len(findings)}")
    print()

    for file, items in sorted(grouped.items()):
        # Only show files with Kalshi-related findings
        has_kalshi = any(i["kind"] == "kalshi_mentions" for i in items)
        if not has_kalshi:
            continue
            
        print(f"## {file}\n")
        # quick flags: does file mention kalshi, et, utc?
        has_et = any(i["kind"] == "zoneinfo_et" for i in items)
        has_utc = any(i["kind"] in ("datetime_utcnow", "timezone_utc") for i in items)
        has_window_helper = any(i["kind"] == "window_15m_names" for i in items)
        has_minutes_to_expiry = any(i["kind"] == "minutes_to_expiry" for i in items)
        
        print(f"- kalshi-related: {has_kalshi}")
        print(f"- uses ET: {has_et}")
        print(f"- uses UTC: {has_utc}")
        print(f"- has window logic: {has_window_helper}")
        print(f"- has minutes_to_expiry: {has_minutes_to_expiry}")
        print()

        print("| Line | Kind | Code |")
        print("|------|------|------|")
        for it in items:
            code = it["code"].replace("|", "\\|")
            print(f"| {it['line']} | {it['kind']} | `{code}` |")
        print()


if __name__ == "__main__":
    main()
