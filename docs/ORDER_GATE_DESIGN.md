# Pre-Trade Idempotency Gate — Engineering Design Note

## Root Cause: Market-Maker Duplicate Order Blocking

### Symptom

`CRYPTO_15M_MM` (and any other market-maker agent) attempted to place
bid/ask pairs every trade cycle but was blocked with errors such as:

```
[GATE] duplicate blocked coid=... status=pending contract=KXSOL15M-26APR121400-00
       agent=kalshi-crypto_15m_mm_... strategy_group=CRYPTO_15M_MM side=yes qty=1 price_cents=49
[order-router] Pre-trade gate blocked: duplicate:pending
Order failed: bid:Order rejected: gate:duplicate:pending; ask:Order rejected: gate:duplicate:pending
```

### Root Cause

The pre-trade gate assigns a **deterministic internal key** (`coid`) to each
logical order from the preimage:

```
{agent_id}|{strategy_group}|{contract_id}|{side}|{qty}|{price_cents}|{bucket}
```

where `bucket = floor(epoch_seconds / DECISION_BUCKET_WIDTH_S)`.

With `DECISION_BUCKET_WIDTH_S = 60`, all orders sharing the same
`(agent, strategy_group, contract, side, qty, price)` within a 60-second
window map to the **same coid**.

A market-maker running every ~15 s quotes the same spread repeatedly
(e.g. bid 49 / ask 51, qty 1).  Within a single 60-second window:

- Cycle 1 → coid X → status = `pending` → **proceeds**
- Cycle 2 → coid X → gate sees `pending` → **blocked as duplicate**
- Cycle 3 → coid X → gate sees `pending` → **blocked as duplicate**
- Cycle 4 → coid X → gate sees `pending` → **blocked as duplicate**

The market maker is effectively silenced for most of each minute.

---

## Other Non-Bug Behaviours (No Fix Required)

| # | Behaviour | Root cause | Action |
|---|-----------|-----------|--------|
| 2 | `net_edge < terminal_threshold` → `no_action/hold` | Correct strategy logic | None |
| 3 | Far-OTM contracts rejected by strike selector | Intended risk control | None |
| 4 | Circuit breaker open on startup | Transient connectivity | None |

---

## Design

### Chosen Approach: Combined Option A + B

We implement **two complementary mechanisms** so the MM can always place
fresh orders:

**Option A — Per-agent bucket width**

For agents with `is_market_maker=True`, the gate uses
`MM_DECISION_BUCKET_WIDTH_S = 5` (instead of 60).  With a 15-second cycle
period, each cycle falls in a different 5-second bucket and gets a distinct
coid automatically, even without any explicit cycle tracking.

| Agent type | Bucket width | Effect |
|------------|-------------|--------|
| Directional (BTC_15M, ETH_15M, …) | 60 s | One logical order per minute per market/side |
| Market-maker (CRYPTO_15M_MM) | 5 s | One logical order per 5 s per market/side |

**Option B — Optional cycle nonce**

When the trading agent calls `_kalshi_place_order` with `cycle_id` set (e.g.
`str(self.state.cycles_run)`), the cycle nonce is appended to the coid
preimage, giving each MM trade cycle a **unique identity** independent of the
bucket clock.

```
preimage = "{agent}|{group}|{contract}|{side}|{qty}|{price}|{bucket}|{cycle_id}"
```

- `cycle_id` is stable within a single cycle (retries reuse same cycle number).
- `cycle_id` changes when the agent advances to a new cycle (counter increments).

This guarantees correctness even if the MM cycle period happens to align with
the 5-second bucket boundary.

### Why Not Option C (Explicit Cancel-and-Replace)?

Cancel-and-replace requires:
1. Knowing the venue order ID of the previous resting order.
2. An async cancel call before each new quote cycle.
3. Handling cancel latency / partial fill races.

It is architecturally heavier and introduces new failure modes.
Options A+B achieve the same goal with zero extra network round-trips and
are fully reversible.

---

## Implementation

### New file: `merid/event_venues/kalshi/order_gate.py`

Key components:

| Symbol | Description |
|--------|-------------|
| `DECISION_BUCKET_WIDTH_S` | Default 60 s bucket (env `MERID_GATE_BUCKET_S`) |
| `MM_DECISION_BUCKET_WIDTH_S` | MM 5 s bucket (env `MERID_MM_GATE_BUCKET_S`) |
| `OrderGateStatus` | `pending / open / filled / rejected / canceled` |
| `GateEntry` | Per-coid state record |
| `PreTradeGate` | In-memory gate with `check_and_reserve`, `update_status`, `release` |
| `make_coid(...)` | Deterministic coid from preimage |
| `get_pre_trade_gate()` | Process-wide singleton |

