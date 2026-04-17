# MERID REALITY ENFORCEMENT - IMPLEMENTATION GUIDE

## CONSTITUTIONAL MANDATE

**The UI is performing MERID instead of reflecting MERID.**

This document provides the binding implementation plan to eliminate all fake surfaces and force MERID to only display what it can prove.

---

## WHAT WAS IMPLEMENTED

### 1. Reality Registry (`core/reality_registry.py`)

**The single source of truth for what MERID knows.**

- `RealityAssertion` - Bounded claims with automatic decay
- `AssertionAlgebra` - Truth composition rules (AND/OR operations)
- `AssertionDomain` - Market, Onchain, Execution, Governance, Treasury, Simulation, Agent, System
- `AssertionStatus` - Valid, Degraded, Conflicted, Expired, Invalid
- Constitutional rules enforced:
  - Assertions decay automatically
  - Conflicts preserved, never auto-resolved
  - No deletion, only invalidation
  - Effective confidence = raw × provenance × time_decay × regime_factor

### 2. Reality Auditor (`core/reality_auditor.py`)

**The enforcement engine that prevents UI from lying.**

- `audit_ui_component()` - Gate for UI rendering
- `audit_execution_intent()` - Stricter gate for execution
- `audit_loop()` - Continuous assertion status updates
- `check_blindness_condition()` - Detects when system should enter Blindness Mode
- `detect_self_deception()` - Anti-self-deception metrics

### 3. Assertion Algebra Unit Tests (`tests/test_assertion_algebra.py`)

**NON-NEGOTIABLE tests that enforce truth discipline.**

- ✅ Assertion decays over time
- ✅ Provenance suppression (low provenance blocks high confidence)
- ✅ Weakest truth dominates AND
- ✅ Conflict contamination
- ✅ OR never enables execution
- ✅ No averaging across domains
- ✅ Missing assertion blocks execution
- ✅ Regime entropy suppresses assertions
- ✅ **Monotonicity invariant** - Adding uncertainty never increases eligibility

### 4. TruthGate UI Middleware (`web/static/ts/truthgate.ts`)

**UI firewall that independently verifies truth eligibility.**

- `TruthGate.evaluate()` - Component render gate
- `TruthGate.checkExecutionEligibility()` - Execution gate
- `TruthGateState` - RENDER, LOCK, BLIND, SUPPRESSED
- `detectForbiddenAggregations()` - Scans for banned keys
- `TruthBoundComponentManager` - Component registration and state management

### 5. Reality API (`web/api/reality.py`)

**Truth-bound endpoints for UI and external systems.**

- `GET /api/v1/reality/status` - Overall reality status
- `POST /api/v1/reality/assertions/register` - Register new assertion
- `GET /api/v1/reality/assertions/{id}` - Get assertion details
- `GET /api/v1/reality/assertions/domain/{domain}` - Get assertions by domain
- `POST /api/v1/reality/assertions/conflict` - Mark conflict
- `POST /api/v1/reality/audit/component` - Audit UI component
- `POST /api/v1/reality/audit/execution` - Audit execution intent
- `POST /api/v1/reality/regime/entropy` - Update regime entropy
- `GET /api/v1/reality/blindness` - Check blindness condition

### 6. CI Reality Enforcement (`.github/workflows/reality_enforcement.yml`)

**Automated checks that block deceptive PRs.**

- ❌ Forbidden UI keys (overallConfidence, systemHealthScore, etc.)
- ❌ UI components without TruthGate binding
- ❌ Empty provenance in backend
- ❌ Assertion algebra test failures
- ❌ Execution without shadow paths
- ❌ UI stimulation patterns (progress bars for analysis)
- ⚠️  Mock data in production code

---

## WHAT MUST HAPPEN NEXT

### STAGE 1: FAKE SURFACE PURGE (IMMEDIATE)

**Delete these files/patterns NOW:**

#### Category A: Fake Confidence Aggregators
```bash
# Find and remove
grep -r "overallConfidence\|systemHealthScore\|confidenceIndex" web/static/js/ -l
grep -r "globalScore\|healthScore\|signalStrength" core/ trading/ -l
```

**Action:** Remove any code computing global scores or health indicators.

