# 🎯 **MERID SEASON 1 GOVERNANCE METRICS**
**Last Updated:** 2026-01-26  
**Target:** Opinionated Retention, Security, and Observability Practices for Governance Engine

---

## 📊 **UX RETENTION METRIC WITH STRONGEST 30-DAY LINK**

### **Core Task Definition for MERID**
**Definition:** Users who complete the full governance value journey in first session

```python
core_task_events = [
    "user_login_success",
    "dashboard_load_complete",
    "mode_and_risk_banners_viewed", 
    "shadow_pnl_or_positions_inspected",
    "drill_or_dossier_reviewed"  # Optional but tracked
]

# Core task completion calculation
core_task_completion_rate = (users_completing_core_task / total_new_users) * 100
```

### **Day-7 Retention as Leading Indicator**
**Why D7 Matters:** Strongest correlation with D30 retention for high-engagement products

**Implementation:**
```python
# Track D7 retention among core task completers
def calculate_d7_retention():
    core_task_users = get_users_completing_core_task()
    d7_returners = get_users_returning_day7(core_task_users)
    return (d7_returners / core_task_users) * 100

# Funnel analysis for retention optimization
retention_funnel = {
    "d1_activation": "users_login_and_see_dashboard",
    "d7_core_task": "users_completing_core_task_and_returning_day7", 
    "d30_retention": "users_returning_day30"
}
```

**Target Metrics:**
- **Core task completion:** > 60% of new users
- **D7 retention (core task users):** > 40%
- **D30 retention (core task users):** > 25%

**Alert Thresholds:**
- Core task completion < 50% → Onboarding issue
- D7 retention drop > 15% vs baseline → Early workflow problem
- D30 retention drop > 20% vs baseline → Ongoing value issue

### **Retention Optimization Strategy**
```python
# Funnel-based optimization approach
if d1_retention_ok and d7_retention_low:
    focus = "onboarding_and_early_workflows"
elif d7_retention_ok and d30_retention_low:
    focus = "ongoing_value_features"
else:
    focus = "core_value_proposition"
```

**Governance Integration:**
- [ ] Core task completion tracked in weekly dossiers
- [ ] D7/D30 retention metrics in promotion gates
- [ ] Retention drops trigger governance reviews
- [ ] UX improvements logged as governance actions

---

## 🔒 **AUTOMATED SAST IN MERID CI/CD**

### **SAST Tool Selection per Stack**
```yaml
# SAST tools configuration
sast_tools:
  python:
    primary: "CodeQL"
    secondary: "SonarQube"
    scan_paths: ["core/", "merid/", "risk/", "governance/", "scripts/"]
  
  dart_flutter:
    primary: "CodeQL (JavaScript mode)"
    secondary: "Snyk Code"
    scan_paths: ["merid-ui/", "web/"]
  
  javascript:
    primary: "CodeQL"
    secondary: "Snyk Code"
    scan_paths: ["backend/", "web/static/"]
  
  infrastructure:
    primary: "Checkov"
    secondary: "tfsec"
    scan_paths: ["docker-compose.yml", "k8s/"]
```

### **GitHub Actions SAST Implementation**
```yaml
name: SAST Security Scan

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  sast-scan:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
      
      - name: Initialize CodeQL
        uses: github/codeql-action/init@v2
        with:
          languages: python, javascript
      
      - name: Autobuild
        uses: github/codeql-action/autobuild@v2
      
      - name: Perform CodeQL Analysis
        uses: github/codeql-action/analyze@v2
        with:
          output_file_format: sarif
          output_file: codeql-results.sarif
      
      - name: SonarQube Scan
        uses: sonarqube-quality-gate-action@master
        env:
          SONAR_TOKEN: ${{ secrets.SONAR_TOKEN }}
      
      - name: Snyk Code Scan
        uses: snyk/actions/python@master
        env:
          SNYK_TOKEN: ${{ secrets.SNYK_TOKEN }}
        with:
          args: --severity-threshold=high
      
      - name: Upload SARIF to GitHub Security
        uses: github/codeql-action/upload-sarif@v2
        with:
          sarif_file: codeql-results.sarif
```

### **SAST Configuration and Policies**
```python
# sonar-project.properties
sonar.projectKey=merid-season1
sonar.sources=core,merid,risk,governance,scripts,merid-ui,web
sonar.exclusions=**/*_test.py,**/test/**,**/__pycache__/**
sonar.python.bandit.reportPaths=bandit-report.json
sonar.python.pylint.reportPaths=pylint-report.txt
sonar.python.coverage.reportPaths=coverage.xml

# Security rules focus
security_focus_areas = [
    "authentication_and_authorization",
    "input_validation_and_sanitization", 
    "secrets_and_credential_handling",
    "cryptographic_implementations",
    "sql_injection_prevention",
    "xss_prevention",
    "csrf_protection",
    "secure_headers"
]
```

