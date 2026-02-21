# MERID UI Components Guide

## Overview
This guide documents the newly implemented UI components and their integration with the MERID backend.

## New Components

### 1. ReflectionPanel.tsx
**Location:** `web/react/src/components/ReflectionPanel.tsx`

**Purpose:** Visualizes agent self-learning and reflection data, showing how agents improve over time.

**API Endpoints:**
- `GET /api/v1/reflection/summary` - Overall reflection statistics
- `GET /api/v1/reflection/reflections?limit=20` - Recent reflections
- `GET /api/v1/reflection/agents/{agent_id}/stats` - Per-agent statistics

**Features:**
- Agent performance leaderboard with accuracy metrics
- Reality gap tracking (prediction vs actual outcome)
- Recent reflection history with outcome validation
- Learning count per agent

**Usage:**
```tsx
import ReflectionPanel from '@/components/ReflectionPanel';

<ReflectionPanel className="w-full" />
```

**Data Format:**
```typescript
interface AgentStats {
  agent_id: string;
  total_decisions: number;
  accuracy: number;  // Percentage
  avg_reality_gap: number;  // Percentage
  recent_learnings: number;
}
```

---

### 2. ConsensusPanel.tsx
**Location:** `web/react/src/components/ConsensusPanel.tsx`

**Purpose:** Real-time visualization of consensus voting and decision-making across agents.

**API Endpoints:**
- `GET /api/v1/consensus/status` - Current consensus state
- `GET /api/v1/consensus/votes` - Pending votes
- `GET /api/v1/consensus/metrics` - Performance metrics
- `GET /api/v1/consensus/history` - Decision history

**Features:**
- Live vote distribution (bullish/bearish/neutral)
- Quorum status indicator
- Weighted voting visualization
- Trust, energy, and confidence metrics per vote
- Consensus performance statistics

**Usage:**
```tsx
import ConsensusPanel from '@/components/ConsensusPanel';

<ConsensusPanel className="w-full" />
```

**Key Metrics:**
- **Quorum Threshold:** 67% (2/3 majority)
- **Min Votes Required:** 3
- **Vote Weight:** trust × energy × confidence

---

### 3. DriftDetectionPanel.tsx
**Location:** `web/react/src/components/DriftDetectionPanel.tsx`

**Purpose:** Tracks and visualizes significant probability movements in prediction markets.

**API Endpoints:**
- `GET /api/v1/us-compliant/drift-signals?limit=50` - Recent drift signals

**Features:**
- Bullish/bearish drift categorization
- Drift magnitude visualization
- Volume-in-window tracking
- Time-based filtering
- US-compliant data source (Kalshi only)

**Usage:**
```tsx
import DriftDetectionPanel from '@/components/DriftDetectionPanel';

<DriftDetectionPanel className="w-full" />
```

**Drift Thresholds:**
- **Significant:** ≥15% change
- **Moderate:** 8-15% change
- **Minor:** 3-8% change

---

## Existing Components (Enhanced)

### SwarmPanel.tsx
**Status:** Enhanced with proper API integration

**Changes:**
- Backend response now transformed to match frontend expectations
- Agent data includes role names, status, and connections
- Tasks derived from swarm lab ideas with progress tracking

**API Endpoint:**
- `GET /api/v1/swarm/status` - Now returns properly formatted data

---

### ArbitragePanel.tsx
**Status:** Already functional

**API Endpoint:**
- `GET /api/v1/arbitrage/opportunities` - Cross-venue arbitrage opportunities

---

### RiskProtectionsPanel.tsx
**Status:** Already comprehensive

**API Endpoint:**
- `GET /api/v1/risk/protections` - Circuit breaker, kill switch, risk limits

---

### BrierMetricsPanel.tsx
**Status:** Already exists

**API Endpoints:**
- `GET /api/v1/metrics/dashboard/overview` - Brier score dashboard
- `POST /api/v1/metrics/evaluate` - Evaluate predictions

---

## API Documentation

### Consensus Engine API

#### GET /api/v1/consensus/status
Returns current consensus engine state.

**Response:**
```json
{
  "running": true,
  "pending_votes": 4,
  "min_votes_required": 3,
  "quorum_threshold": 0.67,
  "time_until_next": 6.5,
  "vote_distribution": {
    "bullish": 45,
    "bearish": 30,
    "neutral": 25
  }
}
```

#### GET /api/v1/consensus/votes
Returns pending votes awaiting consensus.

**Response:**
```json
{
  "votes": [
    {
      "agent_id": "analyst_gemma",
      "signal": "bullish",
      "confidence": 0.85,
      "trust": 0.92,
      "energy": 1.0,
      "weight": 0.78
    }
  ],
  "count": 4,
  "quorum_met": true
}
```

#### GET /api/v1/consensus/metrics
Returns consensus performance metrics.

**Response:**
```json
{
  "total_rounds": 156,
  "successful_consensus": 142,
  "vetoed_decisions": 8,
  "avg_confidence": 0.78,
  "quorum_rate": 0.91
}
```

