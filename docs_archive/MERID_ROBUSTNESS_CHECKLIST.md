# MERID Legacy, Data Ingestion, LLM Swarm & UI Robustness Checklist (Stay on Mission)

> **Mission**: Keep MERID true to its original plan — an event-driven, multi-asset, multi-agent swarm with strong risk governance — and avoid "rewriting the whole thing from scratch". Treat legacy infra as an asset to wrap and extend, not discard.

---

## 1. Legacy Integrations & Adapters

### Exchange & Broker Wrappers
- [ ] **[Medium/Legacy]** Audit all exchange adapters (Kraken, OKX, Bitfinex, Bybit, HTX, Binance US, Gemini, Coinbase, IBKR) and document which are production-ready vs. stubs
- [ ] **[Medium/Legacy]** Wrap each exchange adapter behind a stable `VenueAdapter` interface that exposes only normalized methods (`get_balance`, `place_order`, `cancel_order`, `get_positions`)
- [ ] **[Easy/Legacy]** Document rate-limit configurations per venue and ensure all adapters use shared rate-limiter middleware
- [ ] **[Medium/Legacy]** Implement US-geo compliance checks in adapter layer (block non-US-compliant venues for production, allow for paper/sim only)
- [ ] **[Hard/Legacy]** Add circuit-breaker pattern to each adapter: after N consecutive failures, mark venue as degraded and emit `venue.status.degraded` event
- [ ] **[Easy/Legacy]** Create adapter versioning scheme (v1, v2) so old adapters can be deprecated without breaking existing flows
- [ ] **[Medium/Legacy]** Ensure all adapters emit standardized `trade.executed.*`, `order.placed.*`, `order.cancelled.*` events to Kafka

### CCXT & Third-Party Library Management
- [ ] **[Easy/Legacy]** Pin CCXT and all exchange SDK versions in requirements.txt with explicit upgrade policy
- [ ] **[Medium/Legacy]** Create thin wrapper around CCXT that catches library-specific exceptions and converts to MERID-standard error types
- [ ] **[Easy/Legacy]** Document which CCXT features MERID actually uses vs. which are unused baggage

### Deprecation Tracking
- [ ] **[Easy/Legacy]** Create `DEPRECATED_ADAPTERS.md` listing adapters scheduled for removal with target dates
- [ ] **[Medium/Legacy]** Add runtime warnings when deprecated adapters are instantiated, logged to `adapter.deprecation.*` topic
- [ ] **[Easy/Legacy]** Mark legacy field names in adapter responses with `_legacy_` prefix to flag them for eventual removal

---

## 2. Legacy Data Pipeline & State (Kafka/Flink/DB/S3/Neo4j)

### Kafka Topic Schema Governance
- [ ] **[Hard/Both]** Define canonical MERID event schemas for all topic families: `prices.*`, `orderbook.*`, `trades.*`, `agent.opinions.*`, `consensus.*`, `risk.*`, `alerts.*`
- [ ] **[Medium/Legacy]** Register all schemas in a schema registry (Confluent or Redpanda Schema Registry) with compatibility mode = BACKWARD
- [ ] **[Medium/Legacy]** Add schema validation sidecar/interceptor that rejects malformed messages to dead-letter queue (`dlq.*`)
- [ ] **[Easy/Legacy]** Document topic naming convention: `{domain}.{entity}.{action}` (e.g., `trades.executed.spot`)

### Event Normalization Layer
- [ ] **[Hard/Legacy]** Create `EventNormalizer` service that transforms legacy/vendor-specific payloads into canonical schemas before publishing
- [ ] **[Medium/Legacy]** Ensure no raw exchange-specific field names leak into topics LLM agents consume (e.g., no `ccxt_order_id`, only `order_id`)
- [ ] **[Medium/Legacy]** Add `schema_version` field to all events for forward compatibility

### Exactly-Once & Idempotency
- [ ] **[Hard/Legacy]** Audit Flink jobs for exactly-once semantics: verify checkpointing is enabled and sinks are idempotent
- [ ] **[Medium/Legacy]** Add `event_id` (UUID) and `idempotency_key` to all events; consumers must deduplicate
- [ ] **[Medium/Legacy]** Implement at-least-once with dedup pattern for services that can't guarantee exactly-once

