# Security & Rate Limiting Posture Review

**Review Date:** 2026-03-28  
**Scope:** External API consumption security + exposed API security  
**Status:** Phase 8 of Rate Limit Audit

---

## 1. API Key Isolation & Environment Separation

### Current State

| Provider | Dev/Staging Key | Production Key | Shared? | Risk |
|----------|-----------------|----------------|---------|------|
| Kalshi | KALSHI_USE_DEMO=true | KALSHI_USE_DEMO=false | ❌ No | Low |
| Messari | MESSARI_API_KEY | Same key possible | ⚠️ Possible | Medium |
| CoinGecko | COINGECKO_API_KEY | COINGECKO_PRO_API_KEY | ❌ No | Low |
| Twitter | X_BEARER_TOKEN | X_BEARER_TOKEN | ⚠️ Likely | High |
| OpenAI | OPENAI_API_KEY | OPENAI_API_KEY | ⚠️ Likely | High |

### Recommendations

1. **Enforce key isolation** — Never use production keys in dev/staging
2. **Use Kalshi demo API** for all non-production (already implemented via `KALSHI_USE_DEMO`)
3. **Create separate Twitter app** for dev vs prod (different API keys)
4. **Use OpenAI organization separation** or different projects for dev/prod
5. **Document key rotation schedule** in `docs/SECURITY.md`

---

## 2. Exposed API Security (MERID's Own Endpoints)

### Current Rate Limiting on MERID APIs

| Endpoint Type | Rate Limiting | Auth Required | Status |
|---------------|---------------|---------------|--------|
| `/api/v1/kalshi/*` | ❌ None per endpoint | ✅ Yes | Gap |
| `/api/v1/prediction/*` | ❌ None per endpoint | ✅ Yes | Gap |
| `/api/v1/system/*` | ❌ None | ✅ Admin only | Low risk |
| WebSocket streams | ❌ None | ✅ Session-based | Gap |
| `/api/v1/sentiment/*` | ❌ None | ✅ Yes | Gap |

### Required Hardening

1. **Implement per-user rate limits** on all external-facing endpoints
   - Recommendation: 100 req/min per user for read endpoints
   - Recommendation: 10 req/min per user for order endpoints
   
2. **Add WAF/gateway rules** (if behind Cloudflare/AWS ALB)
   - Block IPs with >1000 req/min
   - Require User-Agent header
   - Block known bad actors

3. **Add 429 responses with Retry-After headers**
   ```python
   @router.get("/api/v1/kalshi/markets")
   @rate_limit(max_requests=100, window=60)
   async def get_markets():
       ...
   ```

---

## 3. Abuse Resistance Measures

### Current Protections

| Measure | Implementation | Status |
|---------|----------------|--------|
| Kalshi circuit breaker | `CircuitBreaker` in client.py | ✅ Active |
| Telegram circuit breaker | `TGCircuitBreaker` | ✅ Active |
| Kill switch (global) | `RiskController` | ✅ Active |
| Per-venue kill switch | `VenueGate` | ✅ Active |
| IP-based rate limiting | ❌ Not implemented | Gap |

### Recommended Additions

1. **IP-based rate limiting middleware** for FastAPI
   ```python
   @app.middleware("http")
   async def ip_rate_limit(request, call_next):
       ip = request.client.host
       if not rate_limiter.is_allowed(ip):
           return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})
   ```

2. **API key rotation detection**
   - Alert if old keys still in use after rotation
   - Automatic revocation on key leak detection

3. **Unusual pattern detection**
   - Alert if single IP hits 10x normal traffic
   - Alert if new geographic location appears

---

## 4. Secrets Management

### Current State

Secrets stored in `.env` file:
```
KALSHI_API_KEY_ID=xxx
KALSHI_PRIVATE_KEY_PATH=kalshi_private_key.pem
TELEGRAM_TOKEN=xxx
OPENAI_API_KEY=xxx
```

### Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| `.env` committed to git | Low | Critical | ✅ `.gitignore` configured |
| `.env` backup exposure | Medium | High | ⚠️ Manual process |
| Key logged in error traces | Medium | High | ⚠️ Partial sanitization |
| PEM file exposure | Low | Critical | ✅ `.gitignore` covers *.pem |

### Recommendations