### **Merge and Deploy Gates**
```yaml
# PR protection rules
pr_protection:
  required_status_checks:
    strict: true
    contexts:
      - "SAST Security Scan"
      - "SonarQube Quality Gate"
      - "Snyk Vulnerability Scan"
  
  enforce_admins: true
  required_linear_history: true

# Deploy gate
deploy_gate:
  requires:
    - "sast-scan:success"
    - "security-tests:success"
    - "coverage-validation:success"
```

---

## 🛡️ **DAST TOOLS FOR PRODUCTION DEPLOYS**

### **DAST Tool Selection for MERID**
```yaml
dast_tools:
  primary: "StackHawk"
  secondary: "OWASP ZAP"
  tertiary: "GitLab DAST"  # If using GitLab CI

scan_targets:
  web_ui:
    - "https://staging.merid.com"
    - "/dashboard"
    - "/positions"
    - "/risk-controls"
    - "/timeline"
  
  api_endpoints:
    - "/api/v1/health"
    - "/api/v1/reality/state"
    - "/api/v1/metrics"
    - "/api/v1/assertions"
    - "/api/v1/mode/status"
  
  auth_flows:
    - "/api/v1/auth/login"
    - "/api/v1/auth/logout"
    - "/api/v1/auth/refresh"
```

### **StackHawk Integration**
```yaml
# stackhawk.yml
app:
  host: https://staging.merid.com
  name: MERID Season 1
  env: Staging
  
  authentication:
    type: oidc
    loginPath: /api/v1/auth/login
    logoutPath: /api/v1/auth/logout
    username: ${{ hawk_username }}
    password: ${{ hawk_password }}

  # API scanning configuration
  api:
    - OpenAPI: /api/v1/docs/openapi.json
    - GraphQL: /api/v1/graphql
  
  # Custom scan profiles
  profiles:
    trading_security:
      tests:
        - BrokenObjectLevelAuthorization
        - SqlInjection
        - Xss
        - SensitiveDataExposure
        - SecurityMisconfiguration
```

### **OWASP ZAP CI Integration**
```yaml
dast-zap:
  runs-on: ubuntu-latest
  needs: deploy-staging
  steps:
    - name: OWASP ZAP Baseline Scan
      uses: zaproxy/action-baseline@v0.7.0
      with:
        target: https://staging.merid.com
        rules_file_name: .zap/rules.tsv
        cmd_options: -a -t .zap/targets.txt
    
    - name: Upload ZAP Report
      uses: actions/upload-artifact@v3
      with:
        name: zap-report
        path: report_html.html
    
    - name: ZAP Security Gate
      run: |
        if [ $(grep -c "High" report_html.html) -gt 0 ]; then
          echo "High severity issues found - failing deployment"
          exit 1
        fi
```

### **Pre-Production DAST Pipeline**
```python
# DAST execution order
dast_pipeline = {
    "stage_deployment": "Deploy to staging environment",
    "smoke_tests": "Run basic functionality tests",
    "dast_scan": "Execute StackHawk/ZAP scan",
    "security_review": "Manual review of high findings",
    "production_approval": "Approve for production deployment"
}

# DAST failure handling
dast_failure_actions = {
    "high_critical": "Block deployment, require fix",
    "medium": "Document exception, proceed with caution",
    "low": "Track for future fix, proceed"
}
```

---

## 📈 **KPI DASHBOARD TEMPLATES**

### **1. System Health Panel**
```python
system_health_metrics = {
    "api_uptime": {
        "target": "> 99.9%",
        "alert_threshold": "< 99.5%"
    },
    "error_rate": {
        "target": "< 0.5%",
        "alert_threshold": "> 2%"
    },
    "latency_p95": {
        "target": "< 500ms",
        "alert_threshold": "> 1000ms"
    },
    "mode_status": {
        "expected": "BLIND or SIGHTED_DEGRADED",
        "alert": "unexpected_mode"
    },
    "rollback_count": {
        "target": "< 1/hour",
        "alert_threshold": "> 3/hour"
    }
}
```

### **2. Risk & Governance Panel**
```python
risk_governance_metrics = {
    "valid_assertions_per_domain": {
        "core": {"target": "> 95%", "alert": "< 90%"},
        "risk": {"target": "> 98%", "alert": "< 95%"},
        "governance": {"target": "> 95%", "alert": "< 90%"}
    },
    "assertion_failure_rate": {
        "target": "< 1%",
        "alert_threshold": "> 5%"
    },
    "priority_violations": {
        "target": "< 5/hour",
        "alert_threshold": "> 15/hour"
    },
    "execution_blocks": {
        "target": "All unauthorized attempts blocked",
        "alert": "Any unauthorized execution"
    },
    "mode_transitions": {
        "target": "Only authorized transitions",
        "alert": "Unexpected mode changes"
    }
}
```

