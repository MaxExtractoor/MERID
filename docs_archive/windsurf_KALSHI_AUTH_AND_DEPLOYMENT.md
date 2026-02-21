# Kalshi Authentication & Production Deployment Guide
**WebSocket Auth Patterns, Risk Management, and Production Checklist**

---

## 1. Kalshi WebSocket Authentication Pitfalls (TypeScript)

Kalshi uses **header-based RSA-PSS signing** with the same pattern as REST API authentication.

### Common TypeScript Authentication Mistakes

#### Pitfall 1: Wrong Pre-Hash String

**Problem:** Incorrect string format for signature generation

```typescript
// WRONG - Missing method or using query string
const msg = timestamp + "/trade-api/ws/v2";  // Missing "GET"
const msg = timestamp + "GET" + "/trade-api/ws/v2?foo=bar";  // No query string!

// CORRECT - Method + path only (no query string)
const msg = timestamp + "GET" + "/trade-api/ws/v2";
```

**Key:** Use `timestamp + "GET" + "/trade-api/ws/v2"` exactly as documented.

---

#### Pitfall 2: Timestamp Units (Milliseconds vs Seconds)

**Problem:** Using seconds instead of milliseconds

```typescript
// WRONG - Seconds (Unix timestamp)
const timestamp = Math.floor(Date.now() / 1000).toString();  // 1676505600

// CORRECT - Milliseconds
const timestamp = Date.now().toString();  // 1676505600000
```

**Key:** Kalshi expects **milliseconds** for `KALSHI-ACCESS-TIMESTAMP`.

---

#### Pitfall 3: Broken RSA-PSS Implementation

**Problem:** Wrong padding or using public key instead of private

```typescript
// WRONG - Using wrong padding
import crypto from "crypto";

function signWrong(privateKey: crypto.KeyObject, text: string): string {
  const signature = crypto.sign("sha256", Buffer.from(text), privateKey);
  // Missing PSS padding specification!
  return signature.toString("base64");
}

// CORRECT - RSA-PSS with SHA-256
function signCorrect(privateKey: crypto.KeyObject, text: string): string {
  const signature = crypto.sign(
    "sha256",
    Buffer.from(text),
    {
      key: privateKey,
      padding: crypto.constants.RSA_PKCS1_PSS_PADDING,
      saltLength: crypto.constants.RSA_PSS_SALTLEN_DIGEST,
    }
  );
  return signature.toString("base64");
}
```

**Key:** Must use `RSA_PKCS1_PSS_PADDING` with `RSA_PSS_SALTLEN_DIGEST` (SHA-256 digest length).

---

#### Pitfall 4: Headers Not Sent in WS Handshake

**Problem:** WebSocket library doesn't support custom headers (browsers), or headers passed incorrectly

```typescript
// WRONG - Browser WebSocket API doesn't support custom headers
const ws = new WebSocket("wss://api.kalshi.com/...");
ws.setRequestHeader("KALSHI-ACCESS-KEY", keyId);  // Doesn't exist!

// WRONG - Headers in wrong place
const ws = new WebSocket(url, headers);  // Second param is protocols, not headers

// CORRECT - Use Node.js 'ws' library with additional_headers
import WebSocket from "ws";

const headers = createAuthHeaders(privateKey, keyId);
const ws = new WebSocket(url, { headers });  // Node.js only!
```

**Key:** Custom headers only work in **Node.js backends**. Browser WebSocket API doesn't support custom headers.

---

#### Pitfall 5: Clock Skew

**Problem:** Server rejects requests due to timestamp drift

```typescript
// Detection
function checkClockSkew(): void {
  const localTime = Date.now();
  fetch("https://worldtimeapi.org/api/timezone/Etc/UTC")
    .then(r => r.json())
    .then(data => {
      const serverTime = data.unixtime * 1000;
      const skew = Math.abs(localTime - serverTime);
      if (skew > 5000) {  // > 5 seconds
        console.warn(`Clock skew detected: ${skew}ms`);
      }
    });
}

// Mitigation: NTP sync or time offset adjustment
let timeOffset = 0;

async function calibrateTime(): Promise<void> {
  const localTime = Date.now();
  const response = await fetch("https://worldtimeapi.org/api/timezone/Etc/UTC");
  const data = await response.json();
  const serverTime = data.unixtime * 1000;
  timeOffset = serverTime - localTime;
  console.log(`Time offset calibrated: ${timeOffset}ms`);
}

function getTimestamp(): string {
  return (Date.now() + timeOffset).toString();
}
```

