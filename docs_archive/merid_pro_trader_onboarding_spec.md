# 🎯 MERID Pro Trader Onboarding Specification

**Purpose:** Design onboarding and prompts around "deep behaviors" that define activated pro traders  
**Version:** 1.0  
**Date:** 2026-01-26  
**Target:** 15-25% trial activation rate for professional traders  

---

## 🎯 **EXECUTIVE SUMMARY**

### **Pro Trader Activation Definition**
An "activated pro trader" completes all four deep behaviors within the first week:
1. **Intent and Account Setup** - Trading intent defined + required accounts connected
2. **First Strategy Run** - Strategy configured and run in DRY_RUN mode
3. **Risk Guardrails Set** - Custom risk limits configured and confirmed
4. **First Analytics Interaction** - P&L/exposure viewed + trade/alert detail inspected

### **Success Targets**
- **Initial Activation Rate:** 15-25% of trials reaching deep activation within 7 days
- **Day 14 Retention:** >70% for activated users vs <30% for non-activated
- **Time to Activation:** <72 hours for successful onboarding
- **Conversion to Paid:** >60% for activated users by Day 30

---

## 📋 **ONBOARDING STEPS THAT CORRELATE WITH PRO ACTIVATION**

### **Step 1: Intent and Account Setup (Target: <10 minutes)**

#### **Trading Intent Collection**
**Goal:** Understand user's trading profile and personalize experience  
**Fields Required:**
- **Primary Markets:** BTC/USD, ETH/USD, or both
- **Trading Style:** Market making, arbitrage, trend following, or custom
- **Risk Band:** Conservative ($1K daily), Moderate ($5K daily), or Custom
- **Experience Level:** Professional trader, quant operator, or learning

**UI Implementation:**
- Single-screen intent collection with smart defaults
- Visual risk band selector with clear impact display
- Market selection with available venues shown
- Style-based strategy template recommendations

#### **Account Integration**
**Goal:** Connect required trading venues with minimal friction  
**Process:**
- Auto-detect available venues based on market selection
- Guided API key connection with security emphasis
- Encrypted key storage with revocation instructions
- Connection verification with test call

**Success Metrics:**
- Intent completion rate: >95%
- Account connection success rate: >90%
- Time to completion: <10 minutes
- User satisfaction: >4.5/5

### **Step 2: First Strategy Configured and Run (Target: <15 minutes)**

#### **Strategy Configuration**
**Goal:** Get user to first meaningful interaction quickly  
**Process:**
- Recommend strategy template based on intent
- Pre-fill parameters with conservative defaults
- Show expected behavior and risk impact
- One-click configuration with option to customize

**Strategy Templates:**
- **Conservative Market Making:** BTC/USD + ETH/USD, 0.1% spread, $100 max size
- **Simple Arbitrage:** Cross-venue opportunities, $50 max exposure
- **Trend Following:** Basic momentum, $200 max notional
- **Custom Strategy:** Blank template with guided setup

#### **DRY_RUN Execution**
**Goal:** Demonstrate system behavior without risk  
**Process:**
- Launch strategy in DRY_RUN mode
- Show real-time simulated P&L
- Display order flow and execution simulation
- Highlight safety controls and monitoring

**Success Metrics:**
- Strategy creation rate: >85%
- DRY_RUN initiation rate: >80%
- Average DRY_RUN duration: >2 hours
- User understanding: >90% can explain strategy behavior

### **Step 3: Risk Guardrails Set (Target: <5 minutes)**

#### **Risk Limit Configuration**
**Goal:** Establish trust through user control and transparency  
**Process:**
- Present recommended limits based on risk band
- Allow customization with impact visualization
- Show real-time limit utilization during DRY_RUN
- Require explicit confirmation with risk acknowledgment

**Risk Controls:**
- **Daily Loss Limit:** $50 (conservative) to $1,000 (moderate)
- **Max Notional Exposure:** $1,000 to $10,000
- **Per-Trade Size Limit:** $50 to $500
- **Symbol Whitelist:** BTC/USD, ETH/USD initially
- **Venue Limits:** Per-venue exposure caps

