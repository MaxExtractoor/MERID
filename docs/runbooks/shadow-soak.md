# MERID CF-RTI Paper / Shadow Soak Runbook

This runbook defines a reproducible, versioned paper/shadow soak for the
CF Benchmarks RTI 15-minute Kalshi crypto stack. It is intentionally thin:
the durable control plane is `scripts/shadow_report.py`, and this procedure
wraps it.

## 1. Soak environment

Use the dedicated `.env.shadow` file and load it after the base `.env` so the
soak overrides take precedence.  The file is checked into the repo with no real
API keys; Kalshi credentials are taken from the base `.env` or the process
environment.

```text
MERID_CFB_RTI_ADAPTER=true
MERID_CFB_RTI_SOURCE=kalshi_ws
MERID_ALLOW_LIVE_TRADES=false
MERID_PM_TRADING_MODE=paper
MERID_CFB_RTI_SHADOW_TELEMETRY=1
MERID_ENABLE_LEGACY_095_SENTINEL_TRAP=1
```

- `MERID_CFB_RTI_SOURCE=kalshi_ws` uses the authenticated Kalshi
  `cfbenchmarks_value` WebSocket as the primary (and only) RTI source.
- `MERID_CFB_RTI_SOURCE=both` enables the optional direct CF Benchmarks REST
  key as a fallback; set `MERID_CFB_RTI_API_KEY` from your secret store.
- `MERID_CFB_RTI_SOURCE=direct` forces the direct REST key and skips the
  Kalshi WebSocket.

Freeze the following before the first observation:

```powershell
$rev      = git rev-parse HEAD
$envHash  = Get-FileHash .env.shadow
$configHash = Get-FileHash config\profiles\kalshi_crypto_15m_v2.yaml
$runId    = "shadow_$(Get-Date -Format 'yyyyMMdd_HHmmss')_$(git rev-parse --short HEAD)"
$env:MERID_RUN_ID = $runId
```

Do not change the config, thresholds, or revision mid-run. If any change is
required, stop the process and start a new versioned segment with a new
`run_id`.

## 2. Pre-launch verification

Run the focused preflight script before any soak segment:

```powershell
$env:PYTHONPATH='C:\Dev\MERID'
.\.venv\Scripts\python.exe data\shadow\artifacts\preflight_startup_path.py
```

It must report:

- `startup safety validation passed`
- `live-trading safety validation passed`
- `RTI PASS all 5 assets observed`
- `paper mode confirmed`
- `live trading confirmed disabled`

Then verify the manifest against the working tree:

```powershell
$env:PYTHONPATH='C:\Dev\MERID'
.\.venv\Scripts\python.exe data\shadow\artifacts\verify_soak_manifest.py `
  data\shadow\artifacts\shadow_soak_manifest_*.json
```

It must print `ALL HASHES MATCH` for the current manifest. If any file has
changed since the manifest was written, the hash check fails and the segment
must not start until the manifest is regenerated.

### PostgreSQL is required

`.env.shadow` sets `MERID_POSTGRES_REQUIRED=true`. When this is set,
`merid.startup_validations.validate_postgres_liveness()` is called by
`validate_production_startup()` and `merid/event_venues/kalshi/fills_ledger.py`
and `merid/event_venues/kalshi/portfolio_event_log.py` will raise `RuntimeError`
instead of silently falling back to SQLite. A PostgreSQL outage therefore halts
the soak rather than producing an incomplete audit record.

## 3. Launch

```powershell
# Activate the virtual environment
. .\venv\Scripts\Activate.ps1

# Set the CF Benchmarks API key from your secret store
$env:CFB_API_KEY = "<from-secret-store>"

# Load base .env, then the shadow overrides (override=False in merid/settings.py,
# so values already in the process environment win over the repo .env)
Get-Content .\.env | ForEach-Object { if ($_ -match '^([^#][^=]+)=(.*)$') { $n=$matches[1].Trim(); $v=$matches[2].Trim(); if ($n -and $v) { [Environment]::SetEnvironmentVariable($n, $v, 'Process') } } }
Get-Content .\.env.shadow | ForEach-Object { if ($_ -match '^([^#][^=]+)=(.*)$') { $n=$matches[1].Trim(); $v=$matches[2].Trim(); if ($n -and $v) { [Environment]::SetEnvironmentVariable($n, $v, 'Process') } } }

