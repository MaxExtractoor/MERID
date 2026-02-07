# MERID UI Layout Specification

## UI Architecture Overview

MERID's user interface consists of:
- **Web Dashboard**: React-based trading dashboard (`web/react/`)
- **Mobile App**: Flutter cross-platform application (iOS/Android)
- **API Endpoints**: FastAPI backend with 30+ routers (`web/api/`)
- **WebSocket Streams**: Real-time data updates via Socket.io

## Navigation Structure

### Top-Level Navigation

```
┌─────────────────────────────────────────────────────────────┐
│ MERID v2.0  [Overview] [Trading] [Research] [Risk] [Agents] │
│ [Positions] [Orders] [Predictions] [Settings] [Health]      │
└─────────────────────────────────────────────────────────────┘
```

## Page Specifications

### 1. Dashboard Overview (`/` - Overview.tsx)
**Purpose**: System-wide status and key metrics at a glance

**Layout**:
```
┌──────────────────────────────────────────────────────────┐
│ Portfolio Summary                                         │
│ ┌─────────┬──────────┬──────────┬───────────┐          │
│ │ Total   │ Daily    │ Sharpe   │ Active    │          │
│ │ P&L     │ Volume   │ Ratio    │ Positions │          │
│ │ $45,320 │ $125.5k  │ 2.34     │ 12        │          │
│ └─────────┴──────────┴──────────┴───────────┘          │
│                                                          │
│ ┌─────────────────────┬────────────────────────┐        │
│ │ P&L Chart (30d)     │ Asset Allocation       │        │
│ │ [Recharts Line]     │ [Pie Chart]           │        │
│ └─────────────────────┴────────────────────────┘        │
│                                                          │
│ Recent Activity Stream                                   │
│ ├─ 14:32 BUY AAPL 100 @ $185.50 [Executed]             │
│ ├─ 14:28 Swarm Consensus: Bullish on Tech              │
│ └─ 14:25 Risk Alert: Portfolio heat at 78%             │
└──────────────────────────────────────────────────────────┘
```

**Data Sources**:
- `merid/execution/portfolio.py` - Portfolio metrics
- `core/merid_metrics.py` - System metrics
- Event stream via WebSocket

### 2. Trading Interface (`/trading` - Trading.tsx)
**Purpose**: Execute trades and monitor market conditions

**Layout**:
```
┌──────────────────────────────────────────────────────────┐
│ Market Selection & Order Entry                           │
│ ┌───────────────────┬────────────────────────┐         │
│ │ Venue: [Dropdown]  │ Symbol: [___________]  │         │
│ │ □ Kalshi          │                        │         │
│ │ □ Polymarket      │ Side: [BUY] [SELL]     │         │
│ │ □ Alpaca          │                        │         │
│ │                   │ Size: [___________]     │         │
│ │ Market Data       │ Price: [___________]    │         │
│ │ Bid: $185.45      │                        │         │
│ │ Ask: $185.48      │ [Submit Order]          │         │
│ │ Spread: $0.03     │                        │         │
│ └───────────────────┴────────────────────────┘         │
│                                                          │
│ Order Book & Recent Trades                              │
│ ┌────────────────────┬────────────────────────┐        │
│ │ Bids              │ Asks                   │        │
│ │ 185.45  1000      │ 185.48  1500          │        │
│ │ 185.44  2000      │ 185.49  1000          │        │
│ └────────────────────┴────────────────────────┘        │
└──────────────────────────────────────────────────────────┘
```

**Data Sources**:
- `trading/router.py` - Order submission
- `merid/execution/router.py` - ExecutionRouter
- `data/enhanced_market_feed.py` - Market data
- `merid/event_venues/*/client.py` - Venue APIs

### 3. Research & Analysis (`/research` - Research.tsx)
**Purpose**: Market analysis, backtesting, and strategy development