**Key:** Monitor clock skew, use NTP, or calculate offset from reliable time source.

---

### Recommended Pattern: Keep Auth in Python

**Best Practice:** Keep all Kalshi auth in Python, expose normalized events via internal WebSocket bridge

```typescript
// TS agents connect to internal bridge (no Kalshi auth needed)
const wsClient = new SwarmWsClient({
  url: "ws://localhost:8001/swarm-bridge",  // Internal bridge
  // No auth headers - secured via internal network/API key
});

// Python bridge handles all Kalshi auth + WS connection
// TS agents consume normalized events without auth complexity
```

**Benefits:**
- Single auth implementation (Python only)
- TS agents simplified (no crypto dependencies)
- Easier testing (mock internal bridge vs mocking Kalshi auth)
- Better security (private keys stay in Python service)

---

## 2. Risk Management Agent Patterns for Prediction Markets

### Pattern 1: Hard Limit Risk Agent

**Purpose:** Enforce deterministic position and loss limits

```typescript
// packages/agents/src/riskAgent.ts
import { EventBus, EventEnvelope, OrderIntent } from "@merid/swarm-kernel";

interface RiskDecision {
  intent_id: string;
  approved: boolean;
  adjusted_qty?: number;
  rejection_reason?: string;
  risk_score: number;
}

interface RiskLimits {
  maxContractsPerMarket: number;
  maxNotionalPerMarket: number;
  maxAssetExposure: number;      // All BTC markets combined
  maxTotalNotional: number;       // Venue-wide
  maxDailyLoss: number;
  maxLeverage: number;
}

interface PositionState {
  positions: Map<string, number>;  // market_ticker -> contracts
  dailyPnL: number;
  lastResetTime: number;
}

export class HardLimitRiskAgent {
  private state: PositionState = {
    positions: new Map(),
    dailyPnL: 0,
    lastResetTime: Date.now(),
  };

  constructor(
    private bus: EventBus,
    private limits: RiskLimits
  ) {}

  async start(): Promise<void> {
    await this.bus.subscribe<OrderIntent>(
      "intents.orders",
      (evt) => this.assessIntent(evt)
    );
    
    await this.bus.subscribe<Fill>(
      "kalshi.fills",
      (evt) => this.updatePosition(evt)
    );
  }

  private async assessIntent(evt: EventEnvelope<OrderIntent>): Promise<void> {
    const intent = evt.data;
    const decision = this.evaluateRisk(intent);
    
    await this.bus.publish("risk.decisions", decision);
  }

  private evaluateRisk(intent: OrderIntent): RiskDecision {
    // Check 1: Per-market position limit
    const currentPosition = this.state.positions.get(intent.market_ticker) ?? 0;
    const proposedPosition = currentPosition + intent.qty;
    
    if (Math.abs(proposedPosition) > this.limits.maxContractsPerMarket) {
      return {
        intent_id: intent.client_tag,
        approved: false,
        rejection_reason: "market_position_limit",
        risk_score: 1.0,
      };
    }

    // Check 2: Per-asset exposure (e.g., all BTC markets)
    const asset = this.extractAsset(intent.market_ticker);
    const assetExposure = this.getAssetExposure(asset);
    const proposedAssetExposure = assetExposure + intent.qty;
    
    if (Math.abs(proposedAssetExposure) > this.limits.maxAssetExposure) {
      return {
        intent_id: intent.client_tag,
        approved: false,
        rejection_reason: "asset_exposure_limit",
        risk_score: 0.9,
      };
    }

    // Check 3: Total notional limit
    const totalNotional = this.getTotalNotional();
    const intentNotional = intent.qty * intent.price;
    
    if (totalNotional + intentNotional > this.limits.maxTotalNotional) {
      return {
        intent_id: intent.client_tag,
        approved: false,
        rejection_reason: "total_notional_limit",
        risk_score: 0.95,
      };
    }

    // Check 4: Daily loss limit
    this.checkAndResetDailyPnL();
    if (this.state.dailyPnL < -this.limits.maxDailyLoss) {
      return {
        intent_id: intent.client_tag,
        approved: false,
        rejection_reason: "daily_loss_limit",
        risk_score: 1.0,
      };
    }

    // All checks passed
    return {
      intent_id: intent.client_tag,
      approved: true,
      adjusted_qty: intent.qty,
      risk_score: this.computeRiskScore(intent),
    };
  }

  private extractAsset(market_ticker: string): string {
    // Extract asset from ticker (e.g., "BTC-15m-UP" -> "BTC")
    return market_ticker.split("-")[0];
  }

  private getAssetExposure(asset: string): number {
    let exposure = 0;
    for (const [ticker, position] of this.state.positions) {
      if (ticker.startsWith(asset)) {
        exposure += position;
      }
    }
    return exposure;
  }

  private getTotalNotional(): number {
    // Simplified - in production, multiply by current market prices
    let notional = 0;
    for (const position of this.state.positions.values()) {
      notional += Math.abs(position) * 50;  // Assume avg price of 50 cents
    }
    return notional;
  }

  private checkAndResetDailyPnL(): void {
    const now = Date.now();
    const dayInMs = 24 * 60 * 60 * 1000;
    
    if (now - this.state.lastResetTime > dayInMs) {
      this.state.dailyPnL = 0;
      this.state.lastResetTime = now;
    }
  }

  private computeRiskScore(intent: OrderIntent): number {
    // Compute 0-1 risk score based on multiple factors
    const positionRisk = Math.abs(intent.qty) / this.limits.maxContractsPerMarket;
    const notionalRisk = (intent.qty * intent.price) / this.limits.maxTotalNotional;
    return Math.max(positionRisk, notionalRisk);
  }

  private async updatePosition(evt: EventEnvelope<Fill>): Promise<void> {
    const fill = evt.data;
    const currentPosition = this.state.positions.get(fill.market_ticker) ?? 0;
    const delta = fill.side.includes("buy") ? fill.qty : -fill.qty;
    this.state.positions.set(fill.market_ticker, currentPosition + delta);
    
    // Update PnL (simplified)
    const pnl = delta * (fill.price - 50);  // Assume entry at 50
    this.state.dailyPnL += pnl;
  }
}
```

