# CRYPTO SURFACE INTEGRATION CHECKLIST

**Status:** Ready to Integrate  
**Date:** 2026-03-21  
**Effort:** ~2-4 hours for basic integration, ~1 week for full agent migration

---

## Phase 1: Setup (30-60 min)

### [ ] 1.1 Verify Configuration
```bash
cd c:\Dev\MERID
.venv\Scripts\python config/crypto_spot_kalshi_config.py
```
**Expected output:** ✓ All configs consistent, 14 combos configured

### [ ] 1.2 Review Template Files
- [ ] Read: `CRYPTO_SURFACE_QUICK_REFERENCE.md` (5 min)
- [ ] Read: `BACKEND_INTEGRATION_TEMPLATE.py` (10 min — understand structure)
- [ ] Read: `AGENT_MIGRATION_EXAMPLE.py` (10 min — understand before/after)

### [ ] 1.3 Check Existing Infrastructure
- [ ] You have Binance API client (ccxt, binance-connector, etc.)
- [ ] You have Kalshi API client (Kalshi SDK or similar)
- [ ] You have main async backend service/loop

---

## Phase 2: Implement Adapters (1-2 hours)

### [ ] 2.1 Binance Spot Feed Adapter
**File:** `BinanceSpotFeedAdapter` in `BACKEND_INTEGRATION_TEMPLATE.py`

**What to do:**
```python
# In BinanceSpotFeedAdapter._fetch_from_binance_api():
# - Replace the pseudo-code with your actual Binance client calls
# - Return format: {symbol: {"price": float, "ts": datetime}, ...}
# - Handle errors gracefully; don't fail entire fetch if one symbol fails

# Test it:
adapter = BinanceSpotFeedAdapter(your_binance_client)
spots = asyncio.run(adapter.fetch_spot_prices())
assert "BTC" in spots and spots["BTC"]["price"] > 0
```

**Checklist:**
- [ ] Supports all 5 cryptos: BTC, ETH, SOL, XRP, DOGE
- [ ] Returns current prices (not stale)
- [ ] Handles network errors gracefully
- [ ] Logs prices for debugging

### [ ] 2.2 Kalshi Market Fetcher Adapter
**File:** `KalshiMarketFetcherAdapter` in `BACKEND_INTEGRATION_TEMPLATE.py`

**What to do:**
```python
# In KalshiMarketFetcherAdapter._fetch_from_kalshi_api():
# - Replace pseudo-code with your actual Kalshi API client calls
# - Filter for: category=crypto, status=open, frequencies=[15_min, hourly, daily]
# - Return format: {series_ticker: [market_obj, ...], ...}

# Also update these extraction methods to match your market object structure:
# - _extract_series_ticker()
# - _extract_status()
# - _extract_expiry()

# Test it:
fetcher = KalshiMarketFetcherAdapter(your_kalshi_client)
markets = asyncio.run(fetcher.fetch_markets())
assert len(markets) > 0
assert any("KXBTC" in k for k in markets.keys())
```

**Checklist:**
- [ ] Fetches markets for all configured series
- [ ] Only returns "open" markets
- [ ] Handles market object structure correctly
- [ ] Caches results (30s TTL by default)

### [ ] 2.3 Test Adapters in Isolation
```python
# Test both adapters before wiring to service

# Spot feed test
spots = await adapter.fetch_spot_prices()
print(f"✓ Fetched {len(spots)} spot prices")
for symbol, data in spots.items():
    print(f"  {symbol}: {data['price']}")

# Market fetcher test
markets = await fetcher.fetch_markets()
print(f"✓ Fetched {sum(len(m) for m in markets.values())} markets")
for series, market_list in markets.items():
    print(f"  {series}: {len(market_list)} markets")
```

---

## Phase 3: Create Service (30-45 min)

### [ ] 3.1 Copy Integration Template
```bash
# Copy the template to your backend code location
cp BACKEND_INTEGRATION_TEMPLATE.py services/crypto_surface_backend.py

# OR manually create services/crypto_surface_backend.py with:
# - BinanceSpotFeedAdapter (from template)
# - KalshiMarketFetcherAdapter (from template)
# - CryptoSurfaceService (from template, or adapt)
# - MeridBackendService (example, adapt to your code)
```

