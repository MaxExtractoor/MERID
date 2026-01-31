# Swarm Operations v1 - Quick Reference

**Version:** 1.0  
**Status:** ACTIVE  
**Date:** 2026-01-26  

---

## 🎯 WHAT WE MEASURE

### **Core SLOs**
- **Success Rate**: ≥ 90% (CI reliability)
- **Cascade Size**: < 2.0 (failure containment)
- **Branching Factor**: < 1.2 (propagation control)
- **Quality Score**: ≥ 0.8 (code quality)
- **Misalignment**: ≤ 1.0 (agent coordination)
- **Retry Index**: ≤ 2.0 (efficiency)

### **Quality Metrics**
- Test coverage > 80%
- Defect rate < 5%
- Developer efficiency > 80 tokens/turn
- Review time < 300s
- Code complexity < 10 cyclomatic

### **ROI Metrics**
- Time saved per task (hours)
- Quality improvement (-1 to +1)
- ROI score (0-100)
- Cost savings ($100/hour assumption)

---

## 🔄 HOW OFTEN WE REVIEW

### **Weekly (Monday 30 min)**
1. **Metrics Review** (10 min)
   - CI reliability report
   - Cascade metrics and trends
   - Quality score changes
   - Misalignment patterns

2. **Changelog Review** (10 min)
   - Agent/prompt changes
   - Infrastructure modifications
   - Incidents and resolutions

3. **SLO Check** (5 min)
   - Current SLO score
   - Threshold breaches
   - Error budget burn

4. **Action Items** (5 min)
   - Assign improvement tasks
   - Schedule hardening sprints
   - Plan next week's focus

### **Outputs**
- Weekly review report (JSON)
- Action items in project system
- Changelog entry

---

## 🚨 WHAT TRIGGERS HARDENING SPRINT

### **Critical Triggers**
- **Any SLO breach** (immediate)
- **Multiple SLOs below threshold** (within 1 week)
- **Trending down** for 2+ weeks
- **Quality score drop** > 15%

### **Hardening Sprint Focus**
- Root cause analysis
- Targeted fixes
- Validation in staging
- Enhanced monitoring post-fix

---

## 🧪 HOW WE RUN EXPERIMENTS SAFELY

### **Prompt/Role Experiments**
1. **Identify target** from misalignment correlations
2. **Create single variant** with clear hypothesis
3. **Test in topology lab** (5 tasks max)
4. **Evaluate**: improvement > 5% + significance > 60%
5. **Deploy** only if clearly better

### **Topology Experiments**
1. **Limited scope**: 5 tasks, specific task types
2. **Clear thresholds**: Success ≥ 85%, Quality ≥ 0.75, Resilience ≥ 0.8
3. **Isolated environment**: Never in production
4. **Decision rules**: Only consider if clearly better
5. **Gradual rollout**: Start with non-critical tasks

### **Experiment Status**
- **Excellent**: All thresholds exceeded by ≥ 10%
- **Acceptable**: All thresholds met
- **Needs Improvement**: Some thresholds not met
- **Poor**: Multiple thresholds failed

---

## 📊 CURRENT STATUS (Week 1-2)

### **Week 1: Baseline Established**
- **SLO Score**: 80.0/100 ✅ COMPLIANT
- **CI Success Rate**: 100%
- **Cascade Size**: 0.00
- **Quality Score**: Not enough data
- **Status**: Infrastructure ready

### **Week 2: First ROI Use Case**
- **Use Case**: Automated test expansion
- **Tasks**: 3/3 successful (100%)
- **Time Saved**: 9.5 hours (100% reduction)
- **ROI Score**: 97.4/100
- **Quality Improvement**: +0.83
- **Status**: ✅ READY TO SCALE

---

## 🎯 NEXT 4 WEEKS PLAN

### **Week 3: Optimize & Document**
- Fix experiment setup issues
- Deploy successful prompt variants
- Complete Swarm Ops v1 documentation
- Continue weekly cadence

### **Week 4: Scale Success**
- Scale test expansion to more modules
- Run second prompt optimization
- Consider larger topology experiment
- Review 4-week trends

### **Week 5-6: Evaluate & Decide**
- Analyze monthly trends
- Decide on topology changes
- Plan next quarter focus
- Update processes based on learnings

---

## 📋 KEY FILES

### **Operations**
- `swarm/operations/cadence.py` - Weekly review automation
- `swarm/quality/metrics_collector.py` - Quality tracking
- `swarm/roi/tracker.py` - ROI measurement

### **Experimentation**
- `swarm/quality/optimizer.py` - Prompt optimization
- `swarm/lab/topology_lab.py` - Topology experiments
- `swarm/lab/focused_experiments.py` - Controlled tests

### **Documentation**
- `docs/swarm_operations_v1.md` - Full operations guide
- `docs/swarm_resilience_contracts.md` - Versioned contracts
- Weekly review logs (JSON)

---

## 🚀 SUCCESS CRITERIA

### **Monthly Goals**
- **SLO Compliance**: ≥ 80% of weeks
- **ROI Positive**: Net time saved > 0
- **Quality Improving**: Trend up or stable
- **Experiments Learning**: At least 1 successful improvement per month

### **Quarterly Goals**
- **Scale Usage**: Expand to 2+ use case types
- **Process Refinement**: Optimize based on real data
- **Topology Decision**: Based on experiment results
- **Team Training**: All team members proficient

---

## 📞 CONTACTS

### **Swarm Operations Team**
- **Lead**: Swarm Operations Lead
- **Quality**: Quality Metrics Engineer  
- **Experiments**: Topology Lab Engineer

### **Escalation**
1. **Day-to-day**: Swarm Operations Team
2. **Critical**: Swarm Operations Lead
3. **Emergency**: CTO/Engineering Director

---

**Status**: ✅ ACTIVE OPERATIONS  
**Next Review**: Week 3  
**Focus**: Optimize experiments & scale success
