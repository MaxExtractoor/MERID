#!/usr/bin/env python3
"""Script to diagnose CI failures for swarm self-healing.

Usage:
    python swarm_diagnose_failure.py --run-id=12345 --output=diagnosis.json
"""

import argparse
import json
import os
import requests
import sys
from pathlib import Path


def get_workflow_run_logs(run_id, token):
    """Fetch workflow run logs from GitHub API."""
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        return {"error": "GITHUB_REPOSITORY not set"}
    
    url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/logs"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()
        else:
            return {"error": f"API error: {response.status_code}", "details": response.text}
    except Exception as e:
        return {"error": str(e)}


def analyze_failure(logs):
    """Analyze failure logs to identify root cause."""
    diagnosis = {
        "failure_type": "unknown",
        "suspected_cause": "",
        "recommended_action": "",
        "confidence": 0.0
    }
    
    log_text = json.dumps(logs).lower()
    
    # Pattern matching for common failures
    if "coverage" in log_text and "below" in log_text:
        diagnosis["failure_type"] = "coverage_threshold"
        diagnosis["suspected_cause"] = "Coverage below target threshold"
        diagnosis["recommended_action"] = "Generate additional tests for uncovered lines"
        diagnosis["confidence"] = 0.9
    
    elif "pytest" in log_text and ("failed" in log_text or "error" in log_text):
        diagnosis["failure_type"] = "test_failure"
        diagnosis["suspected_cause"] = "One or more tests failing"
        diagnosis["recommended_action"] = "Review and fix failing tests"
        diagnosis["confidence"] = 0.85
    
    elif "lint" in log_text or "ruff" in log_text or "mypy" in log_text:
        diagnosis["failure_type"] = "linting_error"
        diagnosis["suspected_cause"] = "Code style or type checking issues"
        diagnosis["recommended_action"] = "Run lint:fix and type-check corrections"
        diagnosis["confidence"] = 0.8
    
    elif "import" in log_text and "error" in log_text:
        diagnosis["failure_type"] = "import_error"
        diagnosis["suspected_cause"] = "Missing dependencies or circular imports"
        diagnosis["recommended_action"] = "Check requirements and import order"
        diagnosis["confidence"] = 0.75
    
    elif "timeout" in log_text:
        diagnosis["failure_type"] = "timeout"
        diagnosis["suspected_cause"] = "Test or operation exceeded time limit"
        diagnosis["recommended_action"] = "Optimize slow tests or increase timeout"
        diagnosis["confidence"] = 0.8
    
    else:
        diagnosis["failure_type"] = "unknown"
        diagnosis["suspected_cause"] = "Unable to automatically diagnose"
        diagnosis["recommended_action"] = "Manual review required"
        diagnosis["confidence"] = 0.3
    
    return diagnosis


def main():
    parser = argparse.ArgumentParser(description="Diagnose CI failures for swarm self-healing")
    parser.add_argument("--run-id", type=str, required=True, help="GitHub Actions run ID")
    parser.add_argument("--output", type=str, default="diagnosis.json", help="Output file path")
    args = parser.parse_args()
    
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("Error: GITHUB_TOKEN environment variable required", file=sys.stderr)
        sys.exit(1)
    
    print(f"🔍 Analyzing workflow run: {args.run_id}")
    
    # Fetch logs
    logs = get_workflow_run_logs(args.run_id, token)
    
    if "error" in logs:
        print(f"❌ Error fetching logs: {logs['error']}", file=sys.stderr)
        sys.exit(1)
    
    # Analyze failure
    diagnosis = analyze_failure(logs)
    diagnosis["run_id"] = args.run_id
    diagnosis["raw_logs_size"] = len(str(logs))
    
    # Save diagnosis
    with open(args.output, 'w') as f:
        json.dump(diagnosis, f, indent=2)
    
    print(f"📊 Diagnosis:")
    print(f"   Type: {diagnosis['failure_type']}")
    print(f"   Cause: {diagnosis['suspected_cause']}")
    print(f"   Action: {diagnosis['recommended_action']}")
    print(f"   Confidence: {diagnosis['confidence']:.0%}")
    print(f"📄 Saved to: {args.output}")


if __name__ == "__main__":
    main()
