# MERID Control Surface Design

**Design Date**: March 22, 2026  
**Phase**: Season 2 Readiness - Control Surface Specification  
**Status**: Ready for Implementation  
**Version**: 1.0

---

## Executive Summary

**Objective**: Design a single control surface for operators with focused views that align with MERID's actual operational domains

**Approach**: One Command Center plus 4-5 role-focused panels designed for situational awareness and safe action in seconds

**Key Principles**: One-click from alert → relevant panel → concrete action, consistent visual language, human-readable explanations, dark + dense layout with strong hierarchy

---

## Control Surface Architecture

### Overall Structure

```
┌─────────────────────────────────────────────────────────┐
│                MERID Control Surface                     │
├─────────────────────────────────────────────────────────┤
│  1. Command Center (Primary Screen)                     │
│  2. Strategy Panel                                       │
│  3. Execution Panel                                      │
│  4. Analytics Panel                                      │
│  5. Risk Panel                                           │
│  6. Governance & Audit Panel                             │
└─────────────────────────────────────────────────────────┘
```

**Navigation Model**:
- **Command Center**: Primary screen for normal ops and incidents
- **Domain Panels**: Role-focused views for specific domains
- **Cross-Panel Navigation**: One-click navigation between panels
- **Alert Integration**: Direct links from alerts to relevant panels

---

## 1. Command Center (Primary Screen)

### Purpose

**Primary screen for normal operations and incident response**
- Situational awareness at a glance
- Safe action in seconds
- Global status and controls always visible

### Layout Structure

```
┌─────────────────────────────────────────────────────────┐
│                Global Status Strip                      │
├─────────────────────────────────────────────────────────┤
│                Domain Health Tiles                      │
├─────────────────────────────────────────────────────────┤
│                Kill Switch & Mode Controls               │
├─────────────────────────────────────────────────────────┤
│                Alert Stream + Playbook Links             │
└─────────────────────────────────────────────────────────┘
```

### Global Status Strip (Top)

**Overall Lane State**:
- **Normal**: All systems operating normally
- **Degraded**: Some systems experiencing issues
- **Halted**: Critical systems stopped

**High-Level SLO Dials**:
- **E2E Success**: End-to-end success rate (target ≥99.9%)
- **Decision Latency**: Strategy decision latency (target ≤100ms)
- **Execution Latency**: Order execution latency (target ≤500ms)
- **Error Rate**: Overall system error rate (target ≤0.1%)
- **Risk-Limit Compliance**: Risk limit compliance (target 100%)

**Today's P&L and Drawdown**:
- **P&L**: Current day profit/loss
- **Drawdown**: Current drawdown vs guardrails
- **Guardrail Status**: Distance from maximum drawdown limit

### Domain Health Tiles

**Four Domain Tiles**: Strategy / Execution / Analytics / Risk

**Each Tile Shows**:
- **Current Mode**: Normal / Degraded / Off
- **SLO State**: Green (healthy) / Amber (warning) / Red (critical)
- **Error Budget Burn**: Current error budget consumption
- **Active Incidents**: Number and severity of active incidents

**Tile Interaction**:
- **Click**: Drills into that domain's panel
- **Hover**: Shows additional details and metrics
- **Color Coding**: Visual indication of domain health

### Kill Switch & Mode Controls (Always Visible)

**Big, Unambiguous Buttons**:
- **Halt All Trading**: Immediate stop of all trading activity
- **De-Risk / Flatten Only**: Reduce positions and risk exposure
- **Return to Normal**: Resume normal operations
- **Switch Strategy to Baseline**: Switch to baseline strategy mode
- **Disable Analytics Signals**: Disable analytics signal consumption

**Action Confirmation**:
- **What Will Happen**: Clear description of action impact
- **Scope**: Affected systems and domains
- **Confirmation**: Require reason for audit trail
- **Rollback**: Clear rollback procedure

### Alert Stream + Playbook Links

**Chronological Alert List**:
- **Severity**: Critical / High / Medium / Low
- **Affected Domain**: Strategy / Execution / Analytics / Risk
- **Alert Type**: System / Performance / Risk / Business
- **Timestamp**: Alert generation time
- **Status**: Active / Acknowledged / Resolved

**Playbook Integration**:
- **One-Click Link**: Direct link to relevant runbook
- **Context**: Alert context and recommended actions
- **Escalation**: Escalation procedures and contacts
- **Documentation**: Related documentation and references

