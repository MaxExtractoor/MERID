"""
Test script for new risk projection pipeline

This script tests the new pure-function risk projection pipeline
and runs parallel diff validation against the legacy pipeline.

Usage:
    python scripts/test_risk_pipeline.py
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from utils.logger import get_logger

logger = get_logger("scripts.test_risk_pipeline")


async def test_new_pipeline():
    """Test new pipeline in isolation."""
    logger.info("=" * 80)
    logger.info("TEST 1: New Pipeline in Isolation (force_new=true)")
    logger.info("=" * 80)
    
    try:
        from merid.event_venues.kalshi.risk_pipeline_coordinator import get_risk_projection
        
        projection = await get_risk_projection(force_new=True)
        
        logger.info("✅ New pipeline succeeded")
        logger.info(f"  - Positions: {projection.position_count}")
        logger.info(f"  - Total exposure: ${projection.total_exposure_dollars:.2f}")
        logger.info(f"  - Unrealized PnL: ${projection.unrealized_pnl_dollars:.2f}")
        logger.info(f"  - Realized PnL: ${projection.realized_pnl_dollars:.2f}")
        logger.info(f"  - Equity: ${projection.equity_dollars:.2f}")
        logger.info(f"  - Backend timestamp: {projection.backend_timestamp}")
        
        return True
    except Exception as e:
        logger.error(f"❌ New pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_legacy_pipeline():
    """Test legacy pipeline for comparison."""
    logger.info("=" * 80)
    logger.info("TEST 2: Legacy Pipeline (for comparison)")
    logger.info("=" * 80)
    
    try:
        from merid.event_venues.kalshi.risk_pipeline_coordinator import get_risk_projection
        
        projection = await get_risk_projection(force_new=False)
        
        logger.info("✅ Legacy pipeline succeeded")
        logger.info(f"  - Positions: {projection.position_count}")
        logger.info(f"  - Total exposure: ${projection.total_exposure_dollars:.2f}")
        logger.info(f"  - Unrealized PnL: ${projection.unrealized_pnl_dollars:.2f}")
        logger.info(f"  - Realized PnL: ${projection.realized_pnl_dollars:.2f}")
        logger.info(f"  - Equity: ${projection.equity_dollars:.2f}")
        
        return True
    except Exception as e:
        logger.error(f"❌ Legacy pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_parallel_diff():
    """Test parallel diff between old and new pipelines."""
    logger.info("=" * 80)
    logger.info("TEST 3: Parallel Diff Validation")
    logger.info("=" * 80)
    
    try:
        from merid.event_venues.kalshi.risk_pipeline_coordinator import run_parallel_diff
        
        diff = await run_parallel_diff()
        
        logger.info("✅ Parallel diff completed")
        logger.info(f"  - Position count diff: {diff.position_count_diff}")
        logger.info(f"  - Unrealized PnL diff: ${diff.unrealized_pnl_diff_dollars:.2f}")
        logger.info(f"  - Realized PnL diff: ${diff.realized_pnl_diff_dollars:.2f}")
        logger.info(f"  - Total exposure diff: ${diff.total_exposure_diff_dollars:.2f}")
        logger.info(f"  - Equity diff: ${diff.equity_diff_dollars:.2f}")
        logger.info(f"  - Significant discrepancy: {diff.has_significant_discrepancy}")
        logger.info(f"  - Old pipeline source: {diff.old_pipeline_source}")
        logger.info(f"  - New pipeline source: {diff.new_pipeline_source}")
        
        if diff.position_details:
            logger.warning(f"  - Position details ({len(diff.position_details)} items):")
            for key, detail in diff.position_details.items():
                logger.warning(f"    - {key}: {detail}")
        
        # Cutover criteria check
        logger.info("\n" + "=" * 80)
        logger.info("CUTOVER CRITERIA CHECK")
        logger.info("=" * 80)
        
        criteria_passed = True
        
        if diff.position_count_diff != 0:
            logger.error(f"❌ Position count diff is {diff.position_count_diff} (expected 0)")
            criteria_passed = False
        else:
            logger.info("✅ Position count diff is 0")
        
        pnl_diff_cents = abs(float(diff.unrealized_pnl_diff_dollars + diff.realized_pnl_diff_dollars)) * 100
        if pnl_diff_cents > 10:
            logger.error(f"❌ PnL diff is ${pnl_diff_cents/100:.2f} (expected < $0.10)")
            criteria_passed = False
        else:
            logger.info(f"✅ PnL diff is ${pnl_diff_cents/100:.2f} (< $0.10)")
        
        if diff.has_significant_discrepancy:
            logger.error(f"❌ Has significant discrepancy (expected false)")
            criteria_passed = False
        else:
            logger.info("✅ No significant discrepancy")
        
        logger.info("\n" + "=" * 80)
        if criteria_passed:
            logger.info("✅ ALL CUTOVER CRITERIA PASSED - Ready for cutover")
        else:
            logger.error("❌ CUTOVER CRITERIA NOT MET - Do not cutover yet")
        logger.info("=" * 80)
        
        return criteria_passed
        
    except Exception as e:
        logger.error(f"❌ Parallel diff failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_pipeline_status():
    """Test pipeline status endpoint."""
    logger.info("=" * 80)
    logger.info("TEST 4: Pipeline Status")
    logger.info("=" * 80)
    
    try:
        from merid.event_venues.kalshi.risk_pipeline_coordinator import get_pipeline_status
        
        status = get_pipeline_status()
        
        logger.info("✅ Pipeline status retrieved")
        logger.info(f"  - Use new pipeline: {status['use_new_pipeline']}")
        logger.info(f"  - Pipeline type: {status['pipeline_type']}")
        logger.info(f"  - Feature flag: {status['feature_flag']}")
        logger.info(f"  - Cutover ready: {status['cutover_ready']}")
        
        return True
    except Exception as e:
        logger.error(f"❌ Pipeline status failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all tests."""
    logger.info("\n" + "=" * 80)
    logger.info("RISK PIPELINE VALIDATION SUITE")
    logger.info("=" * 80 + "\n")
    
    results = {}
    
    # Test 1: New pipeline
    results["new_pipeline"] = await test_new_pipeline()
    print()
    
    # Test 2: Legacy pipeline
    results["legacy_pipeline"] = await test_legacy_pipeline()
    print()
    
    # Test 3: Parallel diff
    results["parallel_diff"] = await test_parallel_diff()
    print()
    
    # Test 4: Pipeline status
    results["pipeline_status"] = await test_pipeline_status()
    print()
    
    # Summary
    logger.info("=" * 80)
    logger.info("TEST SUMMARY")
    logger.info("=" * 80)
    
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        logger.info(f"  {test_name}: {status}")
    
    all_passed = all(results.values())
    
    logger.info("\n" + "=" * 80)
    if all_passed:
        logger.info("✅ ALL TESTS PASSED")
        logger.info("Recommendation: Ready to enable USE_NEW_RISK_PIPELINE feature flag")
    else:
        logger.error("❌ SOME TESTS FAILED")
        logger.error("Recommendation: Fix failures before enabling feature flag")
    logger.info("=" * 80 + "\n")
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
