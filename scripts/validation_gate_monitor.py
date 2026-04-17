#!/usr/bin/env python3
"""30-minute validation gate monitor for MERID backend."""

import asyncio
import aiohttp
import json
import sys
from datetime import datetime, timezone
from typing import List, Dict, Any

# Configuration
HEALTH_URL = "http://127.0.0.1:8011/api/health"
EVENT_LOOP_URL = "http://127.0.0.1:8011/health/event_loop"
GATE_DURATION_MINUTES = 30
SAMPLE_INTERVAL_SECONDS = 30

gate_pass = True
failures = []

async def sample_health(session: aiohttp.ClientSession, timestamp: str) -> Dict:
    """Sample health endpoints."""
    global gate_pass, failures
    
    try:
        async with session.get(HEALTH_URL, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            data = await resp.json()
            
            lag_data = data.get("checks", {}).get("event_loop_lag", {})
            p95 = lag_data.get("stats", {}).get("p95_ms", 0)
            degraded = lag_data.get("degraded", True)
            
            sample = {
                "timestamp": timestamp,
                "status": data.get("status"),
                "status_code": resp.status,
                "p95_ms": p95,
                "degraded": degraded,
                "startup_complete": data.get("checks", {}).get("agent_grid", {}).get("startup_complete"),
                "agents_ready": data.get("checks", {}).get("agent_grid", {}).get("agents_ready"),
            }
            
            # Check gate criteria
            if p95 >= 500:
                gate_pass = False
                failures.append(f"{timestamp}: P95={p95:.0f}ms >= 500ms threshold")
                print(f"  ❌ FAIL: P95={p95:.0f}ms >= 500ms")
            elif degraded:
                gate_pass = False
                failures.append(f"{timestamp}: degraded=true")
                print(f"  ❌ FAIL: degraded=true")
            else:
                print(f"  ✓ PASS: P95={p95:.0f}ms, degraded={degraded}")
            
            return sample
    except Exception as e:
        gate_pass = False
        failures.append(f"{timestamp}: Health check error: {e}")
        print(f"  ❌ FAIL: Health check error: {e}")
        return {"timestamp": timestamp, "error": str(e)}

async def run_validation_gate():
    """Run 30-minute validation gate."""
    global gate_pass
    
    print("="*70)
    print("MERID 30-MINUTE VALIDATION GATE")
    print("="*70)
    print(f"Duration: {GATE_DURATION_MINUTES} minutes")
    print(f"Sample interval: {SAMPLE_INTERVAL_SECONDS} seconds")
    print(f"Target: P95 < 500ms, degraded=false")
    print("="*70)
    print()
    
    samples: List[Dict] = []
    total_samples = (GATE_DURATION_MINUTES * 60) // SAMPLE_INTERVAL_SECONDS
    
    async with aiohttp.ClientSession() as session:
        # Wait for server to be ready
        print("Waiting for server to be ready...")
        for _ in range(60):
            try:
                async with session.get(HEALTH_URL, timeout=aiohttp.ClientTimeout(total=5)):
                    print("Server is up!\n")
                    break
            except:
                await asyncio.sleep(1)
        else:
            print("Server did not start within 60 seconds")
            gate_pass = False
            return
        
        print(f"Starting gate: {total_samples} samples over {GATE_DURATION_MINUTES} minutes\n")
        
        for i in range(total_samples):
            timestamp = datetime.now(timezone.utc).isoformat()
            print(f"[{i+1}/{total_samples}] {timestamp[:19]} - Sampling...", end=" ")
            
            sample = await sample_health(session, timestamp)
            samples.append(sample)
            
            if i < total_samples - 1:
                await asyncio.sleep(SAMPLE_INTERVAL_SECONDS)
    
    # Generate report
    generate_report(samples)

async def fetch_high_lag_profiles() -> List[Dict]:
    """Fetch any high-lag profiles captured during gate."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "http://127.0.0.1:8011/api/v1/diagnostics/loop-lag-profiles",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
                return data.get("profiles", [])
    except:
        return []

def generate_report(samples: List[Dict]):
    """Generate final validation report."""
    global gate_pass
    
    print("\n" + "="*70)
    print("VALIDATION GATE REPORT")
    print("="*70)
    
    valid_samples = [s for s in samples if "p95_ms" in s]
    
    if not valid_samples:
        print("No valid samples collected")
        gate_pass = False
        return
    
    p95_values = [s["p95_ms"] for s in valid_samples]
    avg_p95 = sum(p95_values) / len(p95_values)
    max_p95 = max(p95_values)
    min_p95 = min(p95_values)
    degraded_count = sum(1 for s in valid_samples if s.get("degraded"))
    
    print(f"\nSamples collected: {len(valid_samples)}")
    print(f"P95 range: {min_p95:.0f}ms - {max_p95:.0f}ms")
    print(f"Avg P95: {avg_p95:.0f}ms")
    print(f"Degraded samples: {degraded_count}/{len(valid_samples)}")
    
    # Check for high-lag profiles
    import asyncio
    profiles = asyncio.get_event_loop().run_until_complete(fetch_high_lag_profiles())
    
    if profiles:
        print(f"\n⚠️  High-lag profiles captured: {len(profiles)}")
        gate_pass = False
        failures.append(f"{len(profiles)} high-lag profiles captured during gate")
    else:
        print(f"\n✓ No high-lag profiles captured")
    
    print("\n" + "="*70)
    if gate_pass:
        print("✅ GATE PASSED")
        print("All criteria met:")
        print("  - P95 < 500ms for all samples")
        print("  - degraded=false for all samples")
        print("  - No high-lag profiles captured")
    else:
        print("❌ GATE FAILED")
        print("\nFailures:")
        for f in failures[:10]:
            print(f"  - {f}")
        if len(failures) > 10:
            print(f"  ... and {len(failures) - 10} more")
    print("="*70)
    
    # Save report
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "duration_minutes": GATE_DURATION_MINUTES,
        "samples": len(valid_samples),
        "p95_min": min_p95,
        "p95_max": max_p95,
        "p95_avg": avg_p95,
        "degraded_samples": degraded_count,
        "high_lag_profiles": len(profiles),
        "passed": gate_pass,
        "failures": failures,
    }
    
    report_file = f"validation_gate_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_file, 'w') as f:
        json.dump(report, f, indent=2)
    print(f"\nReport saved: {report_file}")
    
    sys.exit(0 if gate_pass else 1)

if __name__ == "__main__":
    asyncio.run(run_validation_gate())
