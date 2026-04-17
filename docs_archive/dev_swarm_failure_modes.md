# 🚨 MERID Dev Swarm Failure Modes and Robustness Framework

**Purpose:** Comprehensive failure-mode analysis and robustness framework for MERID's development swarm  
**Version:** 1.0  
**Date:** 2026-01-26  
**Status:** READY FOR IMPLEMENTATION  

---

## 🎯 **EXECUTIVE SUMMARY**

### **Failure Mode Philosophy**
Assume and test for typical multi-agent dev system failures with explicit detection signals and mitigation strategies. Transform from "hope it works" to "designed to fail gracefully."

### **Core Principles**
- **Explicit Detection:** Every failure mode has clear detection signals
- **Graceful Degradation:** System continues with reduced capability rather than silent corruption
- **Human Escalation:** Clear paths for human intervention when automated recovery fails
- **Learning Loop:** All failures feed back into system improvements

---

## 🔄 **DISTRIBUTED TRACING EVENT SCHEMA**

### **OpenTelemetry-Style Event Specification**

#### **Core Event Structure**
```python
@dataclass
class SwarmEvent:
    # OpenTelemetry trace context
    trace_id: str                    # Global task identifier
    span_id: str                     # Current operation identifier  
    parent_span_id: Optional[str]    # Parent operation identifier
    
    # Event metadata
    event_type: str                  # Event type (see taxonomy)
    timestamp: datetime              # Event timestamp (UTC)
    agent_id: str                    # Agent identifier
    task_id: str                     # Task identifier
    
    # Event-specific attributes
    attributes: Dict[str, Any]       # Event-specific data
    resource: Dict[str, str]         # Resource metadata (agent, tool, etc.)
    
    # Status and outcome
    status: str                      # started, finished, error, cancelled
    outcome: Optional[str]           # success, failure, timeout, etc.
    error_message: Optional[str]     # Error details if any
    
    # Performance metrics
    duration_ms: Optional[int]       # Event duration in milliseconds
    token_count: Optional[int]       # Tokens consumed (for LLM events)
```

#### **Event Type Taxonomy**
```python
class EventType:
    # Task lifecycle events
    TASK_STARTED = "task_started"
    TASK_FINISHED = "task_finished"
    TASK_FAILED = "task_failed"
    TASK_CANCELLED = "task_cancelled"
    
    # Agent lifecycle events  
    AGENT_INVOKED = "agent_invoked"
    AGENT_FINISHED = "agent_finished"
    AGENT_FAILED = "agent_failed"
    
    # Communication events
    MESSAGE_SENT = "message_sent"
    MESSAGE_RECEIVED = "message_received"
    COORDINATION_STARTED = "coordination_started"
    COORDINATION_FINISHED = "coordination_finished"
    
    # Tool execution events
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_FINISHED = "tool_call_finished"
    TOOL_CALL_FAILED = "tool_call_failed"
    
    # State management events
    STATE_READ = "state_read"
    STATE_WRITE = "state_write"
    STATE_CONFLICT = "state_conflict"
    SNAPSHOT_CREATED = "snapshot_created"
    
    # CI/CD events
    CI_JOB_STARTED = "ci_job_started"
    CI_JOB_FINISHED = "ci_job_finished"
    CI_JOB_FAILED = "ci_job_failed"
    
    # Watchdog events
    WATCHDOG_ACTION = "watchdog_action"
    STOPPING_RULE_TRIGGERED = "stopping_rule_triggered"
    ESCALATION_TRIGGERED = "escalation_triggered"
```

#### **Event Attribute Schemas**

##### **Task Events**
```python
# TASK_STARTED attributes
task_started_attrs = {
    "task_type": str,              # "feature_development", "bug_fix", "refactoring"
    "priority": str,               # "high", "medium", "low"
    "requirements": List[str],     # Task requirements
    "assigned_agents": List[str],  # Agent IDs assigned to task
    "estimated_duration": int,     # Estimated duration in seconds
    "context_hash": str,           # Git commit hash of initial context
}

# TASK_FINISHED attributes
task_finished_attrs = {
    "outcome": str,                # "success", "partial_success", "failed"
    "artifacts_created": List[str], # List of created artifacts
    "files_modified": List[str],    # List of modified files
    "ci_status": str,              # "passed", "failed", "skipped"
    "total_duration": int,         # Actual duration in seconds
    "total_tokens": int,           # Total tokens consumed
    "human_intervention": bool,    # Whether human intervention was required
}
```

##### **Agent Events**
```python
# AGENT_INVOKED attributes
agent_invoked_attrs = {
    "agent_type": str,             # "planner", "implementer", "tester", "reviewer"
    "agent_role": str,             # Specific role in current task
    "input_context": str,          # Serialized input context
    "tools_available": List[str],  # List of available tools
    "constraints": List[str],      # Agent constraints
    "expected_output": str,        # Expected output description
}

# AGENT_FINISHED attributes
agent_finished_attrs = {
    "output_summary": str,         # Summary of agent output
    "artifacts_produced": List[str], # Artifacts created by agent
    "tools_used": List[str],       # Tools actually used
    "decisions_made": List[str],   # Key decisions made
    "confidence_score": float,     # Agent confidence in output (0-1)
    "needs_review": bool,          # Whether output needs human review
}
```

##### **Tool Events**
```python
# TOOL_CALL_STARTED attributes
tool_call_started_attrs = {
    "tool_name": str,              # Name of tool being called
    "tool_type": str,              # "git", "ci", "file_system", "api"
    "operation": str,              # Specific operation ("clone", "build", "write")
    "parameters": Dict[str, Any],  # Tool parameters (sanitized)
    "target_resource": str,        # Target resource (file path, API endpoint)
    "estimated_duration": int,     # Estimated duration in seconds
}

# TOOL_CALL_FINISHED attributes
tool_call_finished_attrs = {
    "result_summary": str,         # Summary of tool result
    "artifacts_created": List[str], # Artifacts created by tool
    "data_processed": int,         # Amount of data processed (bytes)
    "exit_code": int,              # Tool exit code
    "stdout_hash": str,            # Hash of stdout output
    "stderr_hash": str,            # Hash of stderr output
}
```

##### **State Events**
```python
# STATE_READ attributes
state_read_attrs = {
    "resource_type": str,          # "file", "git_state", "ci_status", "config"
    "resource_path": str,          # Path or identifier of resource
    "read_version": str,           # Version identifier (git hash, timestamp)
    "read_scope": str,             # "full", "partial", "metadata_only"
    "cache_hit": bool,             # Whether read was served from cache
    "freshness_score": float,      # Freshness of data (0-1, 1 = fresh)
}

# STATE_WRITE attributes
state_write_attrs = {
    "resource_type": str,          # "file", "git_commit", "ci_trigger"
    "resource_path": str,          # Path or identifier of resource
    "write_version": str,          # New version identifier
    "previous_version": str,       # Previous version identifier
    "conflict_detected": bool,     # Whether conflict was detected
    "conflict_resolved": bool,     # Whether conflict was resolved
    "atomic_operation": bool,      # Whether write was part of atomic operation
}

# SNAPSHOT_CREATED attributes
snapshot_created_attrs = {
    "snapshot_id": str,            # Unique snapshot identifier
    "snapshot_type": str,          # "state", "context", "artifacts"
    "included_resources": List[str], # Resources included in snapshot
    "snapshot_size": int,          # Size of snapshot in bytes
    "compression_ratio": float,    # Compression ratio if applicable
    "retention_policy": str,       # Retention policy for snapshot
}
```

#### **Event Flow Examples**

##### **Complete Task Flow**
```python
# 1. Task started
task_start = SwarmEvent(
    trace_id="trace_123",
    span_id="span_001", 
    parent_span_id=None,
    event_type=EventType.TASK_STARTED,
    timestamp=datetime.now(),
    agent_id="orchestrator",
    task_id="task_456",
    attributes={
        "task_type": "feature_development",
        "priority": "high",
        "requirements": ["implement_user_auth", "add_tests", "update_docs"],
        "assigned_agents": ["planner_001", "implementer_001", "tester_001", "reviewer_001"],
        "context_hash": "abc123def456"
    },
    status="started"
)

# 2. Planner agent invoked
planner_start = SwarmEvent(
    trace_id="trace_123",
    span_id="span_002",
    parent_span_id="span_001",
    event_type=EventType.AGENT_INVOKED,
    timestamp=datetime.now(),
    agent_id="planner_001",
    task_id="task_456",
    attributes={
        "agent_type": "planner",
        "agent_role": "task_planning",
        "tools_available": ["git", "file_reader", "dependency_analyzer"],
        "expected_output": "detailed_implementation_plan"
    },
    status="started"
)

# 3. Planner reads repository state
state_read = SwarmEvent(
    trace_id="trace_123",
    span_id="span_003",
    parent_span_id="span_002",
    event_type=EventType.STATE_READ,
    timestamp=datetime.now(),
    agent_id="planner_001",
    task_id="task_456",
    attributes={
        "resource_type": "git_state",
        "resource_path": ".",
        "read_version": "abc123def456",
        "read_scope": "full",
        "freshness_score": 1.0
    },
    status="finished",
    duration_ms=250
)

# 4. Planner creates implementation plan
planner_finish = SwarmEvent(
    trace_id="trace_123",
    span_id="span_002",
    parent_span_id="span_001",
    event_type=EventType.AGENT_FINISHED,
    timestamp=datetime.now(),
    agent_id="planner_001",
    task_id="task_456",
    attributes={
        "output_summary": "Created 3-phase implementation plan",
        "artifacts_produced": ["implementation_plan.md"],
        "confidence_score": 0.95,
        "needs_review": False
    },
    status="finished",
    duration_ms=5000,
    token_count=1500
)
```

---

## 🏗️ **RESILIENT SWARM TOPOLOGIES**

### **1. Topology Patterns for Misalignment Resilience**

#### **Star / Hub-and-Spoke Topology**
```python
class StarTopologyCoordinator:
    def __init__(self):
        self.coordinator_agent = "coordinator"
        self.specialist_agents = ["planner", "implementer", "tester", "reviewer"]
        self.communication_rules = {
            "coordinator_to_specialist": "allowed",
            "specialist_to_coordinator": "allowed", 
            "specialist_to_specialist": "blocked"
        }
    
    def route_message(self, from_agent: str, to_agent: str, message: Dict[str, Any]) -> bool:
        """Enforce star topology communication rules"""
        
        # All communication must go through coordinator
        if from_agent != "coordinator" and to_agent != "coordinator":
            self.log_violation("direct_specialist_communication", from_agent, to_agent)
            return False
        
        # Validate message type for agent role
        if not self.validate_message_for_role(to_agent, message):
            self.log_violation("invalid_message_type", from_agent, to_agent)
            return False
        
        return True
    
    def validate_message_for_role(self, agent_role: str, message: Dict[str, Any]) -> bool:
        """Validate message content matches agent role contract"""
        
        role_message_types = {
            "planner": ["task_specification", "requirements", "coordination_request"],
            "implementer": ["implementation_status", "diff_created", "build_result"],
            "tester": ["test_results", "test_plan", "coverage_report"],
            "reviewer": ["review_decision", "feedback", "approval_status"]
        }
        
        message_type = message.get("message_type")
        allowed_types = role_message_types.get(agent_role, [])
        
        return message_type in allowed_types
```

**Pros:**
- Single coordinator enforces contracts and prevents misalignment between specialists
- Easy to reason about causal chains and debug issues
- Low misalignment risk as specialists never negotiate directly

**Cons:**
- Coordinator is single point of failure and bottleneck
- If coordinator mis-specs work, every spoke inherits the error

**Use Case:** Early MERID phases requiring strict orchestration and easy debugging

#### **Shallow Hierarchy Topology**
```python
class ShallowHierarchyCoordinator:
    def __init__(self):
        self.hierarchy_levels = {
            "level_0": ["global_coordinator"],
            "level_1": ["feature_coordinator_a", "feature_coordinator_b"],
            "level_2": ["planner", "implementer", "tester", "reviewer"]
        }
        
        self.allowed_edges = {
            "global_coordinator": ["feature_coordinator_a", "feature_coordinator_b"],
            "feature_coordinator_a": ["planner", "implementer", "tester", "reviewer"],
            "feature_coordinator_b": ["planner", "implementer", "tester", "reviewer"],
            # Fixed workflow within each feature branch
            "planner": ["implementer"],
            "implementer": ["tester"],
            "tester": ["reviewer"]
        }
    
    def validate_communication_path(self, from_agent: str, to_agent: str) -> bool:
        """Validate communication follows hierarchy rules"""
        
        # Check if edge is allowed
        if to_agent not in self.allowed_edges.get(from_agent, []):
            return False
        
        # Check for cross-branch communication (should go through coordinators)
        from_branch = self.get_agent_branch(from_agent)
        to_branch = self.get_agent_branch(to_agent)
        
        if from_branch != to_branch and from_agent not in ["global_coordinator"] + self.hierarchy_levels["level_1"]:
            return False
        
        return True
    
    def get_agent_branch(self, agent_id: str) -> str:
        """Determine which branch/feature an agent belongs to"""
        if agent_id.startswith("feature_a"):
            return "feature_a"
        elif agent_id.startswith("feature_b"):
            return "feature_b"
        else:
            return "global"
```

**Pros:**
- Coordinator(s) at each level provide structure while reducing single point of failure
- Clear phase boundaries (plan → implement → test → review)
- Less brittle than single hub while maintaining structure
- Misalignment contained within branches

**Cons:**
- More complex to configure
- Misalignment can still propagate within a branch if local coordinators are wrong

**Use Case:** Scaling dev swarm while keeping misalignment contained

#### **Sparse Graph with Explicit Edges**
```python
class SparseGraphCoordinator:
    def __init__(self):
        # Only allow well-defined handoff edges
        self.allowed_handoffs = {
            "planner": ["implementer"],
            "implementer": ["tester"], 
            "tester": ["reviewer"],
            "reviewer": ["planner"],  # For feedback loops
            "coordinator": ["planner", "implementer", "tester", "reviewer"]
        }
        
        self.workflow_states = {
            "planning": "planner",
            "implementation": "implementer", 
            "testing": "tester",
            "review": "reviewer",
            "completed": None
        }
    
    def get_next_agent_in_workflow(self, current_agent: str, task_state: str) -> Optional[str]:
        """Get the next agent in the canonical workflow"""
        
        if current_agent == "planner" and task_state == "planning":
            return "implementer"
        elif current_agent == "implementer" and task_state == "implementation":
            return "tester"
        elif current_agent == "tester" and task_state == "testing":
            return "reviewer"
        elif current_agent == "reviewer" and task_state == "review":
            # Reviewer can send back to planner for rework
            return "planner"
        
        return None
    
    def validate_handoff(self, from_agent: str, to_agent: str, artifacts: List[str]) -> bool:
        """Validate handoff follows explicit edge rules"""
        
        # Check if handoff edge exists
        if to_agent not in self.allowed_handoffs.get(from_agent, []):
            return False
        
        # Validate artifacts are appropriate for handoff
        if not self.validate_handoff_artifacts(from_agent, to_agent, artifacts):
            return False
        
        return True
    
    def validate_handoff_artifacts(self, from_agent: str, to_agent: str, artifacts: List[str]) -> bool:
        """Ensure artifacts match expected handoff requirements"""
        
        handoff_requirements = {
            ("planner", "implementer"): ["specification", "requirements", "design_docs"],
            ("implementer", "tester"): ["code_diff", "implementation_notes", "build_artifacts"],
            ("tester", "reviewer"): ["test_results", "coverage_report", "test_execution_log"],
            ("reviewer", "planner"): ["review_feedback", "rework_requirements", "approval_status"]
        }
        
        required_artifacts = handoff_requirements.get((from_agent, to_agent), [])
        
        # Check if all required artifacts are present
        for req_artifact in required_artifacts:
            if not any(req_artifact in artifact for artifact in artifacts):
                return False
        
        return True
```

**Pros:**
- Avoids full mesh topologies that are prone to emergent miscoordination
- Only allows edges that correspond to well-defined handoffs
- Predictable and easy to trace causal paths

**Cons:**
- Less flexible for complex collaboration patterns
- May require coordinator intervention for exceptional cases

**Use Case:** Production systems requiring predictable coordination and easy debugging

---

#### **Inter-Agent Misalignment**

**Trigger:**
- Agents disagree about goals or assumptions due to ambiguous specs or messages
- Reviewer rejects work for "wrong problem" or tester writes tests for behavior implementer never targeted

**Detection Signals:**
```python
class MisalignmentDetector:
    def detect_goal_misalignment(self, task_trace):
        signals = []
        
        # Compare planner goals vs implementer output
        planner_goals = self.extract_goals(task_trace, "planner")
        implementer_output = self.extract_output(task_trace, "implementer")
        
        goal_alignment_score = self.calculate_alignment(planner_goals, implementer_output)
        if goal_alignment_score < 0.7:
            signals.append({
                "type": "goal_misalignment",
                "score": goal_alignment_score,
                "planner_goals": planner_goals,
                "implementer_output": implementer_output
            })
        
        # Check reviewer rejection reasons
        reviewer_feedback = self.extract_feedback(task_trace, "reviewer")
        if "wrong_problem" in reviewer_feedback.lower():
            signals.append({
                "type": "wrong_problem_rejection",
                "feedback": reviewer_feedback
            })
        
        return signals
```

**Mitigation Strategies:**
- **Goal Validation:** Cross-check agent outputs against upstream goals
- **Explicit Assumption Tracking:** Require agents to state assumptions explicitly
- **Alignment Scoring:** Quantitative measurement of goal alignment
- **Human Escalation:** Trigger human review when alignment scores drop

#### **Communication Ambiguity**

**Trigger:**
- Free-form, unstructured messages cause downstream misinterpretation
- "done" meaning "draft" vs "complete" confusion

**Detection Signals:**
```python
class CommunicationAmbiguityDetector:
    def __init__(self):
        self.ambiguous_terms = ["done", "ready", "complete", "fixed", "updated"]
        self.context_requirements = {
            "done": ["tests_passed", "code_reviewed", "documentation_updated"],
            "ready": ["implementation_complete", "tested", "reviewed"]
        }
    
    def detect_ambiguous_communication(self, message_trace):
        signals = []
        
        for message in message_trace:
            content = message.get("content", "").lower()
            
            for term in self.ambiguous_terms:
                if term in content:
                    # Check if required context is present
                    required_context = self.context_requirements.get(term, [])
                    missing_context = []
                    
                    for context_item in required_context:
                        if context_item not in content:
                            missing_context.append(context_item)
                    
                    if missing_context:
                        signals.append({
                            "type": "ambiguous_termination",
                            "term": term,
                            "message_id": message["id"],
                            "missing_context": missing_context,
                            "sender": message["sender"],
                            "receiver": message["receiver"]
                        })
        
        return signals
```

**Mitigation Strategies:**
- **Structured Message Templates:** Enforce specific message formats
- **Context Validation:** Require explicit completion criteria
- **Semantic Clarification:** Flag ambiguous terms for clarification
- **State Verification:** Cross-check message claims against actual state

#### **Causality Breaks**

**Trigger:**
- Agent acts as if prerequisite happened (tests run, diff applied) but step failed or never occurred
- Partial pipelines marked "complete"

**Detection Signals:**
```python
class CausalityBreakDetector:
    def __init__(self):
        self.required_sequences = {
            "code_merge": ["code_written", "tests_passed", "review_approved"],
            "deployment": ["tests_passed", "security_scan_passed", "deployment_approved"],
            "task_completion": ["implementation_complete", "testing_complete", "review_complete"]
        }
    
    def detect_causality_breaks(self, task_trace):
        signals = []
        
        # Check for orphan actions
        for event in task_trace:
            if event["type"] in ["agent_apply_diff", "merge_proposed"]:
                # Check if prerequisites exist
                prerequisites = self.get_prerequisites(event["type"])
                missing_prereqs = []
                
                for prereq in prerequisites:
                    if not self.has_prereq_event(task_trace, prereq, event["timestamp"]):
                        missing_prereqs.append(prereq)
                
                if missing_prereqs:
                    signals.append({
                        "type": "orphan_action",
                        "action": event["type"],
                        "missing_prerequisites": missing_prereqs,
                        "timestamp": event["timestamp"]
                    })
        
        # Check for inverted dependency order
        test_events = [e for e in task_trace if e["type"] == "tests_passed"]
        code_events = [e for e in task_trace if e["type"] in ["diff_created", "code_updated"]]
        
        for test_event in test_events:
            # Find if there's a code event after this test
            later_code = [c for c in code_events if c["timestamp"] > test_event["timestamp"]]
            if later_code:
                signals.append({
                    "type": "inverted_dependency_order",
                    "test_timestamp": test_event["timestamp"],
                    "later_code_events": later_code
                })
        
        return signals
```

**Mitigation Strategies:**
- **Prerequisite Validation:** Enforce sequence validation before actions
- **State Consistency Checks:** Verify actual state matches claimed state
- **Causal Dependency Tracking:** Maintain explicit dependency graphs
- **Automated Rollback:** Roll back actions when causality breaks detected

#### **Under-Specification at Topology Level**

**Trigger:**
- Roles, responsibilities, and allowed actions not crisply defined
- Agents drift into overlapping or conflicting behaviors

**Detection Signals:**
```python
class RoleSpecificationDetector:
    def __init__(self):
        self.role_boundaries = {
            "planner": ["create_plan", "define_requirements", "coordinate_task"],
            "implementer": ["write_code", "create_diff", "update_documentation"],
            "tester": ["write_tests", "run_tests", "report_results"],
            "reviewer": ["review_code", "provide_feedback", "approve_reject"]
        }
    
    def detect_role_boundary_violations(self, task_trace):
        signals = []
        
        for event in task_trace:
            if event["type"] == "agent_action":
                agent_role = event["agent_role"]
                action = event["action"]
                
                # Check if action is within role boundaries
                allowed_actions = self.role_boundaries.get(agent_role, [])
                
                if action not in allowed_actions:
                    signals.append({
                        "type": "role_boundary_violation",
                        "agent_role": agent_role,
                        "action": action,
                        "allowed_actions": allowed_actions,
                        "agent_id": event["agent_id"]
                    })
        
        # Check for overlapping responsibilities
        action_distribution = self.calculate_action_distribution(task_trace)
        for action, roles in action_distribution.items():
            if len(roles) > 1:
                signals.append({
                    "type": "overlapping_responsibilities",
                    "action": action,
                    "performing_roles": roles
                })
        
        return signals
```

**Mitigation Strategies:**
- **Role Contract Enforcement:** Strict enforcement of role boundaries
- **Action Auditing:** Continuous monitoring of role-based actions
- **Conflict Resolution:** Clear protocols for resolving role conflicts
- **Specification Evolution:** Regular updates to role specifications

#### **Role and Behavior Drift Over Time**

**Trigger:**
- Agents slowly change behavior for same role name
- "reviewer" begins editing directly

**Detection Signals:**
```python
class BehaviorDriftDetector:
    def __init__(self):
        self.baseline_profiles = {}
        self.drift_threshold = 0.3  # 30% change triggers alert
    
    def detect_behavior_drift(self, agent_id, current_window, historical_baseline):
        signals = []
        
        # Compare current behavior profile with baseline
        current_profile = self.create_behavior_profile(current_window)
        baseline_profile = self.baseline_profiles.get(agent_id, historical_baseline)
        
        # Calculate drift score
        drift_score = self.calculate_drift_score(current_profile, baseline_profile)
        
        if drift_score > self.drift_threshold:
            signals.append({
                "type": "behavior_drift",
                "agent_id": agent_id,
                "drift_score": drift_score,
                "current_profile": current_profile,
                "baseline_profile": baseline_profile
            })
        
        return signals
```

**Mitigation Strategies:**
- **Baseline Profiling:** Establish and maintain behavior baselines
- **Continuous Drift Monitoring:** Real-time drift detection and alerting
- **Automated Re-training:** Retrain agents when drift detected
- **Role Re-certification:** Periodic validation of role compliance

---

## 📊 **COORDINATION HEALTH METRICS**

### **2. Measuring Causality Between Agents**

#### **Dependency Completeness Metrics**
```python
class DependencyCompletenessTracker:
    def __init__(self):
        self.prerequisite_map = {
            "implementer_create_diff": ["planner_spec", "current_repo_version", "ticket_id"],
            "tester_run_tests": ["implementer_diff", "test_plan", "build_artifacts"],
            "reviewer_approve": ["tester_results", "implementer_diff", "review_criteria"]
        }
    
    def calculate_dependency_completeness(self, task_traces: List[Dict]) -> Dict[str, float]:
        """Calculate % of actions with all prerequisites present"""
        
        completeness_scores = {}
        total_actions = 0
        complete_actions = 0
        
        for trace in task_traces:
            for event in trace["events"]:
                if event["type"] in self.prerequisite_map:
                    total_actions += 1
                    
                    required_prereqs = self.prerequisite_map[event["type"]]
                    available_prereqs = event.get("upstream_artifacts", [])
                    
                    # Check if all prerequisites are present and linked
                    missing_prereqs = []
                    for prereq in required_prereqs:
                        if not any(prereq in artifact for artifact in available_prereqs):
                            missing_prereqs.append(prereq)
                    
                    if not missing_prereqs:
                        complete_actions += 1
                    else:
                        completeness_scores[f"missing_{event['type']}"] = missing_prereqs
        
        overall_completeness = complete_actions / total_actions if total_actions > 0 else 0
        
        return {
            "overall_dependency_completeness": overall_completeness,
            "total_actions": total_actions,
            "complete_actions": complete_actions,
            "missing_dependencies": completeness_scores
        }
```

---

## 🚨 **ROLE VIOLATION EVENT LOGGING**

### **4. Events to Log for Detecting Role Violations**

