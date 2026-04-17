# MERID Port Assignment Map

**Generated**: 2026-01-13  
**Purpose**: Definitive mapping of all existing features to target ports

---

## Port 3000 - User UI (Public)

### HTML Templates

- `unified_standalone.html` - Main dashboard
- `institutional.html` - Institutional control center
- `dashboard.html` - Legacy dashboard
- `simulation.html` - Simulation monitor
- `live_monitor.html` - Live intelligence monitor
- `trading_perps.html` - Perpetual trading UI
- `trading_markets.html` - Prediction markets UI
- `betting.html` - Betting system UI
- `index.html` - Legacy home

### Static Files

- `/static/*` - All CSS, JS, images

### WebSocket Endpoints

- `/ws` - Main event stream (USER EVENTS ONLY, not agent mesh)

### API Routers (User-Facing)

#### `/api/v1/dashboard` - Dashboard Data

**File**: `web/api/dashboard_data.py`

- GET `/api/v1/dashboard/overview` - Dashboard overview
- GET `/api/v1/dashboard/agents` - Agent status for UI
- GET `/api/v1/dashboard/consensus` - Recent consensus
- GET `/api/v1/dashboard/performance` - Performance metrics
- GET `/api/v1/dashboard/alerts` - System alerts

#### `/api/v1/live` - Live Data

**File**: `web/api/live_data.py`

- GET `/api/v1/live/prices` - Live crypto prices
- GET `/api/v1/live/markets` - Market data
- GET `/api/v1/live/orderbook` - Order book data

#### `/api/v1/intelligence` - Market Intelligence

**File**: `web/api/intelligence.py`

- GET `/api/v1/intelligence/news` - Aggregated news
- GET `/api/v1/intelligence/sentiment` - Market sentiment
- GET `/api/v1/intelligence/signals` - Trading signals
- GET `/api/v1/intelligence/defi` - DeFi metrics
- GET `/api/v1/intelligence/fear-greed` - Fear & Greed index
- GET `/api/v1/intelligence/trending` - Trending coins

#### `/api/v1/predictions` - Prediction Markets

**File**: `web/api/predictions.py`

- GET `/api/v1/predictions/markets` - Available markets
- GET `/api/v1/predictions/positions` - User positions
- POST `/api/v1/predictions/bet` - Place bet

#### `/api/v1/institutional` - Institutional Dashboard

**File**: `web/api/institutional.py`

- GET `/api/v1/institutional/predictions/markets` - Market list
- GET `/api/v1/institutional/predictions/market/{id}` - Market details
- GET `/api/v1/institutional/predictions/positions` - Positions
- GET `/api/v1/institutional/agents/status` - Agent status
- GET `/api/v1/institutional/consensus/recent` - Recent consensus
- GET `/api/v1/institutional/analytics/performance` - Performance
- GET `/api/v1/institutional/risk/exposure` - Risk metrics
- GET `/api/v1/institutional/execution/orders` - Order status
- GET `/api/v1/institutional/portfolio/summary` - Portfolio

#### `/api/v1/trading` - Trading Operations

**File**: `web/api/trading.py`

- GET `/api/v1/trading/markets` - Available markets
- GET `/api/v1/trading/positions` - Current positions
- POST `/api/v1/trading/order` - Place order
- GET `/api/v1/trading/orders` - Order history
- DELETE `/api/v1/trading/order/{id}` - Cancel order
- GET `/api/v1/trading/execution/status` - Execution status

#### `/api/v1/betting` - Betting System

**File**: `web/api/betting.py`

- GET `/api/v1/betting/markets` - Betting markets
- POST `/api/v1/betting/place` - Place bet
- GET `/api/v1/betting/history` - Bet history

#### `/api/v1/wallet` - Wallet Management

**File**: `web/api/wallet.py`

- GET `/api/v1/wallet/balance` - Wallet balance
- GET `/api/v1/wallet/transactions` - Transaction history
- POST `/api/v1/wallet/transfer` - Transfer funds

#### `/api/v1/notifications` - User Notifications

**File**: `web/api/notifications.py`

