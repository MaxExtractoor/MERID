"""
Validate Kalshi 15m logging infrastructure before paper dress rehearsal.

This script validates that the new logging components are properly integrated:
- Strategy decision truth table logging (TickEventBus)
- Drift metrics collection (risk_envelope, data_freshness, scheduler)
- Risk/decision structured events

Usage:
    python scripts/validate_kalshi_logging.py
"""
import os
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Set profile to kalshi_crypto_15m_v2
os.environ["MERID_PROFILE"] = "kalshi_crypto_15m_v2"
os.environ["MERID_TRADING_MODE"] = "PAPER"


def validate_strategy_decision_logging():
    """Validate STRATEGY_DECISION event is defined in TickEventBus."""
    print("[1/5] Validating strategy decision logging...")
    
    try:
        from merid.tick_events import STRATEGY_DECISION, TickContext
        print(f"  ✓ STRATEGY_DECISION constant defined: {STRATEGY_DECISION}")
        
        # Check TickContext has emit_strategy_decision method
        context = TickContext(agent_id="test_agent", cycle_number=1)
        assert hasattr(context, 'emit_strategy_decision'), "TickContext missing emit_strategy_decision"
        print(f"  ✓ TickContext.emit_strategy_decision method exists")
        
        return True
    except Exception as e:
        print(f"  ✗ Failed: {e}")
        return False


def validate_drift_metrics_collector():
    """Validate DriftMetricsCollector is available and has required methods."""
    print("[2/5] Validating drift metrics collector...")
    
    try:
        from merid.monitoring.drift_metrics import DriftMetricsCollector, get_drift_metrics_collector
        
        # Check required methods exist
        collector = get_drift_metrics_collector()
        required_methods = [
            'collect_risk_envelope_drift',
            'collect_data_freshness_violation',
            'collect_scheduler_catalog_mismatch',
        ]
        
        for method in required_methods:
            assert hasattr(collector, method), f"DriftMetricsCollector missing {method}"
            print(f"  ✓ DriftMetricsCollector.{method} exists")
        
        return True
    except Exception as e:
        print(f"  ✗ Failed: {e}")
        return False


def validate_risk_envelope_integration():
    """Validate DriftMetricsCollector is integrated into risk envelope."""
    print("[3/5] Validating risk envelope drift integration...")
    
    try:
        # Check that the integration code exists in kalshi_crypto_15m_risk_envelope.py
        from pathlib import Path
        risk_envelope_file = Path("merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py")
        
        if not risk_envelope_file.exists():
            print(f"  ✗ Risk envelope file not found")
            return False
        
        content = risk_envelope_file.read_text(encoding="utf-8")
        
        # Check for drift metrics collection code
        if "collect_risk_envelope_drift" in content:
            print(f"  ✓ Drift metrics collection code found in risk envelope")
            return True
        else:
            print(f"  ✗ Drift metrics collection code not found")
            return False
            
    except Exception as e:
        print(f"  ✗ Failed: {e}")
        return False


def validate_order_router_integration():
    """Validate DriftMetricsCollector is integrated into order router for data freshness."""
    print("[4/5] Validating order router data freshness integration...")
    
    try:
        from pathlib import Path
        order_router_file = Path("merid/event_venues/kalshi/order_router.py")
        
        if not order_router_file.exists():
            print(f"  ✗ Order router file not found")
            return False
        
        content = order_router_file.read_text(encoding="utf-8")
        
        # Check for data freshness drift metrics code
        if "collect_data_freshness_violation" in content:
            print(f"  ✓ Data freshness drift metrics code found in order router")
            return True
        else:
            print(f"  ✗ Data freshness drift metrics code not found")
            return False
            
    except Exception as e:
        print(f"  ✗ Failed: {e}")
        return False


def validate_scheduler_integration():
    """Validate DriftMetricsCollector is integrated into scheduler for catalog mismatch."""
    print("[5/5] Validating scheduler catalog mismatch integration...")
    
    try:
        from pathlib import Path
        scheduler_file = Path("merid/event_venues/kalshi/crypto_15m_scheduler.py")
        
        if not scheduler_file.exists():
            print(f"  ✗ Scheduler file not found")
            return False
        
        content = scheduler_file.read_text(encoding="utf-8")
        
        # Check for catalog mismatch drift metrics code
        if "collect_scheduler_catalog_mismatch" in content:
            print(f"  ✓ Catalog mismatch drift metrics code found in scheduler")
            return True
        else:
            print(f"  ✗ Catalog mismatch drift metrics code not found")
            return False
            
    except Exception as e:
        print(f"  ✗ Failed: {e}")
        return False


def main():
    """Run all validation checks."""
    print("="*80)
    print("KALSHI 15M LOGGING INFRASTRUCTURE VALIDATION")
    print("="*80)
    print()
    
    results = []
    results.append(validate_strategy_decision_logging())
    results.append(validate_drift_metrics_collector())
    results.append(validate_risk_envelope_integration())
    results.append(validate_order_router_integration())
    results.append(validate_scheduler_integration())
    
    print()
    print("="*80)
    passed = sum(results)
    total = len(results)
    print(f"VALIDATION SUMMARY: {passed}/{total} checks passed")
    print("="*80)
    
    if passed == total:
        print("\n✓ All logging infrastructure validated successfully")
        print("\nNext steps for paper dress rehearsal:")
        print("1. Ensure Kalshi API credentials are configured")
        print("2. Run the Kalshi 15m pipeline in paper mode")
        print("3. Monitor logs for STRATEGY_DECISION events")
        print("4. Monitor logs for drift metrics collection")
        print("5. Run for 1-2 cycles (15-30 minutes)")
        return 0
    else:
        print("\n✗ Some validation checks failed")
        print("Fix the issues above before running paper dress rehearsal")
        return 1


if __name__ == "__main__":
    sys.exit(main())