---

## 2. Strategy Panel

### Purpose

**For understanding and controlling strategy behavior**
- Strategy performance and status
- Decision feed and contracts
- Strategy controls and configuration

### Key Components

#### Strategy Roster

**Strategy List**:
- **Strategy Name**: Unique identifier and display name
- **Status**: Active / Inactive / Disabled
- **Capital Allocation**: Current capital allocation
- **ROI**: Return on investment metrics
- **Hours Saved**: Automation impact metrics
- **SLO Status**: Decision success and latency SLO status

**Filters**:
- **Venue**: Filter by trading venue
- **Asset Class**: Filter by asset class
- **Risk Level**: Filter by risk level
- **Performance**: Filter by performance metrics

#### Decision Feed & Contracts

**Decision Stream**:
- **Strategy**: Strategy making the decision
- **Symbol**: Trading symbol
- **Side**: Buy / Sell / Hold
- **Size**: Position size
- **Venue**: Execution venue
- **Risk Mode**: Current risk mode
- **Analytics Contract**: Analytics contract snapshot

**Decision Inspection**:
- **Inputs**: What inputs the decision saw
- **Risk Contract**: Risk contract used
- **Analytics Contract**: Analytics contract used
- **Execution Plan**: Execution plan and parameters

#### Strategy Controls

**Per-Strategy Toggles**:
- **Enabled/Disabled**: Strategy enable/disable
- **Baseline Mode**: Switch between baseline and full mode
- **Risk Mode**: Risk mode configuration
- **Analytics Mode**: Analytics consumption mode

**Per-Strategy Caps**:
- **Capital Caps**: Temporary tighter capital caps
- **Position Caps**: Temporary position size caps
- **Risk Caps**: Temporary risk exposure caps
- **Expiry**: Clear expiry for temporary caps

---

## 3. Execution Panel

### Purpose

**For venue health and order behavior**
- Venue performance and availability
- Order flow and execution metrics
- Venue routing controls

### Key Components

#### Venue Health Matrix

**Venue Rows**:
- **Venue Name**: Trading venue identifier
- **Availability**: Current availability status
- **Latency**: p50/p95/p99 latency metrics
- **Error Rate**: Venue error rate
- **Throttling**: Current throttling status
- **Recent Incidents**: Recent incident history

**Routing Indicators**:
- **Route More**: Increase routing to venue
- **Route Less**: Decrease routing to venue
- **Disabled**: Venue disabled for routing

#### Order Flow View

**Current Orders**:
- **Order ID**: Unique order identifier
- **Status**: Pending / Filled / Cancelled / Rejected
- **Latency**: Order execution latency
- **Slippage**: Execution slippage
- **Errors**: Execution errors
- **Retries**: Retry attempts

**Aggregate Metrics**:
- **Orders/sec**: Orders per second
- **Success Rate**: Order success rate
- **Per-Venue Performance**: Performance by venue
- **Error Analysis**: Error analysis by type

#### Execution Controls

**Per-Venue Routing**:
- **Routing Weights**: Venue routing weights
- **Risk Constraints**: Risk constraint compliance
- **Performance Targets**: Performance targets

**Safe Toggles**:
- **Temporarily Stop Routing**: Stop routing to venue
- **Reason**: Clear reason for routing change
- **Auto-Review**: Automatic review time
- **Rollback**: Rollback procedure

---

## 4. Analytics Panel

### Purpose

**For signals, freshness, and model health**
- Signal catalog and performance
- Signal pipeline health
- Analytics controls and configuration

### Key Components

#### Signal Catalog

**Signal List**:
- **Signal Type**: Signal type and category
- **Report Name**: Report identifier
- **Freshness**: Signal freshness metrics
- **Latency**: Signal latency metrics
- **Quality Score**: Signal quality assessment
- **Correctness SLO**: Correctness SLO compliance

**Signal Tags**:
- **Critical**: Critical for operations
- **Advisory**: Advisory information only
- **Experimental**: Experimental signals

#### Signal Pipeline View

**Pipeline Components**:
- **Data Sources**: Data source health and status
- **Features**: Feature generation and quality
- **Models**: Model performance and health
- **Signals**: Signal generation and quality

**Pipeline Indicators**:
- **Delays**: Pipeline delay indicators
- **Failures**: Pipeline failure indicators
- **Performance**: Pipeline performance metrics
- **Quality**: Pipeline quality metrics

#### Analytics Controls

