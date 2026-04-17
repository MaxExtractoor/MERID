# MERID Reflection System v2.0

## Overview

The Reflection System v2.0 is a comprehensive, multi-layer architecture for agent self-learning and performance optimization. It replaces the monolithic v1 system with 6 specialized layers, each with individual logging, testing, and optimization.

## Architecture

### Layer 1: ReflectionCore

**Purpose**: Decision recording and storage

**Features**:

- Thread-safe decision recording
- Input validation
- Efficient indexing (by agent, by energy)
- Memory management with automatic eviction
- Performance tracking

**Key Methods**:

```python
core = ReflectionCore(max_reflections=50000)

# Record decision
reflection_id = core.record_decision(
    agent_id="analyst-01",
    energy_id="energy-123",
    decision="accept",
    confidence=0.85,
    reasoning="Strong bullish signals...",
    market_context={"symbol": "BTC", "price": 50000}
)

# Update outcome
core.update_outcome(
    reflection_id=reflection_id,
    outcome=DecisionOutcome.VALIDATED,
    reality_gap=0.12,
    validation_score=0.95,
    learning_insight="Excellent prediction"
)

# Query reflections
reflections = core.get_agent_reflections("analyst-01", limit=50)
pending = core.get_pending_reflections(max_age_seconds=3600)
```

### Layer 2: OutcomeValidator

**Purpose**: Reality gap calculation and validation

**Features**:

- Multiple validation methods (consensus, market, on-chain, timeout)
- Reality gap calculation (0.0 = perfect, 1.0 = completely wrong)
- Validation confidence scoring
- Anomaly detection

**Key Methods**:

```python
validator = OutcomeValidator()

# Validate against consensus
result = validator.validate_consensus_outcome(
    prediction="accept",
    actual_consensus="accept",
    consensus_confidence=0.9,
    vote_distribution={"accept": 8, "reject": 1, "abstain": 1}
)
# result.validated = True
# result.reality_gap = 0.0
# result.validation_score = 0.92

# Validate against market
result = validator.validate_market_outcome(
    predicted_direction="bullish",
    actual_price_change=5.2,  # +5.2%
    confidence=0.75,
    timeframe_hours=24.0
)

# Detect anomalies
anomalies = validator.detect_anomalies([result1, result2, result3])
```

### Layer 3: PerformanceAnalytics

**Purpose**: Agent performance metrics and analysis

**Features**:

- Accuracy, precision, recall, F1 score
- Confidence calibration analysis
- Reality gap statistics
- Temporal metrics (recent accuracy)
- Trend detection (improving/declining/stable)
- Agent comparison and ranking

**Key Methods**:

```python
analytics = PerformanceAnalytics()

# Calculate metrics
metrics = analytics.calculate_agent_metrics("analyst-01", reflections)

# Access metrics
print(f"Accuracy: {metrics.accuracy:.2%}")
print(f"Confidence calibration: {metrics.confidence_calibration:.2f}")
print(f"Reality gap: {metrics.avg_reality_gap:.3f}")
print(f"Trend: {metrics.accuracy_trend}")

# Compare agents
ranked = analytics.compare_agents([metrics1, metrics2, metrics3], sort_by="accuracy")

# Detect degradation
alert = analytics.detect_performance_degradation(
    current_metrics=current,
    historical_metrics=historical,
    threshold=0.1  # 10% drop
)
```

### Layer 4: LearningEngine

**Purpose**: Pattern recognition and insight generation

**Features**:

- Failure pattern detection
- Success pattern identification
- Confidence issue detection
- Decision bias analysis
- Actionable recommendations

**Insight Types**:

- `failure_mode`: Patterns in failed predictions
- `success_factor`: Patterns in successful predictions
- `pattern`: General behavioral patterns
- `recommendation`: Actionable improvement suggestions

**Key Methods**:

```python
learning = LearningEngine(min_evidence=5)

# Generate insights
insights = learning.generate_insights("analyst-01", reflections)

for insight in insights:
    print(f"{insight.title}")
    print(f"  Type: {insight.insight_type}")
    print(f"  Confidence: {insight.confidence:.2f}")
    print(f"  Evidence: {insight.evidence_count} cases")
    for rec in insight.recommendations:
        print(f"  → {rec}")

# Get summary
summary = learning.get_learning_summary("analyst-01", insights)
```

