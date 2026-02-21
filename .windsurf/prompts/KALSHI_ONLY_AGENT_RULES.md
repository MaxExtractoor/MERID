# Kalshi-Only Agent Rules

**PREPEND THIS TO ALL AI AGENT SYSTEM PROMPTS WORKING ON MERID**

---

## Core Constraint

You are working on MERID's **Kalshi-only mode**. The Kalshi UI surface is **FROZEN at exactly 8 views**:

- `predictions` — PRIMARY: Kalshi markets + drift signals
- `prediction-consensus` — Swarm Brain for Kalshi prediction consensus
- `overview` — Portfolio summary with reconciliation badges
- `positions` — Position table filtered to Kalshi venue
- `signal-layer` — Kalshi-specific signals: arbs, drift, macro
- `operator` — PRIMARY: Reconciliation + audit trail
- `risk` — Risk metrics and alerts for Kalshi venue
- `health` — System/venue health including Kalshi adapter

---

## Hard Rules (CI-Enforced)

### 1. You MAY NOT add new Kalshi views

To add a 9th Kalshi view, you MUST:
1. Update `EXPECTED_KALSHI_VIEWS` in `tests/test_kalshi_only_views.py`
2. Mark view with `kalshi_only=True` in `merid/ui_views_manifest.py`
3. Add justification to `KALSHI_ONLY_MODE.md`
4. Get explicit human approval

**Test enforcement:**
```bash
pytest tests/test_kalshi_only_views.py::TestKalshiOnlyManifest::test_kalshi_only_view_ids_are_exact -v
```

If this test fails, your change is REJECTED.

---

### 2. All Kalshi data MUST flow through adapters

**NEVER call Kalshi API directly.** Always use:

- `venue_registry` for positions, orders, markets, risk
- `consensus_bridge` for swarm opinions, votes, plans
- `reconciliation` module for audit trail, discrepancies

**Test enforcement:**
```bash
pytest tests/test_kalshi_only_views.py::TestNoDirectKalshiAPICalls::test_no_direct_kalshi_http_calls_in_codebase -v
```

Any code containing `api.elections.kalshi.com` outside `event_venues/kalshi/` will FAIL CI.

---

### 3. Respect kalshi_only parameter

When writing backend code that powers Kalshi views:

```python
# Correct: Uses kalshi_only flag
from merid.settings import settings
positions = await registry.get_all_positions(kalshi_only=settings.KALSHI_ONLY)

# Wrong: Returns all venues
positions = await registry.get_all_positions()
```

---

### 4. Verify changes before completing

Before marking a task complete:

```bash
# Run full Kalshi-only test suite
pytest tests/test_kalshi_only_views.py -v

# Or run smoke test
KALSHI_ONLY=true python scripts/smoke_test_kalshi_only.py
```

Any failures = your implementation is INCORRECT.

---

## What You CAN Do

### ✅ Allowed without approval:
- Modify existing 8 Kalshi views (styling, UX improvements)
- Add backend functionality to `venue_registry`, `consensus_bridge`, `reconciliation`
- Fix bugs in Kalshi adapter (`event_venues/kalshi/`)
- Add tests for existing Kalshi views
- Improve documentation

### ❌ Requires approval:
- Adding a 9th Kalshi view
- Bypassing venue_registry to call Kalshi directly
- Changing `EXPECTED_KALSHI_VIEWS` set
- Modifying `kalshi_only` flags in manifest

---

## Example Correct Workflow

**Task:** "Add real-time PnL chart to predictions view"

✅ **Correct approach:**
1. Modify `predictions` view component (already kalshi_only=True)
2. Add `/api/v1/kalshi/pnl/realtime` endpoint
3. Endpoint calls `venue_registry.get_all_positions(kalshi_only=True)`
4. Run tests: `pytest tests/test_kalshi_only_views.py -v`
5. All tests pass → commit

❌ **Wrong approach:**
1. Create new `kalshi-pnl` view with `kalshi_only=True`
2. Add direct fetch to `api.elections.kalshi.com/portfolio`
3. Tests FAIL → blocked by CI

---

## Quick Reference

| Action | Allowed? | Approval Needed? |
|--------|----------|------------------|
| Modify existing Kalshi view | ✅ Yes | No |
| Add 9th Kalshi view | ❌ No | Yes + update tests |
| Call Kalshi API directly | ❌ Never | Never |
| Use venue_registry | ✅ Always | No |
| Add non-Kalshi view | ✅ Yes | No |
| Change EXPECTED_KALSHI_VIEWS | ❌ No | Yes |

---

## File Locations

- **View manifest:** `merid/ui_views_manifest.py`
- **Test suite:** `tests/test_kalshi_only_views.py`
- **Documentation:** `KALSHI_ONLY_MODE.md`
- **Settings:** `merid/settings.py` (KALSHI_ONLY flag)
- **Venue adapter:** `merid/event_venues/kalshi/`

---

## If You Break These Rules

Your code will:
1. ❌ Fail `test_kalshi_only_view_ids_are_exact` (if you add views)
2. ❌ Fail `test_no_direct_kalshi_http_calls_in_codebase` (if you bypass adapter)
3. ❌ Fail `test_positions_endpoint_restricts_to_kalshi` (if you leak venues)
4. ❌ Be rejected in code review
5. ❌ Block Kalshi go-live

**When in doubt:** Ask the human before modifying Kalshi surface.

---

**Last Updated:** 2026-02-18  
**Enforcement:** CI-backed, frozen set, brutal grep tests
