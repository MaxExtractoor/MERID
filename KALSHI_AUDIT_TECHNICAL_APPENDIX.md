# MERID Kalshi Integration - Technical Appendix

**Companion document to:** KALSHI_INTEGRATION_DEEP_AUDIT_REPORT.md

---

## Appendix A: Detailed Architecture Diagrams

### A.1 Complete Trading Lifecycle Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Phase 1: DISCOVER                                │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐             │
│  │ Kalshi REST  │───▶│   Market     │───▶│   Venue      │             │
│  │   API        │    │   Catalog    │    │   Adapter    │             │
│  │ GET /markets │    │ (5min cache) │    │ (MERID fmt)  │             │
│  └──────────────┘    └──────────────┘    └──────────────┘             │
└─────────────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                        Phase 2: ANALYZE                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐             │
│  │ Sentiment    │───▶│  Feature     │───▶│  Prediction  │             │
│  │   Context    │    │ Engineering  │    │  Market      │             │
│  │ (fear/greed) │    │ (signals)    │    │  Model       │             │
│  └──────────────┘    └──────────────┘    └──────────────┘             │
└─────────────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                       Phase 3: CONSENSUS                                │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐             │
│  │   Agent 1    │───▶│    Swarm     │───▶│  Consensus   │             │
│  │  Proposal    │    │  Consensus   │    │    View      │             │
│  │   (vote)     │    │ Aggregator   │    │ (decision)   │             │
│  ├──────────────┤    │              │    └──────────────┘             │
│  │   Agent 2    │───▶│ • Weighted   │                                  │
│  │  Proposal    │    │   voting     │                                  │
│  ├──────────────┤    │ • Track      │                                  │
│  │   Agent N    │───▶│   record     │                                  │
│  └──────────────┘    │   weighting  │                                  │
│                      └──────────────┘                                  │
└─────────────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                         Phase 4: SIZE                                   │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐             │
│  │  Fractional  │───▶│     CQI      │───▶│   Domain     │             │
│  │    Kelly     │    │   Throttle   │    │    Caps      │             │
│  │  (base size) │    │ (0.35-0.65)  │    │ ($5k/day)    │             │
│  └──────────────┘    └──────────────┘    └──────────────┘             │
└─────────────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                       Phase 5: EXECUTE                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐             │
│  │ Trade Router │───▶│   Circuit    │───▶│   Kalshi     │             │
│  │ (risk gate)  │    │   Breaker    │    │ REST Client  │             │
│  │              │    │ (5 fail)     │    │ POST /orders │             │
│  └──────────────┘    └──────────────┘    └──────────────┘             │
│                                                   ↓                     │
│                                            ┌──────────────┐             │
│                                            │   Order      │             │
│                                            │   Manager    │             │
│                                            │ (lifecycle)  │             │
│                                            └──────────────┘             │
└─────────────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                       Phase 6: MONITOR                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐             │
│  │  WebSocket   │───▶│   Position   │───▶│    Trade     │             │
│  │  (fills)     │    │    Cache     │    │  Analytics   │             │
│  │              │    │ (30s poll)   │    │  (PnL calc)  │             │
│  └──────────────┘    └──────────────┘    └──────────────┘             │
│                                                   ↓                     │
│                                            ┌──────────────┐             │
│                                            │ Reconciler   │             │
│                                            │ (hourly)     │             │
│                                            └──────────────┘             │
└─────────────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                       Phase 7: PROMOTE                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐             │
│  │   Paper      │───▶│   Shadow     │───▶│     LIVE     │             │
│  │ (200 trades) │    │ (100 trades) │    │ (max 3)      │             │
│  │  PF ≥ 1.4    │    │  PF stable   │    │ continuous   │             │
│  └──────────────┘    └──────────────┘    │  rollback    │             │
│                                            └──────────────┘             │
│         ↑                                          ↓                     │
│         └──────────────────────────────────────────┘                    │
│                    (rollback on PF < 0.9)                               │
└─────────────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                       Phase 8: PROTECT                                  │
│  ┌──────────────────────────────────────────────────────┐              │
│  │               6-Layer Safety Stack                   │              │
│  │  Layer 1: Global Kill Switch (ALL domains)          │              │
│  │  Layer 2: Per-Domain Kill Switch (single domain)    │              │
│  │  Layer 3: CQI Throttle (quality-based scaling)      │              │
│  │  Layer 4: Domain Caps ($5k/day per domain)          │              │
│  │  Layer 5: GlobalRiskManager (7 checks)              │              │
│  │  Layer 6: Drawdown Governor (auto-liquidate)        │              │
│  └──────────────────────────────────────────────────────┘              │
└─────────────────────────────────────────────────────────────────────────┘
```

### A.2 Agent Coordination Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          AgentGrid (25+ agents)                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  BTC Agents:                                                            │
│  ┌─────────────┬─────────────┬─────────────┬─────────────┐            │
│  │ BTC_15M     │ BTC_HOURLY  │ BTC_DAILY   │ BTC_WEEKLY  │            │
│  │ 20 ord/win  │ 15 ord/win  │ 10 ord/win  │ 5 ord/win   │            │
│  │ $500 max    │ $1000 max   │ $2000 max   │ $3000 max   │            │
│  └─────────────┴─────────────┴─────────────┴─────────────┘            │
│                                                                         │
│  ETH Agents: (similar structure)                                       │
│  SOL Agents: (similar, 30% smaller sizes)                              │
│  XRP/DOGE Agents: (similar)                                            │
│                                                                         │
│  Specialty Agents:                                                     │
│  ┌─────────────┬─────────────┬─────────────┬─────────────┐            │
│  │ CRYPTO_15M  │ KALSHI_ARB  │ MACRO_DIR   │ FINANCIALS  │            │
│  │ _MM         │ _SCANNER    │ _ECTIONAL   │ _DIRECTIONAL│            │
│  │ (maker)     │ (cross-cat) │ (econ data) │ (indices)   │            │
│  └─────────────┴─────────────┴─────────────┴─────────────┘            │
│                                                                         │
│  Sentiment Agents:                                                     │
│  ┌─────────────┬─────────────┬─────────────┐                          │
│  │ CONTRARIAN  │ REGIME      │ VOL         │                          │
│  │             │ _SWITCH     │ _BREAKOUT   │                          │
│  └─────────────┴─────────────┴─────────────┘                          │
│                                                                         │
│  Risk Supervisor:                                                      │
│  ┌─────────────────────────────────────────┐                          │
│  │       PortfolioRiskAgent                │                          │
│  │  • Max total: $50k notional             │                          │
│  │  • Max per asset: $15k                  │                          │
│  │  • Max daily loss: $5k                  │                          │
│  │  • Max open markets: 200                │                          │
│  └─────────────────────────────────────────┘                          │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
                              ↓
          ┌───────────────────────────────────┐
          │   Market Catalog (shared state)   │
          │   • 2000+ active markets          │
          │   • Refreshed every 5 minutes     │
          │   • Indexed by asset/timeframe    │
          └───────────────────────────────────┘
                              ↓
          ┌───────────────────────────────────┐
          │  SentimentContext (shared state)  │
          │   • Fear/Greed: 0-100             │
          │   • Social sentiment              │
          │   • News sentiment                │
          │   • Kalshi market mood            │
          │   • Volatility regime             │
          └───────────────────────────────────┘
                              ↓
          ┌───────────────────────────────────┐
          │  SwarmConsensusAggregator         │
          │   • Collects agent proposals      │
          │   • Weighted voting               │
          │   • Confidence scoring            │
          │   • Size band recommendation      │
          └───────────────────────────────────┘
```

