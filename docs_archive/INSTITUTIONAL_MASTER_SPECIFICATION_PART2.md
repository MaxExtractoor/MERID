# MERID INSTITUTIONAL MASTER SPECIFICATION - PART 2
## Sections 6-20: Frontend, Backend, and Operational Systems

---

# SECTION 6: FRONTEND TRUTH-ENFORCEMENT STATE MACHINE

## 6.1 State Definitions

```typescript
enum TruthGateState {
    RENDER = "RENDER",           // Truth sufficient, component renders
    LOCK = "LOCK",               // Truth degraded, component frozen
    BLIND = "BLIND",             // Truth insufficient, component hidden
    SUPPRESSED = "SUPPRESSED"    // Forbidden component, never renders
}

interface ComponentTruthRequirements {
    componentId: string;
    requiredDomains: AssertionDomain[];
    minConfidence: number;
    maxAge: number;  // seconds
    criticalityLevel: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
}
```

## 6.2 State Transition Logic

```typescript
class TruthGateStateMachine {
    /**
     * Determine component render state based on assertion health.
     * 
     * TRANSITION RULES:
     * 1. SUPPRESSED → Never transitions (permanent)
     * 2. BLIND → LOCK when partial truth available
     * 3. LOCK → RENDER when full truth restored
     * 4. RENDER → LOCK when truth degrades
     * 5. LOCK → BLIND when truth expires
     * 6. Any state → SUPPRESSED if component forbidden
     */
    
    determineState(
        component: ComponentTruthRequirements,
        assertions: Assertion[],
        systemMode: SystemMode
    ): TruthGateState {
        // Check suppression list first
        if (SUPPRESSED_COMPONENTS.includes(component.componentId)) {
            return TruthGateState.SUPPRESSED;
        }
        
        // System-wide blindness overrides component logic
        if (systemMode === SystemMode.BLIND) {
            return TruthGateState.BLIND;
        }
        
        // Filter assertions for required domains
        const relevantAssertions = assertions.filter(a => 
            component.requiredDomains.includes(a.domain) &&
            a.status === AssertionStatus.VALID
        );
        
        // No assertions = BLIND
        if (relevantAssertions.length === 0) {
            return TruthGateState.BLIND;
        }
        
        // Check confidence threshold
        const currentTime = Date.now() / 1000;
        const validAssertions = relevantAssertions.filter(a => {
            const decayedConf = calculateDecayedConfidence(a, currentTime);
            const age = currentTime - a.timestamp;
            return decayedConf >= component.minConfidence && 
                   age <= component.maxAge;
        });
        
        // Partial truth = LOCK
        if (validAssertions.length < component.requiredDomains.length) {
            return TruthGateState.LOCK;
        }
        
        // Full truth = RENDER
        return TruthGateState.RENDER;
    }
    
    /**
     * Apply state to component rendering.
     */
    applyState(
        element: HTMLElement,
        state: TruthGateState,
        reason: string
    ): void {
        element.dataset.truthGateState = state;
        element.dataset.truthGateReason = reason;
        
        switch (state) {
            case TruthGateState.RENDER:
                element.style.display = '';
                element.style.opacity = '1';
                element.style.pointerEvents = 'auto';
                break;
                
            case TruthGateState.LOCK:
                element.style.opacity = '0.5';
                element.style.pointerEvents = 'none';
                this.showLockOverlay(element, reason);
                break;
                
            case TruthGateState.BLIND:
                element.style.display = 'none';
                break;
                
            case TruthGateState.SUPPRESSED:
                element.remove();  // Permanently remove from DOM
                console.error(`Suppressed component attempted render: ${element.id}`);
                break;
        }
    }
}
```

## 6.3 Component Truth Requirements