### Backpressure & Replay
- [ ] **[Medium/Legacy]** Configure Kafka consumer lag alerting: emit `pipeline.lag.warning` when lag exceeds threshold
- [ ] **[Hard/Legacy]** Build replay tool that can re-emit events from S3/archive for a given time range to reproduce LLM decisions during incidents
- [ ] **[Medium/Legacy]** Document replay procedure in `RUNBOOK_REPLAY.md` with step-by-step instructions

### State Management
- [ ] **[Medium/Legacy]** Audit all stateful Flink jobs and document state size, TTL, and recovery behavior
- [ ] **[Easy/Legacy]** Ensure all derived state (aggregations, features) can be rebuilt from raw event log
- [ ] **[Medium/Legacy]** Add Neo4j write-through cache for relationship queries (agent-to-position, position-to-venue) with TTL

### S3 Archival
- [ ] **[Easy/Legacy]** Verify all Kafka topics have S3 sink configured with partitioned storage (by date/hour)
- [ ] **[Medium/Legacy]** Implement lifecycle policy: raw events → compressed after 7 days → Glacier after 90 days
- [ ] **[Easy/Legacy]** Add integrity checks (checksums) on archived data

---

## 3. Legacy UI/UX & Observability (React, Metrics, Logs)

### Dashboard Stability
- [ ] **[Easy/Legacy]** Audit all React components for proper error boundaries; no single widget crash should take down the dashboard
- [ ] **[Medium/Legacy]** Ensure all WebSocket connections have reconnect logic with exponential backoff (already partially implemented in `useKafkaStream`)
- [ ] **[Easy/Legacy]** Add loading/error states to every data-fetching component; no silent failures

### Metrics & Monitoring
- [ ] **[Medium/Legacy]** Verify Prometheus exporters exist for: Flink job metrics, Kafka consumer lag, API latency, error rates
- [ ] **[Easy/Legacy]** Create Grafana dashboard with key SLIs: p50/p99 latency, error rate, message throughput, agent heartbeat status
- [ ] **[Medium/Legacy]** Add alert rules for: consumer lag > 10k, error rate > 1%, agent heartbeat missing > 60s

### Logging
- [ ] **[Easy/Legacy]** Ensure structured JSON logging across all Python services with consistent fields: `timestamp`, `level`, `service`, `trace_id`
- [ ] **[Medium/Legacy]** Add correlation IDs that flow from API request → Kafka message → Flink job → DB write
- [ ] **[Easy/Legacy]** Implement log level control via environment variable without restart

### Wrapper Pattern for UI
- [ ] **[Medium/Both]** All new UI widgets must consume only WebSocket/REST views over existing topics; no direct external API calls from frontend
- [ ] **[Easy/Legacy]** Document which Kafka topics each dashboard card depends on in a `UI_TOPIC_MAP.md`

---

## 4. LLM Agent Design (Roles, Prompts, Tools)

### Agent Role Definitions
- [ ] **[Medium/LLM]** Define explicit agent roster with narrow roles: `BullAgent`, `BearAgent`, `RiskAgent`, `ExecutionAgent`, `GovernanceAgent`, `SentimentAgent`
- [ ] **[Medium/LLM]** Each agent must have documented: purpose, allowed inputs (topics), allowed outputs (schemas), allowed tools
- [ ] **[Hard/LLM]** Create `AgentManifest` schema that declares agent capabilities, constraints, and dependencies

### System Prompt Engineering
- [ ] **[Hard/LLM]** Each agent's system prompt must include: role constitution, output contract, fallback behavior, escalation rules
- [ ] **[Medium/LLM]** Add "emergent behavior safeguards" to prompts: explicit prohibition on self-modification, spawning new agents, or expanding scope
- [ ] **[Medium/LLM]** Include exponential-growth constraints: "You may not increase position sizes, agent counts, or risk limits beyond initial parameters"
- [ ] **[Easy/LLM]** Version all system prompts with semantic versioning; changes require review

