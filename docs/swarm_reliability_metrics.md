# MERID Swarm Reliability Metrics Specification

**Version:** 1.0  
**Date:** 2026-01-26  
**Owner:** MERID Swarm Reliability Team  

---

## Overview

This specification defines the formal metrics and resilience scoring system for MERID's distributed swarm. It provides the mathematical foundation for measuring cascade behavior, agent misalignment, and topology resilience.

---

## 1. Cascading Metrics

### 1.1 Cascade Size (C)

**Definition:** Total number of agents affected by a failure cascade.

**Computation:**
```python
def calculate_cascade_size(failure_events: List[FailureEvent]) -> int:
    """Count unique agents affected in cascade"""
    affected_agents = set()
    for event in failure_events:
        affected_agents.add(event.agent_id)
        affected_agents.update(event.propagated_to)
    return len(affected_agents)
```

**Mathematical Form::**
\[
C = \left| \bigcup_{i=1}^{n} A_i \right|
\]
where \(A_i\) is the set of agents affected by failure event \(i\).

### 1.2 Cascade Depth (D)

**Definition:** Maximum propagation depth from initial failure.

**Computation:**
```python
def calculate_cascade_depth(failure_events: List[FailureEvent]) -> int:
    """Longest path from initial failure to final affected agent"""
    depth_map = {}
    for event in failure_events:
        if event.is_initial:
            depth_map[event.agent_id] = 0
        else:
            parent_depth = max(depth_map.get(p, 0) for p in event.propagated_from)
            depth_map[event.agent_id] = parent_depth + 1
    return max(depth_map.values(), default=0)
```

**Mathematical Form:**
\[
D = \max_{i \in \text{affected}} \text{dist}(i, \text{initial\_failure})
\]

### 1.3 Branching Factor (b)

**Definition:** Average number of agents each failing agent affects.

**Computation:**
```python
def calculate_branching_factor(failure_events: List[FailureEvent]) -> float:
    """Average propagation count per failing agent"""
    propagation_counts = [len(event.propagated_to) for event in failure_events 
                          if event.propagated_to]
    return sum(propagation_counts) / len(propagation_counts) if propagation_counts else 0.0
```

**Mathematical Form:**
\[
b = \frac{1}{n} \sum_{i=1}^{n} |P_i|
\]
where \(P_i\) is the set of agents that failure \(i\) propagated to.

### 1.4 Retry Index (R)

**Definition:** Ratio of retry attempts to successful operations.

**Computation:**
```python
def calculate_retry_index(operations: List[Operation]) -> float:
    """Retry attempts per successful operation"""
    successful_ops = sum(1 for op in operations if op.status == "success")
    retry_attempts = sum(op.retry_count for op in operations)
    return retry_attempts / successful_ops if successful_ops > 0 else float('inf')
```

**Mathematical Form:**
\[
R = \frac{\sum_{i=1}^{n} r_i}{|\{i : \text{success}_i\}|}
\]

### 1.5 Containment Ratio (CR)

**Definition:** Fraction of cascades contained within k hops.

**Computation:**
```python
def calculate_containment_ratio(cascades: List[Cascade], k: int = 3) -> float:
    """Fraction of cascades contained within k hops"""
    contained = sum(1 for cascade in cascades if cascade.max_depth <= k)
    return contained / len(cascades) if cascades else 1.0
```

**Mathematical Form:**
\[
CR_k = \frac{|\{c : D_c \leq k\}|}{|\{c\}|}
\]

---

## 2. Misalignment Metrics

### 2.1 Variance-Adjusted Cosine Misalignment

**Definition:** Pairwise misalignment between agents A and B using Mahalanobis-whitened cosine similarity.