#### **Agent Action Tracking**
```python
class RoleViolationLogger:
    def __init__(self):
        self.role_action_boundaries = {
            "planner": ["plan_only", "create_spec", "analyze_requirements", "coordinate_task"],
            "implementer": ["edit_code", "create_diff", "run_build", "update_documentation"],
            "tester": ["run_tests", "test_only", "create_test_plan", "report_results"],
            "reviewer": ["review_only", "provide_feedback", "approve_reject", "propose_merge"]
        }
        
        self.restricted_resources = {
            "reviewer": ["/prod/config/", "/infra/production/", "/security/secrets/"],
            "tester": ["/prod/config/", "/infra/production/"],
            "implementer": ["/security/secrets/", "/infra/production/"]
        }
    
    def log_agent_action(self, agent_id: str, agent_role: str, action_type: str,
                        resource_scope: List[str], artifacts: List[str]) -> AgentActionEvent:
        """Log agent action for role violation detection"""
        
        # Check for role boundary violations
        is_violation = self.check_role_violation(agent_role, action_type, resource_scope)
        
        event = AgentActionEvent(
            event_type="agent_action",
            timestamp=datetime.now(),
            agent_id=agent_id,
            agent_role=agent_role,
            action_type=action_type,
            resource_scope=resource_scope,
            artifacts=artifacts,
            is_role_violation=is_violation["is_violation"],
            violation_type=is_violation.get("violation_type"),
            violation_details=is_violation.get("details"),
            policy_decision=None  # Will be filled by policy engine
        )
        
        # Store event
        self.store_action_event(event)
        
        return event
    
    def check_role_violation(self, agent_role: str, action_type: str, 
                           resource_scope: List[str]) -> Dict[str, Any]:
        """Check if action violates role boundaries"""
        
        # Check action type violations
        allowed_actions = self.role_action_boundaries.get(agent_role, [])
        if action_type not in allowed_actions:
            return {
                "is_violation": True,
                "violation_type": "action_boundary_violation",
                "details": f"Agent role '{agent_role}' not allowed to perform action '{action_type}'"
            }
        
        # Check resource scope violations
        restricted_paths = self.restricted_resources.get(agent_role, [])
        for resource_path in resource_scope:
            for restricted_path in restricted_paths:
                if resource_path.startswith(restricted_path):
                    return {
                        "is_violation": True,
                        "violation_type": "resource_scope_violation",
                        "details": f"Agent role '{agent_role}' not allowed to access resource '{resource_path}'"
                    }
        
        # Special case: reviewer editing code
        if agent_role == "reviewer" and action_type == "edit_code":
            return {
                "is_violation": True,
                "violation_type": "reviewer_editing_violation",
                "details": "Reviewer should not edit code directly, only review"
            }
        
        return {"is_violation": False}
```

#### **Policy Decision Logging**
```python
class PolicyDecisionLogger:
    def __init__(self):
        self.policy_decisions = []
        self.violation_counts = {}
    
    def log_policy_decision(self, requested_action: AgentActionEvent, 
                           allowed: bool, reason: str, 
                           policy_engine: str) -> PolicyDecisionEvent:
        """Log policy decision for role violation tracking"""
        
        decision = PolicyDecisionEvent(
            event_type="policy_decision",
            timestamp=datetime.now(),
            requested_action_type=requested_action.action_type,
            requested_agent_role=requested_action.agent_role,
            requested_agent_id=requested_action.agent_id,
            allowed=allowed,
            reason=reason,
            policy_engine=policy_engine,
            resource_scope=requested_action.resource_scope,
            decision_context=self.get_decision_context(requested_action)
        )
        
        # Update violation statistics
        if not allowed:
            self.update_violation_counts(requested_action.agent_role, requested_action.action_type)
        
        # Store decision
        self.policy_decisions.append(decision)
        
        return decision
    
    def calculate_violation_rate(self, time_window: int = 3600) -> Dict[str, float]:
        """Calculate off-contract actions per 100 tasks per role"""
        
        cutoff_time = datetime.now() - timedelta(seconds=time_window)
        recent_decisions = [d for d in self.policy_decisions if d["timestamp"] > cutoff_time]
        
        violation_rates = {}
        
        # Group by role
        role_decisions = {}
        for decision in recent_decisions:
            role = decision["requested_agent_role"]
            if role not in role_decisions:
                role_decisions[role] = {"total": 0, "violations": 0}
            
            role_decisions[role]["total"] += 1
            if not decision["allowed"]:
                role_decisions[role]["violations"] += 1
        
        # Calculate rates
        for role, counts in role_decisions.items():
            if counts["total"] > 0:
                violation_rates[role] = (counts["violations"] / counts["total"]) * 100
            else:
                violation_rates[role] = 0
        
        return violation_rates
```

---

## 📈 **COORDINATION HEALTH KPIS AND THRESHOLDS**

### **5. Coordination Health Metrics Dashboard**

#### **Turn Efficiency Metrics**
```python
class TurnEfficiencyMonitor:
    def __init__(self):
        self.baseline_metrics = {
            "avg_agent_turns_per_task": 8.5,
            "avg_messages_per_task": 12.0,
            "avg_turns_per_agent": {
                "planner": 2.1,
                "implementer": 3.2,
                "tester": 2.0,
                "reviewer": 1.2
            }
        }
        
        self.alert_thresholds = {
            "turns_increase_factor": 2.0,  # Alert if turns double baseline
            "messages_increase_factor": 2.0,
            "efficiency_drop_threshold": 0.5  # Alert if efficiency drops by 50%
        }
    
    def calculate_turn_efficiency(self, task_traces: List[Dict]) -> Dict[str, Any]:
        """Calculate turn efficiency metrics with alerting"""
        
        total_tasks = len(task_traces)
        total_turns = 0
        total_messages = 0
        agent_turns = {}
        
        for trace in task_traces:
            task_turns = self.count_task_turns(trace)
            task_messages = self.count_task_messages(trace)
            
            total_turns += task_turns
            total_messages += task_messages
            
            # Count turns per agent
            for agent_id, turns in self.get_agent_turn_distribution(trace).items():
                if agent_id not in agent_turns:
                    agent_turns[agent_id] = 0
                agent_turns[agent_id] += turns
        
        # Calculate current metrics
        current_metrics = {
            "avg_agent_turns_per_task": total_turns / total_tasks if total_tasks > 0 else 0,
            "avg_messages_per_task": total_messages / total_tasks if total_tasks > 0 else 0,
            "avg_turns_per_agent": {
                agent_id: turns / total_tasks if total_tasks > 0 else 0
                for agent_id, turns in agent_turns.items()
            }
        }
        
        # Check for alerts
        alerts = []
        
        # Check turn count increase
        turns_increase = current_metrics["avg_agent_turns_per_task"] / self.baseline_metrics["avg_agent_turns_per_task"]
        if turns_increase > self.alert_thresholds["turns_increase_factor"]:
            alerts.append({
                "type": "high_turn_count",
                "severity": "medium",
                "message": f"Turn count increased by {turns_increase:.1f}x baseline",
                "current_value": current_metrics["avg_agent_turns_per_task"],
                "baseline_value": self.baseline_metrics["avg_agent_turns_per_task"]
            })
        
        # Check message count increase
        messages_increase = current_metrics["avg_messages_per_task"] / self.baseline_metrics["avg_messages_per_task"]
        if messages_increase > self.alert_thresholds["messages_increase_factor"]:
            alerts.append({
                "type": "high_message_count",
                "severity": "medium",
                "message": f"Message count increased by {messages_increase:.1f}x baseline",
                "current_value": current_metrics["avg_messages_per_task"],
                "baseline_value": self.baseline_metrics["avg_messages_per_task"]
            })
        
        return {
            "current_metrics": current_metrics,
            "baseline_metrics": self.baseline_metrics,
            "alerts": alerts,
            "efficiency_score": self.calculate_efficiency_score(current_metrics)
        }
    
    def calculate_efficiency_score(self, metrics: Dict[str, Any]) -> float:
        """Calculate overall efficiency score (0-1)"""
        
        turns_efficiency = min(1.0, self.baseline_metrics["avg_agent_turns_per_task"] / metrics["avg_agent_turns_per_task"])
        messages_efficiency = min(1.0, self.baseline_metrics["avg_messages_per_task"] / metrics["avg_messages_per_task"])
        
        return (turns_efficiency + messages_efficiency) / 2
```

#### **Useful Work Ratio Metrics**
```python
class UsefulWorkRatioTracker:
    def __init__(self):
        self.useful_actions = [
            "edit_code", "create_diff", "run_tests", "review_only", 
            "propose_merge", "create_spec", "update_documentation"
        ]
        
        self.chatter_actions = [
            "status_update", "coordination_request", "clarification",
            "ping", "acknowledgment", "general_communication"
        ]
        
        self.ratio_threshold = 0.3  # Alert if useful work ratio drops below 30%
    
    def calculate_useful_work_ratio(self, task_traces: List[Dict]) -> Dict[str, Any]:
        """Calculate useful actions vs total actions ratio"""
        
        total_actions = 0
        useful_actions = 0
        chatter_actions = 0
        
        task_ratios = []
        
        for trace in task_traces:
            task_total = 0
            task_useful = 0
            task_chatter = 0
            
            for event in trace["events"]:
                if event["type"] == "agent_action":
                    action_type = event["action_type"]
                    task_total += 1
                    total_actions += 1
                    
                    if action_type in self.useful_actions:
                        task_useful += 1
                        useful_actions += 1
                    elif action_type in self.chatter_actions:
                        task_chatter += 1
                        chatter_actions += 1
            
            if task_total > 0:
                task_ratio = task_useful / task_total
                task_ratios.append(task_ratio)
        
        overall_ratio = useful_actions / total_actions if total_actions > 0 else 0
        
        # Check for alerts
        alerts = []
        if overall_ratio < self.ratio_threshold:
            alerts.append({
                "type": "low_useful_work_ratio",
                "severity": "high",
                "message": f"Useful work ratio {overall_ratio:.2f} below threshold {self.ratio_threshold}",
                "current_ratio": overall_ratio,
                "threshold": self.ratio_threshold
            })
        
        return {
            "overall_ratio": overall_ratio,
            "total_actions": total_actions,
            "useful_actions": useful_actions,
            "chatter_actions": chatter_actions,
            "task_ratios": task_ratios,
            "alerts": alerts,
            "coordination_bloat_detected": overall_ratio < self.ratio_threshold
        }
```

#### **Path Adherence Metrics**
```python
class PathAdherenceMonitor:
    def __init__(self):
        self.canonical_paths = {
            "feature_development": ["planner", "implementer", "tester", "reviewer"],
            "bug_fix": ["planner", "implementer", "tester", "reviewer"],
            "refactoring": ["planner", "implementer", "tester", "reviewer"]
        }
        
        self.adherence_threshold = 0.90  # Alert if adherence drops below 90%
    
    def calculate_path_adherence(self, task_traces: List[Dict]) -> Dict[str, Any]:
        """Calculate % of tasks following canonical path"""
        
        total_tasks = len(task_traces)
        adherent_tasks = 0
        path_violations = []
        
        adherence_by_task_type = {}
        
        for trace in task_traces:
            task_type = trace.get("task_type", "feature_development")
            canonical_path = self.canonical_paths.get(task_type, self.canonical_paths["feature_development"])
            
            # Extract actual path from trace
            actual_path = self.extract_agent_sequence(trace)
            
            # Check adherence
            is_adherent, violations = self.check_path_adherence(canonical_path, actual_path)
            
            if is_adherent:
                adherent_tasks += 1
            else:
                path_violations.append({
                    "task_id": trace["task_id"],
                    "task_type": task_type,
                    "canonical_path": canonical_path,
                    "actual_path": actual_path,
                    "violations": violations
                })
            
            # Track by task type
            if task_type not in adherence_by_task_type:
                adherence_by_task_type[task_type] = {"total": 0, "adherent": 0}
            adherence_by_task_type[task_type]["total"] += 1
            if is_adherent:
                adherence_by_task_type[task_type]["adherent"] += 1
        
        overall_adherence = adherent_tasks / total_tasks if total_tasks > 0 else 0
        
        # Calculate adherence by task type
        adherence_by_task_type["overall"] = {
            "total": total_tasks,
            "adherent": adherent_tasks,
            "adherence_rate": overall_adherence
        }
        
        for task_type, counts in adherence_by_task_type.items():
            if task_type != "overall":
                adherence_by_task_type[task_type]["adherence_rate"] = (
                    counts["adherent"] / counts["total"] if counts["total"] > 0 else 0
                )
        
        # Check for alerts
        alerts = []
        if overall_adherence < self.adherence_threshold:
            alerts.append({
                "type": "low_path_adherence",
                "severity": "high",
                "message": f"Path adherence {overall_adherence:.2f} below threshold {self.adherence_threshold}",
                "current_adherence": overall_adherence,
                "threshold": self.adherence_threshold,
                "violations_count": len(path_violations)
            })
        
        return {
            "overall_adherence": overall_adherence,
            "total_tasks": total_tasks,
            "adherent_tasks": adherent_tasks,
            "path_violations": path_violations,
            "adherence_by_task_type": adherence_by_task_type,
            "alerts": alerts,
            "coordinator_logic_review_needed": overall_adherence < self.adherence_threshold
        }
```

---

## 📊 **CASCADE FAILURE LIKELIHOOD METRICS**

### **1. Metrics for Cascading Failure Likelihood**

#### **Cascade Length Measurement**
```python
class CascadeLengthAnalyzer:
    def __init__(self):
        self.failure_subgraph_builder = FailureSubgraphBuilder()
    
    def calculate_cascade_length(self, failure_incidents: List[Dict]) -> Dict[str, Any]:
        """For each failure incident, count distinct agents and tools touched after first fault"""
        
        cascade_lengths = []
        cascade_details = []
        
        for incident in failure_incidents:
            # Build failure subgraph from trace
            failure_subgraph = self.failure_subgraph_builder.build_subgraph(
                incident["trace_id"], 
                incident["initial_failure_timestamp"]
            )
            
            # Count distinct agents and tools touched after first fault
            cascade_length = self.calculate_subgraph_size(failure_subgraph)
            cascade_lengths.append(cascade_length)
            
            cascade_details.append({
                "incident_id": incident["incident_id"],
                "cascade_length": cascade_length,
                "agents_affected": failure_subgraph["affected_agents"],
                "tools_affected": failure_subgraph["affected_tools"],
                "failure_depth": failure_subgraph["max_depth"]
            })
        
        # Calculate statistics
        avg_cascade_length = sum(cascade_lengths) / len(cascade_lengths) if cascade_lengths else 0
        cascade_lengths.sort()
        p95_cascade_length = cascade_lengths[int(0.95 * len(cascade_lengths))] if cascade_lengths else 0
        
        return {
            "average_cascade_length": avg_cascade_length,
            "p95_cascade_length": p95_cascade_length,
            "max_cascade_length": max(cascade_lengths) if cascade_lengths else 0,
            "total_incidents": len(failure_incidents),
            "cascade_details": cascade_details,
            "cascade_distribution": self.calculate_length_distribution(cascade_lengths)
        }
    
    def calculate_subgraph_size(self, failure_subgraph: Dict) -> int:
        """Calculate size of failure subgraph (agents + tools)"""
        return len(failure_subgraph["affected_agents"]) + len(failure_subgraph["affected_tools"])
```

#### **Cascade Branching Factor**
```python
class CascadeBranchingAnalyzer:
    def __init__(self):
        self.branching_threshold = 1.0  # >1 suggests amplification
    
    def calculate_branching_factor(self, failure_incidents: List[Dict]) -> Dict[str, Any]:
        """Average number of new failing actions per failing action in next step"""
        
        branching_factors = []
        amplification_incidents = []
        
        for incident in failure_incidents:
            failure_timeline = self.build_failure_timeline(incident["trace_events"])
            branching_factor = self.calculate_incident_branching(failure_timeline)
            
            branching_factors.append(branching_factor)
            
            if branching_factor > self.branching_threshold:
                amplification_incidents.append({
                    "incident_id": incident["incident_id"],
                    "branching_factor": branching_factor,
                    "amplification_type": "cascade_amplification",
                    "failure_steps": len(failure_timeline)
                })
        
        mean_branching_factor = sum(branching_factors) / len(branching_factors) if branching_factors else 0
        
        return {
            "mean_branching_factor": mean_branching_factor,
            "max_branching_factor": max(branching_factors) if branching_factors else 0,
            "amplification_rate": len(amplification_incidents) / len(failure_incidents),
            "amplification_incidents": amplification_incidents,
            "branching_distribution": self.calculate_branching_distribution(branching_factors)
        }
    
    def calculate_incident_branching(self, failure_timeline: List[Dict]) -> float:
        """Calculate branching factor for a single incident"""
        
        total_branches = 0
        total_steps = 0
        
        for i in range(len(failure_timeline) - 1):
            current_step = failure_timeline[i]
            next_step = failure_timeline[i + 1]
            
            # Count new failing actions in next step
            current_failing_actions = set(current_step["failing_actions"])
            next_failing_actions = set(next_step["failing_actions"])
            
            new_failures = len(next_failing_actions - current_failing_actions)
            total_branches += new_failures
            total_steps += 1
        
        return total_branches / total_steps if total_steps > 0 else 0
```

#### **Retry-Storm Score**
```python
class RetryStormAnalyzer:
    def __init__(self):
        self.retry_window_seconds = 30  # Δt < 30 seconds for same tool/task
        self.retry_storm_threshold = 3  # >3 retries indicates storm
    
    def calculate_retry_storm_score(self, failure_incidents: List[Dict]) -> Dict[str, Any]:
        """Count tool failures followed by retries from multiple agents in short window"""
        
        retry_storms = []
        retry_scores = []
        
        for incident in failure_incidents:
            tool_failures = self.extract_tool_failures(incident["trace_events"])
            retry_groups = self.group_concurrent_retries(tool_failures)
            
            for retry_group in retry_groups:
                if len(retry_group) >= self.retry_storm_threshold:
                    storm_score = len(retry_group)
                    retry_storms.append({
                        "incident_id": incident["incident_id"],
                        "tool_name": retry_group[0]["tool_name"],
                        "task_id": retry_group[0]["task_id"],
                        "retry_count": storm_score,
                        "participating_agents": list(set(r["agent_id"] for r in retry_group)),
                        "time_window_seconds": retry_group[-1]["timestamp"] - retry_group[0]["timestamp"]
                    })
                    retry_scores.append(storm_score)
        
        avg_retry_score = sum(retry_scores) / len(retry_scores) if retry_scores else 0
        
        return {
            "average_retry_storm_score": avg_retry_score,
            "max_retry_storm_score": max(retry_scores) if retry_scores else 0,
            "total_retry_storms": len(retry_storms),
            "retry_storms": retry_storms,
            "cascading_load_indicators": self.identify_cascading_load_patterns(retry_storms)
        }
```

#### **Containment Rate**
```python
class ContainmentRateAnalyzer:
    def __init__(self):
        self.phases = ["planning", "implementation", "testing", "review"]
    
    def calculate_containment_rate(self, failure_incidents: List[Dict]) -> Dict[str, Any]:
        """Fraction of faults confined to single agent/phase vs multiple phases"""
        
        contained_failures = 0
        cross_phase_failures = 0
        cross_agent_failures = 0
        
        containment_details = []
        
        for incident in failure_incidents:
            affected_phases = self.get_affected_phases(incident["trace_events"])
            affected_agents = self.get_affected_agents(incident["trace_events"])
            
            is_phase_contained = len(affected_phases) == 1
            is_agent_contained = len(affected_agents) == 1
            
            if is_phase_contained and is_agent_contained:
                contained_failures += 1
            else:
                if not is_phase_contained:
                    cross_phase_failures += 1
                if not is_agent_contained:
                    cross_agent_failures += 1
            
            containment_details.append({
                "incident_id": incident["incident_id"],
                "affected_phases": affected_phases,
                "affected_agents": affected_agents,
                "is_phase_contained": is_phase_contained,
                "is_agent_contained": is_agent_contained,
                "containment_type": self.classify_containment_type(is_phase_contained, is_agent_contained)
            })
        
        total_failures = len(failure_incidents)
        
        return {
            "overall_containment_rate": contained_failures / total_failures if total_failures > 0 else 0,
            "phase_containment_rate": (total_failures - cross_phase_failures) / total_failures if total_failures > 0 else 0,
            "agent_containment_rate": (total_failures - cross_agent_failures) / total_failures if total_failures > 0 else 0,
            "contained_failures": contained_failures,
            "cross_phase_failures": cross_phase_failures,
            "cross_agent_failures": cross_agent_failures,
            "containment_details": containment_details,
            "cascade_likelihood_indicator": 1 - (contained_failures / total_failures if total_failures > 0 else 0)
        }
```

---

## 🎯 **INTER-AGENT MISALIGNMENT METRICS**

### **2. Quantitative Measures of Inter-Agent Misalignment**

#### **Spec-Implementation-Test Agreement**
```python
class AgreementScorer:
    def __init__(self):
        self.alignment_evaluator = AlignmentEvaluator()
        self.agreement_scale = (0, 5)  # 0-5 agreement score
    
    def calculate_spec_impl_test_agreement(self, tasks: List[Dict]) -> Dict[str, Any]:
        """Score alignment between spec, diff, and tests (0-5 scale)"""
        
        agreement_scores = []
        agreement_details = []
        
        for task in tasks:
            spec_content = task.get("spec_content", "")
            impl_diff = task.get("implementation_diff", "")
            test_content = task.get("test_content", "")
            
            # Score spec-implementation alignment
            spec_impl_score = self.alignment_evaluator.score_alignment(
                spec_content, impl_diff, "spec_implementation"
            )
            
            # Score implementation-test alignment
            impl_test_score = self.alignment_evaluator.score_alignment(
                impl_diff, test_content, "implementation_test"
            )
            
            # Score spec-test alignment
            spec_test_score = self.alignment_evaluator.score_alignment(
                spec_content, test_content, "spec_test"
            )
            
            # Calculate overall agreement
            overall_agreement = (spec_impl_score + impl_test_score + spec_test_score) / 3
            agreement_scores.append(overall_agreement)
            
            agreement_details.append({
                "task_id": task["task_id"],
                "spec_impl_score": spec_impl_score,
                "impl_test_score": impl_test_score,
                "spec_test_score": spec_test_score,
                "overall_agreement": overall_agreement,
                "misalignment_indicators": self.identify_misalignment_indicators(
                    spec_impl_score, impl_test_score, spec_test_score
                )
            })
        
        # Calculate statistics
        mean_agreement = sum(agreement_scores) / len(agreement_scores) if agreement_scores else 0
        low_agreement_rate = len([s for s in agreement_scores if s < 2.0]) / len(agreement_scores) if agreement_scores else 0
        
        return {
            "mean_agreement_score": mean_agreement,
            "agreement_distribution": self.calculate_score_distribution(agreement_scores),
            "low_agreement_rate": low_agreement_rate,
            "agreement_details": agreement_details,
            "semantic_misalignment_detected": mean_agreement < 3.0
        }
```

---

## 🏗️ **TOPOLOGY RESILIENCE SCORE**

### **3. Resilience Score for Topology Under Agent Faults**

#### **Fault-Injection Experiment Framework**
```python
class TopologyResilienceEvaluator:
    def __init__(self):
        self.baseline_metrics = {
            "success_rate": 0.95,
            "bad_merge_rate": 0.05,
            "avg_cascade_length": 1.2,
            "coordination_overhead": 10.5
        }
        
        self.max_values = {
            "success_rate": 1.0,
            "bad_merge_rate": 0.5,
            "avg_cascade_length": 10.0,
            "coordination_overhead": 50.0
        }
        
        # Weights based on MERID priorities (heavy weight on bad merges and cascades)
        self.weights = {
            "success_rate": 0.2,
            "bad_merge_rate": 0.4,
            "avg_cascade_length": 0.3,
            "coordination_overhead": 0.1
        }
    
    def evaluate_topology_resilience(self, topology_name: str, 
                                   fault_injection_results: List[Dict]) -> Dict[str, Any]:
        """Calculate composite resilience score from fault injection experiments"""
        
        # Aggregate results across experiments
        aggregated_metrics = self.aggregate_experiment_results(fault_injection_results)
        
        # Normalize metrics (higher is better)
        normalized_metrics = self.normalize_metrics(aggregated_metrics)
        
        # Calculate composite resilience score
        resilience_score = self.calculate_resilience_score(normalized_metrics)
        
        return {
            "topology_name": topology_name,
            "resilience_score": resilience_score,
            "raw_metrics": aggregated_metrics,
            "normalized_metrics": normalized_metrics,
            "experiment_summary": {
                "total_experiments": len(fault_injection_results),
                "fault_injection_rate": self.calculate_fault_injection_rate(fault_injection_results),
                "performance_degradation": self.calculate_performance_degradation(aggregated_metrics)
            },
            "resilience_breakdown": {
                "success_rate_contribution": normalized_metrics["success_rate"] * self.weights["success_rate"],
                "bad_merge_rate_contribution": normalized_metrics["bad_merge_rate"] * self.weights["bad_merge_rate"],
                "cascade_length_contribution": normalized_metrics["avg_cascade_length"] * self.weights["avg_cascade_length"],
                "overhead_contribution": normalized_metrics["coordination_overhead"] * self.weights["coordination_overhead"]
            }
        }
    
    def normalize_metrics(self, metrics: Dict[str, float]) -> Dict[str, float]:
        """Normalize metrics to 0-1 scale where higher is better"""
        
        return {
            "success_rate": metrics["success_rate"] / self.max_values["success_rate"],
            "bad_merge_rate": 1 - min(1.0, metrics["bad_merge_rate"] / self.max_values["bad_merge_rate"]),
            "avg_cascade_length": 1 - min(1.0, (metrics["avg_cascade_length"] - 1) / (self.max_values["avg_cascade_length"] - 1)),
            "coordination_overhead": 1 - min(1.0, metrics["coordination_overhead"] / self.max_values["coordination_overhead"])
        }
    
    def calculate_resilience_score(self, normalized_metrics: Dict[str, float]) -> float:
        """Calculate weighted composite resilience score"""
        
        score = 0.0
        for metric, value in normalized_metrics.items():
            score += value * self.weights[metric]
        
        return score
```

