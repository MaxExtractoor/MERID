# MERID Agent Spawner Specification

**Version**: 1.0  
**Status**: Current Implementation Analysis  
**Location**: `core/dev_swarm.py`

---

## Overview

MERID's Agent Spawner is implemented as the **DevSwarm** system - a multi-agent development orchestrator that automates code generation, testing, and quality assurance using LLM-powered agents.

---

## Core Components

### 1. DevSwarm Class

**Purpose**: Main orchestrator that manages agent lifecycle and task execution.

**Interface**:
```python
class DevSwarm:
    def __init__(self, agents: List[DevAgent] = None)
    def register_agent(self, agent: DevAgent) -> None
    async def execute_task(self, task: DevTask) -> Dict[str, Any]
```

**Key Methods**:
- `register_agent()` - Add agent to swarm
- `execute_task()` - Execute multi-phase development task
- `_find_agent()` - Locate agent by role
- `_run_agent_phase()` - Execute single agent phase

### 2. Agent Definition

**DevAgent Dataclass**:
```python
@dataclass
class DevAgent:
    name: str                    # Unique identifier
    role: DevAgentRole          # PLANNER, CODER, TESTER, REVIEWER, AUDITOR
    llm_model: str              # LLM backend (e.g., "deepseek-chat")
    system_prompt: str          # Agent instructions
    tools: List[Callable]       # Available functions
    max_iterations: int = 5     # Retry limit
```

### 3. Task Definition

**DevTask Dataclass**:
```python
@dataclass
class DevTask:
    description: str            # Human-readable task description
    target_files: List[str]     # Files to modify/test
    success_criteria: str       # Completion criteria
    priority: int = 1           # Task priority (1=highest)
    estimated_effort: str = "medium"  # small, medium, large
```

---

## Agent Roles

### Currently Implemented

| Role | Agent Name | Purpose | Tools | Max Iterations |
|------|-----------|---------|-------|----------------|
| **PLANNER** | CoveragePlanner | Analyze coverage gaps and create test plan | analyze_coverage | 3 |
| **CODER** | PyTestCoder | Write comprehensive pytest tests | run_pytest | 5 |
| **TESTER** | TestValidator | Run tests and verify coverage | run_pytest, analyze_coverage | 3 |
| **REVIEWER** | CodeReviewer | Quality checks with linters | run_linters, get_git_status | 2 |
| **AUDITOR** | (not implemented) | Security and architecture review | TBD | TBD |

---

## Execution Pipeline

### Standard Flow

```
Task Submitted
    ↓
Phase 1: Planning (PLANNER agent)
    ↓
Phase 2: Coding (CODER agent)
    ↓
Phase 3: Testing (TESTER agent)
    ↓ (if tests fail)
Phase 2b: Coding Retry (CODER agent, max_iterations--)
    ↓
Phase 4: Review (REVIEWER agent)
    ↓
Results Aggregated
```

### Phase Execution

Each phase:
1. Builds agent-specific prompt with task + context
2. Executes agent tools
3. Returns structured result
4. Result added to context for next phase

### Retry Logic

- Tests fail → CODER retries with test feedback
- CODER max_iterations decremented on retry
- No retries for PLANNER or REVIEWER phases

---

## Tool Functions

### Available Tools

1. **analyze_coverage(task)** - Run `coverage report` on target files
2. **run_pytest(task)** - Execute pytest with test files
3. **run_linters(task)** - Run ruff and mypy on target files
4. **get_git_status(task)** - Get git status and diff stats

### Tool Interface

```python
def tool_function(task: DevTask) -> Dict[str, Any]:
    """
    Tools receive DevTask and return structured results.
    
    Returns:
        {
            "command": str,      # Command executed
            "stdout": str,       # Output
            "stderr": str,       # Errors
            "returncode": int,   # Exit code
            "passed": bool,      # Success flag (optional)
            "error": str         # Error message (if failed)
        }
    """
```

---

## Configuration

### LLM Models

- Default: `"deepseek-chat"`
- Configurable per agent
- No model selection logic or fallback currently

### Limits & Constraints

**Current Limits**:
- Max iterations per agent: 5 (CODER), 3 (PLANNER/TESTER), 2 (REVIEWER)
- No concurrent agent limit
- No timeout per agent or task
- No cost tracking or budgets
- No rate limiting

**⚠️ MISSING SAFETY GUARDRAILS**:
- No maximum concurrent agents
- No task timeout
- No cost caps
- No rate limiting
- No resource limits (CPU, memory)

---

## Lifecycle Management

### Agent Lifecycle

**Startup**: Agents registered to DevSwarm instance  
**Execution**: Agents invoked sequentially per pipeline phase  
**Supervision**: None - agents run until completion or max_iterations  
**Termination**: No explicit cleanup or shutdown

### Task Lifecycle

**Creation**: DevTask instantiated manually or via templates  
**Execution**: `swarm.execute_task(task)` runs pipeline  
**State**: No persistence - results returned, not stored  
**History**: `task_history` list (append-only, in-memory)

---

## Failure Modes

### Current Behavior

1. **Agent tool failure**: Caught, returns `{"error": str(e)}`
2. **Test failure**: Triggers CODER retry (if iterations remain)
3. **LLM failure**: Not handled (would raise exception)
4. **Timeout**: No timeout mechanism
5. **Resource exhaustion**: No protection

