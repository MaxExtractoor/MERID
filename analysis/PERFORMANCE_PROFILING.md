# Performance Profiling Guide

**Date:** 2026-05-13
**Purpose:** Guide for performance profiling of MERID system

## Profiling Tools

### Python Profiling
- **cProfile:** Built-in Python profiler
- **py-spy:** Sampling profiler for production use
- **memory_profiler:** Memory profiling
- **line_profiler:** Line-by-line profiling

### System Monitoring
- **psutil:** System resource monitoring
- **Prometheus:** Metrics collection
- **Grafana:** Metrics visualization

## Profiling Scenarios

### 1. Agent Performance Profiling
**Goal:** Identify slow agents and optimize signal generation

**Tool:** cProfile

```python
import cProfile
import pstats
from merid.agents.eth_15m_agent import Eth15mAgent

profiler = cProfile.Profile()
agent = Eth15mAgent()

profiler.enable()
agent.generate_opinion(market_id="KXETH-15M-...")
profiler.disable()

stats = pstats.Stats(profiler)
stats.sort_stats('cumtime')
stats.print_stats(20)  # Top 20 functions
```

### 2. Trading Loop Profiling
**Goal:** Identify bottlenecks in trading cycle

**Tool:** py-spy (non-intrusive)

```bash
# Install py-spy
pip install py-spy

# Profile running process
py-spy --pid <PID> -o profile.svg

# Or profile specific function
py-spy -- merid/loop.py:run
```

### 3. Memory Profiling
**Goal:** Identify memory leaks and optimize memory usage

**Tool:** memory_profiler

```python
from memory_profiler import profile

@profile
def memory_intensive_function():
    # Code to profile
    pass

memory_intensive_function()
```

### 4. API Endpoint Profiling
**Goal:** Identify slow API endpoints

**Tool:** Middleware timing (already in web/main.py)

```python
# Latency timing is already implemented in web/main.py
# Check logs for endpoint latency metrics
```

## Performance Metrics

### Key Metrics to Monitor
- **Agent signal generation time:** < 100ms per agent
- **Trading cycle time:** < 1s per cycle
- **API endpoint latency:** < 500ms for 95th percentile
- **Memory usage:** < 2GB for typical operations
- **CPU usage:** < 80% under normal load

### Baseline Targets
- **15m cycle time:** 500ms - 1s
- **Agent opinion generation:** 50ms - 100ms
- **Risk check time:** < 10ms
- **Order submission time:** < 100ms
- **Log write time:** < 1ms

## Profiling Workflow

### 1. Baseline Measurement
1. Run system under normal load
2. Profile key components (agents, loop, API)
3. Establish baseline metrics
4. Document current performance

### 2. Identify Bottlenecks
1. Review profiler output
2. Identify slow functions (>100ms)
3. Identify hot paths (frequently called)
4. Prioritize optimization targets

### 3. Optimize
1. Optimize identified bottlenecks
2. Re-profile to measure improvement
3. Compare to baseline
4. Document improvements

### 4. Monitor
1. Set up continuous monitoring
2. Alert on performance degradation
3. Regularly review metrics
4. Trend analysis over time

## Common Performance Issues

### 1. Synchronous Blocking Calls
**Symptom:** Slow cycle times, blocking operations
**Solution:** Use async/await for I/O operations

### 2. Excessive Logging
**Symptom:** High CPU usage, slow write times
**Solution:** Reduce log volume, use async logging

### 3. Inefficient Data Structures
**Symptom:** Slow lookups, high memory usage
**Solution:** Use appropriate data structures (dict vs list, set vs list)

### 4. Unnecessary Computations
**Symptom:** Repeated calculations, wasted CPU
**Solution:** Cache results, avoid redundant work

### 5. Large Object Creation
**Symptom:** Memory spikes, GC pressure
**Solution:** Object pooling, reuse objects

## Optimization Strategies

### 1. Caching
- Cache agent opinions
- Cache market data
- Cache configuration lookups
- Use TTL to invalidate

### 2. Lazy Loading
- Load modules only when needed
- Initialize heavy objects lazily
- Use lazy imports

### 3. Async I/O
- Use async/await for network calls
- Use async file operations
- Use async database queries

### 4. Batch Processing
- Batch API calls
- Batch database operations
- Batch log writes

### 5. Algorithm Optimization
- Use efficient algorithms
- Optimize data structures
- Avoid nested loops

## Profiling Checklist

### Before Profiling
- [ ] Define profiling goals
- [ ] Choose appropriate tool
- [ ] Prepare test environment
- [ ] Establish baseline metrics

### During Profiling
- [ ] Run under representative load
- [ ] Collect sufficient data
- [ ] Note system conditions
- [ ] Document findings

### After Profiling
- [ ] Analyze profiler output
- [ ] Identify bottlenecks
- [ ] Prioritize optimizations
- [ ] Implement changes
- [ ] Re-profile to validate
- [ ] Document improvements

## Continuous Performance Monitoring

### Metrics to Track
- Agent signal generation time
- Trading cycle time
- API endpoint latency
- Memory usage
- CPU usage
- Disk I/O
- Network I/O

### Alerting Thresholds
- Agent signal generation > 500ms: WARNING
- Trading cycle time > 2s: WARNING
- API endpoint latency > 1s: WARNING
- Memory usage > 4GB: CRITICAL
- CPU usage > 90%: CRITICAL

### Dashboard
- Grafana dashboard for metrics
- Real-time performance graphs
- Historical trend analysis
- Alert integration

## Success Criteria

1. Profiling tools identified and documented
2. Performance baseline established
3. Bottlenecks identified and optimized
4. Continuous monitoring set up
5. Alerting thresholds defined
6. Performance improvements documented

## Next Steps

1. Run baseline profiling on current system
2. Identify performance bottlenecks
3. Implement optimizations
4. Set up continuous monitoring
5. Document performance improvements