### Tool Binding
- [ ] **[Hard/LLM]** Implement tool registry that maps tool names to wrapped legacy services (e.g., `get_price` → PriceService → Kafka topic)
- [ ] **[Medium/LLM]** Each tool must have: input schema, output schema, timeout, retry policy, rate limit
- [ ] **[Medium/LLM]** LLM agents can ONLY call tools; no raw HTTP/DB/file access from agent code
- [ ] **[Easy/LLM]** Log all tool invocations to `agent.tool_calls.*` topic for audit

### Inter-Agent Communication
- [ ] **[Hard/LLM]** Define secure inter-agent message schema with sender verification and payload signing
- [ ] **[Medium/LLM]** Agents communicate only via Kafka topics (`agent.messages.*`), never direct function calls
- [ ] **[Medium/LLM]** Implement message TTL: inter-agent messages expire after N seconds to prevent stale decisions

---

## 5. LLM Output Contracts & Validation

### Schema Enforcement
- [ ] **[Hard/LLM]** Define JSON schemas for all agent outputs: `AgentOpinion`, `RiskDecision`, `TradePlan`, `ConsensusVote`, `AlertPayload`
- [ ] **[Hard/LLM]** Implement `OutputValidator` service that validates every LLM response against its declared schema
- [ ] **[Medium/LLM]** Non-conforming outputs are rejected and logged to `agent.validation_failures.*`; agent enters safe-mode

### No Free-Text Execution
- [ ] **[Critical/LLM]** **NEVER** pass free-text LLM output directly to execution layer; all execution commands must be structured and validated
- [ ] **[Medium/LLM]** Implement "blast radius" limits: even valid TradePlan cannot exceed per-trade/per-day limits
- [ ] **[Easy/LLM]** Add `confidence` field to all agent outputs; low-confidence outputs trigger human review

### Parsing Fallbacks
- [ ] **[Medium/LLM]** If LLM returns unparseable output, retry once with explicit "respond only in JSON" instruction
- [ ] **[Medium/LLM]** After retry failure, emit `agent.parse_failure.*` event and use safe default (no-op or reduce exposure)
- [ ] **[Easy/LLM]** Track parse failure rate per agent; alert if > 5% of responses fail parsing

### Output Logging
- [ ] **[Easy/LLM]** Log all raw LLM responses (before validation) to immutable audit log for replay/debugging
- [ ] **[Medium/LLM]** Redact any accidentally-included sensitive data before logging (regex patterns for keys, passwords)

---

## 6. Swarm Coordination & Failure Modes

### TACo-Style Consensus
- [ ] **[Hard/LLM]** Implement consensus engine with configurable quorum (e.g., 3/5 agents must agree)
- [ ] **[Medium/LLM]** Define tie-breaker rules: RiskAgent veto overrides, GovernanceAgent has final say on blocked actions
- [ ] **[Medium/LLM]** Add timeout handling: if quorum not reached within N seconds, emit `consensus.timeout.*` and use safe default
- [ ] **[Easy/LLM]** Log all consensus rounds to `consensus.rounds.*` with individual votes and final decision

### Disagreement Handling
- [ ] **[Medium/LLM]** When agents disagree beyond threshold, escalate to human review via `alerts.human_review.*`
- [ ] **[Medium/LLM]** Implement "confidence-weighted voting": high-confidence votes count more
- [ ] **[Easy/LLM]** Track historical agreement rates between agent pairs for drift detection

### Failure Modes
- [ ] **[Hard/LLM]** Define agent failure states: `healthy`, `degraded`, `offline`, `safe-mode`
- [ ] **[Medium/LLM]** Implement heartbeat system: each agent emits heartbeat every N seconds to `agent.heartbeats.*`
- [ ] **[Medium/LLM]** If agent misses M consecutive heartbeats, mark as offline and redistribute its responsibilities
- [ ] **[Medium/LLM]** Safe-mode behavior: agent can only vote "no action" until manually restored

### Graceful Degradation
- [ ] **[Medium/LLM]** System must function (conservatively) with only RiskAgent and ExecutionAgent alive
- [ ] **[Easy/LLM]** Document minimum viable swarm configuration in `MIN_SWARM_CONFIG.md`
- [ ] **[Medium/LLM]** Implement "limp mode": if < quorum agents available, only allow position reduction, no new entries

---

## 7. Safety, Risk, and Governance

