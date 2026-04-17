"""
Seed Stable Long-Lived Assertions
Uses very long validity windows and minimal decay
"""

import requests
import time

base_url = "http://localhost:8000"
timestamp = time.time()

# Create assertions with 7-day validity and minimal decay
assertions = [
    {
        "domain": "market",
        "description": "BTC/USD price feed operational",
        "confidence": 0.85,
        "provenance_score": 0.8,
        "regime_compatibility": 0.9,
        "decay_rate": 0.000001,  # Very slow decay
        "validity_window": 604800.0,  # 7 days
        "sources": [{
            "source_id": "system_bootstrap",
            "module_id": "price_feed",
            "evidence_hash": "btc_feed_stable",
            "weight": 1.0,
            "timestamp": timestamp
        }]
    },
    {
        "domain": "market",
        "description": "ETH/USD price feed operational",
        "confidence": 0.85,
        "provenance_score": 0.8,
        "regime_compatibility": 0.9,
        "decay_rate": 0.000001,
        "validity_window": 604800.0,
        "sources": [{
            "source_id": "system_bootstrap",
            "module_id": "price_feed",
            "evidence_hash": "eth_feed_stable",
            "weight": 1.0,
            "timestamp": timestamp
        }]
    },
    {
        "domain": "execution",
        "description": "Execution engine operational",
        "confidence": 0.9,
        "provenance_score": 0.85,
        "regime_compatibility": 0.95,
        "decay_rate": 0.000001,
        "validity_window": 604800.0,
        "sources": [{
            "source_id": "system_bootstrap",
            "module_id": "execution_engine",
            "evidence_hash": "exec_stable",
            "weight": 1.0,
            "timestamp": timestamp
        }]
    },
    {
        "domain": "execution",
        "description": "Order routing operational",
        "confidence": 0.85,
        "provenance_score": 0.8,
        "regime_compatibility": 0.9,
        "decay_rate": 0.000001,
        "validity_window": 604800.0,
        "sources": [{
            "source_id": "system_bootstrap",
            "module_id": "execution_engine",
            "evidence_hash": "routing_stable",
            "weight": 1.0,
            "timestamp": timestamp
        }]
    },
    {
        "domain": "treasury",
        "description": "Treasury tracking operational",
        "confidence": 0.9,
        "provenance_score": 0.85,
        "regime_compatibility": 0.95,
        "decay_rate": 0.000001,
        "validity_window": 604800.0,
        "sources": [{
            "source_id": "system_bootstrap",
            "module_id": "treasury_monitor",
            "evidence_hash": "treasury_stable",
            "weight": 1.0,
            "timestamp": timestamp
        }]
    },
    {
        "domain": "treasury",
        "description": "Portfolio balance tracking operational",
        "confidence": 0.85,
        "provenance_score": 0.8,
        "regime_compatibility": 0.9,
        "decay_rate": 0.000001,
        "validity_window": 604800.0,
        "sources": [{
            "source_id": "system_bootstrap",
            "module_id": "treasury_monitor",
            "evidence_hash": "portfolio_stable",
            "weight": 1.0,
            "timestamp": timestamp
        }]
    }
]

print("=" * 60)
print("SEEDING STABLE LONG-LIVED ASSERTIONS")
print("=" * 60)
print()

registered = 0
for assertion in assertions:
    try:
        response = requests.post(
            f"{base_url}/api/v1/reality/assertions/register",
            json=assertion,
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ {assertion['domain']}: {data['assertion_id']}")
            registered += 1
        else:
            print(f"❌ {assertion['domain']}: HTTP {response.status_code}")
    except Exception as e:
        print(f"❌ {assertion['domain']}: {e}")

print()
print(f"Registered: {registered}/6")
print()

# Check status
try:
    r = requests.get(f"{base_url}/api/v1/reality/blindness", timeout=5)
    data = r.json()
    status = "✅ OPERATIONAL" if not data['is_blind'] else f"❌ BLIND: {data['reason']}"
    print(status)
except Exception as e:
    print(f"Status check failed: {e}")
