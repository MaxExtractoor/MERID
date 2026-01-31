"""
UI Audit Test Suite
Comprehensive automated testing for MERID UI pages
"""

import pytest
import json
import time
from pathlib import Path
from typing import Dict, Any, List
from qa.ui_auditor import UIAuditor, UIAuditSeverity, UIAuditCategory

class TestUIAudit:
    """UI Audit Test Suite"""
    
    @pytest.fixture(scope="class")
    def auditor(self):
        """Setup UI auditor"""
        base_url = "http://localhost:8000"
        auditor = UIAuditor(base_url=base_url, headless=True)
        yield auditor
        auditor.cleanup_driver()
    
    @pytest.fixture(scope="class")
    def audit_pages(self):
        """Pages to audit"""
        return [
            "/",
            "/dashboard",
            "/simple-dashboard", 
            "/api-contracts",
            "/mode-management",
            "/observability",
            "/unified.html",
            "/main-test",
            "/debug-v2"
        ]
    
    @pytest.fixture(scope="class")
    def audit_results(self, auditor, audit_pages):
        """Run audit on all pages"""
        return auditor.audit_all_pages(audit_pages)
    
    def test_all_pages_accessible(self, audit_results):
        """Test that all pages are accessible"""
        for result in audit_results:
            assert result.status_code == 200, f"Page {result.page} returned status {result.status_code}"
            assert result.load_time < 10.0, f"Page {result.page} load time {result.load_time:.2f}s exceeds 10s threshold"
    
    def test_no_critical_issues(self, audit_results):
        """Test that no critical issues exist"""
        critical_issues = []
        for result in audit_results:
            critical_issues.extend([issue for issue in result.issues if issue.severity == UIAuditSeverity.CRITICAL])
        
        assert len(critical_issues) == 0, f"Found {len(critical_issues)} critical issues: {[issue.title for issue in critical_issues]}"
    
    def test_accessibility_compliance(self, audit_results):
        """Test accessibility compliance"""
        accessibility_issues = []
        for result in audit_results:
            accessibility_issues.extend([issue for issue in result.issues if issue.category == UIAuditCategory.ACCESSIBILITY])
        
        # Allow some warnings but no errors
        error_issues = [issue for issue in accessibility_issues if issue.severity in [UIAuditSeverity.ERROR, UIAuditSeverity.CRITICAL]]
        assert len(error_issues) == 0, f"Found {len(error_issues)} accessibility errors: {[issue.title for issue in error_issues]}"
        
        # Limit warnings
        assert len(accessibility_issues) <= 10, f"Too many accessibility issues ({len(accessibility_issues)}), limit to 10"
    
    def test_performance_standards(self, audit_results):
        """Test performance standards"""
        performance_issues = []
        for result in audit_results:
            performance_issues.extend([issue for issue in result.issues if issue.category == UIAuditCategory.PERFORMANCE])
        
        # No performance errors or critical issues
        critical_performance = [issue for issue in performance_issues if issue.severity in [UIAuditSeverity.CRITICAL, UIAuditSeverity.ERROR]]
        assert len(critical_performance) == 0, f"Found {len(critical_performance)} critical performance issues: {[issue.title for issue in critical_performance]}"
        
        # Limit warnings
        assert len(performance_issues) <= 5, f"Too many performance issues ({len(performance_issues)}), limit to 5"
    
    def test_responsive_design(self, audit_results):
        """Test responsive design compliance"""
        responsiveness_issues = []
        for result in audit_results:
            responsiveness_issues.extend([issue for issue in result.issues if issue.category == UIAuditCategory.RESPONSIVENESS])
        
        # No responsiveness errors
        error_issues = [issue for issue in responsiveness_issues if issue.severity in [UIAuditSeverity.ERROR, UIAuditSeverity.CRITICAL]]
        assert len(error_issues) == 0, f"Found {len(error_issues)} responsiveness errors: {[issue.title for issue in error_issues]}"
    
    def test_functionality_integrity(self, audit_results):
        """Test functionality integrity"""
        functionality_issues = []
        for result in audit_results:
            functionality_issues.extend([issue for issue in result.issues if issue.category == UIAuditCategory.FUNCTIONALITY])
        
        # No functionality errors
        error_issues = [issue for issue in functionality_issues if issue.severity in [UIAuditSeverity.ERROR, UIAuditSeverity.CRITICAL]]
        assert len(error_issues) == 0, f"Found {len(error_issues)} functionality errors: {[issue.title for issue in error_issues]}"
    
    def test_ui_consistency(self, audit_results):
        """Test UI consistency"""
        consistency_issues = []
        for result in audit_results:
            consistency_issues.extend([issue for issue in result.issues if issue.category == UIAuditCategory.CONSISTENCY])
        
        # Limit consistency warnings
        assert len(consistency_issues) <= 15, f"Too many consistency issues ({len(consistency_issues)}), limit to 15"
    
    def test_security_compliance(self, audit_results):
        """Test security compliance"""
        security_issues = []
        for result in audit_results:
            security_issues.extend([issue for issue in result.issues if issue.category == UIAuditCategory.SECURITY])
        
        # No security errors
        error_issues = [issue for issue in security_issues if issue.severity in [UIAuditSeverity.ERROR, UIAuditSeverity.CRITICAL]]
        assert len(error_issues) == 0, f"Found {len(error_issues)} security errors: {[issue.title for issue in error_issues]}"
    
    def test_seo_optimization(self, audit_results):
        """Test SEO optimization"""
        seo_issues = []
        for result in audit_results:
            seo_issues.extend([issue for issue in result.issues if issue.category == UIAuditCategory.SEO])
        
        # No SEO errors
        error_issues = [issue for issue in seo_issues if issue.severity in [UIAuditSeverity.ERROR, UIAuditSeverity.CRITICAL]]
        assert len(error_issues) == 0, f"Found {len(error_issues)} SEO errors: {[issue.title for issue in error_issues]}"
    
    def test_usability_standards(self, audit_results):
        """Test usability standards"""
        usability_issues = []
        for result in audit_results:
            usability_issues.extend([issue for issue in result.issues if issue.category == UIAuditCategory.USABILITY])
        
        # No usability errors
        error_issues = [issue for issue in usability_issues if issue.severity in [UIAuditSeverity.ERROR, UIAuditSeverity.CRITICAL]]
        assert len(error_issues) == 0, f"Found {len(error_issues)} usability errors: {[issue.title for issue in error_issues]}"
    
    def test_overall_quality_score(self, audit_results):
        """Test overall quality score"""
        total_issues = sum(len(result.issues) for result in audit_results)
        total_pages = len(audit_results)
        
        # Calculate quality score (100 - issues per page * 10)
        issues_per_page = total_issues / total_pages
        quality_score = max(0, 100 - (issues_per_page * 10))
        
        assert quality_score >= 70, f"Quality score {quality_score:.1f} is below 70 (issues per page: {issues_per_page:.1f})"
    
    def test_generate_audit_report(self, auditor, audit_results):
        """Test audit report generation"""
        report = auditor.generate_report()
        
        # Verify report structure
        assert "summary" in report
        assert "pages" in report
        assert "issues_by_category" in report
        assert "issues_by_severity" in report
        
        # Verify summary data
        summary = report["summary"]
        assert "total_pages" in summary
        assert "total_issues" in summary
        assert "critical_issues" in summary
        assert "error_issues" in summary
        assert "warning_issues" in summary
        assert "avg_load_time" in summary
        
        # Verify page data
        pages = report["pages"]
        assert len(pages) == len(audit_results)
        
        for page_data in pages:
            assert "page" in page_data
            assert "url" in page_data
            assert "status_code" in page_data
            assert "load_time" in page_data
            assert "issue_count" in page_data
            assert "issues" in page_data

