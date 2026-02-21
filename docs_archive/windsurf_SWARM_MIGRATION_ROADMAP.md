# MERID → Swarm-Native Kalshi Platform Migration Roadmap

**Status:** Planning Phase  
**Goal:** Transform MERID from messy monorepo to clean, production-grade multi-agent trading platform  
**Approach:** Incremental, reversible, non-breaking changes

---

## Core Principles

✅ **Preserve current working system** - No big-bang rewrites  
✅ **Git-safe operations** - All changes reversible via branches/tags  
✅ **Incremental deployment** - Small PRs, clear impact analysis  
✅ **Test coverage maintained** - No reduction in test protection  
✅ **Kalshi-first focus** - Prediction markets as primary venue

---

## Target Architecture Vision

```
merid/
├── merid_core/           # Domain models, Kalshi clients, risk, PnL, config
├── merid_agents/         # Agent swarm logic, coordination, message schemas
├── merid_streams/        # Market data ingestion (REST, WS), persistence
├── merid_services/       # API services (FastAPI), orchestration endpoints
├── ui/                   # React/Vite dashboards
├── scripts/              # Organized: run/, reports/, maintenance/, testing/
├── tests/                # Unified: unit, integration, swarm-level
├── docs/
│   ├── active/          # Current architecture & design
│   └── archive/         # Historical (compressed/indexed)
├── tools/                # Debug, codegen, utilities
└── infra/                # Deployment configs, Docker, CI/CD
```

---

## Migration Phases

### **Phase 1: Safe Bloat Removal** ⚡ PRIORITY
*Status: Ready to execute*  
*Risk: Low - Removing unused external dependencies*  
*Estimated cleanup: 14,000+ files, 500MB+*

#### 1.1 Create Safety Branch
```bash
git checkout -b pre-bloat-removal
git tag v0.1-pre-cleanup
git push origin v0.1-pre-cleanup
git checkout main
git checkout -b cleanup/phase1-bloat-removal
```

#### 1.2 Remove Flutter SDK (14,000+ files)
**Verification:**
- ✅ No Python imports: `grep -r "from flutter\|import flutter" *.py`
- ✅ Not in requirements.txt
- ✅ No CI/CD references

**Action:**
```bash
git rm -r flutter/
echo "flutter/" >> .gitignore
```

**Rollback:** `git checkout v0.1-pre-cleanup -- flutter/`

#### 1.3 Remove librex PHP Search Engine (135+ files)
**Verification:**
- ✅ No Python imports found
- ✅ Different tech stack (PHP)
- ✅ No cross-references in docs

**Action:**
```bash
git rm -r librex/
echo "librex/" >> .gitignore
```

#### 1.4 Remove merid-api Node.js Stub
**Verification:**
- Check if referenced by web/main.py or React app
- If unused, remove; if needed, document migration path

**Action:**
```bash
# After verification
git rm -r merid-api/
```

#### 1.5 Remove Empty Directories
```bash
git rm -r merid-ui/
git rm -r skills/
git rm -r build/
```

#### 1.6 Remove Temp Files
```bash
git rm tmp_*.py tmp_*.txt
echo "tmp_*" >> .gitignore
```

#### 1.7 Update .gitignore for Generated Artifacts
```gitignore
# Build artifacts
build/
dist/
*.egg-info/

# Coverage & logs
coverage.json
coverage*.xml
*.log
vite.log
MERID_REPO_TREE.txt
_merid-directories.txt

# Databases
*.db
assertions.db
brier_metrics.db

# Temp files
tmp_*
*.tmp

# Dependencies
node_modules/
flutter/
librex/

# IDE
.idea/
.vscode/
__pycache__/
*.pyc
```

**Phase 1 Commit:**
```bash
git add .gitignore
git commit -m "Phase 1: Remove bloat (Flutter SDK, librex, empty dirs, temp files)

- Remove 14,000+ Flutter SDK files (external dependency)
- Remove 135+ librex PHP files (unrelated project)
- Remove empty directories (merid-ui, skills, build)
- Remove temp files (tmp_*.py, tmp_*.txt)
- Update .gitignore for generated artifacts

Impact: ~500MB reduction, cleaner repo
Rollback: git checkout v0.1-pre-cleanup
Tests: All existing tests pass (no production code touched)"
```

---

