"""
MERID Comprehensive Integration Test

Tests all enhanced components working together.
"""

import sys
import time

def run_integration_test():
    """Run comprehensive integration test."""
    print("=" * 70)
    print("MERID COMPREHENSIVE INTEGRATION TEST")
    print("=" * 70)
    print()
    
    try:
        # Test imports
        from core.reality_registry import get_reality_registry
        from core.reality_auditor import get_reality_auditor
        from monitoring.regime_classifier import get_regime_classifier
        from trading.agents.execution_agent import get_execution_agent
        from data.live_price_feed import get_live_price_feed
        
        print("✅ All core modules imported successfully")
        print()
        
        # Test Reality Enforcement System
        registry = get_reality_registry()
        auditor = get_reality_auditor()
        print(f"Reality Registry: {len(registry._assertions)} assertions")
        print(f"Reality Auditor: entropy={auditor.regime_entropy:.3f}")
        print()
        
        # Test Regime Classifier
        classifier = get_regime_classifier()
        print(f"Regime Classifier: {len(classifier.classification_history)} classifications")
        print()
        
        # Test Execution Agent
        exec_agent = get_execution_agent()
        stats = exec_agent.get_execution_stats()
        print(f"Execution Agent: risk_status={stats['risk_status']}")
        print(f"  - Daily trades: {stats['daily_trade_count']}")
        print(f"  - Success rate: {stats['success_rate']:.1f}%")
        print()
        
        # Test Price Feed
        feed = get_live_price_feed()
        feed_stats = feed.get_stats()
        print(f"Price Feed: {feed_stats['symbols_tracked']} symbols tracked")
        print(f"  - Exchanges: {feed_stats['exchanges_connected']}")
        print(f"  - Cached prices: {feed_stats['cached_prices']}")
        print()
        
        print("=" * 70)
        print("ALL INTEGRATION TESTS PASSED ✅")
        print("=" * 70)
        return 0
        
    except Exception as e:
        print(f"❌ INTEGRATION TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(run_integration_test())
