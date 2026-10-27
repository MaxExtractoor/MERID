# Kalshi New UI Shadow Testing Procedure

## Overview

This document outlines the procedure for shadow testing the new Kalshi UI dashboard against production data before full rollout. Shadow testing allows us to validate the new UI against real production data without affecting live operations.

## Prerequisites

### Environment Setup
- Separate staging environment (not production)
- Access to production Kalshi API credentials
- Access to production backend database (read-only)
- Basic authentication or staff-only route protection
- Monitoring and logging enabled

### Access Control
- Restrict access to staff only (engineering, ops, QA)
- Use basic auth or IP whitelisting
- Log all access attempts
- Disable public access

## Shadow Testing Configuration

### Environment Variables
```bash
# .env.staging
VITE_API_BASE=https://staging-api.merid.example.com
VITE_WS_URL=ws://staging-api.merid.example.com/ws/trades
VITE_USE_KALSHI_NEW_UI=true
```

### Backend Configuration
- Point staging backend to production Kalshi API (read-only)
- Enable `/api/v1/kalshi/ui-state` endpoint
- Enable `/api/v1/kalshi/ui-state/ws` WebSocket endpoint
- Use production database for state aggregation (read-only)

### Frontend Configuration
- Set `USE_KALSHI_NEW_UI=true` in staging environment
- Deploy new KalshiDashboard component
- Enable all new UI components
- Configure monitoring and error tracking

## Testing Procedure

### Step 1: Deploy Shadow Environment

1. **Deploy backend to staging**
   ```bash
   # Deploy backend with production data source
   git checkout main
   git pull
   # Deploy to staging environment
   ```

2. **Deploy frontend to staging**
   ```bash
   # Build with new UI enabled
   VITE_USE_KALSHI_NEW_UI=true npm run build
   # Deploy to staging environment
   ```

3. **Verify deployment**
   - Check staging URL is accessible
   - Verify basic auth is working
   - Confirm new UI is enabled
   - Check backend endpoints are responding

### Step 2: Baseline Data Capture

1. **Capture legacy UI state**
   - Navigate to each legacy view (Discover, Analyze, Consensus, Size, Execute, Monitor, Promote, Protect)
   - Take screenshots of each view
   - Record key metrics:
     - Number of markets
     - Number of positions
     - Number of orders
     - Number of fills
     - Risk state (kill switch, execution gate, daily loss)
     - Grid status (running, active agents, cycles)
   - Export data where possible (CSV, JSON)

2. **Capture backend state**
   ```bash
   # Get canonical state
   curl https://staging-api.merid.example.com/api/v1/kalshi/ui-state > baseline-ui-state.json
   
   # Get fills
   curl https://staging-api.merid.example.com/api/v1/kalshi/fills > baseline-fills.json
   
   # Get orders
   curl https://staging-api.merid.example.com/api/v1/kalshi/orders > baseline-orders.json
   
   # Get positions
   curl https://staging-api.merid.example.com/api/v1/kalshi/positions > baseline-positions.json
   ```

### Step 3: Compare New UI to Legacy UI

For each view, compare the following:

#### Discover View
- [ ] Market count matches
- [ ] Market list matches (same tickers)
- [ ] Market data matches (prices, volumes, spreads)
- [ ] Position badges match
- [ ] Filters work correctly

#### Analyze Views (Sentiment, Vol)
- [ ] Sentiment data matches
- [ ] Volatility data matches
- [ ] Charts render correctly
- [ ] Time range selectors work

#### Consensus Views (Swarm, Performance, Calibration)
- [ ] Agent list matches
- [ ] Consensus data matches
- [ ] Performance metrics match
- [ ] Calibration data matches

#### Size View
- [ ] Bankroll data matches
- [ ] Lane configuration matches
- [ ] Sizing metrics match
- [ ] Risk limits match

#### Execute View
- [ ] Order list matches
- [ ] Position list matches
- [ ] Order entry works (paper mode only)
- [ ] Order cancellation works

#### Monitor View
- [ ] Portfolio data matches
- [ ] PnL history matches
- [ ] Health status matches

#### Promote View
- [ ] Pipeline status matches
- [ ] Grid status matches
- [ ] Agent list matches

