# 🚀 MERID Agent Lab - Production Deployment Guide

## ✅ Pre-Flight Checklist - COMPLETED

### Infrastructure Status
- [x] **API Service**: Running on port 8000
- [x] **Agent Registration**: `prediction-arbitrage-analyst` registered
- [x] **Structured Logging**: `logs/agent_runs.jsonl` active with experiment fields
- [x] **Experiment Framework**: HTTP driver and analysis tools ready
- [x] **Docker/Fluent Bit**: Configured for log aggregation

### Current Limitations
- [ ] **Agent Performance**: Taking 60+ seconds to respond (timeout issue)
- [ ] **Production URL**: Need staging/production endpoint configuration

## 🎯 **Staging Deployment**

### 1. Environment Configuration

**Staging Server Setup**:
```bash
# Replace with your staging server details
export STAGING_HOST=staging.merid.example.com
export STAGING_PORT=8000
```

**Verify Connectivity**:
```bash
python -c "import requests; resp = requests.post(f'http://{STAGING_HOST}:{STAGING_PORT}/api/v1/institutional/agents/prediction-arbitrage-analyst/analyze', params={'min_spread': 0.05}, timeout=120); print('✅ Staging API Status:', resp.status_code)"
```

### 2. Run First Staging Experiment

**Execute Experiment**:
```bash
python tools/run_prompt_experiment.py \
  --base-url http://${STAGING_HOST}:${STAGING_PORT} \
  --config experiments/prompt_experiments.yaml
```

**Expected Results**:
- HTTP 200 responses (but may timeout due to agent performance)
- New entries in `logs/agent_runs.jsonl` with `experiment_id=arb-prompt-2026-01-24`
- `agent_version` set to `prompt-A` / `prompt-B`
- `run_type` set to `prompt-experiment`

### 3. Verify Experiment Data

**Check Logs**:
```bash
# Look for experiment entries
grep "experiment_id" logs/agent_runs.jsonl | tail -10

# Check specific experiment
python tools/analyze_agent_runs.py --experiment-id arb-prompt-2026-01-24
```

**Expected Log Format**:
```json
{
  "ts": "2026-01-24T12:00:00Z",
  "service": "merid-agent",
  "level": "INFO",
  "logger": "merid.agent",
  "msg": "agent_run_completed",
  "agent_id": "prediction-arbitrage-analyst-01",
  "run_id": "arb-prompt-2026-01-24-prompt-A-1",
  "agent_version": "prompt-A",
  "run_type": "prompt-experiment",
  "experiment_id": "arb-prompt-2026-01-24",
  "brier_score": 0.003889,
  "estimates_only": true,
  "total_opportunities": 3,
  "recommendations_count": 3,
  "latency_ms": 850.0,
  "status": "success",
  "filters": {
    "min_spread": 0.05,
    "min_liquidity": 50000.0,
    "categories": ["crypto"]
  }
}
```

### 4. Analyze Results

**Quick Analysis**:
```bash
python tools/analyze_agent_runs.py --experiment-id arb-prompt-2026-01-24
```

**Expected Metrics**:
- Runs per variant ≈ configured `runs_per_variant`
- Mean/median Brier scores for comparison
- Latency and status distribution
- Success rate for each variant

## 🚀 **Production Deployment**

### 1. Safe Production Rollout

**Start with Reduced Scope**:
```yaml
# experiments/prompt_experiments_production.yaml
id: arb-prompt-prod-2026-01-24
description: "Production prompt experiment - limited scope"
agent_id: prediction-arbitrage-analyst
runs_per_variant: 10  # Reduced for production

filters:
  min_spread: 0.08      # Higher threshold for safety
  min_liquidity: 100000.0  # Higher liquidity requirement
  categories: ["crypto"]  # Keep focused

variants:
  - name: prompt-A-prod
    description: "Current production prompt"
  - name: prompt-B-prod
    description: "Optimized prompt candidate"
```

**Execute Production Experiment**:
```bash
python tools/run_prompt_experiment.py \
  --base-url https://api.merid.example.com \
  --config experiments/prompt_experiments_production.yaml
```

