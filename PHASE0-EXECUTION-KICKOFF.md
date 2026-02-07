# PHASE 0 EXECUTION KICKOFF GUIDE

## 🚀 **START THE 6-WEEK TRIAL**

### **✅ Environment Setup**
```bash
# Set Phase 0 environment variables
export MERID_ENV=local
export MERID_PHASE0_ENABLED=true
export MERID_PHASE0_MODEL_IDS=crypto_prediction_agent_v1,arbitrage_analyst_v2
export MERID_FEATURE_BRIER_GOVERNANCE=true
export MERID_FEATURE_MINIMAL_SCOPE=true
export MERID_PHASE0_CONTRACT_ENFORCE=true
export GOVERNANCE_DRY_RUN=true
export MERID_LOG_LEVEL=DEBUG
```

### **✅ Start the Trial**
```bash
# Start the 6-week Phase 0 trial
curl -X POST http://localhost:8000/api/v1/phase0/trial/start \
  -H "Content-Type: application/bash" \
  -d '{"duration_weeks": 6}'
```

### **✅ Verify Setup**
```bash
# Verify trial is active
curl http://localhost:8000/api/v1/phase0/trial/status

# Verify minimal scope is working
curl http://localhost:8000/api/v1/minimal/scorecards

# Verify health
curl http://localhost:8000/api/v1/phase0/trial/health
```

---

## 📋 **WEEKLY GOVERNANCE CADENCE**

### **✅ Weekly Meeting (30 Minutes)**
```bash
# 1. Status check (5 minutes)
./weekly_phase0_status.sh

# 2. Governance meeting (20 minutes)
# Review metrics from canonical endpoints
# Discuss patterns and trends
# Make decisions for both models
# Any threshold/policy changes

# 3. Record decisions (5 minutes)
./record_decisions.sh

# 4. Status update (5 minutes)
./weekly_phase0_status.sh
```

### **✅ Weekly Scripts Usage**
```bash
# Make scripts executable
chmod +x weekly_phase0_status.sh
chmod +x record_decisions.sh
chmod +x complete_trial.sh

# Run weekly status
./weekly_phase0_status.sh

# Record weekly decisions
./record_decisions.sh
```

---

## 🎯 **EXECUTION DISCIPLINE**

### **✅ Single Source of Truth**
- **Only use three canonical endpoints**: status, alignment-analysis, contract-compliance
- **No individual scorecard analysis** - focus on aggregate metrics
- **No side channels** - all decisions recorded through formal process

### **✅ Change-Approval Board**
- **Weekly 30-minute meeting is sacred** - no rescheduling
- **No off-cycle tweaks** - all changes must wait for weekly meeting
- **All changes recorded** - including threshold adjustments with reasons

### **✅ Pre-Committed Outcomes**
- **Success (≥70% alignment, ≥95% compliance, ≥12 decisions)**:
  - Add third model to Phase 1
  - Loosen risk limits (Tier 2 allowed)
  - Enable limited auto-promotion
  - Continue with Phase 1

- **Failure (any criteria not met)**:
  - No model additions
  - Maintain recommendation-only mode
  - Adjust thresholds based on evidence
  - Run 4-week iteration trial
  - Continue until success criteria met

### **✅ No Silent Manual Governance**
- **Never revert to manual governance**
- **Never ignore evidence-based recommendations**
- **All changes must follow pre-committed decision tree**

---

## 📊 **SUCCESS TRACKING**

### **✅ Weekly Success Indicators**
```bash
# Success probability calculation
ALIGNMENT=$(curl -s http://localhost:8000/api/v1/phase0/trial/alignment-analysis | jq -r '.analysis.overall_alignment.alignment_rate')
COMPLIANCE=$(curl -s http://localhost:8000/api/v1/phase0/trial/contract-compliance | jq -r '.compliance.overall_compliance.compliance_rate')
DECISIONS=$(curl -s http://localhost:8000/api/v1/phase0/trial/status | jq -r '.current_metrics.total_decisions')

# Success indicators
if (( $(echo "$ALIGNMENT >= 0.7" | bc -l) && $(echo "$COMPLIANCE >= 0.95" | bc -l) && [ $DECISIONS -ge $(expr $(date +%U) \* 2) ]); then
    echo "🟢 ON TRACK"
else
    echo "🟡 NEEDS ATTENTION"
fi
```

### **✅ End-of-Trial Decision**
```bash
# Complete trial and execute decision tree
./complete_trial.sh

# Will automatically execute pre-committed outcomes:
# - SUCCESS: Add model, loosen limits, enable auto-promotion
# - FAILURE: Policy iteration, adjust thresholds, retry trial
```

---

## 🚀 **READY FOR EXECUTION**

### **✅ Complete Execution Package**
- **Trial Management**: ✅ `core/phase0_trial.py` with 6-week trial logic
- **API Endpoints**: ✅ `web/api/phase0_trial_api.py` with canonical endpoints
- **Execution Scripts**: ✅ Weekly status, decision recording, trial completion
- **Integration**: ✅ Integrated with main application and feature flags

### **✅ Minimal, Focused Execution**
- **Three Endpoints Only**: ✅ Status, alignment-analysis, contract-compliance
- **Weekly Cadence**: ✅ 30-minute governance meetings
- **Pre-Committed Outcomes**: ✅ Clear success/failure decision tree
- **No Side Channels**: ✅ Single source of truth enforcement

### **✅ Evidence-Based Scaling**
- **Clear Success Criteria**: ✅ 70% alignment, 95% compliance, 12 decisions
- **Pattern Analysis**: ✅ Override patterns and reason categorization
- **Decision Tree**: ✅ Automated execution of pre-committed outcomes
- **Audit Trail**: ✅ Complete record of all decisions and metrics

**Status: MERID PHASE 0 EXECUTION KICKOFF - PRODUCTION READY** 🎯

The execution kickoff guide provides everything needed to start the 6-week Phase 0 trial immediately. The architecture is complete, the scripts are ready, and the discipline framework is established. The value now comes from running this exact plan end-to-end and letting the evidence drive the next phase decisions.

**Next Step: Start the trial by running the environment setup and trial start commands above.**
