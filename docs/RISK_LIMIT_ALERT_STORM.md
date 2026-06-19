# Risk-Limit Alert Storm Audit (Kalshi BTC)

Context: Multiple `risk_limit` alerts fired within the same second across many BTC tickers (e.g., `KXBTC-26MAR2417-*`, `KXBTC15M-*`). Treat as a systemic fault, not a one-off.

<UPSTREAM>
- Control flow (likely path): Kalshi orderbook fetch (`web/api/v1/kalshi/markets/...` → `merid/event_venues/kalshi/*`) → signal + sizing (`merid/prediction/trading_agent.py`, `merid/prediction/strategy.py`) → risk (`merid/prediction/risk.py::PredictionMarketRisk.check_order`, `merid_core/kalshi/execution_pipeline.py::_check_risk`) → alerting (`merid/prediction/alerts.py::PredictionAlertManager.fire_risk_breach`).
- Hypotheses for simultaneous BTC breaches:
  - Notional aggregation bug: per-contract notional multiplied twice or per-leg grossing instead of netting; per-contract vs per-market vs per-underlying caps mixed.
  - Portfolio roll-up confusion: BTC ladder (`KXBTC-...`) and 15m (`KXBTC15M-...`) treated as distinct underlyings so shared BTC cap never enforced until per-market caps all trigger.
  - Stale exposure ledger: fills recorded twice or never cleared on close → inflated open interest and storm of breaches.
  - Race/duplication: async retry path bypasses dedup so multiple `_check_risk` calls with identical batch emit multiple alerts.
  - Sizing spike: Kelly/edge sizing not clipped by current exposure snapshot; missing max-size clamp when price depth thin.
  - Rate/reset bug: per-minute order window counters not reset, causing cascading rejects that all emit alerts.
- Where to inspect first:
  - `merid/prediction/risk.py` exposure bookkeeping (`_exposures`, `_category_notional`, `_category_contracts`), rate-limit counters, circuit-breaker log.
  - `merid_core/kalshi/execution_pipeline.py::_check_risk` for total_notional estimation and per-market position math.
  - `merid/prediction/trading_agent.py` sizing path (`_btc15m_risk`, `KalshiStrategy`, `PredictionMarketRisk.check_order` integration).
  - `merid/prediction/alerts.py` dedup key (`category:market:title` over 5 minutes) to confirm dedup scope.
- Invariants/assertions to add:
  - After every fill/close: `sum(per-market notional) == portfolio_notional` (within epsilon) and category totals match per-exposure roll-ups.
  - Before alert: assert per-underlying aggregation includes ladder + intraday variants (normalize ticker to asset bucket).
  - Ensure `processed_intents` / idempotency keys are monotonic and cleared daily; assert no duplicate client_tags in batch.
  - Assert rate-limit counters reset on schedule and cannot go negative; add monotonic timestamp check on `_recent_prices`.
  - If `RiskAction.HALT` triggered, enforce single alert per underlying + snapshot hash (see <CODE> AlertRouter).

<DOWNSTREAM>
- Intended propagation when `risk_limit` critical fires:
  - Pause trading for impacted market/underlying; trigger circuit breaker (`hardening/circuit_breaker.py`) or kill switch (`PredictionMarketRisk.halt`).
  - Quarantine: stop new intents for that underlying in `merid_core/kalshi/execution_pipeline` and `merid/prediction/trading_agent`.
  - Notify operators/UI: surface in PM dashboard, Telegram sink, and API status (`/api/risk/protections`), include unblock guidance.
  - Logging: structured event with exposure breakdown, decision, and limit values.
- Failure modes if weak:
  - System keeps trading despite breach (alert-only path); or global halt trips from one noisy market.
  - Alert storm overwhelms sinks; dedup missing so downstream retries spam Slack/Telegram.
  - Circuit stays open but agents continue via bypass path (e.g., paper/live mismatch).
  - Manual unlock occurs while stale exposure still inflated → immediate re-trip.
- Stronger safeguards:
  - Global kill-switch plus per-underlying quarantine with cooldown (e.g., 5–15 minutes, success criteria).
  - Deduplicate identical alerts within window per (account, underlying) with jitter backoff.
  - Health gate: trading loop checks `risk_protections.state` each cycle; block if OPEN or QUARANTINED.
  - Auto-unwind flag from risk engine: if breach severity >= unwind threshold, enqueue close orders and block opens.

<MODEL>
- Tiers:
  - Per-contract: max contracts/order; price tick and min depth guards.
  - Per-market: max contracts + notional per ticker; clamp Kelly size to min(remaining headroom, liquidity).
  - Per-underlying (BTC bucket): normalize tickers (`KXBTC-*`, `KXBTC15M-*`, `KXBTC-26MAR2417-*`) to `BTC`; cap total notional and delta-adjusted exposure.
  - Strategy-level: caps per strategy/agent_id across its markets.
  - Global: portfolio total notional, daily loss, drawdown, and venue-exposure caps.
