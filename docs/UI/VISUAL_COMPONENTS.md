# MERID UI Visual Components

> **Primary Location**: `web/react/src/components/charts/`  
> **Components**: `AgentOpinionChart.tsx`, `MarketHeatmap.tsx`

---

## Overview

These React components provide real-time visualization of the MERID swarm's activity. They consume data from Kafka topics (via WebSocket bridge) and render operator-friendly displays.

### Design Principles

1. **Real-time updates** – Components reflect live swarm state
2. **Minimal latency** – Optimized rendering, no unnecessary re-renders
3. **Operator-focused** – Quick anomaly detection, clear status indicators
4. **Consistent styling** – Tailwind CSS, slate color palette

---

## AgentOpinionChart

Visualizes agent opinions from `agent.opinions.*` topics for a specific symbol.

### File

`web/react/src/components/charts/AgentOpinionChart.tsx`

### Props

| Prop | Type | Required | Description |
|------|------|----------|-------------|
| `symbol` | `string` | ✅ | Trading symbol (e.g., "BTC/USD") |
| `opinions` | `AgentOpinion[]` | ✅ | Array of agent opinions |
| `maxItems` | `number` | ❌ | Max opinions per agent (default: 20) |
| `showRationale` | `boolean` | ❌ | Show reasoning on click (default: false) |
| `onRefresh` | `() => void` | ❌ | Callback for refresh button |

### AgentOpinion Interface

```typescript
interface AgentOpinion {
  opinion_id: string;
  agent_id: string;
  agent_role: string;
  symbol: string;
  stance: 'strong_bull' | 'bull' | 'neutral' | 'bear' | 'strong_bear';
  score: number;      // -1.0 to 1.0
  confidence: number; // 0.0 to 1.0
  timestamp: number;  // Unix timestamp
  rationale?: string;
}
```

### Usage

```tsx
import AgentOpinionChart from '@/components/charts/AgentOpinionChart';

function TradingDashboard() {
  const { opinions } = useKafkaStream('agent.opinions.BTC-USD');
  
  return (
    <AgentOpinionChart
      symbol="BTC/USD"
      opinions={opinions}
      maxItems={20}
      showRationale={true}
      onRefresh={() => refetch()}
    />
  );
}
```

### Visual Elements

1. **Consensus Summary** – Aggregated score from recent opinions (last 5 min)
2. **Score Bar** – Visual indicator from bearish (left) to bullish (right)
3. **Agent List** – Each agent with latest stance, score, confidence
4. **Role Colors** – Color-coded borders by agent role
5. **Sparkline** – Mini history of last 5 scores per agent

### Role Colors

| Role | Border Color |
|------|--------------|
| `bull_analyst` | Green |
| `bear_analyst` | Red |
| `risk_manager` | Yellow |
| `sentiment_analyst` | Purple |
| `technical_analyst` | Blue |
| `execution_agent` | Cyan |

### Stance Colors

| Stance | Style |
|--------|-------|
| `strong_bull` | Green text, green bg |
| `bull` | Light green |
| `neutral` | Gray |
| `bear` | Light red |
| `strong_bear` | Red text, red bg |

### Kafka Topic

Consumes from: `agent.opinions.*`

Schema (from `schemas/events.py`):
```python
AgentOpinionEvent(
    event_type="agent.opinion",
    agent_id="bull_primary",
    agent_role="bull_analyst",
    symbol="BTC/USD",
    stance="bull",
    score=0.7,
    confidence=0.85,
    rationale="Strong momentum...",
)
```

---

## MarketHeatmap

Displays market-wide performance as a color-coded grid.

### File

`web/react/src/components/charts/MarketHeatmap.tsx`

### Props

| Prop | Type | Required | Description |
|------|------|----------|-------------|
| `data` | `MarketData[]` | ✅ | Array of market data |
| `metric` | `MetricType` | ✅ | Metric to visualize |
| `title` | `string` | ❌ | Chart title (default: "Market Heatmap") |
| `columns` | `number` | ❌ | Grid columns (default: 4) |

### MetricType

```typescript
type MetricType = 'change_1h' | 'change_24h' | 'volatility' | 'sentiment';
```

### MarketData Interface

