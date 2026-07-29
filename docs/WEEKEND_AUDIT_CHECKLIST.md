# Weekend Audit Checklist

## Purpose
This checklist ensures comprehensive verification of the trading system before the next trading week begins. It covers all critical components, especially the exit policy fixes and 5-asset stack verification.

## Pre-Audit Preparation

- [ ] **System Shutdown**: Ensure all trading systems are safely shut down
- [ ] **Database Backup**: Complete full database backup
- [ ] **Configuration Snapshot**: Save current configuration files
- [ ] **Logs Archive**: Archive logs from previous week
- [ ] **Deployment Notes**: Document any changes made during the week

## Exit Policy Disconnect Fixes (2026-07-29)

### Position Size Synchronization
- [ ] **Verify position_monitor.py fix**: Confirm ratchet trim and staged exit do NOT update position.size directly
- [ ] **Check fix comments**: Verify "CRITICAL FIX: Do NOT update position.size here" comments are present
- [ ] **Run regression tests**: Execute `py -m pytest tests/test_position_size_synchronization_fixes_2026_07_29.py -v`
- [ ] **Verify all tests pass**: Ensure 10/10 tests pass
- [ ] **Check fill callback path**: Confirm position.size is only updated via fill callback

### Asset-Specific Exit Parameters
- [ ] **Verify exit_policy_resolver.py**: Confirm profile config loading is present
- [ ] **Check asset extraction helper**: Verify extract_asset_from_position() works for all 5 assets
- [ ] **Test profile config**: Confirm all 5 assets (BTC, ETH, SOL, XRP, DOGE) have TP/SL distances configured
- [ ] **Verify Tier 2 adjustments**: Check SOL/XRP/DOGE have wider TP thresholds in order_router.py

## 5-Asset Stack Verification

### WebSocket Feeds
- [ ] **Run end-to-end audit**: Execute `py scripts/audit_5_crypto_assets_end_to_end.py`
- [ ] **Verify BTC WebSocket**: Confirm BTC feed is connected and data is fresh
- [ ] **Verify ETH WebSocket**: Confirm ETH feed is connected and data is fresh
- [ ] **Verify SOL WebSocket**: Confirm SOL feed is connected and data is fresh
- [ ] **Verify XRP WebSocket**: Confirm XRP feed is connected and data is fresh
- [ ] **Verify DOGE WebSocket**: Confirm DOGE feed is connected and data is fresh
- [ ] **Check data staleness**: Verify no asset has stale data (>5 seconds old)
- [ ] **Check connection health**: Verify all WebSocket connections are healthy

### Market Catalog Discovery
- [ ] **Verify BTC markets**: Confirm KXBTC15M series is discovered
- [ ] **Verify ETH markets**: Confirm KXETH15M series is discovered
- [ ] **Verify SOL markets**: Confirm KXSOL15M series is discovered
- [ ] **Verify XRP markets**: Confirm KXXRP15M series is discovered
- [ ] **Verify DOGE markets**: Confirm KXDOGE15M series is discovered
- [ ] **Check market count**: Verify each series has active markets

### Agent Grid Activation
- [ ] **Verify BTC_15M agent**: Confirm BTC_15M agent is active in grid
- [ ] **Verify ETH_15M agent**: Confirm ETH_15M agent is active in grid
- [ ] **Verify SOL_15M agent**: Confirm SOL_15M agent is active in grid
- [ ] **Verify XRP_15M agent**: Confirm XRP_15M agent is active in grid
- [ ] **Verify DOGE_15M agent**: Confirm DOGE_15M agent is active in grid
- [ ] **Check agent health**: Verify all agents are healthy and generating signals

### Risk Enforcement
- [ ] **Verify BTC risk limits**: Confirm BTC has position limits enforced
- [ ] **Verify ETH risk limits**: Confirm ETH has position limits enforced
- [ ] **Verify SOL risk limits**: Confirm SOL has position limits enforced
- [ ] **Verify XRP risk limits**: Confirm XRP has position limits enforced
- [ ] **Verify DOGE risk limits**: Confirm DOGE has position limits enforced
- [ ] **Check $1 exposure cap**: Verify global $1 exposure cap is enforced across all assets

### Exit Policy Parameters
- [ ] **Verify BTC TP/SL**: Confirm BTC has correct TP (80%) and SL (40%) distances
- [ ] **Verify ETH TP/SL**: Confirm ETH has correct TP (80%) and SL (40%) distances
- [ ] **Verify SOL TP/SL**: Confirm SOL has correct TP (80%) and SL (40%) distances
- [ ] **Verify XRP TP/SL**: Confirm XRP has correct TP (80%) and SL (40%) distances
- [ ] **Verify DOGE TP/SL**: Confirm DOGE has correct TP (80%) and SL (40%) distances
- [ ] **Check trailing stops**: Verify trailing stop parameters are loaded per asset

## Position State Monitoring

### Desync Detection
- [ ] **Start position state monitor**: Ensure monitoring service is running
- [ ] **Check desync metrics**: Verify no active desyncs detected
- [ ] **Review desync history**: Check for any desync events in the past week
- [ ] **Verify alerts**: Confirm desync alerts are working if threshold exceeded
- [ ] **Test monitoring**: Trigger test desync to verify detection works

## Legacy Contamination Check

### Production Stack Verification
- [ ] **Verify main_15m_lean.py**: Confirm production uses main_15m_lean.py, NOT main.py
- [ ] **Check imports**: Verify no imports from legacy main.py
- [ ] **Check startup logic**: Confirm proper FastAPI lifespan mechanism
- [ ] **Verify KalshiVenueClient**: Confirm production KalshiVenueClient is used
- [ ] **Check market state store**: Verify production market state store is used

