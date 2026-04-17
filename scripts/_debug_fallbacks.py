"""Debug why fallback data isn't populating."""
import requests, json

BASE = "http://localhost:8011"

# Check grid agents (should have data)
r = requests.get(f"{BASE}/api/v1/kalshi-grid/agents", timeout=30)
d = r.json()
agents = d.get("agents", [])
print(f"Grid agents: {len(agents)}")
if agents:
    print(f"  First: {json.dumps(agents[0], indent=2)[:200]}")

# Check forecasters (should have data)
r = requests.get(f"{BASE}/api/v1/kalshi/metrics/forecasters", timeout=30)
d = r.json()
forecasters = d.get("forecasters", [])
print(f"\nForecasters: {len(forecasters)}")
if forecasters:
    print(f"  First: {json.dumps(forecasters[0], indent=2)[:200]}")

# Check calibration (should now have fallback)
r = requests.get(f"{BASE}/api/v1/kalshi-grid/performance/calibration", timeout=30)
d = r.json()
cal_agents = d.get("agents", [])
print(f"\nCalibration agents: {len(cal_agents)}")
if cal_agents:
    print(f"  First: {json.dumps(cal_agents[0], indent=2)[:200]}")

# Check perf agents
r = requests.get(f"{BASE}/api/v1/kalshi-grid/performance/agents", timeout=30)
d = r.json()
perf_agents = d.get("agents", {})
print(f"\nPerf agents: {len(perf_agents)}")
if perf_agents:
    first_key = list(perf_agents.keys())[0]
    print(f"  First key: {first_key}")
    print(f"  First val: {json.dumps(perf_agents[first_key], indent=2)[:200]}")

# Check teams 
r = requests.get(f"{BASE}/api/v1/prediction/consensus/teams", timeout=30)
d = r.json()
teams = d.get("teams", [])
print(f"\nTeams: {len(teams)}")
if teams:
    print(f"  First: {json.dumps(teams[0], indent=2)[:200]}")

# Check leaderboard
r = requests.get(f"{BASE}/api/v1/prediction/consensus/leaderboard", timeout=30)
d = r.json()
lb_agents = d.get("agents", [])
print(f"\nLeaderboard agents: {len(lb_agents)}")
if lb_agents:
    print(f"  First: {json.dumps(lb_agents[0], indent=2)[:200]}")

# Check telegram log 
r = requests.get(f"{BASE}/api/v1/notifications/telegram/log", timeout=30)
d = r.json()
msgs = d.get("messages", [])
print(f"\nTelegram messages: {len(msgs)}")
if msgs:
    print(f"  First: {json.dumps(msgs[0], indent=2)[:200]}")
