#!/usr/bin/env python3
"""
MERID Phase 0 Structlog Acceptance Test Executor
Complete test execution with enhanced structured logging and analysis
"""

import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from utils.structlog_config import configure_logging, get_logger


def main():
    """Execute complete acceptance test with enhanced structured logging"""
    print("🎯 MERID PHASE 0 STRUCTLOG ACCEPTANCE TEST EXECUTOR")
    print("=" * 60)
    
    # Setup environment for JSON logging
    os.environ["APP_ENV"] = "test"
    configure_logging()
    
    logger = get_logger("test_executor")
    
    # Setup
    test_id = f"phase0_acceptance_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    logger.info("test_execution_started",
                test_id=test_id,
                log_dir=str(log_dir),
                app_env=os.getenv("APP_ENV"))
    
    print(f"Test ID: {test_id}")
    print(f"Log Directory: {log_dir}")
    print(f"Environment: {os.getenv('APP_ENV')}")
    print()
    
    # Step 1: Run structlog acceptance test
    print("🚀 Step 1: Running Phase 0 Structlog Acceptance Test")
    print("-" * 50)
    
    test_script = Path("src/test/phase0_structlog_acceptance_test.py")
    if not test_script.exists():
        logger.error("test_script_not_found", script=str(test_script))
        print(f"❌ Test script not found: {test_script}")
        sys.exit(1)
    
    try:
        # Run test and capture output
        result = subprocess.run([
            sys.executable, str(test_script)
        ], capture_output=True, text=True, cwd=os.getcwd())
        
        print("Test Output:")
        print(result.stdout)
        
        if result.stderr:
            print("Test Errors:")
            print(result.stderr)
        
        test_success = result.returncode == 0
        
        logger.info("test_execution_completed",
                    test_id=test_id,
                    success=test_success,
                    return_code=result.returncode,
                    stdout_lines=len(result.stdout.splitlines()) if result.stdout else 0,
                    stderr_lines=len(result.stderr.splitlines()) if result.stderr else 0)
        
        if test_success:
            print("✅ Acceptance test completed successfully")
        else:
            print("❌ Acceptance test failed")
        
    except Exception as e:
        logger.error("test_execution_exception", error=str(e), error_type=type(e).__name__)
        print(f"❌ Exception running test: {str(e)}")
        test_success = False
    
    print()
    
    # Step 2: Analyze structured logs
    print("📊 Step 2: Analyzing Structured Logs")
    print("-" * 50)
    
    # Look for JSON log files (structured logs would be captured in stdout)
    log_files = list(log_dir.glob("*.jsonl"))
    
    if not log_files:
        print("📝 No JSON log files found - analyzing test output")
        
        # Parse JSON from stdout if present
        json_lines = []
        if result.stdout:
            for line in result.stdout.split('\n'):
                line = line.strip()
                if line.startswith('{') and line.endswith('}'):
                    try:
                        import json
                        json_lines.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        
        if json_lines:
            print(f"✅ Found {len(json_lines)} structured log entries in output")
            analyze_json_logs(json_lines, logger)
        else:
            print("⚠️ No structured logs found in output")
    
    else:
        print(f"✅ Found {len(log_files)} JSON log files")
        for log_file in log_files:
            print(f"  - {log_file}")
    
    print()
    
    # Step 3: Final status
    print("🎯 FINAL STATUS")
    print("=" * 60)
    
    if test_success:
        print("✅ PHASE 0 ACCEPTANCE TEST PASSED")
        print("🚀 Phase 0b can proceed")
        print("📊 Technical infrastructure validated")
        print("⏰ Ready for 4-week re-measurement trial")
        
        logger.info("test_execution_success",
                    test_id=test_id,
                    next_step="phase0b_ready")
    else:
        print("❌ PHASE 0 ACCEPTANCE TEST FAILED")
        print("🔧 Service layer requires performance data")
        print("🚫 Phase 0b blocked until fix")
        print("📝 Fix: Remove performance data requirement")
        
        logger.info("test_execution_failure",
                    test_id=test_id,
                    next_step="fix_service_layer")
    
    print()
    print("📁 Artifacts:")
    for file in log_dir.glob("*"):
        print(f"  - {file}")
    
    print()
    print("=" * 60)
    
    sys.exit(0 if test_success else 1)


def analyze_json_logs(json_logs: list, logger):
    """Analyze structured log entries for key metrics"""
    metrics = {
        "total_events": len(json_logs),
        "error_count": 0,
        "http_requests": 0,
        "sql_queries": 0,
        "test_steps": 0,
        "correlation_ids": set(),
        "decision_attempts": 0,
        "decision_successes": 0,
        "decision_failures": 0
    }
    
    for entry in json_logs:
        # Count errors
        if entry.get("level") == "ERROR":
            metrics["error_count"] += 1
        
        # Count HTTP requests
        if entry.get("event", "").startswith("http_"):
            metrics["http_requests"] += 1
        
        # Count SQL queries
        if entry.get("event", "").startswith("sql_"):
            metrics["sql_queries"] += 1
        
        # Count test steps
        if entry.get("event", "").startswith("step_"):
            metrics["test_steps"] += 1
        
        # Collect correlation IDs
        if "correlation_id" in entry:
            metrics["correlation_ids"].add(entry["correlation_id"])
        
        # Count decision events
        if entry.get("event") == "decision_recording_attempted":
            metrics["decision_attempts"] += 1
        elif entry.get("event") == "decision_recording_passed":
            metrics["decision_successes"] += 1
        elif entry.get("event") == "decision_recording_failed":
            metrics["decision_failures"] += 1
    
    # Convert set to count
    metrics["correlation_ids"] = len(metrics["correlation_ids"])
    
    print(f"📈 Structured Log Analysis:")
    print(f"  - Total Events: {metrics['total_events']}")
    print(f"  - Error Count: {metrics['error_count']}")
    print(f"  - HTTP Requests: {metrics['http_requests']}")
    print(f"  - SQL Queries: {metrics['sql_queries']}")
    print(f"  - Test Steps: {metrics['test_steps']}")
    print(f"  - Correlation IDs: {metrics['correlation_ids']}")
    print(f"  - Decision Attempts: {metrics['decision_attempts']}")
    print(f"  - Decision Successes: {metrics['decision_successes']}")
    print(f"  - Decision Failures: {metrics['decision_failures']}")
    
    logger.info("structured_log_analysis", **metrics)
    
    # Key findings
    if metrics["decision_attempts"] > 0 and metrics["decision_failures"] > 0:
        print(f"🔍 Key Finding: Decision recording failed ({metrics['decision_failures']} failures)")
    
    if metrics["sql_queries"] == 0:
        print("⚠️ No SQL queries detected - check database logging")
    
    if metrics["test_steps"] >= 6:
        print("✅ Complete test execution captured")
    else:
        print(f"⚠️ Incomplete test execution ({metrics['test_steps']}/6 steps)")


if __name__ == "__main__":
    main()
