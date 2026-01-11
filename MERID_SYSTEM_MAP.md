# MERID SYSTEM MAP — CANONICAL SPECIFICATION

**Version:** 1.0.0  
**Status:** FROZEN  
**Last Updated:** 2026-01-11  
**Authority:** Master Build Directive  

---

## PURPOSE

This document provides the **canonical mapping of every MERID module to the institutional stack**. It is:

- Frozen as a spec
- Handoff-ready for implementation
- Auditable without ambiguity

---

## ARCHITECTURAL INVARIANTS

| Invariant | Enforcement |
|-----------|-------------|
| Capital survival > profit | Kelly fractions, thermodynamic cooling, vault firewalls |
| Perception precedes action | Phase 1 blocking requirement |
| Uncertainty modeled explicitly | Epistemic confidence, regime probabilities |
| No single agent trusted indefinitely | Model risk management, validation windows |
| Adversaries assumed hostile | MEV defense, behavioral randomization, honeytokens |
| Every belief decays | Time decay, confidence decay, pheromone evaporation |
| Every action vetoable | Intent-based withdrawals, multi-sig governance |

---

# LAYER 0 — CONSTITUTIONAL FOUNDATION

**System:** `MERID-GOV`

| Module | Location | Role | Status |
|--------|----------|------|--------|
| Consensus Engine | `core/consensus.py` | Enforces quorum + veto logic | ✅ |
| Constitutional Invariants | `governance/constitutional.py` | Hard limits, unoverrideable | ✅ |
| Schema Freeze & Hashing | `schemas/manifest.json` | Contract immutability | ✅ |
| Governance & Permissions | `governance/authority_boundary.py` | Authority control | ✅ |
| Capital Freeze Manager | `recovery/disaster_recovery.py` | Emergency halts | ✅ |
| Agent Quarantine | `recovery/disaster_recovery.py` | Isolate misbehaving agents | ✅ |
| Compliance Engine | `compliance/engine.py` | KYT, auditability | ✅ |
| Shadow Promotion Manager | `recovery/shadow_promotion.py` | Failover control | ✅ |
| Time Decay Manager | `governance/time_decay.py` | Authority expiration | ✅ |
| Adversarial Intelligence | `governance/adversarial.py` | Behavioral randomization, honeytokens | ✅ |
| Model Risk Management | `governance/model_risk.py` | Versioning, validation, kill authority | ✅ |

**Authority:**
- ✅ May veto any system
- ❌ May not generate signals or execute trades

---

# LAYER 1 — REGIME INTELLIGENCE

**System:** `MERID-OPS`

| Module | Location | Role | Status |
|--------|----------|------|--------|
| Signal Engine | `ops/signals.py` | Raw signal synthesis | ✅ |
| Simulation Engine V2 | `simulation/engine_v2.py` | Forward modeling | ✅ |
| Prediction Time Exploit | `prediction/time_exploit.py` | Oracle latency modeling | ✅ |
| Arbitrage Scanners | `arbitrage/scanners.py` | Inefficiency detection | ✅ |
| Cost / Slippage / Latency Models | `arbitrage/cost_models.py` | Execution feasibility | ✅ |
| Data Provenance Scoring | `ops/data_provenance.py` | Source trust decay | ✅ |
| Signal Entropy Tracker | `ops/signal_entropy.py` | Overfitting detection | ✅ |
| Cross-Domain Conflict Detector | `ops/conflict_detector.py` | Price vs news vs PM | ✅ |
| Unknown-Unknown Detector | `ops/vol_spike.py` | Vol without narrative | ✅ |
| Regime Detection | `ops/regime_detection.py` | HMM + Bayesian CPD | ✅ |
| Anomaly Detection | `ops/anomaly_detection.py` | Isolation Forest, CUSUM, Page-Hinkley | ✅ |
| Epistemic Confidence | `ops/epistemic_confidence.py` | Ensemble disagreement, OOD detection | ✅ |
| Information Latency | `ops/information_latency.py` | Oracle/exchange latency, alpha decay | ✅ |
| Causal Attribution | `ops/causal_attribution.py` | Strategy-outcome causality | ✅ |

