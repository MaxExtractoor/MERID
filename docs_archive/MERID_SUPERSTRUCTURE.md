# MERID SUPERSTRUCTURE v1.0

**Document Status:** CANONICAL  
**Created:** 2026-01-11  
**Authority:** Constitutional  
**Checksum:** [COMPUTED ON FREEZE]

---

## Preamble

MERID is not a trading bot. It is a **sovereign financial intelligence organism** composed of five federated subsystems with strict authority boundaries and controlled interfaces.

This document defines the **separation of powers** that makes MERID durable, defensible, and evolvable.

---

## The Five Sovereign Systems

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           MERID SUPERSTRUCTURE                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                 │
│  │  MERID-OPS  │───▶│  MERID-GOV  │◀───│ MERID-FIN   │                 │
│  │ Intelligence│    │ Governance  │    │  Execution  │                 │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘                 │
│         │                  │                  │                         │
│         │                  ▼                  │                         │
│         │           ┌─────────────┐           │                         │
│         └──────────▶│MERID-ARCHIVE│◀──────────┘                         │
│                     │   Memory    │                                     │
│                     └──────┬──────┘                                     │
│                            │                                            │
│                            ▼                                            │
│                     ┌─────────────┐                                     │
│                     │MERID-TREASURY                                     │
│                     │   Capital   │                                     │
│                     └─────────────┘                                     │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## SYSTEM I: MERID-OPS (Operations & Intelligence Fabric)

### Mission

> "What is happening in the world *right now*?"

### Authority

- **CAN:** Observe, model, synthesize, warn, simulate
- **CANNOT:** Trade, move capital, override governance, modify its own rules

### Components

| Component | Purpose | Status |
|-----------|---------|--------|
| Market Streams | Real-time price data | ✅ |
| News Sentinel | RSS/API news ingestion | ✅ |
| Sentiment Analyzer | NLP sentiment scoring | ✅ |
| Prediction Markets | Polymarket/Kalshi aggregation | ✅ |
| Arbitrage Scanners | Opportunity detection | ✅ |
| Memecoin Detector | Token launch analysis | ✅ |
| Cost Models | Gas/slippage/latency estimation | ✅ |
| Time Exploit Analyzer | Oracle/resolution timing | ✅ |
| Simulation Mining | PoUS block production | ✅ |
| Alert Generator | Signal emission | ✅ |
| **Data Provenance Scorer** | Source trust decay | 🔲 |
| **Signal Entropy Tracker** | Overfitting detection | 🔲 |
| **Cross-Domain Conflict Detector** | Disagreement analysis | 🔲 |
| **Unknown Unknowns Detector** | Volatility without narrative | 🔲 |

### Invariants

1. OPS **never** initiates trades
2. OPS **never** moves capital
3. OPS outputs are **advisory only**
4. All OPS signals must include confidence intervals
5. OPS must flag when it has **no signal** (silence is information)

### Interfaces

```
OPS → GOV: Signals, alerts, risk assessments
OPS → ARCHIVE: All observations, predictions, outcomes
OPS ← ARCHIVE: Historical data for backtesting
```

---

## SYSTEM II: MERID-GOV (Governance, Oversight & Law)

### Mission

> "Should this system be allowed to do what it's trying to do?"

### Authority

- **CAN:** Approve, reject, freeze, quarantine, override, audit
- **CANNOT:** Execute trades directly, access private keys, modify ARCHIVE

### Components

| Component | Purpose | Status |
|-----------|---------|--------|
| Consensus Engine | Trust-weighted voting | ✅ |
| Risk Agent | Position/exposure limits | ✅ |
| Skeptic Agent | Challenge proposals | ✅ |
| Meta-Audit Agent | Compliance verification | ✅ |
| Compliance Engine | Regulatory rules | ✅ |
| Agent Quarantine | Isolate misbehaving agents | ✅ |
| Capital Freeze | Emergency halt | ✅ |
| Shadow Mode | Parallel non-execution | ✅ |
| Disaster Recovery | Failover orchestration | ✅ |
| Schema Contracts | Immutable data formats | ✅ |
| Plugin Sandbox | Isolated execution | ✅ |
| **Constitutional Invariants** | Unoverridable rules | 🔲 |
| **Human Veto Registry** | Logged overrides with decay | 🔲 |
| **Self-Audit Cycles** | Periodic assumption challenges | 🔲 |
| **Authority Boundary Enforcer** | System isolation | 🔲 |
| **Time-Based Authority Decay** | Permission expiration | 🔲 |

### Constitutional Invariants (UNOVERRIDABLE)

These rules **cannot** be bypassed even by unanimous consensus:

