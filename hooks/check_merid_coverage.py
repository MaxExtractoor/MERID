#!/usr/bin/env python3
"""
Custom coverage checker for MERID Tier 2 modules.
Enforces per-module coverage thresholds.
"""
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

THRESHOLDS = {
    "core.agent_orchestrator": 85.0,
    "core.cache_manager": 80.0,
    "core.observability_manager": 75.0,
    "core.persistence_manager": 70.0,
    "core.health_monitoring": 75.0,
}

def check_coverage(xml_file: str) -> bool:
    """Check coverage against per-module thresholds."""
    if not Path(xml_file).exists():
        print(f"ERROR: Coverage file {xml_file} not found")
        return False
    
    tree = ET.parse(xml_file)
    root = tree.getroot()
    
    all_passed = True
    for pkg in root.findall('.//package'):
        name = pkg.get('name')
        if name in THRESHOLDS:
            cov_pct = float(pkg.get('line-rate', 0)) * 100
            required = THRESHOLDS[name]
            if cov_pct < required:
                print(f"FAIL {name}: {cov_pct:.1f}% < {required}%")
                all_passed = False
            else:
                print(f"PASS {name}: {cov_pct:.1f}% >= {required}%")
    
    return all_passed

def main():
    """Run coverage check."""
    xml_file = "coverage.xml"
    
    # Run pytest for core modules (will generate coverage.xml)
    print("Running coverage for core modules...")
    result = subprocess.run([
        sys.executable, "-m", "pytest",
        "--cov-config=.coveragerc",
        "--cov=core",
        "--cov-report=xml:coverage.xml",
        "--cov-report=term",
        "tests/core/"
    ], capture_output=False)
    
    if result.returncode != 0:
        print("ERROR: pytest failed")
        sys.exit(1)
    
    # Check per-module thresholds
    if check_coverage(xml_file):
        print("PASS: All Tier 2 module thresholds met")
        sys.exit(0)
    else:
        print("FAIL: Some Tier 2 modules below threshold")
        sys.exit(1)

if __name__ == "__main__":
    main()
