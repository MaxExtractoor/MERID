"""
Tests for technical analysis flaw audit script.

Tests the audit script's ability to detect flaws and gaps in:
- Velocity implementation
- Volatility implementation
- Momentum implementation
- Directional decision making
- Spot-strike tracking
- Trade decision timing
- Configuration consistency
- Cross-layer consistency
"""

import os
import sys
import pytest
import tempfile
import shutil
from datetime import datetime, timezone

# Add parent directory to path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from scripts.technical_analysis_flaw_audit import (
    TechnicalAnalysisAuditor,
    Finding,
    Severity,
    Category,
)


class TestTechnicalAnalysisAuditor:
    """Test suite for TechnicalAnalysisAuditor."""
    
    @pytest.fixture
    def auditor(self):
        """Create a fresh auditor instance for each test."""
        return TechnicalAnalysisAuditor()
    
    @pytest.fixture
    def temp_profile_dir(self):
        """Create a temporary directory for test profile files."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    def test_auditor_initialization(self, auditor):
        """Test auditor initializes correctly."""
        assert auditor.findings == []
        assert auditor.assets == ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        assert auditor.start_time is not None
    
    def test_add_finding(self, auditor):
        """Test adding a finding."""
        auditor.add_finding(
            category=Category.VELOCITY,
            severity=Severity.CRITICAL,
            title="Test finding",
            description="Test description",
            location="test.py",
            recommendation="Fix it",
            evidence={"key": "value"}
        )
        
        assert len(auditor.findings) == 1
        finding = auditor.findings[0]
        assert finding.category == Category.VELOCITY
        assert finding.severity == Severity.CRITICAL
        assert finding.title == "Test finding"
        assert finding.description == "Test description"
        assert finding.location == "test.py"
        assert finding.recommendation == "Fix it"
        assert finding.evidence == {"key": "value"}
    
    def test_generate_report(self, auditor):
        """Test report generation."""
        # Add some test findings
        auditor.add_finding(
            category=Category.VELOCITY,
            severity=Severity.CRITICAL,
            title="Critical finding",
            description="Critical description",
            location="test.py",
            recommendation="Fix critical"
        )
        auditor.add_finding(
            category=Category.VOLATILITY,
            severity=Severity.HIGH,
            title="High finding",
            description="High description",
            location="test2.py",
            recommendation="Fix high"
        )
        
        report = auditor.generate_report()
        
        assert "TECHNICAL ANALYSIS FLAW AUDIT REPORT" in report
        assert "Total Findings: 2" in report
        assert "CRITICAL: 1" in report
        assert "HIGH: 1" in report
        assert "VELOCITY: 1" in report
        assert "VOLATILITY: 1" in report
        assert "Critical finding" in report
        assert "High finding" in report
        
        # Check report file was created
        assert os.path.exists("technical_analysis_flaw_audit_report.txt")
        
        # Clean up
        if os.path.exists("technical_analysis_flaw_audit_report.txt"):
            os.remove("technical_analysis_flaw_audit_report.txt")
        if os.path.exists("technical_analysis_flaw_audit.log"):
            os.remove("technical_analysis_flaw_audit.log")
    
    def test_audit_configuration_consistency_missing_profile(self, auditor):
        """Test configuration audit detects missing profile YAML."""
        from unittest.mock import patch
        with patch('scripts.technical_analysis_flaw_audit.os.path.exists', return_value=False):
            auditor.audit_configuration_consistency()
        
        # Should have finding for missing profile
        config_findings = [f for f in auditor.findings if f.category == Category.CONFIGURATION]
        missing_findings = [f for f in config_findings if "missing" in f.title.lower()]
        assert len(missing_findings) > 0
    
    def test_audit_configuration_consistency_missing_sections(self, auditor):
        """Test configuration audit detects missing profile sections."""
        from unittest.mock import patch, mock_open
        import yaml
        
        # Create a test profile with missing sections
        profile_data = {
            "velocity_thresholds": {
                "btc": 0.00015,
            }
            # Missing guardrails and agent_defaults
        }
        
        # Mock file operations
        with patch('scripts.technical_analysis_flaw_audit.os.path.exists', return_value=True):
            with patch('builtins.open', mock_open(read_data=yaml.dump(profile_data))):
                auditor.audit_configuration_consistency()
        
        # Should have findings for missing sections
        config_findings = [f for f in auditor.findings if f.category == Category.CONFIGURATION]
        section_findings = [f for f in config_findings if "section" in f.title.lower()]
        assert len(section_findings) > 0


def mock_open_read(content):
    """Mock open() for reading files."""
    from unittest.mock import mock_open
    return mock_open(read_data=content).return_value


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