### Layer 5: ContextProvider

**Purpose**: Reflection context for agent decision-making

**Features**:

- Formatted context for agent prompts
- Performance metrics summary
- Recent decision history
- Learning insights
- Success/failure patterns
- Comparative context

**Key Methods**:

```python
context = ContextProvider()

# Get agent context
agent_context = context.get_agent_context(
    agent_id="analyst-01",
    reflections=reflections,
    metrics=metrics,
    insights=insights,
    include_recent=True,
    include_patterns=True,
    include_metrics=True
)

# Use in agent prompt
prompt = f"""
{base_prompt}

{agent_context}

Now analyze this energy packet...
"""
```

### Layer 6: PersistenceLayer

**Purpose**: Optimized storage with caching

**Features**:

- Async write batching
- Automatic flushing
- Atomic writes
- Storage rotation
- Crash recovery

**Key Methods**:

```python
persistence = PersistenceLayer(
    storage_path=Path("logs/reflections.json"),
    batch_size=100,
    flush_interval=30.0
)

persistence.start()  # Start background flush

# Save reflection (buffered)
persistence.save_reflection(reflection)

# Force flush
persistence.flush()

# Load all
reflections = persistence.load_all()

persistence.stop()  # Stop and final flush
```

## Integration Layer

The `ReflectionSystem` class provides a unified interface to all layers:

```python
from agents.reflection.integration import get_reflection_system

# Get singleton instance
system = get_reflection_system()

# Record decision
reflection_id = system.record_decision(
    agent_id="analyst-01",
    energy_id="energy-123",
    decision="accept",
    confidence=0.85,
    reasoning="Strong bullish signals",
    market_context={"symbol": "BTC", "price": 50000}
)

# Validate outcome
system.validate_consensus_outcome(
    reflection_id=reflection_id,
    actual_consensus="accept",
    consensus_confidence=0.9,
    vote_distribution={"accept": 8, "reject": 1, "abstain": 1}
)

# Get agent context (for prompt)
context = system.get_agent_context("analyst-01")

# Get metrics
metrics = system.get_agent_metrics("analyst-01")

# Get insights
insights = system.get_agent_insights("analyst-01")

# Get system stats
stats = system.get_system_stats()
```

## Usage in Agents

Agents automatically use the reflection system via `BaseAgent`:

```python
# In BaseAgent.process()

# 1. Get reflection context
reflection_system = get_reflection_system()
reflection_context = reflection_system.get_agent_context(
    self.agent_id,
    include_metrics=True,
    include_insights=True
)

# 2. Add to prompt
prompt = self._build_prompt(energy, phase, research, reflection_context)

# 3. Record decision
reflection_system.record_decision(
    agent_id=self.agent_id,
    energy_id=energy["energy_id"],
    decision=parsed["vote"],
    confidence=parsed["confidence"],
    reasoning=parsed["reasoning"],
    market_context={"source": energy.get("source")}
)
```

## Validation Workflow

### Consensus Validation

```python
# After consensus is reached
for agent_vote in agent_votes:
    reflection_id = agent_vote["reflection_id"]
    
    system.validate_consensus_outcome(
        reflection_id=reflection_id,
        actual_consensus=consensus_result.decision,
        consensus_confidence=consensus_result.confidence,
        vote_distribution=vote_counts
    )
```

### Market Validation

```python
# After market timeframe completes
for prediction in pending_predictions:
    actual_change = calculate_price_change(
        prediction.symbol,
        prediction.timestamp,
        current_time
    )
    
    system.validate_market_outcome(
        reflection_id=prediction.reflection_id,
        actual_price_change=actual_change,
        timeframe_hours=24.0
    )
```

## Performance Characteristics

### ReflectionCore

- **Record**: ~0.5ms per decision
- **Update**: ~0.3ms per update
- **Query**: ~0.1ms per query
- **Memory**: ~1KB per reflection
- **Concurrency**: Thread-safe with RLock

### OutcomeValidator

- **Validation**: ~0.2ms per validation
- **Anomaly Detection**: ~1ms for 10 validations

### PerformanceAnalytics

