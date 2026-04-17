# MERID Pre-Deployment Checklist

Use this checklist before deploying to production.

## Environment Setup

- [ ] Copied `.env.example` to `.env`
- [ ] Set `MERID_ENV=production`
- [ ] Set `MERID_PROFILE=kalshi-only` (for production)
- [ ] Set `MERID_TRADING_MODE=paper` (start safe)
- [ ] Configured `KALSHI_API_KEY_ID` (if live trading)
- [ ] Placed `kalshi_private_key.pem` in secure location
- [ ] Set `KALSHI_API_PRIVATE_KEY_PATH` correctly
- [ ] Set strong `MERID_DASHBOARD_API_KEY`
- [ ] Disabled dev bypasses: `MERID_DEV_AUTH_BYPASS=0`
- [ ] Configured `MERID_ALLOWED_ORIGINS` for your domain

## Safety Limits (Critical)

- [ ] Set `MERID_MAX_ORDER_SIZE_USD` (recommend: $100 for testing)
- [ ] Set `MERID_MAX_DAILY_LOSS_USD` (recommend: $500 for testing)
- [ ] Set `MERID_MAX_POSITION_SIZE_USD` (recommend: $1000 for testing)
- [ ] Set `MERID_PM_MAX_NOTIONAL_PER_MARKET` (recommend: $500)
- [ ] Set `MERID_PM_MAX_TOTAL_NOTIONAL` (recommend: $5000)
- [ ] Enabled `MERID_REQUIRE_CONFIRMATION=true`

## Security

- [ ] Verified `.env` is in `.gitignore`
- [ ] Verified `kalshi_private_key.pem` is in `.gitignore`
- [ ] No secrets committed to git (run `git log --all --full-history -- .env`)
- [ ] Set `MERID_ENABLE_CAPTCHA=true` (for public deployments)
- [ ] Set `MERID_REQUIRE_VPN_HEADER=true` (for internal deployments)

## Build Verification

- [ ] Docker builds successfully: `docker build -t merid:test .`
- [ ] Frontend builds: `cd web/react && npm run build`
- [ ] No TypeScript errors: `npm run type-check`
- [ ] Tests pass: `npm test` (frontend) / `py -m pytest tests/` (backend)

## Health Checks

- [ ] Backend starts: `python -m web.main`
- [ ] Health endpoint responds: `curl http://localhost:8011/api/v1/health`
- [ ] Kalshi endpoints work: `curl http://localhost:8011/api/v1/kalshi/balance`
- [ ] WebSocket connects: Test via browser DevTools

## Monitoring Setup

- [ ] Health check URL configured in hosting platform
- [ ] Logs are being captured
- [ ] Alerts configured for:
  - [ ] Server downtime
  - [ ] High error rates
  - [ ] Trading halt events
  - [ ] Daily loss limit reached

## Deployment Steps

### Railway Deployment
```bash
railway login
railway link
railway up
railway open
```

### Docker Deployment
```bash
docker build -t merid:latest .
docker run -d -p 8011:8011 --env-file .env --name merid merid:latest
```

### Local Production
```bash
./start.sh production
```

## Post-Deployment Verification

- [ ] Application is accessible at deployed URL
- [ ] Health check returns 200 OK
- [ ] Trading mode shows "PAPER" in UI
- [ ] Kalshi balance displays correctly
- [ ] Can place paper orders
- [ ] Kill switch responds correctly
- [ ] WebSocket streams active

## Before Enabling Live Trading

⚠️ **ONLY after thorough paper trading testing:**

- [ ] Paper trading profitable for 1+ weeks
- [ ] All safety mechanisms tested
- [ ] Kill switch tested and working
- [ ] Circuit breakers tested
- [ ] Emergency contacts configured
- [ ] Set `MERID_TRADING_MODE=live`
- [ ] Set `MERID_PM_LIVE_ENABLED=true`
- [ ] Set `MERID_LIVE_TRADING_UNLOCKED=true`

## Rollback Plan

- [ ] Database backup procedure documented
- [ ] Previous version container image tagged
- [ ] Quick rollback command ready: `docker stop merid && docker run -d --name merid-backup <previous-image>`

## Support Contacts

- [ ] Primary on-call contact configured
- [ ] Backup contact configured
- [ ] Kalshi support contact saved
- [ ] Hosting platform support contact saved

---

**Only proceed to live trading after ALL items are checked and paper trading is verified working correctly.**
