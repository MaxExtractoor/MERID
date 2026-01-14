# MERID MASTER SPECIFICATION v1.0

**Status:** FROZEN - Canonical System Contract  
**Date:** January 10, 2026  
**Authority:** This document is the single source of truth for MERID architecture and implementation.

---

## 1. SYSTEM IDENTITY

**MERID** (Market Event-Reactive Intelligence Daemon) is a sovereign, adversarially-hardened autonomous trading intelligence system designed to survive and operate in hostile market conditions.

### Core Principles
- **Unrestricted Cognition / Constrained Execution**: Agents may reason freely but execution is gated
- **Narrative Immunity**: Price is truth; sentiment is advisory only
- **Anti-Manipulation**: No silent changes; all decisions logged and auditable
- **Human Primacy**: Lockdown capability; governance gates on execution
- **Adversarial Posture**: Assume hostile environment; defense-in-depth

---

## 2. PRODUCTION-GRADE CONSTRAINTS

All code artifacts MUST conform to these constraints:

### 2.1 Code Standards
- **Typed Python only**: All functions must have complete type annotations
- **Explicit error handling**: No bare `except:` clauses; all exceptions typed and logged
- **No TODOs/FIXMEs**: Code is either complete or not committed
- **No placeholders**: No mock data in production paths
- **No speculative logic**: All branches must be reachable and tested

### 2.2 Allowed Patterns
- `NotImplementedError` in abstract base class methods ONLY
- `raise` for explicit failure modes with typed exceptions
- `Optional[T]` for nullable returns with explicit None handling

### 2.3 Forbidden Patterns
- `pass` statements in non-abstract methods
- `# TODO` / `# FIXME` / `# HACK` / `# XXX` comments
- Bare `except:` or `except Exception:`
- `Any` type annotations (use explicit Union types)
- Silent failures (swallowed exceptions)

---

## 3. ARCHITECTURAL LAYERS

### Layer 0: Infrastructure
- **Event Bus**: Async pub/sub with backpressure handling
- **Message Queue**: Redis Streams for durability
- **Orchestration**: Kubernetes with HPA for auto-scaling
- **Observability**: Prometheus metrics + Grafana dashboards

### Layer 1: Data Ingestion
- **Market Streams**: Real-time price feeds via CCXT (Coinbase, Binance)
- **News Feeds**: RSS aggregation (CoinDesk, CoinTelegraph, CryptoPanic)
- **On-Chain Data**: Block explorers and mempool monitoring
- **Social Signals**: Twitter/X sentiment (read-only)

### Layer 2: Agent Mesh
- **8 Core Agents**: Specialized roles with defined charters
- **Autonomous Loops**: Continuous observe-analyze-vote cycles
- **Trust Scoring**: Dynamic reputation based on prediction accuracy
- **Resurrection Protocol**: Failed agents respawn with memory lineage

### Layer 3: Consensus Engine
- **Voting Mechanism**: Weighted by trust scores and expertise
- **Quorum Requirements**: Minimum 5/8 agents for execution decisions
- **Conflict Resolution**: Skeptic agent has veto on high-risk actions
- **Audit Trail**: All votes immutably logged

### Layer 4: Execution Layer
- **Paper Trading**: Default mode for safe testing
- **Live Execution**: Requires explicit toggle + API keys
- **Position Management**: Real-time P&L tracking
- **Risk Controls**: Max position size, stop-loss automation

### Layer 5: Oracle Stack (Triple-Redundant)
- **Primary**: Chainlink price feeds
- **Secondary**: Pyth Network
- **Tertiary**: Switchboard
- **Consensus**: 2-of-3 agreement required for price acceptance

---

## 4. AGENT SPECIFICATIONS

### 4.1 Core Agent Roster

