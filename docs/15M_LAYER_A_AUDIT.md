# Layer A Audit: Kalshi Access & Risk Envelope

**Scope**: Kalshi client, bankroll, fills, settlement, risk envelope

---

## Environment Contract

### Required Environment Variables (Live Trading)
**Location**: web.main_15m.py lines 239-246

```python
required_vars = [
    "KALSHI_API_KEY_ID",
    "KALSHI_PRIVATE_KEY_PATH",
]
```

**Demo Mode Override**:
- If `MERID_DEMO_MODE=1`, validation is skipped and mock credentials are set
- Mock credentials: `KALSHI_BASE_URL`, `KALSHI_EMAIL`, `KALSHI_PASSWORD`, `KALSHI_API_KEY_ID`, `KALSHI_API_KEY_SECRET`

**Verification**: ✅ Correct
- Live trading requires API_KEY_ID + PRIVATE_KEY_PATH (newer format)
- Demo mode allows startup without Kalshi credentials for testing
- Demo mode explicitly warns it's for development/testing only

---

## Kalshi Client

**Module**: `merid.event_venues.kalshi.client`
**Factory**: `get_kalshi_client()`
**Startup**: web.main_15m.py lines 331-344

```python
async def _start_kalshi_client() -> None:
    try:
        from merid.event_venues.kalshi.client import get_kalshi_client
        client = get_kalshi_client()
        _startup_state["kalshi_client"] = client
        logger.info("[KALSHI-CLIENT] Kalshi client initialized")
```

**Verification**: ✅ Correct
- Client initialized and stored in _startup_state
- Exception handling with logging and re-raise
- Used by settlement poller (passed as dependency)

---

## Bankroll Service

**Module**: `merid.event_venues.kalshi.bankroll_service_v2`
**Factory**: `get_bankroll_service()`
**Startup**: web.main_15m.py lines 347-361

```python
async def _start_bankroll_service() -> None:
    try:
        from merid.event_venues.kalshi import get_bankroll_service
        bankroll_service = await get_bankroll_service()
        await bankroll_service.start()
        _startup_state["bankroll_service"] = bankroll_service
        logger.info("[BANKROLL] Bankroll service started")
```

**Verification**: ✅ Correct
- Bankroll service started and stored in _startup_state
- Passed to Kalshi15mLoop constructor
- Used for balance tracking and equity updates

---

## Fills Poller

**Module**: `merid.event_venues.kalshi.fills_poller`
**Factory**: `get_fills_poller()`
**Startup**: web.main_15m.py lines 471-485

```python
async def _start_fills_poller() -> None:
    try:
        from merid.event_venues.kalshi.fills_poller import get_fills_poller
        fills_poller = get_fills_poller()
        await fills_poller.start()
        logger.info("[FILLS-POLLER] Fills poller started")
```

**Verification**: ✅ Correct
- Fills poller started for fill reconciliation
- Shutdown handler calls stop() on stored instance

---

## Settlement Poller

**Module**: `merid.event_venues.kalshi.settlement_poller`
**Factory**: `get_settlement_poller(kalshi_client)`
**Startup**: web.main_15m.py lines 488-508

```python
async def _start_settlement_poller() -> None:
    try:
        from merid.event_venues.kalshi.settlement_poller import get_settlement_poller
        kalshi_client = _startup_state.get("kalshi_client")
        if not kalshi_client:
            raise ValueError("Kalshi client not initialized before settlement poller")
        settlement_poller = get_settlement_poller(kalshi_client)
        await settlement_poller.start()
```

**Verification**: ✅ Correct
- Kalshi client dependency validated before settlement poller
- Settlement poller started for contract settlement
- Shutdown handler calls stop() on stored instance

---

## Risk Envelope

**Module**: `merid.risk.profiles.kalshi_crypto_15m_risk_envelope`
**Factory**: `get_kalshi_crypto_15m_risk_envelope()`
**Usage**: merid.loop_15m.py lines 96-100 (initialization), lines 175-198 (per-cycle updates)

```python
# Initialization in Kalshi15mLoop.__init__
if profile == "kalshi_crypto_15m_v2":
    try:
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
        self._risk_envelope = get_kalshi_crypto_15m_risk_envelope()
        logger.info("[15m-LOOP] Initialized risk envelope for profile")
    except Exception as e:
        logger.warning("[15m-LOOP] Failed to initialize risk envelope: %s", e)

# Per-cycle update in _run_one_cycle
if self._risk_envelope:
    from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import safe_update_envelope_equity
    update_success = safe_update_envelope_equity(self._risk_envelope)
    if update_success:
        # Log band transitions
        current_multiplier = self._risk_envelope.per_trade_risk_multiplier
        if current_multiplier != self._last_risk_multiplier:
            logger.info(
                "[15m-LOOP] Risk band transition: %.2f → %.2f (drawdown=%.2f%%)",
                self._last_risk_multiplier,
                current_multiplier,
                self._risk_envelope.current_drawdown_pct * 100,
            )
            self._last_risk_multiplier = current_multiplier
    
    # Check if halted due to drawdown
    if self._risk_envelope.is_halted:
        logger.warning(
            "[15m-LOOP] Cycle %d skipped: drawdown halt (drawdown=%.2f%% >= %.2f%%)",
            tick,
            self._risk_envelope.current_drawdown_pct * 100,
            self._risk_envelope.drawdown_halt_pct * 100,
        )
        return  # Skip cycle
```

