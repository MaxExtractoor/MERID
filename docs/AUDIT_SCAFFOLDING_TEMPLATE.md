# AUDIT_SCAFFOLDING_TEMPLATE

**One-command bootstrap for audit-as-code in MERID subsystems.**

Copy this template when adding a new venue, asset class, or agent family. Replace all `{{PLACEHOLDER}}` values with specifics.

---

## 1. Document Header

```markdown
# AGENT_AUDIT_{{VENUE_NAME}}_{{ASSET_CLASS}}

**Audit specification for {{VENUE_NAME}} {{ASSET_CLASS}} pipeline.**

- **Formulas Module:** `{{MODULE_PATH}}/formulas.py`
- **Formulas Version:** `{{YYYY-MM-K1}}`
- **Audit Spec Version:** `{{YYYY-MM-A1}}`
- **Last Updated:** {{DATE}}
- **Owner:** {{TEAM/OWNER}}
```

---

## 2. Lifecycle Stages (Customize D→P for your domain)

| Stage | Responsibility | Key Modules | Invariant IDs |
|-------|---------------|-------------|---------------|
| **DISCOVER** | Find tradeable opportunities | `{{discover_module}}` | D1–D5 |
| **ANALYZE** | Signal validation/scoring | `{{analyze_module}}` | A1–A5 |
| **CONSENSUS** | Multi-agent agreement | `{{consensus_module}}` | C1–C6 |
| **SIZE** | Position calculation | `{{size_module}}` | S1–S5 |
| **EXECUTE** | Order placement | `{{execute_module}}` | E1–E5 |
| **MONITOR** | Position tracking | `{{monitor_module}}` | M1–M4 |
| **PROMOTE** | Performance attribution | `{{promote_module}}` | P1–P3 |
| **PROTECT** | Risk/circuit breakers | `{{protect_module}}` | P4–P5 |

---

## 3. Formulas (Copy from merid/formulas.py or extend)

### Core Formulas (Reuse from merid.formulas)

```python
from merid.formulas import (
    FORMULAS_VERSION as BASE_FORMULAS_VERSION,
    AUDIT_SPEC_VERSION as BASE_AUDIT_SPEC_VERSION,
    get_version_info,
    generate_correlation_id,
    parse_correlation_id,
    # Sentiment
    volume_weighted_sentiment,
    reddit_confidence,
    # Consensus
    confidence_weighted_swarm_probability,
    classify_stance,
    brier_score,
    debate_lift,
    # Sizing
    kelly_fraction,
    quarter_kelly_size,
    # Risk
    drawdown_tier_action,
    fee_aware_edge,
)
```

### Venue-Specific Extensions (Add to {{MODULE_PATH}}/formulas.py)

```python
# {{VENUE_NAME}}-specific formulas
def {{venue}}_fee_structure(notional: float) -> float:
    """{{Venue}} fee schedule."""
    ...

def {{venue}}_tick_size(symbol: str) -> float:
    """Tick size for {{venue}} symbol."""
    ...
```

---

## 4. Invariants Template (2–3 must-hold conditions per stage)

### D1–D5: DISCOVER Invariants

| ID | Invariant | Enforcement | Log Format |
|----|-----------|-------------|------------|
| D1 | {{DISCOVER_1}} | `{{location}}` | `INVARIANT_D1_FAILED: {{details}}` |
| D2 | {{DISCOVER_2}} | `{{location}}` | `INVARIANT_D2_FAILED: {{details}}` |
| D3 | {{DISCOVER_3}} | `{{location}}` | `INVARIANT_D3_FAILED: {{details}}` |
| D4 | {{DISCOVER_4}} | `{{location}}` | `INVARIANT_D4_FAILED: {{details}}` |
| D5 | {{DISCOVER_5}} | `{{location}}` | `INVARIANT_D5_FAILED: {{details}}` |

### A1–A5: ANALYZE Invariants

| ID | Invariant | Enforcement | Log Format |
|----|-----------|-------------|------------|
| A1 | {{ANALYZE_1}} | `{{location}}` | `INVARIANT_A1_FAILED: {{details}}` |
| A2 | {{ANALYZE_2}} | `{{location}}` | `INVARIANT_A2_FAILED: {{details}}` |
| A3 | {{ANALYZE_3}} | `{{location}}` | `INVARIANT_A3_FAILED: {{details}}` |
| A4 | {{ANALYZE_4}} | `{{location}}` | `INVARIANT_A4_FAILED: {{details}}` |
| A5 | {{ANALYZE_5}} | `{{location}}` | `INVARIANT_A5_FAILED: {{details}}` |

