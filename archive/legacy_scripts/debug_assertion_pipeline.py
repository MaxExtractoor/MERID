"""
Debug Assertion Registration and Retrieval.

This script debugs the assertion pipeline to identify where the disconnect is occurring.
"""

import requests
import time

def debug_assertion_pipeline():
    """Debug the assertion registration and retrieval pipeline."""
    print('🔍 Debugging Assertion Pipeline')
    print('=' * 50)
    
    try:
        # Step 1: Check initial state
        print('1. Checking initial registry state...')
        response = requests.get("http://127.0.0.1:8001/api/v1/reality/status", timeout=5)
        assert response.status_code == 200
        
        data = response.json()
        registry_status = data["system_state"]["registry_status"]
        print(f'   ✅ Registry Status: {registry_status}')
        
        # Step 2: Load demo data with debug
        print('\n2. Loading demo data with debug...')
        
        # Load market data
        print('   Loading market data...')
        response = requests.post("http://127.0.0.1:8001/api/v1/market/demo-data", timeout=5)
        assert response.status_code == 200
        market_result = response.json()
        print(f'   ✅ Market API Response: {market_result}')
        
        # Step 3: Check market assertions directly
        print('\n3. Checking market assertions directly...')
        response = requests.get("http://127.0.0.1:8001/api/v1/market/assertions", timeout=5)
        assert response.status_code == 200
        
        market_assertions = response.json()
        print(f'   ✅ Market Assertions API Response: {market_assertions}')
        
        # Step 4: Check registry directly
        print('\n4. Checking registry directly...')
        
        # Import and check registry directly
        from core.reality_registry import get_reality_registry, AssertionDomain
        
        registry = get_reality_registry()
        print(f'   ✅ Registry Instance: {registry}')
        
        # Get market assertions from registry
        market_domain_assertions = registry.get_assertions_by_domain(AssertionDomain.MARKET)
        print(f'   ✅ Market Domain Assertions (from registry): {len(market_domain_assertions)}')
        
        # Show details of first few assertions
        for i, assertion in enumerate(market_domain_assertions[:3]):
            print(f'   ✅ Assertion {i+1}: {assertion.assertion_id} - {assertion.status} - {assertion.description}')
        
        # Step 5: Check all domains
        print('\n5. Checking all domains...')
        
        domains = [AssertionDomain.MARKET, AssertionDomain.ONCHAIN, AssertionDomain.SIMULATION, AssertionDomain.AGENT]
        domain_counts = {}
        
        for domain in domains:
            domain_assertions = registry.get_assertions_by_domain(domain)
            valid_count = sum(1 for a in domain_assertions if a.status == AssertionStatus.VALID)
            domain_counts[domain.value] = {
                "total": len(domain_assertions),
                "valid": valid_count
            }
            print(f'   ✅ {domain.value}: {len(domain_assertions)} total, {valid_count} valid')
        
        # Step 6: Test safety check logic directly
        print('\n6. Testing safety check logic directly...')
        
        from core.reality_auditor import get_reality_auditor
        
        auditor = get_reality_auditor()
        current_time = time.time()
        
        # Run safety checks
        safety_result = auditor._run_sighted_degraded_safety_checks(registry_status, current_time)
        print(f'   ✅ Safety Check Result: {safety_result}')
        
        # Step 7: Check system state
        print('\n7. Checking system state...')
        system_state = auditor.get_system_state()
        print(f'   ✅ System State: {system_state}')
        
        print('\n🔍 Debug Results Summary:')
        print('✅ Registry accessible')
        print('✅ Demo data loading works')
        print('✅ API endpoints respond')
        print('✅ Direct registry access works')
        
        # Analysis
        total_valid = sum(count["valid"] for count in domain_counts.values())
        print(f'\n📊 Analysis:')
        print(f'   - Total Valid Assertions: {total_valid}')
        print(f'   - Safety Check Passed: {safety_result["passed"]}')
        print(f'   - System Mode: {system_state["mode"]}')
        
        if total_valid >= 20:
            print('\n🎯 SUCCESS: Assertions are properly registered and valid!')
            print('The assertion pipeline is working correctly.')
            return True
        else:
            print(f'\n❌ ISSUE: Only {total_valid} valid assertions found (need ≥20)')
            print('The assertions are being registered but not marked as valid.')
            return False
        
    except Exception as e:
        print(f'❌ Debug failed: {e}')
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = debug_assertion_pipeline()
    if success:
        print("\n🎯 Assertion pipeline debug complete!")
        print("The assertion registration and retrieval is working correctly.")
    else:
        print("\n❌ Assertion pipeline needs further debugging")
        print("Check assertion registration, status assignment, and retrieval logic.")
