# 🎯 **MERID PHASE 0 - EXPERIMENT SPEC**

## 📅 **1. DATES AND DURATION**

**Start**: Monday Jan 26, 2026  
**Duration**: 6 weeks (42 days)  
**End**: Sunday Mar 8, 2026  

**Weekly Cadence**: Wednesdays 10:00-10:30 (Governance Board)  
**Decision Tree Execution**: Week of Mar 9 (`complete_trial.sh`)

---

## 🎯 **2. SEGMENTS AND EXPOSURE**

### **Environment Segments**
- **Segment A**: Staging / paper / shadow-live (100% Phase 0)
- **Segment B**: Production live governance (unchanged baseline)

### **Model Segments**
- **M1**: `crypto_prediction_agent_v1` (100% in trial)
- **M2**: `arbitrage_analyst_v2` (100% in trial)

### **Exposure Mode**
- **Governance Decisions**: 100% through Phase 0 pipeline (recommendation-only)
- **Trading Impact**: 0% incremental risk (existing manual controls maintained)

---

## 🚀 **3. FEATURE FLAG ROLLOUT**

### **Core Flags**
```bash
PHASE0_MINIMAL_SCOPE_ENABLED=true     # Gate minimal scope APIs
PHASE0_HUMAN_REVIEW_REQUIRED=true      # Must be true for Phase 0
PHASE0_CONTRACT_TEST_ENFORCED=true     # Safety contracts enforced
GOVERNANCE_DRY_RUN=true                # Recommendation-only mode
```

### **Rollout Phases**

**Pre-Trial (Day -1)**
- Deploy code, all flags OFF → identical behavior

**Trial Start (Day 0)**
```bash
# Turn on Phase 0
export PHASE0_MINIMAL_SCOPE_ENABLED=true
export MERID_PHASE0_ENABLED=true
export PHASE0_HUMAN_REVIEW_REQUIRED=true
export PHASE0_CONTRACT_TEST_ENFORCED=true
export GOVERNANCE_DRY_RUN=true

# Start trial
curl -X POST http://localhost:8000/api/v1/phase0/trial/start \
  -H "Content-Type: application/json" \
  -d '{"duration_weeks": 6}'
```

**Mid-Trial (Weekly Board Only)**
- Adjust non-risk flags only if needed
- Contract issues: `PHASE0_CONTRACT_TEST_ENFORCED=false` (log only)
- Log noise: toggle `GOVERNANCE_DEBUG_LOGGING`

**End of Trial**
- Keep flags on until `complete_trial.sh` executed
- Phase 1 (if approved): `PHASE1_EXPANDED_SCOPE_ENABLED=true`

---

## 📊 **4. MONITORING AND ALERTS**

### **Core Metrics**
- **Alignment Rate**: `human_decision == system_recommendation` (target ≥70%)
- **Contract Compliance**: All safety contracts pass (target ≥95%)
- **Decision Count**: Total governance decisions (target ≥12)
- **Trial Progress**: % of planned weeks/decisions

### **Alert Thresholds**
```bash
# Contract compliance
if contract_compliance_rate < 0.9: ALERT

# Alignment (early warning)
if alignment_rate < 0.6 after week 3: ALERT
if alignment_rate < 0.5 at any time: CRITICAL

# Decision volume
if decisions < (2 * week_number): ALERT

# System health
if phase0_endpoint_5xx_rate > 1%: ALERT
if median_latency > 500ms: ALERT
```

### **Monitoring Commands**
```bash
# Weekly status
./weekly_phase0_status.sh

# Real-time checks
curl http://localhost:8000/api/v1/phase0/trial/status
curl http://localhost:8000/api/v1/phase0/trial/alignment-analysis
curl http://localhost:8000/api/v1/phase0/trial/contract-compliance
```

---

## 🔄 **5. ROLLBACK PROCEDURES**

### **Rollback Triggers**
- Phase 0 endpoints cause widespread errors (5xx spike)
- Contract tests misbehaving (false failures blocking governance)
- Trial behavior confusing core operations

### **Rollback Levers**

**Soft Rollback (keep metrics, stop influence)**
```bash
export GOVERNANCE_DRY_RUN=true
export GOVERNANCE_ALLOW_AUTO_PROMOTION=false
export GOVERNANCE_ALLOW_AUTO_DEMOTION=false
# Effect: governance logic runs but only logs
```

**Hard Rollback (turn off experiment)**
```bash
export PHASE0_MINIMAL_SCOPE_ENABLED=false
export MERID_PHASE0_ENABLED=false
# Effect: models revert to existing manual governance
```

**Contract Test Mitigation**
```bash
export PHASE0_CONTRACT_TEST_ENFORCED=false
# Effect: log failures but don't block
```

### **Rollback Procedure**
1. **Detect** via alerts or weekly board
2. **Decide scope**: soft vs hard rollback
3. **Flip flags** using config management
4. **Verify** with `/phase0/trial/status`
5. **Analyze** logs and stored decisions
6. **Decide** on restart or policy iteration

---

## 📋 **6. WEEKLY GOVERNANCE BOARD**

