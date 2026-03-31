# Kalshi Crypto Live-Trading Readiness Implementation

## Overview

This document summarizes the implementation of the comprehensive live-trading readiness checklist system for Kalshi crypto markets, as specified in the problem statement.

## What Was Implemented

### 1. Comprehensive Readiness Script

**File**: `scripts/kalshi_crypto_live_readiness.py`

A comprehensive Python script that validates ALL 5 sections required for live-trading readiness:

#### Section 1: Environment and Mode Sanity Checklist
- ✅ Validates all Kalshi-related environment variables (API credentials, base URL, environment mode)
- ✅ Validates CF Benchmarks RTI configuration (poll URL, API key, adapter type)
- ✅ Validates trading mode toggles (MERID_PM_TRADING_MODE, MERID_PM_LIVE_ENABLED, MERID_LIVE_TRADING_UNLOCKED)
- ✅ Outputs environment variable table with Name, Purpose, Allowed Values, Required in Live?, Valid?, Issue
- ✅ Distinguishes between live vs demo keys
- ✅ Enforces CFB RTI requirement when KALSHI_ENV=live

#### Section 2: Formula and Sizing Conflicts
- ✅ Enumerates all sizing-related formulas (Kelly, per-asset caps, portfolio cap, confidence thresholds)
- ✅ Validates per-asset risk profiles for BTC, ETH, SOL, XRP, DOGE
- ✅ Checks for formula conflicts and double-application of caps
- ✅ Validates per-asset vs global caps enforcement order
- ✅ Outputs formula table with Location, Type, Status (OK/CONFLICT/MISMATCH), Issue

#### Section 3: Agent Proposals, Confidence, and Hardcoding
- ✅ Maps proposal pipeline from agents through unified signal path
- ✅ Detects hardcoded confidence values vs derived confidence
- ✅ Validates YES/NO side selection logic
- ✅ Tags each proposal path: OK, HARD_CODED_CONFIDENCE, BYPASS_UNIFIED_PATH, YES_NO_LOGIC_RISKY
- ✅ Outputs agent table with Agent, Status, Confidence Source, Side Logic, Issue

#### Section 4: Market Coverage Matrix (Asset × Timeframe)
- ✅ Builds full 5×5 grid (BTC/ETH/SOL/XRP/DOGE × 15m/1h/daily/weekly/monthly)
- ✅ Validates 5 coverage dimensions for each market:
  - Catalog OK (market discovery)
  - Strategy OK (agent can generate proposals)
  - Sizing OK (risk engine computes contracts)
  - Execution OK (continuous trader can place order)
  - Monitor/Protect OK (metrics and kill switches track it)
- ✅ Outputs coverage table with Asset, Timeframe, all 5 checks, Notes

#### Section 5: Dry-Run Preflight
- ✅ Config/env validation (all required vars present and valid)
- ✅ Data feeds sanity check (CFB RTI connectivity when enabled)
- ✅ Sample dry-run trades across BTC/ETH/SOL markets
- ✅ UI state probe (mode indicators correct)
- ✅ Final LIVE_READY=YES/NO verdict with blocking failures list

### 2. Comprehensive Runbook

**File**: `docs/KALSHI_CRYPTO_LIVE_READINESS_RUNBOOK.md`

A 30+ page operator runbook covering:

- ✅ Quick start instructions
- ✅ Environment variable reference tables
- ✅ Canonical formulas documentation (Kelly, per-asset caps, portfolio caps)
- ✅ YES/NO side handling rules
- ✅ Agent proposal pipeline flow
- ✅ Market coverage matrix requirements
- ✅ Pre-launch checklist with step-by-step instructions
- ✅ Emergency procedures (kill switch, graceful shutdown, rollback)
- ✅ Monitoring and alerting recommendations
- ✅ Common issues and fixes

### 3. Integration with Existing Systems

The readiness script integrates with:
- ✅ `merid.settings` for environment variable validation
- ✅ `merid/event_venues/kalshi/crypto_kalshi_risk.py` for risk profile validation
- ✅ `merid/data/settlement_rti_buffer.py` for CFB RTI health checks
- ✅ `config/crypto_universe.py` for canonical asset/timeframe definitions
- ✅ `scripts/go_live_preflight.py` for complementary gate validation

## Key Features

### 1. Automated Validation
```bash
# Run full readiness check
python scripts/kalshi_crypto_live_readiness.py

# Verbose mode with detailed diagnostics
python scripts/kalshi_crypto_live_readiness.py --verbose

# Machine-readable JSON output
python scripts/kalshi_crypto_live_readiness.py --json
```

Exit codes:
- `0` = LIVE_READY=YES (all checks passed)
- `1` = LIVE_READY=NO (blocking failures)