- Formulas:
  - Per-contract notional: `notional_contract = contracts * price_cents / 100`.
  - Per-market exposure: `E_market = Σfills_side_signed * price_cents / 100` (signed by YES/NO), headroom = `limit_market - |E_market|`.
  - Underlying aggregate: `E_underlying = Σ_market∈BTC E_market`; notional cap: `|E_underlying| <= limit_underlying`; PnL-based cap: `daily_pnl_underlying >= -limit_daily_loss_underlying`.
  - Portfolio aggregate: `E_portfolio = Σ_underlying |E_underlying|`; enforce `E_portfolio <= limit_portfolio` and `daily_pnl >= -limit_daily_loss_global`.
  - Hysteresis/debounce: breach threshold T_high, clear threshold T_low (e.g., 95% / 85% of limit) with 60–120s stability window before reopening; rate-limit alerts to 1 per underlying per window.

<CODE>
- Refactors/fixes:
  - Centralize checks in a single risk engine façade (wrap `PredictionMarketRisk` + `execution_pipeline._check_risk`) so all order paths call `RiskEngine.check_and_record`.
  - Add normalized underlying bucket helper reused by both sizing and risk aggregation (e.g., `btc` bucket for ladder + 15m).
  - Enforce idempotent alerting via AlertRouter with per-underlying dedup + cooldown and explicit suppression reasons.
  - Guard async/retry paths: all `OrderIntent` submissions must pass through `RiskEngine.check_and_record` (no bypass on retries, paper/live parity).
  - Logging: structured log for each decision with `account_id`, `agent_id`, `market_id`, `underlying`, `portfolio_snapshot_hash`, `exposure_breakdown`, `limit_values`, `decision`.
- Example interfaces/snippets:
  - `RiskEngine.check_and_record(order_batch)`:
    ```python
    class RiskEngine:
        def __init__(self, risk: PredictionMarketRisk, alerts: PredictionAlertManager):
            self.risk = risk
            self.alerts = alerts

        def check_and_record(self, account_id: str, order_batch: list[OrderIntent]) -> list[RiskDecision]:
            snapshot = self._build_snapshot()
            decisions = []
            for intent in order_batch:
                underlying = normalize_underlying(intent.market_ticker)
                check = self.risk.check_order(
                    market_id=intent.market_ticker,
                    event_id=extract_event_id(intent.market_ticker),
                    side=intent.side,
                    contracts=intent.qty,
                    price_cents=Decimal(intent.price * 100),
                    category="crypto",
                )
                decision = RiskDecision.from_check(intent, check, snapshot)
                decisions.append(decision)
                self._record(decision)  # update exposure if allowed
                if not decision.allowed:
                    self._emit_alert(account_id, underlying, decision, snapshot)
            return decisions
    ```
  - `AlertRouter` with dedup window:
    ```python
    class AlertRouter:
        def __init__(self, sinks, window_seconds=120):
            self.window = window_seconds
            self.last: dict[tuple, float] = {}

        def publish(self, alert: PredictionAlert) -> None:
            key = (alert.category, alert.market_id, alert.data.get("underlying"))
            now = time.time()
            if key in self.last and now - self.last[key] < self.window:
                return
            self.last[key] = now
            for sink in self.sinks:
                sink(alert)
    ```
  - Test sketch (BTC shock):
    ```python
    def test_btc_shock_dedup():
        engine = RiskEngine(risk, alerts)
        batch = [make_intent(ticker) for ticker in ladder_and_15m]
        decisions = engine.check_and_record("acct1", batch)
        assert all(not d.allowed for d in decisions)
        assert alerts.count(AlertCategory.RISK_LIMIT, underlying="BTC") == 1
        assert engine.risk.is_halted
    ```

<OBSERVABILITY>
- Metrics:
  - `risk.breach.count{underlying,reason,severity}` per minute.
  - `risk.rejected.fraction{agent,underlying}` = rejected / attempted orders.
  - `risk.trading_active{underlying}` gauge; alert if breach occurred while gauge stayed active.
  - `risk.alerts.deduped` vs `risk.alerts.emitted` to detect storms.
  - `risk.halt.duration{scope}` and `risk.unwind.inflight`.
- Logging/structured fields:
  - Include `account_id`, `agent_id`, `market_id`, `underlying`, `category`, `decision` (`allow/reject/halt/unwind`), `exposure_breakdown` (per-market + per-underlying), `limits`, `portfolio_snapshot_hash`, `alert_id`.
  - Sample at 10–20% when healthy; 100% when breach/halt active; keep bounded history in `PredictionAlertManager`.
- Safety nets:
  - If risk engine detects inconsistent state (checksum mismatch, NaN exposure, missing market), enter degraded mode: halt opens, allow only closes, emit `kill_switch` alert, refresh exposures from ledger, and require operator ack to resume.