**Signal Toggles**:
- **Consumed by Strategy**: Signal consumption mode
- **Advisory Only**: Advisory-only mode
- **Experimental**: Experimental mode

**Pipeline Controls**:
- **Manual Re-runs**: Manual pipeline re-runs
- **Backfills**: Data backfill operations
- **Configuration**: Pipeline configuration

---

## 5. Risk Panel

### Purpose

**For capital, limits, and enforcement behavior**
- Risk posture and capital allocation
- Enforcement decisions and actions
- Risk controls and configuration

### Key Components

#### Risk Posture Dashboard

**Capital Allocation**:
- **By Strategy**: Capital allocation by strategy
- **By Venue**: Capital allocation by venue
- **By Asset**: Capital allocation by asset class
- **Total Capital**: Total capital allocation

**Risk Limits**:
- **Current vs Max**: Current vs maximum limits
- **Capital**: Capital limits and usage
- **Exposure**: Exposure limits and usage
- **Concentration**: Concentration limits and usage
- **VaR Metrics**: Value-at-Risk metrics

**Guardrail History**:
- **Trigger History**: Guardrail trigger history
- **Status**: Current guardrail status
- **Actions**: Actions taken by guardrails

#### Enforcement View

**Enforcement Decisions**:
- **Blocks**: Risk enforcement blocks
- **Resizes**: Position resizing actions
- **De-Risking**: De-risking actions
- **Context**: Decision context and rationale
- **Correctness**: Correctness and false-positive labels

**Alignment Metrics**:
- **Shadow Behavior**: Shadow system alignment
- **Reference Behavior**: Reference system alignment
- **Performance**: Enforcement performance metrics

#### Risk Controls

**Limit Adjustments**:
- **Pre-Approved Ranges**: Pre-approved adjustment ranges
- **Audit Trail**: Complete audit trail
- **Approval**: Approval workflow

**Risk Modes**:
- **Normal**: Normal risk mode
- **Tightened**: Tightened risk mode
- **Emergency**: Emergency risk mode

---

## 6. Governance & Audit Panel

### Purpose

**For SRE and audit work**
- SLO and error budget monitoring
- Change and incident history
- Artifact and retention management

### Key Components

#### SLO & Error Budget View

**SLO Compliance**:
- **Per-Domain SLOs**: SLOs by domain
- **Current Compliance**: Current compliance status
- **Error Budgets**: Error budget status
- **Burn Rate**: Error budget burn rate

**Drill-In Views**:
- **Periods**: Time period analysis
- **Incidents**: Incident impact on budgets
- **Trends**: Budget consumption trends

#### Change & Incident History

**Timeline View**:
- **Deployments**: Deployment history
- **Config Changes**: Configuration changes
- **Incidents**: Incident history
- **Kill-Switch Events**: Kill-switch event history

**Filters**:
- **Severity**: Filter by severity
- **Domain**: Filter by domain
- **Date**: Filter by date range
- **Type**: Filter by change type

#### Artifact & Retention View

**Key Artifacts**:
- **PRRs**: Production readiness reviews
- **Season Reports**: Season reports and summaries
- **Runbooks**: Operational runbooks
- **Policies**: Policies and procedures

**Retention Classes**:
- **Logs**: Log retention classes
- **Audit Trails**: Audit trail retention
- **Metrics**: Metrics retention
- **Documents**: Document retention

---

## 7. Cross-Cutting UX Principles

### Navigation and Interaction

**One-Click Navigation**:
- **Alert → Panel**: One-click from alert to relevant panel
- **Panel → Action**: One-click from panel to concrete action
- **Context Preservation**: Maintain context across navigation
- **Breadcrumbs**: Clear navigation breadcrumbs

**Consistent Visual Language**:
- **SLO States**: Consistent color coding for SLO states
- **Modes**: Consistent iconography for modes
- **Risk Levels**: Consistent visual indicators for risk levels
- **Alert Severity**: Consistent severity indicators

### Human-Readable Explanations

**Critical Controls**:
- **Clear Descriptions**: Human-readable control descriptions
- **Impact Statements**: Clear impact statements
- **Rollback Procedures**: Clear rollback procedures
- **Audit Requirements**: Clear audit requirements

**Contextual Help**:
- **Tooltips**: Contextual tooltips and help
- **Documentation**: Links to relevant documentation
- **Examples**: Usage examples and scenarios
- **Best Practices**: Best practice guidance