**Success Metrics:**
- Limit customization rate: >70%
- Risk acknowledgment rate: >95%
- Limit breach rate during DRY_RUN: 0%
- User confidence: >85% feel in control

### **Step 4: First Monitoring/Analytics Interaction (Target: <10 minutes)**

#### **Analytics Introduction**
**Goal:** Demonstrate value of data-driven insights  
**Process:**
- Guide user to P&L dashboard during DRY_RUN
- Show exposure and risk utilization visualization
- Highlight trade detail and execution quality
- Introduce alert and incident monitoring

**Key Analytics Features:**
- **Real-time P&L Tracking:** Strategy performance visualization
- **Exposure Analysis:** Current positions and risk utilization
- **Trade Detail View:** Individual trade execution quality
- **Alert Monitoring:** Risk and system health notifications

**Success Metrics:**
- Dashboard view rate: >90%
- Trade detail inspection rate: >60%
- Alert panel interaction rate: >40%
- Analytics satisfaction: >4.0/5

---

## 📊 **BENCHMARK ACTIVATION RATES**

### **Industry Benchmarks**

#### **B2B SaaS Trial Activation**
- **Complex Technical Products:** 15-35% activation rate
- **Integration-Heavy Tools:** 10-25% initial activation
- **Multi-Session Engagement:** Sharp conversion increase after 3+ sessions

#### **Fintech Onboarding Impact**
- **Friction Reduction:** Double-digit improvement in D7 retention
- **Personalized Flows:** 20-30% higher activation rates
- **Goal-Based Onboarding:** 25% increase in user engagement

### **MERID-Specific Targets**

#### **Realistic Initial Goals**
- **Week 1 Activation:** 15-25% reach deep activation definition
- **Day 14 Retention:** >70% activated vs <30% non-activated
- **Day 30 Conversion:** >60% activated users convert to paid
- **Time to Activation:** <72 hours average

#### **Optimization Goals**
- **Month 3:** 25-35% activation rate through flow optimization
- **Month 6:** 35-45% activation rate with personalization
- **Month 12:** >50% activation rate with advanced features

---

## 💬 **BEST IN-APP PROMPT COPY**

### **Prompt Design Principles**
- **Safety-Forward Language:** Emphasize protection and control
- **Goal-Oriented CTAs:** Clear, action-oriented buttons
- **Contextual Timing:** Based on user behavior, not calendar
- **Personalization:** Reference user's specific strategies and goals

### **Core Prompt Library**

#### **"Complete First Safe Run"**
**Trigger:** Account connected, no strategy started  
**Copy:** "Run your first strategy in DRY_RUN to see how MERID behaves—no real orders, just simulated P&L."  
**CTA:** "Start a safe test run"  
**Placement:** Dashboard banner after account setup

#### **"Promote Successful Tests to Canary"**
**Trigger:** Strategy completed 2+ hours DRY_RUN without breaches  
**Copy:** "This strategy has passed {hours} hours in DRY_RUN without breaching your limits. Try CANARY with a capped max loss of ${amount}."  
**CTA:** "Promote to canary"  
**Placement:** Strategy card with success indicator

#### **"Set Your Guardrails"**
**Trigger:** Strategy created but limits not customized  
**Copy:** "Before going live, set your daily loss and notional caps so MERID trades within your risk budget."  
**CTA:** "Configure risk limits"  
**Placement:** Risk panel with warning indicator

#### **"Connect Required Venues"**
**Trigger:** Markets selected but venues not connected  
**Copy:** "To trade {markets}, connect your exchange/broker account. Your keys are encrypted and can be revoked anytime."  
**CTA:** "Connect {venue_name}"  
**Placement:** Setup wizard with venue cards

