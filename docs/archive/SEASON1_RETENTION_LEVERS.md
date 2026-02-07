# 🎯 **MERID SEASON 1 RETENTION LEVERS**
**Last Updated:** 2026-01-26  
**Target:** Single Early Metric + Clean Instrumentation + Simple Correlation + SonarQube CI Integration

---

## 📊 **EARLY METRIC THAT BEST PREDICTS D30**

### **Day-7 Core Activation Retention**
**Why D7 Matters:** Strongest early predictor of long-term retention for high-engagement products

```python
# Core task definition for MERID
core_task_sequence = [
    "user_login_success",
    "dashboard_load_complete", 
    "mode_and_risk_banners_viewed",
    "positions_or_shadow_pnl_inspected"
]

# D7 retention calculation
def calculate_d7_core_retention(cohort_date):
    cohort_users = get_users_by_first_seen(cohort_date)
    core_task_users = get_users_completing_core_task(cohort_users)
    d7_returners = get_users_returning_on_day(core_task_users, cohort_date, 7)
    return (d7_returners / core_task_users) * 100 if core_task_users else 0
```

**Target Metrics:**
- **Core task completion:** > 60% of new users
- **D7 core retention:** > 40% (top quartile predictor)
- **D30 retention:** > 25% (strongly correlated with D7)

**Why This Works:**
- **D1:** Measures onboarding effectiveness
- **D7:** Reflects repeatable value discovery and habit formation
- **Top Quartile Performance:** Benchmarks show D7 top quartile = D30 top performers

---

## 🔧 **INSTRUMENTING D7 AND D14 COHORTS**

### **Event Definition Schema**
```python
# Core event definitions
event_schema = {
    "user_registered": {
        "description": "User first seen/registered",
        "cohort_anchor": True,
        "required_fields": ["user_id", "event_time_utc", "platform"]
    },
    "core_value_experienced": {
        "description": "User completed core task sequence",
        "value_indicator": True,
        "required_fields": ["user_id", "event_time_utc", "task_completion_time"]
    },
    "session_active": {
        "description": "Meaningful session activity",
        "activity_threshold": "dashboard_open > 30 seconds OR key_screens_viewed",
        "required_fields": ["user_id", "event_time_utc", "session_duration", "screens_viewed"]
    }
}
```

### **Data Capture Implementation**
```python
# Event storage schema
events_table = {
    "event_id": "UUID PRIMARY KEY",
    "user_id": "VARCHAR NOT NULL", 
    "event_name": "VARCHAR NOT NULL",
    "event_time_utc": "TIMESTAMP NOT NULL",
    "platform": "VARCHAR",
    "session_id": "VARCHAR",
    "metadata": "JSONB",
    "created_at": "TIMESTAMP DEFAULT NOW()"
}

# Event capture function
def capture_user_event(user_id, event_name, metadata=None):
    event_data = {
        "user_id": user_id,
        "event_name": event_name,
        "event_time_utc": datetime.utcnow().isoformat(),
        "platform": "merid_web",
        "metadata": metadata or {}
    }
    insert_event_to_analytics(event_data)
```

### **Cohort Building Logic**
```python
def build_retention_cohorts(cohort_start_date, cohort_end_date):
    cohorts = {}
    
    for date in date_range(cohort_start_date, cohort_end_date):
        # Get cohort users (first seen on this date)
        cohort_users = get_users_by_first_seen(date)
        
        # Calculate D7 and D14 retention
        d7_retained = get_users_returning_on_day(cohort_users, date, 7)
        d14_retained = get_users_returning_on_day(cohort_users, date, 14)
        d30_retained = get_users_returning_on_day(cohort_users, date, 30)
        
        # Calculate core task completion
        core_task_users = get_users_completing_core_task(cohort_users)
        d7_core_retained = get_users_returning_on_day(core_task_users, date, 7)
        
        cohorts[date] = {
            "cohort_size": len(cohort_users),
            "core_task_users": len(core_task_users),
            "d7_retention": (d7_retained / len(cohort_users)) * 100 if cohort_users else 0,
            "d14_retention": (d14_retained / len(cohort_users)) * 100 if cohort_users else 0,
            "d30_retention": (d30_retained / len(cohort_users)) * 100 if cohort_users else 0,
            "d7_core_retention": (d7_core_retained / len(core_task_users)) * 100 if core_task_users else 0
        }
    
    return cohorts
```

