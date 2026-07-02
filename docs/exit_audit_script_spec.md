# Exit Audit Script Specification

## Purpose

This script audits the effectiveness of de-risking, profit-taking, and exit mechanisms by analyzing trade logs to determine if exits are behaving as designed.

## Data Fields to Extract Per Trade

### Entry Information
- `entry_timestamp`: When the trade was entered
- `entry_price_cents`: Entry price in cents
- `entry_side`: "yes" or "no"
- `entry_count`: Number of contracts
- `entry_notional_usd`: Notional value at entry
- `edge_pct`: Edge percentage at entry
- `confidence`: Confidence at entry
- `side_choice_reason`: Why the side was chosen (edge_argmax, depth_tiebreak, unified_edge)
- `edge_yes`: Edge for YES side
- `edge_no`: Edge for NO side

### Exit Targets
- `tp_price_cents`: Take profit price (if set)
- `tp_r_multiple`: R-multiple for TP
- `sl_price_cents`: Stop loss price (if set)
- `sl_r_multiple`: R-multiple for SL
- `tp_sl_rationale`: Rationale for TP/SL calculation
- `sizing_rationale`: Rationale for sizing calculation

### Exit Outcome
- `exit_timestamp`: When the trade was exited
- `exit_price_cents`: Exit price in cents
- `exit_type`: How the trade exited (take_profit, stop_loss, expiry, manual, cooldown, guardrail)
- `exit_reason`: Detailed reason for exit
- `hold_time_seconds`: Time held
- `pnl_usd`: Profit/loss in USD
- `pnl_pct`: Profit/loss as percentage

### Risk Management
- `winrate_at_entry`: Recent win rate at entry (if available)
- `size_halved_by_winrate_guard`: Boolean - was size halved by winrate guard?
- `regime_cooldown_active`: Boolean - was regime cooldown active?
- `risk_cap_rejected`: Boolean - was trade rejected by risk cap?

### Market Conditions
- `spread_cents_at_entry`: Spread at entry
- `time_to_expiry_min_at_entry`: Time to expiry at entry
- `volatility_regime_at_entry`: Volatility regime (LOW, NORMAL, HIGH, EXTREME)

## Key Ratios to Compute

### Exit Effectiveness
- `tp_hit_rate`: % of trades that hit take profit
- `sl_hit_rate`: % of trades that hit stop loss
- `expiry_exit_rate`: % of trades that exited at expiry
- `manual_exit_rate`: % of trades that exited manually

### TP/SL Performance
- `avg_r_multiple_on_tp`: Average R-multiple achieved on TP exits
- `avg_r_multiple_on_sl`: Average R-multiple lost on SL exits
- `tp_vs_sl_ratio`: Ratio of TP hits to SL hits

### De-risking Effectiveness
- `winrate_guard_trigger_rate`: % of trades where winrate guard halved size
- `regime_cooldown_trigger_rate`: % of trades blocked by regime cooldown
- `risk_cap_rejection_rate`: % of trades rejected by risk caps

### Microstructure Sanity
- `tp_below_spread_rate`: % of trades where TP was below spread (should be near 0)
- `avg_spread_cents`: Average spread at entry
- `avg_time_to_expiry_min`: Average time to expiry at entry

### Time-Based Analysis
- `avg_hold_time_seconds`: Average time held
- `hold_time_by_exit_type`: Average hold time per exit type
- `tte_regime_distribution`: Distribution of trades by TTE regime

## Audit Queries

### 1. Exit Type Distribution
```sql
SELECT 
    exit_type,
    COUNT(*) as trade_count,
    AVG(pnl_usd) as avg_pnl,
    AVG(pnl_pct) as avg_pnl_pct
FROM trades
GROUP BY exit_type
```

### 2. TP/SL Hit Rates
```sql
SELECT 
    COUNT(CASE WHEN exit_type = 'take_profit' THEN 1 END) as tp_hits,
    COUNT(CASE WHEN exit_type = 'stop_loss' THEN 1 END) as sl_hits,
    COUNT(CASE WHEN exit_type = 'expiry' THEN 1 END) as expiry_exits,
    COUNT(*) as total_trades,
    100.0 * COUNT(CASE WHEN exit_type = 'take_profit' THEN 1 END) / COUNT(*) as tp_hit_rate,
    100.0 * COUNT(CASE WHEN exit_type = 'stop_loss' THEN 1 END) / COUNT(*) as sl_hit_rate
FROM trades
```