#### Category B: UI-Only State
```bash
# Find and remove
grep -r "safeToTrade\|executionReady\|inferredRisk" web/static/js/ -l
```

**Action:** UI must never infer execution readiness. Only display what backend proves.

#### Category C: Optimistic Aggregators
```bash
# Find and remove files that:
# - Average signals across domains
# - Normalize disagreements
# - Compress multi-dimensional truth into scalars
```

#### Category D: Placeholder Engines
```bash
# Already removed most of these, but verify:
grep -r "mock_.*=\|fake_.*=\|random\." core/ trading/ --include="*.py" | grep -v test
```

#### Category E: Soft-Gated Actions
```bash
# Find disabled buttons without TruthGate
grep -r "disabled.*button\|button.*disabled" web/templates/ -l
```

**Action:** Replace with TruthGate enforcement, not tooltips.

---

### STAGE 2: COMPONENT → ENGINE BINDING (CRITICAL)

**Every UI component must declare its truth requirements.**

#### Binding Manifest Template

```typescript
// Example: Regime Badge Component
globalTruthGate.register({
  componentId: "regime-badge",
  requiredAssertions: [
    "market-regime-classification",
    "regime-confidence-score",
  ],
  minConfidence: 0.6,
  allowConflict: false,
  allowExpired: false,
});
```

#### Components That MUST Be Bound

1. **Market Overview Panel**
   - Price displays → `market-price-assertion`
   - Trend indicators → `regime-state-assertion`
   - Volatility → `volatility-estimate-assertion`

2. **Execution Panels**
   - Execution buttons → `execution-intent-assertion` + `slippage-estimate-assertion`
   - Order forms → `market-liquidity-assertion`

3. **Strategy/Alpha Panels**
   - Signal displays → `strategy-proposal-assertion`
   - Expected returns → `simulated-outcome-assertion`

4. **Treasury/PnL Panels**
   - Realized PnL → `settled-pnl-assertion`
   - Unrealized PnL → `mark-to-market-assertion`

5. **Agent Panels**
   - Agent accuracy → `agent-ledger-assertion`
   - Influence weights → `influence-score-assertion`

---

### STAGE 3: BLINDNESS MODE UI (REQUIRED)

**When truth collapses, UI must reflect it honestly.**

#### Entry Conditions
- >40% assertions expired
- Core domain (MARKET, EXECUTION, TREASURY) has zero valid assertions
- Regime entropy > 0.7
- Conflicts exceed resolution threshold

#### What Happens in Blindness Mode

**Most panels disappear. Only these remain:**

1. **Reality Failure Panel** (NEW - MUST CREATE)
```html
<div id="reality-failure-panel" class="blindness-panel">
  <h2>⚠️ REALITY UNSTABLE</h2>
  <div class="failure-reason"></div>
  <div class="failed-assertions"></div>
  <div class="last-known-safe-state"></div>
</div>
```

2. **What We Don't Know Panel** (NEW - MUST CREATE)
```html
<div id="unknown-panel" class="blindness-panel">
  <h3>Current Blind Spots</h3>
  <ul id="blind-spots-list"></ul>
</div>
```

3. **Recovery Checklist** (NEW - MUST CREATE)
```html
<div id="recovery-checklist" class="blindness-panel">
  <h3>Recovery Requirements</h3>
  <ul>
    <li>✓ Market data feed restored</li>
    <li>✗ Regime classification stable</li>
    <li>✗ Execution path verified</li>
  </ul>
</div>
```

#### CSS for Blindness Mode
```css
.blindness-mode {
  background: #1a0000;
  color: #ff6b6b;
}

.blindness-panel {
  border: 2px solid #ff0000;
  padding: 20px;
  margin: 20px;
  background: rgba(255, 0, 0, 0.1);
}

.blindness-mode .chart,
.blindness-mode .execution-panel,
.blindness-mode .recommendation {
  display: none !important;
}
```

---

### STAGE 4: INTEGRATE WITH EXISTING SYSTEMS

#### A. Connect to Regime Classifier

