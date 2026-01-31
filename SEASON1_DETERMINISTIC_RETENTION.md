# 🎯 **MERID SEASON 1 DETERMINISTIC RETENTION FRAMEWORK**
**Last Updated:** 2026-01-26  
**Target:** Fully Deterministic Retention + SAST Integration

---

## 📊 **EARLY RETENTION METRIC TO PREDICT D30**

### **D7 Core Activation Retention**
**Definition:** Users who reached core value once and are active on day 7 after D0

```python
# Core value definition for MERID
core_value_sequence = [
    "dashboard_load_complete",
    "mode_and_risk_banners_viewed", 
    "positions_or_shadow_pnl_inspected"
]

# D7 core activation retention calculation
def calculate_d7_core_activation_retention(cohort_date):
    # Get users who completed core task at D0
    d0_users = get_users_completing_core_task(cohort_date)
    
    # Get users who are active on D7 (D0 + 7 days)
    d7_active = get_users_active_on_date(d0_users, cohort_date + timedelta(days=7))
    
    # Calculate retention rate
    return (len(d7_active) / len(d0_users)) * 100 if d0_users else 0

# D30 retention for correlation
def calculate_d30_retention(cohort_date):
    d0_users = get_users_completing_core_task(cohort_date)
    d30_active = get_users_active_on_date(d0_users, cohort_date + timedelta(days=30))
    return (len(d30_active) / len(d0_users)) * 100 if d0_users else 0
```

**Target Metrics:**
- **Core task completion:** > 60% of new users
- **D7 core activation retention:** > 40% (strong D30 predictor)
- **D30 retention:** > 25% (strongly correlated with D7)

**Why This Works:**
- **D7 reflects repeatable value discovery** and habit formation
- **Core task restriction** ensures meaningful engagement
- **Strong correlation** with long-term retention proven across products

---

## 🔧 **EVENT SCHEMA FOR D0-D30 LIFECYCLE**

### **Events Table Schema**
```sql
-- Core events table
CREATE TABLE events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR NOT NULL,
    event_name VARCHAR NOT NULL,
    event_time TIMESTAMP NOT NULL,
    properties JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    
    INDEX idx_events_user_time (user_id, event_time),
    INDEX idx_events_name_time (event_name, event_time)
);

-- Materialized view for user first activity
CREATE MATERIALIZED VIEW user_first_active AS
SELECT 
    user_id,
    MIN(event_time::date) AS first_active_at,
    MIN(CASE WHEN event_name = 'core_value_experienced' 
         THEN event_time::date END) AS first_core_value_at
FROM events 
WHERE event_name IN ('first_active', 'core_value_experienced')
GROUP BY user_id;
```

### **Canonical Events**
```python
canonical_events = {
    "first_active": {
        "description": "User's first meaningful action",
        "triggers": ["dashboard_load_complete", "session_duration > 60s"],
        "defines_d0": True
    },
    "session_active": {
        "description": "User reached active state in session",
        "triggers": ["dashboard_loaded", "key_screen_viewed"],
        "used_for_retention": True
    },
    "core_value_experienced": {
        "description": "User completed core value sequence",
        "triggers": ["positions_viewed", "risk_banners_seen", "shadow_pnl_inspected"],
        "used_for_segmentation": True
    }
}
```

### **Event Capture Implementation**
```python
def capture_user_event(user_id, event_name, properties=None):
    event_data = {
        "user_id": user_id,
        "event_name": event_name,
        "event_time": datetime.utcnow(),
        "properties": properties or {}
    }
    
    # Insert into events table
    insert_event(event_data)
    
    # Handle special events
    if event_name == "first_active":
        update_user_first_active(user_id, datetime.utcnow())
    elif event_name == "core_value_experienced":
        update_user_core_value(user_id, datetime.utcnow())

def update_user_first_active(user_id, event_time):
    # Only set if not already set
    sql = """
    INSERT INTO user_first_active (user_id, first_active_at)
    SELECT %s, %s
    WHERE NOT EXISTS (
        SELECT 1 FROM user_first_active WHERE user_id = %s
    )
    """
    execute_sql(sql, (user_id, event_time.date(), user_id))
```

---

## 📈 **D7 AND D14 COHORT MEMBERSHIP DEFINITIONS**