---

## Appendix B: Key Metrics & Observability

### B.1 Critical Metrics Definitions

**Market Discovery Metrics:**
```python
# Catalog refresh performance
kalshi_catalog_refresh_latency_ms {p50, p95, p99}
  # Target: p95 < 3000ms, p99 < 5000ms

kalshi_catalog_refresh_timeout_total
  # Target: 0 (alert on any timeout)

kalshi_catalog_market_count {category, asset, timeframe}
  # Track market availability over time

kalshi_catalog_uncategorized_markets_total
  # Target: < 5% of total markets

kalshi_catalog_new_markets_discovered_total
  # Rate of new market detection

# WebSocket health
kalshi_ws_lag_ms {p50, p95, p99}
  # Target: p99 < 500ms

kalshi_ws_sequence_gaps_total
  # Target: 0 (alert on any gap)

kalshi_ws_reconnects_total
  # Target: < 1 per hour
```

**Consensus Metrics:**
```python
# Proposal submission
kalshi_consensus_proposals_submitted_total {agent_id, asset, timeframe}
  # Track agent participation

kalshi_consensus_formation_latency_ms {p50, p95, p99}
  # Target: p95 < 2000ms

kalshi_consensus_herding_detected_total
  # Target: < 5% of consensus formations

kalshi_consensus_confidence_score {asset, timeframe}
  # Track confidence distribution (0-1)

kalshi_consensus_direction_breakdown {asset, timeframe, direction}
  # yes/no/neutral vote distribution

kalshi_consensus_disagreement_flags_total {asset, timeframe, reason}
  # Track sources of disagreement
```

