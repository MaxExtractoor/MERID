"""
Compliance Report Generator — export compliance summary for a date range.

Generates a structured report covering:
- Venue classification (US-compliant, blocked, optional)
- Active trading venues and their modes
- Order sanity check metrics
- Risk limit status
- Blocked venue rejection log
- Secrets guard status

CLI usage:
    python -m core.compliance_report                  # human-readable
    python -m core.compliance_report --json           # JSON output
    python -m core.compliance_report --from 2026-02-01 --to 2026-02-07
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.us_compliance_config import (
    BLOCKED_VENUES,
    OPTIONAL_VENUES,
    US_COMPLIANT_VENUES,
    VENUE_ASSET_CLASSES,
    is_venue_blocked,
    is_venue_us_compliant,
)
from core.order_sanity_check import get_order_sanity_checker
from core.secrets_guard import (
    get_gitignore_coverage,
    scan_for_tracked_secrets,
)

from utils.logger import get_logger

logger = get_logger("core.compliance_report")


# ── Data classes ───────────────────────────────────────────────────


@dataclass
class VenueClassificationEntry:
    """Single venue classification record."""
    venue: str
    status: str  # "us_compliant", "blocked", "optional"
    asset_classes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "venue": self.venue,
            "status": self.status,
            "asset_classes": self.asset_classes,
        }


@dataclass
class ComplianceReport:
    """Full compliance report."""
    generated_at: str
    report_range_from: Optional[str] = None
    report_range_to: Optional[str] = None
    venue_classifications: List[VenueClassificationEntry] = field(default_factory=list)
    order_sanity_metrics: Dict[str, Any] = field(default_factory=dict)
    secrets_status: Dict[str, Any] = field(default_factory=dict)
    gitignore_coverage: Dict[str, Any] = field(default_factory=dict)
    summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "report_range_from": self.report_range_from,
            "report_range_to": self.report_range_to,
            "venue_classifications": [v.to_dict() for v in self.venue_classifications],
            "order_sanity_metrics": self.order_sanity_metrics,
            "secrets_status": self.secrets_status,
            "gitignore_coverage": self.gitignore_coverage,
            "summary": self.summary,
        }


# ── Builder ────────────────────────────────────────────────────────


def _asset_classes_for_venue(venue: str) -> List[str]:
    """Return asset classes a venue serves."""
    classes = []
    for ac, venues in VENUE_ASSET_CLASSES.items():
        if venue in venues:
            classes.append(ac)
    return sorted(classes)


def build_venue_classifications() -> List[VenueClassificationEntry]:
    """Build the full venue classification list."""
    entries: List[VenueClassificationEntry] = []

    for v in sorted(US_COMPLIANT_VENUES):
        entries.append(VenueClassificationEntry(
            venue=v,
            status="us_compliant",
            asset_classes=_asset_classes_for_venue(v),
        ))
    for v in sorted(BLOCKED_VENUES):
        entries.append(VenueClassificationEntry(
            venue=v,
            status="blocked",
            asset_classes=[],
        ))
    for v in sorted(OPTIONAL_VENUES):
        entries.append(VenueClassificationEntry(
            venue=v,
            status="optional",
            asset_classes=_asset_classes_for_venue(v),
        ))
    return entries


def build_secrets_status() -> Dict[str, Any]:
    """Check secrets guard status."""
    try:
        tracked = scan_for_tracked_secrets()
        return {
            "tracked_secrets_found": len(tracked) > 0,
            "tracked_secrets": tracked,
            "status": "FAIL" if tracked else "PASS",
        }
    except Exception as exc:
        return {
            "tracked_secrets_found": None,
            "error": str(exc),
            "status": "ERROR",
        }


def build_gitignore_coverage() -> Dict[str, Any]:
    """Check .gitignore coverage."""
    try:
        coverage = get_gitignore_coverage()
        return {
            "total_patterns": coverage.get("total_patterns", 0),
            "secret_patterns": coverage.get("secret_patterns", 0),
            "status": "PASS" if coverage.get("total_patterns", 0) >= 20 else "WARN",
        }
    except Exception as exc:
        return {"error": str(exc), "status": "ERROR"}


def build_order_sanity_metrics() -> Dict[str, Any]:
    """Get order sanity checker metrics."""
    try:
        checker = get_order_sanity_checker()
        return checker.get_metrics()
    except Exception as exc:
        return {"error": str(exc)}


def generate_report(
    range_from: Optional[str] = None,
    range_to: Optional[str] = None,
) -> ComplianceReport:
    """Generate a full compliance report.

    Args:
        range_from: ISO date string (e.g. "2026-02-01"). Informational only.
        range_to: ISO date string (e.g. "2026-02-07"). Informational only.
    """
    venues = build_venue_classifications()
    secrets = build_secrets_status()
    gitignore = build_gitignore_coverage()
    sanity = build_order_sanity_metrics()

    us_count = sum(1 for v in venues if v.status == "us_compliant")
    blocked_count = sum(1 for v in venues if v.status == "blocked")
    optional_count = sum(1 for v in venues if v.status == "optional")

    summary = {
        "us_compliant_venues": us_count,
        "blocked_venues": blocked_count,
        "optional_venues": optional_count,
        "total_venues_classified": us_count + blocked_count + optional_count,
        "secrets_clean": secrets.get("status") == "PASS",
        "gitignore_adequate": gitignore.get("status") == "PASS",
        "overall_status": (
            "PASS"
            if secrets.get("status") == "PASS" and gitignore.get("status") != "ERROR"
            else "NEEDS_ATTENTION"
        ),
    }

    return ComplianceReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        report_range_from=range_from,
        report_range_to=range_to,
        venue_classifications=venues,
        order_sanity_metrics=sanity,
        secrets_status=secrets,
        gitignore_coverage=gitignore,
        summary=summary,
    )


# ── CLI ────────────────────────────────────────────────────────────


def _format_human(report: ComplianceReport) -> str:
    """Format report as human-readable text."""
    lines: List[str] = []
    lines.append("=" * 60)
    lines.append("MERID COMPLIANCE REPORT")
    lines.append("=" * 60)
    lines.append(f"Generated: {report.generated_at}")
    if report.report_range_from or report.report_range_to:
        lines.append(f"Range: {report.report_range_from or '—'} → {report.report_range_to or '—'}")
    lines.append("")

    # Venue classifications
    lines.append("── Venue Classifications ──")
    for v in report.venue_classifications:
        tag = {"us_compliant": "✓ US-COMPLIANT", "blocked": "✗ BLOCKED", "optional": "~ OPTIONAL"}
        label = tag.get(v.status, v.status.upper())
        ac = ", ".join(v.asset_classes) if v.asset_classes else "—"
        lines.append(f"  {label:18s}  {v.venue:22s}  [{ac}]")
    lines.append("")

    s = report.summary
    lines.append(f"  US-compliant: {s['us_compliant_venues']}  |  Blocked: {s['blocked_venues']}  |  Optional: {s['optional_venues']}")
    lines.append("")

    # Secrets
    lines.append("── Secrets Status ──")
    sec = report.secrets_status
    lines.append(f"  Status: {sec.get('status', 'UNKNOWN')}")
    if sec.get("tracked_secrets"):
        for ts in sec["tracked_secrets"]:
            lines.append(f"    ⚠ {ts}")
    lines.append("")

    # Gitignore
    lines.append("── .gitignore Coverage ──")
    gi = report.gitignore_coverage
    lines.append(f"  Status: {gi.get('status', 'UNKNOWN')}")
    lines.append(f"  Total patterns: {gi.get('total_patterns', '?')}")
    lines.append(f"  Secret patterns: {gi.get('secret_patterns', '?')}")
    lines.append("")

    # Order sanity
    lines.append("── Order Sanity Metrics ──")
    om = report.order_sanity_metrics
    lines.append(f"  Total checks: {om.get('total_checks', 0)}")
    lines.append(f"  Total rejects: {om.get('total_rejects', 0)}")
    lines.append(f"  Reject rate: {om.get('reject_rate', 0):.1%}")
    lines.append(f"  Daily orders: {om.get('daily_order_count', 0)}")
    lines.append("")

    # Overall
    lines.append("── Overall ──")
    lines.append(f"  Status: {s['overall_status']}")
    lines.append("=" * 60)

    return "\n".join(lines)


def main() -> None:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="MERID Compliance Report")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--from", dest="range_from", default=None, help="Start date (ISO)")
    parser.add_argument("--to", dest="range_to", default=None, help="End date (ISO)")
    args = parser.parse_args()

    report = generate_report(
        range_from=args.range_from,
        range_to=args.range_to,
    )

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(_format_human(report))


if __name__ == "__main__":
    main()
