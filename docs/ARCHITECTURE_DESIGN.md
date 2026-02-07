# MERID Trading Platform - Full-Stack Architecture Design
## Production-Grade Kubernetes Deployment for $10k-$100k Trading

---

## 1. System & Service Layout

### Core Services

| Service | Responsibility | Scaling | Protocol |
|---------|---------------|---------|----------|
| **API Gateway** | Auth, rate limiting, routing, WAF | 3+ replicas | HTTP/2 + gRPC |
| **Orchestrator** | Agent lifecycle, strategy scheduling | 2 replicas | Internal HTTP |
| **Strategy Engine** | Signal generation, backtesting | Auto-scaled (HPA) | gRPC |
| **Risk Service** | Pre-trade checks, exposure limits | 2 replicas (HA) | gRPC |
| **Order Router** | Alpaca adapter, order management | 2 replicas | REST/WebSocket |
| **Data Ingestion** | Market data, bars, quotes | Auto-scaled | WebSocket |
| **Position Manager** | Portfolio tracking, P&L calc | 2 replicas | Internal HTTP |

### Supporting Services

| Service | Responsibility |
|---------|---------------|
| **Auth Service** | JWT/OAuth2, MFA, session mgmt |
| **Audit Log** | Immutable action logs, compliance export |
| **Metrics/Observability** | Prometheus, Grafana, distributed tracing |
| **Config Store** | Risk limits, feature flags (Vault + Consul) |
| **Notification Hub** | Alerts, PagerDuty, Slack webhooks |
| **SBOM/Attestation** | Sigstore signing, supply chain security |

### Kubernetes Layout

```
Namespace: merid-prod
├── api-gateway/ (3 replicas, Ingress)
├── core/
│   ├── orchestrator/ (2 replicas)
│   ├── strategy-engine/ (HPA: 2-10)
│   └── risk-service/ (2 replicas, anti-affinity)
├── execution/
│   ├── order-router/ (2 replicas)
│   └── position-manager/ (2 replicas)
├── data/
│   ├── ingestion/ (HPA: 2-8)
│   └── redis-cluster/ (cache + pub/sub)
├── platform/
│   ├── auth-service/ (2 replicas)
│   ├── audit-log/ (Kafka + ClickHouse)
│   └── notification-hub/ (2 replicas)
└── observability/
    ├── prometheus/ + grafana/
    ├── jaeger/ (tracing)
    └── fluentd/ (log aggregation)

Secrets: HashiCorp Vault (inject via sidecar)
ConfigMaps: Environment-specific settings
Ingress: nginx-ingress + cert-manager
```

### Communication Flow

```
[Trader/UI] → API Gateway → Auth Check → Rate Limit
    ↓
[Orchestrator] ←→ [Strategy Engine] (gRPC)
    ↓
[Risk Service] ← Pre-trade validation (gRPC, <50ms)
    ↓ (if approved)
[Order Router] → Alpaca API
    ↓
[Position Manager] ← Order fills (WebSocket)
    ↓
[Audit Log] ← All actions (async Kafka)
```

---

## 2. Backend API & Domain Layout

### Domain Modules

```
merid/
├── accounts/          # User/organization mgmt
├── positions/         # Portfolio state, P&L
├── orders/            # Order lifecycle, history
├── marketdata/        # Bars, quotes, tick data
├── risk/              # Limits, exposure, circuit breakers
├── strategies/        # Strategy configs, signals
├── agents/            # Agent lifecycle, health
├── audit/             # Compliance logs, trails
└── admin/             # Kill switch, config, diagnostics
```

### API Endpoints

#### Observability (SRE-Focused)

