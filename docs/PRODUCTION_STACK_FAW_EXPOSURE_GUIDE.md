# Production Stack Flaw Exposure Guide

## Overview

The `production_stack_flaw_exposure.py` script performs comprehensive end-to-end testing of the MERID 15m Kalshi crypto trading stack to expose flaws across all architectural layers. This script is based on 2026 industry best practices from:

- **Muninn**: Deterministic replay architecture for byte-identical reproducibility
- **SysTradeBench**: Build-test-patch benchmarking for trading systems
- **QUANTAF**: Enterprise-grade testing framework for financial systems
- **Low-Latency Trading Research**: 5-layer latency audit methodology

## Architecture Layers Tested

### UPSTREAM (Configuration Layer)
- Profile YAML files (`config/profiles/kalshi_crypto_15m_v2.yaml`)
- Risk limits and percentage thresholds
- Asset-specific configurations (BTC, ETH, SOL, XRP, DOGE)
- Agent defaults (max_notional_pct, max_orders_per_window, etc.)

### MIDSTREAM (Risk Envelope Layer)
- Risk envelope calculations (`merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py`)
- Profile adapter (`merid/risk/profiles/crypto_15m_profile.py`)
- Percentage-to-USD conversions
- Per-asset cap enforcement
- Agent default enforcement
- Window-based risk tracking (fixed $1.00 exposure cap per 15m window - MERID_FIXED_EXPOSURE_CAP_USD)

### DOWNSTREAM (Sizing Layer)
- Unified sizing (`merid/prediction/unified_sizing.py`)
- Position management
- Order routing
- Position size multipliers

### END-TO-END (Data Flow)
- Full signal-to-order-to-fill pipeline
- Legacy vs production module contamination
- Entry point validation (main_15m_lean vs main.py)
- Agent grid validation (agent_grid_15m vs legacy agent_grid)

## Test Categories

### 1. Data Flow Integrity
Tests for:
- Module import dependencies
- Legacy contamination in production code
- Data pipeline consistency
- Signal-to-order flow validation

### 2. Resilience and Fault Tolerance
Tests for:
- Circuit breaker implementation
- Kill switch availability
- Disaster recovery procedures
- Window exposure reset mechanisms
- Graceful degradation

### 3. Latency and Performance
Tests for:
- Module import latency
- Performance monitoring infrastructure
- Optimization mechanisms
- Tail latency analysis

### 4. Asset Tracking Consistency
Tests for:
- All 5 assets (BTC, ETH, SOL, XRP, DOGE) have agents
- Market catalog includes all assets
- Spot service fetches all assets
- Per-asset cap enforcement

### 5. Computational Load Analysis
Tests for:
- Memory usage patterns
- CPU utilization
- Object count (memory leak detection)
- Resource optimization

### 6. Configuration Consistency
Tests for:
- Profile YAML structure and validity
- Required sections present
- Window-based risk limits configured correctly
- 75c threshold alignment

### 7. Cross-Layer Consistency
Tests for:
- Profile YAML values match risk envelope defaults
- Risk envelope defaults match sizing layer behavior
- No scaling multipliers interfere with hard limits
- 3% per asset / 5% per 15m window limits respected

## Usage

### Running the Script

```bash
# From the MERID repository root
python scripts/production_stack_flaw_exposure.py
```

### Output

The script generates:
1. **Console output**: Real-time test progress and summary
2. **JSON report**: Detailed findings saved to `output/production_stack_flaw_report_YYYYMMDD_HHMMSS.json`

### Report Structure

```json
{
  "summary": {
    "total_flaws": 10,
    "total_tests": 8,
    "total_duration_seconds": 5.23,
    "passed_tests": 6,
    "failed_tests": 2
  },
  "severity_breakdown": {
    "CRITICAL": 2,
    "HIGH": 3,
    "MEDIUM": 3,
    "LOW": 2
  },
  "category_breakdown": {
    "CONFIGURATION": 3,
    "CONSISTENCY": 4,
    "ASSET_TRACKING": 2,
    "RESILIENCE": 1
  },
  "layer_breakdown": {
    "UPSTREAM": 3,
    "MIDSTREAM": 4,
    "DOWNSTREAM": 2,
    "END_TO_END": 1
  },
  "test_results": [...],
  "all_flaws": [...]
}
```

