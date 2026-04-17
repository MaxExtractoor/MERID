# Operator Dashboard Specification

## Overview

The MERID Operator Dashboard provides real-time visibility and control over the trading system.

## Sections

### 1. System Status
- Current trading mode (paper/live/sim)
- Venue connectivity status
- Active circuit breaker states

### 2. Execution Gate
- Kill switch status
- Daily notional usage vs. cap
- Position count vs. limit

### 3. Agent Performance
- Per-agent win rate
- Consensus participation rate
- Recent predictions and outcomes

### 4. Order Management
- Active orders by venue
- Order group lifecycle status
- Fill rates and slippage

### 5. Risk Dashboard
- Current exposure by market
- VaR and expected shortfall
- Drawdown from peak

### 6. Operator Controls
- Pause/resume trading
- Adjust position limits
- Force paper mode
- Manual order entry

## API Endpoints

- `GET /api/v1/operator/summary` - Operator summary
- `GET /api/v1/operator/audit-trail` - Audit trail
- `POST /api/v1/operator/pause` - Pause trading
- `POST /api/v1/operator/resume` - Resume trading
- `GET /api/v1/operator/equity-series` - Equity curve
- `GET /api/v1/operator/risk-utilization` - Risk utilization