### Global Risk Limits (Smart Contract Stubs)
- [ ] **[Hard/Both]** Define `RiskLimits` configuration: max position per symbol, max total exposure, max leverage, max daily loss
- [ ] **[Hard/Both]** Implement `RiskGuard` service that validates all TradePlans against limits BEFORE execution
- [ ] **[Medium/Both]** Limits are stored in versioned config (not code); changes require dual approval and emit `governance.limit_change.*`

### Tradable Universe
- [ ] **[Medium/Both]** Maintain allowlist of tradable symbols per venue; LLMs cannot propose trades outside this list
- [ ] **[Easy/Both]** Add/remove symbols via governance process, not ad-hoc code changes
- [ ] **[Easy/Both]** Log all universe changes to `governance.universe_change.*`

### Permission Model
- [ ] **[Hard/Both]** Define agent permission tiers: `read-only`, `propose`, `execute-small`, `execute-full`
- [ ] **[Medium/Both]** No agent ever has direct signing power; all trades go through `ExecutionService` which holds keys
- [ ] **[Critical/Both]** Keys/secrets stored in vault (HashiCorp Vault or AWS Secrets Manager); agents access via token with TTL

### Kill Switch
- [ ] **[Medium/Both]** Implement global kill switch: single command halts all trading and moves to cash
- [ ] **[Easy/Both]** Kill switch accessible via: API, Telegram command (privileged user), dashboard button
- [ ] **[Easy/Both]** Kill switch activation emits `governance.kill_switch.*` and requires manual reset

### Human Override
- [ ] **[Medium/Both]** Implement manual override workflow: human can approve/reject pending TradePlans via dashboard or Telegram
- [ ] **[Easy/Both]** Time-boxed auto-approval: if no human response in N minutes, use safe default (no action)

---

## 8. Testing, Replay, and Drift Monitoring

### Legacy Testing
- [ ] **[Medium/Legacy]** Achieve 80%+ unit test coverage on all adapter wrappers and normalization logic
- [ ] **[Medium/Legacy]** Add integration tests that verify end-to-end flow: mock exchange → adapter → Kafka → Flink → DB
- [ ] **[Easy/Legacy]** Run tests in CI on every PR; block merge on failure

### LLM Testing
- [ ] **[Hard/LLM]** Create "golden response" test suite: known inputs → expected structured outputs
- [ ] **[Medium/LLM]** Add "adversarial prompt" tests: verify agents reject attempts to override their constitution
- [ ] **[Medium/LLM]** Implement output schema compliance tests for every agent type

### Replay Testing
- [ ] **[Hard/Both]** Build replay harness that feeds historical events to LLM agents and compares decisions to recorded decisions
- [ ] **[Medium/Both]** Flag decision drift: if replayed agent makes different decision than production, alert for review
- [ ] **[Easy/Both]** Run replay tests weekly on last 7 days of data

### Drift Monitoring
- [ ] **[Medium/LLM]** Track agent output distribution over time; alert if significantly different from baseline
- [ ] **[Medium/LLM]** Monitor confidence score distributions; alert if mean confidence drops
- [ ] **[Easy/LLM]** Track tool call frequency per agent; alert on unusual patterns

### Chaos Testing
- [ ] **[Hard/Both]** Implement chaos tests: randomly kill agents, delay messages, inject invalid data
- [ ] **[Medium/Both]** Verify system degrades gracefully and recovers automatically
- [ ] **[Easy/Both]** Document expected behavior under each failure mode

---

## 9. Privacy, Secrets, and Compliance

### Secrets Management
- [ ] **[Medium/Both]** All API keys, signing keys, and credentials stored in vault; never in code or environment files
- [ ] **[Medium/Both]** Implement automatic key rotation with configurable interval (default: 90 days)
- [ ] **[Easy/Both]** Audit secret access: log all vault reads to `security.secret_access.*`

### Telemetry Redaction
- [ ] **[Medium/Both]** Redact PII and sensitive data from all logs before shipping to log aggregator
- [ ] **[Medium/Both]** Telemetry used for training/fine-tuning must pass data minimization review
- [ ] **[Easy/Both]** Define "safe to log" vs "redact" field lists per event type

