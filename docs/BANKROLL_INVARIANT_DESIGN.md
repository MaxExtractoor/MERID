# CT Bankroll Invariant — Design Note

## 1. Spec vs Code Gap

The external spec described a "bankroll invariant" that was *downgraded from kill switch
to WARNING* because `record_trade_result(pnl_cents)` was never called and
`total_pnl_cents` stayed at zero.

**What actually existed before this patch:**

| Symbol | Location (pre-patch) |
|--------|----------------------|
| `record_trade_result` | Only in `merid/risk/capital_engine.py` and `merid/risk/crypto_swarm_risk_btc15m.py` — **not CT** |
| `total_pnl_cents` | Only in `merid/event_venues/kalshi/bracket_risk.py`, `client.py`, `historical_sim.py` — **not CT** |
| `realized_pnl_cents` | Only in `merid/metrics/realized_edge.py` — **not CT** |
| bankroll invariant | **Did not exist** anywhere |

**Conclusion:** The invariant was a spec-level feature that needed to be implemented
from scratch. This patch is that implementation.

---

## 2. What Was Implemented

### 2.1 CT bankroll state (`merid/trading/kalshi_continuous_trader.py`)

Three new fields added to `KalshiContinuousTrader.__init__`:

```python
self._total_pnl_cents: int = 0
self._session_start_balance_cents: Optional[int] = None
self._session_start_bankroll_cents: Optional[int] = None
self._last_invariant_status: Dict[str, Any] = {}
```

Two new methods:

- **`record_trade_result(pnl_cents: int)`** — called once per settled CT market to
  accumulate realized PnL. Never called at fill time.

- **`check_bankroll_invariant(balance_cents, portfolio_cents, *, fee_cents=0, epsilon_cents=500)`** —
  runs the invariant check and returns a status dict.

Both are exposed in `status()["bankroll"]` for UI and log visibility.

### 2.2 Settlement wiring (`merid/reconciliation.py`)

`_fire_settlement_hooks()` now calls `ct.record_trade_result(pnl_cents)` after the
existing `tracker.record_outcome()` block. This is the single authoritative integration
point because:

- It fires exactly when Kalshi removes a position from the portfolio.
- It already has `settled_yes_api` (the actual YES/NO result from the Kalshi REST API).
- It iterates over `KalshiFillsLedger.fills_for_ticker(market_id)`, which stores every
  fill for that market keyed by Kalshi `fill_id` (no duplicates).

---

## 3. Invariant Formula

```
actual_bankroll   = balance_cents + portfolio_cents - fee_cents
expected_bankroll = session_start_bankroll_cents + _total_pnl_cents
delta             = actual_bankroll - expected_bankroll
```

**Why this formula:**

- `balance_cents` is Kalshi's reported cash balance.
- `session_start_bankroll_cents` is the bankroll baseline captured on the first
  invariant call, using the same bankroll definition as the live snapshot.
- `portfolio_cents` is the mark-to-market value of still-open positions.
  When a market settles, Kalshi moves the payout into `balance_cents` and removes the
  position, so `portfolio_cents` drops while `balance_cents` rises — but both the
  actual and expected sides still use the same bankroll definition.
- `_total_pnl_cents` is CT's internal sum of all settled trade results.
- A near-zero `delta` means CT's internally-accounted realized PnL matches the
  change in mark-to-market bankroll. A large delta indicates a wiring problem.

**Known noise sources (why epsilon = 500¢ = $5):**

- Mark-to-market vs cost-basis: open positions contribute to `portfolio_cents` at
  current market price, while CT's accounting only knows cost. This creates transient
  deltas on open positions that resolve at settlement.
- Race window: Kalshi may update `balance_cents` and remove the portfolio position in
  separate API responses; a brief divergence during that window is expected.
- Fees are not currently stored per-fill in `KalshiFillsLedger` (no `fee_cents` field),
  so computed PnL is pre-fee. Once fees are added to fills, subtract them in the
  settlement hook to tighten the invariant.

---

## 4. Kill-Switch Graduation Criteria

The invariant is **WARNING-only** until all of the following are confirmed:

1. `record_trade_result()` fires reliably on **every** market settlement across multiple
   live sessions (verify via `status()["bankroll"]["total_pnl_cents"]` growing correctly).
2. `delta_cents` stays within `epsilon_cents` (500¢) except during expected race windows
   (i.e., within a few seconds of settlement).
3. No systematic drift: `delta_cents` does not accumulate over multiple settlement cycles.
4. The "Agent D settled fill triggers kill switch" scenario (replay in dry-run) does
   not trip the invariant.

**To enable the kill switch:**

```python
_CT_BANKROLL_DELTA_KILL_CENTS = int(os.getenv("CT_BANKROLL_DELTA_KILL_CENTS", "0"))
# 0 = disabled; set to e.g. 5000 ($50) to enable
```

In `check_bankroll_invariant`, after the WARNING log:
```python
if _CT_BANKROLL_DELTA_KILL_CENTS > 0 and abs(delta) > _CT_BANKROLL_DELTA_KILL_CENTS:
    # initiate controlled CT shutdown + emit CRITICAL alert
    ...
```

Do **not** set this env var in production until all graduation criteria are met.

---

## 5. Exposure Math Notes

CT tracks notional exposure via `DailyRiskState.group_notional`, which accumulates
per `trade_cycle()` call and is only cleared by `reset_daily()`. This is cost-basis
exposure (what CT paid), **not** mark-to-market.

The bankroll invariant must **not** compare `cash + exposure` to `cash + portfolio`.
Exposure is a risk-limit input; bankroll uses mark-to-market `portfolio_cents`.
Using the same bankroll definition on both sides prevents false warnings where the
delta is merely `(exposure - portfolio_mark)`.

Settled positions are automatically removed from `portfolio_cents` by Kalshi but are
**not** automatically removed from `group_notional`. `reset_daily()` handles this at
rollover. For intra-day settlement, the exposure slightly over-counts until the next
daily reset; this is conservative (safe) behavior.

---

## 6. Upstream / Downstream Scan Results

| Area | Status |
|------|--------|
| `KalshiFillsLedger` fields for PnL | ✅ `side`, `action`, `count`, `price_cents` sufficient for settlement PnL calculation |
| `KalshiFillsLedger` has no `fee_cents` field | ⚠️ PnL is pre-fee until fees are added to fills |
| `event_stream` (`LiveEventStream`) | ✅ Not used for CT bookkeeping — best-effort only, CT never subscribes |
| `KalshiRiskManager.kill_switch` | ✅ Independent of CT invariant; driven by daily loss / drawdown via `record_pnl()` |
| `total_pnl_cents` in bracket_risk / historical_sim | ✅ Separate feature; no conflict |
| CT `status()` exposes bankroll state | ✅ Via `status()["bankroll"]` |
