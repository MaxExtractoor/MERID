# MERID Frontend - Known Test Debt

## Current Status (January 30, 2026)

- **TypeScript**: 0 errors ✅
- **Architecture**: Documented in `ARCHITECTURE.md` ✅
- **Tests**: 139 passing, 0 failing ✅
- **CI**: Workflow configured with type-check + test as hard gates

## No Outstanding Test Debt

All test suites are currently passing:

- ✅ `formatters.test.tsx` (50 tests)
- ✅ `validators.test.tsx` (33 tests)
- ✅ `DataTableEnhanced.test.tsx` (6 tests)
- ✅ `MetricCard.test.tsx` (5 tests)
- ✅ `PriceTicker.test.tsx` (6 tests)
- ✅ `StatusIndicator.test.tsx` (8 tests)
- ✅ `useApiData.test.tsx` (7 tests)
- ✅ `useLocalStorage.test.tsx` (15 tests)
- ✅ `useWebSocket.test.tsx` (7 tests)

## Historical Context

Previously tracked async/act() testing issues have been resolved through:

1. **formatters.ts**: Fixed `formatDuration` (seconds vs ms), `formatFileSize` (bytes without decimal), `formatDelta` (sign handling, zero baseline), `formatDate` (YYYY-MM-DD), `formatTime` (UTC), `formatNumber` (natural decimals)
2. **validators.ts**: Fixed `validatePassword` to skip complexity checks when custom options provided
3. **StatusIndicator.tsx**: Fixed default `showText=true`, added `data-testid`

## Future Test Debt Tracking

If test debt is introduced intentionally (e.g., async testing patterns that need refinement):

1. Document the failing test(s) in this file
2. Explain why it's debt (not a bug) and the planned fix approach
3. Update CI to use `continue-on-error: true` for the test step temporarily
4. Fix and remove from this file before merging to main

## CI Configuration

Current CI requires both:
- `npm run type-check` ✅ (hard gate)
- `npm test` ✅ (hard gate)

Both must pass for PR merge.

---

*Last updated: January 30, 2026 - All tests passing*
