# MERID Live Trading Status

**Date**: 2026-10-18
**Status**: **LIVE** on Kalshi production — 15-minute crypto markets (BTC, ETH, SOL, XRP, DOGE)

---

## Current Production State

- **Entrypoint**: `web.main_15m_lean:app` on port **8011** via `.\start_15m.ps1`
- **Profile**: `kalshi_crypto_15m_v2` (`config/profiles/kalshi_crypto_15m_v2.yaml`)
- **Venue**: Kalshi production (`external-api.kalshi.com`), exchange shard 2 for crypto 15m markets
- **Entry authorization**: durable — `auto_execution_mode: 1` in `AGENTS.md` front-matter. On each production restart the startup preflight runs and transitions `STARTING → PREFLIGHT_RUNNING → LIVE_ENTRIES_ENABLED` automatically; any failed check → `LIVE_ENTRIES_HALTED` (entries blocked, exits/cancels preserved).
- **Decision path**: Bachelier/TWAP probability baseline vs executable book price → dynamic edge + executable-cost EV gate → bounded sizing (`MERID_MAX_CONTRACTS_PER_ORDER`, `MERID_FIXED_EXPOSURE_CAP_USD`, `MERID_MIN_HELD_PRICE_CENTS`) → canonical Kalshi order router → monitor → reduce-only exits → settle. Exploration canary overlays are off.
- **Exits**: automatic exit policy required (`MERID_DISABLE_EXIT_POLICY` is removed by the launcher); hard profit lock enabled at 90c.

## Safety Invariants Enforced

- Exact integer centi-contract quantities; `Decimal` price/fee/PnL arithmetic.
- Global `fill_id` idempotency and the `intent_id → client_order_id → order_id` chain; unmatched/untrusted fills are quarantined.
- Per-ticker reconciliation across exchange, ledger, cache, monitor, allocator, and pending-order exposure; divergence halts entries.
- Trusted-fill watermark, WebSocket health, and REST freshness gates; staleness halts entries.
- Reduce-only exits cannot expand or reverse exposure; protective exits and the circuit breaker fail closed.
- Trading-shard collateral preflight (`MERID_AUTO_FUND_TRADING_SHARD=1` moves idle cash to shard 2 as an intra-account transfer; `=0` fails closed instead).
- Fail-closed startup on test/demo/sandbox/mock/paper/shadow/simulation/replay routing, mismatched credentials, wrong endpoint, or noncanonical router.

## How Live Is Authorized

Live entries require all of: production runtime profile, `venue_environment=live`, the four entry latches set by `start_15m.ps1` (`TRADING_ENABLED`, `MERID_PM_TRADING_MODE=live`, `MERID_PM_LIVE_ENABLED`, `MERID_ALLOW_LIVE_TRADES`), `MERID_OBSERVE_ONLY=0`, valid credentials matching the configured account, and a passing startup preflight. `MERID_OBSERVE_ONLY=1` is the operator emergency read-only switch and always wins.

## Observed Performance Note

As of this document, the current deployment has been running live and profitable in its most recent session window. Past results in a single session are **not** a guarantee of future performance — the risk gates, not any win streak, are the safety boundary.

## Key References

- [`AGENTS.md`](AGENTS.md) — the full live-trading operational contract (authoritative)
- [`QUICKSTART.md`](QUICKSTART.md) — safe startup modes + live-launch requirements
- [`RUNBOOK.md`](RUNBOOK.md) — kill-switch policy, halt conditions, checklists
- [`ENV_SETUP.md`](ENV_SETUP.md) — environment variable reference
- [`ARCHITECTURE_15M.md`](ARCHITECTURE_15M.md) — 15m/legacy boundaries

---

*Supersedes the April 2026 configuration status, which predated the canonical 15m entrypoint (`web/main_15m_lean.py`), the durable `auto_execution_mode` contract, and the startup preflight state machine. The previous version of this file referenced `python web/main.py` (legacy quarantined entrypoint) — do not use it.*