```typescript
const COMPONENT_TRUTH_REQUIREMENTS: Record<string, ComponentTruthRequirements> = {
    // Trading components - CRITICAL
    "order-entry-form": {
        componentId: "order-entry-form",
        requiredDomains: [
            AssertionDomain.MARKET_DATA,
            AssertionDomain.EXECUTION,
            AssertionDomain.RISK
        ],
        minConfidence: 0.9,
        maxAge: 5,  // 5 seconds max
        criticalityLevel: "CRITICAL"
    },
    
    "position-display": {
        componentId: "position-display",
        requiredDomains: [
            AssertionDomain.EXECUTION,
            AssertionDomain.RISK
        ],
        minConfidence: 0.95,
        maxAge: 2,
        criticalityLevel: "CRITICAL"
    },
    
    // Agent components - HIGH
    "agent-vote-panel": {
        componentId: "agent-vote-panel",
        requiredDomains: [
            AssertionDomain.AGENT_STATE,
            AssertionDomain.CONSENSUS
        ],
        minConfidence: 0.8,
        maxAge: 10,
        criticalityLevel: "HIGH"
    },
    
    // Market data components - MEDIUM
    "price-chart": {
        componentId: "price-chart",
        requiredDomains: [
            AssertionDomain.MARKET_DATA
        ],
        minConfidence: 0.7,
        maxAge: 30,
        criticalityLevel: "MEDIUM"
    },
    
    // System status - LOW
    "system-health-indicator": {
        componentId: "system-health-indicator",
        requiredDomains: [
            AssertionDomain.SYSTEM
        ],
        minConfidence: 0.6,
        maxAge: 60,
        criticalityLevel: "LOW"
    }
};
```

---

# SECTION 7: BLINDNESS MODE UX SPECIFICATION

## 7.1 Blindness Mode Triggers

```typescript
interface BlindnessModeTrigger {
    triggerId: string;
    condition: () => boolean;
    severity: "HIGH" | "CRITICAL";
    message: string;
    recoverySteps: string[];
}

const BLINDNESS_TRIGGERS: BlindnessModeTrigger[] = [
    {
        triggerId: "NO_MARKET_DATA",
        condition: () => getValidAssertions(AssertionDomain.MARKET_DATA).length === 0,
        severity: "CRITICAL",
        message: "No valid market data assertions",
        recoverySteps: [
            "Verify exchange API connections",
            "Check WebSocket feeds",
            "Restart price feed service",
            "Validate API credentials"
        ]
    },
    {
        triggerId: "HIGH_EXPIRY_RATE",
        condition: () => calculateExpiryRate() > 0.4,
        severity: "CRITICAL",
        message: "Over 40% of assertions expired",
        recoverySteps: [
            "Check agent health status",
            "Verify data feed latency",
            "Review assertion TTL settings",
            "Restart stale agents"
        ]
    },
    {
        triggerId: "REGIME_ENTROPY_HIGH",
        condition: () => calculateRegimeEntropy() > 0.7 * Math.log2(8),
        severity: "HIGH",
        message: "Truth fragmented across domains",
        recoverySteps: [
            "Review assertion distribution",
            "Check for domain-specific failures",
            "Validate cross-domain consistency",
            "Rebalance agent focus"
        ]
    },
    {
        triggerId: "CRITICAL_DOMAIN_EMPTY",
        condition: () => {
            const critical = ["MARKET_DATA", "EXECUTION", "AGENT_STATE"];
            return critical.some(d => getValidAssertions(d).length === 0);
        },
        severity: "CRITICAL",
        message: "Critical domain has no assertions",
        recoverySteps: [
            "Identify empty critical domain",
            "Check responsible agents",
            "Verify data sources",
            "Manual assertion injection if needed"
        ]
    }
];
```

## 7.2 Blindness Mode UI

