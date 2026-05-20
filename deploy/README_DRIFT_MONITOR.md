# Kalshi Live Drift Monitor Deployment

## Overview

The Kalshi Live Drift Monitor (`scripts/kalshi_live_drift_monitor.py`) periodically pulls live positions and fills from Kalshi, replays them in isolation, and runs reconciliation to detect API or behavior drift.

## Systemd Deployment

### Install Service and Timer

```bash
# Copy unit files to systemd directory
sudo cp deploy/kalshi-drift-monitor.service /etc/systemd/system/
sudo cp deploy/kalshi-drift-monitor.timer /etc/systemd/system/

# Reload systemd daemon
sudo systemctl daemon-reload

# Enable and start the timer
sudo systemctl enable kalshi-drift-monitor.timer
sudo systemctl start kalshi-drift-monitor.timer

# Verify status
sudo systemctl status kalshi-drift-monitor.timer
sudo systemctl list-timers | grep kalshi-drift
```

### Configuration

The monitor reads environment variables from `/opt/merid/.env`:

- `KALSHI_API_KEY_ID` - Kalshi API key ID
- `KALSHI_PRIVATE_KEY_PATH` - Path to Kalshi private key
- `DRIFT_MONITOR_MINUTES` - Time window for fills replay (default: 10)
- `DRIFT_MONITOR_SUBACCOUNT` - Subaccount to monitor (optional, defaults to main)

### Manual Testing

Run the monitor once to verify configuration:

```bash
cd /opt/merid
.venv/bin/python scripts/kalshi_live_drift_monitor.py --once --minutes=10
```

Expected output:
- `OK` - No discrepancies detected
- `DRIFTING` - Discrepancies found (check logs for details)
- `ERROR` - API or system error (check logs)

### Monitoring Logs

```bash
# View recent logs
journalctl -u kalshi-drift-monitor.service -n 50 -f

# View timer activation logs
journalctl -u kalshi-drift-monitor.timer -n 50
```

## Alerting Integration

The drift monitor returns a status that can be wired to alerting systems:

### PagerDuty Integration

Add to your alert routing rules:
- Trigger alert when `status == DRIFTING` for 3 consecutive runs
- Include discrepancy count and worst delta in alert details
- Route to on-call rotation for Kalshi trading

### Slack Integration

Post to Slack channel when:
- Status transitions from OK → DRIFTING
- Critical discrepancy count exceeds threshold
- API errors occur (rate limits, auth failures)

Example webhook payload:
```json
{
  "status": "DRIFTING",
  "discrepancy_count": 3,
  "worst_delta": 5.0,
  "asset_breakdown": {
    "BTC": {"count": 2, "worst_delta": 5.0},
    "ETH": {"count": 1, "worst_delta": 2.0}
  },
  "timestamp": "2026-05-16T22:30:00Z"
}
```

## Troubleshooting

### Timer Not Running

```bash
# Check if timer is enabled
sudo systemctl is-enabled kalshi-drift-monitor.timer

# Check if timer is active
sudo systemctl is-active kalshi-drift-monitor.timer

# View timer schedule
systemctl show kalshi-drift-monitor.timer --property=NextElapseUSecMonotonic
```

### Service Failing

```bash
# View service logs for errors
journalctl -u kalshi-drift-monitor.service -n 100 --no-pager

# Test manually with verbose output
.venv/bin/python scripts/kalshi_live_drift_monitor.py --once --minutes=10 --verbose
```

### Rate Limit Issues

If you see rate limit errors:
- Increase `DRIFT_MONITOR_MINUTES` to reduce API call frequency
- Increase timer interval in `kalshi-drift-monitor.timer` (e.g., change to `*:0/15` for every 15 minutes)
- Check Kalshi rate limits at https://docs.kalshi.com/getting_started/rate_limits

## Maintenance

### Update Monitor Script

After updating `scripts/kalshi_live_drift_monitor.py`:

```bash
# Reload service (no restart needed for oneshot)
sudo systemctl daemon-reload
```

### Adjust Schedule

Edit `deploy/kalshi-drift-monitor.timer` and reload:

```bash
sudo cp deploy/kalshi-drift-monitor.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart kalshi-drift-monitor.timer
```

### Disable Monitor

```bash
sudo systemctl stop kalshi-drift-monitor.timer
sudo systemctl disable kalshi-drift-monitor.timer
```

## Related Documentation

- Runbook: `docs/audit/KALSHI_RECONCILIATION_AUDIT.md` - "When Kalshi Reconciliation Breaks" section
- Metrics API: `GET /api/v1/reconciliation/metrics`
- Kalshi API docs: https://docs.kalshi.com
- Kalshi status: https://status.kalshi.com