### Modified: `merid/event_venues/kalshi/order_router.py`

- `OrderIntent` gains three optional fields:
  - `strategy_group: Optional[str]` — strategy label for the gate key
  - `is_market_maker: bool = False` — selects shorter MM bucket
  - `cycle_id: Optional[str]` — optional nonce for explicit cycle identity
- `_route_live()` calls `gate.check_and_reserve(...)` immediately after risk
  checks. On `duplicate_blocked` → returns `rejected` with reason
  `gate:duplicate:{status}`. On success → calls `gate.update_status(coid, ...)`.

### Modified: `merid/prediction/kalshi_tools.py`

- `_kalshi_place_order()` accepts `strategy_group`, `is_market_maker`,
  `cycle_id` and threads them into the `OrderIntent`.

### Modified: `merid/prediction/trading_agent.py`

- In `_execute_signal`:
  - Detects `self.config.archetype == "market_maker"`.
  - Sets `_mm_cycle_id = str(self.state.cycles_run)` (stable per cycle,
    increments between cycles).
  - Passes `strategy_group=self.config.name`, `is_market_maker=_is_mm`,
    `cycle_id=_mm_cycle_id` to every `_kalshi_place_order` call.

---

## Behaviour After the Fix

### Market-maker (`CRYPTO_15M_MM`)

```
cycle 1 (t=0s):   coid=mg_A  cycle_id="1"  bucket=0  → proceed
cycle 2 (t=15s):  coid=mg_B  cycle_id="2"  bucket=3  → proceed  (new cycle_id + new 5s bucket)
cycle 3 (t=30s):  coid=mg_C  cycle_id="3"  bucket=6  → proceed
cycle 4 (t=45s):  coid=mg_D  cycle_id="4"  bucket=9  → proceed
```

Retry of cycle 2 (same `cycle_id="2"`, same params, same 5s bucket):

```
retry at t=16s:   coid=mg_B  cycle_id="2"  → idempotent (existing pending order)
```

### Directional agent (BTC_15M)

```
t=0s:    coid=mg_X  → proceed
t=30s:   coid=mg_X  → duplicate_blocked  (same 60s bucket, still pending)
t=60s:   coid=mg_Y  → proceed            (new bucket)
```

Behaviour is **identical** to what it was before this change for directional
agents.

---

## Gate Status Machine

```
           ┌──────────┐
           │  (none)  │
           └────┬─────┘
                │ check_and_reserve → "proceed"
                ▼
           ┌──────────┐    update_status("open")    ┌──────┐
           │ PENDING  │ ──────────────────────────▶ │ OPEN │
           └────┬─────┘                             └──┬───┘
                │                                      │
      ┌─────────┼──────────────────────────────────────┤
      │         │                                      │
      ▼         ▼                                      ▼
  REJECTED   CANCELED                              FILLED
(terminal)  (terminal)                            (terminal)
```

Terminal statuses allow the same parameters to generate a new coid
on the next `check_and_reserve` call.

---

## Gate Kill Switch

Set `MERID_ORDER_GATE_ENABLED=false` to bypass all gate checks.
All orders proceed as if the gate returned `"proceed"`.

This restores exact pre-gate behaviour (UUID4-only dedup at the Kalshi
layer) and can be activated at runtime without a code change.

---

## Rollback Plan

1. Set `MERID_ORDER_GATE_ENABLED=false` — gate is immediately bypassed.
2. Alternatively, revert the three modified files:
   - `merid/event_venues/kalshi/order_router.py` — remove new `OrderIntent` fields and gate call in `_route_live`.
   - `merid/prediction/kalshi_tools.py` — remove the three new parameters.
   - `merid/prediction/trading_agent.py` — remove `_is_mm` / `_mm_cycle_id` logic.
3. The new `order_gate.py` file can be left in place (it has no effect if not imported).

---

## Testing

See `tests/event_venues/kalshi/test_order_gate.py` for automated tests
covering all scenarios listed in this document.

Key test classes:

| Class | What it covers |
|-------|---------------|
| `TestCoidGeneration` | Determinism, bucket widths, cycle_id influence |
| `TestMMFreshCycle` | MM cycle_id and 5 s bucket both unblock fresh cycles |
| `TestDuplicateBlocking` | pending / open status blocks re-submission |
| `TestTerminalStatusReuse` | filled/rejected/canceled allow new orders |
| `TestNonMMAgents` | Directional agents keep 60 s semantics |
| `TestCancelAndReplace` | `release()` → terminal → new order proceeds |
| `TestGateDisabled` | `MERID_ORDER_GATE_ENABLED=false` bypasses gate |
| `TestStatusTransitions` | Status machine, snapshot, cleanup |
| `TestOrderRouterGateIntegration` | `_route_live` returns `gate:duplicate:*` on block |
