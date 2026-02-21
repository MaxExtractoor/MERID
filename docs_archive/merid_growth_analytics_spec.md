# 📈 MERID Growth and Analytics Specification

**Purpose:** Define comprehensive analytics, tracking, and growth strategy for MERID's unified platform  
**Version:** 1.0  
**Date:** 2026-01-26  
**Target:** Professional traders and quant operators with path to broader market  

---

## 🎯 **EXECUTIVE SUMMARY**

### **Growth Strategy Overview**
MERID's growth strategy focuses on **professional trader activation** and **quant operator efficiency** while maintaining **enterprise-grade safety**. Our approach prioritizes depth over breadth initially, then expands to adjacent user segments.

### **Key Success Metrics**
- **Activation:** Professional traders running strategies in CANARY mode within 7 days
- **Retention:** >90% retention for activated users after 30 days
- **Efficiency:** >50% improvement in trading operations efficiency
- **Safety:** Zero undetected risk incidents or compliance breaches

### **Analytics Philosophy**
- **Event-driven tracking** over page views
- **Behavioral segmentation** for user personas
- **Cohort-based analysis** for LTV calculation
- **Real-time monitoring** for operational insights

---

## 👥 **USER SEGMENTATION AND PERSONAS**

### **Primary Segments**

#### **1) Operations Engineer / Quant Operator (70% focus)**
**Profile:** Technical trader running MERID in production  
**Activation Goal:** Run strategy in CANARY mode within 48 hours  
**Retention Goal:** Daily active usage with <5% session abandonment  

**Key Behaviors:**
- System health monitoring frequency
- Strategy state changes (OFF → DRY_RUN → CANARY)
- Risk limit adjustments
- Incident response time
- Dashboard session duration

#### **2) Power Trader / Quant (25% focus)**
**Profile:** Advanced user optimizing strategies and parameters  
**Activation Goal:** Deep dive into analytics within 72 hours  
**Retention Goal:** Weekly strategy iterations and performance analysis  

**Key Behaviors:**
- Strategy parameter adjustments
- Trade blotter analysis frequency
- Performance drill-down usage
- Historical data analysis
- Strategy comparison activities

#### **3) Risk Oversight (5% focus)**
**Profile:** Compliance and risk management role  
**Activation Goal:** Review risk dashboard within 24 hours  
**Retention Goal:** Weekly risk assessment and reporting  

**Key Behaviors:**
- Risk dashboard access frequency
- Limit utilization monitoring
- Compliance report generation
- Audit trail reviews
- Incident investigation

---

## 📊 **EVENT TRACKING ARCHITECTURE**

### **Event Naming Convention**
**Pattern:** `noun_verb` with snake_case  
**Examples:** `strategy_started`, `trade_executed`, `limit_updated`

### **Core Event Schema**

```json
{
  "event_name": "string",
  "user_id": "string", 
  "timestamp": "ISO8601",
  "session_id": "string",
  "properties": {
    "key": "value"
  },
  "context": {
    "env": "prod_canary|staging",
    "app_version": "string",
    "client": "web|mobile|api",
    "ip": "string"
  }
}
```

### **Critical Event Categories**

#### **Strategy Lifecycle Events**
- `strategy_created` - New strategy configuration
- `strategy_started` - Strategy activated (with mode)
- `strategy_stopped` - Strategy deactivated
- `strategy_mode_changed` - DRY_RUN → CANARY → FULL
- `strategy_deleted` - Strategy removal

#### **Trading Events**
- `trade_executed` - Individual trade execution
- `trade_detail_viewed` - Trade analysis access
- `order_placed` - Order submission
- `order_cancelled` - Order cancellation
- `order_modified` - Order amendment

#### **Risk Management Events**
- `limit_viewed` - Risk limit inspection
- `limit_updated` - Limit modification
- `risk_alert_triggered` - Risk threshold breach
- `kill_switch_activated` - Emergency stop
- `compliance_check_failed` - Pre-trade rejection

