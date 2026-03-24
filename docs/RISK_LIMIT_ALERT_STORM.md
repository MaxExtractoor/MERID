# Risk-Limit Alert Storm Audit (Kalshi BTC)

**Date:** 2026-03-24  
**Scope:** Audit and hardening plan for BTC risk-limit alert storms and simultaneous BTC risk breaches across Kalshi markets.

---

## Context

- Incident class: repeated `risk_limit` alerts and concurrent BTC breaches across multiple Kalshi BTC tickers/timeframes.
- Upstream systems: execution pipeline entry point in `merid_core/kalshi/execution_pipeline.py`, risk gate in `merid/prediction/risk.py` (`PredictionMarketRisk.check_order`), alerts in `merid/prediction/alerts.py` (`PredictionAlertManager`).
- Goal: document hypotheses, required invariants, and propose a centralized `RiskEngine` + `AlertRouter` interface with debouncing and roll-up aware limits.

---

## <UPSTREAM> Signals and Limits

- **Order intake:** `OrderIntent` arrives via Kalshi execution pipeline. Pre-flight checks include Kalshi-native `KalshiPositionLimits.check()` plus MERID risk.
- **Risk gate:** `PredictionMarketRisk.check_order()` enforces tiered caps:
  - Per-market: `contracts` and notional (`max_contracts_per_market`, `max_notional_per_market_usd`).
  - Per-event: `max_notional_per_event_usd` across sibling markets.
  - Portfolio: `max_total_notional_usd`, `max_daily_loss_usd`, `max_open_markets`.
  - Category: `category_limits["crypto"]` for BTC clusters; rate limiting (`max_orders_per_minute`, `max_orders_per_hour`).
  - Market-quality guards: tick size, max spread, slippage guard, depth check, post-fee edge.
- **Formulas (BTC focus):**
  - Per-market exposure: `E_m = contracts_m * price_cents_m / 100`.
  - Per-asset (BTC) roll-up: `E_btc = sum(E_m for m in BTC markets)`.
  - Per-event: `E_event = sum(E_m for m in same event_id)`.
  - Portfolio: `E_port = sum(E_m across book)`; daily loss tracked in `_daily_pnl`.
- **Hypotheses for alert storms:**
  - Multiple BTC tickers (15m, 1h) share `crypto` bucket; burst of intents pushes category notional above limit, causing repeated rejects.
  - Dedup window too small vs retry loop → repeated `risk_limit` alerts per ticker.
  - Missing idempotency on `client_tag` or retries on partial fills cause re-checks at stale positions.

---

## <DOWNSTREAM> Controls and Containment

- **Alert fan-out:** `PredictionAlertManager.fire_*` issues `risk_limit` warnings/critical alerts; dedup key is `category:market_id:title` with a 300s suppress window.
- **Execution response:** `KalshiExecutionPipeline` should:
  - Reject with `REJECTED_RISK` when `check_order` fails.
  - Propagate `reason` (e.g., `max_total_notional_usd`, `category_limit_crypto`, `kalshi_position_limit`) into alerts/telemetry.
- **Containment levers:**
  - Quarantine: stop only BTC intents; pause other assets via category flag.
  - Kill switch: `PredictionMarketRisk` halt toggles ALLOW/HALT; unwind optional.
  - Circuit breaker: rate-limit escalations if spread or depth guards fire repeatedly.
  - Retry backoff: exponential backoff on rejected intents to avoid alert storms.

---

## <MODEL> BTC Roll-ups and Invariants

- **BTC aggregation:** All Kalshi BTC tickers/timeframes map to the `crypto` category; enforce per-asset invariant: `E_btc <= category_limits["crypto"].max_notional_usd`.
- **Event consistency:** For each event_id, ensure `sum_open_contracts` matches recorded exposure; reject if inconsistent.
- **Rate-limit accounting:** Respect per-minute/hour counters before alerting; alerts should include current counter vs threshold.
- **Dedup invariants:**
  - Do not emit more than one `risk_limit` alert per `(market_id, category)` within `suppress_seconds`.
  - Include aggregated BTC totals in every BTC `risk_limit` alert: `current`, `limit`, `pct_utilized`.