### Missing Error Handling

- [ ] Graceful LLM API failures
- [ ] Network timeout handling
- [ ] Task-level timeout
- [ ] Agent crash recovery
- [ ] Partial result recovery
- [ ] Rollback on failure

---

## Safety & Security

### Current Controls

✅ Tool execution isolated to subprocess  
✅ Git operations read-only (status, diff)  
⚠️ No file write protection  
⚠️ No path traversal checks  
⚠️ No command injection protection  
⚠️ No resource limits  

### Missing Safeguards

- [ ] File write permissions/sandboxing
- [ ] Command whitelist/validation
- [ ] Resource quotas (CPU, memory, disk)
- [ ] Rate limiting on tool execution
- [ ] Audit logging of all operations
- [ ] Cost tracking and budgets
- [ ] Agent permission model

---

## Integration Points

### How to Use DevSwarm

**Basic Usage**:
```python
from core.dev_swarm import create_merid_dev_swarm, DevTask

# Create swarm
swarm = create_merid_dev_swarm()

# Create task
task = DevTask(
    description="Add unit tests for trading router",
    target_files=["trading/router.py"],
    success_criteria="Achieve 85% coverage with passing tests",
    priority=1
)

# Execute
results = await swarm.execute_task(task)
```

**Task Templates**:
```python
from core.dev_swarm import DevTaskTemplates

# Coverage gap
task = DevTaskTemplates.fix_coverage_gap("core/energy.py", 45.0, 85.0)

# Add tests
task = DevTaskTemplates.add_tests_for_module("trading/router.py", "unit")

# Refactor
task = DevTaskTemplates.refactor_for_quality("file.py", ["complexity", "typing"])
```

---

## Current Limitations

### Architecture

1. **Sequential Execution**: Agents run in pipeline, no parallelization
2. **In-Memory State**: No persistence, results lost on restart
3. **No Supervision**: Tasks run until complete, no monitoring
4. **No Scaling**: Single swarm instance, no distribution
5. **No API**: Must be imported and called programmatically

### Operational

1. **No 24/7 Capability**: Not designed for daemon operation
2. **No Observability**: Basic logging only, no metrics
3. **No Alerting**: Failures silent beyond logs
4. **No Recovery**: Crashes require manual restart
5. **No UI**: Command-line only

### Safety

1. **No Resource Limits**: Can spawn unlimited subprocess work
2. **No Cost Control**: LLM API calls unbounded
3. **No Permissions**: Agents can modify any file
4. **No Sandboxing**: Full system access
5. **No Audit Trail**: Limited traceability

---

## Recommended Enhancements

### Priority 1: Safety & Limits

- [ ] Task-level timeout (e.g., 30 minutes max)
- [ ] Agent-level timeout (e.g., 5 minutes max per phase)
- [ ] Max concurrent agents (e.g., 5)
- [ ] Cost tracking and budget enforcement
- [ ] Rate limiting on LLM calls
- [ ] Resource quotas (CPU, memory)

### Priority 2: Robustness

- [ ] Graceful error handling and retries
- [ ] State persistence (tasks, runs, outputs)
- [ ] Supervisor/watchdog for long-running tasks
- [ ] Health checks and recovery
- [ ] Structured logging and metrics

### Priority 3: Operationalization

- [ ] REST API for task submission
- [ ] WebSocket for real-time updates
- [ ] Task queue with priorities
- [ ] Background worker daemon
- [ ] UI dashboard integration

### Priority 4: Advanced Features

- [ ] Parallel agent execution (where safe)
- [ ] Agent collaboration (shared context)
- [ ] Dynamic agent spawning based on task
- [ ] Learning from past executions
- [ ] Integration with CI/CD pipelines

---

## API Specification (Proposed)

### REST Endpoints

```
POST   /api/dev-swarm/tasks          # Create new task
GET    /api/dev-swarm/tasks          # List tasks
GET    /api/dev-swarm/tasks/:id      # Get task details
DELETE /api/dev-swarm/tasks/:id      # Cancel task
GET    /api/dev-swarm/agents         # List available agents
GET    /api/dev-swarm/stats          # System stats
```

### WebSocket Events

```
swarm_task_started      # Task execution began
swarm_phase_started     # Agent phase started
swarm_phase_completed   # Agent phase completed
swarm_task_completed    # Task finished
swarm_task_failed       # Task failed
swarm_agent_error       # Agent encountered error
```

---

## Summary

**What Works**:
- ✅ Basic multi-agent pipeline (Plan → Code → Test → Review)
- ✅ Agent role abstraction with tools
- ✅ Retry logic for test failures
- ✅ Pre-configured MERID dev agents
- ✅ Task templates for common workflows

**What's Missing**:
- ❌ Safety limits (timeout, cost, concurrency)
- ❌ Persistent state and history
- ❌ API layer for external access
- ❌ UI integration
- ❌ 24/7 operational readiness
- ❌ Monitoring and alerting
- ❌ Error recovery and rollback
- ❌ Sandboxing and permissions

**Risk Level**: 🔴 **HIGH** - Not production-ready for 24/7 autonomous operation

---

**Next Steps**: Follow steps 1-8 of the integration plan to harden and operationalize this system.