### **Phase 2: Root Directory Reorganization** 📁
*Status: Ready after Phase 1*  
*Risk: Medium - Moving files, updating imports*  
*Estimated: 100+ files moved*

#### 2.1 Move Test Files (83 files)

**Current:** Root directory cluttered with `test_*.py`  
**Target:** `tests/` directory with proper structure

**Strategy:**
```python
# scripts/migration/move_tests.py
import os
import shutil
from pathlib import Path

ROOT_TESTS = [
    "test_advanced_analytics.py",
    "test_ai_signals.py",
    "test_assertion_framework.py",
    # ... all 83 files
]

for test_file in ROOT_TESTS:
    if test_file.startswith("test_merid_"):
        dest = f"tests/integration/{test_file}"
    elif "integration" in test_file or "system" in test_file:
        dest = f"tests/integration/{test_file}"
    else:
        dest = f"tests/unit/{test_file}"
    
    shutil.move(test_file, dest)
    print(f"Moved {test_file} → {dest}")
```

**Verification:**
```bash
pytest tests/ --collect-only  # Verify all tests discovered
pytest tests/ -v              # Run full suite
```

#### 2.2 Move Run Scripts (37 files)

**Target Structure:**
```
scripts/
├── run/
│   ├── phases/
│   │   ├── phase0.py
│   │   ├── phase2.py
│   │   ├── phase4a.py
│   │   └── ...
│   ├── weekly/
│   │   ├── week1.py
│   │   └── ...
│   └── experiments/
│       ├── baseline.py
│       ├── fault_injection.py
│       └── ...
├── reports/
│   └── (moved in 2.3)
└── maintenance/
    └── (existing scripts)
```

**Consolidation Opportunity:**
Create parameterized runner:
```python
# scripts/run/phase_runner.py
import typer
from enum import Enum

app = typer.Typer()

class Phase(str, Enum):
    PHASE0 = "0"
    PHASE2 = "2"
    PHASE3 = "3"
    PHASE4A = "4a"
    PHASE4B = "4b"
    # ...

class Mode(str, Enum):
    GOVERNANCE = "governance"
    OBSERVABILITY = "observability"
    STRATEGY = "strategy"
    # ...

@app.command()
def run(
    phase: Phase,
    mode: Mode = Mode.GOVERNANCE,
    weekly_review: bool = False
):
    """Run MERID phase experiments with specified mode."""
    # Implementation calls appropriate logic
    pass
```

#### 2.3 Move Generate Scripts (19 files)

**Target:** `scripts/reports/`

**Consolidation:**
```python
# scripts/reports/generate_report.py
import typer

app = typer.Typer()

@app.command()
def phase_report(
    phase: int,
    variant: str = "standard"  # standard, ascii, simple, demo
):
    """Generate phase completion report."""
    pass

@app.command()
def risk_shadow(
    variant: str = "standard"
):
    """Generate risk shadow report."""
    pass

@app.command()
def weekly_summary(
    week: int
):
    """Generate weekly summary."""
    pass
```

#### 2.4 Phase 2 Testing Plan

Before committing:
```bash
# Verify imports still work
python -m pytest tests/ --collect-only

# Run subset of critical tests
pytest tests/integration/test_merid_integration.py -v
pytest tests/unit/test_brier_metrics.py -v

# Check no broken imports
python -c "from scripts.run import phase_runner; print('OK')"
```

**Phase 2 Commit:**
```bash
git commit -m "Phase 2: Reorganize root directory structure

- Move 83 test files to tests/unit and tests/integration
- Move 37 run scripts to scripts/run/{phases,weekly,experiments}
- Move 19 generate scripts to scripts/reports/
- Introduce parameterized runners (phase_runner.py, generate_report.py)
- Deprecate individual phase/week scripts (kept in git history)

Impact: Cleaner root, better organization
Rollback: git checkout HEAD~1
Tests: Full pytest suite passes"
```

---

### **Phase 3: Variant Consolidation** 🔄
*Status: Ready after Phase 2*  
*Risk: Medium - Identifying canonical versions*  
*Estimated: 23+ variant files*

#### 3.1 Audit Variants and Identify Canonical

