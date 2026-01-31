# MERID Local Self-Building v0.1 README

## Overview

MERID Local Self-Building capability enables autonomous development without paid LLM dependencies. The system uses local LLM providers (Ollama, LM Studio, vLLM) to coordinate a swarm of dev agents that can implement features, fix bugs, and improve the codebase.

## Architecture

### Components

1. **Local LLM Gateway** (`swarm/local_llm_gateway.py`)
   - Unified interface to local LLM providers
   - Automatic provider fallback
   - Token budget management
   - Request routing by model availability

2. **Dev Swarm Orchestrator** (`swarm/dev_swarm_orchestrator.py`)
   - Coordinates multiple dev agents (coder, reviewer, tester, architect)
   - Task queue management
   - Agent assignment and workflow
   - Code review and testing pipelines

3. **Collaborative Swarm Guardrails** (`swarm/collaborative_swarm_guardrails.py`)
   - Critical file protection
   - Operation safety checks
   - Code quality enforcement
   - Security scanning
   - Rate limiting and budget controls

### Agent Roles

- **Coder Agents**: Feature implementation, bug fixes, refactoring
- **Reviewer Agents**: Code review, security audits, best practices
- **Tester Agents**: Unit testing, integration testing, test generation
- **Architect Agents**: System design, architecture review, refactoring

## Setup

### Prerequisites

1. **Hardware Requirements**
   - CPU: 8+ cores recommended (16+ for optimal performance)
   - RAM: 32GB minimum (64GB+ recommended)
   - GPU: Optional but recommended (NVIDIA with 16GB+ VRAM for larger models)
   - Storage: 100GB+ free space for models

2. **Software Requirements**
   - Python 3.11+
   - One or more local LLM providers:
     - Ollama (recommended): https://ollama.ai
     - LM Studio: https://lmstudio.ai
     - vLLM: https://github.com/vllm-project/vllm

### Installation

#### 1. Install Ollama (Recommended)

```bash
# macOS/Linux
curl -fsSL https://ollama.ai/install.sh | sh

# Windows
# Download from https://ollama.ai/download
```

#### 2. Pull Recommended Models

```bash
# Code generation models
ollama pull codellama:13b
ollama pull deepseek-coder:6.7b

# General purpose models
ollama pull llama3.1:8b
ollama pull mistral:7b
```

#### 3. Configure MERID

```python
from swarm.local_llm_gateway import get_local_llm_gateway

gateway = get_local_llm_gateway()

# Verify provider status
status = gateway.get_provider_status()
print(status)
```

#### 4. Start Dev Swarm

```python
from swarm.dev_swarm_orchestrator import get_dev_swarm_orchestrator, DevTask, TaskType, TaskStatus
import asyncio

orchestrator = get_dev_swarm_orchestrator()

# Submit a task
task = DevTask(
    task_id="feature_001",
    task_type=TaskType.FEATURE,
    description="Add logging to execution engine",
    priority=5,
    status=TaskStatus.PENDING,
)

orchestrator.submit_task(task)

# Start orchestration
await orchestrator.start()

# Check status
status = orchestrator.get_swarm_status()
print(status)
```

## Usage Examples

### Example 1: Feature Implementation

```python
from swarm.dev_swarm_orchestrator import get_dev_swarm_orchestrator, DevTask, TaskType, TaskStatus

orchestrator = get_dev_swarm_orchestrator()

task = DevTask(
    task_id="add_metrics",
    task_type=TaskType.FEATURE,
    description="Add performance metrics to social-aware quant engine",
    priority=8,
    status=TaskStatus.PENDING,
)

task_id = orchestrator.submit_task(task)
print(f"Submitted task: {task_id}")
```

### Example 2: Bug Fix

```python
task = DevTask(
    task_id="fix_rate_limit",
    task_type=TaskType.BUG_FIX,
    description="Fix rate limiting issue in X bot interface",
    priority=10,
    status=TaskStatus.PENDING,
)

orchestrator.submit_task(task)
```

### Example 3: Checking Guardrails

```python
from swarm.collaborative_swarm_guardrails import get_collaborative_swarm_guardrails

guardrails = get_collaborative_swarm_guardrails()

# Check if file modification is allowed
check = guardrails.check_file_modification("core/automated_risk_controls.py")
if check.blocked:
    print(f"Modification blocked: {check.message}")

# Check code quality
code = """
def example_function():
    # TODO: implement this
    pass
"""
quality_check = guardrails.check_code_quality(code)
print(f"Quality check: {quality_check.message}")

# Check security
security_check = guardrails.check_security(code)
print(f"Security check: {security_check.message}")
```

## Guardrails and Safety

### Critical Files (Require Human Approval)

