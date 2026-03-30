# Kalshi Max-Price Config and Reconciled Positions

## Overview

This document describes two related safeguards in the MERID Kalshi stack:

1. **`max_yes_price`** — a per-profile, firm scalar cap on the YES price the bot
   will pay per contract.  It is now the single authoritative source of truth for
   this constraint and is enforced at every layer of the trading pipeline.

2. **Reconciled position cache** — the `KalshiPositionCache` (updated from
   WebSocket fills and reconciliation cycles) is now the primary source of truth
   for positions, replacing the raw Kalshi REST response that frequently returned
   zero positions.

---

## 1. `max_yes_price` configuration

### Where to set it

| Location | Mechanism |
|---|---|
| Environment variable | `MERID_MAX_YES_PRICE=0.50` (dollars; default **0.50**) |
| Python / programmatic | Pass `max_yes_price=0.40` to `KalshiContinuousTrader(…)` |
| `KalshiRiskConfig` | Set `max_yes_price_cents=40` when constructing the risk manager |

All three ultimately control the same cap.  The continuous trader reads
`MERID_MAX_YES_PRICE` at startup; the risk manager uses `KalshiRiskConfig`.
For paper/sandbox profiles you can raise the cap (e.g. `0.65`) to collect
calibration data.  For production keep it at `0.40–0.50`.

### How it propagates

```
MERID_MAX_YES_PRICE env
        │
        ▼
KalshiContinuousTrader._max_yes_price  (dollars, e.g. 0.50)
        │
        ├─► trade_cycle()          — intent layer:  drops YES intents
        │                            whose best_ask_cents > max_yes_price*100
        │
        └─► KalshiRiskConfig.max_yes_price_cents  (cents, e.g. 50)
                │
                └─► KalshiRiskManager.check_order(outcome="yes")
                        │
                        └─► KalshiTrader.buy_yes()  — order layer:
                                _pre_order_check(outcome="yes") calls
                                check_order → rejected if price > cap
```

### Invariant

> **No live YES order may be sent with `price_cents > max_yes_price_cents`.**

Violations are logged at `WARNING` level as:
```
max_yes_price_cap: ticker=KXBTC-15M-T95000 price=65¢ cap=50¢ contracts=10 category=crypto
```

### Trade-offs

| Cap value | Effect |
|---|---|
| 0.35–0.40 | More convex, cheap contracts; misses high-probability plays |
| 0.50 | Balanced default — blocks anything at "coin flip" or higher |
| 0.60–0.65 | Allows higher win-rate contracts; more capital at risk per contract |

---

## 2. Reconciled position cache

### Why REST alone is unreliable

The Kalshi REST `GET /portfolio/positions` endpoint frequently returns 0
positions during market-open windows even when open positions exist.  The
fills ledger and WebSocket reconciliation already reconstruct a reliable
in-memory position map (`KalshiPositionCache`).

### New behaviour of `/api/v1/kalshi/positions`

The endpoint now uses a **two-layer architecture**:

1. **Primary (reconciled cache)** — `KalshiPositionCache.get_all_positions()`
   returns positions rebuilt from WebSocket fills and reconciliation.  These
   appear in `data.positions` and carry `"source": "reconciled"`.

2. **Diagnostic (REST)** — REST positions are fetched and exposed under
   `data.diagnostics.raw_rest_positions` only.

Response shape:
```json
{
  "count": 2,
  "positions": [
    {"ticker": "KXBTC-15M-T95000", "outcome": "yes", "size": 5,
     "avg_price": 0.40, "unrealized_pnl": 0.10, "realized_pnl": 0.00,
     "source": "reconciled"}
  ],
  "diagnostics": {
    "reconciled_count": 2,
    "rest_count": 0,
    "in_sync": false,
    "raw_rest_positions": []
  }
}
```

### Discrepancy logging

When `reconciled_count != rest_count` a structured `WARNING` is emitted:
```
kalshi.position_discrepancy reconciled=2 rest=0 only_reconciled=['KXBTC-…'] only_rest=[]
```

Operators can grep for `position_discrepancy` to spot REST/cache drift.

### Position visibility invariant

> **If reconciliation shows N open positions, `/api/v1/kalshi/positions` must
> return at least those N positions within one reconciliation cycle.**

---

## 3. Verifying invariants at runtime

### Check effective max price
```
curl http://localhost:8000/api/v1/kalshi/continuous-trader/status | jq .config.max_yes_price
# → 0.5
```

Or read the startup log:
```
KalshiContinuousTrader starting … max_yes_price=0.50 min_confidence=0.55 …
```

### Check position discrepancies
```
grep "position_discrepancy" /var/log/merid.log
```

### Check max-price rejections
```
grep "max_yes_price_cap" /var/log/merid.log
```

---

## 4. Extending to other venues

Both patterns are designed to be reusable:

- `max_yes_price_cents` is a field on `KalshiRiskConfig`; other venues can
  add equivalent fields to their own risk configs.
- `KalshiPositionCache` is a standalone singleton; other venue adapters can
  implement a similar `get_position_cache()` contract and wire it into their
  equivalent of `get_positions()`.