**Execution Metrics:**
```python
# Order placement
kalshi_orders_submitted_total {agent_id, venue, domain}
  # Total orders submitted

kalshi_orders_filled_total {agent_id, venue, domain}
  # Successfully filled orders

kalshi_orders_rejected_total {agent_id, venue, domain, reason}
  # Rejected orders by reason

kalshi_order_fill_rate_pct {agent_id, venue}
  # Target: > 70%

# Latency
kalshi_order_placement_latency_ms {p50, p95, p99}
  # Target: p95 < 1000ms, p99 < 2000ms

kalshi_order_fill_latency_ms {p50, p95, p99}
  # Time from submission to fill

# Slippage
kalshi_order_slippage_bps {p50, p95, p99}
  # Target: p95 < 50 bps, p99 < 100 bps

# Circuit breaker
kalshi_circuit_breaker_state {venue}
  # Values: 0=closed (normal), 1=open (failing)

kalshi_circuit_breaker_opens_total {venue}
  # Target: < 1 per day

# Rate limiting
kalshi_rate_limit_429_errors_total {endpoint}
  # Target: 0

kalshi_rate_limiter_tokens_available {type}
  # type=read/write, monitor headroom
```

**Risk & Safety Metrics:**
```python
# CQI tracking
kalshi_cqi_score {domain}
  # Code Quality Index (0-1)
  # Target: > 0.65 for full execution

kalshi_cqi_throttle_pct {domain}
  # Actual size scaling (0-1)

# Domain caps
kalshi_domain_notional_used_usd {domain}
  # Daily notional used

kalshi_domain_notional_remaining_usd {domain}
  # Remaining capacity

kalshi_domain_cap_breaches_total {domain}
  # Target: 0

# Kill switch
kalshi_kill_switch_active {level}
  # level=global/domain
  # Values: 0=inactive, 1=active

kalshi_kill_switch_activations_total {level, reason}
  # Track activation frequency

# Position risk
kalshi_positions_open_total {agent_id, asset}
  # Open position count

kalshi_notional_exposure_usd {agent_id, domain}
  # Total exposure by agent

kalshi_unrealized_pnl_usd {agent_id, domain}
  # Mark-to-market P&L

kalshi_drawdown_pct {agent_id, portfolio}
  # Current drawdown %
  # Target: < 15%
```

**Promotion & Performance Metrics:**
```python
# Agent modes
kalshi_agents_by_mode {mode}
  # mode=PAPER/SHADOW/LIVE

kalshi_agent_promotions_total {agent_id, from_mode, to_mode}
  # Promotion events

kalshi_agent_rollbacks_total {agent_id, from_mode, reason}
  # Rollback events

# Performance
kalshi_agent_profit_factor {agent_id}
  # Target: > 1.4 for PAPER→SHADOW, > 1.0 for LIVE

kalshi_agent_sharpe_ratio {agent_id}
  # Target: > 0.5

kalshi_agent_win_rate_pct {agent_id}
  # Target: > 55%

kalshi_agent_brier_score {agent_id}
  # Calibration metric (lower is better)
  # Target: < 0.2

kalshi_agent_error_rate_pct {agent_id}
  # Target: < 20%
```

### B.2 Prometheus Alert Rules

```yaml
# File: monitoring/alert_rules/kalshi.yml

groups:
  - name: kalshi_discovery
    interval: 30s
    rules:
      - alert: KalshiCatalogRefreshSlow
        expr: kalshi_catalog_refresh_latency_ms{quantile="0.95"} > 5000
        for: 5m
        labels:
          severity: warning
          phase: discover
        annotations:
          summary: "Kalshi catalog refresh is slow"
          description: "P95 latency {{ $value }}ms exceeds 5s threshold"

      - alert: KalshiCatalogRefreshTimeout
        expr: increase(kalshi_catalog_refresh_timeout_total[5m]) > 0
        labels:
          severity: critical
          phase: discover
        annotations:
          summary: "Kalshi catalog refresh timeout"
          description: "Catalog refresh timed out {{ $value }} times in last 5min"

      - alert: KalshiWebSocketLagHigh
        expr: kalshi_ws_lag_ms{quantile="0.99"} > 1000
        for: 2m
        labels:
          severity: warning
          phase: monitor
        annotations:
          summary: "Kalshi WebSocket lag high"
          description: "P99 lag {{ $value }}ms exceeds 1s threshold"

  - name: kalshi_execution
    interval: 15s
    rules:
      - alert: KalshiFillRateLow
        expr: kalshi_order_fill_rate_pct < 50
        for: 5m
        labels:
          severity: warning
          phase: execute
        annotations:
          summary: "Kalshi fill rate low for {{ $labels.agent_id }}"
          description: "Fill rate {{ $value }}% below 50% threshold"

      - alert: KalshiCircuitBreakerOpen
        expr: kalshi_circuit_breaker_state == 1
        labels:
          severity: critical
          phase: execute
        annotations:
          summary: "Kalshi circuit breaker open for {{ $labels.venue }}"
          description: "Circuit breaker triggered, trading halted"

      - alert: KalshiRateLimitErrors
        expr: increase(kalshi_rate_limit_429_errors_total[5m]) > 3
        labels:
          severity: critical
          phase: execute
        annotations:
          summary: "Kalshi rate limit errors detected"
          description: "{{ $value }} 429 errors in last 5min on {{ $labels.endpoint }}"

  - name: kalshi_risk
    interval: 30s
    rules:
      - alert: KalshiCQILow
        expr: kalshi_cqi_score < 0.35
        for: 2m
        labels:
          severity: critical
          phase: protect
        annotations:
          summary: "CQI score critical for {{ $labels.domain }}"
          description: "CQI {{ $value }} below 0.35, trading blocked"

      - alert: KalshiDrawdownHigh
        expr: kalshi_drawdown_pct > 15
        labels:
          severity: critical
          phase: protect
        annotations:
          summary: "Drawdown high for {{ $labels.agent_id }}"
          description: "Drawdown {{ $value }}% exceeds 15% threshold"

      - alert: KalshiKillSwitchActive
        expr: kalshi_kill_switch_active == 1
        labels:
          severity: critical
          phase: protect
        annotations:
          summary: "Kill switch active: {{ $labels.level }}"
          description: "Emergency stop triggered, all trading halted"

      - alert: KalshiDomainCapBreach
        expr: increase(kalshi_domain_cap_breaches_total[5m]) > 0
        labels:
          severity: critical
          phase: protect
        annotations:
          summary: "Domain cap breached for {{ $labels.domain }}"
          description: "{{ $value }} cap breaches in last 5min"
```