---

### Pattern 2: Calibration / Brier-Aware Risk Agent

**Purpose:** Scale position sizes based on agent forecasting accuracy

```typescript
// packages/agents/src/calibrationRiskAgent.ts
interface AgentStats {
  agent_id: string;
  predictions: number;
  brierScore: number;
  winRate: number;
  avgDrawdown: number;
  lastCalibrationCheck: number;
}

export class CalibrationRiskAgent {
  private agentStats: Map<string, AgentStats> = new Map();

  constructor(private bus: EventBus) {}

  async start(): Promise<void> {
    await this.bus.subscribe<OrderIntent>(
      "intents.orders",
      (evt) => this.annotateWithCalibration(evt)
    );
    
    await this.bus.subscribe<Outcome>(
      "market.outcomes",
      (evt) => this.updateCalibration(evt)
    );
  }

  private async annotateWithCalibration(
    evt: EventEnvelope<OrderIntent>
  ): Promise<void> {
    const intent = evt.data;
    const stats = this.agentStats.get(intent.agent_id);
    
    if (!stats || stats.predictions < 10) {
      // New/unproven agent - scale down
      intent.qty = Math.floor(intent.qty * 0.25);
      intent.rationale = `${intent.rationale} [calibration=unproven]`;
    } else {
      // Adjust size based on Brier score (lower is better)
      const calibrationFactor = this.computeCalibrationFactor(stats.brierScore);
      intent.qty = Math.floor(intent.qty * calibrationFactor);
      intent.rationale = `${intent.rationale} [calibration=${calibrationFactor.toFixed(2)}]`;
    }
    
    // Forward adjusted intent
    await this.bus.publish("intents.orders.calibrated", intent);
  }

  private computeCalibrationFactor(brierScore: number): number {
    // Brier score: 0 = perfect, 1 = worst
    // Good: < 0.15, Acceptable: 0.15-0.25, Poor: > 0.25
    if (brierScore < 0.15) return 1.0;
    if (brierScore < 0.25) return 0.5;
    return 0.25;  // Poor calibration - minimal size
  }

  private async updateCalibration(evt: EventEnvelope<Outcome>): Promise<void> {
    const outcome = evt.data;
    const stats = this.agentStats.get(outcome.agent_id);
    
    if (!stats) return;
    
    // Update Brier score: sum of (forecast - outcome)^2 / N
    const error = (outcome.forecast - outcome.realized) ** 2;
    stats.brierScore = (stats.brierScore * stats.predictions + error) / (stats.predictions + 1);
    stats.predictions++;
    
    // Update win rate
    const won = (outcome.forecast > 0.5 && outcome.realized === 1) ||
                (outcome.forecast < 0.5 && outcome.realized === 0);
    stats.winRate = (stats.winRate * (stats.predictions - 1) + (won ? 1 : 0)) / stats.predictions;
  }
}
```

