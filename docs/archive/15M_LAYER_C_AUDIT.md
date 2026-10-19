# Layer C Audit: Spot Price Feed and BinanceUS Fallback

**Scope**: Live price feed, CCXT fallback, BinanceUS oracle, symbol mapping

---

## Live Price Feed Configuration

**Module**: `data.live_price_feed`
**Factory**: `get_live_price_feed()`
**Startup**: web.main_15m.py lines 511-569

### 15m Profile Configuration

**Location**: web.main_15m.py lines 526-530
```python
# Explicitly disable Coinbase streaming for 15m stack - rely on CCXT fallback
# This avoids 401 auth errors and reduces dependency complexity
if hasattr(feed, 'disable_coinbase'):
    feed.disable_coinbase()
    logger.info("[LIVE-PRICE-FEED] Coinbase streaming disabled - using CCXT fallback for 15m stack")
```

**Verification**: ✅ Correct
- Coinbase streaming explicitly disabled for 15m stack
- Relies on CCXT fallback to avoid 401 auth errors
- Reduces dependency complexity

### Fallback Chain

**Location**: live_price_feed.py lines 628-774
```python
async def _fetch_price_with_retry(self, symbol: str):
    """
    Fetch price with retry logic and fallback chain.

    Fetch sequence (in order of preference):
    1. Coinbase Public API (PRIMARY) - no auth required, fast, reliable
    2. Kraken Public API (FALLBACK #1) - no auth required, good depth
    3. CCXT exchanges (FALLBACK #2) - authenticated exchanges via CCXT
    4. BinanceUS (LAST RESORT) - public API, batch fetch
    """
```

**Verification**: ✅ Correct
- Coinbase Public API is primary (but disabled in 15m stack)
- Kraken Public API is fallback #1
- CCXT exchanges are fallback #2
- BinanceUS is last resort fallback only

### CCXT Fallback Configuration

**Location**: web.main_15m.py lines 532-542
```python
# Start price feed in background to avoid blocking startup
async def _run_feed_with_error_handler():
    try:
        await feed.start_streaming()
    except Exception as exc:
        logger.error("[LIVE-PRICE-FEED] Background feed task failed: %s", exc)
        raise

feed_task = asyncio.create_task(_run_feed_with_error_handler(), name="ccxt_stream_loop")
```

**Verification**: ✅ Correct
- CCXT fallback runs in background task
- Error handling with logging
- Task added to background_tasks for shutdown

---

## Symbol Mapping

### Internal Symbols
**Location**: live_price_feed.py lines 68-74
```python
COINBASE_PAIRS = [
    "BTC-USD",   # Primary reference for Kalshi BRTI
    "ETH-USD",
    "SOL-USD",
    "XRP-USD",
    "DOGE-USD",
]
```

**Verification**: ✅ Correct
- Internal format uses USD (not USDT)
- Matches Kalshi BRTI index constituents
- All 5 15m crypto assets included

### BinanceUS Symbol Mapping
**Location**: live_price_feed.py (need to verify)
**Expected Mapping**:
- Internal: BTC/USD → BinanceUS: BTCUSDT
- Internal: ETH/USD → BinanceUS: ETHUSDT
- Internal: SOL/USD → BinanceUS: SOLUSDT
- Internal: XRP/USD → BinanceUS: XRPUSDT
- Internal: DOGE/USD → BinanceUS: DOGEUSDT

**Verification**: ⚠️ Need to verify implementation

---

## BinanceUS Fallback

### BinanceUS Rate Limiting
**Location**: live_price_feed.py lines 103-104, 348-351
```python
_BINANCEUS_COOLDOWN_SECONDS = float(os.getenv("MERID_BINANCEUS_COOLDOWN_SECONDS", "30.0"))
_BINANCEUS_MIN_INTERVAL_SECONDS = float(os.getenv("MERID_BINANCEUS_MIN_INTERVAL_SECONDS", "1.0"))

# BinanceUS rate limiting (fallback only)
self._binanceus_semaphore = asyncio.Semaphore(1)
self._binanceus_last_request: float = 0.0
self._binanceus_cooldown_until: Optional[float] = None
```

**Verification**: ✅ Correct
- BinanceUS rate limiting implemented
- Configurable via environment variables
- Semaphore ensures single concurrent request

### BinanceUS Price Delta Logging
**Location**: live_price_feed.py lines 1599-1612
```python
async def _log_price_delta(self, pair: str, new_price: float):
    """Log price delta vs previous BinanceUS price."""
    legacy_symbol = pair.upper().replace('/', '')
    if legacy_symbol in self._previous_binanceus_prices:
        prev_price = self._previous_binanceus_prices[legacy_symbol]
        delta_pct = ((new_price - prev_price) / prev_price) * 100 if prev_price > 0 else 0
        logger.info(
            f"Price delta for {pair}: {delta_pct:+.2f}% "
            f"(BinanceUS: ${prev_price:.2f}, Coinbase: ${new_price:.2f})"
        )

def record_binanceus_price(self, symbol: str, price: float):
    """Record BinanceUS price for delta comparison during source transition."""
    self._previous_binanceus_prices[symbol] = price
```