### B.3 Grafana Dashboard JSON (Excerpt)

```json
{
  "dashboard": {
    "title": "Kalshi Integration - Execution Health",
    "uid": "kalshi-execution",
    "panels": [
      {
        "title": "Order Fill Rate",
        "type": "graph",
        "targets": [
          {
            "expr": "kalshi_order_fill_rate_pct",
            "legendFormat": "{{ agent_id }}"
          }
        ],
        "yaxes": [
          {
            "format": "percent",
            "min": 0,
            "max": 100
          }
        ],
        "thresholds": [
          {
            "value": 70,
            "colorMode": "critical"
          }
        ]
      },
      {
        "title": "Order Placement Latency",
        "type": "graph",
        "targets": [
          {
            "expr": "kalshi_order_placement_latency_ms{quantile=\"0.50\"}",
            "legendFormat": "P50"
          },
          {
            "expr": "kalshi_order_placement_latency_ms{quantile=\"0.95\"}",
            "legendFormat": "P95"
          },
          {
            "expr": "kalshi_order_placement_latency_ms{quantile=\"0.99\"}",
            "legendFormat": "P99"
          }
        ],
        "yaxes": [
          {
            "format": "ms",
            "logBase": 10
          }
        ],
        "thresholds": [
          {
            "value": 1000,
            "colorMode": "critical",
            "line": true
          }
        ]
      },
      {
        "title": "Circuit Breaker State",
        "type": "stat",
        "targets": [
          {
            "expr": "kalshi_circuit_breaker_state"
          }
        ],
        "mappings": [
          {
            "value": 0,
            "text": "CLOSED",
            "color": "green"
          },
          {
            "value": 1,
            "text": "OPEN",
            "color": "red"
          }
        ]
      },
      {
        "title": "CQI Score",
        "type": "gauge",
        "targets": [
          {
            "expr": "kalshi_cqi_score"
          }
        ],
        "thresholds": [
          {
            "value": 0.35,
            "color": "red"
          },
          {
            "value": 0.65,
            "color": "yellow"
          },
          {
            "value": 1.0,
            "color": "green"
          }
        ]
      }
    ]
  }
}
```

---

## Appendix C: Code Examples for Remediations

### C.1 Schema Validation (Finding D-001)

```python
# File: merid/event_venues/kalshi/models.py

from pydantic import BaseModel, validator, Field
from datetime import datetime, timezone
from typing import Optional

class KalshiMarketSchema(BaseModel):
    """Validated schema for Kalshi market data."""

    market_id: str = Field(..., min_length=1)
    event_ticker: str = Field(..., min_length=1)
    series_ticker: Optional[str] = None
    question: str = Field(..., min_length=1)
    description: Optional[str] = None
    category: Optional[str] = None
    end_date: datetime
    volume: float = Field(..., ge=0.0)
    active: bool = True

    @validator('market_id')
    def validate_market_id(cls, v):
        if not v or len(v) < 3:
            raise ValueError(f"Invalid market_id: {v}")
        return v

    @validator('end_date')
    def validate_end_date(cls, v):
        if v is None:
            raise ValueError("end_date cannot be None")
        now = datetime.now(timezone.utc)
        if v < now:
            raise ValueError(f"end_date {v} is in the past")
        return v

    @validator('volume')
    def validate_volume(cls, v):
        if v < 0:
            raise ValueError(f"volume cannot be negative: {v}")
        return v

    class Config:
        extra = "allow"  # Allow extra fields from API


# In market_catalog.py:

async def refresh(self) -> int:
    """Fetch markets with schema validation."""
    async with self._lock:
        try:
            result = await self._client.list_markets_result(...)
            if not result.success:
                return len(self._markets)

            raw_markets = result.data
            validated_markets = []
            invalid_count = 0

            for raw in raw_markets:
                try:
                    # Validate schema
                    validated = KalshiMarketSchema(**raw)
                    validated_markets.append(validated)
                except ValidationError as e:
                    invalid_count += 1
                    logger.warning(
                        f"Skipping malformed market {raw.get('market_id', 'UNKNOWN')}: {e}"
                    )
                    self._emit_metric(
                        "kalshi_catalog_invalid_markets_total",
                        1,
                        tags={"market_id": raw.get("market_id", "UNKNOWN")}
                    )

            if invalid_count > 0:
                logger.warning(
                    f"Filtered {invalid_count} invalid markets out of {len(raw_markets)}"
                )

            # Continue with enrichment...
            enriched = [self._enrich(m, now) for m in validated_markets]

        except Exception as exc:
            logger.error(f"Catalog refresh failed: {exc}")
            return len(self._markets)
```

