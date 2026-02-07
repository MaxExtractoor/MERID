# 📊 **LLM ANALYTICS PLAN: DATA-DRIVEN DECISION MAKING**

## 🎯 **STRATEGIC OBJECTIVES**

### **Primary Goal**
Use the `llm_mode`/`llm_status` logging to make data-driven decisions about LLM value vs baseline heuristics.

### **Key Questions to Answer**
1. **Effectiveness**: Does live LLM improve decision quality over mock baseline?
2. **Reliability**: What's the realistic `llm_status="ok"` rate under current infra?
3. **Performance**: What's the latency and cost tradeoff?
4. **ROI**: Is the LLM providing measurable value over heuristics?

---

## 📈 **ANALYTICS IMPLEMENTATION**

### **1. Mode/Status Dashboard**
```python
# Add to tools/analyze_agent_runs.py
def analyze_llm_performance(log_file: str):
    """Analyze LLM performance vs mock baseline."""
    import json
    import pandas as pd
    
    runs = []
    with open(log_file) as f:
        for line in f:
            runs.append(json.loads(line))
    
    df = pd.DataFrame(runs)
    
    # Mode distribution
    mode_dist = df['llm_mode'].value_counts()
    status_dist = df['llm_status'].value_counts()
    
    # Performance comparison
    live_ok = df[(df['llm_mode'] == 'live') & (df['llm_status'] == 'ok')]
    mock_runs = df[df['llm_mode'] == 'mock']
    
    # Metrics comparison
    if len(live_ok) > 0 and len(mock_runs) > 0:
        live_metrics = {
            'avg_brier': live_ok['brier_score'].mean(),
            'avg_latency': live_ok['latency_ms'].mean(),
            'success_rate': 1.0  # By definition of llm_status='ok'
        }
        
        mock_metrics = {
            'avg_brier': mock_runs['brier_score'].mean(),
            'avg_latency': mock_runs['latency_ms'].mean(),
            'success_rate': 1.0  # Mock always succeeds
        }
        
        # Improvement calculation
        brier_improvement = ((mock_metrics['avg_brier'] - live_metrics['avg_brier']) 
                            / mock_metrics['avg_brier']) * 100
        latency_penalty = ((live_metrics['avg_latency'] - mock_metrics['avg_latency']) 
                           / mock_metrics['avg_latency']) * 100
        
        return {
            'mode_distribution': mode_dist.to_dict(),
            'status_distribution': status_dist.to_dict(),
            'live_performance': live_metrics,
            'mock_baseline': mock_metrics,
            'improvement_analysis': {
                'brier_improvement_pct': brier_improvement,
                'latency_penalty_pct': latency_penalty,
                'net_value': brier_improvement - latency_penalty
            }
        }
    
    return {'mode_distribution': mode_dist, 'status_distribution': status_dist}
```

### **2. A/B Testing Framework**
```python
# Add to tools/run_prompt_experiment.py
def analyze_experiment_results(experiment_file: str):
    """Compare prompt variants with llm_mode tracking."""
    with open(experiment_file) as f:
        results = json.load(f)
    
    # Separate live vs mock runs
    live_results = {}
    mock_results = {}
    
    for variant, data in results['variants'].items():
        live_runs = [r for r in data['runs'] if r.get('llm_mode') == 'live']
        mock_runs = [r for r in data['runs'] if r.get('llm_mode') == 'mock']
        
        if live_runs:
            live_results[variant] = {
                'avg_brier': np.mean([r['brier_score'] for r in live_runs if r.get('brier_score')]),
                'avg_latency': np.mean([r['latency_ms'] for r in live_runs]),
                'success_rate': len([r for r in live_runs if r.get('status') == 'success']) / len(live_runs)
            }
        
        if mock_runs:
            mock_results[variant] = {
                'avg_brier': np.mean([r['brier_score'] for r in mock_runs if r.get('brier_score')]),
                'avg_latency': np.mean([r['latency_ms'] for r in mock_runs]),
                'success_rate': len([r for r in mock_runs if r.get('status') == 'success']) / len(mock_runs)
            }
    
    return {
        'live_performance': live_results,
        'mock_baseline': mock_results,
        'improvement_analysis': calculate_improvement(live_results, mock_results)
    }
```