### **Segmentation Strategy**
```python
# User segmentation for cohort analysis
user_segments = {
    "core_value_achievers": "users_completing_core_task",
    "non_core_users": "users_not_completing_core_task", 
    "operators": "users_with_operator_role",
    "developers": "users_with_developer_role",
    "traders": "users_with_trader_role"
}

def segment_cohorts(cohorts):
    segmented_cohorts = {}
    
    for date, cohort_data in cohorts.items():
        segmented_cohorts[date] = {
            "all_users": cohort_data,
            "core_value_achievers": build_segment_cohort(date, "core_value_achievers"),
            "non_core_users": build_segment_cohort(date, "non_core_users"),
            "by_role": {
                "operators": build_segment_cohort(date, "operators"),
                "developers": build_segment_cohort(date, "developers"), 
                "traders": build_segment_cohort(date, "traders")
            }
        }
    
    return segmented_cohorts
```

---

## 📈 **MEASURING CORRELATION WITH 30-DAY RETENTION**

### **Simple Correlation Analysis**
```python
import numpy as np
from scipy import stats
import matplotlib.pyplot as plt

def analyze_retention_correlation(cohorts):
    # Extract data points
    d7_retention = [cohort["d7_core_retention"] for cohort in cohorts.values()]
    d30_retention = [cohort["d30_retention"] for cohort in cohorts.values()]
    
    # Calculate Pearson correlation
    correlation, p_value = stats.pearsonr(d7_retention, d30_retention)
    
    # Linear regression
    slope, intercept, r_value, p_value, std_err = stats.linregress(d7_retention, d30_retention)
    
    # Generate predictions
    x_pred = np.array([min(d7_retention), max(d7_retention)])
    y_pred = slope * x_pred + intercept
    
    return {
        "correlation": correlation,
        "p_value": p_value,
        "regression": {
            "slope": slope,
            "intercept": intercept,
            "r_squared": r_value ** 2,
            "std_error": std_err
        },
        "predictions": list(zip(x_pred, y_pred)),
        "data_points": len(d7_retention)
    }

def create_retention_scatter_plot(cohorts):
    d7_retention = [cohort["d7_core_retention"] for cohort in cohorts.values()]
    d30_retention = [cohort["d30_retention"] for cohort in cohorts.values()]
    
    plt.figure(figsize=(10, 6))
    plt.scatter(d7_retention, d30_retention, alpha=0.7)
    
    # Add regression line
    analysis = analyze_retention_correlation(cohorts)
    x_pred, y_pred = zip(*analysis["predictions"])
    plt.plot(x_pred, y_pred, 'r--', label=f'Linear fit (R² = {analysis["regression"]["r_squared"]:.3f})')
    
    plt.xlabel('D7 Core Retention (%)')
    plt.ylabel('D30 Retention (%)')
    plt.title('D7 vs D30 Retention Correlation')
    plt.legend()
    plt.grid(True, alpha=0.3)
    
    return plt
```

### **Multiple Regression with D14**
```python
def analyze_multiple_regression(cohorts):
    # Extract data points
    d7_retention = [cohort["d7_core_retention"] for cohort in cohorts.values()]
    d14_retention = [cohort["d14_retention"] for cohort in cohorts.values()]
    d30_retention = [cohort["d30_retention"] for cohort in cohorts.values()]
    
    # Multiple regression
    X = np.column_stack((d7_retention, d14_retention))
    X = sm.add_constant(X)  # Add intercept
    
    model = sm.OLS(d30_retention, X).fit()
    
    return {
        "model_summary": model.summary(),
        "coefficients": {
            "intercept": model.params[0],
            "d7_coefficient": model.params[1],
            "d14_coefficient": model.params[2]
        },
        "r_squared": model.rsquared,
        "adjusted_r_squared": model.rsquared_adj,
        "p_values": model.pvalues.tolist()
    }
```

