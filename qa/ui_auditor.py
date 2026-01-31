"""
MERID UI Audit Framework
Comprehensive UI testing, validation, and quality assurance
"""

import os
import json
import time
import asyncio
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
import logging
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import requests
from bs4 import BeautifulSoup

class UIAuditSeverity(Enum):
    """UI audit issue severity levels"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

class UIAuditCategory(Enum):
    """UI audit categories"""
    ACCESSIBILITY = "accessibility"
    PERFORMANCE = "performance"
    RESPONSIVENESS = "responsiveness"
    FUNCTIONALITY = "functionality"
    CONSISTENCY = "consistency"
    SECURITY = "security"
    SEO = "seo"
    USABILITY = "usability"

@dataclass
class UIAuditIssue:
    """UI audit issue definition"""
    id: str
    category: UIAuditCategory
    severity: UIAuditSeverity
    title: str
    description: str
    page: str
    element: Optional[str] = None
    recommendation: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class UIAuditResult:
    """UI audit result for a page"""
    page: str
    url: str
    status_code: int
    load_time: float
    issues: List[UIAuditIssue] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    
    @property
    def issue_count(self) -> int:
        return len(self.issues)
    
    @property
    def critical_issues(self) -> int:
        return len([i for i in self.issues if i.severity == UIAuditSeverity.CRITICAL])
    
    @property
    def error_issues(self) -> int:
        return len([i for i in self.issues if i.severity == UIAuditSeverity.ERROR])
    
    @property
    def warning_issues(self) -> int:
        return len([i for i in self.issues if i.severity == UIAuditSeverity.WARNING])

class UIAuditor:
    """Comprehensive UI auditor"""
    
    def __init__(self, base_url: str = "http://localhost:8000", headless: bool = True):
        self.base_url = base_url
        self.headless = headless
        self.driver = None
        self.results: List[UIAuditResult] = []
        self.logger = logging.getLogger(__name__)
        
    def setup_driver(self):
        """Setup Chrome WebDriver"""
        options = Options()
        if self.headless:
            options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-plugins")
        options.add_argument("--disable-images")  # Faster loading
        
        self.driver = webdriver.Chrome(options=options)
        self.driver.set_page_load_timeout(30)
        
    def cleanup_driver(self):
        """Cleanup WebDriver"""
        if self.driver:
            self.driver.quit()
            self.driver = None
    
    def audit_page(self, page_path: str) -> UIAuditResult:
        """Audit a single page"""
        url = f"{self.base_url}{page_path}"
        result = UIAuditResult(page=page_path, url=url)
        
        try:
            # Measure load time
            start_time = time.time()
            self.driver.get(url)
            load_time = time.time() - start_time
            result.load_time = load_time
            
            # Get status code
            result.status_code = self._get_status_code()
            
            # Run all audit checks
            self._audit_accessibility(result)
            self._audit_performance(result)
            self._audit_responsiveness(result)
            self._audit_functionality(result)
            self._audit_consistency(result)
            self._audit_security(result)
            self._audit_seo(result)
            self._audit_usability(result)
            
            # Collect metrics
            result.metrics = self._collect_metrics()
            
        except Exception as e:
            result.issues.append(UIAuditIssue(
                id=f"page_load_error_{page_path}",
                category=UIAuditCategory.FUNCTIONALITY,
                severity=UIAuditSeverity.CRITICAL,
                title="Page Load Error",
                description=f"Failed to load page: {str(e)}",
                page=page_path
            ))
        
        return result
    
    def _get_status_code(self) -> int:
        """Get HTTP status code of current page"""
        try:
            # Use JavaScript to get status code
            status = self.driver.execute_script("return window.performance.getEntries()[0].responseStatus;")
            return status or 200
        except:
            return 200  # Default to 200 if we can't determine
    
    def _audit_accessibility(self, result: UIAuditResult):
        """Audit accessibility compliance"""
        try:
            # Check for alt text on images
            images = self.driver.find_elements(By.TAG_NAME, "img")
            for img in images:
                alt = img.get_attribute("alt")
                if not alt or alt.strip() == "":
                    result.issues.append(UIAuditIssue(
                        id=f"missing_alt_{hash(img.get_attribute('src') or '')}",
                        category=UIAuditCategory.ACCESSIBILITY,
                        severity=UIAuditSeverity.WARNING,
                        title="Missing Alt Text",
                        description="Image missing alt text for accessibility",
                        page=result.page,
                        element=img.get_attribute("src"),
                        recommendation="Add descriptive alt text to all images"
                    ))
            
            # Check for proper heading hierarchy
            headings = self.driver.find_elements(By.XPATH, "//h1|//h2|//h3|//h4|//h5|//h6")
            heading_levels = []
            for heading in headings:
                level = int(heading.tag_name[1])
                heading_levels.append(level)
            
            # Check for skipped heading levels
            for i in range(1, len(heading_levels)):
                if heading_levels[i] - heading_levels[i-1] > 1:
                    result.issues.append(UIAuditIssue(
                        id=f"heading_hierarchy_{i}",
                        category=UIAuditCategory.ACCESSIBILITY,
                        severity=UIAuditSeverity.WARNING,
                        title="Heading Hierarchy Issue",
                        description=f"Skipped heading level from h{heading_levels[i-1]} to h{heading_levels[i]}",
                        page=result.page,
                        recommendation="Use proper heading hierarchy without skipping levels"
                    ))
            
        except Exception as e:
            self.logger.error(f"Accessibility audit failed: {e}")
    
    def _audit_performance(self, result: UIAuditResult):
        """Audit page performance"""
        try:
            # Check page load time
            if result.load_time > 5.0:
                result.issues.append(UIAuditIssue(
                    id="slow_load_time",
                    category=UIAuditCategory.PERFORMANCE,
                    severity=UIAuditSeverity.WARNING,
                    title="Slow Page Load",
                    description=f"Page load time is {result.load_time:.2f}s (threshold: 5s)",
                    page=result.page,
                    recommendation="Optimize images, scripts, and reduce HTTP requests"
                ))
            elif result.load_time > 10.0:
                result.issues.append(UIAuditIssue(
                    id="very_slow_load_time",
                    category=UIAuditCategory.PERFORMANCE,
                    severity=UIAuditSeverity.ERROR,
                    title="Very Slow Page Load",
                    description=f"Page load time is {result.load_time:.2f}s (threshold: 10s)",
                    page=result.page,
                    recommendation="Significantly optimize page performance"
                ))
            
            # Check for large resources
            resources = self.driver.execute_script("""
                return window.performance.getEntries().filter(entry => entry.transferSize > 0);
            """)
            
            large_resources = [r for r in resources if r.get('transferSize', 0) > 1024 * 1024]  # > 1MB
            if large_resources:
                result.issues.append(UIAuditIssue(
                    id="large_resources",
                    category=UIAuditCategory.PERFORMANCE,
                    severity=UIAuditSeverity.WARNING,
                    title="Large Resources Detected",
                    description=f"Found {len(large_resources)} resources larger than 1MB",
                    page=result.page,
                    recommendation="Optimize or compress large resources"
                ))
            
        except Exception as e:
            self.logger.error(f"Performance audit failed: {e}")
    
    def _audit_responsiveness(self, result: UIAuditResult):
        """Audit responsive design"""
        try:
            # Test different viewport sizes
            viewport_sizes = [
                (1920, 1080),  # Desktop
                (768, 1024),   # Tablet
                (375, 667),    # Mobile
            ]
            
            for width, height in viewport_sizes:
                self.driver.set_window_size(width, height)
                time.sleep(0.5)  # Wait for layout adjustment
                
                # Check for horizontal scroll
                has_horizontal_scroll = self.driver.execute_script("""
                    return document.body.scrollWidth > window.innerWidth;
                """)
                
                if has_horizontal_scroll:
                    result.issues.append(UIAuditIssue(
                        id=f"horizontal_scroll_{width}x{height}",
                        category=UIAuditCategory.RESPONSIVENESS,
                        severity=UIAuditSeverity.ERROR,
                        title="Horizontal Scroll Detected",
                        description=f"Page has horizontal scroll at {width}x{height}",
                        page=result.page,
                        recommendation="Fix layout to prevent horizontal scrolling"
                    ))
            
            # Reset to desktop size
            self.driver.set_window_size(1920, 1080)
            
        except Exception as e:
            self.logger.error(f"Responsiveness audit failed: {e}")
    
    def _audit_functionality(self, result: UIAuditResult):
        """Audit page functionality"""
        try:
            # Check for broken links
            links = self.driver.find_elements(By.TAG_NAME, "a")
            broken_links = []
            
            for link in links[:10]:  # Check first 10 links to avoid timeout
                href = link.get_attribute("href")
                if href and href.startswith("http"):
                    try:
                        response = requests.head(href, timeout=5)
                        if response.status_code >= 400:
                            broken_links.append(href)
                    except:
                        broken_links.append(href)
            
            if broken_links:
                result.issues.append(UIAuditIssue(
                    id="broken_links",
                    category=UIAuditCategory.FUNCTIONALITY,
                    severity=UIAuditSeverity.ERROR,
                    title="Broken Links Detected",
                    description=f"Found {len(broken_links)} broken links",
                    page=result.page,
                    metadata={"broken_links": broken_links[:5]},  # Store first 5
                    recommendation="Fix or remove broken links"
                ))
            
            # Check for JavaScript errors
            js_errors = self.driver.execute_script("""
                return window.errors || [];
            """)
            
            if js_errors:
                result.issues.append(UIAuditIssue(
                    id="javascript_errors",
                    category=UIAuditCategory.FUNCTIONALITY,
                    severity=UIAuditSeverity.ERROR,
                    title="JavaScript Errors Detected",
                    description=f"Found {len(js_errors)} JavaScript errors",
                    page=result.page,
                    metadata={"errors": js_errors[:3]},  # Store first 3
                    recommendation="Fix JavaScript errors"
                ))
            
        except Exception as e:
            self.logger.error(f"Functionality audit failed: {e}")
    
    def _audit_consistency(self, result: UIAuditResult):
        """Audit UI consistency"""
        try:
            # Check for consistent color scheme
            colors = self.driver.execute_script("""
                var elements = document.querySelectorAll('*');
                var colors = new Set();
                elements.forEach(el => {
                    var style = window.getComputedStyle(el);
                    var color = style.color;
                    if (color && color !== 'rgba(0, 0, 0, 0)' && color !== 'rgb(0, 0, 0)') {
                        colors.add(color);
                    }
                });
                return Array.from(colors);
            """)
            
            if len(colors) > 20:
                result.issues.append(UIAuditIssue(
                    id="too_many_colors",
                    category=UIAuditCategory.CONSISTENCY,
                    severity=UIAuditSeverity.WARNING,
                    title="Too Many Colors",
                    description=f"Page uses {len(colors)} different colors",
                    page=result.page,
                    recommendation="Reduce color palette for better consistency"
                ))
            
            # Check for consistent font sizes
            font_sizes = self.driver.execute_script("""
                var elements = document.querySelectorAll('*');
                var sizes = new Set();
                elements.forEach(el => {
                    var style = window.getComputedStyle(el);
                    var size = style.fontSize;
                    if (size && size !== '0px') {
                        sizes.add(size);
                    }
                });
                return Array.from(sizes);
            """)
            
            if len(font_sizes) > 15:
                result.issues.append(UIAuditIssue(
                    id="too_many_font_sizes",
                    category=UIAuditCategory.CONSISTENCY,
                    severity=UIAuditSeverity.WARNING,
                    title="Too Many Font Sizes",
                    description=f"Page uses {len(font_sizes)} different font sizes",
                    page=result.page,
                    recommendation="Standardize font sizes for better consistency"
                ))
            
        except Exception as e:
            self.logger.error(f"Consistency audit failed: {e}")
    
    def _audit_security(self, result: UIAuditResult):
        """Audit security issues"""
        try:
            # Check for mixed content
            mixed_content = self.driver.execute_script("""
                var resources = document.querySelectorAll('img, script, link');
                var mixed = [];
                resources.forEach(res => {
                    var src = res.src || res.href;
                    if (src && window.location.protocol === 'https:' && src.startsWith('http:')) {
                        mixed.push(src);
                    }
                });
                return mixed;
            """)
            
            if mixed_content:
                result.issues.append(UIAuditIssue(
                    id="mixed_content",
                    category=UIAuditCategory.SECURITY,
                    severity=UIAuditSeverity.ERROR,
                    title="Mixed Content Detected",
                    description=f"Found {len(mixed_content)} HTTP resources on HTTPS page",
                    page=result.page,
                    recommendation="Use HTTPS for all resources"
                ))
            
            # Check for console errors (security-related)
            console_errors = self.driver.execute_script("""
                return window.console.errors || [];
            """)
            
            security_errors = [e for e in console_errors if any(keyword in str(e).lower() for keyword in ['security', 'xss', 'csrf'])]
            if security_errors:
                result.issues.append(UIAuditIssue(
                    id="security_errors",
                    category=UIAuditCategory.SECURITY,
                    severity=UIAuditSeverity.ERROR,
                    title="Security Errors in Console",
                    description=f"Found {len(security_errors)} security-related console errors",
                    page=result.page,
                    recommendation="Fix security-related errors"
                ))
            
        except Exception as e:
            self.logger.error(f"Security audit failed: {e}")
    
    def _audit_seo(self, result: UIAuditResult):
        """Audit SEO compliance"""
        try:
            # Check for title tag
            title = self.driver.find_elements(By.TAG_NAME, "title")
            if not title or not title[0].text.strip():
                result.issues.append(UIAuditIssue(
                    id="missing_title",
                    category=UIAuditCategory.SEO,
                    severity=UIAuditSeverity.ERROR,
                    title="Missing Page Title",
                    description="Page is missing a title tag",
                    page=result.page,
                    recommendation="Add a descriptive title tag"
                ))
            
            # Check for meta description
            meta_desc = self.driver.find_elements(By.XPATH, "//meta[@name='description']")
            if not meta_desc:
                result.issues.append(UIAuditIssue(
                    id="missing_meta_description",
                    category=UIAuditCategory.SEO,
                    severity=UIAuditSeverity.WARNING,
                    title="Missing Meta Description",
                    description="Page is missing meta description",
                    page=result.page,
                    recommendation="Add a meta description for better SEO"
                ))
            
            # Check for heading structure
            h1_tags = self.driver.find_elements(By.TAG_NAME, "h1")
            if len(h1_tags) == 0:
                result.issues.append(UIAuditIssue(
                    id="missing_h1",
                    category=UIAuditCategory.SEO,
                    severity=UIAuditSeverity.WARNING,
                    title="Missing H1 Tag",
                    description="Page is missing an H1 tag",
                    page=result.page,
                    recommendation="Add an H1 tag for better SEO"
                ))
            elif len(h1_tags) > 1:
                result.issues.append(UIAuditIssue(
                    id="multiple_h1",
                    category=UIAuditCategory.SEO,
                    severity=UIAuditCategory.WARNING,
                    title="Multiple H1 Tags",
                    description=f"Page has {len(h1_tags)} H1 tags",
                    page=result.page,
                    recommendation="Use only one H1 tag per page"
                ))
            
        except Exception as e:
            self.logger.error(f"SEO audit failed: {e}")
    
    def _audit_usability(self, result: UIAuditResult):
        """Audit usability issues"""
        try:
            # Check for form labels
            inputs = self.driver.find_elements(By.XPATH, "//input[@type='text' or @type='email' or @type='password']")
            unlabeled_inputs = []
            
            for input_elem in inputs:
                label = input_elem.find_element(By.XPATH, "./preceding::label[1]") if input_elem.find_elements(By.XPATH, "./preceding::label[1]") else None
                placeholder = input_elem.get_attribute("placeholder")
                aria_label = input_elem.get_attribute("aria-label")
                
                if not label and not placeholder and not aria_label:
                    unlabeled_inputs.append(input_elem)
            
            if unlabeled_inputs:
                result.issues.append(UIAuditIssue(
                    id="unlabeled_inputs",
                    category=UIAuditCategory.USABILITY,
                    severity=UIAuditSeverity.WARNING,
                    title="Unlabeled Form Inputs",
                    description=f"Found {len(unlabeled_inputs)} unlabeled form inputs",
                    page=result.page,
                    recommendation="Add labels or placeholders to all form inputs"
                ))
            
            # Check for button accessibility
            buttons = self.driver.find_elements(By.TAG_NAME, "button")
            buttons_without_text = []
            
            for button in buttons:
                text = button.text.strip()
                aria_label = button.get_attribute("aria-label")
                title_attr = button.get_attribute("title")
                
                if not text and not aria_label and not title_attr:
                    buttons_without_text.append(button)
            
            if buttons_without_text:
                result.issues.append(UIAuditIssue(
                    id="buttons_without_text",
                    category=UIAuditCategory.USABILITY,
                    severity=UIAuditCategory.WARNING,
                    title="Buttons Without Text",
                    description=f"Found {len(buttons_without_text)} buttons without accessible text",
                    page=result.page,
                    recommendation="Add text or aria-label to all buttons"
                ))
            
        except Exception as e:
            self.logger.error(f"Usability audit failed: {e}")
    
    def _collect_metrics(self) -> Dict[str, Any]:
        """Collect page metrics"""
        try:
            metrics = self.driver.execute_script("""
                return {
                    dom_size: document.querySelectorAll('*').length,
                    image_count: document.querySelectorAll('img').length,
                    script_count: document.querySelectorAll('script').length,
                    link_count: document.querySelectorAll('link').length,
                    form_count: document.querySelectorAll('form').length,
                    button_count: document.querySelectorAll('button').length,
                    input_count: document.querySelectorAll('input').length,
                    has_console_errors: window.console.errors ? window.console.errors.length : 0,
                    page_height: document.body.scrollHeight,
                    page_width: document.body.scrollWidth
                };
            """)
            return metrics
        except Exception as e:
            self.logger.error(f"Metrics collection failed: {e}")
            return {}
    
    def audit_all_pages(self, pages: List[str]) -> List[UIAuditResult]:
        """Audit multiple pages"""
        self.setup_driver()
        
        try:
            for page in pages:
                self.logger.info(f"Auditing page: {page}")
                result = self.audit_page(page)
                self.results.append(result)
                
                # Brief pause between pages
                time.sleep(1)
                
        finally:
            self.cleanup_driver()
        
        return self.results
    
    def generate_report(self) -> Dict[str, Any]:
        """Generate comprehensive audit report"""
        if not self.results:
            return {"error": "No audit results available"}
        
        total_issues = sum(r.issue_count for r in self.results)
        critical_issues = sum(r.critical_issues for r in self.results)
        error_issues = sum(r.error_issues for r in self.results)
        warning_issues = sum(r.warning_issues for r in self.results)
        
        # Group issues by category
        issues_by_category = {}
        issues_by_severity = {}
        
        for result in self.results:
            for issue in result.issues:
                category = issue.category.value
                severity = issue.severity.value
                
                if category not in issues_by_category:
                    issues_by_category[category] = []
                if severity not in issues_by_severity:
                    issues_by_severity[severity] = []
                
                issues_by_category[category].append(issue)
                issues_by_severity[severity].append(issue)
        
        # Calculate average load time
        avg_load_time = sum(r.load_time for r in self.results) / len(self.results)
        
        return {
            "summary": {
                "total_pages": len(self.results),
                "total_issues": total_issues,
                "critical_issues": critical_issues,
                "error_issues": error_issues,
                "warning_issues": warning_issues,
                "avg_load_time": round(avg_load_time, 2),
                "audit_timestamp": datetime.now().isoformat()
            },
            "pages": [
                {
                    "page": r.page,
                    "url": r.url,
                    "status_code": r.status_code,
                    "load_time": round(r.load_time, 2),
                    "issue_count": r.issue_count,
                    "critical_issues": r.critical_issues,
                    "error_issues": r.error_issues,
                    "warning_issues": r.warning_issues,
                    "issues": [
                        {
                            "id": issue.id,
                            "category": issue.category.value,
                            "severity": issue.severity.value,
                            "title": issue.title,
                            "description": issue.description,
                            "recommendation": issue.recommendation
                        }
                        for issue in r.issues
                    ]
                }
                for r in self.results
            ],
            "issues_by_category": {
                cat: len(issues) for cat, issues in issues_by_category.items()
            },
            "issues_by_severity": {
                sev: len(issues) for sev, issues in issues_by_severity.items()
            }
        }
    
    def save_report(self, filename: str = None) -> str:
        """Save audit report to file"""
        if not filename:
            filename = f"ui_audit_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        report = self.generate_report()
        
        with open(filename, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        return filename

# Convenience function for quick audit
def quick_ui_audit(pages: List[str] = None, base_url: str = "http://localhost:8000") -> Dict[str, Any]:
    """Quick UI audit for common pages"""
    if pages is None:
        pages = [
            "/",
            "/dashboard",
            "/simple-dashboard",
            "/api-contracts",
            "/mode-management",
            "/observability",
            "/unified.html"
        ]
    
    auditor = UIAuditor(base_url=base_url)
    results = auditor.audit_all_pages(pages)
    report = auditor.generate_report()
    
    # Save report
    filename = auditor.save_report()
    print(f"UI Audit report saved to: {filename}")
    
    return report