### **Meeting Structure (30 minutes)**
1. **Status Check (5 min)**
   - Trial status, progress, health
   - `./weekly_phase0_status.sh`

2. **Metrics Review (10 min)**
   - Alignment rate and trends
   - Contract compliance status
   - Override patterns and reasons

3. **Decision Making (10 min)**
   - Model promotion/demotion decisions
   - Threshold adjustments (if needed)
   - Policy changes (if needed)

4. **Recording (5 min)**
   - `./record_decisions.sh`
   - Verify decisions recorded

### **Decision Recording**
```bash
# Record decisions for both models
./record_decisions.sh

# Verification
curl http://localhost:8000/api/v1/phase0/trial/weekly-decisions
```

---

## 🎯 **7. SUCCESS CRITERIA**

### **Primary Success Metrics**
- **Alignment Rate**: ≥70% overall, ≥60% per model
- **Contract Compliance**: ≥95% overall, no critical failures
- **Decision Volume**: ≥12 total decisions (2 models × 6 weeks)

### **Guardrails**
- **Model Performance**: Brier/BSS not worsening >20% vs baseline
- **System Health**: 5xx rate <1%, latency <500ms

### **Decision Tree**
```bash
# Success Path (≥70% alignment, ≥95% compliance, ≥12 decisions)
✅ Add third model to Phase 1
✅ Loosen risk limits (Tier 2 allowed)
✅ Enable limited auto-promotion
✅ Continue with Phase 1

# Failure Path (any criteria not met)
❌ No model additions
❌ Maintain recommendation-only mode
✅ Adjust thresholds based on evidence
✅ Run 4-week iteration trial
✅ Continue until success criteria met
```

---

## 🚀 **8. EXECUTION COMMANDS**

### **Start Trial**
```bash
# Environment setup
export MERID_ENV=local
export MERID_PHASE0_ENABLED=true
export MERID_PHASE0_MODEL_IDS=crypto_prediction_agent_v1,arbitrage_analyst_v2
export MERID_FEATURE_BRIER_GOVERNANCE=true
export MERID_FEATURE_MINIMAL_SCOPE=true
export MERID_PHASE0_CONTRACT_ENFORCED=true
export GOVERNANCE_DRY_RUN=true
export MERID_LOG_LEVEL=DEBUG

# Start trial
curl -X POST http://localhost:8000/api/v1/phase0/trial/start \
  -H "Content-Type: application/json" \
  -d '{"duration_weeks": 6}'
```

### **Weekly Operations**
```bash
# Weekly status
./weekly_phase0_status.sh

# Weekly decisions
./record_decisions.sh

# Health check
curl http://localhost:8000/api/v1/phase0/trial/health
```

### **Complete Trial**
```bash
# Complete trial and execute decision tree
./complete_trial.sh
```

---

## 📊 **9. SUCCESS TRACKING**

### **Weekly Success Indicators**
```bash
# Check if on track
ALIGNMENT=$(curl -s http://localhost:8000/api/v1/phase0/trial/alignment-analysis | jq -r '.analysis.overall_alignment.alignment_rate')
COMPLIANCE=$(curl -s http://localhost:8000/api/v1/phase0/trial/contract-compliance | jq -r '.compliance.overall_compliance.compliance_rate')
DECISIONS=$(curl -s http://localhost:8000/api/v1/phase0/trial/status | jq -r '.current_metrics.total_decisions')

# Success indicators
if (( $(echo "$ALIGNMENT >= 0.7" | bc -l) && $(echo "$COMPLIANCE >= 0.95" | bc -l) && [ $DECISIONS -ge $(expr $(date +%U) \* 2) ])); then
    echo "🟢 ON TRACK"
else
    echo "🟡 NEEDS ATTENTION"
fi
```

### **End-of-Trial Decision**
```bash
# Complete trial and execute decision tree
./complete_trial.sh

# Will automatically execute pre-committed outcomes:
# - SUCCESS: Add model, loosen limits, enable auto-promotion
# - FAILURE: Policy iteration, adjust thresholds, retry trial
```

---

## 🎯 **10. NEXT STEPS**

### **Immediate Actions**
1. **Set environment variables** (above)
2. **Start trial** with `/phase0/trial/start`
3. **Schedule weekly governance meetings** (Wednesdays 10:00-10:30)
4. **Begin weekly cadence** with status and decision recording

### **Weekly Discipline**
- **Only use three canonical endpoints** for decision-making
- **No off-cycle tweaks** - all changes wait for weekly meeting
- **Record all decisions** with reasons
- **Follow pre-committed decision tree** at trial completion

### **Success Path**
- **If successful**: Phase 1 with expanded scope and limited auto-promotion
- **If failed**: Policy iteration with adjusted thresholds and shorter retry

---

**Status: MERID PHASE 0 EXPERIMENT SPEC - EXECUTION READY** 🎯

This one-page spec provides everything needed to execute the 6-week Phase 0 trial with clear dates, segments, flags, monitoring, and rollback procedures. The architecture is complete, the scripts are ready, and the discipline framework is established.

**Next Step: Execute the environment setup and trial start commands to begin the 6-week Phase 0 experiment.**
