# 🎯 **MERID PHASE 0 - OPERATIONAL TRIAL GUIDE**

## ✅ **TIME-BOXED TRIAL STRATEGY READY**

Perfect! The architecture is complete and safe. Now it's time for the operational Phase 0 trial with real governance behavior under controlled risk. This guide provides the complete operational workflow for running a 4-6 week trial with evidence-based iteration.

---

## 📋 **TRIAL CONFIGURATION**

### **✅ Trial Parameters**
```python
TrialConfiguration:
    trial_duration_weeks: 6
    scoped_models: ["crypto_prediction_agent_v1", "arbitrage_analyst_v2"]
    governance_mode: "recommendation_only"  # No auto-execution
    
    # Success criteria
    minimum_alignment_rate: 0.7      # 70% system-human alignment
    minimum_contract_compliance: 0.95  # 95% contract test compliance
    minimum_total_decisions: 12        # 2 models × 6 weeks
    
    # Conservative risk limits
    max_notional_per_model: 50000      # $50K per model
    max_daily_volume_per_model: 200000 # $200K per model
    allowed_tiers: ["tier_3", "tier_4"]  # No Tier 1-2
```

### **✅ Environment Setup**
```bash
# Core Phase 0 flags
export MERID_ENV=local
export MERID_PHASE0_ENABLED=true
export MERID_PHASE0_MODEL_IDS=crypto_prediction_agent_v1,arbitrage_analyst_v2
export MERID_FEATURE_BRIER_GOVERNANCE=true
export MERID_FEATURE_MINIMAL_SCOPE=true

# Safety controls
export MERID_PHASE0_CONTRACT_ENFORCE=true
export GOVERNANCE_DRY_RUN=true  # Recommendation-only mode
export MERID_AUDITOR_MODE=NORMAL
export MERID_LOG_LEVEL=DEBUG
```

---

## 🚀 **TRIAL WORKFLOW**

### **✅ Week 0: Trial Setup**
```bash
# 1. Start the Phase 0 trial
curl -X POST http://localhost:8000/api/v1/phase0/trial/start \
  -H "Content-Type: application/json" \
  -d '{"duration_weeks": 6}'

# Expected response:
# {
#   "success": true,
#   "trial": {
#     "trial_period": {
#       "start_date": "2024-01-24T10:00:00Z",
#       "end_date": "2024-03-06T10:00:00Z",
#       "duration_weeks": 6
#     },
#     "scoped_models": ["crypto_prediction_agent_v1", "arbitrage_analyst_v2"],
#     "governance_mode": "recommendation_only"
#   },
#   "message": "Phase 0 trial started successfully"
# }
```

### **✅ Weekly Operations (Weeks 1-6)**
```bash
# 1. Get current system recommendations
curl http://localhost:8000/api/v1/minimal/scorecards

# 2. Record human decision for each model
curl -X POST http://localhost:8000/api/v1/phase0/trial/record-weekly-decision \
  -H "Content-Type: application/json" \
  -d '{
    "model_id": "crypto_prediction_agent_v1",
    "human_decision": "hold",
    "decision_reason": "Strong performance but need more data points before promotion"
  }'

curl -X POST http://localhost:8000/api/v1/phase0/trial/record-weekly-decision \
  -H "Content-Type: application/json" \
  -d '{
    "model_id": "arbitrage_analyst_v2",
    "human_decision": "hold",
    "decision_reason": "Moderate performance, waiting for stability improvement"
  }'

# 3. Check trial status
curl http://localhost:8000/api/v1/phase0/trial/status

# 4. Verify contract compliance
curl http://localhost:8000/api/v1/minimal/contract-tests
```

### **✅ Weekly Monitoring**
```bash
# Check alignment analysis
curl http://localhost:8000/api/v1/phase0/trial/alignment-analysis

# Check contract compliance
curl http://localhost:8000/api/v1/phase0/trial/contract-compliance

# Get trial summary
curl http://localhost:8000/api/v1/phase0/trial/trial-summary

# Health check
curl http://localhost:8000/api/v1/phase0/trial/health
```

---

## 📊 **DECISION RECORDING EXAMPLES**

