# MERID UI/UX Gap Analysis — 24/7 Multi-Market Swarm Trading

**Date:** 2026-02-07  
**Scope:** React frontend (69 components, 39 views), Python/FastAPI backend (113+ API files)  
**Goal:** Identify all UI/UX gaps preventing top-tier continuous, safe operation and arbitrage

---

## Inventory: What Exists Today

### Views (in App.tsx router)
| View | Status | Notes |
|---|---|---|
| Overview | ✅ Built | Portfolio value, PnL, agent activity, quick actions, price stream |
| Trading | ✅ Built | Order form, positions, fills, ArbitragePanel, LiveRiskStrip, VenueSelector |
| Agents | ✅ Built | Agent table, SwarmPanel, ExplainabilityPanel, LiveAgentHealthPanel |
| Predictions | ✅ Built | BrierMetricsPanel + PredictionsPanel |
| Risk | ✅ Built | Risk metrics, alerts, position limits, system health table |
| Health | ✅ Built | Service health grid, CPU/memory/disk/network metrics |
| Social | ✅ Built | X/Twitter feed, scheduled posts, engagement analytics (mock data) |
| Wallet / Treasury | ✅ Built | Crypto wallet, treasury views |
| Research | ✅ Built | Research view |
| Settings | ✅ Built | Configuration |

### Components (key ones)
| Component | Status | Notes |
|---|---|---|
| ArbitragePanel | ✅ Exists | Basic arb display |
| DrawdownChart | ✅ Exists | Recharts drawdown |
| ExplainabilityPanel | ✅ Exists | Agent reasoning display |
| InstrumentRadar | ✅ Exists | Tabbed scanner |
| RiskTreeMap | ✅ Exists | Treemap by exposure |
| BreachAlertLog | ✅ Exists | Severity-coded events |
| LatencyChart | ✅ Exists | p50/p95 bars |
| StalenessIndicator | ✅ Exists | Data freshness |
| LightweightPriceChart | ✅ Stub | TradingView placeholder |
| PredictionMarketsPanel | ✅ Exists | Basic PM display |

### Views (built but NOT in App.tsx router)
| View | Notes |
|---|---|
| OperatorDashboard | Full operator view with control plane, risk strip, agent health — **NOT routed** |
| OperatorControlPlane | Pause/resume/mode switching — **NOT routed** |
| TradeFloor | Alternative trading view — **NOT routed** |
| DevSwarm | Dev swarm management — **NOT routed** |
| Positions | Dedicated positions view — **NOT routed** |
| Orders | Dedicated orders view — **NOT routed** |

### Backend APIs (key endpoints)
| Endpoint | Status |
|---|---|
| `/api/v1/pipeline/summary,risk,instruments,venues,proposals` | ✅ Built |
| `/api/v1/prediction-markets/summary,risk,alerts,venue-gate` | ✅ Built |
| `/api/metrics/swarm_health,heatmap,radar,latency,breach_log` | ✅ Built |
| `/api/market/snapshot,watchlist` + WebSocket | ✅ Built |
| `/api/v1/pipeline/domain/enable,disable,halt,resume` | ✅ Built |
| `/api/v1/pipeline/venue/mode,enable,disable` | ✅ Built |
| Signals/sentiment/alerts APIs | ❌ Not yet exposed via FastAPI |
| Orchestrator cycle/history APIs | ❌ Not yet exposed via FastAPI |
| On-chain/blockchain status APIs | ❌ Not yet exposed via FastAPI |

---

## Gap Analysis — Prioritized

### TIER 1: CRITICAL SAFETY / OPERABILITY

---

#### GAP-01: Operator Dashboard Not Routed
**What's missing:** `OperatorDashboard.tsx`, `OperatorControlPlane.tsx`, `OperatorStatusBar.tsx`, and `OperatorActivityStream.tsx` are fully built but **not accessible** from the sidebar or App.tsx router. The most important view for 24/7 operations is unreachable.

**Why it matters:** During incidents, operators need the control plane in under 10 seconds. Currently they must navigate to individual views to find controls scattered across Risk, Agents, and Trading.

