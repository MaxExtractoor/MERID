# Kalshi 15m Crypto Tuning Matrix
# Per-asset threshold ranges by time-in-window
# Research-aligned parameters for BTC, ETH, SOL, XRP, DOGE

## Overview
This tuning matrix provides per-asset parameter ranges for the 15-minute crypto trading system on Kalshi. Thresholds are dynamic based on time-in-window to align with volatility compression and information resolution over time.

## Time-in-Window Regimes
- **Early Window** (10-15 min remaining): High conviction required, conservative thresholds
- **Mid Window** (5-10 min remaining): Medium conviction, balanced thresholds
- **Late Window** (0-5 min remaining): Lower conviction, aggressive thresholds for high-probability convergence

## Per-Asset Parameter Table

| Asset | Early Window (10-15m) | Mid Window (5-10m) | Late Window (0-5m) | Notes |
|-------|----------------------|-------------------|-------------------|-------|
| **BTC** | | | | |
| Min Edge | 2.0% | 1.2% | 0.8% | High liquidity, tighter spreads |
| Min Confidence | 0.70 | 0.65 | 0.60 | Deep markets allow lower confidence late |
| Price Band | 10-75c | 10-75c | 5-90c | Late window allows extreme prices |
| Max Spread | 15c | 18c | 20c | Wider spreads acceptable late |
| Min Depth | 100 | 80 | 50 | Depth requirements relax late |
| OBI Threshold | 0.50 | 0.45 | 0.40 | Stronger OBI required early |
| | | | | |
| **ETH** | | | | |
| Min Edge | 2.0% | 1.2% | 0.8% | Similar to BTC, slightly less liquid |
| Min Confidence | 0.70 | 0.65 | 0.60 | Deep markets allow lower confidence late |
| Price Band | 10-75c | 10-75c | 5-90c | Late window allows extreme prices |
| Max Spread | 15c | 18c | 20c | Wider spreads acceptable late |
| Min Depth | 80 | 60 | 40 | Slightly less depth than BTC |
| OBI Threshold | 0.50 | 0.45 | 0.40 | Stronger OBI required early |
| | | | | |
| **SOL** | | | | |
| Min Edge | 2.2% | 1.4% | 1.0% | Higher edge required (thinner book) |
| Min Confidence | 0.72 | 0.67 | 0.62 | Higher confidence for volatility |
| Price Band | 10-75c | 10-75c | 5-90c | Late window allows extreme prices |
| Max Spread | 18c | 20c | 22c | Wider spreads due to volatility |
| Min Depth | 60 | 40 | 25 | Thinner book, lower depth |
| OBI Threshold | 0.55 | 0.50 | 0.45 | Higher OBI threshold |
| | | | | |
| **XRP** | | | | |
| Min Edge | 2.2% | 1.4% | 1.0% | Higher edge required (thinner book) |
| Min Confidence | 0.72 | 0.67 | 0.62 | Higher confidence for volatility |
| Price Band | 10-75c | 10-75c | 5-90c | Late window allows extreme prices |
| Max Spread | 18c | 20c | 22c | Wider spreads due to volatility |
| Min Depth | 60 | 40 | 25 | Thinner book, lower depth |
| OBI Threshold | 0.55 | 0.50 | 0.45 | Higher OBI threshold |
| | | | | |
| **DOGE** | | | | |
| Min Edge | 2.5% | 1.8% | 1.2% | Highest edge required (most volatile) |
| Min Confidence | 0.75 | 0.70 | 0.65 | Highest confidence required |
| Price Band | 10-75c | 10-75c | 5-90c | Late window allows extreme prices |
| Max Spread | 20c | 22c | 25c | Widest spreads due to high volatility |
| Min Depth | 50 | 30 | 20 | Thinnest book, lowest depth |
| OBI Threshold | 0.60 | 0.55 | 0.50 | Highest OBI threshold |

## Dynamic Edge Threshold Formula
```
if time_to_expiry_sec > 600:  # Early window (>10 min)
    min_edge = max(base_min_edge, 0.020)  # 2.0% minimum
elif time_to_expiry_sec > 300:  # Mid window (5-10 min)
    min_edge = max(base_min_edge, 0.012)  # 1.2% minimum
else:  # Late window (<5 min)
    min_edge = max(base_min_edge, 0.008)  # 0.8% minimum
```

## Dynamic Price Band Formula
```
if time_to_expiry_sec < 300:  # Late window (<5 min)
    min_price_cents = 5
    max_price_cents = 90
else:  # Early/mid window
    min_price_cents = 5  # CRITICAL FIX (2026-08-01): Lowered from 10c to 5c for 15m crypto volatility
    max_price_cents = 85  # CRITICAL FIX (2026-08-01): Expanded from 75c to 85c for 15m crypto volatility
```

## Exposure-Aware Re-Entry Logic
- **Edge Improvement Delta**: 0.5% (0.005)
- Allow re-entry if: `current_edge > prior_edge + 0.005`
- This captures late-window edge formation without overtrading

## Rejection Reason Monitoring
Track the following rejection reasons to identify filtering bottlenecks:
- `parity_blocked`: Both YES and NO edges below min_edge
- `edge_below_threshold`: Edge below dynamic threshold
- `duplicate_order`: No material edge improvement for re-entry
- `price_out_of_range`: Price outside dynamic price band
- `position_exists`: Asset already has position in window
- `resting_order_exists`: Asset has resting order in window
- `edge_validation_failed`: Edge validation check failed
- `exit_policy_failed`: Exit policy resolution failed
- `router_rejected`: Order router rejected the order
- `other`: Other rejection reasons

## Deployment Checklist
- [ ] Review per-asset thresholds against current market conditions
- [ ] Validate dynamic edge threshold logic in test environment
- [ ] Confirm price band expansion works for late-window trades
- [ ] Monitor rejection counters for first 100 cycles
- [ ] Adjust per-asset OBI thresholds based on book depth
- [ ] Verify exposure-aware re-entry doesn't cause overtrading
- [ ] Check that $1 fixed exposure cap is still enforced

## Monitoring Metrics
- Rejection rate by reason (per 100-cycle window)
- Edge distribution histogram per asset
- Price distribution within dynamic bands
- Re-entry success rate (edge improvement trades)
- Late-window trade win rate vs early/mid window

## Research Alignment
These thresholds align with 2026 research on:
- Volatility compression over time (lower thresholds late)
- Information resolution (higher conviction early, lower late)
- Market microstructure (depth/spread relationships)
- Probability convergence (late-window extreme prices valid)