```typescript
class BlindnessModeUI {
    /**
     * Render full-screen blindness overlay.
     * 
     * REQUIREMENTS:
     * - Blocks all trading actions
     * - Shows active triggers
     * - Displays recovery checklist
     * - Provides manual override (with confirmation)
     * - Logs all operator actions
     */
    
    render(triggers: BlindnessModeTrigger[]): HTMLElement {
        const overlay = document.createElement('div');
        overlay.id = 'blindness-mode-overlay';
        overlay.className = 'blindness-overlay';
        
        overlay.innerHTML = `
            <div class="blindness-container">
                <div class="blindness-header">
                    <h1>⚠️ BLINDNESS MODE ACTIVE</h1>
                    <p class="blindness-subtitle">
                        System truth insufficient for safe operation
                    </p>
                </div>
                
                <div class="blindness-triggers">
                    <h2>Active Triggers</h2>
                    ${triggers.map(t => `
                        <div class="trigger-card severity-${t.severity}">
                            <h3>${t.triggerId}</h3>
                            <p>${t.message}</p>
                            <div class="recovery-steps">
                                <h4>Recovery Steps:</h4>
                                <ol>
                                    ${t.recoverySteps.map(step => 
                                        `<li>${step}</li>`
                                    ).join('')}
                                </ol>
                            </div>
                        </div>
                    `).join('')}
                </div>
                
                <div class="blindness-actions">
                    <button id="refresh-truth-btn" class="btn-primary">
                        Refresh Truth Status
                    </button>
                    <button id="manual-override-btn" class="btn-danger">
                        Manual Override (Dangerous)
                    </button>
                </div>
                
                <div class="blindness-footer">
                    <p>
                        Trading is disabled until truth is restored.
                        All positions remain open but no new orders accepted.
                    </p>
                </div>
            </div>
        `;
        
        // Attach event handlers
        this.attachHandlers(overlay);
        
        return overlay;
    }
    
    attachHandlers(overlay: HTMLElement): void {
        const refreshBtn = overlay.querySelector('#refresh-truth-btn');
        refreshBtn?.addEventListener('click', async () => {
            await this.refreshTruthStatus();
        });
        
        const overrideBtn = overlay.querySelector('#manual-override-btn');
        overrideBtn?.addEventListener('click', async () => {
            await this.handleManualOverride();
        });
    }
    
    async handleManualOverride(): Promise<void> {
        const confirmed = confirm(
            "WARNING: Manual override bypasses truth enforcement.\n\n" +
            "This should ONLY be used in emergencies.\n\n" +
            "All actions will be logged and audited.\n\n" +
            "Do you want to proceed?"
        );
        
        if (!confirmed) return;
        
        const reason = prompt("Enter reason for manual override:");
        if (!reason || reason.trim().length < 10) {
            alert("Override reason must be at least 10 characters.");
            return;
        }
        
        // Log override to audit trail
        await fetch('/api/v1/reality/override', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                operator: getCurrentOperator(),
                reason: reason,
                timestamp: Date.now(),
                triggers: getActiveBlindnessTriggers()
            })
        });
        
        // Exit blindness mode
        exitBlindnessMode();
    }
}
```

## 7.3 Partial Blindness (Lock Mode)

```typescript
/**
 * Lock mode for components with degraded but not absent truth.
 * 
 * BEHAVIOR:
 * - Component visible but grayed out
 * - No interaction allowed
 * - Shows specific truth deficiency
 * - Provides path to restoration
 */
class LockModeOverlay {
    show(
        element: HTMLElement,
        missingDomains: AssertionDomain[],
        degradedConfidence: number
    ): void {
        const overlay = document.createElement('div');
        overlay.className = 'lock-mode-overlay';
        
        overlay.innerHTML = `
            <div class="lock-content">
                <div class="lock-icon">🔒</div>
                <h3>Component Locked</h3>
                <p>Truth insufficient for interaction</p>
                
                ${missingDomains.length > 0 ? `
                    <div class="missing-domains">
                        <h4>Missing Domains:</h4>
                        <ul>
                            ${missingDomains.map(d => 
                                `<li>${d}</li>`
                            ).join('')}
                        </ul>
                    </div>
                ` : ''}
                
                ${degradedConfidence < 0.8 ? `
                    <div class="degraded-confidence">
                        <h4>Confidence Too Low:</h4>
                        <p>Current: ${(degradedConfidence * 100).toFixed(1)}%</p>
                        <p>Required: 80%+</p>
                    </div>
                ` : ''}
                
                <div class="lock-footer">
                    <small>Waiting for truth restoration...</small>
                </div>
            </div>
        `;
        
        element.appendChild(overlay);
    }
}
```

---

# SECTION 8: UI COMPONENT KILL-LIST

## 8.1 Forbidden Components (Delete Immediately)

```typescript
/**
 * Components that MUST be removed from codebase.
 * These violate truth enforcement or create deceptive UX.
 */
const FORBIDDEN_COMPONENTS = [
    // Fake progress indicators
    "analysis-progress-bar",
    "loading-spinner-with-percentage",
    "processing-animation",
    
    // Synthetic confidence displays
    "overall-confidence-meter",
    "system-health-score",
    "aggregated-sentiment-gauge",
    
    // Misleading charts
    "smooth-price-prediction-line",
    "confidence-interval-without-provenance",
    "projected-pnl-chart",
    
    // Opaque AI displays
    "black-box-recommendation",
    "unexplained-trade-signal",
    "mystery-score-indicator",
    
    // Dangerous automation
    "auto-execute-toggle",
    "set-and-forget-mode",
    "blind-follow-ai-button",
    
    // Hidden risk
    "simplified-risk-view",
    "hide-slippage-toggle",
    "suppress-warnings-checkbox"
];

/**
 * Forbidden CSS classes that hide uncertainty.
 */
const FORBIDDEN_CSS_CLASSES = [
    "hide-uncertainty",
    "smooth-transition-always",
    "suppress-error-state",
    "fake-loading",
    "confidence-booster"
];

/**
 * Forbidden data attributes.
 */
const FORBIDDEN_DATA_ATTRIBUTES = [
    "data-synthetic-confidence",
    "data-averaged-metric",
    "data-smoothed-value",
    "data-hide-on-error"
];
```

