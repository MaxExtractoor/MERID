#!/usr/bin/env python3
"""Run tests in clean environment with plugin autoloading disabled."""

import os
import sys
import subprocess

# Disable plugin autoloading
os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"

# Use the venv python
venv_python = r".venv\Scripts\python.exe"
if not os.path.exists(venv_python):
    venv_python = sys.executable  # fallback

def run_test(test_path, output_file):
    """Run a test and save output."""
    cmd = [
        venv_python, "-m", "pytest", test_path, "-vv", "--tb=short",
        "-p", "no:langsmith",
        "-p", "no:charset_normalizer"
    ]
    
    print(f"Running: {' '.join(cmd)}")
    
    result = subprocess.run(
        cmd,
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
    
    # Print key lines
    lines = result.stdout.split("\n")
    for line in lines:
        if any(x in line for x in ["passed", "failed", "error", "PASSED", "FAILED", "ERROR", "::"]):
            print(line)
    
    return result.returncode

print("="*70)
print("RUNNING RISK ENFORCEMENT TESTS")
print("="*70)
risk_rc = run_test("tests/risk/test_unified_risk_enforcement.py", "risk_test_results.txt")

print("\n" + "="*70)
print("RUNNING PASS 9 SCENARIO TESTS")
print("="*70)
scenario_rc = run_test("tests/scenario/test_pass9_scenarios.py", "scenario_test_results.txt")

print("\n" + "="*70)
print("SUMMARY")
print("="*70)
print(f"Risk tests: {'PASS' if risk_rc == 0 else 'FAIL'} (return code {risk_rc})")
print(f"Scenario tests: {'PASS' if scenario_rc == 0 else 'FAIL'} (return code {scenario_rc})")

sys.exit(max(risk_rc, scenario_rc))
