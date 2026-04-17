# MERID Expiry Behavior Map — Kalshi Crypto Series

**Purpose:** Document current system behavior in the final 5 minutes before expiration for all Kalshi crypto agents/series.  
**Date:** 2026-03-28  
**Ground Truth:** `docs/KALSHI_RTI_SETTLEMENT_WINDOW_REFERENCE.md`

---

## 1. Series and Agent Coverage Matrix

| Asset | Series | Timeframe | Agent(s) | RTI-Settled | Settlement Window |
|-------|--------|-----------|----------|-------------|-------------------|
| BTC | KXBTC-15M | 15m | BTC_15M_Agent, Continuous Trader | ✅ | 60s TWAP |
| BTC | KXBTC | 1h | BTC_1H_Agent, Continuous Trader | ✅ | 60s TWAP |
| BTC | KXBTC-D1 | daily | BTC_DAILY_Agent | ✅ | 1800s TWAP (Ref Rate) |
| BTC | KXBTC-W1 | weekly | BTC_WEEKLY_Agent | ✅ | 1800s TWAP (Ref Rate) |
| ETH | KXETH-15M | 15m | ETH_15M_Agent, Continuous Trader | ✅ | 60s TWAP |
| ETH | KXETH | 1h | ETH_1H_Agent, Continuous Trader | ✅ | 60s TWAP |
| ETH | KXETH-D1 | daily | ETH_DAILY_Agent | ✅ | 1800s TWAP (Ref Rate) |
| ETH | KXETH-W1 | weekly | ETH_WEEKLY_Agent | ✅ | 1800s TWAP (Ref Rate) |
| SOL | KXSOL-15M | 15m | SOL_15M_Agent, Continuous Trader | ✅ | 60s TWAP |
| SOL | KXSOL | 1h | SOL_1H_Agent, Continuous Trader | ✅ | 60s TWAP |
| SOL | KXSOL-D1 | daily | SOL_DAILY_Agent | ✅ | 1800s TWAP (Ref Rate) |
| SOL | KXSOL-W1 | weekly | SOL_WEEKLY_Agent | ✅ | 1800s TWAP (Ref Rate) |
| XRP | KXXRP-15M | 15m | XRP_15M_Agent, Continuous Trader | ✅ | 60s TWAP |
| XRP | KXXRP | 1h | XRP_1H_Agent, Continuous Trader | ✅ | 60s TWAP |
| XRP | KXXRP-D1 | daily | XRP_DAILY_Agent | ✅ | 1800s TWAP (Ref Rate) |
| XRP | KXXRP-W1 | weekly | XRP_WEEKLY_Agent | ✅ | 1800s TWAP (Ref Rate) |
| DOGE | KXDOGE-15M | 15m | DOGE_15M_Agent, Continuous Trader | ✅ | 60s TWAP |
| DOGE | KXDOGE | 1h | DOGE_1H_Agent, Continuous Trader | ✅ | 60s TWAP |
| DOGE | KXDOGE-D1 | daily | DOGE_DAILY_Agent | ✅ | 1800s TWAP (Ref Rate) |
| DOGE | KXDOGE-W1 | weekly | DOGE_WEEKLY_Agent | ✅ | 1800s TWAP (Ref Rate) |

**Total Agents:** 35 individual agents (5 assets × 4 timeframes × ~1.75 agents per cell)

---

## 2. Expiry Behavior Table — Final 5 Minutes

### 2.1 Filter Pipeline Layer

| Time to Expiry | Behavior | Code Location | Config |
|----------------|----------|---------------|--------|
| > 61s | Markets pass through to candidates | `kalshi_filter_pipeline.py:39` | `min_seconds_to_expiry_rti_crypto=61` |
| ≤ 61s | Markets **excluded** from candidate pool | `kalshi_filter_pipeline.py:_passes_expiry()` | Default: 61s buffer |
| N/A (non-RTI) | Uses `min_minutes_to_expiry` only | Same | No RTI guard |

**⚠️ Finding:** Filter pipeline uses **61 seconds** as the exclusion threshold, which is **1 second more** than the 60-second settlement window. This is correct — provides 1s buffer.

### 2.2 Settlement Execution Guard Layer

| Time to Expiry | Action=Buy | Action=Sell | Policy | Code Location |
|----------------|------------|-------------|--------|---------------|
| > 60s | Allowed | Allowed | N/A | `settlement_execution_guard.py:50` |
| ≤ 60s | **BLOCKED** | Allowed | `reduce_ok` (default) | `evaluate_settlement_order()` |
| ≤ 60s | **BLOCKED** | **BLOCKED** | `block_all` | `MERID_RTI_SETTLEMENT_ORDER_POLICY` |
| ≤ 60s | Allowed* | Allowed | `reduce_ok` + `MERID_RTI_ALLOW_BUY_IF_SETTLEMENT_GRADE=1` | If 60-slot buffer complete |

