# MERID Cross-Chain Swarm Hub

**Version:** 1.0  
**Date:** 2026-01-15  
**Status:** ARCHITECTURE DESIGN

---

## 1. Overview

MERID will operate a **Cross-Chain Swarm Hub** that routes swaps and bridges across multiple chains. AI agents optimize routing, manage liquidity, and guard the rails with multi-layer security. The architecture starts with a conservative MVP (Ethereum ↔ Cronos EVM/zkEVM) while remaining modular for future chains (Arbitrum, Base).

**Objectives:**
- Provide unified "swap X on chain A → Y on chain B" experience
- Use AI swarms for route selection, risk control, and monitoring
- Integrate secure messaging (Chainlink CCIP) for intents and state sync
- Enforce strict caps, time-locks, and emergency controls

---

## 2. Architecture

### 2.1 High-Level Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                        MERID Control Plane                   │
│  - Swarm orchestrator                                        │
│  - Routing AI (RL, heuristics)                               │
│  - Security/anomaly agents                                   │
│  - Liquidity/risk agents                                     │
└──────────────────────────────────────────────────────────────┘
         │                         │                         │
         ▼                         ▼                         ▼
┌────────────────┐       ┌────────────────┐        ┌────────────────┐
│   Ethereum     │       │  Cronos EVM    │        │  Cronos zkEVM  │
│  Merid Hub     │       │  Merid Hub     │        │  Merid Hub     │
│  + Swap Mods   │       │  + Swap Mods   │        │  + Swap Mods   │
└────────────────┘       └────────────────┘        └────────────────┘
         │                         │                         │
         └──────────────┬──────────┼───────────┬──────────────┘
                        ▼          ▼           ▼
                 ┌────────────┐ ┌────────┐ ┌────────────┐
                 │ Bridges    │ │ CCIP   │ │ Relayers   │
                 │ (Lock/Mint│ │ Router │ │ + Oracles  │
                 └────────────┘ └────────┘ └────────────┘
```

### 2.2 Components

| Component | Description |
|-----------|-------------|
| **Merid Hub Contract (per chain)** | Tracks deposits, balances, cross-chain intents; exposes `requestSwap`, `requestBridge` |
| **Swap Module** | Integrates with chain-local DEX aggregators to swap tokens before/after bridging |
| **Bridge Adapter** | Wraps specific bridge implementations (MERID lock-mint, CCIP token transfer, third-party bridges) |
| **CCIP Adapter** | Handles cross-chain messaging (state sync, risk updates, governance directives) |
| **Relayer/Ops Layer** | Validates source events, submits proofs to destination chains, batches requests |
| **AI Swarm Layer** | Off-chain agents for routing, security, liquidity, governance coordination |

---

## 3. AI Swarm Roles

### 3.1 Route Optimization Agents
- Inputs: live gas prices, bridge fees, slippage estimates, historical reliability
- Methods: RL (policy gradient), heuristic scoring, time-series forecasting
- Outputs: best path (swap + bridge combination), fallback routes, batching decisions
- KPIs: cost per transfer, latency, success rate

### 3.2 Security & Anomaly Agents
- Monitor bridge flows, validator behavior, CCIP message logs
- Detect anomalies: unusual volume spikes, delayed confirmations, validator downtime
- Actions: block/weight routes, trigger time-locks, notify human ops, pause hub modules
- Techniques: unsupervised anomaly detection, rule-based thresholds, adversarial simulations

### 3.3 Liquidity & Risk Agents
- Determine liquidity allocation per chain/asset/bridge
- Enforce per-route caps, daily limits, per-asset ceilings
- Trigger rebalancing (on-chain + off-chain) via auctions or internal transfers
- Maintain risk dashboard for governance

### 3.4 Governance & Coordination Agents
- Propagate policy updates via CCIP (risk limits, whitelists)
- Enforce compliance with MERID moat (data capture, audit trails)
- Act as sentinels for chain upgrades or protocol changes

---

## 4. Flow: Cross-Chain Swap/Bridge

### 4.1 Sequence

1. **Request Submission**
   - User/agent calls `MeridHub.requestSwap(
       sourceChain, destChain, tokenIn, tokenOut, amount, minOut, preferences
     )`
   - Hub records intent, emits `SwapRequested` event

2. **Route Selection**
   - Routing agents evaluate DEX paths + bridges, considering cost/time/security
   - Selects primary bridge + swap routes, fallback options
   - Writes decision to on-chain queue (optional) or internal ledger

3. **Source Chain Execution**
   - Hub locks tokens (lock contract) or swaps locally if needed
   - Emits `AssetsLocked` event with metadata (amount, destination, route)

4. **Messaging / Proof**
   - Relayers gather event data; CCIP or MPC relayer set proves event to target chain
   - For CCIP: call `ccipSend` with payload (action, user, amount, metadata)

5. **Destination Chain Execution**
   - Hub receives message via `ccipReceive` or custom bridge handler
   - Mints/unlocks wrapped tokens, executes destination swap via swap module
   - Delivers final assets to user/strategy account

6. **Monitoring & Settlement**
   - AI agents track latency, cost, success
   - Liquidity/risk agents adjust caps, rebalancing
   - Audit logs stored in data warehouse (proprietary data moat)

### 4.2 AI Optimization Signals
- Gas price feed per chain
- Bridge fee schedule + reliability metrics
- DEX liquidity depth/slippage curves
- Historical latency per route
- Risk scores from security agents

---

## 5. Security Protocols & Risk Controls

### 5.1 Multi-Layer Security
1. **On-Chain Controls**
   - Time-locks on large transfers (> $250K) with 30-60 min delay
   - Per-asset daily caps (e.g., $1M per asset per bridge)
   - Emergency pause (hub, swap, bridge modules individually)

2. **Bridge Security**
   - MPC/threshold signing for relayer set (5-of-9 multi-sig)
   - Staked validators with slashing for misbehavior
   - Segregated custody for large pools, cold storage reserves

3. **Monitoring & Response**
   - Real-time anomaly detection
   - Automatic circuit breakers (pause when anomalies triggered)
   - Incident response runbooks

### 5.2 Audits & Formal Checks
- Third-party audits covering hub, swap adapters, bridge adapters, CCIP integration
- Formal verification of critical invariants:
  - 1:1 backing between locked & minted assets
  - No mint without proof of lock/burn
  - Cap/time-lock enforcement
- Continuous fuzzing + property-based tests

### 5.3 Risk Data Capture
- Each transfer logged with risk metrics (route ID, gas cost, latency, risk score)
- Stored in proprietary data warehouse for moat reinforcement
- Agents retrain models with new data (closed feedback loops)

---

## 6. Chain Selection Strategy

### 6.1 MVP Chains
1. **Ethereum Mainnet**
   - Canonical MERID assets, governance, deep liquidity
2. **Cronos EVM**
   - Primary execution base, low fees, Crypto.com ecosystem
3. **Cronos zkEVM**
   - Micro-capital flows, AI-heavy strategies
4. **Optional L2 (Arbitrum or Base)**
   - Additional liquidity / perp venues after MVP

**Criteria:**
- MERID strategy deployment footprint
- Liquidity depth and DEX options
- Bridge availability & security
- Operational overhead (monitoring, audits)

### 6.2 Expansion Policy
- Add new chains only when:
  - Clear strategy ROI
  - Bridge security meets standards
  - Liquidity/risk agents can support rebalancing
  - Governance approves with moat impact assessment

---

## 7. Chainlink CCIP Integration

### 7.1 Why CCIP?
- Generalized messaging + token transfer
- Secure oracle network with multiple verification layers
- Built-in rate limiting, allowlists, fee management
- Supported on Cronos roadmap; aligns with MERID security posture

### 7.2 Integration Pattern

**On Cronos Hub:**
```solidity
address constant CCIP_ROUTER = 0x...; // Chainlink CCIP router

function sendMessage(
    uint64 destinationChainSelector,
    bytes memory payload,
    Client.EVMTokenAmount[] memory tokenAmounts
) internal {
    Client.EVM2AnyMessage memory message = Client.EVM2AnyMessage({
        receiver: abi.encode(destinationHub),
        data: payload,
        tokenAmounts: tokenAmounts,
        extraArgs: Client._argsToBytes(
            Client.EVMExtraArgsV1({
                gasLimit: 2_000_000,
                strict: false
            })
        ),
        feeToken: address(0)
    });

    IRouterClient(CCIP_ROUTER).ccipSend{value: fee}(destinationChainSelector, message);
}
```

**On Ethereum Hub:**
```solidity
function ccipReceive(Client.Any2EVMMessage memory message) external {
    require(msg.sender == address(CCIP_ROUTER), "Not router");
    require(allowedSenders[message.sourceChainSelector][message.sender], "Not allowed");

    // Decode payload (action, user, amount, metadata)
    (Action action, bytes memory data) = abi.decode(message.data, (Action, bytes));

    if (action == Action.Mint) {
        _mintWrapped(data);
    } else if (action == Action.SettleSwap) {
        _settleSwap(data);
    }
}
```

### 7.3 Routing Logic with CCIP
- AI agents choose CCIP vs custom bridge per transfer
- CCIP used for message passing + token transfer when available
- Fallback to lock/mint bridge when CCIP congested or chain unsupported
- Rate limits enforced per CCIP lane (Chainlink built-in + MERID overlay)

---

## 8. Deployment Roadmap (MVP → Production)

### Phase 0: Design & Simulation (Week 0-2)
- Finalize architecture, risk models
- Simulate routing algorithms with historical data
- Define cap table, time-lock policies

### Phase 1: MVP (Week 3-6)
- Chains: Ethereum, Cronos EVM, Cronos zkEVM
- Deploy Merid Hub v1, swap modules, lock-mint bridge
- Integrate CCIP testnet for messaging
- Implement AI agents (routing v1, security baseline)
- Limit per-transaction to $50K, daily $500K

### Phase 2: Security Hardening (Week 7-10)
- Full audits (hub, adapters, CCIP integration)
- Formal verification of invariants
- Chaos testing: delayed proofs, relayer failure, gas spikes
- Bug bounty program launch

### Phase 3: Controlled Mainnet Launch (Week 11-14)
- Enable mainnet flows with tight caps
- Monitor performance, adjust AI models
- Add Arbitrum/Base if justified
- Publish user docs + transparency reports

### Phase 4: Scaling (Week 15+)
- Increase caps gradually
- Add more bridges/DEXs per chain
- Integrate additional AI models (multi-armed bandits, predictive failure detection)
- Expand to more chains when ROI positive

---

## 9. Risk Register

| Risk | Mitigation |
|------|------------|
| Bridge exploit | Use audited bridges, MPC custody, slashing, daily caps, time-locks |
| Relayer downtime | Multi-relayer sets, automated failover, CCIP fallback |
| Routing mistakes | AI human-in-the-loop, simulation testing, fallback routes |
| Liquidity imbalance | Liquidity agents rebalancing, on-chain auctions, emergency backstops |
| Governance attack | Multi-sig + timelock for hub upgrades, CCIP whitelists |
| Data poisoning | Trusted data feeds, anomaly detection, cross-validation |

---

## 10. Moat Impact

| Pillar | Moat Contribution |
|--------|-------------------|
| Proprietary Data | Cross-chain routing telemetry, bridge reliability stats, anomaly datasets |
| Execution & Infra | Multi-chain low-latency routing, gas optimization, batching |
| Swarm Architecture | Specialized cross-chain agents, RL routing models, security sentinels |
| Ecosystem & Governance | Integration with Cronos + Ethereum + L2s, CCIP partnerships |
| Legal & Compliance | Audit trails, risk controls, compliance-friendly architecture |

**Moat Score:** +1.0 (Strengthens all pillars)

---

## 11. Next Steps

1. Confirm chain priorities (Ethereum, Cronos EVM, Cronos zkEVM)
2. Define exact swap/bridge adapters for each chain
3. Prototype Merid Hub v1 with CCIP messaging stubs
4. Build AI routing simulator with historical data
5. Draft security audit scope and engage auditors
6. Prepare operations runbooks (monitoring, incident response)

---

**MERID Cross-Chain Swarm Hub** combines conservative bridge mechanics with AI-driven routing, enabling secure, low-latency capital mobility across chains while reinforcing MERID's moat.
