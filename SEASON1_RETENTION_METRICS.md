# 📊 **MERID SEASON 1 RETENTION & SAFETY METRICS**
**Last Updated:** 2026-01-26  
**Target:** Predict User Retention, System Safety, and Deployment Sanity

---

## 🎯 **UX METRICS THAT BEST PREDICT RETENTION**

### **Core Value Activation Rate**
**Definition:** % of new users who complete the full value discovery journey

**Tracking Implementation:**
```python
# Core value funnel events to track
activation_events = [
    "user_login_success",
    "dashboard_load_complete", 
    "venue_or_mode_panel_viewed",
    "position_or_shadow_trade_opened"
]

# Activation rate calculation
activation_rate = (users_completing_all_events / total_new_users) * 100
```

**Target:** > 60% activation rate  
**Why it matters:** Strong predictor of whether users "get" the platform's value

**Monitoring:**
- [ ] Event tracking implemented in UI
- [ ] Funnel analytics dashboard
- [ ] Weekly activation rate reporting
- [ ] Alert if activation rate drops < 50%

### **Day-1 / Day-7 / Day-30 Retention**
**Definition:** Users who return after first meaningful session

**Season 1 Approximation:**
```python
# For Season 1, track returns to core screens
retention_events = [
    "dashboard_review",
    "risk_controls_review", 
    "shadow_performance_review",
    "timeline_inspection"
]

# Retention calculation
day1_retention = (users_returning_day1 / active_users_day0) * 100
day7_retention = (users_returning_day7 / active_users_day0) * 100
day30_retention = (users_returning_day30 / active_users_day0) * 100
```

**Targets:**
- Day-1: > 40%
- Day-7: > 25% 
- Day-30: > 15%

**Monitoring:**
- [ ] Daily retention cohort analysis
- [ ] Retention dashboard in investor pack
- [ ] Weekly retention trend reporting
- [ ] Alert if retention drops > 20% week-over-week

### **Stickiness (DAU/MAU on Core Screens)**
**Definition:** Daily active users / Monthly active users for critical screens

**Core Screens to Track:**
```python
core_screens = [
    "main_dashboard",
    "positions_view", 
    "risk_controls_panel",
    "season1_timeline",
    "mode_status_panel"
]

# Stickiness calculation per screen
screen_stickiness = (daily_active_users_screen / monthly_active_users_screen) * 100
```

**Targets:**
- Main dashboard: > 60%
- Risk controls: > 40%
- Timeline view: > 30%
- Positions view: > 35%

**Why it matters:** Higher stickiness → app becomes part of daily workflow

**Monitoring:**
- [ ] Screen-level analytics tracking
- [ ] DAU/MAU dashboard
- [ ] Weekly stickiness reporting
- [ ] Alert if core screen stickiness drops > 15%

### **Task Success + Error Rate on Key Flows**
**Definition:** Success and failure rates for critical user journeys

**Key Flows to Monitor:**
```python
critical_flows = {
    "load_dashboard": {
        "success_threshold": 95,
        "error_threshold": 2
    },
    "inspect_mode_blind_spots": {
        "success_threshold": 90,
        "error_threshold": 5
    },
    "review_shadow_pnl": {
        "success_threshold": 92,
        "error_threshold": 3
    },
    "acknowledge_alerts": {
        "success_threshold": 88,
        "error_threshold": 4
    }
}
```

**Monitoring:**
- [ ] Flow-level success/error tracking
- [ ] Real-time error rate dashboard
- [ ] Weekly flow performance reporting
- [ ] Alert if any flow fails threshold > 24 hours

### **Time to Value / Latency Perception**
**Definition:** Time from login to fully rendered, correct dashboard

**Implementation:**
```python
# Time to value measurement
time_to_value_events = [
    ("login_start", "login_complete"),
    ("dashboard_load_start", "dashboard_render_complete"),
    ("mode_check_start", "mode_display_correct")
]

# Target: < 3 seconds total time to value
```

**Target:** < 3 seconds from login to functional dashboard  
**Why it matters:** Spikes during deployment are early churn indicators

**Monitoring:**
- [ ] End-to-end latency tracking
- [ ] Perceived performance monitoring
- [ ] Deployment latency comparison
- [ ] Alert if time to value > 5 seconds

### **Support/Feedback Signals (Optional)**
**Definition:** User-reported issues tied to UX

