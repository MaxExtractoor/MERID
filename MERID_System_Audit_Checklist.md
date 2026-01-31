# MERID Layered System Audit Checklist

**Audit Date:** 2026-01-26  
**Audit Scope:** Full production-relevant MERID system  
**Audit Method:** Layered process audit (outside-in + bottom-up)  
**Success Criteria:** All components mapped to control objectives, no critical gaps

---

## 1) Audit Layers and Ownership Matrix

| Layer | Owner | Control Objectives | Key Artifacts |
|-------|-------|-------------------|---------------|
| Infra & Network | Infra/SRE | Security, resilience, observability | Network diagrams, security configs |
| Platform & Services | Platform | Reliability, interfaces, tracing | Service catalog, API specs |
| Engines & Core Modules | Risk/Engineering | Correctness, risk protection | Test reports, config snapshots |
| Agents & Swarm | Swarm Lead | Governance, guardrails, observability | Agent registry, permission matrix |
| Code & Change Control | Security/DevOps | Quality, security, change control | CI configs, SAST reports |
| Governance & Controls | Governance | Policy compliance, kill switches | Governance templates, promotion reports |
| UX & Operator Surface | Product | Truth-bound display, operability | Dashboard screenshots, runbooks |

---

## 2) Infra & Network Layer

**Owner:** Infra/SRE  
**Control Objectives:** Security, resilience, observability

### Network Topology
- [ ] Document current architecture with boundaries between web, merid-api, DB, Redis/queues, on-chain gateways
- [ ] Verify network segmentation and security zones
- [ ] Check firewall rules: only required ports open (80, 443, 8000, internal DB ports)
- [ ] Confirm no direct execution/treasury endpoints exposed to internet
- [ ] Validate TLS configuration for all external endpoints

### Resilience & Capacity
- [ ] Verify auto-restart policies for critical services (core engines, API, DB)
- [ ] Check health check endpoints are properly configured (/health, /ready)
- [ ] Review redundancy for single points of failure
- [ ] Examine last 3-6 months outage logs: root cause, fix, monitoring improvements
- [ ] Validate capacity planning vs current utilization

### Access Controls
- [ ] Confirm RBAC is enforced for all server/cluster access
- [ ] Verify MFA is required for all privileged access
- [ ] Check all access is logged and auditable
- [ ] Review SSH key management and rotation policies
- [ ] Validate least privilege principle for service accounts

**Artifacts:** Network diagrams, security group configs, uptime reports, access logs

---

## 3) Platform & Service Layer

**Owner:** Platform  
**Control Objectives:** Reliability, interfaces, tracing

### Service Inventory
- [ ] List all services: merid-api, observability/, monitoring/, oracles/, onchain/, simulation/, analytics/, war_game_*
- [ ] For each service: health endpoints, dependencies, owner, SLOs
- [ ] Verify service discovery and registration
- [ ] Check service mesh configuration (if used)
- [ ] Validate inter-service communication security

### Interfaces & Contracts
- [ ] Confirm APIs are documented in API_REFERENCE.md
- [ ] Verify API versioning strategy is implemented
- [ ] Check API tests exist (test_api_directly.py, test_endpoints.py)
- [ ] Validate queue/topic configurations are bounded
- [ ] Confirm dead-letter handling for all queues

### Logging & Tracing
- [ ] Ensure structured logging with correlation IDs
- [ ] Verify traceability across service boundaries
- [ ] Check log aggregation and retention policies
- [ ] Validate error handling and escalation paths
- [ ] Confirm monitoring coverage for all services

**Artifacts:** Service catalog, API specs, health check results, logging config

---

## 4) Engines & Core Modules

**Owner:** Risk/Engineering  
**Control Objectives:** Correctness, risk protection

### Reality & Assertions
- [ ] Audit core/ directory structure and implementation
- [ ] Review reality_registry.py and reality_auditor.py
- [ ] Check assertion_source.py and seeding scripts
- [ ] Verify assertions.db integrity and backup procedures
- [ ] Examine test coverage for assertion framework (test_assertion_framework.py, test_enhanced_sighted_degraded_mode.py)

### Risk & Execution
- [ ] Review risk/, execution/, treasury/, governance/ modules
- [ ] Confirm pre-trade risk checks are implemented
- [ ] Verify order validation and kill switches
- [ ] Check compliance with MiFID-style RTS 6/7 equivalents
- [ ] Validate risk parameter configuration and limits

### Analytics & Promotion Logic
- [ ] Audit cohort analysis implementation
- [ ] Review promotion gates (promotion_logic.py)
- [ ] Verify cohort governance integration
- [ ] Check analytics data pipeline integrity
- [ ] Confirm mode decision wiring

**Artifacts:** Module inventory, test reports, coverage reports, risk config snapshots

---

## 5) Agents & Swarm Layer

**Owner:** Swarm Lead  
**Control Objectives:** Governance, guardrails, observability

### Agent Inventory
- [ ] Catalog all agents: strategy, skeptic, risk, news, meta, swarm orchestrators
- [ ] For each agent: purpose, inputs/outputs, permissions, kill conditions
- [ ] Verify agent charter documentation exists
- [ ] Check agent registration and discovery
- [ ] Validate agent lifecycle management