### **Cohort Date Definition**
```python
def get_cohort_date(user_id):
    """Get D0 cohort date for a user"""
    sql = """
    SELECT first_active_at 
    FROM user_first_active 
    WHERE user_id = %s
    """
    result = execute_sql(sql, (user_id,))
    return result[0]['first_active_at'] if result else None

def is_user_retained_on_day(user_id, cohort_date, day_number):
    """Check if user is retained on specific day after D0"""
    target_date = cohort_date + timedelta(days=day_number)
    
    sql = """
    SELECT 1 
    FROM events 
    WHERE user_id = %s 
      AND event_name = 'session_active'
      AND DATE(event_time) = %s
    LIMIT 1
    """
    result = execute_sql(sql, (user_id, target_date))
    return len(result) > 0
```

### **D7 and D14 Retention Calculation**
```python
def calculate_cohort_retention(cohort_date, day_number):
    """Calculate retention for a specific cohort and day"""
    
    # Get all users in cohort
    sql = """
    SELECT user_id 
    FROM user_first_active 
    WHERE first_active_at = %s
    """
    cohort_users = [row['user_id'] for row in execute_sql(sql, (cohort_date,))]
    
    if not cohort_users:
        return {"cohort_size": 0, "retained_users": 0, "retention_rate": 0}
    
    # Count retained users
    retained_count = 0
    for user_id in cohort_users:
        if is_user_retained_on_day(user_id, cohort_date, day_number):
            retained_count += 1
    
    retention_rate = (retained_count / len(cohort_users)) * 100
    
    return {
        "cohort_size": len(cohort_users),
        "retained_users": retained_count,
        "retention_rate": retention_rate
    }

def calculate_d7_d14_retention(cohort_date):
    """Calculate both D7 and D14 retention for a cohort"""
    d7_retention = calculate_cohort_retention(cohort_date, 7)
    d14_retention = calculate_cohort_retention(cohort_date, 14)
    
    return {
        "cohort_date": cohort_date.isoformat(),
        "d7_retention": d7_retention,
        "d14_retention": d14_retention
    }
```

### **Core Value Segmentation**
```python
def calculate_core_value_retention(cohort_date, day_number):
    """Calculate retention among users who experienced core value"""
    
    # Get users who experienced core value at D0
    sql = """
    SELECT user_id 
    FROM user_first_active 
    WHERE first_active_at = %s 
      AND first_core_value_at IS NOT NULL
    """
    core_value_users = [row['user_id'] for row in execute_sql(sql, (cohort_date,))]
    
    if not core_value_users:
        return {"cohort_size": 0, "retained_users": 0, "retention_rate": 0}
    
    # Count retained users
    retained_count = 0
    for user_id in core_value_users:
        if is_user_retained_on_day(user_id, cohort_date, day_number):
            retained_count += 1
    
    retention_rate = (retained_count / len(core_value_users)) * 100
    
    return {
        "cohort_size": len(core_value_users),
        "retained_users": retained_count,
        "retention_rate": retention_rate
    }
```

---

## 📊 **SQL EXAMPLE: D7 → D30 RETENTION CONVERSION**