### Agent RBAC
- [ ] **[Hard/LLM]** Implement per-agent role-based access control: each agent token has explicit scope
- [ ] **[Medium/LLM]** Agents cannot access other agents' internal state or private tools
- [ ] **[Easy/LLM]** Log all permission-denied attempts to `security.access_denied.*`

### Compliance Checks
- [ ] **[Medium/Both]** US-only trading enforced at adapter layer; non-US venues blocked for live trading
- [ ] **[Easy/Both]** Add compliance audit log: all trades, position changes, and limit modifications
- [ ] **[Medium/Both]** Implement trade reporting hooks for regulatory requirements (future-proofing)

---

## 10. Data Ingestion Across Markets, Assets, and Signals

### Market Data (Prices, Orderbook, Trades)
- [ ] **[Medium/Legacy]** Verify all venues emit to canonical topics: `prices.spot.*`, `prices.perps.*`, `orderbook.l2.*`, `trades.executed.*`
- [ ] **[Medium/Legacy]** Normalize all price feeds to MERID schema: `{symbol, venue, price, size, timestamp, source}`
- [ ] **[Easy/Legacy]** Add FX feeds for fiat conversion; normalize to `prices.fx.*`
- [ ] **[Medium/Legacy]** Reuse existing Flink aggregation jobs; only add new operators, not new pipelines

### Social & Sentiment Ingestion
- [ ] **[Hard/Both]** Integrate sentiment API (StockGeist, Santiment, or similar) as upstream source → `social.sentiment.*` topic
- [ ] **[Medium/Both]** Define canonical sentiment schema: `{symbol, source, sentiment_score, volume, timestamp}`
- [ ] **[Medium/Both]** Add fallback web scraper (Apify-style) for sources without APIs; scraper writes to same topic
- [ ] **[Easy/Both]** LLMs never scrape directly; all data comes from normalized topics

### News Ingestion
- [ ] **[Medium/Both]** Integrate financial news API (Finage or similar) → `news.headlines.*` topic
- [ ] **[Medium/Both]** Normalize news schema: `{headline, source, symbols, sentiment_score, timestamp, url}`
- [ ] **[Easy/Both]** Map headlines to symbols using existing symbol normalization service
- [ ] **[Easy/Both]** Deduplicate headlines by content hash

### On-Chain Data
- [ ] **[Hard/Both]** Add whale transaction feed → `onchain.whale_tx.*` topic
- [ ] **[Medium/Both]** Add DeFi TVL/flow feeds → `onchain.defi.*` topic
- [ ] **[Medium/Both]** Normalize on-chain schema: `{chain, address_type, amount_usd, tx_hash, timestamp}`

### Web Scraping Guardrails
- [ ] **[Medium/Both]** All scrapers run as isolated services with dedicated rate limits
- [ ] **[Easy/Both]** Scrapers write to Kafka; no direct DB writes
- [ ] **[Easy/Both]** Add dead-letter queue for failed scraper outputs
- [ ] **[Easy/Both]** Document scraper SLAs (update frequency, expected latency)

### Don't Reinvent Checks
- [ ] **[Easy/Both]** Every new ingestion source must document which existing Flink job/topic it reuses
- [ ] **[Medium/Both]** New sources that don't fit existing schemas require schema evolution review
- [ ] **[Easy/Both]** Prefer adding Flink operators to existing jobs over creating new pipelines

---

## 11. Telegram and X/Twitter Bots as First-Class Tools

### Telegram Bot
- [ ] **[Medium/Both]** Implement thin Telegram bot service that consumes `alerts.*`, `consensus.*`, `agent.opinions.*` topics
- [ ] **[Medium/Both]** Bot posts human-readable summaries (not raw JSON) to configured channels
- [ ] **[Medium/Both]** Accept structured commands (slash commands) that become `telegram.commands.*` events
- [ ] **[Easy/Both]** Commands: `/status`, `/risk`, `/pause`, `/resume`, `/kill` (privileged)

### X/Twitter Bot
- [ ] **[Medium/Both]** Implement X bot that posts selected swarm decisions and market summaries
- [ ] **[Medium/Both]** Optionally consume X sentiment feed as input → `social.twitter.*` topic
- [ ] **[Easy/Both]** Rate-limit posts to avoid spam; configurable cooldown between tweets
- [ ] **[Easy/Both]** Commands via DM map to `twitter.commands.*` events