### 2. Comprehensive Coverage

The script validates **25 distinct markets** (5 assets × 5 timeframes) across:
- Market discovery and catalog availability
- Strategy configuration and proposal generation
- Risk sizing and contract computation
- Order execution capability
- Monitoring and protection systems

### 3. Safety Interlocks

Multiple layers of safety validation:
1. **Environment variables**: Detect demo keys, missing credentials, wrong URLs
2. **Mode consistency**: Ensure KALSHI_ENV, MERID_PM_TRADING_MODE, and unlock flags are aligned
3. **CFB RTI enforcement**: Block live trading when settlement feed is unhealthy (KALSHI_ENV=live only)
4. **Formula conflicts**: Detect double-application of risk caps or inconsistent sizing
5. **Agent behavior**: Flag hardcoded confidence, bypassed unified paths, risky YES/NO logic

### 4. Clear Reporting

Example output:

```
SECTION 1: Environment and Mode Sanity Checklist
========================================================================================================================
Name                                     Purpose                        Required?  Valid?     Issue
------------------------------------------------------------------------------------------------------------------------
KALSHI_API_KEY_ID                        Kalshi API key identifier      Yes        ✓          -
KALSHI_PRIVATE_KEY_PATH                  Path to RSA private key       Yes        ✓          -
KALSHI_ENV                               Kalshi environment mode        Yes        ✓          -
MERID_CFB_RTI_ENABLED                    Enable CFB RTI feed           Yes        ✓          -
...

SECTION 4: Market Coverage Matrix
============================================================================================================================================
Asset    Timeframe    Catalog    Strategy   Sizing     Execution    Monitor    Notes
--------------------------------------------------------------------------------------------------------------------------------------------
BTC      15m          ✓          ✓          ✓          ✓            ✓          -
BTC      1h           ✓          ✓          ✓          ✓            ✓          -
...

========================================================================================================================
LIVE_READY=YES - All checks passed! Safe to enable live trading.
========================================================================================================================
```

## Files Modified/Created

### New Files
1. `scripts/kalshi_crypto_live_readiness.py` (850+ lines)
   - Complete 5-section readiness validation script
   - Color-coded output with ✓/✗/⚠ symbols
   - JSON output mode for automation

2. `docs/KALSHI_CRYPTO_LIVE_READINESS_RUNBOOK.md` (500+ lines)
   - Comprehensive operator manual
   - Environment variable reference
   - Formula documentation
   - Pre-launch checklist
   - Emergency procedures

3. `docs/KALSHI_CRYPTO_LIVE_READINESS_IMPLEMENTATION.md` (this file)
   - Implementation summary
   - Usage examples
   - Integration notes

### Existing Files (No Changes Required)
- `.env.example` — Already contains CFB RTI configuration section
- `scripts/go_live_preflight.py` — Complementary gate validation (Gates 1-9)
- `config/crypto_universe.py` — Canonical asset/timeframe definitions
- `merid/event_venues/kalshi/crypto_kalshi_risk.py` — Per-asset risk profiles

## Mapping to Problem Statement Requirements

