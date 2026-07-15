"""Legacy test audit script.

This script audits the test suite to identify potentially obsolete or legacy tests
that could be archived to maintain a clean production test suite.

Audit Criteria:
1. Tests that import from legacy modules
2. Tests with "legacy" in filename or content
3. Tests that reference archived functionality
4. Tests with old date prefixes that may be obsolete
"""

import os
import re
from pathlib import Path
from typing import List, Dict, Set


class LegacyTestAuditor:
    """Audits test files for legacy/obsolete content."""

    def __init__(self, tests_dir: str):
        self.tests_dir = Path(tests_dir)
        self.legacy_patterns = [
            r'archive\.legacy',
            r'from\s+merid\.legacy',
            r'import\s+.*legacy',
            r'legacy\.',
            r'#\s*LEGACY',
            r'#\s*DEPRECATED',
            r'#\s*TODO.*archive',
        ]
        self.obsolete_date_patterns = [
            r'test_2024_',
            r'test_2025_01_',
            r'test_2025_02_',
            r'test_2025_03_',
            r'test_2025_04_',
            r'test_2025_05_',
        ]

    def find_all_test_files(self) -> List[Path]:
        """Find all Python test files."""
        test_files = []
        for root, dirs, files in os.walk(self.tests_dir):
            # Skip __pycache__ and hidden directories
            dirs[:] = [d for d in dirs if not d.startswith('_') and not d.startswith('.')]
            for file in files:
                if file.startswith('test_') and file.endswith('.py'):
                    test_files.append(Path(root) / file)
        return test_files

    def check_file_for_legacy(self, file_path: Path) -> Dict[str, any]:
        """Check a single test file for legacy indicators."""
        result = {
            'path': str(file_path.relative_to(self.tests_dir)),
            'has_legacy_imports': False,
            'has_legacy_comments': False,
            'has_obsolete_date': False,
            'legacy_references': [],
            'size_kb': file_path.stat().st_size / 1024,
        }

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                
                # Check for legacy imports
                for pattern in self.legacy_patterns:
                    if re.search(pattern, content, re.IGNORECASE):
                        result['has_legacy_imports'] = True
                        result['legacy_references'].append(pattern)
                        break
                
                # Check for legacy comments
                if re.search(r'#\s*(LEGACY|DEPRECATED|OBSOLETE)', content, re.IGNORECASE):
                    result['has_legacy_comments'] = True
                
                # Check for obsolete date patterns
                for pattern in self.obsolete_date_patterns:
                    if re.search(pattern, file_path.name):
                        result['has_obsolete_date'] = True
                        break
        except Exception as e:
            result['error'] = str(e)

        return result

    def audit_all_tests(self) -> Dict[str, any]:
        """Audit all test files."""
        test_files = self.find_all_test_files()
        results = []
        
        for file_path in test_files:
            result = self.check_file_for_legacy(file_path)
            results.append(result)
        
        # Categorize results
        legacy_imports = [r for r in results if r['has_legacy_imports']]
        legacy_comments = [r for r in results if r['has_legacy_comments']]
        obsolete_dates = [r for r in results if r['has_obsolete_date']]
        clean_tests = [r for r in results if not any([
            r['has_legacy_imports'],
            r['has_legacy_comments'],
            r['has_obsolete_date']
        ])]
        
        return {
            'total_tests': len(results),
            'legacy_imports': legacy_imports,
            'legacy_comments': legacy_comments,
            'obsolete_dates': obsolete_dates,
            'clean_tests': clean_tests,
            'all_results': results
        }


def test_legacy_audit():
    """Test the legacy audit functionality."""
    auditor = LegacyTestAuditor('c:/Dev/MERID/tests')
    results = auditor.audit_all_tests()
    
    print(f"\n=== LEGACY TEST AUDIT REPORT ===")
    print(f"Total test files: {results['total_tests']}")
    print(f"Tests with legacy imports: {len(results['legacy_imports'])}")
    print(f"Tests with legacy comments: {len(results['legacy_comments'])}")
    print(f"Tests with obsolete dates: {len(results['obsolete_dates'])}")
    print(f"Clean tests: {len(results['clean_tests'])}")
    
    if results['legacy_imports']:
        print(f"\n=== TESTS WITH LEGACY IMPORTS ===")
        for test in results['legacy_imports']:
            print(f"  - {test['path']}")
            print(f"    References: {test['legacy_references']}")
    
    if results['obsolete_dates']:
        print(f"\n=== TESTS WITH OBSOLETE DATE PATTERNS ===")
        for test in results['obsolete_dates']:
            print(f"  - {test['path']}")
    
    # Assertions for test validation
    assert results['total_tests'] > 0, "Should find test files"
    assert isinstance(results['legacy_imports'], list), "Should return list"
    assert isinstance(results['clean_tests'], list), "Should return list"


if __name__ == '__main__':
    test_legacy_audit()
