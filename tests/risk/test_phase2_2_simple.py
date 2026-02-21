#!/usr/bin/env python3
"""
Simple Phase 2.2 Test
Tests basic connectivity to the new APIs
"""

import requests
import json

def test_phase2_2_simple():
    """Simple test for Phase 2.2 APIs"""
    print("🎯 TESTING PHASE 2.2 - SIMPLE CONNECTIVITY")
    print("=" * 60)
    
    base_url = "http://127.0.0.1:8011"
    
    # Test endpoints
    endpoints = [
        ("/api/v1/prediction/markets", "Prediction Markets"),
        ("/api/v1/prediction/stats", "Prediction Stats"),
        ("/api/v1/agent-cohorts/cohorts", "Agent Cohorts"),
        ("/api/v1/agent-cohorts/agents/list", "Agent List"),
        ("/api/v1/agent-cohorts/stats", "Agent Stats"),
        ("/api/v1/arbitrage/opportunities", "Arbitrage Opportunities"),
        ("/api/v1/system/health", "System Health"),
    ]
    
    results = []
    
    for endpoint, name in endpoints:
        try:
            url = f"{base_url}{endpoint}"
            response = requests.get(url, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and 'markets' in data:
                    count = len(data.get('markets', []))
                    results.append((name, "✅", f"{count} items"))
                elif isinstance(data, dict) and 'cohorts' in data:
                    count = len(data.get('cohorts', []))
                    results.append((name, "✅", f"{count} cohorts"))
                elif isinstance(data, dict) and 'agents' in data:
                    count = len(data.get('agents', []))
                    results.append((name, "✅", f"{count} agents"))
                else:
                    results.append((name, "✅", "Data available"))
            else:
                results.append((name, "❌", f"Status {response.status_code}"))
                
        except requests.exceptions.RequestException as e:
            results.append((name, "❌", f"Connection error: {e}"))
        except Exception as e:
            results.append((name, "❌", f"Error: {e}"))
    
    # Print results
    print(f"\n📊 RESULTS")
    print("=" * 60)
    
    for name, status, details in results:
        print(f"{status} {name}: {details}")
    
    # Summary
    total = len(results)
    passed = len([r for r in results if "✅" in r[0]])
    
    print(f"\n📈 SUMMARY")
    print("=" * 60)
    print(f"📁 Total Tests: {total}")
    print(f"✅ Passed: {passed}")
    print(f"❌ Failed: {total - passed}")
    print(f"📈 Success Rate: {(passed/total*100):.1f}%")
    
    if passed == total:
        print(f"\n🎉 PHASE 2.2 SIMPLE TEST SUCCESS!")
        print(f"✅ All endpoints responding correctly")
        print(f"✅ Ready for full integration testing")
    else:
        print(f"\n⚠️  PHASE 2.2 PARTIAL SUCCESS")
        print(f"✅ {passed}/{total} endpoints working")
        print(f"❌ {total - passed} endpoints need attention")
    
    return passed == total

if __name__ == "__main__":
    test_phase2_2_simple()