### **Interpretation Framework**
```python
def interpret_correlation_analysis(analysis):
    correlation = analysis["correlation"]
    r_squared = analysis["regression"]["r_squared"]
    
    interpretation = {
        "predictive_power": "",
        "recommendation": "",
        "confidence": ""
    }
    
    if correlation > 0.8:
        interpretation["predictive_power"] = "Very Strong - D7 is excellent predictor"
        interpretation["recommendation"] = "Focus heavily on D7 core activation as primary KPI"
        interpretation["confidence"] = "High confidence in using D7 for early retention signals"
    elif correlation > 0.6:
        interpretation["predictive_power"] = "Strong - D7 is good predictor"
        interpretation["recommendation"] = "Use D7 as leading indicator, monitor D14 for additional insight"
        interpretation["confidence"] = "Moderate-high confidence in D7 predictive value"
    elif correlation > 0.4:
        interpretation["predictive_power"] = "Moderate - D7 has predictive value but limitations"
        interpretation["recommendation"] = "Use D7 as one signal among several, investigate other factors"
        interpretation["confidence"] = "Moderate confidence - supplement with other metrics"
    else:
        interpretation["predictive_power"] = "Weak - D7 alone insufficient predictor"
        interpretation["recommendation"] = "Investigate other early indicators, reconsider core task definition"
        interpretation["confidence"] = "Low confidence - need different approach"
    
    return interpretation
```

---

## 🔒 **CI/CD CHECKLIST FOR AUTOMATED SAST INTEGRATION**

### **1. Tool Selection**
```markdown
- [ ] **Primary SAST Tool:** SonarQube/SonarCloud
- [ ] **Secondary Tools:** CodeQL (GitHub), Snyk Code
- [ ] **Coverage:** Python, Dart/Flutter, JavaScript, Infrastructure as Code
- [ ] **Integration:** GitHub Actions, GitLab CI, or equivalent
```

### **2. Project Configuration**
```markdown
- [ ] **SonarQube Project Setup:**
  - [ ] Project key: `merid-season1`
  - [ ] Organization configured
  - [ ] Quality gate rules defined
  
- [ ] **CodeQL Database Setup:**
  - [ ] Languages: Python, JavaScript
  - [ ] Scan paths: `core/`, `merid/`, `merid-ui/`, `scripts/`
  - [ ] Query packs: Security, Quality
  
- [ ] **Snyk Configuration:**
  - [ ] API token configured
  - [ ] Severity threshold: High and Critical
  - [ ] Auto-fix for safe vulnerabilities
```

### **3. CI Job Wiring**
```markdown
- [ ] **PR Triggers:**
  - [ ] SAST scan runs on all PRs to main
  - [ ] Results posted as PR comments
  - [ ] Block merge on new critical issues
  
- [ ] **Main Branch Triggers:**
  - [ ] Full SAST scan on every push
  - [ ] Results stored for baseline comparison
  - [ ] Security dashboard updated
  
- [ ] **Job Dependencies:**
  - [ ] Build job completes successfully
  - [ ] Tests pass before SAST scan
  - [ ] SAST results available before deploy
```

### **4. Policies and Thresholds**
```markdown
- [ ] **Quality Gate Rules:**
  - [ ] New critical vulnerabilities: FAIL
  - [ ] New high vulnerabilities: FAIL
  - [ ] Code coverage < 80%: WARN
  - [ ] Duplicated code > 3%: WARN
  
- [ ] **Security Rules:**
  - [ ] SQL injection: FAIL
  - [ ] XSS vulnerabilities: FAIL
  - [ ] Hardcoded secrets: FAIL
  - [ ] Insecure crypto: FAIL
  
- [ ] **Exception Process:**
  - [ ] Document exceptions in governance template
  - [ ] Require stakeholder approval
  - [ ] Set remediation timeline
  - [ ] Track in weekly dossiers
```

### **5. Deployment Gating**
```markdown
- [ ] **Merge Protection:**
  - [ ] Required status checks: SAST, Tests, Coverage
  - [ ] Branch protection rules enforced
  - [ ] Admin override capability documented
  
- [ ] **Deploy Protection:**
  - [ ] Deployment jobs depend on SAST success
  - [ ] Canary deployment requires clean SAST
  - [ ] Rollback triggers on SAST failures
  
- [ ] **Environment Promotion:**
  - [ ] Staging: Latest SAST pass required
  - [ ] Production: SAST pass + manual review
  - [ ] Hotfix: Exception process with documentation
```