### C1–C6: CONSENSUS Invariants

| ID | Invariant | Enforcement | Log Format |
|----|-----------|-------------|------------|
| C1 | {{CONSENSUS_1}} | `{{location}}` | `INVARIANT_C1_FAILED: {{details}}` |
| C2 | {{CONSENSUS_2}} | `{{location}}` | `INVARIANT_C2_FAILED: {{details}}` |
| C3 | {{CONSENSUS_3}} | `{{location}}` | `INVARIANT_C3_FAILED: {{details}}` |
| C4 | {{CONSENSUS_4}} | `{{location}}` | `INVARIANT_C4_FAILED: {{details}}` |
| C5 | {{CONSENSUS_5}} | `{{location}}` | `INVARIANT_C5_FAILED: {{details}}` |
| C6 | {{CONSENSUS_6}} | `{{location}}` | `INVARIANT_C6_FAILED: {{details}}` |

### S1–S5: SIZE Invariants

| ID | Invariant | Enforcement | Log Format |
|----|-----------|-------------|------------|
| S1 | {{SIZE_1}} | `{{location}}` | `INVARIANT_S1_FAILED: {{details}}` |
| S2 | {{SIZE_2}} | `{{location}}` | `INVARIANT_S2_FAILED: {{details}}` |
| S3 | {{SIZE_3}} | `{{location}}` | `INVARIANT_S3_FAILED: {{details}}` |
| S4 | {{SIZE_4}} | `{{location}}` | `INVARIANT_S4_FAILED: {{details}}` |
| S5 | {{SIZE_5}} | `{{location}}` | `INVARIANT_S5_FAILED: {{details}}` |

### E1–E5: EXECUTE Invariants

| ID | Invariant | Enforcement | Log Format |
|----|-----------|-------------|------------|
| E1 | {{EXECUTE_1}} | `{{location}}` | `INVARIANT_E1_FAILED: {{details}}` |
| E2 | {{EXECUTE_2}} | `{{location}}` | `INVARIANT_E2_FAILED: {{details}}` |
| E3 | {{EXECUTE_3}} | `{{location}}` | `INVARIANT_E3_FAILED: {{details}}` |
| E4 | {{EXECUTE_4}} | `{{location}}` | `INVARIANT_E4_FAILED: {{details}}` |
| E5 | {{EXECUTE_5}} | `{{location}}` | `INVARIANT_E5_FAILED: {{details}}` |

### M1–M4: MONITOR Invariants

| ID | Invariant | Enforcement | Log Format |
|----|-----------|-------------|------------|
| M1 | {{MONITOR_1}} | `{{location}}` | `INVARIANT_M1_FAILED: {{details}}` |
| M2 | {{MONITOR_2}} | `{{location}}` | `INVARIANT_M2_FAILED: {{details}}` |
| M3 | {{MONITOR_3}} | `{{location}}` | `INVARIANT_M3_FAILED: {{details}}` |
| M4 | {{MONITOR_4}} | `{{location}}` | `INVARIANT_M4_FAILED: {{details}}` |

### P1–P5: PROMOTE/PROTECT Invariants

| ID | Invariant | Enforcement | Log Format |
|----|-----------|-------------|------------|
| P1 | {{PROMOTE_1}} | `{{location}}` | `INVARIANT_P1_FAILED: {{details}}` |
| P2 | {{PROMOTE_2}} | `{{location}}` | `INVARIANT_P2_FAILED: {{details}}` |
| P3 | {{PROMOTE_3}} | `{{location}}` | `INVARIANT_P3_FAILED: {{details}}` |
| P4 | {{PROTECT_1}} | `{{location}}` | `INVARIANT_P4_FAILED: {{details}}` |
| P5 | {{PROTECT_2}} | `{{location}}` | `INVARIANT_P5_FAILED: {{details}}` |

---

## 5. Traceability Hooks

### Correlation ID Format

```
{YYYYMMDD}_{HHMMSS}_{asset}_{timeframe}_{uuid8}
```

Example: `20260330_143022_BTC_15m_a1b2c3d4`

### Required Trace Fields per Stage