### 2. Monitoring During Production Experiments

**Key Metrics to Watch**:
- API response times (should not degrade)
- Error rates (should remain <5%)
- System resource usage
- User impact (should be minimal)

**Dashboard Monitoring**:
- `/debug-v2` should continue working normally
- Experiment traffic appears as additional API calls
- No impact on regular user workflows

### 3. Success Criteria

**Technical Success**:
- [ ] All experiment runs complete without system impact
- [ ] Structured logs captured correctly in production
- [ ] Analysis tools work on production data
- [ ] No degradation in regular API performance

**Business Success**:
- [ ] Clear winner identified with statistical significance
- [ ] Brier score improvement measurable
- [ ] No negative impact on user experience
- [ ] Results documented and ready for decision

## 🔧 **Troubleshooting Production Issues**

### Common Issues and Solutions

**1. Agent Timeout Issues**
```bash
# Increase timeout for slow agents
# Edit tools/run_prompt_experiment.py
timeout=180  # 3 minutes
```

**2. Log Aggregation Issues**
```bash
# Verify Fluent Bit is forwarding logs
tail -f /var/log/fluent-bit/fluent-bit.log

# Check Elasticsearch
curl -X GET "localhost:9200/merid-agent-runs-*/_search?pretty"
```

**3. API Performance Issues**
```bash
# Monitor API response times
curl -w "@curl-format.txt" -o /dev/null -s \
  "http://api.merid.example.com/api/v1/institutional/health"
```

**4. Experiment Data Issues**
```bash
# Validate log format
python -c "
import json
with open('logs/agent_runs.jsonl') as f:
    for line in f:
        if 'experiment_id' in line:
            print('✅ Experiment log found:', json.loads(line)['experiment_id'])
"
```

## 📊 **Integration with Monitoring Stack**

### Elasticsearch Integration

**Index Template Applied**:
```bash
# Apply the index template
curl -X PUT "localhost:9200/_index_template/merid-agent-runs-template" \
  -H 'Content-Type: application/json' \
  -d @monitoring/elasticsearch-index-template.json
```

**Query Experiment Data**:
```json
GET merid-agent-runs-*/_search
{
  "query": {
    "term": {
      "experiment_id": "arb-prompt-2026-01-24"
    }
  },
  "aggs": {
    "variants": {
      "terms": {
        "field": "agent_version"
      },
      "aggs": {
        "avg_brier": {
          "avg": {
            "field": "brier_score"
          }
        }
      }
    }
  }
}
```

### Grafana Dashboard Queries

**Brier Score by Variant**:
```
avg by (agent_version) (brier_score)
```

**Experiment Success Rate**:
```
sum by (agent_version) (if(status == "success", 1, 0)) / sum by (agent_version) (1)
```

**Latency Distribution**:
```
histogram_quantile(0.95, latency_ms) by (agent_version)
```

## 🎯 **Rollback Plan**

### Immediate Rollback Triggers
- Error rate > 10%
- API latency > 5s
- User complaints
- System resource usage > 80%

### Rollback Steps
1. Stop experiment driver
2. Monitor system recovery
3. Analyze logs for issues
4. Document findings
5. Plan next iteration

## 📈 **Success Metrics & KPIs**

### Technical KPIs
- **Experiment Success Rate**: >95%
- **API Response Time**: <2s (baseline)
- **Log Capture Rate**: 100%
- **Analysis Speed**: <1s for 1000 runs

### Business KPIs
- **Brier Score Improvement**: >5%
- **User Impact**: <1% error rate increase
- **System Stability**: No degradation
- **Decision Quality**: Data-driven prompt selection

---

## 🎯 **Production Readiness Status**

✅ **Infrastructure**: Complete and tested  
✅ **Experiment Framework**: Production-ready  
✅ **Logging & Monitoring**: Fully integrated  
✅ **Documentation**: Comprehensive guides  
⚠️ **Performance**: Agent optimization needed  
⚠️ **Staging Validation**: Pending staging deployment  

**Next Step**: Deploy to staging environment and validate with real traffic! 🚀