- GET `/api/v1/notifications` - Get notifications
- POST `/api/v1/notifications/read` - Mark as read
- GET `/api/v1/notifications/preferences` - Notification settings

#### `/api/v1/auth` - Authentication

**File**: `web/api/auth.py`

- POST `/api/v1/auth/login` - User login
- POST `/api/v1/auth/logout` - User logout
- GET `/api/v1/auth/session` - Session status

#### `/api/v1/referrals` - Referral System

**File**: `web/api/referrals.py`

- GET `/api/v1/referrals/code` - Get referral code
- POST `/api/v1/referrals/claim` - Claim referral
- GET `/api/v1/referrals/stats` - Referral statistics

#### `/api/v1/paper-trading` - Paper Trading

**File**: `web/api/paper_trading.py`

- GET `/api/v1/paper-trading/portfolio` - Paper portfolio
- POST `/api/v1/paper-trading/trade` - Paper trade
- GET `/api/v1/paper-trading/history` - Trade history

#### `/api/v1/arbitrage` - Arbitrage Opportunities

**File**: `web/api/arbitrage.py`

- GET `/api/v1/arbitrage/opportunities` - Current opportunities
- GET `/api/v1/arbitrage/history` - Arbitrage history
- GET `/api/v1/arbitrage/stats` - Arbitrage statistics

#### `/api/v1/schemas` - Data Schemas

**File**: `web/api/schemas.py`

- GET `/api/v1/schemas/energy` - Energy packet schema
- GET `/api/v1/schemas/agent` - Agent schema
- GET `/api/v1/schemas/consensus` - Consensus schema

#### `/api/v1/streams` - Data Streams

**File**: `web/api/streams.py`

- GET `/api/v1/streams/events` - Event stream
- GET `/api/v1/streams/prices` - Price stream
- GET `/api/v1/streams/consensus` - Consensus stream

#### `/api/v1/live-stream` - Live Streaming

**File**: `web/api/live_stream.py`

- GET `/api/v1/live-stream/connect` - Connect to stream
- GET `/api/v1/live-stream/status` - Stream status

#### `/api/v1/data` - Data Endpoints

**File**: `web/api/data_endpoints.py`

- GET `/api/v1/data/markets` - Market data
- GET `/api/v1/data/assets` - Asset data

#### `/api/v1/dashboard-ws` - Dashboard WebSocket

**File**: `web/api/dashboard_ws.py`

- WebSocket `/api/v1/dashboard-ws/connect` - Dashboard updates

### Core API Endpoints (from main.py)

- GET `/` - Redirect to dashboard
- GET `/dashboard` - Main dashboard
- GET `/institutional` - Institutional dashboard
- GET `/simulation` - Simulation monitor
- GET `/live` - Live monitor
- GET `/trading/perps` - Perps trading
- GET `/trading/markets` - Markets trading
- GET `/betting` - Betting UI
- POST `/submit` - Submit energy (user action)
- GET `/api/v1/health` - Health check
- GET `/api/v1/blocks` - Block stream
- GET `/api/v1/blocks/latest` - Latest block
- GET `/api/v1/blocks/{id}` - Block by ID
- GET `/api/v1/heatmap` - Heatmap data
- GET `/api/v1/ticker` - Ticker data
- GET `/api/v1/assist` - Assist data
- GET `/api/v1/hover-metadata` - Hover metadata
- GET `/api/v1/leaderboard` - Gamification leaderboard
- GET `/api/v1/charters` - Agent charters (public info)
- GET `/api/v1/charters/{role}` - Charter details

---

## Port 8080 - Agent Mesh (Localhost Only)

### Agent Communication

**File**: `agents/mesh.py`

- POST `/mesh/register` - Register agent
- POST `/mesh/unregister` - Unregister agent
- POST `/mesh/message` - Send message
- POST `/mesh/broadcast` - Broadcast message
- POST `/mesh/signal` - Send signal
- POST `/mesh/request` - Request from agent
- POST `/mesh/respond` - Respond to request
- POST `/mesh/handoff` - Task handoff
- GET `/mesh/status` - Mesh status
- GET `/mesh/agents` - List agents

### Agent Status & Control

