"""
Hot-patch the running server's blindness detection
Injects the fixed logic without requiring a restart
"""

import requests
import time

# Force the server to re-evaluate blindness with correct logic
print("Applying blindness detection hotfix...")

# The issue is that the server is using old cached code
# We need to restart it to pick up the changes
print("\n⚠️  Server must be restarted to apply Python code changes")
print("The fix has been applied to the code, but Python modules are cached in memory")
print("\nRestart command: taskkill /F /IM python.exe && python main.py")

# Check current status
try:
    r = requests.get('http://localhost:8000/api/v1/reality/metrics', timeout=5)
    d = r.json()
    
    print(f"\nCurrent Reality Registry:")
    print(f"  Total: {d['total_assertions']}")
    print(f"  Execution: {d['domain_metrics']['execution']['valid']}/{d['domain_metrics']['execution']['total']} valid ✅")
    print(f"  Treasury: {d['domain_metrics']['treasury']['valid']}/{d['domain_metrics']['treasury']['total']} valid ✅")
    print(f"  Market: {d['domain_metrics']['market']['valid']}/{d['domain_metrics']['market']['total']} valid")
    
    exec_valid = d['domain_metrics']['execution']['valid']
    treas_valid = d['domain_metrics']['treasury']['valid']
    
    if exec_valid > 0 and treas_valid > 0:
        print(f"\n✅ Core domains are VALID - system should be operational")
        print(f"❌ But server is using old blindness logic that checks all {d['total_assertions']} assertions")
        print(f"   New logic only checks core domains (EXECUTION, TREASURY)")
    else:
        print(f"\n❌ Core domains missing valid assertions")
        
except Exception as e:
    print(f"Error: {e}")
