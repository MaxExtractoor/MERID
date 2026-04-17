"""Debug why fallback imports fail inside the API endpoints."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Test 1: CalibrationStore
print("=== CalibrationStore ===")
try:
    from merid.metrics.calibration import get_calibration_store
    store = get_calibration_store()
    forecasters = store.list_forecasters()
    print(f"  list_forecasters(): {forecasters}")
    for fid in forecasters:
        summary = store.get_forecaster_summary(fid)
        print(f"  {fid}: {summary}")
except Exception as e:
    print(f"  FAIL: {type(e).__name__}: {e}")

# Test 2: AgentGrid
print("\n=== AgentGrid ===")
try:
    from merid.prediction.agent_grid import get_agent_grid
    grid = get_agent_grid()
    print(f"  agents count: {len(grid.agents)}")
    for name, agent in list(grid.agents.items())[:3]:
        print(f"  {name}: cycles={agent.cycles_run}, orders={agent.orders_placed}, asset={getattr(agent, 'asset', 'N/A')}")
except Exception as e:
    print(f"  FAIL: {type(e).__name__}: {e}")

# Test 3: DebateStore opinions
print("\n=== DebateStore opinions ===")
try:
    from merid.prediction.debate import get_debate_store
    ds = get_debate_store()
    opinions = ds.list_opinions(limit=10)
    print(f"  opinions: {len(opinions)}")
    for op in opinions[:2]:
        d = op.to_dict() if hasattr(op, "to_dict") else op
        print(f"  {d.get('agent_id')}: conf={d.get('confidence')}")
except Exception as e:
    print(f"  FAIL: {type(e).__name__}: {e}")

# Test 4: NotificationStore
print("\n=== NotificationStore ===")
try:
    from core.notifications import get_notification_store
    store = get_notification_store()
    notes = store.list(limit=5)
    print(f"  notifications: {len(notes)}")
    for n in notes[:2]:
        nd = n.to_dict() if hasattr(n, "to_dict") else {}
        print(f"  {nd.get('type', '?')}: {nd.get('message', nd.get('title', ''))[:80]}")
except Exception as e:
    print(f"  FAIL: {type(e).__name__}: {e}")