**File**: `web/api/agents.py`

- GET `/api/v1/agents/status` - Agent status (internal)
- POST `/api/v1/agents/spawn` - Spawn agent
- POST `/api/v1/agents/kill` - Kill agent
- GET `/api/v1/agents/performance` - Agent performance
- POST `/api/v1/agents/configure` - Configure agent

### Reflection System (Agent Queries)

**File**: `web/api/reflection.py`

- GET `/api/v1/reflection/agents/{id}/stats` - Agent reflection stats
- GET `/api/v1/reflection/agents/{id}/reflections` - Agent reflections
- GET `/api/v1/reflection/reflections` - All reflections
- GET `/api/v1/reflection/summary` - Reflection summary
- POST `/api/v1/reflection/record` - Record decision (agents only)
- POST `/api/v1/reflection/validate` - Validate outcome (agents only)

### Consensus Coordination (Internal)

- POST `/mesh/consensus/vote` - Submit vote
- GET `/mesh/consensus/status` - Consensus status
- POST `/mesh/consensus/propose` - Propose decision

### Reality Registry (Agent Access)

**File**: `web/api/reality.py` (subset)

- POST `/api/v1/reality/assert` - Register assertion (agents)
- GET `/api/v1/reality/assertions/{id}` - Get assertion
- POST `/api/v1/reality/validate` - Validate assertion

### Explainability (Agent Recording)

**File**: `web/api/explainability.py` (subset)

- POST `/api/v1/explainability/record` - Record reasoning (agents)
- GET `/api/v1/explainability/agent/{id}` - Get agent reasoning

### Swarm Coordination

- GET `/api/v1/swarm/agents` - Agent population
- GET `/api/v1/swarm/lineage` - Agent lineage
- POST `/api/v1/swarm/coordinate` - Coordinate action

---

## Port 9090 - Ops/Admin (Localhost Only)

### System Control

**File**: `web/api/system_control.py`

- POST `/api/v1/system/start` - Start system
- POST `/api/v1/system/stop` - Stop system
- GET `/api/v1/system/status` - System status
- GET `/api/v1/system/agents` - All agents status
- GET `/api/v1/system/decisions/recent` - Recent decisions
- GET `/api/v1/system/consensus/history` - Consensus history
- POST `/api/v1/system/consensus/propose` - Propose consensus
- POST `/api/v1/system/agents/twitter/post` - Manual tweet
- POST `/api/v1/system/agents/telegram/send` - Manual telegram

### Operations

**File**: `web/api/ops.py`

- GET `/api/v1/ops/provenance/status` - Provenance status
- GET `/api/v1/ops/provenance/sources` - Data sources
- GET `/api/v1/ops/provenance/sources/{id}` - Source details
- GET `/api/v1/ops/provenance/low-trust` - Low trust sources
- POST `/api/v1/ops/provenance/record` - Record data
- POST `/api/v1/ops/provenance/failure` - Record failure
- GET `/api/v1/ops/entropy/status` - Entropy status
- GET `/api/v1/ops/entropy/current` - Current entropy
- GET `/api/v1/ops/entropy/consensus` - Direction consensus
- GET `/api/v1/ops/entropy/diversity` - Source diversity
- GET `/api/v1/ops/entropy/echo-chamber` - Echo chamber check
- GET `/api/v1/ops/entropy/trend` - Entropy trend
- GET `/api/v1/ops/entropy/signals` - Recent signals
- POST `/api/v1/ops/entropy/record` - Record signal
- GET `/api/v1/ops/conflicts/status` - Conflict status
- GET `/api/v1/ops/conflicts/active` - Active conflicts
- GET `/api/v1/ops/conflicts/alignment` - Domain alignment
- POST `/api/v1/ops/conflicts/detect` - Detect conflicts
- GET `/api/v1/ops/conflicts/history` - Conflict history

### Monitoring

**File**: `web/api/monitoring.py`

- GET `/api/v1/monitoring/health` - Health checks
- GET `/api/v1/monitoring/metrics` - System metrics
- GET `/api/v1/monitoring/alerts` - Active alerts
- GET `/api/v1/monitoring/logs` - System logs
- GET `/api/v1/monitoring/performance` - Performance stats

