# 🎯 **MERID PHASE 0B - TECHNICAL RE-MEASUREMENT**

## 📅 **TRIAL SPECIFICATION**

**Duration**: 4 weeks  
**Start Date**: March 7, 2026  
**End Date**: April 4, 2026  
**Models**: crypto_prediction_agent_v1, arbitrage_analyst_v2  
**Governance Mode**: Recommendation-only  

---

## 🚀 **OBJECTIVE**

**Primary**: Fix data persistence and generate real metrics  
**Secondary**: Validate governance process with persisted data  
**Tertiary**: Generate evidence-based Phase 1 decision  

---

## 📋 **TECHNICAL FIXES REQUIRED**

### **✅ Data Persistence Path**
- **API**: `/api/v1/phase0/trial/record-weekly-decision`
- **Adapter**: Phase 0 adapters (DTO conversion)
- **Service**: Phase 0 trial service
- **Database**: Phase 0 decisions table
- **Test**: Decision appears in `/trial/status` and `/alignment-analysis`

### **✅ Success Criteria**
- **Persistence**: All decisions stored in database
- **Metrics**: Real alignment, compliance, decision counts
- **Process**: Same weekly cadence as Phase 0
- **Outcome**: Evidence-based Phase 1 decision

---

## 🎯 **ADJUSTED THRESHOLDS**

### **✅ Success Criteria**
- **Alignment Rate**: ≥ 65% (adjusted from 70%)
- **Contract Compliance**: ≥ 90% (adjusted from 95%)
- **Decision Volume**: ≥ 8 total (adjusted for 4 weeks)
- **Weekly Decisions**: ≥ 2 per week

### **✅ Risk Limits**
- **Max Notional**: $50K per model (unchanged)
- **Allowed Tiers**: Tier 3, Tier 4 (unchanged)
- **Governance**: Recommendation-only (unchanged)

---

## 📋 **WEEKLY PROCESS**

### **✅ Same Cadence as Phase 0**
1. **Status Check**: `& .\weekly_phase0_status.ps1`
2. **Governance Meeting**: 30-minute meeting
3. **Decision Recording**: `& .\record_decisions.ps1`
4. **Verification**: Three canonical endpoints

### **✅ No Process Changes**
- **Same Scripts**: Use existing Phase 0 scripts
- **Same Endpoints**: Only three canonical endpoints
- **Same Meeting**: 30-minute weekly governance meeting
- **Same Discipline**: Single source of truth

---

## 🎯 **PRE-COMMITTED DECISION TREE**

### **✅ Success (≥65% alignment, ≥90% compliance, ≥8 decisions)**
- Add third model to Phase 1
- Loosen risk limits (Tier 2 allowed)
- Enable limited auto-promotion
- Proceed to Phase 1

### **✅ Failure (any criteria not met)**
- Keep recommendation-only mode
- Further policy iteration with adjusted thresholds
- Schedule another technical re-measurement trial
- Continue until success criteria met

---

## 🚀 **EXECUTION PLAN**

### **Week 1**: Technical Fix Verification
- Fix data persistence path
- Verify decision recording works
- Test persistence in database
- Validate metrics calculation

### **Weeks 2-4**: Governance Process
- Same weekly cadence as Phase 0
- Record decisions with reasons
- Monitor alignment and compliance
- Maintain conservative approach

### **Week 4**: Trial Completion
- Execute `& .\complete_trial.ps1`
- Analyze success criteria
- Follow pre-committed decision tree
- Generate Phase 1 recommendation

---

## 🎯 **SUCCESS DEFINITION**

### **✅ Technical Success**
- **Data Persistence**: All decisions stored and retrievable
- **Metrics Calculation**: Real alignment, compliance, counts
- **API Functionality**: All endpoints working with persisted data

### **✅ Governance Success**
- **Process**: Weekly cadence maintained
- **Decision Quality**: Clear reasoning and documentation
- **Risk Management**: Conservative approach maintained
- **System-Human Alignment**: Strong convergence

### **✅ Evidence-Based Decision**
- **Phase 1 Recommendation**: Based on actual metrics
- **Roadmap Impact**: Informed by real governance data
- **Process Validation**: Governance mechanics proven

---

## 🎯 **DIFFERENTIATION FROM PHASE 0**

### **✅ What's Different**
- **Duration**: 4 weeks vs 6 weeks
- **Thresholds**: Adjusted based on Phase 0 learnings
- **Focus**: Technical fix + measurement vs initial validation
- **Data**: Real persisted decisions vs demonstration

### **✅ What's Same**
- **Process**: Identical weekly cadence and scripts
- **Governance**: Same recommendation-only mode
- **Models**: Same two models
- **Discipline**: Same single source of truth

---

## 🎯 **EXPECTED OUTCOMES**

### **✅ Best Case**
- Technical persistence fixed
- Real metrics generated
- Success criteria met
- Phase 1 recommendation: Add model, loosen limits, enable auto-promotion

### **✅ Expected Case**
- Technical persistence fixed
- Real metrics generated
- Partial success (e.g., 60% alignment, 85% compliance)
- Phase 1 recommendation: Policy iteration with further adjustments

### **✅ Worst Case**
- Technical persistence still broken
- No real metrics
- Continue technical fixes until persistence works
- Phase 1 recommendation: Technical focus before governance expansion

---

## 🎯 **FINAL STATUS**

**Status: MERID PHASE 0B - TECHNICAL RE-MEASUREMENT** 🎯

Phase 0 governance process validated, infrastructure failed. Phase 0b is a focused technical re-measurement to fix data persistence and generate real metrics for evidence-based Phase 1 decision.

**Next Step: Fix data persistence, execute 4-week trial, and follow pre-committed decision tree.**
