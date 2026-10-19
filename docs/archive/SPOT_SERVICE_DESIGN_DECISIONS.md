# Spot Service Design Decisions

**Date:** 2026-06-08
**Context:** Based on audit in `SPOT_CONTRACT_AUDIT.md`

---

## Decision 1: Provider Set

**Choice:** **Coinbase-only for now**

**Rationale:**
- Current implementation only has Coinbase working
- Adding Kraken/BinanceUS requires significant implementation effort (API integration, rate limit handling, data normalization)
- Coinbase has been reliable for the supported assets (BTC, ETH, SOL, XRP, DOGE)
- De-scoping to Coinbase-only allows focus on fixing core issues (SLA centralization, error handling, health semantics)
- Can add fallback providers later as a separate enhancement

**Documentation Updates Required:**
- Update `unified_spot_service.py` docstring to remove references to Kraken/BinanceUS
- Add comment: "Coinbase-only; fallback providers to be added in future enhancement"
- Update design docs to reflect current reality

---

## Decision 2: Per-Asset SLA Configuration

**Choice:** Centralized single-source-of-truth SLA config

**SLA Thresholds:**
```python
SPOT_SLA = {
    "BTC": {"fresh_s": 5.0, "stale_s": 10.0, "degrade_s": 5.0},
    "ETH": {"fresh_s": 5.0, "stale_s": 10.0, "degrade_s": 5.0},
    "SOL": {"fresh_s": 10.0, "stale_s": 20.0, "degrade_s": 10.0},
    "XRP": {"fresh_s": 5.0, "stale_s": 10.0, "degrade_s": 5.0},
    "DOGE": {"fresh_s": 5.0, "stale_s": 10.0, "degrade_s": 5.0},
}
```

**Rationale:**
- SOL gets 10s degrade threshold to match its 2s timeout (vs 0.5s for others)
- Other assets use 5s degrade threshold (matches 0.5s timeout)
- `fresh_s` = OK threshold, `stale_s` = warn threshold, `degrade_s` = trading gate threshold
- All components (service, watchdog, health snapshot, callers) reference this single config
- Removes the 5s/10s/20s/600s confusion

**Implementation Location:**
- Create `data/spot_sla_config.py` with centralized config
- Import and use throughout stack

---

## Decision 3: Health Semantics

**Choice:** Clear, non-conflicting health definitions

### Spot Health
- **Degraded spot** = Do NOT trade that asset
- Degradation is triggered when spot age > `degrade_s` threshold
- `_asset_degraded[asset]` flag controls trading gate
- Degraded assets return `SpotError(reason="stale")` from `get()`

### Catalog Health
- **Catalog stuck** = Non-blocking diagnostic only
- Renamed to `catalog_lagging` to avoid confusion
- Indicates Kalshi hasn't published new contracts in expected time window
- Trading allowed if MD is fresh, regardless of catalog lag
- Only blocks trading if `no_active_tickers` (truly no markets available)

### WS vs REST Data Plane
- **WS outage** = Global degraded data plane
- Add `ws_forwarder_healthy` flag to WS bridge stats
- When `ws_forwarder_healthy=False`:
  - **DECISION: Treat as DEGRADED mode (not HALT)**
  - System status changes to DEGRADED in health snapshot
  - Trading continues but with tighter MD staleness thresholds
  - This is fail-open: allow trading while WS recovers, but flag degraded state
- No REST fallback for now (was removed; re-introduction is separate enhancement)

**Rationale:**
- Spot degradation is trading gate (fail-closed)
- Catalog lag is informational (not a hard error)
- WS outage is critical (no MD = no trading)
- Clear separation prevents confusion about what "stuck" means

---

## Implementation Order

1. **Phase 1: Design Lock-in** (this document)
2. **Phase 2: Spot Service Core** (P0)
   - Update docs to Coinbase-only
   - Create centralized SLA config
   - Update UnifiedSpotService to use SLA config
   - Introduce SpotError
3. **Phase 3: Caller Consistency** (P0)
   - Fix health snapshot to use service.get()
   - Update SELECT-MARKETS/scheduler
   - Update Signal/unified edge
   - Update E2E watchdog
4. **Phase 4: Health Semantics** (P1)
   - Rename catalog health states
   - Add ws_forwarder_healthy flag
   - Align agent grid behavior
5. **Phase 5: Testing** (P1)
   - Add unit tests for spot service
   - Add tests for catalog_lagging vs MD stale

---

## Migration Notes

**Breaking Changes:**
- `UnifiedSpotService.get()` now returns `SpotPrice | SpotError` instead of `SpotPrice | None`
- Callers must handle `SpotError` types
- Catalog health state "stuck" renamed to "lagging"

**Non-Breaking:**
- SLA thresholds are internal implementation detail
- Health snapshot API unchanged (just implementation fixed)
- Trading behavior unchanged (just clearer semantics)
