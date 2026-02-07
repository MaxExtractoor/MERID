# 🚀 **MERID BANK-GRADE DEPLOYMENT READINESS CHECKLIST**
**Last Updated:** 2026-01-26  
**Target:** Institutional Capital Deployment  
**Standard:** FCA Algorithmic Trading Controls + Deloitte Governance Standards

---

## 📊 **UX METRICS TO TRACK DURING DEPLOYMENT**

### **Task Success Rate for Critical Flows**
- [ ] **Login completion** vs failure rate logged and tracked
- [ ] **Account switch** success/failure monitoring
- [ ] **Venue status viewing** completion rate
- [ ] **Positions/PnL inspection** task success
- [ ] **Mode inspection** (BLIND/SIGHTED_DEGRADED) accuracy
- [ ] **Shadow trade review** completion rate

### **Time on Task / Latency Perception**
- [ ] **Main dashboard load time** < 2 seconds target
- [ ] **Market view open time** < 1 second target
- [ ] **Risk controls panel render** < 1.5 seconds target
- [ ] **Backend latency correlation** with UI metrics

### **Error Rate and "Frustration" Signals**
- [ ] **UI errors per session** < 0.5% target
- [ ] **Screen quit rate** on critical screens < 2%
- [ ] **Rage-click/tap signals** monitoring (if instrumented)
- [ ] **Failed requests** per session < 1%

### **Crash-Free Sessions**
- [ ] **Front-end crash-free sessions** > 99.5% target
- [ ] **Fatal JS errors** per session < 0.1%
- [ ] **Session recovery** mechanisms tested

### **Mode/State Correctness in UI**
- [ ] **Backend vs UI mode mismatches** = 0 (governance bug if >0)
- [ ] **Real-time state synchronization** verified
- [ ] **Mode transition visibility** in UI tested

---

## 🔒 **SECURITY CHECKS PRE- AND POST-DEPLOYMENT**

### **Pre-Deployment Security**
- [ ] **SAST scanning** (Snyk/CodeQL) across Python, Dart/Flutter, JS
- [ ] **Dependency scanning** for vulnerable packages
- [ ] **Container image scanning** (Trivy/Grype) for vulnerabilities
- [ ] **Secrets scanning** on repo and build artifacts
- [ ] **Config and policy checks**:
  - [ ] Auth/role configs verified
  - [ ] TLS/SSL certificates valid
  - [ ] CORS policies configured
  - [ ] Allowed origins restricted
  - [ ] Firewall rules reviewed
- [ ] **Feature flags verification**:
  - [ ] Dangerous execution paths disabled
  - [ ] Treasury controls disabled in staging
  - [ ] Debug endpoints not exposed
- [ ] **Database and backup checks**:
  - [ ] `assertions.db` backup validated
  - [ ] `brier_metrics.db` backup validated
  - [ ] `per_task_roi.db` backup validated
  - [ ] Production trading DBs backup tested
  - [ ] Restore procedure verified

### **Post-Deployment Security**
- [ ] **DAST/API scan** against key endpoints
- [ ] **Auth/session validation** in deployed UI
- [ ] **Logging/audit verification**:
  - [ ] Mode transitions logged
  - [ ] Assertions changes logged
  - [ ] UI actions logged
  - [ ] WORM storage functioning
- [ ] **Debug endpoint verification** (none exposed in prod)
- [ ] **Test flag verification** (none active in prod)

---

## ✅ **DETERMINISTIC DEPLOYMENT CHECKLIST**

### **1. Code & Tests**
- [ ] **All unit tests green** (Python, Dart/Flutter, JS)
- [ ] **All integration tests green**
- [ ] **UX tests green** (task completion, error handling)
- [ ] **`run_tests_and_coverage.py` completed** with coverage > threshold:
  - [ ] `core/` coverage > 80%
  - [ ] `merid/` coverage > 85%
  - [ ] `risk/` coverage > 90%
  - [ ] `governance/` coverage > 85%
  - [ ] `merid-ui/` backend coverage > 80%
