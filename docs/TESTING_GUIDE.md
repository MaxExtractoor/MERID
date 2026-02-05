# MERID Testing Guide

## Overview
Comprehensive testing guide for all new components, APIs, and enhancements implemented in the MERID system.

---

## Quick Start Testing

### 1. Start the Backend
```bash
cd c:\Dev\MERID
python -m uvicorn web.main:application --reload --port 8000
```

### 2. Start the Frontend
```bash
cd web/react
npm install
npm run dev
```

### 3. Access the Application
- Frontend: http://localhost:3000
- API Docs: http://localhost:8000/docs
- WebSocket Test: ws://localhost:8000/ws/paper-trading

---

## Component Testing

### ReflectionPanel.tsx

**Test Cases:**
1. **Component Renders**
   - Navigate to page with ReflectionPanel
   - Verify component loads without errors
   - Check loading state appears briefly

2. **Data Fetching**
   - Open browser DevTools → Network tab
   - Verify API calls to `/api/v1/reflection/summary`
   - Check response format matches expected structure

3. **Fallback Data**
   - Disable backend or block API endpoint
   - Verify fallback mock data displays
   - Check error message appears

4. **Auto-Refresh**
   - Keep component open for 30+ seconds
   - Verify data refreshes automatically
   - Check Network tab for periodic requests

**Expected Behavior:**
- Agent leaderboard sorted by accuracy
- Reality gap displayed as percentage
- Recent reflections show outcome validation
- Manual refresh button works

---

### ConsensusPanel.tsx

**Test Cases:**
1. **Vote Distribution**
   - Verify bullish/bearish/neutral bars display
   - Check percentages add up to 100%
   - Confirm colors match signal type

2. **Quorum Status**
   - Check quorum indicator (met/not met)
   - Verify min votes required displayed
   - Confirm threshold percentage shown

3. **Pending Votes Table**
   - Verify all columns display correctly
   - Check vote weight calculation
   - Confirm trust/energy/confidence values

4. **Performance Metrics**
   - Verify total rounds counter
   - Check success rate calculation
   - Confirm vetoed decisions count

**Expected Behavior:**
- Real-time updates every 5 seconds
- Vote weights calculated correctly
- Time until next consensus displayed
- All metrics rounded to appropriate precision

---

### DriftDetectionPanel.tsx

**Test Cases:**
1. **Drift Signals Display**
   - Verify signals sorted by magnitude
   - Check direction indicators (up/down arrows)
   - Confirm color coding (green/red)

2. **Filtering**
   - Test "All" filter shows all signals
   - Test "Up" filter shows only bullish
   - Test "Down" filter shows only bearish

3. **Summary Stats**
   - Verify total signals count
   - Check bullish/bearish breakdown
   - Confirm average drift calculation

4. **US Compliance**
   - Verify footer shows "Kalshi (US-compliant)"
   - Check no Polymarket data appears
   - Confirm source label correct

**Expected Behavior:**
- Drift signals from Kalshi only
- Auto-refresh every 30 seconds
- Volume displayed in thousands
- Time ago format (e.g., "2h ago")

---

### PaperTradingPanel.tsx

**Test Cases:**
1. **Portfolio Summary**
   - Verify balance displays correctly
   - Check P&L calculation ($ and %)
   - Confirm win rate percentage

2. **Open Positions**
   - Verify all positions display
   - Check unrealized P&L updates
   - Test close position button

3. **Pending Orders**
   - Verify orders display correctly
   - Check order type badges
   - Test cancel order button

4. **Tab Navigation**
   - Test switching between tabs
   - Verify content changes
   - Check active tab styling

**Expected Behavior:**
- Real-time P&L updates every 5 seconds
- Close position triggers API call
- Cancel order removes from list
- Trade history tab shows placeholder

---

### SimulationControlPanel.tsx

**Test Cases:**
1. **Playback Controls**
   - Test Play button starts simulation
   - Test Pause button stops simulation
   - Test Reset button (with confirmation)

2. **Speed Controls**
   - Test each speed option (1x, 10x, 100x, 1000x)
   - Verify active speed highlighted
   - Check speed label updates

3. **Time Display**
   - Verify current time updates
   - Check elapsed time format (HH:MM:SS)
   - Confirm time progresses at correct speed

4. **State Management**
   - Test Save State button (downloads JSON)
   - Test Load State button (placeholder)
   - Verify state persists across pause/resume

**Expected Behavior:**
- Status indicator shows running/paused
- Speed changes take effect immediately
- Reset clears all paper trading data
- Auto-refresh every 2 seconds

---

## API Endpoint Testing

### Using FastAPI Docs (Swagger UI)

1. Navigate to http://localhost:8000/docs
2. Find endpoint to test
3. Click "Try it out"
4. Fill in parameters
5. Click "Execute"
6. Verify response

### Consensus API

**GET /api/v1/consensus/status**
```bash
curl http://localhost:8000/api/v1/consensus/status
```

