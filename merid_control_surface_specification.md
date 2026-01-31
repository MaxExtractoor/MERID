# MERID Control Surface Specification

**Specification Date**: March 22, 2026  
**Phase**: UI and RBAC Specification  
**Status**: Ready for Implementation  
**Version**: 1.0

---

## Executive Summary

**Objective**: Provide a concise blueprint for UI and RBAC specifications that can be handed to front-end implementation agents or used in Figma

**Approach**: Minimal but distinct roles, critical real-time metrics, decision-speed widgets, SRE-based alert workflows, and prioritized data sources

**Key Principles**: 2-second answers to "are we safe?" and "where's the problem?", actionable alerts, RBAC scalability, phased implementation

---

## 1. Core User Roles and Permissions

### Role-Based Access Control (RBAC) Framework

**Design Philosophy**: Minimal but distinct roles with clear separation of concerns, scalable for future growth

#### Trader / Strategy Owner

**Primary Responsibilities**: Strategy management and performance monitoring

**Permissions**:
- ✅ **View**: All dashboards, P&L, risk metrics
- ✅ **Control**: Enable/disable their strategies
- ✅ **Adjust**: Strategy-level parameters within Risk envelopes
- ✅ **Monitor**: Real-time P&L and risk exposure
- ❌ **Cannot**: Change global risk limits, kill all trading, modify governance/SLOs

**Access Scope**:
- Strategy-specific views and controls
- Personal P&L and risk metrics
- Strategy performance analytics
- Limited to their assigned strategies

#### Risk Officer

**Primary Responsibilities**: Risk management and limit enforcement

**Permissions**:
- ✅ **View**: All risk metrics and enforcement history
- ✅ **Edit**: Risk limits within pre-approved ranges
- ✅ **Control**: Risk modes (normal → tightened → emergency)
- ✅ **Approve**: High-impact changes
- ❌ **Cannot**: Modify strategy logic, deploy code

**Access Scope**:
- Comprehensive risk dashboard
- Risk limit management interface
- Enforcement history and analytics
- Risk policy configuration

#### SRE / Platform Operator

**Primary Responsibilities**: Platform operations and incident response

**Permissions**:
- ✅ **Control**: Kill-switches, service modes (degrade/halt)
- ✅ **Manage**: Deployments and configurations
- ✅ **Operate**: Alert routing, chaos drills
- ❌ **Cannot**: Change strategy parameters, override risk policies without approval

**Access Scope**:
- Command Center controls
- Deployment management interface
- Alert management and routing
- System health and performance

#### Observer / Auditor

**Primary Responsibilities**: Read-only monitoring and audit

**Permissions**:
- ✅ **View**: All dashboards, logs, SLO reports
- ✅ **Access**: Incident records, governance documents
- ❌ **Cannot**: Trigger actions, change configurations

**Access Scope**:
- Read-only access to all panels
- Historical data and reports
- Audit trail and compliance documents
- No control capabilities

### RBAC Implementation Requirements

**Authentication Framework**:
- Multi-factor authentication (MFA)
- Single sign-on (SSO) integration
- Session management with timeout
- Secure credential storage

**Authorization Framework**:
- Role-based access control (RBAC)
- Attribute-based access control (ABAC) for fine-grained permissions
- Dynamic permission evaluation
- Audit trail for all access attempts

**Scalability Considerations**:
- Role hierarchy support
- Permission inheritance
- Dynamic role assignment
- Integration with external identity providers

---

## 2. Critical Real-Time Metrics for Risk & P&L

### Command Center and Risk Panel Metrics

**Update Frequency**: Sub-second updates for critical metrics, 1-5 seconds for secondary metrics

#### P&L and Equity Metrics

**Real-Time P&L**:
- **Realized P&L**: Per strategy, per venue, aggregate
- **Unrealized P&L**: Per position, per strategy, aggregate
- **Total P&L**: Combined realized + unrealized
- **P&L Rate**: P&L change per time period

**Equity Metrics**:
- **Current Equity**: Total account equity
- **Equity Curve**: Historical equity progression
- **Current Drawdown**: Current drawdown from peak
- **Max Drawdown**: Historical maximum drawdown
- **Drawdown Thresholds**: Warning and critical thresholds

**Data Sources**:
- Trading engine position data
- Real-time market data feeds
- P&L calculation engine
- Historical equity database

#### Exposure and Concentration Metrics

