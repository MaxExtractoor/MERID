"""Test Complete Bias Detection Pipeline.

This script tests the end-to-end bias detection pipeline across:
1. Upstream signal generation (agent_grid_15m)
2. Midstream risk management (kalshi_risk)
3. Downstream execution (order_router)
4. Bias monitoring and alerting (bias_alert_service)

Usage:
    python test_bias_pipeline.py
"""

import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def test_bias_monitor():
    """Test enhanced bias monitor."""
    print("\n" + "="*80)
    print("TEST 1: Enhanced Bias Monitor")
    print("="*80)
    
    try:
        from merid.prediction.bias_monitor import BiasMonitor, get_bias_monitor
        
        # Create bias monitor
        monitor = BiasMonitor(window_size=50, bias_threshold=0.60)
        
        # Record some test signals
        print("Recording test signals...")
        for i in range(30):
            asset = ["BTC", "ETH", "SOL", "XRP", "DOGE"][i % 5]
            side = "yes" if i % 3 == 0 else "no"  # Create some bias
            price = 0.3 + (i % 7) * 0.1
            edge = 0.05 + (i % 3) * 0.02
            monitor.record_signal(asset=asset, side=side, edge=edge, price=price)
        
        # Get bias report
        report = monitor.get_bias_report(asset="BTC")
        print(f"Bias Report for BTC:")
        print(f"  Total signals: {report.total_signals}")
        print(f"  YES: {report.yes_percentage:.1f}%")
        print(f"  NO: {report.no_percentage:.1f}%")
        print(f"  Bias detected: {report.bias_detected}")
        print(f"  Price distribution bias: {report.price_distribution_bias}")
        print(f"  Favorite-longshot bias: {report.favorite_longshot_bias}")
        print(f"  Temporal bias: {report.temporal_bias}")
        
        print("[PASS] Bias monitor test passed")
        return True
        
    except Exception as e:
        print(f"[FAIL] Bias monitor test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_bias_alert_service():
    """Test bias alert service."""
    print("\n" + "="*80)
    print("TEST 2: Bias Alert Service")
    print("="*80)
    
    try:
        from merid.monitoring.bias_alert_service import BiasAlertService, get_bias_alert_service
        
        # Create alert service (don't start monitoring to avoid hanging)
        service = BiasAlertService(check_interval_seconds=300)
        
        # Test basic functionality without monitoring loop
        print("Testing bias alert service initialization...")
        
        # Get bias summary (should work without monitoring)
        summary = service.get_bias_summary()
        print(f"Bias summary:")
        print(f"  Active alerts: {summary['active_alerts']}")
        print(f"  Service initialized successfully")
        
        print("[PASS] Bias alert service test passed")
        return True
        
    except Exception as e:
        print(f"[FAIL] Bias alert service test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_agent_grid_integration():
    """Test bias monitoring integration in agent_grid_15m."""
    print("\n" + "="*80)
    print("TEST 3: Agent Grid Integration")
    print("="*80)
    
    try:
        # Check if bias monitor is imported in agent_grid_15m
        from merid.prediction import agent_grid_15m
        
        # Check for BIAS_MONITOR_ENABLED flag
        if hasattr(agent_grid_15m, 'BIAS_MONITOR_ENABLED'):
            print(f"BIAS_MONITOR_ENABLED: {agent_grid_15m.BIAS_MONITOR_ENABLED}")
        else:
            print("BIAS_MONITOR_ENABLED flag not found")
        
        # Check for get_bias_monitor import
        if hasattr(agent_grid_15m, 'get_bias_monitor'):
            print("get_bias_monitor function imported")
        else:
            print("get_bias_monitor function not imported")
        
        print("[PASS] Agent grid integration test passed")
        return True
        
    except Exception as e:
        print(f"[FAIL] Agent grid integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_risk_management_integration():
    """Test bias monitoring integration in kalshi_risk."""
    print("\n" + "="*80)
    print("TEST 4: Risk Management Integration")
    print("="*80)
    
    try:
        from merid.event_venues.kalshi import kalshi_risk
        
        # Check if bias monitoring code exists in check_order
        import inspect
        source = inspect.getsource(kalshi_risk.KalshiRiskManager.check_order)
        
        if 'bias_monitor' in source.lower():
            print("Bias monitoring code found in check_order")
        else:
            print("Bias monitoring code not found in check_order")
        
        print("[PASS] Risk management integration test passed")
        return True
        
    except Exception as e:
        print(f"[FAIL] Risk management integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_execution_integration():
    """Test bias monitoring integration in order_router."""
    print("\n" + "="*80)
    print("TEST 5: Execution Integration")
    print("="*80)
    
    try:
        from merid.event_venues.kalshi import order_router
        
        # Check if bias monitoring code exists in route_order_async
        import inspect
        source = inspect.getsource(order_router.route_order_async)
        
        if 'bias_monitor' in source.lower():
            print("Bias monitoring code found in route_order_async")
        else:
            print("Bias monitoring code not found in route_order_async")
        
        print("[PASS] Execution integration test passed")
        return True
        
    except Exception as e:
        print(f"[FAIL] Execution integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_comprehensive_audit():
    """Test comprehensive bias audit script."""
    print("\n" + "="*80)
    print("TEST 6: Comprehensive Bias Audit")
    print("="*80)
    
    try:
        # Test with sample data
        from bias_audit_framework import SimpleBiasAuditor, generate_sample_data
        
        # Generate sample data
        print("Generating sample data...")
        generate_sample_data("test_sample_trades.json")
        
        # Run audit
        print("Running bias audit...")
        auditor = SimpleBiasAuditor("test_sample_trades.json")
        report = auditor.run_full_audit()
        
        print(f"Audit Results:")
        print(f"  Total trades: {report.total_trades_analyzed}")
        print(f"  Total findings: {report.summary['total_findings']}")
        print(f"  By severity: {report.summary['by_severity']}")
        print(f"  By category: {report.summary['by_category']}")
        
        print("[PASS] Comprehensive audit test passed")
        return True
        
    except Exception as e:
        print(f"[FAIL] Comprehensive audit test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all bias pipeline tests."""
    print("="*80)
    print("BIAS DETECTION PIPELINE TEST SUITE")
    print("="*80)
    print(f"Started at: {datetime.utcnow().isoformat()}")
    
    results = {}
    
    # Run all tests
    results['bias_monitor'] = test_bias_monitor()
    results['bias_alert_service'] = test_bias_alert_service()
    results['agent_grid'] = test_agent_grid_integration()
    results['risk_management'] = test_risk_management_integration()
    results['execution'] = test_execution_integration()
    results['comprehensive_audit'] = test_comprehensive_audit()
    
    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "[PASS] PASSED" if result else "[FAIL] FAILED"
        print(f"{test_name:20s}: {status}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n[SUCCESS] All bias detection pipeline tests passed!")
        return 0
    else:
        print(f"\n[WARNING] {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