**Key:** Poorly calibrated agents get size reductions even if their signals look good.

---

### Pattern 3: Stress-Testing Agent

**Purpose:** Run synthetic scenarios to validate strategy survival

```typescript
// packages/agents/src/stressTestAgent.ts
interface StressScenario {
  name: string;
  volatilityShock: number;    // Multiply spreads by this factor
  liquidityDrop: number;      // Reduce depth by this %
  wsDisconnectProbability: number;
}

const SCENARIOS: StressScenario[] = [
  { name: "vol_spike", volatilityShock: 3.0, liquidityDrop: 0.5, wsDisconnectProbability: 0.1 },
  { name: "liquidity_crisis", volatilityShock: 1.5, liquidityDrop: 0.8, wsDisconnectProbability: 0.05 },
  { name: "network_issues", volatilityShock: 1.0, liquidityDrop: 0.0, wsDisconnectProbability: 0.5 },
];

export class StressTestAgent {
  async runStressTest(strategy: TradingStrategy, scenario: StressScenario): Promise<StressResult> {
    const historicalEvents = await this.loadHistoricalEvents();
    const syntheticEvents = this.applyScenario(historicalEvents, scenario);
    
    // Replay through strategy
    const results = await this.replayEvents(strategy, syntheticEvents);
    
    return {
      scenario: scenario.name,
      maxDrawdown: results.maxDrawdown,
      finalPnL: results.finalPnL,
      worstCase: results.worstCase,
      survived: results.finalPnL > -1000,  // Define survival threshold
    };
  }

  private applyScenario(events: Event[], scenario: StressScenario): Event[] {
    return events.map(evt => {
      if (evt.type === "orderbook") {
        // Apply volatility shock
        evt.data.spread *= scenario.volatilityShock;
        
        // Apply liquidity drop
        evt.data.bids.forEach(([p, size], i) => {
          evt.data.bids[i][1] = size * (1 - scenario.liquidityDrop);
        });
        evt.data.asks.forEach(([p, size], i) => {
          evt.data.asks[i][1] = size * (1 - scenario.liquidityDrop);
        });
      }
      
      if (evt.type === "ws_status" && Math.random() < scenario.wsDisconnectProbability) {
        evt.data.connected = false;
      }
      
      return evt;
    });
  }
}
```

**Key:** Validate strategies survive extreme conditions before going live.

---

## 3. Production Deployment Checklist for Swarm Trading Agents

### Phase 1: Pre-Deployment (Staging/Paper)

