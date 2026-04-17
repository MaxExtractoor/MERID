# MERID External API Rate Limit Audit

**Audit Date:** 2026-03-28  
**Auditor:** Cascade (systematic code audit)  
**Scope:** All external API calls in MERID codebase  
**Status:** Phase 4 of 9 Complete

---

## Executive Summary

This audit maps all outbound API call patterns to identify rate limit gaps and prioritize hardening work.

| Category | Providers | Files with Calls | Rate Limiting Status |
|----------|-----------|------------------|---------------------|
| Prediction Markets | 1 (Kalshi) | 45+ files | ✅ Implemented (KalshiTokenBucket) |
| Crypto Exchanges | 5+ | 12 files | ⚠️ Partial (some use raw httpx) |
| Market Data | 6+ | 30+ files | ❌ Missing (no client-side enforcement) |
| LLM Providers | 4+ | 8 files | ❌ Missing |
| Social APIs | 4+ | 15+ files | ⚠️ Partial (Telegram has circuit breaker) |
| **TOTAL** | **18+** | **78+ files** | **~40% covered** |

---

## 1. Kalshi (Prediction Markets) — PRIMARY VENUE

### Current Rate Limiting
- **Implementation:** `KalshiTokenBucket` in `client.py:176` with separate read/write buckets
- **Tiers Supported:** Basic (20/10), Advanced (30/30), Premier (100/100), Prime (400/400)
- **Self-Limiting:** Conservative 18r/s read, 8r/s write under Basic tier
- **Retry Logic:** Exponential backoff on 429, respects `Retry-After` headers

### Call Sites Inventory

| Module | Function | Pattern | Rate Limited? |
|--------|----------|---------|---------------|
| `kalshi/client.py` | `_request()` | Core HTTP | ✅ Yes (token bucket) |
| `kalshi/ws.py` | `connect()` | WebSocket | ⚠️ No (separate WS limits) |
| `kalshi/fix_client.py` | `send_message()` | FIX protocol | ⚠️ No (session msgs excluded) |
| `strategies/kalshi_rate_limited_client.py` | `get/post()` | REST wrapper | ✅ Yes (separate impl) |
| `kalshi/maker_bot_advanced.py` | `*_order()` | Order placement | ✅ Via KalshiVenueClient |
| `kalshi/venue_adapter.py` | `*_paper_order()` | Paper trading | ✅ Via shared client |
| `trading/kalshi_continuous_trader.py` | `get_market_data()` | Market data | ✅ Via shared client |
| `prediction/agent_grid.py` | `refresh_markets()` | Market sync | ✅ Via shared client |
| `prediction/trading_agent.py` | `_kalshi_get_positions()` | Position fetch | ✅ Via shared client |
| `prediction/social_broadcaster.py` | `publish_consensus()` | Publishing | N/A (outbound only) |

### Gaps Identified
1. **FIX WebSocket:** Session-level rate limiting not implemented (Kalshi excludes session messages from limits, but application messages need tracking)
2. **Multiple Client Instances:** 6+ places create standalone `KalshiVenueClient` instances, each with own token bucket — not a true singleton
3. **No Per-Agent Quotas:** 35 agents share same bucket, no fair-share allocation

---

## 2. Market Data Providers — HIGH PRIORITY

### 2.1 Messari (Crypto Fundamentals)

| File | Line | Call Pattern | Current Limiting |
|------|------|--------------|------------------|
| `prediction/messari_context.py` | 105-111 | `httpx.AsyncClient.get()` | ❌ None (just 15min cache) |
| `prediction/messari_context.py` | 117 | `_get_json()` | ❌ Raw httpx |

**Provider Limits:** 20 req/min (free tier)  
**Current MERID Usage:** Uncapped, only cached  
**Risk:** High (if cache disabled, could exceed 20/min)  
**Recommended:** Use `ExternalAPIClient` with 0.27r/s (15/min with safety factor)

### 2.2 CoinGecko (Crypto Prices)