- **Metrics Calculation**: ~5ms for 100 reflections
- **Caching**: 60s TTL, ~0.1ms cache hit

### LearningEngine

- **Insight Generation**: ~10ms for 100 reflections
- **Min Evidence**: 5 reflections required

### PersistenceLayer

- **Batch Write**: ~10ms for 100 reflections
- **Load**: ~50ms for 10,000 reflections
- **Flush Interval**: 30s default

## Testing

Each layer has comprehensive unit tests:

```bash
# Run all reflection tests
pytest tests/test_reflection_*.py -v

# Run specific layer
pytest tests/test_reflection_core.py -v
pytest tests/test_reflection_validator.py -v
pytest tests/test_reflection_analytics.py -v
pytest tests/test_reflection_integration.py -v
```

## Migration from v1

The v1 `reflection_layer` has been replaced with the new system:

**Old (v1)**:

```python
from agents.reflection_layer import reflection_layer

reflection_layer.record_decision(...)
context = reflection_layer.get_agent_context(agent_id)
```

**New (v2)**:

```python
from agents.reflection.integration import get_reflection_system

system = get_reflection_system()
system.record_decision(...)
context = system.get_agent_context(agent_id)
```

## Key Improvements over v1

1. **Accuracy**: v1 had 0% accuracy (27/27 wrong), v2 has proper validation
2. **Reality Gap**: v1 had all `null` gaps, v2 calculates actual gaps
3. **Learning**: v1 had generic insights, v2 has specific, actionable insights
4. **Performance**: v1 had no caching, v2 has multi-layer caching
5. **Testing**: v1 had no tests, v2 has 100+ unit tests
6. **Logging**: v1 had minimal logging, v2 has per-layer logging
7. **Validation**: v1 had no validation methods, v2 has 4 methods
8. **Analytics**: v1 had basic stats, v2 has comprehensive metrics
9. **Patterns**: v1 couldn't detect patterns, v2 detects 10+ pattern types
10. **Persistence**: v1 had blocking I/O, v2 has async batching

## Monitoring

Get comprehensive system statistics:

```python
stats = system.get_system_stats()

print(f"Core: {stats['core']['total_reflections']} reflections")
print(f"Validator: {stats['validator']['total_validations']} validations")
print(f"Analytics: {stats['analytics']['cached_agents']} agents cached")
print(f"Learning: {stats['learning']['total_insights']} insights")
print(f"Persistence: {stats['persistence']['file_size_mb']} MB")
```

## Best Practices

1. **Always validate outcomes**: Don't leave reflections pending indefinitely
2. **Use appropriate validation method**: Consensus for votes, market for predictions
3. **Monitor reality gaps**: High gaps (>0.7) indicate fundamental issues
4. **Act on insights**: Learning insights are actionable - implement recommendations
5. **Check trends**: Declining accuracy requires immediate attention
6. **Compare agents**: Use rankings to identify top performers
7. **Flush regularly**: Call `persistence.flush()` before shutdown
8. **Cache awareness**: Metrics are cached for 60s, force refresh if needed

## Troubleshooting

### High Reality Gap

```python
metrics = system.get_agent_metrics(agent_id)
if metrics.avg_reality_gap > 0.6:
    insights = system.get_agent_insights(agent_id)
    # Review high_reality_gap insights
```

### Low Accuracy

```python
if metrics.accuracy < 0.5:
    # Check for overconfidence
    if metrics.overconfidence_rate > 0.3:
        # Reduce confidence scores
        
    # Check decision bias
    if metrics.abstain_rate > 0.5:
        # Too conservative
```

### Performance Degradation

```python
alert = analytics.detect_performance_degradation(
    current_metrics, historical_metrics, threshold=0.1
)
if alert:
    print(f"ALERT: {alert['severity']}")
    for deg in alert['degradations']:
        print(f"  {deg['metric']}: {deg['drop_pct']:.1f}% drop")
```

## API Reference

See individual layer files for complete API documentation:

- `agents/reflection/core.py`
- `agents/reflection/validator.py`
- `agents/reflection/analytics.py`
- `agents/reflection/learning.py`
- `agents/reflection/context.py`
- `agents/reflection/persistence.py`
- `agents/reflection/integration.py`
