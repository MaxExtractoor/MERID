# Incident Timeline Example: Manual Order Bypasses Risk Check
## Date: 2026-03-23 16:45 UTC
## Severity: MEDIUM
## ID: INC-2026-0323-003

---

## Summary
A manual order entered by an authorized operator bypassed the Kelly sizing risk check due to a UI flag default. The order executed at 3x the calculated safe size, though still within absolute position limits.

## Detection
- **16:42:00 UTC** — Manual order `ord_manual_045` submitted via operator dashboard
- **16:44:30 UTC** — Position size alert triggered (position > 2x Kelly recommendation)
- **16:45:00 UTC** — `incident_replay.py` shows `manual_or_external=true` with incomplete lineage

## Investigation

```bash
python scripts/incident_replay.py ord_manual_045 \
    --start-time 2026-03-23T16:40:00Z \
    --end-time 2026-03-23T16:50:00Z \
    --format runbook
```

### Output Summary

**Severity:** MEDIUM  
**Data Source:** MANUAL (operator: alice@merid.io)  
**Lineage:** INCOMPLETE (missing risk controller step)  
**Kelly Size:** 150 contracts (calculated)  
**Actual Size:** 500 contracts (manual entry)

## Timeline

| Time | Event | Data Source | Risk Check |
|------|-------|-------------|------------|
| 16:40:00 | Operator opens trade ticket | MANUAL | — |
| 16:41:30 | Size entered: 500 contracts | MANUAL | — |
| 16:41:35 | "Bypass sizing" checkbox ticked | MANUAL | **BYPASSED** |
| 16:42:00 | Order submitted | MANUAL | Skipped |
| 16:42:01 | Kalshi accepts order | LIVE | — |
| 16:42:15 | Fill: 500/500 @ 62¢ | LIVE | — |
| 16:44:30 | Position alert: size > 2x Kelly | LIVE | **Post-hoc** |

## Root Cause

**UI/UX Issue:** The "Bypass Kelly Sizing" checkbox was:
1. Visible to all operators (not just risk-admins)
2. Default unchecked but **persisted** last selection
3. No confirmation modal for >2x Kelly sizes

```typescript
// Bug in KalshiTradeTicket.tsx
const [bypassSizing, setBypassSizing] = useState(
  localStorage.getItem("bypassSizing") === "true"  // Persisted!
);
```

## Resolution Steps

1. ✅ **Immediate (16:46 UTC):** Position sized correctly via hedge order
2. ✅ **Fix (17:00 UTC):** Removed persistence of "bypass sizing" flag
3. ✅ **Fix (17:15 UTC):** Added confirmation modal for >2x Kelly
4. ✅ **Fix (17:30 UTC):** Restricted bypass to `risk_admin` role only

## DataSource Badge Behavior

**Before Fix:**
- Badge showed `MANUAL` but no indication of bypass
- Risk controller step missing from lineage (expected for manual)
- Kelly recommendation not visible in UI at time of entry

**After Fix:**
- Badge shows `MANUAL` + `OVERRIDE` if sizing bypassed
- Lineage includes `manual_bypass` node with reason
- Kelly recommendation displayed as "Recommended: 150, Entered: 500"

## Manual Order Invariant (Property Test)

Added to `test_hypothesis_invariants.py`:

```python
@given(
    st.booleans(),  # is_manual
    st.booleans(),  # bypass_kelly
    st.integers(min_value=1, max_value=1000),  # size
    st.integers(min_value=1, max_value=500),   # kelly_size
)
def test_manual_orders_show_bypass_flag(is_manual, bypass_kelly, size, kelly_size):
    """Manual orders that bypass sizing must show override badge."""
    if is_manual and bypass_kelly and size > kelly_size * 2:
        # API response must include override metadata
        response = api_submit_order(
            size=size,
            bypass_kelly=bypass_kelly,
            is_manual=is_manual,
        )
        assert response["badge"] == "MANUAL"
        assert response["metadata"]["kelly_bypass"] is True
        assert response["metadata"]["kelly_recommended"] == kelly_size
```

## Prevention

1. **UI:** "Bypass sizing" requires `risk_admin` role
2. **UI:** Checkbox never persists, defaults to false
3. **UI:** Confirmation modal for >2x Kelly sizes
4. **API:** Manual orders always log Kelly recommendation even if bypassed
5. **Alert:** Position size >2x Kelly triggers immediate notification

## Replay Command

```bash
python scripts/incident_replay.py ord_manual_045 \
    --start-time 2026-03-23T16:40:00Z \
    --end-time 2026-03-23T16:50:00Z \
    --format markdown
```

## Artifacts

- **Order:** `/api/v1/kalshi/orders/ord_manual_045/lineage`
- **Kelly Calculation:** `/api/v1/kalshi/sizing-metrics?ticker=KXBTC`
- **Audit Log:** `/api/v1/audit/operator-actions?user=alice@merid.io`

## Training Material

This incident is used in operator onboarding to demonstrate:

1. How to verify Kelly recommendation before bypass
2. When to escalate to risk team vs. execute
3. How `incident_replay.py` traces manual orders

**Training exercise:**
```bash
# New operators run this on example incident
python scripts/incident_replay.py ord_manual_045 --format runbook
# Then answer: What would you do differently?
```