**Strategy Document:**
```markdown
# Variant Audit Results

## Fixed Variants (7 files)
| File | Status | Canonical Version | Action |
|------|--------|------------------|--------|
| weekly_review_fixed.py | Superseded | weekly_review_roi.py | Archive |
| run_phase4a_governance_fixed.py | Superseded | run_phase4a_governance_final.py | Archive |
| test_agent_fixed.py | Current | test_agent_fixed.py → test_agent.py | Rename |

## Working Variants (3 files)
| run_phase4a_governance_working_final.py | Latest | Rename to canonical | Rename + archive |

## Simple Variants (8 files)
| meridctl_simple.py | Prototype | meridctl.py has more features | Archive |
| test_bootstrap_simple.py | Minimal | Keep for fast tests | Document as "smoke test" |

## Decision Matrix:
- If "fixed" = bug fix over base → make it canonical, archive base
- If "working" = iteration → rename to canonical, archive previous
- If "simple" = minimal/prototype → keep only if serves different purpose (smoke tests)
- If "demo" = example code → move to examples/ or docs/
- If "v2" = major revision → make canonical, archive v1
```

#### 3.2 Create Archive Structure
```bash
mkdir -p archive/variants/{fixed,working,simple,demo,v2}
mkdir -p archive/variants/README.md
```

**Archive README:**
```markdown
# Archived Variant Implementations

This directory contains historical variant implementations that were part of
iterative development but have been superseded by canonical versions.

## Naming Conventions Deprecated

- `*_fixed.py` - Bug fix iterations (canonical version now has fix)
- `*_working.py` - In-progress iterations (final version completed)
- `*_simple.py` - Prototype/minimal versions (full version complete)
- `*_demo.py` - Example/demo code (moved to examples/ or integrated)
- `*_v2.py` - Version iterations (now canonical)

## Restoration

To restore any archived variant:
```bash
git log --all -- archive/variants/
git checkout <commit> -- path/to/file
```

## Canonical Versions

See `.windsurf/CANONICAL_IMPLEMENTATIONS.md` for current authoritative versions.
```

#### 3.3 Move Variants to Archive
```bash
git mv weekly_review_fixed.py archive/variants/fixed/
git mv run_phase4a_governance_working_final.py archive/variants/working/
git mv generate_phase2_completion_report_simple.py archive/variants/simple/
# ... for all 23 variants
```

#### 3.4 Establish Canonical Versions
```python
# scripts/migration/canonicalize.py
RENAMES = {
    "test_agent_fixed.py": "tests/unit/test_agent.py",
    "run_phase4a_governance_working_final.py": "scripts/run/phases/phase4a.py",
    "meridctl_simple.py": "archive/variants/simple/meridctl_simple.py",  # Keep full version
}

for old, new in RENAMES.items():
    if "archive" not in new:
        shutil.move(old, new)
        print(f"Canonicalized: {old} → {new}")
```

**Phase 3 Commit:**
```bash
git commit -m "Phase 3: Consolidate variant implementations

- Archive 23 variant files (*_fixed, *_working, *_simple, *_demo, *_v2)
- Establish canonical versions for all duplicates
- Create archive/variants/ with restoration guide
- Document canonical implementations in CANONICAL_IMPLEMENTATIONS.md

Impact: Single source of truth for each component
Rollback: git checkout HEAD~1 && git checkout HEAD~1 -- archive/
Tests: Canonical versions pass existing test suites"
```

---

### **Phase 4: Target Monorepo Structure** 🏗️
*Status: Ready after Phase 3*  
*Risk: High - Major restructuring*  
*Approach: Gradual namespace migration*

#### 4.1 Current → Target Namespace Mapping

**Current Structure:**
```
merid/
├── agents/              # Mix of canonical and orchestrator agents
├── merid/               # Core domain logic
├── trading/             # Execution, paper trading
├── data/                # Data ingestion
├── web/                 # FastAPI backend
└── web/react/           # React UI
```