**Tracking:**
```python
support_signals = {
    "bug_reports": {"trend": "decreasing"},
    "feature_requests": {"trend": "stable"},
    "confusion_reports": {"trend": "decreasing"},
    "cannot_find_issues": {"trend": "decreasing"}
}
```

**Monitoring:**
- [ ] Support ticket categorization
- [ ] Weekly support trend analysis
- [ ] Correlation with UX improvements
- [ ] Alert if confusion reports increase > 25%

---

## 🔒 **AUTOMATING PRE-DEPLOYMENT SECURITY SCANS**

### **CI/CD Security Pipeline Integration**

#### **1. SAST (Static Application Security Testing)**
```yaml
# GitHub Actions example
security_sast:
  runs-on: ubuntu-latest
  steps:
    - name: CodeQL Analysis (Python)
      uses: github/codeql-action/init@v2
      with:
        languages: python
    - name: CodeQL Analysis (Dart/Flutter)
      uses: github/codeql-action/init@v2
      with:
        languages: javascript
    - name: Perform CodeQL Analysis
      uses: github/codeql-action/analyze@v2
```

**Configuration:**
- [ ] CodeQL for Python, Dart/Flutter, JavaScript
- [ ] Fail on new high-severity issues
- [ ] Run on PR and main branch pushes
- [ ] Weekly security scan reports

#### **2. SCA (Software Composition Analysis)**
```yaml
dependency_scanning:
  runs-on: ubuntu-latest
  steps:
    - name: Snyk Vulnerability Scan
      uses: snyk/actions/python@master
      env:
        SNYK_TOKEN: ${{ secrets.SNYK_TOKEN }}
    - name: Flutter Dependency Scan
      run: flutter pub deps && snyk test
```

**Policy Enforcement:**
- [ ] Block builds on critical vulnerabilities
- [ ] Require exceptions for high-severity issues
- [ ] Daily dependency vulnerability reports
- [ ] Automated dependency updates where safe

#### **3. Container/Image Scanning**
```yaml
container_security:
  runs-on: ubuntu-latest
  steps:
    - name: Build Docker Image
      run: docker build -t merid:${{ github.sha }} .
    - name: Trivy Vulnerability Scan
      uses: aquasecurity/trivy-action@master
      with:
        image-ref: merid:${{ github.sha }}
        format: 'sarif'
        output: 'trivy-results.sarif'
```

**Requirements:**
- [ ] Fail on critical/high vulnerabilities
- [ ] Scan all production images
- [ ] Weekly container security reports
- [ ] Automated base image updates

#### **4. Secrets Scanning**
```yaml
secrets_detection:
  runs-on: ubuntu-latest
  steps:
    - name: GitGuardian Scan
      uses: GitGuardian/ggshield-action@v1.4.3
      env:
        GGUARDIAN_API_KEY: ${{ secrets.GG_API_KEY }}
    - name: TruffleHog Scan
      uses: trufflesecurity/trufflehog@main
      with:
        path: ./
        base: main
        head: HEAD
```

**Policy:**
- [ ] Block commits with detected secrets
- [ ] Scan entire repository history
- [ ] Weekly secrets audit reports
- [ ] Pre-commit hooks for secret detection

#### **5. Infrastructure Policy Checks**
```yaml
policy_validation:
  runs-on: ubuntu-latest
  steps:
    - name: Conftest Policy Check
      uses: instrumenta/conftest-action@master
      with:
        files: docker-compose.yml k8s/
        policy: policies/security.rego
```

**Security Policies:**
- [ ] No debug ports exposed
- [ ] TLS required for all endpoints
- [ ] Execution endpoints not exposed in production
- [ ] Database access restricted

---

## 📈 **POST-DEPLOYMENT OBSERVABILITY CHECKLIST**

### **Health Endpoints Validation**
```python
health_checks = {
    "/health": "200 OK",
    "/reality/state": "200 OK", 
    "/metrics": "200 OK",
    "/api/v1/system/status": "200 OK"
}
```

**Alerting Rules:**
- [ ] Health check failures > 3 times in 5 minutes
- [ ] Response time > 2 seconds for any health endpoint
- [ ] Unexpected content changes in health responses
- [ ] Health endpoint availability < 99.5%

### **Mode & Risk Controls Monitoring**
```python
mode_monitoring = {
    "current_mode": "BLIND|SIGHTED_DEGRADED",
    "execution_blocked": True,  # Unless intentionally changed
    "reality_mode_rollbacks_total": "< 1/hour",
    "priority_violations_total": "< 5/hour",
    "valid_assertions_domain": "> 95% for core domains"
}
```

