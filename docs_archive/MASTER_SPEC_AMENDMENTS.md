# MERID MASTER SPECIFICATION - AMENDMENTS

**Parent Document:** MASTER_SPEC.md v1.0  
**Amendment Version:** v1.1  
**Date:** January 10, 2026  
**Status:** ACTIVE

---

## PURPOSE

This document contains amendments to MASTER_SPEC.md v1.0 identified during adversarial review. These are **control-surface refinements**, not architectural changes. The constitutional layer (v1.0) remains frozen.

---

## AMENDMENT 1: Consensus Fallback Controls

**Reference:** MASTER_SPEC Section 6.1  
**Issue:** Latency target (P99 < 100ms) conflicts with quorum requirement (5/8 agents) when agents are slow.

### 1.1 Partial Quorum Fallback

```python
@dataclass
class ConsensusRound:
    # Existing fields...
    
    # Amendment 1.1: Fallback thresholds
    partial_quorum_threshold: int = 4  # Fallback if timeout approaching
    partial_approval_threshold: float = 0.75  # Higher bar for partial quorum
    timeout_warning_ms: int = 80  # Trigger fallback evaluation at 80ms
```

### 1.2 Timeout-Triggered Downgrade

When `elapsed_time > timeout_warning_ms` and `votes >= partial_quorum_threshold`:
- Evaluate with `partial_approval_threshold` instead of waiting for full quorum
- Log degraded consensus mode in audit trail
- Set `metadata.consensus_mode = "partial"`

---

## AMENDMENT 2: Oracle Coordination Rules

**Reference:** MASTER_SPEC Section 5 (Oracle Stack)  
**Issue:** Oracle contention limit (3 queries/asset) conflicts with triple-redundant queries.

### 2.1 Query Coalescing

```python
class OracleCoordinator:
    """Coalesce identical oracle requests within dedup window."""
    
    DEDUP_WINDOW_MS: int = 100
    
    async def get_price(self, asset: str) -> OraclePrice:
        """Deduplicate concurrent requests for same asset."""
        cache_key = f"{asset}:{int(time.time() * 10)}"  # 100ms buckets
        
        if cache_key in self._pending_requests:
            return await self._pending_requests[cache_key]
        
        future = asyncio.create_task(self._fetch_consensus_price(asset))
        self._pending_requests[cache_key] = future
        return await future
```

### 2.2 Rate Limit Clarification

| Scope | Limit | Window |
|-------|-------|--------|
| Per-asset | 3 queries | 1 second |
| Global | 30 queries | 1 second |
| Per-oracle | 10 queries | 1 second |

### 2.3 Fallback Order

When primary oracle fails:
1. **Primary:** Chainlink (highest reliability)
2. **Secondary:** Pyth (lowest latency)
3. **Tertiary:** Switchboard (backup)

Consensus requires 2-of-3 agreement. If only 1 oracle responds within timeout, use that value with `confidence = 0.5` and flag for human review.

---

## AMENDMENT 3: Governance Safeguards

**Reference:** MASTER_SPEC Section 6.1, 8.2  
**Issue:** Potential governance deadlocks from skeptic vetoes or quorum failures.

### 3.1 Skeptic Veto Cooldown

```python
class SkepticVetoTracker:
    """Prevent skeptic agent from paralyzing system."""
    
    MAX_VETOES_PER_HOUR: int = 3
    COOLDOWN_SECONDS: int = 3600
    
    def __init__(self) -> None:
        self._veto_timestamps: List[float] = []
    
    def can_veto(self) -> bool:
        """Check if skeptic can issue another veto."""
        now = time.time()
        cutoff = now - self.COOLDOWN_SECONDS
        self._veto_timestamps = [t for t in self._veto_timestamps if t > cutoff]
        return len(self._veto_timestamps) < self.MAX_VETOES_PER_HOUR
    
    def record_veto(self) -> None:
        """Record a veto usage."""
        self._veto_timestamps.append(time.time())
```

### 3.2 Dynamic Quorum Floor

When fewer than 5 agents are alive:

| Alive Agents | Min Quorum | Approval Threshold |
|--------------|------------|-------------------|
| 8 | 5 | 60% |
| 7 | 5 | 60% |
| 6 | 4 | 65% |
| 5 | 4 | 70% |
| 4 | 3 | 75% |
| 3 | 3 | 80% |
| < 3 | LOCKDOWN | N/A |

### 3.3 Abstain Handling

Unanimous abstain (all voting agents abstain) results in:
- State: `REJECTED`
- Reason: `"insufficient_confidence"`
- Action: Escalate to human review queue

---

## AMENDMENT 4: Memory Semantics

**Reference:** MASTER_SPEC Section 4.2  
**Issue:** "Immutable memory" conflicts with agent learning/reflection.

### 4.1 Memory Layer Definitions

| Layer | Mutability | Scope | Persistence |
|-------|------------|-------|-------------|
| Core Ledger | Append-only | System-wide | Permanent |
| Agent History | Append-only | Per-agent | Permanent |
| Working Memory | Mutable | Per-agent | Session |
| Cache | Mutable | System-wide | Ephemeral |

### 4.2 Resurrection Lineage Inheritance

When an agent is resurrected:

```python
@dataclass
class ResurrectionContext:
    """Context passed to resurrected agent."""
    
    predecessor_id: str
    death_reason: str
    death_timestamp: float
    
    # Inherited from predecessor
    trust_score: float  # Decayed by 10%
    expertise_score: float  # Preserved
    
    # Memory inheritance
    core_memories: List[Memory]  # Last 100 entries
    learned_patterns: Dict[str, float]  # Preserved
    
    # Reset on resurrection
    working_memory: Dict[str, Any]  # Empty
    session_state: Dict[str, Any]  # Empty
```

### 4.3 Lineage Chain

Each agent maintains:
- `lineage_id`: UUID of original agent (never changes across resurrections)
- `generation`: Increment on each resurrection
- `predecessor_chain`: List of previous instance IDs

---

## AMENDMENT 5: Scaling Enhancements

**Reference:** MASTER_SPEC Section 7  
**Issue:** 500+ agent scaling requires hierarchical consensus.

### 5.1 Hierarchical Consensus (for >50 agents)

```
Level 0: Individual Agents (8 per cluster)
    ↓ vote
Level 1: Cluster Super-Agents (1 per cluster)
    ↓ aggregate
Level 2: Final Consensus (all super-agents)
```

### 5.2 Cluster Formation Rules

- Clusters formed by expertise domain (market, news, risk, etc.)
- Each cluster elects super-agent by highest trust score
- Super-agent aggregates cluster votes into single weighted vote
- Final consensus uses super-agent votes only

---

## VALIDATION

All amendments must satisfy:

- [ ] No contradiction with MASTER_SPEC v1.0 core principles
- [ ] Typed Python with explicit error handling
- [ ] No TODOs or placeholders
- [ ] Deterministic behavior
- [ ] Audit trail integration

---

## VERSION HISTORY

| Version | Date | Changes |
|---------|------|---------|
| 1.1 | 2026-01-10 | Initial amendments from adversarial review |

---

**MASTER_SPEC_AMENDMENTS v1.1 - ACTIVE**
