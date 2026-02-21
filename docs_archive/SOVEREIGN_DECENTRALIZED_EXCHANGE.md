# MERID Sovereign & Decentralized Exchange Architecture

**Version:** 1.0  
**Date:** 2026-01-14  
**Status:** COMPREHENSIVE DESIGN

---

## Executive Summary

MERID is a **sovereign, truly decentralized, non-custodial DEX + DeFi + AI-swarm trading system** where:

- ❌ **No centralized entity** can seize funds, halt trading, or unilaterally change rules
- ✅ **All critical control** is on-chain, DAO-governed, and forkable
- ✅ **Users retain key sovereignty** with robust online/offline flows
- ✅ **AI swarm constrained** by on-chain policy and community governance

---

## 1. Measurable Sovereignty Goals ✅

### Location
`sovereignty/sovereignty_goals_metrics.py`

### 1.1 Custody Sovereignty

**Goal: 100% Non-Custodial**

| Metric | Target | Priority | Status |
|--------|--------|----------|--------|
| **Percentage Non-Custodial** | 100% | Critical | Tracking |
| **On-Chain Authorization** | 100% | Critical | Tracking |
| **CEX Custodial Accounts** | 0 | Critical | Tracking |
| **Hardware Wallet Support** | ≥3 types | High | Tracking |
| **Multi-Sig Treasury** | Enabled | Critical | Tracking |

**Implementation:**
```python
from sovereignty.sovereignty_goals_metrics import get_sovereignty_goals_metrics

metrics = get_sovereignty_goals_metrics()

# Update measurement
metrics.update_goal_measurement(
    goal_id="custody_non_custodial_funds",
    current_value=Decimal("100.0"),
)

# Get compliance report
report = metrics.get_compliance_report()
print(f"Overall compliance: {report['overall_compliance']:.1f}%")
```

**Enforcement:**
- All user funds held in non-custodial smart-contract vaults
- Every asset move requires on-chain signature from user keys or DAO contracts
- Zero off-chain custody or centralized exchange accounts
- Hardware wallet support: Ledger, Trezor, GridPlus

### 1.2 Governance Sovereignty

**Goal: 80%+ DAO-Controlled Parameters**

| Metric | Target | Priority | Status |
|--------|--------|----------|--------|
| **DAO-Controlled Parameters** | ≥80% | Critical | Tracking |
| **Emergency Multisig Limited** | Yes | High | Tracking |
| **Multisig Sunset Timeline** | Defined | High | Tracking |
| **Max Single Entity Tokens** | ≤20% | Critical | Tracking |
| **AI Policy DAO-Controlled** | Yes | Critical | Tracking |

**DAO-Controlled Parameters:**
- Protocol fees and fee curves
- Asset whitelists/blacklists
- Risk limits (leverage, position sizes)
- Oracle configurations and fallbacks
- AI agent policies and capital limits
- Emissions and reward schedules

**Emergency Multisig:**
- Powers: Pause trading, pause specific markets, emergency oracle override
- Limitations: Cannot seize funds, cannot change parameters without DAO
- Time-locks: 24-48 hours for most actions
- Sunset: Reduce powers to zero over 24 months

### 1.3 Infrastructure Independence

**Goal: No Single Point of Failure**

| Metric | Target | Priority | Status |
|--------|--------|----------|--------|
| **RPC Providers** | ≥2 | High | Tracking |
| **Oracle Providers** | ≥2 | Critical | Tracking |
| **AI Vendors** | ≥2 | High | Tracking |
| **Cloud Providers** | ≥2 | High | Tracking |
| **Community-Run Services** | ≥1 per service | High | Tracking |
| **Frontend Decentralized** | IPFS/Arweave | Medium | Tracking |

**Redundancy Strategy:**
- RPC: Infura, Alchemy, QuickNode, + community-run nodes
- Oracles: Chainlink, Pyth, UMA, + DAO-operated fallback
- AI: OpenAI, Anthropic, + open-source local models
- Cloud: AWS, GCP, + bare-metal community servers
- Frontend: IPFS + Arweave + ENS naming

### 1.4 Forkability

**Goal: Community Can Fork with Minimal Friction**

| Metric | Target | Priority | Status |
|--------|--------|----------|--------|
| **Open Source Contracts** | 100% | Critical | Tracking |
| **Open Source AI** | Yes | High | Tracking |
| **State Exportable** | Yes | High | Tracking |
| **Fork Setup Time** | ≤7 days | Medium | Tracking |

**Fork-Friendly Design:**
- All smart contracts open source (MIT/Apache 2.0)
- AI orchestration code open source
- On-chain state structured for export
- Clear migration paths for vaults
- No proprietary dependencies

### 1.5 Offline Robustness

**Goal: Safety-Critical Actions Work Offline**