**Authority:**
- ✅ May recommend
- ❌ May not execute
- ❌ May not move capital

---

# LAYER 2 — ANOMALY & ADVERSARIAL DETECTION

**System:** `MERID-OPS` + `MERID-GOV`

| Module | Location | Role | Status |
|--------|----------|------|--------|
| MEV Estimator | `arbitrage/cost_models.py` | Front-run risk | ✅ |
| Shadow Divergence Detector | `core/shadow_diff.py` | Parallel reality | ✅ |
| Governance Capture Detection | `governance/capture.py` | Token concentration | ✅ |
| Order Spoofing Detector | `ops/orderbook_anomaly.py` | Fake liquidity | ✅ |
| Social Manipulation Detector | `ops/social_authenticity.py` | Bot clusters | ✅ |
| Prediction Market Manipulation | `prediction/manipulation.py` | PM distortions | ✅ |
| Honeytoken Engine | `governance/adversarial.py` | Trap detection | ✅ |
| Behavioral Randomization | `governance/adversarial.py` | Anti-pattern exploitation | ✅ |
| MEV Defense | `trading/execution/defense.py` | Front-run protection | ✅ |

**Authority:**
- ✅ May escalate to GOV
- ❌ May not suppress alerts silently

---

# LAYER 3 — EXECUTION DOMINANCE

**System:** `MERID-FIN`

| Module | Location | Role | Status |
|--------|----------|------|--------|
| Execution Engine | `trading/execution.py` | CCXT order routing | ✅ |
| Wallet & Custody | `custody/wallets.py` | Hot / warm / cold | ✅ |
| Risk Preview Engine | `trading/risk_preview.py` | Pre-trade exposure | ✅ |
| Emergency Unwind | `trading/unwind.py` | Forced exits | ✅ |
| Slippage Abort Logic | `trading/guards.py` | Kill on breach | ✅ |
| Manual Approval Flow | `trading/approvals.py` | Human gate | ✅ |
| Optimal Execution | `trading/execution/optimal.py` | Almgren-Chriss, VWAP, TWAP | ✅ |
| Queue Position Estimator | `trading/execution/optimal.py` | Limit order fill probability | ✅ |
| MEV Defense Engine | `trading/execution/defense.py` | Manipulation detection | ✅ |

**Authority:**
- ❌ May not generate signals
- ❌ May not override GOV
- ✅ Executes *only* approved intents

---

# LAYER 4 — PORTFOLIO GEOMETRY & TREASURY

**System:** `MERID-TREASURY`

| Module | Location | Role | Status |
|--------|----------|------|--------|
| Yield Source Registry | `treasury/yield_strategies.py` | DeFi venues | ✅ |
| Strategy Simulator | `treasury/yield_strategies.py` | Monte Carlo sandbox | ✅ |
| Auto-Rebalancer | `treasury/drawdown_governor.py` | Passive shifts | ✅ |
| Drawdown Governor | `treasury/drawdown_governor.py` | Capital protection | ✅ |
| Profit Firewall | `treasury/vaults.py` | Principal separation | ✅ |
| Portfolio Geometry | `treasury/portfolio_geometry.py` | Fractional Kelly, HRP | ✅ |
| Copula Tail Dependency | `treasury/portfolio_geometry.py` | Tail risk modeling | ✅ |
| Capital Thermodynamics | `treasury/capital_thermodynamics.py` | Temperature, cooling | ✅ |
| Vault Architecture | `treasury/vaults.py` | Multi-sig, time-locks | ✅ |

**Authority:**
- ❌ Cannot trade markets
- ❌ Cannot fund FIN without GOV
- ✅ Manages *profits only*

---

# LAYER 5 — ALPHA ENSEMBLES

**System:** `MERID-OPS → MERID-FIN`

