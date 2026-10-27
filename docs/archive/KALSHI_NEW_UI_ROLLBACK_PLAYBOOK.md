# Kalshi New UI Rollback Playbook

## Overview

This playbook provides step-by-step instructions for rolling back from the new Kalshi UI to the legacy UI if issues arise during deployment.

## Architecture

### New UI Components
- `KalshiDashboard` - Unified dashboard composing all new components
- `KalshiCompactOverview` - System status, capital, markets, risk, grid overview
- `KalshiActivityStream` - Real-time event stream
- `KalshiDetailDrawer` - Progressive disclosure details
- `KalshiTroubleshootingView` - Logs, failures, reconciliation
- `KalshiActionArea` - Primary controls (grid start/stop, kill switch, mode toggle)

### Backend
- `/api/v1/kalshi/ui-state` - Canonical state aggregation endpoint
- `/api/v1/kalshi/ui-state/ws` - WebSocket endpoint for real-time updates
- `useKalshiUIState` hook - React hook for consuming canonical state

### Config Switch
- `USE_KALSHI_NEW_UI` - Environment variable to enable/disable new UI
- Default: `false` (legacy UI)
- Set to `true` to enable new unified dashboard

## Rollback Triggers

Roll back to legacy UI if any of the following occur:

### Critical Issues
- **Data mismatch**: New UI shows different fills, orders, or positions than legacy UI
- **Missing markets**: Markets visible in legacy UI are not shown in new UI
- **Incorrect risk state**: Risk limits, kill switch status, or execution gate state mismatch
- **WebSocket instability**: Connection status shows "disconnected" or "error" continuously
- **State staleness**: Last refresh time > 30 seconds old despite active trading

### Performance Issues
- **Page load time > 5 seconds** on initial load
- **UI freezes** when switching between tabs
- **Memory leaks** causing browser slowdown
- **High CPU usage** when idle

### Operational Issues
- **Controls not working**: Grid start/stop, kill switch, or mode toggle fail
- **Missing alerts**: Risk alerts not appearing in activity stream
- **Incorrect reconciliation status**: Discrepancy counts don't match backend

## Rollback Procedure

### Immediate Rollback (Emergency)

1. **Set environment variable to false**
   ```bash
   # In .env file or deployment config
   VITE_USE_KALSHI_NEW_UI=false
   ```

2. **Restart frontend**
   ```bash
   # For local development
   npm run dev
   
   # For production
   # Restart the frontend service/container
   ```

3. **Verify rollback**
   - Navigate to any Kalshi view (Discover, Analyze, Consensus, Size, Execute, Monitor, Promote, Protect)
   - Confirm legacy UI is displayed
   - Verify data matches expected state

### Gradual Rollback (If Immediate Rollback Not Possible)

1. **Disable new UI for specific views only**
   - Modify `resolveView` in `App.tsx` to exclude problematic views from redirection
   - Example: Remove 'execute' from kalshiViews array if order entry is broken

2. **Monitor logs**
   - Check browser console for errors
   - Check backend logs for `/api/v1/kalshi/ui-state` failures
   - Check WebSocket connection logs

3. **Report issue**
   - Document the specific issue (data mismatch, performance, etc.)
   - Include screenshots showing the problem
   - Note the exact steps to reproduce

## Post-Rollback Verification

After rollback, verify the following:

### Data Integrity
- [ ] Fills match between new and legacy UI
- [ ] Orders match between new and legacy UI
- [ ] Positions match between new and legacy UI
- [ ] Risk state matches (kill switch, execution gate, daily loss)
- [ ] Grid status matches (running, active agents, cycles)

### Functionality
- [ ] Grid start/stop controls work
- [ ] Kill switch toggle works
- [ ] Mode toggle works
- [ ] All navigation works
- [ ] All tabs load correctly

### Performance
- [ ] Page load time < 3 seconds
- [ ] No UI freezes when switching tabs
- [ ] Memory usage stable
- [ ] CPU usage normal when idle

## Root Cause Investigation

After rollback, investigate the root cause:

### Check Backend
1. **Verify `/api/v1/kalshi/ui-state` endpoint**
   ```bash
   curl http://localhost:8011/api/v1/kalshi/ui-state
   ```
   - Check response time (< 500ms)
   - Verify all fields are populated
   - Check for error messages

2. **Check WebSocket endpoint**
   - Verify WebSocket server is running
   - Check for connection errors in backend logs
   - Test with WebSocket client

### Check Frontend
1. **Check browser console**
   - Look for JavaScript errors
   - Look for network errors (404, 500, timeouts)
   - Check for WebSocket connection errors

2. **Check network tab**
   - Verify API calls are succeeding
   - Check response times
   - Look for failed requests

### Check Data Sources
1. **Verify Kalshi API connectivity**
   - Check if Kalshi API is accessible
   - Verify credentials are valid
   - Check rate limits

2. **Check database**
   - Verify database is accessible
   - Check for slow queries
   - Verify data consistency

## Re-enablement Procedure

After fixing the root cause, re-enable the new UI:

1. **Set environment variable to true**
   ```bash
   VITE_USE_KALSHI_NEW_UI=true
   ```

2. **Restart frontend**
   ```bash
   npm run dev  # or restart production service
   ```

3. **Verify re-enablement**
   - Navigate to Kalshi views
   - Confirm new unified dashboard is displayed
   - Run post-rollback verification checklist

4. **Monitor for issues**
   - Watch browser console for errors
   - Monitor performance metrics
   - Check data integrity

## Contact Information

For issues requiring assistance:
- Backend team: Check `#backend` channel
- Frontend team: Check `#frontend` channel
- Kalshi integration: Check `#kalshi` channel
- Emergency: Contact on-call engineer

## Related Documentation

- [Kalshi UI Simplification Progress](./KALSHI_UI_SIMPLIFICATION_PROGRESS.md)
- [Kalshi UI Audit](./KALSHI_UI_AUDIT.md)
- [API Reference](./API_REFERENCE.md)
- [WebSocket Message Formats](./WEBSOCKET_MESSAGE_FORMATS.md)
