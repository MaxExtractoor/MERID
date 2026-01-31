# MERID Agent Lab - Production Deployment Checklist

## ✅ Pre-Flight Checklist

### 1. Infrastructure Setup
- [ ] API server running on port 8000
- [ ] Agent registered: `prediction-arbitrage-analyst-01`
- [ ] Log directory exists: `logs/`
- [ ] Experiment directory exists: `experiments/results/`

### 2. Experiment Configuration
- [ ] YAML config updated with desired variants
- [ ] Filters set to control input variance
- [ ] Runs per variant appropriate for statistical significance
- [ ] Experiment ID unique and descriptive

### 3. Analysis Tools Ready
- [ ] Log analyzer functional: `tools/analyze_agent_runs.py`
- [ ] Results directory writable
- [ ] Elasticsearch template ready (if using ES)

### 4. Monitoring Setup
- [ ] Log rotation configured (if using Docker)
- [ ] Error handling tested
- [ ] Success criteria defined

## 🚀 Quick Start Commands

### Test Agent Registration
```bash
python -c "from agents.registry import load_agents; print([a.agent_id for a in load_agents()])"
```

### Test API Endpoint
```bash
python -c "import requests; resp = requests.post('http://localhost:8000/api/v1/institutional/agents/prediction-arbitrage-analyst/analyze', params={'min_spread': 0.05}); print('Status:', resp.status_code)"
```

### Run Small Test Experiment
```bash
python tools/run_prompt_experiment.py \
  --base-url http://localhost:8000 \
  --config experiments/prompt_experiments.yaml
```

### Analyze Results
```bash
python tools/analyze_agent_runs.py --experiment-id arb-prompt-2026-01-24
```

## 📊 Success Criteria

### Experiment Success
- [ ] All runs complete without errors
- [ ] Both variants generate different Brier scores
- [ ] Statistical significance achieved (≥50 runs per variant)
- [ ] Winner clearly identified

### Analysis Success
- [ ] Log analyzer processes all runs correctly
- [ ] Brier scores calculated accurately
- [ ] Latency and error rates tracked
- [ ] Results saved to experiments/results/

### Production Readiness
- [ ] Workflow repeatable
- [ ] Results reproducible
- [ ] Documentation complete
- [ ] Team trained on process

## 🔧 Troubleshooting

### Common Issues

**404 Errors on API**
- Check server is running: `netstat -an | findstr :8000`
- Verify agent registration
- Restart server if needed

**Import Errors**
- Check dataclass field defaults
- Verify all imports in agent module
- Run `python -c "from agents.prediction_arbitrage_analyst import PredictionArbitrageAnalystAgent"`

**Log Analysis Issues**
- Verify log file path exists
- Check JSONL format is valid
- Ensure experiment IDs match exactly

**Server Crashes**
- Check uvicorn logs for errors
- Verify all imports are working
- Restart with `python -m uvicorn web.main:application --host 0.0.0.0 --port 8000`

## 📈 Scaling Guidelines

### Sample Size Recommendations
- **Exploratory**: 10-20 runs per variant
- **Validation**: 50-100 runs per variant  
- **Production**: 100+ runs per variant

### Statistical Significance
- **Minimum**: 30 runs per variant (CLT approximation)
- **Recommended**: 50+ runs per variant
- **High Confidence**: 100+ runs per variant

### Performance Considerations
- **Batch Size**: 5-10 runs per batch
- **Rate Limiting**: 1-2 seconds between runs
- **Timeout**: 30 seconds per run
- **Retry Logic**: 3 attempts max

## 🎯 Best Practices

### Experiment Design
- Keep filters consistent across variants
- Use meaningful variant names
- Document hypothesis being tested
- Set clear success criteria

### Data Management
- Archive old experiment results
- Use descriptive experiment IDs
- Store both raw logs and summary results
- Back up important findings

### Team Workflow
- Review experiment design before execution
- Document findings in shared knowledge base
- Communicate results to stakeholders
- Update agent configuration based on winners

## 🔄 Iteration Process

1. **Hypothesis**: Define what you're testing
2. **Design**: Create YAML config with variants
3. **Execute**: Run experiment with sufficient sample size
4. **Analyze**: Use CLI tool to compare results
5. **Decide**: Choose winner based on statistical evidence
6. **Implement**: Update default configuration
7. **Monitor**: Track performance over time
8. **Repeat**: Continue optimizing with new experiments