### Safety & Abuse Controls
- [ ] **[Medium/Both]** Implement RBAC for bot commands: only whitelisted user IDs can execute privileged commands
- [ ] **[Easy/Both]** Add cooldowns: no user can send > N commands per minute
- [ ] **[Easy/Both]** Log all bot interactions to `bots.activity.*` topic
- [ ] **[Medium/Both]** Implement "bot mute" command that silences output without stopping system

### Output Formatting
- [ ] **[Easy/Both]** No raw internal schemas exposed to bot users; all output is human-formatted
- [ ] **[Easy/Both]** Sensitive data (balances, keys) never included in bot messages
- [ ] **[Easy/Both]** Error messages are user-friendly, not stack traces

---

## 12. UI, Graphs, Charts, and Heatmaps

### Time-Series Charts
- [ ] **[Medium/Legacy]** Add price + PnL time-series chart consuming `prices.*` and `portfolio.pnl.*` topics via WebSocket
- [ ] **[Medium/Both]** Add sentiment overlay on price chart using `social.sentiment.*` topic
- [ ] **[Medium/Both]** Add regime indicator (bull/bear/sideways) derived from existing feature jobs
- [ ] **[Easy/Legacy]** Add volatility band overlay from `features.volatility.*` topic

### Agent/Swarm Views
- [ ] **[Hard/Both]** Real-time agent opinion chart: per-symbol bar/line showing Bull/Bear/Risk scores from `agent.opinions.*`
- [ ] **[Medium/Both]** Consensus timeline chart: show when consensus reached, which side, confidence from `consensus.*`
- [ ] **[Easy/Legacy]** Agent status panel: mode (online/degraded/offline), last heartbeat, Sharpe, drawdown

### Heatmaps
- [ ] **[Hard/Both]** Market heatmap: symbols × time showing returns colored by magnitude
- [ ] **[Medium/Both]** Risk exposure heatmap: instruments × risk buckets (delta, leverage, venue concentration)
- [ ] **[Medium/Both]** Agent contribution heatmap: which agents contributing PnL/risk per symbol

### Order Book & Microstructure
- [ ] **[Medium/Legacy]** Lightweight depth chart (bid/ask stacks) from `orderbook.l2.*` feeds
- [ ] **[Medium/Legacy]** Trade tape/flow histogram from `trades.executed.*` topics

### Alerting & Anomaly Markers
- [ ] **[Easy/Both]** Visual markers on charts for: risk veto, kill-switch, big news spike, large sentiment move
- [ ] **[Medium/Both]** Click-to-drill-down: clicking event marker opens detail view with underlying data
- [ ] **[Easy/Both]** Configurable alert filters: show/hide by severity, type, symbol

### Bot Activity Overlay
- [ ] **[Easy/Both]** Show Telegram/X command events on charts from `telegram.commands.*`, `twitter.commands.*`
- [ ] **[Easy/Both]** Add bot control widgets: mute/unmute, throttle alerts, mapped to command topics

### Implementation Constraints
- [ ] **[Medium/Both]** All new UI widgets consume only WebSocket/REST views over Kafka-derived topics
- [ ] **[Easy/Both]** No chart directly queries external APIs; everything from MERID's normalized event store
- [ ] **[Easy/Both]** Document topics/schemas each new view depends on in `UI_TOPIC_MAP.md`
- [ ] **[Easy/Both]** Add new panels to existing dashboard; don't build separate UI apps

---

## 13. Robust Fixes & Non-Reinvention Guardrails

### Legacy-First Rule
- [ ] **[Easy/Both]** Every new feature must declare which existing MERID component it reuses (topic, job, adapter, card)
- [ ] **[Easy/Both]** Features that don't reuse anything are flagged for design review
- [ ] **[Easy/Both]** Maintain `REUSE_INVENTORY.md` documenting all reusable components

### Refactor Over Rewrite
- [ ] **[Medium/Both]** Prefer "wrap and extend" (new operator, new topic, new REST view) over parallel pipelines
- [ ] **[Easy/Both]** Before building new service, check if existing service can be extended
- [ ] **[Medium/Both]** New pipelines require justification document explaining why existing infra is insufficient