| Agent ID | Role | Expertise | Risk Factor |
|----------|------|-----------|-------------|
| market-analyst-01 | Price pattern detection | 0.92 | 0.4 |
| news-analyst-01 | Sentiment analysis | 0.88 | 0.3 |
| risk-agent-01 | Risk assessment | 0.85 | 0.2 |
| skeptic-agent-01 | Adversarial challenge | 0.90 | 0.6 |
| synthesizer-agent-01 | Cross-signal synthesis | 0.87 | 0.4 |
| strategy-agent-01 | Trade strategy | 0.89 | 0.5 |
| archivist-agent-01 | Memory/history | 0.82 | 0.2 |
| meta-audit-agent-01 | System health | 0.86 | 0.3 |

### 4.2 Agent Interface Contract

```python
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from dataclasses import dataclass

@dataclass
class AgentVote:
    agent_id: str
    decision: str  # 'approve' | 'reject' | 'abstain'
    confidence: float  # 0.0 - 1.0
    reasoning: str
    timestamp: float

class AgentInterface(ABC):
    """Base interface all agents must implement."""
    
    @property
    @abstractmethod
    def agent_id(self) -> str:
        raise NotImplementedError
    
    @property
    @abstractmethod
    def expertise_score(self) -> float:
        raise NotImplementedError
    
    @abstractmethod
    async def observe(self, market_state: Dict[str, Any]) -> None:
        """Ingest current market state."""
        raise NotImplementedError
    
    @abstractmethod
    async def analyze(self) -> Dict[str, Any]:
        """Generate analysis from observations."""
        raise NotImplementedError
    
    @abstractmethod
    async def vote(self, proposal: Dict[str, Any]) -> AgentVote:
        """Cast vote on a proposal."""
        raise NotImplementedError
    
    @abstractmethod
    async def reflect(self, outcome: Dict[str, Any]) -> None:
        """Update internal state based on outcome."""
        raise NotImplementedError
```

---

## 5. EVENT SCHEMA

### 5.1 EventEnvelope

```python
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from enum import Enum
import time
import uuid

class EventType(Enum):
    MARKET_DATA = "market_data"
    NEWS = "news"
    AGENT_OUTPUT = "agent_output"
    CONSENSUS = "consensus"
    EXECUTION = "execution"
    SYSTEM = "system"
    AUDIT = "audit"

@dataclass
class EventEnvelope:
    """Canonical event wrapper for all system messages."""
    
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: EventType = EventType.SYSTEM
    source: str = ""
    timestamp: float = field(default_factory=time.time)
    payload: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Traceability
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    
    # Validation
    schema_version: str = "1.0"
    signature: Optional[str] = None  # For authenticated events
    
    def validate(self) -> bool:
        """Validate envelope structure."""
        if not self.event_id:
            return False
        if not self.source:
            return False
        if self.timestamp <= 0:
            return False
        return True
```

---

## 6. CONSENSUS MECHANISM

### 6.1 ConsensusGraph

```python
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum
import time

class ConsensusState(Enum):
    PENDING = "pending"
    QUORUM_REACHED = "quorum_reached"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    VETOED = "vetoed"

@dataclass
class ConsensusRound:
    """Represents a single consensus voting round."""
    
    round_id: str
    proposal: Dict[str, Any]
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + 30.0)
    
    votes: Dict[str, AgentVote] = field(default_factory=dict)
    state: ConsensusState = ConsensusState.PENDING
    
    # Thresholds
    quorum_threshold: int = 5  # Minimum votes required
    approval_threshold: float = 0.6  # 60% approval required
    
    def add_vote(self, vote: AgentVote) -> None:
        """Add a vote to this round."""
        self.votes[vote.agent_id] = vote
        self._evaluate_state()
    
    def _evaluate_state(self) -> None:
        """Evaluate consensus state based on current votes."""
        if time.time() > self.expires_at:
            self.state = ConsensusState.EXPIRED
            return
        
        # Check for veto (skeptic agent)
        for vote in self.votes.values():
            if vote.agent_id == "skeptic-agent-01" and vote.decision == "reject":
                if vote.confidence > 0.8:
                    self.state = ConsensusState.VETOED
                    return
        
        # Check quorum
        if len(self.votes) < self.quorum_threshold:
            return
        
        self.state = ConsensusState.QUORUM_REACHED
        
        # Calculate weighted approval
        total_weight = 0.0
        approval_weight = 0.0
        
        for vote in self.votes.values():
            weight = vote.confidence
            total_weight += weight
            if vote.decision == "approve":
                approval_weight += weight
        
        approval_ratio = approval_weight / total_weight if total_weight > 0 else 0
        
        if approval_ratio >= self.approval_threshold:
            self.state = ConsensusState.APPROVED
        else:
            self.state = ConsensusState.REJECTED
```