---

## <CODE> Proposed Interfaces (Pseudocode)

```python
class RiskEngine:
    def check_and_record(order: OrderIntent, ctx: MarketContext) -> RiskDecision:
        # 1) Refresh Kalshi native limits (best-effort)
        kalshi_result = kalshi_limits.check(order.market_ticker, ctx.position, order.qty)
        if not kalshi_result.ok:
            return reject("kalshi_position_limit", kalshi_result)

        # 2) Roll-up positions by market/event/asset/category
        btc_notional = rollup.notional(asset="BTC")
        event_notional = rollup.notional(event_id=order.event_id)

        # 3) Apply tiered limits (per-market -> event -> category -> portfolio)
        if exceeds_market(order): return reject("market_limit", details)
        if event_notional > cfg.max_notional_per_event_usd: return reject("event_limit", details)
        if btc_notional > cfg.category_limits["crypto"].max_notional_usd: return reject("category_limit_crypto", details)
        if rollup.portfolio_notional > cfg.max_total_notional_usd: return reject("portfolio_limit", details)
        if drawdown > cfg.max_daily_loss_usd: return halt("kill_switch_drawdown", details)

        # 4) Quality gates
        if spread_too_wide(order): return reject("spread_guard", details)
        if insufficient_depth(order): return reject("depth_guard", details)

        # 5) Record exposure if approved (idempotent on client_tag)
        exposures.record(order)
        return allow()


class AlertRouter:
    def dispatch(decision: RiskDecision):
        key = f"{decision.reason}:{decision.market_id or 'portfolio'}"
        if dedup.within_window(key, seconds=300):
            return
        payload = {
            "reason": decision.reason,
            "market_id": decision.market_id,
            "btc_notional": decision.rollups.get("BTC"),
            "portfolio_notional": decision.rollups.get("portfolio"),
            "event_notional": decision.rollups.get("event"),
            "limit": decision.limits.get(decision.reason),
            "pct_utilized": decision.utilization(decision.reason),
        }
        severity = "critical" if decision.action in {"HALT", "UNWIND"} else "warning"
        alert_mgr.fire(PredictionAlert(
            category=AlertCategory.RISK_LIMIT,
            severity=severity,
            title=f"Risk limit {decision.reason}",
            message=render(payload),
            market_id=decision.market_id,
            data=payload,
        ))
```

---

## <OBSERVABILITY> Metrics and Tests

- **Metrics/Logs to add:**
  - `risk.btc.notional`, `risk.btc.utilization_pct`, `risk.portfolio.utilization_pct`, `risk.event.utilization_pct`.
  - Alert dedup counters: `alerts.risk_limit.dedup_hits`, `alerts.risk_limit.sent`.
  - Retry/backoff metrics in execution pipeline: `exec.retry.count`, `exec.retry.skipped_due_to_risk`.
  - Attach `client_tag` and `OrderIntent.timestamp` to logs for correlation.
- **BTC shock test (manual outline):**
  1) Seed positions to 80% of BTC category cap using `PredictionMarketRisk.record_fill`.
  2) Replay burst of BTC `OrderIntent` (15m + 1h) with increasing size until breach.
  3) Expect first breach to emit one `risk_limit` alert, subsequent intents suppressed for 300s.
  4) Verify `check_order` returns `REJECTED_RISK` and no exposure is recorded after breach.
  5) Run variant with widened spreads to ensure spread/depth guards trigger distinct reasons.
- **Review targets for reviewers:**
  - `<UPSTREAM>` roll-up formulas and hypotheses.
  - `<DOWNSTREAM>` containment levers.
  - `<CODE>` interfaces for `RiskEngine.check_and_record` and `AlertRouter`.
  - `<OBSERVABILITY>` metrics and BTC shock test steps.

---

## Notes

- Keep all content ASCII only to match existing docs.
- This document is documentation-only; implementing the pseudocode requires follow-on PRs in `merid/prediction/risk.py`, `merid_core/kalshi/execution_pipeline.py`, and `merid/prediction/alerts.py`.
