#!/usr/bin/env python3
"""Script to analyze coverage gaps for autonomous fixing.

Usage:
    python analyze_coverage_gaps.py --threshold=85 --output=json
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def get_coverage_data():
    """Get coverage data from coverage.py."""
    try:
        result = subprocess.run(
            ["coverage", "json", "-o", "-"],
            capture_output=True,
            text=True
        )
        return json.loads(result.stdout)
    except Exception as e:
        print(f"Error getting coverage: {e}", file=sys.stderr)
        return {}


def identify_low_coverage_modules(coverage_data, threshold=85.0):
    """Identify modules below coverage threshold."""
    low_coverage = []
    
    files = coverage_data.get("files", {})
    
    for file_path, file_data in files.items():
        # Focus on Tier 2 modules
        if not ("core/" in file_path or "trading/router" in file_path or "trading/spectator" in file_path):
            continue
        
        summary = file_data.get("summary", {})
        percent_covered = summary.get("percent_covered", 0)
        
        if percent_covered < threshold:
            low_coverage.append({
                "file": file_path,
                "coverage": percent_covered,
                "missing_lines": summary.get("missing_lines", 0),
                "num_statements": summary.get("num_statements", 0)
            })
    
    # Sort by lowest coverage first
    low_coverage.sort(key=lambda x: x["coverage"])
    
    return low_coverage


def main():
    parser = argparse.ArgumentParser(description="Analyze coverage gaps")
    parser.add_argument("--threshold", type=float, default=85.0, help="Coverage threshold")
    parser.add_argument("--output", choices=["json", "text"], default="text", help="Output format")
    args = parser.parse_args()
    
    coverage_data = get_coverage_data()
    
    if not coverage_data:
        print("[]" if args.output == "json" else "No coverage data available")
        return
    
    low_coverage = identify_low_coverage_modules(coverage_data, args.threshold)
    
    if args.output == "json":
        print(json.dumps([m["file"] for m in low_coverage]))
    else:
        print(f"Modules below {args.threshold}% coverage:")
        print("-" * 60)
        for module in low_coverage:
            print(f"{module['file']:<50} {module['coverage']:>5.1f}%")
        print(f"\nTotal: {len(low_coverage)} modules need attention")


if __name__ == "__main__":
    main()