#### **Comparative Topology Analysis**
```python
class TopologyComparator:
    def __init__(self):
        self.resilience_evaluator = TopologyResilienceEvaluator()
    
    def compare_topologies(self, topology_results: Dict[str, List[Dict]]) -> Dict[str, Any]:
        """Compare resilience scores across multiple topologies"""
        
        resilience_scores = {}
        topology_details = {}
        
        for topology_name, fault_results in topology_results.items():
            evaluation = self.resilience_evaluator.evaluate_topology_resilience(
                topology_name, fault_results
            )
            
            resilience_scores[topology_name] = evaluation["resilience_score"]
            topology_details[topology_name] = evaluation
        
        # Rank topologies by resilience score
        ranked_topologies = sorted(
            resilience_scores.items(), 
            key=lambda x: x[1], 
            reverse=True
        )
        
        # Calculate statistical significance if enough data
        significance_analysis = self.calculate_statistical_significance(topology_results)
        
        return {
            "ranked_topologies": ranked_topologies,
            "topology_details": topology_details,
            "best_topology": ranked_topologies[0][0] if ranked_topologies else None,
            "resilience_scores": resilience_scores,
            "significance_analysis": significance_analysis,
            "recommendations": self.generate_topology_recommendations(ranked_topologies, topology_details)
        }
    
    def generate_topology_recommendations(self, ranked_topologies: List[Tuple[str, float]], 
                                        details: Dict[str, Dict]) -> List[str]:
        """Generate recommendations based on topology comparison"""
        
        recommendations = []
        
        if not ranked_topologies:
            return ["No topology data available for recommendation"]
        
        best_topology = ranked_topologies[0][0]
        best_details = details[best_topology]
        
        recommendations.append(f"Recommended for production: {best_topology} (resilience score: {best_details['resilience_score']:.3f})")
        
        # Check for specific strengths
        if best_details["normalized_metrics"]["bad_merge_rate"] > 0.9:
            recommendations.append(f"{best_topology} shows excellent bad merge prevention")
        
        if best_details["normalized_metrics"]["avg_cascade_length"] > 0.9:
            recommendations.append(f"{best_topology} provides strong cascade containment")
        
        # Check for second-best options for experimentation
        if len(ranked_topologies) > 1:
            second_best = ranked_topologies[1][0]
            recommendations.append(f"Consider {second_best} for experimentation (score: {ranked_topologies[1][1]:.3f})")
        
        return recommendations
```

---

## 🔗 **STRUCTURAL CAUSAL MODEL FOR MULTI-AGENT INFLUENCE**

### **4. Building a Structural Causal Model (SCM)**

#### **Causal Variable Definition**
```python
class MultiAgentSCM:
    def __init__(self):
        # Define causal variables (nodes in the DAG)
        self.variables = {
            # Agent decision variables
            "P": "planner_spec_quality",      # Planner spec quality/type
            "I": "implementer_diff_quality",    # Implementer diff quality
            "T": "test_coverage_result",         # Test coverage/result
            "R": "review_decision",              # Review decision
            
            # Context variables (confounders)
            "C": "task_complexity",              # Task complexity
            "A": "repo_age",                    # Repository age
            "S": "skill_level",                  # Agent skill level
            
            # Outcome variable
            "Y": "final_outcome"                 # Final outcome (good merge, rollback, etc.)
        }
        
        # Define causal structure (edges)
        self.causal_edges = [
            ("P", "I"),  # Planner influences implementer
            ("P", "T"),  # Planner influences tests
            ("I", "R"),  # Implementer influences review
            ("I", "Y"),  # Implementer influences outcome
            ("T", "R"),  # Tests influence review
            ("T", "Y"),  # Tests influence outcome
            ("R", "Y"),  # Review influences outcome
            
            # Context influences
            ("C", "P"), ("C", "I"), ("C", "T"),  # Task complexity affects all
            ("A", "I"), ("A", "T"),              # Repo age affects implementation and tests
            ("S", "P"), ("S", "I"), ("S", "R")   # Skill level affects decisions
        ]
        
        # Structural equations (to be fitted from data)
        self.structural_equations = {}
    
    def fit_structural_equations(self, observational_data: List[Dict]) -> Dict[str, Any]:
        """Fit structural equations from observational data"""
        
        # Convert observational data to tabular format
        df = self.convert_to_dataframe(observational_data)
        
        # Fit each structural equation
        fitted_equations = {}
        
        # P = f_P(C, S, U_P)
        fitted_equations["P"] = self.fit_linear_regression(
            df, "P", ["C", "S"]
        )
        
        # I = f_I(P, C, A, S, U_I)
        fitted_equations["I"] = self.fit_linear_regression(
            df, "I", ["P", "C", "A", "S"]
        )
        
        # T = f_T(P, C, A, S, U_T)
        fitted_equations["T"] = self.fit_linear_regression(
            df, "T", ["P", "C", "A", "S"]
        )
        
        # R = f_R(I, T, S, U_R)
        fitted_equations["R"] = self.fit_linear_regression(
            df, "R", ["I", "T", "S"]
        )
        
        # Y = f_Y(I, T, R, C, U_Y)
        fitted_equations["Y"] = self.fit_linear_regression(
            df, "Y", ["I", "T", "R", "C"]
        )
        
        self.structural_equations = fitted_equations
        
        return {
            "fitted_equations": fitted_equations,
            "model_fit_metrics": self.calculate_model_fit_metrics(fitted_equations, df),
            "causal_assumptions": self.validate_causal_assumptions(df)
        }
    
    def estimate_causal_effect(self, treatment_var: str, treatment_value: float,
                               control_value: float) -> Dict[str, Any]:
        """Estimate causal effect using do-calculus"""
        
        if treatment_var not in self.variables:
            raise ValueError(f"Unknown treatment variable: {treatment_var}")
        
        # Calculate E[Y | do(treatment_var = treatment_value)] - E[Y | do(treatment_var = control_value)]
        treatment_effect = self.calculate_do_effect(treatment_var, treatment_value, control_value)
        
        return {
            "treatment_variable": treatment_var,
            "treatment_value": treatment_value,
            "control_value": control_value,
            "causal_effect": treatment_effect,
            "confidence_interval": self.calculate_confidence_interval(treatment_var, treatment_value, control_value),
            "interpretation": self.interpret_causal_effect(treatment_var, treatment_effect)
        }
```

#### **Causal Effect Estimation Algorithms**
```python
class CausalEffectEstimator:
    def __init__(self):
        self.estimation_methods = ["covariate_adjusted", "propensity_score", "instrumental_variables"]
    
    def estimate_agent_causal_effects(self, task_data: List[Dict], 
                                     upstream_agent: str, downstream_outcome: str,
                                     confounders: List[str]) -> Dict[str, Any]:
        """Apply standard causal-effect estimators to agent variables"""
        
        # Convert to tabular data
        df = self.convert_to_dataframe(task_data)
        
        results = {}
        
        # Method 1: Covariate-adjusted regression
        results["covariate_adjusted"] = self.covariate_adjusted_regression(
            df, upstream_agent, downstream_outcome, confounders
        )
        
        # Method 2: Propensity score matching
        results["propensity_score"] = self.propensity_score_matching(
            df, upstream_agent, downstream_outcome, confounders
        )
        
        # Method 3: Instrumental variables (if available)
        if self.has_instrument(df, upstream_agent):
            results["instrumental_variables"] = self.instrumental_variables(
                df, upstream_agent, downstream_outcome, confounders
            )
        
        # Synthesize results
        synthesis = self.synthesize_estimation_results(results)
        
        return {
            "upstream_agent": upstream_agent,
            "downstream_outcome": downstream_outcome,
            "confounders": confounders,
            "estimation_results": results,
            "synthesis": synthesis,
            "recommendations": self.generate_causal_recommendations(synthesis)
        }
    
    def covariate_adjusted_regression(self, df, treatment: str, outcome: str, 
                                     confounders: List[str]) -> Dict[str, Any]:
        """Covariate-adjusted regression: Y = β₀ + β₁A + β₂confounders + ε"""
        
        import statsmodels.api as sm
        
        # Prepare data
        X = df[[treatment] + confounders]
        X = sm.add_constant(X)
        y = df[outcome]
        
        # Fit model
        model = sm.OLS(y, X).fit()
        
        # Extract treatment effect
        treatment_effect = model.params[treatment]
        treatment_se = model.bse[treatment]
        treatment_pvalue = model.pvalues[treatment]
        
        return {
            "method": "covariate_adjusted_regression",
            "treatment_effect": treatment_effect,
            "standard_error": treatment_se,
            "p_value": treatment_pvalue,
            "confidence_interval": model.conf_int().loc[treatment].tolist(),
            "model_summary": str(model.summary()),
            "r_squared": model.rsquared
        }
    
    def propensity_score_matching(self, df, treatment: str, outcome: str, 
                                   confounders: List[str]) -> Dict[str, Any]:
        """Propensity score matching for causal effect estimation"""
        
        from sklearn.linear_model import LogisticRegression
        from sklearn.neighbors import NearestNeighbors
        
        # Calculate propensity scores
        X_confounders = df[confounders]
        treatment_binary = (df[treatment] > df[treatment].median()).astype(int)
        
        propensity_model = LogisticRegression(random_state=42)
        propensity_model.fit(X_confounders, treatment_binary)
        propensity_scores = propensity_model.predict_proba(X_confounders)[:, 1]
        
        # Match treated and control units
        treated_indices = df[treatment_binary == 1].index
        control_indices = df[treatment_binary == 0].index
        
        # Find matches using nearest neighbors on propensity scores
        nn = NearestNeighbors(n_neighbors=1)
        nn.fit(propensity_scores[control_indices].values.reshape(-1, 1))
        
        matched_pairs = []
        for treated_idx in treated_indices:
            distances, indices = nn.kneighbors(
                [[propensity_scores[treated_idx]]], 
                return_distance=True
            )
            matched_control_idx = control_indices[indices[0][0]]
            matched_pairs.append((treated_idx, matched_control_idx))
        
        # Calculate average treatment effect on treated (ATT)
        treated_outcomes = df.loc[[pair[0] for pair in matched_pairs], outcome]
        control_outcomes = df.loc[[pair[1] for pair in matched_pairs], outcome]
        
        att = (treated_outcomes - control_outcomes).mean()
        
        return {
            "method": "propensity_score_matching",
            "average_treatment_effect_treated": att,
            "matched_pairs": len(matched_pairs),
            "propensity_model_score": propensity_model.score(X_confounders, treatment_binary),
            "balance_check": self.check_propensity_balance(df, matched_pairs, confounders)
        }
```

---

## 🧮 **MATHEMATICAL CASCADE FAILURE METRICS**

### **1. Quantitative Metrics for Cascading Failure Likelihood**

#### **Cascade Size and Depth Analysis**
```python
class CascadeMathAnalyzer:
    def __init__(self):
        self.cascade_metrics = {}
    
    def calculate_cascade_metrics(self, failure_incidents: List[Dict]) -> Dict[str, Any]:
        """Mathematical analysis of cascade propagation over agent/tool graph"""
        
        cascade_sizes = []
        cascade_depths = []
        branching_factors = []
        
        for incident in failure_incidents:
            # Build causal graph from trace
            causal_graph = self.build_causal_graph(incident["trace_events"])
            
            # Calculate cascade size: C_size = number of distinct agents/tools with errors
            c_size = len(causal_graph["error_nodes"])
            cascade_sizes.append(c_size)
            
            # Calculate cascade depth: C_depth = longest failure path length
            c_depth = self.calculate_longest_path(causal_graph)
            cascade_depths.append(c_depth)
            
            # Calculate branching factor: average downstream failures per node
            b = self.calculate_branching_factor(causal_graph)
            branching_factors.append(b)
        
        # Statistical analysis
        return {
            "cascade_size_stats": {
                "mean": np.mean(cascade_sizes),
                "median": np.median(cascade_sizes),
                "p95": np.percentile(cascade_sizes, 95),
                "max": max(cascade_sizes),
                "distribution": cascade_sizes
            },
            "cascade_depth_stats": {
                "mean": np.mean(cascade_depths),
                "median": np.median(cascade_depths),
                "p95": np.percentile(cascade_depths, 95),
                "max": max(cascade_depths),
                "distribution": cascade_depths
            },
            "branching_factor_stats": {
                "mean": np.mean(branching_factors),
                "amplification_rate": len([b for b in branching_factors if b > 1]) / len(branching_factors),
                "distribution": branching_factors
            },
            "cascade_risk_index": self.calculate_cascade_risk_index(
                cascade_sizes, cascade_depths, branching_factors
            )
        }
    
    def calculate_branching_factor(self, causal_graph: Dict) -> float:
        """Calculate average downstream failures per failure node"""
        
        branching_counts = []
        
        for node in causal_graph["error_nodes"]:
            downstream_count = len(causal_graph["adjacency_matrix"].get(node, []))
            branching_counts.append(downstream_count)
        
        return np.mean(branching_counts) if branching_counts else 0
    
    def calculate_cascade_risk_index(self, sizes: List[float], depths: List[float], 
                                    branching: List[float]) -> float:
        """Weighted combination of normalized cascade metrics"""
        
        # Normalize metrics to 0-1 scale
        max_size = max(sizes) if sizes else 1
        max_depth = max(depths) if depths else 1
        max_branching = max(branching) if branching else 1
        
        normalized_sizes = [s / max_size for s in sizes]
        normalized_depths = [d / max_depth for d in depths]
        normalized_branching = [b / max_branching for b in branching]
        
        # Risk weights (higher = more risky)
        w_size = 0.3
        w_depth = 0.3
        w_branching = 0.4
        
        # Calculate risk index (0 = low risk, 1 = high risk)
        risk_scores = [
            w_size * ns + w_depth * nd + w_branching * nb
            for ns, nd, nb in zip(normalized_sizes, normalized_depths, normalized_branching)
        ]
        
        return np.mean(risk_scores)
```

#### **Retry Cascade Index**
```python
class RetryCascadeAnalyzer:
    def __init__(self):
        self.retry_window_seconds = 60  # Window W for retry counting
    
    def calculate_retry_cascade_index(self, failure_incidents: List[Dict]) -> Dict[str, Any]:
        """Calculate R = total_retries / initial_failures for cascade risk"""
        
        retry_indices = []
        cascade_details = []
        
        for incident in failure_incidents:
            initial_failures = self.extract_initial_failures(incident["trace_events"])
            retry_events = self.extract_retry_events(incident["trace_events"])
            
            # Count retries within window W for each initial failure
            total_retries = 0
            
            for initial_failure in initial_failures:
                window_retries = self.count_retries_in_window(
                    retry_events, initial_failure, self.retry_window_seconds
                )
                total_retries += window_retries
            
            # Calculate retry cascade index: R = total_retries / initial_failures
            r_index = total_retries / len(initial_failures) if initial_failures else 0
            retry_indices.append(r_index)
            
            cascade_details.append({
                "incident_id": incident["incident_id"],
                "retry_cascade_index": r_index,
                "initial_failures": len(initial_failures),
                "total_retries": total_retries,
                "retry_storm_indicated": r_index > 3.0  # High retry cascade threshold
            })
        
        return {
            "mean_retry_cascade_index": np.mean(retry_indices),
            "max_retry_cascade_index": max(retry_indices),
            "retry_storm_rate": len([r for r in retry_indices if r > 3.0]) / len(retry_indices),
            "cascade_details": cascade_details,
            "retry_driven_cascade_risk": np.mean(retry_indices) > 2.0
        }
```

#### **Containment Ratio**
```python
class ContainmentRatioCalculator:
    def __init__(self):
        self.local_failure_threshold = 1  # C_size > 1 indicates non-local
    
    def calculate_containment_ratio(self, failure_incidents: List[Dict]) -> Dict[str, float]:
        """C_contain = 1 - (# incidents with C_size > 1) / total_incidents"""
        
        total_incidents = len(failure_incidents)
        multi_agent_incidents = 0
        
        cascade_sizes = []
        
        for incident in failure_incidents:
            # Count distinct agents/tools with errors
            error_agents = set()
            error_tools = set()
            
            for event in incident["trace_events"]:
                if event.get("is_error", False):
                    error_agents.add(event.get("agent_id"))
                    error_tools.add(event.get("tool_name"))
            
            cascade_size = len(error_agents) + len(error_tools)
            cascade_sizes.append(cascade_size)
            
            if cascade_size > self.local_failure_threshold:
                multi_agent_incidents += 1
        
        containment_ratio = 1 - (multi_agent_incidents / total_incidents) if total_incidents > 0 else 0
        
        return {
            "containment_ratio": containment_ratio,
            "total_incidents": total_incidents,
            "multi_agent_incidents": multi_agent_incidents,
            "local_failure_rate": (total_incidents - multi_agent_incidents) / total_incidents if total_incidents > 0 else 0,
            "cascade_size_distribution": self.calculate_size_distribution(cascade_sizes)
        }
```

---

## 📐 **PAIRWISE AGENT MISALIGNMENT (MATHEMATICAL)**

### **2. Mathematical Misalignment Measures**

#### **Vector-Based Misalignment Analysis**
```python
class VectorMisalignmentAnalyzer:
    def __init__(self):
        self.embedding_model = None  # Load appropriate embedding model
        self.misalignment_cache = {}
    
    def calculate_cosine_misalignment(self, agent_a_decisions: List[Dict], 
                                     agent_b_decisions: List[Dict]) -> Dict[str, Any]:
        """m_cos(A,B) = 1 - cos(v_A, v_B) for intent/decision vectors"""
        
        misalignment_scores = []
        task_pairs = []
        
        # Match decisions by task_id
        for decision_a in agent_a_decisions:
            matching_b = self.find_matching_decision(decision_a["task_id"], agent_b_decisions)
            
            if matching_b:
                # Extract or create embeddings
                v_a = self.get_decision_embedding(decision_a)
                v_b = self.get_decision_embedding(matching_b)
                
                # Calculate cosine similarity
                cosine_sim = np.dot(v_a, v_b) / (np.linalg.norm(v_a) * np.linalg.norm(v_b))
                misalignment = 1 - cosine_sim  # m_cos(A,B)
                
                misalignment_scores.append(misalignment)
                task_pairs.append({
                    "task_id": decision_a["task_id"],
                    "misalignment": misalignment,
                    "cosine_similarity": cosine_sim,
                    "agent_a_decision": decision_a["decision_type"],
                    "agent_b_decision": matching_b["decision_type"]
                })
        
        return {
            "mean_cosine_misalignment": np.mean(misalignment_scores),
            "misalignment_std": np.std(misalignment_scores),
            "max_misalignment": max(misalignment_scores) if misalignment_scores else 0,
            "perfect_alignment_rate": len([m for m in misalignment_scores if m < 0.1]) / len(misalignment_scores) if misalignment_scores else 0,
            "task_pairs": task_pairs,
            "misalignment_distribution": self.calculate_misalignment_distribution(misalignment_scores)
        }
```

#### **Policy Disagreement Rate**
```python
class PolicyDisagreementAnalyzer:
    def __init__(self):
        self.discrete_decisions = ["fix_vs_wontfix", "refactor_vs_patch", "approve_vs_reject"]
    
    def calculate_policy_disagreement_rate(self, agent_a_decisions: List[Dict], 
                                          agent_b_decisions: List[Dict]) -> Dict[str, Any]:
        """m_disc(A,B) = # tasks where A and B disagree / total shared tasks"""
        
        disagreement_rates = {}
        shared_tasks = 0
        
        # Find shared tasks
        task_ids_a = set(d["task_id"] for d in agent_a_decisions)
        task_ids_b = set(d["task_id"] for d in agent_b_decisions)
        shared_task_ids = task_ids_a.intersection(task_ids_b)
        shared_tasks = len(shared_task_ids)
        
        if shared_tasks == 0:
            return {"error": "No shared tasks found for comparison"}
        
        # Calculate disagreement rate for each decision type
        for decision_type in self.discrete_decisions:
            disagreements = 0
            comparable_tasks = 0
            
            for task_id in shared_task_ids:
                decision_a = self.find_decision_by_type_and_task(agent_a_decisions, task_id, decision_type)
                decision_b = self.find_decision_by_type_and_task(agent_b_decisions, task_id, decision_type)
                
                if decision_a and decision_b:
                    comparable_tasks += 1
                    
                    if decision_a["decision"] != decision_b["decision"]:
                        disagreements += 1
            
            disagreement_rate = disagreements / comparable_tasks if comparable_tasks > 0 else 0
            disagreement_rates[decision_type] = {
                "disagreement_rate": disagreement_rate,
                "comparable_tasks": comparable_tasks,
                "disagreements": disagreements
            }
        
        # Overall disagreement rate
        overall_disagreements = sum(rate["disagreements"] for rate in disagreement_rates.values())
        overall_comparable = sum(rate["comparable_tasks"] for rate in disagreement_rates.values())
        overall_rate = overall_disagreements / overall_comparable if overall_comparable > 0 else 0
        
        return {
            "overall_policy_disagreement_rate": overall_rate,
            "decision_type_disagreements": disagreement_rates,
            "shared_tasks": shared_tasks,
            "high_disagreement_threshold_met": overall_rate > 0.3
        }
```

#### **Outcome-Conditioned Misalignment**
```python
class OutcomeConditionedMisalignment:
    def __init__(self):
        self.outcome_categories = ["success", "failure", "rollback"]
    
    def calculate_outcome_conditioned_misalignment(self, 
                                                   task_outcomes: List[Dict],
                                                   misalignment_scores: List[float]) -> Dict[str, Any]:
        """m_fail(A,B) = E[m(A,B) | failure] - E[m(A,B) | success]"""
        
        # Group misalignment scores by outcome
        outcome_misalignments = {outcome: [] for outcome in self.outcome_categories}
        
        for task_outcome, misalignment in zip(task_outcomes, misalignment_scores):
            outcome = task_outcome["outcome_category"]
            if outcome in outcome_misalignments:
                outcome_misalignments[outcome].append(misalignment)
        
        # Calculate conditional expectations
        conditional_means = {}
        for outcome, scores in outcome_misalignments.items():
            conditional_means[outcome] = np.mean(scores) if scores else 0
        
        # Calculate outcome-conditioned misalignment
        success_mean = conditional_means.get("success", 0)
        failure_mean = conditional_means.get("failure", 0)
        rollback_mean = conditional_means.get("rollback", 0)
        
        m_fail = failure_mean - success_mean
        m_rollback = rollback_mean - success_mean
        
        return {
            "conditional_misalignment_by_outcome": conditional_means,
            "outcome_conditioned_misalignment": {
                "failure_vs_success": m_fail,
                "rollback_vs_success": m_rollback,
                "interpretation": self.interpret_outcome_misalignment(m_fail, m_rollback)
            },
            "misalignment_correlates_with_failure": m_fail > 0.1,
            "sample_sizes": {outcome: len(scores) for outcome, scores in outcome_misalignments.items()}
        }
```

---

## 🏗️ **MATHEMATICAL RESILIENCE SCORE FORMULA**

### **3. Resilience Score Formula for Topology**

#### **Normalized Resilience Calculation**
```python
class MathematicalResilienceCalculator:
    def __init__(self):
        # MERID priority weights (emphasize bad merges and cascades)
        self.weights = {
            "success_rate": 0.2,
            "bad_merge_rate": 0.4,
            "cascade_size": 0.3,
            "coordination_overhead": 0.1
        }
        
        # Maximum values for normalization
        self.max_values = {
            "success_rate": 1.0,
            "bad_merge_rate": 0.5,
            "cascade_size": 10.0,
            "coordination_overhead": 5.0
        }
        
        # Verify weights sum to 1
        assert abs(sum(self.weights.values()) - 1.0) < 1e-6, "Weights must sum to 1"
    
    def calculate_resilience_score(self, topology_results: Dict[str, Any], 
                                   baseline_results: Dict[str, Any]) -> Dict[str, float]:
        """Calculate Resilience(T) = w_S*S*_T + w_B*B*_T + w_L*L*_T + w_O*O*_T"""
        
        # Extract metrics
        S_T = topology_results["success_rate"] / baseline_results["success_rate"]
        B_T = topology_results["bad_merge_rate"]
        L_T = topology_results["mean_cascade_size"]
        O_T = topology_results["coordination_overhead_factor"]
        
        # Normalize to [0,1] where higher is better
        S_star_T = np.clip(S_T, 0, 1)  # Success rate (already higher=better)
        B_star_T = 1 - np.clip(B_T / self.max_values["bad_merge_rate"], 0, 1)  # Lower is better
        L_star_T = 1 - np.clip((L_T - 1) / (self.max_values["cascade_size"] - 1), 0, 1)  # Lower is better
        O_star_T = 1 - np.clip(O_T / self.max_values["coordination_overhead"], 0, 1)  # Lower is better
        
        # Calculate weighted resilience score
        resilience_score = (
            self.weights["success_rate"] * S_star_T +
            self.weights["bad_merge_rate"] * B_star_T +
            self.weights["cascade_size"] * L_star_T +
            self.weights["coordination_overhead"] * O_star_T
        )
        
        return {
            "resilience_score": resilience_score,
            "normalized_components": {
                "success_rate_normalized": S_star_T,
                "bad_merge_rate_normalized": B_star_T,
                "cascade_size_normalized": L_star_T,
                "coordination_overhead_normalized": O_star_T
            },
            "raw_metrics": {
                "success_rate_ratio": S_T,
                "bad_merge_rate": B_T,
                "cascade_size": L_T,
                "coordination_overhead_factor": O_T
            },
            "component_contributions": {
                "success_rate_contribution": self.weights["success_rate"] * S_star_T,
                "bad_merge_rate_contribution": self.weights["bad_merge_rate"] * B_star_T,
                "cascade_size_contribution": self.weights["cascade_size"] * L_star_T,
                "coordination_overhead_contribution": self.weights["coordination_overhead"] * O_star_T
            }
        }
```

---

## 🔬 **CLOSED-FORM RESILIENCE ANALYSIS**

### **1. Closed-Form Resilience Score for Ring vs Mesh**