#### Protect View
- [ ] Risk state matches
- [ ] Alert list matches
- [ ] Kill switch status matches
- [ ] Context data matches

### Step 4: Real-Time Validation

1. **Test WebSocket connectivity**
   - Open browser DevTools Network tab
   - Filter by WS (WebSocket)
   - Verify connection to `/api/v1/kalshi/ui-state/ws`
   - Check for ping/pong messages
   - Verify event messages are received

2. **Test real-time updates**
   - Place a test order (paper mode)
   - Verify order appears in new UI
   - Verify order appears in legacy UI
   - Cancel the order
   - Verify cancellation in both UIs
   - Verify WebSocket events for order/cancel

3. **Test connection status indicator**
   - Verify connection status shows "connected"
   - Verify last refresh time updates
   - Disconnect WebSocket (simulate network issue)
   - Verify status changes to "disconnected"
   - Verify reconnection attempt
   - Verify status returns to "connected"

### Step 5: Performance Validation

1. **Measure page load times**
   - Clear browser cache
   - Navigate to each view
   - Record load time (DevTools Performance tab)
   - Target: < 3 seconds per view

2. **Measure memory usage**
   - Open DevTools Memory tab
   - Take heap snapshot before navigation
   - Navigate through all views
   - Take heap snapshot after
   - Compare memory usage
   - Target: < 50MB increase

3. **Measure CPU usage**
   - Open DevTools Performance tab
   - Record for 30 seconds of normal usage
   - Check CPU usage
   - Target: < 10% when idle

### Step 6: Error Handling Validation

1. **Test error states**
   - Simulate backend failure (stop backend service)
   - Verify error message displays
   - Verify retry button works
   - Restart backend
   - Verify automatic recovery

2. **Test WebSocket failure**
   - Simulate WebSocket disconnection
   - Verify reconnection attempt
   - Verify exponential backoff
   - Verify connection status updates

3. **Test data staleness**
   - Stop WebSocket updates
   - Verify last refresh time shows old timestamp
   - Verify staleness warning appears (if implemented)

## Acceptance Criteria

The new UI is ready for production rollout when:

### Functional Requirements
- [ ] All views display correct data matching legacy UI
- [ ] All controls work (grid start/stop, kill switch, mode toggle)
- [ ] WebSocket connectivity is stable
- [ ] Real-time updates work correctly
- [ ] Connection status indicator works
- [ ] Error handling works correctly

### Performance Requirements
- [ ] Page load time < 3 seconds
- [ ] Memory usage increase < 50MB
- [ ] CPU usage < 10% when idle
- [ ] WebSocket latency < 100ms

### Data Integrity Requirements
- [ ] Fills match between new and legacy UI
- [ ] Orders match between new and legacy UI
- [ ] Positions match between new and legacy UI
- [ ] Risk state matches
- [ ] Grid status matches

### Operational Requirements
- [ ] No console errors
- [ ] No network errors (404, 500, timeouts)
- [ ] Logging is enabled and working
- [ ] Monitoring is enabled and working

## Rollback Decision

If any acceptance criteria fail, use the rollback playbook:
- [KALSHI_NEW_UI_ROLLBACK_PLAYBOOK.md](./KALSHI_NEW_UI_ROLLBACK_PLAYBOOK.md)

## Sign-Off

After successful shadow testing:

1. **Document findings**
   - Create test report with screenshots
   - Document any discrepancies found
   - Document performance metrics
   - Document any issues and resolutions

2. **Get approval**
   - Engineering lead approval
   - Ops team approval
   - QA team approval

3. **Schedule production rollout**
   - Choose low-traffic window
   - Notify all stakeholders
   - Prepare rollback plan
   - Monitor during rollout

## Contact Information

For shadow testing issues:
- Backend team: Check `#backend` channel
- Frontend team: Check `#frontend` channel
- QA team: Check `#qa` channel
- Ops team: Check `#ops` channel

## Related Documentation

- [Kalshi New UI Rollback Playbook](./KALSHI_NEW_UI_ROLLBACK_PLAYBOOK.md)
- [Kalshi UI Audit](./KALSHI_UI_AUDIT.md)
- [API Reference](./API_REFERENCE.md)
- [WebSocket Message Formats](./WEBSOCKET_MESSAGE_FORMATS.md)