```typescript
interface MarketData {
  symbol: string;
  price: number;
  change_1h: number;
  change_24h: number;
  volume_24h: number;
  volatility?: number;
  sentiment?: number;
}
```

### Usage

```tsx
import MarketHeatmap from '@/components/charts/MarketHeatmap';

function MarketOverview() {
  const { data } = useMarketData();
  
  return (
    <MarketHeatmap
      data={data}
      metric="change_24h"
      title="24H Performance"
      columns={5}
    />
  );
}
```

### Color Scales

**Price Changes** (`change_1h`, `change_24h`):

| Range | Color |
|-------|-------|
| > +5% | Bright green |
| +2% to +5% | Green |
| +0.5% to +2% | Light green |
| 0% to +0.5% | Faded green |
| -0.5% to 0% | Faded red |
| -2% to -0.5% | Light red |
| -5% to -2% | Red |
| < -5% | Bright red |

**Volatility**:

| Range | Color |
|-------|-------|
| > 10% | Dark purple |
| 5-10% | Purple |
| 2-5% | Light purple |
| < 2% | Faded purple |

**Sentiment**:

| Range | Color |
|-------|-------|
| > 0.5 | Green |
| 0.2 to 0.5 | Light green |
| -0.2 to 0.2 | Gray |
| -0.5 to -0.2 | Light red |
| < -0.5 | Red |

### Visual Elements

1. **Grid Layout** – Configurable columns, auto-sized cells
2. **Symbol Label** – Truncated symbol name
3. **Price Display** – Formatted price (k suffix for thousands)
4. **Metric Value** – Formatted based on metric type
5. **Legend** – Color scale explanation at bottom

### Data Source

Typically from `prices.spot.*` topics combined with sentiment data:

```python
# From prices topic
PriceEvent(symbol="BTC/USD", last=50000, volume_24h=15000)

# Combined with sentiment
SentimentEvent(symbol="BTC", sentiment_score=0.65)
```

---

## Integration with WebSocket

Both components are designed to work with the Kafka WebSocket bridge:

```tsx
import { useKafkaStream } from '@/hooks/useKafkaStream';

function Dashboard() {
  // Subscribe to agent opinions
  const { events: opinions } = useKafkaStream('/ws/kafka', {
    topics: ['agent.opinions.*'],
    maxEvents: 100,
  });
  
  // Subscribe to prices
  const { events: prices } = useKafkaStream('/ws/kafka', {
    topics: ['prices.spot.*'],
    maxEvents: 50,
  });
  
  return (
    <div className="grid grid-cols-2 gap-4">
      <AgentOpinionChart symbol="BTC/USD" opinions={opinions} />
      <MarketHeatmap data={prices} metric="change_24h" />
    </div>
  );
}
```

---

## Update Cadence

| Component | Update Frequency | Source |
|-----------|------------------|--------|
| AgentOpinionChart | Per opinion (real-time) | `agent.opinions.*` |
| MarketHeatmap | Per price tick or 1s batched | `prices.spot.*` |

---

## Performance Considerations

### AgentOpinionChart

- Uses `useMemo` to group opinions by agent
- Limits displayed opinions via `maxItems`
- Lazy-renders rationale (only when expanded)

### MarketHeatmap

- Uses `useMemo` to sort data by metric value
- Fixed grid layout (no dynamic resizing)
- Hover effects are CSS-only (no JS)

---

## Accessibility

Both components include:

- `title` and `aria-label` on interactive elements
- Semantic HTML structure
- Color contrast ratios meeting WCAG AA

---

## Styling

Components use Tailwind CSS with MERID's slate color palette:

```css
/* Base container */
bg-slate-900/50 rounded-xl border border-slate-700/50

/* Cards/cells */
bg-slate-800/30 hover:bg-slate-800/50

/* Text */
text-white       /* Primary */
text-slate-400   /* Secondary */
text-slate-500   /* Muted */
```

---

## Extending Components

To add new visualization components:

1. Create in `web/react/src/components/charts/`
2. Follow same prop patterns (data array, optional title)
3. Use existing color utilities
4. Subscribe to appropriate Kafka topics
5. Document in this file

---

*See also*: `docs/PROGRESS_CHECKPOINT_2026-02-05.md` for full module context.