#### **Network Model and Cascade Expectations**
```python
class TopologyResilienceAnalyzer:
    def __init__(self):
        self.topology_params = {
            "ring": {"degree": 2, "name": "ring"},
            "mesh": {"degree": None, "name": "mesh"},  # Will be set empirically
            "star": {"degree": None, "name": "star"},  # Central hub degree = N-1
        }
    
    def calculate_expected_cascade_size(self, topology: str, N: int, 
                                        q: float, degree: int = None) -> float:
        """Calculate E[C] = 1 + (d*q)/(1 - d*q) for given topology"""
        
        if topology == "ring":
            d = 2  # Ring degree is always 2
        elif topology == "mesh":
            d = degree if degree else (N - 1)  # Fully connected mesh
        elif topology == "star":
            d = N - 1  # Central hub connected to all others
        else:
            raise ValueError(f"Unknown topology: {topology}")
        
        # Check stability condition: d*q < 1
        if d * q >= 1:
            return float('inf')  # Unbounded cascade expected
        
        # Expected cascade size formula
        expected_cascade = 1 + (d * q) / (1 - d * q)
        
        return expected_cascade
    
    def calculate_resilience_score(self, topology: str, N: int, 
                                   q: float, degree: int = None) -> float:
        """Calculate R = 1 - d*q (clamped to [0,1])"""
        
        if topology == "ring":
            d = 2
        elif topology == "mesh":
            d = degree if degree else (N - 1)
        elif topology == "star":
            d = N - 1
        else:
            raise ValueError(f"Unknown topology: {topology}")
        
        # Resilience formula: R = 1 - d*q
        resilience = 1 - d * q
        
        # Clamp to [0,1]
        return max(0.0, min(1.0, resilience))
    
    def compare_topology_resilience(self, N: int, q_ring: float, q_mesh: float, 
                                   mesh_degree: int = None) -> Dict[str, Any]:
        """Compare ring vs mesh resilience under empirical propagation probabilities"""
        
        results = {}
        
        # Ring calculations
        ring_cascade = self.calculate_expected_cascade_size("ring", N, q_ring)
        ring_resilience = self.calculate_resilience_score("ring", N, q_ring)
        
        results["ring"] = {
            "expected_cascade_size": ring_cascade,
            "resilience_score": ring_resilience,
            "propagation_prob": q_ring,
            "stability_condition": "stable" if 2 * q_ring < 1 else "unstable"
        }
        
        # Mesh calculations
        mesh_cascade = self.calculate_expected_cascade_size("mesh", N, q_mesh, mesh_degree)
        mesh_resilience = self.calculate_resilience_score("mesh", N, q_mesh, mesh_degree)
        
        results["mesh"] = {
            "expected_cascade_size": mesh_cascade,
            "resilience_score": mesh_resilience,
            "propagation_prob": q_mesh,
            "degree": mesh_degree if mesh_degree else (N - 1),
            "stability_condition": "stable" if (mesh_degree or (N - 1)) * q_mesh < 1 else "unstable"
        }
        
        # Comparison
        results["comparison"] = {
            "more_resilient": "ring" if ring_resilience > mesh_resilience else "mesh",
            "resilience_difference": abs(ring_resilience - mesh_resilience),
            "cascade_size_difference": abs(ring_cascade - mesh_cascade),
            "interpretation": self.interpret_resilience_comparison(results)
        }
        
        return results
    
    def interpret_resilience_comparison(self, results: Dict[str, Any]) -> str:
        """Interpret the resilience comparison results"""
        
        ring_resilience = results["ring"]["resilience_score"]
        mesh_resilience = results["mesh"]["resilience_score"]
        
        if ring_resilience > mesh_resilience + 0.1:
            return "Ring significantly more resilient to cascades (lower effective branching factor)"
        elif mesh_resilience > ring_resilience + 0.1:
            return "Mesh more resilient (better node removal tolerance, but higher cascade risk)"
        else:
            return "Similar resilience levels - topology choice depends on other factors"
```

---

## 📐 **VARIANCE-ADJUSTED MISALIGNMENT METRIC**

### **2. Pairwise Misalignment: Cosine + Variance**

#### **Whitened Cosine Distance Calculation**
```python
class VarianceAdjustedMisalignment:
    def __init__(self):
        self.covariance_matrix = None
        self.whitening_matrix = None
        self.misalignment_cache = {}
    
    def fit_covariance_matrix(self, embedding_vectors: List[np.ndarray]) -> None:
        """Estimate covariance matrix Σ from historical embeddings"""
        
        # Stack all vectors
        X = np.vstack(embedding_vectors)
        
        # Calculate covariance matrix
        self.covariance_matrix = np.cov(X.T)
        
        # Calculate whitening matrix Σ^(-1/2)
        eigenvals, eigenvecs = np.linalg.eigh(self.covariance_matrix)
        
        # Add small regularization to avoid numerical issues
        eigenvals = np.maximum(eigenvals, 1e-8)
        
        # Whitening matrix: Σ^(-1/2) = E * Λ^(-1/2) * E^T
        whitening_diag = np.diag(1.0 / np.sqrt(eigenvals))
        self.whitening_matrix = eigenvecs @ whitening_diag @ eigenvecs.T
    
    def whiten_vector(self, v: np.ndarray) -> np.ndarray:
        """Apply whitening transformation: ṽ = Σ^(-1/2) * v"""
        
        if self.whitening_matrix is None:
            raise ValueError("Covariance matrix not fitted. Call fit_covariance_matrix first.")
        
        return self.whitening_matrix @ v
    
    def calculate_variance_adjusted_cosine(self, v_a: np.ndarray, v_b: np.ndarray) -> float:
        """Calculate d_VAcos(A,B) = 1 - (ṽ_A^T ṽ_B) / (||ṽ_A|| ||ṽ_B||)"""
        
        # Whiten both vectors
        v_a_whitened = self.whiten_vector(v_a)
        v_b_whitened = self.whiten_vector(v_b)
        
        # Calculate cosine similarity in whitened space
        cosine_sim = np.dot(v_a_whitened, v_b_whitened) / (
            np.linalg.norm(v_a_whitened) * np.linalg.norm(v_b_whitened)
        )
        
        # Convert to distance
        va_cos_distance = 1 - cosine_sim
        
        return va_cos_distance
    
    def calculate_misalignment_statistics(self, agent_pairs: List[Tuple[str, str]], 
                                          task_embeddings: Dict[str, List[np.ndarray]]) -> Dict[str, Any]:
        """Calculate μ_AB and σ²_AB for agent pairs over shared tasks"""
        
        results = {}
        
        for agent_a, agent_b in agent_pairs:
            # Find shared tasks
            tasks_a = set(task_embeddings.get(agent_a, {}).keys())
            tasks_b = set(task_embeddings.get(agent_b, {}).keys())
            shared_tasks = tasks_a.intersection(tasks_b)
            
            if not shared_tasks:
                results[f"{agent_a}_{agent_b}"] = {
                    "error": "No shared tasks found",
                    "shared_tasks": 0
                }
                continue
            
            # Calculate VAcos distances for each shared task
            va_distances = []
            
            for task_id in shared_tasks:
                v_a = task_embeddings[agent_a][task_id]
                v_b = task_embeddings[agent_b][task_id]
                
                va_distance = self.calculate_variance_adjusted_cosine(v_a, v_b)
                va_distances.append(va_distance)
            
            # Calculate statistics
            va_distances = np.array(va_distances)
            mu_ab = np.mean(va_distances)
            sigma_ab = np.std(va_distances)
            
            results[f"{agent_a}_{agent_b}"] = {
                "mean_misalignment": mu_ab,
                "std_misalignment": sigma_ab,
                "variance_misalignment": sigma_ab ** 2,
                "shared_tasks": len(shared_tasks),
                "misalignment_instability": sigma_ab,  # Higher σ indicates instability
                "task_distances": va_distances.tolist(),
                "interpretation": self.interpret_misalignment(mu_ab, sigma_ab)
            }
        
        return results
    
    def interpret_misalignment(self, mu: float, sigma: float) -> str:
        """Interpret misalignment statistics"""
        
        if mu < 0.1 and sigma < 0.1:
            return "Highly aligned and stable"
        elif mu < 0.3 and sigma < 0.2:
            return "Moderately aligned with reasonable stability"
        elif mu > 0.5 and sigma > 0.3:
            return "Poorly aligned and highly unstable"
        elif mu > 0.5 and sigma < 0.2:
            return "Consistently misaligned (systematic disagreement)"
        elif mu < 0.3 and sigma > 0.3:
            return "Generally aligned but highly unstable (inconsistent behavior)"
        else:
            return "Moderate misalignment with some instability"
```

---

## ⏱️ **TIME-DELAYED CASCADE SIMULATION**

### **3. Simulating Cascading Failures with Time-Delayed Communications**

#### **Discrete-Time Cascade Simulation**
```python
class TimeDelayedCascadeSimulator:
    def __init__(self):
        self.agents = {}
        self.network_graph = {}
        self.time_step = 0
        self.event_log = []
        
        # Simulation parameters
        self.message_delay_distribution = "geometric"  # or "poisson"
        self.base_failure_prob = 0.1
        self.propagation_prob = 0.2
        self.resource_capacity = 10
        self.max_retries = 3
        self.backoff_base = 2.0
        self.jitter_factor = 0.1
    
    def initialize_network(self, network_config: Dict[str, Any]) -> None:
        """Initialize agents and network topology"""
        
        # Create agents
        for agent_id, agent_config in network_config["agents"].items():
            self.agents[agent_id] = Agent(
                id=agent_id,
                state="healthy",
                position=agent_config["position"],
                message_queue=[],
                tool_call_queue=[],
                retry_counter={}
            )
        
        # Build network graph
        self.network_graph = network_config["topology"]
    
    def simulate_step(self) -> Dict[str, Any]:
        """Execute one discrete time step of the simulation"""
        
        step_events = []
        
        # Process message deliveries
        delivered_messages = self.process_message_deliveries()
        
        # Process tool calls
        tool_results = self.process_tool_calls()
        
        # Process state transitions
        state_transitions = self.process_state_transitions()
        
        # Check for new failures and propagations
        new_failures = self.check_failure_propagation()
        
        # Schedule retries
        retry_events = self.schedule_retries()
        
        # Log events
        step_events = {
            "time_step": self.time_step,
            "delivered_messages": delivered_messages,
            "tool_results": tool_results,
            "state_transitions": state_transitions,
            "new_failures": new_failures,
            "retry_events": retry_events,
            "system_load": self.calculate_system_load()
        }
        
        self.event_log.append(step_events)
        self.time_step += 1
        
        return step_events
    
    def process_message_deliveries(self) -> List[Dict]:
        """Process messages that arrive at current time step"""
        
        delivered = []
        
        for agent_id, agent in self.agents.items():
            messages_to_deliver = []
            
            # Check message queue for deliveries due now
            for msg in agent.message_queue:
                if msg["delivery_time"] == self.time_step:
                    messages_to_deliver.append(msg)
            
            for msg in messages_to_deliver:
                # Process message based on sender's state
                sender_state = self.agents[msg["sender_id"]].state
                
                if sender_state in ["failed", "degraded"]:
                    # Message from failed/degraded agent can cause failure
                    if random.random() < self.propagation_prob:
                        agent.state = "failed"
                        delivered.append({
                            "type": "failure_propagation",
                            "receiver_id": agent_id,
                            "sender_id": msg["sender_id"],
                            "sender_state": sender_state,
                            "time": self.time_step
                        })
                
                # Remove delivered message from queue
                agent.message_queue.remove(msg)
        
        return delivered
    
    def process_tool_calls(self) -> List[Dict]:
        """Process tool calls with load-dependent failure rates"""
        
        results = []
        current_load = self.calculate_system_load()
        
        # Failure probability increases with load
        load_factor = current_load / self.resource_capacity
        failure_prob = self.base_failure_prob * (1 + load_factor ** 2)
        
        for agent_id, agent in self.agents.items():
            calls_to_process = []
            
            # Find calls ready to process
            for call in agent.tool_call_queue:
                if call["execution_time"] == self.time_step:
                    calls_to_process.append(call)
            
            for call in calls_to_process:
                if random.random() < failure_prob:
                    # Tool call failed
                    call["retry_count"] += 1
                    
                    if call["retry_count"] <= self.max_retries:
                        # Schedule retry with exponential backoff + jitter
                        backoff_delay = self.calculate_backoff_delay(call["retry_count"])
                        retry_time = self.time_step + backoff_delay
                        
                        call["execution_time"] = retry_time
                        
                        results.append({
                            "type": "tool_failure_retry",
                            "agent_id": agent_id,
                            "tool_name": call["tool_name"],
                            "retry_count": call["retry_count"],
                            "retry_time": retry_time,
                            "load_factor": load_factor
                        })
                    else:
                        # Max retries exceeded
                        agent.state = "degraded"
                        results.append({
                            "type": "tool_failure_max_retries",
                            "agent_id": agent_id,
                            "tool_name": call["tool_name"],
                            "final_failure": True
                        })
                        
                        # Remove failed call from queue
                        agent.tool_call_queue.remove(call)
                else:
                    # Tool call succeeded
                    results.append({
                        "type": "tool_success",
                        "agent_id": agent_id,
                        "tool_name": call["tool_name"],
                        "load_factor": load_factor
                    })
                    
                    # Remove successful call from queue
                    agent.tool_call_queue.remove(call)
        
        return results
    
    def calculate_backoff_delay(self, retry_count: int) -> int:
        """Calculate exponential backoff with jitter"""
        
        # Exponential backoff: base * (2^retry_count)
        base_delay = self.backoff_base ** retry_count
        
        # Add jitter: ±jitter_factor * base_delay
        jitter = random.uniform(-self.jitter_factor, self.jitter_factor) * base_delay
        
        return max(1, int(base_delay + jitter))
    
    def calculate_system_load(self) -> int:
        """Calculate current system load (in-flight tool calls)"""
        
        total_load = 0
        
        for agent in self.agents.values():
            total_load += len(agent.tool_call_queue)
        
        return total_load
    
    def run_monte_carlo_simulation(self, initial_fault: str, 
                                   max_steps: int = 100) -> Dict[str, Any]:
        """Run Monte Carlo simulation with initial fault"""
        
        # Inject initial fault
        self.agents[initial_fault].state = "failed"
        
        cascade_metrics = {
            "cascade_size": 1,  # Start with initial fault
            "cascade_depth": 0,
            "time_to_quiescence": None,
            "total_retries": 0,
            "peak_load": 0
        }
        
        failed_agents = {initial_fault}
        
        for step in range(max_steps):
            step_result = self.simulate_step()
            
            # Update cascade metrics
            new_failures = step_result["new_failures"]
            for failure in new_failures:
                if failure["type"] == "failure_propagation":
                    failed_agents.add(failure["receiver_id"])
            
            cascade_metrics["cascade_size"] = len(failed_agents)
            cascade_metrics["peak_load"] = max(
                cascade_metrics["peak_load"], 
                step_result["system_load"]
            )
            
            # Count retries
            for event in step_result["retry_events"]:
                if event["type"] == "tool_failure_retry":
                    cascade_metrics["total_retries"] += 1
            
            # Check for quiescence (no new events)
            if self.is_system_quiescent(step_result):
                cascade_metrics["time_to_quiescence"] = step + 1
                break
        
        return {
            "cascade_metrics": cascade_metrics,
            "final_failed_agents": list(failed_agents),
            "event_log": self.event_log,
            "simulation_completed": cascade_metrics["time_to_quiescence"] is not None
        }
```

---

## 📊 **EMPIRICAL PROPAGATION PROBABILITY ESTIMATION**

### **4. Experiment to Estimate Per-Edge Propagation Probability**

#### **Per-Edge Probability Estimation**
```python
class PropagationProbabilityEstimator:
    def __init__(self):
        self.edge_failures = {}
        self.background_rates = {}
        self.observation_window_seconds = 30  # Window W for attribution
    
    def record_failure_event(self, incident_data: Dict) -> None:
        """Record failure event with neighbor information"""
        
        incident_id = incident_data["incident_id"]
        failed_node = incident_data["failed_node"]
        failure_time = incident_data["failure_time"]
        neighbors = incident_data["neighbors"]
        
        # Record initial failure
        if failed_node not in self.edge_failures:
            self.edge_failures[failed_node] = {
                "failure_times": [],
                "neighbor_failures": {}
            }
        
        self.edge_failures[failed_node]["failure_times"].append(failure_time)
        
        # Record neighbor states for failure attribution
        for neighbor_id, neighbor_state in neighbors.items():
            edge_key = (failed_node, neighbor_id)
            
            if edge_key not in self.edge_failures[failed_node]["neighbor_failures"]:
                self.edge_failures[failed_node]["neighbor_failures"][edge_key] = []
            
            self.edge_failures[failed_node]["neighbor_failures"][edge_key].append({
                "initial_state": neighbor_state,
                "failure_time": neighbor_state.get("failure_time"),
                "observation_window": self.observation_window_seconds
            })
    
    def estimate_per_edge_probabilities(self) -> Dict[str, Dict[str, float]]:
        """Estimate q_ij = P(j fails | i fails) for each edge"""
        
        edge_probabilities = {}
        
        for source_node, node_data in self.edge_failures.items():
            for edge_key, neighbor_observations in node_data["neighbor_failures"].items():
                target_node = edge_key[1]
                
                # Count incidents where source fails while target is initially healthy
                total_incidents = 0
                attributed_failures = 0
                
                for obs in neighbor_observations:
                    if obs["initial_state"] == "healthy":
                        total_incidents += 1
                        
                        # Check if target fails within observation window
                        if (obs["failure_time"] and 
                            0 < (obs["failure_time"] - obs["initial_time"]).total_seconds() <= self.observation_window_seconds):
                            attributed_failures += 1
                
                # Calculate raw probability
                raw_q_ij = attributed_failures / total_incidents if total_incidents > 0 else 0
                
                # Adjust for background failure rate
                background_rate = self.estimate_background_failure_rate(target_node)
                adjusted_q_ij = max(0, raw_q_ij - background_rate)
                
                edge_probabilities[f"{source_node}_{target_node}"] = {
                    "raw_probability": raw_q_ij,
                    "adjusted_probability": adjusted_q_ij,
                    "background_rate": background_rate,
                    "total_incidents": total_incidents,
                    "attributed_failures": attributed_failures,
                    "confidence_interval": self.calculate_confidence_interval(
                        attributed_failures, total_incidents
                    )
                }
        
        return edge_probabilities
    
    def estimate_background_failure_rate(self, node_id: str) -> float:
        """Estimate background failure probability p_j for node j"""
        
        if node_id in self.background_rates:
            return self.background_rates[node_id]
        
        # Calculate background rate from historical data
        # This would typically use failure data when neighbors are healthy
        # For now, return a small default value
        return 0.01
    
    def calculate_confidence_interval(self, successes: int, trials: int, 
                                    confidence: float = 0.95) -> Tuple[float, float]:
        """Calculate confidence interval for probability estimate"""
        
        if trials == 0:
            return (0.0, 0.0)
        
        # Wilson score interval for better small-sample performance
        z = 1.96  # 95% confidence
        p = successes / trials
        n = trials
        
        denominator = 1 + z**2 / n
        center = (p + z**2 / (2*n)) / denominator
        margin = z * math.sqrt(p*(1-p)/n + z**2/(4*n**2)) / denominator
        
        return (max(0, center - margin), min(1, center + margin))
```

---

## 🔄 **RETRY-AWARE CASCADE MODELING**

### **5. Incorporating Retry and Backoff into Cascade Models**

#### **Retry-Enhanced Cascade Analysis**
```python
class RetryAwareCascadeAnalyzer:
    def __init__(self):
        self.retry_parameters = {
            "max_retries": 3,
            "base_failure_prob": 0.1,
            "backoff_base": 2.0,
            "jitter_factor": 0.1
        }
    
    def calculate_effective_failure_probability(self, base_failure: float, 
                                                max_retries: int) -> float:
        """Calculate f_eff = f^(k+1) for independent retries"""
        
        return base_failure ** (max_retries + 1)
    
    def calculate_expected_attempts(self, base_failure: float, max_retries: int) -> float:
        """Calculate E[attempts] = Σ(f^n) from n=0 to k"""
        
        if base_failure >= 1.0:
            return float('inf')
        
        if base_failure == 0.0:
            return 1.0
        
        # Geometric series sum
        return (1 - base_failure ** (max_retries + 1)) / (1 - base_failure)
    
    def calculate_retry_cascade_index(self, incident_data: List[Dict]) -> Dict[str, Any]:
        """Calculate RCI = total_retry_attempts / initial_failures"""
        
        total_initial_failures = 0
        total_retry_attempts = 0
        
        incident_rci = []
        
        for incident in incident_data:
            initial_failures = incident["initial_failures"]
            retry_attempts = incident["retry_attempts"]
            
            total_initial_failures += initial_failures
            total_retry_attempts += retry_attempts
            
            if initial_failures > 0:
                incident_rci = retry_attempts / initial_failures
            else:
                incident_rci = 0
            
            incident_rci.append({
                "incident_id": incident["incident_id"],
                "retry_cascade_index": incident_rci,
                "initial_failures": initial_failures,
                "retry_attempts": retry_attempts,
                "exceeds_threshold": incident_rci > 2.0  # Threshold for concerning retry behavior
            })
        
        overall_rci = total_retry_attempts / total_initial_failures if total_initial_failures > 0 else 0
        
        return {
            "overall_retry_cascade_index": overall_rci,
            "total_initial_failures": total_initial_failures,
            "total_retry_attempts": total_retry_attempts,
            "incident_details": incident_rci,
            "high_retry_cascade_rate": len([i for i in incident_rci if i["exceeds_threshold"]]) / len(incident_rci) if incident_rci else 0,
            "interpretation": self.interpret_retry_cascade_index(overall_rci)
        }
    
    def interpret_retry_cascade_index(self, rci: float) -> str:
        """Interpret retry cascade index value"""
        
        if rci < 1.0:
            return "Low retry activity - healthy system"
        elif rci < 2.0:
            return "Moderate retry activity - acceptable"
        elif rci < 5.0:
            return "High retry activity - potential cascade risk"
        else:
            return "Very high retry activity - cascade danger zone"
    
    def optimize_retry_parameters(self, historical_data: List[Dict], 
                                  target_rci_threshold: float = 2.0) -> Dict[str, Any]:
        """Optimize retry parameters to keep RCI below threshold"""
        
        optimization_results = {}
        
        # Test different max_retries values
        for max_retries in range(1, 6):
            # Test different backoff bases
            for backoff_base in [1.5, 2.0, 2.5, 3.0]:
                # Simulate with these parameters
                simulated_rci = self.simulate_retry_behavior(
                    historical_data, max_retries, backoff_base
                )
                
                optimization_results[f"retries_{max_retries}_backoff_{backoff_base}"] = {
                    "max_retries": max_retries,
                    "backoff_base": backoff_base,
                    "simulated_rci": simulated_rci,
                    "meets_threshold": simulated_rci <= target_rci_threshold,
                    "efficiency_score": self.calculate_efficiency_score(
                        simulated_rci, max_retries, backoff_base
                    )
                }
        
        # Find best configuration
        valid_configs = [
            config for config in optimization_results.values()
            if config["meets_threshold"]
        ]
        
        if valid_configs:
            best_config = max(valid_configs, key=lambda x: x["efficiency_score"])
        else:
            # If no config meets threshold, choose one with lowest RCI
            best_config = min(optimization_results.values(), key=lambda x: x["simulated_rci"])
        
        return {
            "recommended_config": best_config,
            "all_configurations": optimization_results,
            "optimization_target": target_rci_threshold
        }
    
    def calculate_efficiency_score(self, rci: float, max_retries: int, backoff_base: float) -> float:
        """Calculate efficiency score balancing RCI and retry aggressiveness"""
        
        # Lower RCI is better, but we also want to be less aggressive with retries
        retry_aggressiveness = max_retries * backoff_base
        
        # Efficiency score: higher is better
        # Penalize high RCI heavily, penalize aggressive retries moderately
        score = 1.0 / (1.0 + rci + 0.1 * retry_aggressiveness)
        
        return score
**Next Review:** After Phase 1 implementation  
**Owner:** MERID Swarm Reliability Team  
**Target:** Production-ready failure-resilient development swarm
                "agent_id": agent_id,
                "drift_score": drift_score,
                "current_profile": current_profile,
                "baseline_profile": baseline_profile,
                "significant_changes": self.identify_drift_changes(current_profile, baseline_profile)
            })
        
        # Check for specific drift patterns
        if self.check_reviewer_editing_drift(current_profile, agent_id):
            signals.append({
                "type": "reviewer_editing_drift",
                "agent_id": agent_id,
                "editing_actions": current_profile.get("edit_code_actions", 0)
            })
        
        return signals
    
    def create_behavior_profile(self, event_window):
        profile = {
            "action_distribution": {},
            "resource_access_patterns": {},
            "decision_patterns": {},
            "communication_patterns": {}
        }
        
        for event in event_window:
            # Action distribution
            action = event.get("action", "unknown")
            profile["action_distribution"][action] = profile["action_distribution"].get(action, 0) + 1
            
            # Resource access patterns
            resource = event.get("resource", "unknown")
            profile["resource_access_patterns"][resource] = profile["resource_access_patterns"].get(resource, 0) + 1
            
            # Decision patterns
            decision = event.get("decision", "unknown")
            profile["decision_patterns"][decision] = profile["decision_patterns"].get(decision, 0) + 1
        
        return profile
```

**Mitigation Strategies:**
- **Baseline Profiling:** Establish and maintain behavior baselines
- **Continuous Drift Monitoring:** Real-time drift detection and alerting
- **Automated Re-training:** Retrain agents when drift detected
- **Role Re-certification:** Periodic validation of role compliance

---

## 📊 **INTER-AGENT CAUSALITY METRICS**

### **2. Metrics Indicating Inter-Agent Causality Breaches**

#### **Orphan Actions Detection**
```python
class OrphanActionMetrics:
    def __init__(self):
        self.prerequisite_map = {
            "agent_apply_diff": ["tests_passed", "review_approved"],
            "merge_proposed": ["tests_passed", "review_approved", "security_scan_passed"],
            "deployment_started": ["tests_passed", "review_approved", "deployment_approved"]
        }
    
    def calculate_orphan_actions(self, task_traces, time_window=3600):
        orphan_count = 0
        total_actions = 0
        orphan_details = []
        
        for trace in task_traces:
            for event in trace["events"]:
                if event["type"] in self.prerequisite_map:
                    total_actions += 1
                    
                    # Check if prerequisites exist in trace
                    prerequisites = self.prerequisite_map[event["type"]]
                    missing_prereqs = []
                    
                    for prereq in prerequisites:
                        if not self.has_prerequisite_event(trace, prereq, event["timestamp"]):
                            missing_prereqs.append(prereq)
                    
                    if missing_prereqs:
                        orphan_count += 1
                        orphan_details.append({
                            "action": event["type"],
                            "timestamp": event["timestamp"],
                            "missing_prerequisites": missing_prereqs,
                            "task_id": trace["task_id"]
                        })
        
        orphan_rate = orphan_count / total_actions if total_actions > 0 else 0
        
        return {
            "orphan_count": orphan_count,
            "total_actions": total_actions,
            "orphan_rate": orphan_rate,
            "orphan_details": orphan_details,
            "time_window": time_window
        }
```

#### **Inverted Dependency Order Detection**
```python
class InvertedDependencyMetrics:
    def __init__(self):
        self.valid_sequences = {
            "code_before_tests": ["diff_created", "code_updated", "tests_passed"],
            "test_before_review": ["tests_passed", "review_started"],
            "review_before_merge": ["review_approved", "merge_proposed"]
        }
    
    def calculate_inverted_dependencies(self, task_traces):
        inversions = []
        total_sequences = 0
        
        for trace in task_traces:
            for sequence_name, valid_order in self.valid_sequences.items():
                total_sequences += 1
                
                # Get timestamps for each event type in sequence
                event_timestamps = {}
                for event_type in valid_order:
                    events = [e for e in trace["events"] if e["type"] == event_type]
                    if events:
                        event_timestamps[event_type] = min(e["timestamp"] for e in events)
                
                # Check if order is violated
                if len(event_timestamps) == len(valid_order):
                    actual_order = sorted(event_timestamps.items(), key=lambda x: x[1])
                    expected_order = [(event_type, event_timestamps[event_type]) for event_type in valid_order]
                    
                    if actual_order != expected_order:
                        inversions.append({
                            "sequence_name": sequence_name,
                            "expected_order": [e[0] for e in expected_order],
                            "actual_order": [e[0] for e in actual_order],
                            "task_id": trace["task_id"]
                        })
        
        inversion_rate = len(inversions) / total_sequences if total_sequences > 0 else 0
        
        return {
            "inversion_count": len(inversions),
            "total_sequences": total_sequences,
            "inversion_rate": inversion_rate,
            "inversions": inversions
        }
```