**Target Structure:**
```
merid/
├── merid_core/          # Core domain (from merid/ + trading/)
│   ├── kalshi/         # Kalshi client, WS bridge, auth
│   ├── risk/           # Risk management, limits
│   ├── portfolio/      # Position tracking, PnL
│   ├── execution/      # Order placement, fills
│   └── config/         # Configuration management
├── merid_agents/        # Agent swarm (from agents/ + new)
│   ├── canonical/      # Canonical agent implementations
│   ├── orchestrator/   # Multi-agent coordination
│   ├── swarm/          # Swarm patterns (auction, voting, consensus)
│   └── schemas/        # Message contracts (Pydantic models)
├── merid_streams/       # Data ingestion (from data/ + monitoring/)
│   ├── kalshi/         # Kalshi WS streams
│   ├── market_data/    # Market data aggregation
│   └── persistence/    # Stream storage
├── merid_services/      # API layer (from web/)
│   ├── api/            # FastAPI routes
│   ├── orchestration/  # Swarm session management
│   └── websockets/     # WS publishers
└── ui/                  # Frontend (from web/react/)
    ├── kalshi-suite/   # Kalshi trading UI
    └── operator/       # Operator dashboard
```

#### 4.2 Migration Strategy: Namespace Aliasing

**Phase 4a: Create new namespaces with aliases**
```python
# merid_core/__init__.py
"""Core domain models and Kalshi integration.

Temporary: Imports from legacy locations to maintain compatibility.
"""
# New canonical location
from merid_core.kalshi import KalshiClient, KalshiWebSocketBridge
from merid_core.risk import RiskManager, PortfolioLimits
from merid_core.portfolio import Position, PortfolioTracker

# Legacy compatibility (DEPRECATED)
from merid.event_venues.kalshi.client import KalshiVenueClient as _LegacyKalshiClient
from trading.risk import RiskEngine as _LegacyRiskEngine

# Aliases for backward compatibility
KalshiVenueClient = _LegacyKalshiClient  # DEPRECATED: Use KalshiClient
```

**Phase 4b: Update imports incrementally**
```python
# Before
from merid.event_venues.kalshi.client import KalshiVenueClient

# After (with deprecation warning)
from merid_core.kalshi import KalshiClient  # New
from merid_core.kalshi import KalshiVenueClient  # Deprecated alias
```

**Phase 4c: Remove aliases after full migration**

#### 4.3 Gradual File Movement

**Week 1: Core Kalshi Integration**
```bash
mkdir -p merid_core/kalshi
git mv merid/event_venues/kalshi/*.py merid_core/kalshi/
# Update imports using automated script
python scripts/migration/update_imports.py --namespace kalshi
```

**Week 2: Risk & Portfolio**
```bash
mkdir -p merid_core/risk merid_core/portfolio
git mv trading/risk*.py merid_core/risk/
git mv trading/paper_trading.py merid_core/portfolio/
```

**Week 3-4: Agents & Swarm**
```bash
mkdir -p merid_agents/{canonical,orchestrator,swarm,schemas}
git mv agents/*.py merid_agents/canonical/
git mv merid/agents/orchestrator.py merid_agents/orchestrator/
```

#### 4.4 Import Update Automation

```python
# scripts/migration/update_imports.py
import ast
import re
from pathlib import Path

IMPORT_MAPPINGS = {
    "merid.event_venues.kalshi": "merid_core.kalshi",
    "trading.risk": "merid_core.risk",
    "trading.paper_trading": "merid_core.portfolio",
    "agents.": "merid_agents.canonical.",
    "merid.agents.orchestrator": "merid_agents.orchestrator",
}

def update_file_imports(file_path: Path):
    content = file_path.read_text()
    for old, new in IMPORT_MAPPINGS.items():
        content = re.sub(
            rf"from {re.escape(old)}(.*?) import",
            rf"from {new}\1 import",
            content
        )
    file_path.write_text(content)
    return content != file_path.read_text()
```

**Phase 4 Verification:**
```bash
# After each week's migration
pytest tests/ -v
python -m merid_services.api  # Verify API starts
curl http://localhost:8000/api/system/health  # Check endpoints
```

---

### **Phase 5: Kalshi Swarm Architecture** 🐝
*Status: Ready after Phase 4*  
*Risk: Medium - New abstractions*  
*Approach: Add alongside existing, feature flag*

#### 5.1 Swarm Message Schema (Pydantic)