### **Complete SQL Implementation**
```sql
-- Materialized view for user first activity
CREATE MATERIALIZED VIEW user_first_active AS
SELECT 
    user_id,
    MIN(event_time::date) AS first_active_at,
    MIN(CASE WHEN event_name = 'core_value_experienced' 
         THEN event_time::date END) AS first_core_value_at
FROM events 
WHERE event_name IN ('first_active', 'core_value_experienced')
GROUP BY user_id;

-- Refresh materialized view periodically
CREATE OR REPLACE FUNCTION refresh_user_first_active()
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW user_first_active;
END;
$$ LANGUAGE plpgsql;

-- D7 to D30 retention conversion analysis
WITH user_first AS (
  SELECT
    user_id,
    first_active_at AS cohort_date
  FROM user_first_active
),

activity_days AS (
  SELECT
    uf.user_id,
    uf.cohort_date,
    (e.event_time::date - uf.cohort_date) AS activity_day
  FROM user_first uf
  JOIN events e
    ON e.user_id = uf.user_id
   AND e.event_name = 'session_active'
   AND e.event_time::date BETWEEN uf.cohort_date
                               AND uf.cohort_date + INTERVAL '30 days'
),

retention_by_cohort AS (
  SELECT
    cohort_date,
    COUNT(DISTINCT user_id) AS cohort_size,
    COUNT(DISTINCT CASE WHEN activity_day = 7  THEN user_id END) AS d7_users,
    COUNT(DISTINCT CASE WHEN activity_day = 30 THEN user_id END) AS d30_users
  FROM activity_days
  GROUP BY cohort_date
),

core_value_retention AS (
  SELECT
    uf.cohort_date,
    COUNT(DISTINCT uf.user_id) AS core_value_cohort_size,
    COUNT(DISTINCT CASE WHEN ad.activity_day = 7  THEN uf.user_id END) AS d7_core_users,
    COUNT(DISTINCT CASE WHEN ad.activity_day = 30 THEN uf.user_id END) AS d30_core_users
  FROM user_first uf
  JOIN activity_days ad
    ON ad.user_id = uf.user_id
   AND uf.first_core_value_at IS NOT NULL
  GROUP BY uf.cohort_date
)

SELECT
  rc.cohort_date,
  rc.cohort_size,
  rc.d7_users,
  rc.d30_users,
  rc.d7_users::decimal / rc.cohort_size                AS d7_retention,
  rc.d30_users::decimal / rc.cohort_size               AS d30_retention,
  CASE WHEN rc.d7_users > 0
       THEN rc.d30_users::decimal / rc.d7_users
       ELSE NULL
  END                                            AS d7_to_d30_conversion,
  
  -- Core value segmentation
  cvr.core_value_cohort_size,
  cvr.d7_core_users,
  cvr.d30_core_users,
  cvr.d7_core_users::decimal / cvr.core_value_cohort_size AS d7_core_retention,
  cvr.d30_core_users::decimal / cvr.core_value_cohort_size AS d30_core_retention,
  CASE WHEN cvr.d7_core_users > 0
       THEN cvr.d30_core_users::decimal / cvr.d7_core_users
       ELSE NULL
  END                                            AS d7_core_to_d30_conversion
  
FROM retention_by_cohort rc
LEFT JOIN core_value_retention cvr ON rc.cohort_date = cvr.cohort_date
ORDER BY rc.cohort_date DESC;
```

---

## 📈 **CONFIDENCE INTERVALS FOR RETENTION RATES**

### **Binomial Proportion Confidence Intervals**
```python
import math
from scipy import stats

def calculate_retention_ci(retained_count, cohort_size, confidence_level=0.95):
    """
    Calculate confidence interval for retention rate using Wilson method
    """
    if cohort_size == 0:
        return {"lower": 0, "point": 0, "upper": 0}
    
    point_estimate = retained_count / cohort_size
    z_score = stats.norm.ppf(1 - (1 - confidence_level) / 2)
    
    # Wilson score interval
    denominator = 1 + z_score**2 / cohort_size
    centre = (point_estimate + z_score**2 / (2 * cohort_size)) / denominator
    margin = (z_score * math.sqrt(point_estimate * (1 - point_estimate) / cohort_size + 
                                    z_score**2 / (4 * cohort_size**2))) / denominator
    
    return {
        "lower": max(0, centre - margin),
        "point": point_estimate,
        "upper": min(1, centre + margin),
        "method": "wilson"
    }

def calculate_cohort_retention_with_ci(cohort_date, day_number, confidence_level=0.95):
    """Calculate retention with confidence intervals"""
    
    # Get cohort data
    sql = """
    SELECT user_id 
    FROM user_first_active 
    WHERE first_active_at = %s
    """
    cohort_users = [row['user_id'] for row in execute_sql(sql, (cohort_date,))]
    
    if not cohort_users:
        return {"cohort_size": 0, "retention_rate": 0, "ci": {"lower": 0, "point": 0, "upper": 0}}
    
    # Count retained users
    retained_count = 0
    for user_id in cohort_users:
        if is_user_retained_on_day(user_id, cohort_date, day_number):
            retained_count += 1
    
    # Calculate retention rate and CI
    retention_rate = retained_count / len(cohort_users)
    ci = calculate_retention_ci(retained_count, len(cohort_users), confidence_level)
    
    return {
        "cohort_size": len(cohort_users),
        "retained_users": retained_count,
        "retention_rate": retention_rate,
        "confidence_interval": ci,
        "retention_rate_percent": retention_rate * 100
    }
```