### C.2 Anti-Herding Protection (Finding C-001)

```python
# File: merid/swarm/consensus_aggregator.py

def _aggregate_proposals(
    self,
    asset: str,
    timeframe: str,
    proposals: List[AgentProposal],
) -> ConsensusView:
    """Aggregate proposals with anti-herding protection."""

    # Detect herding
    herding_detected, herding_score = self._detect_herding(proposals)

    if herding_detected:
        logger.warning(
            f"Herding detected: {len(proposals)} agents, "
            f"herding_score={herding_score:.2f}"
        )

    # Compute base consensus
    consensus = self._compute_weighted_consensus(asset, timeframe, proposals)

    # Apply herding penalty
    if herding_detected:
        confidence_penalty = 1.0 - (herding_score * 0.5)  # Max 50% penalty
        consensus.consensus_confidence *= confidence_penalty
        consensus.disagreement_flags.append(
            f"herding_detected (score={herding_score:.2f}, "
            f"penalty={1-confidence_penalty:.2f})"
        )

        # Reduce size band
        if consensus.size_band == "large":
            consensus.size_band = "base"
        elif consensus.size_band == "base":
            consensus.size_band = "small"

        # Emit metric
        self._emit_metric(
            "kalshi_consensus_herding_detected_total",
            1,
            tags={"asset": asset, "timeframe": timeframe}
        )

    return consensus


def _detect_herding(self, proposals: List[AgentProposal]) -> tuple[bool, float]:
    """Detect if agents are herding (converging to same prediction).

    Returns:
        (herding_detected, herding_score) where herding_score is 0-1
        (1.0 = perfect herding, 0.0 = maximum diversity)
    """
    if len(proposals) < 3:
        return False, 0.0

    # Check probability convergence
    probs = [p.probability for p in proposals]
    prob_range = max(probs) - min(probs)
    prob_std = statistics.stdev(probs) if len(probs) > 1 else 0.0

    # Check direction convergence
    directions = [p.direction for p in proposals]
    direction_entropy = self._compute_entropy(directions)

    # Check agent archetype diversity
    archetypes = [p.agent_archetype for p in proposals]
    archetype_entropy = self._compute_entropy(archetypes)

    # Herding score components
    prob_convergence = 1.0 - min(prob_range / 0.5, 1.0)  # 0.5 = healthy spread
    prob_std_convergence = 1.0 - min(prob_std / 0.15, 1.0)  # 0.15 = healthy std
    direction_convergence = 1.0 - direction_entropy  # Low entropy = herding
    archetype_convergence = 1.0 - archetype_entropy

    # Overall herding score (weighted average)
    herding_score = (
        0.30 * prob_convergence +
        0.30 * prob_std_convergence +
        0.25 * direction_convergence +
        0.15 * archetype_convergence
    )

    # Threshold for detection
    herding_detected = herding_score > 0.70

    return herding_detected, herding_score


def _compute_entropy(self, values: List[str]) -> float:
    """Compute normalized Shannon entropy (0-1)."""
    from collections import Counter
    import math

    counts = Counter(values)
    total = len(values)

    if total <= 1:
        return 0.0

    entropy = -sum(
        (count / total) * math.log2(count / total)
        for count in counts.values()
    )

    # Normalize by max entropy (log2(n))
    max_entropy = math.log2(len(counts)) if len(counts) > 1 else 1.0
    normalized_entropy = entropy / max_entropy if max_entropy > 0 else 0.0

    return normalized_entropy
```

### C.3 Idempotency Protection (Finding E-002)

