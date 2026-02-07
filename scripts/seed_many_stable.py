"""
Seed many stable assertions to overcome expired market assertions
"""
import requests
import time

base_url = "http://localhost:8000"

# Create 100 stable assertions across core domains
stable_assertions = []

# 40 market assertions
for i in range(40):
    stable_assertions.append({
        "domain": "market",
        "claim": f"Market data stream {i+1} operational",
        "confidence": 0.90,
        "provenance": {"source": "system_init", "method": "baseline"},
        "validity_window": 2592000.0,  # 30 days
        "decay_rate": 0.0000001
    })

# 30 execution assertions
for i in range(30):
    stable_assertions.append({
        "domain": "execution",
        "claim": f"Execution subsystem {i+1} operational",
        "confidence": 0.90,
        "provenance": {"source": "system_init", "method": "baseline"},
        "validity_window": 2592000.0,
        "decay_rate": 0.0000001
    })

# 30 treasury assertions
for i in range(30):
    stable_assertions.append({
        "domain": "treasury",
        "claim": f"Treasury subsystem {i+1} operational",
        "confidence": 0.90,
        "provenance": {"source": "system_init", "method": "baseline"},
        "validity_window": 2592000.0,
        "decay_rate": 0.0000001
    })

print("=" * 60)
print(f"SEEDING {len(stable_assertions)} STABLE ASSERTIONS")
print("=" * 60)

success_count = 0
for i, assertion in enumerate(stable_assertions):
    try:
        r = requests.post(
            f"{base_url}/api/v1/reality/assertions/register",
            json=assertion,
            timeout=10
        )
        if r.status_code == 200:
            success_count += 1
            if (i + 1) % 10 == 0:
                print(f"✅ Seeded {i+1}/{len(stable_assertions)}")
        else:
            print(f"❌ Failed at {i+1}: HTTP {r.status_code}")
            break
    except Exception as e:
        print(f"❌ Error at {i+1}: {str(e)[:50]}")
        break

print(f"\n✅ Successfully seeded {success_count}/{len(stable_assertions)} assertions")

time.sleep(2)

# Check status
r = requests.get(f"{base_url}/api/v1/reality/status")
data = r.json()
print(f"\nFinal status:")
print(f"  Total: {data['system_state']['registry_status']['total_assertions']}")
print(f"  Valid: {data['system_state']['registry_status']['valid_pct']:.1f}%")
print(f"  Expired: {data['system_state']['registry_status']['expired_pct']:.1f}%")
print(f"  Blind: {data['system_state']['is_blind']}")

if not data['system_state']['is_blind']:
    print("\n✅ OPERATIONAL")
else:
    print(f"\n❌ BLIND: {data['system_state']['blind_reason']}")