#### **Monitoring Events**
- `dashboard_viewed` - Main dashboard access
- `alert_viewed` - Alert inspection
- `incident_created` - New incident
- `incident_resolved` - Incident closure
- `system_health_checked` - Health status review

#### **Session Events**
- `session_started` - User session initiation
- `session_ended` - Session conclusion
- `tab_changed` - Navigation between sections
- `feature_used` - Specific feature interaction

---

## 🎯 **ACTIVATION METRICS AND FUNNELS**

### **Primary Activation Funnel**

#### **Funnel Stage 1: Onboarding (Day 0-1)**
**Goal:** Complete initial setup and system familiarization  
**Events:** `session_started`, `dashboard_viewed`, `strategy_created`

**Success Criteria:**
- [ ] User completes initial dashboard tour
- [ ] User creates first strategy configuration
- [ ] User understands basic navigation (3+ distinct sections visited)

**Metrics:**
- **Onboarding completion rate:** % users completing all onboarding steps
- **Time to first strategy:** Average time from signup to strategy creation
- **Navigation proficiency:** Number of distinct sections visited

#### **Funnel Stage 2: Dry Run Testing (Day 1-3)**
**Goal:** Test strategy in safe environment  
**Events:** `strategy_started` (mode=DRY_RUN), `strategy_stopped`, `dashboard_viewed`

**Success Criteria:**
- [ ] Strategy runs in DRY_RUN for ≥2 hours
- [ ] User monitors strategy performance
- [ ] User understands strategy behavior patterns

**Metrics:**
- **DRY_RUN adoption rate:** % users running strategies in DRY_RUN
- **DRY_RUN duration:** Average time in DRY_RUN mode
- **Monitoring engagement:** Dashboard views during DRY_RUN

#### **Funnel Stage 3: Canary Activation (Day 3-7)**
**Goal:** Graduate to real-money canary trading  
**Events:** `strategy_mode_changed` (DRY_RUN→CANARY), `trade_executed`, `limit_viewed`

**Success Criteria:**
- [ ] Strategy transitions to CANARY mode
- [ ] At least 1 real trade executed
- [ ] Risk limits reviewed and confirmed

**Metrics:**
- **CANARY conversion rate:** % users transitioning from DRY_RUN to CANARY
- **First trade latency:** Time from CANARY activation to first trade
- **Risk awareness:** % users reviewing limits before CANARY

### **Secondary Activation Funnels**

#### **Power Trader Funnel**
**Goal:** Deep engagement with analytics and optimization  
**Events:** `trade_detail_viewed`, `strategy_mode_changed`, `limit_updated`

**Success Criteria:**
- [ ] Analyzes ≥5 trades in detail
- [ ] Adjusts ≥2 strategy parameters
- [ ] Compares performance across time periods

#### **Risk Oversight Funnel**
**Goal:** Comprehensive risk management engagement  
**Events:** `limit_viewed`, `risk_alert_triggered`, `compliance_check_failed`

**Success Criteria:**
- [ ] Reviews all risk limits
- [ ] Responds to risk alerts
- [ ] Generates compliance reports

---

## 📈 **RETENTION ANALYSIS FRAMEWORK**

### **Retention Definition**
**Active User:** User who both (1) runs at least one strategy (any mode) AND (2) views P&L in a period

### **Cohort Analysis Structure**

#### **Cohort Definition**
**Primary:** Signup month (Jan-2026, Feb-2026, etc.)  
**Secondary:** Acquisition channel (content, referral, paid_ads, enterprise)  
**Tertiary:** Onboarding variant (standard, enhanced, guided)

#### **Retention Grid Construction**
```
            | Day 0 | Day 1 | Day 7 | Day 30 | Day 90 |
-------------------------------------------------------
Jan-2026    | 100%  | 85%   | 72%   | 65%    | 58%   |
Feb-2026    | 100%  | 87%   | 74%   | 68%    | 61%   |
Mar-2026    | 100%  | 89%   | 76%   | 71%    | 64%   |
```

