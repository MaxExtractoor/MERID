# 🔒 MERID REALITY ENFORCEMENT MASTER DIRECTIVE

## CONSTITUTIONAL MANDATE - NON-NEGOTIABLE

---

## THE PROBLEM

You are building **MERID**, a sovereign institutional financial operating system.

**MERID must never represent capability it does not possess.**

Right now, the system suffers from **terminal cosplay**:

- Panels exist without live backing engines
- Indicators render without authoritative data contracts
- "Status" is declarative instead of computed
- UX is lying by omission

**This is a critical institutional sin.**

---

## ABSOLUTE RULE

> **No UI component may render unless it is backed by a live, audited, heartbeat-producing engine registered in the MERID Reality Registry.**

---

## YOU MUST

### 1. Delete All Placeholder UI

- Remove mock data generators
- Remove static status indicators
- Remove hardcoded "healthy" states
- Remove fake progress bars
- Remove confidence aggregations

### 2. Enforce Render-Time Verification

Every UI component must:

- Query the Reality Registry
- Verify assertion validity
- Check effective confidence
- Respect decay and expiration
- Display failure states honestly

### 3. Implement Truth-Bound States

UI components exist in exactly one state:

| State | Meaning |
| ----- | ------- |
| **RENDER** | Engine running, assertions valid, confidence sufficient |
| **LOCK** | Visible but non-interactive, confidence degraded |
| **BLIND** | Content removed, placeholder only, truth collapsed |
| **SUPPRESSED** | Component not mounted, engine not live |

**UNAVAILABLE IS A SUCCESS STATE.**

---

## UI STATES ARE NOT COSMETIC

Every component must truthfully display:

- **LIVE** - Engine running, contract valid
- **DEGRADED** - Engine running, confidence reduced
- **LOCKED** - Governance restriction
- **STALE** - Engine not updated within SLA
- **UNAVAILABLE** - Engine not implemented

If it's **UNAVAILABLE**, it must look uncomfortable.

---

## FAILURE IS VISIBLE

MERID does not hide incompleteness.
It exposes it with authority.

When truth collapses, the system enters **BLINDNESS MODE**:

- Most panels disappear
- No charts, no projections, no recommendations
- Only Reality Failure Panel remains
- Shows what we don't know
- Shows recovery requirements

**Blindness Mode is success, not failure.**

---

## BUILD ORDER

### Phase 1: Reality Registry

- Implement assertion ledger
- Define assertion domains
- Implement decay mathematics
- Register all truth sources

### Phase 2: Render Gate

- Build TruthGate middleware
- Enforce component registration
- Block rendering without assertions
- Implement state transitions

### Phase 3: Component–Engine Binding Map

- Map every UI element to sovereign engine
- Define required assertions per component
- Specify failure behaviors
- Remove unmapped components

### Phase 4: Fake Surface Purge

- Delete placeholder panels
- Remove demo data
- Remove static indicators
- Replace with "ENGINE NOT LIVE" states

### Phase 5: System-by-System Activation

Bring systems online one at a time:

1. OPS (regime, anomaly, trust)
2. GOV (permissions, decay, veto)
3. SIM (shadow reality)
4. FIN (execution envelopes)
5. TREASURY (capital topology)
6. ARCHIVE (memory)

Each system lights up its UI only when ready.

### Phase 6: Continuous Reality Enforcement

- Reality Auditor scans UI tree
- Verifies every component has live engine
- Auto-disables violations
- Logs incidents
- Notifies governance

---

## FORBIDDEN OPERATIONS

### ❌ NEVER DO THESE

1. **Average confidence across domains**
   - Truth is multi-dimensional
   - Domains cannot be collapsed

2. **Normalize uncertainty away**
   - Uncertainty is information
   - Do not hide it

3. **Resolve conflicts silently**
   - Conflicts must be visible
   - Disagreement is valuable

4. **Promote low-confidence agreement over high-confidence dissent**
   - Weight by confidence × provenance
   - Not by vote count

5. **Show "overall system health"**
   - Health is not scalar
   - Show domain-specific states

6. **Display progress bars for analysis**
   - Understanding does not "complete"
   - Truth does not load

7. **Auto-refresh dashboards without timestamps**
   - Time continuity matters
   - Snapshots lie

8. **Persistent charts during blindness**
   - If assertions invalid, charts must disappear
   - No exceptions

---

## CONSTITUTIONAL TESTS

These tests are **NON-NEGOTIABLE**. If any fail, the build is invalid:

✅ Assertion decays over time
✅ Provenance suppresses weak confidence
✅ Weakest truth dominates AND
✅ Conflict contaminates results
✅ OR never enables execution
✅ No averaging across domains
✅ Missing assertion blocks execution
✅ Regime entropy suppresses assertions
✅ **Monotonicity: Adding uncertainty never increases eligibility**

---

## IF A FEATURE IS NOT REAL

- It must not look real
- It must not behave real
- It must not inspire trust

**MERID's credibility comes from restraint, not appearance.**

---

## WHAT THIS MEANS IN PRACTICE

### Before Reality Enforcement

```javascript
// ❌ WRONG
const confidence = (marketConf + socialConf + onchainConf) / 3;
if (confidence > 0.7) {
  showExecuteButton();
}
```

### After Reality Enforcement