#### **"Review Your Performance"**
**Trigger:** DRY_RUN running but analytics not viewed  
**Copy:** "Your strategy is running! See how it's performing with real-time P&L and exposure tracking."  
**CTA:** "View analytics"  
**Placement:** Dashboard notification during DRY_RUN

#### **"Upgrade to Continue"**
**Trigger:** Trial ending with successful activation  
**Copy:** "Your strategies and data remain intact when you upgrade. Continue running {strategy_name} without interruption."  
**CTA:** "Upgrade now"  
**Placement:** Trial expiration banner

### **Advanced Prompt Strategies**

#### **Personalized Context**
- Reference specific strategy names and performance
- Show actual P&L and risk utilization numbers
- Use user's selected markets and risk band
- Highlight user's specific achievements

#### **Urgency and Scarcity**
- Time-limited canary opportunities
- Limited risk band availability
- Exclusive strategy template access
- Priority support for activated users

#### **Social Proof**
- "Join {number} professional traders using MERID"
- "Similar strategies are averaging {return}% returns"
- "Top performers upgrade within {days} days"
- "Professional traders like you choose MERID"

---

## ⏰ **OPTIMAL PROMPT TIMING**

### **Behavior-Based Triggers**

#### **First Session (0-15 minutes)**
**Goal:** Reach first DRY_RUN quickly  
**Triggers:**
- Account connected → "Start safe test run"
- Intent selected → "Configure first strategy"
- Strategy created → "Launch DRY_RUN"

**Success Metrics:**
- First DRY_RUN start rate: >80%
- Session completion rate: >70%
- User satisfaction: >4.5/5

#### **First 24-72 Hours**
**Goal:** Complete activation sequence  
**Triggers:**
- Day 1: No DRY_RUN → "Your strategy is ready to test"
- Day 2: DRY_RUN running, no analytics → "Check your performance"
- Day 3: Limits not set → "Configure your guardrails"

**Success Metrics:**
- Day 1 activation: >40%
- Day 3 activation: >60%
- Analytics interaction: >70%

#### **Mid-Trial (Days 5-10)**
**Goal:** Convert qualified users to canary  
**Triggers:**
- Successful DRY_RUN completion → "Promote to canary"
- Risk limits tested → "Increase your allocation"
- Multiple strategies running → "Upgrade for advanced features"

**Success Metrics:**
- Canary conversion: >50% of qualified users
- Risk limit increases: >30%
- Advanced feature adoption: >40%

#### **Trial End (Days 12-14)**
**Goal:** Convert activated users to paid  
**Triggers:**
- Trial expiration → "Continue without interruption"
- High engagement → "Unlock professional features"
- Multiple strategies → "Upgrade for portfolio management"

**Success Metrics:**
- Paid conversion: >60% of activated users
- Feature adoption: >50% of paid users
- Retention: >80% of paid users

---

## 📊 **EVENT NAMING CONVENTION**

### **Event Design Principles**
- **Consistent Format:** `noun_verb` with snake_case
- **Descriptive Names:** Clear purpose without ambiguity
- **Standardized Properties:** Common fields across events
- **Version Control:** Maintain backward compatibility

### **Core Event Dictionary**

#### **Strategy Lifecycle Events**
```json
{
  "strategy_created": {
    "description": "User creates new strategy configuration",
    "properties": {
      "strategy_id": "string",
      "template_name": "string",
      "asset_class": "string",
      "complexity": "simple|advanced|custom"
    }
  },
  "strategy_started": {
    "description": "User activates strategy in specific mode",
    "properties": {
      "strategy_id": "string",
      "mode": "dry_run|canary|full",
      "trigger": "manual|automated|scheduled"
    }
  },
  "strategy_stopped": {
    "description": "User deactivates strategy",
    "properties": {
      "strategy_id": "string",
      "mode": "string",
      "reason": "user_action|limit_hit|error|timeout"
    }
  },
  "strategy_mode_changed": {
    "description": "User changes strategy operating mode",
    "properties": {
      "strategy_id": "string",
      "from_mode": "string",
      "to_mode": "string",
      "approval_required": "boolean"
    }
  }
}
```

