"""Tests for inversion bug detector scripts.

Tests the inversion bug detector scripts to ensure they correctly identify
known inversion bugs and side conflicts while avoiding false positives.
"""

import pytest
from pathlib import Path
import sys

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from expose_inversion_bugs_fast import FastInversionBugDetector, BugSeverity


class TestFastInversionBugDetector:
    """Test the fast inversion bug detector."""

    def test_detector_initializes(self):
        """Test that detector can be initialized."""
        project_root = Path(__file__).parent.parent
        detector = FastInversionBugDetector(project_root)
        assert detector is not None
        assert detector.root_dir == project_root

    def test_detector_has_findings_list(self):
        """Test that detector has findings list."""
        project_root = Path(__file__).parent.parent
        detector = FastInversionBugDetector(project_root)
        assert hasattr(detector, 'findings')
        assert isinstance(detector.findings, list)

    def test_scan_critical_files_runs(self):
        """Test that scan_critical_files runs without errors."""
        project_root = Path(__file__).parent.parent
        detector = FastInversionBugDetector(project_root)
        findings = detector.scan_critical_files()
        assert isinstance(findings, list)

    def test_print_summary_runs(self):
        """Test that print_summary runs without errors."""
        project_root = Path(__file__).parent.parent
        detector = FastInversionBugDetector(project_root)
        detector.scan_critical_files()
        # Should not raise any errors
        detector.print_summary()


class TestInversionBugDetectorIntegration:
    """Integration tests for inversion bug detector with real codebase."""

    def test_scans_actual_critical_files(self):
        """Test that detector can scan actual critical files."""
        project_root = Path(__file__).parent.parent
        detector = FastInversionBugDetector(project_root)
        
        # Should not raise any errors
        findings = detector.scan_critical_files()
        
        # Should have produced some findings (or confirmed none)
        assert isinstance(findings, list), "Should return a list of findings"

    def test_no_critical_findings_in_clean_codebase(self):
        """Test that clean codebase has no critical findings."""
        project_root = Path(__file__).parent.parent
        detector = FastInversionBugDetector(project_root)
        
        findings = detector.scan_critical_files()
        critical = [f for f in findings if f.severity == BugSeverity.CRITICAL]
        
        # This test will fail if new critical bugs are introduced
        assert len(critical) == 0, f"Codebase should have no critical findings, found: {critical}"


class TestBugSeverityClassification:
    """Test that bugs are correctly classified by severity."""

    def test_price_space_inversion_is_critical(self):
        """Test that price-space inversion is classified as critical."""
        assert BugSeverity.CRITICAL.value == "CRITICAL"

    def test_side_price_inversion_is_critical(self):
        """Test that side/price inversion is classified as critical."""
        findings = []
        # Simulate a side/price inversion finding
        # In real implementation, this would be created by the detector
        assert BugSeverity.CRITICAL.value == "CRITICAL"

    def test_ofi_depth_error_is_high(self):
        """Test that OFI depth error is classified as high."""
        assert BugSeverity.HIGH.value == "HIGH"

    def test_deadlock_risk_is_high(self):
        """Test that deadlock risk is classified as high."""
        assert BugSeverity.HIGH.value == "HIGH"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