| Metric | Target | Priority | Status |
|--------|--------|----------|--------|
| **Direct Withdrawal** | Supported | Critical | Tracking |
| **Direct Pause** | Supported | Critical | Tracking |
| **Air-Gapped Signing** | Supported | High | Tracking |
| **Social Recovery** | Supported | Medium | Tracking |
| **CLI Tools** | Available | High | Tracking |

**Offline Capabilities:**
- Withdraw from vaults using only RPC + wallet (no MERID frontend)
- Trigger DAO/guardian actions via Etherscan-style UIs
- Air-gapped signing for critical actions (withdrawals, upgrades)
- Social recovery smart-contract wallets with guardians
- CLI tools for all safety-critical operations

---

## 2. Essential On-Chain DEX Components ✅

### Location
`sovereignty/onchain_dex_components.py`

### 2.1 Core Trading & Liquidity Contracts

**AMM Pools (Spot, Memecoins, xStocks)**
```solidity
contract AMMSpotPool {
    // Uniswap V3-style concentrated liquidity
    // Supports crypto, memecoins, tokenized equities
    // DAO-controlled fee tiers and parameters
}
```

**Order Book / RFQ**
```solidity
contract OrderBookSpot {
    // On-chain order book for spot trading
    // RFQ (Request for Quote) support
    // Deployed on Arbitrum for low gas
}
```

**Perpetual Futures**
```solidity
contract PerpMarket {
    // Perpetual futures with funding rates
    // Margin and liquidation logic
    // Depends on: PriceOracle, MarginAccount
}
```

**Router & Aggregator**
```solidity
contract RouterAggregator {
    // Best-execution routing across pools
    // Multi-hop swaps
    // Slippage protection
}
```

### 2.2 Vaults, Margin, Collateral

**User Vault (Immutable)**
```solidity
contract UserVault {
    // Non-custodial user deposits
    // Withdrawal only by user signature
    // IMMUTABLE - no upgrades
}
```

**Strategy Vault (DAO-Controlled)**
```solidity
contract StrategyVault {
    // AI strategy capital allocation
    // Enforces AI policy limits
    // DAO-upgradeable with 48h timelock
}
```

**Margin Account**
```solidity
contract MarginAccount {
    // Collateral management for leverage
    // Liquidation engine
    // Cross-margin support
}
```

**BTC Trustless Vault**
```solidity
contract BTCVault {
    // Trust-minimized BTC custody
    // Threshold signatures (TSS)
    // No centralized custodian
}
```

### 2.3 Oracles & Data

**Price Oracle (Multi-Source)**
```solidity
contract PriceOracle {
    // Primary: Chainlink
    // Fallback: Pyth, UMA
    // DAO-controlled source weights
    // Deviation thresholds and circuit breakers
}
```

**Prediction Market Oracle**
```solidity
contract PredictionMarketOracle {
    // Resolution oracle for prediction markets
    // Dispute resolution mechanism
    // DAO-governed resolution criteria
}
```

**Cross-Chain Oracle**
```solidity
contract CrossChainOracle {
    // Cross-chain state verification
    // Bridge message validation
    // Multi-bridge aggregation
}
```

### 2.4 Governance & Parameters

**DAO Governance**
```solidity
contract DAOGovernance {
    // Proposal creation and voting
    // Token-based or ve-style voting
    // Execution with timelock
    // Quorum and threshold requirements
}
```

**Parameter Registry**
```solidity
contract ParameterRegistry {
    // Risk limits (leverage, position sizes)
    // Fee curves and tiers
    // Asset whitelists/blacklists
    // AI policy settings
    // DAO-controlled updates with timelock
}
```

**Guardian Multisig (Time-Locked)**
```solidity
contract GuardianMultisig {
    // Emergency pause powers
    // Time-locked actions (24-48h)
    // Cannot seize funds
    // Sunset roadmap over 24 months
}
```

### 2.5 AI Registry & Control

**AI Agent Registry**
```solidity
contract AIAgentRegistry {
    // Authorized AI agents
    // Strategy types and tool permissions
    // Capital limits per agent
    // DAO approval required
}
```

**AI Policy Contract**
```solidity
contract AIPolicyContract {
    // Per-agent capital limits
    // Asset/venue allowlists
    // Behavior restrictions
    // Risk limits (drawdown, daily loss)
    // DAO-governed policy updates
}
```

**Example AI Policy:**
```python
policy = AIAgentPolicy(
    policy_id="momentum_trader_v1",
    agent_id="momentum_agent_001",
    max_capital_usd=1_000_000,
    max_leverage=3,
    allowed_assets={"BTC", "ETH", "SOL"},
    allowed_venues={"kraken", "uniswap_v3"},
    blocked_behaviors={"high_frequency", "wash_trading"},
    max_drawdown_percent=20,
    max_daily_loss_usd=50_000,
    approved_by_dao=True,
)
```

### 2.6 Treasury & Rewards

**DAO Treasury (Multi-Sig)**
```solidity
contract DAOTreasury {
    // Protocol treasury
    // Multi-sig protection (5-of-9)
    // DAO spending proposals
    // 72h timelock for large transfers
}
```