**⚠️ Finding:** The guard checks `seconds_to_expiry` against `MERID_RTI_SETTLEMENT_FINAL_SECONDS` (default: 60). This **exactly matches** the RTI window, meaning buys are blocked as soon as the settlement window begins.

### 2.3 Order Router Layer

| Step | Behavior | Code | Notes |
|------|----------|------|-------|
| 1 | Route receives `OrderIntent` | `order_router.py:route_order()` | |
| 2 | Mode check (SIM/PAPER/LIVE) | Uses `get_venue_gate()` | Fail-closed |
| 3 | Settlement guard evaluation | Calls `evaluate_settlement_order()` | Only for RTI tickers |
| 4 | TIF resolution | `_resolve_tif()` | IOC auto if < 10s to expiry |
| 5 | Risk check | `PredictionMarketRisk` | Pre-trade validation |
| 6 | Dispatch | Mock/Paper/Live adapter | |

**⚠️ Finding:** No additional expiry buffer in order router beyond settlement guard. Relies on upstream filter pipeline.

### 2.4 Continuous Trader Layer

| Component | Expiry Behavior | Config | Gap |
|-----------|-----------------|--------|-----|
| Filter Pipeline | Excludes markets < 61s | `MERID_FILTER_RTI_MIN_SECONDS` (default: 61) | ✅ Correct |
| Settlement Guard | Blocks buys < 60s | `MERID_RTI_SETTLEMENT_FINAL_SECONDS` (default: 60) | ⚠️ Same-second boundary |
| Candidate Scan | Uses `seconds_to_expiry` from `MarketStateStore` | Real-time calculation | ✅ Fresh data |

**⚠️ Finding:** Continuous trader does NOT explicitly check settlement guard — it relies on the filter pipeline exclusion. If a market passes the filter (e.g., at exactly 61s), the order router will catch it at the guard layer.

### 2.5 Trading Agent (KalshiTradingAgent) Layer

| Behavior | Implementation | Gap Analysis |
|----------|----------------|--------------|
| Entry window check | `EntryWindowConfig` allows time-of-day filtering | ❌ No explicit seconds-to-expiry check in agent |
| Market resolution | Resolves from series tickers → live markets | Uses `market_filter` min/max minutes |
| Strategy evaluation | `KalshiStrategy.generate_signal()` | No expiry-specific logic |
| Pre-trade risk | `PredictionMarketRisk.check_order()` | Checks portfolio limits, not expiry |
| Order placement | `kalshi_place_order()` tool | Relies on order router guard |

**⚠️ CRITICAL GAP:** Trading agents do NOT explicitly check `seconds_to_expiry` before generating signals. They rely entirely on:
1. Market resolution returning only active markets
2. Filter pipeline excluding near-expiry markets
3. Order router settlement guard

This is a **three-layer defense**, but the agent itself is unaware of expiry proximity.

---

## 3. Clock and Timer Dependencies

| Component | Clock Source | Staleness Tolerance | Fallback |
|-----------|--------------|---------------------|----------|
| Filter Pipeline | `MarketStateStore.seconds_to_expiry` | Real-time from Kalshi WS | Uses `close_time` from catalog |
| Settlement Guard | Passed as parameter from caller | Depends on caller | N/A |
| Order Router | `MarketStateStore` via caller | ~1-5s | Catalog `end_date` |
| Agent Decision Loop | `MarketStateStore` via resolver | ~1-5s | Catalog refresh |
| RTI Buffer | CF Benchmarks adapter | 1s per sample | Mark stale after 2s gap |

**⚠️ Finding:** No central "time service" — each component derives time independently from `MarketStateStore` or catalog data. Clock skew risk is mitigated by using Kalshi-provided `expiration_time` (absolute) rather than local calculation where possible.

---

## 4. Kill-Switch and Circuit Breaker Mapping

### 4.1 Global Kill Switches Affecting All Kalshi Crypto

| Switch | Trigger | Effect on Expiry Trading | Code |
|--------|---------|--------------------------|------|
| `kalshi_disabled` | Manual operator, daily loss limit, error rate | All orders rejected immediately | `merid/risk/kill_switches.py` |
| `MERID_PM_TRADING_MODE=sim` | Config, kill switch activation | All orders mocked, no real execution | `venue_gate.py` |
| `drawdown_halt` | Bankroll drops 20% from peak | New positions blocked, flattening allowed | `KalshiRiskEngine` |
| `swarm_degraded` | No consensus for 120s | Orders capped to "small" size, max 3 trades | `KalshiTradingAgent` |