```python
CONSTITUTIONAL_INVARIANTS = {
    "MAX_SINGLE_POSITION_PCT": 10.0,      # Never >10% in one position
    "MAX_CORRELATED_EXPOSURE_PCT": 25.0,  # Never >25% in correlated assets
    "MIN_TREASURY_RESERVE_PCT": 20.0,     # Always keep 20% in safe assets
    "MAX_DAILY_DRAWDOWN_PCT": 5.0,        # Hard stop at 5% daily loss
    "MAX_LEVERAGE": 3.0,                  # Never exceed 3x leverage
    "REQUIRE_HUMAN_ABOVE_USD": 100000,    # Human approval >$100k
    "COLD_WALLET_MIN_PCT": 50.0,          # 50% always in cold storage
    "NO_PRINCIPAL_TRADING": True,         # Only trade with profits
}
```

### Interfaces

```
GOV ← OPS: Signals, risk assessments
GOV → FIN: Approvals, rejections, limits
GOV → TREASURY: Allocation permissions
GOV → ARCHIVE: All decisions, rationale
GOV ← ARCHIVE: Historical decisions for learning
GOV ← HUMAN: Vetos, invariant updates, escalation resolution
```

---

## SYSTEM III: MERID-FIN (Trading & Execution)

### Mission

> "Given permission — execute precisely and safely."

### Authority

- **CAN:** Execute approved trades, manage positions, report status
- **CANNOT:** Approve its own trades, access treasury directly, modify risk limits

### Design Philosophy

**FIN must be dumb, fast, and obedient — not smart.**

### Components

| Component | Purpose | Status |
|-----------|---------|--------|
| Execution Engine | Order submission | ✅ (paper) |
| Risk Preview | Pre-trade validation | ✅ |
| Wallet Manager | Key access (hot only) | ✅ |
| Position Tracker | Current holdings | ✅ |
| Manual Approval Flow | Human-in-loop | ✅ |
| Position Limits | Per-asset caps | ✅ |
| Emergency Unwind | Rapid exit | ✅ |
| **Real P&L Truth Engine** | Exchange reconciliation | 🔲 |
| **Kill-Switch Latency Guarantees** | ms-bound shutdown | 🔲 |
| **Cross-Exchange Position Netting** | Unified view | 🔲 |
| **Adversarial Exchange Detection** | Manipulation detection | 🔲 |
| **Slippage Breach Auto-Abort** | Execution protection | 🔲 |

### Execution Rules

1. FIN **only** executes with valid GOV approval token
2. Approval tokens **expire** (default: 60 seconds)
3. FIN **aborts** if slippage exceeds preview by >50%
4. FIN **reports** every execution to ARCHIVE immediately
5. FIN **cannot** access cold or warm wallets
6. FIN profits **drip-feed** to TREASURY, never direct access

### Interfaces

```
FIN ← GOV: Approval tokens, limits, permissions
FIN → ARCHIVE: Execution logs, P&L, errors
FIN → TREASURY: Profit transfers (one-way, rate-limited)
FIN ← TREASURY: Capital allocation (via GOV only)
```

---

## SYSTEM IV: MERID-TREASURY (Capital Preservation)

### Mission

> "How does MERID survive without trading?"

### Authority

- **CAN:** Deploy to yield sources, rebalance, withdraw from DeFi
- **CANNOT:** Trade speculatively, access FIN directly, override drawdown limits

### Design Philosophy

**TREASURY is the organism's survival mechanism. It must be conservative, diversified, and paranoid.**

### Components

| Component | Purpose | Status |
|-----------|---------|--------|
| Yield Source Registry | Protocol catalog | ✅ |
| Strategy Competition | Agent-based allocation | ✅ |
| Monte Carlo Simulation | Risk modeling | ✅ |
| Drawdown Governor | Loss limits | ✅ |
| Auto-Rebalancer | Drift correction | ✅ |
| Emergency Unwind Manager | DeFi exit | ✅ |
| **Strategy Half-Life Tracker** | Alpha decay detection | 🔲 |
| **Protocol Risk Correlation Graph** | Diversification validation | 🔲 |
| **Chain Risk Diversification** | Multi-chain exposure | 🔲 |
| **Treasury Firewall** | FIN isolation | 🔲 |
| **Principal Protection Rule** | Never trade principal | 🔲 |

### Capital Tiers