### [ ] 3.2 Integrate into Main Server
**Pattern:**

```python
# In your backend's main service/app initialization:

class MyBackendService:
    def __init__(self, binance_client, kalshi_client):
        # Create crypto surface service
        self.crypto_surface = CryptoSurfaceService(
            binance_client=binance_client,
            kalshi_client=kalshi_client,
        )
    
    async def start(self):
        # Start in background
        await self.crypto_surface.start()
    
    async def stop(self):
        # Clean shutdown
        await self.crypto_surface.stop()
```

### [ ] 3.3 Test Service Startup
```python
service = CryptoSurfaceService(your_binance, your_kalshi)
await service.start()

# Wait for first update
await asyncio.sleep(12)

# Check surface
surface = service.get_surface()
assert surface is not None
assert len(surface) > 0

print("✓ Surface initialized successfully")

await service.stop()
```

---

## Phase 4: Wire Agents (1-2 hours per agent)

### [ ] 4.1 Choose Migration Strategy

**Option A: Immediate Compatibility (Safer)**
- Use `AgentCompatibilityAdapter` to wrap existing agents
- No changes needed to agent code
- Agents automatically use surface
- Gradual migration over time

**Option B: Direct Migration (Cleaner)**
- Refactor agent to new pattern (like `NewBtc15mMMAgent`)
- Agents subscribe to surface updates
- Better logging, cleaner code
- Worth it for important agents

### [ ] 4.2 Update Each Agent

**If using Option A (Compat):**
```python
# In backend service init:
self.agents = {
    "btc_15m_mm": OldBtc15mMMAgent(...),
    "eth_15m_mm": OldEth15mMMAgent(...),
}

# Wrap each agent:
self.agent_adapters = {
    name: AgentCompatibilityAdapter(agent, self.crypto_surface)
    for name, agent in self.agents.items()
}

# Subscribe:
for name, adapter in self.agent_adapters.items():
    self.crypto_surface.subscribe(name, adapter.on_surface_updated)
```

**If using Option B (Direct):**
```python
# Create new agent:
agent = NewBtc15mMMAgent(self.crypto_surface)

# Subscribe:
self.crypto_surface.subscribe("btc_15m_mm", agent.on_surface_updated)

# Done! Agent will receive updates automatically
```

### [ ] 4.3 Verify Agent Receives Updates
```python
# Monitor logs for patterns like:
# "BTC_15M_MM: Surface updated; recalculating BTC-15M"
# "Scanning 5 BTC-15M Kalshi markets within ±2.0% of spot..."

# If logs appear: ✓ Agent is connected and receiving updates
```

---

## Phase 5: Validate (30-60 min)

### [ ] 5.1 Check Logs for Alignment
**Look for:**
```
✓ Spot price (BTC: 70743.69) matches timeframe in logs
✓ Series ticker (KXBTC15M) matches spot/timeframe
✓ Distance % makes sense for configured band
✓ Market count is reasonable (not 0, not 1000)
```

### [ ] 5.2 Verify Core Statistics
```python
# Run these checks:

# 1. Surface updates every ~10 seconds
surface1 = service.get_surface()
await asyncio.sleep(15)
surface2 = service.get_surface()
assert surface2.timestamp > surface1.timestamp

# 2. Each entry has markets
surface = service.get_surface()
for entry in surface.entries:
    assert len(entry.kalshi_markets) > 0, f"{entry.symbol} has no markets"

# 3. Near-spot selection works
for symbol in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
    for tf in ["15M", "1H", "1D"]:
        entry = service.get_entry(symbol, tf)
        if entry:
            markets = select_markets_near_spot(entry)
            print(f"{symbol}-{tf}: {len(entry.kalshi_markets)} total, "
                  f"{len(markets)} near-spot")
```