## Common Flaws Detected

### CRITICAL Flaws

#### 1. Missing Asset Configuration
**Category**: ASSET_TRACKING  
**Layer**: UPSTREAM  
**Description**: Missing asset configurations for one or more of the 5 required assets  
**Evidence**: Configured: [BTC, ETH], Required: [BTC, ETH, SOL, XRP, DOGE]  
**Recommendation**: Add configuration for all 5 assets in profile YAML

#### 2. Legacy Module Contamination
**Category**: CONSISTENCY  
**Layer**: END_TO_END  
**Description**: Legacy module loaded in production stack  
**Evidence**: merid.main in sys.modules  
**Recommendation**: Remove legacy module imports, use production equivalents (main_15m_lean)

#### 3. Window Risk Limits Misconfigured
**Category**: CONFIGURATION  
**Layer**: UPSTREAM  
**Description**: Per-agent window risk limit is 5%, expected 3%  
**Evidence**: guardrails_per_window_risk_pct.value = 0.05  
**Recommendation**: Set guardrails_per_window_risk_pct.value to 0.03 (3%)

### HIGH Flaws

#### 1. Profile Adapter Default Mismatch
**Category**: CONSISTENCY  
**Layer**: MIDSTREAM  
**Description**: agent_max_notional_pct is 5%, expected 3%  
**Evidence**: profile.agent_max_notional_pct = 0.05  
**Recommendation**: Align profile adapter default with YAML value (0.03)

#### 2. Missing Per-Asset Caps
**Category**: ASSET_TRACKING  
**Layer**: MIDSTREAM  
**Description**: Missing per-asset caps for: SOL, XRP, DOGE  
**Evidence**: asset_max_notional_usd keys: [BTC, ETH]  
**Recommendation**: Ensure all 5 assets have per-asset caps in profile YAML

#### 3. Kill Switch Not Found
**Category**: RESILIENCE  
**Layer**: END_TO_END  
**Description**: Kill switch implementation not found  
**Evidence**: ImportError when importing merid.risk.kill_switches  
**Recommendation**: Implement kill switch for emergency shutdown

### MEDIUM Flaws

#### 1. High Memory Usage
**Category**: COMPUTATIONAL_LOAD  
**Layer**: END_TO_END  
**Description**: High memory usage: 1.2 GB  
**Evidence**: memory_info.rss = 1258291200 bytes  
**Recommendation**: Investigate memory leaks, optimize data structures

#### 2. Slow Module Import
**Category**: LATENCY  
**Layer**: UPSTREAM  
**Description**: Module import took 1500ms (> 1000ms threshold)  
**Evidence**: Import time: 1500ms  
**Recommendation**: Optimize module imports, defer non-critical imports

#### 3. Circuit Breaker Not Found
**Category**: RESILIENCE  
**Layer**: END_TO_END  
**Description**: Circuit breaker implementation not found  
**Evidence**: ImportError when importing merid.hardening.circuit_breaker  
**Recommendation**: Implement circuit breaker for fault tolerance

### LOW Flaws

#### 1. High CPU Usage
**Category**: COMPUTATIONAL_LOAD  
**Layer**: END_TO_END  
**Description**: High CPU usage: 60%  
**Evidence**: process.cpu_percent() = 60%  
**Recommendation**: Optimize CPU-intensive operations, consider async processing

#### 2. Performance Optimizer Not Found
**Category**: LATENCY  
**Layer**: END_TO_END  
**Description**: Performance optimizer not found  
**Evidence**: ImportError when importing scaling.performance_optimizer  
**Recommendation**: Implement performance optimization for latency reduction

## Remediation Priorities

### Immediate Action (CRITICAL)
1. Fix missing asset configurations
2. Remove legacy module contamination
3. Correct window risk limits
4. Ensure all 5 assets have agents

### Short Term (HIGH)
1. Align profile adapter defaults with YAML
2. Implement missing per-asset caps
3. Add kill switch implementation
4. Fix cross-layer consistency issues