**Exposure Metrics**:
- **Net Exposure**: Net position exposure by asset
- **Gross Exposure**: Gross position exposure by asset
- **Venue Exposure**: Exposure by trading venue
- **Strategy Exposure**: Exposure by strategy
- **Asset Class Exposure**: Exposure by asset class

**Concentration Metrics**:
- **Top N Positions**: Concentration in top N positions
- **Venue Concentration**: Concentration by venue
- **Asset Concentration**: Concentration by asset
- **Strategy Concentration**: Concentration by strategy
- **Concentration Limits**: Warning and critical thresholds

**Data Sources**:
- Position management system
- Risk calculation engine
- Concentration analysis engine
- Real-time exposure monitoring

#### Risk Metrics

**Value-at-Risk (VaR)**:
- **Per-Position VaR**: VaR for individual positions
- **Aggregate VaR**: Portfolio-level VaR
- **VaR Time Windows**: 1-day, 5-day, 10-day VaR
- **VaR Confidence Levels**: 95%, 99% confidence intervals

**Volatility Metrics**:
- **Realized Volatility**: Historical volatility calculations
- **Implied Volatility**: Market-implied volatility
- **Volatility Forecasts**: Predictive volatility models
- **Volatility Thresholds**: Warning and critical levels

**Leverage Metrics**:
- **Current Leverage**: Current leverage ratio
- **Leverage Limits**: Maximum allowable leverage
- **Leverage Utilization**: Percentage of leverage used
- **Leverage Trends**: Historical leverage usage

**Data Sources**:
- Risk calculation engine
- Market data providers
- Volatility calculation models
- Leverage monitoring systems

#### Guardrail Activity Metrics

**Enforcement Actions**:
- **Blocks**: Number of blocked actions
- **Resizes**: Number of position resizes
- **De-Risking**: Number of de-risking actions
- **Mode Changes**: Risk mode changes

**Guardrail Triggers**:
- **Limit Breaches**: Risk limit breach events
- **Threshold Exceedances**: Threshold exceedance events
- **Anomaly Detection**: Anomalous activity detection
- **Guardrail Effectiveness**: Guardrail success rates

**Risk Mode Status**:
- **Current Mode**: Normal / Tightened / Emergency
- **Mode History**: Historical mode changes
- **Mode Triggers**: Triggers for mode changes
- **Mode Effectiveness**: Impact of mode changes

**Data Sources**:
- Risk enforcement engine
- Guardrail monitoring system
- Risk mode management
- Enforcement action logs

#### Operational Health Metrics

**Latency Metrics**:
- **Decision Latency**: Strategy decision latency (p50/p95/p99)
- **Execution Latency**: Order execution latency (p50/p95/p99)
- **End-to-End Latency**: Full system latency (p50/p95/p99)
- **API Latency**: API response latency (p50/p95/p99)

**Error Rate Metrics**:
- **System Error Rate**: Overall system error rate
- **Order Error Rate**: Order execution error rate
- **API Error Rate**: API call error rate
- **Component Error Rate**: Individual component error rates

**Success Rate Metrics**:
- **Order Success Rate**: Order execution success rate
- **API Success Rate**: API call success rate
- **System Success Rate**: Overall system success rate
- **Component Success Rate**: Individual component success rates

**SLO Compliance Metrics**:
- **SLO Status**: Current SLO compliance status
- **Error Budget**: Current error budget status
- **Burn Rate**: Error budget burn rate
- **SLO Trends**: Historical SLO compliance trends

**Data Sources**:
- Performance monitoring system
- SLO monitoring platform
- Error tracking system
- Latency measurement tools

---

## 3. Widgets and Layouts for Decision Speed

### Design Philosophy: "2-Second Answer" to Critical Questions

**Primary Questions**:
1. "Are we safe?" - Risk status and guardrail health
2. "Where's the problem?" - System health and incident location
3. "What's our performance?" - P&L and operational metrics

#### Risk Strip / Risk Meter

**Purpose**: Single-glance risk assessment

**Design**:
- **Compact Multi-Bar**: Visual representation of key risk metrics
- **Color Coding**: Green (Low) / Yellow (Moderate) / Orange (High) / Red (Critical)
- **Aggregated Risk Level**: Overall risk level indicator
- **Click-to-Expand**: Detailed risk panel on click

**Components**:
- **Drawdown Indicator**: Current drawdown vs threshold
- **Exposure Indicator**: Current exposure vs limit
- **Concentration Indicator**: Concentration vs limit
- **VaR Indicator**: VaR vs threshold
- **Guardrail Indicator**: Guardrail activity level