### Governance & Guardrails
- [ ] Review agent constitutions (MERID_REWARD_AND_AGENCY_CHARTER.md)
- [ ] Verify permissions matrix (AGENT_PERMISSIONS_CUSTODY_SAFEGUARDS.md)
- [ ] Confirm agents cannot bypass core risk/execution guards
- [ ] Check META_AUDIT_SWARM.md implementation
- [ ] Validate agent isolation and sandboxing

### Observability
- [ ] Ensure each agent logs decisions and reasons
- [ ] Verify error handling and escalation paths
- [ ] Check trace flows across agents with correlation IDs
- [ ] Confirm agent performance monitoring
- [ ] Validate agent communication security

**Artifacts:** Agent registry, permission matrix, agent log samples, communication diagrams

---

## 6) Codebase & Change Control

**Owner:** Security/DevOps  
**Control Objectives:** Quality, security, change control

### Repo Hygiene
- [ ] Verify branches and tags reflect releases
- [ ] Check for untracked "hotfix" paths
- [ ] Validate .gitignore completeness
- [ ] Confirm secret scanning is enabled
- [ ] Check for dead code removal

### CI/CD & SAST
- [ ] Review pipeline configurations for tests, coverage, SAST/DAST
- [ ] Verify security gates are enforced
- [ ] Check blue-green/canary deployment strategies
- [ ] Confirm promotion gates are implemented
- [ ] Validate test failures block deployments

### Change Management
- [ ] Confirm material changes are documented
- [ ] Check algorithmic governance compliance
- [ ] Verify risk parameter change procedures
- [ ] Review change logs and approval processes
- [ ] Validate rollback procedures

**Artifacts:** CI configs, SAST reports, deployment logs, change documentation

---

## 7) Governance & Controls Layer

**Owner:** Governance  
**Control Objectives:** Policy compliance, kill switches

### Mode & Gate Definitions
- [ ] Review mode definitions (BLIND, SIGHTED_DEGRADED, future modes)
- [ ] Verify promotion gates implementation
- [ ] Check assertion-based mode transitions
- [ ] Confirm cohort metrics integration
- [ ] Validate stress test gates

### Kill Switches & Overrides
- [ ] Verify kill switches exist and are documented
- [ ] Check kill switch testing procedures
- [ ] Confirm override authorization levels
- [ ] Validate kill switch logging and audit trail
- [ ] Test emergency shutdown procedures

### Periodic Review
- [ ] Ensure documented governance review cadence
- [ ] Check Season 1 weekly/bi-weekly review process
- [ ] Verify outcomes are recorded in dossiers
- [ ] Validate governance template usage
- [ ] Check regulatory compliance documentation

**Artifacts:** Governance templates, promotion reports, kill switch docs, review dossiers

---

## 8) UX & Operator Surface

**Owner:** Product  
**Control Objectives:** Truth-bound display, operability

### Dashboards
- [ ] Confirm analytics dashboard shows live data
- [ ] Verify risk dashboard displays current metrics
- [ ] Check system dashboard shows accurate modes
- [ ] Validate governance metrics visibility
- [ ] Ensure no stale or mock data displayed

### Alerting & Runbooks
- [ ] Check alert routing configuration (on-call, Slack, email)
- [ ] Verify critical condition alerts are properly configured
- [ ] Confirm runbooks are up-to-date and tested
- [ ] Validate runbook accessibility and ease of use
- [ ] Check alert fatigue mitigation measures

**Artifacts:** Dashboard screenshots, alert configs, runbook links, UI test results

---

## 9) Cross-Layer Integration Checks

### Control Objective Mapping
- [ ] Map each component to control objectives (correctness, security, observability, change control)
- [ ] Identify gaps in control coverage
- [ ] Verify cross-layer dependencies are documented
- [ ] Check interface contracts between layers
- [ ] Validate end-to-end flow testing

### Runtime Behavior Verification
- [ ] Sample distributed traces for critical flows
- [ ] Verify correlation ID propagation
- [ ] Check metrics vs SLO compliance
- [ ] Validate behavioral audit/replay capabilities
- [ ] Confirm tamper-evident audit trail

**Artifacts:** Control mapping matrix, trace samples, SLO reports, audit trail verification

---

## 10) Automated Tooling Verification

### Code Quality & Security
- [ ] Verify CodeQL/SonarQube integration
- [ ] Check Snyk/Dependabot dependency scanning
- [ ] Confirm secret detection (GitGuardian/Gitleaks)
- [ ] Validate license compliance scanning
- [ ] Check container image security scanning

### Config & Policy
- [ ] Verify Open Policy Agent/Conftest usage
- [ ] Check Kubernetes/Terraform policy validation
- [ ] Validate infrastructure as code security
- [ ] Confirm configuration drift detection
- [ ] Check policy enforcement in CI/CD

**Artifacts:** SAST reports, dependency scans, policy test results, security scan reports

---

## Audit Summary

### Overall System Status
- [ ] **GREEN:** All controls implemented, tested, documented
- [ ] **AMBER:** Some gaps identified, remediation in progress
- [ ] **RED:** Critical gaps requiring immediate attention

### Top 5 Cross-Layer Risks
1. 
2. 
3. 
4. 
5. 

### Critical Findings Requiring Immediate Action
- 
- 
- 

### Remediation Plan
| Finding | Owner | Priority | Deadline | Status |
|---------|-------|----------|----------|---------|
| | | | | |

### Next Audit Date
**Scheduled:** 2026-02-09 (2 weeks)

---

**Audit Completed By:** System Auditor  
**Review Required By:** Governance Board  
**Distribution:** All layer owners, executive team