## 8.2 Replacement Components (Use These Instead)

```typescript
const APPROVED_COMPONENTS = {
    // Truth-bound progress
    "assertion-freshness-indicator": {
        shows: "Time since last assertion update",
        truthBound: true,
        neverFakes: true
    },
    
    "domain-health-panel": {
        shows: "Per-domain assertion counts and confidence",
        truthBound: true,
        neverAverages: true
    },
    
    // Explainable AI
    "agent-reasoning-panel": {
        shows: "Full decision reasoning with provenance",
        truthBound: true,
        requiresEvidence: true
    },
    
    "consensus-vote-breakdown": {
        shows: "Individual agent votes with trust weights",
        truthBound: true,
        showsDissent: true
    },
    
    // Honest risk display
    "full-risk-breakdown": {
        shows: "All risk metrics without simplification",
        truthBound: true,
        cannotHide: true
    },
    
    "slippage-estimate-range": {
        shows: "Min/max slippage with confidence intervals",
        truthBound: true,
        showsUncertainty: true
    }
};
```

## 8.3 Automated Enforcement

```typescript
/**
 * Pre-commit hook to block forbidden components.
 */
function validateComponentUsage(files: string[]): ValidationResult {
    const violations: string[] = [];
    
    for (const file of files) {
        const content = readFileSync(file, 'utf-8');
        
        // Check for forbidden component usage
        for (const forbidden of FORBIDDEN_COMPONENTS) {
            if (content.includes(forbidden)) {
                violations.push(
                    `${file}: Uses forbidden component '${forbidden}'`
                );
            }
        }
        
        // Check for forbidden CSS classes
        for (const forbiddenClass of FORBIDDEN_CSS_CLASSES) {
            if (content.includes(forbiddenClass)) {
                violations.push(
                    `${file}: Uses forbidden CSS class '${forbiddenClass}'`
                );
            }
        }
        
        // Check for forbidden data attributes
        for (const forbiddenAttr of FORBIDDEN_DATA_ATTRIBUTES) {
            if (content.includes(forbiddenAttr)) {
                violations.push(
                    `${file}: Uses forbidden data attribute '${forbiddenAttr}'`
                );
            }
        }
    }
    
    return {
        valid: violations.length === 0,
        violations: violations
    };
}
```

---

# SECTION 9: UI AUTO-ENFORCEMENT MIDDLEWARE

## 9.1 TruthGate Middleware

```typescript
/**
 * Middleware that intercepts all component renders.
 * Enforces truth requirements before allowing display.
 */
class TruthGateMiddleware {
    private stateMachine: TruthGateStateMachine;
    private assertionCache: AssertionCache;
    private auditLogger: AuditLogger;
    
    constructor() {
        this.stateMachine = new TruthGateStateMachine();
        this.assertionCache = new AssertionCache();
        this.auditLogger = new AuditLogger();
    }
    
    /**
     * Intercept component render.
     * 
     * ENFORCEMENT:
     * - Fetch current assertions
     * - Determine truth gate state
     * - Apply state to component
     * - Log decision to audit trail
     * - Return modified component or null
     */
    async interceptRender(
        component: React.Component,
        props: any
    ): Promise<React.Component | null> {
        const componentId = component.constructor.name;
        
        // Check if component requires truth gating
        const requirements = COMPONENT_TRUTH_REQUIREMENTS[componentId];
        if (!requirements) {
            // No requirements = always render
            return component;
        }
        
        // Fetch current assertions
        const assertions = await this.assertionCache.getAssertions(
            requirements.requiredDomains
        );
        
        // Determine state
        const systemMode = await this.getSystemMode();
        const state = this.stateMachine.determineState(
            requirements,
            assertions,
            systemMode
        );
        
        // Log decision
        await this.auditLogger.logRenderDecision({
            componentId: componentId,
            state: state,
            assertionCount: assertions.length,
            timestamp: Date.now()
        });
        
        // Apply state
        switch (state) {
            case TruthGateState.RENDER:
                return component;
                
            case TruthGateState.LOCK:
                return this.wrapWithLockOverlay(component, requirements);
                
            case TruthGateState.BLIND:
                return null;  // Don't render
                
            case TruthGateState.SUPPRESSED:
                console.error(`Suppressed component attempted render: ${componentId}`);
                return null;
        }
    }
    
    /**
     * Wrap component with lock overlay.
     */
    wrapWithLockOverlay(
        component: React.Component,
        requirements: ComponentTruthRequirements
    ): React.Component {
        return (
            <div className="truth-gate-locked">
                <div className="locked-component">
                    {component}
                </div>
                <LockModeOverlay 
                    requirements={requirements}
                    currentAssertions={this.assertionCache.getCached()}
                />
            </div>
        );
    }
}
```