| File | Line | Call Pattern | Current Limiting |
|------|------|--------------|------------------|
| `prediction/coingecko_context.py` | 45-52 | `httpx.get()` | ❌ None |
| `trading/kalshi_continuous_trader.py` | ~180 | CoinGecko direct | ❌ None |

**Provider Limits:** 30 req/min demo, 500 req/min pro  
**Recommended:** Use `ExternalAPIClient` with 0.4r/s (24/min with safety factor)

### 2.3 Finnhub (Equities/Forex)

| File | Line | Call Pattern | Current Limiting |
|------|------|--------------|------------------|
| `prediction/finnhub_context.py` | 40-60 | `httpx.get()` | ❌ None |

**Provider Limits:** 60 req/min free, 300-1000 paid  
**Recommended:** Use `ExternalAPIClient` with 0.8r/s (48/min with safety factor)

### 2.4 Polygon.io (US Equities)

| File | Line | Call Pattern | Current Limiting |
|------|------|--------------|------------------|
| `prediction/polygon_context.py` | 35-55 | `httpx.get()` | ❌ None |

**Provider Limits:** 5-1000 req/min tier-based  
**Recommended:** Use `ExternalAPIClient` with tier-appropriate limits

### 2.5 Alpha Vantage

| File | Line | Call Pattern | Current Limiting |
|------|------|--------------|------------------|
| `prediction/alphavantage_context.py` | 30-45 | `httpx.get()` | ❌ None |

**Provider Limits:** 25/day free (very restrictive)  
**Risk:** Critical (easy to exceed)  
**Recommended:** Use `ExternalAPIClient` with aggressive caching + 0.001r/s

### 2.6 CoinMarketCap

| File | Line | Call Pattern | Current Limiting |
|------|------|--------------|------------------|
| `prediction/coinmarketcap_context.py` | 30-50 | `httpx.get()` | ❌ None |

**Provider Limits:** 10K-800K/month tier-based  
**Recommended:** Use `ExternalAPIClient` with monthly quota tracking

---

## 3. Crypto Exchanges — MEDIUM PRIORITY

### 3.1 Binance

| File | Line | Call Pattern | Current Limiting |
|------|------|--------------|------------------|
| `strategies/binance_auth.py` | 45-80 | `requests.get()` + HMAC | ⚠️ Basic (timestamp) |
| `strategies/binance_us_data.py` | 60-90 | `httpx.get()` | ❌ None |
| `strategies/binance_us_15m_btc.py` | 80-110 | `httpx.AsyncClient` | ❌ None |

**Provider Limits:** 1200 weight/min IP, 10 orders/sec account  
**Risk:** Medium (Binance aggressively rate limits and bans)  
**Recommended:** Implement IP-weight tracking, order rate limiting

### 3.2 Coinbase

| File | Line | Call Pattern | Current Limiting |
|------|------|--------------|------------------|
| `prediction/coingecko_context.py` | 70-90 | Coinbase as fallback | ❌ None |

**Provider Limits:** 10/sec public, 15/sec private  
**Recommended:** Use `ExternalAPIClient`

### 3.3 Kraken

| File | Line | Call Pattern | Current Limiting |
|------|------|--------------|------------------|
| (referenced but no direct calls found) | | | N/A |

---

## 4. LLM Providers — MEDIUM PRIORITY

### 4.1 OpenAI

| File | Line | Call Pattern | Current Limiting |
|------|------|--------------|------------------|
| `llm/client.py` | 55-60 | `requests.post()` | ❌ None |
| Various agents | — | Via `generate()` | ❌ None |

**Provider Limits:** Tier-based 200-10K RPM, 40K-6M TPM  
**Risk:** Medium (cost exposure if uncapped, not just rate)  
**Recommended:** Implement token-based rate limiting + cost tracking

### 4.2 Anthropic (Claude)

| File | Line | Call Pattern | Current Limiting |
|------|------|--------------|------------------|
| `llm/client.py` | 55-60 | `requests.post()` | ❌ None |