### **6. Reporting Integration**
```markdown
- [ ] **Weekly Dossiers:**
  - [ ] SAST summary included
  - [ ] Vulnerability trends tracked
  - [ ] Exception status documented
  
- [ ] **Investor/Regulator Pack:**
  - [ ] Security posture section
  - [ ] SAST metrics and trends
  - [ ] Compliance evidence included
  
- [ ] **Release Evidence:**
  - [ ] SAST results attached to releases
  - [ ] Security scan artifacts stored
  - [ ] Audit trail maintained
```

---

## 🔄 **SAMPLE GITHUB ACTIONS WORKFLOW**

### **Complete CI + SonarQube Integration**
```yaml
name: CI + Security Scan

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  test-and-sast:
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
        with:
          fetch-depth: 0  # Needed for SonarQube analysis

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Set up Node.js
        uses: actions/setup-node@v4
        with:
          node-version: "18"

      - name: Install Python dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-cov

      - name: Install Node dependencies
        run: |
          cd merid-ui && npm install

      - name: Run Python tests with coverage
        run: |
          pytest --cov=core --cov=merid --cov=risk --cov=governance --cov-report=xml

      - name: Run JavaScript tests
        run: |
          cd merid-ui && npm test

      - name: SonarQube Scan
        uses: SonarSource/sonarqube-scan-action@v5
        env:
          SONAR_TOKEN: ${{ secrets.SONAR_TOKEN }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        with:
          projectBaseDir: .
          args: >
            -Dsonar.projectKey=merid-season1
            -Dsonar.organization=merid-org
            -Dsonar.python.version=3.11
            -Dsonar.javascript.lcov.reportPaths=merid-ui/coverage/lcov.info
            -Dsonar.coverage.exclusions=**/*_test.py,**/test/**,**/__pycache__/**
            -Dsonar.python.bandit.reportPaths=bandit-report.json

      - name: CodeQL Analysis
        uses: github/codeql-action/analyze@v2
        with:
          languages: python, javascript

      - name: Snyk Security Scan
        uses: snyk/actions/python@master
        env:
          SNYK_TOKEN: ${{ secrets.SNYK_TOKEN }}
        with:
          args: --severity-threshold=high

      - name: Upload coverage to Codecov
        uses: codecov/codecov-action@v3
        with:
          file: ./coverage.xml
          flags: unittests
          name: codecov-umbrella

  security-gate:
    runs-on: ubuntu-latest
    needs: test-and-sast
    if: github.event_name == 'pull_request'
    
    steps:
      - name: Check SonarQube Quality Gate
        run: |
          curl -u "${{ secrets.SONAR_TOKEN }}:" \
            "${{ secrets.SONAR_HOST_URL }}/api/qualitygates/project_status?analysisId=${{ github.sha }}" \
            | jq -r '.projectStatus.status'
          
          # Fail if quality gate is not OK
          if [ "$(curl -s -u "${{ secrets.SONAR_TOKEN }}:" \
            "${{ secrets.SONAR_HOST_URL }}/api/qualitygates/project_status?analysisId=${{ github.sha }}" \
            | jq -r '.projectStatus.status')" != "OK" ]; then
            echo "SonarQube Quality Gate failed"
            exit 1
          fi

      - name: Security Summary
        run: |
          echo "## Security Scan Summary" >> $GITHUB_STEP_SUMMARY
          echo "- SonarQube Quality Gate: ${{ steps.check-quality-gate.outputs.status }}" >> $GITHUB_STEP_SUMMARY
          echo "- CodeQL Analysis: Completed" >> $GITHUB_STEP_SUMMARY
          echo "- Snyk Scan: Completed" >> $GITHUB_STEP_SUMMARY
```

### **Branch Protection Rules**
```yaml
# GitHub branch protection settings
branch_protection:
  main:
    required_status_checks:
      strict: true
      contexts:
        - "test-and-sast"
        - "security-gate"
    
    enforce_admins: true
    required_linear_history: true
    require_pull_request_reviews: true
    dismiss_stale_reviews: true
    require_code_owner_reviews: true
```

