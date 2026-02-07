"""
Seed assertions via HTTP API using requests library
This will work with the running server instance
"""

import time
import json

try:
    import requests
except ImportError:
    print("Installing requests library...")
    import subprocess
    subprocess.check_call(['pip', 'install', 'requests'])
    import requests

def seed_assertions():
    """Seed baseline assertions via HTTP API."""
    
    base_url = "http://localhost:8000"
    timestamp = time.time()
    
    print("=" * 60)
    print("SEEDING BASELINE REALITY ASSERTIONS VIA API")
    print("=" * 60)
    print()
    
    assertions = [
        {
            "domain": "market",
            "description": "BTC/USD price feed operational (bootstrap)",
            "confidence": 0.6,
            "provenance_score": 0.5,
            "regime_compatibility": 0.7,
            "decay_rate": 0.0001,
            "validity_window": 3600.0,
            "sources": [{
                "source_id": "bootstrap",
                "module_id": "system_init",
                "evidence_hash": "baseline_market_btc",
                "weight": 1.0,
                "timestamp": timestamp
            }]
        },
        {
            "domain": "market",
            "description": "ETH/USD price feed operational (bootstrap)",
            "confidence": 0.6,
            "provenance_score": 0.5,
            "regime_compatibility": 0.7,
            "decay_rate": 0.0001,
            "validity_window": 3600.0,
            "sources": [{
                "source_id": "bootstrap",
                "module_id": "system_init",
                "evidence_hash": "baseline_market_eth",
                "weight": 1.0,
                "timestamp": timestamp
            }]
        },
        {
            "domain": "execution",
            "description": "Execution engine initialized (bootstrap)",
            "confidence": 0.7,
            "provenance_score": 0.6,
            "regime_compatibility": 0.8,
            "decay_rate": 0.00005,
            "validity_window": 7200.0,
            "sources": [{
                "source_id": "bootstrap",
                "module_id": "execution_engine",
                "evidence_hash": "baseline_execution",
                "weight": 1.0,
                "timestamp": timestamp
            }]
        },
        {
            "domain": "execution",
            "description": "Order routing available (bootstrap)",
            "confidence": 0.65,
            "provenance_score": 0.6,
            "regime_compatibility": 0.75,
            "decay_rate": 0.0001,
            "validity_window": 3600.0,
            "sources": [{
                "source_id": "bootstrap",
                "module_id": "execution_engine",
                "evidence_hash": "baseline_routing",
                "weight": 1.0,
                "timestamp": timestamp
            }]
        },
        {
            "domain": "treasury",
            "description": "Treasury state tracking operational (bootstrap)",
            "confidence": 0.7,
            "provenance_score": 0.65,
            "regime_compatibility": 0.8,
            "decay_rate": 0.00005,
            "validity_window": 7200.0,
            "sources": [{
                "source_id": "bootstrap",
                "module_id": "treasury_monitor",
                "evidence_hash": "baseline_treasury",
                "weight": 1.0,
                "timestamp": timestamp
            }]
        },
        {
            "domain": "treasury",
            "description": "Portfolio balance tracking (bootstrap)",
            "confidence": 0.65,
            "provenance_score": 0.6,
            "regime_compatibility": 0.75,
            "decay_rate": 0.0001,
            "validity_window": 3600.0,
            "sources": [{
                "source_id": "bootstrap",
                "module_id": "treasury_monitor",
                "evidence_hash": "baseline_portfolio",
                "weight": 1.0,
                "timestamp": timestamp
            }]
        }
    ]
    
    registered = 0
    failed = 0
    
    for assertion in assertions:
        try:
            response = requests.post(
                f"{base_url}/api/v1/reality/assertions/register",
                json=assertion,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                assertion_id = data.get("assertion_id", "unknown")
                print(f"✅ Registered: {assertion['domain']} - {assertion['description'][:60]}")
                print(f"   ID: {assertion_id}")
                registered += 1
            else:
                print(f"❌ Failed: {assertion['domain']} - HTTP {response.status_code}")
                print(f"   Response: {response.text[:100]}")
                failed += 1
                
        except Exception as e:
            print(f"❌ Error: {assertion['domain']} - {e}")
            failed += 1
    
    print()
    print("=" * 60)
    print(f"SEEDING COMPLETE: {registered} registered, {failed} failed")
    print("=" * 60)
    print()
    
    # Check blindness status
    try:
        response = requests.get(f"{base_url}/api/v1/reality/blindness", timeout=5)
        if response.status_code == 200:
            data = response.json()
            is_blind = data.get("is_blind", True)
            reason = data.get("reason", "unknown")
            
            if is_blind:
                print(f"⚠️  SYSTEM STILL IN BLINDNESS MODE: {reason}")
            else:
                print(f"✅ SYSTEM OPERATIONAL: {reason}")
        else:
            print(f"⚠️  Could not check blindness status: HTTP {response.status_code}")
    except Exception as e:
        print(f"⚠️  Could not check blindness status: {e}")
    
    print()
    
    # Show metrics
    try:
        response = requests.get(f"{base_url}/api/v1/reality/metrics", timeout=5)
        if response.status_code == 200:
            data = response.json()
            print("📊 Reality Registry Metrics:")
            print(f"   Total Assertions: {data.get('total_assertions', 0)}")
            print(f"   Regime Entropy: {data.get('regime_entropy', 0):.3f}")
            
            domain_metrics = data.get("domain_metrics", {})
            if domain_metrics:
                print("\n   Domain Coverage:")
                for domain, metrics in domain_metrics.items():
                    valid = metrics.get('valid', 0)
                    total = metrics.get('total', 0)
                    icon = "✅" if valid > 0 else "⚠️"
                    print(f"   {icon} {domain.upper()}: {valid}/{total} valid")
    except Exception as e:
        print(f"⚠️  Could not fetch metrics: {e}")
    
    print()


if __name__ == "__main__":
    seed_assertions()