#### **Trading and Analytics Events**
```json
{
  "trade_executed": {
    "description": "Strategy executes trade",
    "properties": {
      "strategy_id": "string",
      "symbol": "string",
      "side": "buy|sell",
      "size": "number",
      "price": "number",
      "pnl": "number",
      "slippage_bps": "number",
      "venue": "string"
    }
  },
  "trade_detail_viewed": {
    "description": "User inspects individual trade details",
    "properties": {
      "trade_id": "string",
      "symbol": "string",
      "source_screen": "string",
      "view_duration": "number"
    }
  },
  "pnl_viewed": {
    "description": "User views profit and loss analytics",
    "properties": {
      "scope": "strategy|portfolio|symbol",
      "time_range": "1h|24h|7d|30d",
      "view_type": "chart|table|summary"
    }
  }
}
```

#### **Risk and Limits Events**
```json
{
  "limit_viewed": {
    "description": "User reviews risk limits configuration",
    "properties": {
      "limit_type": "daily_loss|notional|per_trade|symbol",
      "scope": "global|strategy|venue",
      "current_utilization": "number"
    }
  },
  "limit_updated": {
    "description": "User modifies risk limits",
    "properties": {
      "limit_type": "string",
      "scope": "string",
      "old_value": "number",
      "new_value": "number",
      "approval_required": "boolean"
    }
  },
  "risk_preset_selected": {
    "description": "User chooses risk configuration preset",
    "properties": {
      "preset_name": "string",
      "risk_band": "conservative|moderate|aggressive",
      "customization_level": "none|partial|full"
    }
  }
}
```

#### **Monitoring and Incidents**
```json
{
  "alert_viewed": {
    "description": "User reviews system alert",
    "properties": {
      "alert_id": "string",
      "severity": "info|warning|error|critical",
      "category": "risk|system|performance|compliance",
      "action_taken": "dismissed|acknowledged|resolved"
    }
  },
  "incident_created": {
    "description": "System generates incident report",
    "properties": {
      "incident_id": "string",
      "type": "risk_breach|system_error|performance|compliance",
      "severity": "low|medium|high|critical",
      "auto_resolved": "boolean"
    }
  },
  "incident_resolved": {
    "description": "Incident is resolved by user or system",
    "properties": {
      "incident_id": "string",
      "resolution": "auto_resolved|user_action|system_recovery",
      "resolution_time": "number"
    }
  }
}
```

#### **Onboarding and Account Events**
```json
{
  "account_connected": {
    "description": "User connects trading venue account",
    "properties": {
      "provider": "string",
      "account_type": "exchange|broker|custody",
      "connection_method": "api_key|oauth|manual",
      "verification_status": "pending|verified|failed"
    }
  },
  "kyc_completed": {
    "description": "User completes identity verification",
    "properties": {
      "kyc_tier": "basic|enhanced|professional",
      "verification_method": "document|biometric|third_party",
      "processing_time": "number"
    }
  },
  "onboarding_step_completed": {
    "description": "User completes onboarding milestone",
    "properties": {
      "step_name": "intent_setup|account_connection|strategy_creation|risk_limits|analytics_intro",
      "step_order": "number",
      "completion_time": "number",
      "skipped": "boolean"
    }
  }
}
```

---

## 🎯 **ACTIVATION FUNNEL METRICS**

### **Funnel Definition**

#### **Top of Funnel (TOFU)**
- **Sign-up Completion:** User creates account
- **Intent Collection:** User defines trading preferences
- **Account Connection:** User connects at least one venue

**Target Conversion Rates:**
- Sign-up → Intent: >80%
- Intent → Account: >70%
- Account → Strategy: >60%

#### **Middle of Funnel (MOFU)**
- **Strategy Creation:** User creates first strategy
- **DRY_RUN Execution:** User runs strategy in safe mode
- **Analytics Interaction:** User views performance data