---

## 📊 **RETENTION ANALYSIS AUTOMATION**

### **Weekly Cohort Analysis Script**
```python
def generate_weekly_retention_analysis():
    # Build cohorts for last 8 weeks
    end_date = datetime.now().date()
    start_date = end_date - timedelta(weeks=8)
    
    cohorts = build_retention_cohorts(start_date, end_date)
    segmented_cohorts = segment_cohorts(cohorts)
    
    # Analyze correlations
    correlation_analysis = analyze_retention_correlation(cohorts)
    multiple_regression = analyze_multiple_regression(cohorts)
    interpretation = interpret_correlation_analysis(correlation_analysis)
    
    # Generate report
    report = {
        "analysis_date": end_date.isoformat(),
        "cohorts_analyzed": len(cohorts),
        "correlation_analysis": correlation_analysis,
        "multiple_regression": multiple_regression,
        "interpretation": interpretation,
        "key_insights": extract_key_insights(correlation_analysis, cohorts),
        "recommendations": generate_recommendations(interpretation)
    }
    
    # Save to weekly dossier
    add_to_weekly_dossier("retention_analysis", report)
    
    return report

def extract_key_insights(analysis, cohorts):
    insights = []
    
    # Top performing cohorts
    top_cohorts = sorted(cohorts.items(), 
                        key=lambda x: x[1]["d30_retention"], 
                        reverse=True)[:3]
    
    insights.append({
        "type": "top_performers",
        "data": [{"date": date, "d30_retention": data["d30_retention"]} 
                for date, data in top_cohorts]
    })
    
    # Correlation strength
    if analysis["correlation"] > 0.8:
        insights.append({
            "type": "strong_correlation",
            "message": f"D7 retention strongly predicts D30 (r={analysis['correlation']:.3f})"
        })
    
    return insights

def generate_recommendations(interpretation):
    recommendations = []
    
    if "Very Strong" in interpretation["predictive_power"]:
        recommendations.append({
            "priority": "HIGH",
            "action": "Focus heavily on D7 core activation as primary KPI",
            "owner": "product_team"
        })
    
    if "Moderate" in interpretation["confidence"]:
        recommendations.append({
            "priority": "MEDIUM", 
            "action": "Investigate additional early indicators beyond D7",
            "owner": "data_team"
        })
    
    return recommendations
```

---

## 🎯 **IMPLEMENTATION ROADMAP**

### **Week 1: Event Instrumentation**
- [ ] Implement event tracking schema
- [ ] Deploy analytics event capture
- [ ] Set up cohort building logic
- [ ] Test core task completion tracking

### **Week 2: Retention Analysis**
- [ ] Build cohort analysis pipeline
- [ ] Implement correlation analysis
- [ ] Create retention dashboard
- [ ] Set up automated weekly reports

### **Week 3: SAST Integration**
- [ ] Configure SonarQube project
- [ ] Implement GitHub Actions workflow
- [ ] Set up branch protection rules
- [ ] Test security gate functionality

### **Week 4: Governance Integration**
- [ ] Integrate retention metrics into dossiers
- [ ] Add SAST results to investor pack
- [ ] Create war-game drills for security
- [ ] Document all processes

---

## 📈 **SUCCESS METRICS**

### **Retention Success**
- [ ] D7 core retention > 40%
- [ ] D7-D30 correlation > 0.7
- [ ] Cohort analysis automated
- [ ] Weekly retention reports generated

### **Security Success**
- [ ] SAST pipeline functional
- [ ] Zero critical vulnerabilities in production
- [ ] Security gates blocking deployments
- [ ] SAST results in investor pack

### **Governance Success**
- [ ] Retention metrics in weekly dossiers
- [ ] SAST evidence in governance reports
- [ ] Automated analysis and alerting
- [ ] Clear optimization recommendations

---

**🚀 This framework provides MERID Season 1 with the four key levers: single early retention metric (D7), clean cohort instrumentation, simple correlation analysis, and concrete SonarQube CI integration - all directly wired into the governance engine.**