#### Kalshi API Integration
- [ ] All REST/WS calls tested against `demo-api.kalshi.co`
- [ ] RSA-PSS auth headers correct (timestamp in ms, correct pre-hash string)
- [ ] Private key loaded securely (env var or secrets manager, not hardcoded)
- [ ] Clock skew < 5 seconds (use NTP or time offset calibration)
- [ ] WebSocket reconnect logic tested (disconnect, wait, reconnect with backoff)
- [ ] Rate limit guards configured for current tier (reads/writes per second)
- [ ] 429 handling: log, backoff with jitter, metrics
- [ ] API error codes mapped: 401 (auth fail), 403 (forbidden), 429 (rate limit), 5xx (server error)

#### Swarm Architecture
- [ ] All agents emit `OrderIntent` events only (no direct Kalshi calls)
- [ ] Single execution pipeline owns order placement
- [ ] Single risk engine enforces limits (per-market, per-asset, per-venue, daily loss)
- [ ] Global rate limiter shared across all components
- [ ] Event bus topics documented with schemas
- [ ] Message schema versioning implemented (`schema_version` field)

#### Paper Mode Validation
- [ ] Paper trading account on Kalshi demo environment
- [ ] PnL and positions reconcile 1:1 with Kalshi account (daily check)
- [ ] Run for **minimum 7 days** without manual intervention
- [ ] Zero ghost orders or position discrepancies
- [ ] Zero unhandled exceptions or crashes

---

### Phase 2: Swarm Behavior & Reliability

#### Event-Driven Testing
- [ ] Adversarial test: Out-of-order WS messages (seq number violations)
- [ ] Adversarial test: WS disconnect during active session (verify no ghost orders)
- [ ] Adversarial test: API timeout with retry (verify idempotency via `client_order_id`)
- [ ] Adversarial test: Duplicate intent detection (same `client_tag` sent twice)
- [ ] Adversarial test: Rate limit exhaustion (verify graceful degradation)
- [ ] Adversarial test: Fill-then-price vs price-then-fill ordering (verify correct execution price)

#### Orchestration Patterns
- [ ] Sequential orchestrator tested with 3+ agents
- [ ] Auction orchestrator: verify only winner's intent executed
- [ ] Critic-Trader loop: verify max iterations respected
- [ ] Backpressure handling: what happens when consumer falls behind?
- [ ] Confirm no unbounded loops or infinite retries

#### Monitoring & Observability
- [ ] WS connection status dashboard (connected, reconnects, errors)
- [ ] Rate limit usage dashboard (% of read/write budget used)
- [ ] Risk rejection dashboard (by reason: market_limit, daily_loss, etc.)
- [ ] PnL and exposure dashboard (per-market, per-asset, total)
- [ ] Agent activity dashboard (intents generated, approvals, rejections)

---

### Phase 3: Risk & Compliance

