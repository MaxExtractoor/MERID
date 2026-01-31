# Audit-Ready Production Template for MERID

## Required Archive Artifacts for Production Audits

Archive these per domain (Strategy, Execution, Analytics, Risk) and for the joint lane.

### Governance and Design

- [ ] **Architecture Diagrams**: Services, data flows, external dependencies
- [ ] **SLI/SLO Specifications**: Targets, error budgets, windows, rationale
- [ ] **Risk/Constraint Specs**: Capital limits, exposure/drawdown caps, kill-switch rules

### Operational Documents

- [ ] **Runbooks**: Per-domain + cross-domain incident runbook
- [ ] **On-Call Schedule**: Rotation documentation and escalation matrix
- [ ] **Change/RFC Records**: Approvals, testing evidence, rollback plans
- [ ] **Production Readiness Review**: Checklist and sign-off for each major release/phase

### Evidence and History

- [ ] **SLO Compliance Reports**: Monthly, including error-budget usage
- [ ] **Incident Logs/Tables**: SLO breaches, kill-switch events, incidents
- [ ] **Incident Reports/Postmortems**: Timelines, impact, corrective actions
- [ ] **Phase Completion/Promotion Reports**: Gate outcomes and decisions

## Concise Checklist for Multi-Domain SRE Services

### Ownership & Criticality

- [ ] **Owner and On-Call Rota**: Documented and accessible
- [ ] **Domain(s) and Criticality Tier**: Defined (Tier 1 trading, Tier 2 analytics, etc.)

### SLI/SLO & Risk

- [ ] **SLIs/SLOs Documented**: Per domain and for E2E journeys
- [ ] **Error Budgets and Burn-Rate Rules**: Defined and agreed
- [ ] **Risk Limits and Kill-Switch Conditions**: Documented and tested

### Observability & Alerts

- [ ] **Dashboards**: Latency, errors, traffic, saturation, P&L, risk
- [ ] **Alerts Mapped to SLOs**: Each with runbook links
- [ ] **Centralized Logging**: With correlation IDs and retention

### Runbooks & Incidents

- [ ] **Per-Domain Runbooks**: Current and tested
- [ ] **Cross-Domain Incident Runbook**: For multi-domain failures
- [ ] **Severity Levels and Escalation Paths**: Defined and communicated
- [ ] **Postmortem Template**: Standard format and storage location

### Change & Deployment

- [ ] **CI/CD with Tests and Rollback**: Automated and validated
- [ ] **Change/RFC Process**: Followed consistently
- [ ] **Production Readiness Review**: Completed and archived

### Evidence & Archiving

- [ ] **SLO Reports and Incident Records**: Stored and searchable
- [ ] **Docs/Configs Versioned**: Linked to releases with tags

## Minimal Runbook Sections for Cross-Domain Incidents

### Scope & Triggers

- **Domains Covered**: Strategy, Execution, Analytics, Risk
- **Triggering Alerts**: Kill-switch fired, E2E trade failure, major venue outage
- **SLO Breaches**: Any domain SLO breach with error budget impact

### Roles

- **Incident Commander**: Overall coordination and decision authority
- **Domain Leads**: Strategy, Execution, Analytics, Risk subject matter experts
- **SRE/Platform**: Infrastructure and system health expertise

### Immediate Actions

- **Halt/De-Risk**: Kill-switch usage, coordinated lane shutdown
- **Mode Switches**: 
  - Strategy: Baseline mode (no live decisions)
  - Execution: Unwind-only mode (flatten positions)
  - Analytics: Advisory-only mode (no signal consumption)
  - Risk: Guardrail enforcement mode (tight limits)

### Diagnosis

- **Primary Dashboards**: 
  - Joint SLO status and error budget usage
  - Domain-specific health metrics
  - External dependency status (venues, data feeds)
- **Quick Triage**: Determine primary domain or external cause
- **Log Analysis**: Correlation IDs across domains

### Recovery

- **Rollback Steps**: 
  - Strategy: Revert to last known good configuration
  - Execution: Reset venue connections and order state
  - Analytics: Clear signal cache and restart pipelines
  - Risk: Reset guardrail state and re-validate limits