# Generate and persist the startup record
$startRecord = [ordered]@{
    record_type = "shadow_soak_start"
    run_id = $runId
    started_at_utc = (Get-Date -Format o)
    git_revision = $rev
    env_hash = $envHash.Hash
    config_hash = $configHash.Hash
    cf_rti_adapter_enabled = $true
    live_trades_enabled = $false
    trading_mode = "paper"
    shadow_telemetry_enabled = $true
    legacy_095_sentinel_trap_enabled = $true
    enabled_assets = @("BTC", "ETH", "DOGE", "SOL")
    final_minute_cutoff_s = 60
}
$startRecord | ConvertTo-Json -Depth 4 | Set-Content -Path "data\shadow\startup_record_${runId}.json" -Encoding utf8

# Launch the 15m lean web server (the only supported entry point)
$env:MERID_RUN_ID = $runId
. .\.venv\Scripts\python.exe -m uvicorn web.main_15m_lean:app --host 127.0.0.1 --port 8011 --log-level info
```

Verify that `data/shadow/cfb_rti/` is receiving at least one record per
trading cycle. Records are emitted as either `.json` or `.jsonl` and must
contain:

- `schema_version`: 1
- `record_type`: `candidate` | `order` | `settlement`
- `run_id`, `decision_id`, `timestamp_utc`, `ticker`, `asset`
- RTI fields: `settlement_reference`, `cfb_symbol`, `cfb_value`, `cfb_age_ms`
- Decision fields: `p_yes`, `p_no`, `p_selected`, `net_edge`, `confidence`, `confidence_valid`, `confidence_source`
- Book fields: `yes_bid_cents`, `yes_ask_cents`, `no_bid_cents`, `no_ask_cents`, `fee_per_contract_cents`
- Side fields: `selected_outcome`, `selected_action`, `selected_outcome_price`

## 3. Monitor live stop conditions

Stop the soak immediately if any of the following are observed:

- A paper-eligible candidate with `settlement_reference` not equal to `cfb_rti_live`.
- A paper-eligible candidate with invalid or non-`uncertainty_engine` confidence.
- A paper-eligible candidate with `p_selected <= 0.50`.
- A side / V2 book side / economic-exposure mismatch.
- An admitted candidate inside the final-minute cutoff.
- A paper order with no terminal status, an orphan open position, or an
  unreconciled `UNMATCHED_FILL`.
- A replay of a stored record that does not reproduce the original
  probability or net edge.

## 4. End-of-segment report

When the segment has covered a complete set of contract lifecycles, stop the
process and run the shadow report in strict mode:

```powershell
python scripts/shadow_report.py `
  --input data/shadow/cfb_rti `
  --output data/shadow/reports `
  --run-id $runId `
  --strict `
  --format both
```

Artifacts are written to `data/shadow/reports/`:

```text
shadow_report_<run_id>_<utc>.json
shadow_report_<run_id>_<utc>.txt
```

## 5. Pass / fail

Use the script exit code as a hard gate:

| Exit code | Meaning |
|---|---|
| 0 | No hard safety violation found |
| 1 | Input/schema/parsing failure |
| 2 | Invalid settlement provenance reached a paper intent |
| 3 | Invalid confidence provenance reached a paper intent |
| 4 | `p_selected <= 0.50` reached a paper intent |
| 5 | Side / V2 book side / inventory mismatch |
| 6 | Final-minute entry admitted |
| 7 | Unreconciled lifecycle, duplicate intent, or orphan exposure |
| 8 | Edge accounting mismatch |
| 9 | Replay mismatch |
| 10 | Calibration / P&L thresholds not met (only with `--enforce-performance`) |

The report must exit 0 before any calibration or P&L evaluation. Do not
override a non-zero exit code by running the report again in permissive mode.

## 6. Preserve evidence

After a passing run, keep:

- The JSON and text reports.
- The raw telemetry files under `data/shadow/cfb_rti/`.
- The `.env.shadow` snapshot, config hash, and Git revision.
- Any `data/risk_kill_switch.json` or `data/trading_circuit_breaker_*.json`
  state files from the segment.

## 7. Calibration and economics

Only after a clean `exit 0` segment evaluate:

- Expected net edge vs. realized paper P&L.
- Brier score and log loss by probability bucket.
- RTI age p50 / p95 / p99 / max.
- Side and time-to-expiry buckets.

Do not move beyond paper mode until the report is green and calibration /
post-cost expectancy are positive across an adequate sample size.