```typescript
// ✅ CORRECT
const decision = truthGate.checkExecutionEligibility(
  intentId,
  ['market-price-assertion', 'execution-path-assertion'],
  assertions
);

if (decision.state === 'RENDER') {
  showExecuteButton();
} else {
  showBlockedState(decision.reason);
}
```

---

## OPERATOR TRAINING

Operators must learn to:

- **Trust empty screens** - Absence of data is honest
- **Respect missing data** - Don't fill gaps with assumptions
- **Pause when panels disappear** - System is protecting you
- **Fear confidence, not uncertainty** - Overconfidence kills capital

### Correct Responses

#### Drill 1: Silent Failure

- UI removes 60% of panels
- ✅ Do nothing, wait for recovery
- ❌ Try to "fix" or override

#### Drill 2: Conflicting Truth

- Two regimes shown simultaneously
- ✅ Reduce exposure, increase caution
- ❌ Pick one and ignore conflict

#### Drill 3: Blindness Trigger

- System enters Blindness Mode
- ✅ Protect capital, not alpha
- ❌ Override and continue trading

---

## REALITY ENFORCEMENT CHECKLIST

Before any PR is merged:

- [ ] Reality Registry operational keys in code
- [ ] All UI components registered with TruthGate
- [ ] Assertion algebra tests pass
- [ ] No empty provenance in backend
- [ ] Execution paths have shadow comparison
- [ ] No UI stimulation patterns (flashing, pulsing)
- [ ] Blindness Mode triggers correctly
- [ ] Reality Status Panel displays accurate data
- [ ] Self-deception metrics calculated

---

## THE FINAL TRUTH

> **A system that feels confident while uncertain is dangerous.**
> 
> **A system that feels uncomfortable while honest is alive.**

At this point, MERID is no longer a product.
It is a **truth-governed organism**.

---

## IMPLEMENTATION STATUS

### ✅ COMPLETED

1. **Reality Registry** (`core/reality_registry.py`)
   - Assertion ledger with automatic decay
   - Domain classification
   - Conflict detection and preservation
   - Constitutional rules enforced

2. **Reality Auditor** (`core/reality_auditor.py`)
   - UI component audit gate
   - Execution intent audit gate
   - Blindness condition detection
   - Self-deception metrics

3. **Assertion Algebra** (`core/reality_registry.py`)
   - AND/OR operations with correct semantics
   - Execution eligibility checking
   - Monotonicity guarantees

4. **Unit Tests** (`tests/test_assertion_algebra.py`)
   - 9 constitutional tests
   - All passing
   - Regression guards active

5. **TruthGate Middleware** (`web/static/ts/truthgate.ts`)
   - Component render gate
   - Execution eligibility gate
   - Forbidden key detection
   - State management

6. **Reality API** (`web/api/reality.py`)
   - 10 endpoints for truth management
   - Assertion registration
   - Conflict marking
   - Audit endpoints

7. **CI Enforcement** (`.github/workflows/reality_enforcement.yml`)
   - Forbidden key detection
   - Component binding verification
   - Provenance checking
   - Test execution
   - Mock data detection

8. **Documentation**
   - Implementation guide
   - Integration instructions
   - Operator training materials

---

## NEXT ACTIONS

### Immediate (Do This Now)

1. **Purge Fake Surfaces**
   ```bash
   # Find and remove forbidden patterns
   grep -r "overallConfidence\|systemHealthScore" web/static/js/ -l
   ```

2. **Bind Components**
   - Register all UI components with TruthGate
   - Define required assertions
   - Specify failure behaviors

3. **Create Blindness UI**
   - Reality Failure Panel
   - What We Don't Know Panel
   - Recovery Checklist

4. **Integrate Systems**
   - Connect regime classifier to reality auditor
   - Connect execution agent to assertion checks
   - Connect trading mode to reality gates

### Short Term (This Week)

5. **Deploy CI Rules**
   - Enable GitHub Actions workflow
   - Fix any violations found

6. **Train Operators**
   - Run drills
   - Document correct responses
   - Build muscle memory for restraint

7. **Monitor Reality Status**
   - Add Reality Status Panel to dashboard
   - Poll `/api/v1/reality/status` every 5 seconds
   - Display blindness warnings

### Ongoing (Always)

8. **Maintain Truth Discipline**
   - Review all PRs for violations
   - Run assertion algebra tests on every commit
   - Never compromise on truth requirements

---

## SUCCESS CRITERIA

MERID is correctly implemented when:

- ✅ UI feels sparse and uncomfortable
- ✅ Empty screens are common
- ✅ Operators trust missing data
- ✅ Blindness Mode triggers appropriately
- ✅ No fake confidence displays
- ✅ Conflicts visible, never hidden
- ✅ Execution blocked when truth insufficient
- ✅ All tests passing
- ✅ CI enforcing reality discipline

**If MERID appears quiet, slow, or restrictive — it is working correctly.**

---

## CONTACT & SUPPORT

For questions about reality enforcement:
1. Review `REALITY_ENFORCEMENT_IMPLEMENTATION.md`
2. Check assertion algebra tests
3. Inspect Reality API responses
4. Monitor self-deception metrics

**Remember: MERID does not show information. It exposes accountability.**

---

**Build accordingly.**

🔒 **END OF DIRECTIVE** 🔒
