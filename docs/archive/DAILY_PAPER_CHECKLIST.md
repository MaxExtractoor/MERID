# 📋 MERID DAILY PAPER SESSION CHECKLIST

## 🚀 SESSION START (Pre-Launch)

### Environment Setup
- [ ] Set credentials: `export PAPER_API_KEY="PKOWKXL5TGIC4XHG5H67TBGPVF"`
- [ ] Set credentials: `export PAPER_API_SECRET="3JpvXKQkzM2HjYHwyXRuX395pCMwmeE9uoL5dvRawNsi"`
- [ ] Ensure `SIMULATION_MODE` is NOT set (real data only)
- [ ] Verify no synthetic mode: `echo $SIMULATION_MODE` should be empty

### Health Checks
- [ ] Run: `curl http://127.0.0.1:8011/healthz` → should return `"status": "healthy"`
- [ ] Run: `curl http://127.0.0.1:8011/readyz` → should return `"status": "ready"`
- [ ] Verify MERID server running: `ps aux | grep uvicorn`

### Paper Trading Setup
- [ ] Run: `python scripts/setup_paper_trading.py`
- [ ] Verify: ✅ Broker connection OK
- [ ] Verify: ✅ Market data OK  
- [ ] Verify: ✅ Test orders OK
- [ ] Verify: ✅ Config written to `config/paper_trading.json`

### Real Data Validation (GO/NO-GO)
- [ ] Run: `python scripts/validate_real_data.py`
- [ ] Verify: ✅ API Health: MERID API healthy
- [ ] Verify: ✅ Markets Data: Real data only (no synthetic)
- [ ] Verify: ✅ Drift Signals: Real data monitoring
- [ ] Verify: ✅ Arbitrage: Real data monitoring
- [ ] Verify: ✅ Data Freshness: < 5 minutes old
- [ ] **STOP HERE if any validation fails**

## 🎯 PHASE 1: BOOTING (First 5 minutes)

### System Startup
- [ ] Start MERID: `python -m uvicorn web.main:app --host 127.0.0.1 --port 8011`
- [ ] Wait for: "RealPredictionMarketAggregator started" in logs
- [ ] Check: `/healthz` returns healthy
- [ ] Check: `/readyz` returns ready
- [ ] Verify: No synthetic mode warnings in logs

### Data Feed Verification
- [ ] Check: `/api/v1/market/data/freshness` → `"status": "fresh"`
- [ ] Check: `/api/v1/institutional/predictions/markets` → Real markets or empty (never synthetic)
- [ ] Verify: No 2020-2021 data in responses
- [ ] Verify: No "warming up" fallback messages

## 🎯 PHASE 2: WARMING UP (Next 10 minutes)

### Market Data Monitoring
- [ ] Monitor: Market count stabilizes (not growing synthetic data)
- [ ] Check: Drift signals endpoint shows "Monitoring X real markets"
- [ ] Check: Arbitrage endpoint shows "Monitoring X real markets"
- [ ] Verify: Platform count shows 1 (Polymarket) or 0 (APIs down)

### Risk Engine Status
- [ ] Verify: Risk engine threads alive in logs
- [ ] Check: No risk engine errors
- [ ] Verify: Position limits loaded from config
- [ ] Check: Circuit breakers active

## 🎯 PHASE 3: OBSERVATION MODE (30 minutes)

### Shadow Trading (No Real Orders)
- [ ] Enable: Shadow mode in config
- [ ] Monitor: Strategy decisions in logs
- [ ] Watch: UI shows "SHADOW" status
- [ ] Verify: No actual orders placed
- [ ] Check: PnL stays at 0 (no real trades)

### Signal Detection
- [ ] Monitor: Any drift signals appear
- [ ] Monitor: Any arbitrage opportunities appear
- [ ] Log: All signal timestamps and sources
- [ ] Verify: All signals have real market IDs

## 🎯 PHASE 4: PAPER TRADING (2+ hours)

### Enable Real Paper Trading
- [ ] Switch: Shadow → Paper mode
- [ ] Set: Small notional (e.g., $100 per trade)
- [ ] Verify: Paper orders actually placing
- [ ] Monitor: Order fills and rejections
- [ ] Track: Real PnL changes

### Live Monitoring
- [ ] Watch: UI dashboard for live updates
- [ ] Monitor: Execution logs for errors
- [ ] Check: Risk limits being enforced
- [ ] Verify: No synthetic data in any feed
- [ ] Track: Market data freshness stays < 5 minutes

### Incident Response
- [ ] If any synthetic data appears: STOP session immediately
- [ ] If API errors > 5 minutes: Pause trading
- [ ] If risk breaches: Auto-shutdown should trigger
- [ ] If UI shows stale data: Refresh and re-validate

## 🛑 SESSION SHUTDOWN

### Graceful Shutdown
- [ ] Stop: All trading activity
- [ ] Cancel: All open paper orders
- [ ] Export: Session logs and PnL data
- [ ] Save: Market data snapshots
- [ ] Verify: All positions closed

### Post-Session Analysis
- [ ] Review: Total trades placed
- [ ] Analyze: Win/loss ratio
- [ ] Check: Risk limit breaches
- [ ] Document: Any synthetic data incidents
- [ ] Update: Runbook with lessons learned

## 🚨 CRITICAL STOP CONDITIONS

**IMMEDIATELY STOP PAPER TRADING IF:**
- Any synthetic/mock data detected in any API response
- Health endpoints fail (`/healthz` or `/readyz`)
- Data freshness > 5 minutes
- Risk limits breached
- API connectivity issues > 5 minutes
- Unexpected "warming up" messages appear

## 📊 SESSION METRICS TO TRACK

**Every Session:**
- Start time, end time
- Total trades placed
- PnL (paper)
- Risk limit breaches
- API error count
- Synthetic data incidents (should be 0)
- Market data freshness (max age)

**Weekly Review:**
- Session success rate
- Average PnL per session
- Risk compliance rate
- Data quality score

---

## 🎯 SUCCESS CRITERIA

**Session is SUCCESSFUL if:**
- ✅ All pre-launch validations pass
- ✅ Zero synthetic data incidents
- ✅ No risk limit breaches
- ✅ Market data stays fresh
- ✅ Health endpoints remain stable
- ✅ Clean shutdown completed

**Session requires RETRY if:**
- ❌ Any validation fails at start
- ❌ Synthetic data appears
- ❌ Health endpoints fail
- ❌ Risk limits breached

---

*This checklist should be used for EVERY paper trading session. No exceptions.*
