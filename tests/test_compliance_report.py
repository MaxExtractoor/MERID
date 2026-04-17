"""
Tests for ComplianceReport generator (S9-03 hardening).

Validates:
- Venue classification completeness
- Report generation and serialization
- Secrets status integration
- Gitignore coverage integration
- Order sanity metrics integration
- CLI output formats (human-readable and JSON)
- Date range handling
"""

import json
import unittest

from core.compliance_report import (
    ComplianceReport,
    VenueClassificationEntry,
    build_gitignore_coverage,
    build_order_sanity_metrics,
    build_secrets_status,
    build_venue_classifications,
    generate_report,
    _asset_classes_for_venue,
    _format_human,
)
from core.us_compliance_config import (
    BLOCKED_VENUES,
    OPTIONAL_VENUES,
    US_COMPLIANT_VENUES,
)


class TestVenueClassifications(unittest.TestCase):
    """Venue classification list is complete and correct."""

    def setUp(self):
        self.classifications = build_venue_classifications()

    def test_all_us_compliant_present(self):
        us = {v.venue for v in self.classifications if v.status == "us_compliant"}
        self.assertEqual(us, US_COMPLIANT_VENUES)

    def test_all_blocked_present(self):
        blocked = {v.venue for v in self.classifications if v.status == "blocked"}
        self.assertEqual(blocked, BLOCKED_VENUES)

    def test_all_optional_present(self):
        optional = {v.venue for v in self.classifications if v.status == "optional"}
        self.assertEqual(optional, OPTIONAL_VENUES)

    def test_total_count(self):
        expected = len(US_COMPLIANT_VENUES) + len(BLOCKED_VENUES) + len(OPTIONAL_VENUES)
        self.assertEqual(len(self.classifications), expected)

    def test_blocked_venues_have_no_asset_classes(self):
        for v in self.classifications:
            if v.status == "blocked":
                self.assertEqual(v.asset_classes, [], f"Blocked venue {v.venue} should have no asset classes")

    def test_us_compliant_sorted(self):
        us = [v.venue for v in self.classifications if v.status == "us_compliant"]
        self.assertEqual(us, sorted(us))

    def test_kalshi_has_prediction(self):
        kalshi = [v for v in self.classifications if v.venue == "kalshi"]
        self.assertEqual(len(kalshi), 1)
        self.assertIn("prediction", kalshi[0].asset_classes)

    def test_alpaca_has_equities(self):
        alpaca = [v for v in self.classifications if v.venue == "alpaca"]
        self.assertEqual(len(alpaca), 1)
        self.assertIn("equities", alpaca[0].asset_classes)


class TestAssetClassesForVenue(unittest.TestCase):
    """_asset_classes_for_venue returns correct classes."""

    def test_alpaca(self):
        classes = _asset_classes_for_venue("alpaca")
        self.assertIn("equities", classes)
        self.assertIn("crypto_spot", classes)

    def test_unknown_venue(self):
        classes = _asset_classes_for_venue("nonexistent_venue")
        self.assertEqual(classes, [])

    def test_ibkr_has_multiple(self):
        classes = _asset_classes_for_venue("ibkr")
        self.assertGreater(len(classes), 2)


class TestSecretsStatus(unittest.TestCase):
    """Secrets status check returns structured result."""

    def test_returns_dict(self):
        result = build_secrets_status()
        self.assertIsInstance(result, dict)
        self.assertIn("status", result)

    def test_status_is_valid(self):
        result = build_secrets_status()
        self.assertIn(result["status"], {"PASS", "FAIL", "ERROR"})


class TestGitignoreCoverage(unittest.TestCase):
    """Gitignore coverage check returns structured result."""

    def test_returns_dict(self):
        result = build_gitignore_coverage()
        self.assertIsInstance(result, dict)
        self.assertIn("status", result)

    def test_has_pattern_counts(self):
        result = build_gitignore_coverage()
        if result["status"] != "ERROR":
            self.assertIn("total_patterns", result)
            self.assertIn("secret_patterns", result)


class TestOrderSanityMetrics(unittest.TestCase):
    """Order sanity metrics integration."""

    def test_returns_dict(self):
        result = build_order_sanity_metrics()
        self.assertIsInstance(result, dict)

    def test_has_config(self):
        result = build_order_sanity_metrics()
        self.assertIn("config", result)


class TestGenerateReport(unittest.TestCase):
    """Full report generation."""

    def setUp(self):
        self.report = generate_report()

    def test_has_generated_at(self):
        self.assertIsNotNone(self.report.generated_at)
        self.assertIn("T", self.report.generated_at)  # ISO format

    def test_has_venue_classifications(self):
        self.assertGreater(len(self.report.venue_classifications), 0)

    def test_has_summary(self):
        self.assertIn("us_compliant_venues", self.report.summary)
        self.assertIn("blocked_venues", self.report.summary)
        self.assertIn("overall_status", self.report.summary)

    def test_summary_counts_match(self):
        s = self.report.summary
        total = s["us_compliant_venues"] + s["blocked_venues"] + s["optional_venues"]
        self.assertEqual(total, s["total_venues_classified"])

    def test_with_date_range(self):
        report = generate_report(range_from="2026-02-01", range_to="2026-02-07")
        self.assertEqual(report.report_range_from, "2026-02-01")
        self.assertEqual(report.report_range_to, "2026-02-07")

    def test_without_date_range(self):
        self.assertIsNone(self.report.report_range_from)
        self.assertIsNone(self.report.report_range_to)


class TestReportSerialization(unittest.TestCase):
    """Report serializes to dict and JSON correctly."""

    def setUp(self):
        self.report = generate_report(range_from="2026-02-01")

    def test_to_dict(self):
        d = self.report.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("generated_at", d)
        self.assertIn("venue_classifications", d)
        self.assertIsInstance(d["venue_classifications"], list)

    def test_json_roundtrip(self):
        d = self.report.to_dict()
        s = json.dumps(d)
        parsed = json.loads(s)
        self.assertEqual(parsed["report_range_from"], "2026-02-01")

    def test_venue_entry_to_dict(self):
        entry = VenueClassificationEntry(
            venue="test_venue", status="blocked", asset_classes=[]
        )
        d = entry.to_dict()
        self.assertEqual(d["venue"], "test_venue")
        self.assertEqual(d["status"], "blocked")


class TestHumanFormat(unittest.TestCase):
    """Human-readable format output."""

    def setUp(self):
        self.report = generate_report(range_from="2026-02-01", range_to="2026-02-07")
        self.text = _format_human(self.report)

    def test_has_header(self):
        self.assertIn("MERID COMPLIANCE REPORT", self.text)

    def test_has_venue_section(self):
        self.assertIn("Venue Classifications", self.text)

    def test_has_secrets_section(self):
        self.assertIn("Secrets Status", self.text)

    def test_has_gitignore_section(self):
        self.assertIn(".gitignore Coverage", self.text)

    def test_has_order_sanity_section(self):
        self.assertIn("Order Sanity Metrics", self.text)

    def test_has_overall_section(self):
        self.assertIn("Overall", self.text)

    def test_has_date_range(self):
        self.assertIn("2026-02-01", self.text)
        self.assertIn("2026-02-07", self.text)

    def test_blocked_venues_marked(self):
        self.assertIn("BLOCKED", self.text)

    def test_us_compliant_marked(self):
        self.assertIn("US-COMPLIANT", self.text)


if __name__ == "__main__":
    unittest.main()