```
TIER 1 - UNTOUCHABLE (50%)
├── Cold wallet
├── Hardware wallet
└── Never deployed to DeFi

TIER 2 - YIELD (30%)
├── Tier-1 safe protocols only (Aave, Maker DSR)
├── Max 10% per protocol
└── Instant withdrawal capability

TIER 3 - GROWTH (15%)
├── Tier-2/3 protocols (Lido, EigenLayer)
├── Max 5% per protocol
└── May have withdrawal delays

TIER 4 - EXPERIMENTAL (5%)
├── Tier-4 high-risk (Ethena, Pendle)
├── Max 2% per protocol
└── Only from realized profits
```

### Interfaces

```
TREASURY ← GOV: Allocation permissions, rebalance approvals
TREASURY ← FIN: Profit deposits (one-way)
TREASURY → ARCHIVE: All movements, yields, losses
TREASURY → GOV: Status, risk metrics
```

---

## SYSTEM V: MERID-ARCHIVE (Memory & Truth)

### Mission

> "What actually happened, and what did we learn?"

### Authority

- **CAN:** Record, query, analyze, report
- **CANNOT:** Modify history, delete records, influence decisions directly

### Design Philosophy

**ARCHIVE is the organism's memory. Without it, MERID cannot evolve safely.**

### Components

| Component | Purpose | Status |
|-----------|---------|--------|
| Audit Trail | Immutable decision log | ✅ |
| Hash Chain | Integrity verification | ✅ |
| Archivist Agent | Decision logging | ✅ |
| **Outcome-Based Agent Scoring** | Performance tracking | 🔲 |
| **Strategy Autopsy Reports** | Post-mortem analysis | 🔲 |
| **"Why We Lost Money" Narratives** | Loss attribution | 🔲 |
| **Replayable Historical Simulations** | Counterfactual testing | 🔲 |
| **Model Accuracy Decay Tracking** | Prediction degradation | 🔲 |

### Retention Rules

```
RETENTION_POLICY = {
    "decisions": "7_years",        # Regulatory requirement
    "trades": "7_years",           # Regulatory requirement
    "agent_outputs": "2_years",    # Learning window
    "market_data": "1_year",       # Storage optimization
    "simulations": "90_days",      # Recent relevance
    "logs": "30_days",             # Operational
}
```

### Interfaces

```
ARCHIVE ← ALL: Logs, decisions, outcomes
ARCHIVE → OPS: Historical data for backtesting
ARCHIVE → GOV: Decision history for audits
ARCHIVE → HUMAN: Reports, forensics, compliance
```

---

## Capital Flow Rules

### The One-Way Valve Principle

Money flows in **one direction only** through controlled gates:

```
                    ┌─────────────────────────────────────┐
                    │           EXTERNAL MARKETS          │
                    └──────────────────┬──────────────────┘
                                       │
                                       ▼
                    ┌──────────────────────────────────────┐
                    │              MERID-FIN               │
                    │         (Trading Execution)          │
                    └──────────────────┬───────────────────┘
                                       │
                              [PROFITS ONLY]
                              [RATE LIMITED]
                              [GOV APPROVED]
                                       │
                                       ▼
                    ┌──────────────────────────────────────┐
                    │           MERID-TREASURY             │
                    │        (Capital Preservation)        │
                    └──────────────────┬───────────────────┘
                                       │
                              [YIELD ONLY]
                              [AUTO-COMPOUND]
                                       │
                                       ▼
                    ┌──────────────────────────────────────┐
                    │           MERID-TREASURY             │
                    │          (Same, compounding)         │
                    └──────────────────────────────────────┘
                                       │
                              [GOV APPROVAL REQUIRED]
                              [HUMAN APPROVAL >$100K]
                                       │
                                       ▼
                    ┌──────────────────────────────────────┐
                    │              MERID-FIN               │
                    │       (New capital allocation)       │
                    └──────────────────────────────────────┘
```

### Forbidden Flows

```
❌ FIN → TREASURY (direct, without GOV)
❌ TREASURY → FIN (direct, without GOV)
❌ OPS → FIN (signals cannot trigger trades)
❌ FIN → FIN (circular trades)
❌ TREASURY → EXTERNAL (without GOV + HUMAN)
```

---

## Time-Based Authority

### Permission Decay

All permissions and approvals **decay over time**:

```python
AUTHORITY_DECAY = {
    "trade_approval": "60_seconds",      # Must execute quickly
    "strategy_approval": "24_hours",     # Daily revalidation
    "yield_allocation": "7_days",        # Weekly review
    "risk_limit_override": "1_hour",     # Short-lived exceptions
    "human_veto": "30_days",             # Requires re-confirmation
    "agent_trust_score": "decay_0.1%_daily",  # Continuous erosion
}
```

### Zombie Logic Prevention

- Strategies **auto-disable** after 30 days without review
- Models **lose trust weight** if not validated against outcomes
- Approvals **expire** and must be re-requested
- Old code paths **flag warnings** after 90 days unused