### Visual Design

**Dark + Dense Layout**:
- **Dark Theme**: Dark theme for operator comfort
- **Dense Information**: High information density
- **Strong Hierarchy**: Clear visual hierarchy
- **Critical Information**: Critical information prominence

**Responsive Design**:
- **Multi-Screen**: Support for multiple screens
- **Mobile**: Mobile support for critical functions
- **Accessibility**: Accessibility compliance
- **Performance**: Fast loading and response

---

## Implementation Priorities

### Phase 1: Core Functionality

**Command Center**:
- Global status strip
- Domain health tiles
- Kill switch controls
- Alert stream

**Risk Panel**:
- Risk posture dashboard
- Enforcement view
- Risk controls

### Phase 2: Domain Panels

**Strategy Panel**:
- Strategy roster
- Decision feed
- Strategy controls

**Execution Panel**:
- Venue health matrix
- Order flow view
- Execution controls

### Phase 3: Analytics and Governance

**Analytics Panel**:
- Signal catalog
- Pipeline view
- Analytics controls

**Governance Panel**:
- SLO and error budget view
- Change history
- Artifact management

---

## Technical Requirements

### Data Requirements

**Real-Time Data**:
- **Latency**: Sub-second data updates
- **Accuracy**: High data accuracy
- **Completeness**: Complete data coverage
- **Reliability**: Reliable data delivery

**Historical Data**:
- **Retention**: Appropriate data retention
- **Performance**: Fast historical queries
- **Aggregation**: Efficient data aggregation
- **Visualization**: Effective data visualization

### Integration Requirements

**System Integration**:
- **APIs**: Comprehensive API integration
- **Authentication**: Secure authentication
- **Authorization**: Role-based access control
- **Audit Trail**: Complete audit trail

**Third-Party Integration**:
- **Venues**: Venue data integration
- **Analytics**: Analytics system integration
- **Monitoring**: Monitoring system integration
- **Alerting**: Alerting system integration

### Performance Requirements

**Response Time**:
- **Page Load**: <2 seconds page load
- **Data Update**: <1 second data update
- **Action Response**: <500ms action response
- **Navigation**: <200ms navigation

**Scalability**:
- **Concurrent Users**: Support for multiple users
- **Data Volume**: Handle growing data volume
- **Feature Growth**: Support for feature growth
- **Performance**: Maintain performance under load

---

## Security Requirements

### Access Control

**Authentication**:
- **Multi-Factor**: Multi-factor authentication
- **SSO**: Single sign-on integration
- **Session Management**: Secure session management
- **Password Policy**: Strong password policy

**Authorization**:
- **Role-Based**: Role-based access control
- **Least Privilege**: Least privilege principle
- **Dynamic Access**: Dynamic access control
- **Audit Logging**: Complete access logging

### Data Protection

**Data Encryption**:
- **In Transit**: Data encryption in transit
- **At Rest**: Data encryption at rest
- **Key Management**: Secure key management
- **Compliance**: Regulatory compliance

**Privacy**:
- **Data Minimization**: Data minimization principle
- **Anonymization**: Data anonymization
- **Retention**: Data retention policies
- **Rights**: Data subject rights

---

## Conclusion

### Design Summary

**Comprehensive Control Surface**:
- Single command center for operators
- Focused domain panels for specialized tasks
- Consistent visual language and navigation
- Human-readable explanations and controls

**Operational Excellence**:
- One-click from alert to action
- Real-time situational awareness
- Safe and controlled operations
- Comprehensive audit trail

**Technical Excellence**:
- High-performance data delivery
- Scalable architecture
- Secure access control
- Comprehensive integration

### Next Steps

**Implementation Planning**:
- Detailed component specification
- Technology stack selection
- Development roadmap
- Testing and validation

**Stakeholder Review**:
- Design review with stakeholders
- Feedback incorporation
- Approval process
- Implementation authorization

**Development Execution**:
- Phase-based implementation
- Regular progress reviews
- Quality assurance
- Deployment and training

---

**Design Status**: ✅ COMPLETE  
**Technical Requirements**: ✅ DEFINED  
**Security Requirements**: ✅ DEFINED  
**Implementation Plan**: ✅ READY  
**Stakeholder Review**: ✅ READY

**MERID Control Surface Design is complete and ready for implementation. The design provides a comprehensive, user-friendly, and secure control surface that aligns with MERID's operational domains and supports safe, efficient operations.**
