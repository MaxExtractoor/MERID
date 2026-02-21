"""
Trigger initial reconciliation to unblock execution gate.

Usage:
    python scripts/run_reconciliation.py
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from merid.reconciliation import get_kalshi_reconciler
from utils.logger import get_logger
import asyncio

logger = get_logger("scripts.run_reconciliation")

async def run_reconciliation():
    logger.info("=" * 80)
    logger.info("Running Kalshi reconciliation to unblock execution gate")
    logger.info("=" * 80)
    
    # Get Kalshi reconciler
    reconciler = get_kalshi_reconciler()
    
    # Run reconciliation
    report = await reconciler.reconcile()
    
    logger.info("=" * 80)
    logger.info(f"Reconciliation complete: {report.summary}")
    logger.info(f"Severity: {report.severity}")
    logger.info(f"Issues found: {len(report.issues)}")
    logger.info("=" * 80)
    
    # Report results by severity
    critical_issues = [i for i in report.issues if i.severity == "CRITICAL"]
    warning_issues = [i for i in report.issues if i.severity == "WARNING"]
    info_issues = [i for i in report.issues if i.severity == "INFO"]
    
    if critical_issues:
        logger.warning(f"❌ Found {len(critical_issues)} CRITICAL issues:")
        for issue in critical_issues[:5]:  # Show first 5
            logger.warning(f"  {issue.issue_type}: {issue.description}")
    
    if warning_issues:
        logger.warning(f"⚠️  Found {len(warning_issues)} WARNING issues:")
        for issue in warning_issues[:3]:  # Show first 3
            logger.warning(f"  {issue.issue_type}: {issue.description}")
    
    if info_issues:
        logger.info(f"ℹ️  Found {len(info_issues)} INFO issues")
    
    # Check execution gate status
    logger.info("=" * 80)
    if report.severity == "CRITICAL":
        logger.warning("⚠️  Execution gate: BLOCKED (critical issues found)")
        logger.warning("Review issues above and resolve before enabling execution")
        return 1
    else:
        logger.info("✅ Execution gate: CLEAR")
        logger.info("Reconciliation complete - execution can proceed")
        return 0

def main():
    try:
        return asyncio.run(run_reconciliation())
    except Exception as e:
        logger.error(f"Reconciliation failed: {e}", exc_info=True)
        return 1

if __name__ == "__main__":
    sys.exit(main())