**Expected Response:**
```json
{
  "running": true,
  "pending_votes": 4,
  "min_votes_required": 3,
  "quorum_threshold": 0.67,
  "vote_distribution": {
    "bullish": 45,
    "bearish": 30,
    "neutral": 25
  }
}
```

---

### Paper Trading API

**GET /api/v1/paper/portfolio/{user_id}**
```bash
curl http://localhost:8000/api/v1/paper/portfolio/default
```

**POST /api/v1/paper/orders/place**
```bash
curl -X POST http://localhost:8000/api/v1/paper/orders/place \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "default",
    "asset": "BTC-USD",
    "side": "long",
    "size_usd": 1000,
    "order_type": "market",
    "leverage": 2
  }'
```

**POST /api/v1/paper/positions/{position_id}/close**
```bash
curl -X POST "http://localhost:8000/api/v1/paper/positions/pos_1/close?user_id=default"
```

---

### Simulation API

**POST /api/v1/simulation/start**
```bash
curl -X POST http://localhost:8000/api/v1/simulation/start
```

**POST /api/v1/simulation/speed/10**
```bash
curl -X POST http://localhost:8000/api/v1/simulation/speed/10
```

**POST /api/v1/simulation/reset**
```bash
curl -X POST http://localhost:8000/api/v1/simulation/reset
```

---

### Drift Detection API

**GET /api/v1/us-compliant/drift-signals**
```bash
curl "http://localhost:8000/api/v1/us-compliant/drift-signals?limit=20"
```

---

## WebSocket Testing

### Using Browser Console

```javascript
// Connect to paper trading WebSocket
const ws = new WebSocket('ws://localhost:8000/ws/paper-trading');

ws.onopen = () => {
  console.log('Connected to paper trading WebSocket');
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Received:', data);
};

ws.onerror = (error) => {
  console.error('WebSocket error:', error);
};

ws.onclose = () => {
  console.log('WebSocket closed');
};
```

**Expected Events:**
- `{"type": "trade", "trade": {...}}`
- `{"type": "position", "position": {...}}`
- `{"type": "summary", "stats": {...}}`
- `{"type": "ping", "ts": 1234567890}`

---

## Integration Testing

### End-to-End Flow: Place Paper Trade

1. **Start Services**
   - Backend running on port 8000
   - Frontend running on port 3000

2. **Navigate to Paper Trading Panel**
   - Open http://localhost:3000/paper-trading
   - Verify panel loads

3. **Place Order**
   - Use API or UI to place order
   - Verify order appears in pending orders

4. **Check Position**
   - Wait for order execution
   - Verify position appears in open positions
   - Check P&L calculation

5. **Close Position**
   - Click close button
   - Verify position removed
   - Check P&L added to balance

6. **Verify WebSocket Updates**
   - Open browser console
   - Check for real-time events
   - Verify data matches UI

---

### End-to-End Flow: Simulation Control

1. **Open Simulation Control Panel**
   - Navigate to simulation page
   - Verify panel displays

2. **Start Simulation**
   - Click Play button
   - Verify status changes to "RUNNING"
   - Check elapsed time increments

3. **Change Speed**
   - Click 10x speed
   - Verify time progresses faster
   - Check speed indicator updates

4. **Pause and Resume**
   - Click Pause button
   - Verify time stops
   - Click Play to resume
   - Check time continues from pause point

5. **Reset Simulation**
   - Click Reset button
   - Confirm dialog
   - Verify all data cleared
   - Check paper trading portfolios reset

---

## Performance Testing

### Load Testing

**Test 1: Concurrent WebSocket Connections**
```python
import asyncio
import websockets

async def connect():
    async with websockets.connect('ws://localhost:8000/ws/paper-trading') as ws:
        await asyncio.sleep(60)

# Run 100 concurrent connections
asyncio.run(asyncio.gather(*[connect() for _ in range(100)]))
```

**Expected:** All connections stable, no memory leaks

---

**Test 2: API Response Times**
```bash
# Test consensus status endpoint
ab -n 1000 -c 10 http://localhost:8000/api/v1/consensus/status
```

**Expected:** 
- Mean response time < 100ms
- 99th percentile < 500ms
- No failed requests

---

**Test 3: Component Rendering**
- Open React DevTools → Profiler
- Record interaction with component
- Check render times < 200ms
- Verify no unnecessary re-renders

---

## Error Handling Testing

### Test Scenarios

1. **Backend Offline**
   - Stop backend server
   - Verify components show fallback data
   - Check error messages display
   - Confirm retry mechanisms work

2. **Invalid API Responses**
   - Mock API to return 500 error
   - Verify error handling
   - Check user-friendly messages

3. **WebSocket Disconnection**
   - Close WebSocket connection
   - Verify automatic reconnection
   - Check data continuity

4. **Invalid User Input**
   - Try placing order with negative size
   - Try closing non-existent position
   - Verify validation errors

---

## Browser Compatibility

### Test Matrix

| Browser | Version | Status |
|---------|---------|--------|
| Chrome | Latest | ✅ Primary |
| Firefox | Latest | ✅ Supported |
| Safari | Latest | ⚠️ Test |
| Edge | Latest | ✅ Supported |