| Stage | Required Fields | Destination |
|-------|-----------------|-------------|
| DISCOVER | `correlation_id`, `formulas_version`, `audit_spec_version`, `asset`, `timeframe`, `source` | `{{discover_logger}}` |
| ANALYZE | `correlation_id`, `model_prob`, `confidence`, `sentiment_regime` | `{{analyze_logger}}` |
| CONSENSUS | `correlation_id`, `swarm_prob`, `disagreement`, `debate_id` | `{{consensus_store}}` |
| SIZE | `correlation_id`, `kelly_fraction`, `contracts`, `max_contracts` | `{{size_logger}}` |
| EXECUTE | `correlation_id`, `order_id`, `fill_price`, `fill_time` | `{{execute_logger}}` |
| MONITOR | `correlation_id`, `unrealized_pnl`, `hold_time`, `exit_trigger` | `{{monitor_logger}}` |
| PROMOTE | `correlation_id`, `realized_pnl`, `brier_score`, `promotion_action` | `{{promote_store}}` |
| PROTECT | `correlation_id`, `tier_action`, `halt_reason` | `{{protect_logger}}` |

### Trace Decorator Template

```python
from {{MODULE_PATH}}.formulas import generate_correlation_id, get_version_info

def trace_stage(stage_name: str):
    """Decorator for lifecycle stage traceability."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            corr_id = kwargs.get('correlation_id') or generate_correlation_id(
                asset=kwargs.get('asset', 'UNKNOWN'),
                timeframe=kwargs.get('timeframe', 'UNKNOWN'),
            )
            version_info = get_version_info()
            
            logger.info(
                f"[TRACE] {stage_name}_START | corr_id=%s | formulas=%s | audit_spec=%s",
                corr_id,
                version_info['formulas_version'],
                version_info['audit_spec_version'],
            )
            
            try:
                result = func(*args, **kwargs, correlation_id=corr_id)
                logger.info(f"[TRACE] {stage_name}_COMPLETE | corr_id=%s", corr_id)
                return result
            except Exception as e:
                logger.error(f"[TRACE] {stage_name}_FAILED | corr_id=%s | error=%s", corr_id, e)
                raise
        return wrapper
    return decorator
```

---

## 6. Red/Amber/Green Exit Criteria

### Stage-Level R/A/G Gates

| Stage | RED (Block) | AMBER (Caution) | GREEN (Proceed) |
|-------|-------------|-----------------|-----------------|
| DISCOVER | {{D_RED}} | {{D_AMBER}} | {{D_GREEN}} |
| ANALYZE | {{A_RED}} | {{A_AMBER}} | {{A_GREEN}} |
| CONSENSUS | {{C_RED}} | {{C_AMBER}} | {{C_GREEN}} |
| SIZE | {{S_RED}} | {{S_AMBER}} | {{S_GREEN}} |
| EXECUTE | {{E_RED}} | {{E_AMBER}} | {{E_GREEN}} |
| MONITOR | {{M_RED}} | {{M_AMBER}} | {{M_GREEN}} |
| PROMOTE | {{P_RED}} | {{P_AMBER}} | {{P_GREEN}} |
| PROTECT | {{PROT_RED}} | {{PROT_AMBER}} | {{PROT_GREEN}} |

### Aggregate Pipeline Status

```python
def aggregate_pipeline_status(stage_statuses: Dict[str, str]) -> str:
    """
    Combine stage R/A/G into overall pipeline status.
    
    Returns:
        "GREEN" - All stages green
        "AMBER" - Any stage amber, none red
        "RED" - Any stage red
    """
    if any(s == "RED" for s in stage_statuses.values()):
        return "RED"
    if any(s == "AMBER" for s in stage_statuses.values()):
        return "AMBER"
    return "GREEN"
```

---

## 7. Versioning and Change Control

### Version Constants

```python
# {{MODULE_PATH}}/formulas.py
FORMULAS_VERSION: str = "{{YYYY-MM-K1}}"
AUDIT_SPEC_VERSION: str = "{{YYYY-MM-A1}}"
```

### When to Bump Versions

| Version | Bump When | Format |
|---------|-----------|--------|
| FORMULAS_VERSION | Any formula change, new formulas, breaking signatures | `YYYY-MM-K{N}` |
| AUDIT_SPEC_VERSION | Invariant changes, trace hook changes, R/A/G threshold changes | `YYYY-MM-A{N}` |

### Change Control Process

1. **Propose** — Open PR with version bump and rationale
2. **Review** — Architecture review for formulas; Risk review for thresholds
3. **Test** — All tests in `test_{{venue}}_formulas.py` must pass
4. **Sign-off** — Update Section 11 workplan with reviewer names
5. **Merge** — Only after all checks pass
6. **Deploy** — Update running systems with new version

---

## 8. Anti-Regression Rules

### Hard Checks for Code Review

Reviewers must verify:

1. **No Custom Math** — All calculations import from `{{MODULE_PATH}}/formulas.py` or `merid.formulas`
2. **No Untraced Paths** — All decision paths include `correlation_id` in logs
3. **No Missing Invariants** — All invariants D1–P5 enforced in code
4. **No Undocumented Thresholds** — All R/A/G thresholds match Section 10