**Provider Limits:** 50-2000 RPM tier-based  
**Recommended:** Implement token-based rate limiting

### 4.3 DeepSeek / OpenRouter

| File | Line | Call Pattern | Current Limiting |
|------|------|--------------|------------------|
| Settings only | — | No direct calls | N/A |

---

## 5. Social/Sentiment APIs — MEDIUM PRIORITY

### 5.1 Twitter/X API

| File | Line | Call Pattern | Current Limiting |
|------|------|--------------|------------------|
| `sentiment/twitter_fetcher.py` | 60-120 | OAuth 2.0 calls | ❌ None |
| `agents/social_ingestion.py` | 80-150 | Tweet fetching | ❌ None |
| `web/api/x_client.py` | 40-80 | Publishing API | ❌ None |

**Provider Limits:** 500-100K req/15min tier-based  
**Risk:** High (easy to exceed free tier)  
**Recommended:** Implement sliding window per 15min, track per endpoint

### 5.2 Reddit API

| File | Line | Call Pattern | Current Limiting |
|------|------|--------------|------------------|
| `sentiment/reddit_scraper.py` | 90-150 | OAuth calls | ❌ None |

**Provider Limits:** 60 req/min OAuth  
**Recommended:** Use `ExternalAPIClient` with 0.8r/s

### 5.3 Telegram Bot API

| File | Line | Call Pattern | Current Limiting |
|------|------|--------------|------------------|
| `alerts/webhook_client.py` | 85-150 | `_tg_raw_send()` | ✅ Circuit breaker + coalescing |
| `notifications/telegram_client.py` | 60-100 | `send_alert()` | ✅ Via webhook_client |
| `agents/telegram_agent.py` | 70-120 | `send_message()` | ✅ Via circuit breaker |

**Provider Limits:** 30/sec global, 20/min per chat  
**Current Implementation:** 10s coalescing buffer, circuit breaker on 429  
**Status:** Well protected (see `tg_circuit_breaker.py`)

### 5.4 NewsAPI

| File | Line | Call Pattern | Current Limiting |
|------|------|--------------|------------------|
| `prediction/news_context.py` | 40-60 | `httpx.get()` | ❌ None |

**Provider Limits:** 100 req/day free  
**Risk:** High (easy to exceed)  
**Recommended:** Aggressive caching + daily quota tracking

---

## 6. Infrastructure APIs — LOW PRIORITY

### 6.1 Supabase

| File | Line | Call Pattern | Current Limiting |
|------|------|--------------|------------------|
| `db/supabase.py` | 30-80 | `httpx` calls | N/A (unlimited tiers) |

**Risk:** Low  
**Action:** None required

### 6.2 Helius (Solana RPC)

| File | Line | Call Pattern | Current Limiting |
|------|------|--------------|------------------|
| `blockchain/onchain_data.py` | 50-90 | JSON-RPC | ⚠️ Basic (1K-10K/day limits) |

**Provider Limits:** 1K-10K req/day tier-based  
**Recommended:** Request counting if usage grows

---

## 7. Call Pattern Analysis

### 7.1 Pattern Types

| Pattern | Count | Risk Level | Example Files |
|---------|-------|------------|---------------|
| Raw `httpx.get/post()` | ~40 | High | `messari_context.py`, `finnhub_context.py` |
| `httpx.AsyncClient` context | ~25 | High | `coingecko_context.py`, `polygon_context.py` |
| `requests.get/post()` | ~15 | Medium | `kalshi_rate_limited_client.py` (sync) |
| Wrapped venue client | ~20 | Low | `kalshi/client.py`, `kalshi/ws.py` |
| Circuit breaker protected | ~8 | Low | `webhook_client.py`, `telegram_agent.py` |

### 7.2 Temporal Patterns

| Pattern | Risk | Description |
|---------|------|-------------|
| Per-tick polling | High | Called every loop tick (could be 1s) |
| Per-symbol fan-out | High | Loop over symbols, each calls API |
| Per-agent cascade | High | 35 agents each calling same API |
| Cache-first | Low | Only call if cache expired |
| WebSocket push | Low | No polling, event-driven |

