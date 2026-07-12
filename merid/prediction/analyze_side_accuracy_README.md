# Side Accuracy Analyzer

Analyzes agent yes/no decision accuracy to detect flaws in side selection logic.

## Purpose

This script analyzes historical trade data from the 15-minute Kalshi crypto trading system to determine if agents are choosing the correct side (YES/NO) based on velocity direction and actual outcomes. It helps identify systematic biases, velocity-to-side mapping errors, and underperforming side selections.

## Key Analyses

1. **Side Accuracy Metrics**
   - YES vs NO trade distribution (detects systematic bias)
   - YES win rate vs NO win rate
   - Overall win rate per agent and asset

2. **Velocity-to-Side Mapping Validation**
   - Correlation between edge sign (proxy for velocity) and side selection
   - Detects when positive edge incorrectly maps to NO or negative edge to YES
   - Expected accuracy: >90%

3. **Anomaly Detection**
   - Systematic YES/NO bias (>80% of trades on one side)
   - Poor velocity-to-side mapping (<70% accuracy)
   - Side underperformance (win rate <40%)
   - System-wide velocity mapping errors

4. **Per-Agent Analysis**
   - Individual agent side accuracy
   - Agent-specific bias detection
   - Agent performance ranking

5. **Per-Asset Analysis**
   - Asset-specific side accuracy (BTC, ETH, SOL, XRP, DOGE)
   - Asset-specific bias detection
   - Asset performance comparison

## Usage

### Analyze Real Trade Data

```bash
cd C:\Dev\MERID
py merid/prediction/analyze_side_accuracy.py --print
```

This analyzes historical trades from the AgentPerformanceTracker and prints a formatted report.

### Generate Mock Data for Testing

```bash
py merid/prediction/analyze_side_accuracy.py --print --mock-data 100
```

Generates 100 mock trades for testing the analyzer without requiring real trade history.

### Save JSON Report

```bash
py merid/prediction/analyze_side_accuracy.py --output custom_report.json
```

Saves the analysis to a JSON file for programmatic consumption.

### Combined Options

```bash
py merid/prediction/analyze_side_accuracy.py --print --output report.json --mock-data 50
```

Prints report to console and saves to JSON with 50 mock trades.

## Command-Line Options

- `--output FILE`: Output file for JSON report (default: side_accuracy_report.json)
- `--print`: Print formatted report to console
- `--min-trades N`: Minimum trades required for analysis (default: 5)
- `--mock-data N`: Generate N mock trades for testing (0 = use real data)

## Output

### Console Report

The console report includes:
- System-wide summary (total trades, YES/NO distribution, win rates)
- Per-asset breakdown (BTC, ETH, SOL, XRP, DOGE)
- Per-agent breakdown (top 10 by trade count)
- Detected anomalies with severity and recommendations

### JSON Report

The JSON report includes:
- Timestamp
- Detailed metrics per agent
- Detailed metrics per asset
- System-wide metrics
- List of detected anomalies with full details

## Anomaly Types

### Critical Anomalies

- **system_yes_bias**: System-wide YES bias (>70% of trades)
- **system_no_bias**: System-wide NO bias (>70% of trades)
- **system_velocity_mapping**: Poor system-wide velocity-to-side mapping (<80%)
- **poor_velocity_mapping**: Agent has poor velocity-to-side mapping (<70%)

### Warning Anomalies

- **systematic_yes_bias**: Agent has extreme YES bias (>80%)
- **systematic_no_bias**: Agent has extreme NO bias (>80%)
- **yes_underperformance**: YES trades underperforming (win rate <40%)
- **no_underperformance**: NO trades underperforming (win rate <40%)
- **asset_yes_bias**: Asset has extreme YES bias (>80%)
- **asset_no_bias**: Asset has extreme NO bias (>80%)

## Interpretation

### Velocity-to-Side Mapping

The script uses edge sign as a proxy for velocity direction:
- Positive edge → should be YES
- Negative edge → should be NO

If velocity-to-side accuracy is low (<70%), it indicates:
- Edge calculation may be incorrect
- Side selection logic may be broken
- Signal generation may have a bug

### YES/NO Bias

A balanced system should have approximately 50% YES and 50% NO trades. Extreme bias (>80%) indicates:
- Velocity threshold may be too strict for one side
- Signal generation may be rejecting valid signals
- Market conditions may favor one side (temporary)

### Side Win Rates

Both YES and NO should have similar win rates (~50-60% for a well-calibrated system). Significant divergence indicates:
- One side may be entering at unfavorable prices
- Edge calculation may be biased
- Risk management may be asymmetric

## Integration with Production

To use with production data:

1. Ensure the 15m Kalshi system has been running and has accumulated trade history
2. Run the script without `--mock-data` flag
3. Review anomalies and recommendations
4. Investigate critical anomalies in the signal generation pipeline

## Files

- `merid/prediction/analyze_side_accuracy.py`: Main analyzer script
- `side_accuracy_report.json`: Default output file (auto-generated)
- `merid/prediction/agent_performance_tracker.py`: Source of trade data

## Dependencies

- AgentPerformanceTracker (merid.prediction.agent_performance_tracker)
- Standard library only (no external dependencies beyond MERID codebase)

## Notes

- The script uses edge sign as a proxy for velocity direction since velocity is not stored in TradeRecord
- In production, consider adding velocity field to TradeRecord for more accurate analysis
- Mock data mode is for testing only - use real data for production analysis
- Anomaly thresholds are configurable in the script constants