```python
# File: merid/event_venues/kalshi/client.py

import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Set

class KalshiVenueClient(EventVenueClient):
    def __init__(self, config: Optional[KalshiConfig] = None):
        # ... existing init ...

        # Idempotency tracking
        self._inflight_orders: Set[str] = set()
        self._completed_orders: Dict[str, PlacedOrder] = {}
        self._order_ttl = timedelta(hours=24)
        self._order_cleanup_task: Optional[asyncio.Task] = None

    async def connect(self) -> None:
        """Initialize client and start cleanup task."""
        await self._ensure_client()

        # Start idempotency cache cleanup
        if self._order_cleanup_task is None:
            self._order_cleanup_task = asyncio.create_task(
                self._cleanup_completed_orders()
            )

    async def place_order(self, order: VenueOrder) -> PlacedOrder:
        """Place order with idempotency protection."""

        # Generate or use client_order_id
        client_order_id = order.client_order_id or str(uuid.uuid4())

        # Check if order already in flight
        if client_order_id in self._inflight_orders:
            raise RuntimeError(
                f"Order {client_order_id} already in flight. "
                f"Wait for completion or use different ID."
            )

        # Check if order already completed
        if client_order_id in self._completed_orders:
            completed = self._completed_orders[client_order_id]
            logger.info(
                f"Order {client_order_id} already completed, returning cached result"
            )
            return completed

        # Mark as in flight
        self._inflight_orders.add(client_order_id)

        try:
            # Place order
            placed = await self._place_order_internal(order, client_order_id)

            # Cache result
            self._completed_orders[client_order_id] = placed

            logger.debug(
                f"Order {client_order_id} placed successfully: {placed.order_id}"
            )

            return placed

        except Exception as exc:
            logger.error(f"Order {client_order_id} failed: {exc}")

            # On timeout, check if order actually placed
            if isinstance(exc, asyncio.TimeoutError):
                logger.warning(
                    f"Order {client_order_id} timed out, checking status..."
                )

                # Query Kalshi to check if order exists
                try:
                    existing = await self._check_order_status(client_order_id)
                    if existing:
                        logger.info(
                            f"Order {client_order_id} was placed despite timeout"
                        )
                        self._completed_orders[client_order_id] = existing
                        return existing
                except Exception as check_exc:
                    logger.error(
                        f"Failed to check order status: {check_exc}"
                    )

            raise

        finally:
            # Remove from in-flight
            self._inflight_orders.discard(client_order_id)

    async def _place_order_internal(
        self,
        order: VenueOrder,
        client_order_id: str
    ) -> PlacedOrder:
        """Internal order placement with circuit breaker."""
        await self._ensure_client()
        await self._rate_limiter.acquire(is_write=True)

        url = f"{self.config.base_url}/trade-api/v2/orders"

        payload = {
            "ticker": order.market_id,
            "client_order_id": client_order_id,
            "order_type": "limit",
            "action": "buy" if order.side.lower() == "buy" else "sell",
            "side": order.outcome_id or "yes",
            "price": int(float(order.price) * 100),  # Convert to cents
            "count": int(float(order.size)),
        }

        async def _execute():
            response = await self._http_client.post(url, json=payload)
            response.raise_for_status()
            return response.json()

        result = await self._circuit_breaker.call(_execute)

        # Parse response into PlacedOrder
        return self._parse_placed_order(result.data)

    async def _check_order_status(self, client_order_id: str) -> Optional[PlacedOrder]:
        """Check if an order exists by client_order_id."""
        try:
            url = f"{self.config.base_url}/trade-api/v2/orders"
            params = {"client_order_id": client_order_id}

            response = await self._http_client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            if data and "orders" in data and len(data["orders"]) > 0:
                return self._parse_placed_order(data["orders"][0])

            return None
        except Exception as exc:
            logger.error(f"Failed to check order status: {exc}")
            return None

    async def _cleanup_completed_orders(self):
        """Periodic cleanup of old completed orders."""
        while True:
            try:
                await asyncio.sleep(3600)  # Run every hour

                now = datetime.now(timezone.utc)
                expired_keys = []

                for client_order_id, placed_order in self._completed_orders.items():
                    # Check if order is older than TTL
                    # (Assume PlacedOrder has created_at timestamp)
                    if hasattr(placed_order, 'created_at'):
                        age = now - placed_order.created_at
                        if age > self._order_ttl:
                            expired_keys.append(client_order_id)

                # Remove expired orders
                for key in expired_keys:
                    del self._completed_orders[key]

                if expired_keys:
                    logger.debug(
                        f"Cleaned up {len(expired_keys)} expired order records"
                    )

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Order cleanup error: {exc}")
```

---

## Appendix D: Testing Strategy

### D.1 Unit Test Examples

