"""
Direct Reality Assertion Seeder - Bypasses HTTP layer
Seeds assertions directly into the Reality Registry
"""

import sys
import time

# Add parent directory to path
sys.path.insert(0, 'c:/Dev/MERID')

from core.reality_registry import get_reality_registry, AssertionDomain, AssertionProvenance

def seed_baseline_assertions():
    """Seed baseline assertions directly into registry."""
    
    print("=" * 60)
    print("SEEDING BASELINE REALITY ASSERTIONS (DIRECT)")
    print("=" * 60)
    print()
    
    registry = get_reality_registry()
    timestamp = time.time()
    
    assertions = [
        {
            "domain": AssertionDomain.MARKET,
            "description": "BTC/USD price feed operational (bootstrap)",
            "confidence": 0.6,
            "provenance_score": 0.5,
            "regime_compatibility": 0.7,
            "decay_rate": 0.0001,
            "validity_window": 3600.0,
            "sources": [
                AssertionProvenance(
                    source_id="bootstrap",
                    module_id="system_init",
                    evidence_hash="baseline_market_btc",
                    weight=1.0,
                    timestamp=timestamp
                )
            ]
        },
        {
            "domain": AssertionDomain.MARKET,
            "description": "ETH/USD price feed operational (bootstrap)",
            "confidence": 0.6,
            "provenance_score": 0.5,
            "regime_compatibility": 0.7,
            "decay_rate": 0.0001,
            "validity_window": 3600.0,
            "sources": [
                AssertionProvenance(
                    source_id="bootstrap",
                    module_id="system_init",
                    evidence_hash="baseline_market_eth",
                    weight=1.0,
                    timestamp=timestamp
                )
            ]
        },
        {
            "domain": AssertionDomain.EXECUTION,
            "description": "Execution engine initialized and ready (bootstrap)",
            "confidence": 0.7,
            "provenance_score": 0.6,
            "regime_compatibility": 0.8,
            "decay_rate": 0.00005,
            "validity_window": 7200.0,
            "sources": [
                AssertionProvenance(
                    source_id="bootstrap",
                    module_id="execution_engine",
                    evidence_hash="baseline_execution",
                    weight=1.0,
                    timestamp=timestamp
                )
            ]
        },
        {
            "domain": AssertionDomain.EXECUTION,
            "description": "Order routing available (bootstrap)",
            "confidence": 0.65,
            "provenance_score": 0.6,
            "regime_compatibility": 0.75,
            "decay_rate": 0.0001,
            "validity_window": 3600.0,
            "sources": [
                AssertionProvenance(
                    source_id="bootstrap",
                    module_id="execution_engine",
                    evidence_hash="baseline_routing",
                    weight=1.0,
                    timestamp=timestamp
                )
            ]
        },
        {
            "domain": AssertionDomain.TREASURY,
            "description": "Treasury state tracking operational (bootstrap)",
            "confidence": 0.7,
            "provenance_score": 0.65,
            "regime_compatibility": 0.8,
            "decay_rate": 0.00005,
            "validity_window": 7200.0,
            "sources": [
                AssertionProvenance(
                    source_id="bootstrap",
                    module_id="treasury_monitor",
                    evidence_hash="baseline_treasury",
                    weight=1.0,
                    timestamp=timestamp
                )
            ]
        },
        {
            "domain": AssertionDomain.TREASURY,
            "description": "Portfolio balance tracking available (bootstrap)",
            "confidence": 0.65,
            "provenance_score": 0.6,
            "regime_compatibility": 0.75,
            "decay_rate": 0.0001,
            "validity_window": 3600.0,
            "sources": [
                AssertionProvenance(
                    source_id="bootstrap",
                    module_id="treasury_monitor",
                    evidence_hash="baseline_portfolio",
                    weight=1.0,
                    timestamp=timestamp
                )
            ]
        },
        {
            "domain": AssertionDomain.ONCHAIN,
            "description": "On-chain telemetry feed synchronized (bootstrap)",
            "confidence": 0.7,
            "provenance_score": 0.65,
            "regime_compatibility": 0.8,
            "decay_rate": 0.00005,
            "validity_window": 3600.0,
            "sources": [
                AssertionProvenance(
                    source_id="bootstrap",
                    module_id="onchain_monitor",
                    evidence_hash="baseline_onchain",
                    weight=1.0,
                    timestamp=timestamp
                )
            ]
        },
        {
            "domain": AssertionDomain.GOVERNANCE,
            "description": "Governance queue responsive (bootstrap)",
            "confidence": 0.65,
            "provenance_score": 0.6,
            "regime_compatibility": 0.78,
            "decay_rate": 0.0001,
            "validity_window": 5400.0,
            "sources": [
                AssertionProvenance(
                    source_id="bootstrap",
                    module_id="governance_core",
                    evidence_hash="baseline_governance",
                    weight=1.0,
                    timestamp=timestamp
                )
            ]
        },
        {
            "domain": AssertionDomain.SIMULATION,
            "description": "Shadow simulation running baseline scenarios",
            "confidence": 0.6,
            "provenance_score": 0.55,
            "regime_compatibility": 0.75,
            "decay_rate": 0.0001,
            "validity_window": 3600.0,
            "sources": [
                AssertionProvenance(
                    source_id="bootstrap",
                    module_id="shadow_sim",
                    evidence_hash="baseline_simulation",
                    weight=1.0,
                    timestamp=timestamp
                )
            ]
        },
        {
            "domain": AssertionDomain.AGENT,
            "description": "Core agent mesh responsive (bootstrap)",
            "confidence": 0.7,
            "provenance_score": 0.65,
            "regime_compatibility": 0.82,
            "decay_rate": 0.00005,
            "validity_window": 5400.0,
            "sources": [
                AssertionProvenance(
                    source_id="bootstrap",
                    module_id="agent_mesh",
                    evidence_hash="baseline_agents",
                    weight=1.0,
                    timestamp=timestamp
                )
            ]
        },
        {
            "domain": AssertionDomain.SYSTEM,
            "description": "System clock, event bus, and state pipeline healthy",
            "confidence": 0.75,
            "provenance_score": 0.7,
            "regime_compatibility": 0.85,
            "decay_rate": 0.00005,
            "validity_window": 7200.0,
            "sources": [
                AssertionProvenance(
                    source_id="bootstrap",
                    module_id="system_health",
                    evidence_hash="baseline_system",
                    weight=1.0,
                    timestamp=timestamp
                )
            ]
        }
    ]
    
    registered = 0
    for assertion_data in assertions:
        try:
            assertion_id = registry.register_assertion(**assertion_data)
            print(f"✓ Registered: {assertion_data['domain'].value} - {assertion_data['description'][:60]}")
            print(f"  ID: {assertion_id}")
            registered += 1
        except Exception as e:
            print(f"✗ Failed: {assertion_data['domain'].value} - {e}")
    
    print()
    print("=" * 60)
    print(f"SEEDING COMPLETE: {registered} assertions registered")
    print("=" * 60)
    print()
    
    # Check blindness status
    from core.reality_auditor import get_reality_auditor
    auditor = get_reality_auditor()
    
    is_blind, reason = registry.check_blindness_condition(time.time(), auditor.regime_entropy)
    
    if is_blind:
        print(f"⚠️  SYSTEM STILL IN BLINDNESS MODE: {reason}")
    else:
        print(f"✓ SYSTEM OPERATIONAL: {reason}")
    
    print()
    
    # Show registry stats
    stats = registry.get_registry_status(time.time(), auditor.regime_entropy)
    print("Registry Status:")
    print(f"  Total Assertions: {stats.get('total_assertions')}")
    print(f"  Valid %: {stats.get('valid_pct')}")
    print(f"  Expired %: {stats.get('expired_pct')}")
    print(f"  Conflicted %: {stats.get('conflicted_pct')}")
    print(f"  Regime entropy: {stats.get('regime_entropy')}")
    print()


if __name__ == "__main__":
    seed_baseline_assertions()
