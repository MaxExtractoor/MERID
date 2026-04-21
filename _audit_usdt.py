#!/usr/bin/env python3
"""Audit script to find all USDT usage in codebase."""
import os
import sys

def find_usdt_usage():
    """Find all files containing USDT."""
    usdt_occurrences = []
    base_path = r'c:\Dev\MERID'
    
    for root, dirs, files in os.walk(base_path):
        # Skip .claude directories and this script
        dirs[:] = [d for d in dirs if d not in ('.claude', '.git', '__pycache__')]
        
        for file in files:
            if file.endswith('.py') and file != '_audit_usdt.py':
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        if 'USDT' in content:
                            lines = content.split('\n')
                            for i, line in enumerate(lines, 1):
                                if 'USDT' in line:
                                    rel_path = os.path.relpath(filepath, base_path)
                                    usdt_occurrences.append((rel_path, i, line.strip()))
                except Exception as e:
                    pass
    
    return usdt_occurrences

if __name__ == '__main__':
    results = find_usdt_usage()
    
    # Group by file
    by_file = {}
    for path, line_num, line in results:
        if path not in by_file:
            by_file[path] = []
        by_file[path].append((line_num, line))
    
    # Print summary
    print("=" * 80)
    print("USDT USAGE INVENTORY")
    print("=" * 80)
    print(f"\nTotal USDT occurrences: {len(results)}")
    print(f"Files affected: {len(by_file)}")
    print()
    
    # Print by file
    for path in sorted(by_file.keys()):
        print(f"\n{path}")
        for line_num, line in by_file[path]:
            # Truncate long lines
            if len(line) > 100:
                line = line[:97] + "..."
            print(f"  Line {line_num}: {line}")
    
    print(f"\n{'=' * 80}")
    print("END OF INVENTORY")
    print("=" * 80)