### **✅ Week 1: Conservative Start**
```json
{
  "model_id": "crypto_prediction_agent_v1",
  "system_recommendation": "promote",
  "human_decision": "hold",
  "decision_reason": "Strong BSS (0.12) but limited history (150 events). Need more data before Tier 2.",
  "alignment": false,
  "contract_tests_passed": true
}
```

### **✅ Week 2: Pattern Recognition**
```json
{
  "model_id": "arbitrage_analyst_v2",
  "system_recommendation": "hold",
  "human_decision": "hold",
  "decision_reason": "System recommendation aligns with expert judgment. TTC calibration needs more stability.",
  "alignment": true,
  "contract_tests_passed": true
}
```

### **✅ Week 3: Performance Concerns**
```json
{
  "model_id": "crypto_prediction_agent_v1",
  "system_recommendation": "promote",
  "human_decision": "hold",
  "decision_reason": "Recent degradation in Brier score (0.18 → 0.22). Wait for recovery.",
  "alignment": false,
  "contract_tests_passed": true
}
```

---

## 📈 **MONITORING AND ANALYSIS**

### **✅ Alignment Tracking**
```bash
# Get alignment analysis
curl http://localhost:8000/api/v1/phase0/trial/alignment-analysis

# Expected response structure:
{
  "success": true,
  "analysis": {
    "overall_alignment": {
      "total_decisions": 12,
      "aligned_decisions": 9,
      "alignment_rate": 0.75
    },
    "model_alignment": {
      "crypto_prediction_agent_v1": {
        "total_decisions": 6,
        "aligned_decisions": 4,
        "alignment_rate": 0.67
      },
      "arbitrage_analyst_v2": {
        "total_decisions": 6,
        "aligned_decisions": 5,
        "alignment_rate": 0.83
      }
    },
    "override_patterns": {
      "promote_to_hold": 4,
      "hold_to_promote": 1,
      "demote_to_hold": 1
    }
  }
}
```

### **✅ Contract Compliance Monitoring**
```bash
# Get contract compliance
curl http://localhost:8000/api/v1/phase0/trial/contract-compliance

# Expected response structure:
{
  "success": true,
  "compliance": {
    "overall_compliance": {
      "total_decisions": 12,
      "compliant_decisions": 12,
      "compliance_rate": 1.0
    },
    "model_compliance": {
      "crypto_prediction_agent_v1": {
        "total_decisions": 6,
        "compliant_decisions": 6,
        "compliance_rate": 1.0
      },
      "arbitrage_analyst_v2": {
        "total_decisions": 6,
        "compliant_decisions": 6,
        "compliance_rate": 1.0
      }
    },
    "failed_tests": {},
    "recent_failures": []
  }
}
```

---

## 🎯 **TRIAL COMPLETION AND ANALYSIS**

### **✅ Week 6: Trial Completion**
```bash
# Complete the trial
curl -X POST http://localhost:8000/api/v1/phase0/trial/complete

# Expected response:
{
  "success": true,
  "results": {
    "trial_configuration": { ... },
    "decision_analysis": {
      "total_decisions": 12,
      "alignment_rate": 0.75,
      "contract_compliance_rate": 1.0
    },
    "success_determination": {
      "trial_successful": true,
      "recommendations": [
        "Trial successful - ready to expand scope",
        "Consider adding third model to Phase 1",
        "Evaluate limited auto-promotion for Tier 2"
      ],
      "next_phase_config": {
        "phase": "phase1",
        "governance_mode": "limited_auto_execution",
        "scoped_models": ["crypto_prediction_agent_v1", "arbitrage_analyst_v2"],
        "risk_limits": {
          "max_notional_per_model": 100000,
          "allowed_tiers": ["tier_2", "tier_3", "tier_4"]
        }
      }
    }
  }
}
```

---

## 🔄 **EVIDENCE-BASED ITERATION**

### **✅ Success Criteria Evaluation**
```python
# Success determination logic
trial_successful = (
    alignment_rate >= 0.7 and           # 70%+ alignment
    contract_compliance_rate >= 0.95 and  # 95%+ contract compliance
    total_decisions >= 12               # Minimum decisions
)
```

### **✅ Evidence-Based Recommendations**

#### **If Trial Successful:**
- **Expand Scope**: Add third model to Phase 1
- **Loosen Constraints**: Increase risk limits (Tier 2 allowed)
- **Limited Automation**: Enable auto-promotion for Tier 2
- **Continue Monitoring**: Maintain human oversight for demotion

