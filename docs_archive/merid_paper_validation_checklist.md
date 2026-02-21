# MERID Paper Validation Checklist

Run this checklist any time you add a market, venue, or strategy.

## 1. Paper-First Mode Invariant

| Check | How to verify | Status |
|-------|--------------|--------|
| Canonical `TradeMode` enum exists | `trading/trade_mode.py` — `MOCK`, `PAPER`, `LIVE` | |
| Default mode is `PAPER` | `MERID_TRADE_MODE` env var defaults to `paper` | |
| `get_trade_mode()` is the single source of truth | All layers import from `trading.trade_mode` | |
| MOCK → LIVE transition blocked | `set_trade_mode()` raises `RuntimeError` | |
| LIVE requires `MERID_ALLOW_LIVE_TRADES=true` | `set_trade_mode()` checks env | |
| `assert_not_live()` available for safety nets | Import from `trading.trade_mode` | |

## 2. Mode Guard Enforcement

| Check | How to verify | Status |
|-------|--------------|--------|
| `TradingVenueAdapterBase.submit_order()` checks `get_trade_mode()` | `trading/adapters/base.py` — rejects if mode != LIVE | |
| `VenueGate.check_can_trade()` blocks SIM mode | `merid/prediction/venue_gate.py` | |
| `VenueGate.should_simulate_fill()` returns True in PAPER | Tested in `test_paper_reconciliation.py` | |
| `TradingModeController.can_execute_live()` returns False in PAPER | `trading/mode_controller.py` | |
| `TradingGuard.evaluate()` returns SIMULATE for non-live modes | `trading/guards/trading_guard.py` | |

## 3. Static Wiring (per market/venue)

- [ ] Market appears in: config, venue adapter market list, paper engine, router, UI watchlists
- [ ] Strategy is allowed to trade it (whitelist in config)
- [ ] Venue adapter accepts `mode` and never talks to real-money endpoints if `mode != LIVE`

## 4. Data Path

- [ ] Live prices for symbol arrive in unified price feed (`data/live_price_feed.py`)
- [ ] Prices visible to: agents, paper engine, UI charts
- [ ] No symbol has "price unknown" while being tradable

## 5. Intent → Order → Fill Path

- [ ] Agent decision logged via `trading/audit_trail.py::record_intent()`
- [ ] Paper engine fill logged via `trading/audit_trail.py::record_fill()`
- [ ] Causality chain: `intent_id` links intent → order → fill
- [ ] Pre/post snapshot hashes recorded on each fill
- [ ] Audit trail persisted to `data/trade_audit.jsonl`

## 6. Paper State Persistence

- [ ] Positions persisted to `data/paper_positions.json` on every fill/close
- [ ] Trade history persisted (last 500 trades per portfolio)
- [ ] State restored on startup via `_load_paper_state()`
- [ ] Kill-and-restore test: balances and positions match pre-shutdown

## 7. Reconciliation

- [ ] `trading/reconciliation.py::run_reconciliation()` runs without error
- [ ] Balance identity: `cash + sum(positions) == equity`
- [ ] Trade count: `total_trades == len(trade_history)`
- [ ] Win/loss sum: `winning + losing <= total`
- [ ] Per-position PnL: recomputed from price feed matches stored value
- [ ] Cash non-negative (unless leveraged)
- [ ] Periodic reconciliation runs every 5 minutes (background thread)
- [ ] Shutdown reconciliation runs and logs final hash

## 8. API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/trade-mode` | GET | Current canonical trade mode |
| `/api/v1/reconciliation/run` | GET | On-demand reconciliation |
| `/api/v1/reconciliation/status` | GET | Last periodic report |
| `/api/v1/audit-trail/summary` | GET | Audit trail stats |
| `/api/v1/audit-trail/entries` | GET | Recent audit entries |

## 9. Test Suite

Run: `py -m pytest tests/test_paper_reconciliation.py -v`

| Class | Tests | What it covers |
|-------|-------|----------------|
| `TestCanonicalTradeMode` | 8 | Enum values, defaults, transitions, safety |
| `TestModeGuardOnAdapter` | 2 | Adapter rejects orders in paper/mock |
| `TestPaperStatePersistence` | 1 | Save/load cycle preserves positions + trades |
| `TestReconciliation` | 3 | Runs, serializable, enum values |
| `TestAuditTrail` | 2 | Intent→fill chain, summary |
| `TestVenueGateAlignment` | 5 | VenueGate modes, blocks, simulates |
| `TestRuntimeConfigAlignment` | 4 | Runtime config modes, controller defaults |

**Total: 25 tests**

## 10. Files Created/Modified

### New files
- `trading/trade_mode.py` — Canonical `TradeMode` enum + global accessor
- `trading/reconciliation.py` — Balance/PnL reconciliation engine
- `trading/audit_trail.py` — Append-only trade audit trail (JSONL)
- `tests/test_paper_reconciliation.py` — 25-test validation suite
- `docs/merid_paper_validation_checklist.md` — This file

### Modified files
- `trading/adapters/base.py` — Mode guard in `submit_order()`
- `trading/paper_trading.py` — Trade history persistence (save + load)
- `web/api/system_endpoints.py` — Reconciliation + audit trail API endpoints
- `web/main.py` — Periodic reconciliation in startup/shutdown lifecycle
