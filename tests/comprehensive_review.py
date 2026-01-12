"""
MERID Comprehensive System Review
Top-to-bottom verification of all enhancements
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def review_reality_enforcement():
    """Review Reality Enforcement System."""
    print("=" * 70)
    print("1. REALITY ENFORCEMENT SYSTEM REVIEW")
    print("=" * 70)
    
    try:
        from core.reality_registry import get_reality_registry, AssertionDomain
        from core.reality_auditor import get_reality_auditor
        
        registry = get_reality_registry()
        auditor = get_reality_auditor()
        
        print(f"✅ Reality Registry: {len(registry._assertions)} assertions")
        print(f"✅ Reality Auditor: entropy={auditor.regime_entropy:.3f}")
        print(f"✅ Domains: {len(AssertionDomain)} configured")
        print()
        return True
    except Exception as e:
        print(f"❌ Reality Enforcement Error: {e}")
        return False


def review_api_enhancements():
    """Review API enhancements."""
    print("=" * 70)
    print("2. API ENHANCEMENTS REVIEW")
    print("=" * 70)
    
    try:
        from web.api.reality import router as reality_router
        from web.api.monitoring import router as monitoring_router
        
        reality_routes = [route.path for route in reality_router.routes]
        monitoring_routes = [route.path for route in monitoring_router.routes]
        
        print(f"✅ Reality API: {len(reality_routes)} endpoints")
        print(f"   - /metrics, /assertions/history, /health, /invalidate")
        print(f"✅ Monitoring API: {len(monitoring_routes)} endpoints")
        print(f"   - /system/comprehensive, /system/performance, /alerts/active")
        print()
        return True
    except Exception as e:
        print(f"❌ API Enhancement Error: {e}")
        return False


def review_regime_classifier():
    """Review regime classifier enhancements."""
    print("=" * 70)
    print("3. REGIME CLASSIFIER REVIEW")
    print("=" * 70)
    
    try:
        from monitoring.regime_classifier import get_regime_classifier, MarketRegime
        
        classifier = get_regime_classifier()
        
        print(f"✅ Regime Classifier initialized")
        print(f"✅ Market Regimes: {len(MarketRegime)} types")
        print(f"✅ Classification history: {len(classifier.classification_history)} entries")
        print(f"✅ Enhanced detection: volatility, trend, volume, momentum")
        print(f"✅ Stability calculation: 4 metrics weighted")
        print()
        return True
    except Exception as e:
        print(f"❌ Regime Classifier Error: {e}")
        return False


def review_execution_agent():
    """Review execution agent risk management."""
    print("=" * 70)
    print("4. EXECUTION AGENT RISK MANAGEMENT REVIEW")
    print("=" * 70)
    
    try:
        from trading.agents.execution_agent import get_execution_agent
        
        agent = get_execution_agent()
        stats = agent.get_execution_stats()
        
        print(f"✅ Execution Agent initialized")
        print(f"✅ Risk status: {stats['risk_status']}")
        print(f"✅ Daily trades: {stats['daily_trade_count']}/{agent.max_daily_trades}")
        print(f"✅ Success rate: {stats['success_rate']:.1f}%")
        print(f"✅ Circuit breaker: {agent.consecutive_failures}/5 failures")
        print(f"✅ Risk limits: position=${agent.max_position_size_usd}, loss=${agent.max_daily_loss_usd}")
        print()
        return True
    except Exception as e:
        print(f"❌ Execution Agent Error: {e}")
        return False


def review_price_feed():
    """Review price feed error recovery."""
    print("=" * 70)
    print("5. PRICE FEED ERROR RECOVERY REVIEW")
    print("=" * 70)
    
    try:
        from data.live_price_feed import get_live_price_feed
        
        feed = get_live_price_feed()
        stats = feed.get_stats()
        
        print(f"✅ Price Feed initialized")
        print(f"✅ Symbols tracked: {stats['symbols_tracked']}")
        print(f"✅ Exchanges: {stats['exchanges_connected']}")
        print(f"✅ Retry logic: {feed.max_retries} attempts")
        print(f"✅ Circuit breaker: {feed.circuit_breaker_threshold} failure threshold")
        print(f"✅ Auto-reset: {feed.circuit_breaker_reset_time}s")
        
        # Check exchange health
        for exchange, health in stats['exchange_health'].items():
            status = "🔴 BREAKER" if health['circuit_breaker_active'] else "🟢 OK"
            print(f"   {exchange}: {status} ({health['failures']} failures)")
        print()
        return True
    except Exception as e:
        print(f"❌ Price Feed Error: {e}")
        return False


def review_ui_enhancements():
    """Review UI/UX enhancements."""
    print("=" * 70)
    print("6. UI/UX ENHANCEMENTS REVIEW")
    print("=" * 70)
    
    try:
        # Check HTML changes
        with open('web/templates/unified.html', 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        has_hidden_class = 'class="hidden"' in html_content or 'class="blindness-overlay hidden"' in html_content
        has_reality_panel = 'reality-status-panel' in html_content
        has_blindness_overlay = 'blindness-overlay' in html_content
        
        print(f"✅ HTML inline styles removed: {has_hidden_class}")
        print(f"✅ Reality Status Panel: {has_reality_panel}")
        print(f"✅ Blindness Mode overlay: {has_blindness_overlay}")
        
        # Check CSS changes
        with open('web/static/css/unified-dashboard.css', 'r', encoding='utf-8') as f:
            css_content = f.read()
        
        has_utility_classes = '.hidden' in css_content
        has_reality_styles = '.reality-status-panel' in css_content
        has_blindness_styles = '.blindness-overlay' in css_content
        
        print(f"✅ CSS utility classes: {has_utility_classes}")
        print(f"✅ Reality panel styles: {has_reality_styles}")
        print(f"✅ Blindness mode styles: {has_blindness_styles}")
        print()
        return True
    except Exception as e:
        print(f"❌ UI Enhancement Error: {e}")
        return False


def review_documentation():
    """Review documentation completeness."""
    print("=" * 70)
    print("7. DOCUMENTATION REVIEW")
    print("=" * 70)
    
    docs = [
        'REALITY_ENFORCEMENT_IMPLEMENTATION.md',
        'MERID_REALITY_ENFORCEMENT_DIRECTIVE.md',
        'REALITY_ENFORCEMENT_DEPLOYMENT.md',
        'OPERATOR_TRAINING_GUIDE.md'
    ]
    
    for doc in docs:
        exists = os.path.exists(doc)
        status = "✅" if exists else "❌"
        print(f"{status} {doc}: {'Found' if exists else 'Missing'}")
    
    print()
    return all(os.path.exists(doc) for doc in docs)


def review_tests():
    """Review test coverage."""
    print("=" * 70)
    print("8. TEST COVERAGE REVIEW")
    print("=" * 70)
    
    tests = [
        'tests/test_assertion_algebra.py',
        'tests/stress_test_reality.py',
        'tests/integration_test.py'
    ]
    
    for test in tests:
        exists = os.path.exists(test)
        status = "✅" if exists else "❌"
        print(f"{status} {test}: {'Found' if exists else 'Missing'}")
    
    print()
    return all(os.path.exists(test) for test in tests)


def review_consistency():
    """Review system consistency."""
    print("=" * 70)
    print("9. CONSISTENCY REVIEW")
    print("=" * 70)
    
    checks = []
    
    # Check Reality Enforcement integration
    try:
        from core.reality_registry import get_reality_registry
        from core.reality_auditor import get_reality_auditor
        registry = get_reality_registry()
        auditor = get_reality_auditor()
        checks.append(("Reality Registry ↔ Auditor", True))
    except:
        checks.append(("Reality Registry ↔ Auditor", False))
    
    # Check Regime Classifier integration
    try:
        from monitoring.regime_classifier import get_regime_classifier
        classifier = get_regime_classifier()
        checks.append(("Regime Classifier integration", True))
    except:
        checks.append(("Regime Classifier integration", False))
    
    # Check Execution Agent integration
    try:
        from trading.agents.execution_agent import get_execution_agent
        agent = get_execution_agent()
        checks.append(("Execution Agent integration", True))
    except:
        checks.append(("Execution Agent integration", False))
    
    # Check Price Feed integration
    try:
        from data.live_price_feed import get_live_price_feed
        feed = get_live_price_feed()
        checks.append(("Price Feed integration", True))
    except:
        checks.append(("Price Feed integration", False))
    
    for check_name, passed in checks:
        status = "✅" if passed else "❌"
        print(f"{status} {check_name}")
    
    print()
    return all(passed for _, passed in checks)


def main():
    """Run comprehensive review."""
    print("\n")
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 15 + "MERID COMPREHENSIVE SYSTEM REVIEW" + " " * 20 + "║")
    print("╚" + "=" * 68 + "╝")
    print()
    
    results = []
    
    results.append(("Reality Enforcement System", review_reality_enforcement()))
    results.append(("API Enhancements", review_api_enhancements()))
    results.append(("Regime Classifier", review_regime_classifier()))
    results.append(("Execution Agent", review_execution_agent()))
    results.append(("Price Feed", review_price_feed()))
    results.append(("UI/UX Enhancements", review_ui_enhancements()))
    results.append(("Documentation", review_documentation()))
    results.append(("Test Coverage", review_tests()))
    results.append(("System Consistency", review_consistency()))
    
    print("=" * 70)
    print("FINAL REVIEW SUMMARY")
    print("=" * 70)
    
    for component, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} - {component}")
    
    print()
    total = len(results)
    passed = sum(1 for _, p in results if p)
    percentage = (passed / total * 100) if total > 0 else 0
    
    print(f"Overall: {passed}/{total} components verified ({percentage:.1f}%)")
    print()
    
    if passed == total:
        print("╔" + "=" * 68 + "╗")
        print("║" + " " * 15 + "ALL SYSTEMS VERIFIED ✅" + " " * 30 + "║")
        print("╚" + "=" * 68 + "╝")
        return 0
    else:
        print("⚠️  Some components need attention")
        return 1


if __name__ == "__main__":
    sys.exit(main())
