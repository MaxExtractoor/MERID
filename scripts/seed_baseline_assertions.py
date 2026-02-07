"""
Seed Baseline Reality Assertions

Seeds the Reality Registry with baseline assertions for core domains
to prevent blindness mode on system startup.

CONSTITUTIONAL: These are bootstrap assertions with conservative confidence.
They should be replaced by real data-driven assertions as the system runs.
"""

import asyncio
import time
import httpx
from typing import Dict, Any


BASELINE_ASSERTIONS = [
    {
        "domain": "market",
        "description": "BTC/USD price feed operational (bootstrap)",
        "confidence": 0.6,
        "provenance_score": 0.5,
        "regime_compatibility": 0.7,
        "decay_rate": 0.0001,
        "validity_window": 3600.0,
        "sources": [
            {
                "source_id": "bootstrap",
                "module_id": "system_init",
                "evidence_hash": "baseline_market_assertion",
                "weight": 1.0,
                "timestamp": time.time()
            }
        ]
    },
    {
        "domain": "market",
        "description": "ETH/USD price feed operational (bootstrap)",
        "confidence": 0.6,
        "provenance_score": 0.5,
        "regime_compatibility": 0.7,
        "decay_rate": 0.0001,
        "validity_window": 3600.0,
        "sources": [
            {
                "source_id": "bootstrap",
                "module_id": "system_init",
                "evidence_hash": "baseline_market_assertion_eth",
                "weight": 1.0,
                "timestamp": time.time()
            }
        ]
    },
    {
        "domain": "execution",
        "description": "Execution engine initialized and ready (bootstrap)",
        "confidence": 0.7,
        "provenance_score": 0.6,
        "regime_compatibility": 0.8,
        "decay_rate": 0.00005,
        "validity_window": 7200.0,
        "sources": [
            {
                "source_id": "bootstrap",
                "module_id": "execution_engine",
                "evidence_hash": "baseline_execution_assertion",
                "weight": 1.0,
                "timestamp": time.time()
            }
        ]
    },
    {
        "domain": "execution",
        "description": "Order routing available (bootstrap)",
        "confidence": 0.65,
        "provenance_score": 0.6,
        "regime_compatibility": 0.75,
        "decay_rate": 0.0001,
        "validity_window": 3600.0,
        "sources": [
            {
                "source_id": "bootstrap",
                "module_id": "execution_engine",
                "evidence_hash": "baseline_routing_assertion",
                "weight": 1.0,
                "timestamp": time.time()
            }
        ]
    },
    {
        "domain": "treasury",
        "description": "Treasury state tracking operational (bootstrap)",
        "confidence": 0.7,
        "provenance_score": 0.65,
        "regime_compatibility": 0.8,
        "decay_rate": 0.00005,
        "validity_window": 7200.0,
        "sources": [
            {
                "source_id": "bootstrap",
                "module_id": "treasury_monitor",
                "evidence_hash": "baseline_treasury_assertion",
                "weight": 1.0,
                "timestamp": time.time()
            }
        ]
    },
    {
        "domain": "treasury",
        "description": "Portfolio balance tracking available (bootstrap)",
        "confidence": 0.65,
        "provenance_score": 0.6,
        "regime_compatibility": 0.75,
        "decay_rate": 0.0001,
        "validity_window": 3600.0,
        "sources": [
            {
                "source_id": "bootstrap",
                "module_id": "treasury_monitor",
                "evidence_hash": "baseline_portfolio_assertion",
                "weight": 1.0,
                "timestamp": time.time()
            }
        ]
    },
    {
        "domain": "agent",
        "description": "Agent mesh initialized (bootstrap)",
        "confidence": 0.65,
        "provenance_score": 0.6,
        "regime_compatibility": 0.75,
        "decay_rate": 0.0001,
        "validity_window": 3600.0,
        "sources": [
            {
                "source_id": "bootstrap",
                "module_id": "agent_mesh",
                "evidence_hash": "baseline_agent_assertion",
                "weight": 1.0,
                "timestamp": time.time()
            }
        ]
    },
    {
        "domain": "consensus",
        "description": "Consensus engine operational (bootstrap)",
        "confidence": 0.7,
        "provenance_score": 0.65,
        "regime_compatibility": 0.8,
        "decay_rate": 0.00005,
        "validity_window": 7200.0,
        "sources": [
            {
                "source_id": "bootstrap",
                "module_id": "consensus_engine",
                "evidence_hash": "baseline_consensus_assertion",
                "weight": 1.0,
                "timestamp": time.time()
            }
        ]
    }
]