1. **Use secret management service** for production
   - AWS Secrets Manager / Azure Key Vault / HashiCorp Vault
   - Mount secrets as environment variables at runtime

2. **Sanitize logs** — Ensure API keys never appear in logs
   ```python
   # In httpx/http client wrappers
   safe_url = url.replace(api_key, "***")
   ```

3. **Regular key rotation**
   - Kalshi: Every 90 days
   - Twitter: Every 90 days
   - OpenAI: Every 180 days

---

## 5. Provider-Specific Security Notes

### Kalshi (Primary Venue)

**Current Security:**
- RSA-PSS signing (strong)
- Private key in PEM file (acceptable if protected)
- Demo vs Live separation via `KALSHI_USE_DEMO`

**Recommendations:**
1. Encrypt PEM file at rest
2. Use short-lived session tokens if available
3. Monitor for unexpected order patterns

### LLM Providers (OpenAI, Anthropic)

**Current Security:**
- Bearer token auth
- No usage caps enforced client-side

**Risk:** Cost exposure if key leaked

**Recommendations:**
1. Implement monthly spend caps in client wrapper
2. Alert on unusual token usage spikes
3. Use separate keys per environment

### Twitter/X API

**Current Security:**
- OAuth 2.0 + Bearer token
- No rate limit tracking

**Risk:** Account suspension if rate limits exceeded

**Recommendations:**
1. Implement sliding window rate limiter
2. Track per-15min usage
3. Queue tweets if limit approached

---

## 6. Compliance & Audit

### Audit Trail Requirements

1. **Log all external API calls** with:
   - Timestamp
   - Provider
   - Endpoint (sanitized)
   - Response status
   - Request ID
   - User/agent initiating

2. **Log all rate limit events:**
   - 429 responses received
   - Throttled requests
   - Circuit breaker trips
   - Kill switch activations

3. **Retention:** 90 days for operational logs, 1 year for security logs

### Current Audit Trail Coverage

| Event | Logged | Location |
|-------|--------|----------|
| Kalshi order placed | ✅ Yes | `kalshi/client.py` |
| Kalshi 429 received | ✅ Yes | `kalshi/client.py` |
| Telegram sent | ✅ Yes | `webhook_client.py` |
| Rate limit backoff | ✅ Yes | `external_api_rate_limiter.py` |
| Messari call | ⚠️ Partial | No structured logging |
| CoinGecko call | ❌ No | Raw httpx |

---

## 7. Security Checklist

### For New API Integrations

- [ ] Document rate limits in `config/rate_limits.yaml`
- [ ] Use `ExternalAPIClient` or implement token bucket
- [ ] Separate dev/staging/prod API keys
- [ ] Add to secrets rotation schedule
- [ ] Implement structured logging
- [ ] Add circuit breaker for critical paths
- [ ] Document in `docs/EXTERNAL_API_RATE_LIMIT_AUDIT.md`
- [ ] Add tests for rate limiting behavior

### For Existing APIs (Priority Order)

**P0 (Critical):**
- [ ] Migrate Alpha Vantage to rate-limited client (25/day limit)
- [ ] Add per-15min tracking for Twitter
- [ ] Implement IP-based rate limiting on MERID endpoints

**P1 (High):**
- [ ] Migrate Messari to rate-limited client
- [ ] Migrate CoinGecko to rate-limited client
- [ ] Add monthly caps for LLM providers

**P2 (Medium):**
- [ ] Add unusual pattern detection
- [ ] Implement secret management service integration
- [ ] Add geographic anomaly detection

---

## 8. Incident Response

### Rate Limit Breach Response

1. **Immediate (0-5 min):**
   - Activate kill switch if trading affected
   - Alert on-call via Telegram/SMS

2. **Short-term (5-30 min):**
   - Identify source agent/module
   - Implement emergency throttling
   - Contact provider if account-level issue

3. **Recovery (30+ min):**
   - Gradual ramp-up with increased monitoring
   - Post-incident review
   - Update rate limits if consistently hitting

### Key Leak Response

1. **Immediate:**
   - Revoke leaked key
   - Activate kill switch
   - Rotate all related keys

2. **Investigation:**
   - Review logs for unauthorized usage
   - Check billing for unexpected charges
   - Document exposure window

3. **Recovery:**
   - Deploy new keys
   - Resume with monitoring

---

*End of Security Review*