### **3. UX & Retention Signals Panel**
```python
ux_retention_metrics = {
    "core_task_completion": {
        "target": "> 60%",
        "alert_threshold": "< 50%"
    },
    "d7_retention_core_users": {
        "target": "> 40%",
        "alert_threshold": "< 25%"
    },
    "d30_retention_core_users": {
        "target": "> 25%", 
        "alert_threshold": "< 15%"
    },
    "task_success_rates": {
        "dashboard_load": {"target": "> 95%", "alert": "< 85%"},
        "positions_view": {"target": "> 92%", "alert": "< 80%"},
        "risk_panel": {"target": "> 90%", "alert": "< 75%"},
        "timeline_view": {"target": "> 88%", "alert": "< 70%"}
    },
    "crash_free_sessions": {
        "target": "> 99%",
        "alert_threshold": "< 98%"
    }
}
```

### **4. Security Posture Panel**
```python
security_posture_metrics = {
    "sast_status": {
        "target": "Pass",
        "alert": "Fail or high_severity_issues"
    },
    "dast_status": {
        "target": "Pass", 
        "alert": "Fail or high_critical_findings"
    },
    "secrets_scan": {
        "target": "Clean",
        "alert": "Secrets detected"
    },
    "dependency_vulnerabilities": {
        "target": "No critical",
        "alert": "Critical vulnerabilities found"
    },
    "last_security_scan": {
        "target": "< 24 hours ago",
        "alert": "> 48 hours ago"
    }
}
```

### **5. Deployment Status Panel**
```python
deployment_metrics = {
    "current_version": {
        "display": "version and commit hash",
        "tracking": "deployment_timestamp"
    },
    "deployment_time": {
        "target": "< 10 minutes",
        "alert": "> 30 minutes"
    },
    "canary_traffic_split": {
        "display": "percentage in canary",
        "alert": "canary_issues_detected"
    },
    "pre_vs_post_deploy": {
        "metrics": ["error_rate", "latency", "throughput"],
        "alert_threshold": "> 20% degradation"
    },
    "rollback_status": {
        "target": "No rollback",
        "alert": "Rollback initiated"
    }
}
```

---

## 🚨 **ALERTING THRESHOLDS FOR DEGRADED UX**

### **Core UX Alert Thresholds**
```python
ux_alert_thresholds = {
    "error_rate_core_endpoints": {
        "threshold": "> 2%",
        "duration": "> 5 minutes",
        "endpoints": ["/dashboard", "/positions", "/risk-controls", "/timeline"],
        "severity": "WARNING"
    },
    "latency_p95": {
        "threshold": "> 800ms",
        "duration": "> 5 minutes", 
        "endpoints": ["dashboard_load", "positions_view", "risk_panel"],
        "severity": "WARNING"
    },
    "task_success_drop": {
        "threshold": "> 15 percentage points",
        "baseline": "last_7_days",
        "flows": ["dashboard_load_see_mode", "positions_inspection"],
        "severity": "CRITICAL"
    },
    "crash_free_sessions": {
        "threshold": "< 98%",
        "duration": "> 1 hour",
        "severity": "CRITICAL"
    },
    "retention_proxy_alerts": {
        "d1_drop": "> 10% vs median_4_weeks",
        "d7_drop": "> 10% vs median_4_weeks",
        "severity": "WARNING"
    }
}
```

### **Alert Implementation**
```python
# Alert configuration for governance integration
class UXAlertManager:
    def __init__(self):
        self.alert_thresholds = ux_alert_thresholds
        self.governance_integration = True
    
    def check_error_rate(self, endpoint, current_rate):
        threshold = self.alert_thresholds["error_rate_core_endpoints"]
        if current_rate > threshold["threshold"]:
            self.trigger_ux_alert(
                alert_type="HIGH_ERROR_RATE",
                severity=threshold["severity"],
                details=f"{endpoint}: {current_rate}% errors",
                governance_action="create_incident"
            )
    
    def check_task_success_drop(self, flow, current_success, baseline_success):
        threshold = self.alert_thresholds["task_success_drop"]
        drop = baseline_success - current_success
        if drop > threshold["threshold"]:
            self.trigger_ux_alert(
                alert_type="TASK_SUCCESS_DROP",
                severity=threshold["severity"],
                details=f"{flow}: {drop}% drop from baseline",
                governance_action="immediate_review"
            )
    
    def trigger_ux_alert(self, alert_type, severity, details, governance_action):
        # Create alert in monitoring system
        alert = {
            "type": alert_type,
            "severity": severity,
            "details": details,
            "timestamp": datetime.utcnow().isoformat(),
            "governance_action": governance_action
        }
        
        # Integrate with governance workflows
        if self.governance_integration:
            self.create_governance_incident(alert)
            self.log_in_weekly_dossier(alert)
            self.evaluate_promotion_gate_impact(alert)
```

