# T-061: Legacy Frontend Cleanup — What Was Removed & Why

**Date:** 2026-02-23  
**Audit Task:** T-061 (Zero-Trust Audit Stage 3)  
**Author:** Cascade (automated audit)

---

## Summary

Removed **211 files (~1.6 MB)** across 12 `_legacy/` directories in `web/react/src/`.
These files were **not imported by any active component** — confirmed via static analysis.
All content is preserved in **git history** and can be recovered with:

```bash
git log --all --full-history -- "web/react/src/components/_legacy/"
git checkout <commit-hash> -- "web/react/src/components/_legacy/SomeFile.tsx"
```

---

## Directories Removed

| Directory | Files | Notes |
|-----------|-------|-------|
| `components/_legacy/` | 78 | Old dashboard panels, cards, tables |
| `components/_legacy_charts/` | 27 | Recharts/D3 chart components |
| `components/__tests__/_legacy/` | 6 | Tests for removed components |
| `config/_legacy/` | 1 | `uiViewsManifest.ts` — old view registry |
| `hooks/_legacy/` | 35 | Data-fetching hooks for removed views |
| `hooks/__tests__/_legacy/` | 5 | Tests for removed hooks |
| `services/_legacy/` | 1 | `websocket.ts` — replaced by `useWebSocket` |
| `services/__tests__/_legacy/` | 1 | `api.test.ts` — old API service tests |
| `types/_legacy/` | 4 | TypeScript interfaces for removed features |
| `utils/_legacy/` | 3 | `statusMappers`, `stub`, `websocketWithBackoff` |
| `views/_legacy/` | 36 | Full page views (Trading, Predictions, etc.) |
| `views/__tests__/_legacy/` | 14 | Tests for removed views |

---

## Why Removed

1. **Dead code** — No active `import` references from any non-legacy file.
2. **Stale dependencies** — Many reference removed hooks, contexts, or APIs.
3. **Security surface** — Dead code increases audit surface without value.
4. **Build bloat** — 1.6 MB of unused TypeScript slows IDE indexing and linting.
5. **Confusion risk** — New contributors may accidentally import legacy code.

---

## What Was Kept (and Why)

The following directories/files are **NOT legacy** and remain active:

| Path | Reason Kept |
|------|-------------|
| `components/ErrorBoundary.tsx` | Active — wraps all views (T-033) |
| `components/KalshiTradeTicket.tsx` | Active — primary trade UI |
| `components/ModeControlPanel.tsx` | Active — mode switching UI |
| `components/ErrorBar.tsx` | Active — error display component |
| `hooks/useApiData.ts` | Active — primary data fetching hook |
| `hooks/useWebSocket.ts` | Active — WebSocket connection hook |
| `hooks/useMeridSocket.ts` | Active — event bus hook |
| `views/KillSwitchView.tsx` | Active — kill switch dashboard |
| `views/KalshiDashboard.tsx` | Active — Kalshi trading dashboard |
| `config/constants.ts` | Active — API endpoints, URLs |

---

## Components Worth Revisiting for Multi-Venue Scaling

If scaling to more venues/asset types, these removed components have reusable patterns:

| Legacy File | Reusable Pattern | Recovery Command |
|-------------|-----------------|------------------|
| `components/_legacy/VenueSelector.tsx` | Multi-venue dropdown with domain grouping | `git log --all -- "web/react/src/components/_legacy/VenueSelector.tsx"` |
| `components/_legacy/DomainControlPanel.tsx` | Per-domain (crypto/equity/prediction) mode control | Same pattern |
| `components/_legacy/ArbitragePanel.tsx` | Cross-venue arbitrage opportunity display | Same pattern |
| `components/_legacy/CrossAssetView.tsx` | Multi-asset correlation and exposure view | Same pattern |
| `components/_legacy_charts/InstrumentRadar.tsx` | Radar chart for multi-instrument comparison | Same pattern |
| `components/_legacy_charts/RiskTreeMap.tsx` | Treemap for hierarchical risk exposure | Same pattern |
| `hooks/_legacy/useFlowRadar.ts` | Real-time flow aggregation across venues | Same pattern |
| `hooks/_legacy/useMarketsData.ts` | Multi-market data normalization hook | Same pattern |
| `views/_legacy/CrossAssetView.tsx` | Full cross-asset dashboard page | Same pattern |
| `views/_legacy/Institutional.tsx` | Institutional-grade portfolio view | Same pattern |
| `views/_legacy/TradeFloor.tsx` | "Wall of agents trading" live view | Same pattern |
| `types/_legacy/orders.ts` | Venue-agnostic order type definitions | Same pattern |

### How to Recover

```bash
# Find the last commit that touched a legacy file
git log --all --oneline -- "web/react/src/components/_legacy/VenueSelector.tsx"

# Restore it
git checkout <hash> -- "web/react/src/components/_legacy/VenueSelector.tsx"

# Or restore the entire directory
git checkout <hash> -- "web/react/src/components/_legacy/"
```

---

## Verification

After deletion, run:
```bash
cd web/react && npm run build
```
If the build succeeds, no active code depended on the removed files.