### Responsive Testing

**Breakpoints:**
- Mobile: 320px - 767px
- Tablet: 768px - 1023px
- Desktop: 1024px+

**Test Each Component:**
- Verify layout adapts
- Check touch interactions
- Confirm readability

---

## Accessibility Testing

### Checklist

- [ ] All buttons have aria-labels
- [ ] Keyboard navigation works
- [ ] Screen reader compatible
- [ ] Color contrast meets WCAG 2.1 AA
- [ ] Focus indicators visible
- [ ] No keyboard traps

### Tools
- Chrome DevTools → Lighthouse
- axe DevTools extension
- NVDA screen reader (Windows)

---

## Security Testing

### API Security

1. **Authentication**
   - Verify JWT tokens required (where applicable)
   - Test expired token handling
   - Check unauthorized access blocked

2. **Input Validation**
   - Test SQL injection attempts
   - Try XSS payloads
   - Verify parameter validation

3. **Rate Limiting**
   - Send rapid requests
   - Verify rate limits enforced
   - Check 429 responses

---

## Regression Testing

### After Each Change

1. **Run All Component Tests**
   - Verify no existing features broken
   - Check all API endpoints still work
   - Confirm WebSocket connections stable

2. **Visual Regression**
   - Compare screenshots before/after
   - Check for layout shifts
   - Verify styling consistency

3. **Performance Regression**
   - Compare response times
   - Check memory usage
   - Verify no new bottlenecks

---

## Automated Testing (Future)

### Unit Tests
```typescript
// Example: ReflectionPanel.test.tsx
import { render, screen } from '@testing-library/react';
import ReflectionPanel from './ReflectionPanel';

test('renders reflection panel', () => {
  render(<ReflectionPanel />);
  expect(screen.getByText(/Agent Learning/i)).toBeInTheDocument();
});
```

### Integration Tests
```python
# Example: test_paper_trading_api.py
import pytest
from fastapi.testclient import TestClient
from web.main import application

client = TestClient(application)

def test_get_portfolio():
    response = client.get("/api/v1/paper/portfolio/default")
    assert response.status_code == 200
    assert "current_balance" in response.json()
```

---

## Bug Reporting Template

```markdown
### Bug Description
[Clear description of the issue]

### Steps to Reproduce
1. [First step]
2. [Second step]
3. [Third step]

### Expected Behavior
[What should happen]

### Actual Behavior
[What actually happens]

### Environment
- OS: [Windows/Mac/Linux]
- Browser: [Chrome/Firefox/Safari]
- Version: [Version number]

### Screenshots
[If applicable]

### Console Errors
[Copy any error messages]
```

---

## Test Data

### Sample Users
- `default` - Main test user
- `user_1` - Secondary test user
- `test_trader` - High-volume trader

### Sample Assets
- `BTC-USD` - Bitcoin perpetual
- `ETH-USD` - Ethereum perpetual
- `SOL-USD` - Solana perpetual

### Sample Prediction Markets
- `kalshi_btc_100k` - Bitcoin price prediction
- `kalshi_fed_rate` - Fed rate decision
- `kalshi_eth_5k` - Ethereum price prediction

---

## Monitoring & Logging

### Check Logs
```bash
# Backend logs
tail -f logs/merid.log

# Filter for errors
grep ERROR logs/merid.log

# Filter for specific component
grep "paper_trading" logs/merid.log
```

### Monitor WebSocket Connections
```bash
# Check active connections
netstat -an | grep 8000 | grep ESTABLISHED
```

### Monitor API Performance
```bash
# Watch response times
watch -n 1 'curl -w "@curl-format.txt" -o /dev/null -s http://localhost:8000/api/v1/consensus/status'
```

---

## Troubleshooting

### Component Not Loading
1. Check browser console for errors
2. Verify API endpoint accessible
3. Check CORS configuration
4. Verify component imported correctly

### API Returns 404
1. Check endpoint path spelling
2. Verify router registered in main.py
3. Check FastAPI docs for available endpoints
4. Restart backend server

### WebSocket Connection Failed
1. Check WebSocket URL format (ws:// not http://)
2. Verify backend WebSocket endpoint exists
3. Check firewall/proxy settings
4. Test with browser DevTools → Network → WS

### Data Not Updating
1. Check polling interval
2. Verify API returns fresh data
3. Check component state management
4. Verify useEffect dependencies

---

## Success Criteria

### All Tests Pass
- [ ] All components render without errors
- [ ] All API endpoints return valid responses
- [ ] WebSocket connections stable
- [ ] Performance metrics met
- [ ] No console errors
- [ ] Accessibility requirements met
- [ ] Cross-browser compatibility verified

### Ready for Production
- [ ] All critical bugs fixed
- [ ] Documentation complete
- [ ] Code reviewed
- [ ] Security audit passed
- [ ] Performance benchmarks met
- [ ] User acceptance testing passed

---

## Next Steps

1. Run through all test cases
2. Document any issues found
3. Fix critical bugs
4. Re-test after fixes
5. Deploy to staging
6. Final production testing
7. Go live! 🚀