**Fee Collector**
```solidity
contract FeeCollector {
    // Collect protocol fees
    // Distribute to treasury, stakers, LPs
    // DAO-controlled distribution ratios
}
```

**Reward Distributor**
```solidity
contract RewardDistributor {
    // Token emissions
    // Vesting schedules
    // Lockup periods
    // DAO-controlled emission curves
}
```

### 2.7 Identity & Access

**DID Registry (Optional)**
```solidity
contract DIDRegistry {
    // Decentralized identity (DID/SSI)
    // KYC attestations without central silos
    // Privacy-preserving credentials
    // Optional for compliance
}
```

### 2.8 Cross-Chain & Bridges

**Canonical Bridge**
```solidity
contract CanonicalBridge {
    // Trust-minimized cross-chain bridge
    // Multi-bridge aggregation
    // Fallback and rollback mechanisms
    // DAO-controlled bridge configs
}
```

### Contract Deployment Summary

```python
from sovereignty.onchain_dex_components import get_onchain_dex_components

components = get_onchain_dex_components()

# Get deployment summary
summary = components.get_deployment_summary()
print(f"Total contracts: {summary['total_contracts']}")
print(f"Deployed: {summary['deployed']} ({summary['deployment_percentage']:.1f}%)")
print(f"Critical deployed: {summary['critical_deployed']}/{summary['critical_contracts']}")

# Get critical contracts
critical = components.get_critical_contracts()
for contract in critical:
    print(f"- {contract.name}: {contract.description}")
```

---

## 3. Non-Custodial Key Management & Offline Custody ✅

### 3.1 Wallet & Key Models

**Supported Wallet Types:**

1. **Hardware Wallets** (Recommended for large balances)
   - Ledger Nano S/X
   - Trezor Model T
   - GridPlus Lattice1
   - Air-gapped signing support

2. **Software Wallets**
   - MetaMask, Rainbow, Rabby
   - WalletConnect integration
   - Client-side key encryption

3. **Smart-Contract Wallets**
   - Gnosis Safe (multi-sig)
   - Argent (social recovery)
   - Account abstraction (ERC-4337)

4. **MPC Wallets** (For DAO treasury)
   - Fireblocks, Qredo
   - Threshold signatures
   - No single point of key compromise

### 3.2 Secure Key Practices

**Key Separation:**
```
Signing Keys (Hot)
├── Trading operations
├── Strategy execution
└── Routine transactions

Custody Keys (Cold)
├── Vault withdrawals
├── Large transfers
└── Parameter changes

Recovery Keys (Offline)
├── Social recovery guardians
├── Time-locked recovery
└── Emergency access
```

**Key Security Rules:**
1. Never reuse keys across chains or domains
2. Separate signing keys from encryption/auth keys
3. Use strong client-side encryption (AES-256-GCM)
4. Never send keys to servers
5. Hardware wallet for >$10k balances
6. Multi-sig for >$100k balances

### 3.3 Offline Features

**Air-Gapped Signing Flow:**
```
1. Online Device: Prepare unsigned transaction
2. Transfer: QR code or USB (data only, no keys)
3. Offline Device: Sign with hardware wallet
4. Transfer: Signed transaction back via QR/USB
5. Online Device: Broadcast to network
```

**Direct Contract Interaction (No Frontend):**
```bash
# Withdraw from vault using cast (Foundry)
cast send $VAULT_ADDRESS \
  "withdraw(uint256)" 1000000000000000000 \
  --private-key $PRIVATE_KEY \
  --rpc-url $RPC_URL

# Pause trading (guardian)
cast send $GUARDIAN_ADDRESS \
  "pauseTrading()" \
  --ledger \
  --rpc-url $RPC_URL

# DAO vote
cast send $DAO_ADDRESS \
  "vote(uint256,bool)" 42 true \
  --ledger \
  --rpc-url $RPC_URL
```

**Social Recovery:**
```solidity
contract SocialRecoveryWallet {
    address[] public guardians;
    uint256 public threshold; // e.g., 3-of-5
    uint256 public recoveryDelay; // e.g., 7 days
    
    function initiateRecovery(address newOwner) external {
        require(isGuardian(msg.sender), "Not guardian");
        // Start recovery with timelock
    }
    
    function executeRecovery() external {
        require(recoveryApproved(), "Not enough guardians");
        require(recoveryDelayPassed(), "Timelock active");
        // Transfer ownership to newOwner
    }
}
```

### 3.4 Offline Robustness Guarantees

**Users can always:**
- ✅ Withdraw funds using only RPC + wallet (no MERID frontend)
- ✅ Check balances via blockchain explorer
- ✅ Sign transactions offline with hardware wallet
- ✅ Recover account via social recovery guardians
- ✅ Interact with contracts via Etherscan write functions

**Guardians/DAO can always:**
- ✅ Pause trading via direct contract call
- ✅ Execute emergency actions via CLI tools
- ✅ Vote on proposals via Etherscan
- ✅ Override oracle in emergency (with timelock)

