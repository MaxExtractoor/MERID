# MERID Paper Trading Quick Start Checklist

Clean logging, noise-controlled paper trading sessions for MERID.

## Prerequisites

- Alpaca paper trading API keys in `.env`
- `PREDICTION_CONNECTOR_STRICT_ERRORS=false` (recommended for clean logs)
- Python 3.11+ with required dependencies

## Environment Setup

```bash
# Set connector logging to warnings (rate-limited, less noise)
export PREDICTION_CONNECTOR_ERRORS=false

# Or for strict error logging (debugging only)
# export PREDICTION_CONNECTOR_ERRORS=true
```

## Startup Sequence

### 1. Initialize Paper Trading
```bash
python scripts/setup_paper_trading.py
```

### 2. Validate Real Data
```bash
python scripts/validate_real_data.py
# Expect: 6/6 tests passed, no synthetic data
```

### 3. Start MERID Core
```bash
python start_merid.py \
  --mode paper \
  --symbols AAPL,MSFT \
  --strategies drift \
  --venues alpaca \
  --notional 1000 \
  --session-duration 1800
```

### 4. Start Web Interface
```bash
uvicorn web.main:app --port 8011
```

## Verification Checks

- [ ] Brier/Phase 0 tables initialize cleanly
- [ ] Neo4j shows clean warning (no NameError)
- [ ] `/api/v1/paper/session/state` returns JSON with `lifecycle: "OFFLINE"`
- [ ] `/readyz` returns `{"status":"ready","synthetic_mode":false}`
- [ ] Prediction market logs show warnings only (rate-limited)
- [ ] Health monitor logs every 5 minutes max (not every 30 seconds)

## Expected Log Behavior

### Prediction Market Connectors
- **Normal**: Rate-limited warnings every 60 seconds per connector
- **Strict mode**: Errors logged every 30 seconds (debug only)

### Health Monitor
- System health status logged every 5 minutes maximum
- Reduces noise from recurring health issues

## Monitoring

### Web Interfaces
- **Main UI**: http://127.0.0.1:3000
- **API Docs**: http://127.0.0.1:8011/docs
- **Ops/Admin**: http://127.0.0.1:9090
- **Telemetry**: http://127.0.0.1:9091/metrics

### Key Endpoints
- `/api/v1/paper/session/state` - Session lifecycle
- `/api/v1/system/health` - System health
- `/readyz` - Readiness check
- `/api/v1/institutional/predictions/*` - Real prediction data

## Session Duration

- **Short test**: 30 minutes (1800 seconds)
- **Extended**: 60+ minutes for full observation
- Monitor: decisions, orders/fills, PnL, risk guardrails, alerts

## Shutdown Sequence

### 1. Flatten Positions
```bash
# Cancel all open orders and close positions via Alpaca API
# Or use the web interface to flatten
```

### 2. Stop MERID Processes
```bash
# Stop start_merid.py process (Ctrl+C or kill)
# Stop uvicorn process (Ctrl+C or kill)
```

### 3. Verify Clean Shutdown
- No open orders in Alpaca
- All processes terminated
- Logs show graceful shutdown

## Troubleshooting

### Log Noise Issues
- Set `PREDICTION_CONNECTOR_ERRORS=false` for warnings
- Check health monitor rate limiting (5-minute intervals)

### Synthetic Data Detection
- Run `validate_real_data.py` to confirm real data usage
- Check `/readyz` endpoint for `synthetic_mode: false`

### Port Conflicts
- Kill existing processes: `taskkill /F /PID <PID> /T`
- Check port usage: `netstat -ano | findstr LISTENING`

## Production Notes

- Default configuration uses rate-limited warnings for production
- Strict error mode reserved for debugging connector issues
- Health monitor rate limiting prevents log spam in production
- All changes preserve full error visibility when needed