**Layout**:
```
┌──────────────────────────────────────────────────────────┐
│ Strategy Performance & Backtesting                       │
│ ┌─────────────────────────────────────────────┐        │
│ │ Strategy: [Momentum_v2.3]  Period: [30d]    │        │
│ │                                              │        │
│ │ Backtest Results:                            │        │
│ │ - Total Return: 12.5%                        │        │
│ │ - Max Drawdown: -4.2%                        │        │
│ │ - Win Rate: 62%                              │        │
│ │ - Sharpe: 2.1                                │        │
│ │                                              │        │
│ │ [Performance Chart]                           │        │
│ └─────────────────────────────────────────────┘        │
│                                                          │
│ Market Intelligence Feed                                │
│ ├─ News: Fed announces rate decision...                 │
│ ├─ Social: Bullish sentiment on $TSLA (78%)            │
│ └─ Whale: Large buyer detected on BTC                  │
└──────────────────────────────────────────────────────────┘
```

**Data Sources**:
- `backtesting/replay.py` - Backtest engine
- `agents/news_monitor_agent.py` - News feed
- `merid/whales.py` - Whale tracking
- `agents/twitter_agent.py` - Social sentiment

### 4. Risk Management (`/risk` - Risk.tsx)
**Purpose**: Monitor and control portfolio risk

**Layout**:
```
┌──────────────────────────────────────────────────────────┐
│ Risk Dashboard                                           │
│ ┌────────────────────────────────────────────┐         │
│ │ Risk Metrics                                │         │
│ │ Portfolio Heat: [████████░░] 78%           │         │
│ │ VaR (95%): $12,450                         │         │
│ │ Exposure Limit: $250,000 / $500,000        │         │
│ │ Correlation Risk: MODERATE                  │         │
│ └────────────────────────────────────────────┘         │
│                                                          │
│ Circuit Breakers & Guards                               │
│ ├─ Daily Loss Limit: $8,234 / $10,000 ✓                │
│ ├─ Position Concentration: 18% / 25% ✓                  │
│ ├─ Anti-Rug Protection: ACTIVE ✓                        │
│ └─ Slippage Guard: NORMAL                               │
│                                                          │
│ Risk Actions                                             │
│ [Reduce Exposure] [Hedge Portfolio] [Emergency Stop]    │
└──────────────────────────────────────────────────────────┘
```

**Data Sources**:
- `trading/guards/trading_guard.py` - Risk guards
- `core/automated_risk_controls.py` - Risk controls
- `merid/execution/portfolio.py` - Portfolio metrics

### 5. Swarm & Agents (`/agents` - Agents.tsx)
**Purpose**: Monitor and control AI agent swarm

**Layout**:
```
┌──────────────────────────────────────────────────────────┐
│ Agent Swarm Control Panel                                │
│ ┌────────────────────────────────────────────┐         │
│ │ Active Agents (7/7)                        │         │
│ │                                             │         │
│ │ MarketAnalyst    [██████] ACTIVE  92% conf │         │
│ │ RiskGuardian     [██████] ACTIVE  88% conf │         │
│ │ ExecutionEngine  [██████] ACTIVE  95% conf │         │
│ │ TwitterMonitor   [██████] ACTIVE  76% conf │         │
│ │ NewsMonitor      [██████] ACTIVE  81% conf │         │
│ │ ArbitrageAgent   [████░░] IDLE    --       │         │
│ │ SlippageAgent    [██████] ACTIVE  90% conf │         │
│ └────────────────────────────────────────────┘         │
│                                                          │
│ Consensus Formation                                      │
│ ├─ Current Topic: "AAPL earnings impact"               │
│ ├─ Votes: 5 FOR / 2 AGAINST                            │
│ ├─ Confidence: 78%                                      │
│ └─ Decision: APPROVED - Execute long position          │
│                                                          │
│ [Pause Swarm] [Reset Consensus] [Manual Override]      │
└──────────────────────────────────────────────────────────┘
```

**Data Sources**:
- `core/swarm_intelligence.py` - TradingSwarm
- `core/agent_orchestrator.py` - AgentOrchestrator
- `core/consensus_engine.py` - Consensus formation
- `agents/` - Individual agent statuses

### 6. Positions Management (`/positions` - Positions.tsx)
**Purpose**: View and manage current positions