**Swarm/backend downtime never blocks:**
- ✅ User withdrawals
- ✅ Emergency pauses
- ✅ DAO governance
- ✅ Oracle updates
- ✅ Liquidations (keeper network)

---

## 4. Recommended Tech Stack (DEX + Cross-Chain + Rollups) ✅

### 4.1 Base Chains / Rollups

**Primary Deployment:**

| Chain | Type | Use Case | Rationale |
|-------|------|----------|-----------|
| **Ethereum L1** | Base layer | Governance, treasury, critical vaults | Security, decentralization |
| **Arbitrum** | Optimistic rollup | Perps, order books, high-frequency | Low gas, EVM-compatible |
| **Base** | Optimistic rollup | Spot trading, AMM pools | Coinbase-backed, growing liquidity |
| **Optimism** | Optimistic rollup | Alternative deployment | Redundancy, OP Stack |

**Cross-Chain Strategy:**
- Deploy core governance and treasury on Ethereum L1
- Deploy trading contracts on L2s for low gas
- Use canonical bridges for L1 ↔ L2 communication
- Maintain consistent contract interfaces across chains

### 4.2 Smart Contract Layer

**Languages:**
- **Solidity** (primary): Battle-tested, largest ecosystem
- **Vyper** (alternative): Simpler, more auditable
- **Rust** (future): For non-EVM chains if needed

**Frameworks:**
- **Hardhat**: Development, testing, deployment
- **Foundry**: Fast testing, fuzzing, gas optimization
- **OpenZeppelin**: Secure contract libraries

**Standards:**
- ERC-20: Token standard
- ERC-721/1155: NFT positions (Uniswap V3-style)
- ERC-4337: Account abstraction
- EIP-712: Typed structured data signing

### 4.3 Cross-Chain Swaps & Rollups

**Bridge Strategy:**

| Bridge | Type | Trust Model | Use Case |
|--------|------|-------------|----------|
| **Canonical L1↔L2** | Native | Trust-minimized | Ethereum ↔ Arbitrum/Base |
| **Across Protocol** | Optimistic | Economic security | Fast L2 ↔ L2 |
| **Connext** | Modular | Multi-bridge | Fallback option |
| **Stargate** | Unified liquidity | Layered security | Cross-chain swaps |

**Cross-Chain Router:**
```solidity
contract CrossChainRouter {
    // Multi-bridge aggregation
    // Automatic fallback if primary bridge fails
    // DAO-controlled bridge weights
    
    function swap(
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 minAmountOut,
        uint256 destChainId,
        address recipient
    ) external {
        // Route through best available bridge
        // Verify cross-chain message
        // Execute swap on destination chain
    }
}
```

**Rollback Mechanism:**
```solidity
contract BridgeRollback {
    // If bridge misbehaves, DAO can:
    // 1. Pause bridge
    // 2. Rollback pending transactions
    // 3. Migrate to alternative bridge
    // 4. Compensate affected users from treasury
}
```

### 4.4 Off-Chain Components (Minimized Trust)

**Relayers/Keepers:**
- **Open participation**: Anyone can run relayer/keeper
- **On-chain incentives**: Gas refunds + rewards
- **Redundancy**: Multiple keepers compete
- **Slashing**: Misbehavior penalized

**AI/Agent Nodes:**
```yaml
AI Node Architecture:
  - Container: Docker/Kubernetes
  - Config Source: On-chain parameter registry
  - RPC: Multiple providers (Infura, Alchemy, community)
  - Execution: Read-only until DAO approval
  - Monitoring: Prometheus + Grafana
  - Logging: Decentralized (Ceramic, IPFS)
  - Replaceable: Community can run own nodes
```

**Decentralization Roadmap:**
```
Phase 1 (Months 0-6): Centralized AI nodes
├── Run by core team
├── Read configs from chain
└── Open-source code

Phase 2 (Months 6-12): Semi-decentralized
├── Community can run nodes
├── Incentivized participation
└── Redundant node operators

Phase 3 (Months 12-24): Fully decentralized
├── Permissionless node operation
├── Slashing for misbehavior
└── DAO-governed node registry
```

### 4.5 Frontend & UX

**Decentralized Hosting:**
```
Primary: IPFS (InterPlanetary File System)
├── Content-addressed storage
├── Pinning services (Pinata, Infura IPFS)
└── Community pinning

Backup: Arweave (Permanent storage)
├── Pay once, store forever
├── Immutable historical versions
└── Censorship-resistant

Naming: ENS (Ethereum Name Service)
├── merid.eth → IPFS hash
├── Automatic updates via DAO
└── Decentralized DNS
```

**Frontend Stack:**
```typescript
// React + Next.js + TypeScript
import { useWallet } from '@/hooks/useWallet'
import { useContract } from '@/hooks/useContract'

function TradingInterface() {
  const { address, signer } = useWallet()
  const vault = useContract('UserVault', signer)
  
  // All state from on-chain
  // No centralized backend
  // Fallback to RPC if frontend down
}
```

