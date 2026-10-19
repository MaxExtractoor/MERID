# Kalshi Legacy Modules Reference

## Archived Files
The following modules have been archived under `merid.event_venues.kalshi.legacy` and are **not** the authoritative implementation path:

- `legacy/client_enhanced.py`
- `legacy/order_group_manager_enhanced.py`
- `legacy/order_manager_enhanced.py`
- `legacy/trading_enhanced.py`
- `legacy/venue_adapter_enhanced.py`
- `legacy/kalshi_robustness.py`

These files remain available for forensic purposes only and carry a LEGACY NOTICE at the top of each module.

## Canonical Implementation Surface
Use the non-suffixed modules below for all new functionality:

- `merid.event_venues.kalshi.client`
- `merid.event_venues.kalshi.order_group_manager`
- `merid.event_venues.kalshi.order_manager`
- `merid.event_venues.kalshi.trading`
- `merid.event_venues.kalshi.venue_adapter`

## Governance Rules
- **Do not import** from any module under `merid.event_venues.kalshi.legacy` when building new functionality. If you need reference behavior, copy the relevant snippet into a canonical module and document the change.
- **Run the Kalshi test gate** (`make kalshi-test-slice`) for every Kalshi-focused change. For exploratory work or nightlies, use `make kalshi-e2e` to validate against the full E2E/stress bucket.
- **Avoid introducing raw error strings**; new failures should map to `KalshiOrderErrorCode` so taxonomy-driven metrics and alerts remain accurate.
- When key behavior changes are introduced, include a short note describing the impact on risk, operations, or SLOs in the PR description.