- `core/automated_risk_controls.py`
- `trading/execution.py`
- `governance/multi_agent_risk_controls.py`
- `core/memecoin_safety.py`
- `wallet/multi_chain_wallet.py`
- `security/breach_detection.py`
- `core/reality_registry.py`
- `core/reality_auditor.py`
- `.env`
- `config/production.yaml`
- `master_roadmap_checklist.txt`

### Blocked Operations

- `delete_database`
- `drop_table`
- `disable_all_risk_controls`
- `bypass_authentication`
- `expose_private_keys`
- `disable_guardrails`
- `modify_kill_switch`

### Rate Limits

- **Daily Operation Limit**: 100 operations per day
- **Token Budget**: 1,000,000 tokens per day
- **Concurrent Requests**: 4 per provider (configurable)

## Limitations

### Current Limitations

1. **Model Quality**: Local models are less capable than GPT-4/Claude
   - May produce lower quality code
   - May require more iterations
   - May miss edge cases

2. **Hardware Requirements**: Significant compute resources needed
   - Larger models require GPU
   - Inference can be slow on CPU
   - RAM requirements scale with model size

3. **Context Window**: Smaller context windows than cloud models
   - Limited to ~4K-8K tokens for most models
   - May struggle with large codebases
   - Requires careful prompt engineering

4. **No Internet Access**: Local models cannot access external resources
   - Cannot search documentation
   - Cannot fetch latest API specs
   - Cannot verify external dependencies

5. **Limited Reasoning**: Weaker reasoning capabilities
   - May struggle with complex architectural decisions
   - May miss subtle bugs
   - May produce suboptimal solutions

### Workarounds

1. **Hybrid Approach**: Use local models for routine tasks, escalate complex tasks to human review
2. **Iterative Refinement**: Run multiple passes with review/test cycles
3. **Template-Based**: Use code templates and patterns for common tasks
4. **Human-in-Loop**: Require human approval for critical changes
5. **Gradual Rollout**: Start with low-risk tasks, expand as confidence grows

## Monitoring and Observability

### Check Swarm Status

```python
orchestrator = get_dev_swarm_orchestrator()
status = orchestrator.get_swarm_status()

print(f"Running: {status['running']}")
print(f"Queue Length: {status['queue_length']}")
print(f"Completed Tasks: {status['tasks']['completed']}")
print(f"Failed Tasks: {status['tasks']['failed']}")
```

### Check LLM Gateway Status

```python
gateway = get_local_llm_gateway()
status = gateway.get_provider_status()

print(f"Token Budget Remaining: {status['token_budget']['remaining']}")
print(f"Request History: {status['request_history']}")
```

### Check Guardrail Status

```python
guardrails = get_collaborative_swarm_guardrails()
status = guardrails.get_guardrail_status()

print(f"Operations Today: {status['operations_today']}/{status['daily_limit']}")
print(f"Recent Violations: {status['recent_violations_1h']}")
```

## Next Steps

### Phase 1: Validation (Current)
- [x] Implement core components
- [x] Add guardrails and safety checks
- [ ] Test with simple tasks
- [ ] Validate code quality
- [ ] Measure performance

### Phase 2: Enhancement
- [ ] Add more sophisticated code analysis
- [ ] Implement multi-file refactoring
- [ ] Add dependency management
- [ ] Improve test generation
- [ ] Add documentation generation

### Phase 3: Integration
- [ ] Integrate with CI/CD pipeline
- [ ] Add GitHub integration
- [ ] Implement PR generation
- [ ] Add code review automation
- [ ] Connect to issue tracker

### Phase 4: Advanced Features
- [ ] Multi-agent collaboration patterns
- [ ] Learning from human feedback
- [ ] Automated architecture evolution
- [ ] Self-optimization capabilities
- [ ] Cross-repository learning

## Troubleshooting

### Ollama Not Responding

```bash
# Check if Ollama is running
ollama list

# Restart Ollama service
# macOS/Linux
systemctl restart ollama

# Windows
# Restart from Services
```

### Model Loading Issues

```bash
# Check available models
ollama list

# Pull model again if corrupted
ollama pull codellama:13b
```

### Out of Memory

```bash
# Use smaller models
ollama pull codellama:7b
ollama pull mistral:7b

# Or adjust model parameters
# Edit provider config to use quantized models
```

### Slow Performance

1. Use GPU if available
2. Use smaller models (7B instead of 13B)
3. Reduce concurrent requests
4. Increase hardware resources

## Support and Contributing

- **Documentation**: `docs/`
- **Issues**: Submit to internal issue tracker
- **Code Review**: All changes require human review
- **Testing**: Run full test suite before deployment

## License

Internal use only. See LICENSE file for details.

---

**Version**: 0.1  
**Last Updated**: 2026-01-15  
**Status**: Experimental - Use with caution
