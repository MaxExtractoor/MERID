#!/usr/bin/env python3
"""
Inventory and Classification Script for DISABLED and Legacy Code

This script scans the codebase for DISABLED and _legacy markers,
emits a CSV with classification data, and provides recommendations for triage.

Usage:
    python scripts/audit_inventory_disabled_legacy.py
    python scripts/audit_inventory_disabled_legacy.py --output inventory.csv
"""

import os
import re
import csv
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
import argparse


def scan_for_disabled_and_legacy(root_dir: Path) -> List[Dict[str, str]]:
    """Scan codebase for DISABLED and _legacy markers."""
    results = []
    
    # Patterns to search for
    disabled_pattern = re.compile(r'#\s*DISABLED|//\s*DISABLED|"""DISABLED|\'\'\'DISABLED', re.IGNORECASE)
    legacy_pattern = re.compile(r'_legacy|legacy_|LEGACY', re.IGNORECASE)
    
    # Scan Python files
    for py_file in root_dir.rglob("*.py"):
        # Skip test files and __pycache__
        if "__pycache__" in str(py_file) or "test" in py_file.name:
            continue
            
        try:
            with open(py_file, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Check for DISABLED marker
            disabled_match = disabled_pattern.search(content)
            has_disabled = disabled_match is not None
            
            # Check for legacy marker
            legacy_match = legacy_pattern.search(content)
            has_legacy = legacy_match is not None
            
            if has_disabled or has_legacy:
                # Get file stats
                stat = py_file.stat()
                last_modified = datetime.fromtimestamp(stat.st_mtime).isoformat()
                
                # Extract reason from comment if available
                reason = ""
                if has_disabled:
                    # Look for comment after DISABLED marker
                    lines = content.split('\n')
                    for i, line in enumerate(lines):
                        if disabled_pattern.search(line):
                            # Get next few lines for context
                            context_lines = lines[i:i+3]
                            reason = ' '.join(context_lines).strip()
                            # Truncate if too long
                            if len(reason) > 200:
                                reason = reason[:200] + "..."
                            break
                
                # Check for risk logic keywords
                risk_keywords = ['risk', 'kill', 'halt', 'circuit', 'limit', 'threshold', 'sizing', 'position']
                has_risk_logic = any(keyword in content.lower() for keyword in risk_keywords)
                
                results.append({
                    'path': str(py_file.relative_to(root_dir)),
                    'has_disabled': 'y' if has_disabled else 'n',
                    'has_legacy': 'y' if has_legacy else 'n',
                    'reason': reason,
                    'last_modified': last_modified,
                    'owner': '',  # To be filled manually
                    'contains_risk_logic': 'y' if has_risk_logic else 'n',
                    'file_size_bytes': stat.st_size,
                })
                
        except Exception as e:
            print(f"Error reading {py_file}: {e}")
    
    return results


def classify_results(results: List[Dict[str, str]]) -> Dict[str, List[Dict[str, str]]]:
    """Classify results into categories for manual triage."""
    categories = {
        'A_dead_infra': [],
        'B_parking_lot': [],
        'C_risk_logic': [],
        'D_unknown': [],
    }
    
    for result in results:
        # Auto-classification heuristics
        path_lower = result['path'].lower()
        
        # Category A: Dead infrastructure (not wired to production)
        if any(marker in path_lower for marker in ['disabled', 'archive', 'old', 'deprecated']):
            if result['contains_risk_logic'] == 'n':
                categories['A_dead_infra'].append(result)
            else:
                categories['C_risk_logic'].append(result)
        
        # Category C: Historical risk logic
        elif result['contains_risk_logic'] == 'y':
            categories['C_risk_logic'].append(result)
        
        # Category B: Parking-lot features (might be revived)
        elif any(marker in path_lower for marker in ['experimental', 'feature', 'alternative']):
            categories['B_parking_lot'].append(result)
        
        # Category D: Unknown - needs manual review
        else:
            categories['D_unknown'].append(result)
    
    return categories


def write_csv(results: List[Dict[str, str]], output_file: Path):
    """Write results to CSV file."""
    fieldnames = [
        'path', 'has_disabled', 'has_legacy', 'reason', 'last_modified',
        'owner', 'contains_risk_logic', 'file_size_bytes', 'category'
    ]
    
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for result in results:
            writer.writerow(result)


def print_summary(results: List[Dict[str, str]], categories: Dict[str, List[Dict[str, str]]]):
    """Print summary of findings."""
    total = len(results)
    disabled_count = sum(1 for r in results if r['has_disabled'] == 'y')
    legacy_count = sum(1 for r in results if r['has_legacy'] == 'y')
    risk_logic_count = sum(1 for r in results if r['contains_risk_logic'] == 'y')
    
    print(f"\n{'='*60}")
    print(f"DISABLED/Legacy Code Inventory Summary")
    print(f"{'='*60}")
    print(f"Total files with markers: {total}")
    print(f"  - DISABLED markers: {disabled_count}")
    print(f"  - Legacy markers: {legacy_count}")
    print(f"  - Contains risk logic: {risk_logic_count}")
    print()
    
    print("Auto-classification:")
    for category, items in categories.items():
        print(f"  {category}: {len(items)} files")
    print()
    
    print("Category A (Dead Infrastructure) - Safe to delete:")
    for item in categories['A_dead_infra']:
        print(f"  - {item['path']}")
    print()
    
    print("Category B (Parking-Lot Features) - Review before deletion:")
    for item in categories['B_parking_lot']:
        print(f"  - {item['path']}")
    print()
    
    print("Category C (Risk Logic) - REQUIRES EXPLICIT RISK REVIEW:")
    for item in categories['C_risk_logic']:
        print(f"  - {item['path']} (RISK LOGIC)")
    print()
    
    print("Category D (Unknown) - Manual review needed:")
    for item in categories['D_unknown']:
        print(f"  - {item['path']}")


def main():
    parser = argparse.ArgumentParser(description='Inventory DISABLED and legacy code')
    parser.add_argument('--output', '-o', type=str, help='Output CSV file path')
    parser.add_argument('--root', '-r', type=str, default='.', help='Root directory to scan')
    args = parser.parse_args()
    
    root_dir = Path(args.root)
    print(f"Scanning {root_dir} for DISABLED and legacy markers...")
    
    results = scan_for_disabled_and_legacy(root_dir)
    categories = classify_results(results)
    
    print_summary(results, categories)
    
    if args.output:
        # Add category to each result
        category_map = {}
        for cat_name, items in categories.items():
            for item in items:
                category_map[item['path']] = cat_name
        
        for result in results:
            result['category'] = category_map.get(result['path'], 'D_unknown')
        
        output_file = Path(args.output)
        write_csv(results, output_file)
        print(f"\nCSV written to {output_file}")
        print(f"Please manually review and fill in 'owner' field for each item.")
        print(f"Then re-classify as needed based on manual review.")


if __name__ == '__main__':
    main()
