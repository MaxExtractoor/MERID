"""
Check which API endpoints exist for all unified dashboard sections
"""
import requests

base_url = "http://localhost:8000"

# Map sections to their likely API endpoints
section_endpoints = {
    'predictions': [
        '/api/v1/institutional/predictions/drift',
        '/api/v1/institutional/predictions/arbitrage',
        '/api/v1/institutional/predictions/urgent',
    ],
    'four_systems': ['/api/v1/institutional/systems/status'],
    'agents': ['/api/v1/dashboard/agents/status'],
    'consensus': ['/api/v1/dashboard/consensus/recent'],
    'simulation': ['/api/v1/simulation/status'],
    'shadow_merid': ['/api/v1/institutional/shadow/status'],
    'risk': [
        '/api/v1/institutional/risk/summary',
        '/api/v1/dashboard/risk/metrics'
    ],
    'audit_trail': ['/api/v1/audit/recent'],
    'execution': ['/api/v1/dashboard/execution/stats'],
    'analytics': ['/api/v1/dashboard/system/health'],
    'arbitrage': ['/api/v1/arbitrage/opportunities'],
    'portfolio': ['/api/v1/dashboard/portfolio/summary'],
    'backtest': ['/api/v1/backtest/results'],
    'alerts': ['/api/v1/alerts/active'],
    'monitoring': ['/api/v1/monitoring/status'],
    'rate_limits': ['/api/v1/ratelimit/status'],
    'backup': ['/api/v1/backup/status'],
    'plugins': ['/api/v1/plugins/list'],
    'compliance': ['/api/v1/compliance/status'],
    'wallet': ['/api/v1/wallet/status'],
    'treasury': ['/api/v1/treasury/status'],
    'sniping': ['/api/v1/sniping/status'],
    'recovery': ['/api/v1/recovery/status'],
    'spectator': ['/api/v1/spectator/status'],
}

print("=" * 80)
print("CHECKING API ENDPOINTS FOR UNIFIED DASHBOARD SECTIONS")
print("=" * 80)
print()

results = {}

for section, endpoints in section_endpoints.items():
    print(f"\n{section.upper().replace('_', ' ')}:")
    section_results = []
    
    for endpoint in endpoints:
        try:
            r = requests.get(f"{base_url}{endpoint}", timeout=5)
            status = "✅" if r.status_code == 200 else f"❌ {r.status_code}"
            print(f"  {status} {endpoint}")
            section_results.append({
                'endpoint': endpoint,
                'status': r.status_code,
                'working': r.status_code == 200
            })
        except Exception as e:
            print(f"  ❌ {endpoint} - ERROR: {str(e)[:50]}")
            section_results.append({
                'endpoint': endpoint,
                'status': 'error',
                'working': False
            })
    
    results[section] = section_results

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)

working_sections = []
broken_sections = []

for section, section_results in results.items():
    has_working = any(r['working'] for r in section_results)
    if has_working:
        working_sections.append(section)
    else:
        broken_sections.append(section)

print(f"\n✅ Sections with working endpoints ({len(working_sections)}):")
for section in working_sections:
    print(f"   - {section.replace('_', ' ').title()}")

print(f"\n❌ Sections needing endpoints ({len(broken_sections)}):")
for section in broken_sections:
    print(f"   - {section.replace('_', ' ').title()}")

print()
