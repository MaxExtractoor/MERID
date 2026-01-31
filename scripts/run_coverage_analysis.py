"""
Script to run test coverage analysis.
"""

import sys
sys.path.insert(0, 'c:/Dev/MERID')

from qa.test_coverage_analyzer import run_coverage_analysis

if __name__ == "__main__":
    summary = run_coverage_analysis('c:/Dev/MERID', 'c:/Dev/MERID/TEST_COVERAGE_REPORT.md')
    
    print("\n=== TEST COVERAGE SUMMARY ===")
    print(f"Total Modules: {summary['total_modules']}")
    print(f"Tested Modules: {summary['tested_modules']}")
    print(f"Untested Modules: {summary['untested_modules']}")
    print(f"Coverage: {summary['coverage_percentage']:.1f}%")
    print(f"Critical Untested: {summary['critical_untested']}")
    print(f"Total Test Files: {summary['total_test_files']}")
    print(f"\nReport: TEST_COVERAGE_REPORT.md")