### 7.3 Identified Fan-Out Risks

1. **Messari Context:** Called by 35 agents, each could trigger fetch if cache expired simultaneously
2. **CoinGecko:** Called per-symbol by continuous trader (BTC, ETH, SOL, etc.)
3. **Twitter:** Hashtag monitoring loops over multiple hashtags
4. **Kalshi:** 35 agents all hit `/portfolio/positions` on startup (already fixed via pre-fetch)

---

## 8. Risk Prioritization

### P0 (Fix This Week)

1. **Alpha Vantage** — 25/day limit, no enforcement
2. **Twitter API** — 500/15min free tier, no tracking
3. **Messari** — 20/min, called by 35 agents, cache-only protection

### P1 (Fix This Month)

4. **CoinGecko** — 30/min demo tier, direct calls in continuous trader
5. **Finnhub** — 60/min, no enforcement
6. **Polygon** — 5-1000/min tier-based
7. **Reddit** — 60/min, no enforcement

### P2 (Fix When Scaling)

8. **LLM Providers** — Cost-based limiting needed at scale
9. **Binance** — IP-weight tracking needed for aggressive strategies
10. **FIX Application Messages** — Track separately from session messages

---

## 9. Remediation Plan

### Immediate Actions (Done)

- [x] Create `config/rate_limits.yaml` with documented limits
- [x] Build `merid/external_api_rate_limiter.py` with `TokenBucket` + `ExternalAPIClient`
- [x] Implement per-agent quota management
- [x] Add exponential backoff with jitter for 429s

### Short-Term (This Week)

1. Wrap Messari calls with `ExternalAPIClient` (0.27r/s)
2. Wrap CoinGecko calls with `ExternalAPIClient` (0.4r/s)
3. Add per-15min sliding window for Twitter
4. Add daily quota tracker for Alpha Vantage + NewsAPI

### Medium-Term (This Month)

5. Migrate all market data contexts to `ExternalAPIClient`
6. Implement cost-based rate limiting for LLM providers
7. Add IP-weight tracking for Binance
8. Create unified rate limit dashboard in Operator UI

### Long-Term (Next Quarter)

9. Implement predictive rate limiting (slow down before hitting limits)
10. Add cross-provider failover (if Messari rate limited, try CoinGecko)
11. Build ML-based rate limit optimization based on actual usage patterns

---

## 10. Testing Strategy

### Unit Tests (Added to `tests/test_rate_limiter.py`)

- [ ] Token bucket math correctness
- [ ] Burst handling
- [ ] Concurrent request safety
- [ ] 429 retry with exponential backoff
- [ ] Per-agent quota enforcement

### Integration Tests

- [ ] Mock server returning 429s, verify backoff behavior
- [ ] Load test with 100 concurrent agents, verify global limit not exceeded
- [ ] Test quota manager rejects over-allocation

### Synthetic Load Tests

- [ ] Replay worst-case agent behavior (all 35 agents hitting same API)
- [ ] Validate actual headroom against documented limits
- [ ] Measure p99 latency under rate limit pressure

---

## Appendix: Files Requiring Updates

### High Priority (Rate Limiting Missing)

```
merid/prediction/messari_context.py
merid/prediction/coingecko_context.py
merid/prediction/finnhub_context.py
merid/prediction/polygon_context.py
merid/prediction/alphavantage_context.py
merid/prediction/coinmarketcap_context.py
merid/prediction/news_context.py
merid/sentiment/twitter_fetcher.py
merid/sentiment/reddit_scraper.py
merid/llm/client.py
```

### Medium Priority (Already Partially Protected)

```
merid/strategies/binance_auth.py
merid/strategies/binance_us_data.py
merid/blockchain/onchain_data.py
```

### Low Priority (Already Protected)

```
merid/event_venues/kalshi/client.py
merid/alerts/webhook_client.py
merid/alerts/tg_circuit_breaker.py
```

---

*End of Audit Report*