### Failure & Observability
- [ ] **[Medium/Both]** Log and monitor ingestion latency, error rates, coverage metrics for all sources
- [ ] **[Easy/Both]** Add dead-letter queues for all new API/scraper integrations
- [ ] **[Easy/Both]** Alert on: ingestion latency > 5s, error rate > 1%, coverage drop > 10%

### Incremental Delivery
- [ ] **[Easy/Both]** Each feature ships behind feature flag; can be disabled without deploy
- [ ] **[Easy/Both]** New views/widgets are additive; don't remove existing functionality
- [ ] **[Easy/Both]** Document rollback procedure for each new integration

---

## 14. Roadmap to Phase Out or Wrap Legacy Debt

### Immediate Wrapping (Month 1-2)
- [ ] **[High Priority]** Wrap all exchange adapters behind stable VenueAdapter interface
- [ ] **[High Priority]** Add schema validation to all Kafka topic producers
- [ ] **[High Priority]** Implement OutputValidator for all LLM agent outputs

### Stabilization (Month 2-3)
- [ ] **[Medium Priority]** Complete replay tooling for incident reproduction
- [ ] **[Medium Priority]** Add comprehensive integration tests for all adapters
- [ ] **[Medium Priority]** Implement consensus engine with configurable quorum

### Deprecation (Month 3-6)
- [ ] **[Low Priority]** Remove deprecated adapters listed in `DEPRECATED_ADAPTERS.md`
- [ ] **[Low Priority]** Migrate legacy field names to canonical schemas
- [ ] **[Low Priority]** Archive unused Flink jobs and topics

### Documentation
- [ ] **[Easy]** Create architecture diagram showing current state vs. target state
- [ ] **[Easy]** Document all wrapped legacy components with their stable interfaces
- [ ] **[Easy]** Maintain decision log for all "wrap vs. replace" decisions

---

## Suggested Order of Attack

### Phase 1: Stabilize Legacy as Tools (Weeks 1-3)
1. Wrap exchange adapters behind VenueAdapter interface
2. Add schema validation to all Kafka topics
3. Implement replay tooling for incident reproduction
4. Document existing Flink jobs and reusable components

### Phase 2: Lock Down LLM Contracts (Weeks 4-6)
5. Define JSON schemas for all agent outputs (AgentOpinion, TradePlan, etc.)
6. Implement OutputValidator that rejects non-conforming outputs
7. Add "no free-text execution" guardrails
8. Create golden response test suite

### Phase 3: Enhance Data Ingestion (Weeks 7-9)
9. Integrate sentiment API → `social.sentiment.*` topic
10. Integrate news API → `news.headlines.*` topic
11. Add on-chain whale detection → `onchain.whale_tx.*` topic
12. Verify all new sources use existing Flink backbone

### Phase 4: Wire Core UI Views (Weeks 10-12)
13. Add agent opinion chart consuming `agent.opinions.*`
14. Add consensus timeline from `consensus.*`
15. Add basic market heatmap (symbols × returns)
16. Add sentiment overlay on price charts

### Phase 5: Swarm Coordination & Safety (Weeks 13-16)
17. Implement TACo-style consensus with quorum/timeouts
18. Add RiskGuard service validating all TradePlans
19. Implement kill switch and human override workflow
20. Add per-agent RBAC and vault-backed secret access

### Phase 6: Bot Integration (Weeks 17-18)
21. Deploy Telegram bot consuming alerts/consensus topics
22. Add slash commands that emit `telegram.commands.*`
23. Deploy X bot for public market summaries
24. Implement RBAC and rate limiting for bot commands

### Phase 7: Expand & Mature (Weeks 19+)
25. Expand agent roster (new specialized agents)
26. Increase market coverage (more venues, more symbols)
27. Add advanced visualizations (risk heatmaps, microstructure views)
28. Continuous drift monitoring and chaos testing

---

> **Remember**: Every new feature must justify what existing MERID component it reuses. If the answer is "nothing," the design is suspect. Wrap, extend, and iterate—don't rebuild.