#### **Retention Targets**
- **Day 1:** >85% (immediate engagement)
- **Day 7:** >70% (weekly active)
- **Day 30:** >65% (monthly active)
- **Day 90:** >60% (quarterly active)

### **Behavioral Retention Indicators**

#### **High-Retention Behaviors**
- **Strategy diversity:** Users with ≥2 active strategies
- **Parameter optimization:** Users who adjust ≥3 parameters
- **Risk engagement:** Users who review limits weekly
- **Analytics depth:** Users who analyze ≥10 trades

#### **Churn Prediction Indicators**
- **Session abandonment:** <5 minutes average session
- **Single strategy use:** Only one strategy ever created
- **No risk engagement:** Never viewed risk limits
- **No parameter changes:** Default settings only

---

## 💰 **LTV CALCULATION METHODOLOGY**

### **LTV Components**

#### **Revenue Components**
- **Subscription fees:** Monthly/annual platform fees
- **Volume-based fees:** % of trading volume
- **Premium features:** Advanced analytics, API access
- **Enterprise services:** Custom integrations, support

#### **Value Components (for internal LTV)**
- **P&L uplift:** Incremental trading profits attributable to MERID
- **Risk reduction:** Value of avoided losses through risk controls
- **Efficiency gains:** Time savings in trading operations
- **Compliance value:** Reduced regulatory compliance costs

### **LTV Calculation Formula**

#### **12-Month LTV**
```
LTV_12m = (Monthly_Revenue × 12) + (Quarterly_Value × 4) - CAC
```

#### **Cohort LTV**
```
Cohort_LTV = Σ(Revenue_t + Value_t) for t=1 to 12 ÷ Initial_Users
```

#### **LTV/CAC Ratio**
```
LTV/CAC = (12-Month LTV) ÷ Customer_Acquisition_Cost
```

### **LTV Targets by Segment**

#### **Operations Engineer**
- **12-Month LTV:** $2,400 - $6,000
- **LTV/CAC Ratio:** >3:1
- **Primary Value:** Efficiency gains and risk reduction

#### **Power Trader**
- **12-Month LTV:** $4,800 - $12,000
- **LTV/CAC Ratio:** >4:1
- **Primary Value:** P&L uplift and advanced features

#### **Risk Oversight**
- **12-Month LTV:** $1,800 - $3,600
- **LTV/CAC Ratio:** >2.5:1
- **Primary Value:** Compliance and risk management

---

## 🔄 **COHORT ANALYSIS IMPLEMENTATION**

### **Data Schema**

#### **Users Table**
```sql
CREATE TABLE users (
    user_id VARCHAR(255) PRIMARY KEY,
    signup_date DATE,
    acquisition_channel VARCHAR(50),
    onboarding_variant VARCHAR(50),
    persona VARCHAR(50),
    created_at TIMESTAMP
);
```

#### **Events Table**
```sql
CREATE TABLE events (
    event_id VARCHAR(255) PRIMARY KEY,
    user_id VARCHAR(255),
    event_name VARCHAR(100),
    timestamp TIMESTAMP,
    session_id VARCHAR(255),
    properties JSON,
    context JSON,
    created_at TIMESTAMP
);
```

#### **Cohort Summary Table**
```sql
CREATE TABLE cohort_retention (
    cohort_id VARCHAR(100),
    period_number INT,
    retention_rate DECIMAL(5,2),
    active_users INT,
    total_users INT,
    created_at TIMESTAMP
);
```

### **SQL Queries for Analysis**