### **Governance Integration**
```python
# UX alerts as governance signals
governance_ux_integration = {
    "alert_categories": {
        "CRITICAL": "immediate_incident_response",
        "WARNING": "risk_committee_review",
        "INFO": "weekly_dossier_note"
    },
    "promotion_gate_impacts": {
        "task_success_drop": "readiness_score_decrease",
        "high_error_rate": "incident_rate_increase",
        "crash_free_sessions": "stability_metric_decrease"
    },
    "evidence_requirements": {
        "ux_incidents": "document_in_weekly_dossier",
        "resolution_actions": "track_in_governance_timeline",
        "impact_assessment": "include_in_promotion_gates"
    }
}
```

---

## 🔄 **GOVERNANCE ENGINE INTEGRATION**

### **Weekly Dossier Integration**
```python
def add_ux_metrics_to_weekly_dossier():
    dossier_data = {
        "ux_retention_metrics": {
            "core_task_completion": get_core_task_completion_rate(),
            "d7_retention": calculate_d7_retention(),
            "d30_retention": get_d30_retention(),
            "task_success_rates": get_task_success_rates()
        },
        "ux_incidents": get_ux_incidents_week(),
        "ux_alerts_triggered": get_ux_alerts_week(),
        "governance_actions": get_governance_actions_week()
    }
    return dossier_data
```

### **Promotion Gates Integration**
```python
def evaluate_ux_promotion_gates():
    gates_status = {
        "ux_stability_gate": {
            "status": "MET" if crash_free_sessions > 98 else "NOT_MET",
            "current_value": crash_free_sessions,
            "target": 98,
            "consecutive_weeks": calculate_consecutive_weeks("crash_free_sessions", 98)
        },
        "task_success_gate": {
            "status": "MET" if avg_task_success > 90 else "NOT_MET", 
            "current_value": avg_task_success,
            "target": 90,
            "consecutive_weeks": calculate_consecutive_weeks("task_success", 90)
        },
        "retention_gate": {
            "status": "MET" if d7_retention > 40 else "NOT_MET",
            "current_value": d7_retention,
            "target": 40,
            "consecutive_weeks": calculate_consecutive_weeks("d7_retention", 40)
        }
    }
    return gates_status
```

### **War-Game Drill Integration**
```python
def create_ux_degradation_drill():
    drill_scenario = {
        "name": "UX Degradation Response",
        "type": "incident_response",
        "scenario": "Core task success rate drops 20%",
        "expected_response": [
            "Detect within 5 minutes",
            "Identify root cause within 15 minutes", 
            "Implement fix within 30 minutes",
            "Verify recovery within 45 minutes"
        ],
        "governance_integration": {
            "log_in_dossier": True,
            "impact_promotion_gates": True,
            "require_human_annotation": True
        }
    }
    return drill_scenario
```

---

## 📋 **IMPLEMENTATION CHECKLIST**

### **Week 1: Core Tracking Setup**
- [ ] Core task event tracking implemented
- [ ] D7 retention calculation automated
- [ ] Basic UX dashboard created
- [ ] Alert thresholds configured

### **Week 2: Security Integration**
- [ ] SAST pipeline implemented and tested
- [ ] DAST tools configured for staging
- [ ] Security dashboard panels created
- [ ] Security gates integrated into CI/CD

### **Week 3: Governance Integration**
- [ ] UX metrics integrated into weekly dossiers
- [ ] Promotion gates updated with UX criteria
- [ ] War-game drills for UX degradation created
- [ ] Alert-governance workflow implemented

### **Week 4: Optimization & Validation**
- [ ] End-to-end testing of all metrics
- [ ] Alert tuning based on false positives
- [ ] Governance workflow validation
- [ ] Documentation and team training

---

## 🎯 **SUCCESS METRICS**

### **Retention Success**
- [ ] Core task completion > 60%
- [ ] D7 retention > 40% (core users)
- [ ] D30 retention > 25% (core users)
- [ ] Retention funnel optimization working

### **Security Success**
- [ ] Zero critical vulnerabilities in production
- [ ] All SAST/DAST scans passing
- [ ] Security incidents = 0
- [ ] Security posture dashboard green

### **Observability Success**
- [ ] All KPI dashboards functional
- [ ] Alert thresholds tuned and effective
- [ ] Mean time to detection < 5 minutes
- [ ] Mean time to resolution < 30 minutes

### **Governance Success**
- [ ] UX metrics integrated into dossiers
- [ ] Promotion gates include UX criteria
- [ ] War-game drills covering UX scenarios
- [ ] Evidence generation automated

---

**🚀 This governance metrics framework provides MERID Season 1 with opinionated, actionable retention, security, and observability practices directly integrated into the governance engine.**