| Module | Location | Role | Status |
|--------|----------|------|--------|
| Arbitrage Engine | `arbitrage/engine.py` | Non-directional alpha | ✅ |
| Funding Rate Arb | `arbitrage/funding.py` | Perps basis | ✅ |
| Prediction Market Arb | `prediction/arb.py` | PM inefficiencies | ✅ |
| Memecoin Sniping | `sniping/memecoin_engine.py` | High-risk alpha | ✅ |
| Stat Signals | `ops/stat_models.py` | Mean reversion | ✅ |
| Perp-Spot Scanner | `arbitrage/perp_spot_scanner.py` | Cross-venue arb | ✅ |

**Authority:**
- ❌ Cannot self-execute
- ❌ Cannot size positions
- ✅ Produces IntentEnvelopes

---

# LAYER 6 — LEARNING & ADAPTATION

**System:** `MERID-ARCHIVE` + `MERID-OPS`

| Module | Location | Role | Status |
|--------|----------|------|--------|
| Performance Analytics | `analytics/performance.py` | Outcome scoring | ✅ |
| Agent Accuracy Scoring | `analytics/agents.py` | Trust weighting | ✅ |
| Strategy Half-Life | `analytics/decay.py` | Alpha decay | ✅ |
| Counterfactual Engine | `analytics/counterfactual.py` | Regret analysis | ✅ |
| MARL Coordinator | `learning/marl/coordinator.py` | Multi-agent RL training | ✅ |
| MAPPO | `learning/marl/mappo.py` | Multi-Agent PPO | ✅ |
| COMA | `learning/marl/coma.py` | Counterfactual policy gradients | ✅ |
| QMIX | `learning/marl/qmix.py` | Value function factorization | ✅ |
| VDN | `learning/marl/vdn.py` | Value decomposition | ✅ |
| IPPO | `learning/marl/ippo.py` | Independent PPO | ✅ |
| MAML | `learning/meta/maml.py` | Model-agnostic meta-learning | ✅ |
| Regime-Conditioned Policies | `learning/meta/regime_conditioned.py` | Adaptive policies | ✅ |
| PSO | `learning/swarm/pso.py` | Particle swarm optimization | ✅ |
| ACO | `learning/swarm/aco.py` | Ant colony optimization | ✅ |
| ABC | `learning/swarm/abc.py` | Artificial bee colony | ✅ |
| Boids | `learning/swarm/boids.py` | Flocking coordination | ✅ |
| DeepSwarm | `learning/swarm/deep_swarm.py` | Neural architecture search | ✅ |

**Authority:**
- ❌ Cannot deploy live models without GOV approval
- ✅ Research & decay only

---

# LAYER 7 — MEMORY & FORENSICS

**System:** `MERID-ARCHIVE`

| Module | Location | Role | Status |
|--------|----------|------|--------|
| Audit Ledger | `archive/ledger.py` | Immutable history | ✅ |
| Hash Chains | `archive/hashchain.py` | Tamper proofing | ✅ |
| Decision Logs | `archive/decisions.py` | Intent → outcome | ✅ |
| Replay Engine | `archive/replay.py` | Simulation rewind | ✅ |

**Authority:**
- ❌ Cannot influence live systems
- ✅ Immutable truth

---

# AUTHORITY MATRIX

| System | Can Signal | Can Execute | Can Move Capital | Can Veto |
|--------|------------|-------------|------------------|----------|
| OPS | ✅ | ❌ | ❌ | ❌ |
| GOV | ❌ | ❌ | ❌ | ✅ |
| FIN | ❌ | ✅ | ⚠️ (approved only) | ❌ |
| TREASURY | ❌ | ❌ | ✅ (profits only) | ❌ |
| ARCHIVE | ❌ | ❌ | ❌ | ❌ |

---

# DOCUMENT CONTROL

| Field | Value |
|-------|-------|
| Document ID | `MERID-SYS-MAP-001` |
| Classification | INTERNAL |
| Review Cycle | Quarterly |
| Owner | MERID-GOV |
| Hash | `SHA256:TO_BE_COMPUTED_ON_FREEZE` |

---

**END OF DOCUMENT**
