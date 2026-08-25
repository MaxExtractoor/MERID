# Regression Oracle: Intent→Exposure Violation Detection

## Overview

This script analyzes historical trade logs to detect instances where the old "sell Yes as entry" bug would have fired. It uses the new StrategyIntent contract to validate that BULLISH_EVENT produces +Yes exposure and BEARISH_EVENT produces +No exposure.

## Usage

```bash
# Analyze a single log file
python scripts/regression_oracle_intent_exposure.py --log-file path/to/logfile.log

# Analyze all logs in a directory
python scripts/regression_oracle_intent_exposure.py --log-dir path/to/logs/

# Save report to file
python scripts/regression_oracle_intent_exposure.py --log-dir path/to/logs/ --output report.txt
```

## Log Format

The script parses `[INTENT-EXEC]` log entries added in the strategy intent validation fix:

```
[INTENT-EXEC] ticker=KXBTC15M-... intent=BULLISH_EVENT exposure=+YES kalshi_side=BUY_YES action=buy price=42c
```

## Violation Classification

### TRUE_BUG
Entry opened opposite exposure from stated intent. This is the actual bug case:
- `intent=BULLISH_EVENT` but `kalshi_side=BUY_NO` or `kalshi_side=SELL_YES` (+No exposure)
- `intent=BEARISH_EVENT` but `kalshi_side=BUY_YES` or `kalshi_side=SELL_NO` (+Yes exposure)
- Position was flat before the order (fresh entry, not a closure)

### CANONICAL_EQUIVALENT
`sell_yes` and `buy_no` represented the same No exposure and were used correctly:
- Both result in +No exposure (betting against the event)
- Position was not flat before (adjusting existing position)

### CLOSURE_NOISE
A trade that looked inverted but was actually a valid exit from an existing position:
- Sell orders that close a position
- Position was not flat before (reducing/closing existing position)

### NO_VIOLATION
Intent matches exposure correctly (the normal case).

## Position State Reconstruction

The script reconstructs position state over time for each ticker:
- Tracks YES and NO contract counts
- Applies orders in timestamp order
- Calculates net exposure: +YES, +NO, or FLAT
- Uses position state to distinguish entries from closures

## Edge Case Handling

### Canonical Equivalents
Kalshi treats buy Yes / sell No as equivalent and buy No / sell Yes as equivalent:
- `BUY_YES` and `SELL_NO` both result in +Yes exposure
- `BUY_NO` and `SELL_YES` both result in +No exposure

The oracle normalizes these to signed exposure deltas before validation.

### Closure Noise
Fast reversals in 15-minute markets can make an exit and a new entry appear adjacent:
- The oracle checks if position was flat before the order
- If not flat, classifies as closure_noise rather than true_bug
- Sell orders are typically treated as closures

## Output Report

The report includes:
- Total records analyzed
- Total violations found
- Violations grouped by type
- Detailed violation information:
  - Ticker and timestamp
  - Intent and expected exposure
  - Actual exposure and Kalshi side
  - Action and price
  - Position state before order
  - Raw log line for context

## Example Output

```
================================================================================
REGRESSION ORACLE: Intent→Exposure Violation Report
================================================================================
Total records analyzed: 1250
Total violations found: 3

TRUE_BUG: 1 violations
CANONICAL_EQUIVALENT: 1 violations
CLOSURE_NOISE: 1 violations

--------------------------------------------------------------------------------
DETAILED VIOLATIONS
--------------------------------------------------------------------------------

[TRUE_BUG]
  Ticker: KXBTC15M-UP-20260719-1400
  Timestamp: 2026-07-19 14:30:15
  Intent: BULLISH_EVENT (expected exposure: +YES)
  Actual exposure: +NO
  Kalshi side: BUY_NO
  Action: buy
  Price: 45c
  Position before: FLAT
  Was flat before: True
  Raw log: [INTENT-EXEC] ticker=KXBTC15M-... intent=BULLISH_EVENT exposure=+NO kalshi_side=BUY_NO action=buy price=45c
```

## Integration with CI/CD

This oracle can be integrated into CI/CD pipelines to prevent regression:

```yaml
# Example GitHub Actions step
- name: Run Regression Oracle
  run: |
    python scripts/regression_oracle_intent_exposure.py --log-dir logs/ --output report.txt
    if grep -q "TRUE_BUG" report.txt; then
      echo "Intent→Exposure violations detected!"
      exit 1
    fi
```

## Related Files

- `merid/prediction/signal_terminology.py` - StrategyIntent enum definition
- `merid/prediction/agent_grid_15m.py` - Price-based signal logic with intent
- `merid/loop_15m.py` - Execution boundary with intent validation
- `tests/test_strategy_intent_validation.py` - Unit tests for intent invariants