| Endpoint | Method | Purpose | UI Consumer |
|----------|--------|---------|-------------|
| `/health` | GET | Liveness/readiness probes | All views |
| `/metrics` | GET | Prometheus metrics | Grafana |
| `/api/v1/positions/summary` | GET | Open positions, P&L | Dashboard, Portfolio |
| `/api/v1/risk/state` | GET | Current exposure, limits | Risk view |
| `/api/v1/orders/active` | GET | Working orders count | Orders view |
| `/api/v1/circuit-breakers` | GET | CB status per symbol | Dashboard |
| `/api/v1/audit/events` | GET | Recent actions (paginated) | Logs view |
| `/ws/market-data` | WS | Real-time bars/quotes | Charts |
| `/ws/orders` | WS | Order updates | Live panels |

#### Control (Trading Operations)

| Endpoint | Method | Payload | Purpose |
|----------|--------|---------|---------|
| `/api/v1/orders` | POST | `{symbol, qty, side, type, strategy_id}` | Place order |
| `/api/v1/orders/{id}/cancel` | POST | `{reason}` | Cancel order |
| `/api/v1/strategies/{id}/toggle` | POST | `{enabled: bool, reason}` | Enable/disable strategy |
| `/api/v1/risk/limits` | PUT | `{max_position, max_drawdown, ...}` | Update limits |
| `/api/v1/admin/lockdown` | POST | `{lock: bool, severity, reason}` | Kill switch |
| `/api/v1/admin/config` | PATCH | `{key, value}` | Runtime config |

### Request/Response Schemas

#### Pre-Trade Check

**Request:**
```json
{
  "order": {
    "symbol": "AAPL",
    "qty": "100",
    "side": "buy",
    "type": "market"
  },
  "strategy_id": "momentum-v1",
  "request_id": "uuid"
}
```

**Response (Approved):**
```json
{
  "approved": true,
  "order_id": "ord-uuid",
  "risk_checks": ["position_limit", "buying_power"],
  "estimated_fill": 174.52
}
```

**Response (Rejected):**
```json
{
  "approved": false,
  "rejection_reason": "POSITION_LIMIT_EXCEEDED",
  "current_exposure": 50000,
  "max_allowed": 45000,
  "suggested_qty": 50
}
```

#### Risk Exposure View

```json
{
  "portfolio": {
    "total_equity": 125000.00,
    "buying_power": 45000.00,
    "daily_pnl": 2340.50,
    "daily_pnl_pct": 1.87
  },
  "limits": {
    "max_daily_loss": 5000.00,
    "max_position_pct": 0.20,
    "max_leverage": 2.0
  },
  "exposures": [
    {
      "symbol": "AAPL",
      "qty": 100,
      "market_value": 17500.00,
      "pct_of_equity": 0.14,
      "unrealized_pnl": 340.00
    }
  ],
  "circuit_breakers": [
    {"symbol": "TSLA", "triggered": false, "reason": null}
  ]
}
```

---

## 3. Trading Console UI Layout

### Navigation Structure

```
Top Navigation Bar (always visible)
├── Logo + Environment Badge (LIVE/DEV)
├── P&L Summary (real-time)
├── Alert Indicators (circuit breakers, errors)
├── Kill Switch Button (prominent, red)
└── User Menu (role, theme toggle, logout)

Sidebar Navigation
├── Dashboard (overview)
├── Live Strategies (active agents)
├── Orders (working + history)
├── Positions/Portfolio
├── Risk & Limits
├── Logs & Incidents
└── Settings/Admin
```

### Page Layouts

#### Dashboard (Overview)

```
┌─────────────────────────────────────────────────────────┐
│ [Risk Bar: Daily P&L vs Limit | Leverage | CB Status]   │
├─────────────────┬─────────────────┬─────────────────────┤
│ P&L Chart       │ Active          │ Recent Orders       │
│ (24h + MTD)     │ Strategies      │ (last 5)            │
│                 │ (health status) │                     │
├─────────────────┴─────────────────┴─────────────────────┤
│ Market Watch (top movers, positions)                    │
└─────────────────────────────────────────────────────────┘
```

#### Live Strategies

