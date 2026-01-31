"""
Script to run comprehensive codebase audit.
"""

import sys
sys.path.insert(0, 'c:/Dev/MERID')

from qa.codebase_audit_engine import run_audit

if __name__ == "__main__":
    summary = run_audit('c:/Dev/MERID', 'c:/Dev/MERID/CODEBASE_AUDIT_REPORT.md')
    
    print("\n=== AUDIT SUMMARY ===")
    print(f"Files: {summary['files_scanned']}")
    print(f"Lines: {summary['lines_scanned']}")
    print(f"Findings: {summary['total_findings']}")
    print(f"\nBy Severity:")
    print(f"  Critical: {summary['critical_count']}")
    print(f"  High: {summary['high_count']}")
    print(f"  Medium: {summary['medium_count']}")
    print(f"  Low: {summary['low_count']}")
    print(f"\nBy Category:")
    for category, count in summary['by_category'].items():
        print(f"  {category}: {count}")
    print(f"\nReport: CODEBASE_AUDIT_REPORT.md")
