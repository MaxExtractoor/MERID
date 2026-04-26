#!/usr/bin/env python3
"""Run tests and capture output to a file."""

import subprocess
import sys

# Run the risk enforcement tests
print("Running: pytest tests/risk/test_unified_risk_enforcement.py -v")
result1 = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/risk/test_unified_risk_enforcement.py", "-v", "--tb=short"],
    capture_output=True,
    text=True,
    cwd="c:\\Dev\\MERID"
)

with open("test_output_risk.txt", "w") as f:
    f.write("STDOUT:\n")
    f.write(result1.stdout)
    f.write("\n\nSTDERR:\n")
    f.write(result1.stderr)
    f.write(f"\n\nReturn code: {result1.returncode}\n")

print(f"Risk tests: return code {result1.returncode}")
if result1.returncode == 0:
    print("✓ Risk tests passed")
else:
    print("✗ Risk tests failed")
    print(result1.stdout[-2000:])  # Print last 2000 chars

# Run the scenario tests
print("\nRunning: pytest tests/scenario/test_pass9_scenarios.py -v")
result2 = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/scenario/test_pass9_scenarios.py", "-v", "--tb=short"],
    capture_output=True,
    text=True,
    cwd="c:\\Dev\\MERID"
)

with open("test_output_scenario.txt", "w") as f:
    f.write("STDOUT:\n")
    f.write(result2.stdout)
    f.write("\n\nSTDERR:\n")
    f.write(result2.stderr)
    f.write(f"\n\nReturn code: {result2.returncode}\n")

print(f"Scenario tests: return code {result2.returncode}")
if result2.returncode == 0:
    print("✓ Scenario tests passed")
else:
    print("✗ Scenario tests failed")
    print(result2.stdout[-2000:])  # Print last 2000 chars

sys.exit(max(result1.returncode, result2.returncode))