### Medium Term (MEDIUM)
1. Investigate memory leaks
2. Optimize module imports
3. Implement circuit breaker
4. Add disaster recovery procedures

### Long Term (LOW)
1. Optimize CPU usage
2. Implement performance optimizer
3. Add comprehensive monitoring
4. Implement advanced resilience patterns

## Integration with CI/CD

### GitHub Actions Example

```yaml
name: Production Stack Flaw Exposure

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]
  schedule:
    - cron: '0 0 * * *'  # Daily run

jobs:
  flaw_exposure:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
      - name: Run flaw exposure
        run: |
          python scripts/production_stack_flaw_exposure.py
      - name: Upload report
        if: always()
        uses: actions/upload-artifact@v3
        with:
          name: flaw-report
          path: output/production_stack_flaw_report_*.json
      - name: Check for critical flaws
        run: |
          python scripts/production_stack_flaw_exposure.py
          if [ $? -ne 0 ]; then
            echo "CRITICAL FLAWS FOUND - Failing build"
            exit 1
          fi
```

## Best Practices

### Running Before Deployment
1. Always run the script before deploying to production
2. Review CRITICAL and HIGH flaws before merging
3. Address MEDIUM flaws within the next sprint
4. Track LOW flaws for future optimization

### Regular Maintenance
1. Run weekly to catch regressions
2. Update test cases as the stack evolves
3. Add new flaw detection patterns based on incidents
4. Review and update remediation recommendations

### Team Collaboration
1. Share reports with the team for visibility
2. Assign flaws to specific owners
3. Track remediation progress in project management tools
4. Use reports to guide technical debt prioritization

## Research Sources

This script is based on 2026 industry research:

1. **Muninn** - Deterministic replay architecture for trading systems
   - Single immutable event log as source of truth
   - Byte-identical reproducibility between live and historical
   - Build-time ArchUnit rules to enforce invariants

2. **SysTradeBench** - Build-test-patch benchmark for trading systems
   - Iterative build-test-patch evaluation
   - Drift-aware diagnostics
   - Multi-dimensional scorecards (spec fidelity, risk discipline, reliability)

3. **QUANTAF** - Enterprise-grade testing framework
   - 4 concentric layers (protocol adapters, logic core, business rules, test execution)
   - NLP-powered scenario generation
   - Rich reporting with Allure

4. **Low-Latency Trading Research** - 5-layer latency audit
   - Ingress timestamp discipline and PTP drift
   - Memory topology and NUMA allocation
   - Risk layer serialization vs parallelism
   - Binary protocol adoption

5. **Market Simulation Best Practices** - Preprod testing
   - Clock model supporting event time, ingest time, exchange time
   - Deterministic replay with causality preservation
   - Tail latency focus (p99, not just mean)
   - Chaos testing with failure injection

## Limitations

1. **Static Analysis Only**: The script performs static analysis and import testing, not runtime testing
2. **No Live Market Data**: Does not test with actual market data or trading
3. **No Load Testing**: Does not simulate high-load scenarios
4. **No Network Testing**: Does not test network latency or connectivity
5. **No Database Testing**: Does not test database performance or consistency

## Future Enhancements

1. **Runtime Testing**: Add runtime testing with simulated market data
2. **Load Testing**: Add load testing with concurrent order generation
3. **Network Testing**: Add network latency and connectivity testing
4. **Database Testing**: Add database performance and consistency testing
5. **Chaos Testing**: Add chaos engineering with failure injection
6. **Deterministic Replay**: Add replay testing with historical data
7. **Property-Based Testing**: Add property-based invariant checking
8. **Continuous Monitoring**: Add continuous monitoring in production

## Support

For questions or issues:
1. Review the script output for detailed error messages
2. Check the generated JSON report for specific flaws
3. Consult the MERID documentation for architecture details
4. Review the research sources for best practices
5. Contact the development team for complex issues

## Version History

- **v1.0.0** (2026-07-08): Initial release
  - Comprehensive flaw exposure across all layers
  - Based on 2026 industry best practices
  - JSON report generation
  - CI/CD integration examples
