# MERID Documentation Index

## Repository Structure Overview

The MERID repository contains a comprehensive trading platform with AI/ML capabilities, swarm intelligence, and multi-venue execution. Below is an organized index of all significant documentation.

## Core System Documentation

### Primary Documentation
- **README.md** - Main project documentation defining MERID as a sovereign, local-first decision organism with unrestricted cognition but constrained execution
- **MASTER_DOCUMENTATION.md** - Comprehensive system documentation covering all major components
- **START_HERE.md** - Getting started guide for new developers/operators

### Architecture & Design
- **docs/ARCHITECTURE_DESIGN.md** - Full-stack architecture for production-grade Kubernetes deployment ($10k-$100k trading)
- **docs/PRODUCTION_ARCHITECTURE.md** - Detailed production architecture documentation
- **docs/DATA_BRAIN_ARCHITECTURE.md** - Data processing and intelligence architecture
- **docs/COLLABORATIVE_SWARM_LAYER.md** - Swarm intelligence layer documentation
- **docs/SOVEREIGN_DECENTRALIZED_EXCHANGE.md** - DEX architecture and implementation

## Subsystem Documentation

### Trading & Execution
- **trading/** - Trading engine with adapters, guards, router, and execution components
- **merid/execution/** - Execution router and venue-specific executors
- **merid/event_venues/** - Event venue adapters (Kalshi, Polymarket, Metaculus)
- **RISK_POLICY.md** - Risk management policies and circuit breakers
- **docs/MICRO_CAPITAL_TRADING_STRATEGY.md** - Small capital trading strategy documentation

### Core Infrastructure
- **core/** - Core system components including swarm intelligence, orchestrators, health monitoring
- **core/swarm_intelligence.py** - Swarm coordination and intelligence
- **core/agent_orchestrator.py** - Agent lifecycle management
- **core/health_monitor.py** - System health monitoring
- **core/mode_manager.py** - Mode transitions and management

### Data & Analytics
- **data/** - Data feeds, caching, market data management
- **analytics/** - Analytics and metrics computation
- **SEASON1_ANALYTICS_SPEC.md** - Season 1 analytics specifications
- **BRIER-METRICS-IMPLEMENTATION.md** - Brier score implementation for predictions

### Governance & Compliance
- **governance/** - Constitutional governance and decision frameworks
- **compliance/** - Regulatory compliance and audit logging
- **CLOSED-LOOP-GOVERNANCE.md** - Closed-loop governance implementation
- **docs/COMPLIANCE_READINESS.md** - Compliance readiness documentation

### Web & UI
- **web/** - Web interface with React frontend and API endpoints
- **web/API_ENDPOINTS_SPECIFICATION.md** - API endpoint specifications
- **web/MERID_TRADING_DASHBOARD_README.md** - Trading dashboard documentation
- **MERID_UI_LAYOUT.md** (to be created) - Detailed UI layout specification

### Agents & Swarm
- **agents/** - Agent implementations and streaming capabilities
- **swarm/** - Swarm components and orchestration
- **docs/DEV_SWARM_SPEC.md** - Development swarm specifications
- **docs/SWARM_CONSTITUTION.md** - Swarm governance constitution
- **MULTI_AGENT_ARCHITECTURE.md** - Multi-agent system architecture

## Operations & Deployment

### Deployment Guides
- **docs/DEPLOYMENT_GUIDE.md** - Main deployment guide
- **docs/PRODUCTION-DEPLOYMENT-GUIDE.md** - Production deployment procedures
- **LOCAL_VENUE_TESTING_QUICKSTART.md** - Quick start for local venue testing
- **QUICKSTART.md** - Quick start guide

### Runbooks & Operations
- **docs/SEASON1_OPERATOR_RUNBOOK.md** - Season 1 operator procedures
- **docs/launch_runbook_v1.md** - Launch runbook version 1
- **merid_realtime_paper_runbook.md** - Realtime paper trading runbook
- **MERID_OPERATOR_QUICK_SHEET.md** - Quick reference for operators

## Testing & Coverage

### Test Documentation
- **tests/** - Comprehensive test suite (476+ test files)
- **tests/COVERAGE_BACKLOG.md** - Test coverage tracking and backlog
- **coverage.xml** - Detailed coverage report (currently ~43% actual coverage)
- **coverage_summary.md** - Coverage summary report
- **MERID_TEST_COVERAGE_REPORT*.md** - Various test coverage reports

### Quality & Validation
- **TESTING_DEBUG_REPORT.md** - Testing and debugging reports
- **TEST_AUDIT_REPORT.md** - Test audit findings
- **READY_FOR_TESTING.md** - Testing readiness documentation

## Configuration & Environment

### Configuration
- **config/** - Configuration files and settings
- **.env.example** - Environment variable template
- **pytest.ini** - Pytest configuration
- **gunicorn_conf.py** - Gunicorn server configuration

### Infrastructure
- **docker-compose.yml** - Docker composition for services
- **infra/** - Infrastructure as code
- **deployment/** - Deployment configurations

## Phase & Sprint Documentation

### Implementation Phases
- **PHASE0-*.md** - Phase 0 implementation documents (experiment, execution, operations)
- **PHASE_2_*.md** - Phase 2 progress and completion reports
- **PHASE_3_*.md** - Phase 3 sprint reports (9 sprints completed)
- **PHASE_4_OVERVIEW.md** - Phase 4 overview

### Weekly & Sprint Reports
- **WEEK1-WEEK6-*.md** - Weekly execution status and governance meetings
- **SPRINT_*.md** - Sprint planning and completion reports

## Security & Compliance

### Security
- **security/** - Security implementations and breach detection
- **SECURITY_PLAYBOOK.md** - Security procedures and responses
- **SECURITY_REMEDIATION_COMPLETE.md** - Security remediation status
- **docs/HFT_SWARM_SECURITY.md** - High-frequency trading swarm security

### Audits
- **AUDIT_FINDINGS*.md** - Various audit findings
- **MERID_System_Audit_*.md** - System audit reports
- **CODEBASE_AUDIT_REPORT.md** - Codebase audit findings

## Specialized Components

### Prediction Markets & Venues
- **merid/event_venues/kalshi/** - Kalshi integration
- **merid/event_venues/polymarket/** - Polymarket integration  
- **merid/event_venues/metaculus/** - Metaculus integration
- **docs/polymarket_endpoints.md** - Polymarket API documentation

### Blockchain & Web3
- **core/blockchain_*.py** - Blockchain integrations
- **web3/** - Web3 integrations
- **defi/** - DeFi adapters and implementations
- **onchain/** - On-chain components

### Machine Learning
- **ml/** - Machine learning models and pipelines
- **cognitive_core/** - Cognitive core with agents, memory, governance

## Utilities & Tools

### Scripts & Tools
- **scripts/** - Utility scripts (59+ scripts)
- **tools/** - Development and analysis tools
- **meridctl.py** - MERID control CLI
- **startup.py** - System startup script

### Monitoring & Observability
- **monitoring/** - Monitoring implementations
- **observability/** - Observability tools
- **docs/OBSERVABILITY_IMPLEMENTATION.md** - Observability implementation guide

## Notes

- Total Python packages identified: 50+ with __init__.py files
- Total test files: 476+ in tests/ directory
- Documentation files: 200+ markdown files
- Current test coverage: ~43% (discrepancy with COVERAGE_BACKLOG.md claiming 98%)
- Main technologies: Python, Flutter, SQLite, ONNX, Web3, React
- No dedicated UI package found; web interface in web/ directory

This index provides a comprehensive map of the MERID repository documentation and can be used to navigate the codebase effectively.