### 3. Winrate Guard Effectiveness
```sql
SELECT 
    size_halved_by_winrate_guard,
    AVG(pnl_usd) as avg_pnl,
    AVG(pnl_pct) as avg_pnl_pct,
    COUNT(*) as trade_count
FROM trades
GROUP BY size_halved_by_winrate_guard
```

### 4. Microstructure Sanity Check
```sql
SELECT 
    COUNT(CASE WHEN tp_price_cents IS NOT NULL 
         AND ABS(tp_price_cents - entry_price_cents) < spread_cents_at_entry 
         THEN 1 END) as tp_below_spread_count,
    COUNT(CASE WHEN tp_price_cents IS NOT NULL THEN 1 END) as tp_trades,
    100.0 * COUNT(CASE WHEN tp_price_cents IS NOT NULL 
         AND ABS(tp_price_cents - entry_price_cents) < spread_cents_at_entry 
         THEN 1 END) / COUNT(CASE WHEN tp_price_cents IS NOT NULL THEN 1 END) as tp_below_spread_rate
FROM trades
```

### 5. TTE Regime vs Exit Type
```sql
SELECT 
    CASE 
        WHEN time_to_expiry_min_at_entry <= 2 THEN 'terminal'
        WHEN time_to_expiry_min_at_entry <= 5 THEN 'critical'
        WHEN time_to_expiry_min_at_entry <= 10 THEN 'approaching'
        ELSE 'normal'
    END as tte_regime,
    exit_type,
    COUNT(*) as trade_count,
    AVG(pnl_pct) as avg_pnl_pct
FROM trades
GROUP BY tte_regime, exit_type
```

## Expected Outcomes

### Healthy System
- **TP hit rate**: 40-60% (TP should hit more often than SL)
- **SL hit rate**: 20-30% (SL should protect against losses)
- **Expiry exit rate**: 10-20% (Some trades should expire)
- **TP below spread rate**: <5% (TP should be realistic given spread)
- **Winrate guard trigger rate**: <10% (Only in severe negative edge scenarios)
- **Regime cooldown trigger rate**: <5% (Only in sustained poor performance)

### Red Flags
- **TP hit rate < 30%**: TP targets may be too ambitious
- **SL hit rate > 40%**: SL may be too tight or entries poor
- **Expiry exit rate > 40%**: Exits not triggering, "hope and hold" behavior
- **TP below spread rate > 10%**: TP targets not respecting microstructure
- **Winrate guard trigger rate > 20%**: System may have structural edge issues
- **Regime cooldown trigger rate > 15%**: Regime thresholds may be too sensitive

## Implementation Notes

### Data Sources
- **STRATEGY-TRUTH-TABLE logs**: Contains entry information, TP/SL targets, rationales
- **Order router logs**: Contains order execution details
- **Position cache**: Contains exit information
- **Round trip monitor**: Contains PnL and exit reasons

### Log Parsing
- Parse `[STRATEGY-TRUTH-TABLE]` JSON logs for entry data
- Parse `[DYNAMIC-TP-SL-APPLIED]` logs for TP/SL details
- Parse `[TIME-EXIT]` logs for time-based exits
- Parse `[TRAIL-MONITOR]` logs for trailing stop exits

### Output Format
- CSV file with all trade fields
- Summary report with key ratios
- Visualizations (optional):
  - Exit type pie chart
  - PnL distribution by exit type
  - TP/SL hit rate over time
  - Winrate guard trigger rate over time

## Usage

```bash
# Run audit on last 7 days of trades
python scripts/exit_audit.py --days 7 --output output/exit_audit_2026-05-28/

# Run audit on specific date range
python scripts/exit_audit.py --start 2026-05-20 --end 2026-05-28 --output output/exit_audit/

# Generate visualizations
python scripts/exit_audit.py --days 7 --visualize
```

## Integration with Observability

The audit script should:
1. Pull data from centralized log storage (e.g., Loki, Elasticsearch)
2. Cache results for fast re-runs
3. Alert on red flags (e.g., TP hit rate < 30%)
4. Push metrics to Prometheus/Grafana for ongoing monitoring