```python
# In monitoring/regime_classifier.py
from core.reality_auditor import get_reality_auditor

def classify_regime(self, ...):
    # ... existing logic ...
    
    # Update reality auditor
    auditor = get_reality_auditor()
    auditor.update_regime_entropy(self.regime_entropy)
    
    # Register assertion
    from core.reality_registry import get_reality_registry, AssertionDomain, AssertionProvenance
    registry = get_reality_registry()
    
    registry.register_assertion(
        domain=AssertionDomain.MARKET,
        description=f"Market regime classified as {regime}",
        confidence=confidence,
        provenance_score=0.8,
        regime_compatibility=1.0,
        decay_rate=0.05,
        validity_window=300,  # 5 minutes
        sources=[AssertionProvenance(
            source_id="regime-classifier",
            module_id="monitoring.regime_classifier",
            evidence_hash=hash(str(data)),
            weight=1.0,
            timestamp=time.time(),
        )],
    )
```

#### B. Connect to Execution Agent

```python
# In trading/agents/execution_agent.py
from core.reality_auditor import get_reality_auditor

async def execute_order(self, order: Order):
    auditor = get_reality_auditor()
    
    # Audit execution intent
    result = auditor.audit_execution_intent(
        intent_id=order.order_id,
        required_assertions=[
            "market-price-assertion",
            "execution-path-assertion",
            "slippage-estimate-assertion",
        ],
        symbol=order.symbol,
        amount_usd=order.size * order.price,
    )
    
    if not result.passed:
        logger.warning(f"Execution blocked: {result.reason}")
        order.status = OrderStatus.REJECTED
        order.rejection_reason = result.reason
        return
    
    # Proceed with execution...
```

#### C. Connect to Trading Mode Controller

```python
# In trading/mode_controller.py
from core.reality_auditor import get_reality_auditor

def can_execute_live(self, symbol: str, amount_usd: float) -> Tuple[bool, str]:
    # Existing mode checks...
    
    # Add reality check
    auditor = get_reality_auditor()
    system_state = auditor.get_system_state()
    
    if system_state["is_blind"]:
        return False, f"BLINDNESS MODE: {system_state['blind_reason']}"
    
    if not system_state["execution_allowed"]:
        return False, "Reality unstable - execution blocked"
    
    # Continue with existing logic...
```

---

### STAGE 5: UI INTEGRATION

#### A. Reality Status Panel (Add to Dashboard)

```html
<!-- Add to web/templates/unified.html -->
<div class="reality-status-panel">
  <h3>Reality Status</h3>
  <div id="reality-mode" class="mode-badge">OPERATIONAL</div>
  <div class="reality-metrics">
    <div class="metric">
      <span class="label">Valid Assertions</span>
      <span id="valid-pct" class="value">--</span>
    </div>
    <div class="metric">
      <span class="label">Regime Entropy</span>
      <span id="regime-entropy" class="value">--</span>
    </div>
    <div class="metric">
      <span class="label">Active Conflicts</span>
      <span id="active-conflicts" class="value">--</span>
    </div>
    <div class="metric">
      <span class="label">Blind Spots</span>
      <span id="blind-spots-count" class="value">--</span>
    </div>
  </div>
  <div id="blind-spots-list"></div>
</div>
```

#### B. JavaScript Integration

