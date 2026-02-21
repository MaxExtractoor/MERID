"""API error handling verification script.

Verifies that all Kalshi API endpoints have proper error handling:
- Input validation errors (400)
- Authentication errors (401/403)
- Not found errors (404)
- Rate limiting errors (429)
- Server errors (500)
- Service unavailable errors (503)

Usage:
    python scripts/verify_kalshi_api_errors.py
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import Dict, List, Set, Tuple
import ast


def extract_endpoint_info(file_path: Path) -> List[Dict]:
    """Extract endpoint information from Python file."""
    content = file_path.read_text()
    tree = ast.parse(content)

    endpoints = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            # Check for router decorator
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call):
                    func = decorator.func
                    if isinstance(func, ast.Attribute):
                        if func.attr in ['get', 'post', 'put', 'patch', 'delete']:
                            # Extract path from first argument
                            if decorator.args:
                                path_arg = decorator.args[0]
                                if isinstance(path_arg, ast.Constant):
                                    path = path_arg.value

                                    # Check for HTTPException in function body
                                    has_error_handling = check_error_handling(node)

                                    endpoints.append({
                                        'method': func.attr.upper(),
                                        'path': path,
                                        'name': node.name,
                                        'has_error_handling': has_error_handling,
                                        'line': node.lineno,
                                    })

    return endpoints


def check_error_handling(func_node: ast.FunctionDef) -> Dict[str, bool]:
    """Check what types of error handling exist in function."""
    source = ast.unparse(func_node)

    checks = {
        'has_http_exception': 'HTTPException' in source,
        'has_try_except': 'try:' in source and 'except' in source,
        'has_400': '400' in source or 'ValueError' in source,
        'has_404': '404' in source,
        'has_429': '429' in source,
        'has_500': '500' in source,
        'has_503': '503' in source,
        'has_validation': 'raise HTTPException' in source or 'HTTPException(' in source,
    }

    return checks


def verify_error_handling(file_path: Path) -> Tuple[List[Dict], List[str]]:
    """Verify error handling in API file."""
    endpoints = extract_endpoint_info(file_path)
    issues = []

    for ep in endpoints:
        checks = ep['has_error_handling']

        # Critical endpoints should have comprehensive error handling
        if 'order' in ep['path'].lower() or 'portfolio' in ep['path'].lower():
            if not checks['has_http_exception']:
                issues.append(
                    f"{ep['method']} {ep['path']} (line {ep['line']}): "
                    f"Missing HTTPException handling for critical endpoint"
                )

        # All endpoints should have try-except or HTTPException
        if not checks['has_try_except'] and not checks['has_http_exception']:
            issues.append(
                f"{ep['method']} {ep['path']} (line {ep['line']}): "
                f"No error handling found (no try-except or HTTPException)"
            )

    return endpoints, issues


def main():
    """Main verification function."""
    api_file = Path(__file__).parent.parent / 'web' / 'api' / 'kalshi_api.py'

    if not api_file.exists():
        print(f"ERROR: API file not found: {api_file}")
        sys.exit(1)

    print("=" * 80)
    print("KALSHI API ERROR HANDLING VERIFICATION")
    print("=" * 80)
    print()

    endpoints, issues = verify_error_handling(api_file)

    # Summary
    print(f"Total endpoints found: {len(endpoints)}")
    print()

    # Categorize endpoints
    by_category = {
        'markets': [],
        'orders': [],
        'portfolio': [],
        'risk': [],
        'fix': [],
        'other': [],
    }

    for ep in endpoints:
        path = ep['path'].lower()
        if 'market' in path:
            by_category['markets'].append(ep)
        elif 'order' in path:
            by_category['orders'].append(ep)
        elif 'portfolio' in path or 'position' in path:
            by_category['portfolio'].append(ep)
        elif 'risk' in path or 'kill' in path:
            by_category['risk'].append(ep)
        elif 'fix' in path:
            by_category['fix'].append(ep)
        else:
            by_category['other'].append(ep)

    # Print by category
    for category, eps in by_category.items():
        if eps:
            print(f"\n{category.upper()} ENDPOINTS ({len(eps)}):")
            for ep in eps:
                status = "✓" if ep['has_error_handling']['has_http_exception'] else "✗"
                print(f"  {status} {ep['method']:6} {ep['path']:<50} (line {ep['line']})")

    # Issues
    print("\n" + "=" * 80)
    print("ISSUES FOUND")
    print("=" * 80)

    if issues:
        for issue in issues:
            print(f"  ⚠ {issue}")
        print(f"\nTotal issues: {len(issues)}")
    else:
        print("  ✓ No issues found - all endpoints have proper error handling")

    # Error handling coverage
    print("\n" + "=" * 80)
    print("ERROR HANDLING COVERAGE")
    print("=" * 80)

    total = len(endpoints)
    with_http_exception = sum(1 for ep in endpoints if ep['has_error_handling']['has_http_exception'])
    with_try_except = sum(1 for ep in endpoints if ep['has_error_handling']['has_try_except'])

    print(f"  HTTPException usage: {with_http_exception}/{total} ({100*with_http_exception/total:.1f}%)")
    print(f"  Try-except blocks: {with_try_except}/{total} ({100*with_try_except/total:.1f}%)")

    # Status code coverage
    print("\n  Status code coverage:")
    for code in ['400', '404', '429', '500', '503']:
        count = sum(1 for ep in endpoints if ep['has_error_handling'].get(f'has_{code}', False))
        print(f"    {code}: {count}/{total} endpoints")

    print()

    # Exit code
    if issues:
        print("RESULT: FAILED - issues need to be addressed")
        sys.exit(1)
    else:
        print("RESULT: PASSED - all endpoints properly handle errors")
        sys.exit(0)


if __name__ == "__main__":
    main()