#### **Cohort Retention Calculation**
```sql
WITH user_cohorts AS (
    SELECT 
        user_id,
        DATE_TRUNC('month', signup_date) as cohort_month,
        DATE_TRUNC('day', signup_date) as cohort_day
    FROM users
),
activity_periods AS (
    SELECT 
        u.user_id,
        c.cohort_month,
        DATEDIFF(day, c.cohort_day, DATE_TRUNC('day', e.timestamp)) as period_number
    FROM users u
    JOIN user_cohorts c ON u.user_id = c.user_id
    JOIN events e ON u.user_id = e.user_id
    WHERE e.event_name IN ('strategy_started', 'pnl_viewed')
    GROUP BY u.user_id, c.cohort_month, c.cohort_day
)
SELECT 
    cohort_month,
    period_number,
    COUNT(DISTINCT user_id) as active_users,
    COUNT(DISTINCT user_id) * 100.0 / 
        FIRST_VALUE(COUNT(DISTINCT user_id)) OVER (PARTITION BY cohort_month ORDER BY period_number) as retention_rate
FROM activity_periods
GROUP BY cohort_month, period_number
ORDER BY cohort_month, period_number;
```

#### **LTV Calculation by Cohort**
```sql
WITH cohort_revenue AS (
    SELECT 
        u.acquisition_channel,
        DATE_TRUNC('month', u.signup_date) as cohort_month,
        SUM(CASE WHEN e.event_name = 'subscription_payment' THEN CAST(e.properties->>'amount' AS DECIMAL) ELSE 0 END) as revenue,
        SUM(CASE WHEN e.event_name = 'trade_executed' THEN CAST(e.properties->>'commission' AS DECIMAL) ELSE 0 END) as commission
    FROM users u
    JOIN events e ON u.user_id = e.user_id
    WHERE e.timestamp <= u.signup_date + INTERVAL '12 months'
    GROUP BY u.acquisition_channel, DATE_TRUNC('month', u.signup_date)
),
cohort_users AS (
    SELECT 
        acquisition_channel,
        DATE_TRUNC('month', signup_date) as cohort_month,
        COUNT(*) as user_count
    FROM users
    GROUP BY acquisition_channel, DATE_TRUNC('month', signup_date)
)
SELECT 
    r.acquisition_channel,
    r.cohort_month,
    r.user_count,
    r.revenue + r.commission as total_value,
    (r.revenue + r.commission) / r.user_count as ltv_per_user
FROM cohort_revenue r
JOIN cohort_users c ON r.acquisition_channel = c.acquisition_channel AND r.cohort_month = c.cohort_month
ORDER BY r.cohort_month, r.acquisition_channel;
```

---

## 🧪 **A/B TESTING FRAMEWORK**

### **Testing Priorities**

#### **Onboarding Optimization**
**Variant A:** Standard onboarding flow  
**Variant B:** Enhanced onboarding with video tutorials  
**Metrics:** Onboarding completion rate, time to first strategy, D1 retention

#### **Activation Nudges**
**Variant A:** No proactive prompts  
**Variant B:** Contextual "promote to canary" suggestions after DRY_RUN success  
**Metrics:** CANARY conversion rate, time to CANARY, user satisfaction

#### **UI Density**
**Variant A:** Information-dense interface  
**Variant B:** Simplified, cleaner interface  
**Metrics:** Task completion time, error rate, user preference

#### **Risk Communication**
**Variant A:** Numeric risk indicators  
**Variant B:** Visual risk gauges with color coding  
**Metrics:** Risk limit review rate, limit breach incidents, user confidence

### **Test Design Principles**

#### **Statistical Requirements**
- **Sample Size:** Minimum 1,000 users per variant
- **Duration:** 2-4 weeks depending on metric frequency
- **Significance Level:** 95% confidence (p < 0.05)
- **Power:** 80% to detect 10% relative improvement

#### **Safety Constraints**
- **No risk limit relaxation** in any variant
- **All variants maintain safety controls**
- **Emergency controls always accessible**
- **Compliance features never compromised**

---

## 📱 **USER ONBOARDING OPTIMIZATION**

### **Onboarding Flow Design**

#### **Step 1: Environment and Safety Orientation (5 minutes)**
**Goal:** Establish safety mindset and environment awareness  
**Content:** Environment badge, risk caps, emergency controls overview  
**Success Metric:** User can identify current environment and emergency controls

