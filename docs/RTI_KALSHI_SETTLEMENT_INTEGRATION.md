# RTI / Kalshi crypto settlement integration (implementation summary)

**Date:** 2026-03-26  

## New / materially changed modules

| Area | Path | Role |
|------|------|------|
| 60-slot settlement grid | `merid/data/settlement_rti_buffer.py` | Per-market buffer keyed by Kalshi expiry; `filled_count`, `avg_received`, `is_settlement_grade` |
| CFB adapter | `merid/signals/cfb_rti_adapter.py` | `LiveCFBRTIAdapter` (HTTP JSON poll), `require_cfb_for_live_trading()`, config validation |
| Feed loop | `merid/data/rti_feed_service.py` | Async loop → `CryptoRTIMonitor.on_rti_tick`; metrics; optional auto-kill on staleness |
| Reconciliation | `merid/data/rti_reconciler.py` | Internal vs reference RTI divergence tracking |
| Execution policy | `merid/event_venues/kalshi/settlement_execution_guard.py` | Final-minute buy blocks for RTI-settled crypto tickers |
| Dashboard layer | `merid/event_venues/kalshi/btc15m_risk.py` | Snapshots for `/crypto/rti` |
| Settlement audit artifact | `merid/signals/settlement_view.py` | `SettlementView` + SHA-256 hash over 60 slots |
| Sizing | `merid/prediction/risk/settlement_risk_model.py` | `estimate_settlement_variance`, `settlement_kelly_shrink_factor` |
| Series helpers | `config/kalshi_crypto_series_meta.py` | `infer_asset_from_kalshi_market_ticker`, `is_rti_settled_kalshi_crypto_ticker` |

## Legacy / deprecated

- `core/rti_stream.py` is now a **thin re-export** of `merid/data/rti_stream.py` (single source of truth for rolling context).

## When MERID will **not** open new risk in the final minute

- **Order router:** For RTI-settled Kalshi crypto tickers, **`buy`** is rejected when `seconds_to_expiry ≤ 60` unless `MERID_RTI_ALLOW_BUY_IF_SETTLEMENT_GRADE=1` and the 60-slot buffer is complete.
- **Filter pipeline:** Continuous trader defaults to `MERID_FILTER_RTI_MIN_SECONDS=61` — candidates inside that window are dropped for RTI crypto markets.
- **Policy:** `MERID_RTI_SETTLEMENT_ORDER_POLICY=block_all` rejects all sides; default `reduce_ok` allows **`sell`**.

## Environment (see `.env.example`)

- `MERID_CFB_RTI_ADAPTER`, `MERID_CFB_RTI_POLL_URL`, `MERID_CFB_RTI_SIMULATE`, `MERID_ALLOW_NULL_CFB`
- `MERID_PROMO_MIN_SETTLEMENT_FILL_RATIO` — optional LIVE promotion gate on historical 60/60 completion ratio

## Tests

- `tests/rti/` — buffer, guard, settlement risk shrinkage

## Operational note

`MERID_CFB_RTI_POLL_URL` must point at JSON your organization is licensed to receive from CF Benchmarks. **CoinGecko / exchange spot** in `KalshiContinuousTrader._get_all_spots` remains **market context only**, not settlement.