```
┌─────────────────────────────────────────────────────────┐
│ Strategy Controls [Enable All] [Disable All] [Panic]    │
├─────────────────────────────────────────────────────────┤
│ Strategy Card                                           │
│ ├─ Header: Name | Status Toggle | Health Dot            │
│ ├─ Metrics: Positions | P&L | Signal Rate               │
│ ├─ Chart: Equity curve (mini)                           │
│ └─ Actions: [View Logs] [Edit] [Emergency Stop]         │
└─────────────────────────────────────────────────────────┘
```

#### Orders

```
┌─────────────────────────────────────────────────────────┐
│ Filter: [Symbol ▼] [Side ▼] [Status ▼] | [Refresh]      │
├─────────────────────────────────────────────────────────┤
│ Orders Table                                            │
│ Symbol | Side | Qty | Type | Price | Status | Actions   │
│ AAPL   | Buy  | 100 | Mkt  | --   | Filled | [Cancel]  │
└─────────────────────────────────────────────────────────┘
```

#### Risk & Limits

```
┌─────────────────────────────────────────────────────────┐
│ Risk Limits (editable by Admin only)                    │
│ ├─ Max Daily Loss: [$____] / $5,000 [slider]           │
│ ├─ Max Position %: [____] / 20% [slider]               │
│ └─ Max Leverage: [____] / 2.0x [slider]                │
├─────────────────────────────────────────────────────────┤
│ Current Exposure                                        │
│ [Progress bars: per-symbol vs limits]                   │
├─────────────────────────────────────────────────────────┤
│ Circuit Breakers                                        │
│ Symbol | Trigger Price | Status | Reset                 │
└─────────────────────────────────────────────────────────┘
```

### UX Safety Patterns

| Action | Safety Mechanism |
|--------|-----------------|
| Place Order | Pre-trade risk check + confirmation dialog for large orders (>10% of equity) |
| Cancel All | "Cancel All Orders" button requires 3-second hold + confirmation |
| Toggle Strategy | Disabled during active orders; audit log reason required |
| Change Risk Limits | Admin only; requires MFA + reason field; 5-minute delayed effect |
| Kill Switch | Single-click triggers immediate; requires unlock token to reverse |

### Data Density Management

- **Color coding**: Green (profit), Red (loss), Amber (warning), Gray (neutral)
- **Grouping**: Orders by strategy, positions by sector/asset class
- **Filtering**: Symbol search, date range, status dropdowns
- **Pagination**: 50 items default, infinite scroll for logs
- **Hover details**: Tooltips for abbreviations, sparklines for trends

---

## 4. Risk & Observability "Belt and Suspenders"

### Risk Visualizations

| Metric | Display | Backend API |
|--------|---------|-------------|
| Daily P&L vs Limit | Progress bar (green→red as approaches limit) | `/api/v1/positions/summary` |
| Per-Symbol Exposure | Pie chart + table | `/api/v1/risk/exposure` |
| Leverage | Gauge (0-4x, red zone at >2x) | `/api/v1/risk/state` |
| Open Orders vs Cap | Counter badge (red when >90% of cap) | `/api/v1/orders/active` |

### Critical Alerts

| Event | Severity | Channel | UI Pattern |
|-------|----------|---------|------------|
| Circuit breaker trip | CRITICAL | PagerDuty + In-app banner | Red banner, modal block |
| Daily loss >80% of limit | HIGH | Slack + Email | Amber toast, risk bar pulse |
| Exchange disconnect | HIGH | PagerDuty + In-app | Connectivity indicator red |
| Strategy error rate >5% | MEDIUM | Slack | Strategy card amber dot |
| Missed heartbeat (>30s) | CRITICAL | PagerDuty | Agent status red X |

### Incident Response UI

```
Incident Panel (appears when alert triggered)
├─ Incident ID: INC-2025-001
├─ Impact: Strategy "momentum-v1" stopped
├─ Started: 2025-01-31 14:23:05 UTC
├─ Status: INVESTIGATING
├─ Runbook: [View Runbook] [Acknowledge]
├─ Related: [Logs] [Metrics] [Recent Orders]
└─ Actions: [Escalate] [Resolve] [Snooze 15m]
```