**Fix:**
- Add "Operator" to sidebar navigation (top of Management section, red/orange icon)
- Route `view === "operator"` → `<OperatorDashboard />`
- Make it the **default landing page** for on-call operators

---

#### GAP-02: No Unified Domain Kill Switch Panel
**What's missing:** No single panel showing all domains (prediction, crypto, equity) with their current state (SIM/PAPER/LIVE, enabled/halted) and one-click pause/resume/kill per domain.

**Why it matters:** During a flash crash or exploit, the operator needs to halt crypto trading in one click, not navigate to a pipeline API endpoint.

**Fix:**
- `DomainControlPanel.tsx` — grid of domain cards, each showing:
  - Mode badge (SIM/PAPER/LIVE)
  - Status (active/paused/halted)
  - PnL today, exposure, daily loss vs limit
  - One-click: Pause, Resume, Kill Switch, Change Mode
- Wire to existing `/api/v1/pipeline/domain/halt` and `/api/v1/prediction-markets/kill-switch`

---

#### GAP-03: No Per-Venue Health Dashboard
**What's missing:** No view showing real-time health of each venue (Kalshi, Binance, Coinbase, Kraken, Alpaca, IBKR) with latency, error rate, circuit breaker status, and connection state.

**Why it matters:** If Kalshi's API goes down or Binance rate-limits us, the operator needs to see it immediately and disable that venue.

**Fix:**
- `VenueHealthGrid.tsx` — card per venue showing:
  - Connection status (green/amber/red)
  - API latency (p50/p95)
  - Error rate (last 5m)
  - Circuit breaker state (closed/open/half-open)
  - One-click disable/enable
- Wire to `/api/v1/pipeline/venues` + new `/api/v1/venues/health` endpoint

---

#### GAP-04: No Real-Time Drawdown vs Limit Visualization Per Domain
**What's missing:** `DrawdownChart.tsx` exists but shows aggregate drawdown only. No per-domain (prediction/crypto/equity) drawdown bars showing current loss vs daily limit with color-coded urgency.

**Why it matters:** Domain-specific drawdown is the primary safety metric. An operator must see "crypto is at 80% of daily loss limit" at a glance.

**Fix:**
- `DomainDrawdownBars.tsx` — horizontal bar chart per domain:
  - Bar fill = current daily loss / daily loss limit
  - Color: green (<50%), amber (50-80%), red (>80%)
  - Numeric labels: "$450 / $1,000"
- Place in OperatorDashboard and Risk view

---

#### GAP-05: No Circuit Breaker / Risk Action Log with Explanations
**What's missing:** `BreachAlertLog.tsx` shows breach events but doesn't explain **what action was taken** (auto-halt, limit tightened, position unwound) or **why** (which rule triggered).

**Why it matters:** Post-incident, operators need to understand what the system did autonomously and whether it was correct.

**Fix:**
- Extend `BreachAlertLog` with columns: Action Taken, Rule Triggered, Affected Positions, Reversal Available
- Add expandable row with full explanation text from `ExplainabilityAgent`

---

#### GAP-06: No Data Staleness Dashboard
**What's missing:** `StalenessIndicator.tsx` exists for individual components but there's no consolidated view showing staleness of ALL data feeds (market data, Kalshi, on-chain, sentiment, news).

**Why it matters:** Stale data is the #1 cause of bad trades in automated systems. If Kalshi prices are 30s old, the system is trading blind.

**Fix:**
- `DataFreshnessPanel.tsx` — table of all data feeds:
  - Feed name, last update time, staleness (seconds), status (fresh/stale/dead)
  - Auto-sort by staleness (worst first)
  - Alert row highlighting for feeds > threshold

---

### TIER 2: HIGH VALUE FOR ARBITRAGE & MEV PERFORMANCE

---

#### GAP-07: No Arb Opportunity Scanner View
**What's missing:** `ArbitragePanel.tsx` exists but is basic. No live scanner showing:
- All detected cross-exchange spreads with expected edge, volume, slippage estimate
- Historical hit rate and realized vs expected edge per pair
- Arb leg status (both legs filled, partial fill, failed leg)