---

### Reflection Layer API

#### GET /api/v1/reflection/summary
Returns overall reflection statistics.

**Response:**
```json
{
  "total_reflections": 156,
  "active_agents": 5,
  "agents": [
    {
      "agent_id": "analyst_gemma",
      "total_decisions": 45,
      "accuracy": 78.5,
      "avg_reality_gap": 12.3,
      "recent_learnings": 8
    }
  ]
}
```

---

### Drift Detection API

#### GET /api/v1/us-compliant/drift-signals
Returns recent odds drift signals from Kalshi.

**Query Parameters:**
- `limit` (int): Number of signals to return (default: 20, max: 100)

**Response:**
```json
{
  "signals": [
    {
      "signal_id": "drift_001",
      "market_id": "kalshi_btc_100k",
      "platform": "kalshi",
      "question": "Will Bitcoin reach $100,000 by Dec 31?",
      "old_probability": 62.5,
      "new_probability": 68.2,
      "drift_pct": 9.12,
      "direction": "up",
      "volume_in_window": 125000
    }
  ],
  "count": 1,
  "source": "kalshi"
}
```

---

## US Compliance

### Production Data Sources
- **Kalshi** - Primary prediction market (CFTC-regulated)
- All production prediction market data comes from Kalshi only

### Simulation Data Sources
- **SimulationPredictionAggregator** - Includes Polymarket and Augur
- Used ONLY for paper trading, backtesting, and research
- Clearly labeled as "simulation_only" in responses

---

## Component Integration Guide

### Adding a New Panel to Dashboard

1. **Import the component:**
```tsx
import ReflectionPanel from '@/components/ReflectionPanel';
```

2. **Add to your layout:**
```tsx
<div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
  <ReflectionPanel />
  <ConsensusPanel />
</div>
```

3. **Ensure API endpoints are accessible:**
- Check that routers are registered in `web/main.py`
- Verify CORS settings allow frontend access

---

## WebSocket Integration (Future Enhancement)

Currently, all panels use polling (5-30s intervals). For real-time updates, consider:

1. **WebSocket endpoints exist:**
   - `/ws/agents` - Agent outputs
   - `/ws/system` - System events
   - `/ws/prediction` - Prediction market updates

2. **Integration pattern:**
```tsx
useEffect(() => {
  const ws = new WebSocket('ws://localhost:8000/ws/agents');
  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    // Update state
  };
  return () => ws.close();
}, []);
```

---

## Styling Guidelines

All components follow the MERID design system:

- **Background:** `bg-slate-800/50` with `border-slate-700/50`
- **Text:** White primary, `text-gray-400` secondary
- **Accent Colors:**
  - Green: Success, bullish, positive
  - Red: Error, bearish, negative
  - Blue: Info, neutral
  - Purple: Agent/AI-related
  - Yellow: Warning, attention

- **Spacing:** Consistent `gap-4` or `gap-6` for grids
- **Rounded Corners:** `rounded-lg` for cards
- **Hover States:** `hover:bg-slate-700/30` for interactive elements

---

## Performance Considerations

1. **Polling Intervals:**
   - Reflection: 30s (low frequency data)
   - Consensus: 5s (high frequency during active voting)
   - Drift: 30s (moderate frequency)

2. **Data Limits:**
   - Keep API responses under 100 items by default
   - Use pagination for historical data
   - Implement virtual scrolling for large lists

3. **Error Handling:**
   - All components have fallback mock data
   - Error states clearly displayed to users
   - Automatic retry on transient failures

---

## Testing

### Manual Testing Checklist

- [ ] Component renders without errors
- [ ] Loading state displays correctly
- [ ] Error state displays with fallback data
- [ ] Data refreshes on interval
- [ ] Manual refresh button works
- [ ] Responsive on mobile/tablet/desktop
- [ ] Accessibility: keyboard navigation works
- [ ] Accessibility: screen reader compatible

### API Testing

Use the FastAPI docs at `http://localhost:8000/docs` to test endpoints directly.

---

## Troubleshooting

### Component shows "Using fallback data"
- Check API endpoint is accessible
- Verify backend service is running
- Check browser console for CORS errors

### Data not updating
- Verify polling interval is active
- Check WebSocket connection if using real-time
- Ensure backend aggregators are started

### Performance issues
- Reduce polling frequency
- Implement data pagination
- Use React.memo() for expensive renders

---

## Future Enhancements

1. **Real-time WebSocket integration** for all panels
2. **Historical data visualization** with charts
3. **Export functionality** for metrics and reports
4. **Customizable dashboards** with drag-and-drop
5. **Alert system** for significant events
6. **Mobile-optimized views**
7. **Dark/light theme toggle**
8. **Keyboard shortcuts** for power users

---

## Support

For issues or questions:
- Check logs in `logs/` directory
- Review API documentation at `/docs`
- Verify component props match expected types