### Backup & Recovery

**File**: `web/api/backup.py`

- POST `/api/v1/backup/create` - Create backup
- GET `/api/v1/backup/list` - List backups
- POST `/api/v1/backup/restore` - Restore backup
- DELETE `/api/v1/backup/{id}` - Delete backup

**File**: `web/api/recovery.py`

- POST `/api/v1/recovery/checkpoint` - Create checkpoint
- POST `/api/v1/recovery/restore` - Restore from checkpoint
- GET `/api/v1/recovery/status` - Recovery status

### Rate Limiting

**File**: `web/api/ratelimit.py`

- GET `/api/v1/ratelimit/status` - Rate limit status
- POST `/api/v1/ratelimit/configure` - Configure limits
- GET `/api/v1/ratelimit/violations` - Limit violations

### Compliance

**File**: `web/api/compliance.py`

- GET `/api/v1/compliance/reports` - Compliance reports
- POST `/api/v1/compliance/audit` - Trigger audit
- GET `/api/v1/compliance/logs` - Audit logs
- GET `/api/v1/compliance/status` - Compliance status

### Governance

**File**: `web/api/governance.py`

- GET `/api/v1/governance/proposals` - Governance proposals
- POST `/api/v1/governance/propose` - Create proposal
- POST `/api/v1/governance/vote` - Vote on proposal
- GET `/api/v1/governance/results` - Voting results

### Treasury Management

**File**: `web/api/treasury.py`

- GET `/api/v1/treasury/balance` - Treasury balance
- GET `/api/v1/treasury/transactions` - Treasury transactions
- POST `/api/v1/treasury/transfer` - Transfer funds
- GET `/api/v1/treasury/allocations` - Fund allocations

### Archive Management

**File**: `web/api/archive.py`

- POST `/api/v1/archive/snapshot` - Create snapshot
- GET `/api/v1/archive/list` - List archives
- GET `/api/v1/archive/{id}` - Get archive
- DELETE `/api/v1/archive/{id}` - Delete archive

### Offline Mode

**File**: `web/api/offline.py`

- POST `/api/v1/offline/enable` - Enable offline mode
- POST `/api/v1/offline/disable` - Disable offline mode
- GET `/api/v1/offline/status` - Offline status
- GET `/api/v1/offline/cache` - Cached data

### Plugin Management

**File**: `web/api/plugins.py`

- GET `/api/v1/plugins/list` - List plugins
- POST `/api/v1/plugins/install` - Install plugin
- POST `/api/v1/plugins/enable` - Enable plugin
- POST `/api/v1/plugins/disable` - Disable plugin
- DELETE `/api/v1/plugins/{id}` - Uninstall plugin

### Cost Models

**File**: `web/api/cost_models.py`

- GET `/api/v1/cost-models/current` - Current cost model
- POST `/api/v1/cost-models/update` - Update cost model
- GET `/api/v1/cost-models/estimates` - Cost estimates

### Trading Mode Control

**File**: `web/api/trading_mode.py`

- GET `/api/v1/trading-mode/current` - Current mode
- POST `/api/v1/trading-mode/set` - Set trading mode
- GET `/api/v1/trading-mode/history` - Mode history

### Time Exploit Detection

**File**: `web/api/time_exploit.py`

- GET `/api/v1/time-exploit/status` - Detection status
- GET `/api/v1/time-exploit/violations` - Detected violations
- POST `/api/v1/time-exploit/configure` - Configure detection

### Sniping Detection

**File**: `web/api/sniping.py`

- GET `/api/v1/sniping/status` - Sniping detection status
- GET `/api/v1/sniping/alerts` - Sniping alerts
- POST `/api/v1/sniping/configure` - Configure detection

### Mining Control

**File**: `web/api/mining.py`

- POST `/api/v1/mine` - Trigger mining
- GET `/api/v1/mining/status` - Mining status
- POST `/api/v1/mining/configure` - Configure mining

### Prediction System (Admin)

**File**: `web/api/prediction.py`

