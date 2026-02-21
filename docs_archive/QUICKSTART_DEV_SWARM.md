# MERID Dev Swarm - Quick Start Guide

**Get your autonomous development swarm running in 5 minutes.**

---

## Prerequisites

- Python 3.9+
- Node.js 16+ (for React UI)
- MERID backend running
- All dependencies installed

---

## Step 1: Verify Installation

```bash
# Check if Dev Swarm is integrated
python -c "from core.dev_swarm import create_merid_dev_swarm; print('✓ Dev Swarm available')"

# Check API route
grep -r "dev_swarm_router" web/main.py && echo "✓ API integrated"

# Check UI component
ls web/react/src/views/DevSwarm.tsx && echo "✓ UI integrated"
```

---

## Step 2: Start Backend

```bash
# From MERID root directory
python -m uvicorn web.main:app --host 0.0.0.0 --port 8000 --reload
```

**Expected output:**
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete
```

---

## Step 3: Verify API

```bash
# Health check
curl http://localhost:8000/api/dev-swarm/health | jq

# Expected: {"status":"healthy", ...}

# List agents
curl http://localhost:8000/api/dev-swarm/agents | jq

# Expected: Array of 4 agents (Planner, Coder, Tester, Reviewer)
```

---

## Step 4: Access UI

1. **Open browser**: Navigate to `http://localhost:8000`
2. **Find Dev Swarm**: Look for "Dev Swarm" in the sidebar or URL bar
3. **Navigate**: Click "Dev Swarm" or go to `http://localhost:8000/?view=devswarm`

**You should see:**
- Stats dashboard (active tasks, success rate, etc.)
- "+ New Task" button
- Empty task list (initially)

---

## Step 5: Create Your First Task

### Via UI:

1. Click **"+ New Task"**
2. Fill out the form:
   - **Description**: "Add unit tests for example module"
   - **Target Files** (one per line):
     ```
     core/example.py
     tests/test_example.py
     ```
   - **Success Criteria**: "Achieve 85% test coverage"
   - **Priority**: P1 - Critical
   - **Effort**: Medium
   - **Timeout**: 1800 seconds (30 min)
   - **Max Cost**: $5.00
3. Click **"Create Task"**
4. Task will appear in the list with status "running"
5. Auto-refreshes every 5 seconds

### Via API:

```bash
curl -X POST http://localhost:8000/api/dev-swarm/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Add unit tests for example module",
    "target_files": ["core/example.py", "tests/test_example.py"],
    "success_criteria": "Achieve 85% test coverage",
    "priority": 1,
    "estimated_effort": "medium",
    "timeout_seconds": 1800,
    "max_cost_usd": 5.0
  }'
```

### Via Python:

```python
import asyncio
from core.dev_swarm import create_merid_dev_swarm, DevTask

async def main():
    # Create swarm
    swarm = create_merid_dev_swarm()
    
    # Create task
    task = DevTask(
        description="Add unit tests for example module",
        target_files=["core/example.py", "tests/test_example.py"],
        success_criteria="Achieve 85% test coverage",
        priority=1
    )
    
    # Execute
    result = await swarm.execute_task(task)
    
    # Check result
    print(f"Status: {result.status}")
    print(f"Duration: {result.duration_seconds}s")
    print(f"Cost: ${result.cost_usd:.2f}")

asyncio.run(main())
```

---

## Step 6: Monitor Progress

### In UI:
- Task list shows real-time status
- Click task row to see details
- Status badges: 🟢 completed, 🔵 running, 🔴 failed, 🟠 timeout

### Via API:

```bash
# Get task details
curl http://localhost:8000/api/dev-swarm/tasks/task-1707186300000 | jq

# Monitor stats
watch -n 2 'curl -s http://localhost:8000/api/dev-swarm/stats | jq'

# List all tasks
curl http://localhost:8000/api/dev-swarm/tasks | jq
```

---

## Step 7: Run Validation

```bash
# Comprehensive validation
python scripts/validate_dev_swarm.py

# Quick validation (skips task creation)
python scripts/validate_dev_swarm.py --quick
```

**Expected output:**
```
[1/7] ✓ API Health Check              PASS
[2/7] ✓ Agent Registration            PASS
[3/7] ✓ Stats Endpoint                PASS
[4/7] ✓ Task Listing                  PASS
[5/7] ✓ Config Endpoint               PASS
[6/7] ✓ Safety Limits                 PASS
[7/7] ✓ Task Creation                 PASS

✓ ALL CHECKS PASSED - Dev Swarm is operational!
```

---

## Common Tasks

### Check System Stats

```bash
curl http://localhost:8000/api/dev-swarm/stats | jq
```

### Cancel a Running Task

```bash
# Get task ID from task list
TASK_ID="task-1707186300000"

# Cancel it
curl -X DELETE http://localhost:8000/api/dev-swarm/tasks/$TASK_ID
```

### Update Configuration

```bash
# Increase concurrent task limit
curl -X POST "http://localhost:8000/api/dev-swarm/config?max_concurrent_tasks=10"

# Increase daily budget
curl -X POST "http://localhost:8000/api/dev-swarm/config?max_daily_cost_usd=200"
```

