#!/usr/bin/env python3
"""Run tests and capture output."""

import subprocess
import sys

def run_test(test_path, output_file):
    """Run a test and save output to file."""
    print(f"Running: pytest {test_path} -v --tb=short")
    
    result = subprocess.run(
        [sys.executable, "-m", "pytest", test_path, "-v", "--tb=short"],
        capture_output=True,
        text=True,
        cwd=r"c:\Dev\MERID"
    )
    
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("=== STDOUT ===\n")
        f.write(result.stdout)
        f.write("\n=== STDERR ===\n")
        f.write(result.stderr)
        f.write(f"\n=== RETURN CODE: {result.returncode} ===\n")
    
    # Print summary
    lines = result.stdout.split("\n")
    for line in lines:
        if "passed" in line or "failed" in line or "error" in line or "PASSED" in line or "FAILED" in line:
            print(line)
    
    print(f"Output saved to: {output_file}")
    return result.returncode

# Run risk tests
print("\n" + "="*70)
print("RUNNING RISK ENFORCEMENT TESTS")
print("="*70)
risk_rc = run_test("tests/risk/test_unified_risk_enforcement.py", "test_risk_output.txt")

# Run scenario tests  
print("\n" + "="*70)
print("RUNNING SCENARIO TESTS")
print("="*70)
scenario_rc = run_test("tests/scenario/test_pass9_scenarios.py", "test_scenario_output.txt")

print("\n" + "="*70)
print("SUMMARY")
print("="*70)
print(f"Risk tests return code: {risk_rc}")
print(f"Scenario tests return code: {scenario_rc}")

if risk_rc == 0 and scenario_rc == 0:
    print("✓ ALL TESTS PASSED")
else:
    print("✗ SOME TESTS FAILED")
    
sys.exit(max(risk_rc, scenario_rc))