**Critical Alerts:**
- [ ] Unexpected mode transitions
- [ ] Execution enabled without authorization
- [ ] Assertion validity drops below threshold
- [ ] Priority violations spike > 10/hour

### **Logging & Tracing Validation**
```python
logging_checks = {
    "structured_logs_arriving": True,
    "correlation_ids_present": True,
    "log_volume_stable": True,
    "error_logs_no_spike": True,
    "log_format_consistent": True
}
```

**Monitoring:**
- [ ] Log volume drops > 20%
- [ ] Error log spikes > 50%
- [ ] Missing correlation IDs
- [ ] Log format changes
- [ ] Tracing span completeness

### **UX-Visible Symptoms Monitoring**
```python
ux_monitoring = {
    "ui_endpoint_error_rate": "< 1%",
    "latency_threshold": "< 2 seconds",
    "js_error_rate": "< 0.5%",
    "mode_display_consistency": "100%",
    "risk_banner_visibility": "100%"
}
```

**Alert Thresholds:**
- [ ] UI error rate > 2%
- [ ] Latency > 3 seconds
- [ ] JS errors > 1%
- [ ] Mode display mismatches
- [ ] Risk banner not showing

### **Alert Configuration Validation**
```python
alerts_configured = {
    "uptime_latency_monitoring": True,
    "assertion_validity_alerts": True,
    "automatic_rollback_alerts": True,
    "war_game_drill_alerts": True,
    "security_incident_alerts": True
}
```

**Testing:**
- [ ] Weekly alert testing
- [ ] Alert delivery verification
- [ ] Escalation path testing
- [ ] False positive tuning

---

## 📊 **COVERAGE REPORTS VALIDATION & ENFORCEMENT**

### **1. Coverage Artifacts Validation**
```python
coverage_validation = {
    "python": {
        "files": [".coverage", "coverage.xml"],
        "commands": ["coverage xml", "coverage report"]
    },
    "dart": {
        "files": ["coverage/lcov.info"],
        "commands": ["lcov --summary coverage/lcov.info"]
    }
}
```

**Validation Script:**
```python
def validate_coverage_artifacts():
    artifacts = {
        "python": [".coverage", "coverage.xml"],
        "dart": ["coverage/lcov.info"]
    }
    
    for lang, files in artifacts.items():
        for file in files:
            if not os.path.exists(file):
                raise CoverageValidationError(f"Missing {file} for {lang}")
            
            # Validate file format
            if file.endswith('.xml'):
                try:
                    ET.parse(file)
                except ET.ParseError:
                    raise CoverageValidationError(f"Invalid XML in {file}")
```

### **2. Threshold Enforcement**
```python
coverage_thresholds = {
    "overall": {
        "python": 85,
        "dart": 80
    },
    "critical_modules": {
        "core": 90,
        "risk": 95,
        "governance": 90,
        "merid_ui_backend": 85
    },
    "per_module_minimums": {
        "authentication": 95,
        "mode_controls": 95,
        "assertions": 90,
        "risk_enforcement": 95
    }
}
```

**Enforcement Script:**
```python
def enforce_coverage_thresholds():
    coverage_data = parse_coverage_reports()
    
    # Check overall thresholds
    if coverage_data['python']['overall'] < coverage_thresholds['overall']['python']:
        raise CoverageThresholdError("Python overall coverage below threshold")
    
    # Check critical modules
    for module, threshold in coverage_thresholds['critical_modules'].items():
        if coverage_data['python']['modules'][module] < threshold:
            raise CoverageThresholdError(f"Module {module} below threshold")
```

### **3. Policy Layer Integration**
```rego
# coverage.rego policy example
package coverage.policy

default allow = false

allow {
    input.python.overall >= 85
    input.dart.overall >= 80
    input.python.modules.core >= 90
    input.python.modules.risk >= 95
    input.python.modules.governance >= 90
}

deny {
    input.python.overall < 85
} {
    msg := "Python overall coverage below 85%"
}
```

### **4. Evidence Storage**
```python
def store_coverage_evidence(release_version):
    evidence = {
        "release_version": release_version,
        "timestamp": datetime.utcnow().isoformat(),
        "python_coverage": coverage_data['python'],
        "dart_coverage": coverage_data['dart'],
        "thresholds_met": all_thresholds_passed,
        "validation_log": validation_results
    }
    
    # Store in release dossier
    add_to_release_dossier("coverage_validation", evidence)
    
    # Store in artifact registry
    upload_to_artifact_store(f"coverage-{release_version}.json", evidence)
```