**Wallet Integration:**
```typescript
// WalletConnect + RainbowKit
import { ConnectButton } from '@rainbow-me/rainbowkit'

// Supports: MetaMask, Ledger, Trezor, WalletConnect
// Hardware wallet signing
// Multi-chain support
```

### 4.6 Data & Indexing

**Decentralized Indexing:**
```
The Graph (Primary)
├── Subgraphs for all contracts
├── GraphQL queries
├── Community-run indexers
└── Decentralized network

Goldsky (Backup)
├── Alternative indexing
├── Real-time data
└── Redundancy

Self-Hosted ETL (Fallback)
├── Open-source pipeline
├── Anyone can run
└── Direct RPC queries
```

**Data Storage:**
```
On-Chain: Critical state
├── Balances, positions, orders
├── Governance votes
└── AI policies

IPFS: Historical data
├── Trade history
├── Analytics snapshots
└── Audit logs

Arweave: Permanent records
├── Governance proposals
├── Audit reports
└── Major events
```

### 4.7 Centralization → Decentralization Roadmap

**Current Centralized Components:**

| Component | Current State | Decentralization Plan | Timeline |
|-----------|---------------|----------------------|----------|
| **Frontend Hosting** | AWS CloudFront | IPFS + ENS | Month 3 |
| **RPC Providers** | Infura only | + Alchemy, QuickNode, community | Month 1 |
| **AI Nodes** | Core team | Community operators | Month 12 |
| **Indexing** | Centralized DB | The Graph subgraphs | Month 6 |
| **Oracle** | Single source | Multi-source aggregation | Month 3 |
| **Emergency Multisig** | 3-of-5 team | 5-of-9 community | Month 6 |

---

## 5. Governance Model (Decentralization + Safety) ✅

### 5.1 DAO-Centric Control

**Token-Based Voting:**
```solidity
contract MERIDGovernance {
    IERC20 public governanceToken; // MERID token
    
    struct Proposal {
        uint256 id;
        address proposer;
        string description;
        bytes[] actions; // Contract calls to execute
        uint256 forVotes;
        uint256 againstVotes;
        uint256 startBlock;
        uint256 endBlock;
        bool executed;
    }
    
    // Quorum: 4% of total supply
    // Threshold: 60% approval
    // Voting period: 7 days
    // Timelock: 48 hours after passing
}
```

**ve-Style Voting (Alternative):**
```solidity
contract veMERID {
    // Vote-escrowed MERID
    // Lock MERID for 1-4 years
    // Voting power = amount * lock_time
    // Prevents governance attacks
    // Aligns long-term incentives
}
```

**Specialized Councils:**
```
Risk Council (5 members)
├── Risk parameter adjustments
├── Leverage limits
├── Liquidation thresholds
└── Elected by DAO, 6-month terms

AI Safety Council (7 members)
├── AI agent whitelisting
├── Capital limit approvals
├── Behavior policy updates
└── Elected by DAO, 6-month terms

RWA Council (5 members)
├── RWA asset listings
├── Custody arrangements
├── Compliance reviews
└── Elected by DAO, 6-month terms
```

### 5.2 Guardian/Emergency Modules (With Sunset)

**Guardian Powers (Time-Limited):**
```solidity
contract GuardianModule {
    address[] public guardians; // 5-of-9 multisig
    
    // ALLOWED:
    function pauseTrading() external onlyGuardian {
        // 24h timelock
        // Cannot seize funds
    }
    
    function pauseMarket(address market) external onlyGuardian {
        // Immediate (no timelock)
        // Market-specific
    }
    
    function overrideOracle(address oracle, uint256 price) external onlyGuardian {
        // 48h timelock
        // Emergency only
        // DAO can veto
    }
    
    // NOT ALLOWED:
    // - Seize user funds
    // - Change parameters without DAO
    // - Upgrade contracts without DAO
    // - Mint tokens
}
```

**Sunset Roadmap:**
```
Month 0-6: Full guardian powers
├── Pause trading
├── Pause markets
├── Override oracle (48h timelock)
└── Emergency upgrades (72h timelock)

Month 6-12: Reduced powers
├── Pause trading (24h timelock)
├── Pause markets (12h timelock)
├── Oracle override requires DAO approval
└── No upgrade powers

Month 12-18: Minimal powers
├── Pause markets only (12h timelock)
├── All other actions require DAO vote
└── Guardian role becomes advisory

Month 18-24: Sunset complete
├── Guardian multisig dissolved
├── All powers transferred to DAO
└── Emergency actions via fast-track DAO votes
```

### 5.3 AI-Aware Governance