## 9.2 Assertion Cache

```typescript
/**
 * Client-side assertion cache with automatic refresh.
 */
class AssertionCache {
    private cache: Map<string, Assertion[]>;
    private refreshInterval: number = 5000;  // 5 seconds
    private refreshTimer: NodeJS.Timeout | null = null;
    
    constructor() {
        this.cache = new Map();
        this.startAutoRefresh();
    }
    
    async getAssertions(
        domains: AssertionDomain[]
    ): Promise<Assertion[]> {
        const cacheKey = domains.sort().join(',');
        
        // Check cache first
        if (this.cache.has(cacheKey)) {
            const cached = this.cache.get(cacheKey)!;
            
            // Validate cache freshness
            if (this.isCacheFresh(cached)) {
                return cached;
            }
        }
        
        // Fetch from server
        const assertions = await this.fetchFromServer(domains);
        this.cache.set(cacheKey, assertions);
        
        return assertions;
    }
    
    private async fetchFromServer(
        domains: AssertionDomain[]
    ): Promise<Assertion[]> {
        const response = await fetch('/api/v1/reality/assertions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ domains: domains })
        });
        
        if (!response.ok) {
            throw new Error('Failed to fetch assertions');
        }
        
        return await response.json();
    }
    
    private startAutoRefresh(): void {
        this.refreshTimer = setInterval(async () => {
            // Refresh all cached domains
            for (const [key, _] of this.cache.entries()) {
                const domains = key.split(',') as AssertionDomain[];
                const fresh = await this.fetchFromServer(domains);
                this.cache.set(key, fresh);
            }
        }, this.refreshInterval);
    }
    
    private isCacheFresh(assertions: Assertion[]): boolean {
        const now = Date.now() / 1000;
        const maxAge = 10;  // 10 seconds max cache age
        
        return assertions.every(a => 
            (now - a.timestamp) < maxAge
        );
    }
}
```

---

# SECTION 10: REALITY AUDITOR & REPLAY TOOLING

## 10.1 Reality Auditor Architecture