**Interaction**:
- **Hover**: Detailed metric values
- **Click**: Navigate to detailed Risk panel
- **Color Changes**: Real-time risk level updates
- **Alert Integration**: Risk alert integration

#### P&L + Drawdown Panel

**Purpose**: Real-time P&L and drawdown monitoring

**Design**:
- **Combined View**: P&L and drawdown in single panel
- **Real-Time Updates**: Sub-second P&L updates
- **Threshold Markers**: Clear warning and critical thresholds
- **Historical Context**: Intraday P&L curve with drawdown overlay

**Components**:
- **Real-Time P&L**: Current P&L with rate of change
- **Intraday Curve**: Historical P&L progression
- **Drawdown Bar**: Current drawdown with thresholds
- **P&L Breakdown**: P&L by strategy/venue/asset

**Interaction**:
- **Time Range Selection**: Different time ranges for analysis
- **Breakdown Toggle**: Show/hide P&L breakdown
- **Threshold Adjustment**: Adjust warning/critical thresholds
- **Export**: Export P&L data for analysis

#### Venue Health Matrix

**Purpose**: Venue performance and health monitoring

**Design**:
- **Grid Layout**: Rows = venues, columns = health metrics
- **Color Coding**: Green (healthy) / Yellow (warning) / Red (critical)
- **Real-Time Updates**: Sub-second health updates
- **Problem Identification**: Quick venue problem identification

**Components**:
- **Venue Rows**: Individual venue health status
- **Latency Columns**: p50/p95/p99 latency metrics
- **Error Rate Column**: Venue error rate
- **Success Rate Column**: Venue success rate
- **Routing Status Column**: Current routing status

**Interaction**:
- **Sort Options**: Sort by different metrics
- **Filter Options**: Filter by venue status
- **Detail View**: Detailed venue health on click
- **Routing Control**: Venue routing controls

#### Strategy List with Mini Health Badges

**Purpose**: Strategy performance and health monitoring

**Design**:
- **Compact List**: Strategy list with minimal information
- **Health Badges**: Small badges for key metrics
- **Quick Filters**: Fast filtering options
- **Performance Sorting**: Sort by performance metrics

**Components**:
- **Strategy Name**: Strategy identifier
- **P&L Badge**: Current P&L status
- **Error Badge**: Error status indicator
- **Risk Badge**: Risk level indicator
- **Status Badge**: Strategy status (active/inactive)

**Interaction**:
- **Quick Filters**: "Show only degraded", "Show only high exposure"
- **Sort Options**: Sort by P&L, risk, error rate
- **Detail View**: Detailed strategy view on click
- **Control Actions**: Enable/disable strategies

#### Alert Feed with Severity and Suggested Action

**Purpose**: Real-time alert monitoring and response

**Design**:
- **Chronological Feed**: Time-ordered alert list
- **Color Coding**: Severity-based color coding
- **Action Suggestions**: Recommended actions for each alert
- **Quick Response**: One-click response options

**Components**:
- **Alert Timestamp**: Alert generation time
- **Alert Severity**: Critical/High/Medium/Low
- **Alert Category**: Risk/SLO/Venue/Internal
- **Alert Message**: Alert description
- **Suggested Action**: Recommended response action

**Interaction**:
- **Alert Details**: Detailed alert information
- **Runbook Link**: Direct link to relevant runbook
- **Response Actions**: One-click response options
- **Incident Creation**: Create incident from alert

---

## 4. Alerts and Escalation Workflows

### SRE-Based Alert Management for Trading

**Design Philosophy**: Actionable, deduplicated alerts tied to specific runbooks with clear escalation paths

#### Alert Design Principles

**Alert Requirements**:
- **Actionable**: Each alert must have clear action
- **Deduplicated**: No duplicate alerts for same issue
- **Runbook Integration**: Direct link to relevant runbook
- **Context Rich**: Sufficient context for decision making

**Alert Categories**:
- **Risk Alerts**: Limit breaches, high drawdown, abnormal VaR/exposure
- **SLO Alerts**: Latency, error rate, availability breaches
- **Venue Alerts**: Outage, high error rate, throttling
- **Internal Alerts**: State inconsistency, reconciliation failures, observability loss

#### Severity Classification and Routing