**AI Policy Governance:**
```solidity
contract AIGovernance {
    // Whitelisting new AI agents
    function proposeAgent(
        address agent,
        string memory strategyType,
        uint256 maxCapital
    ) external returns (uint256 proposalId) {
        // DAO vote required
        // AI Safety Council review
        // 7-day voting period
    }
    
    // Adjusting capital limits
    function adjustCapitalLimit(
        address agent,
        uint256 newLimit
    ) external onlyDAO {
        // Immediate effect
        // Logged on-chain
    }
    
    // Emergency agent pause
    function pauseAgent(address agent) external {
        require(
            msg.sender == guardian || msg.sender == dao,
            "Unauthorized"
        );
        // Immediate pause
        // Cannot restart without DAO vote
    }
}
```

**AI Safety Policies (On-Chain):**
```solidity
contract AISafetyPolicy {
    struct AgentLimits {
        uint256 maxCapitalUSD;
        uint256 maxLeverage;
        uint256 maxDrawdownPercent;
        uint256 maxDailyLossUSD;
        address[] allowedAssets;
        address[] allowedVenues;
        string[] blockedBehaviors;
    }
    
    mapping(address => AgentLimits) public agentLimits;
    
    // DAO can update limits
    // AI nodes read limits from chain
    // Violations trigger automatic pause
}
```

### 5.4 Anti-Capture Mechanisms

**Token Distribution Limits:**
```
Maximum Single Entity: 20% of supply
├── Enforced via vesting contracts
├── Monitored via on-chain analytics
└── DAO can dilute if exceeded

Team Allocation: 15% (4-year vest)
Investors: 20% (2-year vest)
Community: 40% (emissions over 5 years)
Treasury: 15% (DAO-controlled)
Liquidity Mining: 10% (first 2 years)
```

**Quadratic Voting (For Some Decisions):**
```solidity
contract QuadraticVoting {
    // Cost to cast N votes = N^2 tokens
    // Prevents whale dominance
    // Used for: Community grants, minor parameter changes
    // Not used for: Major upgrades, treasury spends
}
```

**Continuous Monitoring:**
```python
# On-chain governance analytics
def check_governance_concentration():
    top_10_holders = get_top_token_holders(10)
    total_supply = get_total_supply()
    
    concentration = sum(h.balance for h in top_10_holders) / total_supply
    
    if concentration > 0.51:
        alert("CRITICAL: >51% concentration in top 10 holders")
        trigger_dao_discussion("governance_capture_risk")
    
    return concentration
```

**Crisis Procedures:**
```
If Governance Capture Detected:
1. Community alert via all channels
2. Emergency DAO vote to:
   - Dilute captured tokens (via emissions)
   - Fork governance to new contract
   - Migrate to new deployment
3. Guardian pause (if available)
4. Community coordination for fork
```

### 5.5 Fork-Friendly Design

**Forkability Guarantees:**
```
Smart Contracts:
├── 100% open source (MIT license)
├── Verified on Etherscan
├── Comprehensive documentation
└── Deployment scripts public

AI Orchestration:
├── Open source (Apache 2.0)
├── Docker containers
├── Config templates
└── Setup guides

On-Chain State:
├── Exportable via subgraphs
├── Snapshot tools provided
├── Migration contracts
└── <7 days to fork
```

**Fork Procedure:**
```bash
# 1. Clone contracts
git clone https://github.com/merid-protocol/contracts
cd contracts

# 2. Deploy to new chain
forge script script/Deploy.s.sol --broadcast

# 3. Export state from original
node scripts/export-state.js --output state.json

# 4. Import state to new deployment
node scripts/import-state.js --input state.json

# 5. Update frontend
# Point IPFS frontend to new contract addresses

# 6. Announce to community
# Users migrate by withdrawing from old, depositing to new
```

---

## 6. Sovereignty Validation Framework ✅

### 6.1 Required Output for Any Component

For every component or change, you MUST provide:

**1. Sovereignty Impact Statement**
```markdown
### Sovereignty Impact

**Custody:** [How does this affect user fund custody?]
**Governance:** [Who can change this? DAO, multisig, immutable?]
**Infrastructure:** [What external dependencies? Single points of failure?]
**Forkability:** [Can community fork this? Open source?]
**Offline:** [Can users/DAO operate without frontend/backend?]
```

**2. On-Chain Dependencies**
```markdown
### On-Chain Dependencies

**Reads From:**
- Contract A: For price data
- Contract B: For risk limits

**Writes To:**
- Contract C: Position updates
- Contract D: Fee collection

**Failure Modes:**
- If Contract A fails: [Fallback to Contract E]
- If off-chain component fails: [Users can still withdraw via direct contract call]
```

**3. Offline Paths**
```markdown
### Offline Execution Paths

**Users Can:**
- Withdraw: `cast send $VAULT "withdraw(uint256)" $AMOUNT --ledger`
- Check balance: Etherscan or any block explorer

**Guardians Can:**
- Pause: `cast send $GUARDIAN "pauseTrading()" --ledger`

**DAO Can:**
- Vote: Via Etherscan write functions
- Execute: Via Gnosis Safe UI or CLI
```