- **Re-enable Criteria**: 
  - All SLOs green for 15+ minutes
  - Error budgets within safe limits
  - No open Sev-0 incidents
  - Domain lead sign-off

### Recording

- **Incident Record Fields**:
  - ID, timestamp, duration
  - Services/domains impacted
  - Impact severity (P&L, trades, users)
  - Root cause and contributing factors
  - Corrective actions taken
  - Links to RFCs and code changes
  - Postmortem location and sign-off

## Standard SLIs for Multi-Domain Swarms

### Joint End-to-End SLIs

- **E2E Trade Success Rate**: Requested trades that complete correctly
- **E2E Latency**: Decision → execution → confirmation (p50/p95/p99)
- **Aggregate Error Rate**: Failed or incorrect trades / total trades
- **P&L/Drawdown Compliance**: Within guardrails and limits

### Strategy Lane SLIs

- **Decision Success Rate**: Plans created vs attempted
- **Decision Latency**: p50/p95/p99 for decision generation
- **Allocation Correctness**: Respecting caps and constraints

### Execution Lane SLIs

- **Order Submission Success Rate**: Orders accepted by venues
- **Execution Latency**: Submit → ack/fill (p50/p95/p99)
- **Venue-Specific Error Rates**: Per venue success and retry rates

### Analytics Lane SLIs

- **Signal/Report Freshness**: On-time artifacts / scheduled
- **Signal Latency**: Generation to availability
- **Schema Correctness**: Valid schema and data types
- **Quality Score**: Hit-rate or calibration metrics

### Risk Lane SLIs

- **Allocation Correctness**: Capital allocated per constraints
- **Risk Limit Compliance**: Positions within all limits
- **Guardrail Response Time**: Breach detection to action
- **Capital Efficiency**: Utilization within allowed exposure

## SLO Target Ranges: User-Facing vs Internal Services

### User-Facing / Capital-Facing Services

- **Strategy E2E, Execution, Key APIs**
  - **Availability**: 99.9–99.99% for core trade flows
  - **Latency**: 
    - Interactive/E2E: 99% ≤ 200–400ms, 99.9% ≤ 1s
    - Critical decisions/orders: 99% ≤ 100–200ms
  - **Error Rate**: ≤0.1% for core operations

### Internal/Analytics/Batch Services

- **Analytics Processing, Risk Calculations**
  - **Availability**: 99.0–99.9% depending on criticality
  - **Latency**: Freshness SLOs (99.9% within 2–5 minutes)
  - **Error Rate**: ≤0.5–1% with retries/fallbacks

## Versioning and Secure Storage of Artifacts

### Versioning Strategy

- **Git Storage**: SLO specs, playbooks, runbooks, PRR checklists, configs
- **Release Tags**: `phase7-prod-lane-v1.2`, `phase8-analytics-v1.0`
- **Branch/PR Review**: Changes to governance docs require review like code
- **Linkage**: Incidents linked to exact code/doc versions deployed

### Secure Storage

- **Access Control**: Role-based access to governance docs and logs
- **Encryption**: At-rest and in-transit for sensitive data
- **Audit Logs**: Access to governance systems logged and monitored
- **Backup**: Regular backups with retention policies

## Retention Periods and Legal Considerations

### Retention Matrix

| Artifact Type | Purpose | Typical Retention |
|---|---|---|
| SLI/SLO specs, PRRs, policies | Governance, design evidence | 5–7 years |
| Change/RFC records, release notes | Change control evidence | 5–7 years |
| Incident reports & postmortems | Risk & improvement evidence | 5–7 years |
| SLO/error-budget reports | Performance evidence | 3–7 years |
| Access/auth logs | Security & audit trails | 3–7 years (≥5 if financial) |
| Trade/order logs, config changes | Core audit records | 5–7 years (SOX/SEC/BSA) |
| Non-prod/lab logs | Debugging only | 6–24 months |

### Regulatory Domain Mapping

- **SOX/Financial Reporting**: 7 years for audit workpapers and supporting logs
- **SEC (Broker/Dealer)**: 3–6 years for records, 7 years for audit-relevant data
- **BSA/AML**: 5 years for transaction logs and monitoring outputs
- **General Security**: 1–7 years, 3–5 common, 7 conservative for financial

