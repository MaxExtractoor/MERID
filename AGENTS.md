# MERID Agent Notes

## Verification commands

After changing order-router, port, ledger conversion, or exposure-reconciliation code, run at least:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_order_router_ioc_tif_reconciliation.py tests\kalshi_alignment\test_order_router.py tests\event_venues\kalshi\test_port_ledger_adapter.py tests\event_venues\kalshi\test_kalshi_p0_partial_fill_reconciliation.py tests\event_venues\kalshi\test_kalshi_p0_maker_taker_simulator.py tests\event_venues\kalshi\test_kalshi_p0_exit_order_simulator.py tests\test_loop_15m_bugfixes.py tests\test_loop_15m_decimal_fix_2026_07_29.py tests\test_exit_canonicalization_and_policy_2026_08_07.py -v
```

The `TestExposureReconciliation::test_cancels_stale_gtc_and_syncs_exposure` case now passes after the `UnifiedRiskManager` singleton reset fix.

## Canary / restart reconciliation plan

Goal: validate the `OrderResult` semantic split and the fail-closed port -> ledger adapter in a controlled, observable way before general release.

### Invariants to monitor

1. **No `unfilled_ioc` is treated as a trade.**
   - `OrderResult.success` is `False` for `unfilled_ioc`.
   - `OrderResult.has_execution` is `False` for `unfilled_ioc`.
   - Deployment trade counters (`record_live_trade`, `record_shadow_trade`) only increment when `result.has_execution` is `True`.
   - `KalshiRisk.record_order` / API risk tracking only records `result.executed_count` when `result.has_execution` is `True`.

2. **Exits must have actual execution.**
   - `loop_15m._execute_exit_order` only registers the exit / clears in-flight when `result.has_execution` is `True`.
   - `resting_order_monitor` exit retries only treat `has_execution` as success.

3. **DTO -> ledger conversion is fail-closed.**
   - `port_fill_to_ledger_dict` raises `PortLedgerAdapterError` for missing `fill_id`, `ticker`, `size <= 0`, `price_cents = None`, or invalid `side`/`outcome`.
   - `port_position_to_ledger_dict` raises for missing `ticker`/`size`, missing/invalid `outcome` for non-zero positions, or `average_entry_price_cents <= 0` for non-zero positions.
   - Signed NO exposure (`-size` with empty side) is normalized to `side="no"` and positive `contracts`.

4. **Authenticated reads are behind the port.**
   - `kalshi_tools.kalshi_get_balance` uses `port.get_balance()`.
   - `kalshi_api` order-group endpoints use `port.get_order_groups()`.
   - `order_router` divergence check and `market_state` REST sync use `port.get_orderbook()`.
   - `order_router` portfolio-divergence check uses `port.get_balance()`.

### Canary steps

1. **Dry-run in paper/mock mode.**
   - Route a mix of market IOC, limit IOC, GTC limit, and aggressive exit orders.
   - Confirm `OrderResult.status` is accurate and `unfilled_ioc` never increments trade counters.

2. **Force IOC no-fill scenarios.**
   - Submit an IOC order far from the market; expect `unfilled_ioc`.
   - Verify:
     - `universal_agent` increments `orders_unfilled`, not `orders_rejected` or `orders_placed`.
     - `kalshi_tools` does not call `record_live_trade` / `record_shadow_trade`.
     - `loop_15m` re-arms an exit if `unfilled_ioc` occurs.

3. **Partial fill scenarios.**
   - Submit a limit IOC that fills 50% and cancels the remainder.
   - Confirm `OrderResult.executed_count` equals filled amount and `remaining_count` equals unfilled amount.
   - Confirm risk exposure recorded only for the filled notional.

4. **Position reconciliation with malformed DTOs.**
   - Run `FillsPoller` against a simulated port returning fills with missing `fill_id`, `ticker`, `size=0`, or `price_cents=None`.
   - Confirm malformed fills are skipped, logged, and never reach `KalshiFillsLedger._parse_fill`.

5. **Orderbook / balance port reads.**
   - In mock mode, verify `port.get_orderbook`, `port.get_balance`, and `port.get_order_groups` return normalized results and that no direct `client._request_with_resilience` calls remain in `order_router.py` or `market_state.py`.

### Next-release-gate checklist

- [ ] All `OrderResult.success` consumers in production paths reviewed and switched to `request_completed` / `has_execution` / `executed_count` as appropriate.
- [ ] `OrderResult` unit/contract tests cover `unfilled_ioc`, `rejected`, `accepted_live`, `submitted_live`, `resting`, `partial_live`, `filled_*`, `submission_unknown`, `duplicate_unknown`.
- [ ] `port_ledger_adapter` contract tests cover partial fills, zero-size settled positions, signed NO exposure, missing fill ID, missing ticker, missing price, and invalid side/outcome.
- [ ] `kalshi_tools.py` no longer calls `client.get_balance_result` / `client.get_order_groups` directly.
- [ ] `web/api/kalshi_api.py` order-group endpoints use `port.get_order_groups`.
- [ ] `order_router.py` and `market_state.py` use `port.get_orderbook` for REST orderbook snapshots.
- [ ] Canary run in paper mode shows zero `unfilled_ioc` trades and zero malformed ledger dicts.
- [ ] Rollback plan documented: revert to last commit and restart position cache with `PositionCache.reset()` if anomalous fill/position counts observed.