- [ ] **No TODO-blocking items** in checklists
- [ ] **No critical bugs** in issue tracker

### **2. Config & Environment**
- [ ] **`.env` derived from `.env.template`** and validated
- [ ] **`MERID_ENV_AUDIT.md` updated** with current config
- [ ] **`docker-compose*` configs up to date**
- [ ] **K8s manifests updated** (if applicable)
- [ ] **Logging configs match** documentation
- [ ] **Environment parity** verified (staging vs prod)

### **3. Security & Compliance**
- [ ] **Pre-deploy scans all pass** or have signed-off exceptions
- [ ] **`production_governance_template.md` updated** with release details
- [ ] **`audit_ready_production_template.md` updated**
- [ ] **Compliance checklist completed**
- [ ] **Risk assessment signed off**

### **4. Observability**
- [ ] **Dashboards updated** with new metrics:
  - [ ] System health dashboard
  - [ ] Mode transition dashboard
  - [ ] Assertions status dashboard
  - [ ] Priority violations dashboard
  - [ ] UX task success dashboard
- [ ] **`verify_system_health.py` passes** in staging
- [ ] **`check_reality.py` passes** in staging
- [ ] **`run_audit.py` passes** in staging
- [ ] **`monitor_canary.py` passes** in staging
- [ ] **Alert thresholds configured** correctly

### **5. Deployment & Rollback**
- [ ] **Blue-green or canary plan ready**
- [ ] **Rollback procedure tested** on previous release
- [ ] **War-game runbook ready** for deployment anomalies
- [ ] **`war_game_scheduler.py` tested** for post-deployment
- [ ] **`war_game_drills.py` verified** for deployment scenarios
- [ ] **Database migration scripts** tested
- [ ] **Feature flag rollback** procedures tested

### **6. Evidence & Docs**
- [ ] **Weekly dossier generation works** with this version
- [ ] **Promotion gates reports generate** correctly
- [ ] **`Season1_Investor_Regulator_Pack.md` updated** or auto-regenerated
- [ ] **`season1_timeline.html` generates** correctly
- [ ] **`promotion_gates_report.html` generates** correctly
- [ ] **Release notes updated** with changes
- [ ] **API documentation updated** with new endpoints

---

## 📊 **COVERAGE INTEGRITY VALIDATION**

### **File Presence and Format**
- [ ] **`.coverage` exists** and is valid coverage DB
- [ ] **`coverage xml` runs without error**
- [ ] **`coverage.xml` parses** with expected schema
- [ ] **Coverage report generates** successfully

### **Backup Integrity**
- [ ] **`coverage_dir_backup/` contains**:
  - [ ] Copy of `.coverage`
  - [ ] Previous `coverage.xml`
  - [ ] Split coverage data (if parallelized)
- [ ] **Restore test passes**:
  - Move current `.coverage` aside
  - Copy from backup
  - Run `coverage html`/`coverage report`
  - Confirm metrics match baseline

### **Scope Consistency**
- [ ] **Coverage configuration includes** right packages:
  - [ ] `source=` in `.coveragerc` covers `core/`, `merid/`, `risk/`, `governance/`
  - [ ] Excludes test directories properly
- [ ] **Critical modules show non-zero coverage**:
  - [ ] `core/` > 80%
  - [ ] `merid/` > 85%
  - [ ] `risk/` > 90%
  - [ ] `governance/` > 85%
- [ ] **Backup matches main** coverage metrics

### **CI Verification**
- [ ] **CI step loads `.coverage`** and generates summary
- [ ] **CI fails if coverage < threshold**
- [ ] **CI fails if coverage file missing/corrupt**
- [ ] **Coverage trends tracked** in dashboard

---

## 🎯 **DART/FLUTTER COVERAGE BEST PRACTICES**