**Computation:**
```python
def calculate_misalignment(agent_a_state: np.ndarray, 
                          agent_b_state: np.ndarray,
                          covariance_matrix: np.ndarray = None) -> float:
    """Mahalanobis-whitened cosine misalignment m_Σ(A,B)"""
    # Use identity covariance if not provided (falls back to standard cosine)
    if covariance_matrix is None:
        covariance_matrix = np.eye(len(agent_a_state))
    
    # Compute inverse square root of covariance matrix for whitening
    try:
        eigvals, eigvecs = np.linalg.eigh(covariance_matrix)
        sqrt_inv_cov = eigvecs @ np.diag(1.0 / np.sqrt(eigvals + 1e-8)) @ eigvecs.T
    except np.linalg.LinAlgError:
        # Fallback to identity if covariance is singular
        sqrt_inv_cov = np.eye(len(agent_a_state))
    
    # Whiten the state vectors
    v_a_whitened = sqrt_inv_cov @ agent_a_state
    v_b_whitened = sqrt_inv_cov @ agent_b_state
    
    # Compute whitened cosine similarity
    numerator = np.dot(v_a_whitened, v_b_whitened)
    denominator = np.linalg.norm(v_a_whitened) * np.linalg.norm(v_b_whitened)
    
    if denominator < 1e-8:
        return 1.0  # Maximally misaligned for zero vectors
    
    cos_sigma = numerator / denominator
    
    # Convert to misalignment (0 = aligned, 1 = maximally misaligned)
    misalignment = 1.0 - cos_sigma
    return max(0.0, min(1.0, misalignment))
```

**Mathematical Form:**
\[
\cos_{\Sigma}(A,B) = \frac{v_A^\top \Sigma^{-1} v_B}{\sqrt{v_A^\top \Sigma^{-1} v_A}\sqrt{v_B^\top \Sigma^{-1} v_B}}
\]
\[
m_{\Sigma}(A,B) = 1 - \cos_{\Sigma}(A,B)
\]

**Key Properties:**
- Single clean scalar per agent pair
- Accounts for covariance structure in state space
- Plays nicely with clustering and alerting
- Falls back to standard cosine when covariance is identity

### 2.2 Override Rate (OR)

**Definition:** Frequency of agent decisions being overridden by governance.

**Computation:**
```python
def calculate_override_rate(decisions: List[Decision]) -> float:
    """Fraction of decisions overridden"""
    overridden = sum(1 for decision in decisions if decision.overridden)
    return overridden / len(decisions) if decisions else 0.0
```

**Mathematical Form:**
\[
OR = \frac{|\{d : \text{overridden}(d)\}|}{|\{d\}|}
\]

### 2.3 Rollback Rate (RR)

**Definition:** Frequency of agent actions requiring rollback.

**Computation:**
```python
def calculate_rollback_rate(actions: List[Action]) -> float:
    """Fraction of actions rolled back"""
    rolled_back = sum(1 for action in actions if action.rolled_back)
    return rolled_back / len(actions) if actions else 0.0
```

**Mathematical Form:**
\[
RR = \frac{|\{a : \text{rolled\_back}(a)\}|}{|\{a\}|}
\]

---

## 3. Topology Resilience

### 3.1 Ring Resilience Score

**Definition:** Resilience of ring topology with capacity margin α.

**Step Function:**
\[
R_{\text{ring}}(\alpha) =
\begin{cases}
0, & \alpha < \tfrac{1}{2} \\
1, & \alpha \ge \tfrac{1}{2}
\end{cases}
\]

**Smooth Linear Approximation:**
\[
R_{\text{ring}}(\alpha) = \min(1, \max(0, 4\alpha - 1))
\]

**Implementation:**
```python
def ring_resilience_score(alpha: float, smooth: bool = False) -> float:
    """Calculate ring topology resilience score"""
    if not smooth:
        return 0.0 if alpha < 0.5 else 1.0
    else:
        return max(0.0, min(1.0, 4.0 * alpha - 1.0))
```

### 3.2 Mesh Resilience Score

**Definition:** Resilience of mesh topology with degree k and capacity margin α.

**Step Function:**
\[
R_{\text{mesh}}(\alpha,k) =
\begin{cases}
0, & \alpha < \tfrac{1}{k} \\
1, & \alpha \ge \tfrac{1}{k}
\end{cases}
\]

**Smooth Linear Approximation:**
\[
q_m(\alpha,k) = \max(0, 1 - k\alpha)
\]
\[
R_{\text{mesh}}(\alpha,k) = \max(0, 1 - k \cdot q_m(\alpha,k))
\]

