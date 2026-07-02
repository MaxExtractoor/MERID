# Dry-Run / Simulated-Trades Mode

## Overview

Dry-run mode allows you to test configuration changes and strategy adjustments with real market data without submitting actual orders to Kalshi. This is critical for safely tuning parameters like Kelly fraction, edge thresholds, and per-asset caps before running them live.

## Execution Modes

MERID supports three execution modes:

- **normal**: Default mode. Submits real orders to Kalshi API.
- **dry_run**: Logs "would-submit" events without placing real orders. Full routing logic executes (sizing, gate, execution checks), but no actual orders are submitted.
- **simulate**: Same as dry_run, but optionally schedules simulated fills after a delay (e.g., 5-10 seconds) to update PnL, exposure, and reconciliation as if orders filled.

## Configuration

Set the execution mode via environment variable:

```bash
export MERID_EXECUTION_MODE=dry_run  # or "simulate"
```

Or in your `.env` file:

```
MERID_EXECUTION_MODE=dry_run
```

## Usage

### Testing Config Changes

1. **Baseline**: Run in dry-run mode with current config (v2.0.0)
   ```bash
   MERID_EXECUTION_MODE=dry_run python web/main_15m_lean.py
   ```

2. **Tune parameters**: Modify `config/profiles/kalshi_crypto_15m.yaml`
   - Bump profile version to v2.1.0
   - Adjust Kelly fraction from 0.30 to 0.32
   - Tighten min_edge_mid from 2.0% to 2.2%

3. **Compare**: Run dry-run again with new config
   ```bash
   MERID_EXECUTION_MODE=dry_run python web/main_15m_lean.py
   ```

4. **Analyze**: Compare order volumes, edge rejection rates, and fill-rate metrics between v2.0.0 and v2.1.0 dry-run runs.

5. **Deploy**: If results look good, switch to normal mode for live trading:
   ```bash
   MERID_EXECUTION_MODE=normal python web/main_15m_lean.py
   ```

### Startup Validation

The system validates execution mode at startup and warns if running in dry-run mode with live trading enabled:

```
[DRY-RUN-WARNING] Running in LIVE mode with dry-run execution (MERID_EXECUTION_MODE=dry_run). 
No real orders will be submitted to Kalshi. This is safe for testing config changes, 
but ensure you understand the difference between dry-run and live execution.
```

## Logging

Dry-run mode logs detailed "would-submit" events:

```
[DRY-RUN-EXECUTION] mode=dry_run | ticker=KXBTC-15M-20260523-2330 | side=yes | action=buy | 
price=49¢ | count=10 | notional=490¢ | client_tag=agent_BTC_15M_cycle_123 | order_group_id=group_456
```

## Metrics

Dry-run mode tracks separate Prometheus metrics:

- `merid_dry_run_orders_total` - Total dry-run orders (simulated submission)
- `merid_simulated_fills_total` - Total simulated fills (dry-run mode with fill simulation)
- All order lifecycle metrics include `execution_mode` label (normal/dry_run/simulate)

This allows comparing dry-run vs live order volumes in Grafana.

## Session Snapshots

Session snapshots include the execution mode for run documentation:

```json
{
  "run_id": "abc-123",
  "profile_version": "2.1.0",
  "profile_name": "kalshi_crypto_15m_v2",
  "execution_mode": "dry_run",
  "fill_statistics": { ... }
}
```

## Simulated Fills (TODO)

The `simulate` mode includes a placeholder for scheduling simulated fills after a delay. This would:

1. Log "would schedule simulated fill" after dry-run submission
2. Schedule a task to simulate fill after 5-10 seconds
3. Update PnL, exposure, and reconciliation as if the order filled
4. Track simulated fills via `merid_simulated_fills_total` counter

This is not yet implemented but the infrastructure is in place.

## Safety Considerations

- **Dry-run in live mode**: The system warns if running dry-run with `MERID_PM_TRADING_MODE=live` and `MERID_ALLOW_LIVE_TRADES=true`. This is safe for testing but ensure you understand the difference.
- **No real exposure**: Dry-run mode never touches Kalshi API or real capital.
- **Full logic execution**: All routing logic (sizing, gate, execution checks) still executes, so you get realistic order volume and rejection metrics.

## API Endpoint

Get the current execution mode via API:

```bash
GET /api/v1/config/profile_version
```

Returns:
```json
{
  "profile_name": "kalshi_crypto_15m_v2",
  "profile_version": "2.1.0",
  "description": "Config-only risk model for 15m crypto prediction markets on Kalshi",
  "loaded_at": "2026-05-23T22:30:00Z"
}
```

Note: The execution mode is logged in session snapshots but not exposed via a dedicated API endpoint yet. It can be inferred from the snapshot data.

## Comparison with Paper Mode

- **Paper mode**: Uses a local matching engine, no Kalshi API dependency. Good for testing without market data.
- **Dry-run mode**: Uses real market data from Kalshi, routes through full stack, but doesn't submit orders. Good for testing config changes with realistic market conditions.
- **Live mode**: Real money, real fills, real exposure.

## Troubleshooting

### Orders not submitting in dry-run mode

This is expected behavior. Dry-run mode logs "would-submit" events but never calls `client.place_order_result()`. Check logs for `[DRY-RUN-EXECUTION]` entries.

### Metrics not showing dry-run orders

Ensure Prometheus metrics are being scraped and that the `execution_mode` label is being applied. Check Grafana queries include the `execution_mode` label.

### Session snapshot not showing execution mode

Check that `merid/settings.py` is loading the `MERID_EXECUTION_MODE` environment variable correctly. Verify the startup log shows `[EXECUTION-MODE] mode=...`.
