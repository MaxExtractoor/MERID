# MERID Go-Live Checklist

**Paper → Live Cutover Guide**

## Pre-Flight Checks

### 1. Configuration Validation

```bash
# Validate all settings
make validate-config

# Expected output for paper mode:
# Mode: paper
# Env: development
# Ready: True
```

### 2. Environment Variables

| Variable | Paper | Live | Description |
|----------|-------|------|-------------|
| `MERID_TRADING_MODE` | `paper` | `live` | Trading mode |
| `MERID_LIVE_TRADING_UNLOCKED` | `false` | `true` | Explicit unlock |
| `MERID_ENV` | `development` | `production` | Environment |

### 3. Safety Interlocks

| Setting | Default | Recommended Live | Description |
|---------|---------|------------------|-------------|
| `MERID_MAX_ORDER_SIZE_USD` | 100 | Start with 100 | Max single order |
| `MERID_MAX_DAILY_LOSS_USD` | 500 | Start with 500 | Daily loss limit |
| `MERID_MAX_POSITION_SIZE_USD` | 1000 | Start with 1000 | Max position per market |
| `MERID_REQUIRE_CONFIRMATION` | true | Keep true initially | Order confirmation |

---

## Paper Trading Phase

### Step 1: Run Dry-Run

```bash
make go-live-dry-run
```

This validates:
- [ ] Configuration is correct
- [ ] Paper trading smoke tests pass
- [ ] Order flow simulation works

### Step 2: Extended Paper Test (1-7 days)

Run MERID in paper mode with real market data:

```bash
# Start paper trading
MERID_TRADING_MODE=paper python -m merid.run
```

Verify:
- [ ] Orders execute correctly (simulated)
- [ ] Position tracking is accurate
- [ ] P&L calculations are correct
- [ ] No errors in logs
- [ ] Circuit breakers don't trip unexpectedly

### Step 3: Review Paper Results

Before going live, ensure:
- [ ] Paper P&L is reasonable (not too good to be true)
- [ ] Slippage estimates are realistic
- [ ] No unexpected errors or warnings

---

## Go-Live Phase

### Step 1: Credential Setup

For each venue you want to trade:

**Kalshi:**
```bash
export KALSHI_API_KEY_ID="your-key"
export KALSHI_PRIVATE_KEY_PATH="/path/to/key.pem"
# OR
export KALSHI_PRIVATE_KEY_PEM="-----BEGIN PRIVATE KEY-----..."
```

**Polymarket:**
```bash
export POLYMARKET_API_KEY="your-key"
export POLYMARKET_API_SECRET="your-secret"
export POLYMARKET_WALLET_ADDRESS="0x..."
export POLYMARKET_PRIVATE_KEY="your-private-key"
```

**Alpaca:**
```bash
export ALPACA_API_KEY="your-key"
export ALPACA_API_SECRET="your-secret"
```

### Step 2: Validate Credentials

```bash
make validate-config
```

All credential errors should be resolved.

### Step 3: Set Conservative Limits

Start with conservative limits:

```bash
export MERID_MAX_ORDER_SIZE_USD=50      # Small orders first
export MERID_MAX_DAILY_LOSS_USD=100     # Tight loss limit
export MERID_MAX_POSITION_SIZE_USD=200  # Small positions
export MERID_REQUIRE_CONFIRMATION=true  # Require confirmation
```

### Step 4: Unlock Live Trading

```bash
export MERID_TRADING_MODE=live
export MERID_LIVE_TRADING_UNLOCKED=true
```

### Step 5: Final Validation

```bash
make validate-config
# Should show:
# Mode: live
# Ready: True
```

### Step 6: Start with Monitoring

```bash
# Run with verbose logging
MERID_LOG_LEVEL=DEBUG python -m merid.run
```

Monitor:
- [ ] First orders execute correctly
- [ ] Fills are reported accurately
- [ ] No unexpected errors

---

## Rollback Procedure

If issues occur:

### Immediate Stop

```bash
# Kill the process
Ctrl+C

# Or set mode back to paper
export MERID_TRADING_MODE=paper
export MERID_LIVE_TRADING_UNLOCKED=false
```

### Cancel Open Orders

```python
from merid.event_venues.kalshi.client import KalshiVenueClient

client = KalshiVenueClient()
await client.connect()
orders = await client.get_open_orders()
for order in orders:
    await client.cancel_order(order.order_id)
```

### Review Logs

Check logs for errors:
```bash
grep -i error logs/merid.log
grep -i circuit logs/merid.log  # Circuit breaker trips
```

---

## Post-Go-Live Monitoring

### Daily Checks

- [ ] Review P&L
- [ ] Check for circuit breaker trips
- [ ] Verify position accuracy
- [ ] Monitor latency metrics

### Gradual Limit Increases

After 1 week of stable operation:
```bash
export MERID_MAX_ORDER_SIZE_USD=100
export MERID_MAX_DAILY_LOSS_USD=250
```

After 1 month:
```bash
export MERID_MAX_ORDER_SIZE_USD=500
export MERID_MAX_DAILY_LOSS_USD=1000
```

---

## Quick Reference