```python
# merid_agents/schemas/messages.py
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any

class AgentRole(str, Enum):
    SCANNER = "scanner"
    FORECASTER = "forecaster"
    SIGNAL = "signal"
    RISK = "risk"
    EXECUTION = "execution"
    ORCHESTRATOR = "orchestrator"

class MarketSignal(BaseModel):
    """Signal from analysis agent to execution."""
    agent_id: str
    market_ticker: str
    direction: str  # "buy_yes", "sell_no", etc.
    confidence: float = Field(ge=0, le=1)
    expected_value: float
    max_position: int
    rationale: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class RiskDecision(BaseModel):
    """Risk agent approval/rejection."""
    signal_id: str
    approved: bool
    adjusted_position: Optional[int] = None
    rejection_reason: Optional[str] = None
    risk_score: float = Field(ge=0, le=1)

class ExecutionReport(BaseModel):
    """Execution agent fill report."""
    order_id: str
    market_ticker: str
    side: str
    qty: int
    price: float
    status: str  # "filled", "partial", "rejected"
    timestamp: datetime
```

#### 5.2 Swarm Session Orchestration

```python
# merid_agents/orchestrator/session.py
from dataclasses import dataclass, field
from typing import List, Dict, Any
import asyncio

@dataclass
class SwarmSession:
    """Bounded multi-agent trading session."""
    session_id: str
    market_tickers: List[str]
    agents: Dict[AgentRole, List[BaseAgent]]
    mode: str = "paper"  # paper, sim, live
    max_duration_seconds: int = 3600
    
    _signals: List[MarketSignal] = field(default_factory=list)
    _decisions: List[RiskDecision] = field(default_factory=list)
    _executions: List[ExecutionReport] = field(default_factory=list)
    
    async def run(self) -> SessionResult:
        """Run complete swarm session."""
        # 1. Scanner agents discover markets
        opportunities = await self._run_scanners()
        
        # 2. Analysis agents generate signals
        signals = await self._run_analysis(opportunities)
        self._signals.extend(signals)
        
        # 3. Risk agent approves/rejects
        decisions = await self._run_risk_check(signals)
        self._decisions.extend(decisions)
        
        # 4. Execution agent places orders
        approved = [d for d in decisions if d.approved]
        executions = await self._run_execution(approved)
        self._executions.extend(executions)
        
        return SessionResult(
            session_id=self.session_id,
            signals=self._signals,
            decisions=self._decisions,
            executions=self._executions,
            metrics=self._compute_metrics()
        )
    
    async def _run_scanners(self) -> List[MarketOpportunity]:
        scanner_agents = self.agents[AgentRole.SCANNER]
        tasks = [agent.scan(self.market_tickers) for agent in scanner_agents]
        results = await asyncio.gather(*tasks)
        return [opp for result in results for opp in result]
    
    async def _run_analysis(self, opportunities) -> List[MarketSignal]:
        # Parallel signal generation
        pass
    
    async def _run_risk_check(self, signals) -> List[RiskDecision]:
        # Risk agent evaluates each signal
        pass
    
    async def _run_execution(self, approved_decisions) -> List[ExecutionReport]:
        # Execute approved trades
        pass
```

#### 5.3 Coordination Patterns

```python
# merid_agents/swarm/patterns.py

class AuctionPattern:
    """Agents bid on opportunities, highest confidence wins."""
    
    async def coordinate(self, agents: List[BaseAgent], opportunity):
        bids = await asyncio.gather(*[
            agent.bid(opportunity) for agent in agents
        ])
        winner = max(bids, key=lambda b: b.confidence)
        return winner

class VotingPattern:
    """Democratic consensus among agents."""
    
    async def coordinate(self, agents: List[BaseAgent], decision):
        votes = await asyncio.gather(*[
            agent.vote(decision) for agent in agents
        ])
        approval_rate = sum(v.approved for v in votes) / len(votes)
        return approval_rate >= self.threshold

class CriticTraderPattern:
    """Trader proposes, critic challenges, iterate."""
    
    async def coordinate(self, trader, critic, opportunity):
        for iteration in range(self.max_iterations):
            proposal = await trader.propose(opportunity)
            critique = await critic.evaluate(proposal)
            
            if critique.approved:
                return proposal
            
            # Trader refines based on feedback
            opportunity = critique.suggested_adjustments
        
        return None  # No consensus
```

#### 5.4 Kalshi WS Bridge Enhancement

