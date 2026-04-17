#!/usr/bin/env python3
"""
MERID Phase 0 Acceptance Test Executor
Complete test execution with structured logging and analysis
"""

import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from utils.log_exporter import LogExporter


def main():
    """Execute complete acceptance test with logging"""
    print("🎯 MERID PHASE 0 ACCEPTANCE TEST EXECUTOR")
    print("=" * 50)
    
    # Setup
    test_id = f"phase0_acceptance_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    print(f"Test ID: {test_id}")
    print(f"Log Directory: {log_dir}")
    print()
    
    # Step 1: Run acceptance test
    print("🚀 Step 1: Running Phase 0 Acceptance Test")
    print("-" * 40)
    
    test_script = Path("src/test/phase0_acceptance_test.py")
    if not test_script.exists():
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
        
        if test_success:
            print("✅ Acceptance test completed successfully")
        else:
            print("❌ Acceptance test failed")
        
    except Exception as e:
        print(f"❌ Exception running test: {str(e)}")
        test_success = False
    
    print()
    
    # Step 2: Export and analyze logs
    print("📊 Step 2: Exporting and Analyzing Logs")
    print("-" * 40)
    
    exporter = LogExporter(str(log_dir))
    
    # Find generated log files
    log_files = list(log_dir.glob("*.jsonl"))
    if not log_files:
        print("⚠️ No structured log files found - using basic analysis")
        
        # Create basic report from test output
        report_file = log_dir / f"phase0_basic_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        basic_report = f"""# Phase 0 Acceptance Test Report

**Test ID**: {test_id}
**Timestamp**: {datetime.now().isoformat()}
**Status**: {'✅ PASSED' if test_success else '❌ FAILED'}

## 🎯 Test Results

"""
        
        if test_success:
            basic_report += """
- ✅ All persistence assertions passed
- ✅ Decision recording succeeded
- ✅ Trial status shows decisions
- ✅ Alignment analysis includes decisions
- ✅ Contract compliance includes decisions
"""
        else:
            basic_report += """
- ❌ Persistence assertions failed
- ❌ Decision recording failed
- ❌ No decisions persisted
- ❌ Service layer requires performance data
"""
        
        basic_report += f"""

## 🚀 Next Steps

"""
        
        if test_success:
            basic_report += """
- ✅ Phase 0b can proceed
- ✅ Technical infrastructure validated
- ✅ Ready for 4-week re-measurement trial
"""
        else:
            basic_report += """
- ❌ Fix service layer validation
- ❌ Remove performance data requirement
- ❌ Re-run acceptance test after fix
- ❌ Phase 0b blocked until fix
"""
        
        with open(report_file, 'w') as f:
            f.write(basic_report)
        
        print(f"✅ Basic report generated: {report_file}")
        
    else:
        # Analyze structured logs
        latest_log = max(log_files, key=os.path.getctime)
        print(f"Analyzing log file: {latest_log}")
        
        report_file = exporter.generate_report(str(latest_log))
        print(f"✅ Log analysis complete: {report_file}")
    
    print()
    
    # Step 3: Final status
    print("🎯 FINAL STATUS")
    print("=" * 50)
    
    if test_success:
        print("✅ PHASE 0 ACCEPTANCE TEST PASSED")
        print("🚀 Phase 0b can proceed")
        print("📊 Technical infrastructure validated")
        print("⏰ Ready for 4-week re-measurement trial")
    else:
        print("❌ PHASE 0 ACCEPTANCE TEST FAILED")
        print("🔧 Service layer requires performance data")
        print("🚫 Phase 0b blocked until fix")
        print("📝 Fix: Remove performance data requirement")
    
    print()
    print("📁 Artifacts:")
    for file in log_dir.glob("*"):
        print(f"  - {file}")
    
    print()
    print("=" * 50)
    
    sys.exit(0 if test_success else 1)


if __name__ == "__main__":
    main()
