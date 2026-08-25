"""Skip governance and reporting.

Usage:
    python scripts/skip_governance.py [tests_path]

Returns:
    0 if every pytest.skip marker in the tree is owned (contains a TRACKER-XXX tag).
    1 otherwise, and prints a tab-separated skip report by module/reason.

Expected skip reason format:
    P[0-3]-<area>: TRACKER-XXX: human readable reason

Examples:
    P0-EXECUTION: TRACKER-042: requires deterministic exchange simulator
    P3-LEGACY: TRACKER-007: deprecated module scheduled for removal
"""

from __future__ import annotations

import ast
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple


class SkipEntry(NamedTuple):
    path: Path
    line: int
    scope: str
    reason: str
    priority: Optional[str]
    tracker: Optional[str]


_TRACKER_RE = re.compile(r"TRACKER-(\d{3,})")
_PRIORITY_RE = re.compile(r"^P([0-3])-([A-Z0-9_]+):")


def _extract_reason_from_decorator(node: ast.Call) -> Optional[str]:
    """Get the string reason from a pytest.mark.skip call."""
    for kw in node.keywords:
        if kw.arg == "reason" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            return kw.value.value
    for arg in node.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
    return None


def _find_pytest_skip_reasons(path: Path) -> List[Tuple[int, str, str, str]]:
    """Walk an AST and find every pytest.mark.skip (and module pytestmark) with its reason."""
    results: List[Tuple[int, str, str, str]] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        print(f"WARN: syntax error in {path}: {exc}", file=sys.stderr)
        return results

    for body_node in tree.body:
        if isinstance(body_node, ast.Assign):
            for target in body_node.targets:
                if isinstance(target, ast.Name) and target.id == "pytestmark":
                    if isinstance(body_node.value, ast.Call):
                        reason = _extract_reason_from_decorator(body_node.value)
                        if reason:
                            results.append((body_node.lineno, "module", "pytestmark", reason))
                    elif isinstance(body_node.value, (ast.List, ast.Tuple)):
                        for elt in body_node.value.elts:
                            if isinstance(elt, ast.Call):
                                reason = _extract_reason_from_decorator(elt)
                                if reason:
                                    results.append((body_node.lineno, "module", "pytestmark", reason))

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) or isinstance(node, ast.ClassDef):
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call):
                    func = dec.func
                    if isinstance(func, ast.Attribute) and func.attr == "skip" and isinstance(func.value, ast.Name) and func.value.id == "pytest":
                        reason = _extract_reason_from_decorator(dec)
                        if reason:
                            scope = f"{node.__class__.__name__.lower()}:{node.name}"
                            results.append((node.lineno, scope, "decorator", reason))
                    elif isinstance(func, ast.Attribute) and func.attr == "skip" and isinstance(func.value, ast.Attribute) and func.value.attr == "mark" and isinstance(func.value.value, ast.Name) and func.value.value.id == "pytest":
                        reason = _extract_reason_from_decorator(dec)
                        if reason:
                            scope = f"{node.__class__.__name__.lower()}:{node.name}"
                            results.append((node.lineno, scope, "decorator", reason))

    return results


def _classify(reason: str) -> Tuple[Optional[str], Optional[str]]:
    priority: Optional[str] = None
    tracker: Optional[str] = None
    m = _PRIORITY_RE.match(reason.strip())
    if m:
        priority = f"P{m.group(1)}-{m.group(2)}"
    t = _TRACKER_RE.search(reason)
    if t:
        tracker = t.group(0)
    return priority, tracker


def main() -> int:
    tests_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "tests"
    if not tests_path.exists():
        print(f"Path not found: {tests_path}", file=sys.stderr)
        return 2

    entries: List[SkipEntry] = []
    for py_file in tests_path.rglob("*.py"):
        for line, scope, kind, reason in _find_pytest_skip_reasons(py_file):
            priority, tracker = _classify(reason)
            entries.append(SkipEntry(py_file, line, scope, reason, priority, tracker))

    # Report
    by_module: Dict[str, Counter] = {}
    for e in entries:
        by_module.setdefault(e.path.as_posix(), Counter())[f"{e.priority or 'UNPRIORITIZED'} | {e.tracker or 'UNOWNED'}"] += 1

    print(f"\nSkip ownership report ({len(entries)} skip markers across {len(by_module)} files)")
    print("=" * 80)
    for module, counts in sorted(by_module.items()):
        print(f"\n{module}")
        for key, count in counts.most_common():
            print(f"  {count:4d}  {key}")
        print(f"  {sum(counts.values()):4d}  total")

    unowned = [e for e in entries if e.tracker is None]
    unprioritized = [e for e in entries if e.priority is None]

    print("\n" + "=" * 80)
    if unowned:
        print(f"FAIL: {len(unowned)} skip markers are missing a TRACKER-XXX tag:")
        for e in unowned[:20]:
            print(f"  {e.path}:{e.line} ({e.scope}) -> {e.reason[:120]}")
        if len(unowned) > 20:
            print(f"  ... and {len(unowned) - 20} more")
    else:
        print("PASS: every skip marker has a TRACKER-XXX owner.")

    if unprioritized:
        print(f"WARN: {len(unprioritized)} skip markers are missing a P[0-3]-<area> priority prefix.")
    else:
        print("PASS: every skip marker has a P[0-3]-<area> priority prefix.")

    return 1 if (unowned or unprioritized) else 0


if __name__ == "__main__":
    sys.exit(main())