### **Clopper-Pearson Exact Interval**
```python
def calculate_exact_binomial_ci(retained_count, cohort_size, confidence_level=0.95):
    """Calculate exact binomial confidence interval using Clopper-Pearson"""
    
    alpha = 1 - confidence_level
    
    # Lower bound
    lower_beta = stats.beta.ppf(alpha/2, retained_count, cohort_size - retained_count + 1)
    
    # Upper bound  
    upper_beta = stats.beta.ppf(1 - alpha/2, retained_count + 1, cohort_size - retained_count)
    
    return {
        "lower": max(0, lower_beta),
        "point": retained_count / cohort_size,
        "upper": min(1, upper_beta),
        "method": "clopper_pearson"
    }
```

---

## 📊 **STATISTICAL TEST FOR RETENTION CORRELATION**

### **Correlation Analysis Implementation**
```python
import numpy as np
from scipy import stats
import pandas as pd

def analyze_retention_correlation(start_date, end_date):
    """Analyze correlation between D7 and D30 retention across cohorts"""
    
    # Build cohort data
    cohorts = []
    current_date = start_date
    
    while current_date <= end_date:
        d7_data = calculate_cohort_retention_with_ci(current_date, 7)
        d30_data = calculate_cohort_retention_with_ci(current_date, 30)
        
        if d7_data["cohort_size"] > 0 and d30_data["cohort_size"] > 0:
            cohorts.append({
                "cohort_date": current_date,
                "d7_retention": d7_data["retention_rate"],
                "d30_retention": d30_data["retention_rate"],
                "d7_ci": d7_data["confidence_interval"],
                "d30_ci": d30_data["confidence_interval"],
                "cohort_size": d7_data["cohort_size"]
            })
        
        current_date += timedelta(days=1)
    
    if len(cohorts) < 3:
        return {"error": "Insufficient cohort data for correlation analysis"}
    
    # Extract data for correlation
    d7_rates = [c["d7_retention"] for c in cohorts]
    d30_rates = [c["d30_retention"] for c in cohorts]
    
    # Pearson correlation
    correlation, p_value = stats.pearsonr(d7_rates, d30_rates)
    
    # Linear regression
    slope, intercept, r_value, p_value_reg, std_err = stats.linregress(d7_rates, d30_rates)
    
    # Predictions and R-squared
    x_pred = np.array([min(d7_rates), max(d7_rates)])
    y_pred = slope * x_pred + intercept
    r_squared = r_value ** 2
    
    # Spearman correlation (for monotonic relationship)
    spearman_corr, spearman_p = stats.spearmanr(d7_rates, d30_rates)
    
    return {
        "analysis_period": f"{start_date} to {end_date}",
        "cohorts_analyzed": len(cohorts),
        "correlation": {
            "pearson": {
                "correlation": correlation,
                "p_value": p_value,
                "interpretation": interpret_correlation(correlation)
            },
            "spearman": {
                "correlation": spearman_corr,
                "p_value": spearman_p,
                "interpretation": interpret_correlation(spearman_corr)
            }
        },
        "regression": {
            "slope": slope,
            "intercept": intercept,
            "r_squared": r_squared,
            "std_error": std_err,
            "prediction_equation": f"D30 = {intercept:.3f} + {slope:.3f} * D7",
            "interpretation": interpret_regression(r_squared)
        },
        "data_points": {
            "d7_rates": d7_rates,
            "d30_rates": d30_rates,
            "cohort_details": cohorts
        }
    }

def interpret_correlation(correlation):
    """Interpret correlation strength"""
    abs_corr = abs(correlation)
    if abs_corr >= 0.8:
        return "Very strong"
    elif abs_corr >= 0.6:
        return "Strong"
    elif abs_corr >= 0.4:
        return "Moderate"
    elif abs_corr >= 0.2:
        return "Weak"
    else:
        return "Very weak"

def interpret_regression(r_squared):
    """Interpret R-squared value"""
    if r_squared >= 0.8:
        return "Excellent predictive power"
    elif r_squared >= 0.6:
        return "Good predictive power"
    elif r_squared >= 0.4:
        return "Moderate predictive power"
    elif r_squared >= 0.2:
        return "Weak predictive power"
    else:
        return "Very weak predictive power"
```

