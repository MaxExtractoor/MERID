# Gateway Criteria for Adding Agents to 15m Pipelines

This document defines the criteria that any new agent must meet before being wired into a 15m execution pipeline. These criteria ensure the clean 15m execution shell architecture is maintained and prevent degradation into an unmaintainable system.

## Core Principle

Only agents that pass ALL gateway criteria may be added to the `feature_agents` list in a 15m pipeline configuration. The 15m execution agents (BTC_15M, ETH_15M, etc.) have stricter criteria since they directly place trades.

## Gateway Criteria

### 1. Registry Entry Completeness

**Required for all agents:**

- **Role classification**: Must have `role` field set to one of:
  - `feature` — For agents that produce features (sentiment, regime, macro, etc.)
  - `risk` — For agents that can veto trades
  - `research` — For agents that produce theses/analysis
  - `execution` — Only for 15m Kalshi grid agents with `_15M` suffix

- **Feature namespace**: For `role=feature` agents, must specify one of:
  - `sentiment` — News/social sentiment features
  - `microstructure` — Lower timeframe (1m, 5m) features
  - `regime` — Higher timeframe (1h, 4h, daily, weekly) features
  - `macro` — Cross-asset macro features
  - `volatility` — Volatility regime features
  - `confidence` — Ensemble/confidence features
  - `general` — If no specific namespace applies

- **Asset and timeframe**: Must specify:
  - `assets`: List of assets the agent applies to (e.g., ["BTC", "ETH"] or ["CRYPTO"])
  - `timeframes`: List of timeframes (e.g., ["1m", "5m", "15m", "1h", "daily"])

**Validation:**
```python
# Scanner automatically validates these fields
# Run: python scripts/scan_agent_registry.py --output-json inventory.json
# Check that agent has role, feature_namespace, assets, timeframes populated
```

### 2. Clear Semantics and Documentation

**Required for all agents:**

- **Docstring**: Must have a clear docstring stating:
  - What features it produces (for `role=feature`)
  - Output format (e.g., `Dict[str, float]` with bounded values)
  - Invariants (e.g., "all values bounded in [-1, 1]")
  - Dependencies (e.g., "requires Binance API for price data")

- **Type hints**: Method signatures must be typed for clarity

**Example:**
```python
class CryptoNewsSentimentAgent(CanonicalAgent):
    """
    Produces sentiment features from crypto news headlines.
    
    Output format: Dict[str, float]
    - headline_sentiment: float in [-1, 1] (negative=bearish, positive=bullish)
    - news_flow_intensity: float in [0, 1] (0=no news, 1=max news flow)
    - event_risk_flag: float in [0, 1] (0=no risk, 1=high event risk)
    
    Invariants:
    - All output values are bounded in [-1, 1]
    - Returns zeros if news API is unavailable (graceful degradation)
    
    Dependencies:
    - Requires news API key in NEWS_API_KEY env var
    """
```

### 3. Unit Tests

**Required for all agents:**

- **Basic correctness**: Test that the agent produces expected output format
- **Graceful failure**: Test that the agent handles errors gracefully (returns empty dict or zeros)
- **Bounded output**: Test that output values respect declared invariants (e.g., bounds)
- **Latency**: Test that the agent completes within latency budget (see criterion 5)

**Example test structure:**
```python
# tests/pipelines/test_crypto_news_sentiment_agent.py
class TestCryptoNewsSentimentAgent:
    def test_output_format(self):
        """Test that agent returns Dict[str, float]."""
        agent = CryptoNewsSentimentAgent()
        result = agent.run(context)
        assert isinstance(result, dict)
        for v in result.values():
            assert isinstance(v, (int, float))
    
    def test_bounded_output(self):
        """Test that all values are in [-1, 1]."""
        agent = CryptoNewsSentimentAgent()
        result = agent.run(context)
        for v in result.values():
            assert -1 <= v <= 1
    
    def test_graceful_failure(self):
        """Test that agent returns zeros on API failure."""
        agent = CryptoNewsSentimentAgent()
        # Mock API failure
        result = agent.run(context_with_api_failure)
        # Should return zeros, not crash
        assert all(v == 0 for v in result.values())
```

### 4. Backtest Performance Check

**Required for `role=feature` agents:**