| Command | Description |
|---------|-------------|
| `make validate-config` | Validate all settings |
| `make go-live-dry-run` | Full dry run (no real orders) |
| `make show-mode` | Show current trading mode |
| `make smoke-test` | Run smoke tests |

## Safety Reminders

1. **Start small** - Use conservative limits initially
2. **Monitor closely** - Watch first few trades
3. **Keep confirmation on** - Don't disable `MERID_REQUIRE_CONFIRMATION`
4. **Know how to stop** - Have rollback procedure ready
5. **Check circuit breakers** - Review `get_circuit_status()` regularly

---

## Hard Risk Switches

MERID includes hard safety controls that automatically halt trading when limits are breached.

### Kill Switch Types

| Switch | Trigger | Recovery |
|--------|---------|----------|
| **Global Kill** | Manual `emergency_stop()` | Manual `reset()` |
| **Daily Loss** | P&L < -`MERID_MAX_DAILY_LOSS_USD` | New trading day (UTC) |
| **Position Limit** | Total positions > limit | Manual `reset()` |
| **Error Threshold** | >10 errors/hour | Manual `reset()` |

### Using Kill Switches

```python
from merid.risk import can_trade, emergency_stop, get_risk_status, risk_controller

# Check before every trade
if not can_trade():
    print("Trading halted!")
    print(get_risk_status())

# Emergency stop (manual)
emergency_stop("Operator intervention - suspicious activity")

# Check status
status = get_risk_status()
# {
#   'state': 'triggered',
#   'kill_reason': 'daily_loss',
#   'daily_pnl': -520.0,
#   'daily_loss_limit': 500.0,
#   'daily_pnl_pct': 104.0,
#   ...
# }

# Reset after investigation (requires explicit call)
risk_controller.reset(operator="chris")
```

### Monitoring Kill Switches

Add to your monitoring dashboard:

```python
from merid.risk import get_risk_status

def check_risk_health():
    status = get_risk_status()
    
    # Alert if close to limits
    if status["daily_pnl_pct"] > 80:
        alert(f"Daily loss at {status['daily_pnl_pct']:.0f}% of limit")
    
    # Alert if killed
    if status["state"] == "triggered":
        alert(f"TRADING HALTED: {status['kill_reason']}")
```

### Kill Switch Callbacks

Register callbacks for alerts:

```python
from merid.risk import risk_controller, KillSwitchEvent

def on_kill(event: KillSwitchEvent):
    send_telegram(f"🚨 KILL SWITCH: {event.reason} - {event.details}")
    send_email("Trading Halted", str(event))

risk_controller.on_kill(on_kill)
```

### Integration with Resilience Layer

Kill switches integrate with circuit breakers:

```python
from merid.risk import risk_controller
from merid.resilience import get_all_breakers

# Check if all venues are circuit-broken
breakers = get_all_breakers()
all_open = all(b.state.value == "open" for b in breakers.values())

if all_open:
    risk_controller.emergency_stop("All venues circuit-broken")
```

---

## Operator Notes

*Rough edges discovered during operator testing (2026-02-04):*

### Windows Users

**Issue**: `make` is not available on Windows by default.

**Workaround**: Run the Python commands directly:

```powershell
# Instead of: make validate-config
python -c "from merid.settings import settings; r = settings.validate_for_go_live(); print('Mode:', r['mode']); print('Env:', r['env']); print('Ready:', r['ready']); [print('  ERROR:', i) for i in r['issues']]; [print('  WARN:', w) for w in r['warnings']]"

# Instead of: make show-mode
python -c "from merid.settings import settings; print(f'Trading Mode: {settings.MERID_TRADING_MODE}'); print(f'Live Unlocked: {settings.MERID_LIVE_TRADING_UNLOCKED}')"

# Instead of: make smoke-test
pytest tests/smoke/ -m smoke -q --tb=short

# Instead of: make run-paper-demo
python scripts/run_paper_demo.py
```

**Alternative**: Install `make` via Chocolatey (`choco install make`) or use WSL.

### pytest Warnings

**Issue**: `PytestUnknownMarkWarning` for `@pytest.mark.smoke`

**Fix**: Register the mark in `pytest.ini` or `pyproject.toml`:
```ini
[pytest]
markers =
    smoke: marks tests as smoke tests
    e2e: marks tests as end-to-end tests
```

### Neo4j Deprecation Warning

**Issue**: `DeprecationWarning` about Neo4j driver session closing.

**Status**: Non-blocking. Will be fixed in a future Neo4j driver update. Can be suppressed with:
```python
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning, module="neo4j")
```

### Credential Validation

**Note**: `validate-config` will show errors for venues you don't plan to use. To validate only specific venues:

```python
from merid.settings import settings
result = settings.validate_for_go_live(venues=["kalshi"])  # Only check Kalshi
```

### Circuit Breaker Inspection

To check circuit breaker status for a venue client:

```python
from merid.event_venues.kalshi.client import KalshiVenueClient
client = KalshiVenueClient()
print(client.get_circuit_status())
# {'name': 'kalshi_...', 'state': 'closed', 'failure_count': 0, ...}
```

### Dry-Run Flag

**Note**: The `--dry-run` flag for `run_paper_demo.py` is not yet implemented. Paper mode already simulates trades without real execution, so this is functionally equivalent.
