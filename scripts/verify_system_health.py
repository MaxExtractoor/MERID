"""
MERID System Health Verification
Checks all critical systems and provides diagnostic output
"""

import sys
sys.path.insert(0, 'c:/Dev/MERID')

import time
from core.reality_registry import get_reality_registry
from core.reality_auditor import get_reality_auditor
from monitoring.prediction_markets import get_prediction_aggregator

def verify_reality_system():
    """Verify Reality Enforcement System."""
    print("=" * 60)
    print("REALITY ENFORCEMENT SYSTEM")
    print("=" * 60)
    
    try:
        registry = get_reality_registry()
        auditor = get_reality_auditor()
        current_time = time.time()
        
        # Check blindness
        is_blind, reason = registry.check_blindness_condition(current_time, auditor.regime_entropy)
        
        if is_blind:
            print(f"❌ STATUS: BLINDNESS MODE")
            print(f"   Reason: {reason}")
        else:
            print(f"✅ STATUS: OPERATIONAL")
            print(f"   Reason: {reason}")
        
        # Get stats
        stats = registry.get_registry_status(current_time, auditor.regime_entropy)
        
        print(f"\n📊 Registry Metrics:")
        print(f"   Total Assertions: {stats['total_assertions']}")
        print(f"   Valid: {stats['valid_assertions']}")
        print(f"   Expired: {stats['expired_assertions']}")
        print(f"   Conflicted: {stats['conflicted_assertions']}")
        print(f"   Coverage: {stats['coverage_pct']:.1f}%")
        print(f"   Regime Entropy: {auditor.regime_entropy:.3f}")
        
        # Check core domains
        from core.reality_registry import AssertionDomain
        print(f"\n🎯 Core Domain Coverage:")
        for domain in [AssertionDomain.MARKET, AssertionDomain.EXECUTION, AssertionDomain.TREASURY]:
            assertions = registry.get_assertions_by_domain(domain)
            valid = sum(1 for a in assertions if a.is_usable(current_time, auditor.regime_entropy))
            status = "✅" if valid > 0 else "❌"
            print(f"   {status} {domain.value.upper()}: {valid} valid assertion(s)")
        
        print()
        return not is_blind
        
    except Exception as e:
        print(f"❌ ERROR: {e}")
        print()
        return False


def verify_prediction_markets():
    """Verify Prediction Market Aggregator."""
    print("=" * 60)
    print("PREDICTION MARKET AGGREGATOR")
    print("=" * 60)
    
    try:
        aggregator = get_prediction_aggregator()
        status = aggregator.get_status()
        
        if status['running']:
            print(f"✅ STATUS: RUNNING")
        else:
            print(f"⚠️  STATUS: NOT RUNNING")
        
        print(f"\n📊 Aggregator Metrics:")
        print(f"   Total Markets: {status['total_markets']}")
        print(f"   Drift Signals: {status['drift_signals']}")
        print(f"   Arbitrage Opportunities: {status['arbitrage_opportunities']}")
        print(f"   Platforms: {', '.join(status['platforms'])}")
        
        print(f"\n🎯 Markets by Platform:")
        for platform, count in status['markets_by_platform'].items():
            icon = "✅" if count > 0 else "⚠️"
            print(f"   {icon} {platform}: {count} markets")
        
        print()
        return True
        
    except Exception as e:
        print(f"❌ ERROR: {e}")
        print()
        return False


def verify_endpoints():
    """Verify critical API endpoints are accessible."""
    print("=" * 60)
    print("API ENDPOINT HEALTH")
    print("=" * 60)
    
    try:
        import httpx
        import asyncio
        
        async def check_endpoints():
            endpoints = [
                "/api/v1/reality/status",
                "/api/v1/reality/blindness",
                "/api/v1/institutional/predictions/drift",
                "/api/v1/institutional/predictions/arbitrage",
                "/api/v1/institutional/predictions/urgent",
            ]
            
            async with httpx.AsyncClient(timeout=5.0) as client:
                for endpoint in endpoints:
                    try:
                        response = await client.get(f"http://localhost:8000{endpoint}")
                        if response.status_code == 200:
                            print(f"   ✅ {endpoint}")
                        else:
                            print(f"   ⚠️  {endpoint} - HTTP {response.status_code}")
                    except Exception as e:
                        print(f"   ❌ {endpoint} - {e}")
        
        asyncio.run(check_endpoints())
        print()
        return True
        
    except Exception as e:
        print(f"❌ ERROR: {e}")
        print()
        return False


def main():
    """Run all verifications."""
    print("\n" + "=" * 60)
    print("MERID SYSTEM HEALTH CHECK")
    print("=" * 60)
    print()
    
    results = {
        "Reality System": verify_reality_system(),
        "Prediction Markets": verify_prediction_markets(),
        "API Endpoints": verify_endpoints(),
    }
    
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    all_pass = True
    for system, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} - {system}")
        if not passed:
            all_pass = False
    
    print()
    
    if all_pass:
        print("🎉 ALL SYSTEMS OPERATIONAL")
    else:
        print("⚠️  SOME SYSTEMS NEED ATTENTION")
    
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()
