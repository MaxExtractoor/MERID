# Kalshi 15m Crypto Trading System - Comprehensive Documentation

## Overview

This is the comprehensive documentation for the Kalshi 15-minute crypto trading system, covering the complete end-to-end architecture, components, and operational procedures for the 5 core crypto assets (BTC, ETH, SOL, XRP, DOGE).

## Table of Contents

1. [System Overview](#system-overview)
2. [Architecture](#architecture)
3. [Component Documentation](#component-documentation)
4. [Operational Procedures](#operational-procedures)
5. [Critical Fixes and Bugs](#critical-fixes-and-bugs)
6. [Monitoring and Observability](#monitoring-and-observability)
7. [Risk Management](#risk-management)
8. [Troubleshooting](#troubleshooting)

## System Overview

### Purpose

The Kalshi 15m crypto trading system is a production-grade automated trading system that trades binary prediction markets on Kalshi for 5 core crypto assets (BTC, ETH, SOL, XRP, DOGE) using 15-minute expiration contracts.

### Key Characteristics

- **Assets**: BTC, ETH, SOL, XRP, DOGE (must always be included)
- **Timeframe**: 15-minute expiration contracts
- **Strategy**: Velocity-based momentum trading with regime detection and panic fade
- **Risk Model**: Fixed $1.00 total exposure cap across all assets (shared pool)
- **Execution**: Limit orders with fee-aware edge calculation
- **Market Data**: Real-time WebSocket subscriptions with local orderbook management
- **Monitoring**: Comprehensive health checks, alerting, and observability

### Production Stack

- **Entry Point**: `web/main_15m_lean.py` (NOT `web/main.py` - that's legacy)
- **Profile**: `kalshi_crypto_15m_v2.yaml`
- **Startup Command**: `.\start_15m.ps1 -Port 8011 -Profile kalshi_crypto_15m_v2`

## Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         FastAPI Server                          │
│                      (web/main_15m_lean.py)                     │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
┌───────▼────────┐    ┌──────▼──────┐    ┌───────▼────────┐
│  Agent Grid    │    │   Market    │    │   Risk         │
│  (5 agents)    │    │   Data      │    │   Management   │
└───────┬────────┘    └──────┬──────┘    └───────┬────────┘
        │                    │                    │
        │                    │                    │
┌───────▼────────┐    ┌──────▼──────┐    ┌───────▼────────┐
│  Signal        │    │   WebSocket │    │   Global       │
│  Generation    │    │   Bridge    │    │   Allocator    │
└───────┬────────┘    └──────┬──────┘    └───────┬────────┘
        │                    │                    │
        │                    │                    │
┌───────▼────────┐    ┌──────▼──────┐    ┌───────▼────────┐
│  Indicator     │    │   Position  │    │   Order Gate   │
│  Stack         │    │   Cache     │    │   (Idempotent) │
└────────────────┘    └─────────────┘    └────────────────┘
```

### Data Flow

```
Spot Price (Coinbase) → Indicator Stack → Signal Generation → Agent Grid
                                                              ↓
WebSocket (Kalshi) → Orderbook → Market State → Global Allocator → Order Gate
                                                              ↓
                                                        Order Router → Kalshi API
                                                              ↓
                                                        Fill → Position Cache
```

## Component Documentation

### 1. Main Entry Point and Startup Sequence

**File**: `docs/15M_AGENT_GRID_DOCUMENTATION.md` (includes startup sequence)

**Key Points**:
- Production entry point: `web/main_15m_lean.py`
- Legacy entry point: `web/main.py` (DO NOT USE)
- Startup sequence: FastAPI lifespan → Agent Grid initialization → WebSocket subscriptions → Trading loop
- Profile: `kalshi_crypto_15m_v2.yaml`
- Port: 8011 (default)

**Startup Command**:
```powershell
CD C:\Dev\MERID
.\start_15m.ps1 -Port 8011 -Profile kalshi_crypto_15m_v2
```

**Pre-Startup**:
```powershell
taskkill /F /IM python.exe  # Terminate any running server processes
```

### 2. Configuration Profiles and Environment Settings

**File**: `docs/15M_AGENT_GRID_DOCUMENTATION.md` (includes configuration)

**Key Points**:
- Profile YAML: `config/profiles/kalshi_crypto_15m_v2.yaml`
- Environment variables: `config/profiles/env.prod.kalshi-pm.live.example`
- Threshold config: `config/kalshi_15m_thresholds.yaml`
- Risk envelope: `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py`

**Key Configuration Parameters**:
- Capital allocation
- Velocity thresholds per asset
- Risk bands (normal/warning/downsize/halt)
- Depth thresholds per asset
- Spread limits
- Time-to-expiry windows

### 3. Agent Grid Setup and Configuration

**File**: `docs/15M_AGENT_GRID_DOCUMENTATION.md`

**Key Points**:
- 5 agents: BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M
- Each agent has indicator stacks for all 5 assets (redundancy fix)
- Agent grid orchestrator: `LeanAgentGrid15m`
- Trading cycle: 5-second cadence
- REST sync: Every 30 seconds for position reconciliation

**Agent Configuration**:
```python
@dataclass
class LeanAgentConfig:
    name: str
    series_tickers: list[str]
    signal_mode: str = "trend"
    max_spread_cents: int = 100
    min_time_to_expiry_s: int = 180
    max_time_to_expiry_s: int = 900
    per_strip_order_limit: int = 200
    per_asset_cooldown_s: int = 8
    max_orders_per_15m_window: int = 12
    consecutive_loss_pause: int = 3
    max_session_risk_pct: float = 0.10
    velocity_threshold_btc: float = 0.00015
    velocity_threshold_eth: float = 0.00015
    velocity_threshold_sol: float = 0.000225
    velocity_threshold_xrp: float = 0.000225
    velocity_threshold_doge: float = 0.0003
```

### 4. Market Data Pipeline and WebSocket Subscriptions

**File**: `docs/15M_MARKET_DATA_PIPELINE_DOCUMENTATION.md`

**Key Points**:
- WebSocket client: `KalshiWebSocket` (`merid/event_venues/kalshi/ws.py`)
- WebSocket bridge: `KalshiWebSocketBridge` (`merid/event_venues/kalshi/ws_bridge.py`)
- Local orderbook: `LocalOrderbook` (`merid/event_venues/kalshi/orderbook.py`)
- Market state store: `KalshiMarketStateStore` (`merid/event_venues/kalshi/market_state.py`)
- Market catalog: `KalshiMarketCatalog` (`merid/event_venues/kalshi/market_catalog.py`)
- Spot price service: `UnifiedSpotService` (`data/unified_spot_service.py`)

**WebSocket Features**:
- Real-time streaming with exponential backoff reconnect
- Orderbook snapshot caching and delta application
- Async message queue (32768 capacity)
- Sequence tracking for message ordering
- Coalescing buffer for high-frequency updates

**Spot Price Service**:
- Unified spot price from Coinbase Public API
- Caching with TTL
- Fallback mechanisms
- 5 assets: BTC, ETH, SOL, XRP, DOGE

### 5. Signal Generation and Indicators

**File**: `docs/15M_SIGNAL_GENERATION_DOCUMENTATION.md`

**Key Points**:
- Indicator stack: `Crypto15mIndicatorStack` (`merid/signals/crypto_15m_indicators.py`)
- Indicator config: `IndicatorConfig` (kalshi_mode for relaxed thresholds)
- Indicator snapshot: `IndicatorSnapshot` (complete feature vector)
- Signal types: Velocity-based, panic fade, multi-timeframe alignment
- FVG detection: Consolidated to `merid/prediction/forecasters/fvg.py`

**Key Indicators**:
- EMA (trend): 21-period, 9-period fast, 21-period slow, 200-period
- RSI (momentum): 8-period
- MACD (momentum): 12-26-9
- Chop filter (market state): ATR-based
- Fee-aware EV (expected value)
- Volatility regime detection

**Signal Generation**:
- Velocity-based signals: Price velocity vs threshold
- Panic fade: Oversold/overbought reversion
- Multi-timeframe alignment: 1m, 5m, 15m alignment
- Regime detection: Trending vs ranging

### 6. Risk Management and Position Limits

**File**: `docs/15M_RISK_MANAGEMENT_DOCUMENTATION.md`

**Key Points**:
- Risk envelope: `KalshiCrypto15mRiskEnvelope` (`merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py`)
- Global allocator: `GlobalAllocator` (`merid/risk/profiles/global_allocator.py`)
- Position cache: `PositionCache` (`merid/event_venues/kalshi/position_cache.py`)
- Position monitor: `PositionMonitor` (`merid/position_management/position_monitor.py`)

**Risk Model**:
- **Total exposure cap**: $1.00 (shared pool across all 5 assets)
- **Per-asset limit**: None (assets compete for capital based on edge)
- **Per-agent limit**: None (agents compete for capital based on edge)
- **Window limits**: $1.00 total per 15m window (HARD STOP)
- **Drawdown bands**: Normal (0-10%), Warning (10-12%), Downsize (12-15%), Halt (15%+)

**Global Allocator**:
- Top-N edge knapsack under venue cap
- Shared $1 pool model
- 1 contract per asset per window
- Entry price range: 5c-95c
- Confidence threshold: 50%
- Edge threshold: 2.0% (actual percentage)

**Per-Asset Edge Thresholds**:
- BTC: 1.75%
- ETH: 2.0%
- SOL: 2.5%
- XRP: 3.0%
- DOGE: 3.5%

### 7. Execution Pipeline and Guardrails

**File**: `docs/15M_EXECUTION_PIPELINE_DOCUMENTATION.md`

**Key Points**:
- Order gate: `PreTradeGate` (`merid/event_venues/kalshi/order_gate.py`)
- Order router: `OrderRouter` (`merid/event_venues/kalshi/order_router.py`)
- Venue client: `KalshiVenueClient` (`merid/event_venues/kalshi/client.py`)
- Unified fees: `UnifiedFees` (`merid/event_venues/kalshi/unified_fees.py`)

**Pre-Trade Guardrails**:
1. Idempotency (deterministic client_order_id)
2. Fill awareness (position already satisfied)
3. Lease check (venue capacity)
4. Price guard (deep OTM or high price)
5. Price repeat (same ticker+side+price within 15m window)
6. Window limit (3% per agent, 5% total per 15m window)
7. Exit policy (metadata validation)
8. Sequential trading (block new entries when positions exist)

**Post-Trade Guardrails**:
1. Resting order tracking (edge decay monitoring)
2. Position monitoring (take-profit and stop-loss)
3. Window exposure tracking (cumulative exposure)
4. Drawdown tracking (adaptive risk scaling)

**Exit Policy**:
- Take profit: Time-based dynamic R-multiple (1.0R >7min, 0.75R 4-7min, 0.5R <4min)
- Stop loss: R-multiple based
- Trailing stop: Optional (activation at 0.8R, giveback 5c)
- Scale-out: Optional (trigger at 0.7R, scale out 50%)
- Max hold time: 10-15 minutes (aligned with expiry)

### 8. Monitoring, Alerting, and Health Checks

**File**: `docs/15M_MONITORING_ALERTING_DOCUMENTATION.md`

**Key Points**:
- Health monitor: `HealthMonitor` (`core/health.py`)
- Health API: `/api/health` (`web/api/health.py`)
- WebSocket health: `/api/websocket/health` (`web/api/websocket_health.py`)
- Agent health: `/api/v1/agents/health` (`web/api/agents_health.py`)
- Alert rules: `notifications/alert_rules.py`

**Health Checks**:
- ExecutionGuard kill switch
- Kalshi circuit breaker
- MeridLoop liveness
- HealthMonitor status
- Fills ledger health
- Event loop lag (diagnostic)
- AgentGrid readiness

**WebSocket Monitoring**:
- `/ws/trades`: Trade stream endpoint
- `/ws/prices`: Price stream endpoint
- `/ws/portfolio`: Portfolio stream endpoint
- `/ws/paper-trading`: Paper trading endpoint
- `/ws`: General event stream endpoint

**Alert Thresholds**:
- CPU: Warning at 80%, Critical at 90%
- Memory: Warning at 80%, Critical at 90%
- Disk: Warning at 80%, Critical at 90%
- Event loop lag: Warning at 100ms, Critical at 500ms
- Agent grid errors: Warning at 5%, Critical at 10%

## Operational Procedures

### Startup

1. **Terminate existing processes**:
   ```powershell
   taskkill /F /IM python.exe
   ```

2. **Start the server**:
   ```powershell
   CD C:\Dev\MERID
   .\start_15m.ps1 -Port 8011 -Profile kalshi_crypto_15m_v2
   ```

3. **Verify startup**:
   - Check health endpoint: `http://localhost:8011/api/health`
   - Check WebSocket health: `http://localhost:8011/api/websocket/health`
   - Check agent health: `http://localhost:8011/api/v1/agents/health`

### Shutdown

1. **Graceful shutdown**:
   - Send SIGTERM to the process
   - Wait for cleanup (WebSocket disconnect, position sync)

2. **Force shutdown (if needed)**:
   ```powershell
   taskkill /F /IM python.exe
   ```

### Monitoring

1. **Health checks**:
   - K8s liveness probe: Every 10 seconds
   - K8s readiness probe: Every 30 seconds
   - Component health checks: Every 60 seconds

2. **Logs**:
   - Check for critical errors
   - Monitor window limit violations
   - Track order submission/fill rates
   - Monitor drawdown and risk band changes

3. **Alerts**:
   - Kill switch activation
   - Circuit breaker open
   - Agent grid not ready
   - High CPU/memory/disk
   - Event loop lag

### Recovery

1. **Window exposure reset** (if stuck):
   ```python
   from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import force_reset_window_exposure
   force_reset_window_exposure(reason="stale_exposure")
   ```

2. **WebSocket reconnect**:
   - Automatic exponential backoff
   - Manual restart if auto-reconnect fails

3. **Position reconciliation**:
   - REST sync every 30 seconds
   - Manual sync if position cache desyncs

## Critical Fixes and Bugs

**File**: `docs/15M_HIGH_LEVERAGE_BUGS_REPORT.md`

### Critical Bugs (8)

1. **bars_available=1 Issue** - Signal generation completely broken
2. **Strict Spot Market Thresholds** - All signals blocked
3. **Module-Level Window Tracking State Discarded** - Risk limits ineffective
4. **Peak Bankroll Fluctuation** - Inconsistent risk enforcement
5. **Resting Order Exposure Not Tracked** - Exposure accumulation
6. **Per-Agent Limit Blocking Slot Allocator** - Capital allocation broken
7. **Per-Asset Limit Redundant** - Capital efficiency reduced
8. **Edge Threshold Mismatch** - Candidates filtered incorrectly

### High Bugs (5)

9. **Duplicate FVG Implementations** - Inconsistent signals
10. **Async Lock Missing** - Duplicate orders in async contexts
11. **Invalid State Transitions** - Inconsistent order state
12. **Price Repeat Execution** - Order spam
13. **Sequential Trading Not Enforced** - Exposure cap violation

### Medium Bugs (4)

14. **Spread Threshold Too Strict** - Missed opportunities
15. **Depth Threshold Too High** - Missed opportunities in low volume
16. **Health Check in Validation Mode** - Validation unusable
17. **Event Loop Lag Critical** - Unnecessary failures

## Monitoring and Observability

### Grafana Dashboards

- **Merid 15m Pipeline Health**: Overall system health
- **Merid Kalshi Recon Gate**: Reconciliation gate status
- **Merid PnL Exposure**: Profit and loss tracking
- **API Performance**: API latency and error rates
- **Database Health**: Database connection and query performance

### Prometheus Metrics

- `merid_ws_events_dropped_total`: Total WS events dropped
- `merid_ws_fills_dropped_total`: Total WS fill events dropped
- `merid_ws_forwarder_throughput`: WS forwarder throughput
- `merid_health_check_duration_seconds`: Health check duration
- `merid_agent_grid_ticks_total`: Total agent grid ticks
- `merid_agent_grid_errors_total`: Total agent grid errors
- `merid_order_submissions_total`: Total order submissions
- `merid_order_fills_total`: Total order fills
- `merid_position_pnl_cents`: Position PnL in cents

### Log Levels

- **DEBUG**: Detailed diagnostic information
- **INFO**: Normal operational events
- **WARNING**: Degraded performance or potential issues
- **ERROR**: Errors that don't prevent operation
- **CRITICAL**: Errors that prevent operation

## Risk Management

### Risk Envelope

- **Daily loss limit**: 5% (prod) / 10% (test)
- **Drawdown halt**: 15%
- **Window limits**: $1.00 total per 15m window
- **Per-trade risk**: Fixed $1.00 exposure cap

### Risk Bands

- **Normal**: 0-10% drawdown, 100% risk multiplier
- **Warning**: 10-12% drawdown, 50% risk multiplier
- **Downsize**: 12-15% drawdown, 25% risk multiplier
- **Halt**: 15%+ drawdown, 0% risk multiplier (manual resume)

### Position Limits

- **Total exposure**: $1.00 across all assets
- **Per-asset exposure**: None (shared pool)
- **Per-agent exposure**: None (shared pool)
- **Concurrent trades**: Limited by profile config

### Exit Management

- **Take profit**: Time-based dynamic R-multiple
- **Stop loss**: R-multiple based
- **Trailing stop**: Optional
- **Scale-out**: Optional
- **Max hold time**: 10-15 minutes

## Troubleshooting

### Common Issues

#### Issue: No signals generated

**Symptoms**: Agent grid running but no orders submitted

**Possible Causes**:
1. bars_available=1 (indicator stack not receiving enough updates)
2. Strict spot thresholds blocking signals
3. Kalshi mode not enabled
4. Velocity thresholds not met

**Solutions**:
1. Verify indicator stack initialization (all 5 assets per agent)
2. Check kalshi_mode=True in IndicatorConfig
3. Verify velocity thresholds are appropriate
4. Check logs for signal generation failures

#### Issue: Orders blocked by window limit

**Symptoms**: Orders rejected with "total_venue_window_limit"

**Possible Causes**:
1. Window exposure tracking stuck
2. Resting orders accumulating
3. Peak bankroll fluctuation

**Solutions**:
1. Force reset window exposure
2. Cancel resting orders
3. Check peak bankroll at window start

#### Issue: WebSocket not connecting

**Symptoms**: WebSocket health shows error, no market data

**Possible Causes**:
1. Network connectivity issue
2. Kalshi API credentials invalid
3. Circuit breaker open

**Solutions**:
1. Check network connectivity
2. Verify API credentials
3. Check circuit breaker status
4. Restart server

#### Issue: Health check failing

**Symptoms**: /api/health returns 503

**Possible Causes**:
1. Kill switch active
2. Circuit breaker open
3. Agent grid not ready
4. MeridLoop stopped

**Solutions**:
1. Check kill switch status
2. Check circuit breaker status
3. Verify agent grid startup
4. Check MeridLoop status

### Debug Mode

Enable debug logging:
```python
import logging
logging.getLogger("merid").setLevel(logging.DEBUG)
```

### Diagnostic Tools

- **Health check**: `http://localhost:8011/api/health`
- **WebSocket health**: `http://localhost:8011/api/websocket/health`
- **Agent health**: `http://localhost:8011/api/v1/agents/health`
- **Event loop profiles**: `http://localhost:8011/health/event_loop/profiles`

## References

### Documentation Files

- **Agent Grid**: `docs/15M_AGENT_GRID_DOCUMENTATION.md`
- **Market Data Pipeline**: `docs/15M_MARKET_DATA_PIPELINE_DOCUMENTATION.md`
- **Signal Generation**: `docs/15M_SIGNAL_GENERATION_DOCUMENTATION.md`
- **Risk Management**: `docs/15M_RISK_MANAGEMENT_DOCUMENTATION.md`
- **Execution Pipeline**: `docs/15M_EXECUTION_PIPELINE_DOCUMENTATION.md`
- **Monitoring**: `docs/15M_MONITORING_ALERTING_DOCUMENTATION.md`
- **High Leverage Bugs**: `docs/15M_HIGH_LEVERAGE_BUGS_REPORT.md`

### Key Source Files

- **Entry Point**: `web/main_15m_lean.py`
- **Agent Grid**: `merid/prediction/agent_grid_15m.py`
- **Indicators**: `merid/signals/crypto_15m_indicators.py`
- **Risk Envelope**: `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py`
- **Global Allocator**: `merid/risk/profiles/global_allocator.py`
- **Order Gate**: `merid/event_venues/kalshi/order_gate.py`
- **Order Router**: `merid/event_venues/kalshi/order_router.py`
- **WebSocket**: `merid/event_venues/kalshi/ws.py`
- **Position Cache**: `merid/event_venues/kalshi/position_cache.py`
- **Health Monitor**: `core/health.py`
- **Health API**: `web/api/health.py`

### Configuration Files

- **Profile**: `config/profiles/kalshi_crypto_15m_v2.yaml`
- **Environment**: `config/profiles/env.prod.kalshi-pm.live.example`
- **Thresholds**: `config/kalshi_15m_thresholds.yaml`

## Appendix

### Asset Symbols

- **BTC**: Bitcoin
- **ETH**: Ethereum
- **SOL**: Solana
- **XRP**: Ripple
- **DOGE**: Dogecoin

### Critical Constants

- **Total exposure cap**: $1.00
- **Trading cadence**: 5 seconds
- **REST sync frequency**: 30 seconds
- **WebSocket queue size**: 32768
- **Window duration**: 900 seconds (15 minutes)
- **Price repeat window**: 900 seconds (15 minutes)
- **Decision bucket width**: 5 seconds (15m agents)

### Version History

- **v20260529a**: Operation mode support for daily loss limit
- **v20260706**: Window tracking state fix, FVG consolidation
- **v20260708**: Peak bankroll fix, resting order exposure, sequential trading
- **v20260710**: Per-agent/asset limit disabled, edge threshold alignment

### Support

For issues or questions:
1. Check this documentation
2. Review logs for error messages
3. Check health endpoints for system status
4. Review high leverage bugs report for known issues
