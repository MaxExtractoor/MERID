"""
MERID Readiness Score — Aggregate meta-layer.

Encodes the section-level scores from the Swarm Trading & 24/7 Readiness Audit
(docs/SWARM_TRADING_READINESS.md) and provides helpers consumed by the
readiness auditor CLI and other tooling.

Scores are updated manually after each audit review cycle.  The programmatic
checks in ``merid_readiness_auditor.evaluate_swarm_trading()`` can re-derive
these numbers at any time; this module serves as the *declared* baseline
between reviews.

Usage:
    python -m core.merid_readiness_score          # human-readable
    python -m core.merid_readiness_score --json    # JSON output
"""

from __future__ import annotations

import sys
from typing import Dict, Tuple

# ── Section scores (score, max) ─────────────────────────────────────────
# Updated: 2026-02-07  (backlogs #2, #4, #5 + S1-03, S1-04, S5-03, S8-01, S9-01: +8 points)

READINESS_SECTIONS: Dict[str, Tuple[int, int]] = {
    "swarm_architecture":       (8, 8),   # S1-03 1→2 (negotiation), S1-04 1→2 (A/B benchmark)
    "decentralization_trust":   (6, 8),
    "tokenization_value_flow":  (5, 6),
    "strategy_risk_safety":     (8, 8),   # S4-02 1→2, S4-03 1→2
    "observability_ux":         (8, 8),
    "operations_sre":           (7, 8),
    "testing_depth":            (8, 8),   # S7-02 1→2
    "data_models_drift":        (6, 6),   # S8-01 1→2, S8-03 1→2
    "security_ethics":          (5, 6),   # S9-01 0→1 (secrets guard)
    "user_operator_experience": (8, 8),
}

# ── Helpers ──────────────────────────────────────────────────────────────

def aggregate_scores(
    sections: Dict[str, Tuple[int, int]] | None = None,
) -> Tuple[int, int, float]:
    """Return (total, maximum, pct) for the given section dict."""
    sections = sections or READINESS_SECTIONS
    total = sum(s for s, _ in sections.values())
    maximum = sum(m for _, m in sections.values())
    pct = (total / maximum * 100) if maximum else 0.0
    return total, maximum, pct


def readiness_level(pct: float) -> str:
    """Map a percentage to a human-readable readiness label."""
    if pct >= 90:
        return "Production"
    if pct >= 70:
        return "Staging"
    if pct >= 50:
        return "Lab"
    return "Prototype"


def composite_scores(
    sections: Dict[str, Tuple[int, int]] | None = None,
) -> Dict[str, Tuple[int, int, float]]:
    """Return swarm-trading and 24/7 composite sub-scores."""
    sections = sections or READINESS_SECTIONS
    keys = list(sections.keys())
    swarm_keys = keys[:5]   # sections 1-5
    ops_keys = keys[5:]     # sections 6-10

    def _sub(ks):
        t = sum(sections[k][0] for k in ks)
        m = sum(sections[k][1] for k in ks)
        return t, m, (t / m * 100) if m else 0.0

    return {
        "swarm_trading": _sub(swarm_keys),
        "readiness_24_7": _sub(ops_keys),
    }


# ── CLI ──────────────────────────────────────────────────────────────────

def main():
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="MERID Readiness Score (declared baseline)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    total, maximum, pct = aggregate_scores()
    level = readiness_level(pct)
    comp = composite_scores()

    if args.json:
        out = {
            "total": total,
            "max": maximum,
            "pct": round(pct, 1),
            "level": level,
            "sections": {
                k: {"score": s, "max": m}
                for k, (s, m) in READINESS_SECTIONS.items()
            },
            "composite": {
                k: {"score": t, "max": mx, "pct": round(p, 1)}
                for k, (t, mx, p) in comp.items()
            },
        }
        print(json.dumps(out, indent=2))
    else:
        print("=" * 50)
        print("  MERID Readiness Score (declared baseline)")
        print("=" * 50)
        print()
        for key, (s, m) in READINESS_SECTIONS.items():
            label = key.replace("_", " ").title()
            bar = "#" * s + "." * (m - s)
            print(f"  [{bar}] {label}: {s}/{m}")
        print()
        print(f"  TOTAL: {total}/{maximum} ({pct:.0f}%) — {level}")
        print()
        for name, (t, mx, p) in comp.items():
            print(f"  {name.replace('_', ' ').title()}: {t}/{mx} ({p:.0f}%)")
        print()

    sys.exit(0 if pct >= 80 else 1)


if __name__ == "__main__":
    main()