async def seed_assertions(base_url: str = "http://localhost:8000"):
    """Seed baseline assertions via Reality API."""
    
    print("=" * 60)
    print("SEEDING BASELINE REALITY ASSERTIONS")
    print("=" * 60)
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        registered = 0
        failed = 0
        
        for assertion in BASELINE_ASSERTIONS:
            try:
                response = await client.post(
                    f"{base_url}/api/v1/reality/assertions/register",
                    json=assertion
                )
                
                if response.status_code == 200:
                    data = response.json()
                    assertion_id = data.get("assertion_id", "unknown")
                    print(f"✓ Registered: {assertion['domain']} - {assertion['description'][:60]}...")
                    print(f"  ID: {assertion_id}")
                    registered += 1
                else:
                    print(f"✗ Failed: {assertion['domain']} - {response.status_code}")
                    print(f"  Response: {response.text}")
                    failed += 1
                    
            except Exception as e:
                print(f"✗ Error: {assertion['domain']} - {e}")
                failed += 1
        
        print()
        print("=" * 60)
        print(f"SEEDING COMPLETE: {registered} registered, {failed} failed")
        print("=" * 60)
        
        # Check blindness status
        try:
            response = await client.get(f"{base_url}/api/v1/reality/blindness")
            if response.status_code == 200:
                data = response.json()
                is_blind = data.get("is_blind", True)
                reason = data.get("reason", "unknown")
                
                print()
                if is_blind:
                    print(f"⚠️  SYSTEM STILL IN BLINDNESS MODE: {reason}")
                else:
                    print(f"✓ SYSTEM OPERATIONAL: {reason}")
            else:
                print(f"⚠️  Could not check blindness status: {response.status_code}")
        except Exception as e:
            print(f"⚠️  Could not check blindness status: {e}")
        
        print()


async def check_reality_status(base_url: str = "http://localhost:8000"):
    """Check current reality registry status."""
    
    print("=" * 60)
    print("REALITY REGISTRY STATUS")
    print("=" * 60)
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(f"{base_url}/api/v1/reality/metrics")
            if response.status_code == 200:
                data = response.json()
                
                print(f"Total Assertions: {data.get('total_assertions', 0)}")
                print(f"Regime Entropy: {data.get('regime_entropy', 0):.3f}")
                print()
                print("Domain Metrics:")
                
                domain_metrics = data.get("domain_metrics", {})
                for domain, metrics in domain_metrics.items():
                    print(f"  {domain.upper()}:")
                    print(f"    Total: {metrics.get('total', 0)}")
                    print(f"    Valid: {metrics.get('valid', 0)}")
                    print(f"    Valid %: {metrics.get('valid_pct', 0):.1f}%")
                    print(f"    Avg Confidence: {metrics.get('avg_confidence', 0):.3f}")
            else:
                print(f"Failed to fetch metrics: {response.status_code}")
        except Exception as e:
            print(f"Error fetching metrics: {e}")
    
    print()


if __name__ == "__main__":
    import sys
    
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    
    print(f"Target: {base_url}")
    print()
    
    asyncio.run(check_reality_status(base_url))
    asyncio.run(seed_assertions(base_url))
    asyncio.run(check_reality_status(base_url))
