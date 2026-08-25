# Comprehensive Exit Policy Audit Script

## Overview

This script performs a deep audit of the exit policy system and trading pipeline to expose flaws, validate synchronization, and test end-to-end execution. It implements industry best practices from:

- **AgentRails**: Deterministic policy validation
- **PolicyGate Capital**: Runtime capital governance  
- **QUANTAF**: End-to-end transaction lifecycle validation
- **NautilusTrader**: Execution testing specifications

## Architecture

The script validates across four pipeline layers:

1. **Upstream Layer**: Signal generation, edge computation, candidate selection
2. **Midstream Layer**: Order routing, risk checks, execution guards
3. **Downstream Layer**: Position monitoring, exit policy enforcement, settlement
4. **End-to-End**: Full pipeline from signal to exit

## Features

### 1. Flaw Detection
- **Static Code Analysis**: Missing imports, enum coverage gaps, dead code, inconsistent naming, magic numbers
- **Runtime Analysis**: Position field validation, edge population checks, TP/SL config validation
- **Configuration Analysis**: Profile consistency, risk limit sanity checks
- **Regression Testing**: Automatic detection of known issues from AGENTS.md

### 2. Synchronization Validation
- Validates enum consistency between components (ExitReason, ExitAction, etc.)
- Checks dataclass field consistency across modules
- Verifies function signature compatibility
- Tests component pair synchronization across the pipeline

### 3. Exit Policy Trigger Testing
- Tests all exit trigger conditions:
  - Take Profit
  - Stop Loss
  - Time Stop
  - Edge Decay
  - Risk Kill Switch
  - Stale Data
  - Settlement Guard (T-30s forced exit)

### 4. End-to-End Pipeline Testing
- Signal to exit path validation
- Order routing path verification
- Position lifecycle testing

## Usage

### Basic Usage

```bash
# Run full audit (all layers and tests)
python scripts/comprehensive_exit_policy_audit.py --mode full --output output/exit_audit/

# Run flaw detection only
python scripts/comprehensive_exit_policy_audit.py --mode flaw_detection --severity critical --output output/exit_audit/

# Run synchronization validation only
python scripts/comprehensive_exit_policy_audit.py --mode sync_validation --output output/exit_audit/

# Run exit policy trigger tests only
python scripts/comprehensive_exit_policy_audit.py --mode exit_policy_only --output output/exit_audit/

# Run end-to-end tests only
python scripts/comprehensive_exit_policy_audit.py --mode e2e_testing --output output/exit_audit/
```

### Filter by Severity

```bash
# Only critical flaws
python scripts/comprehensive_exit_policy_audit.py --mode flaw_detection --severity critical --output output/exit_audit/

# High and critical flaws
python scripts/comprehensive_exit_policy_audit.py --mode flaw_detection --severity high --output output/exit_audit/
```

### Audit Modes

- `full`: Complete audit of all layers (default)
- `sync_validation`: Focus on synchronization issues
- `flaw_detection`: Focus on flaw detection
- `e2e_testing`: End-to-end pipeline testing
- `exit_policy_only`: Exit policy specific audit

## Output

The script generates three output files:

1. **JSON Report**: `audit_YYYYMMDD_HHMMSS.json` - Machine-readable full report
2. **Markdown Report**: `audit_YYYYMMDD_HHMMSS.md` - Human-readable summary
3. **CSV Flaws**: `audit_YYYYMMDD_HHMMSS_flaws.csv` - Flaws in CSV format for analysis

## Test Results

### Recent Test Run (2026-08-08)

**Executive Summary:**
- **Total Flaws**: 81
  - Critical: 0
  - High: 1
  - Medium: 3
  - Low: 77
- **Sync Issues**: 2
- **Exit Policy Tests**: 7 passed, 0 failed
- **E2E Tests**: 3 passed, 0 failed

### Key Findings

#### High Severity Issues
1. **Missing import: math** in `merid/loop_15m.py`
   - This is a known issue (strike price validation)
   - Remediation: Add `import math` to `merid/loop_15m.py`

#### Medium Severity Issues
1. **ExitReason enum coverage gap** in unified_exit_policy_engine
   - Missing 10 enum values compared to exit_policy module
   - Remediation: Add missing ExitReason values to unified_exit_policy_engine

2. **entry_edge_pct not populated** (REGRESSION)
   - Position.entry_edge_pct field not being populated from intent.edge_pct
   - This is a known issue that has recurred
   - Remediation: Wire entry_edge_pct from intent.edge_pct in position_cache.py and fills_ledger.py

#### Synchronization Issues
1. **unified_exit_policy_engine <-> exit_policy**: Policy layer consistency (enum drift)
2. **loop_15m <-> position_monitor**: Loop to monitor state sync