### CI Enforcement Script

```bash
#!/bin/bash
# scripts/ci_check_{{venue}}_formulas.sh

echo "=== {{VENUE}} Formula Anti-Regression Check ==="

# Check for forbidden patterns outside formulas module
FORBIDDEN=(
    "kelly_fraction\s*="
    "brier_score\s*="
    "volume_weighted_sentiment"
    "drawdown_tier_action"
)

for pattern in "${FORBIDDEN[@]}"; do
    matches=$(grep -r "$pattern" --include="*.py" {{MODULE_PATH}} \
        | grep -v "{{MODULE_PATH}}/formulas.py" \
        | grep -v "from merid.formulas import" || true)
    if [ -n "$matches" ]; then
        echo "❌ VIOLATION: $pattern found outside formulas module"
        echo "$matches"
        exit 1
    fi
done

echo "✅ All checks passed"
```

### Binding Reference Format

All code review comments must use:

```
[AGENT_AUDIT: Section X.Y] — Description of requirement
```

---

## 9. Contractor Workplan Template

```markdown
### {{VENUE_NAME}} {{ASSET_CLASS}} Pipeline — Contractor Workplan

**Formulas Version:** {{YYYY-MM-K1}}  
**Audit Spec Version:** {{YYYY-MM-A1}}  
**Contractor:** {{NAME}}  
**Date:** {{DATE}}

#### Module Checklist

| Module | Import from formulas | Invariants | Trace Hooks | R/A/G Defined | Tests | Status |
|--------|---------------------|------------|-------------|---------------|-------|--------|
| {{mod1}} | [ ] | [ ] | [ ] | [ ] | [ ] | 🔲 |
| {{mod2}} | [ ] | [ ] | [ ] | [ ] | [ ] | 🔲 |
| {{mod3}} | [ ] | [ ] | [ ] | [ ] | [ ] | 🔲 |

#### Formula Test Mapping

| Formula | Test Name | Status |
|---------|-----------|--------|
| {{formula1}} | `Test{{Name1}}.test_{{case}}` | 🔲 |
| {{formula2}} | `Test{{Name2}}.test_{{case}}` | 🔲 |

#### Sign-offs

| Role | Checklist Item | Sign-Off |
|------|---------------|----------|
| **Architecture** | All formulas match spec | [ ] |
| **Engineering** | All invariants enforced | [ ] |
| **DevOps** | Trace correlation IDs in logs | [ ] |
| **Risk** | Exit criteria approved | [ ] |
| **QA** | Integration test passes | [ ] |
```

---

## 10. Bootstrap Checklist

When creating a new venue/asset pipeline, complete this checklist:

- [ ] Create `{{MODULE_PATH}}/formulas.py` with version constants
- [ ] Create `docs/AGENT_AUDIT_{{VENUE}}_{{ASSET}}.md` from this template
- [ ] Define D1–P5 invariants for your domain
- [ ] Wire `generate_correlation_id()` at DISCOVER entry points
- [ ] Add `[AGENT_AUDIT: Section X.Y]` comments to all key modules
- [ ] Create `scripts/ci_check_{{venue}}_formulas.sh`
- [ ] Create `scripts/check_{{venue}}_version_drift.py`
- [ ] Add CI job to `.github/workflows/{{venue}}-pipeline-ci.yml`
- [ ] Create `monitoring/grafana_dashboard_{{venue}}_audit.json`
- [ ] Write `tests/test_{{venue}}_formulas_source_of_truth.py`
- [ ] Run full test suite and verify all passes
- [ ] Do spot-check: sample correlation ID, reconstruct full trace

---

## Quick Start Commands

```bash
# 1. Create formulas module
cp templates/formulas_template.py {{MODULE_PATH}}/formulas.py

# 2. Create audit spec from this template
sed 's/{{VENUE_NAME}}/YourVenue/g; s/{{ASSET_CLASS}}/YourAsset/g' \
  templates/AUDIT_SCAFFOLDING_TEMPLATE.md \
  > docs/AGENT_AUDIT_YOURVENUE_YOURASSET.md

# 3. Create test file
cp templates/test_formulas_template.py \
  tests/test_{{venue}}_formulas_source_of_truth.py

# 4. Make CI scripts executable
chmod +x scripts/ci_check_{{venue}}_formulas.sh
chmod +x scripts/check_{{venue}}_version_drift.py

# 5. Run initial checks
./scripts/ci_check_{{venue}}_formulas.sh
pytest tests/test_{{venue}}_formulas_source_of_truth.py -v
```

---

**End of Template**
