"""Renders audit findings into JSON and Markdown reports."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from tools.audit.models import Finding, Severity, SEVERITY_ORDER


# Severity badges for Markdown
_BADGE = {
    Severity.CRITICAL: "[CRITICAL]",
    Severity.HIGH:     "[HIGH]",
    Severity.MEDIUM:   "[MEDIUM]",
    Severity.LOW:      "[LOW]",
}

_EMOJI = {
    "mandelbug":     "[Mandelbug]",
    "heisenbug":     "[Heisenbug]",
    "schrodinbug":   "[Schrodinbug]",
    "zombie":        "[Zombie]",
    "race_condition":"[Race]",
    "memory_leak":   "[MemLeak]",
    "regression":    "[Regression]",
    "phase_of_moon": "[PhaseOfMoon]",
}

_DESCRIPTION = {
    "mandelbug":     "Complex non-deterministic bugs from emergent system interactions",
    "heisenbug":     "Bugs that disappear when you observe/debug them",
    "schrodinbug":   "Works fine until you read the code and realise it shouldn't",
    "zombie":        "Fixed bugs that keep coming back",
    "race_condition":"Two async operations fighting over shared state",
    "memory_leak":   "Unreleased subscriptions, timers, or event listeners",
    "regression":    "New code that broke existing behaviour",
    "phase_of_moon": "Only reproduces under specific environmental conditions",
}


def _sorted_findings(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: (SEVERITY_ORDER[f.severity], f.bug_type, f.file, f.line))


def write_json(findings: list[Finding], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"bug_audit_{date.today()}.json"

    by_type: dict[str, list[dict]] = defaultdict(list)
    for f in _sorted_findings(findings):
        by_type[f.bug_type].append(f.to_dict())

    summary = {t: len(v) for t, v in by_type.items()}
    summary["TOTAL"] = len(findings)

    payload = {
        "generated": str(date.today()),
        "summary":   summary,
        "findings":  {t: v for t, v in by_type.items()},
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path


def write_markdown(findings: list[Finding], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"bug_audit_{date.today()}.md"

    by_type: dict[str, list[Finding]] = defaultdict(list)
    for f in _sorted_findings(findings):
        by_type[f.bug_type].append(f)

    sev_counts: dict[Severity, int] = defaultdict(int)
    for f in findings:
        sev_counts[f.severity] += 1

    lines = [
        f"# MERID Bug Audit — {date.today()}",
        "",
        "## Executive Summary",
        "",
        f"| Severity | Count |",
        f"|----------|-------|",
    ]
    for sev in [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW]:
        lines.append(f"| {_BADGE[sev]} | {sev_counts[sev]} |")
    lines += [f"| **TOTAL** | **{len(findings)}** |", ""]

    # TOC
    lines += ["## Bug Type Index", ""]
    for bt in _DESCRIPTION:
        if bt in by_type:
            emoji = _EMOJI.get(bt, "•")
            lines.append(f"- [{emoji} {bt.replace('_',' ').title()}](#{bt.replace('_','-')}) — {len(by_type[bt])} findings")
    lines.append("")

    # Sections
    for bt, desc in _DESCRIPTION.items():
        if bt not in by_type:
            continue
        emoji = _EMOJI.get(bt, "•")
        bucket = by_type[bt]
        lines += [
            f"---",
            f"",
            f"## {emoji} {bt.replace('_',' ').title()}",
            f"",
            f"> {desc}",
            f"",
            f"**{len(bucket)} finding(s)**",
            "",
        ]
        for f in bucket:
            badge = _BADGE[f.severity]
            lines += [
                f"### {badge} — {f.title}",
                f"",
                f"**File:** `{f.file}:{f.line}`  ",
                f"**Layer:** {f.layer.value}",
                f"",
            ]
            if f.snippet.strip():
                lines += [
                    "```",
                    f.snippet.strip()[:300],
                    "```",
                    "",
                ]
            if f.explanation:
                lines += [f"**Why it matters:** {f.explanation}", ""]
            if f.suggestion:
                lines += [f"**Fix:** {f.suggestion}", ""]

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path
