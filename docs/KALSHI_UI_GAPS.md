# Kalshi UI-UX Gap Analysis

**Date:** 2026-03-04  
**Source:** `docs/UI/kalshi_workflow.md` + `docs/KALSHI_UI_CHANGELOG.md` + `docs/KALSHI_UI_AUDIT.md`  

---

## Current State: Comprehensive 17-View System

The Kalshi UI surface is well-developed with **17 active views** across **5 sidebar groups**:

### Sidebar Structure
```
LIVE TRADING                     SWARM INTELLIGENCE
  Overview                         Agent Grid
  Terminal                         Swarm Matrix
  Markets                          Performance
  Portfolio                        Calibration
  Positions                        Lane Control
  Orders

ANALYTICS                        COMMAND CENTER
  Fear / Greed                     Operator
  Vol & Sizing                     Kill Switch

SYSTEM
  Logs
  Settings
```

---

## UI-UX Gaps Identified

### 1. **Circuit Breaker Visualization** ⚠️ HIGH
**Gap:** No dedicated view for circuit breaker health status  
**Impact:** Operators can't see CB state transitions in real-time  
**Solution:** Add CB status card to:
- `OperatorDashboard` (small status indicator)
- `KalshiPortfolioView` Risk tab (detailed panel with transition history)
- New endpoint: `GET /api/v1/kalshi/circuit-breaker` (already implemented)

**Components needed:**
- `CircuitBreakerStatusCard` - shows CLOSED/HALF_OPEN/OPEN with color coding
- `CircuitBreakerHistory` - last 10 transitions with timestamps
- Alert badge when CB is OPEN (red pulsing indicator)

---

### 2. **Latency Percentile Dashboard** ⚠️ HIGH  
**Gap:** No visibility into p95/p99 API latency percentiles  
**Impact:** Can't monitor SLO compliance (target: p99 < 500ms)  
**Solution:** Add latency panel to:
- `KalshiVolDashboardView` (most appropriate - already has vol metrics)
- `OperatorDashboard` (system health context)

**Components needed:**
- `LatencyPercentileChart` - histogram or sparkline showing p50/p95/p99
- `LatencyAlertBadge` - fires when p99 exceeds threshold
- Mini latency indicator in mode badge area

**Data source:** `LatencyMonitor` class (already implemented)

---

### 3. **Correlation Risk Heatmap** ⚠️ MEDIUM
**Gap:** No visual representation of inter-asset correlation matrix  
**Impact:** Hard to spot correlation breakdowns that trigger exposure reduction  
**Solution:** Add to `KalshiPortfolioView` Risk tab:
- Correlation heatmap (BTC-ETH-SOL-XRP grid)
- Exposure reduction factor display
- Alert when correlation > 0.85

**Components needed:**
- `CorrelationHeatmap` - color-coded matrix (green=low, red=high)
- `CorrelationAlertBanner` - shows when limits triggered
- Mini correlation indicator in position cards

**Data source:** `/api/v1/kalshi/correlation/matrix` (already implemented)

---

### 4. **Regime Detection Indicators** ⚠️ MEDIUM
**Gap:** No UI for market regime states (trending/volatile/etc)  
**Impact:** Traders don't know when sizing has been auto-adjusted  
**Solution:** Add regime badges to:
- `KalshiDashboardView` market cards (regime badge per market)
- `KalshiTerminalView` (regime indicator near trade ticket)
- `KalshiGridView` (per-agent regime summary)

**Components needed:**
- `RegimeBadge` - shows TRENDING_UP/DOWN/VOLATILE/MEAN_REVERTING
- `RegimeConfidenceIndicator` - confidence % with color
- `RegimeAlertToast` - fires on regime transitions

**Data source:** `regime_detection.py` (already implemented)

---

### 5. **Error Code Breakdown Panel** ⚠️ MEDIUM
**Gap:** No visibility into structured error codes from order rejections  
**Impact:** Can't debug why orders are being rejected at scale  
**Solution:** Add to `KalshiPortfolioView` Orders tab:
- Error code distribution pie chart
- Time-series of rejections by code
- Top rejection reasons list

**Components needed:**
- `OrderRejectionPanel` - shows breakdown by `error_code`
- `ErrorCodeBadge` - shows code inline with rejected orders
- `RejectionTrendChart` - 24h rejection rate

**Data source:** `KalshiOrderErrorCode` taxonomy (already implemented)

---

### 6. **Performance Comparator Dashboard** ⚠️ LOW
**Gap:** No UI for backtest→paper→live comparison  
**Impact:** Can't visually track performance degradation across stages  
**Solution:** New view or add to `LaneControlDashboard`:
- Side-by-side stage comparison (3-column layout)
- Degradation alerts when live underperforms paper
- Promotion gate visualization

**Components needed:**
- `StageComparisonTable` - PF, Sharpe, win rate per stage  
- `DegradationAlert` - warns when live lags paper
- `PromotionGateTimeline` - shows paper→shadow→live progression

**Data source:** `PerformanceComparator` + scheduler (already implemented)

---

## Quick Wins (Can implement immediately)

| Gap | Effort | Files to modify |
|-----|--------|-----------------|
| CB status badge | 1h | `OperatorDashboard.tsx`, `KalshiPortfolioView.tsx` |
| Error code badges | 2h | `KalshiPortfolioView.tsx` Orders tab |
| Regime badges | 2h | `KalshiDashboardView.tsx` market cards |
| Latency mini-indicator | 1h | `KalshiModeBadge.tsx` |

---

## Medium-term Work (Next sprint)

| Gap | Effort | New components needed |
|-----|--------|----------------------|
| Correlation heatmap | 4h | `CorrelationHeatmap.tsx`, `KalshiPortfolioView.tsx` additions |
| Full CB dashboard | 4h | `CircuitBreakerPanel.tsx`, new sub-view |
| Rejection analytics | 6h | `OrderRejectionPanel.tsx`, chart components |
| Performance comparator view | 8h | New view `KalshiPerformanceComparatorView.tsx` |

---

## Already Implemented (From KALSHI_UI_CHANGELOG.md)

✅ Favorites/Watchlist system  
✅ Spread/liquidity badges  
✅ PnL equity curve chart  
✅ Live risk event stream  
✅ Typed AI insights panel  
✅ Paper Sessions navigation  

---

## Recommended Priority Order

1. **Circuit Breaker Status** - Critical for ops visibility
2. **Error Code Breakdown** - Helps debug current rejection issues
3. **Latency Indicator** - SLO compliance visibility
4. **Regime Badges** - Explain auto-sizing behavior
5. **Correlation Heatmap** - Risk visibility (already have endpoint)
6. **Performance Comparator** - Nice-to-have for promotions

---

## Integration Points

All gaps can leverage **existing backend implementations**:
- `/api/v1/kalshi/circuit-breaker` → CB status
- `/api/v1/kalshi/correlation/matrix` → Correlation data  
- `LatencyMonitor.get_stats()` → Latency percentiles
- `regime_detection.get_regime_detector()` → Regime states
- `order_router` error codes → Rejection analytics