- POST `/api/v1/prediction/create` - Create prediction
- POST `/api/v1/prediction/resolve` - Resolve prediction
- GET `/api/v1/prediction/admin` - Admin panel

### UMA Assertions (Admin)

- GET `/api/v1/assertions` - List assertions
- GET `/api/v1/assertions/{id}` - Get assertion
- POST `/api/v1/assertions/{id}/settle` - Settle assertion

### Observability (Admin)

- GET `/api/v1/observability/sources` - Source health
- GET `/api/v1/observability/agents/trust` - Agent trust
- GET `/api/v1/observability/consensus/history` - Consensus history
- GET `/api/v1/observability/hardening/status` - Hardening status
- GET `/api/v1/marl/metrics` - MARL metrics
- GET `/api/v1/pso/metrics` - PSO metrics

---

## Port 9091 - Telemetry (Localhost Only)

### Prometheus Metrics

- GET `/metrics` - Prometheus-compatible metrics
  - `merid_reflections_total`
  - `merid_validations_total`
  - `merid_agents_active`
  - `merid_consensus_rounds_total`
  - `merid_consensus_success_rate`
  - `merid_agent_decisions_total`
  - `merid_agent_accuracy`
  - `merid_reality_gap_avg`
  - `merid_api_requests_total`
  - `merid_api_latency_seconds`
  - `merid_websocket_connections`
  - `merid_energy_packets_total`
  - `merid_block_height`
  - `merid_system_uptime_seconds`

### Health Checks

- GET `/health` - Overall health
- GET `/health/agents` - Agent health
- GET `/health/consensus` - Consensus health
- GET `/health/database` - Database health
- GET `/health/external` - External API health

### Performance Stats

- GET `/stats/reflection` - Reflection system stats
- GET `/stats/agents` - Agent performance stats
- GET `/stats/consensus` - Consensus stats
- GET `/stats/mesh` - Agent mesh stats
- GET `/stats/api` - API performance stats

### Reality System Metrics

**File**: `web/api/reality.py` (telemetry subset)

- GET `/api/v1/reality/status` - Reality system status
- GET `/api/v1/reality/metrics` - Reality metrics
- GET `/api/v1/reality/assertions/stats` - Assertion statistics

### Explainability Metrics

**File**: `web/api/explainability.py` (telemetry subset)

- GET `/api/v1/explainability/stats` - Explainability stats
- GET `/api/v1/explainability/coverage` - Coverage metrics

---

## Summary

### Port Distribution

| Port | Service     | Binding   | Purpose                              | Endpoint Count |
|------|-------------|-----------|--------------------------------------|----------------|
| 3000 | User UI     | 0.0.0.0   | Public dashboard, user actions       | ~80 endpoints  |
| 8080 | Agent Mesh  | 127.0.0.1 | Agent communication, coordination    | ~25 endpoints  |
| 9090 | Ops/Admin   | 127.0.0.1 | System control, admin operations     | ~120 endpoints |
| 9091 | Telemetry   | 127.0.0.1 | Metrics, health checks, monitoring   | ~15 endpoints  |

### Migration Priority

**Week 1** (Critical):

1. Split User UI (port 3000) - Most endpoints
2. Create Agent Mesh (port 8080) - Core swarm functionality

**Week 2** (High):
3. Split Ops/Admin (port 9090) - Security isolation
4. Create Telemetry (port 9091) - Observability

### Files Requiring Updates

**New Files to Create**:

- `web/user_app.py` - Port 3000 app
- `web/agent_app.py` - Port 8080 app
- `web/ops_app.py` - Port 9090 app
- `web/metrics_app.py` - Port 9091 app
- `start_merid.py` - Multi-service startup

**Files to Modify**:

- `web/static/js/unified-master.js` - Update API base URL
- `web/api/agents.py` - Split public vs internal endpoints
- `web/api/reflection.py` - Split user vs agent endpoints
- `web/api/reality.py` - Split user vs telemetry endpoints
- `web/api/explainability.py` - Split user vs telemetry endpoints

**Files to Keep As-Is**:

- All router files stay in `web/api/` (just imported by different apps)
- `agents/mesh.py` - Already created
- `config/ports.py` - Already created