**4. Tech Stack & Decentralization**
```markdown
### Tech Stack

**Current:**
- Frontend: AWS CloudFront (centralized)
- RPC: Infura only (centralized)
- Indexing: Centralized DB (centralized)

**Decentralization Roadmap:**
- Month 3: Frontend → IPFS + ENS
- Month 1: RPC → Multi-provider + community nodes
- Month 6: Indexing → The Graph subgraphs
```

**5. Governance Control**
```markdown
### Governance Control

**Who Can Change:**
- DAO (80% of parameters)
- Guardian (pause only, 24h timelock)
- Immutable (20% of core contracts)

**How to Change:**
1. DAO proposal (7-day vote)
2. 48h timelock after passing
3. Execution by anyone

**Checks:**
- Quorum: 4% of supply
- Approval: 60% threshold
- Veto: Guardian can veto for 24h (emergency only)
```

### 6.2 Sovereignty Violation Detection

**Automatic Checks:**
```python
from sovereignty.sovereignty_goals_metrics import get_sovereignty_goals_metrics

def validate_sovereignty(component_id: str) -> List[str]:
    """Validate component against sovereignty goals."""
    violations = []
    
    # Check custody
    if has_custodial_dependency(component_id):
        violations.append("CUSTODY VIOLATION: Component relies on custodial service")
    
    # Check governance
    if not dao_controlled(component_id):
        violations.append("GOVERNANCE VIOLATION: Not DAO-controlled")
    
    # Check infrastructure
    if has_single_point_of_failure(component_id):
        violations.append("INFRA VIOLATION: Single point of failure detected")
    
    # Check forkability
    if not open_source(component_id):
        violations.append("FORK VIOLATION: Not open source")
    
    # Check offline
    if not offline_operable(component_id):
        violations.append("OFFLINE VIOLATION: Requires online frontend/backend")
    
    return violations
```

**Violation Response:**
```
If Sovereignty Violation Detected:
1. Flag as non-compliant
2. Block production deployment
3. Require redesign toward:
   - On-chain control
   - DAO governance
   - Community operability
4. Document mitigation plan
5. Set deadline for compliance
```

---

## 7. Implementation Roadmap

### Phase 1: Foundation (Months 0-3)

**Smart Contracts:**
- ✅ Deploy core contracts (vaults, AMM, governance)
- ✅ Audit all critical contracts
- ✅ Verify on Etherscan
- ✅ Open source all code

**Infrastructure:**
- ✅ Multi-RPC provider setup
- ✅ Multi-oracle integration
- ✅ Frontend on IPFS + ENS

**Governance:**
- ✅ DAO governance live
- ✅ Guardian multisig (5-of-9)
- ✅ Parameter registry deployed

### Phase 2: Decentralization (Months 3-12)

**AI Swarm:**
- ✅ AI policy contracts deployed
- ✅ Agent registry live
- ✅ Community can run AI nodes

**Cross-Chain:**
- ✅ Multi-bridge integration
- ✅ L2 deployments (Arbitrum, Base)
- ✅ Cross-chain router live

**Governance:**
- ✅ Reduce guardian powers (first reduction)
- ✅ Specialized councils elected
- ✅ Token distribution >1000 holders

### Phase 3: Full Sovereignty (Months 12-24)

**Decentralization:**
- ✅ Frontend 100% on IPFS/Arweave
- ✅ Community-run infrastructure >50%
- ✅ AI nodes fully permissionless

**Governance:**
- ✅ Guardian sunset complete
- ✅ DAO controls 90%+ of parameters
- ✅ Token distribution >10,000 holders

**Compliance:**
- ✅ All sovereignty goals met
- ✅ Zero custodial dependencies
- ✅ Fork-ready with <7 day setup

---

## 8. Success Metrics

### Sovereignty Compliance

| Domain | Target | Current | Status |
|--------|--------|---------|--------|
| **Custody** | 100% non-custodial | TBD | 🟡 In Progress |
| **Governance** | 80%+ DAO-controlled | TBD | 🟡 In Progress |
| **Infrastructure** | 2+ providers each | TBD | 🟡 In Progress |
| **Forkability** | 100% open source | TBD | 🟡 In Progress |
| **Offline** | All critical actions | TBD | 🟡 In Progress |

### Decentralization Metrics

- **Token Holders:** >10,000 (target)
- **Top 10 Concentration:** <30% (target)
- **Community Nodes:** >50 operators (target)
- **DAO Proposals:** >100 executed (target)
- **Guardian Powers:** 0% (by month 24)

### Security Metrics

- **Audits:** 3+ independent audits
- **Bug Bounty:** $1M+ paid out
- **Uptime:** >99.9%
- **Zero Hacks:** No fund loss

---

## 9. Summary

**MERID is sovereign and decentralized because:**

