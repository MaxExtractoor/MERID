# UI Audit - WHITELIST Endpoint Decisions

## Overview
This document tracks decisions for frontend API endpoints that are in the WHITELIST (no backend implementation) or defined but unused.

**Decision Date:** 2026-05-11
**Context:** UI/Frontend Codebase Audit - 10-Pass Deep Analysis

---

## WHITELIST Endpoints (No Backend, Used in UI)

### 1. KALSHI_PUBLISH_PIPELINE, KALSHI_PUBLISH_PIPELINE_TRIGGER

**Used in:** `PublishPipelinePanel.tsx` (338 lines)

**User Flow:**
- Operator views pipeline status (running state, tracked tickers, emission counts)
- Displays recent published insights (ticker, category, action, Telegram status, tweet ID)
- Shows Twitter + Telegram channel status
- Manual trigger for operator testing (input ticker + category)

**Required Request/Response Shape:**
- GET `/api/v1/kalshi/publish-pipeline`
  - Response: `{ pipeline: { running, consumers, tracked_tickers, total_emitted, by_category, by_action, errors, started_at }, news_agent: {...}, twitter: {...}, telegram: {...} }`
- POST `/api/v1/kalshi/publish-pipeline/trigger?ticker={ticker}&category={category}`
  - Response: `{ success: boolean, message: string }`

**Error Modes:**
- 501 Not Implemented (recommended for now)
- 500 Internal Server Error (if implemented but fails)

**Roadmap Relevance:**
- This appears to be a real operator-facing feature for publishing consensus insights to social channels
- Likely needed for near-term roadmap if social publishing is active

**Decision:** **STUB (501)**
- Add backend stub returning 501 with descriptive message: "Publish pipeline not yet implemented"
- Keep PublishPipelinePanel.tsx but add error handling to show "Coming Soon / Disabled" state
- Consider hiding behind feature flag `publish_pipeline_enabled` to avoid confusion

---

### 2. KALSHI_FAVORITES, KALSHI_FAVORITES_TOGGLE

**Used in:** `DiscoverView.tsx` (favorites quick filter, toggle functionality)

**User Flow:**
- User can toggle favorite status on markets
- Quick filter "favorites" shows only favorited markets
- Favorites persisted across sessions

**Required Request/Response Shape:**
- GET `/api/v1/kalshi/favorites`
  - Response: `{ favorites: string[] }` (array of ticker strings)
- POST `/api/v1/kalshi/favorites/toggle`
  - Request: `{ ticker: string }`
  - Response: `{ favorites: string[] }` (updated list)

**Error Modes:**
- 501 Not Implemented (recommended for now)
- 400 Bad Request (invalid ticker)
- 500 Internal Server Error

**Roadmap Relevance:**
- Common UX pattern for market discovery
- Moderate priority - improves user experience but not critical for core trading

**Decision:** **STUB (501)**
- Add backend stub returning 501 with descriptive message: "Favorites feature not yet implemented"
- Keep DiscoverView.tsx favorites UI but add error handling to show disabled state
- Hide favorites quick filter when 501 returned

---

### 3. KALSHI_SENTIMENT_LANE_SNAPSHOT

**Used in:** `useSentimentBundle.ts` (sentiment analysis hook)

**User Flow:**
- Fetches comprehensive sentiment snapshot per asset/lane
- Includes Twitter, Reddit, Fear & Greed, combined signals
- Used by sentiment views and risk engine

**Required Request/Response Shape:**
- GET `/api/v1/kalshi/sentiment/lane-snapshot`
  - Response: `LaneSentimentSnapshot` interface with social sources, FG index, smoothed signals, confidence, staleness metrics

**Error Modes:**
- 501 Not Implemented (recommended for now)
- 500 Internal Server Error

**Roadmap Relevance:**
- Sentiment analysis is core to trading signals
- Likely high priority if sentiment-driven strategies are active

**Decision:** **STUB (501)**
- Add backend stub returning 501 with descriptive message: "Sentiment lane snapshot not yet implemented"
- Keep useSentimentBundle.ts but add fallback to existing sentiment endpoints if available
- Consider hiding sentiment features when 501 returned

---

## Unused Constants (Defined but Not Used)

### 4. KALSHI_NEWS_SIGNALS

**Defined in:** `constants.ts` line 200
**Used in:** Nowhere (grep found no usage)

**Decision:** **REMOVE**
- Delete from `constants.ts`
- Remove from test mocks if present
- No UI impact since not used

---

### 5. KALSHI_CATEGORIES

**Defined in:** `constants.ts` line 205
**Used in:** `KillSwitchView.tsx` (line 68, 200), test mocks

**User Flow:**
- Used in KillSwitchView for category filtering or display
- Appears to be for kill-switch risk categorization

**Required Request/Response Shape:**
- GET `/api/v1/kalshi/categories`
  - Response: `{ categories: string[] }` or similar

**Error Modes:**
- 501 Not Implemented (recommended for now)
- 500 Internal Server Error

**Roadmap Relevance:**
- Used in risk management context
- Moderate priority - needed if kill-switch uses category-based controls

**Decision:** **STUB (501)**
- Add backend stub returning 501 with descriptive message: "Categories endpoint not yet implemented"
- Keep KillSwitchView.tsx but add error handling to show disabled state or fallback

---

## Summary Table

| Endpoint | Used In UI | Decision | Action |
|----------|-----------|----------|--------|
| KALSHI_PUBLISH_PIPELINE | Yes (PublishPipelinePanel) | STUB (501) | Add backend stub, hide UI behind feature flag |
| KALSHI_PUBLISH_PIPELINE_TRIGGER | Yes (PublishPipelinePanel) | STUB (501) | Add backend stub, hide UI behind feature flag |
| KALSHI_FAVORITES | Yes (DiscoverView) | STUB (501) | Add backend stub, show disabled state |
| KALSHI_FAVORITES_TOGGLE | Yes (DiscoverView) | STUB (501) | Add backend stub, show disabled state |
| KALSHI_SENTIMENT_LANE_SNAPSHOT | Yes (useSentimentBundle) | STUB (501) | Add backend stub, add fallback logic |
| KALSHI_NEWS_SIGNALS | No | REMOVE | Delete from constants.ts |
| KALSHI_CATEGORIES | Yes (KillSwitchView) | STUB (501) | Add backend stub, show disabled state |

---

## Backend Implementation Notes

For STUB decisions, backend should return:
```json
{
  "detail": "This endpoint is not yet implemented. Coming soon."
}
```
With HTTP status 501 Not Implemented.

For REMOVE decisions, no backend action needed (endpoint never existed).

---

## Next Steps

1. **Backend:** Add 501 stub handlers for 6 endpoints (PUBLISH_PIPELINE, FAVORITES, SENTIMENT_LANE_SNAPSHOT, CATEGORIES)
2. **Frontend:** Add error handling in PublishPipelinePanel, DiscoverView, useSentimentBundle, KillSwitchView to show "Coming Soon" state on 501
3. **Frontend:** Remove KALSHI_NEWS_SIGNALS from constants.ts (unused)
4. **Frontend:** Update test mocks to removed constant (KALSHI_NEWS_SIGNALS)
5. **Test:** Verify UI handles 501 gracefully without breaking