# Integration tests
class TestUIAuditIntegration:
    """UI Audit Integration Tests"""
    
    def test_quick_ui_audit_function(self):
        """Test quick UI audit function"""
        from qa.ui_auditor import quick_ui_audit
        
        # Test with limited pages to avoid timeout
        pages = ["/", "/dashboard"]
        report = quick_ui_audit(pages=pages, base_url="http://localhost:8000")
        
        assert "summary" in report
        assert report["summary"]["total_pages"] == 2
        assert "pages" in report
        assert len(report["pages"]) == 2
    
    def test_ui_auditor_initialization(self):
        """Test UI auditor initialization"""
        auditor = UIAuditor(base_url="http://localhost:8000", headless=True)
        
        assert auditor.base_url == "http://localhost:8000"
        assert auditor.headless is True
        assert auditor.results == []
        
        auditor.cleanup_driver()
    
    def test_single_page_audit(self):
        """Test single page audit"""
        auditor = UIAuditor(base_url="http://localhost:8000", headless=True)
        
        try:
            result = auditor.audit_page("/")
            
            assert result.page == "/"
            assert result.url == "http://localhost:8000/"
            assert result.status_code == 200
            assert result.load_time > 0
            assert isinstance(result.issues, list)
            assert isinstance(result.metrics, dict)
            
        finally:
            auditor.cleanup_driver()