#### **If Trial Fails (Alignment < 70%):**
- **Threshold Adjustment**: Lower BSS threshold from 0.05 to 0.03
- **Model Review**: Investigate low-alignment models
- **Extend Trial**: Additional 2-4 weeks with adjusted parameters
- **Human Training**: Review decision patterns with governance team

#### **If Trial Fails (Contract Compliance < 95%):**
- **Contract Review**: Investigate failing contract tests
- **Safety Analysis**: Review if constraints are too strict
- **Bug Investigation**: Check for contract test implementation issues
- **Risk Assessment**: Evaluate if safety constraints are appropriate

### **✅ Next Phase Configuration**
```python
# Phase 1 configuration (if successful)
next_phase_config = {
    "phase": "phase1",
    "governance_mode": "limited_auto_execution",
    "scoped_models": ["crypto_prediction_agent_v1", "arbitrage_analyst_v2", "third_model_v1"],
    "risk_limits": {
        "max_notional_per_model": 100000,  # $100K per model
        "max_daily_volume_per_model": 400000,  # $400K per model
        "allowed_tiers": ["tier_2", "tier_3", "tier_4"]  # Still no Tier 1
    },
    "auto_execution": {
        "allow_auto_promotion": True,
        "allow_auto_demotion": False,
        "require_human_review": True
    },
    "success_criteria": {
        "minimum_alignment_rate": 0.75,
        "minimum_contract_compliance": 0.98,
        "minimum_total_decisions": 20
    }
}
```

---

## 📋 **OPERATIONAL CHECKLIST**

### **✅ Pre-Trial Setup**
- [ ] Environment variables configured
- [ ] Feature flags enabled
- [ ] Trial started with 6-week duration
- [ ] Risk limits applied (conservative)
- [ ] Recommendation-only mode enabled

### **✅ Weekly Operations**
- [ ] System recommendations reviewed
- [ ] Human decisions recorded for both models
- [ ] Contract tests verified
- [ ] Alignment metrics calculated
- [ ] Trial status monitored

### **✅ Trial Completion**
- [ ] All 12 decisions recorded (2 models × 6 weeks)
- [ ] Alignment rate calculated (target: ≥70%)
- [ ] Contract compliance verified (target: ≥95%)
- [ ] Evidence-based recommendations generated
- [ ] Next phase configuration prepared

### **✅ Post-Trial Actions**
- [ ] Trial results stored for audit
- [ ] Team review of alignment patterns
- [ ] Decision on Phase 1 initiation
- [ ] Configuration updates for next phase
- [ ] Documentation of lessons learned

---

## 🎯 **PRODUCTION READINESS**

### **✅ Operational Trial System**
- **Time-Boxed Trial**: ✅ 6-week trial with clear start/end dates
- **Recommendation-Only Governance**: ✅ No auto-execution, human oversight required
- **Evidence-Based Analysis**: ✅ Alignment and compliance metrics tracked
- **Risk Management**: ✅ Conservative limits with contract test enforcement
- **Complete API**: ✅ Full REST API for trial management and monitoring

### **✅ Safety and Control**
- **Feature Flags**: ✅ Instant rollback capability
- **Contract Tests**: ✅ Safety properties enforced throughout trial
- **Human Oversight**: ✅ All decisions require human approval
- **Conservative Limits**: ✅ $50K max notional per model
- **Monitoring**: ✅ Real-time alignment and compliance tracking

### **✅ Evidence-Based Iteration**
- **Clear Success Criteria**: ✅ 70% alignment, 95% compliance, 12 decisions
- **Pattern Analysis**: ✅ Override patterns and reasons tracked
- **Recommendation Engine**: ✅ Evidence-based next phase configuration
- **Audit Trail**: ✅ All decisions and metrics stored for analysis

**Status: MERID PHASE 0 OPERATIONAL TRIAL - PRODUCTION READY** 🎯

The operational trial system provides a complete, safe, and evidence-based approach to testing the governance system with real data under controlled risk. This ensures the Phase 0 experiment can be run safely, monitored effectively, and scaled confidently based on evidence-based validation and clear success criteria.
