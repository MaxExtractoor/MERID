#!/usr/bin/env python3
"""Execute tests and write results to file."""

import subprocess
import sys
import os

# Set the environment variable to disable plugin autoloading
os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"

def run_tests():
    """Run the test suites."""
    
    # Run risk tests
    print("Running risk enforcement tests...")
    risk_result = subprocess.run(
        [sys.executable, "-m", "pytest", 
         "tests/risk/test_unified_risk_enforcement.py", 
         "-vv", "--tb=short",
         "-p", "no:langsmith", "-p", "no:charset_normalizer"],
        capture_output=True,
        text=True,
        cwd="c:\\Dev\\MERID"
    )
    
    with open("test_results_risk.txt", "w", encoding="utf-8") as f:
        f.write("STDOUT:\n")
        f.write(risk_result.stdout)
        f.write("\n\nSTDERR:\n")
        f.write(risk_result.stderr)
        f.write(f"\n\nReturn code: {risk_result.returncode}\n")
    
    print(f"Risk tests complete: return code {risk_result.returncode}")
    print("Output saved to: test_results_risk.txt")
    
    # Run scenario tests
    print("\nRunning Pass 9 scenario tests...")
    scenario_result = subprocess.run(
        [sys.executable, "-m", "pytest", 
         "tests/scenario/test_pass9_scenarios.py", 
         "-vv", "--tb=short",
         "-p", "no:langsmith", "-p", "no:charset_normalizer"],
        capture_output=True,
        text=True,
        cwd="c:\\Dev\\MERID"
    )
    
    with open("test_results_scenario.txt", "w", encoding="utf-8") as f:
        f.write("STDOUT:\n")
        f.write(scenario_result.stdout)
        f.write("\n\nSTDERR:\n")
        f.write(scenario_result.stderr)
        f.write(f"\n\nReturn code: {scenario_result.returncode}\n")
    
    print(f"Scenario tests complete: return code {scenario_result.returncode}")
    print("Output saved to: test_results_scenario.txt")
    
    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    print(f"Risk tests: {'PASS' if risk_result.returncode == 0 else 'FAIL'}")
    print(f"Scenario tests: {'PASS' if scenario_result.returncode == 0 else 'FAIL'}")
    
    return max(risk_result.returncode, scenario_result.returncode)

if __name__ == "__main__":
    sys.exit(run_tests())