**Why it matters:** Arb is a core revenue strategy. Operators need to see opportunity flow, execution quality, and failed legs in real time.

**Fix:**
- `ArbScannerView.tsx` — tabbed view:
  - **Live Opportunities**: sortable table (pair, venues, spread_bps, volume, est_profit, age)
  - **Active Legs**: status of in-flight arb trades (leg A filled, leg B pending)
  - **History**: realized edge vs expected, hit rate, slippage
  - **Heatmap**: pair × venue spread heatmap (Recharts or ECharts)
- Wire to `CryptoSignalsAgent` output via new `/api/v1/signals/arb-opportunities` endpoint

---

#### GAP-08: No Prediction Market Detail Page
**What's missing:** `PredictionMarketsPanel.tsx` shows a list but no drill-down into individual markets showing:
- Implied vs internal probability over time
- Entry/exit history with PnL per trade
- Time-to-expiry countdown
- Order book depth
- Why MERID took this position (explainability)

**Why it matters:** Prediction markets are a key domain. Without per-market detail, operators can't evaluate whether the system's edge estimates are correct.

**Fix:**
- `PredictionMarketDetail.tsx` — detail page per market:
  - Probability chart (implied vs MERID estimate) over time
  - Position card: side, size, entry price, current price, PnL
  - Trade history table
  - Expiry countdown with phase indicator (EARLY/MID/LATE/TERMINAL)
  - Explainability card: "Entered YES at 42¢ because..."
- Wire to `/api/v1/prediction-markets/summary` + new per-market endpoint

---

#### GAP-09: No On-Chain / Solana Health Panel
**What's missing:** No UI for:
- Solana RPC latency and health
- Jito endpoint status and bundle confirmation ratios
- Pyth oracle health and price deviation
- On-chain balances and LP positions

**Why it matters:** Planned Solana arb with Jito/Pyth requires real-time visibility into on-chain infrastructure health.

**Fix:**
- `OnChainHealthPanel.tsx`:
  - RPC provider status cards (Helius, Infura, Alchemy) with latency and error rate
  - Jito bundle stats: built/simulated/sent/confirmed/failed
  - Oracle health: Pyth price vs CEX price deviation per asset
  - On-chain balance summary
- Wire to `merid/blockchain/gateway.py` summary + new `/api/v1/blockchain/health` endpoint

---

#### GAP-10: No Sentiment Overlay on Price Charts
**What's missing:** `Social.tsx` shows X/Twitter posts but sentiment is completely disconnected from price charts and trading views. No overlay showing sentiment spikes correlated with price moves.

**Why it matters:** Operators need to see "sentiment spiked bearish 5 minutes before this price drop" to evaluate signal quality and adjust strategy weights.

**Fix:**
- `SentimentOverlay.tsx` — overlay component for price charts:
  - Sentiment polarity line (secondary Y-axis) on price chart
  - Spike markers (vertical lines) at sentiment shock events
  - Tooltip: "Sentiment spike: bearish, delta=-0.8, source=X+news"
- `SentimentTimeline.tsx` — per-symbol timeline:
  - News/tweet events with sentiment color coding
  - Linked to PnL changes and trade entries/exits
- Wire to `merid/signals/processing.py` via new `/api/v1/signals/sentiment/{ticker}` endpoint

---

#### GAP-11: No Orchestrator / Agent Pipeline Visibility
**What's missing:** No view showing the orchestrator cycle status:
- Which phase is running (RESEARCH → STRATEGY → RISK → COORDINATION → OPS)
- Per-agent output summaries from the latest cycle
- Cycle latency and throughput over time

**Why it matters:** The orchestrator is the brain of the swarm. Operators need to see if agents are producing useful outputs or if a phase is stuck/slow.