### **Standardize Test Command**
- [ ] **`dart test`** or **`flutter test`** canonical in CI
- [ ] **Coverage command standardized**:
  ```bash
  dart run test --coverage=coverage
  dart run coverage:format_coverage --lcov --in=coverage --out=coverage/lcov.info --report-on=lib
  ```

### **Ensure `lib/` Coverage**
- [ ] **Coverage tools report on `lib/`** not just `test/`
- [ ] **Imports reference `package:your_app/...`** for proper mapping
- [ ] **UI critical paths covered**:
  - [ ] Auth flows > 90%
  - [ ] Dashboard rendering > 85%
  - [ ] Mode display > 95%
  - [ ] Risk controls > 90%

### **CI Integration and Gating**
- [ ] **`lcov.info` uploaded** to Codecov/SonarQube
- [ ] **Minimum Dart/Flutter coverage** enforced:
  - [ ] Auth layer > 90%
  - [ ] Dashboard > 85%
  - [ ] Mode display > 95%
- [ ] **Coverage delta visible** in CI for changes

### **Alignment with Python Coverage**
- [ ] **Combined coverage documented** in `BUILD.md`
- [ ] **Roll-up calculation** defined in scorecard
- [ ] **Coverage sanity test** passes:
  - Change UI file
  - Add trivial test
  - Confirm delta visible in CI

---

## 🚨 **DEPLOYMENT GATES**

### **Gate 1: Code Quality**
- [ ] All tests pass
- [ ] Coverage thresholds met
- [ ] No critical security findings
- [ ] Code review approved

### **Gate 2: System Health**
- [ ] Health checks pass
- [ ] Monitoring functional
- [ ] Alerts configured
- [ ] Performance benchmarks met

### **Gate 3: Security & Compliance**
- [ ] Security scans pass
- [ ] Configs validated
- [ ] Governance templates updated
- [ ] Risk assessment approved

### **Gate 4: Evidence Generation**
- [ ] Dossiers generate correctly
- [ ] Timeline view updates
- [ ] Promotion gates validate
- [ ] Investor pack current

### **Gate 5: UX Quality**
- [ ] Task success rates met
- [ ] Performance targets met
- [ ] Error rates below threshold
- [ ] Mode accuracy verified

---

## 📈 **POST-DEPLOYMENT MONITORING**

### **First Hour**
- [ ] System health dashboard green
- [ ] UX metrics within targets
- [ ] No critical errors
- [ ] Mode transitions normal

### **First Day**
- [ ] Task success rates stable
- [ ] Performance consistent
- [ ] Security scans clean
- [ ] Evidence generation working

### **First Week**
- [ ] All metrics stable
- [ ] User feedback positive
- [ ] No security incidents
- [ ] Governance compliance maintained

---

## 🎯 **SUCCESS CRITERIA**

### **Technical Success**
- [ ] All deployment gates passed
- [ ] System health stable
- [ ] Security maintained
- [ ] Performance targets met

### **Business Success**
- [ ] UX task success > 95%
- [ ] Mode accuracy = 100%
- [ ] Evidence generation functional
- [ ] Investor requirements met

### **Regulatory Success**
- [ ] FCA controls satisfied
- [ ] Audit trails complete
- [ ] Governance compliance verified
- [ ] Risk controls effective

---

## 📝 **FINAL DEPLOYMENT DECISION**

### **Ready for Institutional Capital: [ ] YES / [ ] NO**

**If YES:**
- All gates passed
- Evidence generation verified
- Security clearance obtained
- Regulatory compliance confirmed

**If NO:**
- Blocking issues identified
- Remediation plan defined
- ETA for re-evaluation
- Stakeholder notification sent

---

**🚀 MERID Bank-Grade Deployment Checklist Complete**

*This checklist ensures MERID meets institutional capital deployment standards with comprehensive governance, security, and evidence generation capabilities.*
