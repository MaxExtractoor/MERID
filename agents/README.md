# MERID Multi-Agent System - Agent Prompts

**Version:** 1.0  
**Date:** January 12, 2026

---

## 📚 AGENT PROMPT FILES

This directory contains the complete system prompts for all 5 constitutional enforcement agents.

### **Agent Files:**

1. **`state-constitution-agent.md`** - Guardian of state-model-core.md
2. **`event-integrity-agent.md`** - Enforcer of state-model-events.md
3. **`flow-runtime-agent.md`** - Guardian of state-model-flow.md
4. **`adversarial-reviewer-agent.md`** - System attacker and vulnerability detector
5. **`implementation-executor-agent.md`** - Specification implementer

---

## 🎯 USAGE

### **For GPT-4 / GPT-4 Turbo:**

Each `.md` file is a complete system prompt. Use it as the system message when creating an agent:

```python
import openai

# Load agent prompt
with open('agents/state-constitution-agent.md', 'r') as f:
    system_prompt = f.read()

# Create agent
response = openai.ChatCompletion.create(
    model="gpt-4-turbo",
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": request_json}
    ]
)
```

### **For Claude (Anthropic):**

Use the prompt as the system parameter:

```python
import anthropic

# Load agent prompt
with open('agents/event-integrity-agent.md', 'r') as f:
    system_prompt = f.read()

# Create agent
client = anthropic.Anthropic(api_key="...")
response = client.messages.create(
    model="claude-3-5-sonnet-20241022",
    system=system_prompt,
    messages=[{"role": "user", "content": request_json}]
)
```

---

## 🔄 AGENT EXECUTION ORDER

```text
New Requirement
    ↓
State Constitution Agent (validates state)
    ↓
Event Integrity Agent (validates events)
    ↓
Flow & Runtime Agent (validates flow)
    ↓
Adversarial Reviewer Agent (attacks proposal)
    ↓
Implementation Executor Agent (implements if approved)
    ↓
Production Code
```

**Each agent has veto power. Any rejection stops the pipeline.**

---

## 📋 QUICK REFERENCE

| Agent | Domain | Veto Power | Primary Check |
| ----- | ------ | ---------- | ------------- |
| State Constitution | state-model-core.md | ✅ Yes | Phantom state, invariants |
| Event Integrity | state-model-events.md | ✅ Yes | Payload completeness, idempotency |
| Flow & Runtime | state-model-flow.md | ✅ Yes | Unidirectional flow, side-channels |
| Adversarial Reviewer | All specs | ❌ No | Vulnerabilities, edge cases |
| Implementation Executor | All specs | ⚠️ Can refuse | Spec completeness, ambiguity |

---

## 🚀 DEPLOYMENT OPTIONS

### **Option 1: PR Gate (GitHub Actions)**

See `../.github/workflows/agent-validation.yml`

### **Option 2: Local Development (VS Code)**

See `../tools/local-agent-runner.js`

### **Option 3: CI/CD Pipeline**

See `../ci/agent-pipeline.yml`

---

## 📖 DOCUMENTATION

- **Architecture:** `../MULTI_AGENT_ARCHITECTURE.md`
- **Specifications:** `../state-model-*.md`
- **Validation:** `../SPECIFICATION_VALIDATION.md`

---

**All agent prompts ready for deployment.**
