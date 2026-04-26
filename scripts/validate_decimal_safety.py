"""Decimal Type Safety Validator for MERID trading system.

Scans codebase for dangerous float/Decimal mixing patterns that cause:
- TypeError: unsupported operand type(s) for float and Decimal
- Precision loss in financial calculations
- Silent rounding errors in position sizing

Usage: python scripts/validate_decimal_safety.py
"""

from decimal import Decimal, InvalidOperation
import re
from pathlib import Path
from typing import List, Dict, Any, Tuple


class DecimalSafetyValidator:
    """Automated validator for Decimal type safety."""

    # Dangerous patterns that indicate float/Decimal mixing
    DANGEROUS_PATTERNS: List[Tuple[str, str, int]] = [
        # Pattern, description, severity (0=info, 1=warn, 2=error)
        (r'Decimal\([^)]+\)\s*([\+\-\*/])\s*(?!Decimal|"|\d+\")[^\s]+', 
         'Decimal arithmetic with non-Decimal operand', 2),
        (r'float\([^)]*Decimal[^)]*\)', 
         'Casting Decimal to float loses precision', 2),
        (r'Decimal\([^)]*float\([^)]*\)[^)]*\)', 
         'Creating Decimal from float loses precision', 2),
        (r'json\.loads.*(?:price|cents|spot|edge|pnl|balance|equity|notional)', 
         'JSON parse of financial data needs Decimal conversion', 1),
        (r'\.get\(["\'].*(?:price|cents|spot|edge|pnl|balance|equity|notional)', 
         'Dict.get() for price data may return float/int', 1),
        (r'(?:price|cents|balance|equity|notional|pnl)\s*=\s*[\d.]+(?![)"])\s*$', 
         'Numeric literal should be Decimal("...")', 1),
        (r'bankroll.*=.*float|equity.*=.*float|balance.*=.*float', 
         'Float assignment to financial variable', 2),
        (r'np\.array.*(?:price|cents|pnl)|pd\.DataFrame.*(?:price|cents)', 
         'NumPy/Pandas operations on price data (converts to float64)', 1),
        (r'\.quantize\(', 
         'Decimal quantize (good - verify first arg is Decimal)', 0),
    ]

    # Files to exclude from scanning
    EXCLUDE_PATTERNS = [
        'venv', '__pycache__', '.git', 'node_modules',
        'test_', '_test.py', 'tests/', 'archive/', 'legacy', 'mock'
    ]

    def __init__(self, root_dir: str = 'c:\\Dev\\MERID'):
        self.root_dir = Path(root_dir)
        self.violations: List[Dict[str, Any]] = []
        self.warnings: List[Dict[str, Any]] = []
        self.info: List[Dict[str, Any]] = []

    def should_exclude(self, filepath: Path) -> bool:
        """Check if file should be excluded from scanning."""
        path_str = str(filepath)
        return any(pattern in path_str for pattern in self.EXCLUDE_PATTERNS)

    def scan_file(self, filepath: Path) -> None:
        """Scan single file for type safety violations."""
        try:
            content = filepath.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            return

        lines = content.split('\n')

        for pattern, message, severity in self.DANGEROUS_PATTERNS:
            for line_num, line in enumerate(lines, 1):
                if re.search(pattern, line):
                    entry = {
                        'file': str(filepath),
                        'line': line_num,
                        'pattern': pattern,
                        'message': message,
                        'code': line.strip(),
                        'severity': severity
                    }
                    if severity == 2:
                        self.violations.append(entry)
                    elif severity == 1:
                        self.warnings.append(entry)
                    else:
                        self.info.append(entry)

    def scan_codebase(self) -> Dict[str, Any]:
        """Scan entire codebase."""
        for py_file in self.root_dir.rglob('*.py'):
            if self.should_exclude(py_file):
                continue
            self.scan_file(py_file)

        return {
            'violations': self.violations,
            'warnings': self.warnings,
            'info': self.info,
            'total_violations': len(self.violations),
            'total_warnings': len(self.warnings),
            'total_info': len(self.info),
            'status': 'FAIL' if len(self.violations) > 0 else 'PASS'
        }

    def print_report(self, results: Dict[str, Any]) -> None:
        """Print formatted report."""
        print(f"\n{'='*80}")
        print(f"DECIMAL TYPE SAFETY SCAN RESULTS")
        print(f"{'='*80}")
        print(f"Status: {results['status']}")
        print(f"Violations (CRITICAL): {results['total_violations']}")
        print(f"Warnings (HIGH): {results['total_warnings']}")
        print(f"Info (MEDIUM): {results['total_info']}")
        print()

        if results['violations']:
            print(f"{'='*80}")
            print("CRITICAL VIOLATIONS (Must Fix)")
            print(f"{'='*80}")
            for v in results['violations']:
                print(f"\n{v['file']}:{v['line']}")
                print(f"  Issue: {v['message']}")
                print(f"  Code: {v['code']}")
            print()

        if results['warnings']:
            print(f"{'='*80}")
            print("WARNINGS (Review Recommended)")
            print(f"{'='*80}")
            for w in results['warnings']:
                print(f"\n{w['file']}:{w['line']}")
                print(f"  Issue: {w['message']}")
                print(f"  Code: {w['code']}")
            print()

        if results['status'] == 'PASS':
            print("✅ All critical checks passed!")
        else:
            print(f"❌ Found {results['total_violations']} critical violation(s)")


def validate_decimal_conversions() -> List[str]:
    """Validate common Decimal conversion patterns."""
    errors = []
    
    # Test valid conversions
    test_cases = [
        ("123.45", Decimal("123.45")),
        (100, Decimal("100")),
        (123.456, None),  # Float input should be avoided
    ]
    
    for input_val, expected in test_cases:
        try:
            if isinstance(input_val, float):
                # This is the dangerous pattern we want to catch
                result = Decimal(input_val)  # noqa
                errors.append(f"DANGER: Decimal({input_val}) creates Decimal('{result}') with float imprecision")
            else:
                result = Decimal(str(input_val))
                if expected and result != expected:
                    errors.append(f"Decimal conversion mismatch: {input_val} -> {result} != {expected}")
        except InvalidOperation as e:
            errors.append(f"InvalidOperation for {input_val}: {e}")
    
    return errors


if __name__ == '__main__':
    validator = DecimalSafetyValidator()
    results = validator.scan_codebase()
    validator.print_report(results)
    
    # Also run conversion validation
    print(f"\n{'='*80}")
    print("CONVERSION VALIDATION")
    print(f"{'='*80}")
    conversion_errors = validate_decimal_conversions()
    if conversion_errors:
        for err in conversion_errors:
            print(f"  ⚠️  {err}")
    else:
        print("  ✅ Conversion patterns valid")
    
    exit(0 if results['status'] == 'PASS' and not conversion_errors else 1)