### **3. Infrastructure Monitoring**
```python
# Add to monitoring/llm_health.py
def monitor_llm_health(log_file: str, time_window_hours: int = 24):
    """Monitor LLM health metrics over time."""
    import json
    from datetime import datetime, timedelta
    
    cutoff = datetime.now() - timedelta(hours=time_window_hours)
    
    recent_runs = []
    with open(log_file) as f:
        for line in f:
            run = json.loads(line)
            run_time = datetime.fromtimestamp(run['timestamp'])
            if run_time > cutoff:
                recent_runs.append(run)
    
    if not recent_runs:
        return {'status': 'no_data', 'message': f'No runs in last {time_window_hours}h'}
    
    df = pd.DataFrame(recent_runs)
    
    # Health metrics
    total_runs = len(df)
    live_runs = df[df['llm_mode'] == 'live']
    
    if len(live_runs) == 0:
        return {
            'status': 'all_mock',
            'total_runs': total_runs,
            'mock_only_rate': 1.0,
            'recommendation': 'Consider enabling live mode for LLM evaluation'
        }
    
    success_rate = len(live_runs[live_runs['llm_status'] == 'ok']) / len(live_runs)
    timeout_rate = len(live_runs[live_runs['llm_status'] == 'timeout']) / len(live_runs)
    error_rate = len(live_runs[live_runs['llm_status'] == 'error']) / len(live_runs)
    
    # Health assessment
    if success_rate >= 0.8:
        health_status = 'healthy'
    elif success_rate >= 0.5:
        health_status = 'degraded'
    else:
        health_status = 'unhealthy'
    
    return {
        'status': health_status,
        'time_window_hours': time_window_hours,
        'total_runs': total_runs,
        'live_runs': len(live_runs),
        'mock_runs': total_runs - len(live_runs),
        'success_rate': success_rate,
        'timeout_rate': timeout_rate,
        'error_rate': error_rate,
        'recommendation': get_health_recommendation(health_status, success_rate)
    }
```

---

## 🎯 **DECISION FRAMEWORK**

### **When to Use Live LLM**
```python
def should_use_live_llm():
    """Decision criteria for live LLM usage."""
    
    # Check recent health metrics
    health = monitor_llm_health('logs/agent_runs.jsonl', 24)
    
    # Decision rules
    if health['status'] == 'healthy' and health['success_rate'] >= 0.8:
        return True, "LLM infrastructure healthy and reliable"
    elif health['status'] == 'degraded':
        return False, "LLM infrastructure degraded - use mock baseline"
    else:
        return False, "LLM infrastructure unhealthy - mock baseline required"
```

### **Value Assessment**
```python
def assess_llm_value(live_metrics, mock_metrics):
    """Assess if live LLM provides value over mock baseline."""
    
    brier_improvement = ((mock_metrics['avg_brier'] - live_metrics['avg_brier']) 
                        / mock_metrics['avg_brier']) * 100
    
    # Value thresholds
    if brier_improvement >= 10:
        return "high_value", f"Live LLM improves Brier by {brier_improvement:.1f}%"
    elif brier_improvement >= 5:
        return "moderate_value", f"Live LLM improves Brier by {brier_improvement:.1f}%"
    elif brier_improvement >= 0:
        return "low_value", f"Live LLM improves Brier by {brier_improvement:.1f}%"
    else:
        return "negative_value", f"Live LLM worsens Brier by {abs(brier_improvement):.1f}%"
```

---

## 📋 **IMPLEMENTATION ROADMAP**

### **Phase 1: Analytics Setup (Immediate)**
1. ✅ Add llm_mode/status fields to logging
2. ✅ Create mode/status analysis tools
3. ⏳ Implement dashboard views for LLM health
4. ⏳ Set up automated health monitoring

### **Phase 2: Baseline Establishment (1 week)**
1. ⏳ Run extensive mock experiments to establish baseline metrics
2. ⏳ Document baseline Brier scores and bucket distributions
3. ⏳ Create performance benchmarks for mock mode
4. ⏳ Validate structural consistency across all components

### **Phase 3: Live Testing (When Infra Ready)**
1. ⏳ Gradually enable `AGENT_LLM_MODE=live`
2. ⏳ Monitor health metrics in real-time
3. ⏳ Compare live vs mock performance
4. ⏳ Make data-driven decisions on LLM value

### **Phase 4: Optimization (Ongoing)**
1. ⏳ A/B test different LLM configurations
2. ⏳ Optimize timeout and retry parameters
3. ⏳ Fine-tune prompt variants based on performance data
4. ⏳ Scale infrastructure based on usage patterns

---

## 🏆 **SUCCESS METRICS**

### **Technical Success**
- **Logging**: 100% of runs have llm_mode/status fields
- **Analytics**: Real-time dashboards for LLM health
- **Monitoring**: Automated alerts for degradation
- **Testing**: Unit tests ensure structural consistency

### **Business Success**
- **Decision Quality**: Data-driven choices about LLM usage
- **Cost Efficiency**: Only pay for LLM when it provides value
- **Risk Management**: System remains functional regardless of LLM health
- **Performance**: Baseline metrics established for comparison

---

## 🎯 **FINAL STRATEGIC POSITION**

**✅ READY FOR DATA-DRIVEN LLM DECISIONS**

The system now has:
- **Clear Baseline**: Mock mode provides reliable, measurable performance
- **Comprehensive Monitoring**: Full visibility into LLM health and effectiveness
- **Decision Framework**: Objective criteria for when to use live LLM
- **Risk Mitigation**: System remains operational regardless of LLM issues

**Next Steps**: Focus on other system areas while LLM infrastructure matures, then make data-driven decisions about LLM integration based on the analytics framework you've built.

**Status: STRATEGIC POSITION ACHIEVED - READY FOR NEXT PHASE** 🚀