---

## 🔄 **CI PIPELINE INTEGRATION**

### **Complete CI Job Structure**
```yaml
name: MERID Security & Coverage Pipeline

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  security_scans:
    runs-on: ubuntu-latest
    steps:
      - name: SAST - CodeQL
        uses: github/codeql-action/analyze@v2
      - name: SCA - Snyk
        uses: snyk/actions/python@master
      - name: Container Scan - Trivy
        uses: aquasecurity/trivy-action@master
      - name: Secrets Scan - GitGuardian
        uses: GitGuardian/ggshield-action@v1.4.3
      - name: Policy Check - Conftest
        uses: instrumenta/conftest-action@master

  coverage_validation:
    runs-on: ubuntu-latest
    needs: security_scans
    steps:
      - name: Python Tests with Coverage
        run: |
          pytest --cov=merid --cov=risk --cov=governance --cov-report=xml
      - name: Flutter Tests with Coverage
        run: |
          flutter test --coverage
          dart run coverage:format_coverage --lcov --in=coverage --out=coverage/lcov.info
      - name: Validate Coverage Artifacts
        run: python scripts/validate_coverage.py
      - name: Enforce Coverage Thresholds
        run: python scripts/enforce_coverage_thresholds.py
      - name: Policy Validation
        run: conftest test coverage-summary.json --policy policies/coverage.rego

  deployment_gate:
    runs-on: ubuntu-latest
    needs: [security_scans, coverage_validation]
    if: github.ref == 'refs/heads/main'
    steps:
      - name: Generate Release Evidence
        run: python scripts/generate_release_evidence.py
      - name: Validate Deployment Readiness
        run: python scripts/validate_deployment_readiness.py
      - name: Deploy to Staging
        run: ./deploy_staging.sh
      - name: Post-Deployment Health Check
        run: python scripts/post_deployment_health_check.py
```

### **Pre-Commit Hook (Optional)**
```python
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: fast-coverage-check
        name: Fast Coverage Check
        entry: python scripts/fast_coverage_check.py
        language: system
        pass_filenames: false
        always_run: true
      - id: security-scan
        name: Security Scan
        entry: bandit -r ./
        language: system
        pass_filenames: false
        always_run: true
```

---

## 🎯 **SUCCESS METRICS & ALERTING**

### **Retention Success Indicators**
- [ ] Activation rate > 60%
- [ ] Day-7 retention > 25%
- [ ] Core screen stickiness > 40%
- [ ] Task success rates > 90%
- [ ] Time to value < 3 seconds

### **Security Success Indicators**
- [ ] Zero critical vulnerabilities in production
- [ ] All security scans passing in CI
- [ ] No secrets detected in repository
- [ ] Infrastructure policies enforced
- [ ] Weekly security reports clean

### **Coverage Success Indicators**
- [ ] Overall coverage > 85% (Python), > 80% (Dart)
- [ ] Critical modules > 90% coverage
- [ ] All coverage thresholds enforced
- [ ] Coverage evidence stored per release
- [ ] Coverage trends improving over time

### **Deployment Success Indicators**
- [ ] All health endpoints responding
- [ ] Mode controls functioning correctly
- [ ] No UX error spikes
- [ ] All alerts configured and tested
- [ ] Post-deployment monitoring stable

---

## 📝 **IMPLEMENTATION ROADMAP**

### **Week 1: Core Tracking Implementation**
- [ ] UX event tracking in UI
- [ ] Retention analytics dashboard
- [ ] Basic security scan integration
- [ ] Coverage validation scripts

### **Week 2: Advanced Monitoring**
- [ ] Full CI/CD security pipeline
- [ ] Post-deployment observability
- [ ] Alert configuration and testing
- [ ] Coverage threshold enforcement

### **Week 3: Optimization & Automation**
- [ ] Pre-commit hooks implementation
- [ ] Automated evidence generation
- [ ] Policy-as-code integration
- [ ] Success metrics dashboard

### **Week 4: Validation & Documentation**
- [ ] End-to-end testing of all metrics
- [ ] Documentation completion
- [ ] Team training on new processes
- [ ] Go-live preparation

---

**🚀 This framework ensures MERID Season 1 maximizes user retention, maintains system safety, and achieves deployment sanity through deterministic metrics and automated validation.**
