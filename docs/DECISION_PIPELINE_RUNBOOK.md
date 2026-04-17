# Decision Pipeline — Operator Runbook

## Overview

Every cycle of every Kalshi trading agent now produces a **first-class `Decision`** object
for each market evaluated. The Decision is either `TRADE` or `HOLD`, with a mandatory
`HoldReason` when holding.

```
[PM_DECISION] action=hold hold_reason=risk_limit market=KXBTC-15M-T1234 agent=BTC_15M cycle=42 elapsed_ms=12.3 detail=max notional per event exceeded
```

## Files

| File | Purpose |
|---|---|
| `merid/prediction/decision.py` | `Decision` dataclass, `DecisionAction`, `HoldReason` enums |
| `merid/prediction/decision_evaluator.py` | `evaluate_cycle_decision()` — stateless pipeline |
| `merid/prediction/trade_hold_config.py` | YAML loader + env override for thresholds |
| `config/trade_hold_config.yaml` | Global default thresholds |
| `config/profiles/trade_hold_live.yaml` | Microscopic-risk live profile |
| `tests/prediction/test_decision_pipeline.py` | 68 tests covering all pipeline stages |

## Pipeline Stages (earliest exit wins)

| # | Stage | HoldReason(s) |
|---|---|---|
| 1 | Config / agent disabled | `config_disabled` |
| 2 | Kill switch | `kill_switch` |
| 3 | Session guard | `session_closed` |
| 4 | Warmup lifecycle | `warmup` |
| 5 | No markets resolved | `no_markets` |
| 6 | Order window limit | `order_limit` |
| 7 | Entry window / expiry | `outside_entry_window`, `expiry_proximity` |
| 8 | Strategy signal | `no_edge`, `edge_below_threshold`, `stale_data`, `spot_strike_veto`, `liquidity_guard`, `conviction_veto`, `pm_spot_gate`, `confidence_too_low` |
| 9 | Consensus / swarm | `consensus_forming`, `consensus_conflicted`, `consensus_direction_mismatch`, `solo_window`, `solo_cap_reached` |
| 10 | Risk pre-trade | `risk_limit`, `risk_halt`, `risk_reduce`, `rate_limit` |
| 11 | All passed | → `TRADE` |

## Observability

### Log Tags
- `[PM_DECISION]` — one per market per cycle (action, hold_reason, elapsed_ms)
- `[PM_CYCLE_TRACE]` — end-of-cycle summary (unchanged, still emitted)
- `[PM_SIGNAL]` — strategy signal detail (unchanged)

### Grepping for HOLD patterns
```bash
# All holds in the last hour
grep "PM_DECISION.*action=hold" /var/log/merid/agent.log | tail -100

# Holds by reason
grep "hold_reason=risk_limit" /var/log/merid/agent.log | wc -l
grep "hold_reason=no_edge" /var/log/merid/agent.log | wc -l

# All trades
grep "PM_DECISION.*action=trade" /var/log/merid/agent.log
```

### Decision Metrics Breakdown
```bash
# Distribution of hold reasons (requires structured log parsing)
grep "PM_DECISION" /var/log/merid/agent.log | \
  sed -n 's/.*hold_reason=\([^ ]*\).*/\1/p' | sort | uniq -c | sort -rn
```

## Configuration

### Environment Variable Overrides
Every config key can be overridden via `MERID_TH_<SECTION>_<KEY>`:

```bash
# Tighten edge threshold
export MERID_TH_STRATEGY_MIN_EDGE_EARLY=0.12

# Disable the Decision pipeline (fallback to legacy code path)
export MERID_TH_ENABLED=false

# Increase warmup time
export MERID_TH_WARMUP_MIN_SECONDS=30
```

### Switching to Live Profile
```bash
cp config/profiles/trade_hold_live.yaml config/trade_hold_config.yaml
# Restart agents
```

### Key Live Profile Differences
| Parameter | Default | Live |
|---|---|---|
| `max_contracts_per_order` | 50 | 10 |
| `max_notional_per_market_usd` | 500 | 100 |
| `max_daily_loss_usd` | 500 | 50 |
| `min_edge_early` | 8% | 10% |
| `expiry_proximity_guard_seconds` | 90 | 120 |
| `max_orders_per_window` | 10 | 5 |

## Troubleshooting

### "All cycles show HOLD — nothing trades"
1. Check `hold_reason` — the reason tells you exactly what gate is blocking
2. Most common: `no_edge` (market doesn't have enough edge) or `no_markets` (market resolution failed)
3. If `warmup` — agent is still starting, wait for `_WARMUP_MAX_SECONDS`
4. If `session_closed` — check Kalshi maintenance window (Thu 3-5AM ET)

### "Agent traded when it shouldn't have"
1. Check the `[PM_DECISION] action=trade` log — it shows the signal and risk summaries
2. Verify config thresholds in `config/trade_hold_config.yaml`
3. Check if env overrides are loosening thresholds

### "Decision pipeline disabled"
If you see `hold_reason=config_disabled` with detail "trade_hold pipeline disabled":
- Check `MERID_TH_ENABLED` env var
- Check `config/trade_hold_config.yaml` → `enabled: true`