**Implementation:**
```python
def mesh_resilience_score(alpha: float, k: int, smooth: bool = False) -> float:
    """Calculate mesh topology resilience score (engineering approximation)"""
    if not smooth:
        critical_alpha = 1.0 / k
        return 0.0 if alpha < critical_alpha else 1.0
    else:
        # Linearized model for engineering use
        q_m = max(0.0, 1.0 - k * alpha)
        resilience = max(0.0, 1.0 - k * q_m)
        return min(1.0, resilience)
```

**Note:** This is an engineering score for comparative analysis, not a literal probability of resilience.

### 3.3 Composite Resilience Score

**Definition:** Weighted combination of topology and operational metrics.

**Computation:**
```python
def composite_resilience_score(topology_score: float,
                              cascade_metrics: Dict[str, float],
                              misalignment_metrics: Dict[str, float],
                              weights: Dict[str, float] = None) -> float:
    """Composite resilience score combining multiple metrics"""
    if weights is None:
        weights = {
            'topology': 0.4,
            'cascade_containment': 0.3,
            'misalignment': 0.2,
            'retry_efficiency': 0.1
        }
    
    # Normalize metrics to [0,1] where higher is better
    cascade_score = 1.0 / (1.0 + cascade_metrics.get('cascade_size', 0))
    containment_score = cascade_metrics.get('containment_ratio', 1.0)
    misalignment_score = 1.0 - misalignment_metrics.get('misalignment', 0.0)
    retry_score = 1.0 / (1.0 + cascade_metrics.get('retry_index', 0))
    
    composite = (
        weights['topology'] * topology_score +
        weights['cascade_containment'] * (cascade_score * containment_score) +
        weights['misalignment'] * misalignment_score +
        weights['retry_efficiency'] * retry_score
    )
    
    return max(0.0, min(1.0, composite))
```

---

## 4. Data Structures

### 4.1 Core Event Types

```python
@dataclass
class FailureEvent:
    agent_id: str
    timestamp: float
    failure_type: str
    propagated_to: List[str]
    propagated_from: List[str]
    is_initial: bool = False

@dataclass
class Operation:
    agent_id: str
    operation_id: str
    status: str  # "success", "failure", "retry"
    retry_count: int = 0
    timestamp: float

@dataclass
class Decision:
    agent_id: str
    decision_id: str
    overridden: bool = False
    timestamp: float

@dataclass
class Action:
    agent_id: str
    action_id: str
    rolled_back: bool = False
    timestamp: float

@dataclass
class Cascade:
    cascade_id: str
    initial_failure: str
    failure_events: List[FailureEvent]
    max_depth: int
    size: int
```

---

## 5. Measurement Protocol

### 5.1 Data Collection

- **Trace IDs:** All operations must have unique trace IDs
- **Span Types:** task_root, agent_execution, agent_message, tool_call, state_read, state_write
- **Timestamps:** High-precision timestamps for all events
- **Agent States:** Vector representations for misalignment calculation

### 5.2 Computation Frequency

- **Real-time:** Cascade size, depth, branching factor (per cascade)
- **Periodic:** Misalignment metrics (hourly), retry index (daily)
- **On-demand:** Resilience scores (per topology change)

### 5.3 Alert Thresholds

- **Cascade Size:** > 10 agents
- **Cascade Depth:** > 5 hops
- **Branching Factor:** > 1.5
- **Misalignment:** > 0.7
- **Retry Index:** > 3.0
- **Resilience Score:** < 0.3

---

## 6. Implementation Requirements

### 6.1 Performance

- Metrics computation must complete within 100ms for real-time alerts
- Historical analysis can take up to 10s
- Memory usage < 100MB for metric storage

### 6.2 Accuracy

- Timestamp precision: 1ms
- Agent state vectors: 128-dimensional float arrays
- Numerical stability: Handle edge cases (division by zero, empty sets)

### 6.3 Integration

- Export metrics via Prometheus endpoint
- Log structured events for analysis
- Support metric queries via API

---

**Next Steps:**
1. Implement tracing infrastructure
2. Deploy watchdog MVP
3. Run initial resilience experiments
4. Refine metrics based on real data

---

**Last Updated:** 2026-01-26  
**Review Date:** 2026-02-02  
**Owner:** MERID Swarm Reliability Team