**Severity Levels**:
- **Sev-0**: Capital/risk limit breach, incorrect trades
- **Sev-1**: SLO breaches, high error rates, venue issues
- **Sev-2**: Warnings, mild latency, rising burn rate

**Routing Rules**:
- **Sev-0**: Page SRE + Risk immediately, auto-halt/de-risk
- **Sev-1**: Page SRE, inform Strategy/Risk
- **Sev-2**: Non-paging alerts or email notifications

**Escalation Triggers**:
- **Time-Based**: Unresolved after X minutes
- **Frequency-Based**: Repeats N times
- **Severity-Based**: Auto-escalate based on impact

#### Alert Workflow Integration

**From Alert Panel**:
- **Auto-Navigate**: Click alert → navigate to relevant domain panel
- **Context Display**: Show relevant context and data
- **Runbook Access**: Direct runbook link and access
- **Response Tracking**: Track alert response and resolution

**Incident Creation**:
- **One-Click Creation**: Create incident from Sev-0/1 alerts
- **Incident Form**: Small form with IC, summary, impact
- **Incident Tracking**: Track incident lifecycle and resolution
- **Post-Incident Review**: Post-incident review and learning

#### Escalation and Auto-Response

**Auto-Escalation**:
- **Widen Notification**: Expand notification audience
- **Bump Severity**: Increase alert severity
- **Trigger Safe Mode**: Auto-trigger safe mode conditions
- **Auto-Response**: Automated response actions

**Manual Escalation**:
- **Operator Escalation**: Manual escalation by operators
- **Supervisor Escalation**: Escalation to supervisors
- **External Escalation**: Escalation to external parties
- **Emergency Escalation**: Emergency escalation procedures

---

## 5. First-Tier Data Sources and APIs

### Prioritized Data Integration Strategy

**Implementation Phases**:
- **Phase 1**: Command Center + Risk + Execution panels
- **Phase 2**: Strategy + Analytics panels
- **Phase 3**: Governance panel

#### Phase 1: Core Data Sources

**Trading and Position Data API**:
- **Live Positions**: Real-time position data
- **Orders**: Current and historical orders
- **Executions**: Order execution data
- **P&L Calculations**: Real-time P&L calculations

**Data Fields**:
- Position ID, symbol, quantity, price, venue
- Order ID, status, timestamp, quantity, price
- Execution ID, order ID, timestamp, quantity, price
- P&L by strategy, venue, asset, aggregate

**Risk Engine API**:
- **Current Limits**: Risk limits and usage
- **Risk Mode**: Current risk mode and history
- **Enforcement Actions**: Recent enforcement decisions
- **Risk Metrics**: VaR, drawdown, concentration, leverage

**Data Fields**:
- Limit type, current value, maximum value, usage percentage
- Risk mode, timestamp, trigger, previous mode
- Action type, timestamp, context, outcome
- Metric type, current value, threshold, status

**SLO / Observability API**:
- **Performance Metrics**: Latency, error rates, availability
- **SLO Compliance**: SLO status and error budget
- **Alert Data**: Active alerts and history
- **System Health**: Component health status

**Data Fields**:
- Metric name, current value, threshold, status
- SLO name, compliance percentage, error budget, burn rate
- Alert ID, severity, category, message, timestamp
- Component name, status, last check, metrics

#### Phase 2: Extended Data Sources

**Analytics / Signals API**:
- **Signal Catalog**: Available signals and metadata
- **Signal Quality**: Signal freshness, latency, quality scores
- **Signal Consumption**: Current signal consumption by strategies
- **Analytics Jobs**: Analytics job status and results

**Data Fields**:
- Signal ID, name, type, freshness, latency, quality
- Signal ID, consumer, timestamp, status
- Job ID, type, status, start time, end time, result

**Strategy Data API**:
- **Strategy Configuration**: Strategy parameters and settings
- **Strategy Performance**: Strategy performance metrics
- **Strategy Decisions**: Recent strategy decisions
- **Strategy Health**: Strategy health and status

**Data Fields**:
- Strategy ID, name, parameters, status, configuration
- Strategy ID, P&L, ROI, risk metrics, performance
- Decision ID, strategy, timestamp, inputs, outputs
- Strategy ID, health status, last check, metrics

#### Phase 3: Governance Data Sources

**Governance API**:
- **Change History**: Configuration and deployment history
- **Incident Records**: Incident data and resolutions
- **Governance Artifacts**: PRRs, reports, policies
- **Audit Data**: Audit trail and compliance data

