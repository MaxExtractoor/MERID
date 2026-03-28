# Portfolio Risk Audit Checklist

This checklist documents the risk model in use for MERID's Kalshi prediction-market trading.
All items must be verified before each phase promotion or live-trading enablement.

---

## 1. Per-trade caps (bankroll fraction)

- [ ] `MERID_BANKROLL_FRACTION` env is set and ≤ 0.03 (3%).
- [ ] `per_trade_cap` ($) in `btc_promotion_config.py` matches the current phase.
- [ ] Position sizer reads `bankroll_fraction` from config — **no hardcoded dollar caps**.
- [ ] Sizing verified: `notional = bankroll × bankroll_fraction` before group-cap reduction.

## 2. Per-asset caps

- [ ] Asset universe limited to configured `unlocked_assets` for the current phase:
  - PHASE_0: BTC only
  - PHASE_1: BTC only
  - PHASE_2: BTC, ETH
  - PHASE_3: BTC, ETH, SOL, XRP, DOGE
- [ ] `KalshiContinuousTrader._CRYPTO_ASSETS` matches PHASE_3 `unlocked_assets`.
- [ ] MarketFilter `allowed_underlyings` aligned with trader asset list.

## 3. Per-group caps (group_notional_cap)

- [ ] `MERID_GROUP_NOTIONAL_CAP` env is set (default $50).
- [ ] `KalshiContinuousTrader._apply_risk_checks()` enforces group-notional cap.
- [ ] `group_id` is always derived from `TradingCandidate.underlying + timeframe` —
      **no local guessing logic** in the trader.
- [ ] `DailyRiskState.group_notional` map is fully cleared by `reset_daily()`.
- [ ] After `reset_daily()`, `group_notional == {}` — verified by unit test.

## 4. Daily loss cap

- [ ] `MERID_DAILY_LOSS_CAP` env is set (e.g. `100.0` = $100 max daily loss).
- [ ] `DailyRiskState.daily_loss` accumulates filled PnL losses intra-day.
- [ ] Trader halts (or reduces to zero sizing) once `daily_loss >= daily_loss_cap`.
- [ ] Cap resets to 0 on `reset_daily()`.

## 5. Maximum exposure

- [ ] `max_exposure` (fraction of equity) from current phase config is respected.
- [ ] Total open notional ≤ `equity × max_exposure` checked before each new order.

## 6. Confidence gate (swarm consensus)

- [ ] `MERID_MIN_CONFIDENCE` env is set (default 0.55).
- [ ] `OpinionStrategy._apply_confidence_clamp()` is called before sizing.
- [ ] Clamped confidence is passed to `_apply_risk_checks()`, **not** raw swarm output.
- [ ] `max_confidence` default 0.95 caps any individual agent opinion.

## 7. Fills ledger (anti-ghost-trade)

- [ ] `KalshiFillsLedger` is the **sole** canonical source for:
  - UI fills table
  - Position reconstruction
  - PnL calculation
- [ ] Every fill upserted with a non-empty Kalshi `fill_id` (rejected otherwise).
- [ ] Duplicate WS/REST deliveries are idempotently merged, never double-counted.
- [ ] Divergence monitor compares ledger-derived positions vs. Kalshi `GET /portfolio/positions`.
- [ ] Divergence alerts logged (and optionally pushed to Prometheus/metrics).

## 8. Settlement poller (cursor integrity)

- [ ] Cursor stored in Redis key `merid:kalshi:settlement_cursor`.
- [ ] Cursor history retained (key `merid:kalshi:settlement_cursor_history`, last 50).
- [ ] Falls back to in-memory cursor when Redis unavailable (no crash).
- [ ] `_seen_ids` set provides secondary deduplication beyond cursor.
- [ ] Poller survives upstream errors (empty responses, 5xx).
- [ ] Crashing downstream handlers do not prevent cursor advancement.

## 9. Execution gates / env flags

| Flag | Default | Purpose |
|------|---------|---------|
| `MERID_EXEC_GATE_REQUIRE_KALSHI_WS` | `1` | Block orders when WS is stale |
| `MERID_PM_LIVE_ENABLED` | `false` | Must be `true` to enter LIVE mode |
| `MERID_PM_TRADING_MODE` | `paper` | Override to `live` for live trading |
| `MERID_DAILY_LOSS_CAP` | `100.0` | Hard daily loss cap in $ |
| `MERID_GROUP_NOTIONAL_CAP` | `50.0` | Per-group notional cap in $ |
| `MERID_MIN_CONFIDENCE` | `0.55` | Min clamped confidence to trade |
| `MERID_BANKROLL_FRACTION` | `0.01` | Max fraction of bankroll per trade |
| `KALSHI_WS_STALE_THRESHOLD` | `60` | Seconds before WS flagged stale |

- [ ] All gates default to safe (fail-closed) values in production.
- [ ] Legacy `merid_core` execution paths remain behind their env gate.

## 10. Phase promotion verification

Before each phase promotion:
- [ ] Run `py -m pytest tests/event_venues/kalshi -v` — all green.
- [ ] Run `py -m pytest tests/test_settlement_poller_boundary_probe.py -v` — all green.
- [ ] Run `py -m pytest tests/trading/test_kalshi_continuous_trader.py -v` — all green.
- [ ] Group-cap reset scenario: flood a group, trip cap, call `reset_daily()`, confirm map empty.
- [ ] `btc_promotion_config.py` phase entry matches current equity/days/trades criteria.
- [ ] `validate_before_lift()` called with latest backtest report — returns `{"ok": True}`.

---

*Last updated: 2026-03-28*
*Owner: MaxExtractoor/MERID risk team*