### [ ] 5.3 Dashboard Integration (Optional)
```python
@app.get("/api/crypto-surface")
async def get_surface_dashboard():
    surface = crypto_surface_service.get_surface()
    return {
        "timestamp": surface.timestamp.isoformat(),
        "entries": [
            {
                "symbol": e.symbol,
                "timeframe": e.timeframe,
                "spot_price": e.spot_price,
                "spot_source": e.spot_source,
                "open_markets": len(e.open_markets()),
                "series": e.kalshi_series,
            }
            for e in surface.entries
        ],
    }
```

### [ ] 5.4 Run in Production (24 hours)
- [ ] Observe logs for 1 hour (should see regular updates)
- [ ] Check agent order submissions have full context
- [ ] Verify surface age stays <15s (default update_interval_s=10)
- [ ] No errors in logs related to surface

---

## Phase 6: Optimization (Optional, Week 2+)

### [ ] 6.1 Tune Near-Spot Bands
Based on live market behavior:
```python
# If MM agents report "no markets found":
# → Widen band in NEAR_SPOT_CONFIG
# Example: ("BTC", "15M"): {"pct_band": 2.5}, ...

# If agents are quoting too many markets:
# → Tighten band
# Example: ("BTC", "15M"): {"pct_band": 1.5}, ...
```

### [ ] 6.2 Add Monitoring
```python
# Prometheus metrics or similar:
- surface_update_latency_seconds
- surface_age_seconds
- markets_selected_per_combo
- agents_subscribed_total
```

### [ ] 6.3 Document Configuration
```markdown
# Crypto Surface Configuration

## Spot Sources
- BTC, ETH, SOL, XRP, DOGE: binance

## Near-Spot Bands (as deployed)
- BTC 15M:  ±2.0% (updated 2026-03-21)
- BTC 1H:   ±1.5%
- ETH 15M:  ±2.5%
- ...
```

---

## Troubleshooting

| Issue | Diagnosis | Fix |
|-------|-----------|-----|
| `Surface is None` | Loader hasn't updated yet | Wait 12+ seconds after service start |
| `No near-spot markets` | Band too tight OR Kalshi markets are far from spot | Check logs; widen band if needed |
| `Agent not receiving updates` | Not subscribed OR subscription failed | Check: `crypto_surface.subscribe()` call; look for logs about subscribers |
| `Surface age is 60+ seconds` | Update loop is slow or failed | Check logs; may need to increase `update_interval_s`; check adapter performance |
| `ModuleNotFoundError` | Python path issue | Run from project root; add `sys.path.insert(0, '.')` |

---

## Rollback Plan

If issues arise:

1. **Stop service:** `await crypto_surface_service.stop()`
2. **Revert agent code:** Use git to revert to previous version
3. **Use compatibility adapter:** Temporarily wrap agents while debugging
4. **Restore old hardcoded config:** Agents can use old config as fallback

---

## Success Criteria

✓ Phase complete when:
- [ ] Service starts without errors
- [ ] Surface updates every ~10 seconds
- [ ] Agents receive `on_surface_updated()` callbacks
- [ ] Logs show alignment: (symbol, timeframe, series, band match)
- [ ] Agents submit orders with full context
- [ ] No errors in 24-hour test run

---

## Rollout Timeline

- **Day 1:** Phases 1-3 (setup + service)
- **Days 2-3:** Phase 4 (agent migration)
- **Days 4-5:** Phase 5 (validation)
- **Week 2+:** Phase 6 (optimization)

---

## Support Resources

- **Quick start:** `CRYPTO_SURFACE_QUICK_REFERENCE.md`
- **Full reference:** `KALSHI_CRYPTO_SURFACE_README.md`
- **Architecture:** `CRYPTO_SURFACE_ARCHITECTURE.txt`
- **Template code:** `BACKEND_INTEGRATION_TEMPLATE.py`
- **Agent examples:** `AGENT_MIGRATION_EXAMPLE.py`

---

**Go live checklist:**
- [ ] Adapters tested
- [ ] Service tested
- [ ] At least 1 agent migrated
- [ ] Logs verified for alignment
- [ ] 24-hour test passed
- [ ] Team briefed on new config

**Status:** Ready to proceed ✓