---

## Human-as-God-Mode

### Human Role

Humans are **not operators**. Humans are:

1. **Invariant Setters** — Define constitutional rules
2. **Escalation Resolvers** — Break deadlocks
3. **Veto Holders** — Override in emergencies
4. **Auditors** — Review ARCHIVE periodically

### Human Interaction Points

```
HUMAN → GOV: Set invariants, approve escalations
HUMAN → GOV: Veto decisions (logged, time-limited)
HUMAN ← ARCHIVE: Receive reports, forensics
HUMAN ← GOV: Escalation requests
```

### What Humans Do NOT Do

```
❌ Micro-manage trades
❌ Override risk limits casually
❌ Access private keys directly
❌ Modify ARCHIVE
❌ Bypass GOV for FIN access
```

---

## Shadow Reality (Always On)

Every live decision is **also**:

1. **Simulated** — What would happen in Monte Carlo?
2. **Counterfactual-tested** — What if we didn't act?
3. **Logged** — Full decision tree preserved

This creates **anti-fragility**:

```
LIVE_DECISION
    ├── ACTUAL_OUTCOME
    ├── SIMULATED_OUTCOME (1000 runs)
    ├── COUNTERFACTUAL_OUTCOME (no action)
    └── DELTA_ANALYSIS
```

---

## System-to-System API Contracts

### OPS → GOV

```python
class OpsSignal:
    signal_id: str
    signal_type: Literal["opportunity", "risk", "alert", "info"]
    source_system: str
    confidence: float  # 0.0 - 1.0
    urgency: Literal["immediate", "soon", "background"]
    data: Dict[str, Any]
    expires_at: float  # Unix timestamp
    provenance: List[str]  # Data source chain
```

### GOV → FIN

```python
class ExecutionApproval:
    approval_id: str
    intent_hash: str  # Must match submitted intent
    approved_by: List[str]  # Agent IDs
    consensus_score: float
    risk_preview_hash: str
    max_slippage_pct: float
    expires_at: float  # Usually 60 seconds
    conditions: List[str]  # Must all be true at execution
```

### FIN → TREASURY

```python
class ProfitTransfer:
    transfer_id: str
    source: str  # FIN wallet
    amount_usd: float
    asset: str
    realized_from: str  # Trade ID
    gov_approval_id: str
    timestamp: float
```

### ALL → ARCHIVE

```python
class ArchiveEntry:
    entry_id: str
    source_system: Literal["OPS", "GOV", "FIN", "TREASURY"]
    entry_type: str
    data: Dict[str, Any]
    timestamp: float
    hash: str  # SHA-256 of data
    prev_hash: str  # Chain link
```

---

## Implementation Checklist

### Phase A: Formalization (Current)

- [x] Document superstructure
- [ ] Implement constitutional invariants
- [ ] Implement authority boundary enforcement
- [ ] Implement time-based authority decay

### Phase B: Missing OPS Components

- [ ] Data provenance scoring
- [ ] Signal entropy tracking
- [ ] Cross-domain conflict detection
- [ ] Unknown unknowns detection

### Phase C: Missing GOV Components

- [ ] Human veto registry
- [ ] Self-audit cycles
- [ ] Authority boundary enforcer

### Phase D: Missing FIN Components

- [ ] Real P&L truth engine
- [ ] Kill-switch latency guarantees
- [ ] Slippage breach auto-abort

### Phase E: Missing TREASURY Components

- [ ] Strategy half-life tracking
- [ ] Protocol risk correlation graph
- [ ] Treasury firewall
- [ ] Principal protection rule

### Phase F: Missing ARCHIVE Components

- [ ] Outcome-based agent scoring
- [ ] Strategy autopsy reports
- [ ] Replayable historical simulations

---

## Appendix: Why This Matters

### Without Separation of Powers

```
MONOLITHIC SYSTEM
    └── One bug can drain everything
    └── One bad decision cascades
    └── No audit trail of authority
    └── Cannot reason about safety
    └── Cannot evolve safely
```

### With Separation of Powers

```
FEDERATED SYSTEMS
    └── OPS failure = no trades (safe)
    └── GOV failure = freeze everything (safe)
    └── FIN failure = no execution (safe)
    └── TREASURY failure = capital preserved (safe)
    └── ARCHIVE failure = no learning (recoverable)
```

**The goal is not to prevent all failures. The goal is to ensure no single failure is catastrophic.**

---

## Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-11 | MERID | Initial superstructure definition |

**This document is CANONICAL. Changes require GOV consensus + HUMAN approval.**