# Performance tests
class TestUIAuditPerformance:
    """UI Audit Performance Tests"""
    
    def test_audit_performance(self):
        """Test audit performance"""
        auditor = UIAuditor(base_url="http://localhost:8000", headless=True)
        
        start_time = time.time()
        
        try:
            # Test with a single page for performance
            result = auditor.audit_page("/")
            audit_time = time.time() - start_time
            
            # Audit should complete within 30 seconds
            assert audit_time < 30.0, f"Audit took {audit_time:.2f}s, expected < 30s"
            
        finally:
            auditor.cleanup_driver()

# Edge case tests
class TestUIAuditEdgeCases:
    """UI Audit Edge Case Tests"""
    
    def test_nonexistent_page(self):
        """Test audit of non-existent page"""
        auditor = UIAuditor(base_url="http://localhost:8000", headless=True)
        
        try:
            result = auditor.audit_page("/nonexistent-page")
            
            # Should handle gracefully
            assert result.page == "/nonexistent-page"
            assert len(result.issues) > 0
            assert any(issue.severity == UIAuditSeverity.CRITICAL for issue in result.issues)
            
        finally:
            auditor.cleanup_driver()
    
    def test_empty_page_list(self):
        """Test audit with empty page list"""
        auditor = UIAuditor(base_url="http://localhost:8000", headless=True)
        
        try:
            results = auditor.audit_all_pages([])
            assert results == []
            
        finally:
            auditor.cleanup_driver()

if __name__ == "__main__":
    # Run quick audit when executed directly
    from qa.ui_auditor import quick_ui_audit
    
    print("Running quick UI audit...")
    report = quick_ui_audit()
    
    print(f"\nAudit Summary:")
    print(f"Total Pages: {report['summary']['total_pages']}")
    print(f"Total Issues: {report['summary']['total_issues']}")
    print(f"Critical Issues: {report['summary']['critical_issues']}")
    print(f"Error Issues: {report['summary']['error_issues']}")
    print(f"Warning Issues: {report['summary']['warning_issues']}")
    print(f"Avg Load Time: {report['summary']['avg_load_time']:.2f}s")
    
    # Show issues by category
    print(f"\nIssues by Category:")
    for category, count in report['issues_by_category'].items():
        if count > 0:
            print(f"  {category}: {count}")
    
    # Show issues by severity
    print(f"\nIssues by Severity:")
    for severity, count in report['issues_by_severity'].items():
        if count > 0:
            print(f"  {severity}: {count}")
    
    # Show pages with most issues
    pages_with_issues = [p for p in report['pages'] if p['issue_count'] > 0]
    if pages_with_issues:
        print(f"\nPages with Issues:")
        for page in sorted(pages_with_issues, key=lambda x: x['issue_count'], reverse=True)[:5]:
            print(f"  {page['page']}: {page['issue_count']} issues")
    
    print(f"\nDetailed report saved to: ui_audit_report_*.json")