**Layout**:
```
┌──────────────────────────────────────────────────────────┐
│ Current Positions                                        │
│ ┌─────────────────────────────────────────────────────┐│
│ │Symbol │Venue    │Size  │Entry  │Current│P&L      ││
│ │AAPL   │Alpaca   │100   │185.50 │186.25 │+$75     ││
│ │BTC-USD│Kalshi   │0.5   │42,100 │42,850 │+$375    ││
│ │TRUMP  │Polymarket│1000 │0.52   │0.54   │+$20     ││
│ └─────────────────────────────────────────────────────┘│
│                                                          │
│ Position Actions                                         │
│ [Close Position] [Add to Position] [Set Stop Loss]      │
└──────────────────────────────────────────────────────────┘
```

**Data Sources**:
- `merid/execution/portfolio.py` - PortfolioAggregator
- `trading/execution.py` - Position management

### 7. Orders & Execution (`/orders` - Orders.tsx)
**Purpose**: Monitor order status and execution quality

**Layout**:
```
┌──────────────────────────────────────────────────────────┐
│ Order Management                                         │
│ ┌─────────────────────────────────────────────────────┐│
│ │ Open Orders (OpenOrdersPanel.tsx)                   ││
│ │ID    │Symbol│Side│Size│Price │Status              ││
│ │#4521 │AAPL  │BUY │100 │185.45│PENDING            ││
│ │#4520 │BTC   │SELL│0.2 │42,900│PARTIALLY_FILLED   ││
│ └─────────────────────────────────────────────────────┘│
│                                                          │
│ Execution Analytics                                     │
│ ├─ Fill Rate: 94.2%                                    │
│ ├─ Avg Slippage: 0.02%                                 │
│ └─ Avg Latency: 45ms                                   │
└──────────────────────────────────────────────────────────┘
```

**Data Sources**:
- `merid/execution/router.py` - Order routing
- `trading/execution.py` - Order management

### 8. Prediction Markets (`/predictions` - PredictionsPanel.tsx)
**Purpose**: Monitor prediction market positions

**Layout**:
```
┌──────────────────────────────────────────────────────────┐
│ Prediction Market Positions                              │
│ ┌─────────────────────────────────────────────────────┐│
│ │Market                    │Prob │Position│Value     ││
│ │Fed raises rates Dec 2024 │72%  │YES $500│$360      ││
│ │BTC > $50k by EOY        │45%  │NO $200 │$110      ││
│ │Trump wins 2024          │52%  │YES $100│$52       ││
│ └─────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────┘
```

**Data Sources**:
- `merid/event_venues/kalshi/` - Kalshi integration
- `merid/event_venues/polymarket/` - Polymarket integration

### 9. Settings & Configuration (`/settings` - Settings.tsx)
**Purpose**: System configuration and preferences

**Layout**:
```
┌──────────────────────────────────────────────────────────┐
│ System Settings                                          │
│ ┌─────────────────────────────────────────────┐        │
│ │ Trading Configuration                        │        │
│ │ □ Enable Paper Trading                       │        │
│ │ □ Enable Prediction Markets                  │        │
│ │ Max Position Size: [___________]             │        │
│ │ Daily Loss Limit: [___________]              │        │
│ │                                              │        │
│ │ API Credentials                              │        │
│ │ Alpaca Key: [****************]              │        │
│ │ Kalshi Key: [****************]              │        │
│ │                                              │        │
│ │ Risk Parameters                              │        │
│ │ Circuit Breaker Threshold: [____%]          │        │
│ │ Anti-Rug Protection: [ON/OFF]               │        │
│ └─────────────────────────────────────────────┘        │
└──────────────────────────────────────────────────────────┘
```

**Data Sources**:
- `merid/settings.py` - System settings
- `config/settings.py` - Configuration management

### 10. System Health (`/health` - Health.tsx)
**Purpose**: Monitor system health and performance

**Layout**:
```
┌──────────────────────────────────────────────────────────┐
│ System Health Monitor                                    │
│ ┌─────────────────────────────────────────────┐        │
│ │ Component Status                             │        │
│ │ API Gateway        [██████] HEALTHY         │        │
│ │ Execution Engine   [██████] HEALTHY         │        │
│ │ Risk Service       [██████] HEALTHY         │        │
│ │ Data Feed          [████░░] DEGRADED        │        │
│ │ Database           [██████] HEALTHY         │        │
│ │                                              │        │
│ │ System Metrics                               │        │
│ │ CPU Usage: 45%                               │        │
│ │ Memory: 8.2GB / 16GB                         │        │
│ │ Disk: 120GB / 500GB                          │        │
│ │ Network Latency: 12ms                        │        │
│ └─────────────────────────────────────────────┘        │
└──────────────────────────────────────────────────────────┘
```