### View Logs

```bash
# All Dev Swarm logs
tail -f logs/merid.log | grep -i "dev.*swarm"

# Task-specific logs
tail -f logs/merid.log | grep "task-1707186300000"
```

---

## Example Workflows

### Coverage Gap Fix

```python
from core.dev_swarm import DevTaskTemplates

# Generate task for coverage gap
task = DevTaskTemplates.fix_coverage_gap(
    module_path="core/energy.py",
    current_coverage=45.0,
    target_coverage=85.0
)

# Execute via API or programmatically
```

### Add Tests for New Module

```python
task = DevTaskTemplates.add_tests_for_module(
    module_path="trading/new_feature.py",
    test_type="unit"
)
```

### Code Quality Refactor

```python
task = DevTaskTemplates.refactor_for_quality(
    file_path="utils/legacy_code.py",
    issues=["high complexity", "missing type hints", "no docstrings"]
)
```

---

## Troubleshooting

### "Connection refused" error

**Problem**: Backend not running

**Solution**:
```bash
python -m uvicorn web.main:app --reload
```

### "No agents registered"

**Problem**: create_merid_dev_swarm() not called

**Solution**: Check `web/main.py` startup or manually initialize:
```python
from core.dev_swarm import create_merid_dev_swarm
swarm = create_merid_dev_swarm()
```

### Tasks stuck in "running"

**Problem**: Task timeout not working or task crashed

**Solution**:
```bash
# Check logs
tail -100 logs/merid.log | grep -i error

# Force cancel
curl -X DELETE http://localhost:8000/api/dev-swarm/tasks/TASK_ID
```

### UI not showing Dev Swarm

**Problem**: React build out of date or not compiled

**Solution**:
```bash
cd web/react
npm install
npm run build
# Or for dev: npm run dev
```

### TypeScript errors in IDE

**Problem**: Modules not recognized (expected during development)

**Solution**:
```bash
cd web/react
npm run build  # Compiles TypeScript
# Or restart TypeScript server in IDE
```

---

## Safety Limits

Default safety limits (configured in `SwarmConfig`):

| Limit | Default | Purpose |
|-------|---------|---------|
| **Max concurrent tasks** | 5 | Prevent overload |
| **Max concurrent agents** | 10 | Resource control |
| **Task timeout** | 30 min | Prevent stuck tasks |
| **Agent timeout** | 5 min | Prevent stuck agents |
| **Daily cost budget** | $100 | Cost control |
| **Task cost limit** | $5 | Per-task budget |

To modify:
```python
from core.dev_swarm import SwarmConfig, DevSwarm

config = SwarmConfig(
    max_concurrent_tasks=10,
    max_daily_cost_usd=200.0,
    default_task_timeout=3600  # 1 hour
)

swarm = DevSwarm(config=config)
```

---

## Next Steps

### Essential (Before Production)

1. **Add State Persistence**
   - Tasks currently in-memory only
   - Add database or file storage
   - See `DEV_SWARM_INTEGRATION_SUMMARY.md` for details

2. **Add Authentication**
   - Currently no access control
   - Implement JWT or API key auth
   - Add per-user budgets

3. **Integrate Real LLM APIs**
   - Currently agents only run tools
   - Add DeepSeek/Claude API calls
   - Implement actual code generation

### Recommended

4. **Add WebSocket Real-Time Updates**
   - Replace polling with WebSockets
   - Stream agent logs live

5. **Add Comprehensive Tests**
   - Run: `pytest tests/test_dev_swarm.py -v`
   - Add API endpoint tests
   - Mock LLM responses

6. **Set Up Monitoring**
   - Prometheus metrics
   - Grafana dashboard
   - Alerting on failures

### Advanced

7. **CI/CD Integration**
   - Trigger on test failures
   - Auto-create PRs

8. **Distributed Workers**
   - Add Celery/RQ
   - Scale horizontally

---

## Getting Help

**Documentation**:
- `AGENT_SPAWNER_SPEC.md` - Detailed spawner specification
- `DEV_SWARM_INTEGRATION_SUMMARY.md` - Complete integration details
- `tests/test_dev_swarm.py` - Test examples

**Validation**:
```bash
python scripts/validate_dev_swarm.py
```

**Logs**:
```bash
tail -f logs/merid.log | grep -i "swarm"
```

**Health Check**:
```bash
curl http://localhost:8000/api/dev-swarm/health | jq
```

---

## Quick Reference

```bash
# Start backend
python -m uvicorn web.main:app --reload

# Validate integration
python scripts/validate_dev_swarm.py

# Run tests
pytest tests/test_dev_swarm.py -v

# Create task (API)
curl -X POST http://localhost:8000/api/dev-swarm/tasks -H "Content-Type: application/json" -d @task.json

# Check stats
curl http://localhost:8000/api/dev-swarm/stats | jq

# View UI
open http://localhost:8000/?view=devswarm
```

---

**You're ready to use MERID Dev Swarm!** 🎉

Start by creating a simple task and watch your autonomous development agents at work.
