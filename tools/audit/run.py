#!/usr/bin/env python3
"""MERID Bug Audit Runner.

Usage:
    py tools/audit/run.py                          # full scan
    py tools/audit/run.py --only race_condition    # single detector
    py tools/audit/run.py --layer frontend         # frontend only
    py tools/audit/run.py --out docs               # custom output dir
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.audit.models import Finding, Layer
from tools.audit.report import write_json, write_markdown

from tools.audit.detectors.mandelbug      import MandelbugDetector
from tools.audit.detectors.heisenbug      import HeisenBugDetector
from tools.audit.detectors.schrodinbug    import SchrodinbugDetector
from tools.audit.detectors.zombie         import ZombieBugDetector
from tools.audit.detectors.race_condition import RaceConditionDetector
from tools.audit.detectors.memory_leak    import MemoryLeakDetector
from tools.audit.detectors.regression     import RegressionDetector
from tools.audit.detectors.phase_of_moon  import PhaseOfMoonDetector

ALL_DETECTORS = [
    MandelbugDetector(),
    HeisenBugDetector(),
    SchrodinbugDetector(),
    ZombieBugDetector(),
    RaceConditionDetector(),
    MemoryLeakDetector(),
    RegressionDetector(),
    PhaseOfMoonDetector(),
]

_LAYER_MAP = {
    "frontend": Layer.FRONTEND,
    "backend":  Layer.BACKEND,
    "cross":    Layer.CROSS,
}


def run(
    only: str | None = None,
    layer: str | None = None,
    out:   str = "docs",
) -> list[Finding]:
    detectors = ALL_DETECTORS
    if only:
        detectors = [d for d in ALL_DETECTORS if d.name == only]
        if not detectors:
            print(f"[!] Unknown detector: {only}. Available: {[d.name for d in ALL_DETECTORS]}")
            sys.exit(1)

    all_findings: list[Finding] = []
    for detector in detectors:
        t0 = time.time()
        print(f"  [{detector.name}] scanning...", end="", flush=True)
        try:
            findings = detector.detect(ROOT)
        except Exception as exc:
            print(f" ERROR: {exc}")
            continue

        # Filter by layer if requested
        if layer:
            target = _LAYER_MAP.get(layer)
            findings = [f for f in findings if f.layer == target]

        print(f" {len(findings)} findings ({time.time()-t0:.1f}s)")
        all_findings.extend(findings)

    return all_findings


def main() -> None:
    parser = argparse.ArgumentParser(description="MERID Bug Audit")
    parser.add_argument("--only",  help="Run a single detector by name")
    parser.add_argument("--layer", choices=["frontend", "backend", "cross"],
                        help="Filter findings by layer")
    parser.add_argument("--out",   default="docs", help="Output directory (default: docs/)")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print("  MERID Bug Audit")
    print(f"{'='*60}\n")

    t0 = time.time()
    findings = run(only=args.only, layer=args.layer, out=args.out)

    out_dir = ROOT / args.out
    json_path = write_json(findings, out_dir)
    md_path   = write_markdown(findings, out_dir)

    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"  Total findings : {len(findings)}")
    print(f"  Elapsed        : {elapsed:.1f}s")
    print(f"  JSON report    : {json_path.relative_to(ROOT)}")
    print(f"  Markdown report: {md_path.relative_to(ROOT)}")
    print(f"{'='*60}\n")

    # Exit code > 0 if any CRITICAL findings (useful for CI)
    from tools.audit.models import Severity
    critical = sum(1 for f in findings if f.severity == Severity.CRITICAL)
    if critical:
        print(f"  [!] {critical} CRITICAL finding(s) -- exiting 1 for CI")
        sys.exit(1)


if __name__ == "__main__":
    main()