**Verification**: ✅ Correct
- Risk envelope only initialized for kalshi_crypto_15m_v2 profile
- `safe_update_envelope_equity()` only called from Kalshi15mLoop._run_one_cycle()
- Band transitions logged
- Drawdown halt check skips cycle if halted
- Exception handling with warning (non-fatal if envelope fails to initialize)

---

## Envelope Metrics Endpoint

**Location**: web.main_15m.py lines 146-181

```python
@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus-compatible metrics endpoint for risk envelope monitoring."""
    try:
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
        envelope = get_kalshi_crypto_15m_risk_envelope()
        
        metrics_text = f"""# HELP kalshi_risk_envelope_band Current risk band (0=normal, 1=reduced, 2=critical, 3=halt)
# TYPE kalshi_risk_envelope_band gauge
kalshi_risk_envelope_band {envelope.current_band}

# HELP kalshi_risk_envelope_distance_to_halt_pct Distance to halt threshold as percentage
# TYPE kalshi_risk_envelope_distance_to_halt_pct gauge
kalshi_risk_envelope_distance_to_halt_pct {envelope.distance_to_halt_pct:.4f}

# HELP kalshi_risk_envelope_per_trade_multiplier Per-trade risk multiplier (0.0-1.0)
# TYPE kalshi_risk_envelope_per_trade_multiplier gauge
kalshi_risk_envelope_per_trade_multiplier {envelope.per_trade_multiplier:.4f}

# HELP kalshi_risk_envelope_is_halted Whether trading is halted (1=yes, 0=no)
# TYPE kalshi_risk_envelope_is_halted gauge
kalshi_risk_envelope_is_halted {1 if envelope.is_halted else 0}

# HELP kalshi_risk_envelope_peak_equity_usd Peak equity for drawdown calculation
# TYPE kalshi_risk_envelope_peak_equity_usd gauge
kalshi_risk_envelope_peak_equity_usd {envelope.peak_equity_usd:.2f}

# HELP kalshi_risk_envelope_current_equity_usd Current equity
# TYPE kalshi_risk_envelope_current_equity_usd gauge
kalshi_risk_envelope_current_equity_usd {envelope.current_equity_usd:.2f}
"""
        return PlainTextResponse(content=metrics_text)
    except Exception as e:
        logger.warning(f"[METRICS] Failed to generate envelope metrics: {e}")
        return PlainTextResponse(content="# No metrics available\n")
```

**Verification**: ✅ Correct
- Returns Prometheus-compatible metrics
- All envelope metrics exposed (band, distance_to_halt, per_trade_multiplier, is_halted, peak_equity, current_equity)
- Exception handling with warning (returns empty metrics on error)
- Safe for monitoring systems

---

## Log Verification Checklist

From startup logs, verify:

- [x] Balance fetch logs: `[BANKROLL] Bankroll service started`
- [x] Bankroll snapshot: Balance fetch in bankroll service
- [x] Envelope initialization: `[15m-LOOP] Initialized risk envelope for profile`
- [x] No exceptions during startup of Kalshi services
- [x] Drawdown halt check: `[15m-LOOP] Cycle X skipped: drawdown halt` (if halted)
- [x] Band transition logs: `[15m-LOOP] Risk band transition: X → Y (drawdown=Z%%)`

---

## Configuration Sources

### Risk Envelope Config
**File**: `config/profiles/kalshi_crypto_15m.yaml`
**Module**: `merid.risk.profiles.kalshi_crypto_15m_risk_envelope`

**Key Settings**:
- `capital_usd`: Starting capital
- `drawdown_halt_pct`: Drawdown threshold for halt
- `adaptive_risk_bands`: Risk band configuration
- `per_trade_risk_multiplier`: Risk multiplier per band

**Verification**: ⚠️ Need to confirm config file exists and is loaded correctly

---

## Issues Found

### Issue 1: Risk Envelope Config File
**Status**: ⚠️ Unverified
**Action**: Confirm `config/profiles/kalshi_crypto_15m.yaml` exists and is loaded by `get_kalshi_crypto_15m_risk_envelope()`

---

## Layer A Summary

**Status**: ✅ Mostly Correct, 1 Unverified

**Correct Components**:
- Environment contract (live vars + demo mode)
- Kalshi client initialization
- Bankroll service startup
- Fills poller startup
- Settlement poller with client dependency
- Risk envelope initialization and per-cycle updates
- Envelope metrics endpoint with error handling

**Unverified**:
- Risk envelope config file existence and loading

**Next Steps**:
1. Verify risk envelope config file exists
2. Proceed to Layer B: Market discovery, state, and WS bridge