```python
class RealityAuditor:
    """
    Comprehensive audit system for all truth assertions and decisions.
    
    REQUIREMENTS:
    - Immutable audit log
    - Cryptographic signatures
    - Full replay capability
    - Tamper detection
    - Regulatory compliance
    """
    
    def __init__(self, storage_backend: AuditStorage):
        self.storage = storage_backend
        self.signer = CryptographicSigner()
        self.replay_engine = ReplayEngine()
    
    def audit_assertion_creation(
        self,
        assertion: Assertion,
        context: Dict[str, Any]
    ) -> AuditEntry:
        """
        Audit new assertion creation.
        
        LOGGED DATA:
        - Full assertion details
        - Creation context (agent, trigger, evidence)
        - System state snapshot
        - Cryptographic signature
        """
        entry = AuditEntry(
            entry_id=str(uuid.uuid4()),
            timestamp=time.time(),
            event_type=AuditEventType.ASSERTION_CREATED,
            assertion_id=assertion.assertion_id,
            data={
                "assertion": asdict(assertion),
                "context": context,
                "system_state": self._capture_system_state()
            }
        )
        
        # Sign entry
        entry.signature = self.signer.sign(entry.to_bytes())
        
        # Store immutably
        self.storage.append(entry)
        
        return entry
    
    def audit_decision(
        self,
        decision_type: str,
        decision_data: Dict[str, Any],
        supporting_assertions: List[str]
    ) -> AuditEntry:
        """
        Audit AI/consensus decision.
        
        LOGGED DATA:
        - Decision type and outcome
        - All supporting assertions
        - Agent votes and reasoning
        - Confidence calculations
        - Timestamp and operator
        """
        entry = AuditEntry(
            entry_id=str(uuid.uuid4()),
            timestamp=time.time(),
            event_type=AuditEventType.DECISION_MADE,
            data={
                "decision_type": decision_type,
                "decision_data": decision_data,
                "supporting_assertions": supporting_assertions,
                "assertion_snapshots": [
                    self._get_assertion_snapshot(aid)
                    for aid in supporting_assertions
                ]
            }
        )
        
        entry.signature = self.signer.sign(entry.to_bytes())
        self.storage.append(entry)
        
        return entry
    
    def audit_execution(
        self,
        order: Order,
        execution_result: ExecutionResult
    ) -> AuditEntry:
        """
        Audit trade execution.
        
        LOGGED DATA:
        - Order details
        - Execution result
        - Slippage
        - Fees
        - Market conditions at execution
        """
        entry = AuditEntry(
            entry_id=str(uuid.uuid4()),
            timestamp=time.time(),
            event_type=AuditEventType.EXECUTION,
            data={
                "order": asdict(order),
                "result": asdict(execution_result),
                "market_snapshot": self._capture_market_state()
            }
        )
        
        entry.signature = self.signer.sign(entry.to_bytes())
        self.storage.append(entry)
        
        return entry
    
    def verify_audit_trail(
        self,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None
    ) -> AuditVerificationResult:
        """
        Verify integrity of audit trail.
        
        CHECKS:
        - Signature validity
        - Temporal ordering
        - No gaps or duplicates
        - Cross-reference consistency
        """
        entries = self.storage.query(start_time, end_time)
        
        violations = []
        
        for i, entry in enumerate(entries):
            # Verify signature
            if not self.signer.verify(entry.to_bytes(), entry.signature):
                violations.append(f"Invalid signature: {entry.entry_id}")
            
            # Verify temporal ordering
            if i > 0 and entry.timestamp < entries[i-1].timestamp:
                violations.append(f"Temporal violation: {entry.entry_id}")
            
            # Verify cross-references
            if not self._verify_cross_references(entry):
                violations.append(f"Invalid cross-reference: {entry.entry_id}")
        
        return AuditVerificationResult(
            valid=len(violations) == 0,
            entries_checked=len(entries),
            violations=violations
        )
```

## 10.2 Replay Engine

```python
class ReplayEngine:
    """
    Replay historical decisions with current or historical assertions.
    
    USE CASES:
    - Debugging decision logic
    - Validating model changes
    - Regulatory compliance
    - Post-mortem analysis
    """
    
    def replay_decision(
        self,
        decision_audit_entry: AuditEntry,
        use_current_logic: bool = False
    ) -> ReplayResult:
        """
        Replay a historical decision.
        
        MODES:
        - Historical: Use exact logic and assertions from decision time
        - Current: Use current logic with historical assertions
        """
        # Extract decision data
        decision_data = decision_audit_entry.data
        assertion_snapshots = decision_data["assertion_snapshots"]
        
        # Reconstruct assertion state
        historical_assertions = [
            Assertion(**snapshot)
            for snapshot in assertion_snapshots
        ]
        
        # Replay decision logic
        if use_current_logic:
            # Use current decision engine
            replayed_decision = self._run_current_logic(
                decision_data["decision_type"],
                historical_assertions
            )
        else:
            # Use historical decision engine
            replayed_decision = self._run_historical_logic(
                decision_data,
                historical_assertions
            )
        
        # Compare results
        original_outcome = decision_data["decision_data"]["outcome"]
        replayed_outcome = replayed_decision["outcome"]
        
        return ReplayResult(
            original_decision=decision_audit_entry,
            replayed_decision=replayed_decision,
            outcomes_match=original_outcome == replayed_outcome,
            differences=self._compute_differences(
                decision_data,
                replayed_decision
            )
        )
    
    def replay_trading_day(
        self,
        date: datetime.date,
        use_current_logic: bool = False
    ) -> List[ReplayResult]:
        """
        Replay all decisions from a trading day.
        """
        # Get all decision audit entries for day
        start_time = datetime.datetime.combine(
            date, datetime.time.min
        ).timestamp()
        end_time = datetime.datetime.combine(
            date, datetime.time.max
        ).timestamp()
        
        entries = self.storage.query(
            start_time=start_time,
            end_time=end_time,
            event_type=AuditEventType.DECISION_MADE
        )
        
        # Replay each decision
        results = []
        for entry in entries:
            result = self.replay_decision(entry, use_current_logic)
            results.append(result)
        
        return results
```

---

*[SPECIFICATION CONTINUES WITH SECTIONS 11-20]*

**Document size limit reached. Continuing in next file...**