#### Exit Policy Tests
All 7 exit policy trigger tests passed:
- take_profit_trigger ✓
- stop_loss_trigger ✓
- time_stop_trigger ✓
- edge_decay_trigger ✓
- risk_kill_switch_trigger ✓
- stale_data_trigger ✓
- settlement_guard_trigger ✓

#### E2E Tests
All 3 end-to-end tests passed:
- signal_to_exit_path ✓
- order_routing_path ✓
- position_lifecycle ✓

## Known Issues Detection

The script includes regression testing for known issues from AGENTS.md:

- `exit_policy_dead_thesis_side`: Position missing thesis_side field (CRITICAL)
- `dynamic_tp_zone_config`: Dynamic TP zone config had targets below entry (CRITICAL)
- `year_rollover_bug`: Ticker parsing assumed current year (HIGH)
- `side_price_inversion`: Side/price inversion for NO-side fills (CRITICAL)
- `entry_edge_pct_not_populated`: entry_edge_pct not populated from signal edge (MEDIUM)
- `strike_validation_import`: Strike price validation missing import math (HIGH)

## Integration with CI/CD

### Exit Codes

The script returns appropriate exit codes for CI/CD integration:

- `0`: Success (no critical or high severity flaws)
- `1`: Critical flaws detected (immediate action required)
- `2`: High severity flaws detected (action recommended)

### Example CI Integration

```yaml
# Example GitHub Actions workflow
- name: Run Exit Policy Audit
  run: |
    python scripts/comprehensive_exit_policy_audit.py --mode full --output output/exit_audit/
  
- name: Upload Audit Results
  if: always()
  uses: actions/upload-artifact@v3
  with:
    name: exit-policy-audit
    path: output/exit_audit/
```

## Design Principles

### Deterministic Validation
- All checks are deterministic and reproducible
- No randomness or probabilistic validation
- Clear pass/fail criteria

### Evidence-Based Reporting
- Every flaw includes evidence
- Clear remediation steps
- Source code location references

### Layered Architecture
- Clear separation between upstream, midstream, downstream
- Independent validation of each layer
- Cross-layer synchronization checks

### Regression Prevention
- Automatic detection of known issues
- Comparison against historical fixes
- Early warning for recurring problems

## Extensibility

### Adding New Flaw Checks

```python
async def _check_your_custom_flaw(self) -> List[Flaw]:
    """Your custom flaw check."""
    flaws = []
    
    # Your validation logic here
    if some_condition:
        flaws.append(Flaw(
            flaw_id="your_custom_flaw",
            title="Your Custom Flaw",
            description="Description of the flaw",
            severity=Severity.MEDIUM,
            layer=Layer.MIDSTREAM,
            component="your_component",
            location="file:line",
            evidence={"key": "value"},
            remediation="How to fix it"
        ))
    
    return flaws
```

### Adding New Exit Policy Tests

```python
async def _test_your_exit_trigger(self) -> ExitPolicyTestResult:
    """Your custom exit trigger test."""
    # Your test logic here
    return ExitPolicyTestResult(
        test_name="your_trigger",
        exit_reason="your_reason",
        should_trigger=True,
        did_trigger=True,
        test_passed=True,
        position_state={},
        market_state={},
        expected_action="exit_market",
        actual_action="exit_market",
    )
```

## Troubleshooting

### Import Errors
If you encounter import errors, ensure:
1. You're running from the project root directory
2. The project root is in your Python path
3. All dependencies are installed

### Module Loading Issues
The script uses safe imports with graceful fallbacks. If a module can't be imported, it will be logged but won't fail the entire audit.

### Performance Considerations
- Full audit typically completes in 3-5 seconds
- Flaw detection mode is fastest (~0.1s)
- Sync validation requires module loading (~1-2s)
- E2E tests are simulated (not actual execution)

## Future Enhancements

Potential improvements for future versions:

1. **Actual E2E Testing**: Replace simulated tests with real execution in test environment
2. **Historical Analysis**: Analyze historical trade logs for exit policy effectiveness
3. **Performance Profiling**: Add timing analysis for exit policy evaluation
4. **Configuration Validation**: Deep YAML schema validation for profile configs
5. **Live Monitoring**: Continuous monitoring mode for production systems
6. **Alerting Integration**: Integration with PagerDuty, Slack, etc. for critical flaws

## Contributing

When adding new checks or tests:

1. Follow the existing patterns for flaw detection
2. Include clear evidence and remediation steps
3. Add appropriate severity levels
4. Update this README with new capabilities
5. Test against known issues to ensure no regressions

## License

This script is part of the MERID project and follows the same license terms.

## Contact

For questions or issues with the audit script, please refer to the main MERID documentation or contact the development team.