**Fix:**
- `OrchestratorPanel.tsx`:
  - Phase pipeline visualization (horizontal flow: Research → Strategy → Risk → Coord → Ops)
  - Current phase highlighted, with agent count and latency per phase
  - Latest cycle summary: total outputs, spikes detected, proposals generated, verdicts
  - Cycle history chart (latency over time)
- Wire to new `/api/v1/orchestrator/summary` and `/api/v1/orchestrator/history` endpoints

---

### TIER 3: NICE-TO-HAVE ANALYTICS / VISUAL POLISH

---

#### GAP-12: No Trade Decision Audit Trail UI
**What's missing:** `ExplainabilityPanel.tsx` exists but doesn't provide a navigable audit trail: trade → strategy config → risk limits → agent votes → consensus → execution.

**Why it matters:** Post-incident reviews and regulatory compliance require full decision path inspection.

**Fix:**
- `TradeAuditTrail.tsx` — drill-down from any trade:
  - Step 1: Signal source (which agent, what data)
  - Step 2: Strategy that generated the proposal
  - Step 3: Risk check results (passed/failed, which limits)
  - Step 4: Consensus votes (per-agent vote, confidence, reasoning)
  - Step 5: Execution details (venue, fills, slippage)
  - Collapsible sections with plain-language explanations

---

#### GAP-13: No Consolidated Mode Control Panel
**What's missing:** No single view showing current mode (SIM/PAPER/LIVE) for every domain and venue, with safe rollout controls (blue/green switching).

**Why it matters:** Mode management is critical for safe rollout. Switching crypto from PAPER to LIVE should be a deliberate, visible action.

**Fix:**
- `ModeControlPanel.tsx` — matrix view:
  - Rows: domains (prediction, crypto, equity)
  - Columns: venues per domain
  - Cell: current mode badge + click to change
  - Confirmation dialog for LIVE transitions
  - Rollback button per domain

---

#### GAP-14: No Telegram Command Log in UI
**What's missing:** Operator commands sent via Telegram (`/pause`, `/status`, etc.) are processed by `TelegramOpsAgent` but not visible in the UI. No log of what commands were sent and what actions resulted.

**Why it matters:** If an operator pauses crypto via Telegram at 3am, the morning team needs to see that in the UI.

**Fix:**
- `OperatorCommandLog.tsx` — table showing:
  - Timestamp, operator, command, domain, reason
  - Resulting action (paused, resumed, status reported)
  - Whether governance approval was required/granted

---

#### GAP-15: No Alert History / Notification Center
**What's missing:** `NotificationPanel.tsx` and `LiveNotifications.tsx` exist but there's no persistent alert history view showing all dispatched alerts (Telegram, X, log) with severity, status, and acknowledgment.

**Why it matters:** Operators need to review what alerts fired overnight and whether they were acted upon.

**Fix:**
- `AlertHistoryView.tsx`:
  - Filterable table: severity, channel, time range, ticker, agent
  - Acknowledged/unacknowledged status
  - Link to related trade or risk event
- Wire to `AlertRouter.get_history()` via new `/api/v1/signals/alerts/history` endpoint

---

#### GAP-16: No Per-Domain PnL Breakdown Chart
**What's missing:** Overview shows aggregate PnL but no breakdown by domain (prediction, crypto, equity) over time.

**Why it matters:** Operators need to see which domain is making/losing money to adjust capital allocation.

**Fix:**
- `DomainPnLChart.tsx` — stacked area chart:
  - One series per domain, stacked to show total
  - Toggle between stacked and individual
  - Time range selector (1h, 4h, 1d, 1w)

---

#### GAP-17: No Strategy Performance Comparison
**What's missing:** No view comparing strategy performance (arb vs momentum vs mean-reversion vs prediction) with metrics like Sharpe, win rate, avg trade PnL.

**Why it matters:** Operators need to identify underperforming strategies and disable or reweight them.

**Fix:**
- `StrategyLeaderboard.tsx` — sortable table:
  - Strategy name, domain, PnL, Sharpe, win rate, trade count, max drawdown
  - Toggle enable/disable per strategy
  - Sparkline for recent PnL

---