### **Multiple Regression with D14**
```python
def analyze_multiple_regression(start_date, end_date):
    """Analyze D7 and D14 as predictors of D30 retention"""
    
    import statsmodels.api as sm
    
    # Build cohort data with D7, D14, D30
    cohorts = []
    current_date = start_date
    
    while current_date <= end_date:
        d7_data = calculate_cohort_retention_with_ci(current_date, 7)
        d14_data = calculate_cohort_retention_with_ci(current_date, 14)
        d30_data = calculate_cohort_retention_with_ci(current_date, 30)
        
        if all(data["cohort_size"] > 0 for data in [d7_data, d14_data, d30_data]):
            cohorts.append({
                "cohort_date": current_date,
                "d7_retention": d7_data["retention_rate"],
                "d14_retention": d14_data["retention_rate"],
                "d30_retention": d30_data["retention_rate"]
            })
        
        current_date += timedelta(days=1)
    
    if len(cohorts) < 3:
        return {"error": "Insufficient cohort data for regression analysis"}
    
    # Prepare data for regression
    df = pd.DataFrame(cohorts)
    X = df[['d7_retention', 'd14_retention']]
    X = sm.add_constant(X)  # Add intercept
    y = df['d30_retention']
    
    # Fit multiple regression
    model = sm.OLS(y, X).fit()
    
    return {
        "model_summary": model.summary().as_text(),
        "coefficients": {
            "intercept": model.params[0],
            "d7_coefficient": model.params[1],
            "d14_coefficient": model.params[2]
        },
        "r_squared": model.rsquared,
        "adjusted_r_squared": model.rsquared_adj,
        "p_values": model.pvalues.to_dict(),
        "interpretation": {
            "predictive_power": interpret_regression(model.rsquared),
            "d7_significance": "significant" if model.pvalues[1] < 0.05 else "not significant",
            "d14_significance": "significant" if model.pvalues[2] < 0.05 else "not significant",
            "d14_additional_value": "adds value" if model.rsquared_adj > 0.6 else "limited additional value"
        }
    }
```

---

## 🔄 **GOVERNANCE ENGINE INTEGRATION**

### **Weekly Dossier Integration**
```python
def add_retention_analysis_to_weekly_dossier(week_number):
    """Add comprehensive retention analysis to weekly dossier"""
    
    end_date = datetime.now().date()
    start_date = end_date - timedelta(weeks=8)
    
    # Analyze correlations
    correlation_analysis = analyze_retention_correlation(start_date, end_date)
    multiple_regression = analyze_multiple_regression(start_date, end_date)
    
    # Get latest cohort data
    latest_cohort = end_date - timedelta(days=7)
    d7_retention = calculate_cohort_retention_with_ci(latest_cohort, 7)
    d30_retention = calculate_cohort_retention_with_ci(latest_cohort, 30)
    
    # Generate insights
    insights = generate_retention_insights(correlation_analysis, multiple_regression)
    
    retention_data = {
        "week_number": week_number,
        "analysis_date": end_date.isoformat(),
        "latest_cohort": {
            "cohort_date": latest_cohort.isoformat(),
            "d7_retention": d7_retention,
            "d30_retention": d30_retention
        },
        "correlation_analysis": correlation_analysis,
        "multiple_regression": multiple_regression,
        "insights": insights,
        "recommendations": generate_retention_recommendations(insights)
    }
    
    # Add to weekly dossier
    add_to_weekly_dossier("retention_analysis", retention_data)
    
    return retention_data

def generate_retention_insights(correlation_analysis, multiple_regression):
    """Generate key insights from retention analysis"""
    
    insights = []
    
    # Correlation strength
    pearson_corr = correlation_analysis["correlation"]["pearson"]["correlation"]
    if abs(pearson_corr) > 0.7:
        insights.append({
            "type": "strong_predictor",
            "message": f"D7 retention strongly predicts D30 (r={pearson_corr:.3f})",
            "confidence": "high"
        })
    
    # Regression performance
    r_squared = multiple_regression["r_squared"]
    if r_squared > 0.6:
        insights.append({
            "type": "predictive_power",
            "message": f"D7 and D14 explain {r_squared:.1%} of D30 retention variance",
            "confidence": "high"
        })
    
    # D14 additional value
    d14_significant = multiple_regression["interpretation"]["d14_significance"] == "significant"
    if d14_significant:
        insights.append({
            "type": "additional_predictor",
            "message": "D14 retention provides additional predictive value beyond D7",
            "confidence": "moderate"
        })
    
    return insights

def generate_retention_recommendations(insights):
    """Generate actionable recommendations based on insights"""
    
    recommendations = []
    
    for insight in insights:
        if insight["type"] == "strong_predictor" and insight["confidence"] == "high":
            recommendations.append({
                "priority": "HIGH",
                "action": "Focus heavily on D7 core activation as primary KPI",
                "owner": "product_team",
                "timeline": "immediate"
            })
        
        elif insight["type"] == "additional_predictor":
            recommendations.append({
                "priority": "MEDIUM",
                "action": "Monitor D14 retention as secondary leading indicator",
                "owner": "data_team",
                "timeline": "next_sprint"
            })
    
    return recommendations
```

