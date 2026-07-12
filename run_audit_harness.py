"""
Test script to run the production audit harness.

This script starts the audit harness and runs a single audit cycle
to verify it works correctly with the running server.
"""

import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from merid.audit import get_production_audit_harness
from utils.logger import get_logger

logger = get_logger("run_audit_harness")


def critical_failure_handler(report, critical_findings):
    """Handle critical failures."""
    logger.error(f"CRITICAL FAILURE: {len(critical_findings)} critical findings")
    for finding in critical_findings:
        logger.error(f"  - {finding.check_name}: {finding.mismatch_details}")


def high_failure_handler(report, high_findings):
    """Handle high severity failures."""
    logger.warning(f"HIGH FAILURE: {len(high_findings)} high findings")
    for finding in high_findings:
        logger.warning(f"  - {finding.check_name}: {finding.mismatch_details}")


def main():
    """Main function to run audit harness."""
    logger.info("=" * 80)
    logger.info("Starting Production Audit Harness Test")
    logger.info("=" * 80)
    
    # Get harness instance
    harness = get_production_audit_harness()
    
    # Set failure callbacks
    harness.set_critical_failure_callback(critical_failure_handler)
    harness.set_high_failure_callback(high_failure_handler)
    
    # Run a single audit cycle immediately (don't start background thread)
    logger.info("Running single audit cycle...")
    
    current_ts = time.time()
    window_start = current_ts - (current_ts % 900)
    window_end = window_start + 900
    cycle_id = "manual_test"
    
    try:
        report = harness._run_audit_cycle(cycle_id, window_start, window_end)
        
        logger.info("=" * 80)
        logger.info(f"Audit Report for Cycle {cycle_id}")
        logger.info("=" * 80)
        logger.info(f"Passed: {report.passed}")
        logger.info(f"Total Findings: {len(report.findings)}")
        logger.info(f"Critical Findings: {len([f for f in report.findings if f.severity.value == 'critical'])}")
        logger.info(f"High Findings: {len([f for f in report.findings if f.severity.value == 'high'])}")
        
        if report.findings:
            logger.info("\nDetailed Findings:")
            for i, finding in enumerate(report.findings, 1):
                logger.info(f"\n{i}. Layer: {finding.layer.value}")
                logger.info(f"   Severity: {finding.severity.value}")
                logger.info(f"   Check: {finding.check_name}")
                logger.info(f"   Intended: {finding.intended_behavior}")
                logger.info(f"   Actual: {finding.actual_behavior}")
                logger.info(f"   Details: {finding.mismatch_details}")
        
        # Export report to JSON
        output_path = project_root / "output" / f"audit_report_{cycle_id}.json"
        output_path.parent.mkdir(exist_ok=True)
        harness.export_report_to_json(report, str(output_path))
        logger.info(f"\nReport exported to: {output_path}")
        
        logger.info("=" * 80)
        logger.info("Audit harness test completed")
        logger.info("=" * 80)
        
        # Return exit code based on result
        if report.passed:
            logger.info("Audit PASSED")
            return 0
        else:
            logger.error("Audit FAILED")
            return 1
            
    except Exception as e:
        logger.error(f"Audit harness test failed with exception: {e}", exc_info=True)
        return 2


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