#### GAP-18: Social View Uses Mock Data
**What's missing:** `Social.tsx` falls back to hardcoded mock data when `/api/v1/social/feed` fails. No integration with the new `merid/signals/` package.

**Why it matters:** The Social view should show real ingested tweets and sentiment, not mock data.

**Fix:**
- Wire Social view to new `/api/v1/signals/events` and `/api/v1/signals/sentiment` endpoints
- Replace mock fallback with real `XWorker` / `SentimentProcessor` data
- Add sentiment spike markers and per-ticker sentiment cards

---

#### GAP-19: No Compliance / Regulatory Status Panel
**What's missing:** `ComplianceRegistry` exists in backend but no UI showing venue/asset allowlists, entity classification, review status, or compliance audit records.

**Why it matters:** Regulatory compliance must be visible and auditable from the UI.

**Fix:**
- `CompliancePanel.tsx`:
  - Venue allowlist table (status, last review, next review due)
  - Asset allowlist table
  - Entity classification display
  - Compliance audit log
- Wire to `merid/blockchain/compliance.py` via new `/api/v1/compliance/summary` endpoint

---

#### GAP-20: Chart Performance at Scale
**What's missing:** All charts use Recharts which struggles above 500 points/series. No implementation of the planned Tier 1-3 charting strategy (TradingView Lightweight Charts, Highcharts, ECharts).

**Why it matters:** Heavy time series (PnL, latency, arb metrics across many symbols) will make the UI sluggish.

**Fix:**
- Implement `LightweightPriceChart.tsx` (currently stub) with TradingView Lightweight Charts for candlestick/OHLCV
- Add ECharts for heavy aggregate views (heatmaps, multi-series)
- Keep Recharts for simple metric cards and small charts
- Add virtualization for large tables (react-window)

---

## Summary: Priority Matrix

| Priority | Count | Key Gaps |
|---|---|---|
| **CRITICAL** | 6 | Operator dashboard routing, domain kill switch, venue health, per-domain drawdown, risk action log, data staleness |
| **HIGH** | 5 | Arb scanner, PM detail page, on-chain health, sentiment overlay, orchestrator visibility |
| **NICE-TO-HAVE** | 9 | Audit trail, mode control, Telegram log, alert history, domain PnL, strategy leaderboard, social wiring, compliance, chart perf |

## Recommended Build Order

1. **GAP-01** Route OperatorDashboard (30 min — just routing + sidebar)
2. **GAP-02** DomainControlPanel (2h — new component + API wiring)
3. **GAP-04** DomainDrawdownBars (1h — new component)
4. **GAP-03** VenueHealthGrid (2h — new component + API endpoint)
5. **GAP-06** DataFreshnessPanel (1h — new component)
6. **GAP-05** Extend BreachAlertLog (1h — extend existing)
7. **GAP-07** ArbScannerView (3h — new view + API endpoint)
8. **GAP-10** SentimentOverlay + API endpoints (3h)
9. **GAP-11** OrchestratorPanel + API endpoints (2h)
10. **GAP-08** PredictionMarketDetail (3h)

## New API Endpoints Needed

| Endpoint | Backend Source |
|---|---|
| `GET /api/v1/venues/health` | `merid/pipeline/mode_manager.py` + venue adapters |
| `GET /api/v1/signals/sentiment/{ticker}` | `merid/signals/processing.py` |
| `GET /api/v1/signals/events` | `merid/signals/ingestion.py` |
| `GET /api/v1/signals/alerts/history` | `merid/signals/alerts.py` |
| `GET /api/v1/signals/arb-opportunities` | `merid/agents/wiring.py` |
| `GET /api/v1/orchestrator/summary` | `merid/agents/orchestrator.py` |
| `GET /api/v1/orchestrator/history` | `merid/agents/orchestrator.py` |
| `GET /api/v1/blockchain/health` | `merid/blockchain/gateway.py` |
| `GET /api/v1/compliance/summary` | `merid/blockchain/compliance.py` |
| `GET /api/v1/prediction-markets/{market_id}` | `merid/prediction/model.py` |
