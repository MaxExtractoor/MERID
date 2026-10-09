# Stale market_filter.py Fix Guide

## Problem
The CT logs show `Post-enrichment filters: ... 41 (price_band), kept 0` but this code does NOT exist in the repo's `merid/event_venues/kalshi/market_filter.py`. This means Python is importing a stale installed version from site-packages rather than the current repo version.

## Diagnostic

Run this from the MERID repo root:

```bash
python diagnose_stale_module.py
```

This will show:
1. Which Python executable is being used
2. Where the market_filter module is being loaded from
3. Whether the stale post-enrichment price_band code is present

## Quick Fix (Hot Patch)

If you need to unblock evaluation immediately without reinstalling:

1. Find the stale file path from the diagnostic output (e.g., `.../site-packages/merid/event_venues/kalshi/market_filter.py`)

2. Edit that file and comment out the post-enrichment price_band block:

```python
# Around line 1315-1320, find this block:
if dropped_distance or dropped_edge or dropped_price or dropped_price_band:
    logger.info(
        "Post-enrichment filters: dropped %d (distance), %d (edge), %d (max_price), "
        "%d (price_band), kept %d",
        dropped_distance, dropped_edge, dropped_price, dropped_price_band, len(filtered),
    )

# Replace with:
if dropped_distance or dropped_edge or dropped_price or dropped_price_band:
    logger.info(
        "[STALE-FIX] Bypassed post-enrichment filters: would have dropped %d (distance), %d (edge), %d (max_price), %d (price_band), kept %d",
        dropped_distance, dropped_edge, dropped_price, dropped_price_band, len(filtered),
    )
    # HOT PATCH: Keep all enriched candidates
    filtered = enriched  # Bypass the filters
```

3. Restart CT and verify the logs now show `kept > 0`

## Permanent Fix (Recommended)

The proper fix is to reinstall the merid package in editable mode so changes in the repo are immediately reflected:

```bash
# 1. Uninstall the stale package
python -m pip uninstall merid -y

# 2. From the MERID repo root, reinstall in editable mode
cd /path/to/MERID
python -m pip install -e .

# 3. Verify the import path
python -c "import merid.event_venues.kalshi.market_filter as mf; print(mf.__file__)"
# Should show: .../MERID/merid/event_venues/kalshi/market_filter.py
# NOT: .../site-packages/merid/...

# 4. Restart CT
```

## Verification

After the fix, CT logs should show:
- `Enriched 41 candidates with spot/strike/edge`
- `Post-enrichment filters: dropped 0 (distance), 0 (edge), 0 (max_price), 0 (price_band), kept 41` (or similar with kept > 0)
- `[UA-TRACE] ... universe_markets>0 evaluated>0 ... orders_submitted>=0`

## Prevention

To avoid this in the future:

1. Always use `pip install -e .` for development (editable mode)
2. Check `python -c "import merid; print(merid.__file__)"` matches your repo path
3. Be careful with PYTHONPATH - ensure repo root comes before site-packages
4. If using Docker, ensure the container mounts the repo as a volume, not copies it