| Problem Statement Section | Implementation | Status |
|---------------------------|----------------|--------|
| **1. Environment and mode sanity checklist** | Section 1 of readiness script | ✅ Complete |
| - Enumerate Kalshi env vars | `check_env_vars()` function | ✅ Complete |
| - Validate KALSHI_API_KEY_ID, KALSHI_API_KEY_SECRET | Credential validation | ✅ Complete (RSA key-based auth) |
| - Check KALSHI_API_BASE_URL for live vs demo | URL validation | ✅ Complete |
| - Validate KALSHI_ENV={sim, live} | Mode validation | ✅ Complete |
| - Enumerate CFB RTI env | CFB_RTI_* variables checked | ✅ Complete |
| - Require CFB for live trading | MERID_REQUIRE_CFB_FOR_LIVE_TRADING logic | ✅ Complete |
| - Risk & mode toggles | MERID_TRADING_MODE validation | ✅ Complete |
| - Output env var table | `print_env_var_table()` | ✅ Complete |
| **2. Formula and sizing conflicts** | Section 2 of readiness script | ✅ Complete |
| - Enumerate sizing formulas | `check_formulas()` function | ✅ Complete |
| - Kelly fraction | Kelly sizing validation | ✅ Complete |
| - Verify single application | Formula conflict detection | ✅ Complete |
| - Check for conflicts | Per-asset vs global cap order | ✅ Complete |
| - Per-asset vs global caps | Portfolio cap enforcement | ✅ Complete |
| - Yes/No side handling | Side selection validation | ✅ Complete |
| - Output formula table | `print_formula_table()` | ✅ Complete |
| **3. Agent proposals, confidence, and hardcoding** | Section 3 of readiness script | ✅ Complete |
| - Map proposal pipeline | `check_proposal_paths()` | ✅ Complete |
| - Identify all proposal sources | TradingAgent, OpinionStrategy, etc. | ✅ Complete |
| - Confirm unified signal path | Bypass detection | ✅ Complete |
| - Inspect confidence | Hardcoded confidence detection | ✅ Complete |
| - Distinguish derived vs hardcoded | Regex pattern matching | ✅ Complete |
| - Yes/No decision logic | Side selection logic validation | ✅ Complete |
| - Tag each proposal path | OK/HARD_CODED/BYPASS/RISKY tags | ✅ Complete |
| **4. ContinuousTrader + agents coverage** | Section 4 of readiness script | ✅ Complete |
| - Build asset/timeframe matrix | 5×5 grid (25 markets) | ✅ Complete |
| - For each matrix cell: Discover | Catalog check | ✅ Complete |
| - Analyze/Consensus | Strategy profile check | ✅ Complete |
| - Size | Risk engine sizing check | ✅ Complete |
| - Execute | Continuous trader validation | ✅ Complete |
| - Monitor/Protect | Kill switch integration check | ✅ Complete |
| - Output coverage table | `print_coverage_table()` | ✅ Complete |
| **5. Crypto-Kalshi readiness script** | Section 5 + main script | ✅ Complete |
| - Config/env validation | `run_dry_run_preflight()` | ✅ Complete |
| - Data/feeds sanity | CFB RTI connectivity check | ✅ Complete |
| - Dry-run trade across matrix | Sample BTC/ETH/SOL sizing | ✅ Complete |
| - UI state probe | Mode indicator validation | ✅ Complete |
| - LIVE_READY=YES/NO verdict | Final summary with blocking failures | ✅ Complete |

## Usage Examples

### Basic Readiness Check

```bash
$ python scripts/kalshi_crypto_live_readiness.py
MERID Kalshi Crypto Live-Trading Readiness Checklist
================================================================================

Running Section 1: Environment and mode sanity...
Running Section 2: Formula and sizing conflicts...
Running Section 3: Agent proposals and confidence...
Running Section 4: Market coverage matrix...
Running Section 5: Dry-run preflight...

[... detailed output ...]

========================================================================================================================
LIVE_READY=YES - All checks passed! Safe to enable live trading.
========================================================================================================================
```

### Verbose Diagnostics

```bash
$ python scripts/kalshi_crypto_live_readiness.py --verbose
# Shows detailed information for each check:
# - Current values for all env vars
# - Full formula snapshots
# - Confidence source details
# - Market coverage notes
```

### JSON for Automation

```bash
$ python scripts/kalshi_crypto_live_readiness.py --json
{
  "live_ready": true,
  "blocking_failures": [],
  "env_vars": [...],
  "formulas": [...],
  "proposals": [...],
  "coverage": [...],
  "dry_run": {...}
}
```

### Integration with CI/CD

```bash
#!/bin/bash
# Pre-deployment validation
python scripts/kalshi_crypto_live_readiness.py
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
  echo "PASS: Ready for live trading deployment"
  exit 0
else
  echo "FAIL: Live trading readiness checks failed"
  python scripts/kalshi_crypto_live_readiness.py --verbose  # Show details
  exit 1
fi
```

## Benefits

1. **Prevents live trading incidents**: Catches misconfigurations before they cause losses
2. **Comprehensive coverage**: All 5 requirement sections from problem statement implemented
3. **Operator-friendly**: Clear, actionable output with color coding and explicit fix suggestions
4. **Automation-ready**: JSON output mode for CI/CD integration
5. **Documentation**: Complete runbook for operators and on-call engineers
6. **Auditable**: Explicit validation of formulas, agent behavior, and market coverage

## Next Steps (Optional Enhancements)

While the current implementation is complete per the problem statement, potential future enhancements could include:

1. **Weekly/monthly strategy profiles**: Map weekly and monthly timeframes to strategy configurations
2. **Historical dry-run**: Test against last 24h of actual market data
3. **Performance benchmarks**: Validate order latency and throughput
4. **Automated alerting**: Slack/PagerDuty integration for failed checks
5. **Continuous monitoring**: Periodic re-runs of readiness checks in production

## Conclusion

The implementation provides a comprehensive, production-ready live-trading readiness validation system that:
- ✅ Covers all 5 sections specified in the problem statement
- ✅ Integrates with existing MERID infrastructure
- ✅ Provides clear, actionable operator guidance
- ✅ Prevents common live-trading configuration errors
- ✅ Includes emergency procedures and rollback instructions

The system is ready for immediate use in validating Kalshi crypto live-trading readiness.
