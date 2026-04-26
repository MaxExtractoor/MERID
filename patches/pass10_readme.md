# Pass 10: Integration + UX/Ops Sweep

## What is Pass 10?

Pass 10 is the **consolidation and integration phase** that sits above all previous passes. Instead of discovering new code issues, it:

1. **Verifies** that Passes 1-9's architectural decisions are consistently enforced
2. **Audits** upstream (UI/UX, CLI) and downstream (logs, metrics, runbooks) surfaces
3. **Produces** a single, authoritative architecture + operations spec and GO/NO-GO matrix

## Why Pass 10 Matters

After 9 passes of deep auditing and patching, we need to ensure:
- The system is **coherent** - all parts work together correctly
- The system is **observable** - operators can tell when things go wrong
- The system is **operable** - humans can't accidentally break it via UX gaps
- The system is **ready** - clear criteria for SIM/PAPER/LIVE progression

## What's In The Spec

### 10.A - Architecture Consolidation
- **Execution topology table** - Map every entry point to the canonical executor
- **Risk model enforcement** - Verify 2% cap, 3-edge limit, fixed-USD ban
- **Guards inventory** - List all guards with test coverage and CI protection
- **CI gaps** - Identify what's missing from regression protection

### 10.B - UI/UX Upstream Sweep
- **Mode clarity audit** - How SIM/PAPER/LIVE are displayed across all interfaces
- **Risk settings audit** - Can users accidentally set unsafe configs?
- **Error feedback audit** - Are guard trips clear and actionable?

### 10.C - Downstream Observability & Ops
- **Logging audit** - Structured logs for all guards and failures
- **Metrics proposal** - Minimal set to detect regressions and issues
- **Runbook skeletons** - 5 runbooks for common failure modes

### 10.D - GO/NO-GO Matrix
- **Criteria** for SIM, PAPER, and LIVE progression
- **Checklists** for each mode transition
- **Risk assessment** of remaining gaps

## How to Use This Spec

1. **Hand to audit agent** as the Pass 10 system prompt
2. **Fill in the tables** by inspecting actual code, UI, and configs
3. **Mark items** as ✅ (verified), ⬜ (to do), or ⚠️ (gap found)
4. **Produce deliverables** at end of each section
5. **Make GO/NO-GO decision** based on 10.D matrix

## Key Files to Inspect

| Section | Key Files |
|---------|-----------|
| 10.A.1 | `web/api/kalshi_api.py`, `web/api/kalshi_continuous_trader_api.py` |
| 10.A.2 | `merid/config/unified_risk_enforcement.py`, `web/main.py` |
| 10.A.3 | `archive/__init__.py`, `web/api/kalshi_api.py` |
| 10.A.4 | `scripts/ci/check_kalshi_invariants.py` |
| 10.B | Web UI code, CLI tools, config UIs |
| 10.C | Log configurations, monitoring setup |

## Expected Outcomes

After Pass 10 completes, you should have:

1. ✅ **Complete architecture map** showing all guards and enforcement points
2. ✅ **UI/UX audit report** with specific recommendations for Pass 11
3. ✅ **Observability spec** with metrics, alerts, and runbooks
4. ✅ **GO/NO-GO decision** for SIM, PAPER, and LIVE modes

## Relationship to Pass 11

Pass 10 produces the **specification** for remaining work. Pass 11 is the **implementation** phase for:
- Any UX fixes identified in 10.B
- Any observability gaps identified in 10.C
- Any CI invariants identified in 10.A.4
- Any architecture gaps that aren't blockers but should be addressed

## Quick Start

Run this audit command to start filling the tables:

```bash
# Architecture topology
grep -r "KalshiRestClient\|KalshiFIXClient" web/api/ --include="*.py" | grep -v "test"

# Guards verification
grep -A5 "PASS 8 P0\|PASS8_GUARD" web/api/kalshi_api.py

# Risk enforcement
grep -r "enforce_at_startup\|enforce_unified_risk_model" merid/ web/ --include="*.py"

# UI/UX surfaces (to be filled after inspection)
# - Check web dashboards for mode display
# - Check CLI tools for risk settings
```

---

**Status:** Ready for audit agent execution  
**Prerequisites:** Pass 9 tests passing (17/17)  
**Next:** Pass 11 implementation of identified gaps