### WORM/Immutable Storage Requirements

**Strong Candidates for WORM:**
- Trade and order logs (timestamps, inputs, decisions, routing)
- Configuration and limit changes affecting capital/risk exposure
- Access and admin activity logs for production trading systems
- Key audit logs for financial reporting and regulatory obligations

**Implementation:**
- Object storage with WORM/retention locks (S3 with retention policies)
- Cryptographic signatures for artifacts (release bundles, policies, PRRs)
- Restricted deletion/shortening to audited security group only

## Mandatory Artifacts by Audit Type

### SOX-Focused Audit (Financial Reporting Controls)

- SLO/SLA and control policies affecting financial systems
- Change/RFC records for systems touching financial data
- Access/change logs for those systems
- Evidence of periodic reviews (PRRs, control testing, segregation of duties)

### SEC-Style (Broker/Dealer, Trading Systems)

- Order/trade logs with timestamps, decisions, routing outcomes
- Configuration and limit changes (risk limits, capital allocations)
- WORM/immutable storage of core trading/audit logs
- Policies for supervision, surveillance, exception handling, incident records

### BSA/AML-Focused

- Transaction logs and monitoring outputs for suspicious activity detection
- Records of alerts, investigations, escalations (even if no SAR filed)
- Retention policies and evidence of log retention (5 years)

## Template Checklist for Multi-Team SRE Service Onboarding

### Service Definition

- [ ] **Name, Owner, Domain**: Strategy/Execution/Analytics/Risk/Other
- [ ] **Criticality Tier**: Documented impact and user scope

### SRE Integration

- [ ] **SLIs and SLOs**: Defined and reviewed with SRE team
- [ ] **Error Budgets and Burn-Rate Policies**: Agreed and documented
- [ ] **Dashboards and Alerts**: Created, mapped to runbooks

### Operations & Incidents

- [ ] **Runbooks**: Drafted and linked to alerts
- [ ] **On-Call Rotation**: Established with escalation paths
- [ ] **Incident Reporting**: Process explained and tools available

### Change & Releases

- [ ] **CI/CD Integration**: Aligned with existing pipelines and standards
- [ ] **Change/RFC Process**: Aligned with approval matrix
- [ ] **Initial PRR**: Completed and archived

### Compliance & Archiving

- [ ] **Artifact Storage**: Central repo/KB with versioning
- [ ] **Retention Expectations**: Communicated (5–7 years for critical data)
- [ ] **Access Control**: Role-based access implemented

## Automated Audit Documentation

### Policy Document (`retention_policy.md`)

```markdown
# Retention Policy for MERID Production Systems

## Artifact Classes

### FIN-7Y (Financial Records)
- **Scope**: Trade logs, order records, config changes affecting capital
- **Retention**: 7 years
- **Storage**: WORM S3 bucket with retention locks
- **Regulatory**: SOX/SEC/BSA compliance

### OPS-5Y (Operational Records)
- **Scope**: SLO reports, incidents, change records, PRRs
- **Retention**: 5 years
- **Storage**: Standard S3 with lifecycle policies
- **Regulatory**: General compliance

### LAB-1Y (Development Records)
- **Scope**: Non-prod logs, debug data, test results
- **Retention**: 1 year
- **Storage**: Standard S3 with automatic cleanup
- **Regulatory**: Not in scope
```

### Configuration Examples

```yaml
# Log retention configuration
log_retention:
  trade_logs:
    class: FIN-7Y
    storage: s3://merid-audit-worm/trade-logs/
    lifecycle: 7y then delete
    immutable: true
  
  slo_reports:
    class: OPS-5Y
    storage: s3://merid-ops/slo-reports/
    lifecycle: 5y then delete
    immutable: false
  
  debug_logs:
    class: LAB-1Y
    storage: s3://merid-dev/debug-logs/
    lifecycle: 1y then delete
    immutable: false
```

### Evidence Generation

