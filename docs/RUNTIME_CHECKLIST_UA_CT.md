# Runtime checklist — UA / CT metrics & micro-live trading

Use this before/after restarting the API. Detailed log ordering and code paths: **[`docs/CT_E2E_AUDIT.md`](CT_E2E_AUDIT.md)**.

---

## 1. Environment (live box)

**Unix/bash:**

```bash
export KALSHI_CT_PROFILE="initial_live"
export MERID_PM_TRADING_MODE="live"
export MERID_PM_LIVE_ENABLED="true"
export MERID_ALLOW_LIVE_TRADES="true"

export MERID_UA_MICRO_LIVE_RISK="1"
export MERID_AGENT_GRID_CT_COORD="1"

export KALSHI_LOOP_LAG_DEGRADE_MS="500"
export KALSHI_LOOP_LAG_HALT_MS="2000"
export KALSHI_LOOP_LAG_HALT_CONSECUTIVE="3"
```

**Windows PowerShell:**

```powershell
$env:KALSHI_CT_PROFILE = "initial_live"
$env:MERID_PM_TRADING_MODE = "live"
$env:MERID_PM_LIVE_ENABLED = "true"
$env:MERID_ALLOW_LIVE_TRADES = "true"
$env:MERID_UA_MICRO_LIVE_RISK = "1"
$env:MERID_AGENT_GRID_CT_COORD = "1"
```

**Notes**

- **`MERID_ALLOW_LIVE_TRADES`** must be truthy or `VenueGate` downgrades LIVE → PAPER at init.
- Use **`KALSHI_CT_PROFILE`** only — there is **no** `KALSHI_CT_EDGE_PROFILE` in this repo.
- **`KALSHI_CT_PROFILE=initial_live`** or **`MERID_UA_MICRO_LIVE_RISK=1`** tightens `KalshiRiskManager` caps (see `KalshiRiskManager._apply_micro_live_profile_if_requested`).
- Loop-lag thresholds are read via `merid.diagnostics.loop_lag.get_loop_lag_thresholds_ms()` (`KALSHI_LOOP_LAG_*` env names above).

Restart the API process after changing env.

---

## 2. Minimal verify sequence

1. Set env vars → **restart** the server (and start Agent Grid if you use it).
2. **Logs**
   - One **`[KALSHI_CT_CONFIG]`** line at CT init (includes `MERID_TRADE_MODE`, `MERID_ALLOW_LIVE_TRADES`, `group_notional_cap_usd`, `universe_assets`, …).
   - **`[UA-GRID]`** about every **60s** once the grid is running (venue `kalshi`, coordination enabled):  
     `ct_running=… ct_cycle=… ua_ct_evaluated=… ua_ct_orders_accepted=… ua_ct_orders_rejected=…`
   - **`[UA-TRACE]`** after each CT cycle (see §4).
3. **HTTP**
   - `GET /api/v1/kalshi/universe/agents` — handler **`get_universal_agents`**; response `agents["sweep-all"]` is always present and merged with CT metrics (`ct_metrics` key).
   - `GET /api/v1/kalshi-grid/status` — top-level **`ua_ct`** = `ua_ct_metrics.snapshot()` (same data also under `metrics.ua_ct` inside grid `summary()`).
4. **Tests (optional)**  
   `py -3 -m pytest tests/test_ua_ct_metrics.py`  
   `py -3 scripts/ct_e2e_smoke_test.py`

---

## 3. Expected log shapes (reference)

**`[KALSHI_CT_CONFIG]`** (startup, truncated):

```text
[KALSHI_CT_CONFIG] dry_run=... min_edge=... ... MERID_TRADE_MODE=... MERID_ALLOW_LIVE_TRADES=... group_notional_cap_usd=... universe_assets=BTC,ETH,...
```

**`[UA-GRID]`** (every ~60s when grid coordination runs):

```text
[UA-GRID] ct_running=True ct_cycle=3 ua_ct_evaluated=42 ua_ct_orders_accepted=1 ua_ct_orders_rejected=0
```

**`[UA-TRACE]`** (each CT cycle):

```text
[UA-TRACE] cycle=3 catalog_markets=1200 universe_markets=15 evaluated=8 approved=2 vetoed=6 orders_submitted=1 trace_error=none
```

If `_run_cycle_inner` raises, you also get **`[UA-TRACE] cycle_inner_failed …`** and `trace_error=…` on the summary line.

**`[CT-TRACE]`** (per candidate):

```text
[CT-TRACE] market=KXBTC15M-... asset=BTC tf=15m | ... best_edge=0.0150 edge_pct=1.50 ... veto=none
```

**CT direct order (REST)** — no router `VenueGate` line:

```text
[RISK] decision=approve reason=ok ticker=... contracts=2 ... limits=max_single_contracts=3 ...
[KALSHI_ORDER_INTENT] ticker=... source=kalshi_ct ...
[KALSHI_ORDER_RESULT] ticker=... status=executed http=201 source=kalshi_ct
```

**Order router LIVE** — `KalshiRiskManager` runs **before** the admitting **`[VENUE-GATE] decision=approve`** (see `CT_E2E_AUDIT.md`):

```text
[RISK] decision=approve reason=ok ticker=... ...
[VENUE-GATE] decision=approve reason=live_order_admitted venue=Kalshi size=2 ...
[KALSHI_ORDER_INTENT] ticker=... source=universal-agent ...
[KALSHI_ORDER_RESULT] ticker=... status=filled_live ... source=order_router
```

Early denies: **`[VENUE-GATE] decision=deny`** (`live_not_enabled`) or **`[RISK] decision=deny`** — `ua_ct_metrics.orders_rejected` increments on these router exits where wired.

---

## 4. Troubleshooting

| Symptom | Check |
|--------|--------|
| No `[UA-GRID]` | Agent Grid not started, `MERID_AGENT_GRID_CT_COORD` off, or venue name ≠ `kalshi` |
| `[UA-TRACE]` `evaluated=0` always | Upstream: no spot, no candidates, execution gate blocking, or exception (`trace_error`) |
| CT never sends orders | `dry_run`, guard observation mode, `_live_ok` false, churn/caps, or edge below threshold |
| API empty / 500 | `get_universal_agents` falls back per-agent if merge fails; check logs for `merge_agent_dict` |

---

## 5. What to paste for review

A slice containing `[KALSHI_CT_CONFIG]`, `[UA-GRID]`, `[UA-TRACE]`, `[CT-TRACE]`, and any `[VENUE-GATE]` / `[RISK]` / `[KALSHI_ORDER_*]` lines is enough to pinpoint remaining blockers.