---

## 5. Security, Compliance & Safety

### Role-Based Access

| Role | Dashboard | Orders | Strategies | Risk Limits | Admin |
|------|-----------|--------|------------|-------------|-------|
| Trader | Read | Create/Cancel | View only | View only | No |
| Quant | Read | View | Enable/Disable* | View only | No |
| SRE | Full | View | View | View | Lockdown only |
| Admin | Full | Full | Full | Full | Full |

*Quant changes require audit reason, applied after delay

### Secrets Management

| Secret Type | Storage | UI Exposure | Logs |
|-------------|---------|-------------|------|
| Alpaca API keys | Vault (inject as env) | Never | Masked (***key) |
| JWT signing key | Vault | Never | Never |
| DB passwords | Vault + Kubernetes secrets | Never | Never |
| User passwords | Hashed (bcrypt) | Never | Never |

### Audit Requirements

| Action | Required Field | Retention |
|--------|---------------|-----------|
| Risk limit change | Reason + ticket ID | 7 years |
| Strategy toggle | Reason + expected impact | 7 years |
| Kill switch | Incident reference | 7 years |
| Order placement | Strategy ID + request ID | 7 years |
| Manual order cancel | Reason | 7 years |

---

## 6. Power User Features

| Feature | Description |
|---------|-------------|
| **Customizable Layouts** | Drag-and-drop widgets, save named workspaces ("Day Trading", "Risk Monitoring") |
| **Advanced Filtering** | Regex search on logs, multi-select filters, saved filter sets |
| **Time-Travel Replay** | Replay market window: select time range, see strategy decisions + risk state overlay |
| **Theme System** | Dark (default), Light, High-contrast (colorblind-friendly red/green) |
| **Keyboard Shortcuts** | `Ctrl+K` (command palette), `Esc` (cancel), `Space` (pause strategies), `Ctrl+Shift+P` (panic) |
| **Export Tools** | CSV/JSON export for orders, positions, audit logs; PDF report generation |
| **Mobile Companion** | Read-only iOS/Android app for monitoring + kill switch |

---

## 7. Implementation Notes

### Frontend Stack

- **Framework**: React 18 + TypeScript
- **State**: Zustand (client) + React Query (server state)
- **Real-time**: WebSocket (order updates) + SSE (metrics)
- **UI Library**: shadcn/ui + Tailwind CSS
- **Charts**: Recharts (lightweight) + TradingView Charting Library (advanced)
- **Testing**: Jest + React Testing Library + Playwright (E2E)

### Backend Patterns

- **Commands**: CQRS - write path via API → Kafka → processors
- **Queries**: Read-optimized views (materialized in Redis/ClickHouse)
- **Idempotency**: All order endpoints require `Idempotency-Key` header
- **Circuit Breaker**: Resilience4j (Java) or pybreaker (Python) per external service
- **Audit**: Async append-only log (Kafka → S3/ClickHouse)

### Testing Strategy

| Layer | Tools | Coverage |
|-------|-------|----------|
| UI Components | Jest + RTL | 80%+ critical paths |
| API Integration | pytest + TestContainers | All endpoints |
| E2E Workflows | Playwright | Order flow, kill switch, risk checks |
| Chaos Tests | Gremlin/Litmus | Circuit breakers, failover |

---

## Summary

This architecture provides:
- **Scalability**: Kubernetes-native with horizontal pod autoscaling
- **Resilience**: Circuit breakers, retries, kill switches at multiple layers
- **Observability**: Full tracing, metrics, alerts for SRE workflows
- **Security**: Zero secrets in UI, RBAC, immutable audit logs
- **UX**: Safety-first design with confirmations, clear risk visualization

Ready for production deployment trading $10k-$100k via Alpaca with confidence.