```python
# Automated evidence collection script
def generate_audit_evidence():
    evidence = {
        "retention_compliance": check_retention_policies(),
        "artifact_inventory": list_artifacts_with_classes(),
        "access_logs": get_recent_access_logs(),
        "change_history": get_recent_changes(),
        "slo_compliance": get_slo_reports(),
        "incident_summary": get_incident_summary()
    }
    save_audit_report(evidence, timestamp=datetime.now())
```

## Production Readiness Review (PRR) Template

### PRR Checklist

#### Design & Architecture
- [ ] **Architecture Diagram**: Current and documented
- [ ] **SLI/SLO Definition**: Complete with targets and budgets
- [ ] **Risk Assessment**: Completed with mitigation plans
- [ ] **Dependency Analysis**: External services and failure modes

#### Implementation & Testing
- [ ] **Code Review**: All changes peer-reviewed and approved
- [ ] **Test Coverage**: Unit, integration, end-to-end tests passing
- [ ] **Performance Testing**: Load testing and capacity planning complete
- [ ] **Security Review**: Security assessment and penetration testing

#### Operations & Monitoring
- [ ] **Monitoring**: Dashboards and alerts configured and tested
- [ ] **Runbooks**: Complete and tested for all failure scenarios
- [ ] **On-Call**: Team trained and escalation paths defined
- [ ] **Backup/Recovery**: Tested and documented

#### Governance & Compliance
- [ ] **Change Process**: RFC process documented and followed
- [ ] **Retention Policy**: Configured and validated
- [ ] **Access Control**: Role-based access implemented
- [ ] **Audit Trail**: Logging and audit capabilities verified

#### Sign-Off
- [ ] **Engineering Lead**: Technical readiness approved
- [ ] **SRE Lead**: Operational readiness approved
- [ ] **Business Owner**: Business impact and risk accepted
- [ ] **Security/Compliance**: Security and regulatory requirements met

## Incident Response Template

### Incident Report Structure

```markdown
# Incident Report: [INC-YYYY-MM-DD-NNN]

## Summary
- **Impact**: Brief description of business/user impact
- **Duration**: Start time to resolution time
- **Severity**: Sev-0/1/2 with justification

## Timeline
- **HH:MM**: Incident detected via [alert]
- **HH:MM**: Incident commander assigned
- **HH:MM**: Initial mitigation actions taken
- **HH:MM**: Root cause identified
- **HH:MM**: Resolution implemented
- **HH:MM**: Service restored to normal

## Impact Analysis
- **Users Affected**: Number and type of users
- **Trades Impacted**: Volume and value of affected trades
- **P&L Impact**: Financial impact if applicable
- **SLO Impact**: Error budget consumption

## Root Cause
- **Primary Cause**: Technical or process failure
- **Contributing Factors**: Secondary causes and conditions
- **Detection Gaps**: Why it wasn't caught earlier

## Corrective Actions
- **Immediate**: Actions taken during incident
- **Short-term**: Actions to prevent recurrence (next 30 days)
- **Long-term**: Process or architectural improvements

## Follow-Up
- **Action Items**: Specific tasks with owners and due dates
- **Postmortem Review**: Scheduled review date
- **RFC Links**: Related change requests
```

## Change Request (RFC) Template

### RFC Structure

```markdown
# RFC-[YYYY-MM-DD-NNN]: [Change Title]

## Change Description
- **Purpose**: Why this change is needed
- **Scope**: What systems/components are affected
- **Risk Assessment**: Potential impact and mitigation strategies

## Technical Details
- **Implementation**: How the change will be implemented
- **Testing**: Test plan and expected results
- **Rollback**: Detailed rollback procedure

## Approval Matrix
- **Engineering Lead**: [ ] Approved
- **SRE Lead**: [ ] Approved
- **Business Owner**: [ ] Approved
- **Security/Compliance**: [ ] Approved

## Execution Plan
- **Change Window**: Scheduled date and time
- **Pre-Change Checks**: Validation steps before implementation
- **Post-Change Validation**: Health checks after implementation
- **Monitoring**: Enhanced monitoring during change window
```

This audit-ready template provides comprehensive coverage for production governance with specific focus on financial services compliance and multi-domain swarm operations.