### **Investor/Regulator Pack Integration**
```python
def add_retention_metrics_to_investor_pack():
    """Add retention metrics to Season 1 Investor/Regulator Pack"""
    
    # Get recent correlation analysis
    end_date = datetime.now().date()
    start_date = end_date - timedelta(weeks=12)
    
    correlation_analysis = analyze_retention_correlation(start_date, end_date)
    
    # Generate retention summary
    retention_summary = {
        "early_predictor": {
            "metric": "D7 Core Activation Retention",
            "target": "> 40%",
            "current_status": get_latest_d7_retention(),
            "correlation_with_d30": correlation_analysis["correlation"]["pearson"]["correlation"],
            "predictive_power": correlation_analysis["regression"]["interpretation"]
        },
        "statistical_validation": {
            "cohorts_analyzed": correlation_analysis["cohorts_analyzed"],
            "confidence_intervals": "Wilson method for binomial proportions",
            "statistical_significance": correlation_analysis["correlation"]["pearson"]["p_value"] < 0.05
        },
        "governance_integration": {
            "weekly_dossier_inclusion": True,
            "promotion_gate_impact": "Readiness score factor",
            "evidence_generation": "Automated"
        }
    }
    
    # Add to investor pack
    update_investor_pack_section("retention_metrics", retention_summary)
    
    return retention_summary
```

---

## 📋 **IMPLEMENTATION ROADMAP**

### **Week 1: Event Schema Implementation**
- [ ] Create events table with proper indexes
- [ ] Implement canonical event definitions
- [ ] Build user_first_active materialized view
- [ ] Create event capture functions

### **Week 2: Cohort Analysis Pipeline**
- [ ] Implement D7/D14/D30 retention calculations
- [ ] Build confidence interval calculations
- [ ] Create cohort retention dashboard
- [ ] Test with sample data

### **Week 3: Statistical Analysis**
- [ ] Implement correlation analysis functions
- [ ] Build regression analysis pipeline
- [ ] Create visualization for correlation
- [ ] Validate statistical significance

### **Week 4: Governance Integration**
- [ ] Integrate retention metrics into weekly dossiers
- [ ] Add retention analysis to investor pack
- [ ] Create retention-based promotion gates
- [ ] Document all processes

---

## 🎯 **SUCCESS METRICS**

### **Retention Success**
- [ ] D7 core activation retention > 40%
- [ ] D7-D30 correlation > 0.7
- [ ] Confidence intervals calculated for all cohorts
- [ ] Statistical significance validated

### **Technical Success**
- [ ] Event schema implemented and functional
- [ ] Cohort analysis pipeline automated
- [ ] Statistical analysis working correctly
- [ ] Governance integration complete

### **Business Success**
- [ ] Early retention predictor validated
- [ ] Actionable insights generated
- [ ] Investor pack enhanced with retention metrics
- [ ] Product optimization recommendations provided

---

**🚀 This framework provides MERID Season 1 with fully deterministic retention analysis: D7 core activation as the best early predictor of D30 retention, complete event schema for D0-D30 lifecycle, SQL implementations for cohort analysis, confidence intervals for statistical rigor, and correlation analysis to validate the predictor - all directly integrated into the governance engine.**