---

## 🔗 **TRACE SPAN DESIGN FOR AGENT-TO-AGENT INTERACTIONS**

### **3. Distributed Tracing Hierarchy**

#### **Basic Span Structure**
```python
@dataclass
class SwarmTraceSpan:
    # OpenTelemetry trace context
    trace_id: str                    # Global task identifier
    span_id: str                     # Current operation identifier
    parent_span_id: Optional[str]    # Parent operation identifier
    
    # Span classification
    span_type: str                   # task_root, agent_execution, agent_message, tool_invocation, state_access
    
    # Agent-specific attributes
    agent_id: Optional[str]          # Agent identifier
    agent_role: Optional[str]        # planner, implementer, tester, reviewer
    parent_agent_id: Optional[str]   # Calling agent for agent spans
    
    # State and artifact tracking
    input_snapshot_id: Optional[str] # State snapshot at span start
    output_artifact_ids: List[str]   # Artifacts created in this span
    
    # Performance metrics
    model_version: Optional[str]     # LLM model version
    token_usage: Optional[int]       # Tokens consumed
    latency_ms: int                  # Span duration
    
    # Communication attributes
    from_agent_id: Optional[str]     # For message spans
    to_agent_id: Optional[str]       # For message spans
    message_type: Optional[str]      # plan, spec, request, review, escalation
    content_digest: Optional[str]    # Message content hash
    turn_index: Optional[int]        # Conversation turn number
    
    # Tool and state attributes
    tool_name: Optional[str]         # Tool name for tool spans
    tool_args_digest: Optional[str]  # Tool arguments hash
    operation: Optional[str]         # read/write for state spans
    resource_type: Optional[str]     # git, config, db for state spans
    resource_id: Optional[str]       # Resource identifier
    version: Optional[str]            # State version
    
    # Status and outcome
    status: str                      # started, finished, error, cancelled
    error_type: Optional[str]        # Error classification
    retry_count: Optional[int]        # Retry attempts
    
    # Span links for async interactions
    span_links: List[SpanLink]       # Links to related spans
    
    # Timestamps
    start_time: datetime              # Span start timestamp
    end_time: Optional[datetime]      # Span end timestamp
```

#### **Span Link Implementation**
```python
@dataclass
class SpanLink:
    trace_id: str                    # Linked span's trace ID
    span_id: str                     # Linked span's span ID
    trace_state: str                  # Trace state context
    attributes: Dict[str, str]       # Link attributes
    
    # Link types for agent coordination
    link_type: str                   # "parent", "child", "follows_from", "causal_dependency"
    
class AgentSpanLinks:
    def create_message_link(self, sender_span: SwarmTraceSpan, 
                          receiver_span: SwarmTraceSpan) -> SpanLink:
        """Create link between sender and receiver message spans"""
        return SpanLink(
            trace_id=receiver_span.trace_id,
            span_id=receiver_span.span_id,
            trace_state="message_delivered",
            attributes={
                "sender_agent": sender_span.agent_id,
                "receiver_agent": receiver_span.agent_id,
                "message_type": receiver_span.message_type,
                "content_digest": receiver_span.content_digest
            },
            link_type="follows_from"
        )
    
    def create_causal_dependency_link(self, prerequisite_span: SwarmTraceSpan,
                                     dependent_span: SwarmTraceSpan) -> SpanLink:
        """Create causal dependency link between spans"""
        return SpanLink(
            trace_id=dependent_span.trace_id,
            span_id=dependent_span.span_id,
            trace_state="dependency_satisfied",
            attributes={
                "prerequisite_type": prerequisite_span.span_type,
                "prerequisite_agent": prerequisite_span.agent_id,
                "dependency_type": "causal_requirement"
            },
            link_type="causal_dependency"
        )
```

#### **Agent-to-Agent Causality Tracking**
```python
class AgentCausalityTracker:
    def __init__(self):
        self.active_traces = {}
        self.span_graphs = {}
    
    def start_agent_execution(self, task_id: str, agent_id: str, agent_role: str,
                             parent_agent_id: Optional[str] = None) -> SwarmTraceSpan:
        """Start tracking agent execution with proper parentage"""
        
        # Find parent span if specified
        parent_span_id = None
        if parent_agent_id:
            parent_span_id = self.find_agent_active_span(task_id, parent_agent_id)
        
        span = SwarmTraceSpan(
            trace_id=task_id,
            span_id=self.generate_span_id(),
            parent_span_id=parent_span_id,
            span_type="agent_execution",
            agent_id=agent_id,
            agent_role=agent_role,
            parent_agent_id=parent_agent_id,
            input_snapshot_id=self.get_current_state_snapshot(task_id),
            status="started",
            start_time=datetime.now()
        )
        
        # Register span
        self.register_span(task_id, span)
        
        return span
    
    def track_agent_message(self, task_id: str, from_agent_id: str, to_agent_id: str,
                           message_type: str, content: str) -> SwarmTraceSpan:
        """Track agent-to-agent message with causal links"""
        
        # Find sender and receiver spans
        sender_span = self.find_agent_active_span(task_id, from_agent_id)
        receiver_span = self.find_agent_active_span(task_id, to_agent_id)
        
        message_span = SwarmTraceSpan(
            trace_id=task_id,
            span_id=self.generate_span_id(),
            parent_span_id=sender_span.span_id,
            span_type="agent_message",
            from_agent_id=from_agent_id,
            to_agent_id=to_agent_id,
            message_type=message_type,
            content_digest=self.hash_content(content),
            turn_index=self.get_next_turn_index(task_id, from_agent_id, to_agent_id),
            status="started",
            start_time=datetime.now()
        )
        
        # Create span links
        sender_link = self.create_message_link(sender_span, message_span)
        receiver_link = self.create_message_link(message_span, receiver_span)
        
        message_span.span_links = [sender_link, receiver_link]
        
        # Register span
        self.register_span(task_id, message_span)
        
        return message_span
    
    def verify_causal_dependencies(self, task_id: str, span: SwarmTraceSpan) -> List[str]:
        """Verify that all causal dependencies are satisfied"""
        
        missing_dependencies = []
        
        # Check span links for causal dependencies
        for link in span.span_links:
            if link.link_type == "causal_dependency":
                prereq_span = self.get_span(link.trace_id, link.span_id)
                
                if not prereq_span or prereq_span.status != "finished":
                    missing_dependencies.append(f"missing_prerequisite: {link.span_id}")
        
        return missing_dependencies

---

## 📋 **ROLE DRIFT EVENT LOGGING**

### **4. Events to Log for Detecting Role Drift**

#### **Agent Role Versioning**
```python
class RoleVersioningLogger:
    def __init__(self):
        self.role_registry = {}
        self.version_history = {}
    
    def log_role_version_change(self, agent_role: str, role_version: str, 
                               change_summary: str, changed_by: str):
        """Log when agent role contracts are updated"""
        
        event = {
            "event_type": "agent_role_versioned",
            "timestamp": datetime.now(),
            "agent_role": agent_role,
            "role_version": role_version,
            "change_summary": change_summary,
            "changed_by": changed_by,
            "previous_version": self.get_previous_version(agent_role),
            "change_type": self.classify_change_type(change_summary)
        }
        
        # Update registry
        self.role_registry[agent_role] = {
            "current_version": role_version,
            "last_updated": event["timestamp"],
            "change_history": self.version_history.get(agent_role, []) + [event]
        }
        
        self.version_history[agent_role] = self.role_registry[agent_role]["change_history"]
        
        return event
    
    def classify_change_type(self, change_summary: str) -> str:
        """Classify the type of role change"""
        summary_lower = change_summary.lower()
        
        if "prompt" in summary_lower:
            return "prompt_change"
        elif "tool" in summary_lower:
            return "tool_change"
        elif "constraint" in summary_lower:
            return "constraint_change"
        elif "permission" in summary_lower:
            return "permission_change"
        else:
            return "general_change"
```

#### **Agent Action Tracking**
```python
class AgentActionLogger:
    def __init__(self):
        self.action_log = []
        self.role_action_boundaries = {
            "planner": ["create_plan", "define_requirements", "coordinate_task", "analyze_spec"],
            "implementer": ["write_code", "create_diff", "update_documentation", "run_build"],
            "tester": ["write_tests", "run_tests", "report_results", "validate_functionality"],
            "reviewer": ["review_code", "provide_feedback", "approve_reject", "check_compliance"]
        }
    
    def log_agent_action(self, agent_id: str, agent_role: str, action_type: str,
                        scope: List[str], artifacts: List[str], context: Dict[str, Any]):
        """Log every agent action for drift detection"""
        
        event = {
            "event_type": "agent_action",
            "timestamp": datetime.now(),
            "agent_id": agent_id,
            "agent_role": agent_role,
            "action_type": action_type,
            "scope": scope,  # Files, services, resources touched
            "artifacts": artifacts,  # Created/modified artifacts
            "context": context,
            "is_boundary_violation": self.check_boundary_violation(agent_role, action_type),
            "action_complexity": self.calculate_action_complexity(action_type, scope, artifacts)
        }
        
        self.action_log.append(event)
        return event
    
    def check_boundary_violation(self, agent_role: str, action_type: str) -> bool:
        """Check if action violates role boundaries"""
        allowed_actions = self.role_action_boundaries.get(agent_role, [])
        return action_type not in allowed_actions
    
    def calculate_action_distribution(self, time_window: int = 3600) -> Dict[str, Dict[str, int]]:
        """Calculate action distribution by role over time window"""
        
        cutoff_time = datetime.now() - timedelta(seconds=time_window)
        recent_actions = [a for a in self.action_log if a["timestamp"] > cutoff_time]
        
        distribution = {}
        for action in recent_actions:
            role = action["agent_role"]
            action_type = action["action_type"]
            
            if role not in distribution:
                distribution[role] = {}
            
            distribution[role][action_type] = distribution[role].get(action_type, 0) + 1
        
        return distribution