**Data Fields**:
- Change ID, type, timestamp, author, description, impact
- Incident ID, severity, category, timeline, resolution
- Artifact ID, type, name, version, date, content
- Audit ID, timestamp, user, action, resource, outcome

### API Integration Requirements

**Performance Requirements**:
- **Latency**: Sub-second response for real-time data
- **Throughput**: Handle concurrent requests from multiple users
- **Reliability**: High availability and failover support
- **Scalability**: Support for growing data volume and users

**Security Requirements**:
- **Authentication**: Secure API authentication
- **Authorization**: Role-based API access control
- **Encryption**: Data encryption in transit and at rest
- **Audit Trail**: Complete API access logging

**Integration Patterns**:
- **WebSocket**: Real-time data streaming
- **REST API**: Standard REST API for configuration
- **GraphQL**: Flexible data querying (optional)
- **Message Queues**: Asynchronous data processing

---

## Implementation Roadmap

### Phase 1: Core Control Surface (Weeks 1-4)

**Week 1-2: Foundation**
- RBAC implementation
- Core data source integration
- Basic UI framework
- Authentication and authorization

**Week 3-4: Command Center**
- Global status strip
- Domain health tiles
- Kill switch controls
- Alert stream integration

**Deliverables**:
- Working Command Center
- Basic RBAC system
- Core data integration
- Alert management

### Phase 2: Domain Panels (Weeks 5-8)

**Week 5-6: Risk and Execution Panels**
- Risk panel with real-time metrics
- Execution panel with venue health
- Enhanced alert workflows
- Incident management

**Week 7-8: Strategy and Analytics Panels**
- Strategy panel with controls
- Analytics panel with signal monitoring
- Enhanced data integration
- Performance optimization

**Deliverables**:
- Complete domain panels
- Enhanced alert workflows
- Full data integration
- Performance optimization

### Phase 3: Governance and Polish (Weeks 9-12)

**Week 9-10: Governance Panel**
- Governance and audit panel
- Change management
- Compliance reporting
- Advanced features

**Week 11-12: Polish and Testing**
- UI/UX polish
- Performance testing
- Security testing
- Documentation and training

**Deliverables**:
- Complete control surface
- Full testing coverage
- Documentation and training
- Production readiness

---

## Success Criteria

### Technical Success Criteria

**Performance**:
- **Page Load**: <2 seconds page load time
- **Data Update**: <1 second data update latency
- **Action Response**: <500ms action response time
- **Concurrent Users**: Support 10+ concurrent users

**Functionality**:
- **Real-Time Data**: Sub-second real-time data updates
- **Alert Management**: Complete alert workflow
- **RBAC**: Full role-based access control
- **Data Integration**: All planned data sources integrated

### Business Success Criteria

**Operational Excellence**:
- **Decision Speed**: 2-second answers to critical questions
- **Risk Management**: Effective risk monitoring and control
- **Incident Response**: Fast incident detection and response
- **User Satisfaction**: High user satisfaction and adoption

**Compliance and Audit**:
- **Audit Trail**: Complete audit trail for all actions
- **Compliance**: Full regulatory compliance
- **Documentation**: Complete documentation and training
- **Security**: Robust security and access control

---

## Conclusion

### Specification Summary

**Comprehensive Blueprint**:
- Complete RBAC specification with 4 distinct roles
- Critical real-time metrics for risk and P&L
- Decision-speed widgets and layouts
- SRE-based alert and escalation workflows
- Prioritized data source integration strategy

**Implementation Ready**:
- Clear implementation roadmap with phases
- Detailed technical requirements
- Success criteria and metrics
- Security and compliance considerations

### Next Steps

**Implementation Planning**:
- Technology stack selection
- Development team assignment
- Project timeline and milestones
- Quality assurance and testing

**Stakeholder Review**:
- Specification review with stakeholders
- Feedback incorporation
- Approval process
- Implementation authorization

**Development Execution**:
- Phase-based implementation
- Regular progress reviews
- Quality assurance and testing
- Deployment and training

---

**Specification Status**: ✅ COMPLETE  
**Technical Requirements**: ✅ DEFINED  
**Implementation Roadmap**: ✅ READY  
**Success Criteria**: ✅ DEFINED  
**Stakeholder Review**: ✅ READY

**MERID Control Surface Specification is complete and ready for implementation. The specification provides a comprehensive blueprint for UI and RBAC that can be handed to front-end implementation agents or used in Figma for design work.**