```python
# File: tests/event_venues/kalshi/test_market_catalog.py

import pytest
from datetime import datetime, timedelta, timezone
from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
from merid.event_venues.kalshi.models import KalshiMarketSchema
from pydantic import ValidationError


class TestSchemaValidation:
    """Test schema validation for malformed API data."""

    def test_valid_market_passes_validation(self):
        """Valid market data should pass schema validation."""
        data = {
            "market_id": "KXBTC-25DEC-T55000",
            "event_ticker": "KXBTC",
            "question": "Will BTC close above $55k on Dec 25?",
            "end_date": datetime.now(timezone.utc) + timedelta(days=1),
            "volume": 1000.0,
            "active": True,
        }

        market = KalshiMarketSchema(**data)
        assert market.market_id == "KXBTC-25DEC-T55000"
        assert market.volume == 1000.0

    def test_missing_market_id_fails(self):
        """Market without ID should fail validation."""
        data = {
            "event_ticker": "KXBTC",
            "question": "Will BTC close above $55k?",
            "end_date": datetime.now(timezone.utc) + timedelta(days=1),
            "volume": 1000.0,
        }

        with pytest.raises(ValidationError) as exc_info:
            KalshiMarketSchema(**data)

        assert "market_id" in str(exc_info.value)

    def test_past_end_date_fails(self):
        """Market with past end_date should fail validation."""
        data = {
            "market_id": "KXBTC-25DEC-T55000",
            "event_ticker": "KXBTC",
            "question": "Will BTC close above $55k?",
            "end_date": datetime.now(timezone.utc) - timedelta(days=1),  # Past
            "volume": 1000.0,
        }

        with pytest.raises(ValidationError) as exc_info:
            KalshiMarketSchema(**data)

        assert "end_date" in str(exc_info.value)

    def test_negative_volume_fails(self):
        """Market with negative volume should fail validation."""
        data = {
            "market_id": "KXBTC-25DEC-T55000",
            "event_ticker": "KXBTC",
            "question": "Will BTC close above $55k?",
            "end_date": datetime.now(timezone.utc) + timedelta(days=1),
            "volume": -100.0,  # Negative
        }

        with pytest.raises(ValidationError) as exc_info:
            KalshiMarketSchema(**data)

        assert "volume" in str(exc_info.value)


class TestCatalogResilience:
    """Test catalog resilience to API failures."""

    @pytest.mark.asyncio
    async def test_catalog_returns_stale_on_api_failure(self, mock_client):
        """Catalog should return stale data on API failure."""
        catalog = KalshiMarketCatalog(client=mock_client)

        # First refresh succeeds
        mock_client.list_markets_result.return_value.success = True
        mock_client.list_markets_result.return_value.data = [
            {"market_id": "M1", "event_ticker": "KXBTC", ...}
        ]
        count1 = await catalog.refresh()
        assert count1 == 1

        # Second refresh fails
        mock_client.list_markets_result.return_value.success = False
        count2 = await catalog.refresh()
        assert count2 == 1  # Returns stale count

        # Markets still available from cache
        markets = catalog.get_all_markets()
        assert len(markets) == 1
```

```python
# File: tests/swarm/test_consensus_aggregator.py

import pytest
from datetime import datetime, timezone
from merid.swarm.consensus_aggregator import (
    SwarmConsensusAggregator,
    AgentProposal,
    ConsensusStatus
)


class TestAntiHerding:
    """Test anti-herding protection in consensus."""

    def test_herding_detected_when_all_agents_agree(self):
        """Herding should be detected when all agents converge."""
        aggregator = SwarmConsensusAggregator(min_agents_for_consensus=3)

        # All agents predict same probability
        proposals = [
            AgentProposal(
                agent_id=f"agent_{i}",
                asset="BTC",
                timeframe="15m",
                direction="yes",
                probability=0.60,  # All agree on 60%
                confidence=0.80,
                size_preference="base",
                rationale="BTC going up",
                edge_estimate=5.0,
                timestamp=datetime.now(timezone.utc),
                agent_archetype="trend",
            )
            for i in range(5)
        ]

        for p in proposals:
            aggregator.submit_proposal(p)

        consensus = aggregator._consensus_cache.get("BTC:15m")

        # Check herding flag
        assert "herding_detected" in " ".join(consensus.disagreement_flags)

        # Check confidence penalty applied
        # Without penalty, 5 agents agreeing should give high confidence
        # With penalty, should be reduced
        assert consensus.consensus_confidence < 0.70

    def test_no_herding_when_agents_diverse(self):
        """No herding when agents have diverse predictions."""
        aggregator = SwarmConsensusAggregator(min_agents_for_consensus=3)

        # Diverse predictions
        proposals = [
            AgentProposal(
                agent_id=f"agent_{i}",
                asset="BTC",
                timeframe="15m",
                direction="yes",
                probability=0.50 + i * 0.05,  # 50%, 55%, 60%, 65%, 70%
                confidence=0.80,
                size_preference="base",
                rationale="BTC analysis",
                edge_estimate=5.0,
                timestamp=datetime.now(timezone.utc),
                agent_archetype="trend" if i < 3 else "mean_reversion",
            )
            for i in range(5)
        ]

        for p in proposals:
            aggregator.submit_proposal(p)

        consensus = aggregator._consensus_cache.get("BTC:15m")

        # No herding flag
        assert not any("herding" in flag for flag in consensus.disagreement_flags)

        # Confidence not penalized
        assert consensus.consensus_confidence >= 0.70
```

### D.2 Integration Test Examples

