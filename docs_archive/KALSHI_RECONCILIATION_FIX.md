# Kalshi Reconciliation Fix - Portfolio Not Showing

**Date:** 2026-02-18 06:42 AM  
**Issue:** Reconciliation showing "0 portfolios" despite user having actual Kalshi account

---

## Root Cause Analysis

### Problem
```
2026-02-18 06:35:07 | INFO | trading.reconciliation | Reconciliation OK: 0 portfolios, 0 positions, hash=0190814585da
```

The reconciliation system was returning 0 portfolios because:

1. **KalshiVenueAdapter was hardcoded to "paper" mode**
   - `get_kalshi_venue_adapter(mode="paper")` always defaulted to paper
   - In paper mode, positions come from matching engine (which had 0 orders)
   - In live mode, positions come from Kalshi REST API

2. **Settings flag `MERID_PM_LIVE_ENABLED` was ignored**
   - User had `MERID_PM_LIVE_ENABLED=True` in `.env`
   - Adapter didn't check this setting
   - Always initialized in paper mode regardless of settings

---

## Fix Applied

### File: `merid/event_venues/kalshi/venue_adapter.py`

**Changed `get_kalshi_venue_adapter()` to respect settings:**

```python
def get_kalshi_venue_adapter(mode: Optional[str] = None) -> KalshiVenueAdapter:
    """Get or create the singleton KalshiVenueAdapter.
    
    Args:
        mode: "paper" or "live" (default: from settings)
        
    Returns:
        KalshiVenueAdapter instance
    """
    from merid.settings import settings
    
    global _adapter
    if _adapter is None:
        # Determine mode from settings if not explicitly provided
        if mode is None:
            # Use live mode if MERID_PM_LIVE_ENABLED is True
            if settings.MERID_PM_LIVE_ENABLED:
                mode = "live"
            else:
                mode = "paper"
        
        _adapter = KalshiVenueAdapter(mode=mode)
        logger.info(f"Created KalshiVenueAdapter singleton: mode={mode}")
    return _adapter
```

**Fixed KalshiConfig initialization:**

```python
# BEFORE (incorrect parameter names)
config = KalshiConfig(
    api_base=os.getenv("KALSHI_API_BASE", "..."),  # ❌ Wrong parameter
    email=os.getenv("KALSHI_EMAIL", ""),
    ...
)

# AFTER (use defaults, auto-loads from env)
config = KalshiConfig()  # ✅ Loads from env in __post_init__
```

---

## Verification

### Test Results (scripts/test_kalshi_positions.py)

**✅ Live Mode Confirmed:**
```
Settings:
  MERID_PM_LIVE_ENABLED: True
  MERID_PM_TRADING_MODE: live
  KALSHI_USE_DEMO: False
  KALSHI_EMAIL: surflkcrzy@gmail.com

KalshiVenueAdapter initialized: mode=live
Adapter mode: live
```

**✅ API Connection Working:**
```
[kalshi] Initializing new HTTP client
Loaded Kalshi RSA key (key_id: 32822964...)
✅ Successfully fetched 0 positions
```

**Result:** 0 positions returned from live API

---

## Why 0 Positions?

### Possible Reasons

1. **Account genuinely has no open positions** ✅ Most likely
   - User may have closed all positions
   - Or never opened any positions yet
   - API connection is working correctly

2. **Positions exist but not returned by API**
   - Could be a Kalshi API issue
   - Check Kalshi web UI to verify actual positions

3. **Authentication issue**
   - But RSA key loaded successfully, so auth is working

---

## How Reconciliation Works

### Paper Mode (OLD behavior)
```python
async def _get_paper_positions(self) -> List[VenuePosition]:
    engine = self._get_matching_engine()
    # Returns positions from local matching engine
    # Only shows simulated trades, not real Kalshi account
```

### Live Mode (NEW behavior)
```python
async def _get_live_positions(self) -> List[VenuePosition]:
    await self.client.connect()
    positions = await self.client.get_positions()  # ← Real Kalshi API
    await self.client.close()
    return positions
```

---

## Next Steps

### 1. Verify Actual Kalshi Positions

**Check Kalshi web UI:**
- Login to https://kalshi.com (or demo-api.kalshi.co if using demo)
- Go to Portfolio → Positions
- Confirm if you actually have open positions

**If positions exist on Kalshi web but not returned by API:**
- Check Kalshi API documentation for `/portfolio/positions` endpoint
- Verify API key has correct permissions
- Check if positions are in a different status (e.g., "settled")

### 2. Place a Test Order

**To verify live integration works:**
```python
# Use the test script or agent grid to place a small order
# Then check reconciliation again to see if position appears
```

### 3. Restart Backend Server

**The singleton adapter may still be using old paper mode:**
```bash
# Stop current server
# Restart to pick up the fix
py -m uvicorn web.main:create_app --factory --host 0.0.0.0 --port 8000 --reload
```

### 4. Re-run Reconciliation

```bash
py scripts/run_reconciliation.py
```

**Expected if account is empty:**
```
Reconciling: 0 internal pos, 0 venue pos, 0 internal orders, 0 venue orders
Reconciliation complete: All positions and orders reconciled successfully
```

**Expected if positions exist:**
```
Reconciling: 0 internal pos, N venue pos, 0 internal orders, 0 venue orders
WARNING: Found N CRITICAL issues (phantom positions)
```

---

## Settings Configuration

### Required Environment Variables

```bash
# .env file
MERID_PM_LIVE_ENABLED=true          # ← Enable live mode
MERID_PM_TRADING_MODE=live
KALSHI_USE_DEMO=false               # Set to true for demo API
KALSHI_EMAIL=your_email@example.com
KALSHI_PASSWORD=your_password
KALSHI_PRIVATE_KEY_PATH=path/to/kalshi_private_key.pem
```

---

## Summary

✅ **Fixed:** Venue adapter now respects `MERID_PM_LIVE_ENABLED` setting  
✅ **Fixed:** KalshiConfig initialization corrected  
✅ **Verified:** Live API connection working (RSA auth successful)  
✅ **Result:** 0 positions returned from live Kalshi API

**If your Kalshi account truly has positions:**
1. Restart the backend server to clear the singleton cache
2. Verify positions exist on Kalshi web UI
3. Re-run reconciliation
4. Check for "phantom position" warnings

**If your account is empty (0 positions):**
- This is correct behavior
- Place a test order to verify full integration
- Reconciliation will show positions once orders are filled

---

**Status:** ✅ Core issue resolved - adapter now uses live mode and connects to real Kalshi API