**Data Sources**:
- `core/health_monitor.py` - Health monitoring
- `core/health.py` - Health checks
- System metrics via psutil

## Real-Time Components

### Live Risk Strip (LiveRiskStrip.tsx)
Persistent top bar showing critical risk metrics:
- Portfolio heat gauge
- Daily P&L
- Circuit breaker status
- Active alerts

### Live Agent Health Panel (LiveAgentHealthPanel.tsx)
Real-time agent status updates via WebSocket:
- Agent online/offline status
- Consensus participation
- Performance metrics

## WebSocket Streams

All real-time updates delivered via Socket.io connections:

1. **Price Feed Stream** (`/ws/prices`)
   - Source: `data/live_price_feed.py`
   - Updates: Price ticks, order book changes

2. **Execution Stream** (`/ws/execution`)
   - Source: `merid/execution/router.py`
   - Updates: Order status, fills, positions

3. **Agent Stream** (`/ws/agents`)
   - Source: `core/agent_orchestrator.py`
   - Updates: Agent decisions, consensus

4. **Risk Stream** (`/ws/risk`)
   - Source: `core/automated_risk_controls.py`
   - Updates: Risk metrics, alerts

5. **System Health Stream** (`/ws/health`)
   - Source: `core/health_monitor.py`
   - Updates: Component health, metrics

## Mobile UI (Flutter)

The Flutter mobile app mirrors the web dashboard with optimizations for mobile:

### Mobile Navigation
- Bottom tab bar: Overview, Trading, Positions, Alerts, Settings
- Swipe gestures for quick actions
- Pull-to-refresh on all data views

### Mobile-Specific Features
- Push notifications for:
  - Order fills
  - Risk alerts
  - Consensus decisions
- Biometric authentication
- Offline mode with cached data
- Voice commands for hands-free trading

## Accessibility Features

All UI components follow WCAG 2.2 AA standards:
- Keyboard navigation support
- Screen reader compatibility
- High contrast mode
- Configurable font sizes
- Focus indicators
- ARIA labels on all interactive elements

## Theme & Styling

### Color Palette (Dark Mode Default)
- Background: `#020617` (deep slate-black)
- Primary: `#f59e0b` (amber - cognition)
- Success: `#10b981` (emerald - safe/active)
- Danger: `#f43f5e` (rose - blocked/violation)
- Text: `#e2e8f0` (light gray)
- Monospace font: JetBrains Mono

### Component Library
- React components use Lucide icons
- Charts via Recharts
- Tables via @tanstack/react-table
- Real-time updates with socket.io-client
- State management via @tanstack/react-query

## Security Features

### UI Security
- JWT authentication on all API calls
- WebSocket authentication via tokens
- Role-based access control (RBAC)
- Session timeout after inactivity
- Secure credential storage
- CORS protection

### Data Protection
- End-to-end encryption for sensitive data
- No client-side storage of credentials
- Audit logging of all actions
- Rate limiting on API endpoints

## Performance Optimization

### Frontend Optimization
- Code splitting for faster initial load
- Lazy loading of views
- Virtual scrolling for large lists
- Memoization of expensive computations
- WebWorkers for heavy calculations

### Data Optimization
- Pagination on large datasets
- Debounced search inputs
- Throttled WebSocket updates
- Client-side caching with invalidation
- Progressive data loading

## Summary

The MERID UI provides a comprehensive trading interface with:
- **10 main views** covering all aspects of trading
- **Real-time updates** via 5 WebSocket streams
- **React web dashboard** with modern components
- **Flutter mobile app** for iOS/Android
- **Full accessibility** compliance (WCAG 2.2 AA)
- **Dark theme** optimized for extended use
- **Security-first** design with JWT/RBAC
- **Performance optimized** for real-time trading

The UI directly interfaces with the backend services mapped in MERID_SYSTEM_ARCHITECTURE.md, providing operators complete control over the sovereign decision organism while maintaining the core principle of constrained execution.
