# MERID MASTER SPECIFICATION v1.0

**Version:** 1.0.0  
**Frozen:** 2026-01-11  
**Checksum:** SHA-256 computed at bottom of document  
**Status:** LOCKED - Amendments require MASTER_SPEC_CHANGELOG.md entry

---

## 1. SYSTEM ARCHITECTURE

### 1.1 Core Philosophy
MERID is a sovereign, autonomous trading intelligence system designed for:
- **Zero external dependency** for critical decisions
- **Consensus-driven execution** with multi-agent validation
- **Full auditability** with immutable decision trails
- **Graceful degradation** under partial failure

### 1.2 Four Pillars
1. **Streaming Intelligence Engine** - Real-time data ingestion and signal generation
2. **Autonomous Agent Mesh** - Specialized agents with trust-weighted voting
3. **Consensus Protocol** - Byzantine-fault-tolerant decision making
4. **Execution Layer** - Safe, auditable trade execution

---

## 2. CANONICAL SCHEMAS (Phase 14)

All data structures MUST validate against these schemas:

| Schema | Purpose | Checksum (SHA-256) |
|--------|---------|-------------------|
| IntentEnvelope | Atomic unit of agent decision | `79d4a972c149dfb0...` |
| ConsensusBlock | Immutable consensus record | `54fff0826119b5f1...` |
| SimulationReport | Proof-of-Useful-Simulation | `2cb8dda914943bfb...` |
| RiskPreview | Pre-execution risk assessment | `a298612b7ce08b74...` |
| ExecutionResult | Trade execution record | `bdc15b3aa626dccd...` |
| ArbitrageOpportunity | Detected market inefficiency | `1865a9b1182ec668...` |

**Schema Manifest Hash:** `df30bacb16485a77341bb0a314d2062d6b02fb1d0c3f80f1d75733543b3e15f8`

---

## 3. AGENT ROLES

### 3.1 Official Agent Charters
- **Sentinel** - Market monitoring and anomaly detection
- **Strategist** - Trade strategy formulation
- **Executor** - Order execution and fill optimization
- **Auditor** - Compliance and audit trail maintenance
- **Guardian** - Risk management and position limits
- **Oracle** - External data validation and cross-referencing

### 3.2 Trust Scoring
- Initial trust: 0.5
- Range: [0.0, 1.0]
- Decay rate: 0.01 per bad decision
- Recovery rate: 0.005 per good decision
- Quarantine threshold: < 0.3

---

## 4. CONSENSUS PROTOCOL

### 4.1 Voting Rules
- **Quorum:** 67% of active agent weight
- **Approval threshold:** 67% weighted approval
- **Timeout:** 30 seconds default
- **Tie-breaker:** Guardian agent

### 4.2 Block Structure
- Sequential block numbers
- SHA-256 hash chain
- Merkle root of votes
- Immutable once finalized

---

## 5. RISK MANAGEMENT

### 5.1 Position Limits
- Max single position: 10% of equity
- Max sector exposure: 30% of equity
- Max leverage: 3x
- Max daily loss: 5% of equity

### 5.2 Drawdown Governance (Treasury)
- Caution: 3%
- Warning: 5%
- Critical: 8%
- Emergency: 12%

### 5.3 Capital Freeze Triggers
- Drawdown exceeds emergency threshold
- Anomaly detection (critical severity)
- Manual override
- Exchange connectivity loss > 5 minutes

---

## 6. EXECUTION MODES

### 6.1 Trading Modes
- **SHADOW** - Paper trading, no real execution
- **PRIMARY** - Live execution enabled
- **ALERT_ONLY** - Signals only, no execution

### 6.2 Mode Transitions
- Shadow → Primary: Requires governance approval
- Primary → Shadow: Automatic on anomaly
- Any → Frozen: Automatic on capital freeze

---

## 7. API STRUCTURE

### 7.1 Registered Routers (31 total)
1. root_router
2. router (/api)
3. router_v1 (/api/v1)
4. reflection_router
5. mining_router
6. auth_router
7. referrals_router
8. trading_router
9. betting_router
10. streams_router
11. paper_trading_router
12. system_control_router
13. data_endpoints_router
14. live_stream_router
15. institutional_router
16. schemas_router
17. arbitrage_router
18. prediction_router
19. wallet_router
20. offline_router
21. notifications_router
22. compliance_router
23. plugins_router
24. monitoring_router
25. ratelimit_router
26. backup_router
27. cost_models_router
28. time_exploit_router
29. sniping_router
30. recovery_router
31. treasury_router

---

## 8. DATA FLOWS

### 8.1 Intelligence Pipeline
```
Exchange WebSocket → Price Aggregator → Signal Generator → Agent Mesh → Consensus → Execution
```

### 8.2 Audit Trail
```
Intent → Simulation → Risk Preview → Consensus Block → Execution Result → Compliance Log
```

---

## 9. SAFETY RAILS

### 9.1 Execution Gates
- All execution disabled by default
- Requires explicit consensus approval
- Manual approval for high-risk operations
- Kill switch available at all times

### 9.2 Auto-Reject Rules (Sniping)
- Max buy tax: 15%
- Max sell tax: 20%
- Min liquidity: $1,000
- Require liquidity lock: Yes
- Min lock duration: 30 days
- Max dev holding: 20%
- Reject honeypots: Yes
- Reject proxy contracts: Yes
- Reject mint functions: Yes

---

## 10. RECOVERY PROCEDURES

### 10.1 Disaster Recovery Playbooks
1. Database Failure Recovery
2. Exchange Disconnection Recovery
3. Agent Cascade Failure Recovery
4. Capital Anomaly Recovery
5. Full System Restart

### 10.2 State Reconstruction
- Positions reconstructed from trade logs
- Consensus chain reconstructed from block logs
- Agent state reconstructed from decision logs

---

## 11. COMPLIANCE

### 11.1 Audit Requirements
- All trades logged with timestamps
- All consensus decisions recorded
- 7-year retention for financial records
- SOX compliance for audit logs

### 11.2 Report Types
- Daily Activity Report
- Monthly Summary Report
- Tax Report
- Large Transaction Report
- Suspicious Activity Report

---

## 12. VERSION CONTROL

This specification is FROZEN as of 2026-01-11.

Any changes MUST:
1. Be documented in MASTER_SPEC_CHANGELOG.md
2. Include rationale for change
3. Be approved by system governance
4. Update the document checksum

---

## DOCUMENT CHECKSUM

To verify document integrity:
```bash
sha256sum MASTER_SPEC_v1.0.md
```

**Expected checksum will be computed after document creation.**

---

*END OF MASTER SPECIFICATION v1.0*