```javascript
// Add to web/static/js/unified-dashboard.js

async function updateRealityStatus() {
  try {
    const response = await fetch('/api/v1/reality/status');
    const data = await response.json();
    
    const state = data.system_state;
    
    // Update mode badge
    const modeBadge = document.getElementById('reality-mode');
    modeBadge.textContent = state.mode;
    modeBadge.className = `mode-badge mode-${state.mode.toLowerCase()}`;
    
    // Update metrics
    document.getElementById('valid-pct').textContent = 
      `${state.registry_status.valid_pct.toFixed(1)}%`;
    document.getElementById('regime-entropy').textContent = 
      state.regime_entropy.toFixed(3);
    document.getElementById('active-conflicts').textContent = 
      state.registry_status.active_conflicts;
    document.getElementById('blind-spots-count').textContent = 
      state.registry_status.blind_spots.length;
    
    // Handle blindness mode
    if (state.is_blind) {
      enterBlindnessMode(state.blind_reason);
    } else {
      exitBlindnessMode();
    }
    
    // Check self-deception metrics
    const deception = data.deception_metrics;
    if (deception.warning) {
      console.warn('Self-deception warning:', deception);
    }
    
  } catch (error) {
    console.error('Error updating reality status:', error);
  }
}

function enterBlindnessMode(reason) {
  document.body.classList.add('blindness-mode');
  
  // Show failure panel
  const failurePanel = document.getElementById('reality-failure-panel');
  if (failurePanel) {
    failurePanel.style.display = 'block';
    failurePanel.querySelector('.failure-reason').textContent = reason;
  }
  
  // Hide most UI
  document.querySelectorAll('.chart, .execution-panel, .recommendation').forEach(el => {
    el.style.display = 'none';
  });
}

function exitBlindnessMode() {
  document.body.classList.remove('blindness-mode');
  
  const failurePanel = document.getElementById('reality-failure-panel');
  if (failurePanel) {
    failurePanel.style.display = 'none';
  }
  
  // Restore UI (but still gated by TruthGate)
  document.querySelectorAll('.chart, .execution-panel, .recommendation').forEach(el => {
    el.style.display = '';
  });
}

// Poll reality status
setInterval(updateRealityStatus, 5000);
updateRealityStatus();
```

---

## FORBIDDEN OPERATIONS (PERMANENT BAN)

### 1. Averaging Confidence Across Domains
```python
# ❌ FORBIDDEN
overall_confidence = (market_conf + social_conf + onchain_conf) / 3

# ✅ CORRECT
# Display each domain separately with its own confidence
```

### 2. Normalizing Uncertainty Away
```python
# ❌ FORBIDDEN
normalized_score = (raw_score - min_score) / (max_score - min_score)

# ✅ CORRECT
# Show raw uncertainty, don't hide it
```

### 3. Collapsing Conflicts into Consensus
```python
# ❌ FORBIDDEN
if agent_a.prediction != agent_b.prediction:
    consensus = (agent_a.prediction + agent_b.prediction) / 2

# ✅ CORRECT
# Show conflict explicitly, never resolve silently
```

### 4. Promoting Low-Confidence Agreement Over High-Confidence Dissent
```python
# ❌ FORBIDDEN
if agreement_count > dissent_count:
    use_consensus()

# ✅ CORRECT
# Weight by confidence × provenance, not vote count
```

---

## TESTING CHECKLIST

Before deploying:

- [ ] Run `pytest tests/test_assertion_algebra.py -v`
- [ ] All assertion algebra tests pass
- [ ] CI reality enforcement checks pass
- [ ] No forbidden keys in codebase
- [ ] All UI components registered with TruthGate
- [ ] Blindness Mode triggers correctly
- [ ] Reality Status Panel displays accurate data
- [ ] Execution blocked when assertions invalid
- [ ] Regime entropy updates propagate
- [ ] Self-deception metrics calculated

---

## OPERATOR TRAINING

**Operators must be trained to trust empty screens.**

### Drill 1: Silent Failure
- UI removes 60% of panels
- **Correct response:** Do nothing
- **Incorrect response:** Try to "fix" it

### Drill 2: Conflicting Truth
- Two regimes shown simultaneously
- **Correct response:** Reduce exposure
- **Incorrect response:** Pick one and ignore the other

### Drill 3: Blindness Trigger
- System enters Blindness Mode
- **Correct response:** Protect capital, not alpha
- **Incorrect response:** Override and continue trading

---

## FINAL TRUTH

**If MERID appears quiet, slow, or restrictive — it is working correctly.**

Any system that keeps operating while blind is unfit for capital.

**Blindness Mode is success, not failure.**

---

## NEXT STEPS

1. **Run tests:** `pytest tests/test_assertion_algebra.py -v`
2. **Purge fake surfaces:** Remove forbidden patterns
3. **Bind components:** Register all UI components with TruthGate
4. **Create Blindness UI:** Build failure panels
5. **Integrate systems:** Connect regime classifier, execution agent, trading mode
6. **Deploy CI rules:** Enable GitHub Actions workflow
7. **Train operators:** Run drills

**MERID will stop pretending and start becoming undeniable.**