```python
# merid_core/kalshi/ws_bridge.py (enhanced)
from typing import Callable, Dict, List
import asyncio
import json

class KalshiWebSocketBridge:
    """Enhanced WS bridge with event routing."""
    
    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = {}
        self._connection = None
    
    async def subscribe(self, topic: str, handler: Callable):
        """Subscribe to Kalshi events by topic."""
        if topic not in self._subscribers:
            self._subscribers[topic] = []
        self._subscribers[topic].append(handler)
    
    async def _handle_message(self, raw_message: str):
        """Route incoming WS messages to subscribers."""
        msg = json.loads(raw_message)
        msg_type = msg.get("type")
        
        # Map Kalshi message types to topics
        topic_map = {
            "orderbook_snapshot": "kalshi.orderbook",
            "orderbook_delta": "kalshi.orderbook",
            "fill": "kalshi.fills",
            "order_status": "kalshi.orders",
        }
        
        topic = topic_map.get(msg_type)
        if topic and topic in self._subscribers:
            for handler in self._subscribers[topic]:
                await handler(msg)
    
    async def publish_to_agents(self, topic: str, data: Dict):
        """Publish normalized events to agent swarm."""
        if topic in self._subscribers:
            for handler in self._subscribers[topic]:
                await handler(data)
```

**Phase 5 Commit:**
```bash
git commit -m "Phase 5: Implement Kalshi swarm architecture

- Add Pydantic message schemas for agent communication
- Implement SwarmSession orchestration with bounded execution
- Add coordination patterns (auction, voting, critic-trader)
- Enhance Kalshi WS bridge with event routing
- Feature flag: ENABLE_SWARM_MODE=false (default off)

Impact: Foundation for multi-agent trading
Rollback: git checkout HEAD~1
Tests: New swarm integration tests pass, existing tests unaffected"
```

---

## Safety Rails & Validation

### Pre-commit Checklist
- [ ] All existing tests pass
- [ ] No imports broken (run `python -c "import merid_core; import merid_agents"`)
- [ ] API still starts (`python -m merid_services.api`)
- [ ] Dashboard loads (`cd ui && npm run dev`)
- [ ] Git history clean (meaningful commits, no force-push to main)

### Circuit Breakers
- Swarm mode disabled by default (`ENABLE_SWARM_MODE=false`)
- Paper trading enforced in non-prod (`TRADING_MODE=paper`)
- Position limits enforced per agent and globally
- Kalshi API rate limiting respected

### Rollback Plan
Each phase has tag:
```bash
# Phase 1
git tag v0.2-post-phase1
# Phase 2
git tag v0.3-post-phase2
# etc.

# Rollback to any phase
git reset --hard v0.2-post-phase1
```

---

## Timeline & Ownership

| Phase | Duration | Owner | Status |
|-------|----------|-------|--------|
| Phase 1: Bloat removal | 1 day | Repo Surgeon | Ready |
| Phase 2: Reorganization | 3 days | Architect | Ready |
| Phase 3: Consolidation | 2 days | Architect | Ready |
| Phase 4: Monorepo structure | 2-4 weeks | Team | Planned |
| Phase 5: Swarm architecture | 2-3 weeks | Swarm Team | Planned |

---

## Success Metrics

### Phase 1-3 (Cleanup)
- ✅ 500MB+ storage reduction
- ✅ 100+ files removed/moved
- ✅ All tests pass
- ✅ Zero production breakage

### Phase 4 (Structure)
- ✅ Clear namespace boundaries
- ✅ No circular dependencies
- ✅ Import paths < 4 levels deep
- ✅ All services start cleanly

### Phase 5 (Swarm)
- ✅ Multi-agent sessions run end-to-end
- ✅ Agent communication via typed schemas
- ✅ Kalshi WS events route to agents
- ✅ Session replay & explainability working

---

## Next Actions

**Immediate (Ready to execute):**
1. Create safety branch: `git checkout -b pre-bloat-removal && git tag v0.1-pre-cleanup`
2. Execute Phase 1 bloat removal (Flutter, librex, temp files)
3. Verify all tests pass post-cleanup
4. Commit and tag `v0.2-post-phase1`

**This Week:**
5. Execute Phase 2 reorganization (tests, scripts)
6. Create consolidated runners (`phase_runner.py`, `generate_report.py`)
7. Commit and tag `v0.3-post-phase2`

**Next Week:**
8. Execute Phase 3 variant consolidation
9. Document canonical implementations
10. Begin Phase 4 planning with namespace mapping

---

**Last Updated:** 2026-02-16  
**Next Review:** After Phase 1 completion  
**Reference:** REPOSITORY_CLEANUP_AUDIT.md