**Target Conversion Rates:**
- Account → Strategy: >60%
- Strategy → DRY_RUN: >80%
- DRY_RUN → Analytics: >70%

#### **Bottom of Funnel (BOFU)**
- **Risk Configuration:** User sets custom limits
- **Canary Promotion:** User graduates to real trading
- **Paid Conversion:** User subscribes to professional plan

**Target Conversion Rates:**
- Analytics → Risk: >70%
- Risk → Canary: >50%
- Canary → Paid: >60%

### **Activation Scoring System**

#### **Deep Behavior Points**
- **Intent Setup:** 15 points
- **Account Connection:** 20 points
- **Strategy Creation:** 25 points
- **DRY_RUN Execution:** 20 points
- **Risk Configuration:** 15 points
- **Analytics Interaction:** 5 points

#### **Activation Thresholds**
- **Partially Activated:** 50-74 points (basic engagement)
- **Fully Activated:** 75-100 points (deep engagement)
- **Power User:** 90-100 points + advanced features

---

## 📈 **SUCCESS METRICS AND KPIs**

### **Primary Activation Metrics**

#### **Activation Rate**
- **Week 1 Activation:** 15-25% of trials reach 75+ points
- **Week 2 Activation:** 20-30% of trials reach 75+ points
- **Month 1 Activation:** 25-35% of trials reach 75+ points

#### **Time to Activation**
- **Average Time:** <72 hours for full activation
- **Median Time:** <48 hours for full activation
- **Fastest 25%:** <24 hours for full activation

#### **Activation Quality**
- **Deep Engagement Score:** >80 points average for activated users
- **Feature Adoption:** >3 distinct features used by activated users
- **Session Frequency:** >5 sessions in first week for activated users

### **Secondary Impact Metrics**

#### **Retention Correlation**
- **Day 7 Retention:** >70% for activated vs <30% for non-activated
- **Day 14 Retention:** >60% for activated vs <20% for non-activated
- **Day 30 Retention:** >50% for activated vs <15% for non-activated

#### **Conversion Correlation**
- **Paid Conversion:** >60% for activated users
- **Upgrade Speed:** <7 days from activation to payment
- **Plan Selection:** >80% choose professional or enterprise plans

#### **Engagement Correlation**
- **Session Duration:** >15 minutes average for activated users
- **Feature Depth:** >5 features used by activated users
- **Support Tickets:** <10% of activated users contact support

---

## 🧪 **A/B TESTING FRAMEWORK**

### **Testing Priorities**

#### **Onboarding Flow Optimization**
**Variant A:** Current linear flow  
**Variant B:** Personalized flow based on trading intent  
**Metrics:** Activation rate, time to activation, user satisfaction

#### **Prompt Effectiveness**
**Variant A:** Generic prompts  
**Variant B:** Personalized, contextual prompts  
**Metrics:** CTR, conversion rate, task completion time

#### **Risk Configuration**
**Variant A:** Default limits only  
**Variant B:** Guided limit customization  
**Metrics:** Limit customization rate, user confidence, safety perception

#### **Analytics Introduction**
**Variant A:** Passive dashboard access  
**Variant B:** Guided analytics tour  
**Metrics:** Analytics interaction rate, feature adoption, retention

### **Test Design Specifications**

#### **Statistical Requirements**
- **Sample Size:** Minimum 500 users per variant
- **Duration:** 2 weeks per test
- **Significance Level:** 95% confidence (p < 0.05)
- **Power:** 80% to detect 10% relative improvement

#### **Success Criteria**
- **Primary Metric:** Activation rate improvement >5%
- **Secondary Metrics:** Time to activation reduction >10%
- **Guardrail Metrics:** No increase in support tickets or user frustration

---

## 🔧 **TECHNICAL IMPLEMENTATION**

### **Onboarding Infrastructure**

#### **Progress Tracking**
- **Step Completion Events:** Real-time onboarding progress
- **Activation Scoring:** Dynamic point calculation
- **Personalization Engine:** Context-aware prompt delivery
- **A/B Testing Framework:** Variant assignment and measurement