### WebSocket Stack Verification
- [ ] **Verify KalshiWebSocketBridge**: Confirm production WebSocket bridge is used
- [ ] **Check WebSocket client**: Verify ws.py client is used, not websocket_service
- [ ] **Check subscriptions**: Verify correct market IDs are subscribed
- [ ] **Monitor IDLE state**: Check for IDLE state issues indicating subscription problems

## Risk Controls

### Exposure Cap
- [ ] **Verify $1 cap**: Confirm MERID_FIXED_EXPOSURE_CAP_USD=1.00 is set
- [ ] **Check enforcement**: Verify cap is enforced across all 5 assets
- [ ] **Test cap violation**: Attempt to exceed cap and verify rejection
- [ ] **Review exposure logs**: Check for any cap violations in past week

### Kill Switches
- [ ] **Test risk kill switch**: Verify risk kill switch can be activated
- [ ] **Test per-market kill switch**: Verify per-market kill switches work
- [ ] **Check kill switch logs**: Review kill switch activation history
- [ ] **Verify auto-recovery**: Confirm auto-recovery mechanisms work

## Order Execution

### Order Routing
- [ ] **Verify order_router.py**: Confirm latest fixes are applied
- [ ] **Check duplicate window**: Verify 5-second duplicate window is in place
- [ ] **Check post_only logic**: Verify marketable orders are NOT post_only
- [ ] **Test anti-stacking**: Verify open-order guard prevents stacking
- [ ] **Check fill accounting**: Verify fill accounting path is fixed

### Resting Order Monitor
- [ ] **Verify find_open_order**: Confirm find_open_order() function exists
- [ ] **Check polling interval**: Verify 30-second polling interval
- [ ] **Test order tracking**: Verify resting orders are tracked correctly
- [ ] **Check TERMINAL_STATUSES**: Verify terminal status filtering works

## Data Integrity

### Spot Data
- [ ] **Verify spot provider**: Confirm spot provider is available
- [ ] **Test spot fetch**: Test get_spot_price() for all 5 assets
- [ ] **Check data freshness**: Verify spot data is not stale
- [ ] **Review spot logs**: Check for spot data errors in past week

### Market Data
- [ ] **Verify market state**: Confirm market state store is populated
- [ ] **Check orderbook data**: Verify orderbook data is fresh
- [ ] **Test price updates**: Verify price updates are received via WebSocket
- [ ] **Check timestamp consistency**: Verify timestamps are consistent

## Performance Monitoring

### Latency
- [ ] **Check WebSocket latency**: Verify WebSocket latency is <200ms
- [ ] **Check order routing latency**: Verify order routing latency is acceptable
- [ ] **Check fill callback latency**: Verify fill callback latency is acceptable
- [ ] **Review latency logs**: Check for latency spikes in past week

### Error Rates
- [ ] **Check error classification**: Review error classification logs
- [ ] **Verify error handling**: Confirm errors are handled gracefully
- [ ] **Check retry logic**: Verify retry logic is working
- [ ] **Review error rates**: Check for elevated error rates

## Pre-Deployment Checklist

### Configuration
- [ ] **Verify profile config**: Confirm kalshi_crypto_15m_v2.yaml is correct
- [ ] **Check environment variables**: Verify all required env vars are set
- [ ] **Test configuration load**: Verify configuration loads without errors
- [ ] **Check config validation**: Run configuration validation

### Dependencies
- [ ] **Check Python version**: Verify correct Python version is used
- [ ] **Verify dependencies**: Confirm all dependencies are installed
- [ ] **Check for updates**: Verify no critical updates are pending
- [ ] **Test imports**: Verify all imports work correctly

### Testing
- [ ] **Run unit tests**: Execute unit test suite
- [ ] **Run integration tests**: Execute integration test suite
- [ ] **Run regression tests**: Execute regression test suite
- [ ] **Verify test coverage**: Check test coverage is adequate

## Post-Deployment Verification

### Startup
- [ ] **Verify clean startup**: Confirm system starts without errors
- [ ] **Check initialization**: Verify all components initialize correctly
- [ ] **Monitor startup logs**: Review startup logs for warnings/errors
- [ ] **Verify health checks**: Confirm all health checks pass

### Runtime
- [ ] **Monitor for 1 hour**: Observe system behavior for first hour
- [ ] **Check WebSocket connections**: Verify all WebSocket connections are stable
- [ ] **Monitor position state**: Verify no position state desyncs occur
- [ ] **Check order flow**: Verify orders are routed correctly

### Rollback Plan
- [ ] **Document rollback steps**: Document steps to rollback if needed
- [ ] **Test rollback**: Test rollback procedure
- [ ] **Verify backup integrity**: Verify backups are accessible
- [ ] **Set rollback criteria**: Define criteria for triggering rollback

## Sign-Off

- [ ] **Auditor Name**: ___________________
- [ ] **Audit Date**: ___________________
- [ ] **Audit Result**: PASS / FAIL
- [ ] **Notes**: ___________________

## Critical Issues Found

If any critical issues are found during the audit:
1. Document the issue in detail
2. Assess impact and severity
3. Implement fix or workaround
4. Re-test after fix
5. Update this checklist with resolution

## Continuous Improvement

After each audit:
1. Review audit findings
2. Identify areas for improvement
3. Update checklist as needed
4. Share lessons learned with team
5. Implement process improvements