- **Performance impact**: Adding the agent to the pipeline must not worsen key metrics beyond thresholds:
  - Sharpe ratio: Must not decrease by more than 0.1
  - Max drawdown: Must not increase by more than 2%
  - Win rate: Must not decrease by more than 5%

- **Neutral or positive contribution**: Agent should be neutral or positive to performance. If it degrades performance, it should not be added.

**Procedure:**
```bash
# Run backtest with current pipeline
python scripts/backtest_15m_pipeline.py --asset BTC --start 2024-01-01 --end 2024-03-31

# Add new agent to pipeline config
# Edit config/kalshi_15m_pipelines.yaml to add agent to feature_agents

# Run backtest with new agent
python scripts/backtest_15m_pipeline.py --asset BTC --start 2024-01-01 --end 2024-03-31

# Compare metrics
# If Sharpe decreased by >0.1 or drawdown increased by >2%, reject agent
```

**Required for `role=execution` agents (15m only):**

- **Stricter performance**: Must show positive Sharpe ratio (>0.5) and max drawdown <10% in backtest
- **Risk-adjusted returns**: Must improve risk-adjusted returns compared to baseline

### 5. Latency Budget

**Required for all agents:**

- **Feature agents**: Must complete within 500ms under load (95th percentile)
- **Execution agents**: Must complete within 200ms under load (95th percentile)
- **Risk agents**: Must complete within 100ms under load (95th percentile)

**Testing:**
```python
# tests/pipelines/test_agent_latency.py
import time

def test_agent_latency_under_load():
    """Test that agent completes within latency budget."""
    agent = CryptoNewsSentimentAgent()
    
    # Run 100 iterations
    latencies = []
    for _ in range(100):
        start = time.time()
        result = agent.run(context)
        latencies.append((time.time() - start) * 1000)  # Convert to ms
    
    # Check 95th percentile
    p95 = sorted(latencies)[94]  # 95th percentile
    assert p95 < 500, f"95th percentile latency {p95}ms exceeds 500ms budget"
```

### 6. Inter-Agent Hygiene

**Required for all agents:**

- **No direct agent-to-agent calls**: Agents must not call other agents directly. All composition happens through the orchestrator.
- **No trading client access**: Feature agents must not have access to the Kalshi trading client.
- **No state sharing**: Agents must not share mutable state between runs. State should be passed via the context object.

**Validation:**
```python
# Scanner checks for trading client imports
# Grep for "KalshiTradingAgent" or "place_order" in feature agent code
# If found, reject the agent
```

### 7. Configuration Validation

**Required for all agents:**

- **YAML config**: If added to `kalshi_15m_pipelines.yaml`, the entry must pass validation:
  ```yaml
  feature_agents:
    - name: NEW_AGENT
      role: feature  # Must be feature
      feature_namespace: sentiment  # Must be valid namespace
      enabled: true
      assets: [BTC]  # Must include target asset or CRYPTO
  ```

- **Pipeline validator**: Must pass `pipeline.validate()` checks
  - Asset must be in {BTC, ETH, SOL, XRP, DOGE}
  - Timeframe must be "15m" for execution agents
  - No execution agents in feature_agents list

## Exception Process

Agents that fail gateway criteria may still be added with explicit approval and documentation of the exception. Exceptions require:

1. **Justification**: Clear reason why the criterion doesn't apply
2. **Mitigation**: Plan to mitigate the risk
3. **Review**: Approval from system architect
4. **Monitoring**: Enhanced monitoring for the agent

## Checklist for Adding a New Agent

- [ ] Registry entry complete (role, feature_namespace, assets, timeframes)
- [ ] Clear docstring with semantics and invariants
- [ ] Unit tests pass (correctness, graceful failure, bounded output)
- [ ] Backtest shows neutral or positive performance (Sharpe, drawdown)
- [ ] Latency budget satisfied (feature: 500ms, execution: 200ms)
- [ ] No direct agent-to-agent calls or trading client access
- [ ] YAML config passes validation
- [ ] Inter-agent hygiene verified

## Enforcement

The pipeline loader (`merid/pipelines/pipeline_loader.py`) validates configurations on load. The agent scanner (`scripts/scan_agent_registry.py`) validates registry entries. Backtest harness (`merid/pipelines/backtest_harness.py`) validates performance.

These automated checks should be run as part of CI/CD before merging any agent changes.