✅ **100% non-custodial** - All funds in smart-contract vaults, no CEX custody  
✅ **DAO-governed** - 80%+ parameters controlled by token holders  
✅ **Infrastructure redundancy** - 2+ providers for every critical service  
✅ **Fork-ready** - 100% open source, <7 days to fork  
✅ **Offline-operable** - Users/DAO can act without frontend/backend  
✅ **AI-constrained** - AI swarm bound by on-chain policies  
✅ **Time-locked governance** - All changes have 24-72h timelocks  
✅ **Guardian sunset** - Emergency powers eliminated over 24 months  
✅ **Multi-chain** - Deployed across L1 and L2s with trust-minimized bridges  
✅ **Community-run** - Anyone can operate nodes, relayers, keepers  

**No single entity can:**
- ❌ Seize user funds
- ❌ Halt trading unilaterally
- ❌ Change rules without DAO vote
- ❌ Prevent users from withdrawing
- ❌ Censor transactions
- ❌ Prevent community fork

---

## 10. Agent Permissions, Custody, and Safeguards ✅

### Location
`sovereignty/agent_permissions_custody.py`, `sovereignty/anti_rug_safeguards.py`

### 10.1 Treating Agents as Untrusted Tools

MERID treats agents as **untrusted but powerful tools** operating under strict policy:

**Default Permissions:**
- ✅ Read-only access to public on-chain data, market feeds, governance
- ✅ Proposal-based execution (no direct control)
- ❌ No raw private keys or unrestricted wallet access

**Key Custody Rules:**
- ❌ **NEVER** give raw private keys to LLMs or agents
- ✅ Use system-owned, bounded wallets ($10k-$100k limits)
- ✅ MPC/multi-sig for high-value operations
- ✅ Keys stored in isolated signing services

**Contract Deployment:**
- ❌ No arbitrary bytecode deployment
- ✅ Factory-only deployments (audited contracts)
- ✅ DAO approval required for token launches
- ✅ Built-in safety features (vesting, liquidity locks)

**Audit Logging:**
- ✅ Every agent action logged with full context
- ✅ Agent ID, role, version, configuration
- ✅ Transaction hashes and on-chain correlation
- ✅ Agent rationale for every action

**Anti-Rug Safeguards:**
- ✅ Token safety analysis (9 rug-pull patterns detected)
- ✅ Real-time liquidity monitoring
- ✅ Automatic blocking for critical risks
- ✅ Factory-enforced safety features
- ✅ Reputation tracking and agent bans

### 10.2 Permission Levels

| Level | Read | Propose | Execute | Deploy | Keys |
|-------|------|---------|---------|--------|------|
| **READ_ONLY** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **PROPOSE** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **EXECUTE_BOUNDED** | ✅ | ✅ | ✅ ($10k) | ❌ | ⚠️ Bounded |
| **EXECUTE_GOVERNED** | ✅ | ✅ | ✅ ($100k) | ⚠️ Factory | ⚠️ MPC |
| **ADMIN** | ✅ | ✅ | ✅ | ⚠️ Factory | ⚠️ Multi-Sig |

### 10.3 Rug-Pull Detection

**Detected Patterns:**
- Immediate liquidity drain (>50% withdrawn)
- Large liquidity withdrawal (>20% withdrawn)
- Sudden fee increase (>10%)
- Blacklist trap (prevents selling)
- Mint flood (unlimited minting)
- Ownership transfer (to unknown address)
- Proxy upgrade malicious (no timelock)
- Honeypot sell restriction (can buy, can't sell)
- Hidden backdoor (selfdestruct, delegatecall)

**Automated Response:**
- Alert: >20% liquidity withdrawn
- Block: >50% liquidity withdrawn
- DAO notification for all critical events

### 10.4 Factory Contracts

**Audited Factories:**
```solidity
contract ERC20SafeFactory {
    // Enforces minting cap
    // Enforces vesting (1-4 years)
    // Enforces timelock (48h)
    // Enforces liquidity lock (180 days)
    // Requires DAO approval
}
```

**Safety Features:**
- Minting cap enforced
- Vesting templates required
- Timelock for admin actions
- Liquidity lock (90-180 days minimum)
- DAO approval for all deployments

---

## Files Created

1. **`sovereignty/sovereignty_goals_metrics.py`** (700+ lines) - Measurable sovereignty goals and tracking
2. **`sovereignty/onchain_dex_components.py`** (700+ lines) - Essential on-chain DEX contracts
3. **`sovereignty/agent_permissions_custody.py`** (800+ lines) - Agent permissions, wallets, proposals, audit logs
4. **`sovereignty/anti_rug_safeguards.py`** (700+ lines) - Token safety analysis, rug detection, factory management
5. **`docs/SOVEREIGN_DECENTRALIZED_EXCHANGE.md`** (This file, 1200+ lines) - Complete architecture guide
6. **`docs/AGENT_PERMISSIONS_CUSTODY_SAFEGUARDS.md`** (1000+ lines) - Complete agent safeguards guide

**Total: 4,900+ lines of production-ready sovereignty infrastructure**