```python
# File: tests/integration/test_kalshi_e2e_trade_flow.py

import pytest
from decimal import Decimal
from merid.pipeline.router import TradeRouter
from merid.pipeline.proposal import TradeProposal, TradeSide
from merid.event_venues.kalshi.client import KalshiVenueClient


@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_trade_lifecycle_paper_mode(
    mock_kalshi_client,
    mock_market_catalog,
    mock_sentiment_context
):
    """Test complete trade flow in paper mode."""

    # Setup
    router = TradeRouter()

    # Create proposal
    proposal = TradeProposal(
        proposal_id="test-001",
        instrument_id="PRED:KALSHI:BTC_25DEC:YES",
        venue="kalshi",
        domain="prediction",
        side=TradeSide.BUY,
        qty=Decimal("10"),
        price=Decimal("55"),
        agent_id="test-agent",
    )

    # Submit
    result = await router.submit(proposal)

    # Verify
    assert result.status == "FILLED"
    assert result.execution_result.filled_qty == Decimal("10")
    assert result.execution_result.avg_price == Decimal("55")
    assert result.execution_result.status == "filled"

    # Check risk tracking
    assert router._risk.daily_notional_by_domain["prediction"] > 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_circuit_breaker_opens_on_repeated_failures(
    mock_kalshi_client_failing
):
    """Test circuit breaker opens after failures."""

    client = KalshiVenueClient(config=mock_config)

    # Mock 5 failures
    for i in range(5):
        with pytest.raises(Exception):
            await client.place_order(mock_order)

    # Circuit should be open
    assert client._circuit_breaker.state == "open"

    # Next call should fail-fast
    with pytest.raises(CircuitOpenError):
        await client.place_order(mock_order)
```

---

## Appendix E: Runbook Procedures

### E.1 Emergency Response Procedures

**Kill Switch Activation:**
```bash
# Manual kill switch activation
curl -X POST http://localhost:8000/api/v1/operator/emergency-stop \
  -H "Authorization: Bearer ${OPERATOR_TOKEN}" \
  -d '{"reason": "manual_operator_halt", "level": "global"}'

# Verify kill switch active
curl http://localhost:8000/api/v1/operator/status | jq '.kill_switch_active'

# Deactivate after resolution
curl -X POST http://localhost:8000/api/v1/operator/resume-trading \
  -H "Authorization: Bearer ${OPERATOR_TOKEN}"
```

**Circuit Breaker Reset:**
```bash
# Check circuit breaker state
curl http://localhost:8000/api/v1/kalshi/circuit-breaker | jq '.state'

# Force reset (use cautiously)
curl -X POST http://localhost:8000/api/v1/kalshi/circuit-breaker/reset \
  -H "Authorization: Bearer ${OPERATOR_TOKEN}"
```

**Agent Rollback:**
```bash
# Rollback specific agent
curl -X POST http://localhost:8000/api/v1/kalshi-grid/agent/BTC_HOURLY/rollback \
  -H "Authorization: Bearer ${OPERATOR_TOKEN}" \
  -d '{"reason": "profit_factor_collapsed"}'

# Check agent status
curl http://localhost:8000/api/v1/kalshi-grid/agent/BTC_HOURLY/status | jq
```

### E.2 Monitoring Runbook

**Daily Health Check:**
```bash
#!/bin/bash
# File: scripts/daily_health_check.sh

echo "=== MERID Kalshi Integration Health Check ==="
echo

# 1. Check catalog health
echo "1. Market Catalog:"
curl -s http://localhost:8000/api/v1/kalshi/catalog/summary | \
  jq '{market_count, last_refresh, running}'

# 2. Check agent modes
echo "2. Agent Deployment:"
curl -s http://localhost:8000/api/v1/kalshi-grid/health | \
  jq '{agents_by_mode, live_agents: .agents_by_mode.LIVE}'

# 3. Check circuit breaker
echo "3. Circuit Breaker:"
curl -s http://localhost:8000/api/v1/kalshi/circuit-breaker | \
  jq '{state, failure_count, last_success}'

# 4. Check kill switch
echo "4. Kill Switch:"
curl -s http://localhost:8000/api/v1/operator/status | \
  jq '{kill_switch_active, reason: .kill_switch_reason}'

# 5. Check CQI
echo "5. CQI Scores:"
curl -s http://localhost:8000/api/v1/execution-guard/status | \
  jq '.cqi_by_domain'

# 6. Check domain caps
echo "6. Domain Caps:"
curl -s http://localhost:8000/api/v1/execution-guard/domain-caps | \
  jq 'to_entries | map({domain: .key, remaining: .value.remaining_notional_usd})'

# 7. Check recent fills
echo "7. Recent Fills (last 1h):"
curl -s "http://localhost:8000/api/v1/kalshi/fills?since=1h" | \
  jq '[.fills[] | {agent: .agent_id, size: .filled_qty, pnl: .realized_pnl}] | length'

echo
echo "=== Health Check Complete ==="
```

---

**END OF TECHNICAL APPENDIX**