#### **Prompt Delivery System**
- **Behavioral Triggers:** Event-based prompt activation
- **Context Engine:** User state and history analysis
- **Template System:** Dynamic prompt generation
- **Frequency Capping:** Prevent prompt fatigue

#### **Analytics Integration**
- **Event Collection:** Comprehensive behavioral tracking
- **Funnel Analysis:** Real-time conversion monitoring
- **Cohort Analysis:** User segment performance
- **Predictive Modeling**: Churn risk and intervention opportunities

### **Data Schema**

#### **Onboarding Progress Table**
```sql
CREATE TABLE onboarding_progress (
    user_id VARCHAR(255) PRIMARY KEY,
    signup_date TIMESTAMP,
    intent_completed BOOLEAN DEFAULT FALSE,
    accounts_connected INT DEFAULT 0,
    strategies_created INT DEFAULT 0,
    dry_run_completed BOOLEAN DEFAULT FALSE,
    limits_configured BOOLEAN DEFAULT FALSE,
    analytics_viewed BOOLEAN DEFAULT FALSE,
    activation_score INT DEFAULT 0,
    activation_date TIMESTAMP,
    last_activity TIMESTAMP
);
```

#### **Prompt Interactions Table**
```sql
CREATE TABLE prompt_interactions (
    interaction_id VARCHAR(255) PRIMARY KEY,
    user_id VARCHAR(255),
    prompt_id VARCHAR(255),
    prompt_type VARCHAR(50),
    trigger_event VARCHAR(100),
    shown_at TIMESTAMP,
    clicked_at TIMESTAMP,
    dismissed_at TIMESTAMP,
    converted_at TIMESTAMP,
    variant VARCHAR(50),
    created_at TIMESTAMP
);
```

---

## 📅 **IMPLEMENTATION ROADMAP**

### **Phase 1: Foundation (Weeks 1-4)**
- [ ] Implement core onboarding flow
- [ ] Deploy behavioral tracking system
- [ ] Create prompt delivery infrastructure
- [ ] Establish activation scoring system

### **Phase 2: Optimization (Weeks 5-8)**
- [ ] Launch A/B testing framework
- [ ] Implement personalized prompts
- [ ] Optimize onboarding conversion rates
- [ ] Deploy analytics dashboard

### **Phase 3: Advanced Features (Weeks 9-12)**
- [ ] Implement predictive analytics
- [ ] Deploy advanced personalization
- [ ] Launch power user features
- [ ] Optimize long-term retention

---

## 🚨 **RISKS AND MITIGATION**

### **User Experience Risks**
**Risk:** Onboarding friction reduces activation  
**Mitigation:** Continuous A/B testing, user feedback loops, progressive disclosure

### **Technical Risks**
**Risk:** Tracking system failures affect analytics  
**Mitigation:** Redundant tracking, data validation, real-time monitoring

### **Business Risks**
**Risk:** Low activation rates impact revenue  
**Mitigation:** Multiple onboarding paths, personalization, prompt optimization

### **Compliance Risks**
**Risk:** Prompts violate regulatory requirements  
**Mitigation:** Legal review, compliance monitoring, conservative messaging

---

## 📝 **DOCUMENTATION AND GOVERNANCE**

### **Analytics Documentation**
- **Event Dictionary:** Complete event catalog with definitions
- **Activation Playbook:** Step-by-step activation optimization guide
- **Prompt Library:** All prompt templates and usage guidelines
- **A/B Testing Results:** Historical test outcomes and learnings

### **Governance Framework**
- **Activation Standards:** Clear definition and measurement criteria
- **Prompt Approval Process:** Review and approval workflow
- **Data Privacy:** User data protection and consent management
- **Quality Assurance:** Testing and validation procedures

---

**Last Updated:** 2026-01-26  
**Next Review:** Monthly or after major onboarding changes  
**Owner:** MERID Growth and Product Teams  
**Target:** 15-25% professional trader activation rate