```

#### **Decision Outcome Tracking**
```python
class DecisionOutcomeLogger:
    def __init__(self):
        self.decision_log = []
        self.decision_types = ["approve", "reject", "escalate", "noop", "request_changes"]
    
    def log_decision_outcome(self, agent_id: str, agent_role: str, decision_type: str,
                           justification: str, upstream_artifacts: List[str],
                           confidence_score: Optional[float] = None):
        """Log agent decisions for pattern analysis"""
        
        event = {
            "event_type": "decision_outcome",
            "timestamp": datetime.now(),
            "agent_id": agent_id,
            "agent_role": agent_role,
            "decision_type": decision_type,
            "justification_digest": self.hash_justification(justification),
            "justification_text": justification,
            "upstream_artifact_ids": upstream_artifacts,
            "confidence_score": confidence_score,
            "decision_complexity": self.calculate_decision_complexity(justification, upstream_artifacts)
        }
        
        self.decision_log.append(event)
        return event
    
    def analyze_decision_patterns(self, agent_role: str, time_window: int = 3600) -> Dict[str, Any]:
        """Analyze decision patterns for a role over time"""
        
        cutoff_time = datetime.now() - timedelta(seconds=time_window)
        role_decisions = [d for d in self.decision_log 
                        if d["agent_role"] == agent_role and d["timestamp"] > cutoff_time]
        
        if not role_decisions:
            return {"error": "No decisions found in time window"}
        
        # Calculate decision distribution
        decision_counts = {}
        for decision in role_decisions:
            decision_type = decision["decision_type"]
            decision_counts[decision_type] = decision_counts.get(decision_type, 0) + 1
        
        # Calculate average confidence
        confidences = [d["confidence_score"] for d in role_decisions if d["confidence_score"] is not None]
        avg_confidence = sum(confidences) / len(confidences) if confidences else None
        
        # Check for pattern changes
        recent_half = role_decisions[len(role_decisions)//2:]
        early_half = role_decisions[:len(role_decisions)//2]
        
        recent_distribution = self.calculate_distribution(recent_half)
        early_distribution = self.calculate_distribution(early_half)
        
        pattern_drift = self.calculate_distribution_drift(early_distribution, recent_distribution)
        
        return {
            "total_decisions": len(role_decisions),
            "decision_distribution": decision_counts,
            "average_confidence": avg_confidence,
            "pattern_drift": pattern_drift,
            "decision_rate": len(role_decisions) / (time_window / 3600)  # decisions per hour
        }
```

#### **Behavior Profile Snapshots**
```python
class BehaviorProfileLogger:
    def __init__(self):
        self.profile_snapshots = []
        self.snapshot_interval = 3600  # 1 hour
    
    def create_behavior_profile_snapshot(self, agent_id: str, agent_role: str,
                                        time_window: int = 3600) -> Dict[str, Any]:
        """Create periodic behavior profile snapshot"""
        
        cutoff_time = datetime.now() - timedelta(seconds=time_window)
        
        # Collect recent actions and decisions
        recent_actions = [a for a in self.get_action_log() 
                         if a["agent_id"] == agent_id and a["timestamp"] > cutoff_time]
        recent_decisions = [d for d in self.get_decision_log() 
                           if d["agent_id"] == agent_id and d["timestamp"] > cutoff_time]
        
        # Calculate profile metrics
        profile = {
            "snapshot_id": self.generate_snapshot_id(),
            "timestamp": datetime.now(),
            "agent_id": agent_id,
            "agent_role": agent_role,
            "time_window_seconds": time_window,
            
            # Action metrics
            "actions_per_hour": len(recent_actions),
            "action_distribution": self.calculate_action_distribution(recent_actions),
            "resource_access_patterns": self.calculate_resource_patterns(recent_actions),
            "scope_complexity": self.calculate_scope_complexity(recent_actions),
            
            # Decision metrics
            "decisions_per_hour": len(recent_decisions),
            "decision_distribution": self.calculate_decision_distribution(recent_decisions),
            "average_confidence": self.calculate_average_confidence(recent_decisions),
            "justification_complexity": self.calculate_justification_complexity(recent_decisions),
            
            # Communication metrics
            "messages_sent": self.count_messages_sent(agent_id, time_window),
            "messages_received": self.count_messages_received(agent_id, time_window),
            "communication_partners": self.get_communication_partners(agent_id, time_window),
            
            # Error and success metrics
            "success_rate": self.calculate_success_rate(agent_id, time_window),
            "error_rate": self.calculate_error_rate(agent_id, time_window),
            "retry_rate": self.calculate_retry_rate(agent_id, time_window)
        }
        
        # Store snapshot
        self.profile_snapshots.append(profile)
        
        return profile
    
    def detect_drift_between_snapshots(self, snapshot1: Dict[str, Any], 
                                      snapshot2: Dict[str, Any]) -> Dict[str, Any]:
        """Compare two snapshots to detect behavior drift"""
        
        drift_indicators = {}
        
        # Compare action distributions
        action_drift = self.calculate_distribution_drift(
            snapshot1["action_distribution"],
            snapshot2["action_distribution"]
        )
        drift_indicators["action_distribution_drift"] = action_drift
        
        # Compare decision patterns
        decision_drift = self.calculate_distribution_drift(
            snapshot1["decision_distribution"],
            snapshot2["decision_distribution"]
        )
        drift_indicators["decision_distribution_drift"] = decision_drift
        
        # Compare rates
        rate_changes = {
            "action_rate_change": snapshot2["actions_per_hour"] - snapshot1["actions_per_hour"],
            "decision_rate_change": snapshot2["decisions_per_hour"] - snapshot1["decisions_per_hour"],
            "success_rate_change": snapshot2["success_rate"] - snapshot1["success_rate"],
            "error_rate_change": snapshot2["error_rate"] - snapshot1["error_rate"]
        }
        drift_indicators["rate_changes"] = rate_changes
        
        # Calculate overall drift score
        drift_score = self.calculate_overall_drift_score(drift_indicators)
        drift_indicators["overall_drift_score"] = drift_score
        
        return drift_indicators

---

## ⏰ **STATE READ/WRITE TIMESTAMP RELIABILITY**

### **5. Capturing State Read/Write Timestamps Reliably**

#### **Central Time Source Implementation**
```python
class CentralizedTimeService:
    def __init__(self):
        self.authoritative_clock = datetime.now()
        self.clock_drift_threshold = timedelta(milliseconds=100)
        self.time_sync_interval = 60  # seconds
    
    def get_authoritative_timestamp(self) -> datetime:
        """Get authoritative timestamp from orchestrator"""
        
        # In production, this would sync with a central time service
        # For now, use orchestrator's clock with periodic sync
        current_time = datetime.now()
        
        # Check for clock drift and sync if needed
        if abs(current_time - self.authoritative_clock) > self.clock_drift_threshold:
            self.sync_central_clock()
        
        return self.authoritative_clock
    
    def sync_central_clock(self):
        """Sync central clock with authoritative source"""
        # In production, this would sync with NTP or a central time service
        self.authoritative_clock = datetime.now()
    
    def attach_timestamp(self, operation_type: str, resource_id: str) -> Dict[str, Any]:
        """Attach authoritative timestamp to state operation"""
        
        timestamp = self.get_authoritative_timestamp()
        
        return {
            "timestamp": timestamp,
            "timestamp_source": "orchestrator_central",
            "operation_type": operation_type,
            "resource_id": resource_id,
            "timestamp_iso": timestamp.isoformat(),
            "timestamp_unix": int(timestamp.timestamp())
        }
```

#### **Versioned State Access API**
```python
class VersionedStateAccess:
    def __init__(self, time_service: CentralizedTimeService):
        self.time_service = time_service
        self.state_versions = {}
        self.optimistic_locks = {}
    
    def read_state(self, resource_id: str, agent_id: str) -> StateReadResult:
        """Read state with version and timestamp tracking"""
        
        # Get current version
        current_version = self.get_current_version(resource_id)
        
        # Attach read timestamp
        timestamp_info = self.time_service.attach_timestamp("state_read", resource_id)
        
        # Create state read event
        state_read_event = {
            "event_type": "state_read",
            "agent_id": agent_id,
            "resource_id": resource_id,
            "read_timestamp": timestamp_info["timestamp"],
            "read_version": current_version,
            "read_timestamp_iso": timestamp_info["timestamp_iso"],
            "cache_hit": self.check_cache_hit(resource_id, current_version),
            "freshness_score": self.calculate_freshness_score(resource_id, current_version)
        }
        
        # Log the event
        self.log_state_event(state_read_event)
        
        return StateReadResult(
            data=self.get_state_data(resource_id),
            version=current_version,
            timestamp=timestamp_info["timestamp"],
            freshness_score=state_read_event["freshness_score"]
        )
    
    def write_state(self, resource_id: str, new_data: Any, agent_id: str,
                   expected_version: Optional[str] = None) -> StateWriteResult:
        """Write state with optimistic concurrency and timestamp tracking"""
        
        # Get current version for conflict detection
        current_version = self.get_current_version(resource_id)
        
        # Check for version conflicts
        if expected_version and expected_version != current_version:
            conflict_event = {
                "event_type": "state_conflict",
                "agent_id": agent_id,
                "resource_id": resource_id,
                "expected_version": expected_version,
                "actual_version": current_version,
                "conflict_timestamp": self.time_service.get_authoritative_timestamp(),
                "conflict_type": "version_mismatch"
            }
            
            self.log_state_event(conflict_event)
            
            return StateWriteResult(
                success=False,
                conflict=conflict_event,
                current_version=current_version
            )
        
        # Generate new version
        new_version = self.generate_new_version(resource_id)
        
        # Attach write timestamp
        timestamp_info = self.time_service.attach_timestamp("state_write", resource_id)
        
        # Perform the write
        self.perform_state_write(resource_id, new_data, new_version)
        
        # Create state write event
        state_write_event = {
            "event_type": "state_write",
            "agent_id": agent_id,
            "resource_id": resource_id,
            "write_timestamp": timestamp_info["timestamp"],
            "previous_version": current_version,
            "new_version": new_version,
            "write_timestamp_iso": timestamp_info["timestamp_iso"],
            "write_size_bytes": self.calculate_data_size(new_data),
            "atomic_operation": True
        }
        
        # Log the event
        self.log_state_event(state_write_event)
        
        return StateWriteResult(
            success=True,
            new_version=new_version,
            previous_version=current_version,
            timestamp=timestamp_info["timestamp"]
        )
```

---

#### **Trigger**
- Agents repeatedly re-plan without progress
- Hand tasks back and forth without advancing (ping-pong patterns)
- Circular dependencies in agent communication

#### **Detection Signals**
```python
class CoordinationLoopDetector:
    def __init__(self):
        self.message_history = []
        self.artifact_history = []
    
    def detect_ping_pong(self, current_message):
        # Check for repeated message patterns
        recent_messages = self.message_history[-10:]
        
        if len(recent_messages) >= 4:
            pattern = [m.sender for m in recent_messages[-4:]]
            if pattern == ["agent_a", "agent_b", "agent_a", "agent_b"]:
                return "ping_pong_detected"
        
        # Check for replanning without artifacts
        recent_artifacts = self.artifact_history[-5:]
        if len(recent_artifacts) == 0 and len(recent_messages) > 5:
            return "replanning_without_progress"
        
        return None
    
    def add_message(self, message):
        self.message_history.append(message)
    
    def add_artifact(self, artifact):
        self.artifact_history.append(artifact)
```

#### **Mitigation Strategies**
- **Loop Detection:** Identify repeated communication patterns
- **Progress Validation:** Require new artifacts for continued coordination
- **Timeout Enforcement:** Limit coordination rounds per task
- **Escalation Protocol:** Human intervention when loops detected

#### **Implementation Example**
```python
def prevent_coordination_loops(coordinator, max_rounds=5):
    round_count = 0
    last_artifacts = set()
    
    while round_count < max_rounds:
        current_artifacts = get_current_artifacts()
        
        # Check for progress
        if current_artifacts != last_artifacts:
            last_artifacts = current_artifacts
            round_count = 0  # Reset counter on progress
        else:
            round_count += 1
        
        if round_count >= 3:  # Warning threshold
            coordinator.log_warning("potential_coordination_loop")
        
        if round_count >= max_rounds:
            coordinator.escalate_to_human("coordination_loop_detected")
            break
        
        proceed_with_coordination()
```

---

### **4. Retry Storms and Thrash**

#### **Trigger**
- Tool/API failures trigger multiple independent agent retries
- Overloading of services or spamming CI systems
- Cascading failures from retry amplification

#### **Detection Signals**
```python
class RetryStormDetector:
    def __init__(self):
        self.retry_attempts = {}
        self.tool_error_rates = {}
    
    def detect_retry_storm(self, tool_call):
        tool_name = tool_call.tool
        timestamp = tool_call.timestamp
        
        # Track retry attempts per tool
        if tool_name not in self.retry_attempts:
            self.retry_attempts[tool_name] = []
        
        self.retry_attempts[tool_name].append(timestamp)
        
        # Check for retry storm
        recent_retries = [t for t in self.retry_attempts[tool_name] 
                         if timestamp - t < 60]  # Last minute
        
        if len(recent_retries) > 10:
            return f"retry_storm_{tool_name}"
        
        # Check for increasing error rate
        if self.calculate_error_rate(tool_name) > 0.5:
            return f"high_error_rate_{tool_name}"
        
        return None
    
    def calculate_error_rate(self, tool_name, window=300):
        # Calculate error rate in last 5 minutes
        recent_calls = get_recent_tool_calls(tool_name, window)
        errors = [c for c in recent_calls if c.status == "error"]
        
        return len(errors) / len(recent_calls) if recent_calls else 0
```

#### **Mitigation Strategies**
- **Centralized Retry Management:** Single coordinator manages all retries
- **Exponential Backoff:** Implement proper backoff strategies
- **Circuit Breaker Pattern:** Stop retrying failing tools temporarily
- **Load Balancing:** Distribute requests across multiple instances

#### **Implementation Example**
```python
class RetryManager:
    def __init__(self):
        self.circuit_breakers = {}
        self.retry_backoffs = {}
    
    def execute_with_retry(self, tool_call, max_retries=3):
        tool_name = tool_call.tool
        
        # Check circuit breaker
        if self.is_circuit_open(tool_name):
            raise CircuitBreakerOpen(f"Tool {tool_name} circuit breaker open")
        
        for attempt in range(max_retries):
            try:
                result = execute_tool_call(tool_call)
                self.record_success(tool_name)
                return result
            except Exception as e:
                self.record_failure(tool_name)
                
                if attempt < max_retries - 1:
                    backoff = self.calculate_backoff(tool_name, attempt)
                    time.sleep(backoff)
                else:
                    raise e
    
    def calculate_backoff(self, tool_name, attempt):
        base_delay = 1
        max_delay = 60
        delay = min(base_delay * (2 ** attempt), max_delay)
        
        # Add jitter to prevent thundering herd
        jitter = random.uniform(0, 0.1 * delay)
        return delay + jitter
```

---

### **5. Conflicting Edits and Race Conditions**

#### **Trigger**
- Two agents modify related files concurrently (same module, schema + code)
- Lack of proper locking/ownership causes merge conflicts
- Logical inconsistencies from concurrent modifications

#### **Detection Signals**
```python
class ConflictDetector:
    def __init__(self):
        self.file_locks = {}
        self.active_modifications = {}
    
    def detect_potential_conflict(self, agent, file_path):
        # Check if file is being modified by another agent
        if file_path in self.active_modifications:
            other_agent = self.active_modifications[file_path]
            if other_agent != agent:
                return f"conflict_detected_with_{other_agent}"
        
        # Check for related file modifications
        related_files = get_related_files(file_path)
        for related_file in related_files:
            if related_file in self.active_modifications:
                return f"related_file_conflict_{related_file}"
        
        return None
    
    def acquire_file_lock(self, agent, file_path):
        conflict = self.detect_potential_conflict(agent, file_path)
        
        if conflict:
            raise ConflictError(conflict)
        
        self.active_modifications[file_path] = agent
        return True
    
    def release_file_lock(self, agent, file_path):
        if self.active_modifications.get(file_path) == agent:
            del self.active_modifications[file_path]
```

#### **Mitigation Strategies**
- **File Locking:** Implement exclusive access for file modifications
- **Conflict Detection:** Pre-modification conflict checking
- **Atomic Operations:** Batch related changes together
- **Rollback Capability:** Automatic rollback on conflict detection

#### **Implementation Example**
```python
class FileModificationManager:
    def __init__(self):
        self.lock_manager = ConflictDetector()
        self.pending_changes = {}
    
    def modify_files(self, agent, file_changes):
        # Acquire locks for all files
        acquired_locks = []
        
        try:
            for file_path in file_changes:
                self.lock_manager.acquire_file_lock(agent, file_path)
                acquired_locks.append(file_path)
            
            # Apply changes atomically
            for file_path, changes in file_changes.items():
                self.apply_changes(file_path, changes)
                self.pending_changes[file_path] = changes
            
            return True
            
        except ConflictError as e:
            # Rollback any partial changes
            self.rollback_changes(acquired_locks)
            raise e
        
        finally:
            # Release all locks
            for file_path in acquired_locks:
                self.lock_manager.release_file_lock(agent, file_path)
```

---

### **6. Silent Failure and Partial Completion**

#### **Trigger**
- Sub-task fails quietly (test generation, migration, config update)
- Coordinator marks overall task as "done" despite incomplete work
- Merged incomplete work causes system issues

#### **Detection Signals**
```python
class SilentFailureDetector:
    def __init__(self):
        self.task_requirements = {}
        self.completion_status = {}
    
    def define_task_requirements(self, task_id, requirements):
        self.task_requirements[task_id] = requirements
        self.completion_status[task_id] = {}
    
    def track_subtask_completion(self, task_id, subtask, status):
        if task_id not in self.completion_status:
            self.completion_status[task_id] = {}
        
        self.completion_status[task_id][subtask] = status
    
    def detect_silent_failure(self, task_id):
        if task_id not in self.task_requirements:
            return "no_requirements_defined"
        
        requirements = self.task_requirements[task_id]
        status = self.completion_status.get(task_id, {})
        
        missing_requirements = []
        for req in requirements:
            if req not in status or status[req] != "completed":
                missing_requirements.append(req)
        
        if missing_requirements:
            return f"incomplete_requirements: {missing_requirements}"
        
        return None
```

#### **Mitigation Strategies**
- **Requirement Tracking:** Explicit definition and tracking of all sub-tasks
- **Status Validation:** Verify all requirements completed before marking task done
- **Health Checks:** Post-completion validation of system state
- **Rollback Capability:** Ability to undo incomplete changes

#### **Implementation Example**
```python
class TaskCompletionValidator:
    def __init__(self):
        self.requirement_tracker = SilentFailureDetector()
    
    def complete_task(self, task_id, coordinator):
        # Define requirements for task type
        requirements = self.get_task_requirements(task_id)
        self.requirement_tracker.define_task_requirements(task_id, requirements)
        
        # Track completion of each sub-task
        for subtask in requirements:
            status = coordinator.get_subtask_status(subtask)
            self.requirement_tracker.track_subtask_completion(task_id, subtask, status)
        
        # Validate completion
        silent_failure = self.requirement_tracker.detect_silent_failure(task_id)
        if silent_failure:
            coordinator.handle_silent_failure(task_id, silent_failure)
            return False
        
        # Post-completion health check
        if not self.validate_system_health(task_id):
            coordinator.handle_health_check_failure(task_id)
            return False
        
        return True
    
    def validate_system_health(self, task_id):
        # Run system health checks relevant to task
        health_checks = self.get_health_checks(task_id)
        
        for check in health_checks:
            if not check():
                return False
        
        return True
```

---

### **7. Governance / Safety Violations**

#### **Trigger**
- Agents bypass agreed boundaries (prod configs, secrets, high-risk code paths)
- Constraints not enforced at tooling level
- Security or compliance violations

#### **Detection Signals**
```python
class GovernanceViolationDetector:
    def __init__(self):
        self.restricted_paths = [
            "/infra/prod/",
            "/config/secrets/",
            "/security/",
            "/production/"
        ]
        self.restricted_operations = [
            "delete_production_data",
            "modify_security_config",
            "access_secrets",
            "deploy_to_production"
        ]
    
    def detect_violation(self, agent_action):
        violations = []
        
        # Check for restricted file access
        for file_path in agent_action.files_modified:
            if self.is_restricted_path(file_path):
                violations.append(f"restricted_file_access: {file_path}")
        
        # Check for restricted operations
        for operation in agent_action.operations:
            if operation in self.restricted_operations:
                violations.append(f"restricted_operation: {operation}")
        
        # Check for privilege escalation
        if agent_action.requires_privilege and not agent.has_privilege:
            violations.append(f"privilege_escalation: {agent_action.requires_privilege}")
        
        return violations
    
    def is_restricted_path(self, file_path):
        return any(restricted in file_path for restricted in self.restricted_paths)
```

#### **Mitigation Strategies**
- **Policy Enforcement:** Tool-level enforcement of governance rules
- **Privilege Management:** Role-based access control for agents
- **Audit Logging:** Complete audit trail of all actions
- **Human Approval:** Required approval for high-risk operations

#### **Implementation Example**
```python
class GovernanceEnforcer:
    def __init__(self):
        self.violation_detector = GovernanceViolationDetector()
        self.approval_queue = []
    
    def enforce_governance(self, agent, action):
        violations = self.violation_detector.detect_violation(action)
        
        if violations:
            # Block the action
            self.log_violation(agent.id, violations)
            self.notify_security_team(agent.id, violations)
            
            # Require human approval for bypass
            if self.request_human_approval(agent, action, violations):
                return self.execute_with_approval(agent, action)
            else:
                raise GovernanceViolation(violations)
        
        # Check privilege requirements
        if action.requires_privilege and not agent.has_privilege:
            raise PrivilegeViolation(f"Agent {agent.id} lacks required privilege")
        
        return self.execute_action(agent, action)
    
    def request_human_approval(self, agent, action, violations):
        approval_request = {
            "agent_id": agent.id,
            "action": action,
            "violations": violations,
            "timestamp": datetime.now(),
            "status": "pending"
        }
        
        self.approval_queue.append(approval_request)
        return self.wait_for_human_approval(approval_request)
```

---

## 📊 **OBSERVABILITY METRICS FRAMEWORK**

### **Coordination-Aware Metrics**

#### **Reliability / Outcome Metrics**
```python
class ReliabilityMetrics:
    def __init__(self):
        self.task_outcomes = []
        self.invariant_violations = []
    
    def track_task_outcome(self, task_id, outcome, details):
        self.task_outcomes.append({
            "task_id": task_id,
            "outcome": outcome,  # success, rollback, needs_human
            "timestamp": datetime.now(),
            "details": details
        })
    
    def calculate_success_rate(self, time_window=3600):
        recent_outcomes = [o for o in self.task_outcomes 
                          if (datetime.now() - o["timestamp"]).seconds < time_window]
        
        if not recent_outcomes:
            return 0.0
        
        successful = len([o for o in recent_outcomes if o["outcome"] == "success"])
        return successful / len(recent_outcomes)
    
    def track_invariant_violation(self, invariant_type, details):
        self.invariant_violations.append({
            "type": invariant_type,
            "timestamp": datetime.now(),
            "details": details
        })
```

#### **Coordination and Communication Metrics**
```python
class CoordinationMetrics:
    def __init__(self):
        self.message_log = []
        self.agent_calls = []
        self.anti_patterns = []
    
    def track_message(self, from_agent, to_agent, message_type):
        self.message_log.append({
            "from": from_agent,
            "to": to_agent,
            "type": message_type,
            "timestamp": datetime.now()
        })
    
    def track_agent_call(self, caller_agent, callee_agent, tool_call):
        self.agent_calls.append({
            "caller": caller_agent,
            "callee": callee_agent,
            "tool_call": tool_call,
            "timestamp": datetime.now()
        })
    
    def detect_anti_patterns(self):
        # Detect ping-pong loops
        recent_messages = self.message_log[-20:]
        ping_pong = self.detect_ping_pong(recent_messages)
        
        # Detect repeated replanning
        replanning = self.detect_replanning(recent_messages)
        
        # Detect retry storms
        retry_storm = self.detect_retry_storm(self.agent_calls[-50:])
        
        return {
            "ping_pong": ping_pong,
            "replanning": replanning,
            "retry_storm": retry_storm
        }
```

#### **Latency and Scalability Metrics**
```python
class LatencyMetrics:
    def __init__(self):
        self.task_latencies = []
        self.phase_latencies = {}
    
    def track_task_latency(self, task_id, phases):
        total_latency = sum(phase["duration"] for phase in phases)
        
        self.task_latencies.append({
            "task_id": task_id,
            "total_latency": total_latency,
            "phases": phases,
            "timestamp": datetime.now()
        })
        
        # Track phase-specific latencies
        for phase in phases:
            phase_name = phase["name"]
            if phase_name not in self.phase_latencies:
                self.phase_latencies[phase_name] = []
            
            self.phase_latencies[phase_name].append(phase["duration"])
    
    def calculate_latency_breakdown(self):
        breakdown = {}
        
        for phase_name, latencies in self.phase_latencies.items():
            breakdown[phase_name] = {
                "average": sum(latencies) / len(latencies),
                "p95": sorted(latencies)[int(len(latencies) * 0.95)],
                "p99": sorted(latencies)[int(len(latencies) * 0.99)]
            }
        
        return breakdown
```

#### **Cost and Efficiency Metrics**
```python
class CostMetrics:
    def __init__(self):
        self.token_usage = []
        self.task_costs = []
    
    def track_token_usage(self, task_id, agent_id, tokens_used, outcome):
        self.token_usage.append({
            "task_id": task_id,
            "agent_id": agent_id,
            "tokens": tokens_used,
            "outcome": outcome,
            "timestamp": datetime.now()
        })
    
    def calculate_waste_metrics(self, time_window=3600):
        recent_usage = [u for u in self.token_usage 
                       if (datetime.now() - u["timestamp"]).seconds < time_window]
        
        if not recent_usage:
            return {"waste_ratio": 0.0, "total_waste": 0}
        
        successful_tokens = sum(u["tokens"] for u in recent_usage 
                               if u["outcome"] == "success")
        total_tokens = sum(u["tokens"] for u in recent_usage)
        
        waste_tokens = total_tokens - successful_tokens
        waste_ratio = waste_tokens / total_tokens if total_tokens > 0 else 0
        
        return {
            "waste_ratio": waste_ratio,
            "total_waste": waste_tokens,
            "successful_tokens": successful_tokens,
            "total_tokens": total_tokens
        }
```

---

## **STALE-READ DETECTION INSTRUMENTATION**

### **Version Tagging and Optimistic Concurrency**

#### **State Version Management**
```python
class StateVersionManager:
    def __init__(self):
        self.version_cache = {}
        self.conflict_tracker = ConflictTracker()
    
    def read_state_with_version(self, resource_path: str, agent_id: str) -> StateSnapshot:
        # Get current version identifier
        current_version = self.get_resource_version(resource_path)
        
        # Create state snapshot with version
        snapshot = StateSnapshot(
            resource_path=resource_path,
            version=current_version,
            timestamp=datetime.now(),
            agent_id=agent_id,
            data=self.read_resource_data(resource_path),
            freshness_score=self.calculate_freshness(resource_path)
        )
        
        # Cache for conflict detection
        self.version_cache[resource_path] = snapshot
        
        return snapshot
    
    def write_state_with_optimistic_concurrency(self, resource_path: str, 
                                               new_data: Any, agent_id: str,
                                               expected_version: str) -> WriteResult:
        # Check for conflicts
        current_version = self.get_resource_version(resource_path)
        
        if current_version != expected_version:
            conflict = self.conflict_tracker.detect_conflict(
                resource_path, expected_version, current_version, agent_id
            )
            
            return WriteResult(
                success=False,
                conflict=conflict,
                current_version=current_version,
                requires_resolution=True
            )
        
        # Perform write with new version
        new_version = self.generate_new_version(resource_path)
        self.write_resource_data(resource_path, new_data, new_version)
        
        return WriteResult(
            success=True,
            new_version=new_version,
            previous_version=expected_version
        )
    
    def get_resource_version(self, resource_path: str) -> str:
        # Use git commit hash for files, timestamps for CI state
        if resource_path.startswith("file://"):
            return self.get_git_hash(resource_path[7:])
        elif resource_path.startswith("ci://"):
            return self.get_ci_state_version(resource_path[5:])
        else:
            return str(int(datetime.now().timestamp() * 1000))
```

#### **Snapshot Isolation for Compound Operations**
```python
class SnapshotIsolationManager:
    def __init__(self):
        self.active_snapshots = {}
        self.compound_operation_tracker = {}
    
    def create_compound_snapshot(self, operation_id: str, 
                                 resource_paths: List[str], 
                                 agent_id: str) -> CompoundSnapshot:
        # Create consistent snapshot across all resources
        snapshot_timestamp = datetime.now()
        resource_snapshots = {}
        
        for resource_path in resource_paths:
            resource_snapshot = StateSnapshot(
                resource_path=resource_path,
                version=self.get_resource_version(resource_path),
                timestamp=snapshot_timestamp,
                agent_id=agent_id,
                data=self.read_resource_data(resource_path),
                snapshot_id=f"{operation_id}_{resource_path.replace('/', '_')}"
            )
            resource_snapshots[resource_path] = resource_snapshot
        
        compound_snapshot = CompoundSnapshot(
            operation_id=operation_id,
            snapshot_id=f"compound_{operation_id}",
            timestamp=snapshot_timestamp,
            agent_id=agent_id,
            resource_snapshots=resource_snapshots,
            isolation_level="serializable"
        )
        
        self.active_snapshots[operation_id] = compound_snapshot
        return compound_snapshot
    
    def validate_compound_operation(self, operation_id: str) -> ValidationResult:
        snapshot = self.active_snapshots.get(operation_id)
        if not snapshot:
            return ValidationResult(valid=False, reason="No active snapshot")
        
        # Check if any resources have changed
        conflicts = []
        for resource_path, resource_snapshot in snapshot.resource_snapshots.items():
            current_version = self.get_resource_version(resource_path)
            if current_version != resource_snapshot.version:
                conflicts.append({
                    "resource_path": resource_path,
                    "expected_version": resource_snapshot.version,
                    "current_version": current_version
                })
        
        if conflicts:
            return ValidationResult(
                valid=False, 
                reason="Resource versions changed",
                conflicts=conflicts
            )
        
        return ValidationResult(valid=True)
    
    def commit_compound_operation(self, operation_id: str) -> CommitResult:
        validation = self.validate_compound_operation(operation_id)
        if not validation.valid:
            return CommitResult(success=False, conflicts=validation.conflicts)
        
        # Apply all changes atomically
        snapshot = self.active_snapshots[operation_id]
        applied_changes = []
        
        for resource_path in snapshot.resource_snapshots:
            # Apply pending changes for this resource
            changes = self.get_pending_changes(operation_id, resource_path)
            if changes:
                new_version = self.apply_changes(resource_path, changes)
                applied_changes.append({
                    "resource_path": resource_path,
                    "new_version": new_version
                })
        
        # Clean up snapshot
        del self.active_snapshots[operation_id]
        
        return CommitResult(
            success=True,
            applied_changes=applied_changes
        )
```

#### **Freshness Monitoring and Latency Detection**
```python
class FreshnessMonitor:
    def __init__(self):
        self.freshness_metrics = {}
        self.latency_tracker = {}
        self.stale_threshold = 300  # 5 minutes
        self.latency_threshold = 30  # 30 seconds
    
    def monitor_state_propagation(self, resource_path: str, 
                                 operation_time: datetime,
                                 propagation_time: datetime):
        latency = (propagation_time - operation_time).total_seconds()
        
        # Track propagation latency
        if resource_path not in self.latency_tracker:
            self.latency_tracker[resource_path] = []
        
        self.latency_tracker[resource_path].append({
            "operation_time": operation_time,
            "propagation_time": propagation_time,
            "latency_seconds": latency
        })
        
        # Check for stale state
        current_time = datetime.now()
        age = (current_time - operation_time).total_seconds()
        
        freshness_score = max(0, 1 - (age / self.stale_threshold))
        
        self.freshness_metrics[resource_path] = {
            "last_operation": operation_time,
            "last_propagation": propagation_time,
            "age_seconds": age,
            "freshness_score": freshness_score,
            "latency_seconds": latency
        }
        
        # Trigger alerts for stale data
        if freshness_score < 0.5:
            self.trigger_stale_data_alert(resource_path, freshness_score)
        
        # Trigger alerts for high latency
        if latency > self.latency_threshold:
            self.trigger_latency_alert(resource_path, latency)
    
    def calculate_freshness_score(self, resource_path: str) -> float:
        if resource_path not in self.freshness_metrics:
            return 1.0  # Assume fresh if no metrics
        
        metrics = self.freshness_metrics[resource_path]
        return metrics["freshness_score"]
    
    def detect_stale_read_patterns(self, agent_id: str, 
                                  time_window: int = 3600) -> List[StaleReadPattern]:
        patterns = []
        current_time = datetime.now()
        
        # Look for agents consistently reading stale data
        agent_reads = self.get_agent_reads(agent_id, time_window)
        
        stale_reads = [read for read in agent_reads 
                      if read.freshness_score < 0.7]
        
        if len(stale_reads) / len(agent_reads) > 0.3:  # >30% stale reads
            patterns.append(StaleReadPattern(
                agent_id=agent_id,
                pattern_type="high_stale_read_ratio",
                stale_read_ratio=len(stale_reads) / len(agent_reads),
                affected_resources=list(set(read.resource_path for read in stale_reads)),
                time_window=time_window
            ))
        
        return patterns
```

---

## **WATCHDOG AGENTS AND STOPPING RULES**

### **Watchdog Agent Implementation**

#### **Core Responsibilities**
```python
class SwarmWatchdog:
    def __init__(self):
        self.global_limits = {
            "max_turns": 50,
            "max_tokens": 500000,
            "max_elapsed_time": 3600,  # 1 hour
            "max_coordination_rounds": 10
        }
        
        self.anti_pattern_detectors = {
            "ping_pong": PingPongDetector(max_exchanges=3),
            "replanning": ReplanningDetector(max_replans=5),
            "retry_storm": RetryStormDetector(max_retries_per_minute=10)
        }
        
        self.safety_enforcer = GovernanceEnforcer()
        self.event_stream = []
    
    def monitor_task(self, task_id):
        task_start = datetime.now()
        
        while not self.is_task_complete(task_id):
            # Process event stream
            current_event = self.get_next_event(task_id)
            
            if current_event:
                self.event_stream.append(current_event)
                self.check_global_limits(task_id, task_start)
                self.check_anti_patterns(task_id)
                self.check_safety_violations(current_event)
            
            # Check stopping conditions
            if self.should_stop_task(task_id, task_start):
                self.stop_task(task_id)
                break
            
            time.sleep(1)  # Check every second
    
    def check_global_limits(self, task_id, start_time):
        elapsed = (datetime.now() - start_time).seconds
        
        if elapsed > self.global_limits["max_elapsed_time"]:
            self.trigger_stop(task_id, "time_limit_exceeded")
        
        if self.get_token_count(task_id) > self.global_limits["max_tokens"]:
            self.trigger_stop(task_id, "token_limit_exceeded")
        
        if self.get_turn_count(task_id) > self.global_limits["max_turns"]:
            self.trigger_stop(task_id, "turn_limit_exceeded")
```

#### **Stopping Rules Implementation**

##### **Loop Guard**
```python
class LoopGuard:
    def __init__(self, max_exchanges=3):
        self.max_exchanges = max_exchanges
        self.message_pairs = {}
    
    def check_loop_guard(self, task_id, from_agent, to_agent):
        pair_key = f"{from_agent}_{to_agent}"
        
        if pair_key not in self.message_pairs:
            self.message_pairs[pair_key] = 0
        
        self.message_pairs[pair_key] += 1
        
        if self.message_pairs[pair_key] > self.max_exchanges:
            return f"loop_guard_triggered_{pair_key}"
        
        return None
```

##### **Turn Limit**
```python
class TurnLimit:
    def __init__(self, max_turns=50):
        self.max_turns = max_turns
        self.turn_count = {}
    
    def check_turn_limit(self, task_id):
        if task_id not in self.turn_count:
            self.turn_count[task_id] = 0
        
        self.turn_count[task_id] += 1
        
        if self.turn_count[task_id] > self.max_turns:
            return f"turn_limit_exceeded_{task_id}"
        
        return None
```

##### **Failure Threshold**
```python
class FailureThreshold:
    def __init__(self, max_failures=3):
        self.max_failures = max_failures
        self.failure_counts = {}
    
    def check_failure_threshold(self, task_id, failure_type):
        if task_id not in self.failure_counts:
            self.failure_counts[task_id] = {}
        
        if failure_type not in self.failure_counts[task_id]:
            self.failure_counts[task_id][failure_type] = 0
        
        self.failure_counts[task_id][failure_type] += 1
        
        if self.failure_counts[task_id][failure_type] > self.max_failures:
            return f"failure_threshold_exceeded_{failure_type}"
        
        return None
```

##### **Safety Guard**
```python
class SafetyGuard:
    def __init__(self):
        self.restricted_paths = [
            "/infra/prod/",
            "/config/secrets/",
            "/security/"
        ]
        self.restricted_operations = [
            "delete_production_data",
            "modify_security_config"
        ]
    
    def check_safety_guard(self, action):
        violations = []
        
        # Check restricted paths
        for file_path in action.files_modified:
            if any(restricted in file_path for restricted in self.restricted_paths):
                violations.append(f"restricted_path_access: {file_path}")
        
        # Check restricted operations
        for operation in action.operations:
            if operation in self.restricted_operations:
                violations.append(f"restricted_operation: {operation}")
        
        if violations:
            return f"safety_guard_triggered: {violations}"
        
        return None
```

---

## 🧪 **ADVERSARIAL TESTS FOR NETWORK PARTITIONS**

### **Test Harness Implementation**

#### **Tool/API Degradation Tests**
```python
class ToolDegradationTest:
    def __init__(self):
        self.degradation_scenarios = {
            "latency": {"delay_range": (1, 10), "failure_rate": 0.1},
            "timeout": {"timeout_range": (5, 30), "failure_rate": 0.3},
            "intermittent": {"failure_rate": 0.4, "recovery_time": 60}
        }
    
    def run_degradation_test(self, scenario_name, task):
        scenario = self.degradation_scenarios[scenario_name]
        
        # Inject degradation
        with ToolDegradationContext(scenario):
            result = self.execute_swarm_task(task)
        
        # Verify graceful degradation
        self.verify_degradation_response(result, scenario)
        
        return result
    
    def verify_degradation_response(self, result, scenario):
        # Check for retry storms
        if result.tool_calls > 20:
            raise AssertionError("Retry storm detected")
        
        # Check for proper error handling
        if not result.errors_reported:
            raise AssertionError("Errors not properly reported")
        
        # Check for graceful degradation
        if result.partial_completion and not result.partial_completion_reported:
            raise AssertionError("Partial completion not reported")
```

#### **State Partition Tests**
```python
class StatePartitionTest:
    def __init__(self):
        self.partition_scenarios = [
            "head_vs_head_minus_1",
            "different_branches",
            "stale_vs_fresh_context"
        ]
    
    def run_partition_test(self, scenario_name, task):
        # Create partitioned state
        partitioned_state = self.create_partitioned_state(scenario_name)
        
        # Assign different states to different agents
        with StatePartitionContext(partitioned_state):
            result = self.execute_swarm_task(task)
        
        # Verify conflict detection
        self.verify_conflict_handling(result)
        
        return result
    
    def verify_conflict_handling(self, result):
        # Check for merge conflicts
        if result.merge_conflicts and not result.conflicts_resolved:
            raise AssertionError("Merge conflicts not resolved")
        
        # Check for invariant violations
        if result.invariant_violations and not result.violations_handled:
            raise AssertionError("Invariant violations not handled")
        
        # Check for data consistency
        if not self.verify_data_consistency(result):
            raise AssertionError("Data consistency issues detected")
```

#### **One-Agent Blackhole Tests**
```python
class AgentBlackholeTest:
    def __init__(self):
        self.blackhole_scenarios = [
            "tester_unavailable",
            "reviewer_unavailable",
            "implementer_unavailable"
        ]
    
    def run_blackhole_test(self, scenario_name, task):
        # Create blackhole for specific agent type
        with AgentBlackholeContext(scenario_name):
            result = self.execute_swarm_task(task)
        
        # Verify graceful degradation
        self.verify_blackhole_response(result, scenario_name)
        
        return result
    
    def verify_blackhole_response(self, result, scenario_name):
        # Check for graceful degradation
        if not result.graceful_degradation:
            raise AssertionError("No graceful degradation detected")
        
        # Check for human escalation
        if not result.human_escalation:
            raise AssertionError("No human escalation triggered")
        
        # Check for partial completion reporting
        if result.partial_completion and not result.partial_completion_reported:
            raise AssertionError("Partial completion not reported")
```

---

## 📈 **COORDINATION OVERHEAD AND SCALABILITY LIMITS**

### **Overhead Measurement Framework**

#### **Per-Task Overhead Analysis**
```python
class OverheadAnalyzer:
    def __init__(self):
        self.task_metrics = []
    
    def analyze_task_overhead(self, task_id, agent_count, messages, tool_calls, tokens, latency):
        overhead_metrics = {
            "task_id": task_id,
            "agent_count": agent_count,
            "messages": messages,
            "tool_calls": tool_calls,
            "tokens": tokens,
            "latency": latency,
            "messages_per_agent": messages / agent_count,
            "tokens_per_agent": tokens / agent_count,
            "coordination_efficiency": self.calculate_coordination_efficiency(messages, tool_calls)
        }
        
        self.task_metrics.append(overhead_metrics)
        return overhead_metrics
    
    def calculate_coordination_efficiency(self, messages, tool_calls):
        # Ratio of coordination messages to productive tool calls
        coordination_messages = messages - tool_calls
        return tool_calls / messages if messages > 0 else 0
    
    def generate_scaling_report(self):
        report = {
            "scaling_analysis": self.analyze_scaling_curves(),
            "efficiency_analysis": self.analyze_efficiency_trends(),
            "recommendations": self.generate_recommendations()
        }
        
        return report
```

#### **Scaling Curve Analysis**
```python
class ScalingAnalyzer:
    def __init__(self):
        self.scaling_data = []
    
    def run_scaling_test(self, agent_counts, task_distribution):
        results = {}
        
        for agent_count in agent_counts:
            # Run test with specified agent count
            result = self.run_swarm_with_agents(agent_count, task_distribution)
            
            results[agent_count] = {
                "latency": result.latency,
                "tokens": result.tokens,
                "success_rate": result.success_rate,
                "rollback_rate": result.rollback_rate
            }
            
            self.scaling_data.append({
                "agent_count": agent_count,
                "result": result
            })
        
        return results
    
    def analyze_scaling_curves(self):
        # Analyze how metrics scale with agent count
        scaling_curves = {}
        
        for metric in ["latency", "tokens", "success_rate", "rollback_rate"]:
            curve_data = []
            
            for data_point in self.scaling_data:
                agent_count = data_point["agent_count"]
                value = data_point["result"][metric]
                curve_data.append((agent_count, value))
            
            # Fit curve and analyze scaling behavior
            scaling_curves[metric] = self.fit_scaling_curve(curve_data)
        
        return scaling_curves
    
    def fit_scaling_curve(self, data):
        # Simple linear regression for demonstration
        x = [point[0] for point in data]
        y = [point[1] for point in data]
        
        # Calculate correlation and trend
        correlation = self.calculate_correlation(x, y)
        trend = "increasing" if correlation > 0 else "decreasing"
        
        return {
            "correlation": correlation,
            "trend": trend,
            "data_points": data
        }
```

---

## 🎯 **IMPLEMENTATION ROADMAP**

### **Phase 1: Failure Mode Detection (Weeks 1-4)**
- [ ] Implement all failure mode detectors
- [ ] Create detection signal framework
- [ ] Build basic mitigation strategies
- [ ] Establish failure logging and alerting

### **Phase 2: Observability Framework (Weeks 5-8)**
- [ ] Implement coordination-aware metrics
- [ ] Build distributed tracing system
- [ ] Create real-time monitoring dashboard
- [ ] Establish alerting for anti-patterns

### **Phase 3: Watchdog Implementation (Weeks 9-12)**
- [ ] Build core watchdog agent
- [ ] Implement all stopping rules
- [ ] Create human escalation workflows
- [ ] Test and validate watchdog effectiveness

### **Phase 4: Adversarial Testing (Weeks 13-16)**
- [ ] Build comprehensive test harness
- [ ] Implement all adversarial scenarios
- [ ] Create automated resilience testing
- [ ] Establish continuous resilience validation

---

## 🚨 **SUCCESS CRITERIA**

### **Failure Mode Coverage**
- **100% of defined failure modes** have detection signals
- **95% of detected failures** have automated mitigation
- **100% of critical failures** trigger human escalation
- **<5 minutes** mean time to detection for all failures

### **Observability Coverage**
- **100% of agent interactions** are traced
- **Real-time detection** of all coordination anti-patterns
- **Complete audit trail** for all swarm activities
- **Automated alerting** for all critical metrics

### **Resilience Validation**
- **All adversarial scenarios** pass automated tests
- **<10% performance degradation** under failure conditions
- **Zero silent failures** in production environment
- **Complete recovery** from all simulated failures

---

**Last Updated:** 2026-01-26  
**Next Review:** After Phase 1 implementation  
**Owner:** MERID Swarm Reliability Team  
**Target:** Production-ready failure-resilient development swarm

---

## 📐 **SIMPLE CLOSED-FORM MODELS**

### **1. Ring Resilience with Uniform Capacity and Load Redistribution**

#### **Deterministic Threshold Model**
```python
class SimpleRingResilienceModel:
    def __init__(self):
        self.critical_alpha = 0.5  # α_c = 1/2 for ring topology
    
    def calculate_neighbor_load_after_failure(self, L: float) -> float:
        """Calculate L' = L + L/2 = 3L/2 after neighbor failure in ring"""
        return 1.5 * L
    
    def check_overload_condition(self, alpha: float) -> bool:
        """Check if 3/2 L > (1+α)L => α < 1/2"""
        return alpha < self.critical_alpha
    
    def calculate_per_neighbor_failure_prob(self, alpha: float, 
                                             smooth: bool = False) -> float:
        """Calculate q_r(α) - step function or smooth linear approximation"""
        
        if not smooth:
            # Step function: q_r = 1 if α < 1/2, 0 otherwise
            return 1.0 if alpha < self.critical_alpha else 0.0
        else:
            # Smooth linear: q_r = max(0, 1 - 2α)
            return max(0.0, 1.0 - 2.0 * alpha)
    
    def calculate_branching_factor(self, alpha: float, smooth: bool = False) -> float:
        """Calculate branching factor b_r = 2 * q_r for ring (degree = 2)"""
        
        q_r = self.calculate_per_neighbor_failure_prob(alpha, smooth)
        return 2.0 * q_r
    
    def calculate_expected_cascade_size(self, alpha: float, 
                                        smooth: bool = False) -> float:
        """Calculate E[C_ring] using Galton-Watson approximation"""
        
        b_r = self.calculate_branching_factor(alpha, smooth)
        
        if b_r >= 1.0:
            return float('inf')  # Unbounded cascade
        else:
            return 1.0 / (1.0 - b_r)
    
    def calculate_resilience_score(self, alpha: float, smooth: bool = False) -> float:
        """Calculate R_ring(α) - step function or smooth linear"""
        
        if not smooth:
            # Step function: R = 0 if α < 1/2, 1 otherwise
            return 0.0 if alpha < self.critical_alpha else 1.0
        else:
            # Smooth linear: R = 1 - 2q_r = min(1, max(0, 4α - 1))
            q_r = self.calculate_per_neighbor_failure_prob(alpha, smooth)
            resilience = 1.0 - 2.0 * q_r
            return max(0.0, min(1.0, resilience))
    
    def analyze_capacity_margin_effect(self) -> Dict[str, Any]:
        """Analyze effect of capacity margin α on ring resilience"""
        
        alpha_range = np.linspace(0.1, 1.0, 100)
        
        step_results = []
        smooth_results = []
        
        for alpha in alpha_range:
            step_results.append({
                "alpha": alpha,
                "resilience_step": self.calculate_resilience_score(alpha, smooth=False),
                "cascade_size_step": self.calculate_expected_cascade_size(alpha, smooth=False),
                "resilience_smooth": self.calculate_resilience_score(alpha, smooth=True),
                "cascade_size_smooth": self.calculate_expected_cascade_size(alpha, smooth=True)
            })
        
        return {
            "critical_alpha": self.critical_alpha,
            "interpretation": "α < 0.5 leads to deterministic cascade, α ≥ 0.5 provides resilience",
            "alpha_range_results": step_results,
            "key_points": {
                "alpha_0_25": {"resilience": 0.0, "interpretation": "No resilience"},
                "alpha_0_5": {"resilience": 1.0, "interpretation": "Full resilience"},
                "alpha_0_75": {"resilience": 1.0, "interpretation": "Saturated resilience"}
            }
        }
```

### **2. Mesh Resilience with Degree k (Uniform Capacity)**

#### **Generalized Degree-Dependent Model**
```python
class SimpleMeshResilienceModel:
    def __init__(self):
        self.default_degree = 4  # Default mesh degree
    
    def calculate_neighbor_load_after_failure(self, L: float, k: int) -> float:
        """Calculate L' = L + L/k = (1 + 1/k)L for mesh with degree k"""
        return (1.0 + 1.0 / k) * L
    
    def check_overload_condition(self, alpha: float, k: int) -> bool:
        """Check if (1 + 1/k)L > (1+α)L => α < 1/k"""
        return alpha < (1.0 / k)
    
    def calculate_per_neighbor_failure_prob(self, alpha: float, k: int, 
                                             smooth: bool = False) -> float:
        """Calculate q_m(α,k) - step function or smooth linear approximation"""
        
        critical_alpha = 1.0 / k
        
        if not smooth:
            # Step function: q_m = 1 if α < 1/k, 0 otherwise
            return 1.0 if alpha < critical_alpha else 0.0
        else:
            # Smooth linear: q_m = max(0, 1 - kα)
            return max(0.0, 1.0 - k * alpha)
    
    def calculate_branching_factor(self, alpha: float, k: int, 
                                   smooth: bool = False) -> float:
        """Calculate branching factor b_m = k * q_m for mesh with degree k"""
        
        q_m = self.calculate_per_neighbor_failure_prob(alpha, k, smooth)
        return k * q_m
    
    def calculate_expected_cascade_size(self, alpha: float, k: int, 
                                        smooth: bool = False) -> float:
        """Calculate E[C_mesh] using Galton-Watson approximation"""
        
        b_m = self.calculate_branching_factor(alpha, k, smooth)
        
        if b_m >= 1.0:
            return float('inf')  # Unbounded cascade
        else:
            return 1.0 / (1.0 - b_m)
    
    def calculate_resilience_score(self, alpha: float, k: int, 
                                   smooth: bool = False) -> float:
        """Calculate R_mesh(α,k) - step function or smooth linear"""
        
        if not smooth:
            # Step function: R = 0 if α < 1/k, 1 otherwise
            critical_alpha = 1.0 / k
            return 0.0 if alpha < critical_alpha else 1.0
        else:
            # Smooth linear: R = 1 - k*q_m
            q_m = self.calculate_per_neighbor_failure_prob(alpha, k, smooth)
            resilience = 1.0 - k * q_m
            return max(0.0, min(1.0, resilience))
    
    def compare_ring_mesh_resilience(self, alpha: float, k: int = None) -> Dict[str, Any]:
        """Compare ring vs mesh resilience for given parameters"""
        
        if k is None:
            k = self.default_degree
        
        ring_model = SimpleRingResilienceModel()
        
        # Calculate resilience for both topologies
        ring_resilience_step = ring_model.calculate_resilience_score(alpha, smooth=False)
        ring_resilience_smooth = ring_model.calculate_resilience_score(alpha, smooth=True)
        
        mesh_resilience_step = self.calculate_resilience_score(alpha, k, smooth=False)
        mesh_resilience_smooth = self.calculate_resilience_score(alpha, k, smooth=True)
        
        # Calculate critical thresholds
        ring_critical = 0.5
        mesh_critical = 1.0 / k
        
        return {
            "parameters": {"alpha": alpha, "k": k},
            "critical_thresholds": {
                "ring": ring_critical,
                "mesh": mesh_critical,
                "interpretation": f"Mesh threshold ({mesh_critical:.3f}) {'<' if mesh_critical < ring_critical else '>'} ring threshold ({ring_critical})"
            },
            "step_model": {
                "ring_resilience": ring_resilience_step,
                "mesh_resilience": mesh_resilience_step,
                "more_resilient": "ring" if ring_resilience_step > mesh_resilience_step else "mesh"
            },
            "smooth_model": {
                "ring_resilience": ring_resilience_smooth,
                "mesh_resilience": mesh_resilience_smooth,
                "more_resilient": "ring" if ring_resilience_smooth > mesh_resilience_smooth else "mesh"
            },
            "analysis": self.interpret_resilience_comparison(alpha, k, ring_resilience_smooth, mesh_resilience_smooth)
        }
    
    def interpret_resilience_comparison(self, alpha: float, k: int, 
                                       ring_r: float, mesh_r: float) -> str:
        """Interpret ring vs mesh resilience comparison"""
        
        ring_critical = 0.5
        mesh_critical = 1.0 / k
        
        if alpha < mesh_critical:
            return f"Both vulnerable (α {alpha} < mesh threshold {mesh_critical:.3f})"
        elif alpha < ring_critical:
            return f"Mesh vulnerable, ring resilient (mesh threshold {mesh_critical:.3f} < α {alpha} < ring threshold {ring_critical})"
        else:
            return f"Both resilient (α {alpha} > ring threshold {ring_critical})"
```

### **3. Targeted Attack Resilience Analysis**

#### **High-Degree Node Targeting Model**
```python
class TargetedAttackResilienceModel:
    def __init__(self):
        self.ring_model = SimpleRingResilienceModel()
        self.mesh_model = SimpleMeshResilienceModel()
    
    def calculate_targeted_mesh_resilience(self, alpha: float, hub_degree: int, 
                                          smooth: bool = False) -> float:
        """Calculate mesh resilience under targeted attack on hub nodes"""
        
        # Targeted nodes have degree ŷk >> k, use hub degree for calculation
        critical_alpha = 1.0 / hub_degree
        
        if not smooth:
            # Step function with hub degree threshold
            return 0.0 if alpha < critical_alpha else 1.0
        else:
            # Smooth linear with hub degree
            q_m_targ = max(0.0, 1.0 - hub_degree * alpha)
            resilience = 1.0 - hub_degree * q_m_targ
            return max(0.0, min(1.0, resilience))
    
    def analyze_targeted_vulnerability(self, alpha: float, k: int = 4, 
                                     hub_multiplier: float = 2.0) -> Dict[str, Any]:
        """Analyze vulnerability under targeted vs random attacks"""
        
        hub_degree = int(k * hub_multiplier)
        
        # Random attack resilience
        ring_random = self.ring_model.calculate_resilience_score(alpha, smooth=True)
        mesh_random = self.mesh_model.calculate_resilience_score(alpha, k, smooth=True)
        
        # Targeted attack resilience
        ring_targeted = ring_random  # Ring: targeted ≈ random
        mesh_targeted = self.calculate_targeted_mesh_resilience(alpha, hub_degree, smooth=True)
        
        # Calculate degradation
        ring_degradation = ring_random - ring_targeted
        mesh_degradation = mesh_random - mesh_targeted
        
        # Critical thresholds
        ring_critical = 0.5
        mesh_random_critical = 1.0 / k
        mesh_targeted_critical = 1.0 / hub_degree
        
        return {
            "parameters": {
                "alpha": alpha,
                "k": k,
                "hub_degree": hub_degree,
                "hub_multiplier": hub_multiplier
            },
            "critical_thresholds": {
                "ring_random": ring_critical,
                "mesh_random": mesh_random_critical,
                "mesh_targeted": mesh_targeted_critical,
                "interpretation": f"Targeted attacks lower mesh threshold from {mesh_random_critical:.3f} to {mesh_targeted_critical:.3f}"
            },
            "random_attacks": {
                "ring_resilience": ring_random,
                "mesh_resilience": mesh_random,
                "more_resilient": "ring" if ring_random > mesh_random else "mesh"
            },
            "targeted_attacks": {
                "ring_resilience": ring_targeted,
                "mesh_resilience": mesh_targeted,
                "more_resilient": "ring" if ring_targeted > mesh_targeted else "mesh"
            },
            "vulnerability_analysis": {
                "ring_degradation": ring_degradation,
                "mesh_degradation": mesh_degradation,
                "more_vulnerable_to_targeting": "mesh" if mesh_degradation > ring_degradation else "ring",
                "degradation_ratio": mesh_degradation / ring_degradation if ring_degradation > 0 else float('inf')
            },
            "qualitative_assessment": "Ring maintains resilience longer under targeting; mesh collapses at smaller perturbations when attacks concentrate on hubs"
        }
```

### **4. Probabilistic Load Redistribution Model**

#### **Random Load Splitting Analysis**
```python
class ProbabilisticRedistributionModel:
    def __init__(self):
        self.distribution_types = ["uniform", "beta", "empirical"]
    
    def calculate_failure_probability_uniform(self, alpha: float) -> float:
        """Calculate q_prob(α) for uniform distribution of load fractions"""
        
        # For uniform distribution on [0, 2/k] (since sum of k fractions = 1)
        # Each neighbor gets X ~ Uniform(0, 2/k) approximately
        # P(X > α) = max(0, 1 - k*α/2)
        return max(0.0, 1.0 - 0.5 * alpha)  # Simplified for k=2, adjust for general k
    
    def calculate_failure_probability_beta(self, alpha: float, a: float = 2.0, 
                                          b: float = 2.0) -> float:
        """Calculate q_prob(α) for Beta distribution of load fractions"""
        
        # Beta(a,b) distribution on [0,1], scaled to load fractions
        # P(X > α) = 1 - F_X(α) where F_X is Beta CDF
        try:
            from scipy.stats import beta
            
            # Scale alpha to [0,1] range for Beta distribution
            scaled_alpha = min(1.0, max(0.0, alpha * 2))  # Rough scaling
            
            survival_prob = 1.0 - beta.cdf(scaled_alpha, a, b)
            return survival_prob
        except ImportError:
            # Fallback to simple approximation if scipy not available
            return max(0.0, 1.0 - alpha)
    
    def calculate_branching_factor_probabilistic(self, alpha: float, k: int, 
                                                 distribution: str = "uniform") -> float:
        """Calculate branching factor b_prob = k * q_prob(α)"""
        
        if distribution == "uniform":
            q_prob = self.calculate_failure_probability_uniform(alpha)
        elif distribution == "beta":
            q_prob = self.calculate_failure_probability_beta(alpha)
        else:
            raise ValueError(f"Unknown distribution: {distribution}")
        
        return k * q_prob
    
    def calculate_expected_cascade_probabilistic(self, alpha: float, k: int, 
                                                  distribution: str = "uniform") -> float:
        """Calculate E[C_mesh,prob] = 1/(1 - k*q_prob(α)) for b_prob < 1"""
        
        b_prob = self.calculate_branching_factor_probabilistic(alpha, k, distribution)
        
        if b_prob >= 1.0:
            return float('inf')
        else:
            return 1.0 / (1.0 - b_prob)
    
    def calculate_resilience_probabilistic(self, alpha: float, k: int, 
                                          distribution: str = "uniform") -> float:
        """Calculate R_mesh,prob(α,k) = 1 - k*q_prob(α)"""
        
        if distribution == "uniform":
            q_prob = self.calculate_failure_probability_uniform(alpha)
        elif distribution == "beta":
            q_prob = self.calculate_failure_probability_beta(alpha)
        else:
            raise ValueError(f"Unknown distribution: {distribution}")
        
        resilience = 1.0 - k * q_prob
        return max(0.0, min(1.0, resilience))
    
    def compare_deterministic_vs_probabilistic(self, alpha: float, k: int) -> Dict[str, Any]:
        """Compare deterministic vs probabilistic load redistribution models"""
        
        mesh_model = SimpleMeshResilienceModel()
        
        # Deterministic model
        det_resilience = mesh_model.calculate_resilience_score(alpha, k, smooth=True)
        det_cascade = mesh_model.calculate_expected_cascade_size(alpha, k, smooth=True)
        
        # Probabilistic models
        uniform_resilience = self.calculate_resilience_probabilistic(alpha, k, "uniform")
        uniform_cascade = self.calculate_expected_cascade_probabilistic(alpha, k, "uniform")
        
        beta_resilience = self.calculate_resilience_probabilistic(alpha, k, "beta")
        beta_cascade = self.calculate_expected_cascade_probabilistic(alpha, k, "beta")
        
        return {
            "parameters": {"alpha": alpha, "k": k},
            "deterministic": {
                "resilience": det_resilience,
                "cascade_size": det_cascade,
                "interpretation": "Equal load split assumption"
            },
            "probabilistic_uniform": {
                "resilience": uniform_resilience,
                "cascade_size": uniform_cascade,
                "interpretation": "Random uniform load distribution"
            },
            "probabilistic_beta": {
                "resilience": beta_resilience,
                "cascade_size": beta_cascade,
                "interpretation": "Beta-distributed load fractions"
            },
            "comparison": {
                "most_resilient": max([
                    ("deterministic", det_resilience),
                    ("uniform", uniform_resilience),
                    ("beta", beta_resilience)
                ], key=lambda x: x[1])[0],
                "resilience_range": max(det_resilience, uniform_resilience, beta_resilience) - min(det_resilience, uniform_resilience, beta_resilience)
            }
        }
```

### **5. Capacity Margin Effect Analysis**

#### **α-Parameter Impact on Resilience**
```python
class CapacityMarginAnalyzer:
    def __init__(self):
        self.ring_model = SimpleRingResilienceModel()
        self.mesh_model = SimpleMeshResilienceModel()
    
    def analyze_ring_capacity_margin(self) -> Dict[str, Any]:
        """Detailed analysis of capacity margin α effect on ring resilience"""
        
        # Key α values for ring
        critical_points = {
            "no_resilience": 0.25,    # R = 0
            "critical_threshold": 0.5,  # R = 1 (step), linear transition point
            "full_resilience": 0.75     # R = 1 (saturated)
        }
        
        results = {}
        
        for point_name, alpha in critical_points.items():
            resilience_step = self.ring_model.calculate_resilience_score(alpha, smooth=False)
            resilience_smooth = self.ring_model.calculate_resilience_score(alpha, smooth=True)
            cascade_step = self.ring_model.calculate_expected_cascade_size(alpha, smooth=False)
            cascade_smooth = self.ring_model.calculate_expected_cascade_size(alpha, smooth=True)
            
            results[point_name] = {
                "alpha": alpha,
                "resilience_step": resilience_step,
                "resilience_smooth": resilience_smooth,
                "cascade_size_step": cascade_step,
                "cascade_size_smooth": cascade_smooth,
                "interpretation": self.interpret_alpha_point(alpha, resilience_smooth)
            }
        
        # Generate full curve
        alpha_range = np.linspace(0.1, 1.0, 100)
        resilience_curve = []
        cascade_curve = []
        
        for alpha in alpha_range:
            resilience_curve.append(self.ring_model.calculate_resilience_score(alpha, smooth=True))
            cascade_curve.append(self.ring_model.calculate_expected_cascade_size(alpha, smooth=True))
        
        return {
            "critical_points": results,
            "resilience_curve": list(zip(alpha_range, resilience_curve)),
            "cascade_curve": list(zip(alpha_range, cascade_curve)),
            "interpretation": {
                "threshold_behavior": "α < 0.5 leads to cascade propagation, α ≥ 0.5 provides resilience",
                "linear_region": "0.25 < α < 0.5: resilience rises linearly from 0 to 1",
                "saturation_region": "α > 0.5: resilience saturated at 1",
                "merid_interpretation": "α represents safety margin in agent capacity (time, tokens, error budget) before behavior degrades"
            }
        }
    
    def interpret_alpha_point(self, alpha: float, resilience: float) -> str:
        """Interpret specific α value for MERID swarm design"""
        
        if alpha < 0.25:
            return "Insufficient capacity margin - high cascade risk"
        elif alpha < 0.5:
            return "Moderate capacity margin - partial resilience"
        elif alpha < 0.75:
            return "Good capacity margin - full resilience achieved"
        else:
            return "Excellent capacity margin - resilience saturated"
    
    def generate_capacity_recommendations(self, target_resilience: float = 0.8) -> Dict[str, Any]:
        """Generate capacity margin recommendations for target resilience"""
        
        # Find minimum α for target resilience
        alpha_range = np.linspace(0.1, 1.0, 1000)
        
        for alpha in alpha_range:
            resilience = self.ring_model.calculate_resilience_score(alpha, smooth=True)
            if resilience >= target_resilience:
                min_alpha = alpha
                break
        else:
            min_alpha = 1.0
        
        # Calculate safety factors
        safety_factor = min_alpha / 0.5  # Relative to critical threshold
        
        return {
            "target_resilience": target_resilience,
            "minimum_alpha": min_alpha,
            "safety_factor": safety_factor,
            "recommendations": {
                "minimum_margin": f"α ≥ {min_alpha:.3f} required for {target_resilience:.1%} resilience",
                "safety_margin": f"Safety factor of {safety_factor:.2f} above critical threshold",
                "merid_guidance": "Allocate extra capacity for agents based on calculated α to ensure swarm stability"
            },
            "cost_benefit_analysis": self.analyze_capacity_cost_benefit(min_alpha)
        }
    
    def analyze_capacity_cost_benefit(self, alpha: float) -> Dict[str, Any]:
        """Analyze cost-benefit of capacity margin investment"""
        
        resilience = self.ring_model.calculate_resilience_score(alpha, smooth=True)
        cascade_size = self.ring_model.calculate_expected_cascade_size(alpha, smooth=True)
        
        # Simple cost model: cost proportional to α, benefit proportional to resilience
        cost_factor = alpha  # Normalized cost
        benefit_factor = resilience  # Normalized benefit
        
        # Efficiency metric
        efficiency = benefit_factor / cost_factor if cost_factor > 0 else 0
        
        return {
            "alpha": alpha,
            "resilience": resilience,
            "cascade_size": cascade_size,
            "cost_factor": cost_factor,
            "benefit_factor": benefit_factor,
            "efficiency": efficiency,
            "interpretation": self.interpret_efficiency(efficiency)
        }
    
    def interpret_efficiency(self, efficiency: float) -> str:
        """Interpret capacity investment efficiency"""
        
        if efficiency > 2.0:
            return "Highly efficient capacity investment"
        elif efficiency > 1.5:
            return "Good efficiency - recommended investment level"
        elif efficiency > 1.0:
            return "Moderate efficiency - acceptable investment"
        else:
            return "Low efficiency - consider alternative resilience strategies"
```

---

## 📐 **SIMPLE ANALYTIC SCAFFOLDING MODELS**

### **1. Mesh Resilience with Uniform Capacity (Degree k)**

#### **Flow-Style Model with Equal Load Splitting**
```python
class MeshResilienceFlowModel:
    def __init__(self):
        self.default_degree = 4  # Default mesh degree
    
    def calculate_neighbor_load_after_failure(self, L: float, k: int) -> float:
        """Calculate L' = L + L/k = (1 + 1/k)L for mesh with degree k"""
        return (1.0 + 1.0 / k) * L
    
    def check_overload_condition(self, alpha: float, k: int) -> bool:
        """Check if (1 + 1/k)L > (1+α)L => α < 1/k"""
        return alpha < (1.0 / k)
    
    def calculate_per_neighbor_failure_prob(self, alpha: float, k: int, 
                                             smooth: bool = False) -> float:
        """Calculate q_m(α,k) - step function or smooth linear approximation"""
        
        critical_alpha = 1.0 / k
        
        if not smooth:
            # Step function: q_m = 1 if α < 1/k, 0 otherwise
            return 1.0 if alpha < critical_alpha else 0.0
        else:
            # Smooth linear: q_m = max(0, 1 - kα)
            return max(0.0, 1.0 - k * alpha)
    
    def calculate_branching_factor(self, alpha: float, k: int, 
                                   smooth: bool = False) -> float:
        """Calculate branching factor b_m = k * q_m for mesh with degree k"""
        
        q_m = self.calculate_per_neighbor_failure_prob(alpha, k, smooth)
        return k * q_m
    
    def calculate_expected_cascade_size(self, alpha: float, k: int, 
                                        smooth: bool = False) -> float:
        """Calculate E[C_mesh] using branching process approximation"""
        
        b_m = self.calculate_branching_factor(alpha, k, smooth)
        
        if b_m >= 1.0:
            return float('inf')  # Unbounded cascade
        else:
            return 1.0 / (1.0 - b_m)
    
    def calculate_resilience_score(self, alpha: float, k: int, 
                                   smooth: bool = False) -> float:
        """Calculate R_mesh(α,k) - step function or smooth linear"""
        
        if not smooth:
            # Step function: R = 0 if α < 1/k, 1 otherwise
            critical_alpha = 1.0 / k
            return 0.0 if alpha < critical_alpha else 1.0
        else:
            # Smooth linear: R = 1 - k*q_m
            q_m = self.calculate_per_neighbor_failure_prob(alpha, k, smooth)
            resilience = 1.0 - k * q_m
            return max(0.0, min(1.0, resilience))
    
    def analyze_critical_capacity_margin(self, k: int = None) -> Dict[str, Any]:
        """Analyze critical capacity margin for mesh topology"""
        
        if k is None:
            k = self.default_degree
        
        critical_alpha = 1.0 / k
        
        # Generate analysis around critical point
        alpha_range = np.linspace(0.05, 1.0, 100)
        
        step_results = []
        smooth_results = []
        
        for alpha in alpha_range:
            step_results.append({
                "alpha": alpha,
                "overload_condition": self.check_overload_condition(alpha, k),
                "resilience_step": self.calculate_resilience_score(alpha, k, smooth=False),
                "cascade_size_step": self.calculate_expected_cascade_size(alpha, k, smooth=False),
                "resilience_smooth": self.calculate_resilience_score(alpha, k, smooth=True),
                "cascade_size_smooth": self.calculate_expected_cascade_size(alpha, k, smooth=True)
            })
        
        return {
            "parameters": {"k": k},
            "critical_alpha": critical_alpha,
            "interpretation": f"α < {critical_alpha:.3f} leads to deterministic cascade, α ≥ {critical_alpha:.3f} provides resilience",
            "alpha_range_results": step_results,
            "key_insights": {
                "threshold_behavior": "Sharp transition at α = 1/k",
                "degree_impact": f"Higher degree k lowers critical threshold (α_c = 1/k)",
                "engineering_guidance": "Increase degree or capacity margin to improve resilience"
            }
        }
```

### **2. Ring Resilience Under Targeted High-Degree Attack**

#### **Uniform Degree Ring Analysis**
```python
class RingTargetedAttackModel:
    def __init__(self):
        self.critical_alpha = 0.5  # α_c = 1/2 for ring topology
        self.degree = 2  # Ring degree is always 2
    
    def calculate_neighbor_load_after_failure(self, L: float) -> float:
        """Calculate L' = L + L/2 = 3L/2 after neighbor failure in ring"""
        return 1.5 * L
    
    def check_overload_condition(self, alpha: float) -> bool:
        """Check if 3/2 L > (1+α)L => α < 1/2"""
        return alpha < self.critical_alpha
    
    def calculate_per_neighbor_failure_prob(self, alpha: float, 
                                             smooth: bool = False) -> float:
        """Calculate q_r(α) - step function or smooth linear approximation"""
        
        if not smooth:
            # Step function: q_r = 1 if α < 1/2, 0 otherwise
            return 1.0 if alpha < self.critical_alpha else 0.0
        else:
            # Smooth linear: q_r = max(0, 1 - 2α)
            return max(0.0, 1.0 - 2.0 * alpha)
    
    def calculate_branching_factor(self, alpha: float, smooth: bool = False) -> float:
        """Calculate branching factor b_r = 2 * q_r for ring (degree = 2)"""
        
        q_r = self.calculate_per_neighbor_failure_prob(alpha, smooth)
        return 2.0 * q_r
    
    def calculate_expected_cascade_size(self, alpha: float, 
                                        smooth: bool = False) -> float:
        """Calculate E[C_ring] using branching process approximation"""
        
        b_r = self.calculate_branching_factor(alpha, smooth)
        
        if b_r >= 1.0:
            return float('inf')  # Unbounded cascade
        else:
            return 1.0 / (1.0 - b_r)
    
    def calculate_resilience_score(self, alpha: float, smooth: bool = False) -> float:
        """Calculate R_ring(α) - step function or smooth linear"""
        
        if not smooth:
            # Step function: R = 0 if α < 1/2, 1 otherwise
            return 0.0 if alpha < self.critical_alpha else 1.0
        else:
            # Smooth linear: R = 1 - 2q_r = min(1, max(0, 4α - 1))
            q_r = self.calculate_per_neighbor_failure_prob(alpha, smooth)
            resilience = 1.0 - 2.0 * q_r
            return max(0.0, min(1.0, resilience))
    
    def analyze_targeted_attack_robustness(self) -> Dict[str, Any]:
        """Analyze ring robustness under targeted attacks"""
        
        # Generate analysis around critical point
        alpha_range = np.linspace(0.1, 1.0, 100)
        
        results = []
        
        for alpha in alpha_range:
            results.append({
                "alpha": alpha,
                "overload_condition": self.check_overload_condition(alpha),
                "resilience_step": self.calculate_resilience_score(alpha, smooth=False),
                "cascade_size_step": self.calculate_expected_cascade_size(alpha, smooth=False),
                "resilience_smooth": self.calculate_resilience_score(alpha, smooth=True),
                "cascade_size_smooth": self.calculate_expected_cascade_size(alpha, smooth=True),
                "interpretation": self.interpret_alpha_point(alpha)
            })
        
        return {
            "parameters": {"degree": self.degree, "critical_alpha": self.critical_alpha},
            "targeted_attack_impact": "Ring does not get structurally worse under targeting (no hubs)",
            "alpha_range_results": results,
            "key_insights": {
                "uniform_degree": "All nodes have degree 2, so targeted ≈ random",
                "critical_threshold": f"α_c = {self.critical_alpha} independent of attack strategy",
                "vs_mesh": "Ring maintains resilience longer under targeting than mesh"
            }
        }
    
    def interpret_alpha_point(self, alpha: float) -> str:
        """Interpret specific α value for ring resilience"""
        
        if alpha < 0.25:
            return "Critical overload risk - cascades likely"
        elif alpha < 0.5:
            return "Moderate risk - near critical threshold"
        elif alpha < 0.75:
            return "Good resilience - cascades contained"
        else:
            return "Excellent resilience - minimal cascade risk"
```

### **3. Critical Attack Fraction: Ring vs Mesh**

#### **Percolation-Style Collapse Analysis**
```python
class PercolationCollapseModel:
    def __init__(self):
        self.ring_model = RingTargetedAttackModel()
        self.mesh_model = MeshResilienceFlowModel()
    
    def calculate_ring_critical_attack_fraction(self, alpha: float) -> float:
        """Calculate p_c^ring based on overload cascade behavior"""
        
        # Ring: p_c depends primarily on α, not on attack fraction
        if alpha >= 0.5:
            return 0.0  # No cascade propagation
        else:
            return 1.0  # Any initial failure can trigger full cascade
    
    def calculate_mesh_connectivity_threshold(self, k: int) -> float:
        """Calculate p_c^conn ≈ 1/k for mesh connectivity"""
        return 1.0 / k
    
    def calculate_mesh_overload_threshold(self, k: int) -> float:
        """Calculate α_c^mesh = 1/k for overload cascade"""
        return 1.0 / k
    
    def calculate_mesh_targeted_threshold(self, k: int, hub_multiplier: float = 2.0) -> Dict[str, float]:
        """Calculate thresholds under targeted attacks on high-degree nodes"""
        
        hub_degree = int(k * hub_multiplier)
        
        return {
            "overload_threshold": 1.0 / hub_degree,  # α_c^mesh,targ ≈ 1/ŷk
            "connectivity_threshold": 1.0 / hub_degree,  # p_c^conn increases with targeting
            "interpretation": f"Targeting lowers thresholds from 1/k to 1/{hub_degree}"
        }
    
    def compare_ring_mesh_collapse_conditions(self, k: int = 4, 
                                              alpha: float = 0.3, 
                                              hub_multiplier: float = 2.0) -> Dict[str, Any]:
        """Compare ring vs mesh collapse conditions"""
        
        # Ring analysis
        ring_p_c = self.calculate_ring_critical_attack_fraction(alpha)
        ring_resilience = self.ring_model.calculate_resilience_score(alpha, smooth=True)
        
        # Mesh analysis (random attacks)
        mesh_p_c_conn = self.calculate_mesh_connectivity_threshold(k)
        mesh_p_c_overload = self.calculate_mesh_overload_threshold(k)
        mesh_resilience_random = self.mesh_model.calculate_resilience_score(alpha, k, smooth=True)
        
        # Mesh analysis (targeted attacks)
        targeted_thresholds = self.calculate_mesh_targeted_threshold(k, hub_multiplier)
        mesh_resilience_targeted = self.mesh_model.calculate_targeted_mesh_resilience(
            alpha, int(k * hub_multiplier), smooth=True
        )
        
        return {
            "parameters": {
                "k": k,
                "alpha": alpha,
                "hub_multiplier": hub_multiplier
            },
            "ring_analysis": {
                "critical_attack_fraction": ring_p_c,
                "resilience_score": ring_resilience,
                "interpretation": "Ring collapse depends primarily on α, not attack fraction"
            },
            "mesh_random_attacks": {
                "connectivity_threshold": mesh_p_c_conn,
                "overload_threshold": mesh_p_c_overload,
                "resilience_score": mesh_resilience_random,
                "interpretation": f"Mesh collapse when p < {mesh_p_c_conn:.3f} or α < {mesh_p_c_overload:.3f}"
            },
            "mesh_targeted_attacks": {
                "overload_threshold": targeted_thresholds["overload_threshold"],
                "connectivity_threshold": targeted_thresholds["connectivity_threshold"],
                "resilience_score": mesh_resilience_targeted,
                "interpretation": f"Targeting lowers thresholds to {targeted_thresholds['overload_threshold']:.3f}"
            },
            "comparative_analysis": {
                "more_resilient_random": "ring" if ring_resilience > mesh_resilience_random else "mesh",
                "more_resilient_targeted": "ring" if ring_resilience > mesh_resilience_targeted else "mesh",
                "collapse_vulnerability": f"p_c^mesh,targ >> p_c^ring - mesh collapses at smaller attack fractions"
            }
        }
```

### **4. First-Order vs Second-Order Collapse Conditions**

#### **Collapse Transition Analysis**
```python
class CollapseTransitionAnalyzer:
    def __init__(self):
        self.ring_model = RingTargetedAttackModel()
        self.mesh_model = MeshResilienceFlowModel()
    
    def analyze_collapse_order(self, topology: str, k: int = None) -> Dict[str, Any]:
        """Analyze whether collapse is first-order (abrupt) or second-order (continuous)"""
        
        if topology == "ring":
            return self.analyze_ring_collapse_order()
        elif topology == "mesh":
            return self.analyze_mesh_collapse_order(k)
        else:
            raise ValueError(f"Unknown topology: {topology}")
    
    def analyze_ring_collapse_order(self) -> Dict[str, Any]:
        """Analyze ring collapse transition characteristics"""
        
        # Ring: first-order behavior in step model
        alpha_range = np.linspace(0.1, 1.0, 100)
        
        step_resilience = []
        smooth_resilience = []
        
        for alpha in alpha_range:
            step_resilience.append(self.ring_model.calculate_resilience_score(alpha, smooth=False))
            smooth_resilience.append(self.ring_model.calculate_resilience_score(alpha, smooth=True))
        
        # Calculate transition sharpness
        transition_sharpness = self.calculate_transition_sharpness(alpha_range, step_resilience)
        
        return {
            "topology": "ring",
            "critical_alpha": 0.5,
            "collapse_order": "first_order",
            "transition_sharpness": transition_sharpness,
            "interpretation": "Ring shows abrupt collapse at α = 0.5 in idealized model",
            "smooth_model_behavior": "Linear transition region with gradual change",
            "engineering_implication": "Treat α_c = 0.5 as critical capacity margin for ring topologies"
        }
    
    def analyze_mesh_collapse_order(self, k: int) -> Dict[str, Any]:
        
        if k is None:
            k = 4  # Default degree
        
        alpha_range = np.linspace(0.05, 1.0, 100)
        
        step_resilience = []
        smooth_resilience = []
        
        for alpha in alpha_range:
            step_resilience.append(self.mesh_model.calculate_resilience_score(alpha, k, smooth=False))
            smooth_resilience.append(self.mesh_model.calculate_resilience_score(alpha, k, smooth=True))
        
        # Calculate transition sharpness
        transition_sharpness = self.calculate_transition_sharpness(alpha_range, step_resilience)
        
        return {
            "topology": "mesh",
            "critical_alpha": 1.0 / k,
            "collapse_order": "first_order",
            "transition_sharpness": transition_sharpness,
            "interpretation": f"Mesh shows abrupt collapse at α = {1.0/k:.3f} in step model",
            "smooth_model_behavior": "Linear transition region with gradual change",
            "engineering_implication": f"Treat α_c = {1.0/k:.3f} as critical capacity margin for degree {k} mesh"
        }
    
    def calculate_transition_sharpness(self, alpha_range: List[float], 
                                  resilience_values: List[float]) -> float:
        """Calculate how sharp the transition is around critical point"""
        
        # Find critical point (where resilience changes most rapidly)
        max_gradient_idx = np.argmax(np.abs(np.diff(resilience_values)))
        
        if max_gradient_idx < len(alpha_range) - 1:
            critical_alpha = alpha_range[max_gradient_idx]
            gradient_magnitude = abs(resilience_values[max_gradient_idx + 1] - resilience_values[max_gradient_idx])
        else:
            gradient_magnitude = 0.0
        
        return gradient_magnitude
    
    def analyze_mixed_collapse_behavior(self, topology: str, k: int = None, 
                                       heterogeneity: float = 0.1) -> Dict[str, Any]:
        """Analyze mixed first/second-order behavior with heterogeneity"""
        
        if k is None:
            k = 4
        
        # Add heterogeneity to capacity margins
        alpha_range = np.linspace(0.05, 1.0, 100)
        
        mixed_results = []
        
        for alpha in alpha_range:
            # Simulate heterogeneous capacity margins
            alpha_heterogeneous = alpha * (1 + heterogeneity * (np.random.random() - 0.5))
            
            if topology == "ring":
                resilience = self.ring_model.calculate_resilience_score(alpha_heterogeneous, smooth=True)
            else:  # mesh
                resilience = self.mesh_model.calculate_resilience_score(alpha_heterogeneous, k, smooth=True)
            
            mixed_results.append({
                "alpha": alpha,
                "alpha_heterogeneous": alpha_heterogeneous,
                "resilience": resilience
            })
        
        # Analyze transition characteristics
        resilience_values = [r["resilience"] for r in mixed_results]
        variance = np.var(resilience_values)
        
        return {
            "topology": topology,
            "heterogeneity": heterogeneity,
            "collapse_order": "mixed",
            "resilience_variance": variance,
            "interpretation": "Heterogeneity creates mixed first/second-order behavior with small cascades and rare large ones",
            "engineering_guidance": "Expect both localized failures and occasional large cascades near critical threshold"
        }
```

### **5. Mesh Resilience with Flow Redistribution Rules**

#### **Probabilistic Load Distribution Model**
```python
class FlowRedistributionModel:
    def __init__(self):
        self.distribution_types = ["deterministic", "uniform", "beta", "empirical"]
    
    def calculate_failure_probability_deterministic(self, alpha: float, k: int) -> float:
        """Calculate q_flow(α) for deterministic equal splitting (X = 1/k)"""
        
        # Deterministic: X = 1/k always
        critical_alpha = 1.0 / k
        return 1.0 if alpha < critical_alpha else 0.0
    
    def calculate_failure_probability_uniform(self, alpha: float) -> float:
        """Calculate q_flow(α) for uniform distribution of load fractions"""
        
        # For uniform distribution on [0, 2/k] (simplified)
        return max(0.0, 1.0 - 0.5 * alpha)  # Simplified for k=2, adjust for general k
    
    def calculate_failure_probability_beta(self, alpha: float, a: float = 2.0, 
                                        b: float = 2.0) -> float:
        """Calculate q_flow(α) for Beta distribution of load fractions"""
        
        try:
            from scipy.stats import beta
            
            # Scale alpha to [0,1] range for Beta distribution
            scaled_alpha = min(1.0, max(0.0, alpha * 2))  # Rough scaling
            
            survival_prob = 1.0 - beta.cdf(scaled_alpha, a, b)
            return survival_prob
        except ImportError:
            # Fallback to simple approximation if scipy not available
            return max(0.0, 1.0 - alpha)
    
    def calculate_failure_probability_empirical(self, alpha: float, 
                                             empirical_data: List[float] = None) -> float:
        """Calculate q_flow(α) from empirical load redistribution data"""
        
        if empirical_data is None:
            # Fallback to uniform distribution
            return self.calculate_failure_probability_uniform(alpha)
        
        # Calculate empirical CDF
        sorted_data = sorted(empirical_data)
        n = len(sorted_data)
        
        # Count values > alpha
        count_above_alpha = sum(1 for x in sorted_data if x > alpha)
        
        return count_above_alpha / n
    
    def calculate_branching_factor_flow(self, alpha: float, k: int, 
                                        distribution: str = "deterministic") -> float:
        """Calculate branching factor b_flow = k * q_flow(α)"""
        
        if distribution == "deterministic":
            q_flow = self.calculate_failure_probability_deterministic(alpha, k)
        elif distribution == "uniform":
            q_flow = self.calculate_failure_probability_uniform(alpha)
        elif distribution == "beta":
            q_flow = self.calculate_failure_probability_beta(alpha)
        elif distribution == "empirical":
            q_flow = self.calculate_failure_probability_empirical(alpha)
        else:
            raise ValueError(f"Unknown distribution: {distribution}")
        
        return k * q_flow
    
    def calculate_expected_cascade_flow(self, alpha: float, k: int, 
                                      distribution: str = "deterministic") -> float:
        """Calculate E[C_mesh,flow] = 1/(1 - b_flow) for b_flow < 1"""
        
        b_flow = self.calculate_branching_factor_flow(alpha, k, distribution)
        
        if b_flow >= 1.0:
            return float('inf')
        else:
            return 1.0 / (1.0 - b_flow)
    
    def calculate_resilience_flow(self, alpha: float, k: int, 
                                  distribution: str = "deterministic") -> float:
        """Calculate R_mesh,flow(α,k) = 1 - k[1 - F_X(α)]"""
        
        if distribution == "deterministic":
            q_flow = self.calculate_failure_probability_deterministic(alpha, k)
        elif distribution == "uniform":
            q_flow = self.calculate_failure_probability_uniform(alpha)
        elif distribution == "beta":
            q_flow = self.calculate_failure_probability_beta(alpha)
        elif distribution == "empirical":
            q_flow = self.calculate_failure_probability_empirical(alpha)
        else:
            raise ValueError(f"Unknown distribution: {distribution}")
        
        resilience = 1.0 - k * q_flow
        return max(0.0, min(1.0, resilience))
    
    def compare_redistribution_models(self, alpha: float, k: int = 4, 
                                     empirical_data: List[float] = None) -> Dict[str, Any]:
        """Compare different load redistribution models"""
        
        models = ["deterministic", "uniform", "beta"]
        if empirical_data:
            models.append("empirical")
        
        results = {}
        
        for model in models:
            if model == "empirical" and empirical_data is None:
                continue
                
            resilience = self.calculate_resilience_flow(alpha, k, model)
            cascade_size = self.calculate_expected_cascade_flow(alpha, k, model)
            branching_factor = self.calculate_branching_factor_flow(alpha, k, model)
            
            results[model] = {
                "resilience": resilience,
                "cascade_size": cascade_size,
                "branching_factor": branching_factor,
                "interpretation": self.interpret_redistribution_model(model, resilience)
            }
        
        # Find most resilient model
        if results:
            most_resilient = max(results.items(), key=lambda x: x[1]["resilience"])[0]
            resilience_range = max(r["resilience"] for r in results.values()) - min(r["resilience"] for r in results.values())
        else:
            most_resilient = None
            resilience_range = 0.0
        
        return {
            "parameters": {"alpha": alpha, "k": k},
            "model_results": results,
            "comparison": {
                "most_resilient": most_resilient,
                "resilience_range": resilience_range,
                "deterministic_vs_probabilistic": "Equal splitting vs random distribution comparison"
            },
            "engineering_guidance": "Fit empirical load redistribution patterns to Beta distribution for accurate modeling"
        }
    
    def interpret_redistribution_model(self, model: str, resilience: float) -> str:
        """Interpret redistribution model characteristics"""
        
        interpretations = {
            "deterministic": "Equal load splitting - baseline model",
            "uniform": "Random uniform distribution - higher variability",
            "beta": "Beta distribution - flexible shape parameters",
            "empirical": "Data-driven model - most accurate"
        }
        
        base_interpretation = interpretations.get(model, "Unknown model")
        
        if resilience > 0.8:
            return f"{base_interpretation} - high resilience"
        elif resilience > 0.5:
            return f"{base_interpretation} - moderate resilience"
        elif resilience > 0.2:
            return f"{base_interpretation} - low resilience"
        else:
            return f"{base_interpretation} - very low resilience"
```

---

## 📐 **COMPACT DERIVATION SET FOR TOPOLOGY RESILIENCE**

### **1. Mesh Resilience with Uniform Load and Capacity**

#### **Homogeneous Mesh Assumptions**
- N nodes, each with initial load L
- Capacity C = (1+α)L (uniform capacity margin α>0)
- Each node has degree k
- Failed node load redistributed equally among k neighbors (flow-style model)

#### **Load Redistribution and Overload Condition**
After one neighbor fails:
```
L' = L + L/k = (1 + 1/k)L
```

Overload condition:
```
L' > C ↔ (1 + 1/k)L > (1+α)L ↔ α < 1/k
```

#### **Deterministic Per-Neighbor Failure Probability**
```
q_m(α,k) = {
    1, if α < 1/k
    0, if α ≥ 1/k
}
```

#### **Branching Factor and Cascade Size**
Branching factor: b_m(α,k) = k * q_m(α,k)

Galton-Watson approximation:
```
E[C_mesh] = {
    ∞, if b_m ≥ 1
    1/(1 - b_m), if b_m < 1
}
```

#### **Resilience Score**
```
R_mesh(α,k) = {
    0, if α < 1/k
    1, if α ≥ 1/k
}
```

#### **Smooth Engineering Approximation**
```
q_m(α,k) = max(0, 1 - k*α)
```
For k * q_m(α,k) < 1:
```
E[C_mesh] ≈ 1/(1 - k * q_m(α,k))
R_mesh(α,k) = 1 - k * q_m(α,k)
```

### **2. Critical Attack Fraction for Ring Under Targeted Attack**

#### **Ring Properties**
- Fixed degree: d_r = 2
- Degree-targeted attacks ≈ random removals (no hubs)

#### **Two Notions of Critical Fraction**

**1. Connectivity Percolation Threshold**
- Ring remains connected until cycle broken
- No clean closed-form p_c like Erdős–Rényi
- Not dominant for overload-driven cascades

**2. Overload-Driven Cascade Threshold**
From uniform ring derivation (neighbors get L/2 each):
```
Overload when α < 1/2
```

#### **Critical Attack Fraction Analysis**
- If α ≥ 1/2: targeted attack fraction p doesn't induce cascades
- If α < 1/2: even single targeted failure can trigger full cascade
```
p_c^ring,overload ≈ 0 when α < 1/2
```

**Key Insight**: Capacity margin α is the key threshold, not attack fraction.

### **3. Analytical Comparison: Ring vs Mesh Critical Fractions**

#### **Overload Thresholds**
- **Ring**: α_c^ring ≈ 1/2
- **Mesh**: α_c^mesh ≈ 1/k

#### **Critical Attack Fractions**
- **Ring**: p_c^ring,overload ≈ 0 when α < 1/2
- **Mesh**: p_c^mesh,overload ≈ 0 when α < 1/k

#### **Comparative Analysis**
Since k > 2 for typical meshes:
```
α_c^mesh = 1/k < 1/2 = α_c^ring
```

**Operating Regions**:
- 1/k ≤ α < 1/2: Mesh safe, ring still dangerous
- α ≥ 1/2: Both safe under idealized model

#### **Targeted Attack Impact on Mesh**
High-degree nodes with degree k̃ ≫ k removed first:
```
α_c^mesh,targ ≈ 1/k̃
```
Mesh becomes significantly more vulnerable to targeted removal than ring.

### **4. Derivation Pipeline for Closed-Form Mesh Resilience**

#### **Step-by-Step Derivation**
1. **Assume uniform load and capacity**: L_i = L, C_i = (1+α)L
2. **Pick redistribution rule**: failed node load split equally among k neighbors ⇒ each gets L/k
3. **Compute neighbor overload condition**:
   ```
   L' = L + L/k ⇒ L' > (1+α)L ⇒ α < 1/k
   ```
4. **Define per-neighbor failure probability** q_m(α,k) (step or smoothed)
5. **Branching factor**: b_m(α,k) = k * q_m(α,k)
6. **Expected cascade size**: E[C] ≈ 1/(1 - b_m) if b_m<1
7. **Resilience score**: R_mesh = 1 - b_m (clamped)

#### **Refinement Points**
- Step 2: Different flow rules (unequal splitting, probabilistic)
- Step 4: Probabilistic q_m with distributions
- Structure remains unchanged for analytical tractability

### **5. Assumptions in Uniform-Capacity Mesh Model**

#### **Core Simplifying Assumptions**

**Homogeneity**
- All nodes have same initial load L and capacity C=(1+α)L
- All nodes have same degree k

**Equal Redistribution**
- Failed node load split equally among k neighbors
- No heterogeneous weights or preferential attachment

**Local Failure Rule**
- Neighbor fails if post-redistribution load exceeds capacity
- No other failure mechanisms considered

**Independence/Branching Approximation**
- Later overload events approximated as independent branching
- Leads to 1/(1-b) formula
- Ignores correlations and spatial effects

**Single-Layer Network**
- No interdependent/network-of-networks structure
- Avoids more abrupt, first-order transitions

#### **Purpose of Simplifications**
These assumptions are intentionally minimal to enable:
- Analytical tractability for topology comparison
- Clear parameter tuning (α, k, redistribution rules)
- Direct reasoning about safe operating regions
- Foundation for more complex extensions

---

**Last Updated:** 2026-01-26  
**Next Review:** After Phase 1 implementation  
**Owner:** MERID Swarm Reliability Team  
**Target:** Production-ready failure-resilient development swarm