### 4.2 Per-Agent Kill Switches

| Switch | Trigger | Effect | Code |
|--------|---------|--------|------|
| `consecutive_errors ≥ 5` | 5 cycle errors in a row | Agent pauses itself | `KalshiTradingAgent` |
| `solo_trades_this_degraded_session ≥ 3` | Too many solo trades | Agent halts | `KalshiTradingAgent` |
| `lifecycle = DRAINING` | Graceful shutdown | Finishes current cycle, stops | `KalshiTradingAgent` |

### 4.3 Circuit Breakers

| Breaker | Condition | Action | Recovery |
|---------|-----------|--------|----------|
| Kalshi API 5xx | 3 consecutive errors | Pause for 30s | Auto-retry |
| WebSocket disconnect | Unplanned disconnect | Reconnect with backoff | Auto |
| RTI data stale | No new samples for 2s | Log warning, degrade gracefully | Auto when data resumes |

---

## 5. Gap Analysis and Findings

### 5.1 ✅ Correctly Implemented

1. **Filter pipeline** uses 61s threshold (1s buffer beyond 60s window)
2. **Settlement guard** blocks buys at exactly 60s (aligns with RTI window start)
3. **Order router** is the final gate before API submission
4. **Reduce-only policy** allows position closing during settlement window
5. **TIF resolution** automatically uses IOC for < 10s to expiry

### 5.2 ⚠️ Gaps and Risks

| # | Gap | Risk | Severity | Recommended Fix |
|---|-----|------|----------|---------------|
| G1 | `KalshiTradingAgent` has no explicit expiry check | Agent may generate signals for markets about to expire | MEDIUM | Add `seconds_to_expiry` check before signal generation |
| G2 | Continuous trader relies solely on filter pipeline | If filter pipeline bypassed, no expiry protection | LOW | Add explicit settlement guard call in CT |
| G3 | `seconds_to_expiry` calculation distributed | Clock skew between components could allow trades at 59s | LOW | Use centralized `expiration_time` comparison |
| G4 | No RTI buffer health check in trading loop | May trade with incomplete settlement data | MEDIUM | Gate trades on `is_settlement_grade()` |
| G5 | `MERID_RTI_ALLOW_BUY_IF_SETTLEMENT_GRADE=1` allows buys at 60s | Race condition: buy at T-60s, fill during RTI window | HIGH | Remove this flag or require T-120s minimum |
| G6 | No dedicated "expiry mode" in kill switches | Cannot quickly halt all near-expiry trading | MEDIUM | Add `expiry_proximity` kill switch reason |

### 5.3 ❌ Not Implemented (Acceptable)

- Early suspension handling (Kalshi rarely suspends crypto markets)
- Extended expiry handling (CFTC review extensions are rare for crypto)
- Per-market kill switches (overkill for current scale)

---

## 6. Time-to-Expiry Decision Matrix

| Time Remaining | Filter Pipeline | Settlement Guard | Order Router | Trading Allowed? | Notes |
|----------------|-----------------|-------------------|--------------|------------------|-------|
| > 5 minutes | Pass | Pass | Pass | ✅ YES | Normal trading |
| 61s - 5min | Pass | Pass | Pass | ✅ YES | Normal trading |
| 60s - 61s | **EXCLUDE** | N/A | N/A | ❌ NO | Filter pipeline blocks |
| 0s - 60s | Excluded | **BLOCK BUY** | N/A | ⚠️ SELL ONLY | Reduce-only mode |
| Expired | Excluded | N/A | N/A | ❌ NO | Market closed |

---

## 7. Dependencies on External Systems

```
┌─────────────────────────────────────────────────────────────┐
│  CF Benchmarks RTI Feed (60 samples, 1 per second)           │
│  ↓                                                          │
│  merid/data/rti_feed_service.py → 60-slot buffer            │
│  ↓                                                          │
│  merid/data/settlement_rti_buffer.py (per-market)          │
│  ↓                                                          │
│  MarketStateStore.seconds_to_expiry (real-time)              │
│  ↓                                                          │
│  ┌──────────────┐  ┌──────────────────┐  ┌──────────────┐  │
│  │ Filter       │  │ Settlement       │  │ Order        │  │
│  │ Pipeline     │→ │ Execution Guard  │→ │ Router       │  │
│  │ (exclusion)  │  │ (buy blocking)   │  │ (TIF/IOC)    │  │
│  └──────────────┘  └──────────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

**Document Status:** Ground truth for expiry chaos test design  
**Next Action:** Use this mapping to design concrete chaos scenarios in `EXPIRY_CHAOS_TEST_PLAN.md`