#### **Step 2: Strategy Creation (10 minutes)**
**Goal:** Create first strategy with guided configuration  
**Content:** Strategy template selection, parameter explanation, risk impact display  
**Success Metric:** Strategy created with appropriate risk limits

#### **Step 3: Dry Run Testing (15 minutes)**
**Goal:** Experience strategy behavior in safe environment  
**Content:** DRY_RUN activation, monitoring dashboard, performance interpretation  
**Success Metric:** User runs strategy ≥2 hours in DRY_RUN

#### **Step 4: Risk Confirmation (5 minutes)**
**Goal:** Explicit risk acknowledgment and limit review  
**Content:** Limit review, risk impact confirmation, safety checklist  
**Success Metric:** User explicitly confirms risk understanding

#### **Step 5: Canary Activation (5 minutes)**
**Goal:** Graduate to real-money trading with confidence  
**Content:** CANARY mode explanation, final confirmation, monitoring setup  
**Success Metric:** Strategy successfully activated in CANARY mode

### **Onboarding Success Metrics**

#### **Completion Metrics**
- **Overall completion rate:** >85%
- **Step-specific completion:** >90% for each step
- **Time to completion:** <45 minutes average
- **Drop-off points:** <5% at each step transition

#### **Understanding Metrics**
- **Environment identification:** 100% correct
- **Safety control location:** 100% can identify kill switches
- **Risk limit understanding:** >90% can explain limits
- **Strategy behavior:** >80% can interpret basic metrics

---

## 📊 **DASHBOARD AND REPORTING REQUIREMENTS**

### **Real-Time Dashboards**

#### **Growth Dashboard**
- **New user signups** by channel and cohort
- **Activation funnel** with conversion rates
- **Daily active users** by persona segment
- **Feature adoption** rates and trends

#### **Retention Dashboard**
- **Cohort retention grid** with heat map
- **User engagement trends** by segment
- **Churn prediction indicators**
- **Behavioral clustering analysis**

#### **LTV Dashboard**
- **Revenue by cohort** and channel
- **LTV calculations** by segment
- **LTV/CAC ratios** over time
- **Value component breakdown**

### **Executive Reporting**

#### **Weekly Growth Report**
- New user acquisition and activation
- Key funnel conversion rates
- A/B test results and insights
- Week-over-week growth trends

#### **Monthly Retention Report**
- Cohort retention analysis
- User engagement patterns
- Churn prediction and prevention
- LTV updates by segment

#### **Quarterly Business Review**
- Overall growth metrics
- LTV and CAC analysis
- Market expansion opportunities
- Product roadmap impact

---

## 🔧 **TECHNICAL IMPLEMENTATION**

### **Analytics Stack**

#### **Event Collection**
- **Client-side:** JavaScript SDK for web events
- **Server-side:** Python/Node.js SDK for backend events
- **Batch processing:** Kafka for event streaming
- **Storage:** PostgreSQL for event data warehouse

#### **Data Processing**
- **Real-time:** Apache Flink for live analytics
- **Batch:** Apache Spark for historical analysis
- **OLAP:** ClickHouse for fast querying
- **Visualization:** Grafana for dashboards

#### **Privacy and Compliance**
- **Data anonymization:** User ID hashing
- **Consent management:** GDPR/CCPA compliance
- **Data retention:** Configurable retention policies
- **Security:** Encryption at rest and in transit

### **Integration Points**

#### **Product Analytics**
- **Funnel tracking:** User journey analysis
- **Feature usage:** Adoption and engagement metrics
- **Performance monitoring:** System health correlation
- **Error tracking:** Bug impact on user behavior

#### **Business Intelligence**
- **Revenue tracking:** Subscription and usage fees
- **Cost analysis:** Infrastructure and support costs
- **Profitability analysis:** Margin by user segment
- **Forecasting:** Growth and revenue projections

---

## 🎯 **SUCCESS METRICS AND KPIs**

### **North Star Metrics**