**Verification**: ✅ Correct
- Price delta logging vs previous BinanceUS price
- Used for source transition monitoring
- Helps detect pricing anomalies

---

## RTI Construction and Settlement Logic

### RTI Feed Service
**Location**: web.main_15m.py lines 572-602
```python
async def _start_rti_feed_service() -> None:
    """Start RTI feed service for real-time signals."""
    import os
    profile = os.getenv("MERID_PROFILE", "").lower()
    if profile == "kalshi_crypto_15m_v2":
        logger.info("[RTI-FEED] RTI feed service skipped for kalshi_crypto_15m_v2 (lean 15m stack)")
        _startup_state["services"]["rti_feed"] = {
            "status": "skipped",
            "reason": "profile_guard",
        }
        return
```

**Verification**: ✅ Correct
- RTI feed service skipped for kalshi_crypto_15m_v2
- BinanceUS cannot be used in RTI construction if RTI is disabled
- Profile guard prevents RTI startup

### Kalshi Settlement Logic
**Verification**: ⚠️ Need to verify
- Confirm BinanceUS is excluded from Kalshi settlement logic
- Check if settlement_poller or venue_adapter uses BinanceUS
- Verify RTI is not constructed from BinanceUS prices

---

## CoinGecko Usage

**Verification**: ⚠️ Need to verify
- Ensure no CoinGecko in any 15m trading-critical path
- Check if live_price_feed or spot_models uses CoinGecko
- Verify no CoinGecko imports in 15m startup chain

---

## Staleness Configuration

### Kalshi 15m Staleness
**Location**: live_price_feed.py lines 106-113
```python
# FIX: Kalshi 15m crypto contract assets
KALSHI_15M_ASSETS = {'BTC', 'ETH', 'SOL', 'XRP', 'DOGE'}

# FIX: Stricter staleness for Kalshi 15m settlement windows
# 15min = 900s, need sub-second precision near settlement
KALSHI_15M_STALE_MS = int(os.getenv('MERID_KALSHI_15M_STALE_MS', '2000'))  # 2s max stale
KALSHI_15M_MISSING_MS = int(os.getenv('MERID_KALSHI_15M_MISSING_MS', '10000'))  # 10s max missing
```

**Verification**: ✅ Correct
- Stricter staleness thresholds for Kalshi 15m assets
- 2s max stale, 10s max missing
- Configurable via environment variables

---

## Log Verification Checklist

From startup logs, verify:

- [x] Coinbase streaming disabled: `[LIVE-PRICE-FEED] Coinbase streaming disabled - using CCXT fallback for 15m stack`
- [x] CCXT stream loop started: `[CCXT-STREAM] Loop entered, starting while True`
- [x] CCXT fetch cycles: `[CCXT-STREAM] Coinbase Public API succeeded for BTC/USD: $PRICE`
- [x] BinanceUS fallback (if needed): `[BINANCEUS-FALLBACK] Degraded pricing mode - falling back from CCXT to BinanceUS`
- [ ] RTI feed skipped: `[RTI-FEED] RTI feed service skipped for kalshi_crypto_15m_v2`
- [ ] BinanceUS excluded from settlement: Need to verify

---

## Issues Found

### Issue 1: BinanceUS Symbol Mapping Unverified
**Status**: ⚠️ MEDIUM
**Impact**: Unknown if symbol mapping is correct (BTC/USD → BTCUSDT)
**Action**: Verify _fetch_from_binanceus() implementation

### Issue 2: BinanceUS Exclusion from Settlement Unverified
**Status**: ⚠️ HIGH
**Impact**: Unknown if BinanceUS is used in Kalshi settlement logic
**Action**: Verify settlement_poller and venue_adapter do not use BinanceUS

### Issue 3: CoinGecko Usage Unverified
**Status**: ⚠️ MEDIUM
**Impact**: Unknown if CoinGecko is used in 15m trading-critical path
**Action**: Verify no CoinGecko imports in 15m startup chain

---

## Layer C Summary

**Status**: ⚠️ 3 Unverified

**Correct Components**:
- Coinbase streaming disabled for 15m stack
- CCXT fallback configured and running
- Fallback chain: Coinbase (primary, disabled) → Kraken → CCXT → BinanceUS (last resort)
- BinanceUS rate limiting implemented
- BinanceUS price delta logging
- RTI feed service skipped for 15m profile
- Stricter staleness thresholds for Kalshi 15m assets

**Unverified**:
1. BinanceUS symbol mapping implementation (medium)
2. BinanceUS exclusion from settlement logic (high)
3. CoinGecko usage in 15m trading path (medium)

**Next Steps**:
1. Verify BinanceUS symbol mapping implementation
2. Verify BinanceUS is excluded from settlement logic
3. Verify no CoinGecko in 15m trading-critical path
4. Proceed to Layer D: Agent grid, policies, and loop