#### Hard Limits Configuration
- [ ] Per-market limits: max contracts, max notional, max % of open interest
- [ ] Per-asset limits: cap exposure across all markets for same underlying
- [ ] Per-venue limits: max total notional, max leverage
- [ ] Daily loss limit: circuit breaker when hit
- [ ] Separate configs for: `paper`, `staging_live`, `production_live`
- [ ] Environment-based enforcement (can't accidentally use prod limits in paper)

#### Audit & Explainability
- [ ] Every order intent logged with: `session_id`, `agent_id`, `market_ticker`, `qty`, `price`, `rationale`
- [ ] Every risk decision logged with: `intent_id`, `approved`, `rejection_reason`, `risk_score`
- [ ] Every execution outcome logged with: `order_id`, `status`, `timestamp`
- [ ] Kalshi fill confirmations stored with immutable IDs
- [ ] Audit log retention: minimum 90 days for compliance
- [ ] Replay capability: reconstruct any session from event log

#### Kill Switch
- [ ] Manual kill switch: disable all live trading immediately
- [ ] Automatic kill switch: triggered by daily loss threshold
- [ ] Partial kill switch: disable specific agents or markets
- [ ] Kill switch preserves data ingest and paper sims (read-only mode)
- [ ] Kill switch tested in staging (verify no orders placed after activation)

---

### Phase 4: Observability & Runbooks

#### Dashboards
- [ ] **WS Health:** Latency, reconnects, error rates, last message time
- [ ] **API Health:** 4xx/5xx rates, timeout rates, success rate by endpoint
- [ ] **Rate Limits:** Read/write budget usage, 429 count, queue depth
- [ ] **Risk:** Rejections by reason, positions vs limits, daily PnL vs limit
- [ ] **Execution:** Order acceptance rate, fill rate, avg fill time, slippage
- [ ] **Agent Activity:** Intents per agent, win rate, Brier score, calibration factor

#### Alerts
- [ ] **Critical:** WS disconnected for > 2 minutes
- [ ] **Critical:** No fills for > 30 minutes (during active trading hours)
- [ ] **Critical:** Daily loss threshold breached (50%, 75%, 100%)
- [ ] **Warning:** Rate limit usage > 80% of tier limit
- [ ] **Warning:** Risk rejection rate > 30% of intents
- [ ] **Warning:** Position limit within 10% of cap

#### Runbooks
- [ ] **Key Rotation:** How to rotate Kalshi API keys without downtime
- [ ] **Auth Failure:** Diagnose 401 errors (clock skew, wrong key, signature mismatch)
- [ ] **Rate Limit Exceeded:** Identify noisy component, throttle, upgrade tier
- [ ] **Emergency Stop:** Kill switch activation procedure, team notification
- [ ] **Tier Upgrade:** Process to move from Basic → Premier → Prime
- [ ] **Agent Misbehavior:** How to disable specific agent, analyze logs, rollback deployment

---

### Phase 5: Gradual Rollout

#### Restricted Market Set
- [ ] Start with **2-3 liquid markets** (e.g., BTC-15m, ETH-15m)
- [ ] Verify stable PnL and no operational issues for **7 days**
- [ ] Expand to **5-10 markets** for next **7 days**
- [ ] Full market set only after **30 days** stable operation

#### Progressive Limits
- [ ] Start with 25% of intended per-market caps
- [ ] Increase to 50% after 7 days if no issues
- [ ] Increase to 75% after 14 days
- [ ] Full caps after 30 days

#### Shadow Swarm
- [ ] Run parallel paper swarm mirroring live decisions
- [ ] Compare live vs shadow PnL, win rate, drawdown
- [ ] Shadow swarm can test experimental agents/strategies safely
- [ ] Shadow swarm provides rollback target if live performance degrades

---

## 4. Kalshi Tier Requirements & Rate Limits

### Tier Comparison

| Tier     | Monthly Volume | Read/s | Write/s | Cost         | Requirements                     |
|----------|----------------|--------|---------|--------------|----------------------------------|
| Basic    | < 3.75%        | 20     | 10      | Free         | Email verification               |
| Advanced | None           | 30     | 30      | $500/mo      | Payment method                   |
| Premier  | > 3.75%        | 100    | 100     | Volume-based | Monitoring + security practices  |
| Prime    | > 7.5%         | 400    | 400     | Volume-based | Advanced monitoring + compliance |

**Key:**
- Volume % = Your volume / Total Kalshi volume for that month
- Premier/Prime require: Rate-limit self-throttling, security best practices, monitoring, incident response
- Use **WebSocket for all streaming data** (orderbooks, trades, fills) to conserve REST quota

---

## 5. Next Steps: Risk-Aware Trader Agent Template

**Coming Next:** Complete TypeScript agent that:
- Consumes `signals.market_features`
- Applies built-in sizing rules (Kelly criterion, position limits)
- Emits `OrderIntent` with confidence and rationale
- Includes JSON schemas for Python ↔ TypeScript interop

**Plus:** Mock execution pipeline for end-to-end testing without Kalshi.

---

**Last Updated:** 2026-02-16  
**Status:** Production deployment patterns documented  
**Reference:** TYPESCRIPT_SWARM_IMPLEMENTATION.md, KALSHI_SWARM_SAFETY_GUIDE.md
