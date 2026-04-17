# P0 Crypto Guardrails — PR & Merge Checklist

**Status:** ✅ All CI tests passing (62/62)  
**Scope:** P0-001, P0-002, P0-003 patches + CI validation  
**Lock Date:** 2026-04-11

---

## ⚠️ TEAM POLICY — READ FIRST

> **No new UI surface area for crypto/Kalshi until this checklist is complete.**
>
> This means: no new dashboards, no new views, no new toggles, no new React components for the crypto trading flow until:
> 1. CI tests in `tests/ci/` pass locally and in CI
> 2. Existing views are validated against the new P0 guardrails
>
> New UX must be layered **on top of** verified behavior, not in parallel with unverified changes.

---

## ✅ Pre-Merge Checklist

### 1. Run CI Tests (Mandatory)

```bash
# From repo root
pytest tests/ci/ -v
```

**Expected:** 62 passed, 0 failed

**Coverage:**
- `test_kalshi_series_meta_consistency.py` — Series ticker uniqueness, prefix/suffix alignment
- `test_spot_staleness_consistency.py` — `max_spot_age_seconds()` behavior, metric registration
- `test_strike_asset_consistency.py` — Cross-asset validation, rejection reasons, metric increments
- `test_settlement_guard_timeframes.py` — Per-timeframe guard values (15m=30s, 1h=60s, daily+=300s)

### 2. Validate Existing UI Surfaces

Use current MERID UI/UX (no new panels) to confirm:

| Surface | What to Check |
|---------|---------------|
| **Discover** | Kalshi market discovery still resolves correct series tickers |
| **Analyze** | Spot prices show age; stale prices trigger warnings |
| **Consensus** | Edge calculations use fresh spot data |
| **Size** | Strike selector rejects cross-asset mismatches (check logs for `ASSET_TICKER_MISMATCH`) |
| **Execute** | Settlement guard values logged per-timeframe |
| **Monitor** | Prometheus metrics visible: `merid_pm_spot_age_seconds`, `merid_pm_spot_staleness_violations_total`, `merid_pm_strike_asset_mismatch_total` |
| **Protect** | Kill switches fire on stale spot > 120s (or env override) |

**Log Patterns to Verify:**
```
# P0-001: Spot staleness violation
[model] Stale spot price for asset=BTC market=KXBTC15M-... age=145s > 120s
merid_pm_spot_staleness_violations_total{asset="BTC",market_id="KXBTC15M-..."} 1

# P0-002: Asset-ticker mismatch
[strike] Asset-ticker mismatch: asset=BTC ticker=KXETH15M-... inferred_asset=ETH
merid_pm_strike_asset_mismatch_total{asset="BTC",ticker="KXETH15M-...",inferred_asset="ETH"} 1
RejectionReason.ASSET_TICKER_MISMATCH

# P0-003: Settlement guard per timeframe
[settlement] guard_seconds=30 for BTC 15m (RTI TWAP)
[settlement] guard_seconds=300 for BTC daily (Reference Rate)
```

### 3. Verify Metrics Endpoints

```bash
# Check metrics are registered
curl http://localhost:8011/metrics | grep merid_pm_spot
curl http://localhost:8011/metrics | grep merid_pm_strike
```

Expected output should include:
- `merid_pm_spot_staleness_violations_total`
- `merid_pm_spot_age_seconds`
- `merid_pm_strike_asset_mismatch_total`

---

## 📁 Files Changed

### P0-001: Spot Staleness Consistency
- `merid/prediction/strategy.py` — Uses `max_spot_age_seconds()`
- `merid/prediction/model.py` — Emits staleness metrics
- `monitoring/metrics.py` — New counter/gauge + helpers

### P0-002: Asset-in-Ticker Validation
- `merid/prediction/kalshi_strike_selector.py` — `asset_in_ticker()` + `RejectionReason.ASSET_TICKER_MISMATCH`

### P0-003: Per-Timeframe Settlement Guard
- `merid/event_venues/kalshi/cfb_settlement.py` — `_SETTLEMENT_GUARD_BY_TIMEFRAME` lookup table

### CI Tests
- `tests/ci/test_kalshi_series_meta_consistency.py`
- `tests/ci/test_spot_staleness_consistency.py`
- `tests/ci/test_strike_asset_consistency.py`
- `tests/ci/test_settlement_guard_timeframes.py`

---

## 🚫 Merge Blockers

Do not merge if:
- [ ] Any CI test fails
- [ ] Spot staleness metrics not visible in `/metrics`
- [ ] Cross-asset validation not rejecting mismatches in logs
- [ ] Settlement guards not logged per-timeframe

---

## ✅ Sign-Off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Author | Cascade | 2026-04-11 | ✅ |
| CI Gate | — | — | [ ] |
| UI Validation | — | — | [ ] |
| Merge Approver | — | — | [ ] |

---

## References

- Audit Report: `docs/audits/crypto_spot_kalshi_wiring_2026-04-11.md`
- CF Benchmarks Methodology: RTI (Real-Time Index) TWAP vs Reference Rate
- Kalshi API Docs: Settlement timing rules