#### **Primary North Star: Activated Professional Traders**
**Definition:** Users who run strategies in CANARY mode within 7 days  
**Target:** 100 activated traders by end of Q1 2026  
**Current:** [Baseline to be established]

#### **Secondary North Star: Monthly Active Trading Volume**
**Definition:** Total notional volume traded through MERID monthly  
**Target:** $10M monthly volume by end of Q2 2026  
**Current:** [Baseline to be established]

### **Leading Indicators**

#### **Activation Metrics**
- **Sign-up to strategy creation:** <24 hours
- **DRY_RUN to CANARY conversion:** >60%
- **First trade latency:** <4 hours after CANARY activation
- **Risk limit review rate:** >90% before CANARY

#### **Engagement Metrics**
- **Daily active users:** >70% of activated users
- **Average session duration:** >15 minutes
- **Feature adoption:** >50% use advanced analytics
- **Support ticket rate:** <5% of active users

### **Lagging Indicators**

#### **Retention Metrics**
- **Day 7 retention:** >70%
- **Day 30 retention:** >65%
- **Day 90 retention:** >60%
- **Churn rate:** <5% monthly

#### **Business Metrics**
- **LTV/CAC ratio:** >3:1
- **Monthly recurring revenue:** $50K by Q2 2026
- **Customer satisfaction:** >4.5/5 rating
- **Net promoter score:** >60

---

## 📅 **IMPLEMENTATION ROADMAP**

### **Phase 1: Foundation (Weeks 1-4)**
- [ ] Event tracking infrastructure setup
- [ ] Core analytics dashboard implementation
- [ ] User segmentation and persona tracking
- [ ] Basic funnel analysis capability

### **Phase 2: Activation Optimization (Weeks 5-8)**
- [ ] Onboarding flow analytics
- [ ] Activation funnel optimization
- [ ] A/B testing framework deployment
- [ ] Real-time user behavior tracking

### **Phase 3: Retention Analysis (Weeks 9-12)**
- [ ] Cohort analysis implementation
- [ ] Retention prediction models
- [ ] LTV calculation framework
- [ ] Churn prevention systems

### **Phase 4: Advanced Analytics (Weeks 13-16)**
- [ ] Behavioral clustering analysis
- [ ] Advanced segmentation
- [ ] Predictive analytics models
- [ ] Executive reporting automation

---

## 🚨 **RISKS AND MITIGATION**

### **Privacy and Compliance Risks**
**Risk:** Data privacy violations or non-compliance  
**Mitigation:** Privacy-by-design architecture, regular compliance audits, data minimization

### **Technical Risks**
**Risk:** Analytics infrastructure failures or data quality issues  
**Mitigation:** Redundant systems, data validation checks, monitoring and alerting

### **Business Risks**
**Risk:** Low user adoption or poor retention  
**Mitigation:** Continuous A/B testing, user feedback loops, rapid iteration capability

### **Security Risks**
**Risk:** Analytics data breaches or unauthorized access  
**Mitigation:** Encryption, access controls, regular security audits, penetration testing

---

## 📝 **DOCUMENTATION AND GOVERNANCE**

### **Analytics Documentation**
- **Event taxonomy:** Complete event catalog with definitions
- **Data dictionary:** All metrics and KPI definitions
- **User guides:** How to use analytics dashboards
- **API documentation:** Analytics data access methods

### **Governance Framework**
- **Data ownership:** Clear ownership of analytics data
- **Access controls:** Role-based access to analytics systems
- **Change management:** Process for analytics changes
- **Quality assurance:** Data quality validation procedures

### **Compliance and Ethics**
- **Privacy policy:** Clear data usage and retention policies
- **User consent:** Transparent consent mechanisms
- **Ethical guidelines:** Responsible analytics practices
- **Audit trails:** Complete audit logging for all analytics activities

---

**Last Updated:** 2026-01-26  
**Next Review:** Monthly or after major feature releases  
**Owner:** MERID Growth and Analytics Team  
**Compliance:** GDPR/CCPA aligned with US financial regulations