---

## 7. SCALABILITY LAYER

### 7.1 Infrastructure Components

| Component | Technology | Purpose |
|-----------|------------|---------|
| Distributed Training | Ray RLlib | Agent learning at scale |
| Message Queue | Apache Kafka | High-throughput event streaming |
| Cache Layer | Redis Cluster | State caching, rate limiting |
| Orchestration | Kubernetes | Container orchestration |
| Auto-scaling | K8s HPA | Dynamic pod scaling |
| Metrics | Prometheus | Time-series metrics |
| Dashboards | Grafana | Visualization |

### 7.2 Scaling Thresholds

- **Agent Count**: Tested up to 500 concurrent agents
- **Event Throughput**: 10,000 events/second sustained
- **Latency Target**: P99 < 100ms for consensus rounds
- **Oracle Contention**: Max 3 concurrent oracle queries per asset

---

## 8. ADVERSARIAL HARDENING (Stage 6.5)

### 8.1 Threat Model

| Threat | Mitigation |
|--------|------------|
| Oracle manipulation | Triple-redundant oracle stack with 2-of-3 consensus |
| Agent compromise | Trust scoring + anomaly detection + resurrection |
| Network partition | Graceful degradation + local consensus fallback |
| Data poisoning | Input validation + outlier rejection |
| Denial of service | Rate limiting + circuit breakers |

### 8.2 Governance Safeguards

- **Lockdown Mode**: Immediate halt of all execution
- **Skeptic Veto**: High-confidence rejection blocks action
- **Audit Trail**: Immutable logging of all decisions
- **Human Override**: Manual intervention always possible

---

## 9. BUILD ORDER

Strict implementation sequence:

1. **Event Bus + Schema** (`core/streaming_bus.py`, `core/events.py`)
2. **Agent Interface** (`agents/base_agent.py`)
3. **Consensus Engine** (`core/consensus.py`)
4. **Data Streams** (`streams/market.py`, `streams/news.py`)
5. **Core Agents** (8 agents per roster)
6. **Execution Layer** (`trading/execution.py`)
7. **Oracle Stack** (`oracles/chainlink.py`, `oracles/pyth.py`, `oracles/switchboard.py`)
8. **Observability** (`monitoring/metrics.py`, `monitoring/dashboards/`)
9. **Hardening** (`hardening/watchdog.py`, `hardening/circuit_breaker.py`)

---

## 10. VALIDATION CHECKLIST

Before any code merge:

- [ ] All functions have complete type annotations
- [ ] No TODO/FIXME/HACK/XXX comments
- [ ] All exceptions are typed and logged
- [ ] No bare `except:` clauses
- [ ] No `Any` type annotations
- [ ] All branches are reachable
- [ ] Unit tests cover happy path + error cases
- [ ] Integration tests pass
- [ ] Conforms to this MASTER_SPEC

---

## 11. VERSION HISTORY

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-10 | Initial frozen specification |

---

**This document is IMMUTABLE. Any changes require a new version with explicit changelog.**

**MERID MASTER_SPEC v1.0 - FROZEN**
